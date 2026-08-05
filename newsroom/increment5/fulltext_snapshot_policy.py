"""Shared deterministic snapshot policy for the Increment 5B2 branch."""

from __future__ import annotations

from newsroom.increment5.branch_contracts import BranchOutcome
from newsroom.projection.models import ProjectionGenerationState
from newsroom.projection.neo4j.models import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
)

from .fulltext_contracts import (
    FULLTEXT_ANALYZER,
    FULLTEXT_PROVIDER,
    FullTextBranchRequest,
    FullTextContractError,
    FullTextIndexState,
    FullTextProjectionSnapshot,
)


def fulltext_snapshot_failure(
    request: FullTextBranchRequest,
    snapshot: FullTextProjectionSnapshot,
) -> tuple[BranchOutcome, str] | None:
    """Return the exact fail-closed outcome for one retained projection snapshot."""

    if not isinstance(request, FullTextBranchRequest):
        raise FullTextContractError("full-text snapshot policy request must be typed")
    if not isinstance(snapshot, FullTextProjectionSnapshot):
        raise FullTextContractError("full-text snapshot policy value must be typed")
    if snapshot.generation_state is not ProjectionGenerationState.ACTIVE:
        return BranchOutcome.STALE, "GENERATION_NOT_ACTIVE"
    if snapshot.generation_id != request.expected_generation_id:
        return BranchOutcome.STALE, "GENERATION_MISMATCH"
    if (
        snapshot.generation_identity_digest
        != request.expected_generation_identity_digest
    ):
        return BranchOutcome.STALE, "GENERATION_IDENTITY_MISMATCH"
    if (
        snapshot.fulltext_component_digest
        != request.fulltext_component_digest
        or snapshot.normalization_component_digest
        != request.normalization_component_digest
    ):
        return BranchOutcome.STALE, "GENERATION_COMPONENT_MISMATCH"
    if snapshot.rights_manifest_digest != request.expected_rights_manifest_digest:
        return BranchOutcome.STALE, "RIGHTS_MANIFEST_MISMATCH"
    if snapshot.contiguous_ledger_seq < request.minimum_watermark:
        return BranchOutcome.STALE, "PROJECTION_WATERMARK_STALE"
    if snapshot.open_gap_count:
        return BranchOutcome.INCOMPLETE, "PROJECTION_GAPS_OPEN"
    if snapshot.dead_letter_count:
        return BranchOutcome.INCOMPLETE, "PROJECTION_DEAD_LETTERS_PRESENT"
    if snapshot.validation_recorded_at.value > request.serving_time.value:
        return BranchOutcome.INCOMPLETE, "PROJECTION_TIME_INVALID"
    age_seconds = (
        request.serving_time.value - snapshot.validation_recorded_at.value
    ).total_seconds()
    if (
        request.serving_time.value > snapshot.freshness_deadline.value
        or age_seconds > request.max_projection_age_seconds
    ):
        return BranchOutcome.STALE, "PROJECTION_FRESHNESS_STALE"
    if snapshot.index_state is FullTextIndexState.POPULATING:
        return BranchOutcome.INCOMPLETE, "FULLTEXT_INDEX_POPULATING"
    if snapshot.index_state in {
        FullTextIndexState.FAILED,
        FullTextIndexState.MISSING,
    }:
        return BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_UNAVAILABLE"
    if (
        snapshot.provider != FULLTEXT_PROVIDER
        or snapshot.analyzer != FULLTEXT_ANALYZER
        or snapshot.server_version != NEO4J_B2_SERVER_VERSION
        or snapshot.driver_version != NEO4J_B2_DRIVER_VERSION
    ):
        return BranchOutcome.UNAVAILABLE, "COMPONENT_INCOMPATIBLE"
    return None


__all__ = ["fulltext_snapshot_failure"]
