import json
import sqlite3
from contextlib import contextmanager

import pytest

from newsroom.control_plane.native_pipeline import NativePipeline, NativePipelineReport
from newsroom.control_plane.native_service import (
    NativeService, NativeServiceAlreadyRunning, _instance_lock,
)
from newsroom.control_plane.veto import VetoError
from scripts.hermes_native import main
from newsroom.authority.canonical import digest_canonical


def _pipeline(monkeypatch, tick):
    pipeline = object.__new__(NativePipeline)
    pipeline._test_tick = tick
    monkeypatch.setattr(
        NativePipeline, "tick",
        lambda self, *, cycle_id: self._test_tick(cycle_id),
    )
    opened = []

    @contextmanager
    def factory():
        opened.append("open")
        try:
            yield pipeline
        finally:
            opened.append("close")

    return factory, opened


def _service(tmp_path, factory, **values):
    return NativeService(
        pipeline_factory=factory,
        ledger_path=str(tmp_path / "unpublished.sqlite3"),
        lock_path=tmp_path / "hermes-native.lock",
        stop_check=values.pop("stop_check", lambda: None),
        interval_seconds=values.pop("interval_seconds", 2),
        failure_backoff_seconds=values.pop("failure_backoff_seconds", 7),
        cycle_id_factory=values.pop("cycle_id_factory", iter(("cycle-1", "cycle-2")).__next__),
        **values,
    )


def test_native_service_runs_two_ticks_without_story_cap_and_closes(tmp_path, monkeypatch):
    ticks, waits = [], []
    factory, opened = _pipeline(
        monkeypatch,
        lambda cycle_id: (
            ticks.append(cycle_id)
            or NativePipelineReport((), {"ACKNOWLEDGED": 4}, 0)
        ),
    )

    def wait(seconds):
        waits.append(seconds)
        return len(waits) == 2

    report = _service(tmp_path, factory, wait=wait).run()
    assert ticks == ["cycle-1", "cycle-2"]
    assert waits == [2, 2]
    assert opened == ["open", "close"]
    assert report.outcome == "COMPLETE"
    assert report.pipeline.revision_states == {"ACKNOWLEDGED": 4}
    with sqlite3.connect(tmp_path / "unpublished.sqlite3") as connection:
        assert connection.execute(
            "SELECT kind FROM ledger WHERE kind LIKE 'NATIVE_SERVICE_%' ORDER BY seq"
        ).fetchall() == [
            ("NATIVE_SERVICE_CYCLE_STARTED",), ("NATIVE_SERVICE_CYCLE_TERMINAL",),
            ("NATIVE_SERVICE_CYCLE_STARTED",), ("NATIVE_SERVICE_CYCLE_TERMINAL",),
        ]


def test_native_service_failure_is_terminal_then_restart_continues(tmp_path, monkeypatch):
    factory, opened = _pipeline(
        monkeypatch, lambda _cycle_id: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    failed = _service(
        tmp_path, factory, cycle_id_factory=lambda: "failed-cycle",
    ).run(once=True)
    assert failed.failure_class == "RuntimeError"
    assert opened == ["open", "close"]

    factory, _ = _pipeline(
        monkeypatch,
        lambda _cycle_id: NativePipelineReport((), {"QUEUED": 2}, 2),
    )
    complete = _service(
        tmp_path, factory, cycle_id_factory=lambda: "restart-cycle",
    ).run(once=True)
    assert complete.outcome == "COMPLETE"
    with sqlite3.connect(tmp_path / "unpublished.sqlite3") as connection:
        terminals = [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM ledger "
            "WHERE kind='NATIVE_SERVICE_CYCLE_TERMINAL' ORDER BY seq"
        )]
    assert [(item["cycle_id"], item["outcome"]) for item in terminals] == [
        ("failed-cycle", "FAILED"), ("restart-cycle", "COMPLETE"),
    ]
    assert "secret" not in json.dumps(terminals)


def test_native_service_preserves_veto_and_singleton_lock(tmp_path, monkeypatch):
    factory, opened = _pipeline(
        monkeypatch, lambda _cycle_id: (_ for _ in ()).throw(VetoError("signed stop")),
    )
    service = _service(tmp_path, factory, cycle_id_factory=lambda: "stopped-cycle")
    with pytest.raises(VetoError, match="signed stop"):
        service.run(once=True)
    assert opened == ["open", "close"]
    with sqlite3.connect(tmp_path / "unpublished.sqlite3") as connection:
        records = [(kind, json.loads(payload)) for kind, payload in connection.execute(
            "SELECT kind, payload_json FROM ledger ORDER BY seq"
        )]
    assert [kind for kind, _ in records] == [
        "NATIVE_SERVICE_CYCLE_STARTED", "NATIVE_SERVICE_CYCLE_TERMINAL",
    ]
    assert all(payload["cycle_id"] == "stopped-cycle" for _, payload in records)
    assert records[-1][1] == {
        "cycle_id": "stopped-cycle", "outcome": "STOPPED",
        "failure_class": "VetoError", "pipeline": None,
    }
    assert "signed stop" not in json.dumps(records)

    with _instance_lock(tmp_path / "hermes-native.lock"):
        with pytest.raises(NativeServiceAlreadyRunning):
            service.run(once=True)


def test_native_service_preflight_precedes_lock_ledger_and_pipeline(tmp_path, monkeypatch):
    factory, opened = _pipeline(
        monkeypatch, lambda _: pytest.fail("pipeline tick after failed preflight"),
    )
    ledger = tmp_path / "unpublished.sqlite3"
    lock = tmp_path / "locks" / "hermes-native.lock"

    def reject():
        raise ValueError("deployment path differs")

    service = NativeService(
        pipeline_factory=factory, ledger_path=str(ledger), lock_path=lock,
        stop_check=lambda: None, preflight=reject,
    )
    with pytest.raises(ValueError, match="deployment path differs"):
        service.run(once=True)
    assert opened == []
    assert not ledger.exists()
    assert not lock.parent.exists()


def test_native_service_binds_both_cycle_records_to_runtime_identity(tmp_path, monkeypatch):
    factory, _ = _pipeline(monkeypatch, lambda _: NativePipelineReport((), {}, 0))
    identity = digest_canonical({"actual_test_deployment": str(tmp_path)})

    @contextmanager
    def bound():
        with factory() as pipeline:
            pipeline.runtime_identity_digest = identity
            yield pipeline

    qualified = []

    def qualify(connection, digest):
        assert connection.execute("SELECT kind FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()[0] == "NATIVE_SERVICE_CYCLE_TERMINAL"
        qualified.append(digest)

    _service(tmp_path, bound, qualify_once=qualify).run(once=True)
    assert qualified == [identity]
    with sqlite3.connect(tmp_path / "unpublished.sqlite3") as connection:
        records = tuple(json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM ledger WHERE kind LIKE 'NATIVE_SERVICE_%' ORDER BY seq"
        ))
    assert len(records) == 2
    assert all(record["runtime_identity_digest"] == identity for record in records)


def test_hermes_native_once_cli_reports_exact_terminal(tmp_path, monkeypatch, capsys):
    factory, _ = _pipeline(
        monkeypatch, lambda _cycle_id: NativePipelineReport((), {}, 0),
    )

    def service_factory(args):
        assert args.once and args.interval == 3 and args.failure_backoff == 9
        return NativeService(
            pipeline_factory=factory, ledger_path=args.ledger,
            lock_path=tmp_path / "cli.lock", stop_check=lambda: None,
            interval_seconds=args.interval,
            failure_backoff_seconds=args.failure_backoff,
            cycle_id_factory=lambda: "cli-cycle",
        )

    assert main(service_factory, [
        "--once", "--ledger", str(tmp_path / "cli.sqlite3"),
        "--lock", str(tmp_path / "ignored-by-interim-factory.lock"),
        "--interval", "3", "--failure-backoff", "9",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "public_effect": False,
        "service": {
            "cycle_id": "cli-cycle", "failure_class": None,
            "outcome": "COMPLETE",
            "pipeline": {"revision_states": {}, "sources": [], "unclassified_revisions": 0},
        },
    }


def test_hermes_native_owner_stop_is_not_a_supervisor_crash(tmp_path, monkeypatch, capsys):
    factory, opened = _pipeline(monkeypatch, lambda _: None)

    def stopped():
        raise VetoError("private stop details")

    assert main(lambda args: _service(tmp_path, factory, stop_check=stopped), [
        "--once", "--ledger", str(tmp_path / "unpublished.sqlite3"),
        "--lock", str(tmp_path / "hermes-native.lock"),
    ]) == 0
    assert not opened
    assert not (tmp_path / "unpublished.sqlite3").exists()
    assert json.loads(capsys.readouterr().out) == {
        "service": None, "owner_stop": True, "public_effect": False,
    }
