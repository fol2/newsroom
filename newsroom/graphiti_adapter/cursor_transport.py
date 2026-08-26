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
from dataclasses import dataclass, field
from pathlib import Path

from newsroom.control_plane.child_environment import unprivileged_child_environment
from newsroom.graphiti_adapter.evaluation_packet import CURSOR_AGENT_MODEL_ID

QUALIFIED_CURSOR_AGENT_VERSION = "2026.08.11-e8db854"
QUALIFIED_CURSOR_AGENT_BIN = "/Users/jamesto/.local/bin/cursor-agent"
QUALIFIED_CURSOR_AGENT_RESOLVED_BIN = (
    "/Users/jamesto/.local/share/cursor-agent/versions/"
    f"{QUALIFIED_CURSOR_AGENT_VERSION}/cursor-agent"
)
QUALIFIED_CURSOR_LOGIN_KEYCHAIN = "/Users/jamesto/Library/Keychains/login.keychain-db"
CURSOR_AUTHENTICATION_BRIDGE = "MACOS_LOGIN_KEYCHAIN_FILE_SYMLINK_V1"
CURSOR_AUTHENTICATION_STATUS = "AUTHENTICATED_ACCESS_REFRESH"
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
    CURSOR_AUTHENTICATION_BRIDGE,
    "AUTHENTICATED_STATUS_PREFLIGHT",
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
    "0!==t.length&&(i(t)?n.add(t):r.push(t))}if(r.length>0)throw new Error",
    "return[...n]}}",
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
    authentication_bridge: str = "UNOBSERVED"
    authentication_bridge_digest: str = "UNOBSERVED"
    authentication_status: str = "UNOBSERVED"
    authentication_status_digest: str = "UNOBSERVED"
    _authentication_bridge_proof: _CursorAuthenticationBridgeProof | None = field(
        default=None,
        repr=False,
        compare=False,
    )

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
            "authentication_bridge": self.authentication_bridge,
            "authentication_bridge_digest": self.authentication_bridge_digest,
            "authentication_status": self.authentication_status,
            "authentication_status_digest": self.authentication_status_digest,
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


@dataclass(frozen=True, slots=True)
class _CursorAuthenticationBridgeProof:
    method: str
    source: str
    source_device: int
    source_inode: int
    source_uid: int
    source_mode: int
    destination: str

    @property
    def identity_digest(self) -> str:
        return _sha256_bytes(
            json.dumps(
                {
                    "method": self.method,
                    "source": self.source,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )


@dataclass(frozen=True, slots=True)
class _CursorAuthenticationStatusProof:
    is_authenticated: bool
    has_access_token: bool
    has_refresh_token: bool

    @property
    def status(self) -> str:
        if self.is_authenticated and self.has_access_token and self.has_refresh_token:
            return CURSOR_AUTHENTICATION_STATUS
        return "UNAUTHENTICATED"

    @property
    def canonical_digest(self) -> str:
        return _sha256_bytes(
            json.dumps(
                {
                    "has_access_token": self.has_access_token,
                    "has_refresh_token": self.has_refresh_token,
                    "is_authenticated": self.is_authenticated,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _owned_private_directory(path: Path, *, description: str) -> os.stat_result:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise CliPredispatchRefusal(f"Cursor CLI {description} is absent") from exc
    if (
        not stat.S_ISDIR(observed.st_mode)
        or path.is_symlink()
        or observed.st_uid != os.getuid()
        or stat.S_IMODE(observed.st_mode) != 0o700
    ):
        raise CliPredispatchRefusal(
            f"Cursor CLI {description} is not an owner-private directory"
        )
    return observed


def _qualified_login_keychain() -> tuple[Path, os.stat_result]:
    source = Path(QUALIFIED_CURSOR_LOGIN_KEYCHAIN)
    try:
        observed = source.lstat()
    except OSError as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI qualified login keychain source is absent"
        ) from exc
    if (
        not source.is_absolute()
        or source.is_symlink()
        or not stat.S_ISREG(observed.st_mode)
        or os.path.realpath(source) != str(source)
        or observed.st_uid != os.getuid()
        or stat.S_IMODE(observed.st_mode) & 0o022
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI login keychain source is not a fixed regular file"
        )
    return source, observed


def _authentication_bridge_destination(
    environment: Mapping[str, str],
) -> Path:
    home_value = environment.get("HOME", "")
    if not home_value or not os.path.isabs(home_value):
        raise CliPredispatchRefusal(
            "Cursor CLI authentication bridge requires an absolute hermetic HOME"
        )
    home = Path(home_value)
    _owned_private_directory(home, description="hermetic HOME")
    library = home / "Library"
    keychains = library / "Keychains"
    for path, description in (
        (library, "hermetic Library"),
        (keychains, "hermetic Keychains"),
    ):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise CliPredispatchRefusal(
                f"Cursor CLI {description} could not be created"
            ) from exc
        _owned_private_directory(path, description=description)
    return keychains / "login.keychain-db"


def _inspect_cursor_authentication_bridge(
    environment: Mapping[str, str],
) -> _CursorAuthenticationBridgeProof:
    source, source_stat = _qualified_login_keychain()
    destination = _authentication_bridge_destination(environment)
    try:
        destination_stat = destination.lstat()
    except OSError as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI authentication bridge is absent"
        ) from exc
    if (
        not stat.S_ISLNK(destination_stat.st_mode)
        or os.readlink(destination) != str(source)
        or os.path.realpath(destination) != str(source)
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI authentication bridge differs from the fixed login keychain"
        )
    return _CursorAuthenticationBridgeProof(
        method=CURSOR_AUTHENTICATION_BRIDGE,
        source=str(source),
        source_device=source_stat.st_dev,
        source_inode=source_stat.st_ino,
        source_uid=source_stat.st_uid,
        source_mode=stat.S_IMODE(source_stat.st_mode),
        destination=str(destination),
    )


def _install_cursor_authentication_bridge(
    environment: Mapping[str, str],
) -> _CursorAuthenticationBridgeProof:
    source, _source_stat = _qualified_login_keychain()
    destination = _authentication_bridge_destination(environment)
    if os.path.lexists(destination):
        raise CliPredispatchRefusal(
            "Cursor CLI authentication bridge destination is not empty"
        )
    try:
        destination.symlink_to(source)
    except OSError as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI authentication bridge could not be installed"
        ) from exc
    return _inspect_cursor_authentication_bridge(environment)


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


def _cursor_command(*, binary: str, prompt: str, workspace: str) -> tuple[str, ...]:
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
        raise CliPredispatchRefusal("Cursor CLI qualified package artifacts are absent")
    launcher_digest = _sha256_bytes(resolved.read_bytes())
    command_surface_bytes = command_surface.read_bytes()
    command_surface_digest = _sha256_bytes(command_surface_bytes)
    control_semantics_bytes = control_semantics.read_bytes()
    control_semantics_digest = _sha256_bytes(control_semantics_bytes)
    package_digest = _package_manifest_digest(root)
    try:
        command_surface_text = command_surface_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CliPredispatchRefusal("Cursor CLI command surface is not UTF-8") from exc
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
        or command_surface_digest != QUALIFIED_CURSOR_AGENT_COMMAND_SURFACE_DIGEST
        or control_semantics_digest != QUALIFIED_CURSOR_AGENT_CONTROL_SEMANTICS_DIGEST
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

    async def collect(stream: asyncio.StreamReader, *, destination: bytearray) -> None:
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
        returncode = await asyncio.wait_for(process.wait(), timeout=remaining)
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
        returncode=returncode,
        stdout=_decode_output(bytes(outputs["stdout"]), name=name),
        stderr=_decode_output(bytes(outputs["stderr"]), name=name),
    )


def _qualification_evidence(
    *,
    binary: str,
    max_tokens: int,
    version: str = "UNOBSERVED",
    package: _CursorPackageProof | None = None,
    authentication_bridge: _CursorAuthenticationBridgeProof | None = None,
    authentication_status: _CursorAuthenticationStatusProof | None = None,
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
        "authentication_bridge": (
            "UNOBSERVED"
            if authentication_bridge is None
            else authentication_bridge.method
        ),
        "authentication_bridge_digest": (
            "UNOBSERVED"
            if authentication_bridge is None
            else authentication_bridge.identity_digest
        ),
        "authentication_status": (
            "UNOBSERVED"
            if authentication_status is None
            else authentication_status.status
        ),
        "authentication_status_digest": (
            "UNOBSERVED"
            if authentication_status is None
            else authentication_status.canonical_digest
        ),
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


def _cursor_authentication_status(
    result: _ProcessOutput,
    *,
    evidence: Mapping[str, object],
) -> _CursorAuthenticationStatusProof:
    if result.returncode != 0:
        retained = dict(evidence)
        retained.update(
            {
                "authentication_status": "STATUS_COMMAND_FAILED",
                "authentication_status_digest": _sha256_text(
                    f"cursor-authentication-status-returncode-v1:{result.returncode}"
                ),
            }
        )
        raise CliPredispatchRefusal(
            "Cursor CLI authentication status preflight failed",
            qualification_evidence=retained,
        )
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        value = None
    if not isinstance(value, dict) or not all(
        isinstance(value.get(key), bool)
        for key in ("isAuthenticated", "hasAccessToken", "hasRefreshToken")
    ):
        retained = dict(evidence)
        retained.update(
            {
                "authentication_status": "INVALID_STATUS",
                "authentication_status_digest": _sha256_text(
                    "cursor-authentication-status-invalid-v1"
                ),
            }
        )
        raise CliPredispatchRefusal(
            "Cursor CLI authentication status is invalid",
            qualification_evidence=retained,
        )
    proof = _CursorAuthenticationStatusProof(
        is_authenticated=value["isAuthenticated"],
        has_access_token=value["hasAccessToken"],
        has_refresh_token=value["hasRefreshToken"],
    )
    retained = dict(evidence)
    retained.update(
        {
            "authentication_status": proof.status,
            "authentication_status_digest": proof.canonical_digest,
        }
    )
    if proof.status != CURSOR_AUTHENTICATION_STATUS:
        raise CliPredispatchRefusal(
            "Cursor CLI is not authenticated in the isolated runtime",
            qualification_evidence=retained,
        )
    return proof


def _require_qualified_request_path(
    binary: str, *, evidence: Mapping[str, object]
) -> None:
    if os.path.abspath(binary) != QUALIFIED_CURSOR_AGENT_BIN:
        raise CliPredispatchRefusal(
            "Cursor CLI request path differs from the checked policy",
            qualification_evidence=evidence,
        )


def _require_qualified_static_results(
    *,
    version_result: _ProcessOutput,
    help_result: _ProcessOutput,
    evidence: Mapping[str, object],
) -> None:
    version = version_result.stdout.strip()
    if version_result.returncode != 0 or version != QUALIFIED_CURSOR_AGENT_VERSION:
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


def _build_qualification(
    *,
    binary: str,
    max_tokens: int,
    package: _CursorPackageProof,
    authentication_bridge: _CursorAuthenticationBridgeProof,
    authentication_status: _CursorAuthenticationStatusProof,
    version_result: _ProcessOutput,
    help_result: _ProcessOutput,
) -> CursorCliQualification:
    version = version_result.stdout.strip()
    evidence = _qualification_evidence(
        binary=binary,
        max_tokens=max_tokens,
        version=version or "UNOBSERVED",
        package=package,
        authentication_bridge=authentication_bridge,
        authentication_status=authentication_status,
    )
    _require_qualified_static_results(
        version_result=version_result,
        help_result=help_result,
        evidence=evidence,
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
        authentication_bridge=authentication_bridge.method,
        authentication_bridge_digest=authentication_bridge.identity_digest,
        authentication_status=authentication_status.status,
        authentication_status_digest=authentication_status.canonical_digest,
        _authentication_bridge_proof=authentication_bridge,
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
        _authentication_bridge_destination(environment)
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
        evidence = _qualification_evidence(
            binary=binary,
            max_tokens=max_tokens,
            version=version_result.stdout.strip() or "UNOBSERVED",
            package=package,
        )
        _require_qualified_static_results(
            version_result=version_result,
            help_result=help_result,
            evidence=evidence,
        )
        authentication_bridge = _install_cursor_authentication_bridge(environment)
        evidence = _qualification_evidence(
            binary=binary,
            max_tokens=max_tokens,
            version=version_result.stdout.strip() or "UNOBSERVED",
            package=package,
            authentication_bridge=authentication_bridge,
        )
        authentication_result = _run_bounded_process(
            (resolved_binary, "status", "--format", "json"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
        )
        authentication_status = _cursor_authentication_status(
            authentication_result,
            evidence=evidence,
        )
        qualification = _build_qualification(
            binary=binary,
            max_tokens=max_tokens,
            package=package,
            authentication_bridge=authentication_bridge,
            authentication_status=authentication_status,
            version_result=version_result,
            help_result=help_result,
        )
        if _inspect_cursor_package(resolved_binary) != package:
            raise CliPredispatchRefusal(
                "Cursor CLI package changed during qualification",
                qualification_evidence=evidence,
            )
        if _inspect_cursor_authentication_bridge(environment) != authentication_bridge:
            raise CliPredispatchRefusal(
                "Cursor CLI authentication bridge changed during qualification",
                qualification_evidence=qualification.as_dict(),
            )
        return qualification
    except CliPredispatchRefusal as exc:
        if exc.qualification_evidence:
            raise
        raise CliPredispatchRefusal(str(exc), qualification_evidence=evidence) from exc
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
        _authentication_bridge_destination(environment)
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
        evidence = _qualification_evidence(
            binary=binary,
            max_tokens=max_tokens,
            version=version_result.stdout.strip() or "UNOBSERVED",
            package=package,
        )
        _require_qualified_static_results(
            version_result=version_result,
            help_result=help_result,
            evidence=evidence,
        )
        authentication_bridge = _install_cursor_authentication_bridge(environment)
        evidence = _qualification_evidence(
            binary=binary,
            max_tokens=max_tokens,
            version=version_result.stdout.strip() or "UNOBSERVED",
            package=package,
            authentication_bridge=authentication_bridge,
        )
        authentication_result = await _run_bounded_process_async(
            (resolved_binary, "status", "--format", "json"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
        )
        authentication_status = _cursor_authentication_status(
            authentication_result,
            evidence=evidence,
        )
        qualification = _build_qualification(
            binary=binary,
            max_tokens=max_tokens,
            package=package,
            authentication_bridge=authentication_bridge,
            authentication_status=authentication_status,
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
        retained_bridge = await asyncio.to_thread(
            _inspect_cursor_authentication_bridge, environment
        )
        if retained_bridge != authentication_bridge:
            raise CliPredispatchRefusal(
                "Cursor CLI authentication bridge changed during qualification",
                qualification_evidence=qualification.as_dict(),
            )
        return qualification
    except CliPredispatchRefusal as exc:
        if exc.qualification_evidence:
            raise
        raise CliPredispatchRefusal(str(exc), qualification_evidence=evidence) from exc
    except (CliOutputBoundExceeded, CliOutputDecodeError, OSError, TimeoutError) as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI exact-binary preflight failed",
            qualification_evidence=evidence,
        ) from exc


def _require_retained_cursor_authentication_bridge(
    qualification: CursorCliQualification,
    *,
    environment: Mapping[str, str],
) -> None:
    expected = qualification._authentication_bridge_proof
    try:
        retained = _inspect_cursor_authentication_bridge(environment)
    except CliPredispatchRefusal as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI authentication bridge was lost before dispatch",
            qualification_evidence=qualification.as_dict(),
        ) from exc
    if expected is None or retained != expected:
        raise CliPredispatchRefusal(
            "Cursor CLI authentication bridge changed before dispatch",
            qualification_evidence=qualification.as_dict(),
        )


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
    _require_retained_cursor_authentication_bridge(
        qualification,
        environment=environment,
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
    await asyncio.to_thread(
        _require_retained_cursor_authentication_bridge,
        qualification,
        environment=environment,
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
    "CURSOR_AUTHENTICATION_BRIDGE",
    "CURSOR_AUTHENTICATION_STATUS",
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
    "QUALIFIED_CURSOR_LOGIN_KEYCHAIN",
    "CliOutputBoundExceeded",
    "CliOutputDecodeError",
    "CliPredispatchRefusal",
    "CursorCliQualification",
    "cursor_stdout_limit",
    "run_cursor_transport",
    "run_cursor_transport_async",
]
