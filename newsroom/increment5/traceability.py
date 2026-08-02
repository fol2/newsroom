"""Truthful requirement-to-decision and requirement-to-delivery mapping.

A 5A row says that the reviewed contract binds a requirement. It does not claim
that a deferred retriever, tool, hydration path, Operational Profile, or
qualification run already exists. Every decision anchor is assigned explicitly;
there is no prefix-derived fallback that can point an auditor at the wrong field.
"""

from __future__ import annotations

from ._traceability_anchors import ANCHOR_BY_REQUIREMENT
from ._traceability_model import (
    ALL_REQUIREMENTS,
    DELIVERY_GROUPS,
    INHERITED_AUTHORITY,
    ISSUE_BY_DELIVERY,
    TARGET_BY_DELIVERY,
    VERIFY_BY_DELIVERY,
    Increment5DecisionTrace,
    Increment5DeliveryTrace,
    Increment5TraceabilityRow,
)


def _delivery_for(requirement_id: str) -> Increment5DeliveryTrace:
    matches = [
        delivery
        for delivery, requirements in DELIVERY_GROUPS.items()
        if requirement_id in requirements
    ]
    if len(matches) != 1:
        raise RuntimeError(f"ambiguous delivery for {requirement_id}")
    return matches[0]


def _rows() -> tuple[Increment5TraceabilityRow, ...]:
    rows: list[Increment5TraceabilityRow] = []
    for requirement_id in sorted(ALL_REQUIREMENTS):
        delivery = _delivery_for(requirement_id)
        rows.append(
            Increment5TraceabilityRow(
                requirement_id=requirement_id,
                decision_anchor=ANCHOR_BY_REQUIREMENT[requirement_id],
                decision_trace=(
                    Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY
                    if requirement_id in INHERITED_AUTHORITY
                    else Increment5DecisionTrace.BOUND_BY_5A
                ),
                delivery_trace=delivery,
                delivery_issue=ISSUE_BY_DELIVERY[delivery],
                delivery_target=TARGET_BY_DELIVERY[delivery],
                verification_target=VERIFY_BY_DELIVERY[delivery],
            )
        )
    return tuple(rows)


INCREMENT_5_TRACEABILITY = _rows()


def validate_increment5_traceability() -> None:
    identifiers = tuple(row.requirement_id for row in INCREMENT_5_TRACEABILITY)
    if len(identifiers) != 114 or len(set(identifiers)) != 114:
        raise RuntimeError("Increment 5 traceability must contain 114 unique rows")
    if frozenset(identifiers) != ALL_REQUIREMENTS:
        raise RuntimeError("Increment 5 traceability requirement inventory differs")

    seen: set[str] = set()
    for delivery, requirements in DELIVERY_GROUPS.items():
        overlap = seen.intersection(requirements)
        if overlap:
            raise RuntimeError(
                f"delivery groups overlap at {delivery.value}: {sorted(overlap)}"
            )
        seen.update(requirements)
    if seen != set(ALL_REQUIREMENTS):
        raise RuntimeError("delivery groups do not cover the accepted inventory")

    expected_counts = {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 20,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 2,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 6,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 29,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 52,
        Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 1,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 4,
    }
    actual_counts = {
        delivery: sum(
            row.delivery_trace is delivery for row in INCREMENT_5_TRACEABILITY
        )
        for delivery in Increment5DeliveryTrace
    }
    if actual_counts != expected_counts:
        raise RuntimeError("delivery counts differ from the accepted dependency map")

    for row in INCREMENT_5_TRACEABILITY:
        if row.delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A:
            if row.delivery_issue != 250 or "test_increment5a" not in row.verification_target:
                raise RuntimeError("5A row overstates deferred implementation")
        elif row.delivery_trace is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT:
            if row.delivery_issue != 144:
                raise RuntimeError("prior authority row has the wrong issue")
        elif row.delivery_trace is Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION:
            if row.requirement_id != "GRPROD-022":
                raise RuntimeError("outside-activation row differs from v1")
        elif row.delivery_issue not in {251, 252, 253, 254}:
            raise RuntimeError("deferred row has the wrong issue")

    rows = {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}
    deferred_operational_anchors = {
        "DOPS-001": "issue:#254:deferred:versioned-operational-profile",
        "DOPS-002": (
            "issue:#254:deferred:scope-specific-timing-freshness-retry-"
            "capacity-alert-objectives"
        ),
        "DOPS-030": (
            "issue:#254:deferred:retry-classification-bounded-backoff-"
            "health-and-circuit-controls"
        ),
        "DOPS-031": (
            "issue:#254:deferred:retry-classification-bounded-backoff-"
            "health-and-circuit-controls"
        ),
        "DOPS-032": (
            "issue:#254:deferred:retry-classification-bounded-backoff-"
            "health-and-circuit-controls"
        ),
        "DOPS-033": (
            "issue:#254:deferred:retry-classification-bounded-backoff-"
            "health-and-circuit-controls"
        ),
        "DOPS-034": (
            "issue:#254:deferred:retry-classification-bounded-backoff-"
            "health-and-circuit-controls"
        ),
        "DOPS-037": (
            "issue:#254:deferred:bounded-role-aware-contingency-"
            "activation-and-deactivation"
        ),
        "DOPS-040": (
            "issue:#254:deferred:queue-retention-and-explicit-closure-"
            "evidence"
        ),
        "DOPS-060": (
            "issue:#254:deferred:version-attributed-metrics-logs-alerts-"
            "and-incidents"
        ),
    }
    for requirement, expected_anchor in deferred_operational_anchors.items():
        row = rows[requirement]
        if (
            row.delivery_trace is not Increment5DeliveryTrace.DEFERRED_TO_5E
            or row.delivery_issue != 254
            or row.decision_anchor != expected_anchor
        ):
            raise RuntimeError(
                f"operational evidence is overstated or misplaced: {requirement}"
            )


validate_increment5_traceability()
