from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).parents[2]
WORKFLOW_ROOT = REPO_ROOT / ".github" / "workflows"
FOCUS_PATH = WORKFLOW_ROOT / "focus-gates.yml"
RESEARCH_PATH = WORKFLOW_ROOT / "ci.yml"
HEALTH_PATH = WORKFLOW_ROOT / "evidence.yml"
PINNED_ACTIONS = {
    "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
    "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
    "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b",
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}


def _load(path: Path) -> dict[str, Any]:
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def _steps(job: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = job["steps"]
    assert isinstance(value, list)
    assert all(isinstance(step, dict) for step in value)
    return value


def test_every_retained_workflow_job_has_a_positive_explicit_timeout() -> None:
    for path in sorted(WORKFLOW_ROOT.glob("*.yml")):
        jobs = _load(path)["jobs"]
        assert isinstance(jobs, dict)
        for job_id, job in jobs.items():
            assert isinstance(job, dict)
            timeout = job.get("timeout-minutes")
            assert timeout is not None, (path.name, job_id)
            assert int(timeout) > 0, (path.name, job_id, timeout)


def test_focus_gate_is_one_job_and_one_conditional_bootstrap() -> None:
    workflow = _load(FOCUS_PATH)
    assert workflow["name"] == "Focus Gates"
    assert set(workflow["on"]) == {"pull_request", "workflow_dispatch"}
    assert set(workflow["jobs"]) == {"focus"}
    job = workflow["jobs"]["focus"]
    assert job["name"] == "focus-gates"
    assert workflow["concurrency"]["cancel-in-progress"] == "true"

    steps = _steps(job)
    rendered = FOCUS_PATH.read_text(encoding="utf-8")
    assert rendered.count("astral-sh/setup-uv@") == 1
    assert rendered.count("uv sync --dev --locked") == 1
    assert "scripts.sdlc.focus_gate" in rendered
    assert "--output .focus/route.json" in rendered
    assert "owner-authorised" in rendered
    assert "graphiti-core" not in rendered
    assert "test_graphiti_combined_temporal" not in rendered
    assert "matrix:" not in rendered
    assert "poll" not in rendered.casefold()

    setup_uv = next(step for step in steps if step.get("name") == "Set up uv once")
    assert setup_uv["if"] == "steps.route.outputs.bootstrap_required == 'true'"
    service = next(
        step for step in steps if step.get("name") == "Start bounded Neo4j service"
    )
    assert service["if"] == "steps.route.outputs.service_required == 'true'"
    for name in (
        "NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED",
        "NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED",
        "NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED",
        "NEWSROOM_NEO4J_SERVICE_REQUIRED",
    ):
        assert name not in job["env"]
    execute = next(
        step for step in steps if step.get("name") == "Execute selected evidence"
    )
    assert all(
        "steps.route.outputs.service_required" in value
        for value in execute["env"].values()
    )


def test_graphiti_research_is_path_scoped_and_provider_free() -> None:
    workflow = _load(RESEARCH_PATH)
    assert workflow["name"] == "Graphiti Research"
    assert set(workflow["on"]) == {"pull_request", "schedule", "workflow_dispatch"}
    assert "push" not in workflow["on"]
    assert workflow["on"]["pull_request"]["paths"]
    rendered = RESEARCH_PATH.read_text(encoding="utf-8")
    assert "uv sync --dev --extra graphiti --locked" in rendered
    assert "graphiti-core" in rendered
    assert "test_graphiti_combined_temporal_runtime.py" in rendered
    assert "${{ secrets." not in rendered
    assert "CURSOR_API_KEY" not in rendered
    assert "OPENROUTER" not in rendered
    assert "provider-free" in rendered


def test_full_health_is_absent_from_ordinary_pull_requests() -> None:
    workflow = _load(HEALTH_PATH)
    assert workflow["name"] == "Full Repository Health"
    assert set(workflow["on"]) == {"merge_group", "schedule", "workflow_dispatch"}
    assert "pull_request" not in workflow["on"]
    assert set(workflow["jobs"]) == {"full-health"}
    rendered = HEALTH_PATH.read_text(encoding="utf-8")
    assert rendered.count("astral-sh/setup-uv@") == 1
    assert rendered.count("uv sync --dev --locked") == 1
    assert "newsroom/tests" in rendered
    assert "-n 4" in rendered
    assert "matrix:" not in rendered


def test_new_sdlc_workflows_use_only_exactly_pinned_actions() -> None:
    observed: set[str] = set()
    for path in (FOCUS_PATH, RESEARCH_PATH, HEALTH_PATH):
        jobs = _load(path)["jobs"]
        for job in jobs.values():
            for step in _steps(job):
                selected = step.get("uses")
                if selected is not None:
                    observed.add(selected)
                    assert selected in PINNED_ACTIONS
    assert observed == PINNED_ACTIONS
