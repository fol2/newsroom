"""Immutable Increment 5 traceability types and closed-world delivery inventory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


_REQUIREMENT_ID = re.compile(r"^(?:GRAG|GRPROD|TRI|DEVAL|DOPS)-[0-9]{3}$")


class Increment5DecisionTrace(StrEnum):
    BOUND_BY_5A = "BOUND_BY_5A"
    INHERITED_ACCEPTED_AUTHORITY = "INHERITED_ACCEPTED_AUTHORITY"


class Increment5DeliveryTrace(StrEnum):
    DELIVERED_IN_5A = "DELIVERED_IN_5A"
    DEFERRED_TO_5B = "DEFERRED_TO_5B"
    DEFERRED_TO_5C = "DEFERRED_TO_5C"
    DEFERRED_TO_5D = "DEFERRED_TO_5D"
    DEFERRED_TO_5E = "DEFERRED_TO_5E"
    OUTSIDE_INCREMENT_5_ACTIVATION = "OUTSIDE_INCREMENT_5_ACTIVATION"
    SATISFIED_BY_PRIOR_INCREMENT = "SATISFIED_BY_PRIOR_INCREMENT"


@dataclass(frozen=True, slots=True)
class Increment5TraceabilityRow:
    requirement_id: str
    decision_anchor: str
    decision_trace: Increment5DecisionTrace
    delivery_trace: Increment5DeliveryTrace
    delivery_issue: int
    delivery_target: str
    verification_target: str

    def __post_init__(self) -> None:
        if _REQUIREMENT_ID.fullmatch(self.requirement_id) is None:
            raise ValueError("invalid requirement identifier")
        for name in ("decision_anchor", "delivery_target", "verification_target"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be canonical non-empty text")
        if not isinstance(self.decision_trace, Increment5DecisionTrace):
            raise ValueError("decision trace must be typed")
        if not isinstance(self.delivery_trace, Increment5DeliveryTrace):
            raise ValueError("delivery trace must be typed")
        if self.delivery_issue not in {143, 144, 250, 251, 252, 253, 254}:
            raise ValueError("delivery issue is outside the admitted chain")


def _ids(prefix: str, values: tuple[int, ...]) -> frozenset[str]:
    return frozenset(f"{prefix}-{value:03d}" for value in values)


GRAG_REQUIREMENTS = _ids(
    "GRAG",
    (
        30,
        31,
        32,
        33,
        34,
        35,
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
    ),
)
GRPROD_REQUIREMENTS = _ids(
    "GRPROD",
    (*range(1, 6), *range(10, 17), *range(20, 25), *range(30, 33)),
)
TRI_REQUIREMENTS = _ids("TRI", tuple(range(20, 29)))

# The readiness ladder selects DEVAL-* and DOPS-* as closed-world normative
# families. These inventories therefore contain every requirement heading in
# the two accepted specifications, not a manually curated applicability subset.
DEVAL_REQUIREMENTS = _ids(
    "DEVAL",
    (
        *range(1, 5),
        *range(10, 15),
        *range(20, 27),
        *range(30, 34),
        *range(40, 48),
        *range(50, 55),
        *range(60, 65),
        *range(70, 75),
    ),
)
DOPS_REQUIREMENTS = _ids(
    "DOPS",
    (
        *range(1, 9),
        *range(10, 17),
        *range(20, 27),
        *range(30, 38),
        *range(40, 49),
        *range(50, 56),
        *range(60, 69),
        *range(70, 77),
    ),
)

ALL_REQUIREMENTS = frozenset().union(
    GRAG_REQUIREMENTS,
    GRPROD_REQUIREMENTS,
    TRI_REQUIREMENTS,
    DEVAL_REQUIREMENTS,
    DOPS_REQUIREMENTS,
)

# 5D ends at one bounded read-only retrieval request. It owns the hybrid result
# and request-local authority semantics. It does not own upstream collection,
# downstream decisions or Candidate admission, product-profile outage behaviour,
# operational policy, health, queues, durability, later reconciliation,
# containment, or incidents.
REQUEST_RETRIEVAL_REQUIREMENTS = frozenset(
    {
        "GRAG-031",
        "GRAG-032",
        "GRAG-040",
        "GRAG-041",
        "GRAG-042",
        "GRAG-043",
        "TRI-020",
        "TRI-021",
        "TRI-023",
        "TRI-025",
        "TRI-027",
    }
)

# These obligations consume retrieval state but cannot be completed by the
# retrieval request itself. They require upstream or downstream integration or
# system-level outage policy and therefore belong to the 5E remainder.
CROSS_REQUEST_INTEGRATION_REQUIREMENTS = frozenset(
    {
        "GRAG-044",
        "GRAG-045",
        "GRPROD-024",
        "TRI-024",
        "TRI-026",
    }
)

DELIVERED_IN_5A_REQUIREMENTS = frozenset(
    {
        "GRAG-052",
        "GRAG-053",
        "GRAG-058",
        "GRPROD-032",
        "DEVAL-010",
        "DEVAL-011",
        "DEVAL-012",
        "DEVAL-051",
        "DOPS-076",
    }
)
# 5B is a partial implementation dependency. Four independent branches
# are necessary for later composition, but no selected whole requirement
# is complete before 5D applies exact-first orchestration and fusion.
DEFERRED_TO_5B_REQUIREMENTS = frozenset()
DEFERRED_TO_5C_REQUIREMENTS = frozenset(
    {
        "GRAG-033",
        "GRAG-034",
        "GRAG-035",
        "TRI-022",
    }
)
OUTSIDE_INCREMENT_5_REQUIREMENTS = frozenset({"GRPROD-022"})
INHERITED_AUTHORITY = frozenset(
    {
        "GRAG-030",
        "GRPROD-003",
        "GRPROD-005",
        "GRPROD-013",
        "GRPROD-014",
        "GRPROD-016",
        "GRPROD-020",
    }
)

# 5E is the closed-world remainder after every smaller, exact delivery boundary
# is removed. New accepted DEVAL/DOPS requirements cannot disappear silently:
# once present in the family inventory they belong to 5E unless explicitly
# assigned to another reviewed boundary.
_NON_5E_REQUIREMENTS = frozenset().union(
    DELIVERED_IN_5A_REQUIREMENTS,
    DEFERRED_TO_5B_REQUIREMENTS,
    DEFERRED_TO_5C_REQUIREMENTS,
    REQUEST_RETRIEVAL_REQUIREMENTS,
    OUTSIDE_INCREMENT_5_REQUIREMENTS,
    INHERITED_AUTHORITY,
)
DEFERRED_TO_5E_REQUIREMENTS = ALL_REQUIREMENTS.difference(_NON_5E_REQUIREMENTS)

# DOPS is the operational specification. DOPS-076 is the 5A
# admission-not-activation rule; every other accepted DOPS row is executable
# operational work owned by 5E. 5C still validates the local named-tool input
# shape, but it does not claim the complete DOPS-026 policy/egress/budget/
# authority boundary.
OPERATIONAL_DOPS = DOPS_REQUIREMENTS.difference({"DOPS-076"})

DELIVERY_GROUPS: dict[Increment5DeliveryTrace, frozenset[str]] = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: DELIVERED_IN_5A_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5B: DEFERRED_TO_5B_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5C: DEFERRED_TO_5C_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5D: REQUEST_RETRIEVAL_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5E: DEFERRED_TO_5E_REQUIREMENTS,
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: (
        OUTSIDE_INCREMENT_5_REQUIREMENTS
    ),
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: INHERITED_AUTHORITY,
}

if len(ALL_REQUIREMENTS) != 155:
    raise RuntimeError("Increment 5 accepted inventory must contain 155 requirements")
if len(DEFERRED_TO_5E_REQUIREMENTS) != 123:
    raise RuntimeError("5E closed-world remainder must contain 123 requirements")
if not CROSS_REQUEST_INTEGRATION_REQUIREMENTS.issubset(
    DEFERRED_TO_5E_REQUIREMENTS
):
    raise RuntimeError("cross-request integration requirements must belong to 5E")
if REQUEST_RETRIEVAL_REQUIREMENTS.intersection(
    CROSS_REQUEST_INTEGRATION_REQUIREMENTS
):
    raise RuntimeError("request-local and cross-request requirements overlap")
if not OPERATIONAL_DOPS.issubset(DEFERRED_TO_5E_REQUIREMENTS):
    raise RuntimeError("every operational DOPS row except DOPS-076 must belong to 5E")

PRIOR_DELIVERY_EVIDENCE: dict[str, tuple[int, str, str]] = {
    requirement: (
        144,
        "increment-4-accepted-authority",
        "main@c9e31879421083e82e2538d57087d04e9b454d34",
    )
    for requirement in INHERITED_AUTHORITY
}

ISSUE_BY_DELIVERY = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: 250,
    Increment5DeliveryTrace.DEFERRED_TO_5B: 251,
    Increment5DeliveryTrace.DEFERRED_TO_5C: 252,
    Increment5DeliveryTrace.DEFERRED_TO_5D: 253,
    Increment5DeliveryTrace.DEFERRED_TO_5E: 254,
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 250,
}
TARGET_BY_DELIVERY = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: (
        "contract-profile-plan-and-traceability"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5B: (
        "issue:#251:four-independent-retriever-implementations"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5C: (
        "issue:#252:six-named-read-only-tools"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5D: (
        "issue:#253:one-request-hybrid-composition-lineage-hydration-and-outcomes"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5E: (
        "issue:#254:closed-world-operational-admission-evaluation-security-and-recovery"
    ),
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: (
        "explicitly-not-authorized-by-increment-5"
    ),
}
VERIFY_BY_DELIVERY = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: (
        "newsroom/tests/test_increment5a_traceability.py"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5B: "issue:#251:completion-evidence",
    Increment5DeliveryTrace.DEFERRED_TO_5C: "issue:#252:completion-evidence",
    Increment5DeliveryTrace.DEFERRED_TO_5D: "issue:#253:completion-evidence",
    Increment5DeliveryTrace.DEFERRED_TO_5E: "issue:#254:completion-evidence",
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: (
        "contract:#/payload/non_effects"
    ),
}
