from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "evidence.yml"

CHECKOUT = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
SETUP_UV = "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b"
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWNLOAD = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
EVALUATED_SHA = (
    "${{ github.event.pull_request.head.sha || "
    "github.event.merge_group.head_sha || github.sha }}"
)
ROUTE_ARTIFACT = (
    "newsroom-sdlc-route-${{ github.run_id }}-${{ github.run_attempt }}-"
    + EVALUATED_SHA
)
_ACTION_SHA = re.compile(r"[0-9a-f]{40}")


def _workflow() -> dict[str, Any]:
    value = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def _jobs() -> dict[str, Mapping[str, Any]]:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _steps(job_id: str) -> list[Mapping[str, Any]]:
    steps = _jobs()[job_id]["steps"]
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return steps


def _step(job_id: str, name: str) -> Mapping[str, Any]:
    matches = [step for step in _steps(job_id) if step.get("name") == name]
    assert len(matches) == 1, (job_id, name, matches)
    return matches[0]


def _uses_steps(job_id: str, selected: str) -> list[Mapping[str, Any]]:
    return [step for step in _steps(job_id) if step.get("uses") == selected]


def _all_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            result.extend(_all_strings(key))
            result.extend(_all_strings(item))
        return result
    if isinstance(value, list):
        return [text for item in value for text in _all_strings(item)]
    return []


def test_shadow_workflow_has_exact_nonprivileged_event_surface() -> None:
    workflow = _workflow()
    assert set(workflow) == {"name", "on", "permissions", "concurrency", "jobs"}
    assert workflow["name"] == "SDLC Evidence Shadow"

    events = workflow["on"]
    assert isinstance(events, dict)
    assert set(events) == {"pull_request", "merge_group", "workflow_dispatch"}
    assert "push" not in events
    assert events["merge_group"] == {"types": ["checks_requested"]}
    manual = events["workflow_dispatch"]
    assert isinstance(manual, dict)
    assert manual["inputs"]["base_sha"]["required"] == "false"
    assert manual["inputs"]["base_sha"]["type"] == "string"

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": (
            "newsroom-sdlc-evidence-${{ github.event.pull_request.number || "
            "github.event.merge_group.head_sha || github.ref }}"
        ),
        "cancel-in-progress": "true",
    }

    rendered = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pull_request_target" not in rendered
    assert "${{ secrets." not in rendered
    assert "continue-on-error" not in rendered


def test_job_graph_is_exact_and_decision_always_reports() -> None:
    jobs = _jobs()
    assert set(jobs) == {"route", "core", "service", "decision"}
    assert {job_id: jobs[job_id]["name"] for job_id in jobs} == {
        "route": "route",
        "core": "core",
        "service": "service",
        "decision": "decision",
    }
    assert jobs["core"]["needs"] == ["route"]
    assert jobs["service"]["needs"] == ["route"]
    assert jobs["decision"]["needs"] == ["route", "core", "service"]
    assert jobs["core"]["if"] == "needs.route.result == 'success'"
    assert jobs["service"]["if"] == (
        "needs.route.result == 'success' && "
        "needs.route.outputs.service_required == 'true'"
    )
    assert jobs["decision"]["if"] == "always()"
    assert jobs["decision"]["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert jobs["route"]["outputs"] == {
        "service_required": "${{ steps.route_output.outputs.service_required }}"
    }
    assert all(int(job["timeout-minutes"]) <= 5 for job in jobs.values())


def test_every_action_is_release_pinned_to_an_exact_sha() -> None:
    workflow = _workflow()
    allowed = {CHECKOUT, SETUP_PYTHON, SETUP_UV, UPLOAD, DOWNLOAD}
    observed: list[str] = []
    for job_id in _jobs():
        for step in _steps(job_id):
            selected = step.get("uses")
            if selected is None:
                continue
            assert isinstance(selected, str)
            repository, separator, commit = selected.partition("@")
            assert separator and repository
            assert _ACTION_SHA.fullmatch(commit), selected
            assert selected in allowed
            observed.append(selected)
    assert set(observed) == allowed
    assert observed.count(CHECKOUT) == 4
    assert observed.count(SETUP_PYTHON) == 4
    assert observed.count(SETUP_UV) == 2
    assert observed.count(UPLOAD) == 4
    assert observed.count(DOWNLOAD) == 2


def test_each_job_checks_out_the_exact_evaluated_head_without_credentials() -> None:
    for job_id in _jobs():
        checkouts = _uses_steps(job_id, CHECKOUT)
        assert len(checkouts) == 1
        assert _steps(job_id)[0] == checkouts[0]
        assert checkouts[0]["with"] == {
            "ref": EVALUATED_SHA,
            "fetch-depth": "0",
            "persist-credentials": "false",
            "show-progress": "false",
        }
        python = _uses_steps(job_id, SETUP_PYTHON)
        assert len(python) == 1
        assert python[0]["with"] == {"python-version": "3.12"}


def test_uv_cache_is_exact_observable_and_untrusted_prs_cannot_save() -> None:
    core = _uses_steps("core", SETUP_UV)
    service = _uses_steps("service", SETUP_UV)
    assert len(core) == len(service) == 1
    common = {
        "version": "0.8.0",
        "enable-cache": "true",
        "cache-dependency-glob": "uv.lock",
        "restore-cache": "true",
        "cache-suffix": "newsroom-py312",
        "prune-cache": "false",
        "cache-python": "false",
    }
    assert core[0]["with"] == {
        **common,
        "save-cache": "${{ github.event_name != 'pull_request' }}",
    }
    assert service[0]["with"] == {**common, "save-cache": "false"}
    assert not _uses_steps("route", SETUP_UV)
    assert not _uses_steps("decision", SETUP_UV)

    expected_cache_env = {
        "NEWSROOM_SDLC_CACHE_KEY": "${{ steps.setup_uv.outputs.cache-key }}",
        "NEWSROOM_SDLC_CACHE_HIT": "${{ steps.setup_uv.outputs.cache-hit }}",
    }
    for job_id in ("core", "service"):
        assert _step(job_id, "Execute evidence lane")["env"] == expected_cache_env
        assert _step(job_id, "Finalize evidence")["env"] == expected_cache_env
    for job_id in ("route", "decision"):
        assert all("NEWSROOM_SDLC_CACHE" not in text for text in _all_strings(_steps(job_id)))


def test_route_artifact_transport_is_attempt_and_head_scoped() -> None:
    upload = _step("route", "Upload route evidence")
    assert upload["uses"] == UPLOAD
    assert upload["with"] == {
        "name": ROUTE_ARTIFACT,
        "path": ".sdlc-run/route",
        "if-no-files-found": "error",
        "retention-days": "30",
        "compression-level": "0",
        "overwrite": "false",
        "include-hidden-files": "false",
        "archive": "true",
    }
    for job_id in ("core", "service"):
        download = _step(job_id, "Download exact route evidence")
        assert download["uses"] == DOWNLOAD
        assert download["with"] == {
            "name": ROUTE_ARTIFACT,
            "path": ".sdlc-run/route",
            "merge-multiple": "false",
            "digest-mismatch": "error",
        }


def test_lane_and_decision_artifacts_are_compact_immutable_and_attempt_scoped() -> None:
    expected = {
        "core": (
            "Upload core lane evidence",
            "newsroom-sdlc-${{ github.run_id }}-${{ github.run_attempt }}-core-"
            + EVALUATED_SHA,
            ".sdlc-run/core",
        ),
        "service": (
            "Upload service lane evidence",
            "newsroom-sdlc-${{ github.run_id }}-${{ github.run_attempt }}-service-"
            + EVALUATED_SHA,
            ".sdlc-run/service",
        ),
        "decision": (
            "Upload final decision evidence",
            "newsroom-sdlc-decision-${{ github.run_id }}-${{ github.run_attempt }}-"
            + EVALUATED_SHA,
            None,
        ),
    }
    for job_id, (name, artifact_name, path) in expected.items():
        upload = _step(job_id, name)
        assert upload["uses"] == UPLOAD
        assert upload["if"] == "always()"
        values = upload["with"]
        assert values["name"] == artifact_name
        assert values["retention-days"] == "30"
        assert values["compression-level"] == "0"
        assert values["overwrite"] == "false"
        assert values["include-hidden-files"] == "false"
        assert values["archive"] == "true"
        assert values["if-no-files-found"] == "error"
        if path is not None:
            assert values["path"] == path
        else:
            assert values["path"].splitlines() == [
                ".sdlc-run/decision-input/context.json",
                ".sdlc-run/decision-input/collection.json",
                ".sdlc-run/decision.json",
            ]


def test_lane_step_names_match_jobs_api_telemetry_contract() -> None:
    for job_id in _jobs():
        names = [step.get("name") for step in _steps(job_id)]
        assert all(isinstance(name, str) and name for name in names)
        assert len(names) == len(set(names))
    assert "Sync locked environment" in {
        step["name"] for step in _steps("core")
    }
    assert "Finalize evidence" in {step["name"] for step in _steps("core")}
    assert "Sync locked environment" in {
        step["name"] for step in _steps("service")
    }
    assert "Wait for authenticated Neo4j" in {
        step["name"] for step in _steps("service")
    }
    assert "Finalize evidence" in {step["name"] for step in _steps("service")}


def test_service_boundary_is_exact_authenticated_loopback_and_bounded() -> None:
    job = _jobs()["service"]
    assert job["env"] == {
        "NEO4J_B2_IMAGE": "neo4j:2026.06.0-community-trixie",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_ADMIN_USERNAME": "neo4j",
        "NEWSROOM_NEO4J_DATABASE": "neo4j",
        "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",
        "NEWSROOM_NEO4J_SERVICE_REQUIRED": "1",
        "NEWSROOM_NEO4J_URI": "bolt://localhost:7687",
    }
    assert not any("PASSWORD" in name or "TOKEN" in name for name in job["env"])

    start = _step("service", "Generate masked credentials and start Neo4j")["run"]
    for required in (
        "::add-mask::${NEO4J_ADMIN_PASSWORD}",
        "::add-mask::${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}",
        "--publish 127.0.0.1:7687:7687",
        "--pull=never",
        "timeout --signal=TERM --kill-after=5s 55s",
        "timeout --signal=TERM --kill-after=2s 10s",
    ):
        assert required in start

    wait = _step("service", "Wait for authenticated Neo4j")["run"]
    for required in (
        "time.monotonic() + 25.0",
        "connection_timeout=1.0",
        "CREATE USER newsroom_projector IF NOT EXISTS",
        "verify_connectivity()",
    ):
        assert required in wait

    cleanup = _step("service", "Remove disposable Neo4j state")
    assert cleanup["if"] == "always()"
    assert "docker rm --force newsroom-sdlc-neo4j" in cleanup["run"]
    assert "kill-after=2s 10s" in cleanup["run"]


def test_repository_owned_gate_budgets_drive_route_lane_and_decision() -> None:
    route = _step("route", "Classify exact change")["run"]
    assert "scripts.sdlc.workflow_budget route" in route
    assert '${RUNNER_TEMP}/route-gate.json' in route
    assert ".sdlc-run/route-gate.json" not in route

    for job_id, lane in (("core", "core"), ("service", "service")):
        execute = _step(job_id, "Execute evidence lane")["run"]
        finalize = _step(job_id, "Finalize evidence")
        assert "scripts.sdlc.workflow_lane execute" in execute
        assert f"--lane {lane}" in execute
        assert finalize["if"] == "always()"
        assert "scripts.sdlc.workflow_budget finalize-lane" in finalize["run"]
        assert f"--lane {lane}" in finalize["run"]
        assert "${RUNNER_TEMP}" in finalize["run"]

    collect = _step("decision", "Collect exact lane evidence")
    assert collect["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}
    assert "timeout --signal=TERM --kill-after=2s 55s" in collect["run"]
    assert "scripts.sdlc.workflow_orchestrator collect" in collect["run"]
    finalize = _step("decision", "Finalize decision")
    assert finalize["if"] == "always()"
    assert "scripts.sdlc.workflow_orchestrator decide" in finalize["run"]
    report = _step("decision", "Report decision")
    assert report["if"] == "always()"
    assert "scripts.sdlc.workflow_orchestrator enforce" in report["run"]
    assert _steps("decision")[-1] == report


def test_github_token_exists_only_on_exact_collection_step() -> None:
    locations: list[tuple[str, str]] = []
    for job_id in _jobs():
        for step in _steps(job_id):
            environment = step.get("env")
            if isinstance(environment, dict) and "GITHUB_TOKEN" in environment:
                locations.append((job_id, str(step.get("name"))))
    assert locations == [("decision", "Collect exact lane evidence")]


def test_workflow_never_invokes_prohibited_product_runtime() -> None:
    rendered = WORKFLOW_PATH.read_text(encoding="utf-8").lower()
    for forbidden in (
        "graphiti",
        "embedding",
        "gdelt",
        "rss_pool",
        "news_pool_update",
        "publication",
        "canary",
        "production activation",
    ):
        assert forbidden not in rendered
