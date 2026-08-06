"""Requirement-specific decision anchors for the amended Increment 5 map.

Delivery issues identify the owner of complete implementation. Decision anchors
remain normative accepted specifications, exact 5A contract/plan material, or
exact accepted Increment 4 evidence; an issue never substitutes for authority.
"""

from __future__ import annotations

from ._traceability_model import (
    ALL_REQUIREMENTS,
    DEVAL_REQUIREMENTS,
    DOPS_REQUIREMENTS,
    INHERITED_AUTHORITY,
)


_CONTRACT = "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"
_DECISION = "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
_EVALUATION = (
    "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
)
_MACHINE_EVALUATION = (
    "newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json"
)
_GRAG_SPEC = (
    "docs/specs/editorial-automation/"
    "governed-graphrag-and-knowledge-projection.md"
)
_GRPROD_SPEC = (
    "docs/specs/editorial-automation/graphrag-native-production-deployment.md"
)
_TRI_SPEC = (
    "docs/specs/editorial-automation/discovery-triage-and-event-grouping.md"
)
_DEVAL_SPEC = (
    "docs/specs/editorial-automation/discovery-shadow-evaluation.md"
)
_DOPS_SPEC = (
    "docs/specs/editorial-automation/discovery-reliability-and-operations.md"
)
_PRIOR_INCREMENT4 = (
    "main@c9e31879421083e82e2538d57087d04e9b454d34:"
    "newsroom/increment4/traceability.py"
)

_SPEC_BY_PREFIX = {
    "GRAG": _GRAG_SPEC,
    "GRPROD": _GRPROD_SPEC,
    "TRI": _TRI_SPEC,
    "DEVAL": _DEVAL_SPEC,
    "DOPS": _DOPS_SPEC,
}


_EXACT_ANCHOR_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    (f"{_CONTRACT}#/payload/required_modes", frozenset({"GRPROD-001"})),
    (
        f"{_CONTRACT}#/payload/authority_boundaries",
        frozenset({"GRAG-032", "GRAG-040", "GRAG-041", "TRI-020", "TRI-025"}),
    ),
    (f"{_CONTRACT}#/payload/named_tools", frozenset({"GRAG-033"})),
    (
        f"{_CONTRACT}#/payload/delivery_boundaries/5C",
        frozenset({"GRAG-034"}),
    ),
    (
        f"{_CONTRACT}#/payload/delivery_boundaries/5E",
        frozenset(
            {
                "GRAG-046",
                "GRAG-057",
                "GRPROD-011",
                "GRPROD-030",
                "GRPROD-031",
            }
        ),
    ),
    (
        f"{_CONTRACT}#/payload/components",
        frozenset({"GRAG-050", "GRAG-052", "GRPROD-010"}),
    ),
    (f"{_DECISION}#package-neutrality", frozenset({"GRAG-053"})),
    (f"{_CONTRACT}#/payload/change_control", frozenset({"GRPROD-012"})),
    (
        f"{_MACHINE_EVALUATION}#/mandatory_query_families",
        frozenset({"GRAG-054"}),
    ),
    (
        f"{_CONTRACT}#/payload/evaluation_plan/required_slices",
        frozenset({"DEVAL-043"}),
    ),
    (f"{_MACHINE_EVALUATION}#/decision_scope", frozenset({"GRAG-055"})),
    (
        f"{_MACHINE_EVALUATION}#/zero_tolerance_gates",
        frozenset({"GRAG-056"}),
    ),
    (
        f"{_EVALUATION}#frozen-gates",
        frozenset({"DEVAL-050", "DEVAL-053"}),
    ),
    (
        f"{_CONTRACT}#/payload/non_effects",
        frozenset(
            {
                "GRAG-058",
                "GRPROD-022",
                "GRPROD-032",
                "DEVAL-003",
                "DOPS-076",
            }
        ),
    ),
    (f"{_CONTRACT}#/payload/evaluation_plan", frozenset({"DEVAL-010"})),
    (
        f"{_MACHINE_EVALUATION}#/epoch_protocol",
        frozenset({"DEVAL-011"}),
    ),
    (
        f"{_EVALUATION}#evaluation-evidence-semantics",
        frozenset(
            {
                "DEVAL-012",
                "DEVAL-013",
                "DEVAL-041",
                "DEVAL-042",
                "DEVAL-044",
                "DEVAL-052",
            }
        ),
    ),
    (
        f"{_EVALUATION}#decision-output",
        frozenset(
            {
                "DEVAL-014",
                "DEVAL-040",
                "DEVAL-045",
                "DEVAL-047",
                "DEVAL-054",
                "DEVAL-070",
                "DEVAL-071",
                "DEVAL-073",
                "DEVAL-074",
            }
        ),
    ),
    (
        f"{_MACHINE_EVALUATION}#/triage_error_protocol",
        frozenset({"DEVAL-046"}),
    ),
    (
        f"{_CONTRACT}#/payload/evaluation_plan/"
        "thresholds_frozen_before_qualification",
        frozenset({"DEVAL-051"}),
    ),
    (f"{_CONTRACT}#/payload/rights_matrix", frozenset({"DEVAL-064"})),
)


def _build_exact_anchor_map() -> dict[str, str]:
    result = {
        requirement: f"{_PRIOR_INCREMENT4}#{requirement}"
        for requirement in INHERITED_AUTHORITY
    }
    for anchor, requirements in _EXACT_ANCHOR_GROUPS:
        overlap = set(result).intersection(requirements)
        if overlap:
            raise RuntimeError(
                f"requirements have competing exact anchors: {sorted(overlap)}"
            )
        result.update({requirement: anchor for requirement in requirements})
    return result


_EXACT_ANCHOR_BY_REQUIREMENT = _build_exact_anchor_map()


def _anchor(requirement_id: str) -> str:
    exact = _EXACT_ANCHOR_BY_REQUIREMENT.get(requirement_id)
    if exact is not None:
        return exact
    prefix = requirement_id.split("-", 1)[0]
    return f"{_SPEC_BY_PREFIX[prefix]}#{requirement_id}"


ANCHOR_BY_REQUIREMENT = {
    requirement_id: _anchor(requirement_id)
    for requirement_id in sorted(ALL_REQUIREMENTS)
}

if frozenset(ANCHOR_BY_REQUIREMENT) != ALL_REQUIREMENTS:
    raise RuntimeError("decision-anchor inventory differs from accepted requirements")
if any(anchor.startswith("issue:") for anchor in ANCHOR_BY_REQUIREMENT.values()):
    raise RuntimeError("delivery issue cannot substitute for decision authority")
if frozenset(
    requirement
    for requirement in DEVAL_REQUIREMENTS | DOPS_REQUIREMENTS
    if requirement not in _EXACT_ANCHOR_BY_REQUIREMENT
).difference(ANCHOR_BY_REQUIREMENT):
    raise RuntimeError("normative evaluation/operations anchors are incomplete")
