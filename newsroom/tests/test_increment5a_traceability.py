from __future__ import annotations

from collections import Counter

from newsroom.increment5.traceability import (
    ALL_REQUIREMENTS,
    DELIVERY_GROUPS,
    INCREMENT_5_TRACEABILITY,
    Increment5DecisionTrace,
    Increment5DeliveryTrace,
    validate_increment5_traceability,
)


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
        Increment5DeliveryTrace.DELIVERED_IN_5A: 18,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 2,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 6,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 29,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 54,
        Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 1,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 4,
    }

    for row in INCREMENT_5_TRACEABILITY:
        if row.delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A:
            assert row.delivery_issue == 250
            assert row.delivery_target == "contract-profile-plan-and-traceability"
            assert "test_increment5a" in row.verification_target
        elif row.delivery_trace is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT:
            assert row.delivery_issue == 144
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
        "DOPS-030",
        "DOPS-031",
        "DOPS-032",
        "DOPS-033",
        "DOPS-034",
        "DOPS-037",
        "DOPS-040",
        "DOPS-060",
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
