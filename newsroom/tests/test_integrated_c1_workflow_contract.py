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


def test_permanent_neo4j_gate_retains_increment5e2_closed_world_receipt() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    required = (
        "newsroom/tests/test_projection_b2_*.py",
        "newsroom/tests/test_increment5b4_neo4j_service.py",
        "newsroom/tests/test_increment6g_neo4j_service.py",
        "scripts.sdlc.increment5e2_closeout_receipt actual-service",
        "--service-junit-report projection-b2-b3-c1-complete-retrieval-neo4j-results.xml",
        "--output increment5e2-actual-service-closeout.json",
        "increment5e2-actual-service-closeout.json",
        "Remove disposable credential files",
        '${RUNNER_TEMP}/newsroom-b2-neo4j-admin.env',
        '${RUNNER_TEMP}/newsroom-b2-neo4j-projector.env',
        'export NEWSROOM_NEO4J_PASSWORD="${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}"',
    )
    for statement in required:
        assert statement in text
    assert "GITHUB_ENV" not in text
    assert text.index("Remove disposable credential files") < text.index(
        "Build Increment 5E2 actual-service closeout receipt"
    )
    assert "if: steps.focused.outcome == 'success'" in text
