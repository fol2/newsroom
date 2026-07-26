from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from newsroom.authority import TrustScope, UtcTimestamp
from newsroom.retrieval import (
    HYBRID_FIXTURE_POLICY_V1,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalBranch,
    RetrievalBranchExecution,
    RetrievalBranchHit,
    RetrievalContractError,
    RetrievalExclusionReason,
    canonical_score,
    fuse_fixture_candidates,
)


_QUERY_DIGEST = "sha256:" + "4" * 64
_PRIOR_ROOT = "candidate:00000000-0000-4000-8000-000000002012"


def _hit(
    branch: RetrievalBranch,
    rank: int,
    root: str,
    passage_id: str | None,
) -> RetrievalBranchHit:
    return RetrievalBranchHit(
        branch=branch,
        query_id=f"fixture-{branch.value.lower()}",
        query_digest=_QUERY_DIGEST,
        rank=rank,
        raw_score=canonical_score(1.0 / rank),
        result_key=f"{branch.value}:{rank}:{root}",
        dependency_root_id=root,
        passage_id=passage_id,
        trust_scope=(
            TrustScope.ADMITTED
            if branch is RetrievalBranch.ADMITTED_GRAPH
            else TrustScope.OBSERVED
        ),
        source_kind=(
            "RELATION_ASSERTION"
            if branch is RetrievalBranch.ADMITTED_GRAPH
            else "GOVERNED_PASSAGE"
        ),
        source_identity=passage_id or root,
    )


def _execution(
    branch: RetrievalBranch,
    rows: tuple[tuple[str, str | None], ...],
) -> RetrievalBranchExecution:
    hits = tuple(
        _hit(branch, rank, root, passage_id)
        for rank, (root, passage_id) in enumerate(rows, start=1)
    )
    return RetrievalBranchExecution(
        branch=branch,
        query_id=f"fixture-{branch.value.lower()}",
        query_digest=_QUERY_DIGEST,
        result_limit=8,
        elapsed_ms=2,
        hits=hits,
    )


def test_fusion_collapses_bilingual_dependencies_and_excludes_distractors() -> None:
    executions = (
        _execution(RetrievalBranch.EXACT, ((_PRIOR_ROOT, "ifv2-prior-en"),)),
        _execution(RetrievalBranch.ADMITTED_GRAPH, ((_PRIOR_ROOT, None),)),
        _execution(
            RetrievalBranch.FULL_TEXT,
            (
                ("query:00000000-0000-4000-8000-000000002005", "ifv2-new-en"),
                (_PRIOR_ROOT, "ifv2-prior-en"),
                ("distractor:distinct-jurisdiction", "ifv2-distinct-jurisdiction"),
            ),
        ),
        _execution(
            RetrievalBranch.VECTOR,
            (
                ("query:00000000-0000-4000-8000-000000002005", "ifv2-new-en"),
                ("distractor:incompatible-formal-id", "ifv2-incompatible-formal-id"),
                (_PRIOR_ROOT, "ifv2-prior-zh-hk"),
            ),
        ),
    )

    retained, excluded = fuse_fixture_candidates(
        executions=executions,
        policy=HYBRID_FIXTURE_POLICY_V1,
        fixture=INTEGRATED_FIXTURE_V2_RETRIEVAL,
    )

    assert len(retained) == 1
    candidate = retained[0]
    assert candidate.candidate_version_id == (
        INTEGRATED_FIXTURE_V2_RETRIEVAL.prior_candidate_version_id
    )
    assert candidate.contributing_branches == tuple(
        sorted(RetrievalBranch, key=lambda item: item.value)
    )
    assert candidate.score.fraction == (
        Fraction(1, 61) + Fraction(1, 61) + Fraction(1, 62) + Fraction(1, 63)
    )
    # The two prior-language passages collapse under one dependency root while
    # their branch lineage remains inspectable.
    assert {hit.passage_id for hit in candidate.branch_hits} == {
        None,
        "ifv2-prior-en",
        "ifv2-prior-zh-hk",
    }

    assert {item.reason for item in excluded} == {
        RetrievalExclusionReason.SELF_QUERY,
        RetrievalExclusionReason.INCOMPATIBLE_FORMAL_ID,
        RetrievalExclusionReason.INCOMPATIBLE_JURISDICTION,
    }


def test_fusion_rejects_missing_or_duplicate_branch_execution() -> None:
    empty = tuple(
        _execution(branch, ())
        for branch in RetrievalBranch
    )
    with pytest.raises(RetrievalContractError, match="all four"):
        fuse_fixture_candidates(
            executions=empty[:-1],
            policy=HYBRID_FIXTURE_POLICY_V1,
            fixture=INTEGRATED_FIXTURE_V2_RETRIEVAL,
        )

    with pytest.raises(RetrievalContractError, match="all four"):
        fuse_fixture_candidates(
            executions=(empty[0], empty[0], empty[2], empty[3]),
            policy=HYBRID_FIXTURE_POLICY_V1,
            fixture=INTEGRATED_FIXTURE_V2_RETRIEVAL,
        )


def test_fusion_rejects_unchecked_dependency_root() -> None:
    executions = tuple(
        _execution(
            branch,
            (("attacker:caller-selected-root", "ifv2-prior-en"),)
            if branch is RetrievalBranch.EXACT
            else (),
        )
        for branch in RetrievalBranch
    )
    with pytest.raises(RetrievalContractError, match="checked dependency root"):
        fuse_fixture_candidates(
            executions=executions,
            policy=HYBRID_FIXTURE_POLICY_V1,
            fixture=INTEGRATED_FIXTURE_V2_RETRIEVAL,
        )


def test_fusion_excludes_checked_root_outside_server_owned_date_window() -> None:
    root_id = "distractor:distinct-jurisdiction"
    roots = tuple(
        replace(
            root,
            observed_at=UtcTimestamp.parse(
                "2041-01-01T00:00:00.000000Z"
            ),
        )
        if root.root_id == root_id
        else root
        for root in INTEGRATED_FIXTURE_V2_RETRIEVAL.roots
    )
    fixture = replace(
        INTEGRATED_FIXTURE_V2_RETRIEVAL,
        roots=roots,
    )
    executions = tuple(
        _execution(
            branch,
            ((root_id, "ifv2-distinct-jurisdiction"),)
            if branch is RetrievalBranch.FULL_TEXT
            else (),
        )
        for branch in RetrievalBranch
    )

    retained, excluded = fuse_fixture_candidates(
        executions=executions,
        policy=HYBRID_FIXTURE_POLICY_V1,
        fixture=fixture,
    )

    assert retained == ()
    assert len(excluded) == 1
    assert excluded[0].reason is RetrievalExclusionReason.OUTSIDE_TEMPORAL_SCOPE
