from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.increment2 import (
    INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
    Increment2CompleteProofController,
    Increment2PreparedAuthority,
    Increment2ProofEnvironment,
    Increment2ProofKeys,
    Increment2ProofStateError,
)
from newsroom.integrated import CandidateAdmissionOutcome, IntegratedTriageProposalId
from newsroom.projection import ProjectionGenerationId
from newsroom.retrieval import (
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalContextV2Id,
    RetrievalRequestId,
)

from .increment_2d_helpers import (
    MemoryHybridRetrievalAdapter,
    open_candidate_test_system,
    proof,
    seed_active_retrieval_authority,
)


def _prepared(database: Path) -> Increment2PreparedAuthority:
    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT g.generation_id,MAX(c.contiguous_ledger_seq) "
            "FROM projection_generations g "
            "JOIN projection_checkpoint_versions c "
            "ON c.generation_id=g.generation_id "
            "WHERE g.state='ACTIVE' GROUP BY g.generation_id"
        ).fetchone()
    if row is None:
        raise AssertionError("fixture lacks one ACTIVE complete generation")
    return Increment2PreparedAuthority(
        fixture_id=INTEGRATED_FIXTURE_V2_RETRIEVAL.fixture_id,
        generation_id=ProjectionGenerationId.parse(str(row[0])),
        checkpoint_ledger_seq=int(row[1]),
        relation_key=INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE.relation_key,
    )


def _keys(prefix: str) -> Increment2ProofKeys:
    return Increment2ProofKeys(
        request_id=RetrievalRequestId.new(),
        context_id=RetrievalContextV2Id.new(),
        proposal_id=IntegratedTriageProposalId.new(),
        retrieval_idempotency_key=f"{prefix}-retrieval",
        candidate_idempotency_key=f"{prefix}-candidate",
    )


def _environment(
    database: Path,
    object_root: Path,
    *,
    prepared: Increment2PreparedAuthority | None = None,
) -> Increment2ProofEnvironment:
    selected = _prepared(database) if prepared is None else prepared
    return Increment2ProofEnvironment(
        prepare=lambda _proof, _keys: selected,
        open_candidate_authority=lambda: open_candidate_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        ),
    )


def _candidate_counts(database: Path) -> tuple[int, int, int]:
    with sqlite3.connect(database) as conn:
        return tuple(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "development_candidates_v2",
                "development_candidate_versions_v2",
                "development_candidate_admission_decisions_v2",
            )
        )


def test_complete_controller_binds_retrieval_candidate_replay_and_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    controller = Increment2CompleteProofController(
        _environment(database, object_root)
    )
    keys = _keys("increment-2d-controller")

    result = controller.run(proof=proof(), keys=keys)

    assert result.candidate.outcome is CandidateAdmissionOutcome.ADMITTED
    assert result.context.context_id == keys.context_id
    assert result.context.request_id == keys.request_id
    assert result.retrieval_replay_confirmed is True
    assert result.candidate_replay_confirmed is True
    assert result.restart_confirmed is True
    assert _candidate_counts(database) == (1, 1, 1)

    replay = controller.run(proof=proof(), keys=keys)
    assert replay.context.context_digest == result.context.context_digest
    assert replay.candidate == result.candidate
    assert _candidate_counts(database) == (1, 1, 1)


def test_controller_rejects_context_from_unprepared_generation_before_candidate(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    actual = _prepared(database)
    mismatched = Increment2PreparedAuthority(
        fixture_id=actual.fixture_id,
        generation_id=ProjectionGenerationId.new(),
        checkpoint_ledger_seq=actual.checkpoint_ledger_seq,
        relation_key=actual.relation_key,
    )
    controller = Increment2CompleteProofController(
        _environment(database, object_root, prepared=mismatched)
    )

    with pytest.raises(
        Increment2ProofStateError,
        match="prepared projection authority",
    ):
        controller.run(
            proof=proof(),
            keys=_keys("increment-2d-wrong-generation"),
        )

    assert _candidate_counts(database) == (0, 0, 0)


def test_prepared_authority_rejects_fixture_alias_instead_of_canonical_id() -> None:
    with pytest.raises(
        Increment2ProofStateError,
        match="prepared fixture differs from integrated_fixture_v2",
    ):
        Increment2PreparedAuthority(
            fixture_id="integrated_fixture_v2",
            generation_id=ProjectionGenerationId.new(),
            checkpoint_ledger_seq=1,
            relation_key=INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE.relation_key,
        )


def test_proof_environment_rejects_non_callable_authority_composition() -> None:
    with pytest.raises(TypeError, match="preparation"):
        Increment2ProofEnvironment(  # type: ignore[arg-type]
            prepare=None,
            open_candidate_authority=lambda: None,
        )
    with pytest.raises(TypeError, match="opener"):
        Increment2ProofEnvironment(  # type: ignore[arg-type]
            prepare=lambda _proof, _keys: None,
            open_candidate_authority=None,
        )
