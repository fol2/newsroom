"""Subscription CLI chat client used by Graphiti EVALUATION execution."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from newsroom.control_plane.child_environment import unprivileged_child_environment
from newsroom.control_plane.graphiti_fallback_policy import (
    FallbackEligibility,
    classify_graphiti_fallback,
)
from newsroom.graphiti_adapter.cursor_transport import (
    CURSOR_AGENT_BIN,
    QUALIFIED_CURSOR_AGENT_VERSION,
    CliOutputBoundExceeded,
    CliOutputDecodeError,
    CliPredispatchRefusal,
    CliTransportTimeout,
    CursorCliQualification,
    cursor_stdout_limit,
    run_cursor_transport,
    run_cursor_transport_async,
    stop_process_async,
    timeout_deadline_after,
    timeout_diagnostic,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    CURSOR_AGENT_MODEL_ID,
    GROK_CHAT_MODEL_ID,
    GROK_CHAT_REASONING,
    GRAPHITI_EXTRACTION_TIMEOUT_MS,
    GRAPHITI_MAX_CLEANUP_TIMEOUT_MS,
)
from newsroom.graphiti_adapter.usage_meter import (
    cursor_cli_usage,
    grok_cli_usage,
    no_provider_call_cli_usage,
    unreported_cli_usage,
)

GROK_BIN = os.environ.get("NEWSROOM_GROK_BIN", "/Users/jamesto/.grok/bin/grok")
CLI_CALL_TIMEOUT_SECONDS = (
    GRAPHITI_EXTRACTION_TIMEOUT_MS - GRAPHITI_MAX_CLEANUP_TIMEOUT_MS
) // 1_000


@dataclass(frozen=True, slots=True)
class CliExecution:
    text: str
    usage: dict[str, object]
    transport_qualification: dict[str, object] | None = None


CliOutput = str | CliExecution


class CliRunner(Protocol):
    def __call__(
        self,
        prompt: str,
        *,
        max_tokens: int,
        dispatch_started: Callable[[], None] | None = None,
    ) -> CliOutput: ...


class GrokRunner(Protocol):
    def __call__(
        self,
        prompt: str,
        schema: str | None,
        *,
        max_tokens: int,
        dispatch_started: Callable[[], None] | None = None,
    ) -> CliOutput: ...


class AsyncCliRunner(Protocol):
    async def __call__(
        self,
        prompt: str,
        *,
        max_tokens: int,
        dispatch_started: Callable[[], None] | None = None,
    ) -> CliOutput: ...


class AsyncGrokRunner(Protocol):
    async def __call__(
        self,
        prompt: str,
        schema: str | None,
        *,
        max_tokens: int,
        dispatch_started: Callable[[], None] | None = None,
    ) -> CliOutput: ...


class CliResponseError(RuntimeError):
    """Both subscription CLI responses failed the Graphiti JSON contract."""


class CliDispatchMarkerError(RuntimeError):
    """Durable dispatch observation failed before provider I/O."""


class GraphitiCliClient(Protocol):
    invocations: list[dict[str, object]]

    async def _generate_response(
        self,
        messages: list[Any],
        response_model: type[Any] | None = None,
        max_tokens: int = 0,
        model_size: object = None,
    ) -> dict[str, Any]: ...


class CliInvocationObserver(Protocol):
    def before_cli_invocation(
        self,
        *,
        provider: str,
        model: str,
        prompt: str,
        schema: str | None,
        semantic_request_class: str,
        max_tokens: int,
    ) -> object: ...

    def transport_dispatch_started(self, token: object) -> None: ...

    def after_cli_invocation(
        self,
        token: object,
        *,
        outcome: str,
        usage: dict[str, object],
    ) -> Mapping[str, str] | None: ...


def extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Graphiti CLI returned no JSON object")
    return raw[start : end + 1]


def run_cli(
    command: tuple[str, ...],
    *,
    timeout: float,
    cwd: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> str:
    name = os.path.basename(command[0])
    started = time.monotonic()
    deadline_at = timeout_deadline_after(timeout)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=False,
            timeout=timeout,
            cwd=cwd,
            env=dict(environment or unprivileged_child_environment()),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _timeout_output(exc.stdout)
        stderr = _timeout_output(exc.stderr)
        raise CliTransportTimeout(
            f"{name} Graphiti LLM timed out",
            evidence=timeout_diagnostic(
                boundary="CONTROLLER_DEADLINE",
                phase="FALLBACK_TRANSPORT",
                cause="CONFIGURED_TIMEOUT_EXPIRED",
                configured_timeout_ms=round(timeout * 1_000),
                elapsed_ms=round((time.monotonic() - started) * 1_000),
                deadline_at=deadline_at,
                last_progress=(
                    "OUTPUT_OBSERVED" if stdout or stderr else "NO_OUTPUT_OBSERVED"
                ),
                termination="PROCESS_KILLED",
                process=name,
                stdout=stdout,
                stderr=stderr,
            ),
        ) from None
    if result.returncode != 0:
        raise RuntimeError(f"{name} Graphiti LLM failed")
    text = _decode_stdout(result.stdout, name=name)
    if not text.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return text


def _decode_stdout(stdout: bytes, *, name: str) -> str:
    try:
        return stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise CliOutputDecodeError(
            f"{name} Graphiti LLM returned malformed UTF-8"
        ) from None


def _timeout_output(value: bytes | str | None) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return b""


async def run_cli_async(
    command: tuple[str, ...],
    *,
    timeout: float,
    cwd: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Run a cancellable CLI child so the extraction deadline remains authoritative."""

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

    async def collect(stream: asyncio.StreamReader, destination: bytearray) -> None:
        while True:
            chunk = await stream.read(65_536)
            if not chunk:
                return
            destination.extend(chunk)

    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + timeout
    deadline_at = timeout_deadline_after(timeout)
    try:
        await asyncio.wait_for(
            asyncio.gather(
                collect(process.stdout, outputs["stdout"]),
                collect(process.stderr, outputs["stderr"]),
            ),
            timeout=timeout,
        )
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError
        await asyncio.wait_for(process.wait(), timeout=remaining)
    except TimeoutError:
        termination = await stop_process_async(process)
        stdout = bytes(outputs["stdout"])
        stderr = bytes(outputs["stderr"])
        raise CliTransportTimeout(
            f"{name} Graphiti LLM timed out",
            evidence=timeout_diagnostic(
                boundary="CONTROLLER_DEADLINE",
                phase="FALLBACK_TRANSPORT",
                cause="CONFIGURED_TIMEOUT_EXPIRED",
                configured_timeout_ms=round(timeout * 1_000),
                elapsed_ms=round((loop.time() - started) * 1_000),
                deadline_at=deadline_at,
                last_progress=(
                    "OUTPUT_OBSERVED" if stdout or stderr else "NO_OUTPUT_OBSERVED"
                ),
                termination=termination,
                process=name,
                stdout=stdout,
                stderr=stderr,
            ),
        ) from None
    except asyncio.CancelledError:
        await stop_process_async(process)
        raise
    except BaseException:
        await stop_process_async(process)
        raise
    if process.returncode != 0:
        raise RuntimeError(f"{name} Graphiti LLM failed")
    text = _decode_stdout(bytes(outputs["stdout"]), name=name)
    if not text.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return text


def _grok_command(
    *, prompt: str, schema: str | None, request_dir: str, max_tokens: int
) -> tuple[str, ...]:
    path = os.path.join(request_dir, "prompt.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(prompt)
    command = [
        GROK_BIN,
        "--prompt-file",
        path,
        "-m",
        GROK_CHAT_MODEL_ID,
        "--disable-web-search",
        "--sandbox",
        "read-only",
        "--permission-mode",
        "plan",
        "--tools",
        "",
        "--deny",
        "*",
        "--no-plan",
        "--max-turns",
        "1",
        "--max-output-tokens",
        str(max_tokens),
        "--no-subagents",
        "--reasoning-effort",
        GROK_CHAT_REASONING,
    ]
    if schema:
        command.extend(["--json-schema", schema])
    command.extend(["--output-format", "streaming-json"])
    return tuple(command)


@dataclass(frozen=True, slots=True)
class _GraphitiCliWorkspace:
    cwd: str
    request_dir: str
    environment: dict[str, str]


def _hermetic_cli_workspace(root: str, *, binary: str) -> _GraphitiCliWorkspace:
    paths = {
        "cwd": os.path.join(root, "workspace"),
        "home": os.path.join(root, "home"),
        "request": os.path.join(root, "request"),
        "tmp": os.path.join(root, "tmp"),
        "config": os.path.join(root, "xdg-config"),
        "data": os.path.join(root, "xdg-data"),
        "cache": os.path.join(root, "xdg-cache"),
        "state": os.path.join(root, "xdg-state"),
    }
    for path in paths.values():
        os.mkdir(path, mode=0o700)
    binary_dirs = tuple(
        dict.fromkeys(
            (os.path.dirname(binary), "/usr/bin", "/bin", "/usr/sbin", "/sbin")
        )
    )
    environment = {
        "HOME": paths["home"],
        "LANG": "en_GB.UTF-8",
        "LC_ALL": "en_GB.UTF-8",
        "PATH": os.pathsep.join(binary_dirs),
        "TMPDIR": paths["tmp"],
        "XDG_CACHE_HOME": paths["cache"],
        "XDG_CONFIG_HOME": paths["config"],
        "XDG_DATA_HOME": paths["data"],
        "XDG_STATE_HOME": paths["state"],
    }
    return _GraphitiCliWorkspace(
        cwd=paths["cwd"],
        request_dir=paths["request"],
        environment=environment,
    )


def _prove_cli_controls(
    *,
    binary: str,
    required_controls: tuple[str, ...],
    workspace: _GraphitiCliWorkspace,
) -> None:
    try:
        result = subprocess.run(
            (binary, "--help"),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            cwd=workspace.cwd,
            env=workspace.environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CliPredispatchRefusal("Graphiti CLI preflight failed") from exc
    if result.returncode != 0 or not all(
        control in result.stdout for control in required_controls
    ):
        raise CliPredispatchRefusal(
            "Graphiti CLI cannot prove tool isolation and max_tokens enforcement"
        )


async def _prove_cli_controls_async(
    *,
    binary: str,
    required_controls: tuple[str, ...],
    workspace: _GraphitiCliWorkspace,
) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "--help",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace.cwd,
            env=workspace.environment,
        )
    except OSError as exc:
        raise CliPredispatchRefusal("Graphiti CLI preflight failed") from exc
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise CliPredispatchRefusal("Graphiti CLI preflight timed out") from None
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    try:
        help_text = stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CliPredispatchRefusal(
            "Graphiti CLI preflight returned malformed UTF-8"
        ) from exc
    if process.returncode != 0 or not all(
        control in help_text for control in required_controls
    ):
        raise CliPredispatchRefusal(
            "Graphiti CLI cannot prove tool isolation and max_tokens enforcement"
        )


def parse_cursor_output(raw: str) -> CliExecution:
    """Extract Cursor's model result and final provider-reported token usage."""

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return CliExecution(text=raw, usage=unreported_cli_usage())
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), str):
        return CliExecution(text=raw, usage=unreported_cli_usage())
    return CliExecution(
        text=str(payload["result"]),
        usage=cursor_cli_usage(payload.get("usage")),
    )


def _grok_update(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    params = value.get("params")
    if isinstance(params, dict) and isinstance(params.get("update"), dict):
        return params["update"]
    update = value.get("update")
    if isinstance(update, dict):
        return update
    return value


def parse_grok_stream_output(raw: str) -> CliExecution:
    """Extract message chunks and ``turn_completed`` usage from Grok NDJSON."""

    chunks: list[str] = []
    usage = unreported_cli_usage()
    recognised = False
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        update = _grok_update(value)
        if update is None:
            continue
        kind = update.get("sessionUpdate") or update.get("type")
        if kind in {"agent_message_chunk", "assistant_message_chunk"}:
            content = update.get("content")
            text = content.get("text") if isinstance(content, dict) else content
            if isinstance(text, str):
                chunks.append(text)
                recognised = True
        elif kind in {"turn_completed", "turnEnded"}:
            usage = grok_cli_usage(update.get("usage"))
            recognised = True
    return CliExecution(
        text="".join(chunks) if recognised and chunks else raw,
        usage=usage,
    )


def run_cursor_agent_llm(
    prompt: str,
    *,
    max_tokens: int,
    dispatch_started: Callable[[], None] | None = None,
) -> CliExecution:
    _require_positive_max_tokens(max_tokens)
    with tempfile.TemporaryDirectory(prefix="newsroom-cursor-graphiti-") as root:
        workspace = _hermetic_cli_workspace(root, binary=CURSOR_AGENT_BIN)
        raw, qualification = run_cursor_transport(
            binary=CURSOR_AGENT_BIN,
            prompt=prompt,
            max_tokens=max_tokens,
            timeout=CLI_CALL_TIMEOUT_SECONDS,
            cwd=workspace.cwd,
            environment=workspace.environment,
            dispatch_started=dispatch_started,
        )
        execution = parse_cursor_output(raw)
        return CliExecution(
            text=execution.text,
            usage=execution.usage,
            transport_qualification=qualification.as_dict(),
        )


async def run_cursor_agent_llm_async(
    prompt: str,
    *,
    max_tokens: int,
    dispatch_started: Callable[[], None] | None = None,
) -> CliExecution:
    _require_positive_max_tokens(max_tokens)
    with tempfile.TemporaryDirectory(prefix="newsroom-cursor-graphiti-") as root:
        workspace = _hermetic_cli_workspace(root, binary=CURSOR_AGENT_BIN)
        raw, qualification = await run_cursor_transport_async(
            binary=CURSOR_AGENT_BIN,
            prompt=prompt,
            max_tokens=max_tokens,
            timeout=CLI_CALL_TIMEOUT_SECONDS,
            cwd=workspace.cwd,
            environment=workspace.environment,
            dispatch_started=dispatch_started,
        )
        execution = parse_cursor_output(raw)
        return CliExecution(
            text=execution.text,
            usage=execution.usage,
            transport_qualification=qualification.as_dict(),
        )


def run_grok_llm(
    prompt: str,
    schema: str | None,
    *,
    max_tokens: int,
    dispatch_started: Callable[[], None] | None = None,
) -> CliExecution:
    _require_positive_max_tokens(max_tokens)
    with tempfile.TemporaryDirectory(prefix="newsroom-grok-graphiti-") as root:
        workspace = _hermetic_cli_workspace(root, binary=GROK_BIN)
        _prove_cli_controls(
            binary=GROK_BIN,
            required_controls=("--max-output-tokens",),
            workspace=workspace,
        )
        if dispatch_started is not None:
            dispatch_started()
        return parse_grok_stream_output(
            run_cli(
                _grok_command(
                    prompt=prompt,
                    schema=schema,
                    request_dir=workspace.request_dir,
                    max_tokens=max_tokens,
                ),
                timeout=CLI_CALL_TIMEOUT_SECONDS,
                cwd=workspace.cwd,
                environment=workspace.environment,
            )
        )


async def run_grok_llm_async(
    prompt: str,
    schema: str | None,
    *,
    max_tokens: int,
    dispatch_started: Callable[[], None] | None = None,
) -> CliExecution:
    _require_positive_max_tokens(max_tokens)
    with tempfile.TemporaryDirectory(prefix="newsroom-grok-graphiti-") as root:
        workspace = _hermetic_cli_workspace(root, binary=GROK_BIN)
        await _prove_cli_controls_async(
            binary=GROK_BIN,
            required_controls=("--max-output-tokens",),
            workspace=workspace,
        )
        if dispatch_started is not None:
            dispatch_started()
        return parse_grok_stream_output(
            await run_cli_async(
                _grok_command(
                    prompt=prompt,
                    schema=schema,
                    request_dir=workspace.request_dir,
                    max_tokens=max_tokens,
                ),
                timeout=CLI_CALL_TIMEOUT_SECONDS,
                cwd=workspace.cwd,
                environment=workspace.environment,
            )
        )


def messages_to_prompt(messages: list[Any]) -> str:
    return "\n\n".join(
        f"{getattr(message, 'role', 'user')}:\n{getattr(message, 'content', '')}"
        for message in messages
    )


def _parsed_object(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(extract_json(raw))
    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _execution(value: CliOutput) -> CliExecution:
    if isinstance(value, CliExecution):
        return value
    return CliExecution(text=value, usage=unreported_cli_usage())


def _invocation(
    *,
    provider: str,
    model: str,
    outcome: str,
    execution: CliExecution | None = None,
    failure: str | None = None,
    requested_max_tokens: int = 0,
    receipt_binding: Mapping[str, str] | None = None,
    transport_diagnostic: Mapping[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "provider": provider,
        "model": model,
        "outcome": outcome,
        "usage": (
            dict(execution.usage) if execution is not None else unreported_cli_usage()
        ),
        "requested_max_tokens": requested_max_tokens,
    }
    if receipt_binding is not None:
        value.update(receipt_binding)
    if execution is not None and execution.transport_qualification is not None:
        value["transport_qualification"] = dict(
            execution.transport_qualification
        )
    if failure is not None:
        value["failure"] = failure
    if transport_diagnostic is not None:
        value["transport_diagnostic"] = dict(transport_diagnostic)
    return value


def _retained_timeout_diagnostic(
    exc: BaseException,
    *,
    phase: str,
    started: float,
    transport_started: bool,
) -> Mapping[str, object]:
    if isinstance(exc, CliTransportTimeout):
        return exc.evidence
    return timeout_diagnostic(
        boundary="UNOBSERVED_TIMEOUT_BOUNDARY",
        phase=phase,
        cause="TIMEOUT_ORIGIN_UNOBSERVED",
        configured_timeout_ms=CLI_CALL_TIMEOUT_SECONDS * 1_000,
        elapsed_ms=round((time.monotonic() - started) * 1_000),
        deadline_at=None,
        last_progress=("DISPATCH_STARTED" if transport_started else "PREDISPATCH"),
        termination="UNOBSERVED",
    )


def _bind_requested_max_tokens(prompt: str, max_tokens: int) -> str:
    _require_positive_max_tokens(max_tokens)
    return (
        f"{prompt}\n\n"
        "<newsroom_controller_output_contract>\n"
        f"maximum_output_tokens={max_tokens}\n"
        "</newsroom_controller_output_contract>"
    )


def _require_positive_max_tokens(max_tokens: int) -> None:
    if isinstance(max_tokens, bool) or max_tokens <= 0:
        raise ValueError("Graphiti requested max_tokens must be positive")


def _output_exceeds_conservative_transport_ceiling(
    execution: CliExecution, *, max_tokens: int
) -> bool:
    """Bound unreported output using one UTF-8 byte as the safe token floor."""

    return len(execution.text.encode("utf-8")) > max_tokens


def _output_limit_exceeded(
    execution: CliExecution, *, max_tokens: int
) -> bool:
    output_tokens = execution.usage.get("output_tokens")
    if (
        execution.usage.get("usage_basis") == "PROVIDER_REPORTED"
        and isinstance(output_tokens, int)
        and not isinstance(output_tokens, bool)
        and output_tokens >= 0
    ):
        return output_tokens > max_tokens
    return _output_exceeds_conservative_transport_ceiling(
        execution, max_tokens=max_tokens
    )


def _before_observed_cli_invocation(
    observer: CliInvocationObserver,
    *,
    provider: str,
    model: str,
    prompt: str,
    schema: str | None,
    semantic_request_class: str,
    max_tokens: int,
) -> object:
    method = observer.before_cli_invocation
    parameters = inspect.signature(method).parameters.values()
    accepts_extended_contract = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    ) or {"semantic_request_class", "max_tokens"}.issubset(
        inspect.signature(method).parameters
    )
    values: dict[str, object] = {
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "schema": schema,
    }
    if accepts_extended_contract:
        values.update(
            {
                "semantic_request_class": semantic_request_class,
                "max_tokens": max_tokens,
            }
        )
    return method(**values)  # type: ignore[arg-type]


def _runner_accepts_dispatch_marker(runner: Callable[..., object]) -> bool:
    try:
        parameters = inspect.signature(runner).parameters
    except (TypeError, ValueError):
        return False
    return "dispatch_started" in parameters


def _mark_observed_transport_dispatch(
    observer: CliInvocationObserver | None, token: object
) -> None:
    if observer is None:
        return
    method = getattr(observer, "transport_dispatch_started", None)
    if callable(method):
        method(token)


async def run_cli_chain(
    *,
    prompt: str,
    schema: str | None,
    cursor_runner: CliRunner | AsyncCliRunner,
    grok_runner: GrokRunner | AsyncGrokRunner,
    invocations: list[dict[str, object]],
    invocation_observer: CliInvocationObserver | None = None,
    semantic_request_class: str = "UNSTRUCTURED",
    max_tokens: int = 16_384,
) -> dict[str, Any]:
    """Execute cursor then Grok fallback while retaining every call outcome."""

    prompt = _bind_requested_max_tokens(prompt, max_tokens)
    cursor_token = (
        None
        if invocation_observer is None
        else _before_observed_cli_invocation(
            invocation_observer,
            provider="cursor-agent-cli",
            model=CURSOR_AGENT_MODEL_ID,
            prompt=prompt,
            schema=schema,
            semantic_request_class=semantic_request_class,
            max_tokens=max_tokens,
        )
    )
    cursor_transport_started = False
    cursor_started = time.monotonic()

    def mark_cursor_transport_started() -> None:
        nonlocal cursor_transport_started
        if cursor_transport_started:
            raise RuntimeError("Cursor Graphiti transport dispatch repeated")
        try:
            _mark_observed_transport_dispatch(invocation_observer, cursor_token)
        except Exception as exc:
            raise CliDispatchMarkerError(
                "Cursor durable dispatch observation failed"
            ) from exc
        cursor_transport_started = True

    def observe(
        token: object,
        *,
        outcome: str,
        usage: dict[str, object],
    ) -> Mapping[str, str] | None:
        if invocation_observer is None:
            return None
        return invocation_observer.after_cli_invocation(
            token,
            outcome=outcome,
            usage=usage,
        )

    try:
        if inspect.iscoroutinefunction(cursor_runner):
            if _runner_accepts_dispatch_marker(cursor_runner):
                raw = await cursor_runner(
                    prompt,
                    max_tokens=max_tokens,
                    dispatch_started=mark_cursor_transport_started,
                )
            else:
                mark_cursor_transport_started()
                raw = await cursor_runner(prompt, max_tokens=max_tokens)
        else:
            if _runner_accepts_dispatch_marker(cursor_runner):
                raw = await asyncio.to_thread(
                    cursor_runner,
                    prompt,
                    max_tokens=max_tokens,
                    dispatch_started=mark_cursor_transport_started,
                )
            else:
                mark_cursor_transport_started()
                raw = await asyncio.to_thread(
                    cursor_runner, prompt, max_tokens=max_tokens
                )
    except CliDispatchMarkerError as exc:
        cursor_usage = no_provider_call_cli_usage()
        binding = observe(
            cursor_token,
            outcome="DISPATCH_FENCE_REFUSED",
            usage=cursor_usage,
        )
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome="DISPATCH_FENCE_REFUSED",
                execution=CliExecution(text="", usage=cursor_usage),
                failure=type(exc.__cause__ or exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
            )
        )
        if isinstance(exc.__cause__, Exception):
            raise exc.__cause__
        raise
    except asyncio.CancelledError as exc:
        cursor_usage = (
            unreported_cli_usage()
            if cursor_transport_started
            else no_provider_call_cli_usage()
        )
        binding = observe(cursor_token, outcome="CANCELLED", usage=cursor_usage)
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome="CANCELLED",
                execution=CliExecution(text="", usage=cursor_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
                transport_diagnostic=timeout_diagnostic(
                    boundary="CALLER_CANCELLATION",
                    phase="PRIMARY_TRANSPORT",
                    cause="CALLER_CANCELLED",
                    configured_timeout_ms=CLI_CALL_TIMEOUT_SECONDS * 1_000,
                    elapsed_ms=round(
                        (time.monotonic() - cursor_started) * 1_000
                    ),
                    deadline_at=None,
                    last_progress=(
                        "DISPATCH_STARTED"
                        if cursor_transport_started
                        else "PREDISPATCH"
                    ),
                    termination="TASK_CANCELLED",
                ),
            )
        )
        raise
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        cursor_usage = (
            unreported_cli_usage()
            if cursor_transport_started
            else no_provider_call_cli_usage()
        )
        binding = observe(cursor_token, outcome="TIMEOUT", usage=cursor_usage)
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome="TIMEOUT",
                execution=CliExecution(text="", usage=cursor_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
                transport_diagnostic=_retained_timeout_diagnostic(
                    exc,
                    phase="PRIMARY_TRANSPORT",
                    started=cursor_started,
                    transport_started=cursor_transport_started,
                ),
            )
        )
        cursor_outcome = "TIMEOUT"
        payload = None
    except CliOutputBoundExceeded as exc:
        cursor_usage = (
            unreported_cli_usage()
            if cursor_transport_started
            else no_provider_call_cli_usage()
        )
        binding = observe(
            cursor_token, outcome="OUTPUT_LIMIT_EXCEEDED", usage=cursor_usage
        )
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome="OUTPUT_LIMIT_EXCEEDED",
                execution=CliExecution(text="", usage=cursor_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
            )
        )
        raise CliResponseError(
            "Cursor Graphiti response exceeded controller stdout bound"
        ) from exc
    except (FileNotFoundError, CliPredispatchRefusal) as exc:
        cursor_usage = (
            unreported_cli_usage()
            if cursor_transport_started
            else no_provider_call_cli_usage()
        )
        refusal_outcome = (
            "EXECUTABLE_NOT_FOUND"
            if isinstance(exc, FileNotFoundError)
            else "PREDISPATCH_REFUSED"
        )
        binding = observe(
            cursor_token, outcome=refusal_outcome, usage=cursor_usage
        )
        invocation = _invocation(
            provider="cursor-agent-cli",
            model=CURSOR_AGENT_MODEL_ID,
            outcome=refusal_outcome,
            execution=CliExecution(text="", usage=cursor_usage),
            failure=type(exc).__name__,
            requested_max_tokens=max_tokens,
            receipt_binding=binding,
        )
        if isinstance(exc, CliPredispatchRefusal) and exc.qualification_evidence:
            invocation["transport_qualification"] = dict(
                exc.qualification_evidence
            )
        invocations.append(invocation)
        cursor_outcome = refusal_outcome
        payload = None
    except (RuntimeError, OSError) as exc:
        cursor_usage = (
            unreported_cli_usage()
            if cursor_transport_started
            else no_provider_call_cli_usage()
        )
        binding = observe(cursor_token, outcome="FAILED", usage=cursor_usage)
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome="FAILED",
                execution=CliExecution(text="", usage=cursor_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
            )
        )
        cursor_outcome = "FAILED"
        payload = None
    else:
        cursor_execution = _execution(cast(CliOutput, raw))
        payload = _parsed_object(cursor_execution.text)
        output_limit_exceeded = _output_limit_exceeded(
            cursor_execution, max_tokens=max_tokens
        )
        cursor_outcome = (
            "OUTPUT_LIMIT_EXCEEDED"
            if output_limit_exceeded
            else "COMPLETE"
            if payload is not None
            else "MALFORMED_OUTPUT"
        )
        binding = observe(
            cursor_token,
            outcome=cursor_outcome,
            usage=dict(cursor_execution.usage),
        )
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome=cursor_outcome,
                execution=cursor_execution,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
            )
        )
        if output_limit_exceeded:
            raise CliResponseError(
                "Cursor Graphiti response exceeded requested max_tokens"
            )
    if payload is not None:
        return payload
    if (
        classify_graphiti_fallback(cursor_outcome).eligibility
        is not FallbackEligibility.ELIGIBLE
    ):
        raise CliResponseError(
            f"Cursor Graphiti outcome {cursor_outcome} is ineligible for fallback"
        )

    grok_token = (
        None
        if invocation_observer is None
        else _before_observed_cli_invocation(
            invocation_observer,
            provider="grok-build-cli",
            model=GROK_CHAT_MODEL_ID,
            prompt=prompt,
            schema=schema,
            semantic_request_class=semantic_request_class,
            max_tokens=max_tokens,
        )
    )
    grok_transport_started = False
    grok_started = time.monotonic()

    def mark_grok_transport_started() -> None:
        nonlocal grok_transport_started
        if grok_transport_started:
            raise RuntimeError("Grok Graphiti transport dispatch repeated")
        try:
            _mark_observed_transport_dispatch(invocation_observer, grok_token)
        except Exception as exc:
            raise CliDispatchMarkerError(
                "Grok durable dispatch observation failed"
            ) from exc
        grok_transport_started = True
    try:
        if inspect.iscoroutinefunction(grok_runner):
            if _runner_accepts_dispatch_marker(grok_runner):
                raw = await grok_runner(
                    prompt,
                    schema,
                    max_tokens=max_tokens,
                    dispatch_started=mark_grok_transport_started,
                )
            else:
                mark_grok_transport_started()
                raw = await grok_runner(prompt, schema, max_tokens=max_tokens)
        else:
            if _runner_accepts_dispatch_marker(grok_runner):
                raw = await asyncio.to_thread(
                    grok_runner,
                    prompt,
                    schema,
                    max_tokens=max_tokens,
                    dispatch_started=mark_grok_transport_started,
                )
            else:
                mark_grok_transport_started()
                raw = await asyncio.to_thread(
                    grok_runner, prompt, schema, max_tokens=max_tokens
                )
    except CliDispatchMarkerError as exc:
        grok_usage = no_provider_call_cli_usage()
        binding = observe(
            grok_token,
            outcome="DISPATCH_FENCE_REFUSED",
            usage=grok_usage,
        )
        invocations.append(
            _invocation(
                provider="grok-build-cli",
                model=GROK_CHAT_MODEL_ID,
                outcome="DISPATCH_FENCE_REFUSED",
                execution=CliExecution(text="", usage=grok_usage),
                failure=type(exc.__cause__ or exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
            )
        )
        if isinstance(exc.__cause__, Exception):
            raise exc.__cause__
        raise
    except asyncio.CancelledError as exc:
        grok_usage = (
            unreported_cli_usage()
            if grok_transport_started
            else no_provider_call_cli_usage()
        )
        binding = observe(grok_token, outcome="CANCELLED", usage=grok_usage)
        invocations.append(
            _invocation(
                provider="grok-build-cli",
                model=GROK_CHAT_MODEL_ID,
                outcome="CANCELLED",
                execution=CliExecution(text="", usage=grok_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
                transport_diagnostic=timeout_diagnostic(
                    boundary="CALLER_CANCELLATION",
                    phase="FALLBACK_TRANSPORT",
                    cause="CALLER_CANCELLED",
                    configured_timeout_ms=CLI_CALL_TIMEOUT_SECONDS * 1_000,
                    elapsed_ms=round((time.monotonic() - grok_started) * 1_000),
                    deadline_at=None,
                    last_progress=(
                        "DISPATCH_STARTED"
                        if grok_transport_started
                        else "PREDISPATCH"
                    ),
                    termination="TASK_CANCELLED",
                ),
            )
        )
        raise
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        grok_usage = (
            unreported_cli_usage()
            if grok_transport_started
            else no_provider_call_cli_usage()
        )
        binding = observe(grok_token, outcome="TIMEOUT", usage=grok_usage)
        invocations.append(
            _invocation(
                provider="grok-build-cli",
                model=GROK_CHAT_MODEL_ID,
                outcome="TIMEOUT",
                execution=CliExecution(text="", usage=grok_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
                transport_diagnostic=_retained_timeout_diagnostic(
                    exc,
                    phase="FALLBACK_TRANSPORT",
                    started=grok_started,
                    transport_started=grok_transport_started,
                ),
            )
        )
        raise CliResponseError("Graphiti fallback CLI timed out") from exc
    except (FileNotFoundError, CliPredispatchRefusal) as exc:
        grok_usage = (
            unreported_cli_usage()
            if grok_transport_started
            else no_provider_call_cli_usage()
        )
        refusal_outcome = (
            "EXECUTABLE_NOT_FOUND"
            if isinstance(exc, FileNotFoundError)
            else "PREDISPATCH_REFUSED"
        )
        binding = observe(
            grok_token, outcome=refusal_outcome, usage=grok_usage
        )
        invocations.append(
            _invocation(
                provider="grok-build-cli",
                model=GROK_CHAT_MODEL_ID,
                outcome=refusal_outcome,
                execution=CliExecution(text="", usage=grok_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
            )
        )
        raise CliResponseError("Graphiti fallback CLI executable not found") from exc
    except (RuntimeError, OSError) as exc:
        grok_usage = (
            unreported_cli_usage()
            if grok_transport_started
            else no_provider_call_cli_usage()
        )
        binding = observe(grok_token, outcome="FAILED", usage=grok_usage)
        invocations.append(
            _invocation(
                provider="grok-build-cli",
                model=GROK_CHAT_MODEL_ID,
                outcome="FAILED",
                execution=CliExecution(text="", usage=grok_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
            )
        )
        raise CliResponseError("Graphiti fallback CLI failed") from exc
    grok_execution = _execution(cast(CliOutput, raw))
    payload = _parsed_object(grok_execution.text)
    output_limit_exceeded = _output_limit_exceeded(
        grok_execution, max_tokens=max_tokens
    )
    grok_outcome = (
        "OUTPUT_LIMIT_EXCEEDED"
        if output_limit_exceeded
        else "COMPLETE"
        if payload is not None
        else "MALFORMED_OUTPUT"
    )
    binding = observe(
        grok_token,
        outcome=grok_outcome,
        usage=dict(grok_execution.usage),
    )
    invocations.append(
        _invocation(
            provider="grok-build-cli",
            model=GROK_CHAT_MODEL_ID,
            outcome=grok_outcome,
            execution=grok_execution,
            requested_max_tokens=max_tokens,
            receipt_binding=binding,
        )
    )
    if output_limit_exceeded:
        raise CliResponseError("Grok Graphiti response exceeded requested max_tokens")
    if payload is None:
        raise CliResponseError("Graphiti CLI JSON was not an object")
    return payload


def build_cli_llm_client(
    *,
    cursor_runner: CliRunner | None = None,
    grok_runner: GrokRunner | None = None,
    invocation_observer: CliInvocationObserver | None = None,
) -> GraphitiCliClient:
    """Build Graphiti's LLMClient while retaining every attempted CLI call."""

    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.errors import EmptyResponseError
    from pydantic import BaseModel

    cursor: CliRunner | AsyncCliRunner = cursor_runner or run_cursor_agent_llm_async
    grok: GrokRunner | AsyncGrokRunner = grok_runner or run_grok_llm_async

    class CliChainGraphitiLlmClient(LLMClient):
        def __init__(self) -> None:
            super().__init__(
                LLMConfig(
                    model=CURSOR_AGENT_MODEL_ID, small_model=CURSOR_AGENT_MODEL_ID
                ),
                cache=False,
            )
            self.invocations: list[dict[str, object]] = []

        async def _generate_response(
            self,
            messages: list[Any],
            response_model: type[BaseModel] | None = None,
            max_tokens: int = 0,
            model_size: object = None,
        ) -> dict[str, Any]:
            del model_size
            prompt = messages_to_prompt(messages)
            schema = (
                json.dumps(response_model.model_json_schema())
                if response_model is not None
                else None
            )
            semantic_request_class = (
                response_model.__name__
                if response_model is not None
                else "UNSTRUCTURED"
            )
            requested_max_tokens = max_tokens if max_tokens > 0 else 16_384
            try:
                return await run_cli_chain(
                    prompt=prompt,
                    schema=schema,
                    cursor_runner=cursor,
                    grok_runner=grok,
                    invocations=self.invocations,
                    invocation_observer=invocation_observer,
                    semantic_request_class=semantic_request_class,
                    max_tokens=requested_max_tokens,
                )
            except CliResponseError as exc:
                raise EmptyResponseError(str(exc)) from exc

    return CliChainGraphitiLlmClient()


__all__ = [
    "QUALIFIED_CURSOR_AGENT_VERSION",
    "CliInvocationObserver",
    "CliOutputBoundExceeded",
    "CliOutputDecodeError",
    "CliPredispatchRefusal",
    "CliResponseError",
    "CursorCliQualification",
    "build_cli_llm_client",
    "cursor_stdout_limit",
    "extract_json",
    "run_cli",
    "run_cli_chain",
    "run_cursor_agent_llm",
    "run_grok_llm",
]
