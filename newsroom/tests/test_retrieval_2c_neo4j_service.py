from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from newsroom.authority import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
)
from newsroom.authority._retrieval_system import (
    open_hybrid_retrieval_authority_system,
)
from newsroom.projection import (
    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
)
from newsroom.projection.neo4j import Neo4jProjectorConfig
from newsroom.retrieval import (
    FindRelatedEventCandidatesRequest,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalBranch,
    RetrievalContextV2Id,
    RetrievalExclusionReason,
    RetrievalOutcome,
    RetrievalRequestId,
)

from .authority_a2b_helpers import _policy_registries
from .authority_event_helpers import payload_schemas
from .complete_projection_2b_helpers import (
    COMPLETE_NOW,
    complete_contract_registry,
    complete_scopes,
    proof,
)
from .projection_b1_helpers import source_command_registry
from .retrieval_2c_helpers import object_limits
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


_REQUIRED_FLAG = "NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED"


def _service_config() -> Neo4jProjectorConfig:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("actual hybrid retrieval Neo4j service is required only by the 2C gate")
    return Neo4jProjectorConfig.from_environment()


def _request(*, key: str = "actual-retrieval-2c-request") -> FindRelatedEventCandidatesRequest:
    fixture = INTEGRATED_FIXTURE_V2_RETRIEVAL
    return FindRelatedEventCandidatesRequest(
        request_id=RetrievalRequestId.new(),
        context_id=RetrievalContextV2Id.new(),
        fixture_id=fixture.fixture_id,
        query_revision_id=fixture.query_revision_id,
        query_hypothesis_version_id=fixture.query_hypothesis_version_id,
        query_valid_time=fixture.query_valid_time,
        idempotency_key=f"{key}-{uuid4().hex}",
    )


def _open_retrieval(database: Path, object_root: Path):
    rights, hydration, admissions = _policy_registries()
    scopes = frozenset({*complete_scopes(), "authority.retrieval.read"})
    return open_hybrid_retrieval_authority_system(
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
            policy_version="retrieval-2c-actual-service-authz-v1",
            grants_by_principal={"principal.alpha": scopes},
        ),
        neo4j_config=_service_config(),
        clock=lambda: COMPLETE_NOW,
    )


def _activate(tmp_path: Path):
    database, object_root, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    rebuilt = _rebuild(
        system,
        generation,
        database,
        key=f"actual-retrieval-2c-rebuild-{uuid4().hex}",
    )
    validation = _validate(
        system,
        generation.generation_id,
        rebuilt.checkpoint_ledger_seq,
        key=f"actual-retrieval-2c-validate-{uuid4().hex}",
    )
    _qualify(system, generation.generation_id, rebuilt.checkpoint_ledger_seq)
    current = _current(system, generation.generation_id)
    promoted = system.projections.promote_generation(
        ProjectionGenerationPromotionRequest(
            generation_id=generation.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
            validation_digest=validation.validation_digest,
            reason_code="INCREMENT_2C_ACTUAL_SERVICE_PROMOTE",
            idempotency_key=f"actual-retrieval-2c-promote-{uuid4().hex}",
        ),
        proof=proof(),
    )
    assert promoted.generation.state is ProjectionGenerationState.ACTIVE
    system.close()
    return database, object_root, generation


def test_actual_service_executes_all_four_branches_and_hydrates_authority(
    tmp_path: Path,
) -> None:
    database, object_root, generation = _activate(tmp_path)
    request = _request()
    system = _open_retrieval(database, object_root)
    try:
        result = system.retrieval.find_related_event_candidates(
            request,
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
        )
        assert result.outcome is RetrievalOutcome.COMPLETE
        assert result.context is not None
        context = result.context
        assert tuple(item.branch for item in context.branches) == tuple(RetrievalBranch)
        assert all(item.hits for item in context.branches)
        assert context.retained_candidates[0].candidate_version_id == (
            INTEGRATED_FIXTURE_V2_RETRIEVAL.prior_candidate_version_id
        )
        graph = next(
            item
            for item in context.branches
            if item.branch is RetrievalBranch.ADMITTED_GRAPH
        )
        assert len(graph.hits) == 1
        assert graph.hits[0].trust_scope.value == "ADMITTED"
        assert graph.hits[0].source_kind == "RELATION_ASSERTION"
        assert tuple(item.passage_id for item in context.hydrated_passages) == (
            "ifv2-prior-en",
            "ifv2-prior-zh-hk",
        )
        assert all(item.rights_state == "PERMITTED" for item in context.hydrated_passages)
        assert {
            item.reason for item in context.exclusions
        } >= {
            RetrievalExclusionReason.SELF_QUERY,
            RetrievalExclusionReason.INCOMPATIBLE_FORMAL_ID,
            RetrievalExclusionReason.INCOMPATIBLE_JURISDICTION,
        }
    finally:
        system.close()

    reopened = _open_retrieval(database, object_root)
    try:
        replay = reopened.retrieval.find_related_event_candidates(
            request,
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
        )
        assert replay.replayed is True
        assert replay.context is not None
        assert replay.context.context_digest == context.context_digest
    finally:
        reopened.close()
        _cleanup_generation(generation.generation_id)


def test_actual_service_missing_fulltext_index_is_unavailable_not_no_match(
    tmp_path: Path,
) -> None:
    database, object_root, generation = _activate(tmp_path)
    names = _names(generation.generation_id)
    _projector_write(f"DROP INDEX `{names.fulltext_index_name}`")
    system = _open_retrieval(database, object_root)
    try:
        result = system.retrieval.find_related_event_candidates(
            _request(key="actual-retrieval-2c-missing-fulltext"),
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
        )
        assert result.outcome is RetrievalOutcome.UNAVAILABLE
        assert result.failure is not None
        assert result.failure.reason_code == "NEO4J_RETRIEVAL_UNAVAILABLE"
        assert result.context is None
    finally:
        system.close()
        _cleanup_generation(generation.generation_id)


def test_actual_service_missing_admitted_relation_is_incomplete_not_no_match(
    tmp_path: Path,
) -> None:
    database, object_root, generation = _activate(tmp_path)
    _projector_write(
        "MATCH ()-[relation:DEVELOPMENT_OF {generation_id:$generation_id}]->() "
        "DELETE relation",
        generation_id=str(generation.generation_id),
    )
    system = _open_retrieval(database, object_root)
    try:
        result = system.retrieval.find_related_event_candidates(
            _request(key="actual-retrieval-2c-missing-relation"),
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
        )
        assert result.outcome is RetrievalOutcome.INCOMPLETE
        assert result.failure is not None
        assert result.failure.reason_code == "RETRIEVAL_CONTRACT_MISMATCH"
        assert result.context is None
    finally:
        system.close()
        _cleanup_generation(generation.generation_id)
