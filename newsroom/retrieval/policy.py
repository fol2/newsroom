from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import TrustScope, UtcTimestamp, require_token
from newsroom.relations.models import RelationPredicate, RelationRecordType

from .models import RetrievalBranch, RetrievalContractError


@dataclass(frozen=True, slots=True)
class HybridRetrievalPolicy:
    policy_id: str
    policy_version: str
    tool_name: str
    tool_version: str
    purpose: str
    fusion_version: str
    graph_depth: int
    relation_fanout: int
    branch_result_limit: int
    retained_candidate_limit: int
    date_window_seconds: int
    max_projection_age_seconds: int
    timeout_ms: int
    response_byte_limit: int
    reciprocal_rank_k: int
    allowed_endpoint_types: frozenset[RelationRecordType]
    allowed_predicates: frozenset[RelationPredicate]
    allowed_trust_scopes: frozenset[TrustScope]

    def __post_init__(self) -> None:
        for field_name in (
            "policy_id",
            "policy_version",
            "tool_name",
            "tool_version",
            "purpose",
            "fusion_version",
        ):
            require_token(getattr(self, field_name), field=field_name)
        if self.tool_name != "find_related_event_candidates":
            raise RetrievalContractError("retrieval policy exposes an unknown tool")
        fixed = {
            "graph_depth": 2,
            "relation_fanout": 32,
            "branch_result_limit": 8,
            "retained_candidate_limit": 12,
            "date_window_seconds": 31 * 24 * 60 * 60,
            "max_projection_age_seconds": 60 * 60,
            "timeout_ms": 5_000,
            "response_byte_limit": 262_144,
            "reciprocal_rank_k": 60,
        }
        for field_name, expected in fixed.items():
            if getattr(self, field_name) != expected:
                raise RetrievalContractError(
                    f"{field_name} differs from the accepted fixture bound"
                )
        if self.allowed_endpoint_types != frozenset(
            {RelationRecordType.EVENT_HYPOTHESIS_VERSION}
        ):
            raise RetrievalContractError("retrieval endpoint allow-list is not exact")
        if self.allowed_predicates != frozenset({RelationPredicate.DEVELOPMENT_OF}):
            raise RetrievalContractError("retrieval predicate allow-list is not exact")
        if self.allowed_trust_scopes != frozenset(
            {TrustScope.OBSERVED, TrustScope.ADMITTED}
        ):
            raise RetrievalContractError("retrieval trust allow-list is not exact")

    @property
    def required_branches(self) -> tuple[RetrievalBranch, ...]:
        return tuple(RetrievalBranch)

    def date_window_start(self, query_valid_time: UtcTimestamp) -> UtcTimestamp:
        if not isinstance(query_valid_time, UtcTimestamp):
            raise RetrievalContractError("query-valid time must be typed")
        return UtcTimestamp(
            query_valid_time.value
            - timedelta(seconds=self.date_window_seconds)
        )

    def projection_freshness_deadline(
        self,
        validation_recorded_at: UtcTimestamp,
    ) -> UtcTimestamp:
        if not isinstance(validation_recorded_at, UtcTimestamp):
            raise RetrievalContractError(
                "projection validation time must be typed"
            )
        return UtcTimestamp(
            validation_recorded_at.value
            + timedelta(seconds=self.max_projection_age_seconds)
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "purpose": self.purpose,
            "fusion_version": self.fusion_version,
            "graph_depth": self.graph_depth,
            "relation_fanout": self.relation_fanout,
            "branch_result_limit": self.branch_result_limit,
            "retained_candidate_limit": self.retained_candidate_limit,
            "date_window_seconds": self.date_window_seconds,
            "max_projection_age_seconds": self.max_projection_age_seconds,
            "timeout_ms": self.timeout_ms,
            "response_byte_limit": self.response_byte_limit,
            "reciprocal_rank_k": self.reciprocal_rank_k,
            "allowed_endpoint_types": sorted(
                item.value for item in self.allowed_endpoint_types
            ),
            "allowed_predicates": sorted(item.value for item in self.allowed_predicates),
            "allowed_trust_scopes": sorted(
                item.value for item in self.allowed_trust_scopes
            ),
            "required_branches": [item.value for item in self.required_branches],
            "generation_selection": "AUTHORITY_SELECTED_ACTIVE_COMPLETE",
            "required_gap_count": 0,
            "required_dead_letter_count": 0,
            "hydration_authority": "sqlite-ledger-and-governed-objects",
            "fusion_is_authority": False,
        }

    @property
    def contract_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


HYBRID_FIXTURE_POLICY_V1 = HybridRetrievalPolicy(
    policy_id="hybrid_fixture_retrieval_v1",
    policy_version="hybrid-fixture-retrieval-policy-v1",
    tool_name="find_related_event_candidates",
    tool_version="find-related-event-candidates-v1",
    purpose="development-context-retrieval",
    fusion_version="hybrid_fixture_fusion_v1",
    graph_depth=2,
    relation_fanout=32,
    branch_result_limit=8,
    retained_candidate_limit=12,
    date_window_seconds=31 * 24 * 60 * 60,
    max_projection_age_seconds=60 * 60,
    timeout_ms=5_000,
    response_byte_limit=262_144,
    reciprocal_rank_k=60,
    allowed_endpoint_types=frozenset(
        {RelationRecordType.EVENT_HYPOTHESIS_VERSION}
    ),
    allowed_predicates=frozenset({RelationPredicate.DEVELOPMENT_OF}),
    allowed_trust_scopes=frozenset({TrustScope.OBSERVED, TrustScope.ADMITTED}),
)
