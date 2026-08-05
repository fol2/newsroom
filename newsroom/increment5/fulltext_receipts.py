"""Canonical independently attributable receipts for the 5B2 full-text branch."""

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
from newsroom.increment5.branch_contracts import (
    BRANCH_RESULT_LIMIT,
    BRANCH_TIMEOUT_MS,
    BranchExclusion,
    BranchExclusionReason,
    BranchOutcome,
    BranchReceiptId,
    BranchRequestId,
)
from newsroom.retrieval.models import RetrievalBranch, RetrievalBranchHit

from .fulltext_contracts import (
    FULLTEXT_RESPONSE_BYTE_LIMIT,
    FullTextContractError,
    FullTextProjectionSnapshot,
    NormalizedFullTextQuery,
)


@dataclass(frozen=True, slots=True)
class FullTextBranchReceipt:
    receipt_id: BranchReceiptId
    request_id: BranchRequestId
    request_digest: str
    contract_digest: str
    policy_id: str
    fulltext_component_digest: str
    normalization_component_digest: str
    outcome: BranchOutcome
    reason_code: str
    started_at: UtcTimestamp
    completed_at: UtcTimestamp
    elapsed_ms: int
    snapshot: FullTextProjectionSnapshot | None
    authority_view_digest: str | None
    normalized_query: NormalizedFullTextQuery | None
    hits: tuple[RetrievalBranchHit, ...]
    exclusions: tuple[BranchExclusion, ...]
    authority_read_count: int
    neo4j_read_count: int
    implementation_version: str = "neo4j-fulltext-generation-v1"
    external_call_count: int = 0
    gross_cost_microunits: int = 0
    authority_effect: str = "NONE"
    hybrid_result_claimed: bool = False
    projection_text_factual_use_allowed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_id, BranchReceiptId) or not isinstance(
            self.request_id, BranchRequestId
        ):
            raise FullTextContractError(
                "full-text receipt identities must be typed"
            )
        for field_name in (
            "request_digest",
            "contract_digest",
            "fulltext_component_digest",
            "normalization_component_digest",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if self.authority_view_digest is not None:
            validate_sha256_digest(
                self.authority_view_digest,
                field="fulltext_authority_view_digest",
            )
        require_token(self.policy_id, field="fulltext_receipt_policy_id")
        if not isinstance(self.outcome, BranchOutcome):
            raise FullTextContractError(
                "full-text receipt outcome must be typed"
            )
        require_token(self.reason_code, field="fulltext_reason_code")
        if not isinstance(self.started_at, UtcTimestamp) or not isinstance(
            self.completed_at, UtcTimestamp
        ):
            raise FullTextContractError("full-text receipt times must be typed")
        if self.completed_at.value < self.started_at.value:
            raise FullTextContractError(
                "full-text receipt completion precedes start"
            )
        if (
            isinstance(self.elapsed_ms, bool)
            or not isinstance(self.elapsed_ms, int)
            or not 0 <= self.elapsed_ms <= BRANCH_TIMEOUT_MS
        ):
            raise FullTextContractError(
                "full-text elapsed time exceeds its hard bound"
            )
        if self.snapshot is not None and not isinstance(
            self.snapshot, FullTextProjectionSnapshot
        ):
            raise FullTextContractError(
                "full-text receipt snapshot must be typed"
            )
        if self.normalized_query is not None and not isinstance(
            self.normalized_query, NormalizedFullTextQuery
        ):
            raise FullTextContractError(
                "full-text receipt normalized query must be typed"
            )
        if not isinstance(self.hits, tuple) or len(self.hits) > BRANCH_RESULT_LIMIT:
            raise FullTextContractError(
                "full-text receipt hits exceed their fixed bound"
            )
        if any(
            not isinstance(hit, RetrievalBranchHit)
            or hit.branch is not RetrievalBranch.FULL_TEXT
            for hit in self.hits
        ):
            raise FullTextContractError(
                "full-text receipt hits must be typed FULL_TEXT hits"
            )
        ranks = tuple(hit.rank for hit in self.hits)
        if ranks != tuple(range(1, len(self.hits) + 1)):
            raise FullTextContractError(
                "full-text receipt ranks must be contiguous"
            )
        if len({hit.result_key for hit in self.hits}) != len(self.hits):
            raise FullTextContractError(
                "full-text receipt result keys must be unique"
            )
        if not isinstance(self.exclusions, tuple) or any(
            not isinstance(item, BranchExclusion)
            for item in self.exclusions
        ):
            raise FullTextContractError(
                "full-text receipt exclusions must be typed"
            )
        for field_name, maximum in (
            ("authority_read_count", 1),
            ("neo4j_read_count", 3),
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= maximum
            ):
                raise FullTextContractError(
                    f"{field_name} is outside its fixed bound"
                )
        if self.authority_read_count == 0 and (
            self.snapshot is not None
            or self.authority_view_digest is not None
            or self.normalized_query is not None
        ):
            raise FullTextContractError(
                "full-text authority evidence requires an authority read"
            )
        if self.authority_read_count == 1 and (
            self.snapshot is None or self.authority_view_digest is None
        ):
            raise FullTextContractError(
                "full-text authority read requires snapshot and view identity"
            )
        require_token(
            self.implementation_version,
            field="fulltext_implementation_version",
        )
        if (
            self.external_call_count != 0
            or self.gross_cost_microunits != 0
            or self.authority_effect != "NONE"
            or self.hybrid_result_claimed is not False
            or self.projection_text_factual_use_allowed is not False
        ):
            raise FullTextContractError(
                "full-text receipt cannot claim external, authority, hybrid or factual effect"
            )
        if self.outcome is not BranchOutcome.COMPLETE and self.hits:
            raise FullTextContractError(
                "non-complete full-text receipt cannot expose hits"
            )
        if self.outcome is BranchOutcome.COMPLETE and (
            self.snapshot is None
            or self.normalized_query is None
            or self.authority_view_digest is None
            or self.authority_read_count != 1
            or self.neo4j_read_count != 3
        ):
            raise FullTextContractError(
                "complete full-text receipt requires complete authority and Neo4j evidence"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.fulltext-branch-receipt.v1",
            "receipt_id": str(self.receipt_id),
            "request_id": str(self.request_id),
            "request_digest": self.request_digest,
            "branch": RetrievalBranch.FULL_TEXT.value,
            "contract_digest": self.contract_digest,
            "policy_id": self.policy_id,
            "fulltext_component_digest": self.fulltext_component_digest,
            "normalization_component_digest": (
                self.normalization_component_digest
            ),
            "implementation_version": self.implementation_version,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "started_at": self.started_at.to_text(),
            "completed_at": self.completed_at.to_text(),
            "elapsed_ms": self.elapsed_ms,
            "snapshot": (
                None if self.snapshot is None else self.snapshot.canonical_value()
            ),
            "authority_view_digest": self.authority_view_digest,
            "normalized_query": (
                None
                if self.normalized_query is None
                else self.normalized_query.canonical_value()
            ),
            "hits": [hit.canonical_value() for hit in self.hits],
            "exclusions": [
                item.canonical_value() for item in self.exclusions
            ],
            "authority_read_count": self.authority_read_count,
            "neo4j_read_count": self.neo4j_read_count,
            "external_call_count": self.external_call_count,
            "gross_cost_microunits": self.gross_cost_microunits,
            "authority_effect": self.authority_effect,
            "hybrid_result_claimed": self.hybrid_result_claimed,
            "projection_text_factual_use_allowed": (
                self.projection_text_factual_use_allowed
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        value = canonical_json_bytes(self.canonical_value())
        if len(value) > FULLTEXT_RESPONSE_BYTE_LIMIT:
            raise FullTextContractError(
                "full-text receipt exceeds the fixed response byte limit"
            )
        return value

    @property
    def receipt_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "FullTextBranchReceipt":
        value = _decode_canonical_json(raw)
        if (
            value.get("schema_version")
            != "newsroom.increment5.fulltext-branch-receipt.v1"
            or value.get("branch") != RetrievalBranch.FULL_TEXT.value
        ):
            raise FullTextContractError(
                "stored full-text receipt schema differs"
            )
        snapshot_value = value["snapshot"]
        normalized_value = value["normalized_query"]
        hits = tuple(
            RetrievalBranchHit(
                branch=RetrievalBranch(str(item["branch"])),
                query_id=str(item["query_id"]),
                query_digest=str(item["query_digest"]),
                rank=int(item["rank"]),
                raw_score=str(item["raw_score"]),
                result_key=str(item["result_key"]),
                dependency_root_id=str(item["dependency_root_id"]),
                passage_id=(
                    None
                    if item["passage_id"] is None
                    else str(item["passage_id"])
                ),
                trust_scope=TrustScope(str(item["trust_scope"])),
                source_kind=str(item["source_kind"]),
                source_identity=str(item["source_identity"]),
            )
            for item in value["hits"]
        )
        exclusions = tuple(
            BranchExclusion(
                authority_kind=str(item["authority_kind"]),
                authority_id=str(item["authority_id"]),
                reason=BranchExclusionReason(str(item["reason"])),
            )
            for item in value["exclusions"]
        )
        receipt = cls(
            receipt_id=BranchReceiptId.parse(str(value["receipt_id"])),
            request_id=BranchRequestId.parse(str(value["request_id"])),
            request_digest=str(value["request_digest"]),
            contract_digest=str(value["contract_digest"]),
            policy_id=str(value["policy_id"]),
            fulltext_component_digest=str(
                value["fulltext_component_digest"]
            ),
            normalization_component_digest=str(
                value["normalization_component_digest"]
            ),
            implementation_version=str(value["implementation_version"]),
            outcome=BranchOutcome(str(value["outcome"])),
            reason_code=str(value["reason_code"]),
            started_at=UtcTimestamp.parse(str(value["started_at"])),
            completed_at=UtcTimestamp.parse(str(value["completed_at"])),
            elapsed_ms=int(value["elapsed_ms"]),
            snapshot=(
                None
                if snapshot_value is None
                else FullTextProjectionSnapshot.from_canonical_value(
                    snapshot_value
                )
            ),
            authority_view_digest=(
                None
                if value["authority_view_digest"] is None
                else str(value["authority_view_digest"])
            ),
            normalized_query=(
                None
                if normalized_value is None
                else NormalizedFullTextQuery.from_canonical_value(
                    normalized_value
                )
            ),
            hits=hits,
            exclusions=exclusions,
            authority_read_count=int(value["authority_read_count"]),
            neo4j_read_count=int(value["neo4j_read_count"]),
            external_call_count=int(value["external_call_count"]),
            gross_cost_microunits=int(value["gross_cost_microunits"]),
            authority_effect=str(value["authority_effect"]),
            hybrid_result_claimed=bool(value["hybrid_result_claimed"]),
            projection_text_factual_use_allowed=bool(
                value["projection_text_factual_use_allowed"]
            ),
        )
        if receipt.canonical_bytes != raw:
            raise FullTextContractError(
                "stored full-text receipt is not canonical"
            )
        return receipt


def _without_duplicate_names(
    pairs: list[tuple[str, Any]]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise FullTextContractError(
                f"duplicate full-text receipt object name: {name}"
            )
        result[name] = value
    return result


def _decode_canonical_json(raw: bytes) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw:
        raise FullTextContractError(
            "stored full-text receipt bytes are required"
        )
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FullTextContractError(
            "stored full-text receipt is not valid JSON"
        ) from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise FullTextContractError(
            "stored full-text receipt must use canonical JSON"
        )
    return value


__all__ = ["FullTextBranchReceipt"]
