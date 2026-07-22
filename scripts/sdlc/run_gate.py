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
import threading
import time
from typing import BinaryIO, Mapping, Sequence

from .contracts import ContractError, SdlcContract, load_contract


SCHEMA_VERSION = "newsroom.sdlc.gate-run.v1"
_SECRET_NAME = re.compile(r"(?:AUTH|CREDENTIAL|KEY|PASSWORD|SECRET|TOKEN)", re.IGNORECASE)
_SAFE_ID = re.compile(r"[A-Za-z0-9_.*-]{1,128}")
_MAX_OUTPUT_BYTES = 1_048_576
_SCHEDULER_MARGIN_SECONDS = 0.05


class GateRunError(ValueError):
    """Raised when a bounded gate invocation is invalid."""


@dataclass(frozen=True)
class LaneDeadline:
    started_ns: int
    timeout_ms: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.started_ns, bool)
            or not isinstance(self.started_ns, int)
            or self.started_ns < 0
        ):
            raise GateRunError("deadline start must be a nonnegative monotonic integer")
        if (
            isinstance(self.timeout_ms, bool)
            or not isinstance(self.timeout_ms, int)
            or not 0 < self.timeout_ms < 60_000
        ):
            raise GateRunError("lane timeout must be positive and below 60 seconds")

    @classmethod
    def start(cls, timeout_seconds: float) -> "LaneDeadline":
        timeout = _timeout_seconds(timeout_seconds, "lane timeout")
        return cls(time.monotonic_ns(), max(1, int(timeout * 1000)))

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


class _TailBuffer:
    def __init__(self, retained_bytes: int) -> None:
        self._retained_bytes = retained_bytes
        self._data = bytearray()
        self.total_bytes = 0

    def feed(self, payload: bytes) -> None:
        self.total_bytes += len(payload)
        if len(payload) >= self._retained_bytes:
            self._data[:] = payload[-self._retained_bytes :]
            return
        self._data.extend(payload)
        overflow = len(self._data) - self._retained_bytes
        if overflow > 0:
            del self._data[:overflow]

    def render(
        self,
        *,
        output_limit: int,
        secrets: Sequence[str],
        incomplete: bool,
    ) -> tuple[str, bool]:
        text = bytes(self._data).decode("utf-8", errors="replace")
        for secret in secrets:
            text = text.replace(secret, "***")
        encoded = text.encode("utf-8")
        if len(encoded) > output_limit:
            encoded = encoded[-output_limit:]
            text = encoded.decode("utf-8", errors="replace")
            while len(text.encode("utf-8")) > output_limit:
                text = text[1:]
        return text, incomplete or self.total_bytes > output_limit


def _validate_id(value: str, name: str) -> None:
    if _SAFE_ID.fullmatch(value) is None:
        raise GateRunError(f"{name} contains unsupported characters")


def _timeout_seconds(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateRunError(f"{name} must be numeric")
    timeout = float(value)
    if timeout <= 0 or timeout >= 60:
        raise GateRunError(f"{name} must be positive and below 60 seconds")
    return timeout


def _secret_values(
    environment: Mapping[str, str], explicit: Sequence[str]
) -> tuple[str, ...]:
    if any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in environment.items()
    ):
        raise GateRunError("environment names and values must be strings")
    if any(not isinstance(value, str) for value in explicit):
        raise GateRunError("redaction values must be strings")
    values = {
        value
        for name, value in environment.items()
        if value and _SECRET_NAME.search(name)
    }
    values.update(value for value in explicit if value)
    return tuple(sorted(values, key=lambda item: (-len(item), item)))


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_group_gone(
    process_group: int,
    timeout_seconds: float,
    *,
    leader: subprocess.Popen[bytes] | None = None,
) -> bool:
    stop_at = time.monotonic() + timeout_seconds
    while time.monotonic() < stop_at:
        if leader is not None:
            leader.poll()
        if not _group_exists(process_group):
            return True
        time.sleep(0.01)
    if leader is not None:
        leader.poll()
    return not _group_exists(process_group)


def _terminate_group(process: subprocess.Popen[bytes], grace_seconds: float) -> None:
    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if not _wait_group_gone(process_group, grace_seconds, leader=process):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=max(0.05, grace_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _drain(stream: BinaryIO, buffer: _TailBuffer, errors: list[str]) -> None:
    try:
        while payload := stream.read(65_536):
            buffer.feed(payload)
    except (OSError, ValueError) as exc:
        errors.append(type(exc).__name__)
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _budget_result(gate_id: str, phase: str) -> GateRunResult:
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


def _run_gate_command(
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
    if os.name != "posix":
        raise GateRunError("bounded process-group execution requires POSIX")
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise GateRunError("argv must contain non-empty strings")
    command_timeout = _timeout_seconds(command_timeout_seconds, "command timeout")
    grace = _timeout_seconds(termination_grace_seconds, "termination grace")
    if grace > 5:
        raise GateRunError("termination grace must not exceed five seconds")
    if isinstance(output_limit_bytes, bool) or not isinstance(output_limit_bytes, int):
        raise GateRunError("output limit must be an integer")
    if not 0 < output_limit_bytes <= _MAX_OUTPUT_BYTES:
        raise GateRunError("output limit must be between 1 and 1048576 bytes")

    budget = min(deadline.remaining_seconds(), command_timeout)
    margin = min(_SCHEDULER_MARGIN_SECONDS, budget / 10)
    if budget <= grace + margin:
        return _budget_result(gate_id, phase)
    run_timeout = budget - grace - margin

    environment = dict(os.environ if env is None else env)
    secrets = _secret_values(environment, redact_values)
    overlap = max((len(secret.encode("utf-8")) for secret in secrets), default=0)
    stdout_buffer = _TailBuffer(output_limit_bytes + overlap)
    stderr_buffer = _TailBuffer(output_limit_bytes + overlap)
    capture_errors: list[str] = []
    started_ns = time.monotonic_ns()
    try:
        process = subprocess.Popen(
            tuple(argv),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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

    assert process.stdout is not None and process.stderr is not None
    readers = (
        threading.Thread(
            target=_drain,
            args=(process.stdout, stdout_buffer, capture_errors),
            daemon=True,
        ),
        threading.Thread(
            target=_drain,
            args=(process.stderr, stderr_buffer, capture_errors),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    timed_out = False
    background_process = False
    try:
        process.wait(timeout=run_timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_group(process, grace)
    else:
        if not _wait_group_gone(process.pid, min(0.05, grace / 2)):
            background_process = True
            _terminate_group(process, grace)

    cleanup_stop = time.monotonic() + max(
        0.0,
        min(grace + margin, deadline.remaining_seconds()),
    )
    for reader in readers:
        reader.join(timeout=max(0.0, cleanup_stop - time.monotonic()))
    capture_incomplete = any(reader.is_alive() for reader in readers)
    execution_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
    if deadline.remaining_seconds() <= 0 or execution_ms > int(budget * 1000):
        timed_out = True
    stdout, stdout_truncated = stdout_buffer.render(
        output_limit=output_limit_bytes,
        secrets=secrets,
        incomplete=capture_incomplete,
    )
    stderr, stderr_truncated = stderr_buffer.render(
        output_limit=output_limit_bytes,
        secrets=secrets,
        incomplete=capture_incomplete,
    )

    if timed_out:
        result = "BUDGET_EXCEEDED"
        reason = f"BUDGET_EXCEEDED:{gate_id}:{phase}"
    elif capture_errors or capture_incomplete:
        result = "ENVIRONMENT_ERROR"
        reason = f"ENVIRONMENT_ERROR:{gate_id}:{phase}:output_capture"
    elif background_process:
        result = "UNAUTHORISED_EFFECT"
        reason = f"UNAUTHORISED_EFFECT:{gate_id}:{phase}:background_process"
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


def start_lane_deadline(contract: SdlcContract, gate_id: str) -> LaneDeadline:
    _, lane_timeout = _gate_configuration(contract, gate_id)
    return LaneDeadline.start(lane_timeout)


def run_configured_gate(
    *,
    contract: SdlcContract,
    gate_id: str,
    phase: str,
    argv: Sequence[str],
    deadline: LaneDeadline | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    redact_values: Sequence[str] = (),
    output_limit_bytes: int = 65_536,
    termination_grace_seconds: float = 0.5,
) -> GateRunResult:
    command_timeout, lane_timeout = _gate_configuration(contract, gate_id)
    active_deadline = deadline or LaneDeadline.start(lane_timeout)
    if active_deadline.timeout_ms > int(lane_timeout * 1000):
        raise GateRunError("deadline exceeds the accepted lane timeout")
    return _run_gate_command(
        gate_id=gate_id,
        phase=phase,
        argv=argv,
        deadline=active_deadline,
        command_timeout_seconds=command_timeout,
        cwd=cwd,
        env=env,
        redact_values=redact_values,
        output_limit_bytes=output_limit_bytes,
        termination_grace_seconds=termination_grace_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one Newsroom gate command within its accepted budget"
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--gate-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--output")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = (
        arguments.command[1:]
        if arguments.command[:1] == ["--"]
        else arguments.command
    )
    try:
        contract = load_contract(arguments.repo_root)
        result = run_configured_gate(
            contract=contract,
            gate_id=arguments.gate_id,
            phase=arguments.phase,
            argv=command,
            cwd=arguments.repo_root,
        )
    except (ContractError, GateRunError, OSError) as exc:
        print(f"ENVIRONMENT_ERROR:{type(exc).__name__}", file=sys.stderr)
        return 3
    rendered = json.dumps(
        result.as_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    if arguments.output:
        Path(arguments.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return {"PASS": 0, "FAIL": 1, "BUDGET_EXCEEDED": 2}.get(result.result, 3)


if __name__ == "__main__":
    raise SystemExit(main())
