from __future__ import annotations

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPOSITORY_ROOT / ".github/workflows/projection-b2-neo4j.yml"


def test_permanent_neo4j_gate_executes_exact_increment4e_actual_service_proof() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    required = (
        "newsroom/tests/test_increment4e_neo4j_service.py",
        "test_actual_service_increment4_admitted_state_projects_exactly_and_replays",
        "test_actual_service_increment4_graph_loss_replays_retained_authority_exactly",
        "test_actual_service_increment4_replacement_generation_is_only_serving_state",
        "test_actual_service_increment4_tombstone_purges_and_never_resurrects",
        "required Increment 4E actual-service cases differ",
        "Increment 4E actual-service cases were skipped",
        "Increment 4E actual-service cases failed",
    )
    for statement in required:
        assert text.count(statement) == 1


def test_increment4e_actual_service_gate_retains_runtime_boundary() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8").casefold()
    for statement in (
        "graphiti",
        "openai",
        "embedding",
        "publish.article",
        "production activation",
    ):
        assert statement not in text
