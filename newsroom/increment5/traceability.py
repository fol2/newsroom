"""Truthful requirement-to-decision and amended delivery ownership mapping.

A row states where an accepted requirement is completely delivered. Supporting
seams or evidence produced by Increment 5 do not move full evaluation,
operational, triage or Candidate obligations out of their later owner.
"""

from __future__ import annotations

from ._traceability_anchors import ANCHOR_BY_REQUIREMENT
from ._traceability_model import (
    ALL_REQUIREMENTS,
    CROSS_REQUEST_INTEGRATION_REQUIREMENTS,
    DEFERRED_TO_5E_REQUIREMENTS,
    DEFERRED_TO_INCREMENT_6_REQUIREMENTS,
    DEFERRED_TO_INCREMENT_8_REQUIREMENTS,
    DELIVERED_IN_5A_REQUIREMENTS,
    DELIVERY_GROUPS,
    DEVAL_REQUIREMENTS,
    DOPS_REQUIREMENTS,
    INHERITED_AUTHORITY,
    ISSUE_BY_DELIVERY,
    OPERATIONAL_DOPS,
    PRIOR_DELIVERY_EVIDENCE,
    REQUEST_RETRIEVAL_REQUIREMENTS,
    RETRIEVAL_QUALIFICATION_REQUIREMENTS,
    TARGET_BY_DELIVERY,
    VERIFY_BY_DELIVERY,
    Increment5DecisionTrace,
    Increment5DeliveryTrace,
    Increment5TraceabilityRow,
)


def _delivery_for(requirement_id: str) -> Increment5DeliveryTrace:
    matches = tuple(
        delivery
        for delivery, requirements in DELIVERY_GROUPS.items()
        if requirement_id in requirements
    )
    if len(matches) != 1:
        raise RuntimeError(f"ambiguous delivery for {requirement_id}")
    return matches[0]


def _delivery_metadata(
    requirement_id: str,
    delivery: Increment5DeliveryTrace,
) -> tuple[int, str, str]:
    if delivery is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT:
        try:
            return PRIOR_DELIVERY_EVIDENCE[requirement_id]
        except KeyError as exc:
            raise RuntimeError(
                f"prior delivery has no exact evidence: {requirement_id}"
            ) from exc
    return (
        ISSUE_BY_DELIVERY[delivery],
        TARGET_BY_DELIVERY[delivery],
        VERIFY_BY_DELIVERY[delivery],
    )


def _rows() -> tuple[Increment5TraceabilityRow, ...]:
    rows: list[Increment5TraceabilityRow] = []
    for requirement_id in sorted(ALL_REQUIREMENTS):
        delivery = _delivery_for(requirement_id)
        delivery_issue, delivery_target, verification_target = _delivery_metadata(
            requirement_id,
            delivery,
        )
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
                delivery_issue=delivery_issue,
                delivery_target=delivery_target,
                verification_target=verification_target,
            )
        )
    return tuple(rows)


INCREMENT_5_TRACEABILITY = _rows()


def validate_increment5_traceability() -> None:
    identifiers = tuple(row.requirement_id for row in INCREMENT_5_TRACEABILITY)
    if len(identifiers) != 155 or len(set(identifiers)) != 155:
        raise RuntimeError("Increment 5 traceability must contain 155 unique rows")
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
        Increment5DeliveryTrace.DELIVERED_IN_5A: 9,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 0,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 2,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 12,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 9,
        Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6: 6,
        Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8: 110,
        Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 0,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 7,
    }
    actual_counts = {
        delivery: sum(
            row.delivery_trace is delivery for row in INCREMENT_5_TRACEABILITY
        )
        for delivery in Increment5DeliveryTrace
    }
    if actual_counts != expected_counts:
        raise RuntimeError("delivery counts differ from the accepted amendment")

    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5B]:
        raise RuntimeError("5B cannot claim a complete selected requirement")
    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5D] != (
        REQUEST_RETRIEVAL_REQUIREMENTS
    ):
        raise RuntimeError("5D differs from the exact request-local boundary")
    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E] != (
        RETRIEVAL_QUALIFICATION_REQUIREMENTS
    ):
        raise RuntimeError("5E differs from the retrieval-specific boundary")
    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6] != (
        CROSS_REQUEST_INTEGRATION_REQUIREMENTS
    ):
        raise RuntimeError("Increment 6 differs from cross-request ownership")
    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8] != (
        DEFERRED_TO_INCREMENT_8_REQUIREMENTS
    ):
        raise RuntimeError("Increment 8 differs from evaluation/operations ownership")

    if REQUEST_RETRIEVAL_REQUIREMENTS.intersection(
        DEFERRED_TO_INCREMENT_6_REQUIREMENTS
    ):
        raise RuntimeError("5D contains a cross-request effect")
    if DEFERRED_TO_5E_REQUIREMENTS.intersection(
        DEFERRED_TO_INCREMENT_8_REQUIREMENTS
    ):
        raise RuntimeError("retrieval qualification claims full operational work")
    if any(item.startswith("DOPS-") for item in REQUEST_RETRIEVAL_REQUIREMENTS):
        raise RuntimeError("5D cannot claim operational DOPS delivery")
    if any(item.startswith("DOPS-") for item in DEFERRED_TO_5E_REQUIREMENTS):
        raise RuntimeError("5E cannot claim complete operational DOPS delivery")
    if OPERATIONAL_DOPS != DOPS_REQUIREMENTS.intersection(
        DEFERRED_TO_INCREMENT_8_REQUIREMENTS
    ):
        raise RuntimeError("all operational DOPS rows must be owned by Increment 8")

    expected_later_deval = DEVAL_REQUIREMENTS.difference(
        DELIVERED_IN_5A_REQUIREMENTS
    )
    if expected_later_deval != DEVAL_REQUIREMENTS.intersection(
        DEFERRED_TO_INCREMENT_8_REQUIREMENTS
    ):
        raise RuntimeError("all non-5A DEVAL rows must be owned by Increment 8")

    prior = DELIVERY_GROUPS[
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT
    ]
    if frozenset(PRIOR_DELIVERY_EVIDENCE) != prior:
        raise RuntimeError("prior delivery evidence differs from prior inventory")

    for row in INCREMENT_5_TRACEABILITY:
        if not row.decision_anchor or row.decision_anchor != row.decision_anchor.strip():
            raise RuntimeError(f"decision anchor is not canonical: {row.requirement_id}")
        if row.delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A:
            if row.delivery_issue != 250 or "test_increment5a" not in (
                row.verification_target
            ):
                raise RuntimeError("5A row overstates deferred implementation")
        elif row.delivery_trace is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT:
            if (
                row.delivery_issue,
                row.delivery_target,
                row.verification_target,
            ) != PRIOR_DELIVERY_EVIDENCE[row.requirement_id]:
                raise RuntimeError(
                    f"prior delivery metadata differs: {row.requirement_id}"
                )
        elif row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6:
            if row.delivery_issue != 146:
                raise RuntimeError("Increment 6 row has the wrong owner")
        elif row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8:
            if row.delivery_issue != 148:
                raise RuntimeError("Increment 8 row has the wrong owner")
        elif row.delivery_trace is Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION:
            raise RuntimeError("ownerless outside-activation requirements remain")
        elif row.delivery_issue not in {251, 252, 253, 254}:
            raise RuntimeError("Increment 5 deferred row has the wrong issue")

    rows = {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}
    machine_plan = (
        "newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json"
    )
    if rows["DEVAL-011"].decision_anchor != machine_plan + "#/epoch_protocol":
        raise RuntimeError("qualification Epoch anchor differs")
    for requirement in prior:
        expected_anchor = (
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            f"newsroom/increment4/traceability.py#{requirement}"
        )
        if (
            rows[requirement].decision_trace
            is not Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY
            or rows[requirement].delivery_issue != 144
            or rows[requirement].decision_anchor != expected_anchor
        ):
            raise RuntimeError(f"prior evidence differs: {requirement}")

    expected_increment6 = {
        "GRAG-042",
        "GRAG-044",
        "GRPROD-021",
        "TRI-024",
        "TRI-026",
        "TRI-028",
    }
    if {
        row.requirement_id
        for row in INCREMENT_5_TRACEABILITY
        if row.delivery_issue == 146
    } != expected_increment6:
        raise RuntimeError("Increment 6 transfer differs from owner amendment")

    expected_increment8_graph = {
        "GRAG-045",
        "GRAG-046",
        "GRAG-057",
        "GRPROD-002",
        "GRPROD-004",
        "GRPROD-011",
        "GRPROD-012",
        "GRPROD-022",
        "GRPROD-024",
        "GRPROD-030",
        "GRPROD-031",
    }
    if not expected_increment8_graph.issubset(
        DEFERRED_TO_INCREMENT_8_REQUIREMENTS
    ):
        raise RuntimeError("Increment 8 graph/product transfer is incomplete")


validate_increment5_traceability()
