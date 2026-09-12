from contextlib import nullcontext
from dataclasses import replace
import threading
from types import SimpleNamespace as NS

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.control_plane import native_pipeline as n
from newsroom.control_plane.native_graphiti import NativeGraphitiOutcome
from newsroom.control_plane.native_progress import NativeRevisionJournal
from newsroom.control_plane.store import connect
from newsroom.control_plane.veto import OperatorDrainRequested, VetoError
from newsroom.tests.test_native_graphiti import _native


def _open(tmp_path, monkeypatch):
    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    units = (_native("one"), _native("two"))
    calls = []
    class Graphiti:
        def advance(self, selected, *, cycle_id, **kwargs):
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


def test_native_pipeline_retains_same_state_association_without_retry(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, units, calls, dispositions = _open(
        tmp_path, monkeypatch,
    )
    triage_calls = []

    def associate(**kwargs):
        unit = kwargs["statuses"][0].lead
        triage_calls.append(unit.revision_id)
        return (
            NS(
                revision_id=unit.revision_id,
                state="SAME_STATE_ASSOCIATED",
                triage=NS(candidate=None),
                reason=None,
            ),
        )

    monkeypatch.setattr(n, "advance_native_cycle", associate)
    try:
        first = pipeline.tick(cycle_id="same-state")
        assert first.revision_states == {"SAME_STATE_ASSOCIATED": 2}
        assert triage_calls == [item.revision_id for item in units]
        assert not any(call[0] == "publish" for call in calls)

        dispositions[0] = ()
        second = pipeline.tick(cycle_id="same-state-replay")
        assert second.revision_states == {"SAME_STATE_ASSOCIATED": 2}
        assert triage_calls == [item.revision_id for item in units]
        assert all(
            journal.progress[item.revision_id]["stage"]
            == "SAME_STATE_ASSOCIATED"
            for item in units
        )
    finally:
        connection.close()


def test_native_pipeline_drains_between_revisions_and_restart_reuses_settled_work(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, units, calls, dispositions = _open(
        tmp_path, monkeypatch,
    )
    service_event = threading.Event()
    original = pipeline._publish

    class DrainAfterFirstPublication:
        def advance(self, *, revision_id, candidate_version_id):
            original.advance(
                revision_id=revision_id,
                candidate_version_id=candidate_version_id,
            )
            service_event.set()

    pipeline._publish = DrainAfterFirstPublication()
    pipeline._operator_drain_requested = service_event.is_set
    try:
        with pytest.raises(OperatorDrainRequested):
            pipeline.tick(cycle_id="draining")
        assert len([call for call in calls if call[0] == "graphiti"]) == 1
        assert [
            journal.progress[unit.revision_id]["stage"] for unit in units
        ] == ["ACKNOWLEDGED", "GRAPHITI_COMPLETE"]
        assert len([call for call in calls if call[0] == "publish"]) == 1

        service_event.clear()
        pipeline._publish = original
        dispositions[0] = ()
        report = pipeline.tick(cycle_id="restart")
        assert report.revision_states == {"ACKNOWLEDGED": 2}
        assert len([call for call in calls if call[0] == "graphiti"]) == 1
        assert len([call for call in calls if call[0] == "publish"]) == 2
    finally:
        connection.close()


def test_native_pipeline_lands_polled_work_before_operator_drain(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, units, calls, _, = _open(tmp_path, monkeypatch)
    service_event = threading.Event()
    original_poll = pipeline._intake.poll

    def poll_then_drain():
        result = original_poll()
        service_event.set()
        return result

    pipeline._intake = NS(poll=poll_then_drain)
    pipeline._operator_drain_requested = service_event.is_set
    try:
        with pytest.raises(OperatorDrainRequested):
            pipeline.tick(cycle_id="drain-after-poll")
        assert set(journal.units) == {unit.revision_id for unit in units}
        assert not any(call[0] == "graphiti" for call in calls)
    finally:
        connection.close()


def test_native_pipeline_checkpoints_graphiti_results_before_operator_drain(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, units, calls, _ = _open(tmp_path, monkeypatch)
    service_event = threading.Event()
    original = pipeline._graphiti

    class GraphitiThenDrain:
        def advance(self, selected, *, cycle_id, **kwargs):
            result = original.advance(selected, cycle_id=cycle_id, **kwargs)
            service_event.set()
            return result

    pipeline._graphiti = GraphitiThenDrain()
    pipeline._operator_drain_requested = service_event.is_set
    try:
        with pytest.raises(OperatorDrainRequested):
            pipeline.tick(cycle_id="drain-after-graphiti")
        assert all(
            journal.progress[unit.revision_id]["stage"] == "GRAPHITI_COMPLETE"
            for unit in units
        )
        assert not any(call[0] in {"discovery", "publish"} for call in calls)
    finally:
        connection.close()


def test_native_pipeline_checkpoints_candidate_before_operator_drain(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, units, calls, dispositions = _open(
        tmp_path, monkeypatch,
    )
    service_event = threading.Event()
    dispositions[0] = ()
    unit = units[0]
    journal.land((unit,))
    journal.advance(unit.revision_id, stage="GRAPHITI_COMPLETE", facts={
        "graphiti_receipts": [{}],
    })

    def advance_then_drain(**kw):
        service_event.set()
        lead = kw["statuses"][0].lead
        return (NS(
            revision_id=lead.revision_id, state="CANDIDATE_ADMITTED",
            triage=NS(candidate=NS(version_id="candidate:" + lead.item_key)),
        ),)

    monkeypatch.setattr(n, "advance_native_cycle", advance_then_drain)
    pipeline._operator_drain_requested = service_event.is_set
    try:
        with pytest.raises(OperatorDrainRequested):
            pipeline.tick(cycle_id="drain-after-candidate")
        progress = journal.progress[unit.revision_id]
        assert progress["stage"] == "CANDIDATE_ADMITTED"
        assert progress["facts"]["candidate_version_id"] == "candidate:one"
        assert not any(call[0] == "publish" for call in calls)
    finally:
        connection.close()


def test_native_pipeline_only_reclassifies_retained_assessment_interruption(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, units, calls, dispositions = _open(
        tmp_path, monkeypatch,
    )
    dispositions[0] = ()
    journal.land((units[0],))
    journal.advance(units[0].revision_id, stage="ASSESSMENT_INTERRUPTED", facts={
        "candidate_version_id": "candidate:one",
        "graphiti_receipts": [{}],
        "failure_class": "EvidencePackageError",
        "reason": "ACQUISITION_RESULT_NOT_RETAINED",
    })

    class Recovery:
        def advance(self, *, revision_id, candidate_version_id):
            calls.append(("recover", revision_id, candidate_version_id))
            journal.advance(revision_id, stage="EVIDENCE_HOLD", facts={
                **journal.progress[revision_id]["facts"],
                "reason": "ASSESSOR_OUTPUT_CONTRACT_HOLD",
                "acquisition_retryable": False,
            })

    pipeline._publish = Recovery()
    calls.clear()
    try:
        first = pipeline.tick(cycle_id="recovery")
        assert first.revision_states == {"EVIDENCE_HOLD": 1}
        assert calls == [
            ("rights", "current"),
            ("recover", units[0].revision_id, "candidate:one"),
        ]
        calls.clear()
        pipeline.tick(cycle_id="replay")
        assert calls == [("rights", "current")]
    finally:
        connection.close()


def test_native_pipeline_does_not_restart_unproved_assessment_interruptions(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, units, calls, dispositions = _open(
        tmp_path, monkeypatch,
    )
    dispositions[0] = ()
    retained_ordinals = {}
    for unit, failure_class in zip(
        units, ("EvidencePackageError", "OSError"), strict=True
    ):
        journal.land((unit,))
        journal.advance(unit.revision_id, stage="ASSESSMENT_INTERRUPTED", facts={
            "candidate_version_id": "candidate:" + unit.item_key,
            "graphiti_receipts": [{}],
            "failure_class": failure_class,
            "reason": "ACQUISITION_RESULT_NOT_RETAINED",
        })
        retained_ordinals[unit.revision_id] = journal.progress[unit.revision_id][
            "ordinal"
        ]

    class UnprovedRecovery:
        def advance(self, *, revision_id, candidate_version_id):
            calls.append(("proof-only", revision_id, candidate_version_id))
            return NS(state="ASSESSMENT_INTERRUPTED")

    pipeline._publish = UnprovedRecovery()
    calls.clear()
    try:
        report = pipeline.tick(cycle_id="unproved-recovery")
        assert report.revision_states == {"ASSESSMENT_INTERRUPTED": 2}
        assert calls == [
            ("rights", "current"),
            ("proof-only", units[0].revision_id, "candidate:one"),
            ("proof-only", units[1].revision_id, "candidate:two"),
        ]
        assert {
            revision_id: journal.progress[revision_id]["ordinal"]
            for revision_id in retained_ordinals
        } == retained_ordinals
    finally:
        connection.close()


def test_native_pipeline_retains_hold_reason_then_clears_it_on_continuation(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, units, calls, dispositions = _open(
        tmp_path, monkeypatch,
    )
    prefix = replace(units[1], chunk_count=2)
    predecessor_held = replace(
        prefix, chunk_ordinal=2, predecessor_ingest_id=prefix.ingest_id,
    )
    dispositions[0] = (
        NS(source_id=units[0].source_id, status="READY", reason_code="RETAINED", units=(units[0],)),
        NS(source_id=prefix.source_id, status="READY", reason_code="RETAINED", units=(prefix, predecessor_held)),
    )
    attempts = 0

    class Graphiti:
        def advance(self, selected, *, cycle_id, **kwargs):
            nonlocal attempts
            attempts += 1
            outcomes = []
            for unit in selected:
                state = "GRAPHITI_COMPLETE"
                reason = None
                if attempts == 1 and unit.revision_id == prefix.revision_id:
                    state = (
                        "EXTRACTION_COMPLETE"
                        if unit.chunk_ordinal == 1
                        else "GRAPHITI_HOLD"
                    )
                    reason = (
                        None
                        if unit.chunk_ordinal == 1
                        else "RIGHTS_OR_PREDECESSOR_HOLD"
                    )
                outcomes.append(NativeGraphitiOutcome(
                    unit.ingest_id, state,
                    None if state == "GRAPHITI_HOLD" else "sha256:" + "a" * 64,
                    reason,
                ))
            return tuple(outcomes)

    pipeline._graphiti = Graphiti()
    try:
        first = pipeline.tick(cycle_id="first-frontier")
        assert first.revision_states == {"ACKNOWLEDGED": 1, "GRAPHITI_HOLD": 1}
        held = journal.progress[prefix.revision_id]
        assert held["facts"]["reason"] == "RIGHTS_OR_PREDECESSOR_HOLD"
        assert [item["state"] for item in held["facts"]["graphiti_outcomes"]] == [
            "EXTRACTION_COMPLETE", "GRAPHITI_HOLD",
        ]
        first_publish = [call for call in calls if call[0] == "publish"]

        dispositions[0] = ()
        second = pipeline.tick(cycle_id="second-frontier")
        assert second.revision_states == {"ACKNOWLEDGED": 2}
        assert [call for call in calls if call[0] == "publish"] == first_publish + [
            ("publish", prefix.revision_id),
        ]
        completed = journal.progress[prefix.revision_id]["facts"]
        assert "reason" not in completed
        assert "graphiti_outcomes" not in completed
        assert completed["graphiti_receipts"][0]["state"] == "GRAPHITI_COMPLETE"
    finally:
        connection.close()


def test_native_pipeline_rolls_up_multiple_holds_and_rejects_a_missing_reason(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, _, _, dispositions = _open(tmp_path, monkeypatch)
    first = replace(_native("multi"), chunk_count=2)
    second = replace(
        first, chunk_ordinal=2, predecessor_ingest_id=first.ingest_id,
    )
    dispositions[0] = (
        NS(source_id=first.source_id, status="READY", reason_code="RETAINED", units=(first, second)),
    )

    class Graphiti:
        missing = False

        def advance(self, selected, *, cycle_id, **kwargs):
            return (
                NativeGraphitiOutcome(
                    selected[0].ingest_id, "GRAPHITI_HOLD", None,
                    None if self.missing else "RETRY_PENDING",
                ),
                NativeGraphitiOutcome(
                    selected[1].ingest_id, "GRAPHITI_HOLD", None,
                    "RIGHTS_OR_PREDECESSOR_HOLD",
                ),
            )

    graphiti = Graphiti()
    pipeline._graphiti = graphiti
    try:
        pipeline.tick(cycle_id="multiple-holds")
        retained = journal.progress[first.revision_id]
        assert retained["facts"]["reason"] == "MULTIPLE_GRAPHITI_HOLDS"
        assert {item["reason"] for item in retained["facts"]["graphiti_outcomes"]} == {
            "RETRY_PENDING", "RIGHTS_OR_PREDECESSOR_HOLD",
        }

        dispositions[0] = ()
        graphiti.missing = True
        pipeline.tick(cycle_id="missing-reason")
        assert journal.progress[first.revision_id]["facts"]["reason"] == "ValueError"
        assert "graphiti_receipts" not in journal.progress[first.revision_id]["facts"]
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


@pytest.mark.parametrize("reason", (
    "ASSESSOR_CLAIM_BINDING_HOLD", "ASSESSOR_NAMED_ENTITY_CONTRACT_HOLD",
    "NO_QUALIFYING_NEW_INFORMATION",
    "EDITORIAL_ADMISSION_HOLD",
))
def test_native_pipeline_revalidates_only_repairable_holds_once_per_contract(tmp_path, monkeypatch, reason):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    pipeline._assessment_contract_version = "new-contract"
    journal.land((units[0],))
    journal.advance(units[0].revision_id, stage="EVIDENCE_HOLD", facts={
        "graphiti_receipts": [{"retained": True}],
        "candidate_version_id": "candidate:one", "reason": reason,
        "editorial_hold_reason_codes": (
            ["INVALID_GOVERNED_CLAIM_EVIDENCE", "UNQUALIFIED_HEADLINE_CLAIM"]
            if reason == "EDITORIAL_ADMISSION_HOLD" else []
        ),
    })
    dispositions[0] = ()

    def publish(*, revision_id, candidate_version_id):
        calls.append(("revalidate", revision_id))
        journal.advance(revision_id, stage="EVIDENCE_HOLD", facts={
            **journal.progress[revision_id]["facts"],
            "assessment_contract_version": pipeline._assessment_contract_version,
        })

    pipeline._publish = NS(advance=publish)
    try:
        for cycle in ("first", "unchanged"):
            pipeline.tick(cycle_id=cycle)
        expected = int(reason != "NO_QUALIFYING_NEW_INFORMATION")
        assert len([call for call in calls if call[0] == "revalidate"]) == expected
        pipeline._assessment_contract_version = "next-contract"
        pipeline.tick(cycle_id="changed-contract")
        assert len([call for call in calls if call[0] == "revalidate"]) == 2 * expected
    finally:
        connection.close()


def test_native_pipeline_time_slices_changed_contract_reassessment_without_starving_work(
    tmp_path, monkeypatch,
):
    pipeline, journal, connection, _, calls, dispositions = _open(
        tmp_path, monkeypatch,
    )
    due = tuple(_native(f"due-{index}") for index in range(3))
    ordinary = _native("ordinary")
    fresh = _native("fresh")
    now = [0.0]
    polls = []
    pipeline._assessment_contract_version = "v8"
    pipeline._reassessment_quantum = 300
    pipeline._monotonic_clock = lambda: now[0]
    dispositions[0] = ()
    pipeline._intake = NS(poll=lambda: (polls.append(now[0]) or dispositions[0]))
    for unit in due:
        journal.land((unit,))
        journal.advance(unit.revision_id, stage="EVIDENCE_HOLD", facts={
            "graphiti_receipts": [{"retained": True}],
            "candidate_version_id": "candidate:" + unit.item_key,
            "reason": "ASSESSOR_CLAIM_BINDING_HOLD",
            "assessment_contract_version": "v7",
        })
    journal.land((ordinary,))
    journal.advance(ordinary.revision_id, stage="GRAPHITI_COMPLETE", facts={
        "graphiti_receipts": [{"retained": True}],
        "candidate_version_id": "candidate:" + ordinary.item_key,
    })
    dispositions[0] = (NS(
        source_id=fresh.source_id, status="READY", reason_code="RETAINED",
        units=(fresh,),
    ),)
    original_publish = pipeline._publish

    class Publisher:
        def advance(self, *, revision_id, candidate_version_id):
            if revision_id in {unit.revision_id for unit in due}:
                if journal.progress[revision_id]["stage"] == "ASSESSMENT_STARTED":
                    calls.append(("resume", revision_id))
                    journal.advance(revision_id, stage="EVIDENCE_HOLD", facts={
                        **journal.progress[revision_id]["facts"],
                        "assessment_contract_version": "v8",
                    })
                    return
                calls.append(("revalidate", revision_id))
                now[0] += 301
                if revision_id == due[0].revision_id:
                    journal.advance(
                        revision_id, stage="ASSESSMENT_STARTED",
                        facts=journal.progress[revision_id]["facts"],
                    )
                    return
                journal.advance(revision_id, stage="EVIDENCE_HOLD", facts={
                    **journal.progress[revision_id]["facts"],
                    "assessment_contract_version": "v8",
                })
                return
            original_publish.advance(
                revision_id=revision_id,
                candidate_version_id=candidate_version_id,
            )

    pipeline._publish = Publisher()
    try:
        for cycle in ("first", "second", "third", "unchanged"):
            pipeline.tick(cycle_id=cycle)
            dispositions[0] = ()
        assert [revision_id for kind, revision_id in calls if kind == "revalidate"] == [
            unit.revision_id for unit in due
        ]
        assert [revision_id for kind, revision_id in calls if kind == "resume"] == [
            due[0].revision_id
        ]
        assert len(polls) == 4
        assert journal.progress[ordinary.revision_id]["stage"] == "ACKNOWLEDGED"
        assert journal.progress[fresh.revision_id]["stage"] == "ACKNOWLEDGED"
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


@pytest.mark.parametrize("stop_after_retained", [False, True])
def test_native_pipeline_advances_retained_work_before_new_graphiti_once(
    tmp_path, monkeypatch, stop_after_retained,
):
    pipeline, journal, connection, units, calls, _ = _open(tmp_path, monkeypatch)
    retained, pending = units
    journal.land((retained,))
    journal.advance(retained.revision_id, stage="GRAPHITI_COMPLETE", facts={
        "graphiti_receipts": [{}],
    })
    stopped = False
    original_graphiti = pipeline._graphiti

    def check():
        if stopped:
            raise VetoError("owner stop before fresh dispatch")

    def retrieval(selected):
        nonlocal stopped
        calls.append(("retrieval", selected[0].item_key))
        if selected[0].revision_id == retained.revision_id:
            stopped = stop_after_retained
            raise RuntimeError("retained downstream failure")
        return object()

    def graphiti(selected, *, cycle_id, **kwargs):
        assert selected == (pending,)
        # The failure is committed before new provider work, not only in memory.
        reopened = NativeRevisionJournal(connection)
        assert reopened.progress[retained.revision_id]["stage"] == "RETRIEVAL_HOLD"
        return original_graphiti.advance(selected, cycle_id=cycle_id, **kwargs)

    pipeline._check = check
    pipeline._retrieval_for = retrieval
    pipeline._graphiti = NS(advance=graphiti)
    try:
        if stop_after_retained:
            with pytest.raises(VetoError, match="before fresh dispatch"):
                pipeline.tick(cycle_id="retained-first-stop")
            assert not any(call[0] == "graphiti" for call in calls)
        else:
            report = pipeline.tick(cycle_id="retained-first")
            assert report.revision_states == {"RETRIEVAL_HOLD": 1, "ACKNOWLEDGED": 1}
            assert [call for call in calls if call[0] in {"retrieval", "graphiti"}] == [
                ("retrieval", retained.item_key),
                ("graphiti", pending.item_key),
                ("retrieval", pending.item_key),
            ]
        assert calls.count(("retrieval", retained.item_key)) == 1
    finally:
        connection.close()


def test_ordinary_downstream_quantum_preserves_next_revision_until_next_poll(tmp_path, monkeypatch):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    now = [0.0]
    pipeline._monotonic_clock = lambda: now[0]
    dispositions[0] = ()
    pipeline._intake = NS(poll=lambda: calls.append(("poll", "current")) or ())
    for unit in units:
        journal.land((unit,))
        journal.advance(unit.revision_id, stage="GRAPHITI_COMPLETE", facts={
            "graphiti_receipts": [{}], "candidate_version_id": "candidate:" + unit.item_key,
        })
    previous = dict(journal.progress[units[1].revision_id])
    original = pipeline._publish

    def publish(**kwargs):
        original.advance(**kwargs)
        now[0] += 301

    pipeline._publish = NS(advance=publish)
    try:
        first = pipeline.tick(cycle_id="first")
        assert first.revision_states == {"ACKNOWLEDGED": 1, "GRAPHITI_COMPLETE": 1}
        assert journal.progress[units[1].revision_id] == previous
        pipeline.tick(cycle_id="second")
        assert [call for call in calls if call[0] in {"poll", "publish"}] == [
            ("poll", "current"), ("publish", units[0].revision_id),
            ("poll", "current"), ("publish", units[1].revision_id),
        ]
    finally:
        connection.close()


def test_three_disjoint_turns_progress_with_revalidation_and_sustained_fresh_work(tmp_path, monkeypatch):
    pipeline, journal, connection, _, calls, _ = _open(tmp_path, monkeypatch)
    ordinary = _native("ordinary")
    due = tuple(_native(f"due-{index}") for index in range(2))
    fresh = tuple(_native(f"fresh-{index}") for index in range(3))
    now = [0.0]
    incoming = [fresh[:2]]
    pipeline._assessment_contract_version = "v9"
    pipeline._monotonic_clock = lambda: now[0]

    def poll():
        calls.append(("poll", "current"))
        return tuple(NS(source_id=unit.source_id, status="READY", reason_code="RETAINED", units=(unit,)) for unit in incoming[0])

    pipeline._intake = NS(poll=poll)
    for unit in (ordinary, *due):
        journal.land((unit,))
        journal.advance(unit.revision_id, stage="EVIDENCE_HOLD" if unit in due else "GRAPHITI_COMPLETE", facts={
            "graphiti_receipts": [{}], "candidate_version_id": "candidate:" + unit.item_key,
            "reason": "ASSESSOR_CLAIM_BINDING_HOLD", "assessment_contract_version": "v8",
        })
    original = pipeline._publish

    def publish(**kwargs):
        revision_id = kwargs["revision_id"]
        if revision_id in {unit.revision_id for unit in due}:
            calls.append(("revalidate", revision_id))
            journal.advance(revision_id, stage="EVIDENCE_HOLD", facts={
                **journal.progress[revision_id]["facts"], "assessment_contract_version": "v9",
            })
        else:
            original.advance(**kwargs)
        now[0] += 301

    def graphiti(selected, *, cycle_id, defer_before_unit):
        results = []
        for unit in selected:
            if defer_before_unit(unit):
                results.append(NativeGraphitiOutcome(unit.ingest_id, "GRAPHITI_DEFERRED", None, "WORK_QUANTUM_EXHAUSTED"))
            else:
                calls.append(("extract", unit.revision_id))
                now[0] += 301
                results.append(NativeGraphitiOutcome(unit.ingest_id, "GRAPHITI_COMPLETE", unit.digest, None))
        return tuple(results)

    pipeline._publish = NS(advance=publish)
    pipeline._graphiti = NS(advance=graphiti)
    try:
        first = pipeline.tick(cycle_id="first")
        assert first.revision_states == {"ACKNOWLEDGED": 1, "EVIDENCE_HOLD": 2, "GRAPHITI_COMPLETE": 1, "QUEUED": 1}
        assert fresh[1].revision_id not in journal.progress
        incoming[0] = (fresh[2],)
        second = pipeline.tick(cycle_id="second")
        assert second.revision_states == {"ACKNOWLEDGED": 2, "EVIDENCE_HOLD": 2, "GRAPHITI_COMPLETE": 1, "QUEUED": 1}
        assert fresh[2].revision_id not in journal.progress
        assert [call for call in calls if call[0] in {"poll", "publish", "revalidate", "extract"}] == [
            ("poll", "current"), ("publish", ordinary.revision_id),
            ("revalidate", due[0].revision_id), ("extract", fresh[0].revision_id),
            ("poll", "current"), ("publish", fresh[0].revision_id),
            ("revalidate", due[1].revision_id), ("extract", fresh[1].revision_id),
        ]
    finally:
        connection.close()


@pytest.mark.parametrize("stage", ["ASSESSMENT_INTERRUPTED", "ASSESSMENT_STARTED", "PUBLICATION_STARTED"])
def test_unknown_settlement_keeps_priority_but_defers_next_unit_after_quantum(tmp_path, monkeypatch, stage):
    pipeline, journal, connection, units, calls, dispositions = _open(tmp_path, monkeypatch)
    ordinary = _native("ordinary")
    now = [0.0]
    pipeline._monotonic_clock = lambda: now[0]
    dispositions[0] = ()
    pipeline._intake = NS(poll=lambda: calls.append(("poll", "current")) or ())
    for unit in (ordinary, *units):
        journal.land((unit,))
        journal.advance(unit.revision_id, stage="GRAPHITI_COMPLETE" if unit == ordinary else stage, facts={
            "graphiti_receipts": [{}], "candidate_version_id": "candidate:" + unit.item_key,
        })
    previous = dict(journal.progress)

    def publish(**kwargs):
        calls.append(("settle", kwargs["revision_id"]))
        now[0] += 301
        if (kwargs["revision_id"] == units[0].revision_id
                and calls.count(("settle", units[0].revision_id)) == 2):
            # A later retained settlement result, not permission to redispatch.
            journal.advance(units[0].revision_id, stage="EVIDENCE_HOLD", facts={
                **journal.progress[units[0].revision_id]["facts"], "reason": "RETAINED_HOLD",
            })
        elif stage != "ASSESSMENT_INTERRUPTED":
            raise OSError("still unresolved; retain exact marker")

    pipeline._publish = NS(advance=publish)
    try:
        pipeline.tick(cycle_id="settle-first")
        assert [call for call in calls if call[0] == "settle"] == [("settle", units[0].revision_id)]
        assert now[0] == 301
        assert journal.progress == previous
        pipeline.tick(cycle_id="settle-continuation")
        assert now[0] == 602
        assert journal.progress[units[1].revision_id] == previous[units[1].revision_id]
        pipeline.tick(cycle_id="next-continuation")
        assert now[0] == 903
        assert [call for call in calls if call[0] in {"poll", "settle"}] == [
            ("poll", "current"), ("settle", units[0].revision_id),
            ("poll", "current"), ("settle", units[0].revision_id),
            ("poll", "current"), ("settle", units[1].revision_id),
        ]
        assert journal.progress[ordinary.revision_id] == previous[ordinary.revision_id]
        assert journal.progress[units[1].revision_id] == previous[units[1].revision_id]
        assert not any(call[0] in {"graphiti", "discovery"} for call in calls)
    finally:
        connection.close()
