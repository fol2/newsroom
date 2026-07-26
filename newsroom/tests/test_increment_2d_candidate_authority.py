from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthenticationProof
from newsroom.authority.migrations import SCHEMA_VERSION
from newsroom.increment2 import (
    DevelopmentCandidateAdmissionRequest,
    INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
)
from newsroom.integrated import CandidateAdmissionOutcome, IntegratedTriageProposalId
from newsroom.relations import (
    INTEGRATED_FIXTURE_V2,
    RelationCurrentState,
    RelationDecisionAction,
)
from newsroom.retrieval import (
    RetrievalContextV2Id,
    RetrievalOutcome,
    RetrievalStateError,
)

from .increment_2d_helpers import (
    MemoryHybridRetrievalAdapter,
    fixture_passage_admission_id,
    open_candidate_object_system,
    open_candidate_relation_system,
    candidate_request,
    open_candidate_test_system,
    proof,
    retained_relation_identities,
    retrieval_request,
    scopes,
    seed_active_retrieval_authority,
)

from .relation_2a_helpers import decision_request
from .retrieval_2c_helpers import block_active_retrieval_generation


def _complete_context(system, *, key: str):
    result = system.retrieval.find_related_event_candidates(
        retrieval_request(key=key),
        proof=proof(),
    )
    assert result.context is not None
    return result.context


def test_schema_version_advances_to_candidate_authority_v9(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    system.close()
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 9
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {
        "development_candidates_v2",
        "development_candidate_versions_v2",
        "development_candidate_admission_decisions_v2",
    } <= names


def test_fixture_candidate_manifest_contains_minimum_handoff_content() -> None:
    manifest = INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE
    assert manifest.coverage_basis
    assert manifest.hypothesis_summary.startswith("Unverified development hypothesis:")
    assert manifest.geography == "synthetic_hong_kong"
    assert manifest.category == "formal_process_update"
    assert manifest.urgency == "time_bounded_material_change"
    assert "27 March 2042" in manifest.likely_new_information
    assert manifest.reader_utility_basis
    assert len(manifest.uncertainties) == 2
    assert len(manifest.evidence_objectives) == 3
    assert manifest.coverage_contract_version
    assert manifest.triage_policy_version
    assert manifest.retrieval_policy_version
    assert manifest.admission_policy_version
    assert manifest.canonical_value()["hypothesis_trust_scope"] == "PROPOSED"


def test_complete_context_admits_and_replays_exact_development_candidate(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        context = _complete_context(system, key="increment-2d-context")
        request = candidate_request(context, key="increment-2d-admit")
        admitted = system.candidates.admit(request, proof=proof())
        replay = system.candidates.admit(request, proof=proof())
        assert admitted == replay
        assert admitted.outcome is CandidateAdmissionOutcome.ADMITTED
        assert admitted.retrieval_context_id == context.context_id
        assert admitted.retrieval_context_digest == context.context_digest
        assert admitted.manifest_digest == (
            INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE.manifest_digest
        )
        assert admitted.semantic_collision_digest == (
            INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE.semantic_collision_digest
        )
        assert system.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
    finally:
        system.close()


def test_equivalent_context_deduplicates_to_same_candidate_and_version(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        first_context = _complete_context(system, key="increment-2d-context-1")
        first = system.candidates.admit(
            candidate_request(first_context, key="increment-2d-admit-1"),
            proof=proof(),
        )
        second_context = _complete_context(system, key="increment-2d-context-2")
        second = system.candidates.admit(
            candidate_request(second_context, key="increment-2d-admit-2"),
            proof=proof(),
        )
        assert second.outcome is CandidateAdmissionOutcome.DEDUPLICATED
        assert second.candidate_id == first.candidate_id
        assert second.candidate_version_id == first.candidate_version_id
        assert second.retrieval_context_id == second_context.context_id
    finally:
        system.close()


def test_admission_authenticates_before_context_lookup(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    denied = scopes() - {"authority.candidate.admit"}
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
        granted_scopes=denied,
    )
    try:
        request = DevelopmentCandidateAdmissionRequest(
            proposal_id=IntegratedTriageProposalId.new(),
            retrieval_context_id=RetrievalContextV2Id.new(),
            expected_context_digest="sha256:" + "a" * 64,
            idempotency_key="increment-2d-denied",
        )
        with pytest.raises(PermissionError):
            system.candidates.admit(request, proof=proof())
    finally:
        system.close()


def test_context_digest_rebinding_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        context = _complete_context(system, key="increment-2d-context-rebind")
        request = candidate_request(context, key="increment-2d-rebind")
        rebound = replace(
            request,
            expected_context_digest="sha256:" + "b" * 64,
        )
        with pytest.raises(Exception):
            system.candidates.admit(rebound, proof=proof())
    finally:
        system.close()


def test_reopen_rejects_redigested_normalized_candidate_tamper(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        context = _complete_context(system, key="increment-2d-tamper-context")
        system.candidates.admit(
            candidate_request(context, key="increment-2d-tamper-admit"),
            proof=proof(),
        )
    finally:
        system.close()
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TRIGGER immutable_development_candidate_version_update")
        conn.execute(
            "UPDATE development_candidate_versions_v2 "
            "SET canonical_process_id='SYN-PROC-TAMPERED'"
        )
        conn.commit()
    with pytest.raises(Exception):
        open_candidate_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )


def _candidate_counts(database: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(database) as conn:
        return tuple(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "development_candidates_v2",
                "development_candidate_versions_v2",
                "development_candidate_admission_decisions_v2",
                "ledger_events",
            )
        )


def test_restart_revalidates_and_replays_without_rewriting_candidate_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    request = None
    admitted = None
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        context = _complete_context(system, key="increment-2d-restart-context")
        request = candidate_request(context, key="increment-2d-restart-admit")
        admitted = system.candidates.admit(request, proof=proof())
    finally:
        system.close()
    assert request is not None and admitted is not None
    before = _candidate_counts(database)

    reopened = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        assert reopened.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        assert reopened.candidates.admit(request, proof=proof()) == admitted
    finally:
        reopened.close()

    assert _candidate_counts(database) == before


def test_relation_revocation_preserves_candidate_history_and_blocks_later_admission(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        context = _complete_context(system, key="increment-2d-relation-context")
        admitted = system.candidates.admit(
            candidate_request(context, key="increment-2d-relation-admit"),
            proof=proof(),
        )
    finally:
        system.close()
    before = _candidate_counts(database)

    proposal_id, decision_id = retained_relation_identities(database)
    relations = open_candidate_relation_system(database)
    try:
        proposal = relations.relations.proposal(proposal_id, proof=proof())
        revoked = relations.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.REVOKE,
                expected_version=1,
                previous_decision_id=decision_id,
                key="increment-2d-relation-revoke",
            ),
            proof=proof(),
        )
        assert revoked.current_state is RelationCurrentState.REVOKED
    finally:
        relations.close()

    adapter = MemoryHybridRetrievalAdapter()
    reopened = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        assert reopened.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        with pytest.raises(RetrievalStateError, match="source watermark is stale"):
            reopened.candidates.admit(
                candidate_request(context, key="increment-2d-after-relation-revoke"),
                proof=proof(),
            )
        later = reopened.retrieval.find_related_event_candidates(
            retrieval_request(key="increment-2d-context-after-relation-revoke"),
            proof=proof(),
        )
        assert later.outcome is RetrievalOutcome.STALE
        assert later.context is None
        assert later.failure is not None
        assert later.failure.reason_code == "RETRIEVAL_SOURCE_STALE"
        assert adapter.call_count == 0
    finally:
        reopened.close()

    after = _candidate_counts(database)
    assert after[:3] == before[:3]
    assert after[3] > before[3]


def test_tombstoned_hydration_preserves_candidate_history_and_never_replays_bytes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    retrieval = retrieval_request(key="increment-2d-object-context")
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        result = system.retrieval.find_related_event_candidates(
            retrieval,
            proof=proof(),
        )
        assert result.context is not None
        context = result.context
        admitted = system.candidates.admit(
            candidate_request(context, key="increment-2d-object-admit"),
            proof=proof(),
        )
    finally:
        system.close()
    before = _candidate_counts(database)

    passage = INTEGRATED_FIXTURE_V2.passage_by_id["ifv2-prior-en"]
    admission_id = fixture_passage_admission_id(
        database,
        passage_id=passage.passage_id,
    )
    objects = open_candidate_object_system(database, object_root=object_root)
    try:
        objects.objects.revoke(
            admission_id,
            reason_code="INCREMENT_2D_PRIOR_PASSAGE_REVOKED",
            idempotency_key="increment-2d-prior-passage-revoke",
            proof=proof(),
        )
        deletion = objects.objects.request_deletion(
            passage.blob_digest,
            reason_code="INCREMENT_2D_PRIOR_PASSAGE_DELETE",
            idempotency_key="increment-2d-prior-passage-delete",
            proof=proof(),
        )
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="INCREMENT_2D_PRIOR_PASSAGE_TOMBSTONE",
            idempotency_key="increment-2d-prior-passage-tombstone",
            proof=proof(),
        )
    finally:
        objects.close()

    adapter = MemoryHybridRetrievalAdapter()
    reopened = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        assert reopened.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        with pytest.raises(RetrievalStateError, match="source watermark is stale"):
            reopened.candidates.admit(
                candidate_request(context, key="increment-2d-after-tombstone"),
                proof=proof(),
            )
        replay = reopened.retrieval.find_related_event_candidates(
            retrieval,
            proof=proof(),
        )
        assert replay.replayed is True
        assert replay.outcome is RetrievalOutcome.STALE
        assert replay.context is None
        assert replay.failure is not None
        assert replay.failure.reason_code == "RETRIEVAL_SOURCE_STALE"
        assert adapter.call_count == 0
    finally:
        reopened.close()

    after = _candidate_counts(database)
    assert after[:3] == before[:3]
    assert after[3] > before[3]


@pytest.mark.parametrize(
    ("dead_letter", "reason_code"),
    (
        (False, "RETRIEVAL_GAP_BLOCKED"),
        (True, "RETRIEVAL_DEAD_LETTER_BLOCKED"),
    ),
)
def test_gap_or_dead_letter_cannot_create_context_or_candidate(
    tmp_path: Path,
    dead_letter: bool,
    reason_code: str,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    block_active_retrieval_generation(
        database,
        object_root=object_root,
        dead_letter=dead_letter,
    )
    adapter = MemoryHybridRetrievalAdapter()
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        result = system.retrieval.find_related_event_candidates(
            retrieval_request(
                key=(
                    "increment-2d-dead-letter-context"
                    if dead_letter
                    else "increment-2d-gap-context"
                )
            ),
            proof=proof(),
        )
        assert result.outcome is RetrievalOutcome.INCOMPLETE
        assert result.context is None
        assert result.failure is not None
        assert result.failure.reason_code == reason_code
        assert adapter.call_count == 0
    finally:
        system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM hybrid_retrieval_contexts_v2"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM development_candidates_v2"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM development_candidate_versions_v2"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM development_candidate_admission_decisions_v2"
        ).fetchone()[0] == 0
