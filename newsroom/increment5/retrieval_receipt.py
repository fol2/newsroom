"""Immutable independently attributable receipt for one Increment 5B branch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp

from ._retrieval_validation import (
    Increment5RetrievalContractError,
    bounded_int,
    require_bool,
    require_digest,
)
from .retrieval_context import BranchRequestContext
from .retrieval_hits import BranchExclusion, BranchHit
from .retrieval_outcomes import BranchFailureCode, BranchOutcome
from .retrieval_snapshot import BranchSourceSnapshot


@dataclass(frozen=True, slots=True)
class BranchReceipt:
    request_context: BranchRequestContext
    request_digest: str
    outcome: BranchOutcome
    failure_code: BranchFailureCode
    failure_detail_digest: str | None
    source_snapshot: BranchSourceSnapshot
    hits: tuple[BranchHit, ...]
    exclusions: tuple[BranchExclusion, ...]
    started_at: UtcTimestamp
    completed_at: UtcTimestamp
    elapsed_ms: int
    external_call_count: int = 0
    provider_cost_microunits: int = 0
    authority_effect: str = "NONE"
    hybrid_composed: bool = False
    final_hybrid_order_selected: bool = False
    dependency_deduplicated: bool = False
    candidate_effect: str = "NONE"

    _CONTRACT: ClassVar[str] = "newsroom.increment5b.branch-receipt.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.request_context, BranchRequestContext):
            raise Increment5RetrievalContractError("receipt context must be typed")
        require_digest(self.request_digest, field="receipt request digest")
        if not isinstance(self.outcome, BranchOutcome):
            raise Increment5RetrievalContractError("receipt outcome must be typed")
        if not isinstance(self.failure_code, BranchFailureCode):
            raise Increment5RetrievalContractError("receipt failure code must be typed")
        if self.outcome is BranchOutcome.COMPLETE:
            if self.failure_code is not BranchFailureCode.NONE or self.failure_detail_digest:
                raise Increment5RetrievalContractError(
                    "complete receipt cannot carry failure detail"
                )
        else:
            if self.failure_code is BranchFailureCode.NONE:
                raise Increment5RetrievalContractError(
                    "non-complete receipt requires a failure code"
                )
            require_digest(self.failure_detail_digest, field="failure detail digest")
        if not isinstance(self.source_snapshot, BranchSourceSnapshot):
            raise Increment5RetrievalContractError("receipt snapshot must be typed")
        if self.source_snapshot != self.request_context.source_snapshot:
            raise Increment5RetrievalContractError(
                "receipt snapshot differs from request snapshot"
            )
        if not isinstance(self.hits, tuple) or len(self.hits) > 8:
            raise Increment5RetrievalContractError("receipt hits exceed fixed bound")
        if not all(isinstance(hit, BranchHit) for hit in self.hits):
            raise Increment5RetrievalContractError("receipt hits are untyped")
        if any(hit.mode is not self.request_context.mode for hit in self.hits):
            raise Increment5RetrievalContractError("receipt mixes branch modes")
        if tuple(hit.rank for hit in self.hits) != tuple(range(1, len(self.hits) + 1)):
            raise Increment5RetrievalContractError("receipt ranks must be contiguous")
        keys = tuple(hit.result_key for hit in self.hits)
        if len(keys) != len(set(keys)):
            raise Increment5RetrievalContractError("receipt result keys must be unique")
        if not isinstance(self.exclusions, tuple) or not all(
            isinstance(item, BranchExclusion) for item in self.exclusions
        ):
            raise Increment5RetrievalContractError("receipt exclusions must be typed")
        exclusion_keys = tuple(
            (item.reason.value, item.source_kind, item.source_identity)
            for item in self.exclusions
        )
        if exclusion_keys != tuple(sorted(set(exclusion_keys))):
            raise Increment5RetrievalContractError(
                "receipt exclusions must be sorted and unique"
            )
        if not isinstance(self.started_at, UtcTimestamp) or not isinstance(
            self.completed_at, UtcTimestamp
        ):
            raise Increment5RetrievalContractError("receipt times must be typed")
        if self.completed_at.value < self.started_at.value:
            raise Increment5RetrievalContractError("receipt completion precedes start")
        bounded_int(self.elapsed_ms, field="elapsed ms", maximum=5000)
        bounded_int(self.external_call_count, field="external calls")
        bounded_int(self.provider_cost_microunits, field="provider cost")
        if self.external_call_count or self.provider_cost_microunits:
            raise Increment5RetrievalContractError("5B permits zero calls and spend")
        if self.authority_effect != "NONE" or self.candidate_effect != "NONE":
            raise Increment5RetrievalContractError(
                "branch receipt cannot claim authority or Candidate effect"
            )
        for field, value in (
            ("hybrid composed", self.hybrid_composed),
            ("final hybrid order", self.final_hybrid_order_selected),
            ("dependency deduplicated", self.dependency_deduplicated),
        ):
            require_bool(value, field=field)
            if value:
                raise Increment5RetrievalContractError(
                    "5B receipt cannot claim composition or deduplication"
                )

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": self._CONTRACT,
            "request_context": self.request_context.canonical_value(),
            "request_digest": self.request_digest,
            "outcome": self.outcome.value,
            "failure_code": self.failure_code.value,
            "failure_detail_digest": self.failure_detail_digest,
            "source_snapshot": self.source_snapshot.canonical_value(),
            "hits": [hit.canonical_value() for hit in self.hits],
            "exclusions": [item.canonical_value() for item in self.exclusions],
            "started_at": self.started_at.to_text(),
            "completed_at": self.completed_at.to_text(),
            "elapsed_ms": self.elapsed_ms,
            "external_call_count": self.external_call_count,
            "provider_cost_microunits": self.provider_cost_microunits,
            "authority_effect": self.authority_effect,
            "hybrid_composed": self.hybrid_composed,
            "final_hybrid_order_selected": self.final_hybrid_order_selected,
            "dependency_deduplicated": self.dependency_deduplicated,
            "candidate_effect": self.candidate_effect,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "BranchReceipt":
        from .retrieval_receipt_codec import parse_branch_receipt

        return parse_branch_receipt(raw)



@dataclass(frozen=True, slots=True)
class BranchExecutionResult:
    receipt: BranchReceipt
    replayed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, BranchReceipt):
            raise Increment5RetrievalContractError("execution result requires receipt")
        require_bool(self.replayed, field="branch replayed")


__all__ = ["BranchExecutionResult", "BranchReceipt"]
