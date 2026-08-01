"""Truthful requirement-to-delivery map for Increment 5.

The table separates the digest-bound 5A decision from later implementation,
actual-service qualification, and activation. A bound row is never evidence
that a deferred retriever, tool, hydration path, or qualification run exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


_REQUIREMENT_ID = re.compile(r"^(?:GRAG|GRPROD|TRI|DEVAL|DOPS)-[0-9]{3}$")
_DECISION_PACKET = (
    "newsroom/increment5/data/"
    "increment5a_production_retrieval_decision_v1.json"
)
_CONTRACT_TEST = "newsroom/tests/test_increment5a_contracts.py"
_TRACE_TEST = "newsroom/tests/test_increment5a_traceability.py"


class Increment5DecisionTrace(StrEnum):
    BOUND_BY_5A = "BOUND_BY_5A"
    BLOCKED_PENDING_OWNER_APPROVAL = "BLOCKED_PENDING_OWNER_APPROVAL"
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
    implementation_symbol: str
    verification_node: str
    decision_trace: Increment5DecisionTrace
    delivery_trace: Increment5DeliveryTrace
    delivery_issue: int

    def __post_init__(self) -> None:
        if _REQUIREMENT_ID.fullmatch(self.requirement_id) is None:
            raise ValueError("invalid requirement identifier")
        for field_name in (
            "decision_anchor",
            "implementation_symbol",
            "verification_node",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be non-empty canonical text")
        if not isinstance(self.decision_trace, Increment5DecisionTrace):
            raise ValueError("decision trace must be typed")
        if not isinstance(self.delivery_trace, Increment5DeliveryTrace):
            raise ValueError("delivery trace must be typed")
        if (
            isinstance(self.delivery_issue, bool)
            or not isinstance(self.delivery_issue, int)
            or self.delivery_issue not in {144, 250, 251, 252, 253, 254}
        ):
            raise ValueError("delivery issue is not an admitted Increment 5 boundary")


def _ids(prefix: str, values: tuple[int, ...]) -> frozenset[str]:
    return frozenset(f"{prefix}-{value:03d}" for value in values)


_ALL_REQUIREMENTS = frozenset().union(
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
    _ids(
        "GRPROD",
        (*range(1, 6), *range(10, 17), *range(20, 25), *range(30, 33)),
    ),
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

_DELIVERY_GROUPS: dict[Increment5DeliveryTrace, frozenset[str]] = {
    Increment5DeliveryTrace.DEFERRED_TO_5B: frozenset(
        {"GRAG-031", "TRI-021"}
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5C: frozenset(
        {
            "GRAG-033",
            "GRAG-034",
            "GRAG-035",
            "TRI-022",
            "DOPS-026",
            "DOPS-060",
            "DOPS-067",
        }
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
            "DOPS-075",
        }
    ),
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
            "DOPS-074",
            "DOPS-076",
        }
    ),
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: frozenset(
        {"GRPROD-022"}
    ),
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: frozenset(
        {"GRAG-030", "GRAG-042", "GRPROD-005", "DOPS-007"}
    ),
}

_PENDING_OWNER_APPROVAL = frozenset(
    {
        "GRAG-058",
        "GRPROD-022",
        "GRPROD-032",
        "DEVAL-010",
        "DEVAL-051",
        "DEVAL-073",
        "DOPS-001",
        "DOPS-002",
        "DOPS-076",
    }
)
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
_SYMBOL_BY_DELIVERY = {
    Increment5DeliveryTrace.DELIVERED_IN_5A: (
        "newsroom.increment5.decision:load_increment5a_decision_packet"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5B: (
        "newsroom.retrieval:RetrievalRuntime"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5C: (
        "newsroom.retrieval.tools:NamedRetrievalToolRegistry"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5D: (
        "newsroom.retrieval:RetrievalContext"
    ),
    Increment5DeliveryTrace.DEFERRED_TO_5E: (
        "newsroom.increment5.qualification:Increment5QualificationReport"
    ),
    Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: (
        "newsroom.increment5.profiles:validate_profile_manifest"
    ),
    Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: (
        "newsroom.increment4:INCREMENT4_ADMITTED_CONTRACT_REGISTRY"
    ),
}


def _delivery_for(requirement_id: str) -> Increment5DeliveryTrace:
    matches = [
        delivery
        for delivery, ids in _DELIVERY_GROUPS.items()
        if requirement_id in ids
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"requirement has ambiguous Increment 5 delivery: {requirement_id}"
        )
    return matches[0]


def _decision_for(requirement_id: str) -> Increment5DecisionTrace:
    if requirement_id in _PENDING_OWNER_APPROVAL:
        return Increment5DecisionTrace.BLOCKED_PENDING_OWNER_APPROVAL
    if requirement_id in _INHERITED_AUTHORITY:
        return Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY
    return Increment5DecisionTrace.BOUND_BY_5A


_DOPS_ANCHOR_BY_REQUIREMENT: dict[str, str] = {
    "DOPS-001": _DECISION_PACKET + "#/payload/components",
    "DOPS-002": _DECISION_PACKET + "#/payload/budgets",
    "DOPS-007": _DECISION_PACKET + "#/payload/authority_boundaries",
    "DOPS-010": _DECISION_PACKET + "#/payload/components",
    "DOPS-011": _DECISION_PACKET + "#/payload/components",
    "DOPS-012": _DECISION_PACKET + "#/payload/components",
    "DOPS-013": _DECISION_PACKET + "#/payload/components",
    "DOPS-014": _DECISION_PACKET + "#/payload/components",
    "DOPS-015": _DECISION_PACKET + "#/payload/components",
    "DOPS-016": _DECISION_PACKET + "#/payload/components",
    "DOPS-026": _DECISION_PACKET + "#/payload/pr_boundaries/5C",
    "DOPS-030": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-031": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-032": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-033": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-034": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-035": _DECISION_PACKET + "#/payload/pr_boundaries/5E",
    "DOPS-036": _DECISION_PACKET + "#/payload/pr_boundaries/5E",
    "DOPS-037": _DECISION_PACKET + "#/payload/components",
    "DOPS-040": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-043": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-044": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-045": "issue:#254:deferred:capacity-qualification-evidence",
    "DOPS-046": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-047": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-048": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-050": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-052": _DECISION_PACKET + "#/payload/rollback",
    "DOPS-054": "issue:#254:deferred:backup-restore-rebuild-evidence",
    "DOPS-060": _DECISION_PACKET + "#/payload/pr_boundaries/5C",
    "DOPS-064": "issue:#254:deferred:owner-escalation-runbook-evidence",
    "DOPS-067": _DECISION_PACKET + "#/payload/components",
    "DOPS-070": _DECISION_PACKET + "#/payload/components",
    "DOPS-072": _DECISION_PACKET + "#/payload/rollback",
    "DOPS-073": _DECISION_PACKET + "#/payload/pr_boundaries/5D",
    "DOPS-074": _DECISION_PACKET + "#/payload/rights_matrix",
    "DOPS-075": "issue:#254:deferred:operational-admission-evidence",
    "DOPS-076": _DECISION_PACKET + "#/payload/runtime_authority",
}
_DOPS_REQUIREMENTS = frozenset(
    item for item in _ALL_REQUIREMENTS if item.startswith("DOPS-")
)
if frozenset(_DOPS_ANCHOR_BY_REQUIREMENT) != _DOPS_REQUIREMENTS:
    raise RuntimeError("Increment 5 DOPS anchors are incomplete")


def _anchor_for(requirement_id: str) -> str:
    if requirement_id.startswith("DOPS-"):
        return _DOPS_ANCHOR_BY_REQUIREMENT[requirement_id]
    if requirement_id.startswith("DEVAL-"):
        suffix = "evaluation_plan"
    elif requirement_id.startswith("TRI-"):
        suffix = "components"
    elif requirement_id.startswith("GRPROD-"):
        suffix = "pr_boundaries"
    else:
        suffix = "required_modes"
    return f"{_DECISION_PACKET}#/payload/{suffix}"

def _row(requirement_id: str) -> Increment5TraceabilityRow:
    delivery = _delivery_for(requirement_id)
    return Increment5TraceabilityRow(
        requirement_id=requirement_id,
        decision_anchor=_anchor_for(requirement_id),
        implementation_symbol=_SYMBOL_BY_DELIVERY[delivery],
        verification_node=(
            _CONTRACT_TEST
            if delivery is Increment5DeliveryTrace.DELIVERED_IN_5A
            else _TRACE_TEST
        ),
        decision_trace=_decision_for(requirement_id),
        delivery_trace=delivery,
        delivery_issue=_ISSUE_BY_DELIVERY[delivery],
    )


if frozenset().union(*_DELIVERY_GROUPS.values()) != _ALL_REQUIREMENTS:
    raise RuntimeError(
        "Increment 5 delivery groups do not cover exact requirements"
    )
if sum(len(ids) for ids in _DELIVERY_GROUPS.values()) != len(_ALL_REQUIREMENTS):
    raise RuntimeError("Increment 5 delivery groups overlap")

INCREMENT5_TRACEABILITY = tuple(
    _row(item) for item in sorted(_ALL_REQUIREMENTS)
)
INCREMENT5_TRACEABILITY_BY_REQUIREMENT = {
    row.requirement_id: row for row in INCREMENT5_TRACEABILITY
}
