"""Immutable Increment 5 traceability types and amended delivery inventory."""

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
    DEFERRED_TO_INCREMENT_6 = "DEFERRED_TO_INCREMENT_6"
    DEFERRED_TO_INCREMENT_8 = "DEFERRED_TO_INCREMENT_8"
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
        if self.delivery_issue not in {
            143,
            144,
            146,
            148,
            250,
            251,
            252,
            253,
            254,
        }:
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

# The readiness ladder selected the complete accepted DEVAL and DOPS families.
# Replanning changes the delivery owner, never the normative inventory.
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

# 5B supplies four independently attributable retriever branches. Whole selected
# requirements are credited only at composition or a later integrated boundary.
DEFERRED_TO_5B_REQUIREMENTS = frozenset()

DEFERRED_TO_5C_REQUIREMENTS = frozenset({"GRAG-033", "GRAG-034"})

# 5D ends at one bounded read-only request. It owns exact-first composition,
# hydration, inspectable receipts and truthful request outcomes. Event
# Hypothesis/Candidate effects and later Handoff reconciliation are not local to
# that request.
REQUEST_RETRIEVAL_REQUIREMENTS = frozenset(
    {
        "GRAG-031",
        "GRAG-032",
        "GRAG-035",
        "GRAG-040",
        "GRAG-041",
        "GRAG-043",
        "TRI-020",
        "TRI-021",
        "TRI-022",
        "TRI-023",
        "TRI-025",
        "TRI-027",
    }
)

# Increment 5E is deliberately small and retrieval-specific: actual-service
# implementation identity, mandatory-mode/configuration enforcement, bounded
# challenger policy, corpus/ablation and provenance/temporal qualification.
DEFERRED_TO_5E_REQUIREMENTS = frozenset(
    {
        "GRAG-050",
        "GRAG-051",
        "GRAG-054",
        "GRAG-055",
        "GRAG-056",
        "GRPROD-001",
        "GRPROD-010",
        "GRPROD-015",
        "GRPROD-023",
    }
)
RETRIEVAL_QUALIFICATION_REQUIREMENTS = DEFERRED_TO_5E_REQUIREMENTS

# Cross-request triage and Candidate effects are owned by Increment 6.
DEFERRED_TO_INCREMENT_6_REQUIREMENTS = frozenset(
    {
        "GRAG-042",
        "GRAG-044",
        "GRPROD-021",
        "TRI-024",
        "TRI-026",
        "TRI-028",
    }
)
CROSS_REQUEST_INTEGRATION_REQUIREMENTS = (
    DEFERRED_TO_INCREMENT_6_REQUIREMENTS
)

# Full evaluation, operations, production-equivalent shadow and operational
# admission are restored to Increment 8. Increment 5 may produce seams or
# supporting retrieval evidence, but cannot claim these complete requirements.
_INCREMENT_8_GRAPH_AND_PRODUCT = frozenset(
    {
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
)
DEFERRED_TO_INCREMENT_8_REQUIREMENTS = frozenset().union(
    DEVAL_REQUIREMENTS.difference(DELIVERED_IN_5A_REQUIREMENTS),
    DOPS_REQUIREMENTS.difference(DELIVERED_IN_5A_REQUIREMENTS),
    _INCREMENT_8_GRAPH_AND_PRODUCT,
)

# DOPS-076 is the 5A admission-is-not-activation rule. Every other DOPS row is
# complete operational work deferred to Increment 8.
OPERATIONAL_DOPS = DOPS_REQUIREMENTS.difference({"DOPS-076"})

# The previous "outside Increment 5 activation" bucket is retained as a typed
# compatibility category, but ownership is now explicit: GRPROD-022 belongs to
# Increment 8 rather than an ownerless remainder.
OUTSIDE_INCREMENT_5_REQUIREMENTS = frozenset()

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

DELIVERY_GROUPS: dict[Increment5DeliveryTrace, frozenset[str]] = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: DELIVERED_IN_5A_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5B: DEFERRED_TO_5B_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5C: DEFERRED_TO_5C_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5D: REQUEST_RETRIEVAL_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5E: DEFERRED_TO_5E_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6: (
        DEFERRED_TO_INCREMENT_6_REQUIREMENTS
    ),
    Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8: (
        DEFERRED_TO_INCREMENT_8_REQUIREMENTS
    ),
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: (
        OUTSIDE_INCREMENT_5_REQUIREMENTS
    ),
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: INHERITED_AUTHORITY,
}

_EXPECTED_COUNTS = {
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

if len(ALL_REQUIREMENTS) != 155:
    raise RuntimeError("Increment 5 accepted inventory must contain 155 requirements")
if {delivery: len(rows) for delivery, rows in DELIVERY_GROUPS.items()} != (
    _EXPECTED_COUNTS
):
    raise RuntimeError("amended delivery counts differ from the accepted map")
_seen: set[str] = set()
for _delivery, _requirements in DELIVERY_GROUPS.items():
    if _seen.intersection(_requirements):
        raise RuntimeError(f"delivery groups overlap at {_delivery.value}")
    _seen.update(_requirements)
if _seen != set(ALL_REQUIREMENTS):
    raise RuntimeError("amended delivery groups do not cover the accepted inventory")
if OPERATIONAL_DOPS != DOPS_REQUIREMENTS.intersection(
    DEFERRED_TO_INCREMENT_8_REQUIREMENTS
):
    raise RuntimeError("all operational DOPS requirements must belong to Increment 8")

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
    Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6: 146,
    Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8: 148,
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 145,
}
TARGET_BY_DELIVERY = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: (
        "contract-profile-plan-and-traceability"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5B: (
        "issue:#251:four-independent-retriever-implementations"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5C: (
        "issue:#252:bounded-named-read-only-tools"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5D: (
        "issue:#253:one-request-composition-hydration-and-truthful-outcomes"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5E: (
        "issue:#254:retrieval-specific-qualification-security-rights-and-recovery"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6: (
        "issue:#146:cross-request-triage-candidate-and-handoff-effects"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8: (
        "issue:#148:full-evaluation-operations-recovery-security-and-admission"
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
    Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6: (
        "issue:#146:completion-evidence"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8: (
        "issue:#148:completion-evidence"
    ),
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: (
        "contract:#/payload/non_effects"
    ),
}
