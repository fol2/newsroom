from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
import inspect

import pytest

from newsroom.authority import ObjectAdmissionId, TrustScope, digest_bytes
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.retrieval import (
    FindRelatedEventCandidatesRequest,
    FusedRetrievalCandidate,
    HYBRID_FIXTURE_POLICY_V1,
    HybridRetrievalAuthoritySystem,
    HydratedRetrievalPassage,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    ReciprocalRankScore,
    RetrievalBranch,
    RetrievalBranchExecution,
    RetrievalBranchHit,
    RetrievalContextV2,
    RetrievalContextV2Id,
    RetrievalContractError,
    RetrievalOutcome,
    RetrievalProjectionMetadata,
    RetrievalRequestId,
    canonical_score,
    open_hybrid_retrieval_authority_system,
)

from .complete_projection_2b_helpers import COMPLETE_NOW, complete_identity


_REQUEST_ID = RetrievalRequestId.parse(
    "00000000-0000-4000-8000-000000002301"
)
_CONTEXT_ID = RetrievalContextV2Id.parse(
    "00000000-0000-4000-8000-000000002302"
)
_QUERY_DIGEST = INTEGRATED_FIXTURE_V2_RETRIEVAL.query_digest(
    generation_identity_digest=complete_identity().identity_digest,
    query_valid_time=COMPLETE_NOW.to_text(),
    watermark=42,
)


def _hit(
    branch: RetrievalBranch,
    *,
    rank: int = 1,
    root: str = "candidate:00000000-0000-4000-8000-000000002012",
    passage_id: str | None = "ifv2-prior-en",
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
        source_identity=(
            INTEGRATED_FIXTURE_V2_RETRIEVAL.prior_hypothesis_version_id
            if branch is RetrievalBranch.ADMITTED_GRAPH
            else (passage_id or INTEGRATED_FIXTURE_V2_RETRIEVAL.prior_candidate_version_id)
        ),
    )


def _executions() -> tuple[RetrievalBranchExecution, ...]:
    return tuple(
        RetrievalBranchExecution(
            branch=branch,
            query_id=f"fixture-{branch.value.lower()}",
            query_digest=_QUERY_DIGEST,
            result_limit=8,
            elapsed_ms=1,
            hits=(_hit(branch),),
        )
        for branch in RetrievalBranch
    )


def test_policy_and_fixture_contracts_pin_the_accepted_2c_bounds() -> None:
    policy = HYBRID_FIXTURE_POLICY_V1
    fixture = INTEGRATED_FIXTURE_V2_RETRIEVAL

    assert policy.required_branches == tuple(RetrievalBranch)
    assert policy.graph_depth == 2
    assert policy.relation_fanout == 32
    assert policy.branch_result_limit == 8
    assert policy.retained_candidate_limit == 12
    assert policy.date_window_seconds == 31 * 24 * 60 * 60
    assert policy.max_projection_age_seconds == 60 * 60
    assert policy.reciprocal_rank_k == 60
    assert fixture.policy_digest == policy.contract_digest
    assert fixture.prior_revision_id.endswith("2004")
    assert fixture.prior_candidate_version_id.endswith("2012")
    assert fixture.root_by_passage_id["ifv2-prior-en"].candidate_version_id == (
        fixture.prior_candidate_version_id
    )
    assert fixture.root_by_passage_id["ifv2-new-en"].candidate_version_id is None
    assert "ifv2-tombstoned-negative" not in fixture.root_by_passage_id


def test_fixture_contract_rejects_identity_and_root_ambiguity() -> None:
    fixture = INTEGRATED_FIXTURE_V2_RETRIEVAL
    with pytest.raises(RetrievalContractError, match="canonical process"):
        replace(fixture, canonical_process_id="attacker-selected-process")

    candidate = fixture.root_by_id[
        f"candidate:{fixture.prior_candidate_version_id}"
    ]
    query = fixture.root_by_id[f"query:{fixture.query_revision_id}"]
    ambiguous_passages = replace(
        candidate,
        passage_ids=tuple(sorted((*candidate.passage_ids, query.passage_ids[0]))),
    )
    with pytest.raises(RetrievalContractError, match="passage authority is ambiguous"):
        replace(
            fixture,
            roots=tuple(
                sorted(
                    (
                        ambiguous_passages,
                        *(root for root in fixture.roots if root is not candidate),
                    ),
                    key=lambda root: root.root_id,
                )
            ),
        )

    ambiguous_dependencies = replace(
        candidate,
        dependency_ids=tuple(
            sorted((*candidate.dependency_ids, query.dependency_ids[0]))
        ),
    )
    with pytest.raises(RetrievalContractError, match="dependency authority is ambiguous"):
        replace(
            fixture,
            roots=tuple(
                sorted(
                    (
                        ambiguous_dependencies,
                        *(root for root in fixture.roots if root is not candidate),
                    ),
                    key=lambda root: root.root_id,
                )
            ),
        )


def test_fixture_contract_rejects_rebound_root_lineage_and_query_identity() -> None:
    fixture = INTEGRATED_FIXTURE_V2_RETRIEVAL
    candidate = fixture.root_by_id[
        f"candidate:{fixture.prior_candidate_version_id}"
    ]
    query = fixture.root_by_id[f"query:{fixture.query_revision_id}"]
    rebound_candidate = replace(
        candidate,
        passage_ids=query.passage_ids,
    )
    rebound_query = replace(
        query,
        passage_ids=candidate.passage_ids,
    )
    with pytest.raises(RetrievalContractError, match="root lineage"):
        replace(
            fixture,
            roots=tuple(
                sorted(
                    (
                        rebound_candidate,
                        rebound_query,
                        *(
                            root
                            for root in fixture.roots
                            if root not in {candidate, query}
                        ),
                    ),
                    key=lambda root: root.root_id,
                )
            ),
        )

    with pytest.raises(RetrievalContractError, match="query digest time"):
        fixture.query_digest(
            generation_identity_digest=complete_identity().identity_digest,
            query_valid_time="2042-03-12T12:00:00.000001Z",
            watermark=42,
        )
    with pytest.raises(RetrievalContractError, match="watermark"):
        fixture.query_digest(
            generation_identity_digest=complete_identity().identity_digest,
            query_valid_time=fixture.query_valid_time.to_text(),
            watermark=0,
        )


def test_request_has_no_caller_selected_limit_generation_or_query_surface() -> None:
    request = FindRelatedEventCandidatesRequest(
        request_id=_REQUEST_ID,
        context_id=_CONTEXT_ID,
        fixture_id=INTEGRATED_FIXTURE_V2_RETRIEVAL.fixture_id,
        query_revision_id=INTEGRATED_FIXTURE_V2_RETRIEVAL.query_revision_id,
        query_hypothesis_version_id=(
            INTEGRATED_FIXTURE_V2_RETRIEVAL.query_hypothesis_version_id
        ),
        query_valid_time=COMPLETE_NOW,
        idempotency_key="fixture-related-events-v1",
    )

    assert set(request.canonical_value()) == {
        "contract",
        "request_id",
        "context_id",
        "fixture_id",
        "query_revision_id",
        "query_hypothesis_version_id",
        "query_valid_time",
        "idempotency_key",
    }
    assert all(
        token not in request.canonical_value()
        for token in ("limit", "generation_id", "label", "predicate", "cypher")
    )


def test_branch_execution_requires_contiguous_bounded_unique_hits() -> None:
    first = _hit(RetrievalBranch.FULL_TEXT, rank=1)
    second = _hit(
        RetrievalBranch.FULL_TEXT,
        rank=2,
        root="distractor:incompatible-formal-id",
        passage_id="ifv2-incompatible-formal-id",
    )
    execution = RetrievalBranchExecution(
        branch=RetrievalBranch.FULL_TEXT,
        query_id=first.query_id,
        query_digest=first.query_digest,
        result_limit=8,
        elapsed_ms=4,
        hits=(first, second),
    )
    assert len(execution.hits) == 2

    with pytest.raises(RetrievalContractError, match="contiguous"):
        RetrievalBranchExecution(
            branch=RetrievalBranch.FULL_TEXT,
            query_id=first.query_id,
            query_digest=first.query_digest,
            result_limit=8,
            elapsed_ms=4,
            hits=(second,),
        )


@pytest.mark.parametrize(
    ("branch", "score", "message"),
    (
        (RetrievalBranch.EXACT, 0.5, "exact retrieval score"),
        (RetrievalBranch.ADMITTED_GRAPH, 0.0, "graph retrieval score"),
        (RetrievalBranch.FULL_TEXT, -0.5, "full-text retrieval score"),
        (RetrievalBranch.VECTOR, 1.01, "vector retrieval score"),
    ),
)
def test_branch_hit_score_domains_are_typed_and_bounded(
    branch: RetrievalBranch,
    score: float,
    message: str,
) -> None:
    with pytest.raises(RetrievalContractError, match=message):
        replace(_hit(branch), raw_score=canonical_score(score))


def test_canonical_score_accepts_exact_binary64_fixed_notation() -> None:
    # This is the actual Neo4j 2026.06 full-text score that exposed the old
    # fractional-digit cap.  ``.17g`` correctly emits 17 significant digits,
    # which requires 18 fractional digits for a value in the 10^-2 range.
    score = 0.03687901422381401
    canonical = canonical_score(score)
    assert canonical == "0.036879014223814011"
    hit = replace(_hit(RetrievalBranch.FULL_TEXT), raw_score=canonical)
    assert hit.raw_score == canonical


def test_score_text_still_rejects_noncanonical_binary64_spellings() -> None:
    with pytest.raises(RetrievalContractError, match="score text"):
        replace(
            _hit(RetrievalBranch.FULL_TEXT),
            raw_score="0.036879014223814010",
        )


def test_shared_timeout_is_rechecked_by_typed_and_fixture_authority() -> None:
    executions = tuple(
        replace(execution, elapsed_ms=1_300)
        for execution in _executions()
    )
    with pytest.raises(RetrievalContractError, match="shared tool timeout"):
        __import__(
            "newsroom.retrieval.fixture_v2",
            fromlist=["validate_fixture_branch_executions"],
        ).validate_fixture_branch_executions(
            executions=executions,
            policy=HYBRID_FIXTURE_POLICY_V1,
            contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            query_digest=_QUERY_DIGEST,
        )


def test_context_v2_requires_all_four_branches_active_projection_and_exact_hydration() -> None:
    projection = RetrievalProjectionMetadata(
        identity=complete_identity(),
        generation_state=__import__(
            "newsroom.projection.models", fromlist=["ProjectionGenerationState"]
        ).ProjectionGenerationState.ACTIVE,
        contiguous_ledger_seq=42,
        open_gap_count=0,
        dead_letter_count=0,
        validation_recorded_at=COMPLETE_NOW,
        date_window_start=(
            HYBRID_FIXTURE_POLICY_V1.date_window_start(COMPLETE_NOW)
        ),
        query_valid_time=COMPLETE_NOW,
        freshness_deadline=(
            HYBRID_FIXTURE_POLICY_V1.projection_freshness_deadline(
                COMPLETE_NOW
            )
        ),
        serving_time=COMPLETE_NOW,
    )
    hits = tuple(_hit(branch) for branch in RetrievalBranch)
    candidate = FusedRetrievalCandidate(
        dependency_root_id=(
            "candidate:00000000-0000-4000-8000-000000002012"
        ),
        candidate_version_id=(
            INTEGRATED_FIXTURE_V2_RETRIEVAL.prior_candidate_version_id
        ),
        contributing_branches=tuple(
            sorted(RetrievalBranch, key=lambda item: item.value)
        ),
        branch_hits=tuple(
            sorted(
                hits,
                key=lambda item: (item.branch.value, item.rank, item.result_key),
            )
        ),
        dependency_ids=tuple(sorted((
            INTEGRATED_FIXTURE_V2_RETRIEVAL.prior_candidate_version_id,
            INTEGRATED_FIXTURE_V2_RETRIEVAL.prior_hypothesis_version_id,
            "00000000-0000-4000-8000-000000002004",
        ))),
        score=ReciprocalRankScore.from_fraction(Fraction(4, 61)),
        final_rank=1,
    )
    passage = HydratedRetrievalPassage(
        passage_id="ifv2-prior-en",
        admission_id=ObjectAdmissionId.parse(
            "00000000-0000-4000-8000-000000002303"
        ),
        blob_digest="sha256:" + "1" * 64,
        language="en-GB",
        text="Authoritative synthetic fixture passage.",
        text_digest=digest_bytes("Authoritative synthetic fixture passage.".encode()),
        hydration_policy_contract_digest="sha256:" + "2" * 64,
        access_decision_id=ObjectAccessDecisionId.parse(
            "00000000-0000-4000-8000-000000002304"
        ),
        byte_start=0,
        byte_end=len("Authoritative synthetic fixture passage.".encode()),
        rights_state="PERMITTED",
        lifecycle_state="ACTIVE",
        trust_scope=TrustScope.OBSERVED,
    )
    context = RetrievalContextV2(
        context_id=_CONTEXT_ID,
        request_id=_REQUEST_ID,
        tool_name="find_related_event_candidates",
        tool_version=HYBRID_FIXTURE_POLICY_V1.tool_version,
        policy_digest=HYBRID_FIXTURE_POLICY_V1.contract_digest,
        query_digest=_QUERY_DIGEST,
        outcome=RetrievalOutcome.COMPLETE,
        projection=projection,
        branches=_executions(),
        retained_candidates=(candidate,),
        exclusions=(),
        hydrated_passages=(passage,),
        total_context_bytes=len(passage.text.encode()),
        truncated=False,
        recorded_at=COMPLETE_NOW,
    )
    assert context.context_digest.startswith("sha256:")

    with pytest.raises(RetrievalContractError, match="shared tool timeout"):
        replace(
            context,
            branches=tuple(
                replace(execution, elapsed_ms=1_300)
                for execution in context.branches
            ),
        )

    with pytest.raises(RetrievalContractError, match="all four"):
        RetrievalContextV2(
            context_id=_CONTEXT_ID,
            request_id=_REQUEST_ID,
            tool_name="find_related_event_candidates",
            tool_version=HYBRID_FIXTURE_POLICY_V1.tool_version,
            policy_digest=HYBRID_FIXTURE_POLICY_V1.contract_digest,
            query_digest=_QUERY_DIGEST,
            outcome=RetrievalOutcome.COMPLETE,
            projection=projection,
            branches=_executions()[:-1],
            retained_candidates=(candidate,),
            exclusions=(),
            hydrated_passages=(passage,),
            total_context_bytes=len(passage.text.encode()),
            truncated=False,
            recorded_at=COMPLETE_NOW,
        )


def test_public_named_tool_surface_exposes_no_driver_or_query_language() -> None:
    parameters = set(
        inspect.signature(
            open_hybrid_retrieval_authority_system
        ).parameters
    )
    assert "neo4j_config" in parameters
    assert {
        "driver",
        "cypher",
        "label",
        "predicate",
        "limit",
        "policy",
        "retrieval_contract",
    }.isdisjoint(
        parameters
    )
    assert HybridRetrievalAuthoritySystem.__slots__ == (
        "retrieval",
        "__close",
    )
    assert not hasattr(HybridRetrievalAuthoritySystem, "driver")
    assert not hasattr(HybridRetrievalAuthoritySystem, "execute_cypher")
