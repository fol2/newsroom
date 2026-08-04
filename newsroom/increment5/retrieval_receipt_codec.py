"""Canonical byte decoder for one Increment 5B branch receipt."""

from __future__ import annotations

from newsroom.authority.types import UtcTimestamp

from ._retrieval_validation import (
    Increment5RetrievalContractError,
    parse_canonical_json_object,
    require_sequence,
)
from .retrieval_context import BranchRequestContext
from .retrieval_hits import BranchExclusion, BranchHit
from .retrieval_outcomes import BranchFailureCode, BranchOutcome
from .retrieval_snapshot import BranchSourceSnapshot


def parse_branch_receipt(raw: bytes):
    from .retrieval_receipt import BranchReceipt

    item = parse_canonical_json_object(raw, field="branch receipt")
    if item.get("contract") != BranchReceipt._CONTRACT:
        raise Increment5RetrievalContractError("receipt contract identity differs")
    receipt = BranchReceipt(
        request_context=BranchRequestContext.from_value(item["request_context"]),
        request_digest=str(item["request_digest"]),
        outcome=BranchOutcome(item["outcome"]),
        failure_code=BranchFailureCode(item["failure_code"]),
        failure_detail_digest=(
            None if item.get("failure_detail_digest") is None
            else str(item["failure_detail_digest"])
        ),
        source_snapshot=BranchSourceSnapshot.from_value(item["source_snapshot"]),
        hits=tuple(
            BranchHit.from_value(value)
            for value in require_sequence(item["hits"], field="receipt hits")
        ),
        exclusions=tuple(
            BranchExclusion.from_value(value)
            for value in require_sequence(item["exclusions"], field="receipt exclusions")
        ),
        started_at=UtcTimestamp.parse(str(item["started_at"])),
        completed_at=UtcTimestamp.parse(str(item["completed_at"])),
        elapsed_ms=item["elapsed_ms"],
        external_call_count=item["external_call_count"],
        provider_cost_microunits=item["provider_cost_microunits"],
        authority_effect=str(item["authority_effect"]),
        hybrid_composed=item["hybrid_composed"],
        final_hybrid_order_selected=item["final_hybrid_order_selected"],
        dependency_deduplicated=item["dependency_deduplicated"],
        candidate_effect=str(item["candidate_effect"]),
    )
    if receipt.canonical_bytes != raw:
        raise Increment5RetrievalContractError(
            "receipt bytes differ after typed reconstruction"
        )
    return receipt


__all__ = ["parse_branch_receipt"]
