from __future__ import annotations

from collections import Counter
from pathlib import Path

from newsroom.increment5.traceability import (
    ALL_REQUIREMENTS,
    DELIVERY_GROUPS,
    INCREMENT_5_TRACEABILITY,
    Increment5DecisionTrace,
    Increment5DeliveryTrace,
    validate_increment5_traceability,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _rows() -> dict[str, object]:
    return {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}


def test_traceability_is_complete_unique_and_self_validating() -> None:
    validate_increment5_traceability()
    identifiers = [row.requirement_id for row in INCREMENT_5_TRACEABILITY]

    assert len(identifiers) == 114
    assert len(set(identifiers)) == 114
    assert frozenset(identifiers) == ALL_REQUIREMENTS


def test_delivery_map_matches_dependency_order_without_overclaim() -> None:
    counts = Counter(row.delivery_trace for row in INCREMENT_5_TRACEABILITY)
    assert counts == {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 12,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 6,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 31,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 56,
        Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 1,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 7,
    }

    for row in INCREMENT_5_TRACEABILITY:
        if row.delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A:
            assert row.delivery_issue == 250
            assert row.delivery_target == "contract-profile-plan-and-traceability"
            assert "test_increment5a" in row.verification_target
        elif row.delivery_trace is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT:
            assert row.delivery_issue == 144
            assert row.delivery_target == "increment-4-accepted-authority"
        elif (
            row.delivery_trace
            is Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION
        ):
            assert row.requirement_id == "GRPROD-022"
        else:
            assert row.delivery_issue in {251, 252, 253, 254}
            assert row.delivery_target.startswith("issue:#")
            assert row.verification_target.endswith(":completion-evidence")


def test_decision_map_has_no_runtime_approval_or_post_merge_admission_state() -> None:
    assert {
        row.decision_trace for row in INCREMENT_5_TRACEABILITY
    } == {
        Increment5DecisionTrace.BOUND_BY_5A,
        Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY,
    }
    assert all(
        "approval" not in row.delivery_target.lower()
        for row in INCREMENT_5_TRACEABILITY
    )
    assert all(
        "github" not in row.verification_target.lower()
        for row in INCREMENT_5_TRACEABILITY
    )


def test_delivery_groups_are_disjoint_and_cover_all_requirements() -> None:
    seen: set[str] = set()
    for requirements in DELIVERY_GROUPS.values():
        assert not seen.intersection(requirements)
        seen.update(requirements)
    assert seen == set(ALL_REQUIREMENTS)


def test_prior_delivery_uses_exact_increment_and_existing_traceability_target() -> None:
    rows = _rows()
    expected = {
        "GRAG-030": (
            144,
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            "newsroom/increment4/traceability.py#GRAG-030",
        ),
        "GRPROD-003": (
            144,
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            "newsroom/increment4/traceability.py#GRPROD-003",
        ),
        "GRPROD-005": (
            144,
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            "newsroom/increment4/traceability.py#GRPROD-005",
        ),
        "GRPROD-013": (
            144,
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            "newsroom/increment4/traceability.py#GRPROD-013",
        ),
        "GRPROD-014": (
            144,
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            "newsroom/increment4/traceability.py#GRPROD-014",
        ),
        "GRPROD-016": (
            144,
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            "newsroom/increment4/traceability.py#GRPROD-016",
        ),
        "GRPROD-020": (
            144,
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            "newsroom/increment4/traceability.py#GRPROD-020",
        ),
    }
    assert frozenset(expected) == DELIVERY_GROUPS[
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT
    ]
    for requirement, (issue, anchor) in expected.items():
        row = rows[requirement]
        assert (
            row.decision_trace
            is Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY
        )
        assert (
            row.delivery_trace
            is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT
        )
        assert row.delivery_issue == issue
        assert row.decision_anchor == anchor

    prior_rows = (
        row
        for row in INCREMENT_5_TRACEABILITY
        if row.delivery_trace
        is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT
    )
    for row in prior_rows:
        _, location = row.decision_anchor.split(":", 1)
        path_text, fragment = location.split("#", 1)
        source = (_REPOSITORY_ROOT / path_text).read_text(encoding="utf-8")
        assert fragment in source, row.requirement_id


def test_hybrid_composition_and_complete_lineage_are_owned_by_5d() -> None:
    rows = _rows()
    expected = {
        "GRAG-031": (
            "issue:#253:deferred:deterministic-hybrid-fusion-and-dependency-"
            "root-deduplication"
        ),
        "GRAG-042": (
            "issue:#253:deferred:source-revision-signal-lead-hypothesis-and-"
            "candidate-lineage-projection-and-hydration"
        ),
    }
    for requirement, anchor in expected.items():
        row = rows[requirement]
        assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5D
        assert row.delivery_issue == 253
        assert row.delivery_target == (
            "issue:#253:hybrid-composition-lineage-hydration-freshness-and-"
            "degradation"
        )
        assert row.decision_anchor == anchor


def test_conditional_challenger_policy_remains_deferred_to_5e() -> None:
    row = _rows()["GRAG-051"]
    assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A
    assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
    assert row.delivery_issue == 254
    assert row.decision_anchor == (
        "issue:#254:deferred:conditional-challenger-requires-measured-blocker-"
        "or-owner-approved-comparison-purpose"
    )


def test_production_profile_and_readiness_validation_remain_deferred_to_5e() -> None:
    rows = _rows()

    assert rows["GRPROD-004"].delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
    assert rows["GRPROD-004"].delivery_issue == 254
    assert rows["GRPROD-004"].decision_anchor == (
        "issue:#254:deferred:production-profile-rejects-fake-noop-disabled-or-"
        "omitted-graphrag"
    )

    assert rows["GRPROD-015"].delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
    assert rows["GRPROD-015"].delivery_issue == 254
    assert rows["GRPROD-015"].decision_anchor == (
        "issue:#254:deferred:production-configuration-build-and-readiness-"
        "validation"
    )


def test_operational_profiles_and_sensitive_evidence_remain_deferred_to_5e() -> None:
    rows = _rows()
    for requirement in (
        "DOPS-001",
        "DOPS-002",
        "DOPS-007",
        "DOPS-030",
        "DOPS-031",
        "DOPS-032",
        "DOPS-033",
        "DOPS-034",
        "DOPS-037",
        "DOPS-040",
        "DOPS-060",
        "DOPS-070",
        "DEVAL-073",
        "DOPS-064",
        "DOPS-072",
        "DOPS-074",
        "DOPS-075",
    ):
        row = rows[requirement]
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254

    assert rows["DOPS-001"].decision_anchor == (
        "issue:#254:deferred:versioned-operational-profile"
    )
    assert rows["DOPS-002"].decision_anchor == (
        "issue:#254:deferred:scope-specific-timing-freshness-retry-capacity-"
        "alert-objectives"
    )
    assert rows["DOPS-007"].decision_anchor == (
        "issue:#254:deferred:source-planned-wall-monotonic-and-authoritative-"
        "record-time-separation"
    )
    for requirement in (
        "DOPS-030",
        "DOPS-031",
        "DOPS-032",
        "DOPS-033",
        "DOPS-034",
    ):
        assert rows[requirement].decision_anchor == (
            "issue:#254:deferred:retry-classification-bounded-backoff-health-"
            "and-circuit-controls"
        )
    assert rows["DOPS-037"].decision_anchor == (
        "issue:#254:deferred:bounded-role-aware-contingency-activation-and-"
        "deactivation"
    )
    assert rows["DOPS-040"].decision_anchor == (
        "issue:#254:deferred:queue-retention-and-explicit-closure-evidence"
    )
    assert rows["DOPS-060"].decision_anchor == (
        "issue:#254:deferred:version-attributed-metrics-logs-alerts-and-"
        "incidents"
    )
    assert rows["DOPS-070"].decision_anchor == (
        "issue:#254:deferred:every-new-source-adapter-parser-profile-worker-"
        "retrieval-and-provider-version-requires-operational-admission"
    )


def test_graphrag_use_cases_and_decision_scope_use_exact_machine_plan_anchors() -> None:
    rows = _rows()

    assert rows["GRAG-054"].decision_anchor == (
        "newsroom/increment5/data/"
        "increment5_retrieval_evaluation_plan_v1.json"
        "#/mandatory_query_families"
    )
    assert rows["GRAG-055"].decision_anchor == (
        "newsroom/increment5/data/"
        "increment5_retrieval_evaluation_plan_v1.json"
        "#/decision_scope"
    )
    assert rows["GRAG-056"].decision_anchor == (
        "newsroom/increment5/data/"
        "increment5_retrieval_evaluation_plan_v1.json"
        "#/zero_tolerance_gates"
    )


def test_evaluation_requirements_use_requirement_specific_anchors() -> None:
    rows = _rows()

    assert rows["DEVAL-003"].decision_anchor.endswith("#/payload/non_effects")
    assert rows["DEVAL-051"].decision_anchor.endswith(
        "#/payload/evaluation_plan/thresholds_frozen_before_qualification"
    )
    assert rows["DEVAL-064"].decision_anchor.endswith("#/payload/rights_matrix")
    assert rows["DEVAL-072"].decision_anchor.endswith("#public-artifact-safety")
    assert rows["DEVAL-073"].decision_anchor.endswith("#decision-output")

    deval_anchors = {
        row.decision_anchor
        for row in INCREMENT_5_TRACEABILITY
        if row.requirement_id.startswith("DEVAL-")
    }
    assert len(deval_anchors) >= 8
    assert not all(
        anchor.endswith("#/payload/evaluation_plan") for anchor in deval_anchors
    )


def test_every_requirement_has_one_nonempty_explicit_anchor() -> None:
    anchors = [row.decision_anchor for row in INCREMENT_5_TRACEABILITY]
    assert len(anchors) == 114
    assert all(anchor and anchor == anchor.strip() for anchor in anchors)
    assert all("prefix-default" not in anchor for anchor in anchors)