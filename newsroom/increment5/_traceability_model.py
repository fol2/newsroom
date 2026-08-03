"""Immutable Increment 5 traceability types and delivery inventory."""

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


ALL_REQUIREMENTS = frozenset().union(
    _ids(
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
    ),
    _ids("GRPROD", (*range(1, 6), *range(10, 17), *range(20, 25), *range(30, 33))),
    _ids("TRI", tuple(range(20, 29))),
    _ids(
        "DEVAL",
        (3, *range(10, 15), *range(40, 48), *range(50, 55), 64, *range(70, 75)),
    ),
    _ids(
        "DOPS",
        (
            1,
            2,
            7,
            *range(10, 17),
            26,
            *range(30, 38),
            40,
            *range(43, 49),
            50,
            52,
            54,
            60,
            64,
            67,
            70,
            *range(72, 77),
        ),
    ),
)

# 5D ends at one bounded retrieval request. It owns the hybrid result and its
# request-local authority semantics, not operational health, queues, durable
# transition delivery, later reconciliation, system containment, or incidents.
REQUEST_RETRIEVAL_REQUIREMENTS = frozenset(
    {
        "GRAG-031",
        "GRAG-032",
        "GRAG-040",
        "GRAG-041",
        "GRAG-042",
        "GRAG-043",
        "GRAG-044",
        "GRAG-045",
        "GRPROD-021",
        "GRPROD-024",
        "TRI-020",
        "TRI-023",
        "TRI-024",
        "TRI-025",
        "TRI-026",
        "TRI-027",
    }
)

# DOPS is the operational specification. DOPS-026 is delivered with the 5C
# untrusted-input boundary and DOPS-076 is the 5A admission-not-activation rule;
# every other accepted DOPS row is executable operational work owned by 5E.
OPERATIONAL_DOPS = frozenset(
    requirement
    for requirement in ALL_REQUIREMENTS
    if requirement.startswith("DOPS-")
).difference({"DOPS-026", "DOPS-076"})

_DEFERRED_TO_5E_NON_OPERATIONAL = frozenset(
    {
        "GRAG-046",
        "GRAG-050",
        "GRAG-051",
        "GRAG-054",
        "GRAG-055",
        "GRAG-056",
        "GRAG-057",
        "GRPROD-001",
        "GRPROD-004",
        "GRPROD-010",
        "GRPROD-011",
        "GRPROD-012",
        "GRPROD-015",
        "GRPROD-030",
        "GRPROD-031",
        "DEVAL-003",
        "DEVAL-013",
        "DEVAL-014",
        "DEVAL-040",
        "DEVAL-041",
        "DEVAL-042",
        "DEVAL-043",
        "DEVAL-044",
        "DEVAL-045",
        "DEVAL-046",
        "DEVAL-047",
        "DEVAL-050",
        "DEVAL-052",
        "DEVAL-053",
        "DEVAL-054",
        "DEVAL-064",
        "DEVAL-070",
        "DEVAL-071",
        "DEVAL-073",
        "DEVAL-074",
        "TRI-028",
    }
)

DELIVERY_GROUPS: dict[Increment5DeliveryTrace, frozenset[str]] = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: frozenset(
        {
            "GRAG-052",
            "GRAG-053",
            "GRAG-058",
            "GRPROD-002",
            "GRPROD-023",
            "GRPROD-032",
            "DEVAL-010",
            "DEVAL-011",
            "DEVAL-012",
            "DEVAL-051",
            "DEVAL-072",
            "DOPS-076",
        }
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5B: frozenset({"TRI-021"}),
    Increment5DeliveryTrace.DEFERRED_TO_5C: frozenset(
        {
            "GRAG-033",
            "GRAG-034",
            "GRAG-035",
            "TRI-022",
            "DOPS-026",
        }
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5D: REQUEST_RETRIEVAL_REQUIREMENTS,
    Increment5DeliveryTrace.DEFERRED_TO_5E: (
        _DEFERRED_TO_5E_NON_OPERATIONAL | OPERATIONAL_DOPS
    ),
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: frozenset(
        {"GRPROD-022"}
    ),
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: frozenset(
        {
            "GRAG-030",
            "GRPROD-003",
            "GRPROD-005",
            "GRPROD-013",
            "GRPROD-014",
            "GRPROD-016",
            "GRPROD-020",
        }
    ),
}

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
        "issue:#254:operational-admission-qualification-security-and-recovery"
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
