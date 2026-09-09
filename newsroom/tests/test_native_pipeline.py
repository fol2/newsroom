from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.control_plane import native_pipeline as n
from newsroom.control_plane.native_graphiti import NativeGraphitiOutcome
from newsroom.control_plane.native_progress import NativeRevisionJournal
from newsroom.control_plane.store import connect
from newsroom.control_plane.veto import VetoError
from newsroom.tests.test_native_graphiti import _native


def _open(tmp_path, monkeypatch):
    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    units = (_native("one"), _native("two"))
    calls = []
    class Graphiti:
        def advance(self, selected, *, cycle_id):
            calls.append(("graphiti", selected[0].item_key))
            return tuple(NativeGraphitiOutcome(unit.ingest_id, "GRAPHITI_COMPLETE", unit.digest, None) for unit in selected)
    class Discovery:
        def deliver(self, unit, **kw):
            calls.append(("discovery", unit.item_key))
            return unit
        def admit_lead(self, unit, **kw):
            return NS(lead=unit, phase=NS(value="LEAD"))
    class Publisher:
        def advance(self, *, revision_id, candidate_version_id):
            calls.append(("publish", revision_id))
            journal.advance(revision_id, stage="ACKNOWLEDGED", facts={
                **journal.progress[revision_id]["facts"], "ack_receipt": "isolated-test-only",
            })
    def advance(**kw):
        unit = kw["statuses"][0].lead
        return (NS(revision_id=unit.revision_id, state="CANDIDATE_ADMITTED",
                   triage=NS(candidate=NS(version_id="candidate:" + unit.item_key))),)
    monkeypatch.setattr(n, "advance_native_cycle", advance)
    dispositions = [tuple(NS(source_id=unit.source_id, status="READY", reason_code="RETAINED",
                             units=(unit,)) for unit in units)]
    pipeline = n.NativePipeline(
        runtime=NS(authority=object(), proof=object()), journal=journal,
        source_intake=NS(poll=lambda: dispositions[0]), graphiti=Graphiti(),
        discovery=Discovery(), retrieval_for=lambda units: object(), collision=object(),
        publish=Publisher(), actor_identity_digest="sha256:" + "a" * 64,
        stop_check=lambda: None, stop_fence=nullcontext,
        refresh_rights=lambda: calls.append(("rights", "current")),
        clock=lambda: UtcTimestamp.parse("2026-09-08T12:00:00Z"),
    )
    return pipeline, journal, connection, units, calls, dispositions


def test_native_pipeline_continues_multiple_revisions_and_skips_acknowledged(tmp_path, monkeypatch):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    try:
        report = pipeline.tick(cycle_id="first")
        assert report.revision_states == {"ACKNOWLEDGED": 2}
        assert report.unclassified_revisions == 0
        assert len([item for item in calls if item[0] == "graphiti"]) == 1
        first_calls = tuple(calls)
        dispositions[0] = ()
        pipeline.tick(cycle_id="second")
        assert tuple(calls) == first_calls + (("rights", "current"),)
        assert len(journal.units) == 2
    finally:
        connection.close()


def test_native_pipeline_isolates_retrieval_failure_and_keeps_disappeared_work(tmp_path, monkeypatch):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    try:
        def retrieval(selected):
            if selected[0].item_key == "one": raise RuntimeError("isolated branch fault")
            return object()
        pipeline._retrieval_for = retrieval
        report = pipeline.tick(cycle_id="first")
        assert report.revision_states == {"RETRIEVAL_HOLD": 1, "ACKNOWLEDGED": 1}
        graphiti_calls = [item for item in calls if item[0] == "graphiti"]
        pipeline._retrieval_for = lambda _: object()
        dispositions[0] = ()
        assert pipeline.tick(cycle_id="second").revision_states == {"ACKNOWLEDGED": 2}
        assert [item for item in calls if item[0] == "graphiti"] == graphiti_calls
    finally:
        connection.close()


def test_native_pipeline_preserves_ambiguous_assessment_marker(tmp_path, monkeypatch):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    def publish(*, revision_id, candidate_version_id):
        journal.advance(revision_id, stage="ASSESSMENT_STARTED", facts=journal.progress[revision_id]["facts"])
        raise OSError("interrupted after possible provider dispatch")
    pipeline._publish = NS(advance=publish)
    try:
        report = pipeline.tick(cycle_id="first")
        assert report.revision_states == {"ASSESSMENT_STARTED": 2}
    finally:
        connection.close()


def test_native_pipeline_retries_only_a_rights_evidence_hold_after_refresh(tmp_path, monkeypatch):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    try:
        journal.land((units[0],))
        journal.advance(units[0].revision_id, stage="EVIDENCE_HOLD", facts={
            "graphiti_receipts": [{"retained": True}],
            "candidate_version_id": "candidate:one",
            "reason": "PUBLICATION_RIGHTS_HOLD",
        })
        dispositions[0] = ()
        report = pipeline.tick(cycle_id="rights-restored")
        assert report.revision_states == {"ACKNOWLEDGED": 1}
        assert calls[:2] == [("rights", "current"), ("publish", units[0].revision_id)]
    finally:
        connection.close()


def test_native_pipeline_retries_a_bounded_acquisition_hold_next_cycle(tmp_path, monkeypatch):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    try:
        journal.land((units[0],))
        journal.advance(units[0].revision_id, stage="EVIDENCE_HOLD", facts={
            "graphiti_receipts": [{"retained": True}],
            "candidate_version_id": "candidate:one",
            "reason": "ACQUISITION_TRANSPORT_RETRY",
            "acquisition_attempt_count": 1,
            "acquisition_retryable": True,
        })
        dispositions[0] = ()
        report = pipeline.tick(cycle_id="next-cycle")
        assert report.revision_states == {"ACKNOWLEDGED": 1}
        assert calls[:2] == [("rights", "current"), ("publish", units[0].revision_id)]
    finally:
        connection.close()


def test_native_pipeline_honours_global_stop_before_source_poll(tmp_path, monkeypatch):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    def stop(): raise VetoError("owner stop")
    pipeline._check = stop
    try:
        with pytest.raises(VetoError): pipeline.tick(cycle_id="stopped")
        assert not journal.units and not calls
    finally:
        connection.close()
