"""Typed read-only Candidate collision request and receipt for 5B1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.authority.types import UtcTimestamp

from ._retrieval_validation import (
    Increment5RetrievalContractError,
    bounded_int,
    bounded_text,
    require_bool,
    require_digest,
)
from .contract_types import RetrievalMode
from .exact_request import (
    EXACT_RETRIEVAL_REQUIRED_SCOPE,
)
from .retrieval_context import BranchRequestContext
from .retrieval_outcomes import BranchFailureCode, BranchOutcome
from .retrieval_snapshot import BranchSourceSystem

CANDIDATE_COLLISION_PURPOSE: Final[str] = "retrieval.candidate_collision"
CANDIDATE_COLLISION_COMPONENT_DIGEST: Final[str] = digest_canonical(
    {
        "contract": "newsroom.increment5b.sqlite-candidate-collision.v1",
        "authority": "sqlite-authoritative-exact-collision",
        "query_surface": "fixed-parameterised-sql",
        "result_limit": 8,
        "timeout_ms": 5000,
        "candidate_effect": "NONE",
    }
)


class CandidateCollisionDisposition(StrEnum):
    CLEAR = "CLEAR"
    EXACT_COLLISION = "EXACT_COLLISION"


@dataclass(frozen=True, slots=True)
class CandidateCollisionRequest:
    context: BranchRequestContext
    semantic_collision_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.context, BranchRequestContext):
            raise Increment5RetrievalContractError("collision context must be typed")
        if self.context.mode is not RetrievalMode.EXACT:
            raise Increment5RetrievalContractError("collision must use exact lane")
        if self.context.purpose != CANDIDATE_COLLISION_PURPOSE:
            raise Increment5RetrievalContractError("collision purpose differs")
        if self.context.required_scope != EXACT_RETRIEVAL_REQUIRED_SCOPE:
            raise Increment5RetrievalContractError("collision scope differs")
        if self.context.component_contract_digest != CANDIDATE_COLLISION_COMPONENT_DIGEST:
            raise Increment5RetrievalContractError("collision component differs")
        if self.context.source_snapshot.source_system is not BranchSourceSystem.SQLITE_AUTHORITY:
            raise Increment5RetrievalContractError("collision requires SQLite authority")
        require_digest(self.semantic_collision_digest, field="semantic collision digest")

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom.increment5b.candidate-collision-request.v1",
            "context": self.context.canonical_value(),
            "semantic_collision_digest": self.semantic_collision_digest,
        }

    @property
    def request_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class CandidateCollisionMatch:
    candidate_id: str
    candidate_version_id: str
    semantic_collision_digest: str
    candidate_manifest_digest: str
    candidate_version_digest: str
    authority_event_id: str
    admission_decision_digest: str
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        for field, value in (
            ("candidate identity", self.candidate_id),
            ("candidate version", self.candidate_version_id),
            ("candidate event", self.authority_event_id),
        ):
            bounded_text(value, field=field, maximum_bytes=128)
        for field, value in (
            ("semantic collision digest", self.semantic_collision_digest),
            ("candidate manifest digest", self.candidate_manifest_digest),
            ("candidate version digest", self.candidate_version_digest),
            ("admission decision digest", self.admission_decision_digest),
        ):
            require_digest(value, field=field)
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise Increment5RetrievalContractError("collision match time must be typed")

    def canonical_value(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_version_id": self.candidate_version_id,
            "semantic_collision_digest": self.semantic_collision_digest,
            "candidate_manifest_digest": self.candidate_manifest_digest,
            "candidate_version_digest": self.candidate_version_digest,
            "authority_event_id": self.authority_event_id,
            "admission_decision_digest": self.admission_decision_digest,
            "recorded_at": self.recorded_at.to_text(),
        }


@dataclass(frozen=True, slots=True)
class CandidateCollisionReceipt:
    request_context: BranchRequestContext
    request_digest: str
    outcome: BranchOutcome
    failure_code: BranchFailureCode
    failure_detail_digest: str | None
    disposition: CandidateCollisionDisposition | None
    matches: tuple[CandidateCollisionMatch, ...]
    started_at: UtcTimestamp
    completed_at: UtcTimestamp
    elapsed_ms: int
    authority_effect: str = "NONE"
    candidate_effect: str = "NONE"
    ranking_applied: bool = False
    similarity_used: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request_context, BranchRequestContext):
            raise Increment5RetrievalContractError("collision receipt context must be typed")
        require_digest(self.request_digest, field="collision request digest")
        if not isinstance(self.outcome, BranchOutcome):
            raise Increment5RetrievalContractError("collision outcome must be typed")
        if not isinstance(self.failure_code, BranchFailureCode):
            raise Increment5RetrievalContractError("collision failure code must be typed")
        if self.outcome is BranchOutcome.COMPLETE:
            if self.failure_code is not BranchFailureCode.NONE or self.failure_detail_digest:
                raise Increment5RetrievalContractError("complete collision cannot fail")
            if not isinstance(self.disposition, CandidateCollisionDisposition):
                raise Increment5RetrievalContractError("complete collision needs disposition")
        else:
            if self.failure_code is BranchFailureCode.NONE:
                raise Increment5RetrievalContractError("failed collision needs code")
            require_digest(self.failure_detail_digest, field="collision failure detail")
            if self.disposition is not None:
                raise Increment5RetrievalContractError("failed collision has disposition")
        if not isinstance(self.matches, tuple) or len(self.matches) > 8:
            raise Increment5RetrievalContractError("collision matches exceed bound")
        if not all(isinstance(item, CandidateCollisionMatch) for item in self.matches):
            raise Increment5RetrievalContractError("collision matches are untyped")
        ids = tuple((item.candidate_id, item.candidate_version_id) for item in self.matches)
        if ids != tuple(sorted(set(ids))):
            raise Increment5RetrievalContractError("collision matches must be sorted")
        if self.disposition is CandidateCollisionDisposition.CLEAR and self.matches:
            raise Increment5RetrievalContractError("CLEAR cannot have matches")
        if self.disposition is CandidateCollisionDisposition.EXACT_COLLISION and not self.matches:
            raise Increment5RetrievalContractError("EXACT_COLLISION needs matches")
        if not isinstance(self.started_at, UtcTimestamp) or not isinstance(
            self.completed_at, UtcTimestamp
        ):
            raise Increment5RetrievalContractError("collision times must be typed")
        if self.completed_at.value < self.started_at.value:
            raise Increment5RetrievalContractError("collision completion precedes start")
        bounded_int(self.elapsed_ms, field="collision elapsed ms", maximum=5000)
        if self.authority_effect != "NONE" or self.candidate_effect != "NONE":
            raise Increment5RetrievalContractError("collision cannot create effects")
        require_bool(self.ranking_applied, field="collision ranking")
        require_bool(self.similarity_used, field="collision similarity")
        if self.ranking_applied or self.similarity_used:
            raise Increment5RetrievalContractError("collision cannot rank or use similarity")

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom.increment5b.candidate-collision-receipt.v1",
            "request_context": self.request_context.canonical_value(),
            "request_digest": self.request_digest,
            "outcome": self.outcome.value,
            "failure_code": self.failure_code.value,
            "failure_detail_digest": self.failure_detail_digest,
            "disposition": None if self.disposition is None else self.disposition.value,
            "matches": [item.canonical_value() for item in self.matches],
            "started_at": self.started_at.to_text(),
            "completed_at": self.completed_at.to_text(),
            "elapsed_ms": self.elapsed_ms,
            "authority_effect": self.authority_effect,
            "candidate_effect": self.candidate_effect,
            "ranking_applied": self.ranking_applied,
            "similarity_used": self.similarity_used,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


__all__ = [
    "CANDIDATE_COLLISION_COMPONENT_DIGEST",
    "CANDIDATE_COLLISION_PURPOSE",
    "CandidateCollisionDisposition",
    "CandidateCollisionMatch",
    "CandidateCollisionReceipt",
    "CandidateCollisionRequest",
]
