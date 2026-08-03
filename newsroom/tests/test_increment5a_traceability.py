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


def test_traceability_is_complete_unique_disjoint_and_self_validating() -> None:
    validate_increment5_traceability()
    identifiers = [row.requirement_id for row in INCREMENT_5_TRACEABILITY]

    assert len(identifiers) == 114
    assert len(set(identifiers)) == 114
    assert frozenset(identifiers) == ALL_REQUIREMENTS

    seen: set[str] = set()
    for requirements in DELIVERY_GROUPS.values():
        assert not seen.intersection(requirements)
        seen.update(requirements)
    assert seen == set(ALL_REQUIREMENTS)


def test_delivery_map_matches_dependency_order_without_overclaim() -> None:
    counts = Counter(row.delivery_trace for row in INCREMENT_5_TRACEABILITY)
    assert counts == {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 12,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 5,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 29,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 59,
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


def test_decision_map_has_no_runtime_approval_or_admission_state() -> None:
    assert {row.decision_trace for row in INCREMENT_5_TRACEABILITY} == {
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


def test_prior_delivery_points_to_existing_increment4_evidence() -> None:
    rows = _rows()
    expected = DELIVERY_GROUPS[
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT
    ]
    assert expected == {
        "GRAG-030",
        "GRPROD-003",
        "GRPROD-005",
        "GRPROD-013",
        "GRPROD-014",
        "GRPROD-016",
        "GRPROD-020",
    }

    for requirement in expected:
        row = rows[requirement]
        assert (
            row.decision_trace
            is Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY
        )
        assert row.delivery_issue == 144
        assert row.decision_anchor == (
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            f"newsroom/increment4/traceability.py#{requirement}"
        )

        _, location = row.decision_anchor.split(":", 1)
        path_text, fragment = location.split("#", 1)
        source = (_REPOSITORY_ROOT / path_text).read_text(encoding="utf-8")
        assert fragment in source, requirement


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
        assert row.decision_anchor == anchor


def test_deval_046_uses_the_complete_frozen_machine_protocol() -> None:
    row = _rows()["DEVAL-046"]
    assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
    assert row.delivery_issue == 254
    assert row.decision_anchor == (
        "newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json"
        "#/triage_error_protocol"
    )


def test_operational_security_reconciliation_and_containment_belong_to_5e() -> None:
    rows = _rows()
    expected = {
        "DOPS-050": (
            "issue:#254:deferred:full-reconciliation-orphaned-ownership-"
            "ambiguous-calls-duplicate-delivery-stale-work-and-pending-handoffs"
        ),
        "DOPS-067": (
            "issue:#254:deferred:least-privilege-credential-source-access-"
            "and-approved-network-destination-evidence"
        ),
        "DOPS-073": (
            "issue:#254:deferred:narrowest-safe-scope-pause-and-broadened-"
            "operational-containment"
        ),
    }
    for requirement, anchor in expected.items():
        row = rows[requirement]
        assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254
        assert row.decision_anchor == anchor


def test_production_and_challenger_controls_remain_deferred_to_5e() -> None:
    rows = _rows()
    for requirement in ("GRAG-051", "GRPROD-004", "GRPROD-015"):
        row = rows[requirement]
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254


def test_every_requirement_has_one_explicit_anchor() -> None:
    anchors = [row.decision_anchor for row in INCREMENT_5_TRACEABILITY]
    assert len(anchors) == 114
    assert all(anchor and anchor == anchor.strip() for anchor in anchors)
    assert all("prefix-default" not in anchor for anchor in anchors)
