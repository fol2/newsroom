from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from newsroom.control_plane import native_graphiti as n
from newsroom.control_plane import cycle
from newsroom.control_plane.store import connect, insert_graphiti_ingest
from newsroom.control_plane.veto import VetoError
from newsroom.tests.test_graphiti_operational_readiness import _unit
from newsroom.projection.models import ProjectionGenerationState


def _open(tmp_path, monkeypatch, *, ingest, rights=lambda _: {"current": True}):
    connection = connect(str(tmp_path / "private.sqlite3"))
    calls = []
    admission = SimpleNamespace(
        enqueue_complete_receipts=lambda **kw: calls.append(("enqueue", kw)),
        drain=lambda **kw: calls.append(("drain", kw)),
        preflight_decided_cohort=lambda **kw: calls.append(("preflight", kw)),
        finalise_decided_cohort=lambda **kw: calls.append(("finalise", kw)),
    )
    monkeypatch.setattr(n, "EvaluationGraphitiRunner", lambda **kw: object())
    monkeypatch.setattr(n, "compose_existing_graphiti_admission_consumer", lambda *a, **kw: admission)
    monkeypatch.setattr(n, "_ingest", ingest)
    @contextmanager
    def fence():
        calls.append(("fence", {}))
        yield
    system = SimpleNamespace(**dict.fromkeys(("graphiti", "extraction", "objects", "entities", "relations", "increment4")))
    def build_current(request, **kw):
        calls.append(("empty-cohort-build", {"request": request}))
        return SimpleNamespace(generation=SimpleNamespace(state=ProjectionGenerationState.ACTIVE))
    system.increment4 = SimpleNamespace(build_current_and_promote=build_current)
    processor = n.NativeGraphitiProcessor(
        system=system, connection=connection, usage=None, proof=None,
        rights_for=rights, stop_check=lambda: None, dispatch_fence=fence,
        clock=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    )
    return processor, connection, calls


def _native(item="one"):
    unit = _unit(item_key=item)
    return replace(unit, proving_run_id="native-source:" + unit.observation_digest)


def _complete(connection, **kw):
    for unit in kw["units"]:
        insert_graphiti_ingest(
            connection, ingest_id=unit.ingest_id, source_id=unit.source_id,
            item_key=unit.item_key, outcome="COMPLETE", proposal_count=0,
            entity_count=0, relation_count=0, failure_code="",
            temporal_basis=unit.temporal().basis.value,
            reference_time=unit.temporal().reference_time.to_text(),
            generation_id="test-isolated-generation", receipt_digest=unit.digest,
        )
    connection.commit()


def test_native_cohort_finalises_once_and_replays_without_new_ingests(tmp_path, monkeypatch):
    processor, connection, calls = _open(tmp_path, monkeypatch, ingest=_complete)
    units = (_native("one"), _native("two"))
    try:
        outcomes = processor.advance(units, cycle_id="native-cycle:1")
        assert [item.state for item in outcomes] == ["GRAPHITI_COMPLETE"] * 2
        assert [entry for entry in calls if entry[0] == "finalise"] == [
            ("finalise", {"ingest_ids": tuple(sorted(unit.ingest_id for unit in units))})
        ]
        assert len([entry for entry in calls if entry[0] == "empty-cohort-build"]) == 1
        processor.advance(units, cycle_id="native-cycle:2")
        assert len([entry for entry in calls if entry[0] == "empty-cohort-build"]) == 1
        assert connection.execute("SELECT count(*) FROM unpublished_graphiti_ingest").fetchone()[0] == 2
    finally:
        connection.close()


def test_native_worker_rejects_historical_campaign_before_dispatch(tmp_path, monkeypatch):
    processor, connection, calls = _open(tmp_path, monkeypatch, ingest=lambda *a, **kw: pytest.fail("dispatch"))
    try:
        with pytest.raises(ValueError, match="historical campaign"):
            processor.advance((_unit(),), cycle_id="native-cycle:1")
        assert calls == []
    finally:
        connection.close()


def test_native_missing_or_partial_extraction_never_becomes_complete(tmp_path, monkeypatch):
    processor, connection, calls = _open(tmp_path, monkeypatch, ingest=lambda *a, **kw: None)
    try:
        result = processor.advance((_native(),), cycle_id="native-cycle:1")
        assert result[0].state == "GRAPHITI_HOLD"
        assert not any(name == "finalise" for name, _ in calls)
    finally:
        connection.close()


def test_native_rights_revocation_blocks_projection_after_extraction(tmp_path, monkeypatch):
    processor, connection, calls = _open(tmp_path, monkeypatch, ingest=_complete, rights=lambda _: None)
    try:
        result = processor.advance((_native(),), cycle_id="native-cycle:1")
        assert result[0].state == "ADMISSION_HOLD"
        assert not any(name == "finalise" for name, _ in calls)
    finally:
        connection.close()


def test_rights_hold_isolates_complete_revision_and_resumes_without_reprojection(
    tmp_path, monkeypatch
):
    held = set()
    revoked = [False]

    def complete_then_revoke(connection, **kwargs):
        assert all(kwargs["rights_check"](unit) for unit in kwargs["units"])
        _complete(connection, units=kwargs["units"])
        if not revoked[0]:
            held.add("two")
            revoked[0] = True

    processor, connection, calls = _open(
        tmp_path,
        monkeypatch,
        ingest=complete_then_revoke,
        rights=lambda unit: None if unit.item_key in held else {"current": True},
    )
    units = (_native("one"), _native("two"))
    try:
        first = processor.advance(units, cycle_id="one")
        assert [item.state for item in first] == [
            "GRAPHITI_COMPLETE",
            "ADMISSION_HOLD",
        ]
        assert [
            kwargs["ingest_ids"]
            for name, kwargs in calls
            if name == "finalise"
        ] == [(units[0].ingest_id,)]

        held.clear()
        second = processor.advance(units, cycle_id="two")
        assert [item.state for item in second] == ["GRAPHITI_COMPLETE"] * 2
        assert [
            kwargs["ingest_ids"]
            for name, kwargs in calls
            if name == "finalise"
        ] == [(units[0].ingest_id,), (units[1].ingest_id,)]
    finally:
        connection.close()


def test_admission_preflight_isolates_bad_revision_then_projects_only_verified(
    tmp_path, monkeypatch
):
    from newsroom.control_plane.graphiti_admission import (
        GraphitiAdmissionConsumerError,
    )

    processor, connection, calls = _open(
        tmp_path, monkeypatch, ingest=_complete
    )
    units = (_native("one"), _native("two"))
    held = {units[1].ingest_id}

    def preflight(*, ingest_ids):
        calls.append(("preflight", {"ingest_ids": ingest_ids}))
        if set(ingest_ids) & held:
            raise GraphitiAdmissionConsumerError(
                "exact Graphiti cohort contains non-terminal work"
            )

    processor._admission.preflight_decided_cohort = preflight
    try:
        first = processor.advance(units, cycle_id="one")
        assert [item.state for item in first] == [
            "GRAPHITI_COMPLETE",
            "ADMISSION_HOLD",
        ]
        assert first[1].reason == (
            "exact Graphiti cohort contains non-terminal work"
        )
        assert [
            kwargs["ingest_ids"]
            for name, kwargs in calls
            if name == "finalise"
        ] == [(units[0].ingest_id,)]
        assert len([
            entry for entry in calls if entry[0] == "empty-cohort-build"
        ]) == 1

        held.clear()
        second = processor.advance(units, cycle_id="two")
        assert [item.state for item in second] == ["GRAPHITI_COMPLETE"] * 2
        assert [
            kwargs["ingest_ids"]
            for name, kwargs in calls
            if name == "finalise"
        ] == [(units[0].ingest_id,), (units[1].ingest_id,)]
        assert len([
            entry for entry in calls if entry[0] == "empty-cohort-build"
        ]) == 2
    finally:
        connection.close()


def test_actual_consumer_preflight_has_no_projection_and_reuses_finaliser_checks(
    tmp_path
):
    from newsroom.control_plane.graphiti_admission import (
        GraphitiAdmissionConsumerError,
        GraphitiProposalAdmissionAction,
    )
    from newsroom.extraction.types import ExtractionProposalKind
    from newsroom.tests.test_graphiti_admission_consumer import (
        _Authority,
        _Projector,
        _Rights,
        _consumer,
        _draft,
        _seed_receipt,
    )

    connection = connect(str(tmp_path / "actual-preflight.sqlite3"))
    first_id = "00000000-0000-4000-8000-000000008101"
    second_id = "00000000-0000-4000-8000-000000008102"
    first = _draft("entity.8101", ExtractionProposalKind.ENTITY_MENTION)
    second = _draft("entity.8102", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, first, ingest_id=first_id)
    _seed_receipt(connection, second, ingest_id=second_id)
    projector = _Projector()
    consumer = _consumer(
        connection,
        _Authority({
            first.local_id: GraphitiProposalAdmissionAction.ADMIT,
            second.local_id: GraphitiProposalAdmissionAction.ADMIT,
        }),
        projector,
        _Rights(),
    )
    try:
        assert consumer.enqueue_complete_receipts(
            ingest_ids=(first_id, second_id)
        ) == 2
        assert consumer.drain(
            worker_id="first", limit=1, ingest_ids=(first_id,)
        ).decided == 1

        consumer.preflight_decided_cohort(ingest_ids=(first_id,))
        with pytest.raises(
            GraphitiAdmissionConsumerError, match="not completely decided"
        ):
            consumer.preflight_decided_cohort(ingest_ids=(second_id,))
        assert projector.generation_calls == []

        assert consumer.drain(
            worker_id="second", limit=1, ingest_ids=(second_id,)
        ).decided == 1
        consumer.preflight_decided_cohort(ingest_ids=(second_id,))
        result = consumer.finalise_decided_cohort(
            ingest_ids=(first_id, second_id)
        )
        assert result.projected == 2
        assert len(projector.generation_calls) == 1
        consumer.preflight_decided_cohort(ingest_ids=(first_id,))
        assert len(projector.generation_calls) == 1
    finally:
        connection.close()


def test_native_fence_passes_bounded_deadline_and_current_rights(tmp_path, monkeypatch):
    processor, connection, calls = _open(tmp_path, monkeypatch, ingest=lambda *a, **kw: None)
    try:
        with processor._fence(_native()) as authority:
            assert authority.rights == {"current": True}
            assert authority.deadline == datetime(2026, 9, 8, 0, 15, tzinfo=UTC)
        assert calls == [("fence", {})]
    finally:
        connection.close()


def test_native_fence_authorises_its_provider_callback_thread_only_while_held(
    tmp_path, monkeypatch,
):
    proving = tmp_path / "proving.sqlite3"
    with sqlite3.connect(proving) as database:
        database.executescript(
            """
            CREATE TABLE proving_runs(run_id TEXT PRIMARY KEY);
            CREATE TABLE proving_gates(
                run_id TEXT NOT NULL, gate_id TEXT NOT NULL, status TEXT NOT NULL
            );
            INSERT INTO proving_runs VALUES('run-1');
            INSERT INTO proving_gates VALUES(
                'run-1', 'NO_ACTIVE_HUMAN_EMERGENCY_STOP', 'PASS'
            );
            """
        )
    monkeypatch.setattr(cycle, "_PROVING_FENCE_TIMEOUT_SECONDS", 0.05)
    processor, connection, _ = _open(tmp_path, monkeypatch, ingest=lambda *a, **kw: None)
    processor._dispatch_fence = lambda: cycle.owner_emergency_stop_fence(str(proving))
    processor._stop_check = lambda: cycle.assert_no_owner_emergency_stop(str(proving))
    errors = []
    try:
        with processor._fence(_native()) as authority:
            worker = threading.Thread(
                target=lambda: _capture_error(authority.owner_stop_check, errors)
            )
            worker.start()
            worker.join(timeout=0.5)
            assert not worker.is_alive()
            assert errors == []
            parent_pid = n.os.getpid()
            with monkeypatch.context() as child:
                child.setattr(n.os, "getpid", lambda: parent_pid + 1)
                with pytest.raises(VetoError, match="belongs to another process"):
                    authority.owner_stop_check()
        with pytest.raises(VetoError, match="fence has expired"):
            authority.owner_stop_check()
    finally:
        connection.close()


def _capture_error(operation, errors):
    try:
        operation()
    except Exception as exc:
        errors.append(exc)


def test_incomplete_chunk_prefix_does_not_poison_the_completed_revision(tmp_path, monkeypatch):
    from newsroom.control_plane.corpus import MAX_EPISODE_BYTES
    base = replace(_native(), body="Retained source text. " * (MAX_EPISODE_BYTES // 22 + 1))
    units = tuple(replace(base, chunk_ordinal=ordinal, chunk_count=2) for ordinal in (1, 2))
    ready = [units[:1]]
    def ingest(connection, **kw):
        _complete(connection, units=ready[0])
    processor, connection, calls = _open(tmp_path, monkeypatch, ingest=ingest)
    try:
        first = processor.advance(units, cycle_id="one")
        assert not any(item.state == "GRAPHITI_COMPLETE" for item in first)
        assert not any(name == "finalise" for name, _ in calls)
        ready[0] = units
        second = processor.advance(units, cycle_id="two")
        assert all(item.state == "GRAPHITI_COMPLETE" for item in second)
        assert [kw["ingest_ids"] for name, kw in calls if name == "finalise"] == [tuple(sorted(unit.ingest_id for unit in units))]
    finally:
        connection.close()


def test_completed_cohort_continues_a_subset_without_rebuilding(tmp_path, monkeypatch):
    processor, connection, calls = _open(tmp_path, monkeypatch, ingest=_complete)
    units = (_native("one"), _native("two"))
    try:
        processor.advance(units, cycle_id="one")
        before = len(calls)
        result = processor.advance(units[:1], cycle_id="resume-after-first-revision-journal-write")
        assert result[0].state == "GRAPHITI_COMPLETE"
        assert not any(name == "finalise" for name, _ in calls[before:])
    finally:
        connection.close()


def test_native_worker_rejects_another_observation_before_dispatch(tmp_path, monkeypatch):
    processor, connection, calls = _open(tmp_path, monkeypatch, ingest=lambda *a, **kw: pytest.fail("dispatch"))
    try:
        with pytest.raises(ValueError, match="observation provenance"):
            processor.advance((replace(_native(), observation_digest="sha256:" + "f" * 64),), cycle_id="one")
        assert not calls
    finally:
        connection.close()
