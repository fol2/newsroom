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
        "runtime-generated",
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
