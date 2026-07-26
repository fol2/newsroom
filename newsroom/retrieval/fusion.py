from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from typing import Iterable

from .fixture_v2 import IntegratedFixtureV2RetrievalContract
from .models import (
    FusedRetrievalCandidate,
    ReciprocalRankScore,
    RetrievalBranch,
    RetrievalBranchExecution,
    RetrievalBranchHit,
    RetrievalContractError,
    RetrievalExclusion,
    RetrievalExclusionReason,
)
from .policy import HybridRetrievalPolicy


def fuse_fixture_candidates(
    *,
    executions: tuple[RetrievalBranchExecution, ...],
    policy: HybridRetrievalPolicy,
    fixture: IntegratedFixtureV2RetrievalContract,
) -> tuple[tuple[FusedRetrievalCandidate, ...], tuple[RetrievalExclusion, ...]]:
    if tuple(item.branch for item in executions) != policy.required_branches:
        raise RetrievalContractError("fusion requires all four branches exactly once")

    grouped: dict[str, list[RetrievalBranchHit]] = defaultdict(list)
    for execution in executions:
        for hit in execution.hits:
            if hit.dependency_root_id not in fixture.root_by_id:
                raise RetrievalContractError("branch hit has no checked dependency root")
            grouped[hit.dependency_root_id].append(hit)

    candidates: list[tuple[Fraction, str, tuple[RetrievalBranchHit, ...]]] = []
    exclusions: list[RetrievalExclusion] = []
    date_window_start = policy.date_window_start(fixture.query_valid_time)
    for root_id in sorted(grouped):
        root = fixture.root_by_id[root_id]
        hits = _best_hit_per_branch(grouped[root_id])
        if _outside_date_window(
            observed_at=root.observed_at,
            date_window_start=date_window_start,
            query_valid_time=fixture.query_valid_time,
        ):
            exclusions.append(
                RetrievalExclusion(
                    dependency_root_id=root_id,
                    reason=RetrievalExclusionReason.OUTSIDE_TEMPORAL_SCOPE,
                    branch_hits=hits,
                    detail=(
                        "The dependency root falls outside the server-owned "
                        "retrieval date window."
                    ),
                )
            )
            continue
        if root.exclusion_reason is not None:
            exclusions.append(
                RetrievalExclusion(
                    dependency_root_id=root_id,
                    reason=root.exclusion_reason,
                    branch_hits=hits,
                    detail=_exclusion_detail(root.exclusion_reason),
                )
            )
            continue
        score = sum(
            (Fraction(1, policy.reciprocal_rank_k + hit.rank) for hit in hits),
            start=Fraction(0, 1),
        )
        if score <= 0:
            raise RetrievalContractError("retained candidate has no fusion evidence")
        candidates.append((score, root_id, hits))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    retained: list[FusedRetrievalCandidate] = []
    for final_rank, (score, root_id, hits) in enumerate(
        candidates[: policy.retained_candidate_limit], start=1
    ):
        root = fixture.root_by_id[root_id]
        retained.append(
            FusedRetrievalCandidate(
                dependency_root_id=root_id,
                candidate_version_id=root.candidate_version_id,
                contributing_branches=tuple(
                    sorted({item.branch for item in hits}, key=lambda item: item.value)
                ),
                branch_hits=hits,
                dependency_ids=root.dependency_ids,
                score=ReciprocalRankScore.from_fraction(score),
                final_rank=final_rank,
            )
        )

    for _score, root_id, hits in candidates[policy.retained_candidate_limit :]:
        exclusions.append(
            RetrievalExclusion(
                dependency_root_id=root_id,
                reason=RetrievalExclusionReason.RESULT_BOUND,
                branch_hits=hits,
                detail="The server-owned retained-candidate bound excluded this dependency root.",
            )
        )

    exclusions.sort(key=lambda item: item.dependency_root_id)
    return tuple(retained), tuple(exclusions)


def _best_hit_per_branch(
    hits: Iterable[RetrievalBranchHit],
) -> tuple[RetrievalBranchHit, ...]:
    selected: dict[RetrievalBranch, RetrievalBranchHit] = {}
    for hit in hits:
        current = selected.get(hit.branch)
        if current is None or (hit.rank, hit.result_key) < (
            current.rank,
            current.result_key,
        ):
            selected[hit.branch] = hit
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (item.branch.value, item.rank, item.result_key),
        )
    )


def _outside_date_window(
    *,
    observed_at: object,
    date_window_start: object,
    query_valid_time: object,
) -> bool:
    from newsroom.authority.types import UtcTimestamp

    if not all(
        isinstance(value, UtcTimestamp)
        for value in (observed_at, date_window_start, query_valid_time)
    ):
        raise RetrievalContractError(
            "retrieval temporal bounds must be typed UTC values"
        )
    return (
        observed_at.value < date_window_start.value
        or observed_at.value > query_valid_time.value
    )


def _exclusion_detail(reason: RetrievalExclusionReason) -> str:
    return {
        RetrievalExclusionReason.SELF_QUERY: (
            "The result belongs to the current query revision and cannot be prior context."
        ),
        RetrievalExclusionReason.INCOMPATIBLE_FORMAL_ID: (
            "The formal process identifier differs from the checked query authority."
        ),
        RetrievalExclusionReason.INCOMPATIBLE_JURISDICTION: (
            "The result belongs to a different checked jurisdiction/year lineage."
        ),
    }.get(reason, "The checked fixture policy excluded this dependency root.")
