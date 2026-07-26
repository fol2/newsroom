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
from newsroom.retrieval import RetrievalContextV2Id

from .increment_2d_helpers import (
    MemoryHybridRetrievalAdapter,
    candidate_request,
    open_candidate_test_system,
    proof,
    retrieval_request,
    scopes,
    seed_active_retrieval_authority,
)


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
