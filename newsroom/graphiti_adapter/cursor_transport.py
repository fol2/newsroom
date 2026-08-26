"""Exact-binary Cursor transport qualification and bounded execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from newsroom.graphiti_adapter.cli_process import (
    CliOutputBoundExceeded,
    CliOutputDecodeError,
    CliProcessOutput,
    CliTransportTimeout,
    run_bounded_process,
    run_bounded_process_async,
    timeout_deadline_after,
    timeout_diagnostic,
)
from newsroom.graphiti_adapter.evaluation_packet import CURSOR_AGENT_MODEL_ID

QUALIFIED_CURSOR_AGENT_VERSION = "2026.08.11-e8db854"
QUALIFIED_CURSOR_AGENT_BIN = "/Users/jamesto/.local/bin/cursor-agent"
QUALIFIED_CURSOR_AGENT_RESOLVED_BIN = (
    "/Users/jamesto/.local/share/cursor-agent/versions/"
    f"{QUALIFIED_CURSOR_AGENT_VERSION}/cursor-agent"
)
QUALIFIED_CURSOR_LOGIN_KEYCHAIN = "/Users/jamesto/Library/Keychains/login.keychain-db"
QUALIFIED_CURSOR_SECURITY_BIN = "/usr/bin/security"
QUALIFIED_CURSOR_SECURITY_OWNER_UID = 0
CURSOR_AUTHENTICATION_BRIDGE = "MACOS_LOGIN_KEYCHAIN_FILE_SYMLINK_V1"
CURSOR_AUTHENTICATION_PROBE = "MACOS_CURSOR_KEYCHAIN_LOOKUP_V1"
CURSOR_CREDENTIAL_ACCOUNT = "cursor-user"
CURSOR_CREDENTIAL_SEARCH = "DEFAULT_KEYCHAIN_SEARCH_LIST"
CURSOR_CREDENTIAL_STATE = "LOCAL_ACCESS_REFRESH_TOKENS_READABLE"
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
CURSOR_LOCAL_CREDENTIAL_PROBE_TIMEOUT_SECONDS = 5
CURSOR_PREFLIGHT_MAX_BYTES = 64 * 1024
CURSOR_STDOUT_BASE_BYTES = 64 * 1024
CURSOR_STDOUT_BYTES_PER_TOKEN = 64
CURSOR_STDOUT_LIMIT_FORMULA = "65536+64*REQUEST_MAX_TOKENS"
CURSOR_STDOUT_LIMIT_IDENTITY = (
    "cursor-controller-stdout-v1:" + CURSOR_STDOUT_LIMIT_FORMULA
)
CURSOR_COMMAND_SURFACE_PROOF = "PINNED_PACKAGE_HIDDEN_OPTION_REGISTRATIONS_V1"
_ProcessOutput = CliProcessOutput
_run_bounded_process = run_bounded_process
_run_bounded_process_async = run_bounded_process_async

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
    CURSOR_AUTHENTICATION_PROBE,
)
_CURSOR_CREDENTIAL_SERVICES = (
    "cursor-access-token",
    "cursor-refresh-token",
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
    authentication_probe: str = "UNOBSERVED"
    authentication_probe_digest: str = "UNOBSERVED"
    credential_state: str = "UNOBSERVED"
    credential_state_digest: str = "UNOBSERVED"
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
            "authentication_probe": self.authentication_probe,
            "authentication_probe_digest": self.authentication_probe_digest,
            "credential_state": self.credential_state,
            "credential_state_digest": self.credential_state_digest,
        }


@dataclass(frozen=True, slots=True)
class _CursorPackageProof:
    root: str
    launcher_digest: str
    command_surface_digest: str
    control_semantics_digest: str
    package_digest: str


@dataclass(frozen=True, slots=True)
class _CursorQualificationPreparation:
    package: _CursorPackageProof
    resolved_binary: str
    evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class _CursorAuthenticationBridgeProof:
    method: str
    source: str
    source_device: int
    source_inode: int
    source_uid: int
    source_mode: int
    source_size: int
    source_mtime_ns: int
    source_ctime_ns: int
    destination: str

    @property
    def policy_digest(self) -> str:
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
class _CursorCredentialProbeProof:
    security_binary: str
    account: str
    search: str
    access_token_readable: bool
    refresh_token_readable: bool

    @property
    def probe_policy_digest(self) -> str:
        return _sha256_bytes(
            json.dumps(
                {
                    "method": CURSOR_AUTHENTICATION_PROBE,
                    "security_binary": self.security_binary,
                    "account": self.account,
                    "search": self.search,
                    "services": list(_CURSOR_CREDENTIAL_SERVICES),
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )

    @property
    def credential_state(self) -> str:
        if self.access_token_readable and self.refresh_token_readable:
            return CURSOR_CREDENTIAL_STATE
        return "LOCAL_CREDENTIALS_UNAVAILABLE"

    @property
    def credential_state_digest(self) -> str:
        return _sha256_bytes(
            json.dumps(
                {
                    "account": self.account,
                    "access_token_readable": self.access_token_readable,
                    "refresh_token_readable": self.refresh_token_readable,
                    "search": self.search,
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
        source_size=source_stat.st_size,
        source_mtime_ns=source_stat.st_mtime_ns,
        source_ctime_ns=source_stat.st_ctime_ns,
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


def _qualified_cursor_security_binary() -> tuple[Path, os.stat_result]:
    binary = Path(QUALIFIED_CURSOR_SECURITY_BIN)
    try:
        observed = binary.lstat()
    except OSError as exc:
        raise CliPredispatchRefusal(
            "Cursor CLI local credential probe executable is absent"
        ) from exc
    if (
        not binary.is_absolute()
        or binary.is_symlink()
        or not stat.S_ISREG(observed.st_mode)
        or os.path.realpath(binary) != str(binary)
        or observed.st_uid != QUALIFIED_CURSOR_SECURITY_OWNER_UID
        or stat.S_IMODE(observed.st_mode) & 0o022
        or not observed.st_mode & stat.S_IXUSR
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI local credential probe executable is not fixed"
        )
    return binary, observed


def _probe_cursor_credentials_locally(
    *,
    environment: Mapping[str, str],
    authentication_bridge: _CursorAuthenticationBridgeProof,
    evidence: Mapping[str, object],
) -> _CursorCredentialProbeProof:
    security_binary, security_before = _qualified_cursor_security_binary()
    if _inspect_cursor_authentication_bridge(environment) != authentication_bridge:
        raise CliPredispatchRefusal(
            "Cursor CLI authentication bridge changed before credential lookup",
            qualification_evidence=evidence,
        )
    returncodes: list[int] = []
    command_environment = {
        key: environment[key]
        for key in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        if key in environment
    }
    for service in _CURSOR_CREDENTIAL_SERVICES:
        started = time.monotonic()
        deadline_at = timeout_deadline_after(
            CURSOR_LOCAL_CREDENTIAL_PROBE_TIMEOUT_SECONDS
        )
        try:
            result = subprocess.run(
                (
                    str(security_binary),
                    "find-generic-password",
                    "-a",
                    CURSOR_CREDENTIAL_ACCOUNT,
                    "-s",
                    service,
                    "-w",
                ),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=CURSOR_LOCAL_CREDENTIAL_PROBE_TIMEOUT_SECONDS,
                cwd="/",
                env=command_environment,
            )
        except subprocess.TimeoutExpired as exc:
            retained = dict(evidence)
            retained.update(
                {
                    "authentication_probe": CURSOR_AUTHENTICATION_PROBE,
                    "credential_state": "LOCAL_PROBE_TIMED_OUT",
                    "timeout_diagnostic": timeout_diagnostic(
                        boundary="CONTROLLER_DEADLINE",
                        phase="CREDENTIAL_PROBE",
                        cause="CONFIGURED_TIMEOUT_EXPIRED",
                        configured_timeout_ms=(
                            CURSOR_LOCAL_CREDENTIAL_PROBE_TIMEOUT_SECONDS * 1_000
                        ),
                        elapsed_ms=round(
                            (time.monotonic() - started) * 1_000
                        ),
                        deadline_at=deadline_at,
                        last_progress="CREDENTIAL_PROBE_STARTED",
                        termination="UNOBSERVED",
                        process=security_binary.name,
                    ),
                }
            )
            raise CliPredispatchRefusal(
                "Cursor CLI local credential probe timed out",
                qualification_evidence=retained,
            ) from exc
        except OSError as exc:
            retained = dict(evidence)
            retained.update(
                {
                    "authentication_probe": CURSOR_AUTHENTICATION_PROBE,
                    "credential_state": "LOCAL_PROBE_FAILED",
                }
            )
            raise CliPredispatchRefusal(
                "Cursor CLI local credential probe failed",
                qualification_evidence=retained,
            ) from exc
        returncodes.append(result.returncode)
    _security_after, security_after = _qualified_cursor_security_binary()
    if (
        security_before.st_dev,
        security_before.st_ino,
        security_before.st_uid,
        stat.S_IMODE(security_before.st_mode),
    ) != (
        security_after.st_dev,
        security_after.st_ino,
        security_after.st_uid,
        stat.S_IMODE(security_after.st_mode),
    ):
        raise CliPredispatchRefusal(
            "Cursor CLI local credential probe executable changed",
            qualification_evidence=evidence,
        )
    proof = _CursorCredentialProbeProof(
        security_binary=str(security_binary),
        account=CURSOR_CREDENTIAL_ACCOUNT,
        search=CURSOR_CREDENTIAL_SEARCH,
        access_token_readable=returncodes[0] == 0,
        refresh_token_readable=returncodes[1] == 0,
    )
    if proof.credential_state != CURSOR_CREDENTIAL_STATE:
        retained = dict(evidence)
        retained.update(
            {
                "authentication_probe": CURSOR_AUTHENTICATION_PROBE,
                "authentication_probe_digest": proof.probe_policy_digest,
                "credential_state": proof.credential_state,
                "credential_state_digest": proof.credential_state_digest,
            }
        )
        raise CliPredispatchRefusal(
            "Cursor CLI local credentials are not readable",
            qualification_evidence=retained,
        )
    return proof


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


def _qualification_evidence(
    *,
    binary: str,
    max_tokens: int,
    version: str = "UNOBSERVED",
    package: _CursorPackageProof | None = None,
    authentication_bridge: _CursorAuthenticationBridgeProof | None = None,
    credential_probe: _CursorCredentialProbeProof | None = None,
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
            else authentication_bridge.policy_digest
        ),
        "authentication_probe": (
            "UNOBSERVED" if credential_probe is None else CURSOR_AUTHENTICATION_PROBE
        ),
        "authentication_probe_digest": (
            "UNOBSERVED"
            if credential_probe is None
            else credential_probe.probe_policy_digest
        ),
        "credential_state": (
            "UNOBSERVED"
            if credential_probe is None
            else credential_probe.credential_state
        ),
        "credential_state_digest": (
            "UNOBSERVED"
            if credential_probe is None
            else credential_probe.credential_state_digest
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
    credential_probe: _CursorCredentialProbeProof,
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
        credential_probe=credential_probe,
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
        authentication_bridge_digest=authentication_bridge.policy_digest,
        authentication_probe=CURSOR_AUTHENTICATION_PROBE,
        authentication_probe_digest=credential_probe.probe_policy_digest,
        credential_state=credential_probe.credential_state,
        credential_state_digest=credential_probe.credential_state_digest,
        _authentication_bridge_proof=authentication_bridge,
    )


def _prepare_cursor_qualification(
    *,
    binary: str,
    environment: Mapping[str, str],
    max_tokens: int,
) -> _CursorQualificationPreparation:
    evidence = _qualification_evidence(binary=binary, max_tokens=max_tokens)
    try:
        _require_qualified_request_path(binary, evidence=evidence)
        package = _inspect_cursor_package(binary)
        evidence = _qualification_evidence(
            binary=binary, max_tokens=max_tokens, package=package
        )
        _authentication_bridge_destination(environment)
        return _CursorQualificationPreparation(
            package=package,
            resolved_binary=os.path.realpath(binary),
            evidence=evidence,
        )
    except CliPredispatchRefusal as exc:
        if exc.qualification_evidence:
            raise
        raise CliPredispatchRefusal(str(exc), qualification_evidence=evidence) from exc


def _complete_cursor_qualification(
    *,
    binary: str,
    environment: Mapping[str, str],
    max_tokens: int,
    preparation: _CursorQualificationPreparation,
    version_result: _ProcessOutput,
    help_result: _ProcessOutput,
) -> CursorCliQualification:
    package = preparation.package
    evidence = _qualification_evidence(
        binary=binary,
        max_tokens=max_tokens,
        version=version_result.stdout.strip() or "UNOBSERVED",
        package=package,
    )
    try:
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
        credential_probe = _probe_cursor_credentials_locally(
            environment=environment,
            authentication_bridge=authentication_bridge,
            evidence=evidence,
        )
        qualification = _build_qualification(
            binary=binary,
            max_tokens=max_tokens,
            package=package,
            authentication_bridge=authentication_bridge,
            credential_probe=credential_probe,
            version_result=version_result,
            help_result=help_result,
        )
        if _inspect_cursor_package(preparation.resolved_binary) != package:
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


def _qualify_cursor_agent(
    *,
    binary: str,
    cwd: str,
    environment: Mapping[str, str],
    max_tokens: int,
) -> CursorCliQualification:
    evidence = _qualification_evidence(binary=binary, max_tokens=max_tokens)
    try:
        preparation = _prepare_cursor_qualification(
            binary=binary,
            environment=environment,
            max_tokens=max_tokens,
        )
        evidence = preparation.evidence
        version_result = _run_bounded_process(
            (preparation.resolved_binary, "--version"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
            phase="PREDISPATCH_VERSION",
        )
        help_result = _run_bounded_process(
            (preparation.resolved_binary, "--help"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
            phase="PREDISPATCH_HELP",
        )
        return _complete_cursor_qualification(
            binary=binary,
            environment=environment,
            max_tokens=max_tokens,
            preparation=preparation,
            version_result=version_result,
            help_result=help_result,
        )
    except CliPredispatchRefusal as exc:
        if exc.qualification_evidence:
            raise
        raise CliPredispatchRefusal(str(exc), qualification_evidence=evidence) from exc
    except (CliOutputBoundExceeded, CliOutputDecodeError, OSError, TimeoutError) as exc:
        if isinstance(exc, CliTransportTimeout):
            evidence = {**evidence, "timeout_diagnostic": dict(exc.evidence)}
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
        preparation = await asyncio.to_thread(
            _prepare_cursor_qualification,
            binary=binary,
            environment=environment,
            max_tokens=max_tokens,
        )
        evidence = preparation.evidence
        version_result = await _run_bounded_process_async(
            (preparation.resolved_binary, "--version"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
            phase="PREDISPATCH_VERSION",
        )
        help_result = await _run_bounded_process_async(
            (preparation.resolved_binary, "--help"),
            timeout=CURSOR_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=CURSOR_PREFLIGHT_MAX_BYTES,
            cwd=cwd,
            environment=environment,
            phase="PREDISPATCH_HELP",
        )
        return await asyncio.to_thread(
            _complete_cursor_qualification,
            binary=binary,
            environment=environment,
            max_tokens=max_tokens,
            preparation=preparation,
            version_result=version_result,
            help_result=help_result,
        )
    except CliPredispatchRefusal as exc:
        if exc.qualification_evidence:
            raise
        raise CliPredispatchRefusal(str(exc), qualification_evidence=evidence) from exc
    except (CliOutputBoundExceeded, CliOutputDecodeError, OSError, TimeoutError) as exc:
        if isinstance(exc, CliTransportTimeout):
            evidence = {**evidence, "timeout_diagnostic": dict(exc.evidence)}
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
        phase="PRIMARY_TRANSPORT",
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
        phase="PRIMARY_TRANSPORT",
    )
    if result.returncode != 0:
        raise RuntimeError("cursor-agent Graphiti LLM failed")
    if not result.stdout.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return result.stdout, qualification


__all__ = [
    "CURSOR_AGENT_BIN",
    "CURSOR_AUTHENTICATION_BRIDGE",
    "CURSOR_AUTHENTICATION_PROBE",
    "CURSOR_COMMAND_SURFACE_PROOF",
    "CURSOR_CREDENTIAL_ACCOUNT",
    "CURSOR_CREDENTIAL_SEARCH",
    "CURSOR_CREDENTIAL_STATE",
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
    "QUALIFIED_CURSOR_SECURITY_BIN",
    "CliPredispatchRefusal",
    "CursorCliQualification",
    "cursor_stdout_limit",
    "run_cursor_transport",
    "run_cursor_transport_async",
]
