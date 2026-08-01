from __future__ import annotations

from collections import Counter
from pathlib import Path

from newsroom.increment5.traceability import (
    INCREMENT5_TRACEABILITY,
    INCREMENT5_TRACEABILITY_BY_REQUIREMENT,
    Increment5DecisionTrace,
    Increment5DeliveryTrace,
)


_EXPECTED_GRAG = {
    "GRAG-030",
    "GRAG-031",
    "GRAG-032",
    "GRAG-033",
    "GRAG-034",
    "GRAG-035",
    "GRAG-040",
    "GRAG-041",
    "GRAG-042",
    "GRAG-043",
    "GRAG-044",
    "GRAG-045",
    "GRAG-046",
    "GRAG-050",
    "GRAG-051",
    "GRAG-052",
    "GRAG-053",
    "GRAG-054",
    "GRAG-055",
    "GRAG-056",
    "GRAG-057",
    "GRAG-058",
}

_EXPECTED_GRPROD = {
    *(f"GRPROD-{value:03d}" for value in range(1, 6)),
    *(f"GRPROD-{value:03d}" for value in range(10, 17)),
    *(f"GRPROD-{value:03d}" for value in range(20, 25)),
    *(f"GRPROD-{value:03d}" for value in range(30, 33)),
}

_EXPECTED_TRI = {f"TRI-{value:03d}" for value in range(20, 29)}

_EXPECTED_DEVAL = {
    "DEVAL-003",
    *(f"DEVAL-{value:03d}" for value in range(10, 15)),
    *(f"DEVAL-{value:03d}" for value in range(40, 48)),
    *(f"DEVAL-{value:03d}" for value in range(50, 55)),
    "DEVAL-064",
    *(f"DEVAL-{value:03d}" for value in range(70, 75)),
}

_EXPECTED_DOPS = {
    "DOPS-001",
    "DOPS-002",
    "DOPS-007",
    *(f"DOPS-{value:03d}" for value in range(10, 17)),
    "DOPS-026",
    *(f"DOPS-{value:03d}" for value in range(30, 38)),
    "DOPS-040",
    *(f"DOPS-{value:03d}" for value in range(43, 49)),
    "DOPS-050",
    "DOPS-052",
    "DOPS-054",
    "DOPS-060",
    "DOPS-064",
    "DOPS-067",
    "DOPS-070",
    *(f"DOPS-{value:03d}" for value in range(72, 77)),
}


def _ids(prefix: str) -> set[str]:
    return {
        row.requirement_id
        for row in INCREMENT5_TRACEABILITY
        if row.requirement_id.startswith(prefix)
    }


def test_all_applicable_requirement_families_are_explicitly_mapped() -> None:
    assert _ids("GRAG-") == _EXPECTED_GRAG
    assert _ids("GRPROD-") == _EXPECTED_GRPROD
    assert _ids("TRI-") == _EXPECTED_TRI
    assert _ids("DEVAL-") == _EXPECTED_DEVAL
    assert _ids("DOPS-") == _EXPECTED_DOPS
    assert len(INCREMENT5_TRACEABILITY) == 114


def test_traceability_is_unique_typed_and_uses_admitted_issue_boundaries() -> None:
    assert len(INCREMENT5_TRACEABILITY_BY_REQUIREMENT) == len(
        INCREMENT5_TRACEABILITY
    )
    for row in INCREMENT5_TRACEABILITY:
        assert isinstance(row.decision_trace, Increment5DecisionTrace)
        assert isinstance(row.delivery_trace, Increment5DeliveryTrace)
        assert row.delivery_issue in {144, 250, 251, 252, 253, 254}
        assert (
            row.decision_anchor.startswith("newsroom/increment5/data/")
            or row.decision_anchor.startswith("issue:#254:deferred:")
        )
        assert row.verification_node.startswith("newsroom/tests/")


def test_deferred_delivery_rows_do_not_claim_increment5a_runtime_completion() -> None:
    deferred = {
        Increment5DeliveryTrace.DEFERRED_TO_5B: 251,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 252,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 253,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 254,
    }
    for row in INCREMENT5_TRACEABILITY:
        expected_issue = deferred.get(row.delivery_trace)
        if expected_issue is not None:
            assert row.delivery_issue == expected_issue
            assert row.delivery_trace is not Increment5DeliveryTrace.DELIVERED_IN_5A


def test_owner_approval_and_activation_boundaries_remain_visible() -> None:
    pending = {
        row.requirement_id
        for row in INCREMENT5_TRACEABILITY
        if row.decision_trace
        is Increment5DecisionTrace.BLOCKED_PENDING_OWNER_APPROVAL
    }
    assert pending == {
        "DEVAL-010",
        "DEVAL-051",
        "DEVAL-073",
        "DOPS-001",
        "DOPS-002",
        "DOPS-076",
        "GRAG-058",
        "GRPROD-022",
        "GRPROD-032",
    }
    assert (
        INCREMENT5_TRACEABILITY_BY_REQUIREMENT["GRPROD-022"].delivery_trace
        is Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION
    )


def test_completed_run_decision_ownership_and_rollback_remain_in_5e() -> None:
    for requirement_id in (
        "DEVAL-073",
        "DOPS-064",
        "DOPS-072",
        "DOPS-074",
    ):
        row = INCREMENT5_TRACEABILITY_BY_REQUIREMENT[requirement_id]
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254


def test_no_graph_free_or_fake_production_trace_is_present() -> None:
    searchable = "\n".join(
        (
            row.decision_anchor
            + " "
            + row.implementation_symbol
            + " "
            + row.decision_trace.value
            + " "
            + row.delivery_trace.value
        )
        for row in INCREMENT5_TRACEABILITY
    ).lower()
    assert "graph-free-production" not in searchable
    assert "fake-production" not in searchable
    assert "optional-plugin" not in searchable


def test_traceability_delivery_distribution_remains_truthful() -> None:
    counts = Counter(row.delivery_trace for row in INCREMENT5_TRACEABILITY)
    assert counts[Increment5DeliveryTrace.DELIVERED_IN_5A] == 23
    assert counts[Increment5DeliveryTrace.DEFERRED_TO_5B] == 2
    assert counts[Increment5DeliveryTrace.DEFERRED_TO_5C] == 7
    assert counts[Increment5DeliveryTrace.DEFERRED_TO_5D] == 35
    assert counts[Increment5DeliveryTrace.DEFERRED_TO_5E] == 42
    assert counts[Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT] == 4
    assert counts[Increment5DeliveryTrace.OUTSIDE_INCREMENT_5_ACTIVATION] == 1


def test_dops_decision_anchors_are_individual_and_truthful() -> None:
    anchors = {
        requirement_id: INCREMENT5_TRACEABILITY_BY_REQUIREMENT[
            requirement_id
        ].decision_anchor
        for requirement_id in _EXPECTED_DOPS
    }
    packet = (
        "newsroom/increment5/data/"
        "increment5a_production_retrieval_decision_v1.json"
    )
    expected = {
        "DOPS-001": packet + "#/payload/components",
        "DOPS-002": packet + "#/payload/budgets",
        "DOPS-007": packet + "#/payload/authority_boundaries",
        "DOPS-010": packet + "#/payload/components",
        "DOPS-011": packet + "#/payload/components",
        "DOPS-012": packet + "#/payload/components",
        "DOPS-013": packet + "#/payload/components",
        "DOPS-014": packet + "#/payload/components",
        "DOPS-015": packet + "#/payload/components",
        "DOPS-016": packet + "#/payload/components",
        "DOPS-026": packet + "#/payload/pr_boundaries/5C",
        "DOPS-030": packet + "#/payload/pr_boundaries/5D",
        "DOPS-031": packet + "#/payload/pr_boundaries/5D",
        "DOPS-032": packet + "#/payload/pr_boundaries/5D",
        "DOPS-033": packet + "#/payload/pr_boundaries/5D",
        "DOPS-034": packet + "#/payload/pr_boundaries/5D",
        "DOPS-035": packet + "#/payload/pr_boundaries/5E",
        "DOPS-036": packet + "#/payload/pr_boundaries/5E",
        "DOPS-037": packet + "#/payload/components",
        "DOPS-040": packet + "#/payload/pr_boundaries/5D",
        "DOPS-043": packet + "#/payload/pr_boundaries/5D",
        "DOPS-044": packet + "#/payload/pr_boundaries/5D",
        "DOPS-045": (
            "issue:#254:deferred:capacity-qualification-evidence"
        ),
        "DOPS-046": packet + "#/payload/pr_boundaries/5D",
        "DOPS-047": packet + "#/payload/pr_boundaries/5D",
        "DOPS-048": packet + "#/payload/pr_boundaries/5D",
        "DOPS-050": packet + "#/payload/pr_boundaries/5D",
        "DOPS-052": packet + "#/payload/rollback",
        "DOPS-054": (
            "issue:#254:deferred:backup-restore-rebuild-evidence"
        ),
        "DOPS-060": packet + "#/payload/pr_boundaries/5C",
        "DOPS-064": (
            "issue:#254:deferred:owner-escalation-runbook-evidence"
        ),
        "DOPS-067": packet + "#/payload/components",
        "DOPS-070": packet + "#/payload/components",
        "DOPS-072": packet + "#/payload/rollback",
        "DOPS-073": packet + "#/payload/pr_boundaries/5D",

"DOPS-074": (
    "issue:#254:deferred:rights-terms-pricing-access-"
    "credential-change-review-evidence"
),
        "DOPS-075": (
            "issue:#254:deferred:operational-admission-evidence"
        ),
        "DOPS-076": packet + "#/payload/runtime_authority",
    }
    assert anchors == expected
    assert {
        requirement_id
        for requirement_id, anchor in anchors.items()
        if anchor.endswith("#/payload/budgets")
    } == {"DOPS-002"}
    assert anchors["DOPS-052"].endswith("#/payload/rollback")
    assert anchors["DOPS-072"].endswith("#/payload/rollback")


def test_increment5a_documents_are_present() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = {
        root
        / "docs"
        / "decisions"
        / "2026-08-01-increment-5a-owner-approval-attestation.md",
        root
        / "docs"
        / "decisions"
        / "2026-08-01-increment-5a-production-retrieval-contract-proposal.md",
        root
        / "docs"
        / "evaluation"
        / "2026-08-01-increment-5-retrieval-evaluation-plan-v1.md",
        root
        / "docs"
        / "operations"
        / "increment-5-production-retrieval-contract.md",
        root
        / "docs"
        / "traceability"
        / "increment-5-production-retrieval.md",
    }
    missing = sorted(str(path) for path in expected if not path.is_file())
    assert not missing
