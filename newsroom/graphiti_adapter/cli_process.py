"""Shared bounded CLI execution and secret-free timeout diagnostics."""

from __future__ import annotations

import asyncio
import hashlib
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from newsroom.authority.canonical import validate_sha256_digest
from newsroom.authority.types import UtcTimestamp

CLI_TIMEOUT_DIAGNOSTIC_SCHEMA_VERSION = "newsroom.graphiti-timeout-diagnostic.v1"
_PROCESS_CLEANUP_TIMEOUT_SECONDS = 0.5
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
_TIMEOUT_DIAGNOSTIC_VOCABULARY = {
    "boundary": frozenset(
        {
            "CALLER_CANCELLATION",
            "CLEANUP_DEADLINE",
            "CONTROLLER_DEADLINE",
            "EXTRACTION_DEADLINE",
            "UNOBSERVED_TIMEOUT_BOUNDARY",
        }
    ),
    "phase": frozenset(
        {
            "CLI_TRANSPORT",
            "CONNECTION_CLEANUP",
            "CREDENTIAL_PROBE",
            "EXTRACTION",
            "FALLBACK_TRANSPORT",
            "PREDISPATCH_HELP",
            "PREDISPATCH_SETUP",
            "PREDISPATCH_VERSION",
            "PRIMARY_TRANSPORT",
            "ROLLBACK_CLEANUP",
        }
    ),
    "cause": frozenset(
        {
            "CALLER_CANCELLED",
            "CLEANUP_DEADLINE_EXPIRED",
            "CONFIGURED_TIMEOUT_EXPIRED",
            "EXTRACTION_DEADLINE_EXPIRED",
            "TIMEOUT_ORIGIN_UNOBSERVED",
        }
    ),
    "last_progress": frozenset(
        {
            "CANCELLED",
            "COMPLETE",
            "CONNECTION_CLOSE_INCOMPLETE",
            "CREDENTIAL_PROBE_STARTED",
            "DISPATCH_FENCE_REFUSED",
            "DISPATCH_STARTED",
            "EXECUTABLE_NOT_FOUND",
            "FAILED",
            "MALFORMED_OUTPUT",
            "NO_OUTPUT_OBSERVED",
            "NO_PROVIDER_INVOCATION",
            "OUTPUT_LIMIT_EXCEEDED",
            "OUTPUT_OBSERVED",
            "PREDISPATCH",
            "PREDISPATCH_REFUSED",
            "ROLLBACK_INCOMPLETE",
            "TIMEOUT",
            "UNOBSERVED",
        }
    ),
    "termination": frozenset(
        {
            "NO_PROVIDER_TASK",
            "PROCESS_ALREADY_EXITED",
            "PROCESS_CLEANUP_TIMEOUT",
            "PROCESS_EXIT_RACE",
            "PROCESS_KILLED",
            "TASK_CANCELLED",
            "UNOBSERVED",
        }
    ),
    "process": frozenset({"CLI_CHILD", "CURSOR_CREDENTIAL_HELPER"}),
}
CLI_QUALIFICATION_SCHEMA_VERSION = "newsroom.graphiti-cli-qualification.v1"
_CLI_QUALIFICATION_DIGEST_FIELDS = frozenset(
    {
        "authentication_bridge_digest",
        "authentication_probe_digest",
        "command_surface_digest",
        "command_template_digest",
        "control_semantics_digest",
        "credential_state_digest",
        "help_digest",
        "launcher_digest",
        "package_digest",
        "version_digest",
    }
)
_CLI_QUALIFICATION_FIELDS = (
    frozenset({"schema_version", "transport", "stdout_limit_bytes"})
    | _CLI_QUALIFICATION_DIGEST_FIELDS
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


def _unprivileged_child_environment() -> dict[str, str]:
    """Resolve the control-plane helper lazily to keep imports acyclic."""

    from newsroom.control_plane.child_environment import (
        unprivileged_child_environment,
    )

    return unprivileged_child_environment()


def _signal_process(
    process: subprocess.Popen[bytes] | asyncio.subprocess.Process,
    *,
    process_group_id: int | None,
    already_exited: bool,
) -> str:
    """Signal an isolated CLI process group, with a fallback for test doubles."""

    if already_exited and process_group_id is None:
        return "PROCESS_ALREADY_EXITED"
    try:
        if process_group_id is None:
            process.kill()
        else:
            os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return "PROCESS_ALREADY_EXITED" if already_exited else "PROCESS_EXIT_RACE"
    return "PROCESS_KILLED"


def stop_process(
    process: subprocess.Popen[bytes],
    *,
    process_group_id: int | None = None,
    cleanup_timeout: float = _PROCESS_CLEANUP_TIMEOUT_SECONDS,
) -> str:
    """Stop and reap one isolated CLI process group within a hard deadline."""

    termination = _signal_process(
        process,
        process_group_id=process_group_id,
        already_exited=process.poll() is not None,
    )
    try:
        process.wait(timeout=cleanup_timeout)
    except subprocess.TimeoutExpired:
        return "PROCESS_CLEANUP_TIMEOUT"
    return termination


async def stop_process_async(
    process: asyncio.subprocess.Process,
    *,
    process_group_id: int | None = None,
    readers: tuple[asyncio.Task[None], ...] = (),
    cleanup_timeout: float = _PROCESS_CLEANUP_TIMEOUT_SECONDS,
) -> str:
    """Stop, drain and reap one isolated CLI process group within a deadline."""

    async def drain_and_wait() -> None:
        communicate = getattr(process, "communicate", None)
        if callable(communicate):
            await communicate()
        else:
            # Minimal test doubles and non-pipe process adapters expose wait only.
            await process.wait()

    loop = asyncio.get_running_loop()
    cleanup_deadline = loop.time() + cleanup_timeout
    termination = _signal_process(
        process,
        process_group_id=process_group_id,
        already_exited=process.returncode is not None,
    )
    for reader in readers:
        if not reader.done():
            reader.cancel()
    if readers:
        done, pending = await asyncio.wait(
            readers,
            timeout=max(0.0, cleanup_deadline - loop.time()),
        )
        for reader in done:
            try:
                reader.result()
            except BaseException:
                pass
        if pending:
            return "PROCESS_CLEANUP_TIMEOUT"

    # asyncio subprocesses can withhold wait() completion while unread pipe
    # buffers remain. communicate() drains both pipes before reaping. Use
    # asyncio.wait rather than wait_for so a cancellation-resistant awaitable
    # cannot extend the controller-owned cleanup deadline.
    cleanup_task = asyncio.create_task(drain_and_wait())
    done, _pending = await asyncio.wait(
        (cleanup_task,),
        timeout=max(0.0, cleanup_deadline - loop.time()),
    )
    if cleanup_task not in done:
        cleanup_task.cancel()
        cleanup_task.add_done_callback(_consume_task_result)
        return "PROCESS_CLEANUP_TIMEOUT"
    try:
        cleanup_task.result()
    except BaseException:
        return "PROCESS_CLEANUP_TIMEOUT"
    return termination


def _consume_task_result(task: asyncio.Task[object]) -> None:
    """Consume a late cleanup result without retaining payload or warnings."""

    try:
        task.result()
    except BaseException:
        pass


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
    return _validated_timeout_diagnostic(evidence)


def _validated_timeout_diagnostic(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Graphiti timeout diagnostic must be an object")
    item = dict(value)
    fields = frozenset(item)
    allowed_fields = (
        _TIMEOUT_DIAGNOSTIC_REQUIRED_FIELDS | _TIMEOUT_DIAGNOSTIC_OPTIONAL_FIELDS
    )
    if not _TIMEOUT_DIAGNOSTIC_REQUIRED_FIELDS.issubset(fields) or not fields.issubset(
        allowed_fields
    ):
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
        if item[field] not in _TIMEOUT_DIAGNOSTIC_VOCABULARY[field]:
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
            raise ValueError("Graphiti timeout diagnostic deadline is invalid") from exc
        if parsed_deadline.to_text() != deadline_at:
            raise ValueError(
                "Graphiti timeout diagnostic deadline is not canonical UTC"
            )
    process = item.get("process")
    if process is not None and process not in _TIMEOUT_DIAGNOSTIC_VOCABULARY["process"]:
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
    return item


def validated_timeout_diagnostics(value: object) -> list[dict[str, object]]:
    """Validate secret-free timeout evidence before durable propagation."""

    if not isinstance(value, list) or not value:
        raise ValueError("Graphiti timeout diagnostics must be a non-empty list")
    return [_validated_timeout_diagnostic(item) for item in value]


def retained_cli_qualification(value: object) -> dict[str, object]:
    """Reduce a successful qualification to fixed tokens and digests."""

    if not isinstance(value, Mapping):
        raise ValueError("Graphiti CLI qualification must be an object")
    retained: dict[str, object] = {
        "schema_version": CLI_QUALIFICATION_SCHEMA_VERSION,
        "transport": "CURSOR_AGENT_CLI",
        "stdout_limit_bytes": value.get("stdout_limit_bytes"),
    }
    retained.update(
        {field: value.get(field) for field in _CLI_QUALIFICATION_DIGEST_FIELDS}
    )
    return validated_transport_qualification(retained)


def validated_transport_qualification(value: object) -> dict[str, object]:
    """Validate the only qualification forms permitted in durable receipts."""

    if not isinstance(value, dict):
        raise ValueError("Graphiti transport qualification must be an object")
    retained = dict(value)
    if frozenset(retained) == frozenset({"timeout_diagnostic"}):
        return {
            "timeout_diagnostic": validated_timeout_diagnostics(
                [retained["timeout_diagnostic"]]
            )[0]
        }
    if frozenset(retained) != _CLI_QUALIFICATION_FIELDS:
        raise ValueError("Graphiti transport qualification fields are invalid")
    if (
        retained["schema_version"] != CLI_QUALIFICATION_SCHEMA_VERSION
        or retained["transport"] != "CURSOR_AGENT_CLI"
    ):
        raise ValueError("Graphiti transport qualification identity is invalid")
    stdout_limit = retained["stdout_limit_bytes"]
    if (
        isinstance(stdout_limit, bool)
        or not isinstance(stdout_limit, int)
        or stdout_limit <= 0
    ):
        raise ValueError("Graphiti transport qualification output limit is invalid")
    for field in _CLI_QUALIFICATION_DIGEST_FIELDS:
        digest = retained[field]
        if digest == "UNOBSERVED" and field in {
            "authentication_bridge_digest",
            "authentication_probe_digest",
            "credential_state_digest",
        }:
            continue
        if not isinstance(digest, str):
            raise ValueError(f"Graphiti transport qualification {field} is invalid")
        try:
            validate_sha256_digest(digest, field=field)
        except ValueError as exc:
            raise ValueError(
                f"Graphiti transport qualification {field} is invalid"
            ) from exc
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
            process="CLI_CHILD",
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
        env=dict(environment or _unprivileged_child_environment()),
        start_new_session=True,
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
    cleanup_attempted = False

    def stop_cli_group() -> str:
        nonlocal cleanup_attempted
        cleanup_attempted = True
        return stop_process(process, process_group_id=process.pid)

    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                termination = stop_cli_group()
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
                    stop_cli_group()
                    raise CliOutputBoundExceeded(
                        f"{name} Graphiti LLM exceeded output byte limit"
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            termination = stop_cli_group()
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
            termination = stop_cli_group()
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
        # The direct child may have exited while a descendant still owns the
        # inherited pipes or remains alive in the isolated session.
        if not cleanup_attempted:
            stop_cli_group()
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
        env=dict(environment or _unprivileged_child_environment()),
        start_new_session=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    retained = 0

    async def collect(stream: asyncio.StreamReader, *, destination: bytearray) -> None:
        nonlocal retained
        while True:
            chunk = await stream.read(65_536)
            if not chunk:
                return
            retainable = max(0, max_output_bytes + 1 - retained)
            retained_chunk = chunk[:retainable]
            destination.extend(retained_chunk)
            retained += len(retained_chunk)
            if len(retained_chunk) != len(chunk) or retained > max_output_bytes:
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
    cleanup_attempted = False

    async def stop_collectors_and_process() -> str:
        nonlocal cleanup_attempted
        cleanup_attempted = True
        process_group_id = getattr(process, "pid", None)
        return await stop_process_async(
            process,
            process_group_id=(
                process_group_id if isinstance(process_group_id, int) else None
            ),
            readers=collectors,
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
        termination = await stop_collectors_and_process()
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
        await stop_collectors_and_process()
        raise
    except BaseException:
        await stop_collectors_and_process()
        raise
    finally:
        if not cleanup_attempted:
            for collector in collectors:
                if not collector.done():
                    collector.cancel()
            done, _pending = await asyncio.wait(
                collectors,
                timeout=_PROCESS_CLEANUP_TIMEOUT_SECONDS,
            )
            for collector in done:
                try:
                    collector.result()
                except BaseException:
                    pass
    return CliProcessOutput(
        returncode=returncode,
        stdout=_decode_output(bytes(outputs["stdout"]), name=name),
        stderr=_decode_output(bytes(outputs["stderr"]), name=name),
    )


__all__ = [
    "CLI_QUALIFICATION_SCHEMA_VERSION",
    "CLI_TIMEOUT_DIAGNOSTIC_SCHEMA_VERSION",
    "CliOutputBoundExceeded",
    "CliOutputDecodeError",
    "CliProcessOutput",
    "CliTransportTimeout",
    "run_bounded_process",
    "run_bounded_process_async",
    "retained_cli_qualification",
    "stop_process",
    "stop_process_async",
    "timeout_deadline_after",
    "timeout_diagnostic",
    "validated_timeout_diagnostics",
    "validated_transport_qualification",
]
