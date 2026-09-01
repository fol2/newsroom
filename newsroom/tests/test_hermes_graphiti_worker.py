from __future__ import annotations

import json

import pytest

from newsroom.control_plane.graphiti_events import GraphitiProcessResult


def _arguments(*extra: str) -> list[str]:
    return [
        "--event-id",
        "event-1",
        "--ledger-seq",
        "7",
        "--max-reserved-gbp-microunits",
        "500000",
        *extra,
    ]


def test_exact_event_is_preflighted_time_bounded_and_fallback_free(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    captured: dict[str, object] = {}

    class Runner:
        def __init__(self, *, fallback_permitted: bool) -> None:
            captured["fallback_permitted"] = fallback_permitted

    def qualify(**kwargs: object) -> dict[str, object]:
        captured["preflight"] = kwargs
        return {
            "evidence_digest": "sha256:" + "a" * 64,
            "resolved_units": [{"ingest_id": "ingest-1"}],
        }

    def consume(**kwargs: object) -> GraphitiProcessResult:
        captured["consume"] = kwargs
        return GraphitiProcessResult("event-1", 7, "TERMINAL", 1)

    monkeypatch.setattr(worker, "EvaluationGraphitiRunner", Runner)
    monkeypatch.setattr(worker, "qualify_fresh_graphiti_event", qualify)
    monkeypatch.setattr(worker, "consume_next_graphiti_event", consume)
    monkeypatch.setattr(worker, "ensure_control_plane_state_root", lambda: None)

    assert worker.main(_arguments("--max-runtime-seconds", "45")) == 0

    assert captured["fallback_permitted"] is False
    assert captured["preflight"] == {
        "proving_store": str(worker.CANONICAL_PROVING_STORE),
        "unpublished_store": str(worker.CANONICAL_UNPUBLISHED_STORE),
        "event_id": "event-1",
        "ledger_seq": 7,
    }
    consumed = captured["consume"]
    assert isinstance(consumed, dict)
    assert consumed["event_id"] == "event-1"
    assert consumed["require_fresh"] is True
    assert consumed["recover_model_usage"] is False
    assert consumed["max_dispatch_seconds"] == 45
    assert consumed["prepared_event_preflight"] == {
        "evidence_digest": "sha256:" + "a" * 64,
        "resolved_units": [{"ingest_id": "ingest-1"}],
    }
    assert consumed["max_reserved_gbp_microunits"] == 500000
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [body["event"] for body in bodies] == [
        "GRAPHITI_EVENT_PREFLIGHT",
        "GRAPHITI_EVENT_RESULT",
        "GRAPHITI_WORKER_STOPPED",
    ]
    assert bodies[-1]["reason"] == "EXACT_EVENT_TERMINAL"
    assert bodies[-1]["completed_events"] == 1


def test_exact_event_not_claimed_is_fail_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    assert worker._run(consume=lambda: None) == 2
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert bodies[-1]["reason"] == "EXACT_EVENT_NOT_CLAIMED"


def test_exact_event_execution_refusal_is_structured_and_terminal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    assert worker._run(consume=lambda: (_ for _ in ()).throw(ValueError("drift"))) == 2
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert bodies[0]["reason"] == "EXACT_EVENT_EXECUTION_REFUSED"
    assert bodies[1]["failure_type"] == "ValueError"


@pytest.mark.parametrize(
    "state",
    ["RIGHTS_HELD", "RETRY_HELD", "CONFIGURATION_HELD", "DEAD_LETTER"],
)
def test_non_terminal_result_stops_without_another_selection(state: str) -> None:
    from scripts import hermes_graphiti_worker as worker

    calls: list[object] = []

    def consume() -> GraphitiProcessResult:
        calls.append("consume")
        return GraphitiProcessResult("event-1", 1, state, 1)

    assert worker._run(consume=consume) == 2
    assert calls == ["consume"]


def test_preflight_refusal_has_no_runner_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    monkeypatch.setattr(worker, "ensure_control_plane_state_root", lambda: None)
    monkeypatch.setattr(
        worker,
        "qualify_fresh_graphiti_event",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("not fresh")),
    )
    monkeypatch.setattr(
        worker,
        "EvaluationGraphitiRunner",
        lambda **_kwargs: pytest.fail("runner constructed after refused preflight"),
    )
    monkeypatch.setattr(
        worker,
        "consume_next_graphiti_event",
        lambda **_kwargs: pytest.fail("dispatch reached after refused preflight"),
    )

    assert worker.main(_arguments()) == 2
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert bodies[0]["reason"] == "PREFLIGHT_REFUSED"
    assert bodies[1]["failure_type"] == "ValueError"


def test_conservative_spend_bound_refuses_before_runner_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    monkeypatch.setattr(worker, "ensure_control_plane_state_root", lambda: None)
    monkeypatch.setattr(
        worker,
        "qualify_fresh_graphiti_event",
        lambda **_kwargs: {
            "resolved_units": [
                {"ingest_id": "ingest-1"},
                {"ingest_id": "ingest-2"},
            ]
        },
    )
    monkeypatch.setattr(
        worker,
        "EvaluationGraphitiRunner",
        lambda **_kwargs: pytest.fail("runner constructed beyond spend cap"),
    )

    assert worker.main(_arguments()) == 2
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert bodies == [
        {
            "event": "GRAPHITI_WORKER_STOPPED",
            "reason": "RESERVED_SPEND_BOUND_EXCEEDED",
            "completed_events": 0,
            "result": None,
            "public_dispatch": False,
            "auto_publish": False,
        }
    ]


@pytest.mark.parametrize(
    "argv",
    (
        [],
        ["--event-id", "event-1"],
        ["--ledger-seq", "1"],
        _arguments("--max-runtime-seconds", "0"),
        _arguments("--max-runtime-seconds", "nan"),
        _arguments("--max-runtime-seconds", "inf"),
        [
            "--event-id",
            "event-1",
            "--ledger-seq",
            "0",
            "--max-reserved-gbp-microunits",
            "500000",
        ],
        [
            "--event-id",
            "event-1",
            "--ledger-seq",
            "1",
            "--max-reserved-gbp-microunits",
            "0",
        ],
    ),
)
def test_worker_refuses_missing_or_invalid_bounds(argv: list[str]) -> None:
    from scripts import hermes_graphiti_worker as worker

    with pytest.raises(SystemExit):
        worker.main(argv)
