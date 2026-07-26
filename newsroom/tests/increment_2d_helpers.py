from __future__ import annotations

from pathlib import Path
from typing import Callable

from newsroom.authority import (
    ObjectAdmissionId,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
)
from newsroom.authority._development_candidate_system import (
    _open_complete_fixture_candidate_with_adapter,
)
from newsroom.increment2 import DevelopmentCandidateAdmissionRequest
from newsroom.increment2.policy import (
    merge_development_candidate_authority_registries,
)
from newsroom.integrated import IntegratedTriageProposalId
from newsroom.projection.policy import merge_projection_authority_registries
from newsroom.relations import (
    RelationAdmissionDecisionId,
    RelationProposalId,
)
from newsroom.relations.policy import merge_relation_authority_registries
from newsroom.retrieval import (
    FindRelatedEventCandidatesRequest,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalContextV2Id,
    RetrievalRequestId,
)

from .authority_a2b_helpers import _policy_registries, open_object_system
from .authority_event_helpers import payload_schemas
from .complete_projection_2b_helpers import (
    COMPLETE_NOW,
    complete_contract_registry,
    complete_scopes,
    proof,
)
from .projection_b1_helpers import source_command_registry
from .relation_2a_helpers import (
    authenticator as relation_authenticator,
    authorizer as relation_authorizer,
    event_read_policy as relation_event_read_policy,
    relation_read_policy,
)
from newsroom.authority._relation_system import (
    open_governed_relation_authority_system,
)
from newsroom.authority.object_policy import merge_authority_registries
from .retrieval_2c_helpers import (
    MemoryHybridRetrievalAdapter,
    object_limits,
    seed_active_retrieval_authority,
)


def scopes() -> frozenset[str]:
    return frozenset(
        {
            *complete_scopes(),
            "authority.retrieval.read",
            "authority.candidate.admit",
            "authority.candidate.read",
        }
    )


def candidate_registries():
    object_commands, object_schemas = merge_authority_registries(
        command_registry=source_command_registry(),
        payload_schemas=payload_schemas(),
    )
    relation_commands, relation_schemas = merge_relation_authority_registries(
        command_registry=object_commands,
        payload_schemas=object_schemas,
    )
    projection_commands, projection_schemas = (
        merge_projection_authority_registries(
            command_registry=relation_commands,
            payload_schemas=relation_schemas,
        )
    )
    return merge_development_candidate_authority_registries(
        command_registry=projection_commands,
        payload_schemas=projection_schemas,
    )


def open_candidate_relation_system(database: Path):
    commands, schemas = candidate_registries()
    return open_governed_relation_authority_system(
        path=database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=relation_authenticator(),
        authorizer=relation_authorizer(),
        event_read_policy=relation_event_read_policy(),
        relation_read_policy=relation_read_policy(),
        clock=lambda: COMPLETE_NOW,
    )


def open_candidate_object_system(database: Path, *, object_root: Path):
    commands, schemas = candidate_registries()
    return open_object_system(
        database,
        object_root=object_root,
        scopes=scopes(),
        command_registry=commands,
        payload_schema_registry=schemas,
        clock=lambda: COMPLETE_NOW,
    )


def retained_relation_identities(
    database: Path,
) -> tuple[RelationProposalId, RelationAdmissionDecisionId]:
    import sqlite3

    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT proposal_id,decision_id FROM relation_decision_heads "
            "WHERE current_state='ADMITTED'"
        ).fetchone()
    if row is None:
        raise AssertionError("fixture relation is not admitted")
    return (
        RelationProposalId.parse(str(row[0])),
        RelationAdmissionDecisionId.parse(str(row[1])),
    )


def fixture_passage_admission_id(
    database: Path,
    *,
    passage_id: str,
) -> ObjectAdmissionId:
    import sqlite3

    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT admission_id FROM integrated_fixture_v2_passage_objects "
            "WHERE passage_id=?",
            (passage_id,),
        ).fetchone()
    if row is None:
        raise AssertionError(f"fixture passage {passage_id!r} is not bound")
    return ObjectAdmissionId.parse(str(row[0]))


def open_candidate_test_system(
    database: Path,
    *,
    object_root: Path,
    adapter: object,
    granted_scopes: frozenset[str] | None = None,
    clock: Callable = lambda: COMPLETE_NOW,
):
    rights, hydration, admissions = _policy_registries()
    selected = scopes() if granted_scopes is None else granted_scopes
    return _open_complete_fixture_candidate_with_adapter(
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
            policy_version="increment-2d-candidate-authz-v1",
            grants_by_principal={"principal.alpha": selected},
        ),
        adapter=adapter,
        clock=clock,
    )


def retrieval_request(*, key: str) -> FindRelatedEventCandidatesRequest:
    fixture = INTEGRATED_FIXTURE_V2_RETRIEVAL
    return FindRelatedEventCandidatesRequest(
        request_id=RetrievalRequestId.new(),
        context_id=RetrievalContextV2Id.new(),
        fixture_id=fixture.fixture_id,
        query_revision_id=fixture.query_revision_id,
        query_hypothesis_version_id=fixture.query_hypothesis_version_id,
        query_valid_time=fixture.query_valid_time,
        idempotency_key=key,
    )


def candidate_request(context, *, key: str) -> DevelopmentCandidateAdmissionRequest:
    return DevelopmentCandidateAdmissionRequest(
        proposal_id=IntegratedTriageProposalId.new(),
        retrieval_context_id=context.context_id,
        expected_context_digest=context.context_digest,
        idempotency_key=key,
    )


__all__ = [
    "MemoryHybridRetrievalAdapter",
    "candidate_request",
    "open_candidate_test_system",
    "proof",
    "retrieval_request",
    "scopes",
    "seed_active_retrieval_authority",
]
