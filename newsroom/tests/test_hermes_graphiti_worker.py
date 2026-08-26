from __future__ import annotations

import json

import pytest

from newsroom.control_plane.graphiti_events import GraphitiProcessResult


def test_once_processes_one_event_without_running_source_cycle(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    captured: dict[str, object] = {}

    def consume(**kwargs: object) -> GraphitiProcessResult:
        captured.update(kwargs)
        return GraphitiProcessResult("event-1", 7, "TERMINAL", 1)

    monkeypatch.setattr(worker, "consume_next_graphiti_event", consume)
    monkeypatch.setattr(worker, "ensure_control_plane_state_root", lambda: None)

    assert (
        worker.main(
            [
                "--once",
                "--proving",
                "/tmp/proving.sqlite3",
                "--unpublished",
                "/tmp/unpublished.sqlite3",
            ]
        )
        == 0
    )

    assert captured["proving_store"] == "/tmp/proving.sqlite3"
    assert captured["unpublished_store"] == "/tmp/unpublished.sqlite3"
    assert str(captured["owner_id"]).startswith("hermes-graphiti:")
    body = json.loads(capsys.readouterr().out)
    assert body == {
        "event": "GRAPHITI_EVENT_RESULT",
        "result": {
            "event_id": "event-1",
            "ledger_seq": 7,
            "state": "TERMINAL",
            "attempt_count": 1,
        },
        "public_dispatch": False,
        "auto_publish": False,
    }


def test_idle_once_is_a_successful_no_effect_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    monkeypatch.setattr(
        worker, "consume_next_graphiti_event", lambda **_kwargs: None
    )
    monkeypatch.setattr(worker, "ensure_control_plane_state_root", lambda: None)

    assert worker.main(["--once"]) == 0
    assert json.loads(capsys.readouterr().out)["event"] == "GRAPHITI_EVENT_IDLE"


def test_worker_refuses_to_weaken_failure_backoff() -> None:
    from scripts import hermes_graphiti_worker as worker

    with pytest.raises(SystemExit):
        worker.main(["--once", "--failure-seconds", "29"])


def test_continuous_worker_drains_results_before_sleeping_on_idle(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    results = iter(
        (
            GraphitiProcessResult("event-1", 1, "TERMINAL", 1),
            GraphitiProcessResult("event-2", 2, "RIGHTS_HELD", 1),
            None,
        )
    )
    calls: list[object] = []

    class StopWorker(Exception):
        pass

    def consume() -> GraphitiProcessResult | None:
        calls.append("consume")
        return next(results)

    def sleep(seconds: float) -> None:
        calls.append(("sleep", seconds))
        raise StopWorker

    with pytest.raises(StopWorker):
        worker._run(
            consume=consume,
            once=False,
            idle_seconds=1.5,
            failure_seconds=30,
            sleep=sleep,
        )

    assert calls == ["consume", "consume", "consume", ("sleep", 1.5)]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["result"]["event_id"] for line in lines] == [
        "event-1",
        "event-2",
    ]


def test_retry_held_result_backs_off_before_claiming_another_event() -> None:
    from scripts import hermes_graphiti_worker as worker

    calls: list[object] = []

    class StopWorker(Exception):
        pass

    def consume() -> GraphitiProcessResult:
        calls.append("consume")
        return GraphitiProcessResult("event-1", 1, "RETRY_HELD", 1)

    def sleep(seconds: float) -> None:
        calls.append(("sleep", seconds))
        raise StopWorker

    with pytest.raises(StopWorker):
        worker._run(
            consume=consume,
            once=False,
            idle_seconds=1,
            failure_seconds=30,
            sleep=sleep,
        )

    assert calls == ["consume", ("sleep", 30)]
