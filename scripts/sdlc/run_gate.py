from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Mapping, Sequence

from .contracts import ContractError, SdlcContract, load_contract


SCHEMA_VERSION = "newsroom.sdlc.gate-run.v1"
_SECRET_NAME = re.compile(r"(?:AUTH|CREDENTIAL|KEY|PASSWORD|SECRET|TOKEN)", re.IGNORECASE)
_SAFE_ID = re.compile(r"[A-Za-z0-9_.*-]{1,128}")


class GateRunError(ValueError):
    """Raised when a bounded gate invocation is invalid."""


@dataclass(frozen=True)
class LaneDeadline:
    started_ns: int
    timeout_ms: int

    @classmethod
    def start(cls, timeout_seconds: float) -> "LaneDeadline":
        timeout_ms = int(timeout_seconds * 1000)
        if timeout_ms <= 0 or timeout_ms >= 60_000:
            raise GateRunError("lane timeout must be positive and below 60 seconds")
        return cls(time.monotonic_ns(), timeout_ms)

    def remaining_seconds(self, *, now_ns: int | None = None) -> float:
        current = time.monotonic_ns() if now_ns is None else now_ns
        elapsed_ms = max(0, (current - self.started_ns) // 1_000_000)
        return max(0.0, (self.timeout_ms - elapsed_ms) / 1000.0)


@dataclass(frozen=True)
class GateRunResult:
    gate_id: str
    phase: str
    result: str
    result_reason: str
    returncode: int | None
    execution_ms: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "gate_id": self.gate_id,
            "phase": self.phase,
            "result": self.result,
            "result_reason": self.result_reason,
            "returncode": self.returncode,
            "execution_ms": self.execution_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
        }


def _validate_id(value: str, name: str) -> None:
    if _SAFE_ID.fullmatch(value) is None:
        raise GateRunError(f"{name} contains unsupported characters")


def _timeout_seconds(value: float, name: str) -> float:
    if isinstance(value, bool) or value <= 0 or value >= 60:
        raise GateRunError(f"{name} must be positive and below 60 seconds")
    return float(value)


def _secret_values(environment: Mapping[str, str], explicit: Sequence[str]) -> tuple[str, ...]:
    values = {
        value
        for name, value in environment.items()
        if value and _SECRET_NAME.search(name)
    }
    values.update(value for value in explicit if value)
    return tuple(sorted(values, key=lambda item: (-len(item), item)))


def _redact(value: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        value = value.replace(secret, "***")
    return value


def _read_tail(stream: object, limit: int) -> tuple[str, bool]:
    if limit <= 0:
        raise GateRunError("output limit must be positive")
    stream.seek(0, os.SEEK_END)  # type: ignore[attr-defined]
    size = stream.tell()  # type: ignore[attr-defined]
    truncated = size > limit
    stream.seek(max(0, size - limit))  # type: ignore[attr-defined]
    payload = stream.read()  # type: ignore[attr-defined]
    return payload.decode("utf-8", errors="replace"), truncated


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate(process: subprocess.Popen[bytes], grace_seconds: float) -> None:
    if os.name != "posix":
        process.terminate()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return

    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    stop_at = time.monotonic() + grace_seconds
    while time.monotonic() < stop_at and _group_exists(process_group):
        time.sleep(0.01)
    if _group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=max(0.1, grace_seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_gate_command(
    *,
    gate_id: str,
    phase: str,
    argv: Sequence[str],
    deadline: LaneDeadline,
    command_timeout_seconds: float,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    redact_values: Sequence[str] = (),
    output_limit_bytes: int = 65_536,
    termination_grace_seconds: float = 0.5,
) -> GateRunResult:
    _validate_id(gate_id, "gate_id")
    _validate_id(phase, "phase")
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise GateRunError("argv must contain non-empty strings")
    command_timeout = _timeout_seconds(command_timeout_seconds, "command timeout")
    if termination_grace_seconds <= 0:
        raise GateRunError("termination grace must be positive")

    remaining = min(deadline.remaining_seconds(), command_timeout)
    if remaining <= 0:
        return GateRunResult(
            gate_id,
            phase,
            "BUDGET_EXCEEDED",
            f"BUDGET_EXCEEDED:{gate_id}:{phase}",
            None,
            0,
            "",
            "",
            False,
            False,
        )

    environment = dict(os.environ if env is None else env)
    secrets = _secret_values(environment, redact_values)
    started_ns = time.monotonic_ns()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                tuple(argv),
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            elapsed = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
            return GateRunResult(
                gate_id,
                phase,
                "ENVIRONMENT_ERROR",
                f"ENVIRONMENT_ERROR:{gate_id}:{phase}:{type(exc).__name__}",
                None,
                elapsed,
                "",
                "",
                False,
                False,
            )

        timed_out = False
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate(process, termination_grace_seconds)

        execution_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
        stdout, stdout_truncated = _read_tail(stdout_file, output_limit_bytes)
        stderr, stderr_truncated = _read_tail(stderr_file, output_limit_bytes)
        stdout = _redact(stdout, secrets)
        stderr = _redact(stderr, secrets)

    if timed_out:
        result = "BUDGET_EXCEEDED"
        reason = f"BUDGET_EXCEEDED:{gate_id}:{phase}"
    elif process.returncode == 0:
        result = "PASS"
        reason = f"PASS:{gate_id}:{phase}"
    else:
        result = "FAIL"
        reason = f"FAIL:{gate_id}:{phase}:exit={process.returncode}"
    return GateRunResult(
        gate_id,
        phase,
        result,
        reason,
        process.returncode,
        execution_ms,
        stdout,
        stderr,
        stdout_truncated,
        stderr_truncated,
    )


def _gate_configuration(contract: SdlcContract, gate_id: str) -> tuple[float, float]:
    for gate in contract.data["gate"].values():
        if gate["id"] != gate_id:
            continue
        lane = contract.data["lanes"][gate["lane"]]
        lane_timeout = lane.get(
            "hard_timeout_seconds",
            lane.get("per_shard_hard_timeout_seconds"),
        )
        return float(gate["hard_timeout_seconds"]), float(lane_timeout)
    raise GateRunError(f"unknown gate id: {gate_id}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Newsroom gate command within its accepted budget")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--gate-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--output")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = arguments.command[1:] if arguments.command[:1] == ["--"] else arguments.command
    try:
        contract = load_contract(arguments.repo_root)
        command_timeout, lane_timeout = _gate_configuration(contract, arguments.gate_id)
        result = run_gate_command(
            gate_id=arguments.gate_id,
            phase=arguments.phase,
            argv=command,
            deadline=LaneDeadline.start(lane_timeout),
            command_timeout_seconds=command_timeout,
            cwd=arguments.repo_root,
        )
    except (ContractError, GateRunError, OSError) as exc:
        print(f"ENVIRONMENT_ERROR:{type(exc).__name__}", file=sys.stderr)
        return 3
    rendered = json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"
    if arguments.output:
        Path(arguments.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return {"PASS": 0, "FAIL": 1, "BUDGET_EXCEEDED": 2}.get(result.result, 3)


if __name__ == "__main__":
    raise SystemExit(main())
