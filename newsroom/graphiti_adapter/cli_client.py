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

from newsroom.control_plane.graphiti_fallback_policy import (
    FallbackEligibility,
    classify_graphiti_fallback,
)
from newsroom.graphiti_adapter.cli_process import (
    CliOutputBoundExceeded,
    CliOutputDecodeError,
    CliTransportTimeout,
    retained_cli_qualification,
    run_bounded_process,
    run_bounded_process_async,
    timeout_diagnostic,
    validated_process_exit_diagnostic,
    validated_sdk_terminal,
    validated_timeout_diagnostics,
)
from newsroom.graphiti_adapter.cursor_transport import (
    CliPredispatchRefusal,
    CursorSdkAmbiguousDispatch,
    CursorSdkBoundedFailure,
    CursorSdkCleanupError,
    CursorSdkError,
    CursorSdkExecution,
    CursorToolCallViolation,
    cursor_stdout_limit,
    run_cursor_transport,
    run_cursor_transport_async,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    CURSOR_AGENT_MODEL_ID,
    GROK_CHAT_MODEL_ID,
    GROK_CHAT_REASONING,
    GRAPHITI_EXTRACTION_TIMEOUT_MS,
    GRAPHITI_MAX_CLEANUP_TIMEOUT_MS,
)
from newsroom.graphiti_adapter.usage_meter import (
    grok_cli_usage,
    no_provider_call_cli_usage,
    unreported_cli_usage,
)

GROK_BIN = os.environ.get("NEWSROOM_GROK_BIN", "/Users/jamesto/.grok/bin/grok")
GROK_PREFLIGHT_TIMEOUT_SECONDS = 20
GROK_PREFLIGHT_MAX_BYTES = 64 * 1024
GROK_STDOUT_BASE_BYTES = 64 * 1024
GROK_STDOUT_BYTES_PER_TOKEN = 64
GROK_STDOUT_LIMIT_FORMULA = "65536+64*REQUEST_MAX_TOKENS"
GROK_STDOUT_LIMIT_IDENTITY = (
    "grok-controller-stdout-v1:" + GROK_STDOUT_LIMIT_FORMULA
)
CLI_CALL_TIMEOUT_SECONDS = (
    GRAPHITI_EXTRACTION_TIMEOUT_MS - GRAPHITI_MAX_CLEANUP_TIMEOUT_MS
) // 1_000


@dataclass(frozen=True, slots=True)
class CliExecution:
    text: str
    usage: dict[str, object]
    transport_qualification: dict[str, object] | None = None
    sdk_agent_id: str | None = None
    sdk_run_id: str | None = None
    sdk_request_id: str | None = None
    sdk_terminal: dict[str, object] | None = None


CliOutput = str | CliExecution


class CliRunner(Protocol):
    def __call__(
        self,
        prompt: str,
        *,
        max_tokens: int,
        dispatch_started: Callable[[], None] | None = None,
        idempotency_key: str | None = None,
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
        idempotency_key: str | None = None,
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


def grok_stdout_limit(max_tokens: int) -> int:
    _require_positive_max_tokens(max_tokens)
    return GROK_STDOUT_BASE_BYTES + GROK_STDOUT_BYTES_PER_TOKEN * max_tokens


def run_cli(
    command: tuple[str, ...],
    *,
    timeout: float,
    cwd: str | None = None,
    environment: Mapping[str, str] | None = None,
    max_output_bytes: int = (
        GROK_STDOUT_BASE_BYTES + GROK_STDOUT_BYTES_PER_TOKEN * 16_384
    ),
) -> str:
    """Run one fallback CLI through the shared bounded-process contract."""

    name = os.path.basename(command[0])
    result = run_bounded_process(
        command,
        timeout=timeout,
        max_output_bytes=max_output_bytes,
        cwd=cwd,
        environment=environment,
        phase="FALLBACK_TRANSPORT",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{name} Graphiti LLM failed")
    if not result.stdout.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return result.stdout


async def run_cli_async(
    command: tuple[str, ...],
    *,
    timeout: float,
    cwd: str | None = None,
    environment: Mapping[str, str] | None = None,
    max_output_bytes: int = (
        GROK_STDOUT_BASE_BYTES + GROK_STDOUT_BYTES_PER_TOKEN * 16_384
    ),
) -> str:
    """Async fallback wrapper over the shared bounded-process contract."""

    name = os.path.basename(command[0])
    result = await run_bounded_process_async(
        command,
        timeout=timeout,
        max_output_bytes=max_output_bytes,
        cwd=cwd,
        environment=environment,
        phase="FALLBACK_TRANSPORT",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{name} Graphiti LLM failed")
    if not result.stdout.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return result.stdout


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
        result = run_bounded_process(
            (binary, "--help"),
            timeout=GROK_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=GROK_PREFLIGHT_MAX_BYTES,
            cwd=workspace.cwd,
            environment=workspace.environment,
            phase="PREDISPATCH_HELP",
        )
    except CliTransportTimeout as exc:
        raise CliPredispatchRefusal(
            "Graphiti CLI preflight timed out",
            qualification_evidence={"timeout_diagnostic": dict(exc.evidence)},
        ) from exc
    except (CliOutputBoundExceeded, CliOutputDecodeError, OSError) as exc:
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
        result = await run_bounded_process_async(
            (binary, "--help"),
            timeout=GROK_PREFLIGHT_TIMEOUT_SECONDS,
            max_output_bytes=GROK_PREFLIGHT_MAX_BYTES,
            cwd=workspace.cwd,
            environment=workspace.environment,
            phase="PREDISPATCH_HELP",
        )
    except CliTransportTimeout as exc:
        raise CliPredispatchRefusal(
            "Graphiti CLI preflight timed out",
            qualification_evidence={"timeout_diagnostic": dict(exc.evidence)},
        ) from exc
    except (CliOutputBoundExceeded, CliOutputDecodeError, OSError) as exc:
        raise CliPredispatchRefusal("Graphiti CLI preflight failed") from exc
    if result.returncode != 0 or not all(
        control in result.stdout for control in required_controls
    ):
        raise CliPredispatchRefusal(
            "Graphiti CLI cannot prove tool isolation and max_tokens enforcement"
        )


def _sdk_execution(value: CursorSdkExecution) -> CliExecution:
    return CliExecution(
        text=value.text,
        usage=dict(value.usage),
        transport_qualification=value.qualification.as_dict(),
        sdk_agent_id=value.agent_id,
        sdk_run_id=value.run_id,
        sdk_request_id=value.request_id,
        sdk_terminal=value.terminal_record(),
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
    idempotency_key: str | None = None,
) -> CliExecution:
    _require_positive_max_tokens(max_tokens)
    return _sdk_execution(
        run_cursor_transport(
            prompt=prompt,
            max_tokens=max_tokens,
            timeout=CLI_CALL_TIMEOUT_SECONDS,
            dispatch_started=dispatch_started,
            idempotency_key=idempotency_key,
        )
    )


async def run_cursor_agent_llm_async(
    prompt: str,
    *,
    max_tokens: int,
    dispatch_started: Callable[[], None] | None = None,
    idempotency_key: str | None = None,
) -> CliExecution:
    _require_positive_max_tokens(max_tokens)
    return _sdk_execution(
        await run_cursor_transport_async(
            prompt=prompt,
            max_tokens=max_tokens,
            timeout=CLI_CALL_TIMEOUT_SECONDS,
            dispatch_started=dispatch_started,
            idempotency_key=idempotency_key,
        )
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
                max_output_bytes=grok_stdout_limit(max_tokens),
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
                max_output_bytes=grok_stdout_limit(max_tokens),
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


def _sdk_failure_execution(exc: BaseException) -> CliExecution | None:
    execution = getattr(exc, "execution", None)
    if isinstance(execution, CursorSdkExecution):
        return _sdk_execution(execution)
    return None


def _cursor_usage_for_failure(
    exc: BaseException | None,
    *,
    transport_started: bool,
    sdk_execution: CliExecution | None = None,
) -> dict[str, object]:
    if isinstance(exc, CursorSdkAmbiguousDispatch):
        return unreported_cli_usage()
    if transport_started:
        if sdk_execution is not None:
            return dict(sdk_execution.usage)
        if isinstance(exc, CursorSdkError):
            return dict(exc.usage)
        return unreported_cli_usage()
    return no_provider_call_cli_usage()


def _sdk_failure_outcome(exc: CursorSdkError) -> str:
    if isinstance(exc, CursorSdkAmbiguousDispatch):
        return "AMBIGUOUS_DISPATCH"
    if isinstance(exc, CursorSdkBoundedFailure):
        return exc.outcome
    if exc.error_class == "RATE_LIMIT":
        return "QUOTA_EXCEEDED"
    if exc.error_class == "AUTHENTICATION":
        return "AUTHENTICATION_FAILED"
    return "FAILED"


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
    process_exit_diagnostic: Mapping[str, object] | None = None,
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
        value["transport_qualification"] = retained_cli_qualification(
            execution.transport_qualification
        )
    if execution is not None and execution.sdk_agent_id:
        value["sdk_agent_id"] = execution.sdk_agent_id
    if execution is not None and execution.sdk_run_id:
        value["sdk_run_id"] = execution.sdk_run_id
    if execution is not None and execution.sdk_request_id:
        value["sdk_request_id"] = execution.sdk_request_id
    if execution is not None and execution.sdk_terminal is not None:
        value["sdk_terminal"] = validated_sdk_terminal(execution.sdk_terminal)
    if failure is not None:
        value["failure"] = failure
    if transport_diagnostic is not None:
        value["transport_diagnostic"] = validated_timeout_diagnostics(
            [dict(transport_diagnostic)]
        )[0]
    if process_exit_diagnostic is not None:
        value["process_exit_diagnostic"] = validated_process_exit_diagnostic(
            dict(process_exit_diagnostic)
        )
    return value


def _retained_refusal_qualification(
    exc: CliPredispatchRefusal,
) -> dict[str, object] | None:
    """Retain only a validated causal diagnostic from refusal evidence."""

    diagnostic = exc.qualification_evidence.get("timeout_diagnostic")
    if diagnostic is None:
        return None
    try:
        retained = validated_timeout_diagnostics([diagnostic])[0]
    except ValueError:
        return None
    return {"timeout_diagnostic": retained}


def _retained_timeout_diagnostic(
    exc: BaseException,
    *,
    phase: str,
    started: float,
    transport_started: bool,
) -> Mapping[str, object]:
    if isinstance(exc, CliTransportTimeout):
        try:
            return validated_timeout_diagnostics([dict(exc.evidence)])[0]
        except ValueError:
            pass
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


def _runner_accepts_idempotency_key(runner: Callable[..., object]) -> bool:
    try:
        parameters = inspect.signature(runner).parameters
    except (TypeError, ValueError):
        return False
    return "idempotency_key" in parameters


def _governed_idempotency_key(token: object | None) -> str | None:
    request_digest = getattr(token, "request_digest", None)
    if isinstance(request_digest, str) and request_digest.startswith("sha256:"):
        return request_digest
    return None


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
    fallback_permitted: bool = True,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Execute cursor then Grok fallback while retaining every call outcome."""

    if not isinstance(fallback_permitted, bool):
        raise TypeError("Graphiti fallback permission must be boolean")
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
    cursor_idempotency_key = (
        _governed_idempotency_key(cursor_token) or idempotency_key
    )
    if invocation_observer is not None and cursor_idempotency_key is None:
        raise CliDispatchMarkerError(
            "Cursor governed request digest is unavailable before transport"
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
                    idempotency_key=cursor_idempotency_key,
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
                    idempotency_key=cursor_idempotency_key,
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
    except (TimeoutError, subprocess.TimeoutExpired, CursorSdkBoundedFailure) as exc:
        sdk_execution = _sdk_failure_execution(exc)
        cursor_usage = _cursor_usage_for_failure(
            exc,
            transport_started=cursor_transport_started,
            sdk_execution=sdk_execution,
        )
        outcome = (
            exc.outcome
            if isinstance(exc, CursorSdkBoundedFailure)
            else "TIMEOUT"
        )
        binding = observe(cursor_token, outcome=outcome, usage=cursor_usage)
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome=outcome,
                execution=sdk_execution
                or CliExecution(text="", usage=cursor_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
                transport_diagnostic=_retained_timeout_diagnostic(
                    exc,
                    phase="PRIMARY_TRANSPORT",
                    started=cursor_started,
                    transport_started=cursor_transport_started,
                )
                if outcome == "TIMEOUT"
                else None,
            )
        )
        if outcome == "OUTPUT_LIMIT_EXCEEDED":
            raise CliResponseError(
                "Cursor Graphiti response exceeded requested max_tokens"
            ) from exc
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
        if isinstance(exc, CliPredispatchRefusal):
            retained_qualification = _retained_refusal_qualification(exc)
            if retained_qualification is not None:
                invocation["transport_qualification"] = retained_qualification
        invocations.append(invocation)
        cursor_outcome = refusal_outcome
        payload = None
    except CursorSdkError as exc:
        sdk_execution = _sdk_failure_execution(exc)
        cursor_usage = _cursor_usage_for_failure(
            exc,
            transport_started=cursor_transport_started,
            sdk_execution=sdk_execution,
        )
        cursor_outcome = _sdk_failure_outcome(exc)
        binding = observe(
            cursor_token, outcome=cursor_outcome, usage=cursor_usage
        )
        ambiguous_execution = sdk_execution
        if ambiguous_execution is None and isinstance(exc, CursorSdkAmbiguousDispatch):
            ambiguous_execution = CliExecution(
                text="",
                usage=cursor_usage,
                sdk_request_id=exc.request_id,
            )
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome=cursor_outcome,
                execution=ambiguous_execution
                or CliExecution(text="", usage=cursor_usage),
                failure=type(exc).__name__,
                requested_max_tokens=max_tokens,
                receipt_binding=binding,
            )
        )
        payload = None
        if cursor_outcome == "OUTPUT_LIMIT_EXCEEDED":
            raise CliResponseError(
                "Cursor Graphiti response exceeded requested max_tokens"
            ) from exc
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
    if not fallback_permitted:
        raise CliResponseError("Graphiti fallback is disabled before dispatch")
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
        invocation = _invocation(
            provider="grok-build-cli",
            model=GROK_CHAT_MODEL_ID,
            outcome=refusal_outcome,
            execution=CliExecution(text="", usage=grok_usage),
            failure=type(exc).__name__,
            requested_max_tokens=max_tokens,
            receipt_binding=binding,
        )
        if isinstance(exc, CliPredispatchRefusal):
            retained_qualification = _retained_refusal_qualification(exc)
            if retained_qualification is not None:
                invocation["transport_qualification"] = retained_qualification
        invocations.append(invocation)
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
    fallback_permitted: bool = True,
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
                    fallback_permitted=fallback_permitted,
                )
            except CliResponseError as exc:
                raise EmptyResponseError(str(exc)) from exc

    return CliChainGraphitiLlmClient()


__all__ = [
    "GROK_STDOUT_LIMIT_IDENTITY",
    "CliInvocationObserver",
    "CliOutputBoundExceeded",
    "CliOutputDecodeError",
    "CliPredispatchRefusal",
    "CliResponseError",
    "build_cli_llm_client",
    "cursor_stdout_limit",
    "extract_json",
    "grok_stdout_limit",
    "run_cli",
    "run_cli_chain",
    "run_cursor_agent_llm",
    "run_grok_llm",
]
