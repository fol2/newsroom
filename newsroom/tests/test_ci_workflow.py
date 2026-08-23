from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).parents[2]
WORKFLOW_ROOT = REPO_ROOT / ".github" / "workflows"
CI_PATH = WORKFLOW_ROOT / "ci.yml"
EVIDENCE_PATH = WORKFLOW_ROOT / "evidence.yml"
GATES_PATH = REPO_ROOT / ".sdlc" / "gates.toml"
LEGACY_DIAGNOSTICS = (
    "authority-a2a.yml",
    "authority-a2b.yml",
    "projection-b1.yml",
    "projection-b2-neo4j.yml",
)
SMOKE_TESTS = (
    "newsroom/tests/test_ci_workflow.py",
    "newsroom/tests/test_sdlc_contract.py",
    "newsroom/tests/test_sdlc_evidence_workflow.py",
    "newsroom/tests/test_pr_lifecycle.py",
)
CURRENT_GATE_GUIDANCE = (
    REPO_ROOT / ".github" / "pull_request_template.md",
    REPO_ROOT / "docs" / "README.md",
    REPO_ROOT
    / "docs"
    / "plans"
    / "2026-08-09-012-increment-6-current-head-readiness.md",
    REPO_ROOT
    / "docs"
    / "specs"
    / "sdlc"
    / "high-performance-evidence-sdlc.md",
)


def _load(path: Path) -> dict[str, Any]:
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def _steps(job: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = job["steps"]
    assert isinstance(value, list)
    assert all(isinstance(step, dict) for step in value)
    return value


def _step(job: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    matches = [step for step in _steps(job) if step.get("name") == name]
    assert len(matches) == 1, (name, matches)
    return matches[0]


def test_every_retained_workflow_job_has_a_positive_explicit_timeout() -> None:
    for path in sorted(WORKFLOW_ROOT.glob("*.yml")):
        jobs = _load(path)["jobs"]
        assert isinstance(jobs, dict)
        for job_id, job in jobs.items():
            assert isinstance(job, dict)
            timeout = job.get("timeout-minutes")
            assert timeout is not None, (path.name, job_id)
            assert int(timeout) > 0, (path.name, job_id, timeout)


def test_ci_is_an_exact_head_bounded_compatibility_gate() -> None:
    workflow = _load(CI_PATH)
    assert workflow["name"] == "CI"
    assert set(workflow["jobs"]) == {"test"}
    job = workflow["jobs"]["test"]
    assert job["name"] == "test"
    assert job["timeout-minutes"] == "10"

    checkout = next(step for step in _steps(job) if step.get("uses") == "actions/checkout@v4")
    assert checkout["with"]["ref"] == (
        "${{ github.event.pull_request.head.sha || github.sha }}"
    )
    assert checkout["with"]["fetch-depth"] == "0"

    source_check = _step(job, "Source integrity")
    source_command = source_check["run"]
    assert "python -m scripts.sdlc.workflow_lane source-check" in source_command
    assert "--base-sha" in source_command
    assert "--head-sha" in source_command
    assert "github.event.repository.default_branch" in str(source_check)
    assert "git merge-base" in source_command
    assert "refs/remotes/origin/${DEFAULT_BRANCH}" in source_command
    assert "github.event.pull_request.base.sha" in str(source_check)
    assert "github.event.before" in str(source_check)

    smoke = _step(job, "Bounded compatibility smoke")
    smoke_command = smoke["run"]
    assert "timeout --signal=TERM --kill-after=10s 180s" in smoke_command
    for selector in SMOKE_TESTS:
        assert smoke_command.count(selector) == 1
    assert '"PASS"' in smoke_command
    assert '"PRODUCT_FAILURE"' in smoke_command
    assert '"INFRASTRUCTURE_TIMEOUT"' in smoke_command
    assert '"${exit_code}" -eq 124 || "${exit_code}" -eq 137' in smoke_command
    assert "--junitxml=ci-smoke-results.xml" in smoke_command

    upload = _step(job, "Upload compatibility smoke result")
    assert upload["if"] == "always() && steps.smoke.outcome != 'skipped'"
    assert set(upload["with"]["path"].splitlines()) == {
        "ci-smoke-result.json",
        "ci-smoke-results.xml",
    }
    enforce = _step(job, "Enforce compatibility smoke result")
    assert enforce["if"] == "always() && steps.smoke.outcome != 'skipped'"
    assert "ci-smoke-result.json" in enforce["run"]
    assert "PASS" in enforce["run"]

    graphiti_sync = _step(job, "Sync Graphiti extra")
    assert graphiti_sync["run"] == "uv sync --dev --extra graphiti --locked"
    graphiti_research = _step(job, "Run provider-free Graphiti research fixtures")
    assert "newsroom/tests/test_graphiti_combined_temporal_extraction.py" in (
        graphiti_research["run"]
    )
    assert "newsroom/tests/test_graphiti_combined_temporal_pipeline.py" in (
        graphiti_research["run"]
    )
    assert "test_graphiti_token_meter.py" not in graphiti_research["run"]
    live_pin = _step(job, "Verify Graphiti combined-temporal live pin")
    assert "scripts/graphiti_combined_temporal_extraction.py" in live_pin["run"]

    rendered = CI_PATH.read_text(encoding="utf-8")
    assert "pytest -q\n" not in rendered
    assert "eval_clustering_metrics.py" not in rendered
    assert "clustering_eval_dataset" not in rendered


def test_legacy_authority_and_projection_workflows_are_manual_only() -> None:
    for filename in LEGACY_DIAGNOSTICS:
        workflow = _load(WORKFLOW_ROOT / filename)
        assert workflow["on"] == {"workflow_dispatch": ""}
        assert "push" not in workflow["on"]
        assert "pull_request" not in workflow["on"]


def test_sdlc_workflow_retains_dynamic_complete_evidence_topology() -> None:
    workflow = _load(EVIDENCE_PATH)
    jobs = workflow["jobs"]
    assert {"route", "source", "core_shard", "core", "service", "decision"} <= set(
        jobs
    )
    assert jobs["source"]["needs"] == ["route"]
    assert jobs["core_shard"]["needs"] == ["route"]
    assert jobs["core_shard"]["strategy"]["matrix"]["shard"] == [
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
    ]
    assert jobs["core"]["needs"] == ["route", "source", "core_shard"]
    assert jobs["core"]["if"] == "always() && needs.route.result == 'success'"
    assert all(
        "scripts.sdlc.workflow_lane execute " not in str(step.get("run", ""))
        for step in _steps(jobs["core"])
    )
    assert jobs["service"]["needs"] == ["route"]
    assert jobs["service"]["if"] == (
        "needs.route.result == 'success' && "
        "needs.route.outputs.service_required == 'true'"
    )
    assert jobs["decision"]["needs"] == ["route", "core", "service"]
    assert jobs["decision"]["if"] == "always()"

    rendered = EVIDENCE_PATH.read_text(encoding="utf-8")
    assert "python -m scripts.sdlc.workflow_lane execute-source" in rendered
    assert "python -m scripts.sdlc.workflow_lane execute-core-shard" in rendered
    assert rendered.count("python -m scripts.sdlc.workflow_lane reduce-core") == 1
    assert "--lane service" in rendered
    assert "service_required" in rendered
    assert ".sdlc-run/core" in rendered
    assert ".sdlc-run/service" in rendered


def test_retired_clustering_path_group_selects_no_evaluator_dependencies() -> None:
    contract = tomllib.loads(GATES_PATH.read_text(encoding="utf-8"))
    clustering_paths = set(contract["classification"]["paths"]["clustering"])
    assert clustering_paths == {"newsroom/legacy_operational_stack_retired.py"}


def test_pr_admission_does_not_mislabel_core_evidence_as_signed() -> None:
    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in CURRENT_GATE_GUIDANCE
    )

    assert re.search(r"signed(?: SDLC)? core receipt", rendered, re.IGNORECASE) is None
    assert "decision-validated exact-head SDLC core receipt" in rendered
    assert "transport-verified" in rendered
    assert "not signed attestations" in rendered
    assert "exact-main" in rendered
