from __future__ import annotations

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPOSITORY_ROOT / ".github/workflows/projection-b2-neo4j.yml"


def test_permanent_neo4j_gate_executes_the_exact_increment_1c_proof() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    required = (
        "name: Projection B2/B3/C1 Neo4j",
        "NEWSROOM_NEO4J_SERVICE_REQUIRED: \"1\"",
        "newsroom/tests/test_integrated_c1_neo4j_service.py",
        "test_actual_service_integrated_foundation_replay_recovery_and_tombstone",
        "required C1 actual-service proof did not execute exactly once",
        "C1 actual-service proof was skipped",
        "C1 actual-service proof failed",
        "projection-b2-b3-c1-neo4j-evidence",
        "Generate masked disposable credentials and start Neo4j",
    )
    for statement in required:
        assert statement in text


def test_permanent_increment_1c_gate_preserves_non_activating_boundaries() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    prohibited = (
        "graphiti",
        "openai",
        "embedding",
        "publish.article",
        "shadow activation",
        "production activation",
    )
    lowered = text.casefold()
    for statement in prohibited:
        assert statement not in lowered


def test_permanent_neo4j_gate_executes_every_b3_and_3e_actual_service_case() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    required = (
        "expected exactly 8 B3 actual-service tests",
        "test_actual_service_active_read_resolves_only_authority_promoted_generation",
        "test_actual_service_active_generation_revalidates_after_incremental_delivery",
        "test_actual_service_promotion_rejects_graph_loss_after_validation",
        "test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
        "test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
        "test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild",
        "test_actual_service_3e_projects_complete_lineage_and_recovers_graph_loss",
        "test_actual_service_3e_replacement_generation_becomes_only_active_lineage",
    )
    for statement in required:
        assert text.count(statement) == 1
