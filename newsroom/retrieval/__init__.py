"""Bounded, non-authoritative retrieval contracts for Increment 2C."""

from .fixture_v2 import (
    FixtureDependencyRoot,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    IntegratedFixtureV2RetrievalContract,
)
from .fusion import fuse_fixture_candidates
from .models import (
    FindRelatedEventCandidatesRequest,
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
    RetrievalOutcome,
    RetrievalProjectionMetadata,
    RetrievalRequestId,
    RetrievalStateError,
    canonical_score,
)
from .policy import HYBRID_FIXTURE_POLICY_V1, HybridRetrievalPolicy

__all__ = [
    "FindRelatedEventCandidatesRequest",
    "FixtureDependencyRoot",
    "FusedRetrievalCandidate",
    "HYBRID_FIXTURE_POLICY_V1",
    "HydratedRetrievalPassage",
    "INTEGRATED_FIXTURE_V2_RETRIEVAL",
    "IntegratedFixtureV2RetrievalContract",
    "HybridRetrievalPolicy",
    "ReciprocalRankScore",
    "RetrievalBranch",
    "RetrievalBranchExecution",
    "RetrievalBranchHit",
    "RetrievalContextV2",
    "RetrievalContextV2Id",
    "RetrievalContractError",
    "RetrievalExclusion",
    "RetrievalExclusionReason",
    "RetrievalOutcome",
    "RetrievalProjectionMetadata",
    "RetrievalRequestId",
    "RetrievalStateError",
    "canonical_score",
    "fuse_fixture_candidates",
]
