"""Truthful requirement-to-decision and requirement-to-delivery mapping.

A 5A row says that the contract binds a requirement.  It does not claim that a
retriever, tool, hydration path, or qualification run already exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


_REQUIREMENT_ID = re.compile(r"^(?:GRAG|GRPROD|TRI|DEVAL|DOPS)-[0-9]{3}$")
_CONTRACT = (
    "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"
)


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
    contract_anchor: str
    decision_trace: Increment5DecisionTrace
    delivery_trace: Increment5DeliveryTrace
    delivery_issue: int
    delivery_target: str
    verification_target: str

    def __post_init__(self) -> None:
        if _REQUIREMENT_ID.fullmatch(self.requirement_id) is None:
            raise ValueError("invalid requirement identifier")
        for name in ("contract_anchor", "delivery_target", "verification_target"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be canonical non-empty text")
        if not isinstance(self.decision_trace, Increment5DecisionTrace):
            raise ValueError("decision trace must be typed")
        if not isinstance(self.delivery_trace, Increment5DeliveryTrace):
            raise ValueError("delivery trace must be typed")
        if self.delivery_issue not in {144, 250, 251, 252, 253, 254}:
            raise ValueError("delivery issue is outside the admitted chain")


def _ids(prefix: str, values: tuple[int, ...]) -> frozenset[str]:
    return frozenset(f"{prefix}-{value:03d}" for value in values)


ALL_REQUIREMENTS = frozenset().union(
    _ids(
        "GRAG",
        (30, 31, 32, 33, 34, 35, 40, 41, 42, 43, 44, 45, 46, 50, 51, 52, 53, 54, 55, 56, 57, 58),
    ),
    _ids("GRPROD", (*range(1, 6), *range(10, 17), *range(20, 25), *range(30, 33))),
    _ids("TRI", tuple(range(20, 29))),
    _ids("DEVAL", (3, *range(10, 15), *range(40, 48), *range(50, 55), 64, *range(70, 75))),
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

DELIVERY_GROUPS: dict[Increment5DeliveryTrace, frozenset[str]] = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: frozenset(
        {
            "GRAG-051",
            "GRAG-052",
            "GRAG-053",
            "GRAG-058",
            "GRPROD-002",
            "GRPROD-003",
            "GRPROD-004",
            "GRPROD-013",
            "GRPROD-014",
            "GRPROD-015",
            "GRPROD-020",
            "GRPROD-023",
            "GRPROD-032",
            "DEVAL-010",
            "DEVAL-011",
            "DEVAL-012",
            "DEVAL-051",
            "DEVAL-072",
            "DOPS-001",
            "DOPS-002",
            "DOPS-037",
            "DOPS-070",
            "DOPS-076",
        }
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5B: frozenset({"GRAG-031", "TRI-021"}),
    Increment5DeliveryTrace.DEFERRED_TO_5C: frozenset(
        {"GRAG-033", "GRAG-034", "GRAG-035", "TRI-022", "DOPS-026", "DOPS-060", "DOPS-067"}
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5D: frozenset(
        {
            "GRAG-032",
            "GRAG-040",
            "GRAG-041",
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
            "TRI-028",
            "DOPS-010",
            "DOPS-011",
            "DOPS-012",
            "DOPS-013",
            "DOPS-014",
            "DOPS-015",
            "DOPS-016",
            "DOPS-030",
            "DOPS-031",
            "DOPS-032",
            "DOPS-033",
            "DOPS-034",
            "DOPS-040",
            "DOPS-043",
            "DOPS-044",
            "DOPS-046",
            "DOPS-047",
            "DOPS-048",
            "DOPS-050",
            "DOPS-073",
        }
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5E: frozenset(
        {
            "GRAG-046",
            "GRAG-050",
            "GRAG-054",
            "GRAG-055",
            "GRAG-056",
            "GRAG-057",
            "GRPROD-001",
            "GRPROD-010",
            "GRPROD-011",
            "GRPROD-012",
            "GRPROD-016",
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
            "DOPS-035",
            "DOPS-036",
            "DOPS-045",
            "DOPS-052",
            "DOPS-054",
            "DOPS-064",
            "DOPS-072",
            "DOPS-074",
            "DOPS-075",
        }
    ),
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: frozenset({"GRPROD-022"}),
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: frozenset(
        {"GRAG-030", "GRAG-042", "GRPROD-005", "DOPS-007"}
    ),
}

_INHERITED_AUTHORITY = frozenset(
    {"GRAG-030", "GRAG-042", "GRPROD-005", "GRPROD-016", "DOPS-007"}
)
_ISSUE_BY_DELIVERY = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: 250,
    Increment5DeliveryTrace.DEFERRED_TO_5B: 251,
    Increment5DeliveryTrace.DEFERRED_TO_5C: 252,
    Increment5DeliveryTrace.DEFERRED_TO_5D: 253,
    Increment5DeliveryTrace.DEFERRED_TO_5E: 254,
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 250,
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 144,
}
_TARGET_BY_DELIVERY = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: "contract-and-profile-validation",
    Increment5DeliveryTrace.DEFERRED_TO_5B: "issue:#251:four-retriever-implementations",
    Increment5DeliveryTrace.DEFERRED_TO_5C: "issue:#252:six-named-read-only-tools",
    Increment5DeliveryTrace.DEFERRED_TO_5D: "issue:#253:hydration-freshness-and-degradation",
    Increment5DeliveryTrace.DEFERRED_TO_5E: "issue:#254:qualification-security-purge-and-recovery",
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: "explicitly-not-authorized-by-increment-5",
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: "increment-4-accepted-authority",
}
_VERIFY_BY_DELIVERY = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: "newsroom/tests/test_increment5a_contract.py",
    Increment5DeliveryTrace.DEFERRED_TO_5B: "issue:#251:completion-evidence",
    Increment5DeliveryTrace.DEFERRED_TO_5C: "issue:#252:completion-evidence",
    Increment5DeliveryTrace.DEFERRED_TO_5D: "issue:#253:completion-evidence",
    Increment5DeliveryTrace.DEFERRED_TO_5E: "issue:#254:completion-evidence",
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: "contract:#/non_effects",
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: "main@c9e31879421083e82e2538d57087d04e9b454d34",
}


def _delivery_for(requirement_id: str) -> Increment5DeliveryTrace:
    matches = [
        delivery
        for delivery, requirements in DELIVERY_GROUPS.items()
        if requirement_id in requirements
    ]
    if len(matches) != 1:
        raise RuntimeError(f"ambiguous delivery for {requirement_id}")
    return matches[0]


def _anchor_for(requirement_id: str) -> str:
    if requirement_id.startswith("DEVAL-"):
        section = "evaluation_plan"
    elif requirement_id.startswith("TRI-"):
        section = "named_tools"
    elif requirement_id.startswith("DOPS-"):
        if requirement_id in {"DOPS-002"}:
            section = "budgets"
        elif requirement_id in {"DOPS-052", "DOPS-054", "DOPS-072"}:
            section = "rollback"
        elif requirement_id in {"DOPS-076"}:
            section = "effect"
        else:
            section = "delivery_boundaries"
    elif requirement_id in {"GRAG-030", "GRAG-032", "GRAG-042"}:
        section = "authority_boundaries"
    elif requirement_id.startswith("GRAG-"):
        section = "components"
    elif requirement_id in {"GRPROD-022"}:
        section = "non_effects"
    else:
        section = "components"
    return f"{_CONTRACT}#/payload/{section}"


def _rows() -> tuple[Increment5TraceabilityRow, ...]:
    rows: list[Increment5TraceabilityRow] = []
    for requirement_id in sorted(ALL_REQUIREMENTS):
        delivery = _delivery_for(requirement_id)
        rows.append(
            Increment5TraceabilityRow(
                requirement_id=requirement_id,
                contract_anchor=_anchor_for(requirement_id),
                decision_trace=(
                    Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY
                    if requirement_id in _INHERITED_AUTHORITY
                    else Increment5DecisionTrace.BOUND_BY_5A
                ),
                delivery_trace=delivery,
                delivery_issue=_ISSUE_BY_DELIVERY[delivery],
                delivery_target=_TARGET_BY_DELIVERY[delivery],
                verification_target=_VERIFY_BY_DELIVERY[delivery],
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
        if seen.intersection(requirements):
            raise RuntimeError(f"delivery groups overlap at {delivery.value}")
        seen.update(requirements)
    if seen != set(ALL_REQUIREMENTS):
        raise RuntimeError("delivery groups do not cover the accepted inventory")
    expected_counts = {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 23,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 2,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 7,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 35,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 42,
        Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 1,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 4,
    }
    actual_counts = {
        delivery: sum(row.delivery_trace is delivery for row in INCREMENT_5_TRACEABILITY)
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


validate_increment5_traceability()
