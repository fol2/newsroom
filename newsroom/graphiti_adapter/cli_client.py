"""Subscription CLI chat client used by Graphiti EVALUATION execution."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any, Awaitable, Protocol

from newsroom.graphiti_adapter.evaluation_packet import (
    CURSOR_AGENT_MODEL_ID,
    GROK_CHAT_MODEL_ID,
    GROK_CHAT_REASONING,
)

CURSOR_AGENT_BIN = os.environ.get(
    "NEWSROOM_CURSOR_AGENT_BIN", "/Users/jamesto/.local/bin/cursor-agent"
)
GROK_BIN = os.environ.get("NEWSROOM_GROK_BIN", "/Users/jamesto/.grok/bin/grok")
CLI_CALL_TIMEOUT_SECONDS = 80

CliRunner = Callable[[str], str]
GrokRunner = Callable[[str, str | None], str]
AsyncCliRunner = Callable[[str], Awaitable[str]]
AsyncGrokRunner = Callable[[str, str | None], Awaitable[str]]


class CliResponseError(RuntimeError):
    """Both subscription CLI responses failed the Graphiti JSON contract."""


class GraphitiCliClient(Protocol):
    invocations: list[dict[str, object]]

    async def _generate_response(
        self,
        messages: list[Any],
        response_model: type[Any] | None = None,
        max_tokens: int = 0,
        model_size: object = None,
    ) -> dict[str, Any]: ...


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
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{name} Graphiti LLM timed out") from None
    if result.returncode != 0:
        raise RuntimeError(f"{name} Graphiti LLM failed")
    if not result.stdout.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return result.stdout


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
    )
    try:
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
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
    text = stdout.decode("utf-8")
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
        "text",
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
        "--no-plan",
        "--max-turns",
        "3",
        "--no-subagents",
        "--reasoning-effort",
        GROK_CHAT_REASONING,
    ]
    if schema:
        command.extend(["--json-schema", schema])
    return tuple(command)


def run_cursor_agent_llm(prompt: str) -> str:
    with tempfile.TemporaryDirectory(prefix="newsroom-cursor-graphiti-") as cwd:
        return run_cli(
            _cursor_command(prompt),
            timeout=CLI_CALL_TIMEOUT_SECONDS,
            cwd=cwd,
        )


async def run_cursor_agent_llm_async(prompt: str) -> str:
    with tempfile.TemporaryDirectory(prefix="newsroom-cursor-graphiti-") as cwd:
        return await run_cli_async(
            _cursor_command(prompt),
            timeout=CLI_CALL_TIMEOUT_SECONDS,
            cwd=cwd,
        )


def run_grok_llm(prompt: str, schema: str | None) -> str:
    with tempfile.TemporaryDirectory(prefix="newsroom-grok-graphiti-") as cwd:
        return run_cli(
            _grok_command(prompt=prompt, schema=schema, cwd=cwd),
            timeout=CLI_CALL_TIMEOUT_SECONDS,
            cwd=cwd,
        )


async def run_grok_llm_async(prompt: str, schema: str | None) -> str:
    with tempfile.TemporaryDirectory(prefix="newsroom-grok-graphiti-") as cwd:
        return await run_cli_async(
            _grok_command(prompt=prompt, schema=schema, cwd=cwd),
            timeout=CLI_CALL_TIMEOUT_SECONDS,
            cwd=cwd,
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


async def run_cli_chain(
    *,
    prompt: str,
    schema: str | None,
    cursor_runner: CliRunner | AsyncCliRunner,
    grok_runner: GrokRunner | AsyncGrokRunner,
    invocations: list[dict[str, object]],
) -> dict[str, Any]:
    """Execute cursor then Grok fallback while retaining every call outcome."""

    try:
        if inspect.iscoroutinefunction(cursor_runner):
            raw = await cursor_runner(prompt)
        else:
            raw = await asyncio.to_thread(cursor_runner, prompt)
    except (RuntimeError, OSError) as exc:
        invocations.append(
            {
                "provider": "cursor-agent-cli",
                "model": CURSOR_AGENT_MODEL_ID,
                "outcome": "FAILED",
                "failure": type(exc).__name__,
            }
        )
        payload = None
    else:
        payload = _parsed_object(raw)
        invocations.append(
            {
                "provider": "cursor-agent-cli",
                "model": CURSOR_AGENT_MODEL_ID,
                "outcome": "COMPLETE" if payload is not None else "MALFORMED_OUTPUT",
            }
        )
    if payload is not None:
        return payload

    try:
        if inspect.iscoroutinefunction(grok_runner):
            raw = await grok_runner(prompt, schema)
        else:
            raw = await asyncio.to_thread(grok_runner, prompt, schema)
    except (RuntimeError, OSError) as exc:
        invocations.append(
            {
                "provider": "grok-build-cli",
                "model": GROK_CHAT_MODEL_ID,
                "outcome": "FAILED",
                "failure": type(exc).__name__,
            }
        )
        raise CliResponseError("Graphiti fallback CLI failed") from exc
    payload = _parsed_object(raw)
    invocations.append(
        {
            "provider": "grok-build-cli",
            "model": GROK_CHAT_MODEL_ID,
            "outcome": "COMPLETE" if payload is not None else "MALFORMED_OUTPUT",
        }
    )
    if payload is None:
        raise CliResponseError("Graphiti CLI JSON was not an object")
    return payload


def build_cli_llm_client(
    *,
    cursor_runner: CliRunner | None = None,
    grok_runner: GrokRunner | None = None,
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
                LLMConfig(model=CURSOR_AGENT_MODEL_ID, small_model=CURSOR_AGENT_MODEL_ID),
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
                )
            except CliResponseError as exc:
                raise EmptyResponseError(str(exc)) from exc

    return CliChainGraphitiLlmClient()


__all__ = [
    "build_cli_llm_client",
    "CliResponseError",
    "extract_json",
    "run_cli",
    "run_cursor_agent_llm",
    "run_grok_llm",
    "run_cli_chain",
]
