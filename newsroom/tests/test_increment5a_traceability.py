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


def test_traceability_is_complete_unique_and_self_validating() -> None:
    validate_increment5_traceability()
    identifiers = [row.requirement_id for row in INCREMENT_5_TRACEABILITY]

    assert len(identifiers) == 114
    assert len(set(identifiers)) == 114
    assert frozenset(identifiers) == ALL_REQUIREMENTS


def test_delivery_map_matches_dependency_order_without_overclaim() -> None:
    counts = Counter(row.delivery_trace for row in INCREMENT_5_TRACEABILITY)
    assert counts == {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 23,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 2,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 7,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 35,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 42,
        Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 1,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 4,
    }

    for row in INCREMENT_5_TRACEABILITY:
        if row.delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A:
            assert row.delivery_issue == 250
            assert row.delivery_target == "contract-and-profile-validation"
            assert "test_increment5a" in row.verification_target
        elif row.delivery_trace is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT:
            assert row.delivery_issue == 144
        elif row.delivery_trace is Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION:
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
    assert all("approval" not in row.delivery_target.lower() for row in INCREMENT_5_TRACEABILITY)
    assert all("github" not in row.verification_target.lower() for row in INCREMENT_5_TRACEABILITY)


def test_delivery_groups_are_disjoint_and_cover_all_requirements() -> None:
    seen: set[str] = set()
    for requirements in DELIVERY_GROUPS.values():
        assert not seen.intersection(requirements)
        seen.update(requirements)
    assert seen == set(ALL_REQUIREMENTS)


def test_sensitive_operational_evidence_remains_deferred_to_5e() -> None:
    rows = {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}
    for requirement in ("DEVAL-073", "DOPS-064", "DOPS-072", "DOPS-074"):
        assert rows[requirement].delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert rows[requirement].delivery_issue == 254
