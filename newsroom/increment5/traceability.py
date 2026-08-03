"""Truthful requirement-to-decision and requirement-to-delivery mapping.

A 5A row says that the reviewed contract binds a requirement. It does not claim
that a deferred retriever, tool, composer, operational control, or qualification
run already exists.
"""

from __future__ import annotations

from ._traceability_anchors import ANCHOR_BY_REQUIREMENT
from ._traceability_model import (
    ALL_REQUIREMENTS,
    DEFERRED_TO_5E_REQUIREMENTS,
    DELIVERED_IN_5A_REQUIREMENTS,
    DELIVERY_GROUPS,
    DEVAL_REQUIREMENTS,
    DOPS_REQUIREMENTS,
    INHERITED_AUTHORITY,
    ISSUE_BY_DELIVERY,
    OPERATIONAL_DOPS,
    PRIOR_DELIVERY_EVIDENCE,
    REQUEST_RETRIEVAL_REQUIREMENTS,
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

    prior = DELIVERY_GROUPS[Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT]
    if frozenset(PRIOR_DELIVERY_EVIDENCE) != prior:
        raise RuntimeError("prior delivery evidence differs from prior inventory")

    expected_counts = {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 0,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 117,
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

    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5B]:
        raise RuntimeError(
            "5B branch implementation cannot claim a complete requirement"
        )
    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5D] != (
        REQUEST_RETRIEVAL_REQUIREMENTS
    ):
        raise RuntimeError("5D differs from the exact one-request retrieval boundary")
    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E] != (
        DEFERRED_TO_5E_REQUIREMENTS
    ):
        raise RuntimeError("5E differs from the closed-world remainder")
    if any(item.startswith("DOPS-") for item in REQUEST_RETRIEVAL_REQUIREMENTS):
        raise RuntimeError("5D cannot claim operational DOPS delivery")
    if any(
        item.startswith("DOPS-")
        for item in DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5C]
    ):
        raise RuntimeError("5C cannot claim the complete operational DOPS boundary")
    if not OPERATIONAL_DOPS.issubset(
        DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E]
    ):
        raise RuntimeError("operational DOPS requirements must be owned by 5E")

    expected_5e_deval = DEVAL_REQUIREMENTS.difference(
        DELIVERED_IN_5A_REQUIREMENTS
    )
    actual_5e_deval = DEVAL_REQUIREMENTS.intersection(
        DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E]
    )
    if actual_5e_deval != expected_5e_deval:
        raise RuntimeError("all non-5A DEVAL requirements must be owned by 5E")

    expected_5e_dops = DOPS_REQUIREMENTS.difference({"DOPS-076"})
    actual_5e_dops = DOPS_REQUIREMENTS.intersection(
        DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E]
    )
    if actual_5e_dops != expected_5e_dops:
        raise RuntimeError("all operational DOPS requirements must be owned by 5E")

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
        elif row.delivery_trace is Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION:
            if row.requirement_id != "GRPROD-022":
                raise RuntimeError("outside-activation row differs from v1")
        elif row.delivery_issue not in {251, 252, 253, 254}:
            raise RuntimeError("deferred row has the wrong issue")

    if any(
        "approval" in row.delivery_target.lower()
        or "github" in row.verification_target.lower()
        for row in INCREMENT_5_TRACEABILITY
    ):
        raise RuntimeError("runtime approval or GitHub admission target reintroduced")

    rows = {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}
    machine_plan = (
        "newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json"
    )
    for requirement, fragment in {
        "GRAG-054": "#/mandatory_query_families",
        "GRAG-055": "#/decision_scope",
        "GRAG-056": "#/zero_tolerance_gates",
        "DEVAL-011": "#/epoch_protocol",
        "DEVAL-046": "#/triage_error_protocol",
    }.items():
        if rows[requirement].decision_anchor != machine_plan + fragment:
            raise RuntimeError(f"qualification plan anchor differs: {requirement}")

    for requirement in prior:
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
            raise RuntimeError(f"prior evidence differs: {requirement}")

    critical_5d = {
        "GRAG-031": (
            "issue:#253:deferred:deterministic-hybrid-fusion-and-dependency-"
            "root-deduplication"
        ),
        "GRAG-042": (
            "issue:#253:deferred:source-revision-signal-lead-hypothesis-and-"
            "candidate-lineage-projection-and-hydration"
        ),
        "TRI-021": (
            "issue:#253:deferred:exact-source-formal-process-and-explicit-"
            "lineage-before-approximate-similarity"
        ),
    }
    for requirement, anchor in critical_5d.items():
        _require_deferred_anchor(
            rows,
            requirement,
            Increment5DeliveryTrace.DEFERRED_TO_5D,
            253,
            anchor,
        )

    critical_5e = {
        "GRPROD-021": (
            "issue:#254:deferred:complete-graph-native-vertical-slice-"
            "through-triage-and-candidate-admission"
        ),
        "GRPROD-002": (
            "issue:#254:deferred:no-production-canary-or-complete-"
            "live-shadow-without-graphrag"
        ),
        "GRPROD-023": (
            "issue:#254:deferred:graphrag-cannot-be-an-optional-"
            "production-plugin"
        ),
        "TRI-028": (
            "issue:#254:deferred:urgent-degraded-retrieval-requires-durable-"
            "later-reconciliation"
        ),
        "DOPS-010": "issue:#254:deferred:multidimensional-operational-health",
        "DOPS-015": (
            "issue:#254:deferred:active-obligation-path-loss-and-scoped-"
            "coverage-containment"
        ),
        "DOPS-026": (
            "issue:#254:deferred:source-and-model-content-cannot-alter-"
            "operational-policy-egress-budgets-or-authority"
        ),
        "DOPS-043": (
            "issue:#254:deferred:queue-backpressure-and-current-authority-"
            "revalidation-before-commit"
        ),
        "DOPS-046": (
            "issue:#254:deferred:atomic-or-deterministically-reconcilable-"
            "transition-delivery"
        ),
        "DOPS-048": (
            "issue:#254:deferred:dependency-specific-scheduler-network-parser-"
            "store-retrieval-model-search-and-evidence-intake-failure"
        ),
        "DOPS-050": (
            "issue:#254:deferred:full-reconciliation-orphaned-ownership-"
            "ambiguous-calls-duplicate-delivery-stale-work-and-pending-handoffs"
        ),
        "DOPS-067": (
            "issue:#254:deferred:least-privilege-credential-source-access-and-"
            "approved-network-destination-evidence"
        ),
        "DOPS-073": (
            "issue:#254:deferred:narrowest-safe-scope-pause-and-broadened-"
            "operational-containment"
        ),
    }
    for requirement, anchor in critical_5e.items():
        _require_deferred_anchor(
            rows,
            requirement,
            Increment5DeliveryTrace.DEFERRED_TO_5E,
            254,
            anchor,
        )


validate_increment5_traceability()
