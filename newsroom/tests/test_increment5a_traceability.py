from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from newsroom.increment5.traceability import (
    ALL_REQUIREMENTS,
    DEFERRED_TO_5E_REQUIREMENTS,
    DELIVERY_GROUPS,
    DEVAL_REQUIREMENTS,
    DOPS_REQUIREMENTS,
    INCREMENT_5_TRACEABILITY,
    OPERATIONAL_DOPS,
    REQUEST_RETRIEVAL_REQUIREMENTS,
    Increment5DecisionTrace,
    Increment5DeliveryTrace,
    validate_increment5_traceability,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEVAL_SPEC = _REPOSITORY_ROOT / (
    "docs/specs/editorial-automation/discovery-shadow-evaluation.md"
)
_DOPS_SPEC = _REPOSITORY_ROOT / (
    "docs/specs/editorial-automation/discovery-reliability-and-operations.md"
)


def _rows() -> dict[str, object]:
    return {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}


def _requirements_from_spec(path: Path, prefix: str) -> frozenset[str]:
    text = path.read_text(encoding="utf-8")
    return frozenset(
        re.findall(rf"^\*\*({prefix}-[0-9]{{3}})\s+—", text, flags=re.MULTILINE)
    )


def test_traceability_is_complete_unique_disjoint_and_self_validating() -> None:
    validate_increment5_traceability()
    identifiers = [row.requirement_id for row in INCREMENT_5_TRACEABILITY]
    assert len(identifiers) == len(set(identifiers)) == 155
    assert frozenset(identifiers) == ALL_REQUIREMENTS

    seen: set[str] = set()
    for requirements in DELIVERY_GROUPS.values():
        assert not seen.intersection(requirements)
        seen.update(requirements)
    assert seen == set(ALL_REQUIREMENTS)


def test_deval_and_dops_are_closed_world_specification_inventories() -> None:
    assert _requirements_from_spec(_DEVAL_SPEC, "DEVAL") == DEVAL_REQUIREMENTS
    assert _requirements_from_spec(_DOPS_SPEC, "DOPS") == DOPS_REQUIREMENTS
    assert len(DEVAL_REQUIREMENTS) == 43
    assert len(DOPS_REQUIREMENTS) == 61


def test_delivery_distribution_matches_the_dependency_boundary() -> None:
    assert Counter(row.delivery_trace for row in INCREMENT_5_TRACEABILITY) == {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 116,
        Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION: 1,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 7,
    }
    assert DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E] == (
        DEFERRED_TO_5E_REQUIREMENTS
    )


def test_5d_is_exactly_one_request_retrieval_semantics() -> None:
    assert DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5D] == (
        REQUEST_RETRIEVAL_REQUIREMENTS
    )
    assert REQUEST_RETRIEVAL_REQUIREMENTS == {
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
    assert not any(item.startswith("DOPS-") for item in REQUEST_RETRIEVAL_REQUIREMENTS)


def test_all_operational_dops_except_admission_nonactivation_have_one_owner_in_5e() -> None:
    rows = _rows()
    assert OPERATIONAL_DOPS == DOPS_REQUIREMENTS.difference({"DOPS-076"})
    assert all(
        rows[item].delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        and rows[item].delivery_issue == 254
        for item in OPERATIONAL_DOPS
    )
    assert not any(
        item.startswith("DOPS-")
        for item in DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5C]
    )
    assert rows["DOPS-076"].delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A


def test_omitted_label_review_and_operational_evidence_rows_are_now_owned_by_5e() -> None:
    rows = _rows()
    omitted_deval = {
        "DEVAL-001",
        "DEVAL-002",
        "DEVAL-004",
        *{f"DEVAL-{value:03d}" for value in range(20, 27)},
        *{f"DEVAL-{value:03d}" for value in range(30, 34)},
        *{f"DEVAL-{value:03d}" for value in range(60, 64)},
    }
    omitted_dops = {
        *{f"DOPS-{value:03d}" for value in range(3, 7)},
        "DOPS-008",
        *{f"DOPS-{value:03d}" for value in range(20, 26)},
        "DOPS-041",
        "DOPS-042",
        "DOPS-051",
        "DOPS-053",
        "DOPS-055",
        "DOPS-061",
        "DOPS-062",
        "DOPS-063",
        "DOPS-065",
        "DOPS-066",
        "DOPS-068",
        "DOPS-071",
    }
    assert len(omitted_deval) == 18
    assert len(omitted_dops) == 23

    for requirement in omitted_deval:
        row = rows[requirement]
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254
        assert row.decision_anchor == (
            "docs/specs/editorial-automation/discovery-shadow-evaluation.md"
            f"#{requirement}"
        )

    for requirement in omitted_dops:
        row = rows[requirement]
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254
        assert row.decision_anchor == (
            "docs/specs/editorial-automation/discovery-reliability-and-operations.md"
            f"#{requirement}"
        )


def test_decision_map_has_no_runtime_approval_or_admission_state() -> None:
    assert {row.decision_trace for row in INCREMENT_5_TRACEABILITY} == {
        Increment5DecisionTrace.BOUND_BY_5A,
        Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY,
    }
    assert all("approval" not in row.delivery_target.lower() for row in INCREMENT_5_TRACEABILITY)
    assert all("github" not in row.verification_target.lower() for row in INCREMENT_5_TRACEABILITY)


def test_prior_delivery_points_to_existing_increment4_evidence() -> None:
    rows = _rows()
    expected = DELIVERY_GROUPS[Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT]
    assert expected == {
        "GRAG-030",
        "GRPROD-003",
        "GRPROD-005",
        "GRPROD-013",
        "GRPROD-014",
        "GRPROD-016",
        "GRPROD-020",
    }
    for requirement in expected:
        row = rows[requirement]
        assert row.decision_trace is Increment5DecisionTrace.INHERITED_ACCEPTED_AUTHORITY
        assert row.delivery_issue == 144
        assert row.decision_anchor == (
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            f"newsroom/increment4/traceability.py#{requirement}"
        )
        _, location = row.decision_anchor.split(":", 1)
        path_text, fragment = location.split("#", 1)
        assert fragment in (_REPOSITORY_ROOT / path_text).read_text(encoding="utf-8")


def test_epoch_and_six_class_protocols_use_exact_machine_anchors() -> None:
    rows = _rows()
    plan = "newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json"
    assert rows["DEVAL-011"].decision_anchor == plan + "#/epoch_protocol"
    assert rows["DEVAL-011"].delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A
    assert rows["DEVAL-046"].decision_anchor == plan + "#/triage_error_protocol"
    assert rows["DEVAL-046"].delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E


def test_request_composition_and_lineage_are_owned_by_5d() -> None:
    rows = _rows()
    assert rows["GRAG-031"].decision_anchor == (
        "issue:#253:deferred:deterministic-hybrid-fusion-and-dependency-root-"
        "deduplication"
    )
    assert rows["GRAG-042"].decision_anchor == (
        "issue:#253:deferred:source-revision-signal-lead-hypothesis-and-"
        "candidate-lineage-projection-and-hydration"
    )
    assert all(
        rows[item].delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5D
        for item in ("GRAG-031", "GRAG-042")
    )


def test_full_untrusted_input_boundary_belongs_to_5e() -> None:
    row = _rows()["DOPS-026"]
    assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
    assert row.delivery_issue == 254
    assert row.decision_anchor == (
        "issue:#254:deferred:source-and-model-content-cannot-alter-operational-"
        "policy-egress-budgets-or-authority"
    )


def test_later_reconciliation_health_queues_and_failures_belong_to_5e() -> None:
    rows = _rows()
    expected = {
        "TRI-028": "urgent-degraded-retrieval-requires-durable-later-reconciliation",
        "DOPS-010": "multidimensional-operational-health",
        "DOPS-015": "active-obligation-path-loss-and-scoped-coverage-containment",
        "DOPS-043": "queue-backpressure-and-current-authority-revalidation-before-commit",
        "DOPS-046": "atomic-or-deterministically-reconcilable-transition-delivery",
        "DOPS-048": (
            "dependency-specific-scheduler-network-parser-store-retrieval-model-"
            "search-and-evidence-intake-failure"
        ),
        "DOPS-050": (
            "full-reconciliation-orphaned-ownership-ambiguous-calls-duplicate-"
            "delivery-stale-work-and-pending-handoffs"
        ),
        "DOPS-073": "narrowest-safe-scope-pause-and-broadened-operational-containment",
    }
    for requirement, suffix in expected.items():
        row = rows[requirement]
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254
        assert row.decision_anchor == f"issue:#254:deferred:{suffix}"




def test_production_graphrag_enforcement_is_owned_by_5e() -> None:
    rows = _rows()
    expected = {
        "GRPROD-002": (
            "issue:#254:deferred:no-production-canary-or-complete-live-shadow-"
            "without-graphrag"
        ),
        "GRPROD-023": (
            "issue:#254:deferred:graphrag-cannot-be-an-optional-production-"
            "plugin"
        ),
    }
    for requirement, anchor in expected.items():
        row = rows[requirement]
        assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254
        assert row.decision_anchor == anchor


def test_every_requirement_has_one_explicit_anchor() -> None:
    anchors = [row.decision_anchor for row in INCREMENT_5_TRACEABILITY]
    assert len(anchors) == 155
    assert all(anchor and anchor == anchor.strip() for anchor in anchors)
    assert all("prefix-default" not in anchor for anchor in anchors)
