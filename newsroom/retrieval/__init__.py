"""Bounded, non-authoritative retrieval contracts for Increment 2C."""

from .fixture_v2 import (
    FixtureDependencyRoot,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    IntegratedFixtureV2RetrievalContract,
    validate_fixture_branch_executions,
)
from .fusion import fuse_fixture_candidates
from .models import (
    FindRelatedEventCandidatesRequest,
    FindRelatedEventCandidatesResult,
    FusedRetrievalCandidate,
    HydratedRetrievalPassage,
    ReciprocalRankScore,
    RetrievalBranch,
    RetrievalBranchExecution,
    RetrievalBranchHit,
    RetrievalContextV2,
    RetrievalContextV2Id,
    RetrievalContractError,
    RetrievalExclusion,
    RetrievalExclusionReason,
    RetrievalFailure,
    RetrievalOutcome,
    RetrievalProjectionMetadata,
    RetrievalRequestId,
    RetrievalStateError,
    canonical_score,
)
from .policy import HYBRID_FIXTURE_POLICY_V1, HybridRetrievalPolicy


def __getattr__(name: str):
    if name in {
        "HybridRetrievalAuthoritySystem",
        "RelatedEventCandidateRetrieval",
        "open_hybrid_retrieval_authority_system",
    }:
        from newsroom.authority import retrieval_system as _system

        return getattr(_system, name)
    raise AttributeError(name)


__all__ = [
    "FindRelatedEventCandidatesRequest",
    "FindRelatedEventCandidatesResult",
    "FixtureDependencyRoot",
    "FusedRetrievalCandidate",
    "HYBRID_FIXTURE_POLICY_V1",
    "HybridRetrievalAuthoritySystem",
    "HydratedRetrievalPassage",
    "INTEGRATED_FIXTURE_V2_RETRIEVAL",
    "IntegratedFixtureV2RetrievalContract",
    "HybridRetrievalPolicy",
    "ReciprocalRankScore",
    "RelatedEventCandidateRetrieval",
    "RetrievalBranch",
    "RetrievalBranchExecution",
    "RetrievalBranchHit",
    "RetrievalContextV2",
    "RetrievalContextV2Id",
    "RetrievalContractError",
    "RetrievalExclusion",
    "RetrievalExclusionReason",
    "RetrievalFailure",
    "RetrievalOutcome",
    "RetrievalProjectionMetadata",
    "RetrievalRequestId",
    "RetrievalStateError",
    "canonical_score",
    "fuse_fixture_candidates",
    "open_hybrid_retrieval_authority_system",
    "validate_fixture_branch_executions",
]
