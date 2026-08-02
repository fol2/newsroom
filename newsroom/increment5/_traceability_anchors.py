"""Requirement-specific decision anchors for Increment 5."""

from __future__ import annotations

from ._traceability_model import ALL_REQUIREMENTS


_CONTRACT = "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"
_EVALUATION = (
    "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
)
_OPERATIONS = "docs/operations/increment-5-production-retrieval-contract.md"
_PRIOR_INCREMENT4 = (
    "main@c9e31879421083e82e2538d57087d04e9b454d34:"
    "newsroom/increment4/traceability.py"
)

# An anchor group is an explicit semantic claim. Group construction fails if a
# requirement is omitted or appears under two competing anchors.
_ANCHOR_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        f"{_PRIOR_INCREMENT4}#GRAG-030",
        frozenset({"GRAG-030"}),
    ),
    (
        f"{_PRIOR_INCREMENT4}#GRAG-042",
        frozenset({"GRAG-042"}),
    ),
    (
        f"{_PRIOR_INCREMENT4}#GRPROD-005",
        frozenset({"GRPROD-005"}),
    ),
    (
        f"{_PRIOR_INCREMENT4}#GRPROD-016",
        frozenset({"GRPROD-016"}),
    ),
    (
        f"{_PRIOR_INCREMENT4}#DOPS-007",
        frozenset({"DOPS-007"}),
    ),
    (
        f"{_CONTRACT}#/payload/required_modes",
        frozenset({"GRAG-031", "GRPROD-001", "GRPROD-002", "TRI-021"}),
    ),
    (
        f"{_CONTRACT}#/payload/authority_boundaries",
        frozenset(
            {
                "GRAG-032",
                "GRAG-040",
                "GRAG-041",
                "GRPROD-013",
                "TRI-020",
                "TRI-025",
                "TRI-026",
            }
        ),
    ),
    (
        f"{_CONTRACT}#/payload/named_tools",
        frozenset({"GRAG-033"}),
    ),
    (
        f"{_CONTRACT}#/payload/delivery_boundaries/5C",
        frozenset(
            {
                "GRAG-034",
                "GRAG-035",
                "DOPS-026",
                "DOPS-067",
                "TRI-022",
            }
        ),
    ),
    (
        f"{_OPERATIONS}#outcomes",
        frozenset(
            {
                "GRAG-043",
                "GRAG-044",
                "GRPROD-024",
                "TRI-023",
                "TRI-024",
                "TRI-027",
                "TRI-028",
            }
        ),
    ),
    (
        f"{_CONTRACT}#/payload/delivery_boundaries/5D",
        frozenset(
            {
                "GRAG-045",
                "GRPROD-021",
                "DOPS-010",
                "DOPS-011",
                "DOPS-012",
                "DOPS-013",
                "DOPS-014",
                "DOPS-015",
                "DOPS-016",
                "DOPS-043",
                "DOPS-044",
                "DOPS-046",
                "DOPS-047",
                "DOPS-048",
                "DOPS-050",
                "DOPS-073",
            }
        ),
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
        frozenset(
            {
                "GRAG-050",
                "GRAG-052",
                "GRPROD-003",
                "GRPROD-010",
                "GRPROD-014",
                "GRPROD-020",
                "GRPROD-023",
            }
        ),
    ),
    (
        f"{_CONTRACT}#/payload/change_control",
        frozenset({"GRAG-051", "GRAG-053", "GRPROD-012", "DOPS-070"}),
    ),
    (
        f"{_CONTRACT}#/payload/evaluation_plan/required_slices",
        frozenset({"GRAG-054", "DEVAL-043"}),
    ),
    (
        f"{_CONTRACT}#/payload/evaluation_plan/ablations",
        frozenset({"GRAG-055"}),
    ),
    (
        f"{_EVALUATION}#frozen-gates",
        frozenset({"GRAG-056", "DEVAL-050", "DEVAL-053"}),
    ),
    (
        f"{_CONTRACT}#/payload/non_effects",
        frozenset(
            {"GRAG-058", "GRPROD-022", "GRPROD-032", "DEVAL-003", "DOPS-076"}
        ),
    ),
    (
        f"{_CONTRACT}#/payload/evaluation_plan",
        frozenset({"DEVAL-010"}),
    ),
    (
        f"{_EVALUATION}#evaluation-evidence-semantics",
        frozenset(
            {
                "DEVAL-011",
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
        f"{_EVALUATION}#dataset-protocol",
        frozenset({"DEVAL-046"}),
    ),
    (
        f"{_CONTRACT}#/payload/evaluation_plan/thresholds_frozen_before_qualification",
        frozenset({"DEVAL-051"}),
    ),
    (
        f"{_CONTRACT}#/payload/rights_matrix",
        frozenset({"DEVAL-064"}),
    ),
    (
        f"{_EVALUATION}#public-artifact-safety",
        frozenset({"DEVAL-072"}),
    ),
    (
        "issue:#254:deferred:production-profile-rejects-fake-noop-disabled-"
        "or-omitted-graphrag",
        frozenset({"GRPROD-004"}),
    ),
    (
        "issue:#254:deferred:production-configuration-build-and-readiness-validation",
        frozenset({"GRPROD-015"}),
    ),
    (
        "issue:#254:deferred:versioned-operational-profile",
        frozenset({"DOPS-001"}),
    ),
    (
        "issue:#254:deferred:scope-specific-timing-freshness-retry-"
        "capacity-alert-objectives",
        frozenset({"DOPS-002"}),
    ),
    (
        "issue:#254:deferred:retry-classification-bounded-backoff-"
        "health-and-circuit-controls",
        frozenset({"DOPS-030", "DOPS-031", "DOPS-032", "DOPS-033", "DOPS-034"}),
    ),
    (
        "issue:#254:deferred:bounded-role-aware-contingency-activation-"
        "and-deactivation",
        frozenset({"DOPS-037"}),
    ),
    (
        "issue:#254:deferred:queue-retention-and-explicit-closure-evidence",
        frozenset({"DOPS-040"}),
    ),
    (
        "issue:#254:deferred:quarantine-and-authorized-release-evidence",
        frozenset({"DOPS-035", "DOPS-036"}),
    ),
    (
        "issue:#254:deferred:capacity-qualification-evidence",
        frozenset({"DOPS-045"}),
    ),
    (
        "issue:#254:deferred:versioned-replay-evidence",
        frozenset({"DOPS-052"}),
    ),
    (
        "issue:#254:deferred:backup-restore-and-rebuild-evidence",
        frozenset({"DOPS-054"}),
    ),
    (
        "issue:#254:deferred:version-attributed-metrics-logs-alerts-and-incidents",
        frozenset({"DOPS-060"}),
    ),
    (
        "issue:#254:deferred:owner-escalation-and-versioned-runbook-evidence",
        frozenset({"DOPS-064"}),
    ),
    (
        "issue:#254:deferred:tested-rollback-and-scoped-disable-evidence",
        frozenset({"DOPS-072"}),
    ),
    (
        "issue:#254:deferred:rights-terms-pricing-access-and-credential-change-review",
        frozenset({"DOPS-074"}),
    ),
    (
        "issue:#254:deferred:operational-admission-evidence",
        frozenset({"DOPS-075"}),
    ),
)


def _build_anchor_map() -> dict[str, str]:
    result: dict[str, str] = {}
    for anchor, requirements in _ANCHOR_GROUPS:
        overlap = set(result).intersection(requirements)
        if overlap:
            raise RuntimeError(
                f"requirements have competing decision anchors: {sorted(overlap)}"
            )
        result.update({requirement: anchor for requirement in requirements})
    if frozenset(result) != ALL_REQUIREMENTS:
        missing = sorted(ALL_REQUIREMENTS.difference(result))
        extra = sorted(set(result).difference(ALL_REQUIREMENTS))
        raise RuntimeError(
            "decision anchors differ from accepted inventory: "
            f"missing={missing}, extra={extra}"
        )
    return result


ANCHOR_BY_REQUIREMENT = _build_anchor_map()
