"""F1 fake-SDK matrix for the Graphiti Cursor SDK transport (#807)."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.graphiti_adapter.cli_client import (
    CliResponseError,
    run_cli_chain,
    run_cursor_agent_llm,
)
from newsroom.graphiti_adapter.cursor_transport import (
    CURSOR_SDK_AUTH_SOURCE,
    PINNED_MODEL,
    PINNED_SDK_VERSION,
    CliPredispatchRefusal,
    CursorSdkBoundedFailure,
    CursorSdkCleanupError,
    CursorSdkError,
    CursorSdkRunRequest,
    CursorToolCallViolation,
    OfficialCursorSdkRuntime,
    bind_cursor_sdk_runtime,
    qualify_cursor_sdk,
    run_cursor_transport,
)
from newsroom.graphiti_adapter.usage_meter import cursor_sdk_usage, unreported_cli_usage

_ADAPTER = Path(__file__).resolve().parents[1] / "graphiti_adapter"
_GRAPHITI_JSON = '{"entities":[],"entity_resolutions":[],"edges":[]}'


@dataclass
class FakeUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.total_tokens == 0:
            self.total_tokens = (
                self.input_tokens
                + self.output_tokens
                + self.cache_read_tokens
                + self.cache_write_tokens
            )


@dataclass
class FakeMessage:
    type: str
    usage: object | None = None
    request_id: str | None = None
    call_id: str | None = None
    name: str | None = None
    status: str | None = None
    text: str = ""
    message: object | None = None


@dataclass
class FakeTerminal:
    status: str = "finished"
    result: str = ""
    usage: object | None = None
    model: object | None = None
    duration_ms: int | None = 12
    error: object | None = None


@dataclass
class FakeRun:
    id: str = "run-807"
    agent_id: str = "agent-807"
    status: str = "running"
    model: object | None = field(default_factory=lambda: SimpleNamespace(id=PINNED_MODEL))
    usage: object | None = None
    duration_ms: int | None = None
    messages: tuple[object, ...] = ()
    terminal: FakeTerminal = field(default_factory=FakeTerminal)
    close_error: Exception | None = None
    cancel_count: int = 0
    close_count: int = 0
    stream_error: Exception | None = None

    def stream(self) -> Iterator[object]:
        if self.stream_error is not None:
            raise self.stream_error
        yield from self.messages

    def wait(self) -> object:
        if self.status == "running":
            self.status = self.terminal.status
        return self.terminal

    def cancel(self) -> None:
        self.cancel_count += 1
        self.status = "cancelled"
        self.terminal.status = "cancelled"

    def close(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


@dataclass
class FakeRuntime:
    sdk_version: str = PINNED_SDK_VERSION
    models: tuple[str, ...] = (PINNED_MODEL,)
    run: FakeRun = field(default_factory=FakeRun)
    start_error: Exception | None = None
    requests: list[CursorSdkRunRequest] = field(default_factory=list)
    empty_non_git_cwds: list[bool] = field(default_factory=list)

    def list_model_ids(self, *, api_key: str) -> tuple[str, ...]:
        del api_key
        return self.models

    def start_run(self, request: CursorSdkRunRequest) -> FakeRun:
        cwd = Path(request.cwd)
        self.empty_non_git_cwds.append(
            cwd.is_dir() and not any(cwd.iterdir()) and not (cwd / ".git").exists()
        )
        self.requests.append(request)
        if self.start_error is not None:
            raise self.start_error
        return self.run


def _assistant(text: str) -> FakeMessage:
    return FakeMessage(
        type="assistant",
        message=SimpleNamespace(content=(SimpleNamespace(type="text", text=text),)),
    )


def _bind(monkeypatch: pytest.MonkeyPatch, runtime: FakeRuntime) -> FakeRuntime:
    monkeypatch.setenv(CURSOR_SDK_AUTH_SOURCE, "crsr_test_key")
    previous = bind_cursor_sdk_runtime(runtime)
    monkeypatch.setattr(
        "newsroom.graphiti_adapter.cursor_transport._bound_runtime",
        runtime,
    )
    del previous
    return runtime


def _streamed_and_terminal() -> tuple[FakeRuntime, FakeUsage]:
    usage = FakeUsage(input_tokens=11, output_tokens=7, cache_read_tokens=2)
    runtime = FakeRuntime(
        run=FakeRun(
            messages=(
                FakeMessage(type="request", request_id="req-807"),
                FakeMessage(type="usage", usage=usage),
                _assistant(_GRAPHITI_JSON),
            ),
            terminal=FakeTerminal(
                result=_GRAPHITI_JSON,
                usage=usage,
                model=SimpleNamespace(id=PINNED_MODEL),
            ),
            usage=usage,
        )
    )
    return runtime, usage


def test_streamed_and_terminal_usage_match(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, usage = _streamed_and_terminal()
    _bind(monkeypatch, runtime)
    execution = run_cursor_transport(
        prompt="extract",
        max_tokens=64,
        timeout=5,
    )

    assert execution.text == _GRAPHITI_JSON
    assert execution.usage == cursor_sdk_usage(usage)
    assert execution.usage["usage_basis"] == "PROVIDER_REPORTED"
    assert execution.request_id == "req-807"
    assert execution.run_id == "run-807"
    assert execution.agent_id == "agent-807"
    assert runtime.requests[0].cwd
    assert runtime.empty_non_git_cwds == [True]


def test_terminal_only_usage_is_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = FakeUsage(input_tokens=4, output_tokens=3)
    runtime = _bind(
        monkeypatch,
        FakeRuntime(
            run=FakeRun(
                messages=(_assistant(_GRAPHITI_JSON),),
                terminal=FakeTerminal(result=_GRAPHITI_JSON, usage=terminal),
                usage=terminal,
            )
        ),
    )

    execution = run_cursor_transport(prompt="extract", max_tokens=32, timeout=5)

    assert execution.usage == cursor_sdk_usage(terminal)
    assert execution.usage["input_tokens"] == 4
    assert len(runtime.requests) == 1


def test_missing_usage_stays_unreported(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind(
        monkeypatch,
        FakeRuntime(
            run=FakeRun(
                messages=(_assistant(_GRAPHITI_JSON),),
                terminal=FakeTerminal(result=_GRAPHITI_JSON, usage=None),
            )
        ),
    )

    execution = run_cursor_transport(prompt="extract", max_tokens=32, timeout=5)

    assert execution.usage == unreported_cli_usage()
    assert execution.usage["input_tokens"] is None
    assert execution.usage["total_tokens"] is None


def test_pre_send_refusal_is_zero_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = FakeRuntime(models=("other-model",))
    _bind(monkeypatch, runtime)
    started: list[str] = []

    with pytest.raises(CliPredispatchRefusal, match="composer-2.5"):
        run_cursor_transport(
            prompt="extract",
            max_tokens=32,
            timeout=5,
            dispatch_started=lambda: started.append("sent"),
        )

    assert started == []
    assert runtime.requests == []


def test_missing_api_key_is_zero_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = FakeRuntime()
    bind_cursor_sdk_runtime(runtime)
    monkeypatch.delenv(CURSOR_SDK_AUTH_SOURCE, raising=False)
    started: list[str] = []

    with pytest.raises(CliPredispatchRefusal, match="CURSOR_API_KEY"):
        run_cursor_transport(
            prompt="extract",
            max_tokens=32,
            timeout=5,
            dispatch_started=lambda: started.append("sent"),
        )

    assert started == []
    assert runtime.requests == []
    bind_cursor_sdk_runtime(None)


def test_run_identity_commits_dispatch_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _usage = _streamed_and_terminal()
    _bind(monkeypatch, runtime)
    started: list[str] = []

    execution = run_cursor_agent_llm(
        "extract",
        max_tokens=32,
        dispatch_started=lambda: started.append(runtime.run.id),
    )

    assert started == ["run-807"]
    assert execution.sdk_run_id == "run-807"
    assert execution.sdk_agent_id == "agent-807"
    assert execution.sdk_request_id == "req-807"
    assert len(runtime.requests) == 1


def test_tool_call_cancels_once_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = FakeRun(
        messages=(
            FakeMessage(type="request", request_id="req-tool"),
            FakeMessage(type="tool_call", call_id="call-1", name="shell", status="running"),
            _assistant(_GRAPHITI_JSON),
        ),
        terminal=FakeTerminal(status="cancelled", usage=FakeUsage(3, 1)),
    )
    runtime = _bind(monkeypatch, FakeRuntime(run=run))

    with pytest.raises(CursorToolCallViolation):
        run_cursor_transport(prompt="extract", max_tokens=32, timeout=5)

    assert run.cancel_count == 1
    assert len(runtime.requests) == 1


def test_malformed_graphiti_output_remains_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _bind(
        monkeypatch,
        FakeRuntime(
            run=FakeRun(
                messages=(_assistant("not-json"),),
                terminal=FakeTerminal(result="not-json", usage=FakeUsage(2, 1)),
            )
        ),
    )
    invocations: list[dict[str, object]] = []

    with pytest.raises(CliResponseError):
        asyncio.run(
            run_cli_chain(
                prompt="prompt",
                schema=None,
                cursor_runner=run_cursor_agent_llm,
                grok_runner=lambda *_args, **_values: pytest.fail("fallback ran"),
                invocations=invocations,
                fallback_permitted=False,
            )
        )

    assert invocations[0]["outcome"] == "MALFORMED_OUTPUT"
    assert invocations[0]["sdk_run_id"] == "run-807"
    assert len(runtime.requests) == 1


@pytest.mark.parametrize(
    ("error", "error_class"),
    [
        (RuntimeError("network connect refused"), "NETWORK"),
        (type("RateLimitError", (Exception,), {})("rate limit"), "RATE_LIMIT"),
        (RuntimeError("model composer-2.5 is unavailable"), "MODEL_UNAVAILABLE"),
        (RuntimeError("upstream server exploded"), "SDK_ERROR"),
    ],
)
def test_typed_sdk_errors_map_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    error_class: str,
) -> None:
    runtime = _bind(monkeypatch, FakeRuntime(start_error=error))

    with pytest.raises((CursorSdkError, CliPredispatchRefusal)) as caught:
        run_cursor_transport(prompt="extract", max_tokens=32, timeout=5)

    if isinstance(caught.value, CursorSdkError):
        assert caught.value.error_class == error_class
    assert len(runtime.requests) == 1


def test_timeout_retains_partial_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    partial = FakeUsage(input_tokens=9, output_tokens=1)
    run = FakeRun(
        messages=(
            FakeMessage(type="usage", usage=partial),
            _assistant('{"partial":true}'),
        ),
        terminal=FakeTerminal(status="cancelled", usage=partial),
    )
    runtime = _bind(monkeypatch, FakeRuntime(run=run))
    clock = iter((0.0, 0.0, 10.0))
    monkeypatch.setattr(
        "newsroom.graphiti_adapter.cursor_transport.time.monotonic",
        lambda: next(clock, 10.0),
    )

    with pytest.raises(CursorSdkBoundedFailure) as caught:
        run_cursor_transport(prompt="extract", max_tokens=32, timeout=1)

    assert caught.value.error_class == "TIMEOUT"
    assert caught.value.usage == cursor_sdk_usage(partial)
    assert run.cancel_count == 1
    assert len(runtime.requests) == 1


def test_output_bound_retains_partial_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    partial = FakeUsage(input_tokens=5, output_tokens=8)
    huge = "x" * 200_000
    run = FakeRun(
        messages=(
            FakeMessage(type="usage", usage=partial),
            _assistant(huge),
        ),
        terminal=FakeTerminal(status="cancelled", usage=partial),
    )
    runtime = _bind(monkeypatch, FakeRuntime(run=run))

    with pytest.raises(CursorSdkBoundedFailure) as caught:
        run_cursor_transport(prompt="extract", max_tokens=1, timeout=5)

    assert caught.value.error_class == "OUTPUT_BOUND"
    assert caught.value.usage == cursor_sdk_usage(partial)
    assert run.cancel_count == 1
    assert len(runtime.requests) == 1


def test_cleanup_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    run = FakeRun(
        messages=(_assistant(_GRAPHITI_JSON),),
        terminal=FakeTerminal(result=_GRAPHITI_JSON, usage=FakeUsage(1, 1)),
        close_error=RuntimeError("store unlink failed"),
    )
    _bind(monkeypatch, FakeRuntime(run=run))

    with pytest.raises(CursorSdkCleanupError) as caught:
        run_cursor_transport(prompt="extract", max_tokens=32, timeout=5)

    assert caught.value.error_class == "CLEANUP"
    assert caught.value.execution is not None
    assert caught.value.execution.text == _GRAPHITI_JSON


def test_no_sdk_controller_or_fallback_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _bind(
        monkeypatch,
        FakeRuntime(start_error=RuntimeError("transient network connect failed")),
    )
    invocations: list[dict[str, object]] = []

    with pytest.raises(CliResponseError):
        asyncio.run(
            run_cli_chain(
                prompt="prompt",
                schema=None,
                cursor_runner=run_cursor_agent_llm,
                grok_runner=lambda *_args, **_values: pytest.fail("fallback ran"),
                invocations=invocations,
                fallback_permitted=True,
            )
        )

    assert invocations[0]["outcome"] == "FAILED"
    assert len(runtime.requests) == 1


def test_wrong_sdk_version_is_predispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = FakeRuntime(sdk_version="1.0.28")
    _bind(monkeypatch, runtime)

    with pytest.raises(CliPredispatchRefusal, match="pinned lock"):
        qualify_cursor_sdk(runtime=runtime, api_key="crsr_test_key")
    assert runtime.requests == []


def test_official_runtime_uses_supported_sdk_api() -> None:
    source = ast.parse(Path(OfficialCursorSdkRuntime.__init__.__code__.co_filename).read_text())
    text = (_ADAPTER / "cursor_transport.py").read_text(encoding="utf-8")
    assert "launch_bridge" in text
    assert "allow_api_key_env_fallback=False" in text
    assert "max_retries=_PROCESS_CLIENT_MAX_RETRIES" in text
    assert "tools=[]" in text
    assert "disallowed_tools=list(CURSOR_SDK_DISALLOWED_TOOLS)" in text
    assert "mcp_servers={}" in text
    assert "agents={}" in text
    assert "setting_sources" not in ast.unparse(
        next(
            node
            for node in source.body
            if isinstance(node, ast.ClassDef) and node.name == "OfficialCursorSdkRuntime"
        )
    )


def test_production_graphiti_cursor_path_has_no_cli_harness() -> None:
    transport = (_ADAPTER / "cursor_transport.py").read_text(encoding="utf-8")
    client = (_ADAPTER / "cli_client.py").read_text(encoding="utf-8")
    forbidden = (
        "cursor-agent",
        "run_bounded_process",
        "login.keychain",
        "Keychain",
        "/Users/jamesto/.local/bin/cursor-agent",
        "/Users/jamesto/.local/share/cursor-agent",
        "parse_cursor_output",
    )
    for token in forbidden:
        assert token not in transport
    cursor_runner = ast.parse(client)
    for node in cursor_runner.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "run_cursor_agent_llm",
            "run_cursor_agent_llm_async",
        }:
            text = ast.unparse(node)
            assert "run_cursor_transport" in text
            assert "cursor-agent" not in text
            assert "run_bounded_process" not in text
            assert "security" not in text
    assert "import newsroom.graphiti_adapter.cli_process" not in transport
    assert "from newsroom.graphiti_adapter.cli_process" not in transport
    assert "stderr" not in transport
