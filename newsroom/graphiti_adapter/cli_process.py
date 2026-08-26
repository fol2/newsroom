"""Shared bounded CLI execution and secret-free timeout diagnostics."""

from __future__ import annotations

import asyncio
import hashlib
import os
import selectors
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from newsroom.authority.canonical import validate_sha256_digest
from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane.child_environment import unprivileged_child_environment

CLI_TIMEOUT_DIAGNOSTIC_SCHEMA_VERSION = "newsroom.graphiti-timeout-diagnostic.v1"
_TIMEOUT_DIAGNOSTIC_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "boundary",
        "phase",
        "cause",
        "provider_cause",
        "configured_timeout_ms",
        "elapsed_ms",
        "deadline_at",
        "last_progress",
        "termination",
    }
)
_TIMEOUT_DIAGNOSTIC_OUTPUT_FIELDS = frozenset(
    {
        "stdout_bytes",
        "stderr_bytes",
        "stdout_digest",
        "stderr_digest",
    }
)
_TIMEOUT_DIAGNOSTIC_OPTIONAL_FIELDS = (
    frozenset({"process"}) | _TIMEOUT_DIAGNOSTIC_OUTPUT_FIELDS
)


class CliOutputDecodeError(RuntimeError):
    """A dispatched subscription CLI returned non-UTF-8 output."""


class CliOutputBoundExceeded(RuntimeError):
    """A CLI exceeded its controller-owned output byte ceiling."""


class CliTransportTimeout(TimeoutError):
    """A controller deadline terminated a CLI with secret-free diagnostics."""

    def __init__(self, message: str, *, evidence: Mapping[str, object]) -> None:
        super().__init__(message)
        self.evidence = dict(evidence)


@dataclass(frozen=True, slots=True)
class CliProcessOutput:
    returncode: int
    stdout: str
    stderr: str


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _decode_output(value: bytes, *, name: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        raise CliOutputDecodeError(
            f"{name} Graphiti LLM returned malformed UTF-8"
        ) from None


def _require_execution_bounds(*, timeout: float, max_output_bytes: int) -> None:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("CLI timeout must be positive")
    if (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes <= 0
    ):
        raise ValueError("CLI max_output_bytes must be positive")


def stop_process(process: subprocess.Popen[bytes]) -> str:
    """Stop one child and report the observed termination race truthfully."""

    if process.poll() is not None:
        process.wait()
        return "PROCESS_ALREADY_EXITED"
    try:
        process.kill()
    except ProcessLookupError:
        termination = "PROCESS_EXIT_RACE"
    else:
        termination = "PROCESS_KILLED"
    process.wait()
    return termination


async def stop_process_async(process: asyncio.subprocess.Process) -> str:
    """Async equivalent of :func:`stop_process`."""

    if process.returncode is not None:
        await process.wait()
        return "PROCESS_ALREADY_EXITED"
    try:
        process.kill()
    except ProcessLookupError:
        termination = "PROCESS_EXIT_RACE"
    else:
        termination = "PROCESS_KILLED"
    await process.wait()
    return termination


def timeout_deadline_after(timeout_seconds: float) -> str:
    """Return a canonical UTC deadline for secret-free timeout evidence."""

    deadline = datetime.now(tz=UTC) + timedelta(seconds=timeout_seconds)
    return deadline.isoformat(timespec="microseconds").replace("+00:00", "Z")


def timeout_diagnostic(
    *,
    boundary: str,
    phase: str,
    cause: str,
    configured_timeout_ms: int,
    elapsed_ms: int,
    deadline_at: str | None,
    last_progress: str,
    termination: str,
    process: str | None = None,
    stdout: bytes | None = None,
    stderr: bytes | None = None,
) -> dict[str, object]:
    """Build one causal timeout record without retaining provider content."""

    evidence: dict[str, object] = {
        "schema_version": CLI_TIMEOUT_DIAGNOSTIC_SCHEMA_VERSION,
        "boundary": boundary,
        "phase": phase,
        "cause": cause,
        "provider_cause": "UNOBSERVED",
        "configured_timeout_ms": configured_timeout_ms,
        "elapsed_ms": elapsed_ms,
        "deadline_at": deadline_at,
        "last_progress": last_progress,
        "termination": termination,
    }
    if process is not None:
        evidence["process"] = process
    if stdout is not None and stderr is not None:
        evidence.update(
            {
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
                "stdout_digest": _sha256_bytes(stdout),
                "stderr_digest": _sha256_bytes(stderr),
            }
        )
    return evidence


def validated_timeout_diagnostics(value: object) -> list[dict[str, object]]:
    """Validate secret-free timeout evidence before durable propagation."""

    if not isinstance(value, list) or not value:
        raise ValueError("Graphiti timeout diagnostics must be a non-empty list")
    retained: list[dict[str, object]] = []
    allowed_fields = (
        _TIMEOUT_DIAGNOSTIC_REQUIRED_FIELDS | _TIMEOUT_DIAGNOSTIC_OPTIONAL_FIELDS
    )
    for raw_item in value:
        if not isinstance(raw_item, dict):
            raise ValueError("Graphiti timeout diagnostic must be an object")
        item = dict(raw_item)
        fields = frozenset(item)
        if not _TIMEOUT_DIAGNOSTIC_REQUIRED_FIELDS.issubset(
            fields
        ) or not fields.issubset(allowed_fields):
            raise ValueError("Graphiti timeout diagnostic fields are invalid")
        if item["schema_version"] != CLI_TIMEOUT_DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("Graphiti timeout diagnostic schema is invalid")
        for field in (
            "boundary",
            "phase",
            "cause",
            "last_progress",
            "termination",
        ):
            field_value = item[field]
            if (
                not isinstance(field_value, str)
                or not field_value
                or len(field_value) > 128
            ):
                raise ValueError(f"Graphiti timeout diagnostic {field} is invalid")
        if item["provider_cause"] != "UNOBSERVED":
            raise ValueError("Graphiti timeout provider cause must remain unobserved")
        for field in ("configured_timeout_ms", "elapsed_ms"):
            field_value = item[field]
            if (
                isinstance(field_value, bool)
                or not isinstance(field_value, int)
                or field_value < 0
            ):
                raise ValueError(f"Graphiti timeout diagnostic {field} is invalid")
        deadline_at = item["deadline_at"]
        if deadline_at is not None:
            try:
                parsed_deadline = UtcTimestamp.parse(deadline_at)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Graphiti timeout diagnostic deadline is invalid"
                ) from exc
            if parsed_deadline.to_text() != deadline_at:
                raise ValueError(
                    "Graphiti timeout diagnostic deadline is not canonical UTC"
                )
        process = item.get("process")
        if process is not None and (
            not isinstance(process, str) or not process or len(process) > 255
        ):
            raise ValueError("Graphiti timeout diagnostic process is invalid")
        present_output_fields = _TIMEOUT_DIAGNOSTIC_OUTPUT_FIELDS.intersection(fields)
        if (
            present_output_fields
            and present_output_fields != _TIMEOUT_DIAGNOSTIC_OUTPUT_FIELDS
        ):
            raise ValueError("Graphiti timeout output evidence is incomplete")
        if present_output_fields:
            for field in ("stdout_bytes", "stderr_bytes"):
                field_value = item[field]
                if (
                    isinstance(field_value, bool)
                    or not isinstance(field_value, int)
                    or field_value < 0
                ):
                    raise ValueError(f"Graphiti timeout diagnostic {field} is invalid")
            for field in ("stdout_digest", "stderr_digest"):
                digest = item[field]
                if not isinstance(digest, str):
                    raise ValueError(f"Graphiti timeout diagnostic {field} is invalid")
                try:
                    validate_sha256_digest(digest, field=field)
                except ValueError as exc:
                    raise ValueError(
                        f"Graphiti timeout diagnostic {field} is invalid"
                    ) from exc
        retained.append(item)
    return retained


def _transport_timeout(
    *,
    name: str,
    phase: str,
    timeout: float,
    elapsed: float,
    deadline_at: str,
    stdout: bytes,
    stderr: bytes,
    termination: str,
) -> CliTransportTimeout:
    return CliTransportTimeout(
        f"{name} Graphiti LLM timed out",
        evidence=timeout_diagnostic(
            boundary="CONTROLLER_DEADLINE",
            phase=phase,
            cause="CONFIGURED_TIMEOUT_EXPIRED",
            configured_timeout_ms=round(timeout * 1_000),
            elapsed_ms=round(elapsed * 1_000),
            deadline_at=deadline_at,
            last_progress=(
                "OUTPUT_OBSERVED" if stdout or stderr else "NO_OUTPUT_OBSERVED"
            ),
            termination=termination,
            process=name,
            stdout=stdout,
            stderr=stderr,
        ),
    )


def run_bounded_process(
    command: tuple[str, ...],
    *,
    timeout: float,
    max_output_bytes: int,
    cwd: str | None,
    environment: Mapping[str, str] | None,
    phase: str = "CLI_TRANSPORT",
) -> CliProcessOutput:
    """Run one CLI under an exact deadline and aggregate output ceiling."""

    _require_execution_bounds(
        timeout=timeout,
        max_output_bytes=max_output_bytes,
    )
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
    started = time.monotonic()
    deadline = started + timeout
    deadline_at = timeout_deadline_after(timeout)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                termination = stop_process(process)
                raise _transport_timeout(
                    name=name,
                    phase=phase,
                    timeout=timeout,
                    elapsed=time.monotonic() - started,
                    deadline_at=deadline_at,
                    stdout=bytes(stdout_output),
                    stderr=bytes(stderr_output),
                    termination=termination,
                )
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
                    stop_process(process)
                    raise CliOutputBoundExceeded(
                        f"{name} Graphiti LLM exceeded output byte limit"
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            termination = stop_process(process)
            raise _transport_timeout(
                name=name,
                phase=phase,
                timeout=timeout,
                elapsed=time.monotonic() - started,
                deadline_at=deadline_at,
                stdout=bytes(stdout_output),
                stderr=bytes(stderr_output),
                termination=termination,
            )
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            termination = stop_process(process)
            raise _transport_timeout(
                name=name,
                phase=phase,
                timeout=timeout,
                elapsed=time.monotonic() - started,
                deadline_at=deadline_at,
                stdout=bytes(stdout_output),
                stderr=bytes(stderr_output),
                termination=termination,
            ) from None
    except BaseException:
        if process.poll() is None:
            stop_process(process)
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return CliProcessOutput(
        returncode=int(process.returncode),
        stdout=_decode_output(bytes(stdout_output), name=name),
        stderr=_decode_output(bytes(stderr_output), name=name),
    )


async def run_bounded_process_async(
    command: tuple[str, ...],
    *,
    timeout: float,
    max_output_bytes: int,
    cwd: str | None,
    environment: Mapping[str, str] | None,
    phase: str = "CLI_TRANSPORT",
) -> CliProcessOutput:
    """Async equivalent of :func:`run_bounded_process`."""

    _require_execution_bounds(
        timeout=timeout,
        max_output_bytes=max_output_bytes,
    )
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

    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + timeout
    deadline_at = timeout_deadline_after(timeout)
    collectors = (
        asyncio.create_task(collect(process.stdout, destination=outputs["stdout"])),
        asyncio.create_task(collect(process.stderr, destination=outputs["stderr"])),
    )
    try:
        await asyncio.wait_for(
            asyncio.gather(*collectors),
            timeout=timeout,
        )
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError
        returncode = await asyncio.wait_for(process.wait(), timeout=remaining)
    except TimeoutError:
        termination = await stop_process_async(process)
        raise _transport_timeout(
            name=name,
            phase=phase,
            timeout=timeout,
            elapsed=loop.time() - started,
            deadline_at=deadline_at,
            stdout=bytes(outputs["stdout"]),
            stderr=bytes(outputs["stderr"]),
            termination=termination,
        ) from None
    except asyncio.CancelledError:
        await stop_process_async(process)
        raise
    except BaseException:
        await stop_process_async(process)
        raise
    finally:
        for collector in collectors:
            if not collector.done():
                collector.cancel()
        await asyncio.gather(*collectors, return_exceptions=True)
    return CliProcessOutput(
        returncode=returncode,
        stdout=_decode_output(bytes(outputs["stdout"]), name=name),
        stderr=_decode_output(bytes(outputs["stderr"]), name=name),
    )


__all__ = [
    "CLI_TIMEOUT_DIAGNOSTIC_SCHEMA_VERSION",
    "CliOutputBoundExceeded",
    "CliOutputDecodeError",
    "CliProcessOutput",
    "CliTransportTimeout",
    "run_bounded_process",
    "run_bounded_process_async",
    "stop_process",
    "stop_process_async",
    "timeout_deadline_after",
    "timeout_diagnostic",
    "validated_timeout_diagnostics",
]
