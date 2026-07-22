from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Mapping, Sequence

from .contracts import ContractError, SdlcContract, load_contract
from .emit_evidence import EvidenceError, canonical_json_bytes, sha256_identity
from .run_gate import GateRunError, GateRunResult, run_configured_gate


SCHEMA_VERSION = "newsroom.sdlc.command-spec.v1"
RUN_SCHEMA_VERSION = "newsroom.sdlc.command-run.v1"
_MAX_SPEC_BYTES = 256 * 1024
_MAX_ARGUMENTS = 256
_MAX_ARGUMENT_CHARS = 4096
_MAX_ENVIRONMENT_ITEMS = 128
_MAX_ENVIRONMENT_VALUE_CHARS = 4096
_MAX_OUTPUT_BYTES = 1_048_576
_MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
_MAX_PASSED_ENV_VALUE_CHARS = 65_536
_MAX_PASSED_ENV_TOTAL_CHARS = 262_144
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.*-]{1,128}")
_SECRET_NAME = re.compile(
    r"(?:AUTH|CREDENTIAL|KEY|PASSWORD|SECRET|TOKEN)", re.IGNORECASE
)
_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "gate_id",
        "phase",
        "argv",
        "cwd",
        "static_env",
        "pass_env",
        "redact_env",
        "executable_digest",
        "output_limit_bytes",
        "termination_grace_ms",
    }
)


class CommandSpecError(ValueError):
    """Raised when a command specification cannot safely drive a gate."""


@dataclass(frozen=True)
class CommandSpec:
    gate_id: str
    phase: str
    argv: tuple[str, ...]
    cwd: str
    static_env: tuple[tuple[str, str], ...]
    pass_env: tuple[str, ...]
    redact_env: tuple[str, ...]
    executable_digest: str
    output_limit_bytes: int
    termination_grace_ms: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "gate_id": self.gate_id,
            "phase": self.phase,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "static_env": dict(self.static_env),
            "pass_env": list(self.pass_env),
            "redact_env": list(self.redact_env),
            "executable_digest": self.executable_digest,
            "output_limit_bytes": self.output_limit_bytes,
            "termination_grace_ms": self.termination_grace_ms,
        }

    @property
    def digest(self) -> str:
        try:
            return sha256_identity(self.as_dict())
        except EvidenceError as exc:
            raise CommandSpecError("canonicalization") from exc


@dataclass(frozen=True)
class CommandRun:
    command_spec_digest: str
    gate_run: GateRunResult

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": RUN_SCHEMA_VERSION,
            "command_spec_digest": self.command_spec_digest,
            "gate_run": self.gate_run.as_dict(),
        }


def _bounded_string(
    value: object,
    code: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or (not value and not allow_empty)
        or len(value) > maximum
    ):
        raise CommandSpecError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CommandSpecError(code)
    return value


def _environment_name(value: object) -> str:
    if not isinstance(value, str) or _ENVIRONMENT_NAME.fullmatch(value) is None:
        raise CommandSpecError("environment_name")
    return value


def _safe_relative_directory(repo_root: Path, relative: object) -> tuple[str, Path]:
    text = _bounded_string(relative, "cwd", maximum=512)
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in text:
        raise CommandSpecError("cwd")
    current = repo_root
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise CommandSpecError("cwd_symlink")
    resolved = current.resolve()
    if not resolved.is_relative_to(repo_root) or not resolved.is_dir():
        raise CommandSpecError("cwd")
    normalized = resolved.relative_to(repo_root).as_posix()
    return normalized if normalized != "." else ".", resolved


def _accepted_gate_ids(contract: SdlcContract) -> frozenset[str]:
    return frozenset(str(gate["id"]) for gate in contract.data["gate"].values())


def executable_digest(path: str | Path) -> tuple[str, str]:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise CommandSpecError("executable_path")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise CommandSpecError("executable_path") from exc
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise CommandSpecError("executable_open") from exc
    digest = hashlib.sha256()
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= _MAX_EXECUTABLE_BYTES
            or not os.access(resolved, os.X_OK)
        ):
            raise CommandSpecError("executable_file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while payload := stream.read(1024 * 1024):
                digest.update(payload)
    finally:
        os.close(descriptor)
    return resolved.as_posix(), "sha256:" + digest.hexdigest()


def _verified_executable(path: str, expected_digest: object) -> tuple[str, str]:
    if not isinstance(expected_digest, str) or _SHA256.fullmatch(expected_digest) is None:
        raise CommandSpecError("executable_digest")
    resolved, actual = executable_digest(path)
    if actual != expected_digest:
        raise CommandSpecError("executable_digest")
    return resolved, actual


def parse_command_spec(
    value: object,
    *,
    contract: SdlcContract,
) -> CommandSpec:
    if not isinstance(value, dict) or frozenset(value) != _REQUIRED_KEYS:
        raise CommandSpecError("shape")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise CommandSpecError("schema_version")

    gate_id = _bounded_string(value.get("gate_id"), "gate_id", maximum=128)
    if _SAFE_ID.fullmatch(gate_id) is None or gate_id not in _accepted_gate_ids(contract):
        raise CommandSpecError("gate_id")
    phase = _bounded_string(value.get("phase"), "phase", maximum=128)
    if _SAFE_ID.fullmatch(phase) is None:
        raise CommandSpecError("phase")

    raw_argv = value.get("argv")
    if not isinstance(raw_argv, list) or not 0 < len(raw_argv) <= _MAX_ARGUMENTS:
        raise CommandSpecError("argv")
    argv_values = tuple(
        _bounded_string(item, "argv", maximum=_MAX_ARGUMENT_CHARS)
        for item in raw_argv
    )

    cwd, _ = _safe_relative_directory(contract.repo_root, value.get("cwd"))

    raw_static = value.get("static_env")
    if not isinstance(raw_static, dict) or len(raw_static) > _MAX_ENVIRONMENT_ITEMS:
        raise CommandSpecError("static_env")
    static: dict[str, str] = {}
    for raw_name, raw_value in raw_static.items():
        name = _environment_name(raw_name)
        if _SECRET_NAME.search(name):
            raise CommandSpecError("static_secret_name")
        static[name] = _bounded_string(
            raw_value,
            "static_env_value",
            maximum=_MAX_ENVIRONMENT_VALUE_CHARS,
            allow_empty=True,
        )

    raw_pass = value.get("pass_env")
    if not isinstance(raw_pass, list) or len(raw_pass) > _MAX_ENVIRONMENT_ITEMS:
        raise CommandSpecError("pass_env")
    passed = tuple(sorted(_environment_name(item) for item in raw_pass))
    if len(set(passed)) != len(passed):
        raise CommandSpecError("pass_env_duplicate")
    if any(_SECRET_NAME.search(name) is None for name in passed):
        raise CommandSpecError("unbound_environment")

    raw_redact = value.get("redact_env")
    if not isinstance(raw_redact, list) or len(raw_redact) > _MAX_ENVIRONMENT_ITEMS:
        raise CommandSpecError("redact_env")
    redacted = tuple(sorted(_environment_name(item) for item in raw_redact))
    if len(set(redacted)) != len(redacted):
        raise CommandSpecError("redact_env_duplicate")
    if redacted != passed:
        raise CommandSpecError("unbound_environment")

    resolved_executable, expected_executable_digest = _verified_executable(
        argv_values[0],
        value.get("executable_digest"),
    )
    argv = (resolved_executable, *argv_values[1:])

    output_limit = value.get("output_limit_bytes")
    if (
        isinstance(output_limit, bool)
        or not isinstance(output_limit, int)
        or not 0 < output_limit <= _MAX_OUTPUT_BYTES
    ):
        raise CommandSpecError("output_limit")

    grace_ms = value.get("termination_grace_ms")
    if (
        isinstance(grace_ms, bool)
        or not isinstance(grace_ms, int)
        or not 0 < grace_ms <= 5000
    ):
        raise CommandSpecError("termination_grace")

    return CommandSpec(
        gate_id=gate_id,
        phase=phase,
        argv=argv,
        cwd=cwd,
        static_env=tuple(sorted(static.items())),
        pass_env=passed,
        redact_env=redacted,
        executable_digest=expected_executable_digest,
        output_limit_bytes=output_limit,
        termination_grace_ms=grace_ms,
    )


def _safe_input_path(repo_root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
    ):
        raise CommandSpecError("spec_path")
    current = repo_root
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise CommandSpecError("spec_symlink")
    resolved = current.resolve()
    if not resolved.is_relative_to(repo_root):
        raise CommandSpecError("spec_path")
    try:
        metadata = os.lstat(current)
    except OSError as exc:
        raise CommandSpecError("spec_stat") from exc
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= _MAX_SPEC_BYTES:
        raise CommandSpecError("spec_file")
    return current


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if name in value:
            raise CommandSpecError("spec_duplicate_key")
        value[name] = item
    return value


def load_command_spec(
    repo_root: str | Path,
    spec_path: str | Path,
    *,
    contract: SdlcContract | None = None,
) -> CommandSpec:
    root = Path(repo_root).resolve()
    accepted = contract or load_contract(root)
    if accepted.repo_root != root:
        raise CommandSpecError("contract_root")
    path = _safe_input_path(root, spec_path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CommandSpecError("spec_open") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= _MAX_SPEC_BYTES:
            raise CommandSpecError("spec_file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(_MAX_SPEC_BYTES + 1)
    finally:
        os.close(descriptor)
    if not payload or len(payload) > _MAX_SPEC_BYTES:
        raise CommandSpecError("spec_file")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CommandSpecError("spec_json") from exc
    return parse_command_spec(value, contract=accepted)


def build_environment(
    spec: CommandSpec,
    ambient: Mapping[str, str],
) -> dict[str, str]:
    if any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in ambient.items()
    ):
        raise CommandSpecError("ambient_environment")
    environment = dict(spec.static_env)
    total = 0
    for name in spec.pass_env:
        value = ambient.get(name)
        if value is None:
            raise CommandSpecError("missing_environment")
        if "\x00" in value or len(value) > _MAX_PASSED_ENV_VALUE_CHARS:
            raise CommandSpecError("environment_value")
        total += len(value)
        if total > _MAX_PASSED_ENV_TOTAL_CHARS:
            raise CommandSpecError("environment_size")
        environment[name] = value
    return environment


def execute_command_spec(
    *,
    contract: SdlcContract,
    spec: CommandSpec,
    ambient_env: Mapping[str, str] | None = None,
) -> CommandRun:
    validated = parse_command_spec(spec.as_dict(), contract=contract)
    if validated != spec:
        raise CommandSpecError("spec_not_normalized")
    _, cwd = _safe_relative_directory(contract.repo_root, validated.cwd)
    environment = build_environment(
        validated, os.environ if ambient_env is None else ambient_env
    )
    result = run_configured_gate(
        contract=contract,
        gate_id=validated.gate_id,
        phase=validated.phase,
        argv=validated.argv,
        cwd=cwd,
        env=environment,
        redact_values=tuple(
            environment[name]
            for name in validated.redact_env
            if environment[name]
        ),
        output_limit_bytes=validated.output_limit_bytes,
        termination_grace_seconds=validated.termination_grace_ms / 1000.0,
    )
    return CommandRun(validated.digest, result)


def _safe_output_path(repo_root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
        or candidate.suffix != ".json"
    ):
        raise CommandSpecError("output_path")
    current = repo_root
    for part in candidate.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise CommandSpecError("output_parent")
    parent = current.resolve()
    if not parent.is_relative_to(repo_root) or not parent.is_dir():
        raise CommandSpecError("output_parent")
    return current / candidate.name


def _publish_output(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise CommandSpecError("output_exists")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise CommandSpecError("output_exists") from exc
        try:
            directory = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
        except OSError:
            directory = -1
        if directory >= 0:
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute one canonical Newsroom command specification"
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repo_root).resolve()
    try:
        contract = load_contract(root)
        spec = load_command_spec(root, arguments.spec, contract=contract)
        command_run = execute_command_spec(contract=contract, spec=spec)
        rendered = canonical_json_bytes(command_run.as_dict()) + b"\n"
        if arguments.output:
            _publish_output(_safe_output_path(root, arguments.output), rendered)
        else:
            sys.stdout.write(rendered.decode("utf-8"))
    except (CommandSpecError, ContractError, GateRunError, EvidenceError, OSError) as exc:
        code = (
            str(exc)
            if isinstance(exc, CommandSpecError) and str(exc)
            else type(exc).__name__
        )
        print(f"ENVIRONMENT_ERROR:command-spec:{code}", file=sys.stderr)
        return 3
    return {
        "PASS": 0,
        "FAIL": 1,
        "BUDGET_EXCEEDED": 2,
    }.get(command_run.gate_run.result, 3)


if __name__ == "__main__":
    raise SystemExit(main())
