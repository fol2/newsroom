from __future__ import annotations

from pathlib import Path
from typing import Callable

from newsroom.authority import (
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
)
from newsroom.authority._development_candidate_system import (
    _open_complete_fixture_candidate_with_adapter,
)
from newsroom.increment2 import DevelopmentCandidateAdmissionRequest
from newsroom.integrated import IntegratedTriageProposalId
from newsroom.retrieval import (
    FindRelatedEventCandidatesRequest,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalContextV2Id,
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
