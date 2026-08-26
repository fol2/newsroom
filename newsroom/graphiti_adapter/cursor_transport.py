"""Exact-binary Cursor transport qualification and bounded execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import selectors
import stat
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from newsroom.control_plane.child_environment import unprivileged_child_environment
from newsroom.graphiti_adapter.evaluation_packet import CURSOR_AGENT_MODEL_ID

QUALIFIED_CURSOR_AGENT_VERSION = "2026.08.11-e8db854"
QUALIFIED_CURSOR_AGENT_BIN = "/Users/jamesto/.local/bin/cursor-agent"
QUALIFIED_CURSOR_AGENT_RESOLVED_BIN = (
    "/Users/jamesto/.local/share/cursor-agent/versions/"
    f"{QUALIFIED_CURSOR_AGENT_VERSION}/cursor-agent"
)
CURSOR_AGENT_BIN = os.environ.get(
    "NEWSROOM_CURSOR_AGENT_BIN", QUALIFIED_CURSOR_AGENT_BIN
)
QUALIFIED_CURSOR_AGENT_PACKAGE_DIGEST = (
    "sha256:957df7e19a94bcdf3a263f6e2839af1f8c7e8059bc76ae339464df07982848ea"
)
QUALIFIED_CURSOR_AGENT_LAUNCHER_DIGEST = (
    "sha256:eed61c5224668c9236334c4c68936a16aecc37374b592f59e31eb50433817831"
)
QUALIFIED_CURSOR_AGENT_COMMAND_SURFACE_DIGEST = (
    "sha256:6aceb24b7c7ecddb1993946ebb18a7dd4d025842e6efda955eb0c13255b1e5f0"
)
QUALIFIED_CURSOR_AGENT_CONTROL_SEMANTICS_DIGEST = (
    "sha256:285e3f24126b457872064e9661d76ab0e35a0059256ffa4ab44507821efe334e"
)
CURSOR_PREFLIGHT_TIMEOUT_SECONDS = 20
CURSOR_PREFLIGHT_MAX_BYTES = 64 * 1024
CURSOR_STDOUT_BASE_BYTES = 64 * 1024
CURSOR_STDOUT_BYTES_PER_TOKEN = 64
CURSOR_STDOUT_LIMIT_FORMULA = "65536+64*REQUEST_MAX_TOKENS"
CURSOR_STDOUT_LIMIT_IDENTITY = (
    "cursor-controller-stdout-v1:" + CURSOR_STDOUT_LIMIT_FORMULA
)
CURSOR_COMMAND_SURFACE_PROOF = "PINNED_PACKAGE_HIDDEN_OPTION_REGISTRATIONS_V1"

_CURSOR_PUBLIC_CONTROLS = (
    "--print",
    "--mode",
    "--output-format",
    "--sandbox",
    "--workspace",
    "--trust",
    "--model",
)
_CURSOR_ISOLATION_CONTROLS = (
    "--single-turn",
    "--exclude-workspace-context",
    "--allowed-tools=EMPTY",
    "HERMETIC_HOME_XDG",
)
_CURSOR_CONTROL_ARGUMENTS = (
    "--print",
    "--single-turn",
    "--mode",
    "ask",
    "--output-format",
    "json",
    "--sandbox",
    "enabled",
    "--exclude-workspace-context",
    "--allowed-tools",
    "",
    "--trust",
    "--model",
    CURSOR_AGENT_MODEL_ID,
)
_CURSOR_HIDDEN_CONTROL_SOURCE_MARKERS = (
    'addOption(new f.c$("--single-turn","Finish after the initial user turn',
    'addOption(new f.c$("--exclude-workspace-context","Strip all workspace-sourced context',
    'addOption(new f.c$("--allowed-tools <tool>","Allow only proto ToolCall oneof tool(s)',
)
_CURSOR_CONTROL_SEMANTIC_SOURCE_MARKERS = (
    'if(void 0!==o.allowedTools)try{return(0,_.nm)(o.allowedTools,"--allowed-tools")',
    '0!==t.length&&(i(t)?n.add(t):r.push(t))}if(r.length>0)throw new Error',
    'return[...n]}}',
    'function i(e,t){return void 0===t?e:Object.assign(Object.assign({},null!=e?e:{}),{[o.iq]:t.join(",")})}',
    "We=()=>{try{return(0,$.FS)((0,L.S)((0,L.I)(qe,Be),Ye)",
    "excludeWorkspaceContext:o.excludeWorkspaceContext",
    "singleTurn:o.singleTurn",
)


class CliPredispatchRefusal(RuntimeError):
    """The installed CLI cannot prove the checked transport contract."""

    def __init__(
        self,
        message: str,
        *,
        qualification_evidence: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.qualification_evidence = dict(qualification_evidence or {})


class CliOutputDecodeError(RuntimeError):
    """A dispatched subscription CLI returned non-UTF-8 output."""


class CliOutputBoundExceeded(RuntimeError):
    """A CLI exceeded its controller-owned output byte ceiling."""


@dataclass(frozen=True, slots=True)
class CursorCliQualification:
    binary: str
    resolved_binary: str
    version: str
    expected_version: str
    controls: tuple[str, ...]
    version_digest: str
    help_digest: str
    command_template_digest: str
    launcher_digest: str
    command_surface_digest: str
    control_semantics_digest: str
    package_digest: str
    command_surface_proof: str
    stdout_limit_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "binary": self.binary,
            "resolved_binary": self.resolved_binary,
            "version": self.version,
            "expected_version": self.expected_version,
            "controls": list(self.controls),
            "version_digest": self.version_digest,
            "help_digest": self.help_digest,
            "command_template_digest": self.command_template_digest,
            "launcher_digest": self.launcher_digest,
            "command_surface_digest": self.command_surface_digest,
            "control_semantics_digest": self.control_semantics_digest,
            "package_digest": self.package_digest,
            "command_surface_proof": self.command_surface_proof,
            "stdout_limit_bytes": self.stdout_limit_bytes,
            "stdout_limit_formula": CURSOR_STDOUT_LIMIT_FORMULA,
            "stdout_limit_identity": CURSOR_STDOUT_LIMIT_IDENTITY,
        }


@dataclass(frozen=True, slots=True)
class _ProcessOutput:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class _CursorPackageProof:
    root: str
    launcher_digest: str
    command_surface_digest: str
    control_semantics_digest: str
    package_digest: str


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _decode_output(value: bytes, *, name: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        raise CliOutputDecodeError(
            f"{name} Graphiti LLM returned malformed UTF-8"
        ) from None


def cursor_stdout_limit(max_tokens: int) -> int:
    if isinstance(max_tokens, bool) or max_tokens <= 0:
        raise ValueError("Graphiti requested max_tokens must be positive")
    return CURSOR_STDOUT_BASE_BYTES + CURSOR_STDOUT_BYTES_PER_TOKEN * max_tokens


def _cursor_command(
    *, binary: str, prompt: str, workspace: str
) -> tuple[str, ...]:
    return (
        binary,
        *_CURSOR_CONTROL_ARGUMENTS,
        "--workspace",
        workspace,
        prompt,
    )


def _command_template_digest(*, binary: str) -> str:
    canonical_command = _cursor_command(
        binary=binary,
        prompt="PROMPT",
        workspace="HERMETIC_EMPTY",
    )
    return _sha256_text("\x00".join(canonical_command))


def _package_manifest_digest(root: Path) -> str:
    entries: list[tuple[str, int, int, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".running" in relative.parts:
            continue
        if path.is_symlink():
            raise CliPredispatchRefusal(
                "Cursor CLI qualified package contains a symbolic link"
            )
        if not path.is_file():
            continue
        value = path.read_bytes()
        entries.append(
            (
                relative.as_posix(),
                stat.S_IMODE(path.stat().st_mode),
                len(value),
                hashlib.sha256(value).hexdigest(),
            )
        )
    manifest = json.dumps(
        entries,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(manifest)


def _inspect_cursor_package(binary: str) -> _CursorPackageProof:
    resolved = Path(os.path.realpath(binary))
    root = resolved.parent
    if str(resolved) != QUALIFIED_CURSOR_AGENT_RESOLVED_BIN:
        raise CliPredispatchRefusal(
            "Cursor CLI installation is outside the qualified deployment paths"
        )
    if resolved.name != "cursor-agent" or root.name != QUALIFIED_CURSOR_AGENT_VERSION:
        raise CliPredispatchRefusal(
            "Cursor CLI resolved installation is outside the qualified version root"
        )
    command_surface = root / "index.js"
    control_semantics = root / "6260.index.js"
    if (
        not resolved.is_file()
        or not command_surface.is_file()
        or not control_semantics.is_file()
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI qualified package artifacts are absent"
        )
    launcher_digest = _sha256_bytes(resolved.read_bytes())
    command_surface_bytes = command_surface.read_bytes()
    command_surface_digest = _sha256_bytes(command_surface_bytes)
    control_semantics_bytes = control_semantics.read_bytes()
    control_semantics_digest = _sha256_bytes(control_semantics_bytes)
    package_digest = _package_manifest_digest(root)
    try:
        command_surface_text = command_surface_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI command surface is not UTF-8"
        ) from exc
    if not all(
        marker in command_surface_text
        for marker in _CURSOR_HIDDEN_CONTROL_SOURCE_MARKERS
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI command surface lacks qualified hidden isolation controls"
        )
    try:
        control_semantics_text = control_semantics_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI control semantics are not UTF-8"
        ) from exc
    if not all(
        marker in control_semantics_text
        for marker in _CURSOR_CONTROL_SEMANTIC_SOURCE_MARKERS
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI does not apply the qualified isolation controls"
        )
    if (
        launcher_digest != QUALIFIED_CURSOR_AGENT_LAUNCHER_DIGEST
        or command_surface_digest
        != QUALIFIED_CURSOR_AGENT_COMMAND_SURFACE_DIGEST
        or control_semantics_digest
        != QUALIFIED_CURSOR_AGENT_CONTROL_SEMANTICS_DIGEST
        or package_digest != QUALIFIED_CURSOR_AGENT_PACKAGE_DIGEST
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI package differs from the qualified command surface"
        )
    return _CursorPackageProof(
        root=str(root),
        launcher_digest=launcher_digest,
        command_surface_digest=command_surface_digest,
        control_semantics_digest=control_semantics_digest,
        package_digest=package_digest,
    )


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()


async def _stop_process_async(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


def _run_bounded_process(
    command: tuple[str, ...],
    *,
    timeout: int,
    max_output_bytes: int,
    cwd: str,
    environment: Mapping[str, str],
) -> _ProcessOutput:
    if isinstance(max_output_bytes, bool) or max_output_bytes <= 0:
        raise ValueError("CLI max_output_bytes must be positive")
    name = os.path.basename(command[0])
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=dict(environment or unprivileged_child_environment()),
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    stdout_output = bytearray()
    stderr_output = bytearray()
    selector = selectors.DefaultSelector()
    streams = {
        stdout_fd: (process.stdout, stdout_output),
        stderr_fd: (process.stderr, stderr_output),
    }
    for stream, _output in streams.values():
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise TimeoutError(f"{name} Graphiti LLM timed out")
            events = selector.select(timeout=min(remaining, 0.1))
            if not events:
                continue
            for key, _mask in events:
                stream, output = streams[key.fd]
                retained = sum(len(value[1]) for value in streams.values())
                read_size = min(65_536, max_output_bytes - retained + 1)
                chunk = os.read(key.fd, max(read_size, 1))
                if not chunk:
                    selector.unregister(stream)
                    continue
                output.extend(chunk)
                if sum(len(value[1]) for value in streams.values()) > max_output_bytes:
                    _stop_process(process)
                    raise CliOutputBoundExceeded(
                        f"{name} Graphiti LLM exceeded output byte limit"
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _stop_process(process)
            raise TimeoutError(f"{name} Graphiti LLM timed out")
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _stop_process(process)
            raise TimeoutError(f"{name} Graphiti LLM timed out") from None
    except BaseException:
        if process.poll() is None:
            _stop_process(process)
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return _ProcessOutput(
        returncode=int(process.returncode),
        stdout=_decode_output(bytes(stdout_output), name=name),
        stderr=_decode_output(bytes(stderr_output), name=name),
    )


async def _run_bounded_process_async(
    command: tuple[str, ...],
    *,
    timeout: int,
    max_output_bytes: int,
    cwd: str,
    environment: Mapping[str, str],
) -> _ProcessOutput:
    if isinstance(max_output_bytes, bool) or max_output_bytes <= 0:
        raise ValueError("CLI max_output_bytes must be positive")
    name = os.path.basename(command[0])
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=dict(environment or unprivileged_child_environment()),
    )
    assert process.stdout is not None
    assert process.stderr is not None
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    retained = 0

    async def collect(
        stream: asyncio.StreamReader, *, destination: bytearray
    ) -> None:
        nonlocal retained
        while True:
            read_size = min(65_536, max_output_bytes - retained + 1)
            chunk = await stream.read(max(read_size, 1))
            if not chunk:
                return
            destination.extend(chunk)
            retained += len(chunk)
            if retained > max_output_bytes:
                raise CliOutputBoundExceeded(
                    f"{name} Graphiti LLM exceeded output byte limit"
                )

    deadline = asyncio.get_running_loop().time() + timeout
    try:
        await asyncio.wait_for(
            asyncio.gather(
                collect(process.stdout, destination=outputs["stdout"]),
                collect(process.stderr, destination=outputs["stderr"]),
            ),
            timeout=timeout,
        )
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        await asyncio.wait_for(process.wait(), timeout=remaining)
    except TimeoutError:
        await _stop_process_async(process)
        raise TimeoutError(f"{name} Graphiti LLM timed out") from None
    except asyncio.CancelledError:
        await _stop_process_async(process)
        raise
    except BaseException:
        await _stop_process_async(process)
        raise
    return _ProcessOutput(
        returncode=int(process.returncode),
        stdout=_decode_output(bytes(outputs["stdout"]), name=name),
        stderr=_decode_output(bytes(outputs["stderr"]), name=name),
    )


def _qualification_evidence(
    *,
    binary: str,
    max_tokens: int,
    version: str = "UNOBSERVED",
    package: _CursorPackageProof | None = None,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "binary": binary,
        "resolved_binary": os.path.realpath(binary),
        "version": version,
        "expected_version": QUALIFIED_CURSOR_AGENT_VERSION,
        "controls": list(_CURSOR_ISOLATION_CONTROLS),
        "command_surface_proof": CURSOR_COMMAND_SURFACE_PROOF,
        "stdout_limit_bytes": cursor_stdout_limit(max_tokens),
        "stdout_limit_formula": CURSOR_STDOUT_LIMIT_FORMULA,
        "stdout_limit_identity": CURSOR_STDOUT_LIMIT_IDENTITY,
    }
    if package is not None:
        evidence.update(
            {
                "launcher_digest": package.launcher_digest,
                "command_surface_digest": package.command_surface_digest,
                "control_semantics_digest": package.control_semantics_digest,
                "package_digest": package.package_digest,
            }
        )
    return evidence


def _require_qualified_request_path(
    binary: str, *, evidence: Mapping[str, object]
) -> None:
    if os.path.abspath(binary) != QUALIFIED_CURSOR_AGENT_BIN:
        raise CliPredispatchRefusal(
            "Cursor CLI request path differs from the checked policy",
            qualification_evidence=evidence,
        )


def _build_qualification(
    *,
    binary: str,
    max_tokens: int,
    package: _CursorPackageProof,
    version_result: _ProcessOutput,
    help_result: _ProcessOutput,
) -> CursorCliQualification:
    version = version_result.stdout.strip()
    evidence = _qualification_evidence(
        binary=binary,
        max_tokens=max_tokens,
        version=version or "UNOBSERVED",
        package=package,
    )
    if (
        version_result.returncode != 0
        or version != QUALIFIED_CURSOR_AGENT_VERSION
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI version is outside the qualified transport contract",
            qualification_evidence=evidence,
        )
    if help_result.returncode != 0 or not all(
        control in help_result.stdout for control in _CURSOR_PUBLIC_CONTROLS
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI cannot prove the qualified public command surface",
            qualification_evidence=evidence,
        )
    resolved_binary = os.path.realpath(binary)
    return CursorCliQualification(
        binary=binary,
        resolved_binary=resolved_binary,
        version=version,
        expected_version=QUALIFIED_CURSOR_AGENT_VERSION,
        controls=_CURSOR_ISOLATION_CONTROLS,
        version_digest=_sha256_text(version_result.stdout),
        help_digest=_sha256_text(help_result.stdout),
        command_template_digest=_command_template_digest(binary=resolved_binary),
        launcher_digest=package.launcher_digest,
        command_surface_digest=package.command_surface_digest,
        control_semantics_digest=package.control_semantics_digest,
        package_digest=package.package_digest,
        command_surface_proof=CURSOR_COMMAND_SURFACE_PROOF,
        stdout_limit_bytes=cursor_stdout_limit(max_tokens),
    )


def _qualify_cursor_agent(
    *,
    binary: str,
    cwd: str,
    environment: Mapping[str, str],
    max_tokens: int,
) -> CursorCliQualification:
    evidence = _qualification_evidence(binary=binary, max_tokens=max_tokens)
    try:
        _require_qualified_request_path(binary, evidence=evidence)
        package = _inspect_cursor_package(binary)
        evidence = _qualification_evidence(
            binary=binary, max_tokens=max_tokens, package=package
        )
        resolved_binary = os.path.realpath(binary)
        version_result = _run_bounded_process(
            (resolved_binary, "--version"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
        )
        help_result = _run_bounded_process(
            (resolved_binary, "--help"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
        )
        qualification = _build_qualification(
            binary=binary,
            max_tokens=max_tokens,
            package=package,
            version_result=version_result,
            help_result=help_result,
        )
        if _inspect_cursor_package(resolved_binary) != package:
            raise CliPredispatchRefusal(
                "Cursor CLI package changed during qualification",
                qualification_evidence=evidence,
            )
        return qualification
    except CliPredispatchRefusal as exc:
        if exc.qualification_evidence:
            raise
        raise CliPredispatchRefusal(
            str(exc), qualification_evidence=evidence
        ) from exc
    except (CliOutputBoundExceeded, CliOutputDecodeError, OSError, TimeoutError) as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI exact-binary preflight failed",
            qualification_evidence=evidence,
        ) from exc


async def _qualify_cursor_agent_async(
    *,
    binary: str,
    cwd: str,
    environment: Mapping[str, str],
    max_tokens: int,
) -> CursorCliQualification:
    evidence = _qualification_evidence(binary=binary, max_tokens=max_tokens)
    try:
        _require_qualified_request_path(binary, evidence=evidence)
        package = await asyncio.to_thread(_inspect_cursor_package, binary)
        evidence = _qualification_evidence(
            binary=binary, max_tokens=max_tokens, package=package
        )
        resolved_binary = os.path.realpath(binary)
        version_result = await _run_bounded_process_async(
            (resolved_binary, "--version"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
        )
        help_result = await _run_bounded_process_async(
            (resolved_binary, "--help"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
        )
        qualification = _build_qualification(
            binary=binary,
            max_tokens=max_tokens,
            package=package,
            version_result=version_result,
            help_result=help_result,
        )
        retained_package = await asyncio.to_thread(
            _inspect_cursor_package, resolved_binary
        )
        if retained_package != package:
            raise CliPredispatchRefusal(
                "Cursor CLI package changed during qualification",
                qualification_evidence=evidence,
            )
        return qualification
    except CliPredispatchRefusal as exc:
        if exc.qualification_evidence:
            raise
        raise CliPredispatchRefusal(
            str(exc), qualification_evidence=evidence
        ) from exc
    except (CliOutputBoundExceeded, CliOutputDecodeError, OSError, TimeoutError) as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI exact-binary preflight failed",
            qualification_evidence=evidence,
        ) from exc


def run_cursor_transport(
    *,
    binary: str,
    prompt: str,
    max_tokens: int,
    timeout: int,
    cwd: str,
    environment: Mapping[str, str],
    dispatch_started: Callable[[], None] | None = None,
) -> tuple[str, CursorCliQualification]:
    """Qualify and invoke one pinned Cursor package under controller bounds."""

    qualification = _qualify_cursor_agent(
        binary=binary,
        cwd=cwd,
        environment=environment,
        max_tokens=max_tokens,
    )
    if dispatch_started is not None:
        dispatch_started()
    result = _run_bounded_process(
        _cursor_command(
            binary=qualification.resolved_binary,
            prompt=prompt,
            workspace=cwd,
        ),
        timeout=timeout,
        max_output_bytes=qualification.stdout_limit_bytes,
        cwd=cwd,
        environment=environment,
    )
    if result.returncode != 0:
        raise RuntimeError("cursor-agent Graphiti LLM failed")
    if not result.stdout.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return result.stdout, qualification


async def run_cursor_transport_async(
    *,
    binary: str,
    prompt: str,
    max_tokens: int,
    timeout: int,
    cwd: str,
    environment: Mapping[str, str],
    dispatch_started: Callable[[], None] | None = None,
) -> tuple[str, CursorCliQualification]:
    """Async pinned Cursor transport with cancellable bounded children."""

    qualification = await _qualify_cursor_agent_async(
        binary=binary,
        cwd=cwd,
        environment=environment,
        max_tokens=max_tokens,
    )
    if dispatch_started is not None:
        dispatch_started()
    result = await _run_bounded_process_async(
        _cursor_command(
            binary=qualification.resolved_binary,
            prompt=prompt,
            workspace=cwd,
        ),
        timeout=timeout,
        max_output_bytes=qualification.stdout_limit_bytes,
        cwd=cwd,
        environment=environment,
    )
    if result.returncode != 0:
        raise RuntimeError("cursor-agent Graphiti LLM failed")
    if not result.stdout.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return result.stdout, qualification


__all__ = [
    "CURSOR_AGENT_BIN",
    "CURSOR_COMMAND_SURFACE_PROOF",
    "CURSOR_STDOUT_LIMIT_FORMULA",
    "CURSOR_STDOUT_LIMIT_IDENTITY",
    "QUALIFIED_CURSOR_AGENT_BIN",
    "QUALIFIED_CURSOR_AGENT_COMMAND_SURFACE_DIGEST",
    "QUALIFIED_CURSOR_AGENT_CONTROL_SEMANTICS_DIGEST",
    "QUALIFIED_CURSOR_AGENT_LAUNCHER_DIGEST",
    "QUALIFIED_CURSOR_AGENT_PACKAGE_DIGEST",
    "QUALIFIED_CURSOR_AGENT_RESOLVED_BIN",
    "QUALIFIED_CURSOR_AGENT_VERSION",
    "CliOutputBoundExceeded",
    "CliOutputDecodeError",
    "CliPredispatchRefusal",
    "CursorCliQualification",
    "cursor_stdout_limit",
    "run_cursor_transport",
    "run_cursor_transport_async",
]
