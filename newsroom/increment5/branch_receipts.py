"""Canonical immutable receipts for independent Increment 5 branches."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import TrustScope, UtcTimestamp, require_token

from .branch_contracts import (
    BRANCH_RESULT_LIMIT,
    BRANCH_TIMEOUT_MS,
    BranchExclusion,
    BranchExclusionReason,
    BranchMode,
    BranchOutcome,
    BranchReceiptId,
    BranchRequestId,
    ExactBranchHit,
    Increment5BranchContractError,
    _bounded_non_negative_int,
    _bounded_text,
)


@dataclass(frozen=True, slots=True)
class ExactBranchReceipt:
    receipt_id: BranchReceiptId
    request_id: BranchRequestId
    request_digest: str
    contract_digest: str
    policy_id: str
    outcome: BranchOutcome
    reason_code: str
    authority_watermark: int
    started_at: UtcTimestamp
    completed_at: UtcTimestamp
    elapsed_ms: int
    hits: tuple[ExactBranchHit, ...]
    exclusions: tuple[BranchExclusion, ...]
    source_generation: str = "SQLITE_AUTHORITY"
    implementation_version: str = "sqlite-exact-identity-retriever-v1"
    external_call_count: int = 0
    gross_cost_microunits: int = 0
    authority_effect: str = "NONE"
    hybrid_result_claimed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_id, BranchReceiptId) or not isinstance(
            self.request_id, BranchRequestId
        ):
            raise Increment5BranchContractError("branch receipt identities must be typed")
        for field_name in ("request_digest", "contract_digest"):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        require_token(self.policy_id, field="receipt_policy_id")
        if not isinstance(self.outcome, BranchOutcome):
            raise Increment5BranchContractError("branch receipt outcome must be typed")
        require_token(self.reason_code, field="branch_reason_code")
        _bounded_non_negative_int(self.authority_watermark, field="authority_watermark")
        if not isinstance(self.started_at, UtcTimestamp) or not isinstance(
            self.completed_at, UtcTimestamp
        ):
            raise Increment5BranchContractError("receipt times must be typed")
        if self.completed_at.value < self.started_at.value:
            raise Increment5BranchContractError("receipt completion precedes start")
        _bounded_non_negative_int(self.elapsed_ms, field="elapsed_ms")
        if self.elapsed_ms > BRANCH_TIMEOUT_MS:
            raise Increment5BranchContractError("branch receipt exceeds its hard timeout")
        if not isinstance(self.hits, tuple) or len(self.hits) > BRANCH_RESULT_LIMIT:
            raise Increment5BranchContractError("branch receipt hits exceed their fixed bound")
        if not all(isinstance(item, ExactBranchHit) for item in self.hits):
            raise Increment5BranchContractError("branch receipt hits must be typed")
        if tuple(item.rank for item in self.hits) != tuple(range(1, len(self.hits) + 1)):
            raise Increment5BranchContractError("exact branch ranks must be contiguous")
        keys = tuple((item.authority_kind, item.authority_id) for item in self.hits)
        if len(keys) != len(set(keys)):
            raise Increment5BranchContractError("exact branch hits must be unique")
        if not isinstance(self.exclusions, tuple) or not all(
            isinstance(item, BranchExclusion) for item in self.exclusions
        ):
            raise Increment5BranchContractError("branch exclusions must be a typed tuple")
        require_token(self.source_generation, field="source_generation")
        require_token(self.implementation_version, field="implementation_version")
        if (
            self.external_call_count != 0
            or self.gross_cost_microunits != 0
            or self.authority_effect != "NONE"
            or self.hybrid_result_claimed is not False
        ):
            raise Increment5BranchContractError("5B exact receipt cannot claim an external or authority effect")
        if self.outcome is not BranchOutcome.COMPLETE and self.hits:
            raise Increment5BranchContractError("non-complete exact receipt cannot expose hits")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.exact-branch-receipt.v1",
            "receipt_id": str(self.receipt_id),
            "request_id": str(self.request_id),
            "request_digest": self.request_digest,
            "branch": BranchMode.EXACT.value,
            "contract_digest": self.contract_digest,
            "policy_id": self.policy_id,
            "implementation_version": self.implementation_version,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "source_generation": self.source_generation,
            "authority_watermark": self.authority_watermark,
            "started_at": self.started_at.to_text(),
            "completed_at": self.completed_at.to_text(),
            "elapsed_ms": self.elapsed_ms,
            "hits": [item.canonical_value() for item in self.hits],
            "exclusions": [item.canonical_value() for item in self.exclusions],
            "external_call_count": self.external_call_count,
            "gross_cost_microunits": self.gross_cost_microunits,
            "authority_effect": self.authority_effect,
            "hybrid_result_claimed": self.hybrid_result_claimed,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "ExactBranchReceipt":
        value = _decode_canonical_json(raw)
        if value.get("schema_version") != "newsroom.increment5.exact-branch-receipt.v1":
            raise Increment5BranchContractError("stored exact receipt schema differs")
        hits = tuple(
            ExactBranchHit(
                rank=int(item["rank"]),
                authority_kind=str(item["authority_kind"]),
                authority_id=str(item["authority_id"]),
                dependency_root_id=str(item["dependency_root_id"]),
                match_signal=str(item["match_signal"]),
                source_identity=str(item["source_identity"]),
                trust_scope=TrustScope(item["trust_scope"]),
                provenance_digest=str(item["provenance_digest"]),
                raw_score_ppm=int(item["raw_score_ppm"]),
            )
            for item in value["hits"]
        )
        exclusions = tuple(
            BranchExclusion(
                authority_kind=str(item["authority_kind"]),
                authority_id=str(item["authority_id"]),
                reason=BranchExclusionReason(item["reason"]),
            )
            for item in value["exclusions"]
        )
        receipt = cls(
            receipt_id=BranchReceiptId.parse(str(value["receipt_id"])),
            request_id=BranchRequestId.parse(str(value["request_id"])),
            request_digest=str(value["request_digest"]),
            contract_digest=str(value["contract_digest"]),
            policy_id=str(value["policy_id"]),
            implementation_version=str(value["implementation_version"]),
            outcome=BranchOutcome(value["outcome"]),
            reason_code=str(value["reason_code"]),
            source_generation=str(value["source_generation"]),
            authority_watermark=int(value["authority_watermark"]),
            started_at=UtcTimestamp.parse(str(value["started_at"])),
            completed_at=UtcTimestamp.parse(str(value["completed_at"])),
            elapsed_ms=int(value["elapsed_ms"]),
            hits=hits,
            exclusions=exclusions,
            external_call_count=int(value["external_call_count"]),
            gross_cost_microunits=int(value["gross_cost_microunits"]),
            authority_effect=str(value["authority_effect"]),
            hybrid_result_claimed=bool(value["hybrid_result_claimed"]),
        )
        if receipt.canonical_bytes != raw:
            raise Increment5BranchContractError("stored exact receipt is not canonical")
        return receipt


@dataclass(frozen=True, slots=True)
class CandidateCollisionReceipt:
    receipt_id: BranchReceiptId
    request_id: BranchRequestId
    request_digest: str
    contract_digest: str
    policy_id: str
    outcome: BranchOutcome
    reason_code: str
    authority_watermark: int
    occupied: bool
    candidate_id: str | None
    started_at: UtcTimestamp
    completed_at: UtcTimestamp
    elapsed_ms: int
    implementation_version: str = "sqlite-candidate-collision-read-v1"
    external_call_count: int = 0
    gross_cost_microunits: int = 0
    authority_effect: str = "NONE"
    hybrid_result_claimed: bool = False
    ranking_performed: bool = False
    candidate_created: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_id, BranchReceiptId) or not isinstance(
            self.request_id, BranchRequestId
        ):
            raise Increment5BranchContractError("collision receipt identities must be typed")
        validate_sha256_digest(self.request_digest, field="collision_request_digest")
        validate_sha256_digest(self.contract_digest, field="collision_contract_digest")
        require_token(self.policy_id, field="collision_receipt_policy_id")
        if not isinstance(self.outcome, BranchOutcome):
            raise Increment5BranchContractError("collision receipt outcome must be typed")
        require_token(self.reason_code, field="collision_reason_code")
        _bounded_non_negative_int(self.authority_watermark, field="authority_watermark")
        if not isinstance(self.occupied, bool):
            raise Increment5BranchContractError("collision occupancy must be boolean")
        if self.occupied:
            _bounded_text(self.candidate_id or "", field="collision_candidate_id")
        elif self.candidate_id is not None:
            raise Increment5BranchContractError("unoccupied collision cannot name a Candidate")
        if self.outcome is not BranchOutcome.COMPLETE and (
            self.occupied or self.candidate_id is not None
        ):
            raise Increment5BranchContractError("non-complete collision receipt cannot assert occupancy")
        if not isinstance(self.started_at, UtcTimestamp) or not isinstance(
            self.completed_at, UtcTimestamp
        ):
            raise Increment5BranchContractError("collision receipt times must be typed")
        if self.completed_at.value < self.started_at.value:
            raise Increment5BranchContractError("collision receipt completion precedes start")
        _bounded_non_negative_int(self.elapsed_ms, field="elapsed_ms")
        if self.elapsed_ms > BRANCH_TIMEOUT_MS:
            raise Increment5BranchContractError("collision receipt exceeds its hard timeout")
        require_token(self.implementation_version, field="implementation_version")
        if (
            self.external_call_count != 0
            or self.gross_cost_microunits != 0
            or self.authority_effect != "NONE"
            or self.hybrid_result_claimed is not False
            or self.ranking_performed is not False
            or self.candidate_created is not False
        ):
            raise Increment5BranchContractError(
                "collision seam cannot call externally, rank, or create a Candidate"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.candidate-collision-receipt.v1",
            "receipt_id": str(self.receipt_id),
            "request_id": str(self.request_id),
            "request_digest": self.request_digest,
            "contract_digest": self.contract_digest,
            "policy_id": self.policy_id,
            "implementation_version": self.implementation_version,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "authority_watermark": self.authority_watermark,
            "occupied": self.occupied,
            "candidate_id": self.candidate_id,
            "started_at": self.started_at.to_text(),
            "completed_at": self.completed_at.to_text(),
            "elapsed_ms": self.elapsed_ms,
            "external_call_count": self.external_call_count,
            "gross_cost_microunits": self.gross_cost_microunits,
            "authority_effect": self.authority_effect,
            "hybrid_result_claimed": self.hybrid_result_claimed,
            "ranking_performed": self.ranking_performed,
            "candidate_created": self.candidate_created,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "CandidateCollisionReceipt":
        value = _decode_canonical_json(raw)
        if value.get("schema_version") != "newsroom.increment5.candidate-collision-receipt.v1":
            raise Increment5BranchContractError("stored collision receipt schema differs")
        receipt = cls(
            receipt_id=BranchReceiptId.parse(str(value["receipt_id"])),
            request_id=BranchRequestId.parse(str(value["request_id"])),
            request_digest=str(value["request_digest"]),
            contract_digest=str(value["contract_digest"]),
            policy_id=str(value["policy_id"]),
            implementation_version=str(value["implementation_version"]),
            outcome=BranchOutcome(value["outcome"]),
            reason_code=str(value["reason_code"]),
            authority_watermark=int(value["authority_watermark"]),
            occupied=bool(value["occupied"]),
            candidate_id=(None if value["candidate_id"] is None else str(value["candidate_id"])),
            started_at=UtcTimestamp.parse(str(value["started_at"])),
            completed_at=UtcTimestamp.parse(str(value["completed_at"])),
            elapsed_ms=int(value["elapsed_ms"]),
            external_call_count=int(value["external_call_count"]),
            gross_cost_microunits=int(value["gross_cost_microunits"]),
            authority_effect=str(value["authority_effect"]),
            hybrid_result_claimed=bool(value["hybrid_result_claimed"]),
            ranking_performed=bool(value["ranking_performed"]),
            candidate_created=bool(value["candidate_created"]),
        )
        if receipt.canonical_bytes != raw:
            raise Increment5BranchContractError("stored collision receipt is not canonical")
        return receipt


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise Increment5BranchContractError(f"duplicate object name: {name}")
        result[name] = value
    return result


def _decode_canonical_json(raw: bytes) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw:
        raise Increment5BranchContractError("stored receipt bytes are required")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5BranchContractError("stored receipt is not valid JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise Increment5BranchContractError("stored receipt must use canonical JSON")
    return value


__all__ = [
    "CandidateCollisionReceipt",
    "ExactBranchReceipt",
]
