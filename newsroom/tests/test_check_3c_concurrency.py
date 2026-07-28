from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

from newsroom.checks import AdmissionRecordState
from newsroom.discovery_adapters import run_fixture_adapter

from .check_3c_authority_helpers import open_check_system, proof
from .test_check_3c_admission import (
    _adapter_request,
    _admission,
    _scenario,
    _seed_check,
    _seed_source,
)


def test_competing_workers_converge_on_one_exact_authority_lineage(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    _seed_source(system)
    adapter_request = _adapter_request(suffix=31)
    proposal = run_fixture_adapter(
        adapter_request,
        _scenario(adapter_request, suffix=31),
    )
    request, attempt = _seed_check(system, adapter_request, suffix=31)
    admission = _admission(request, attempt, adapter_request, proposal)
    barrier = Barrier(2)

    def admit():
        barrier.wait(timeout=10)
        return system.checks.admit_proposal(admission, proof=proof())

    with ThreadPoolExecutor(max_workers=2) as executor:
        left_future = executor.submit(admit)
        right_future = executor.submit(admit)
        left = left_future.result(timeout=30)
        right = right_future.result(timeout=30)

    assert left.outcome.event_id == right.outcome.event_id
    assert left.baseline is not None and right.baseline is not None
    assert left.baseline.event_id == right.baseline.event_id
    assert left.observations[0].item.event_id == right.observations[0].item.event_id
    assert (
        left.observations[0].revision.event_id
        == right.observations[0].revision.event_id
    )
    assert (
        left.observations[0].occurrence.event_id
        == right.observations[0].occurrence.event_id
    )
    created_occurrences = sum(
        result.observations[0].occurrence_state is AdmissionRecordState.CREATED
        for result in (left, right)
    )
    assert created_occurrences == 1
    assert {
        left.observations[0].occurrence_state,
        right.observations[0].occurrence_state,
    } <= {
        AdmissionRecordState.CREATED,
        AdmissionRecordState.REUSED,
        AdmissionRecordState.REPLAYED,
    }
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM check_outcomes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_items").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_representations"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_occurrences"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM baseline_decisions"
        ).fetchone()[0] == 1


def test_crash_after_baseline_resumes_missing_activation_transition(
    tmp_path,
    monkeypatch,
) -> None:
    from newsroom.authority._proposal_admission import _ProposalAdmissionBoundary
    from newsroom.sources import ObservationModel

    from .test_check_3c_model_policies import (
        _adapter_request as model_adapter_request,
        _admission as model_admission,
        _proposal as model_proposal,
        _seed_check as model_seed_check,
        _seed_source as model_seed_source,
    )

    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    model_seed_source(system, ObservationModel.COMPLETE_CURRENT_STATE)
    adapter_request = model_adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=32,
    )
    proposal = model_proposal(
        adapter_request,
        suffix=32,
        items=[
            {
                "id": "crash-active",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "active",
                "title": "Crash recovery item",
            }
        ],
    )
    request, attempt = model_seed_check(
        system,
        adapter_request,
        suffix=32,
    )
    admission = model_admission(
        request,
        attempt,
        adapter_request,
        proposal,
    )
    original = _ProposalAdmissionBoundary._commit_decisions

    class InjectedCrash(RuntimeError):
        pass

    def crash_after_baseline(self, authorized):
        plan = authorized.plan
        assert plan.baseline_request is not None
        assert authorized.baseline_grant is not None
        self._store.commit_baseline_decision(
            authorized.baseline_grant,
            request=plan.baseline_request,
        )
        raise InjectedCrash("after baseline before activation")

    monkeypatch.setattr(
        _ProposalAdmissionBoundary,
        "_commit_decisions",
        crash_after_baseline,
    )
    try:
        import pytest

        with pytest.raises(InjectedCrash):
            system.checks.admit_proposal(admission, proof=proof())
    finally:
        monkeypatch.setattr(
            _ProposalAdmissionBoundary,
            "_commit_decisions",
            original,
        )

    resumed = system.checks.admit_proposal(admission, proof=proof())

    assert resumed.baseline is not None
    assert len(resumed.transitions) == 1
    assert resumed.transitions[0].request.kind.value == "ACTIVATED"
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM check_outcomes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM baseline_decisions").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM observable_transitions"
        ).fetchone()[0] == 1
