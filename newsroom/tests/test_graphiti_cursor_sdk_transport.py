"""F1 fake-SDK matrix for the Graphiti Cursor SDK transport (#807)."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.control_plane.graphiti import GraphitiModelUsageObserver
from newsroom.control_plane.model_usage import (
    ModelUsageAdmissionError,
    ModelUsageService,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.graphiti_adapter.cli_client import (
    CliDispatchMarkerError,
    CliResponseError,
    run_cli_chain,
    run_cursor_agent_llm,
)
from newsroom.graphiti_adapter.cursor_transport import (
    CURSOR_SDK_AUTH_SOURCE,
    PINNED_MODEL,
    PINNED_SDK_VERSION,
    CliPredispatchRefusal,
    CursorSdkAmbiguousDispatch,
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
from newsroom.graphiti_adapter.usage_meter import (
    cursor_sdk_usage,
    no_provider_call_cli_usage,
    unreported_cli_usage,
)

_ADAPTER = Path(__file__).resolve().parents[1] / "graphiti_adapter"
_GRAPHITI_JSON = '{"entities":[],"entity_resolutions":[],"edges":[]}'
_TEST_IDEMPOTENCY_KEY = "sha256:" + ("a" * 64)
_OBSERVER_T0 = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


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

    def start_run(
        self,
        request: CursorSdkRunRequest,
        *,
        dispatch_started: Callable[[], None] | None = None,
    ) -> FakeRun:
        cwd = Path(request.cwd)
        self.empty_non_git_cwds.append(
            cwd.is_dir() and not any(cwd.iterdir()) and not (cwd / ".git").exists()
        )
        if dispatch_started is not None:
            dispatch_started()
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


def _observer_fixture(
    tmp_path: Path,
) -> tuple[ModelUsageService, GraphitiModelUsageObserver, datetime]:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-sdk-807",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=_OBSERVER_T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-sdk-807",
        graphiti_attempt_id="ingest-sdk-807:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: _OBSERVER_T0 + timedelta(seconds=10),
        owner_stop_check=lambda: None,
    )
    return service, observer, _OBSERVER_T0


def _assert_observed_ambiguous_terminal(
    *,
    service: ModelUsageService,
    runtime: FakeRuntime,
    invocations: list[dict[str, object]],
    observed_at: datetime,
    expected_outcome: str = "AMBIGUOUS_DISPATCH",
) -> None:
    assert len(invocations) == 1
    assert invocations[0]["outcome"] == expected_outcome
    assert invocations[0]["usage"]["usage_basis"] == "UNREPORTED"
    assert len(runtime.requests) == 1
    leaves = service.query(
        start=observed_at, end=observed_at + timedelta(minutes=1)
    )["leaves"]
    assert len(leaves) == 1
    leaf = leaves[0]
    assert leaf["transport_dispatch_observed"] is True
    assert leaf["pre_dispatch_zero_proved"] is False
    assert leaf["dispatch_at"] is not None
    assert leaf["usage_status"] == "UNREPORTED"
    assert leaf["request_digest"] == runtime.requests[0].idempotency_key
    assert leaf["terminal_digest"] is not None


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
        idempotency_key=_TEST_IDEMPOTENCY_KEY,
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

    execution = run_cursor_transport(
        prompt="extract", max_tokens=32, timeout=5, idempotency_key=_TEST_IDEMPOTENCY_KEY
    )

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

    execution = run_cursor_transport(
        prompt="extract", max_tokens=32, timeout=5, idempotency_key=_TEST_IDEMPOTENCY_KEY
    )

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
            idempotency_key=_TEST_IDEMPOTENCY_KEY,
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
            idempotency_key=_TEST_IDEMPOTENCY_KEY,
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
        idempotency_key=_TEST_IDEMPOTENCY_KEY,
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
        run_cursor_transport(
            prompt="extract", max_tokens=32, timeout=5, idempotency_key=_TEST_IDEMPOTENCY_KEY
        )

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
                idempotency_key=_TEST_IDEMPOTENCY_KEY,
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
        run_cursor_transport(
            prompt="extract", max_tokens=32, timeout=5, idempotency_key=_TEST_IDEMPOTENCY_KEY
        )

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
        run_cursor_transport(
            prompt="extract", max_tokens=32, timeout=1, idempotency_key=_TEST_IDEMPOTENCY_KEY
        )

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
        run_cursor_transport(
            prompt="extract", max_tokens=1, timeout=5, idempotency_key=_TEST_IDEMPOTENCY_KEY
        )

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
        run_cursor_transport(
            prompt="extract", max_tokens=32, timeout=5, idempotency_key=_TEST_IDEMPOTENCY_KEY
        )

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
                idempotency_key=_TEST_IDEMPOTENCY_KEY,
            )
        )

    assert invocations[0]["outcome"] == "AMBIGUOUS_DISPATCH"
    assert invocations[0]["usage"]["usage_basis"] == "UNREPORTED"
    assert len(runtime.requests) == 1
    assert runtime.requests[0].idempotency_key == _TEST_IDEMPOTENCY_KEY


def test_governed_request_digest_reaches_sdk_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_digest = "sha256:" + ("b" * 64)
    runtime = _bind(
        monkeypatch,
        FakeRuntime(
            run=FakeRun(
                messages=(_assistant(_GRAPHITI_JSON),),
                terminal=FakeTerminal(result=_GRAPHITI_JSON, usage=FakeUsage(1, 1)),
            )
        ),
    )

    class Observer:
        def before_cli_invocation(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(request_digest=request_digest)

        def transport_dispatch_started(self, _token: object) -> None:
            return None

        def after_cli_invocation(
            self, _token: object, *, outcome: str, usage: dict[str, object]
        ) -> dict[str, str]:
            return {}

    asyncio.run(
        run_cli_chain(
            prompt="prompt",
            schema=None,
            cursor_runner=run_cursor_agent_llm,
            grok_runner=lambda *_args, **_values: pytest.fail("fallback ran"),
            invocations=[],
            invocation_observer=Observer(),
            fallback_permitted=False,
        )
    )

    assert runtime.requests[0].idempotency_key == request_digest


def test_same_prompt_different_governed_digests_use_distinct_idempotency_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _bind(
        monkeypatch,
        FakeRuntime(
            run=FakeRun(
                messages=(_assistant(_GRAPHITI_JSON),),
                terminal=FakeTerminal(result=_GRAPHITI_JSON, usage=FakeUsage(1, 1)),
            )
        ),
    )
    digests = ("sha256:" + ("c" * 64), "sha256:" + ("d" * 64))

    class Observer:
        def __init__(self, request_digest: str) -> None:
            self._request_digest = request_digest

        def before_cli_invocation(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(request_digest=self._request_digest)

        def transport_dispatch_started(self, _token: object) -> None:
            return None

        def after_cli_invocation(
            self, _token: object, *, outcome: str, usage: dict[str, object]
        ) -> dict[str, str]:
            return {}

    for request_digest in digests:
        asyncio.run(
            run_cli_chain(
                prompt="same prompt",
                schema=None,
                cursor_runner=run_cursor_agent_llm,
                grok_runner=lambda *_args, **_values: _GRAPHITI_JSON,
                invocations=[],
                invocation_observer=Observer(request_digest),
                fallback_permitted=False,
            )
        )

    assert [item.idempotency_key for item in runtime.requests] == list(digests)


def test_missing_run_id_after_send_is_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind(
        monkeypatch,
        FakeRuntime(run=FakeRun(id="", agent_id="agent-807")),
    )

    with pytest.raises(CursorSdkAmbiguousDispatch) as caught:
        run_cursor_transport(
            prompt="extract",
            max_tokens=32,
            timeout=5,
            idempotency_key=_TEST_IDEMPOTENCY_KEY,
        )

    assert caught.value.error_class == "MISSING_RUN_ID"
    assert caught.value.usage["usage_basis"] == "UNREPORTED"


def test_missing_agent_id_after_send_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind(
        monkeypatch,
        FakeRuntime(run=FakeRun(id="run-807", agent_id="")),
    )

    with pytest.raises(CursorSdkAmbiguousDispatch) as caught:
        run_cursor_transport(
            prompt="extract",
            max_tokens=32,
            timeout=5,
            idempotency_key=_TEST_IDEMPOTENCY_KEY,
        )

    assert caught.value.error_class == "MISSING_AGENT_ID"
    assert caught.value.usage["usage_basis"] == "UNREPORTED"


def test_wrong_sdk_version_is_predispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = FakeRuntime(sdk_version="1.0.28")
    _bind(monkeypatch, runtime)

    with pytest.raises(CliPredispatchRefusal, match="pinned lock"):
        qualify_cursor_sdk(runtime=runtime, api_key="crsr_test_key")
    assert runtime.requests == []


def test_dispatch_marker_precedes_sdk_send(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    runtime = _bind(
        monkeypatch,
        FakeRuntime(start_error=RuntimeError("network connect refused")),
    )

    with pytest.raises(CursorSdkAmbiguousDispatch):
        run_cursor_transport(
            prompt="extract",
            max_tokens=32,
            timeout=5,
            idempotency_key=_TEST_IDEMPOTENCY_KEY,
            dispatch_started=lambda: order.append("marker"),
        )

    assert order == ["marker"]
    assert len(runtime.requests) == 1


@pytest.mark.parametrize(
    ("runtime_factory", "expected_outcome"),
    [
        (
            lambda: FakeRuntime(
                start_error=RuntimeError("network connect refused")
            ),
            "AMBIGUOUS_DISPATCH",
        ),
        (
            lambda: FakeRuntime(run=FakeRun(id="", agent_id="agent-807")),
            "AMBIGUOUS_DISPATCH",
        ),
        (
            lambda: FakeRuntime(run=FakeRun(id="run-807", agent_id="")),
            "AMBIGUOUS_DISPATCH",
        ),
    ],
)
def test_observed_sdk_ambiguous_terminal_retains_dispatch_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime_factory: object,
    expected_outcome: str,
) -> None:
    service, observer, observed_at = _observer_fixture(tmp_path)
    runtime = _bind(monkeypatch, runtime_factory())
    invocations: list[dict[str, object]] = []

    with pytest.raises(CliResponseError, match="fallback is disabled"):
        asyncio.run(
            run_cli_chain(
                prompt="prompt",
                schema=None,
                cursor_runner=run_cursor_agent_llm,
                grok_runner=lambda *_args, **_values: pytest.fail("fallback ran"),
                invocations=invocations,
                invocation_observer=observer,
                fallback_permitted=False,
            )
        )

    _assert_observed_ambiguous_terminal(
        service=service,
        runtime=runtime,
        invocations=invocations,
        observed_at=observed_at,
        expected_outcome=expected_outcome,
    )


def test_conflicting_caller_idempotency_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _bind(monkeypatch, FakeRuntime())
    _, observer, _ = _observer_fixture(tmp_path)

    with pytest.raises(CliDispatchMarkerError, match="conflicts with caller"):
        asyncio.run(
            run_cli_chain(
                prompt="prompt",
                schema=None,
                cursor_runner=run_cursor_agent_llm,
                grok_runner=lambda *_args, **_values: pytest.fail("fallback ran"),
                invocations=[],
                invocation_observer=observer,
                fallback_permitted=False,
                idempotency_key=_TEST_IDEMPOTENCY_KEY,
            )
        )


def test_observed_dispatch_fence_refusal_is_proved_zero_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-sdk-fence-refusal",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=_OBSERVER_T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-sdk-fence-refusal",
        graphiti_attempt_id="ingest-sdk-fence-refusal:1",
    )
    service.open_envelope(envelope)

    stop_calls = 0

    def refuse_dispatch() -> None:
        nonlocal stop_calls
        stop_calls += 1
        if stop_calls > 1:
            raise ModelUsageAdmissionError("owner stop during dispatch")

    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: _OBSERVER_T0 + timedelta(seconds=10),
        owner_stop_check=refuse_dispatch,
    )
    runtime = _bind(monkeypatch, FakeRuntime())
    invocations: list[dict[str, object]] = []

    with pytest.raises(ModelUsageAdmissionError, match="owner stop during dispatch"):
        asyncio.run(
            run_cli_chain(
                prompt="prompt",
                schema=None,
                cursor_runner=run_cursor_agent_llm,
                grok_runner=lambda *_args, **_values: pytest.fail("fallback ran"),
                invocations=invocations,
                invocation_observer=observer,
                fallback_permitted=True,
            )
        )

    assert len(invocations) == 1
    assert invocations[0]["outcome"] == "DISPATCH_FENCE_REFUSED"
    assert invocations[0]["usage"] == no_provider_call_cli_usage()
    assert runtime.requests == []
    leaves = service.query(
        start=_OBSERVER_T0, end=_OBSERVER_T0 + timedelta(minutes=1)
    )["leaves"]
    assert len(leaves) == 1
    leaf = leaves[0]
    assert leaf["invocation_outcome"] == "DISPATCH_FENCE_REFUSED"
    assert leaf["transport_dispatch_observed"] is False
    assert leaf["pre_dispatch_zero_proved"] is True
    assert leaf["dispatch_at"] is None
    assert invocations[0]["usage"]["usage_basis"] == "NO_PROVIDER_CALL"

    close_count = 0
    send_called = False

    class StubAgent:
        def close(self) -> None:
            nonlocal close_count
            close_count += 1

        def send(self, *_args: object, **_kwargs: object) -> object:
            nonlocal send_called
            send_called = True
            raise AssertionError("agent.send must not run after dispatch fence refusal")

    class StubAgents:
        def create(self, _options: object) -> StubAgent:
            return StubAgent()

    official = OfficialCursorSdkRuntime()
    (tmp_path / "cwd").mkdir()
    (tmp_path / "store").mkdir()
    monkeypatch.setattr(official, "_client", SimpleNamespace(agents=StubAgents()))
    try:
        with pytest.raises(CliDispatchMarkerError, match="durable dispatch observation"):
            official.start_run(
                CursorSdkRunRequest(
                    prompt="extract",
                    api_key="crsr_test_key",
                    cwd=str(tmp_path / "cwd"),
                    store=str(tmp_path / "store"),
                    timeout=5,
                    max_output_bytes=65536,
                    idempotency_key=_TEST_IDEMPOTENCY_KEY,
                ),
                dispatch_started=lambda: (_ for _ in ()).throw(
                    CliDispatchMarkerError("durable dispatch observation failed")
                ),
            )
    finally:
        official.close()

    assert close_count == 1
    assert send_called is False


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
    assert "idempotency_key=request.idempotency_key" in text
    assert text.index("dispatch_started()") < text.index("agent.send(")
    assert "setting_sources" not in ast.unparse(
        next(
            node
            for node in source.body
            if isinstance(node, ast.ClassDef) and node.name == "OfficialCursorSdkRuntime"
        )
    )


def test_official_runtime_constructs_and_closes_without_provider_calls() -> None:
    import importlib.metadata
    import shutil

    pytest.importorskip("cursor_sdk")
    assert importlib.metadata.version("cursor-sdk") == PINNED_SDK_VERSION

    runtime = OfficialCursorSdkRuntime()
    root = runtime._root
    try:
        assert root.is_dir()
        assert (root / "workspace").is_dir()
        assert (root / "store").is_dir()
        assert (root / "bridge-state").is_dir()
    finally:
        runtime.close()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        assert not root.exists()


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
