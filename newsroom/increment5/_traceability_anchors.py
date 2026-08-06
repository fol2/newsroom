"""Requirement-specific decision anchors for the amended Increment 5 map."""

from __future__ import annotations

from ._traceability_model import ALL_REQUIREMENTS, INHERITED_AUTHORITY


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

_FIXED_ANCHORS = {
    "GRAG-052": f"{_CONTRACT}#/payload/components",
    "GRAG-053": f"{_DECISION}#package-neutrality",
    "GRAG-058": f"{_CONTRACT}#/payload/non_effects",
    "GRPROD-032": f"{_CONTRACT}#/payload/non_effects",
    "DEVAL-010": f"{_CONTRACT}#/payload/evaluation_plan",
    "DEVAL-011": f"{_MACHINE_EVALUATION}#/epoch_protocol",
    "DEVAL-012": f"{_EVALUATION}#evaluation-evidence-semantics",
    "DEVAL-051": (
        f"{_CONTRACT}#/payload/evaluation_plan/"
        "thresholds_frozen_before_qualification"
    ),
    "DOPS-076": f"{_CONTRACT}#/payload/non_effects",
}


def _anchor(requirement_id: str) -> str:
    if requirement_id in INHERITED_AUTHORITY:
        return f"{_PRIOR_INCREMENT4}#{requirement_id}"
    if requirement_id in _FIXED_ANCHORS:
        return _FIXED_ANCHORS[requirement_id]
    prefix = requirement_id.split("-", 1)[0]
    return f"{_SPEC_BY_PREFIX[prefix]}#{requirement_id}"


ANCHOR_BY_REQUIREMENT = {
    requirement_id: _anchor(requirement_id)
    for requirement_id in sorted(ALL_REQUIREMENTS)
}

if frozenset(ANCHOR_BY_REQUIREMENT) != ALL_REQUIREMENTS:
    raise RuntimeError("decision-anchor inventory differs from accepted requirements")
if len(set(ANCHOR_BY_REQUIREMENT.values())) < len(INHERITED_AUTHORITY):
    raise RuntimeError("prior delivery anchors are not independently attributable")
