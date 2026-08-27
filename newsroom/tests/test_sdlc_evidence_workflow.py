from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).parents[2]
WORKFLOW_ROOT = REPO_ROOT / ".github" / "workflows"


def _load(name: str) -> dict[str, object]:
    value = yaml.load(
        (WORKFLOW_ROOT / name).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(value, dict)
    return value


def test_ordinary_route_removes_twenty_plus_job_bootstrap_fanout() -> None:
    focus = _load("focus-gates.yml")
    assert len(focus["jobs"]) == 1
    rendered = (WORKFLOW_ROOT / "focus-gates.yml").read_text(encoding="utf-8")
    assert rendered.count("setup-uv@") == 1
    assert "core-shard" not in rendered
    assert "matrix" not in rendered
    assert "reduce-core" not in rendered


def test_complete_inventory_remains_post_merge_and_independently_runnable() -> None:
    health = _load("evidence.yml")
    assert set(health["on"]) == {"push", "schedule", "workflow_dispatch"}
    assert health["on"]["push"]["branches"] == ["main"]
    rendered = (WORKFLOW_ROOT / "evidence.yml").read_text(encoding="utf-8")
    assert "Run complete deterministic product inventory" in rendered
    assert "scripts.sdlc.focus_gate_v2" in rendered
    assert "--repo-root . full-health" in rendered
    assert "--junit full-health.xml" in rendered
    assert "pull_request:" not in rendered
    assert "merge_group:" not in rendered


def test_research_and_product_regression_event_surfaces_do_not_overlap_by_default() -> None:
    focus = _load("focus-gates.yml")
    research = _load("ci.yml")
    assert focus["on"]["pull_request"] == ""
    assert research["on"]["pull_request"]["paths"]
    research_text = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    focus_text = (WORKFLOW_ROOT / "focus-gates.yml").read_text(encoding="utf-8")
    assert "test_graphiti_core_0293_call_shape.py" in research_text
    assert "test_graphiti_core_0293_call_shape.py" not in focus_text
    assert "extra graphiti" in research_text
    assert "extra graphiti" not in focus_text


def test_obsolete_heads_are_cancelled_in_all_new_lanes() -> None:
    for filename in ("focus-gates.yml", "ci.yml", "evidence.yml"):
        workflow = _load(filename)
        assert workflow["concurrency"]["cancel-in-progress"] == "true"


def test_service_and_f4_are_conditional_not_deleted() -> None:
    rendered = (WORKFLOW_ROOT / "focus-gates.yml").read_text(encoding="utf-8")
    assert "Start bounded Neo4j service" in rendered
    assert "steps.route.outputs.service_required == 'true'" in rendered
    assert "Require owner exception for F4" in rendered
    assert "steps.route.outputs.owner_authority_required == 'true'" in rendered
