"""Truthful requirement-to-decision and requirement-to-delivery mapping.

A 5A row says that the reviewed contract binds a requirement. It does not claim
that a deferred retriever, tool, composer, reconciliation control, containment
control, Operational Profile, or qualification run already exists.
"""

from __future__ import annotations

from ._traceability_anchors import ANCHOR_BY_REQUIREMENT
from ._traceability_model import (
    ALL_REQUIREMENTS,
    DELIVERY_GROUPS,
    INHERITED_AUTHORITY,
    ISSUE_BY_DELIVERY,
    PRIOR_DELIVERY_EVIDENCE,
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


def _require_deferred_anchor(
    rows: dict[str, Increment5TraceabilityRow],
    requirement: str,
    delivery: Increment5DeliveryTrace,
    issue: int,
    anchor: str,
) -> None:
    row = rows[requirement]
    if (
        row.decision_trace is not Increment5DecisionTrace.BOUND_BY_5A
        or row.delivery_trace is not delivery
        or row.delivery_issue != issue
        or row.decision_anchor != anchor
    ):
        raise RuntimeError(f"deferred ownership differs: {requirement}")


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

    prior_requirements = DELIVERY_GROUPS[
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT
    ]
    if frozenset(PRIOR_DELIVERY_EVIDENCE) != prior_requirements:
        raise RuntimeError("prior delivery evidence differs from prior inventory")

    expected_counts = {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 12,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 5,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 29,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 59,
        Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 1,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 7,
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
            if (
                row.delivery_issue != 250
                or "test_increment5a" not in row.verification_target
            ):
                raise RuntimeError("5A row overstates deferred implementation")
        elif row.delivery_trace is Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT:
            expected = PRIOR_DELIVERY_EVIDENCE[row.requirement_id]
            actual = (
                row.delivery_issue,
                row.delivery_target,
                row.verification_target,
            )
            if actual != expected:
                raise RuntimeError(
                    f"prior delivery metadata differs: {row.requirement_id}"
                )
        elif (
            row.delivery_trace
            is Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION
        ):
            if row.requirement_id != "GRPROD-022":
                raise RuntimeError("outside-activation row differs from v1")
        elif row.delivery_issue not in {251, 252, 253, 254}:
            raise RuntimeError("deferred row has the wrong issue")

    rows = {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}

    machine_plan_anchors = {
        "GRAG-054": "#/mandatory_query_families",
        "GRAG-055": "#/decision_scope",
        "GRAG-056": "#/zero_tolerance_gates",
        "DEVAL-046": "#/triage_error_protocol",
    }
    machine_plan_path = (
        "newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json"
    )
    for requirement, fragment in machine_plan_anchors.items():
        if rows[requirement].decision_anchor != machine_plan_path + fragment:
            raise RuntimeError(f"qualification plan anchor differs: {requirement}")

    package_neutrality = rows["GRAG-053"]
    if (
        package_neutrality.delivery_trace
        is not Increment5DeliveryTrace.DELIVERED_IN_5A
        or package_neutrality.decision_anchor
        != (
            "docs/decisions/2026-08-02-increment-5a-production-retrieval-"
            "contract.md#package-neutrality"
        )
    ):
        raise RuntimeError("package neutrality is not bound to its decision")

    for requirement in DELIVERY_GROUPS[
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT
    ]:
        row = rows[requirement]
        expected_anchor = (
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            f"newsroom/increment4/traceability.py#{requirement}"
        )
        if (
            row.decision_trace
            is not Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY
            or row.delivery_issue != 144
            or row.decision_anchor != expected_anchor
        ):
            raise RuntimeError(
                f"existing delivery has the wrong prior evidence: {requirement}"
            )

    deferred_5d = {
        "GRAG-031": (
            "issue:#253:deferred:deterministic-hybrid-fusion-and-dependency-"
            "root-deduplication"
        ),
        "GRAG-042": (
            "issue:#253:deferred:source-revision-signal-lead-hypothesis-and-"
            "candidate-lineage-projection-and-hydration"
        ),
    }
    for requirement, anchor in deferred_5d.items():
        _require_deferred_anchor(
            rows,
            requirement,
            Increment5DeliveryTrace.DEFERRED_TO_5D,
            253,
            anchor,
        )

    retry_anchor = (
        "issue:#254:deferred:retry-classification-bounded-backoff-"
        "health-and-circuit-controls"
    )
    deferred_5e = {
        "GRAG-051": (
            "issue:#254:deferred:conditional-challenger-requires-measured-"
            "blocker-or-owner-approved-comparison-purpose"
        ),
        "GRPROD-004": (
            "issue:#254:deferred:production-profile-rejects-fake-noop-"
            "disabled-or-omitted-graphrag"
        ),
        "GRPROD-015": (
            "issue:#254:deferred:production-configuration-build-and-"
            "readiness-validation"
        ),
        "DOPS-001": "issue:#254:deferred:versioned-operational-profile",
        "DOPS-002": (
            "issue:#254:deferred:scope-specific-timing-freshness-retry-"
            "capacity-alert-objectives"
        ),
        "DOPS-007": (
            "issue:#254:deferred:source-planned-wall-monotonic-and-"
            "authoritative-record-time-separation"
        ),
        "DOPS-030": retry_anchor,
        "DOPS-031": retry_anchor,
        "DOPS-032": retry_anchor,
        "DOPS-033": retry_anchor,
        "DOPS-034": retry_anchor,
        "DOPS-037": (
            "issue:#254:deferred:bounded-role-aware-contingency-activation-"
            "and-deactivation"
        ),
        "DOPS-040": (
            "issue:#254:deferred:queue-retention-and-explicit-closure-evidence"
        ),
        "DOPS-050": (
            "issue:#254:deferred:full-reconciliation-orphaned-ownership-"
            "ambiguous-calls-duplicate-delivery-stale-work-and-pending-handoffs"
        ),
        "DOPS-060": (
            "issue:#254:deferred:version-attributed-metrics-logs-alerts-"
            "and-incidents"
        ),
        "DOPS-067": (
            "issue:#254:deferred:least-privilege-credential-source-access-"
            "and-approved-network-destination-evidence"
        ),
        "DOPS-070": (
            "issue:#254:deferred:every-new-source-adapter-parser-profile-"
            "worker-retrieval-and-provider-version-requires-operational-"
            "admission"
        ),
        "DOPS-073": (
            "issue:#254:deferred:narrowest-safe-scope-pause-and-broadened-"
            "operational-containment"
        ),
    }
    for requirement, anchor in deferred_5e.items():
        _require_deferred_anchor(
            rows,
            requirement,
            Increment5DeliveryTrace.DEFERRED_TO_5E,
            254,
            anchor,
        )


validate_increment5_traceability()
