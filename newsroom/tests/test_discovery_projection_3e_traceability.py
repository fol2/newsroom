from __future__ import annotations

from pathlib import Path

from newsroom.projection.discovery_traceability import (
    INCREMENT_3E_DEFERRED,
    INCREMENT_3E_EXCLUSIONS,
    INCREMENT_3E_TRACEABILITY,
)


_ROOT = Path(__file__).resolve().parents[2]
_OPERATIONS = _ROOT / "docs/operations/increment-3e-discovery-lineage-health.md"
_DESIGN = _ROOT / "docs/research/2026-07-29-increment-3e-design-record.md"


def test_increment_3e_traceability_covers_every_review_unit() -> None:
    expected = {
        "3E-01-STRUCTURAL-LINEAGE/COV-020-COV-025/FLOW-030-FLOW-040/DREC-030-DREC-035",
        "3E-02-ORDERED-CHECKPOINT-GAP-DEADLETTER/GRAG-024-GRAG-025",
        "3E-03-REBUILD-RECONCILE-ACTIVATE/GRAG-026-GRAG-028",
        "3E-04-ATTRIBUTABLE-HEALTH/DOUT-001-DOUT-012/DOPS-001-DOPS-012",
        "3E-05-COVERAGE-PATH-HONESTY/COV-040-COV-045/SRC-010",
        "3E-06-BOUNDED-AUTHENTICATED-READS/GRAG-035/FLOW-001-FLOW-006",
        "3E-07-ACTUAL-NEO4J-EVIDENCE/GRAG-042-GRAG-045",
        "3E-08-BOUNDARY-ROLLBACK/ADR-0001-ADR-0002-ADR-0004-ADR-0005",
    }
    assert set(INCREMENT_3E_TRACEABILITY) == expected
    assert all(len(references) >= 3 for references in INCREMENT_3E_TRACEABILITY.values())
    flattened = {
        reference
        for references in INCREMENT_3E_TRACEABILITY.values()
        for reference in references
    }
    assert {
        ".github.workflows.projection-b2-neo4j",
        "docs.operations.increment-3e-discovery-lineage-health",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.authority._projection_store",
        "newsroom.projection.discovery_lineage",
        "newsroom.projection.health",
        "newsroom.projection.neo4j.discovery_lineage_reads",
        "newsroom.tests.test_discovery_projection_3e_observation_models",
        "newsroom.tests.test_integrated_c1_workflow_contract",
        "newsroom.tests.test_projection_b3_neo4j_service",
        "scripts.sdlc.workflow_lane",
    } <= flattened


def test_increment_3e_exclusions_and_deferrals_do_not_overclaim() -> None:
    assert "MODEL_GRAPHITI_EMBEDDING_OR_SEARCH_EXECUTION" in INCREMENT_3E_EXCLUSIONS
    assert "ARBITRARY_CYPHER_DRIVER_OR_MUTATION_SURFACE" in INCREMENT_3E_EXCLUSIONS
    assert "GRAPHITI_MODEL_PROMPT_EMBEDDING_AND_COST_AUTHORITY" in INCREMENT_3E_DEFERRED
    assert "TRIAGE_AND_CANDIDATE_AUTHORITY" in INCREMENT_3E_DEFERRED
    assert INCREMENT_3E_EXCLUSIONS.isdisjoint(INCREMENT_3E_DEFERRED)


def test_increment_3e_operations_preserve_fail_closed_recovery() -> None:
    text = _OPERATIONS.read_text(encoding="utf-8")
    required = (
        "SQLite ledger records",
        "Neo4j is a disposable, rebuildable structural projection",
        "Never perform graph-to-ledger recovery",
        "server-computed reconciliation",
        "A failed, stale, gapped, dead-lettered, wrong-contract or graph-tampered generation must not become ACTIVE",
        "Quiet publication history is not stale by itself",
        "A healthy Comparator or source count cannot repair an unavailable sole Anchor",
        "no Neo4j driver, arbitrary Cypher",
        "must not resurrect material excluded",
        "Increment 4 remains blocked",
    )
    for statement in required:
        assert statement in text


def test_increment_3e_design_and_operations_preserve_explicit_exclusions() -> None:
    combined = _DESIGN.read_text(encoding="utf-8") + _OPERATIONS.read_text(encoding="utf-8")
    for phrase in (
        "named live source",
        "source credential",
        "model, Graphiti, embedding or search execution",
        "Event Hypothesis, Candidate or Evidence Handoff",
        "publication, spending, production activation or public effect",
    ):
        assert phrase in combined
