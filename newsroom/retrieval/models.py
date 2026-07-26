from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
import math
import re
from typing import Iterable

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.types import (
    ObjectAdmissionId,
    TrustScope,
    UUIDv4Id,
    UtcTimestamp,
    require_token,
)
from newsroom.projection.models import ProjectionGenerationId, ProjectionGenerationState
from newsroom.projection.neo4j.complete_models import CompleteProjectionIdentity


_SCORE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,17})?(?:e-?[0-9]{1,3})?$")


class RetrievalContractError(ValueError):
    """A bounded retrieval contract or retained record is malformed."""


class RetrievalStateError(RuntimeError):
    """Current authority cannot support a complete retrieval result."""


class RetrievalBranch(StrEnum):
    EXACT = "EXACT"
    ADMITTED_GRAPH = "ADMITTED_GRAPH"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"


class RetrievalOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class RetrievalExclusionReason(StrEnum):
    SELF_QUERY = "SELF_QUERY"
    INCOMPATIBLE_FORMAL_ID = "INCOMPATIBLE_FORMAL_ID"
    INCOMPATIBLE_JURISDICTION = "INCOMPATIBLE_JURISDICTION"
    OUTSIDE_TEMPORAL_SCOPE = "OUTSIDE_TEMPORAL_SCOPE"
    UNADMITTED_RELATION = "UNADMITTED_RELATION"
    RIGHTS_NOT_CURRENT = "RIGHTS_NOT_CURRENT"
    TOMBSTONED = "TOMBSTONED"
    DEPENDENCY_DUPLICATE = "DEPENDENCY_DUPLICATE"
    RESULT_BOUND = "RESULT_BOUND"
    HYDRATION_FAILED = "HYDRATION_FAILED"


class RetrievalContextV2Id(UUIDv4Id):
    pass


class RetrievalRequestId(UUIDv4Id):
    pass


def _bounded_text(value: str, *, field: str, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise RetrievalContractError(f"{field} must be bounded canonical text")
    return value


def _sorted_unique_text(
    value: tuple[str, ...],
    *,
    field: str,
    allow_empty: bool = False,
    maximum_items: int = 64,
    maximum_item_bytes: int = 1024,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise RetrievalContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not value:
        raise RetrievalContractError(f"{field} cannot be empty")
    if len(value) > maximum_items:
        raise RetrievalContractError(f"{field} exceeds its item bound")
    normalized = tuple(
        _bounded_text(item, field=field, maximum_bytes=maximum_item_bytes)
        for item in value
    )
    if normalized != tuple(sorted(set(normalized))):
        raise RetrievalContractError(f"{field} must be sorted and unique")
    return normalized


def canonical_score(value: float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RetrievalContractError("retrieval score must be numeric")
    score = float(value)
    if not math.isfinite(score):
        raise RetrievalContractError("retrieval score must be finite")
    text = format(score, ".17g").lower().replace("e+", "e")
    if _SCORE.fullmatch(text) is None:
        raise RetrievalContractError("retrieval score is not canonical")
    return text


def _validate_score(value: str) -> str:
    if not isinstance(value, str) or _SCORE.fullmatch(value) is None:
        raise RetrievalContractError("retrieval score text is not canonical")
    score = float(value)
    if not math.isfinite(score) or canonical_score(score) != value:
        raise RetrievalContractError("retrieval score text is not canonical")
    return value


@dataclass(frozen=True, slots=True)
class FindRelatedEventCandidatesRequest:
    request_id: RetrievalRequestId
    context_id: RetrievalContextV2Id
    fixture_id: str
    query_revision_id: str
    query_hypothesis_version_id: str
    query_valid_time: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, RetrievalRequestId):
            raise RetrievalContractError("retrieval request identity must be typed")
        if not isinstance(self.context_id, RetrievalContextV2Id):
            raise RetrievalContractError("retrieval context identity must be typed")
        for field_name in (
            "fixture_id",
            "query_revision_id",
            "query_hypothesis_version_id",
        ):
            _bounded_text(getattr(self, field_name), field=field_name, maximum_bytes=128)
        if not isinstance(self.query_valid_time, UtcTimestamp):
            raise RetrievalContractError("query-valid time must be typed")
        _bounded_text(self.idempotency_key, field="idempotency_key", maximum_bytes=256)

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom-find-related-event-candidates-request-v1",
            "request_id": str(self.request_id),
            "context_id": str(self.context_id),
            "fixture_id": self.fixture_id,
            "query_revision_id": self.query_revision_id,
            "query_hypothesis_version_id": self.query_hypothesis_version_id,
            "query_valid_time": self.query_valid_time.to_text(),
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class RetrievalProjectionMetadata:
    identity: CompleteProjectionIdentity
    generation_state: ProjectionGenerationState
    contiguous_ledger_seq: int
    open_gap_count: int
    dead_letter_count: int
    query_valid_time: UtcTimestamp
    serving_time: UtcTimestamp
    authoritative_system: str = "sqlite-ledger-and-governed-objects"
    projection_role: str = "non-authoritative-rebuildable-context"

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise RetrievalContractError("complete projection identity must be typed")
        if self.generation_state is not ProjectionGenerationState.ACTIVE:
            raise RetrievalStateError("hybrid retrieval requires an ACTIVE generation")
        for field_name in (
            "contiguous_ledger_seq",
            "open_gap_count",
            "dead_letter_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RetrievalContractError(f"{field_name} must be non-negative")
        if self.contiguous_ledger_seq <= 0:
            raise RetrievalStateError("hybrid retrieval requires a positive watermark")
        if self.open_gap_count or self.dead_letter_count:
            raise RetrievalStateError("hybrid retrieval cannot conceal gaps or dead letters")
        if not isinstance(self.query_valid_time, UtcTimestamp) or not isinstance(
            self.serving_time, UtcTimestamp
        ):
            raise RetrievalContractError("retrieval times must be typed")
        if self.query_valid_time.value > self.serving_time.value:
            raise RetrievalStateError("query-valid time exceeds serving time")
        if self.authoritative_system != "sqlite-ledger-and-governed-objects":
            raise RetrievalStateError("retrieval must return to SQLite/object authority")
        if self.projection_role != "non-authoritative-rebuildable-context":
            raise RetrievalStateError("retrieval projection role is not non-authoritative")

    def canonical_value(self) -> dict[str, object]:
        return {
            "identity": self.identity.canonical_value(),
            "generation_state": self.generation_state.value,
            "contiguous_ledger_seq": self.contiguous_ledger_seq,
            "open_gap_count": self.open_gap_count,
            "dead_letter_count": self.dead_letter_count,
            "query_valid_time": self.query_valid_time.to_text(),
            "serving_time": self.serving_time.to_text(),
            "authoritative_system": self.authoritative_system,
            "projection_role": self.projection_role,
        }


@dataclass(frozen=True, slots=True)
class RetrievalBranchHit:
    branch: RetrievalBranch
    query_id: str
    query_digest: str
    rank: int
    raw_score: str
    result_key: str
    dependency_root_id: str
    passage_id: str | None
    trust_scope: TrustScope
    source_kind: str
    source_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.branch, RetrievalBranch):
            raise RetrievalContractError("retrieval branch must be typed")
        require_token(self.query_id, field="retrieval_query_id")
        validate_sha256_digest(self.query_digest, field="retrieval_query_digest")
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or not 1 <= self.rank <= 8:
            raise RetrievalContractError("branch rank exceeds the fixed bound")
        _validate_score(self.raw_score)
        for field_name in ("result_key", "dependency_root_id", "source_identity"):
            _bounded_text(getattr(self, field_name), field=field_name, maximum_bytes=256)
        if self.passage_id is not None:
            require_token(self.passage_id, field="retrieval_passage_id")
        if self.trust_scope not in {TrustScope.OBSERVED, TrustScope.ADMITTED}:
            raise RetrievalContractError("retrieval hit trust scope is not permitted")
        require_token(self.source_kind, field="retrieval_source_kind")

    @property
    def hit_digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def canonical_value(self) -> dict[str, object]:
        return {
            "branch": self.branch.value,
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "rank": self.rank,
            "raw_score": self.raw_score,
            "result_key": self.result_key,
            "dependency_root_id": self.dependency_root_id,
            "passage_id": self.passage_id,
            "trust_scope": self.trust_scope.value,
            "source_kind": self.source_kind,
            "source_identity": self.source_identity,
        }


@dataclass(frozen=True, slots=True)
class RetrievalBranchExecution:
    branch: RetrievalBranch
    query_id: str
    query_digest: str
    result_limit: int
    elapsed_ms: int
    hits: tuple[RetrievalBranchHit, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.branch, RetrievalBranch):
            raise RetrievalContractError("branch execution kind must be typed")
        require_token(self.query_id, field="branch_query_id")
        validate_sha256_digest(self.query_digest, field="branch_query_digest")
        if self.result_limit != 8:
            raise RetrievalContractError("branch execution limit must remain fixed at 8")
        if isinstance(self.elapsed_ms, bool) or not isinstance(self.elapsed_ms, int) or self.elapsed_ms < 0:
            raise RetrievalContractError("branch elapsed time must be non-negative")
        if not isinstance(self.hits, tuple) or len(self.hits) > self.result_limit:
            raise RetrievalContractError("branch hits exceed their fixed result bound")
        if any(
            not isinstance(hit, RetrievalBranchHit)
            or hit.branch is not self.branch
            or hit.query_id != self.query_id
            or hit.query_digest != self.query_digest
            for hit in self.hits
        ):
            raise RetrievalContractError("branch hit identity differs from execution")
        ranks = tuple(hit.rank for hit in self.hits)
        if ranks != tuple(range(1, len(self.hits) + 1)):
            raise RetrievalContractError("branch ranks must be contiguous")
        keys = tuple(hit.result_key for hit in self.hits)
        if len(keys) != len(set(keys)):
            raise RetrievalContractError("branch result keys must be unique")

    def canonical_value(self) -> dict[str, object]:
        return {
            "branch": self.branch.value,
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "result_limit": self.result_limit,
            "elapsed_ms": self.elapsed_ms,
            "hits": [item.canonical_value() for item in self.hits],
        }


@dataclass(frozen=True, slots=True)
class ReciprocalRankScore:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.numerator, bool)
            or not isinstance(self.numerator, int)
            or self.numerator <= 0
            or isinstance(self.denominator, bool)
            or not isinstance(self.denominator, int)
            or self.denominator <= 0
        ):
            raise RetrievalContractError("fusion score must be a positive fraction")
        reduced = Fraction(self.numerator, self.denominator)
        if (reduced.numerator, reduced.denominator) != (
            self.numerator,
            self.denominator,
        ):
            raise RetrievalContractError("fusion score must be reduced")

    @classmethod
    def from_fraction(cls, value: Fraction) -> "ReciprocalRankScore":
        if not isinstance(value, Fraction) or value <= 0:
            raise RetrievalContractError("fusion score fraction must be positive")
        return cls(value.numerator, value.denominator)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def canonical_value(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}


@dataclass(frozen=True, slots=True)
class FusedRetrievalCandidate:
    dependency_root_id: str
    candidate_version_id: str | None
    contributing_branches: tuple[RetrievalBranch, ...]
    branch_hits: tuple[RetrievalBranchHit, ...]
    dependency_ids: tuple[str, ...]
    score: ReciprocalRankScore
    final_rank: int

    def __post_init__(self) -> None:
        _bounded_text(self.dependency_root_id, field="dependency_root_id", maximum_bytes=256)
        if self.candidate_version_id is not None:
            _bounded_text(
                self.candidate_version_id,
                field="candidate_version_id",
                maximum_bytes=128,
            )
        if (
            not isinstance(self.contributing_branches, tuple)
            or not self.contributing_branches
            or self.contributing_branches
            != tuple(sorted(set(self.contributing_branches), key=lambda item: item.value))
        ):
            raise RetrievalContractError("candidate branches must be sorted and unique")
        if not isinstance(self.branch_hits, tuple) or not self.branch_hits:
            raise RetrievalContractError("fused candidate requires branch evidence")
        hit_keys = tuple((item.branch.value, item.rank, item.result_key) for item in self.branch_hits)
        if hit_keys != tuple(sorted(set(hit_keys))):
            raise RetrievalContractError("candidate branch evidence must be sorted and unique")
        if set(item.branch for item in self.branch_hits) != set(self.contributing_branches):
            raise RetrievalContractError("candidate branches differ from branch evidence")
        object.__setattr__(
            self,
            "dependency_ids",
            _sorted_unique_text(
                self.dependency_ids,
                field="dependency_ids",
                maximum_items=64,
                maximum_item_bytes=256,
            ),
        )
        if not isinstance(self.score, ReciprocalRankScore):
            raise RetrievalContractError("candidate fusion score must be typed")
        if isinstance(self.final_rank, bool) or not isinstance(self.final_rank, int) or not 1 <= self.final_rank <= 12:
            raise RetrievalContractError("candidate final rank exceeds retained bound")

    def canonical_value(self) -> dict[str, object]:
        return {
            "dependency_root_id": self.dependency_root_id,
            "candidate_version_id": self.candidate_version_id,
            "contributing_branches": [item.value for item in self.contributing_branches],
            "branch_hits": [item.canonical_value() for item in self.branch_hits],
            "dependency_ids": list(self.dependency_ids),
            "score": self.score.canonical_value(),
            "final_rank": self.final_rank,
        }


@dataclass(frozen=True, slots=True)
class RetrievalExclusion:
    dependency_root_id: str
    reason: RetrievalExclusionReason
    branch_hits: tuple[RetrievalBranchHit, ...]
    detail: str

    def __post_init__(self) -> None:
        _bounded_text(self.dependency_root_id, field="excluded_dependency_root_id", maximum_bytes=256)
        if not isinstance(self.reason, RetrievalExclusionReason):
            raise RetrievalContractError("retrieval exclusion reason must be typed")
        if not isinstance(self.branch_hits, tuple):
            raise RetrievalContractError("retrieval exclusion evidence must be immutable")
        _bounded_text(self.detail, field="retrieval_exclusion_detail", maximum_bytes=2048)

    def canonical_value(self) -> dict[str, object]:
        return {
            "dependency_root_id": self.dependency_root_id,
            "reason": self.reason.value,
            "branch_hits": [item.canonical_value() for item in self.branch_hits],
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class HydratedRetrievalPassage:
    passage_id: str
    admission_id: ObjectAdmissionId
    blob_digest: str
    language: str
    text: str
    text_digest: str
    hydration_policy_contract_digest: str
    access_decision_id: ObjectAccessDecisionId
    byte_start: int
    byte_end: int
    rights_state: str
    lifecycle_state: str
    trust_scope: TrustScope

    def __post_init__(self) -> None:
        require_token(self.passage_id, field="hydrated_passage_id")
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise RetrievalContractError("hydrated passage admission must be typed")
        for field_name in (
            "blob_digest",
            "text_digest",
            "hydration_policy_contract_digest",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if self.language not in {"en-GB", "zh-HK"}:
            raise RetrievalContractError("hydrated passage language is invalid")
        _bounded_text(self.text, field="hydrated_passage_text", maximum_bytes=256 * 1024)
        if digest_bytes(self.text.encode("utf-8")) != self.text_digest:
            raise RetrievalContractError("hydrated passage text digest differs")
        if not isinstance(self.access_decision_id, ObjectAccessDecisionId):
            raise RetrievalContractError("hydration access decision must be typed")
        for field_name in ("byte_start", "byte_end"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RetrievalContractError(f"{field_name} must be non-negative")
        if self.byte_start != 0 or self.byte_end != len(self.text.encode("utf-8")):
            raise RetrievalContractError(
                "fixture hydration must cover the exact governed object bytes"
            )
        require_token(self.rights_state, field="hydrated_rights_state")
        require_token(self.lifecycle_state, field="hydrated_lifecycle_state")
        if self.trust_scope is not TrustScope.OBSERVED:
            raise RetrievalContractError("hydrated factual bytes require OBSERVED trust")

    def canonical_value(self) -> dict[str, object]:
        return {
            "passage_id": self.passage_id,
            "admission_id": str(self.admission_id),
            "blob_digest": self.blob_digest,
            "language": self.language,
            "text": self.text,
            "text_digest": self.text_digest,
            "hydration_policy_contract_digest": self.hydration_policy_contract_digest,
            "access_decision_id": str(self.access_decision_id),
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "rights_state": self.rights_state,
            "lifecycle_state": self.lifecycle_state,
            "trust_scope": self.trust_scope.value,
        }


@dataclass(frozen=True, slots=True)
class RetrievalContextV2:
    context_id: RetrievalContextV2Id
    request_id: RetrievalRequestId
    tool_name: str
    tool_version: str
    policy_digest: str
    query_digest: str
    outcome: RetrievalOutcome
    projection: RetrievalProjectionMetadata
    branches: tuple[RetrievalBranchExecution, ...]
    retained_candidates: tuple[FusedRetrievalCandidate, ...]
    exclusions: tuple[RetrievalExclusion, ...]
    hydrated_passages: tuple[HydratedRetrievalPassage, ...]
    total_context_bytes: int
    truncated: bool
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.context_id, RetrievalContextV2Id):
            raise RetrievalContractError("context identity must be typed")
        if not isinstance(self.request_id, RetrievalRequestId):
            raise RetrievalContractError("context request identity must be typed")
        if self.tool_name != "find_related_event_candidates":
            raise RetrievalContractError("unknown retrieval tool")
        require_token(self.tool_version, field="retrieval_tool_version")
        for field_name in ("policy_digest", "query_digest"):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if not isinstance(self.outcome, RetrievalOutcome):
            raise RetrievalContractError("retrieval outcome must be typed")
        if not isinstance(self.projection, RetrievalProjectionMetadata):
            raise RetrievalContractError("retrieval projection metadata must be typed")
        if not isinstance(self.branches, tuple):
            raise RetrievalContractError("retrieval branches must be immutable")
        branch_order = tuple(item.branch for item in self.branches)
        if branch_order != tuple(RetrievalBranch):
            raise RetrievalContractError("all four retrieval branches must execute exactly once")
        if not isinstance(self.retained_candidates, tuple) or len(self.retained_candidates) > 12:
            raise RetrievalContractError("retained candidates exceed fixed context bound")
        ranks = tuple(item.final_rank for item in self.retained_candidates)
        if ranks != tuple(range(1, len(ranks) + 1)):
            raise RetrievalContractError("retained candidate ranks must be contiguous")
        roots = tuple(item.dependency_root_id for item in self.retained_candidates)
        if len(roots) != len(set(roots)):
            raise RetrievalContractError("retained candidates must be dependency-deduplicated")
        if not isinstance(self.exclusions, tuple):
            raise RetrievalContractError("retrieval exclusions must be immutable")
        exclusion_roots = tuple(item.dependency_root_id for item in self.exclusions)
        if exclusion_roots != tuple(sorted(set(exclusion_roots))):
            raise RetrievalContractError("retrieval exclusions must be sorted and unique")
        if set(roots) & set(exclusion_roots):
            raise RetrievalContractError("a dependency root cannot be retained and excluded")
        if not isinstance(self.hydrated_passages, tuple):
            raise RetrievalContractError("hydrated passages must be immutable")
        passage_ids = tuple(item.passage_id for item in self.hydrated_passages)
        if passage_ids != tuple(sorted(set(passage_ids))):
            raise RetrievalContractError("hydrated passages must be sorted and unique")
        if isinstance(self.total_context_bytes, bool) or not isinstance(self.total_context_bytes, int) or self.total_context_bytes < 0:
            raise RetrievalContractError("context byte count must be non-negative")
        if self.total_context_bytes > 262_144:
            raise RetrievalContractError("retrieval context exceeds fixed byte bound")
        if not isinstance(self.truncated, bool):
            raise RetrievalContractError("context truncation flag must be boolean")
        if self.truncated:
            raise RetrievalStateError("a truncated fixture context cannot be complete")
        if self.outcome is RetrievalOutcome.COMPLETE and not self.retained_candidates:
            raise RetrievalStateError("complete retrieval requires a retained candidate")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise RetrievalContractError("context recorded time must be typed")
        if self.recorded_at != self.projection.serving_time:
            raise RetrievalStateError("context time differs from projection serving time")

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom-retrieval-context-v2",
            "context_id": str(self.context_id),
            "request_id": str(self.request_id),
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "policy_digest": self.policy_digest,
            "query_digest": self.query_digest,
            "outcome": self.outcome.value,
            "projection": self.projection.canonical_value(),
            "branches": [item.canonical_value() for item in self.branches],
            "retained_candidates": [
                item.canonical_value() for item in self.retained_candidates
            ],
            "exclusions": [item.canonical_value() for item in self.exclusions],
            "hydrated_passages": [
                item.canonical_value() for item in self.hydrated_passages
            ],
            "total_context_bytes": self.total_context_bytes,
            "truncated": self.truncated,
            "recorded_at": self.recorded_at.to_text(),
        }

    @property
    def context_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class RetrievalFailure:
    request_id: RetrievalRequestId
    context_id: RetrievalContextV2Id
    outcome: RetrievalOutcome
    reason_code: str
    policy_digest: str
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, RetrievalRequestId):
            raise RetrievalContractError("retrieval failure request identity must be typed")
        if not isinstance(self.context_id, RetrievalContextV2Id):
            raise RetrievalContractError("retrieval failure context identity must be typed")
        if not isinstance(self.outcome, RetrievalOutcome) or self.outcome is RetrievalOutcome.COMPLETE:
            raise RetrievalContractError("retrieval failure requires a non-complete outcome")
        require_token(self.reason_code, field="retrieval_failure_reason")
        validate_sha256_digest(self.policy_digest, field="retrieval_failure_policy_digest")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise RetrievalContractError("retrieval failure time must be typed")

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom-retrieval-failure-v1",
            "request_id": str(self.request_id),
            "context_id": str(self.context_id),
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "policy_digest": self.policy_digest,
            "recorded_at": self.recorded_at.to_text(),
        }

    @property
    def failure_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class FindRelatedEventCandidatesResult:
    request: FindRelatedEventCandidatesRequest
    context: RetrievalContextV2 | None
    failure: RetrievalFailure | None
    replayed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.request, FindRelatedEventCandidatesRequest):
            raise RetrievalContractError("retrieval result request must be typed")
        if (self.context is None) == (self.failure is None):
            raise RetrievalContractError(
                "retrieval result requires exactly one context or failure"
            )
        if self.context is not None:
            if not isinstance(self.context, RetrievalContextV2):
                raise RetrievalContractError("retrieval result context must be typed")
            if (
                self.context.request_id != self.request.request_id
                or self.context.context_id != self.request.context_id
            ):
                raise RetrievalContractError(
                    "retrieval result context identity differs from request"
                )
        if self.failure is not None:
            if not isinstance(self.failure, RetrievalFailure):
                raise RetrievalContractError("retrieval result failure must be typed")
            if (
                self.failure.request_id != self.request.request_id
                or self.failure.context_id != self.request.context_id
            ):
                raise RetrievalContractError(
                    "retrieval result failure identity differs from request"
                )
        if not isinstance(self.replayed, bool):
            raise RetrievalContractError("retrieval replay flag must be boolean")

    @property
    def outcome(self) -> RetrievalOutcome:
        if self.context is not None:
            return self.context.outcome
        assert self.failure is not None
        return self.failure.outcome

    @property
    def result_digest(self) -> str:
        value = (
            self.context.canonical_value()
            if self.context is not None
            else self.failure.canonical_value()  # type: ignore[union-attr]
        )
        return digest_canonical(
            {
                "contract": "newsroom-find-related-event-candidates-result-v1",
                "request": self.request.canonical_value(),
                "result": value,
            }
        )


def sorted_branch_hits(value: Iterable[RetrievalBranchHit]) -> tuple[RetrievalBranchHit, ...]:
    return tuple(
        sorted(
            value,
            key=lambda item: (
                item.branch.value,
                item.rank,
                item.result_key,
            ),
        )
    )
