from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import json
import sqlite3

import pytest

from newsroom.authority import (
    AuthenticationProof,
    AuthorityPersistenceError,
    IdempotencyConflict,
    StaticAuthorizer,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.authority.migrations import SCHEMA_VERSION
from newsroom.increment2 import (
    DevelopmentCandidateAdmissionRequest,
    INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
)
from newsroom.integrated import CandidateAdmissionOutcome, IntegratedTriageProposalId
from newsroom.projection.neo4j import (
    CompleteDerivativeType,
    Neo4jIdentityConflict,
)
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
    block_active_candidate_generation,
    candidate_request,
    fixture_passage_admission_id,
    open_candidate_object_system,
    open_candidate_relation_system,
    open_candidate_test_system,
    proof,
    rebuild_replacement_generation,
    replace_active_retrieval_generation,
    retained_relation_identities,
    retrieval_request,
    scopes,
    seed_active_retrieval_authority,
)

from .relation_2a_helpers import decision_request


def _complete_context(system, *, key: str):
    result = system.retrieval.find_related_event_candidates(
        retrieval_request(key=key),
        proof=proof(),
    )
    assert result.context is not None
    return result.context


def _admit_fixture_candidate(tmp_path: Path, *, key: str):
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        context = _complete_context(system, key=f"{key}-context")
        request = candidate_request(context, key=f"{key}-admit")
        admitted = system.candidates.admit(request, proof=proof())
    finally:
        system.close()
    return database, object_root, context, request, admitted


def _candidate_counts(database: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(database) as conn:
        return tuple(
            int(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in (
                "development_candidates_v2",
                "development_candidate_versions_v2",
                "development_candidate_admission_decisions_v2",
                "ledger_events",
            )
        )


def _trigger_sql(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and isinstance(row[0], str)
    return str(row[0])


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


def test_replacement_generation_recovery_deduplicates_without_rewriting_history(
    tmp_path: Path,
) -> None:
    database, object_root, _context, _request, admitted = (
        _admit_fixture_candidate(tmp_path, key="increment-2d-replacement")
    )
    replacement_id = replace_active_retrieval_generation(
        database,
        object_root=object_root,
        suffix="candidate-recovery",
    )

    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        recovered_context = _complete_context(
            system,
            key="increment-2d-replacement-recovered-context",
        )
        assert recovered_context.projection.identity.generation_id == replacement_id
        recovered = system.candidates.admit(
            candidate_request(
                recovered_context,
                key="increment-2d-replacement-recovered-admit",
            ),
            proof=proof(),
        )
        assert recovered.outcome is CandidateAdmissionOutcome.DEDUPLICATED
        assert recovered.candidate_id == admitted.candidate_id
        assert recovered.candidate_version_id == admitted.candidate_version_id
        assert recovered.decision_id != admitted.decision_id
        assert system.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        assert _candidate_counts(database)[:3] == (1, 1, 2)
    finally:
        system.close()


def test_relation_revocation_preserves_candidate_history_and_blocks_later_admission(
    tmp_path: Path,
) -> None:
    database, object_root, context, original_request, admitted = (
        _admit_fixture_candidate(tmp_path, key="increment-2d-relation-revoke")
    )
    proposal_id, admission_decision_id = retained_relation_identities(database)
    with open_candidate_relation_system(database) as relation_system:
        proposal = relation_system.relations.proposal(proposal_id, proof=proof())
        revoked = relation_system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.REVOKE,
                expected_version=1,
                previous_decision_id=admission_decision_id,
                key="increment-2d-revoke-admitted-development",
            ),
            proof=proof(),
        )
        assert revoked.current_state is RelationCurrentState.REVOKED

    stale = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        assert stale.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        with pytest.raises(RetrievalStateError, match="source watermark is stale"):
            stale.candidates.admit(original_request, proof=proof())
        assert _candidate_counts(database)[:3] == (1, 1, 1)
    finally:
        stale.close()

    replace_active_retrieval_generation(
        database,
        object_root=object_root,
        suffix="after-relation-revocation",
    )
    current = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        later_context = _complete_context(
            current,
            key="increment-2d-after-relation-revocation",
        )
        with pytest.raises(
            AuthorityPersistenceError,
            match="relation is not currently admitted",
        ):
            current.candidates.admit(
                candidate_request(
                    later_context,
                    key="increment-2d-revoked-relation-admit",
                ),
                proof=proof(),
            )
        assert current.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        assert context.context_digest == admitted.retrieval_context_digest
        assert _candidate_counts(database)[:3] == (1, 1, 1)
    finally:
        current.close()


def test_governed_deletion_preserves_candidate_history_and_prevents_resurrection(
    tmp_path: Path,
) -> None:
    database, object_root, _context, original_request, admitted = (
        _admit_fixture_candidate(tmp_path, key="increment-2d-object-delete")
    )
    passage = INTEGRATED_FIXTURE_V2.passage_by_id["ifv2-prior-en"]
    admission_id = fixture_passage_admission_id(
        database,
        passage_id=passage.passage_id,
    )
    with open_candidate_object_system(
        database,
        object_root=object_root,
    ) as object_system:
        object_system.objects.revoke(
            admission_id,
            reason_code="INCREMENT_2D_PRIOR_PASSAGE_REVOKED",
            idempotency_key="increment-2d-prior-passage-revoke",
            proof=proof(),
        )
        deletion = object_system.objects.request_deletion(
            passage.blob_digest,
            reason_code="INCREMENT_2D_PRIOR_PASSAGE_DELETE",
            idempotency_key="increment-2d-prior-passage-delete",
            proof=proof(),
        )
        object_system.objects.tombstone(
            deletion.deletion_id,
            reason_code="INCREMENT_2D_PRIOR_PASSAGE_TOMBSTONE",
            idempotency_key="increment-2d-prior-passage-tombstone",
            proof=proof(),
        )

    stale = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        assert stale.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        with pytest.raises(RetrievalStateError):
            stale.candidates.admit(original_request, proof=proof())
    finally:
        stale.close()

    adapter, replacement_id, _checkpoint = rebuild_replacement_generation(
        database,
        object_root=object_root,
        suffix="after-prior-passage-tombstone",
    )
    documents = tuple(
        document
        for (generation_id, _ledger_seq), batch in adapter.deliveries.items()
        if generation_id == str(replacement_id)
        for document in batch.documents
    )
    removals = tuple(
        removal
        for (generation_id, _ledger_seq), batch in adapter.deliveries.items()
        if generation_id == str(replacement_id)
        for removal in batch.removals
        if removal.stable_key == passage.passage_id
    )
    assert passage.passage_id not in {item.passage_id for item in documents}
    assert {item.derivative_type for item in removals} == {
        CompleteDerivativeType.FULL_TEXT,
        CompleteDerivativeType.VECTOR,
    }
    assert all(item.object_admission_ids == (admission_id,) for item in removals)
    with pytest.raises(
        Neo4jIdentityConflict,
        match="active set differs from fixture",
    ):
        replace_active_retrieval_generation(
            database,
            object_root=object_root,
            suffix="after-prior-passage-tombstone-qualification",
        )

    current = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        result = current.retrieval.find_related_event_candidates(
            retrieval_request(key="increment-2d-after-tombstone-retrieval"),
            proof=proof(),
        )
        assert result.outcome is RetrievalOutcome.STALE
        assert result.context is None
        assert result.failure is not None
        assert result.failure.reason_code == "RETRIEVAL_SOURCE_STALE"
        assert current.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        assert _candidate_counts(database)[:3] == (1, 1, 1)
    finally:
        current.close()


@pytest.mark.parametrize(
    ("dead_letter", "reason_fragment", "failure_code"),
    (
        (False, "required gap", "RETRIEVAL_GAP_BLOCKED"),
        (True, "dead letter", "RETRIEVAL_DEAD_LETTER_BLOCKED"),
    ),
)
def test_gap_or_dead_letter_preserves_history_and_blocks_candidate_reuse(
    tmp_path: Path,
    dead_letter: bool,
    reason_fragment: str,
    failure_code: str,
) -> None:
    database, object_root, _context, original_request, admitted = (
        _admit_fixture_candidate(
            tmp_path,
            key=f"increment-2d-blocked-{dead_letter}",
        )
    )
    block_active_candidate_generation(
        database,
        object_root=object_root,
        dead_letter=dead_letter,
    )
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
    )
    try:
        assert system.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
        with pytest.raises(RetrievalStateError, match=reason_fragment):
            system.candidates.admit(original_request, proof=proof())
        blocked = system.retrieval.find_related_event_candidates(
            retrieval_request(
                key=f"increment-2d-blocked-retrieval-{dead_letter}"
            ),
            proof=proof(),
        )
        assert blocked.outcome is RetrievalOutcome.INCOMPLETE
        assert blocked.context is None
        assert blocked.failure is not None
        assert blocked.failure.reason_code == failure_code
        assert _candidate_counts(database)[:3] == (1, 1, 1)
    finally:
        system.close()




class _RecordingAuthorizer:
    def __init__(self, delegate: StaticAuthorizer) -> None:
        self._delegate = delegate
        self.requests: list[object] = []

    def authorize(self, context, request, *, now):
        self.requests.append(request)
        return self._delegate.authorize(context, request, now=now)


def test_candidate_decision_read_uses_candidate_security_scope(
    tmp_path: Path,
) -> None:
    database, object_root, _context, _request, admitted = (
        _admit_fixture_candidate(tmp_path, key="increment-2d-read-scope")
    )
    recorder = _RecordingAuthorizer(
        StaticAuthorizer(
            policy_version="increment-2d-read-scope-v1",
            grants_by_principal={"principal.alpha": scopes()},
        )
    )
    system = open_candidate_test_system(
        database,
        object_root=object_root,
        adapter=MemoryHybridRetrievalAdapter(),
        authorizer=recorder,
    )
    try:
        assert system.candidates.decision(
            admitted.decision_id,
            proof=proof(),
        ) == admitted
    finally:
        system.close()
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert getattr(request, "required_scope") == "authority.candidate.read"
    assert getattr(request, "security_scope") == "authority.candidate"

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
        with pytest.raises(
            IdempotencyConflict,
            match="expected context digest differs",
        ):
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
        trigger_sql = _trigger_sql(
            conn,
            "immutable_development_candidate_version_update",
        )
        conn.execute("DROP TRIGGER immutable_development_candidate_version_update")
        conn.execute(
            "UPDATE development_candidate_versions_v2 "
            "SET canonical_process_id='SYN-PROC-TAMPERED'"
        )
        conn.execute(trigger_sql)
        conn.commit()
    with pytest.raises(
        AuthorityPersistenceError,
        match="development Candidate version normalized columns differ",
    ):
        open_candidate_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )



def test_reopen_rejects_normalized_candidate_decision_tamper(
    tmp_path: Path,
) -> None:
    database, object_root, _context, _request, _admitted = (
        _admit_fixture_candidate(tmp_path, key="decision-normalized-tamper")
    )
    with sqlite3.connect(database) as conn:
        trigger_sql = _trigger_sql(
            conn,
            "immutable_development_candidate_decision_update",
        )
        conn.execute(
            "DROP TRIGGER immutable_development_candidate_decision_update"
        )
        conn.execute(
            "UPDATE development_candidate_admission_decisions_v2 "
            "SET relation_key=?",
            ("sha256:" + "f" * 64,),
        )
        conn.execute(trigger_sql)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="development Candidate decision normalized columns differ",
    ):
        open_candidate_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )


def test_reopen_rejects_redigested_candidate_decision_outcome_tamper(
    tmp_path: Path,
) -> None:
    database, object_root, _context, _request, _admitted = (
        _admit_fixture_candidate(tmp_path, key="decision-outcome-tamper")
    )
    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT canonical_bytes FROM "
            "development_candidate_admission_decisions_v2"
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row[0]).decode("utf-8"))
        value["outcome"] = CandidateAdmissionOutcome.DEDUPLICATED.value
        canonical = canonical_json_bytes(value)
        trigger_sql = _trigger_sql(
            conn,
            "immutable_development_candidate_decision_update",
        )
        conn.execute(
            "DROP TRIGGER immutable_development_candidate_decision_update"
        )
        conn.execute(
            "UPDATE development_candidate_admission_decisions_v2 "
            "SET outcome=?,canonical_bytes=?,canonical_digest=?",
            (
                CandidateAdmissionOutcome.DEDUPLICATED.value,
                canonical,
                digest_bytes(canonical),
            ),
        )
        conn.execute(trigger_sql)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="development Candidate identity chronology differs",
    ):
        open_candidate_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )


def test_reopen_rejects_candidate_identity_chronology_tamper(
    tmp_path: Path,
) -> None:
    database, object_root, _context, _request, _admitted = (
        _admit_fixture_candidate(tmp_path, key="candidate-chronology-tamper")
    )
    with sqlite3.connect(database) as conn:
        trigger_sql = _trigger_sql(
            conn,
            "immutable_development_candidate_update",
        )
        conn.execute("DROP TRIGGER immutable_development_candidate_update")
        conn.execute(
            "UPDATE development_candidates_v2 "
            "SET created_at='2042-03-12T12:00:01.000000Z'"
        )
        conn.execute(trigger_sql)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="development Candidate identity chronology differs",
    ):
        open_candidate_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )


def test_reopen_rejects_candidate_command_payload_rebinding(
    tmp_path: Path,
) -> None:
    database, object_root, _context, _request, _admitted = (
        _admit_fixture_candidate(tmp_path, key="candidate-payload-tamper")
    )
    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT e.payload_id,p.payload_bytes "
            "FROM development_candidate_admission_decisions_v2 d "
            "JOIN ledger_events e ON e.event_id=d.authority_event_id "
            "JOIN authority_payloads p ON p.payload_id=e.payload_id"
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row[1]).decode("utf-8"))
        value["expected_context_digest"] = "sha256:" + "e" * 64
        canonical = canonical_json_bytes(value)
        digest = digest_bytes(canonical)
        payload_trigger = _trigger_sql(conn, "immutable_authority_payloads_update")
        event_trigger = _trigger_sql(conn, "immutable_ledger_events_update")
        conn.execute("DROP TRIGGER immutable_authority_payloads_update")
        conn.execute("DROP TRIGGER immutable_ledger_events_update")
        conn.execute(
            "UPDATE authority_payloads SET payload_bytes=?,payload_digest=? "
            "WHERE payload_id=?",
            (canonical, digest, str(row[0])),
        )
        conn.execute(
            "UPDATE ledger_events SET payload_digest=? WHERE payload_id=?",
            (digest, str(row[0])),
        )
        conn.execute(payload_trigger)
        conn.execute(event_trigger)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="development Candidate decision payload differs from authority",
    ):
        open_candidate_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
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
