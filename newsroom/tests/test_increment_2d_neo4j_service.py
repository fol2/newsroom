from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from newsroom.authority import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
)
from newsroom.authority.development_candidate_system import (
    open_complete_fixture_candidate_authority_system,
)
from newsroom.increment2 import (
    INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
    Increment2CompleteProofController,
    Increment2PreparedAuthority,
    Increment2ProofEnvironment,
    Increment2ProofKeys,
    Increment2ProofStateError,
)
from newsroom.integrated import CandidateAdmissionOutcome, IntegratedTriageProposalId
from newsroom.projection import ProjectionGenerationPromotionRequest, ProjectionGenerationState
from newsroom.projection.neo4j import Neo4jProjectorConfig
from newsroom.retrieval import RetrievalContextV2Id, RetrievalRequestId

from .authority_a2b_helpers import _policy_registries
from .authority_event_helpers import payload_schemas
from .complete_projection_2b_helpers import (
    COMPLETE_NOW,
    complete_contract_registry,
    proof,
)
from .increment_2d_helpers import object_limits, scopes
from .projection_b1_helpers import source_command_registry
from .test_complete_projection_2b_neo4j_service import (
    _cleanup_generation,
    _current,
    _names,
    _projector_write,
    _qualify,
    _rebuild,
    _setup,
    _validate,
)


_REQUIRED_FLAG = "NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED"


def _service_config() -> Neo4jProjectorConfig:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("complete Increment 2D actual Neo4j service is required")
    return Neo4jProjectorConfig.from_environment()


def _open_candidate(database: Path, object_root: Path):
    rights, hydration, admissions = _policy_registries()
    return open_complete_fixture_candidate_authority_system(
        path=database,
        object_root=object_root,
        object_limits=object_limits(),
        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=complete_contract_registry(),
        admission_registry=admissions,
        rights_policies=rights,
        hydration_policies=hydration,
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="increment-2d-actual-service-authz-v1",
            grants_by_principal={"principal.alpha": scopes()},
        ),
        neo4j_config=_service_config(),
        clock=lambda: COMPLETE_NOW,
    )


def _keys(prefix: str) -> Increment2ProofKeys:
    return Increment2ProofKeys(
        request_id=RetrievalRequestId.new(),
        context_id=RetrievalContextV2Id.new(),
        proposal_id=IntegratedTriageProposalId.new(),
        retrieval_idempotency_key=f"{prefix}-retrieval-{uuid4().hex}",
        candidate_idempotency_key=f"{prefix}-candidate-{uuid4().hex}",
    )


def _controller_fixture(tmp_path: Path):
    (
        database,
        object_root,
        _seeded,
        _proposal,
        _decision,
        complete_system,
        generation,
    ) = _setup(tmp_path)
    prepared: dict[str, Increment2PreparedAuthority] = {}

    def prepare(
        authentication: AuthenticationProof,
        _keys: Increment2ProofKeys,
    ) -> Increment2PreparedAuthority:
        if not isinstance(authentication, AuthenticationProof):
            raise TypeError("actual proof preparation authentication must be typed")
        current = prepared.get("authority")
        if current is not None:
            return current
        rebuilt = _rebuild(
            complete_system,
            generation,
            database,
            key=f"increment-2d-service-rebuild-{uuid4().hex}",
        )
        validation = _validate(
            complete_system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key=f"increment-2d-service-validate-{uuid4().hex}",
        )
        _qualify(
            complete_system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
        )
        validating = _current(complete_system, generation.generation_id)
        promoted = complete_system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    validating.authority_aggregate_version
                ),
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                validation_digest=validation.validation_digest,
                reason_code="INCREMENT_2D_COMPLETE_PROOF_PROMOTE",
                idempotency_key=(
                    f"increment-2d-service-promote-{uuid4().hex}"
                ),
            ),
            proof=proof(),
        )
        assert promoted.generation.state is ProjectionGenerationState.ACTIVE
        complete_system.close()
        current = Increment2PreparedAuthority(
            fixture_id="integrated_fixture_v2",
            generation_id=generation.generation_id,
            checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
            relation_key=(
                INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE.relation_key
            ),
        )
        prepared["authority"] = current
        return current

    controller = Increment2CompleteProofController(
        Increment2ProofEnvironment(
            prepare=prepare,
            open_candidate_authority=lambda: _open_candidate(
                database,
                object_root,
            ),
        )
    )
    return (
        database,
        object_root,
        complete_system,
        generation,
        prepared,
        prepare,
        controller,
    )


def _authentication() -> AuthenticationProof:
    return AuthenticationProof(method="STATIC_TOKEN", credential="token-1")


def _candidate_count(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM development_candidates_v2"
            ).fetchone()[0]
        )


def test_actual_service_complete_increment_2_proof_admits_replays_and_restarts(
    tmp_path: Path,
) -> None:
    (
        _database,
        _object_root,
        complete_system,
        generation,
        prepared,
        _prepare,
        controller,
    ) = _controller_fixture(tmp_path)
    keys = _keys("increment-2d-actual")

    try:
        result = controller.run(proof=_authentication(), keys=keys)
        assert result.candidate.outcome is CandidateAdmissionOutcome.ADMITTED
        assert result.retrieval_replay_confirmed is True
        assert result.candidate_replay_confirmed is True
        assert result.restart_confirmed is True

        replay = controller.run(proof=_authentication(), keys=keys)
        assert replay.context.context_digest == result.context.context_digest
        assert replay.candidate == result.candidate
    finally:
        if "authority" not in prepared:
            complete_system.close()
        _cleanup_generation(generation.generation_id)


@pytest.mark.parametrize("surface", ("relation", "fulltext", "vector"))
def test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost(
    tmp_path: Path,
    surface: str,
) -> None:
    (
        database,
        _object_root,
        complete_system,
        generation,
        prepared,
        prepare,
        controller,
    ) = _controller_fixture(tmp_path)
    keys = _keys(f"increment-2d-loss-{surface}")

    try:
        prepare(_authentication(), keys)
        names = _names(generation.generation_id)
        if surface == "relation":
            _projector_write(
                "MATCH ()-[relation:DEVELOPMENT_OF "
                "{generation_id:$generation_id}]->() DELETE relation",
                generation_id=str(generation.generation_id),
            )
        elif surface == "fulltext":
            _projector_write(f"DROP INDEX `{names.fulltext_index_name}`")
        else:
            _projector_write(f"DROP INDEX `{names.vector_index_name}`")

        with pytest.raises(
            Increment2ProofStateError,
            match="complete retrieval proof failed",
        ):
            controller.run(proof=_authentication(), keys=keys)
        assert _candidate_count(database) == 0
    finally:
        if "authority" not in prepared:
            complete_system.close()
        _cleanup_generation(generation.generation_id)
