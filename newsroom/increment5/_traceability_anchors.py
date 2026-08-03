"""Requirement-specific decision anchors for Increment 5."""

from __future__ import annotations

from ._traceability_model import (
    ALL_REQUIREMENTS,
    DEVAL_REQUIREMENTS,
    DOPS_REQUIREMENTS,
)


_CONTRACT = "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"
_DECISION = "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
_EVALUATION = (
    "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
)
_MACHINE_EVALUATION = (
    "newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json"
)
_OPERATIONS = "docs/operations/increment-5-production-retrieval-contract.md"
_DEVAL_SPEC = "docs/specs/editorial-automation/discovery-shadow-evaluation.md"
_DOPS_SPEC = "docs/specs/editorial-automation/discovery-reliability-and-operations.md"
_PRIOR_INCREMENT4 = (
    "main@c9e31879421083e82e2538d57087d04e9b454d34:"
    "newsroom/increment4/traceability.py"
)


_EXPLICIT_ANCHOR_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    (f"{_PRIOR_INCREMENT4}#GRAG-030", frozenset({"GRAG-030"})),
    (f"{_PRIOR_INCREMENT4}#GRPROD-003", frozenset({"GRPROD-003"})),
    (f"{_PRIOR_INCREMENT4}#GRPROD-005", frozenset({"GRPROD-005"})),
    (f"{_PRIOR_INCREMENT4}#GRPROD-013", frozenset({"GRPROD-013"})),
    (f"{_PRIOR_INCREMENT4}#GRPROD-014", frozenset({"GRPROD-014"})),
    (f"{_PRIOR_INCREMENT4}#GRPROD-016", frozenset({"GRPROD-016"})),
    (f"{_PRIOR_INCREMENT4}#GRPROD-020", frozenset({"GRPROD-020"})),
    (f"{_CONTRACT}#/payload/required_modes", frozenset({"GRPROD-001"})),
    (
        "issue:#253:deferred:exact-source-formal-process-and-explicit-"
        "lineage-before-approximate-similarity",
        frozenset({"TRI-021"}),
    ),
    (
        "issue:#254:deferred:no-production-canary-or-complete-live-shadow-"
        "without-graphrag",
        frozenset({"GRPROD-002"}),
    ),
    (
        "issue:#253:deferred:deterministic-hybrid-fusion-and-dependency-root-"
        "deduplication",
        frozenset({"GRAG-031"}),
    ),
    (
        f"{_CONTRACT}#/payload/authority_boundaries",
        frozenset(
            {
                "GRAG-032",
                "GRAG-040",
                "GRAG-041",
                "TRI-020",
                "TRI-025",
                "TRI-026",
            }
        ),
    ),
    (
        "issue:#253:deferred:source-revision-signal-lead-hypothesis-and-"
        "candidate-lineage-projection-and-hydration",
        frozenset({"GRAG-042"}),
    ),
    (f"{_CONTRACT}#/payload/named_tools", frozenset({"GRAG-033"})),
    (
        f"{_CONTRACT}#/payload/delivery_boundaries/5C",
        frozenset({"GRAG-034", "GRAG-035", "TRI-022"}),
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
            }
        ),
    ),
    (
        f"{_CONTRACT}#/payload/delivery_boundaries/5D",
        frozenset({"GRAG-045"}),
    ),
    (
        "issue:#254:deferred:complete-graph-native-vertical-slice-"
        "through-triage-and-candidate-admission",
        frozenset({"GRPROD-021"}),
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
    (
        "issue:#254:deferred:graphrag-cannot-be-an-optional-"
        "production-plugin",
        frozenset({"GRPROD-023"}),
    ),
    (f"{_DECISION}#package-neutrality", frozenset({"GRAG-053"})),
    (f"{_CONTRACT}#/payload/change_control", frozenset({"GRPROD-012"})),
    (
        "issue:#254:deferred:conditional-challenger-requires-measured-blocker-"
        "or-owner-approved-comparison-purpose",
        frozenset({"GRAG-051"}),
    ),
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
    (f"{_EVALUATION}#frozen-gates", frozenset({"DEVAL-050", "DEVAL-053"})),
    (
        f"{_CONTRACT}#/payload/non_effects",
        frozenset(
            {"GRAG-058", "GRPROD-022", "GRPROD-032", "DEVAL-003", "DOPS-076"}
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
        f"{_CONTRACT}#/payload/evaluation_plan/thresholds_frozen_before_qualification",
        frozenset({"DEVAL-051"}),
    ),
    (f"{_CONTRACT}#/payload/rights_matrix", frozenset({"DEVAL-064"})),
    (f"{_EVALUATION}#public-artifact-safety", frozenset({"DEVAL-072"})),
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
        "issue:#254:deferred:source-planned-wall-monotonic-and-authoritative-"
        "record-time-separation",
        frozenset({"DOPS-007"}),
    ),
    (
        "issue:#254:deferred:multidimensional-operational-health",
        frozenset({"DOPS-010"}),
    ),
    (
        "issue:#254:deferred:successful-observation-freshness-staleness-and-"
        "coverage-posture",
        frozenset({"DOPS-011", "DOPS-012", "DOPS-013", "DOPS-014"}),
    ),
    (
        "issue:#254:deferred:active-obligation-path-loss-and-scoped-coverage-"
        "containment",
        frozenset({"DOPS-015"}),
    ),
    (
        "issue:#254:deferred:comparator-non-substitution-for-anchor-health",
        frozenset({"DOPS-016"}),
    ),
    (
        "issue:#254:deferred:source-and-model-content-cannot-alter-operational-"
        "policy-egress-budgets-or-authority",
        frozenset({"DOPS-026"}),
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
        "issue:#254:deferred:queue-backpressure-and-current-authority-"
        "revalidation-before-commit",
        frozenset({"DOPS-043", "DOPS-044"}),
    ),
    (
        "issue:#254:deferred:capacity-qualification-evidence",
        frozenset({"DOPS-045"}),
    ),
    (
        "issue:#254:deferred:atomic-or-deterministically-reconcilable-"
        "transition-delivery",
        frozenset({"DOPS-046"}),
    ),
    (
        "issue:#254:deferred:authoritative-store-or-audit-failure-blocks-effects",
        frozenset({"DOPS-047"}),
    ),
    (
        "issue:#254:deferred:dependency-specific-scheduler-network-parser-store-"
        "retrieval-model-search-and-evidence-intake-failure",
        frozenset({"DOPS-048"}),
    ),
    (
        "issue:#254:deferred:full-reconciliation-orphaned-ownership-ambiguous-"
        "calls-duplicate-delivery-stale-work-and-pending-handoffs",
        frozenset({"DOPS-050"}),
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
        "issue:#254:deferred:least-privilege-credential-source-access-and-"
        "approved-network-destination-evidence",
        frozenset({"DOPS-067"}),
    ),
    (
        "issue:#254:deferred:every-new-source-adapter-parser-profile-worker-"
        "retrieval-and-provider-version-requires-operational-admission",
        frozenset({"DOPS-070"}),
    ),
    (
        "issue:#254:deferred:tested-rollback-and-scoped-disable-evidence",
        frozenset({"DOPS-072"}),
    ),
    (
        "issue:#254:deferred:narrowest-safe-scope-pause-and-broadened-"
        "operational-containment",
        frozenset({"DOPS-073"}),
    ),
    (
        "issue:#254:deferred:rights-terms-pricing-access-and-credential-change-review",
        frozenset({"DOPS-074"}),
    ),
    (
        "issue:#254:deferred:operational-admission-evidence",
        frozenset({"DOPS-075"}),
    ),
    (
        "issue:#254:deferred:urgent-degraded-retrieval-requires-durable-later-"
        "reconciliation",
        frozenset({"TRI-028"}),
    ),
)


def _explicit_requirements() -> frozenset[str]:
    result: set[str] = set()
    for _, requirements in _EXPLICIT_ANCHOR_GROUPS:
        overlap = result.intersection(requirements)
        if overlap:
            raise RuntimeError(
                f"requirements have competing explicit anchors: {sorted(overlap)}"
            )
        result.update(requirements)
    return frozenset(result)


_EXPLICIT_REQUIREMENTS = _explicit_requirements()
_SPEC_OWNED_REQUIREMENTS = (
    DEVAL_REQUIREMENTS | DOPS_REQUIREMENTS
).difference(_EXPLICIT_REQUIREMENTS)
_NORMATIVE_SPEC_ANCHOR_GROUPS: tuple[tuple[str, frozenset[str]], ...] = tuple(
    (
        f"{_DEVAL_SPEC if requirement.startswith('DEVAL-') else _DOPS_SPEC}"
        f"#{requirement}",
        frozenset({requirement}),
    )
    for requirement in sorted(_SPEC_OWNED_REQUIREMENTS)
)
_ANCHOR_GROUPS = (*_EXPLICIT_ANCHOR_GROUPS, *_NORMATIVE_SPEC_ANCHOR_GROUPS)


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
