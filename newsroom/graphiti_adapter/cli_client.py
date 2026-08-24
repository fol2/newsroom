"""Subscription CLI chat client used by Graphiti EVALUATION execution."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from newsroom.control_plane.child_environment import unprivileged_child_environment
from newsroom.graphiti_adapter.evaluation_packet import (
    CURSOR_AGENT_MODEL_ID,
    GROK_CHAT_MODEL_ID,
    GROK_CHAT_REASONING,
)
from newsroom.graphiti_adapter.usage_meter import (
    cursor_cli_usage,
    grok_cli_usage,
    no_provider_call_cli_usage,
    unreported_cli_usage,
)

CURSOR_AGENT_BIN = os.environ.get(
    "NEWSROOM_CURSOR_AGENT_BIN", "/Users/jamesto/.local/bin/cursor-agent"
)
GROK_BIN = os.environ.get("NEWSROOM_GROK_BIN", "/Users/jamesto/.grok/bin/grok")
CLI_CALL_TIMEOUT_SECONDS = 80


@dataclass(frozen=True, slots=True)
class CliExecution:
    text: str
    usage: dict[str, object]


CliOutput = str | CliExecution
CliRunner = Callable[[str], CliOutput]
GrokRunner = Callable[[str, str | None], CliOutput]
AsyncCliRunner = Callable[[str], Awaitable[CliOutput]]
AsyncGrokRunner = Callable[[str, str | None], Awaitable[CliOutput]]


class CliResponseError(RuntimeError):
    """Both subscription CLI responses failed the Graphiti JSON contract."""


class CliOutputDecodeError(RuntimeError):
    """A dispatched subscription CLI returned non-UTF-8 output."""


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
        self, *, provider: str, model: str, prompt: str, schema: str | None
    ) -> object: ...

    def after_cli_invocation(
        self,
        token: object,
        *,
        outcome: str,
        usage: dict[str, object],
    ) -> None: ...


def extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Graphiti CLI returned no JSON object")
    return raw[start : end + 1]


def run_cli(command: tuple[str, ...], *, timeout: int, cwd: str | None = None) -> str:
    name = os.path.basename(command[0])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=False,
            timeout=timeout,
            cwd=cwd,
            env=unprivileged_child_environment(),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{name} Graphiti LLM timed out") from None
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


async def run_cli_async(
    command: tuple[str, ...], *, timeout: int, cwd: str | None = None
) -> str:
    """Run a cancellable CLI child so the extraction deadline remains authoritative."""

    name = os.path.basename(command[0])
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=unprivileged_child_environment(),
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"{name} Graphiti LLM timed out") from None
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise RuntimeError(f"{name} Graphiti LLM failed")
    text = _decode_stdout(stdout, name=name)
    if not text.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return text


def _cursor_command(prompt: str) -> tuple[str, ...]:
    return (
        CURSOR_AGENT_BIN,
        "--print",
        "--mode",
        "ask",
        "--output-format",
        "json",
        "--sandbox",
        "enabled",
        "--trust",
        "--model",
        CURSOR_AGENT_MODEL_ID,
        prompt,
    )


def _grok_command(*, prompt: str, schema: str | None, cwd: str) -> tuple[str, ...]:
    path = os.path.join(cwd, "prompt.txt")
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
        "--no-subagents",
        "--reasoning-effort",
        GROK_CHAT_REASONING,
    ]
    if schema:
        command.extend(["--json-schema", schema])
    command.extend(["--output-format", "streaming-json"])
    return tuple(command)


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


def run_cursor_agent_llm(prompt: str) -> CliExecution:
    with tempfile.TemporaryDirectory(prefix="newsroom-cursor-graphiti-") as cwd:
        return parse_cursor_output(
            run_cli(
                _cursor_command(prompt),
                timeout=CLI_CALL_TIMEOUT_SECONDS,
                cwd=cwd,
            )
        )


async def run_cursor_agent_llm_async(prompt: str) -> CliExecution:
    with tempfile.TemporaryDirectory(prefix="newsroom-cursor-graphiti-") as cwd:
        return parse_cursor_output(
            await run_cli_async(
                _cursor_command(prompt),
                timeout=CLI_CALL_TIMEOUT_SECONDS,
                cwd=cwd,
            )
        )


def run_grok_llm(prompt: str, schema: str | None) -> CliExecution:
    with tempfile.TemporaryDirectory(prefix="newsroom-grok-graphiti-") as cwd:
        return parse_grok_stream_output(
            run_cli(
                _grok_command(prompt=prompt, schema=schema, cwd=cwd),
                timeout=CLI_CALL_TIMEOUT_SECONDS,
                cwd=cwd,
            )
        )


async def run_grok_llm_async(prompt: str, schema: str | None) -> CliExecution:
    with tempfile.TemporaryDirectory(prefix="newsroom-grok-graphiti-") as cwd:
        return parse_grok_stream_output(
            await run_cli_async(
                _grok_command(prompt=prompt, schema=schema, cwd=cwd),
                timeout=CLI_CALL_TIMEOUT_SECONDS,
                cwd=cwd,
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
) -> dict[str, object]:
    value: dict[str, object] = {
        "provider": provider,
        "model": model,
        "outcome": outcome,
        "usage": (
            dict(execution.usage) if execution is not None else unreported_cli_usage()
        ),
    }
    if failure is not None:
        value["failure"] = failure
    return value


async def run_cli_chain(
    *,
    prompt: str,
    schema: str | None,
    cursor_runner: CliRunner | AsyncCliRunner,
    grok_runner: GrokRunner | AsyncGrokRunner,
    invocations: list[dict[str, object]],
    invocation_observer: CliInvocationObserver | None = None,
) -> dict[str, Any]:
    """Execute cursor then Grok fallback while retaining every call outcome."""

    cursor_token = (
        None
        if invocation_observer is None
        else invocation_observer.before_cli_invocation(
            provider="cursor-agent-cli",
            model=CURSOR_AGENT_MODEL_ID,
            prompt=prompt,
            schema=schema,
        )
    )
    try:
        if inspect.iscoroutinefunction(cursor_runner):
            raw = await cursor_runner(prompt)
        else:
            raw = await asyncio.to_thread(cursor_runner, prompt)
    except asyncio.CancelledError as exc:
        cursor_usage = unreported_cli_usage()
        if invocation_observer is not None:
            invocation_observer.after_cli_invocation(
                cursor_token, outcome="CANCELLED", usage=cursor_usage
            )
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome="CANCELLED",
                failure=type(exc).__name__,
            )
        )
        raise
    except FileNotFoundError as exc:
        cursor_usage = no_provider_call_cli_usage()
        if invocation_observer is not None:
            invocation_observer.after_cli_invocation(
                cursor_token, outcome="EXECUTABLE_NOT_FOUND", usage=cursor_usage
            )
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome="EXECUTABLE_NOT_FOUND",
                execution=CliExecution(text="", usage=cursor_usage),
                failure=type(exc).__name__,
            )
        )
        payload = None
    except (RuntimeError, OSError) as exc:
        cursor_usage = unreported_cli_usage()
        if invocation_observer is not None:
            invocation_observer.after_cli_invocation(
                cursor_token, outcome="FAILED", usage=cursor_usage
            )
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome="FAILED",
                failure=type(exc).__name__,
            )
        )
        payload = None
    else:
        cursor_execution = _execution(cast(CliOutput, raw))
        payload = _parsed_object(cursor_execution.text)
        invocations.append(
            _invocation(
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                outcome=("COMPLETE" if payload is not None else "MALFORMED_OUTPUT"),
                execution=cursor_execution,
            )
        )
        if invocation_observer is not None:
            invocation_observer.after_cli_invocation(
                cursor_token,
                outcome=("COMPLETE" if payload is not None else "MALFORMED_OUTPUT"),
                usage=dict(cursor_execution.usage),
            )
    if payload is not None:
        return payload

    grok_token = (
        None
        if invocation_observer is None
        else invocation_observer.before_cli_invocation(
            provider="grok-build-cli",
            model=GROK_CHAT_MODEL_ID,
            prompt=prompt,
            schema=schema,
        )
    )
    try:
        if inspect.iscoroutinefunction(grok_runner):
            raw = await grok_runner(prompt, schema)
        else:
            raw = await asyncio.to_thread(grok_runner, prompt, schema)
    except asyncio.CancelledError as exc:
        grok_usage = unreported_cli_usage()
        if invocation_observer is not None:
            invocation_observer.after_cli_invocation(
                grok_token, outcome="CANCELLED", usage=grok_usage
            )
        invocations.append(
            _invocation(
                provider="grok-build-cli",
                model=GROK_CHAT_MODEL_ID,
                outcome="CANCELLED",
                failure=type(exc).__name__,
            )
        )
        raise
    except FileNotFoundError as exc:
        grok_usage = no_provider_call_cli_usage()
        if invocation_observer is not None:
            invocation_observer.after_cli_invocation(
                grok_token, outcome="EXECUTABLE_NOT_FOUND", usage=grok_usage
            )
        invocations.append(
            _invocation(
                provider="grok-build-cli",
                model=GROK_CHAT_MODEL_ID,
                outcome="EXECUTABLE_NOT_FOUND",
                execution=CliExecution(text="", usage=grok_usage),
                failure=type(exc).__name__,
            )
        )
        raise CliResponseError("Graphiti fallback CLI executable not found") from exc
    except (RuntimeError, OSError) as exc:
        grok_usage = unreported_cli_usage()
        if invocation_observer is not None:
            invocation_observer.after_cli_invocation(
                grok_token, outcome="FAILED", usage=grok_usage
            )
        invocations.append(
            _invocation(
                provider="grok-build-cli",
                model=GROK_CHAT_MODEL_ID,
                outcome="FAILED",
                failure=type(exc).__name__,
            )
        )
        raise CliResponseError("Graphiti fallback CLI failed") from exc
    grok_execution = _execution(cast(CliOutput, raw))
    payload = _parsed_object(grok_execution.text)
    invocations.append(
        _invocation(
            provider="grok-build-cli",
            model=GROK_CHAT_MODEL_ID,
            outcome="COMPLETE" if payload is not None else "MALFORMED_OUTPUT",
            execution=grok_execution,
        )
    )
    if invocation_observer is not None:
        invocation_observer.after_cli_invocation(
            grok_token,
            outcome="COMPLETE" if payload is not None else "MALFORMED_OUTPUT",
            usage=dict(grok_execution.usage),
        )
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
            del max_tokens, model_size
            prompt = messages_to_prompt(messages)
            schema = (
                json.dumps(response_model.model_json_schema())
                if response_model is not None
                else None
            )
            try:
                return await run_cli_chain(
                    prompt=prompt,
                    schema=schema,
                    cursor_runner=cursor,
                    grok_runner=grok,
                    invocations=self.invocations,
                    invocation_observer=invocation_observer,
                )
            except CliResponseError as exc:
                raise EmptyResponseError(str(exc)) from exc

    return CliChainGraphitiLlmClient()


__all__ = [
    "CliInvocationObserver",
    "CliOutputDecodeError",
    "CliResponseError",
    "build_cli_llm_client",
    "extract_json",
    "run_cli",
    "run_cli_chain",
    "run_cursor_agent_llm",
    "run_grok_llm",
]
