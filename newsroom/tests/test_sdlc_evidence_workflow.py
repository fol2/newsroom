from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "evidence.yml"

CHECKOUT = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
SETUP_UV = "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b"
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWNLOAD = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
ATTEST = "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
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
    assert manual["inputs"]["base_sha"]["required"] == "true"
    assert manual["inputs"]["base_sha"]["description"] == (
        "Required exact non-head base commit for a manual comparison"
    )
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
    assert set(jobs) == {
        "route",
        "source",
        "core_shard",
        "core",
        "service",
        "decision",
        "signed-closeout",
    }
    assert {job_id: jobs[job_id]["name"] for job_id in jobs} == {
        "route": "route",
        "source": "source",
        "core_shard": "core-shard-${{ matrix.shard }}",
        "core": "core",
        "service": "service",
        "decision": "decision",
        "signed-closeout": "signed-closeout",
    }
    assert jobs["source"]["needs"] == ["route"]
    assert jobs["core_shard"]["needs"] == ["route"]
    assert jobs["core"]["needs"] == ["route", "source", "core_shard"]
    assert jobs["service"]["needs"] == ["route"]
    assert jobs["decision"]["needs"] == ["route", "core", "service"]
    assert jobs["signed-closeout"]["needs"] == ["route", "decision"]
    assert jobs["source"]["if"] == "needs.route.result == 'success'"
    assert jobs["core_shard"]["if"] == "needs.route.result == 'success'"
    assert jobs["core"]["if"] == "always() && needs.route.result == 'success'"
    assert jobs["core_shard"]["strategy"] == {
        "fail-fast": "false",
        "matrix": {
            "shard": [
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
            ]
        },
    }
    assert jobs["service"]["if"] == (
        "needs.route.result == 'success' && "
        "needs.route.outputs.service_required == 'true'"
    )
    assert jobs["decision"]["if"] == "always()"
    assert jobs["decision"]["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert jobs["signed-closeout"]["if"] == (
        "github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/main' && "
        "needs.route.outputs.service_required == 'true' && "
        "needs.decision.result == 'success'"
    )
    assert jobs["signed-closeout"]["permissions"] == {
        "actions": "read",
        "artifact-metadata": "write",
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }
    assert jobs["route"]["outputs"] == {
        "service_required": "${{ steps.route_output.outputs.service_required }}"
    }
    assert {job_id: job["timeout-minutes"] for job_id, job in jobs.items()} == {
        "route": "6",
        "source": "10",
        "core_shard": "10",
        "core": "10",
        "service": "10",
        "decision": "10",
        "signed-closeout": "6",
    }


def test_every_action_is_release_pinned_to_an_exact_sha() -> None:
    allowed = {CHECKOUT, SETUP_PYTHON, SETUP_UV, UPLOAD, DOWNLOAD, ATTEST}
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
    assert observed.count(CHECKOUT) == 6
    assert observed.count(SETUP_PYTHON) == 6
    assert observed.count(SETUP_UV) == 5
    assert observed.count(UPLOAD) == 7
    assert observed.count(DOWNLOAD) == 7
    assert observed.count(ATTEST) == 1


def test_execution_jobs_check_out_the_exact_evaluated_head_without_credentials() -> (
    None
):
    for job_id in ("route", "source", "core_shard", "core", "service", "decision"):
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
    assert not _uses_steps("signed-closeout", CHECKOUT)
    assert not _uses_steps("signed-closeout", SETUP_PYTHON)


def test_uv_cache_is_exact_observable_and_untrusted_prs_cannot_save() -> None:
    source = _uses_steps("source", SETUP_UV)
    shard = _uses_steps("core_shard", SETUP_UV)
    core = _uses_steps("core", SETUP_UV)
    service = _uses_steps("service", SETUP_UV)
    decision = _uses_steps("decision", SETUP_UV)
    assert len(source) == len(shard) == len(core) == len(service) == len(decision) == 1
    common = {
        "version": "0.8.0",
        "github-token": "",
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
    assert source[0]["with"] == {**common, "save-cache": "false"}
    assert shard[0]["with"] == {**common, "save-cache": "false"}
    assert service[0]["with"] == {**common, "save-cache": "false"}
    assert decision[0]["with"] == {**common, "save-cache": "false"}
    assert decision[0]["if"] == ("needs.route.outputs.service_required == 'true'")
    assert not _uses_steps("route", SETUP_UV)

    expected_cache_env = {
        "NEWSROOM_SDLC_CACHE_KEY": "${{ steps.setup_uv.outputs.cache-key }}",
        "NEWSROOM_SDLC_CACHE_HIT": "${{ steps.setup_uv.outputs.cache-hit }}",
    }
    for job_id, step_name in (
        ("source", "Execute source integrity"),
        ("core_shard", "Execute bounded core shard"),
        ("core", "Reduce exact core fragments"),
        ("service", "Execute evidence lane"),
    ):
        assert _step(job_id, step_name)["env"] == expected_cache_env
    for job_id in ("core", "service"):
        assert _step(job_id, "Finalize evidence")["env"] == expected_cache_env
    for job_id in ("route", "decision"):
        assert all(
            "NEWSROOM_SDLC_CACHE" not in text for text in _all_strings(_steps(job_id))
        )


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
    for job_id in ("source", "core_shard", "core", "service"):
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
                ".sdlc-run/increment5e2-final-closeout.json",
                ".sdlc-run/increment6g-final-closeout.json",
                ".sdlc-run/increment7g-final-closeout.json",
                    ".sdlc-run/increment8f-final-closeout.json",
                    ".sdlc-run/increment8-qualification-packet.json",
                    ".sdlc-run/increment8-operational-admission-decision.json",
                ]


def test_core_shards_are_exact_inputs_to_one_canonical_core_artifact() -> None:
    source_upload = _step("source", "Upload source fragment")
    assert source_upload["if"] == "always()"
    assert source_upload["with"]["path"] == ".sdlc-run/source-fragment"
    shard_upload = _step("core_shard", "Upload canonical core fragment")
    assert shard_upload["if"] == "always()"
    assert shard_upload["with"]["name"] == (
        "newsroom-sdlc-core-fragment-${{ github.run_id }}-"
        "${{ github.run_attempt }}-" + EVALUATED_SHA + "-${{ matrix.shard }}"
    )
    assert shard_upload["with"]["path"] == ".sdlc-run/core-fragment"

    download = _step("core", "Download exact core fragments")
    assert download["with"]["pattern"] == (
        "newsroom-sdlc-core-fragment-${{ github.run_id }}-"
        "${{ github.run_attempt }}-" + EVALUATED_SHA + "-*"
    )
    assert download["with"]["merge-multiple"] == "false"
    assert download["with"]["digest-mismatch"] == "error"

    canonical_uploads = [
        step
        for step in _uses_steps("core", UPLOAD)
        if step["with"]["name"].startswith("newsroom-sdlc-${{ github.run_id }}")
    ]
    assert len(canonical_uploads) == 1
    assert not _uses_steps("core_shard", ATTEST)
    reducer_invocations = [
        text
        for job_id in _jobs()
        for text in _all_strings(_steps(job_id))
        if "scripts.sdlc.workflow_lane reduce-core" in text
    ]
    assert len(reducer_invocations) == 1
    assert "scripts.sdlc.workflow_lane execute --lane core" not in (
        WORKFLOW_PATH.read_text(encoding="utf-8")
    )

    rendered_fast = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pytest -q newsroom/tests" not in rendered_fast
    assert "pytest -q \\\n              newsroom/tests \\" not in rendered_fast


def test_signed_closeout_attests_only_the_validated_exact_main_receipt() -> None:
    job = _jobs()["signed-closeout"]
    download = _step("signed-closeout", "Download exact final decision evidence")
    assert download["uses"] == DOWNLOAD
    assert download["with"] == {
        "name": (
            "newsroom-sdlc-decision-${{ github.run_id }}-"
            "${{ github.run_attempt }}-${{ github.sha }}"
        ),
        "path": ".sdlc-run/signed-closeout-input",
        "merge-multiple": "false",
        "digest-mismatch": "error",
    }

    validate = _step("signed-closeout", "Validate final closeout subject")
    assert validate["env"] == {"EXPECTED_HEAD_SHA": "${{ github.sha }}"}
    validation = validate["run"]
    for expected in (
        "newsroom.increment5e2.final-closeout-receipt.v1",
        "newsroom.increment6g.final-closeout-receipt.v1",
        "newsroom.increment7.closeout-receipt.v1",
            "newsroom.increment8.closeout-receipt.v2",
            "newsroom.increment8.qualification-packet.v1",
            "newsroom.increment8.operational-admission-decision.v1",
        "receipt_identity",
        "evaluated_sha",
        "EXPECTED_HEAD_SHA",
        "hashlib.sha256",
        "allow_nan=False",
        "object_pairs_hook=unique_object",
        "newsroom.sdlc.shadow-decision.v1",
        "workflow_dispatch",
        "refs/heads/main",
        "signed decision binding differs",
    ):
        assert expected in validation

    attest = _step(
        "signed-closeout",
        "Attest final decision and closeout receipt",
    )
    assert attest["uses"] == ATTEST
    assert attest["with"]["subject-path"].splitlines() == [
        ".sdlc-run/signed-closeout-input/decision.json",
        (".sdlc-run/signed-closeout-input/increment5e2-final-closeout.json"),
        ".sdlc-run/signed-closeout-input/increment6g-final-closeout.json",
        ".sdlc-run/signed-closeout-input/increment7g-final-closeout.json",
            ".sdlc-run/signed-closeout-input/increment8f-final-closeout.json",
            ".sdlc-run/signed-closeout-input/increment8-qualification-packet.json",
            ".sdlc-run/signed-closeout-input/increment8-operational-admission-decision.json",
        ]
    upload = _step("signed-closeout", "Retain attestation bundle")
    assert upload["uses"] == UPLOAD
    assert upload["with"] == {
        "name": (
            "newsroom-sdlc-attestation-${{ github.run_id }}-"
            "${{ github.run_attempt }}-${{ github.sha }}"
        ),
        "path": "${{ steps.attest.outputs.bundle-path }}",
        "if-no-files-found": "error",
        "retention-days": "30",
        "compression-level": "0",
        "overwrite": "false",
        "include-hidden-files": "false",
        "archive": "true",
    }
    assert job["steps"][-1] == upload


def test_only_signed_closeout_receives_oidc_and_attestation_permissions() -> None:
    jobs = _jobs()
    for job_id, job in jobs.items():
        permissions = job.get("permissions", _workflow()["permissions"])
        if job_id == "signed-closeout":
            continue
        assert permissions.get("id-token") != "write"
        assert permissions.get("attestations") != "write"
        assert permissions.get("artifact-metadata") != "write"

    rendered = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert rendered.count("id-token: write") == 1
    assert rendered.count("attestations: write") == 1
    assert rendered.count("artifact-metadata: write") == 1


def test_lane_step_names_match_jobs_api_telemetry_contract() -> None:
    for job_id in _jobs():
        names = [step.get("name") for step in _steps(job_id)]
        assert all(isinstance(name, str) and name for name in names)
        assert len(names) == len(set(names))
    assert "Sync locked environment" in {step["name"] for step in _steps("core")}
    assert "Finalize evidence" in {step["name"] for step in _steps("core")}
    assert "Sync locked environment" in {step["name"] for step in _steps("service")}
    assert "Wait for authenticated Neo4j" in {
        step["name"] for step in _steps("service")
    }
    assert "Finalize evidence" in {step["name"] for step in _steps("service")}


def test_core_bootstrap_precompiles_exact_source_before_timed_lane() -> None:
    sync = _step("core", "Sync locked environment")["run"]
    assert sync.splitlines()[-1] == (
        "uv run --no-sync python -m compileall -q newsroom scripts"
    )
    names = [step["name"] for step in _steps("core")]
    assert names.index("Sync locked environment") < names.index(
        "Reduce exact core fragments"
    )
    assert "compileall" not in _step("service", "Sync locked environment")["run"]


def test_decision_bootstraps_locked_runtime_before_closeout_receipt() -> None:
    sync_step = _step("decision", "Sync locked closeout environment")
    assert sync_step["if"] == "needs.route.outputs.service_required == 'true'"
    sync = sync_step["run"]
    assert sync.splitlines() == [
        "set -euo pipefail",
        "uv lock --check",
        "uv sync --locked --no-dev",
    ]
    closeout = _step("decision", "Build Increment 5E2 final closeout receipt")
    invocation = (
        "uv run --no-sync python -m scripts.sdlc.increment5e2_closeout_receipt final"
    )
    assert invocation in closeout["run"]
    names = [step["name"] for step in _steps("decision")]
    assert names.index("Sync locked closeout environment") < names.index(
        "Build Increment 5E2 final closeout receipt"
    )
    increment7 = _step("decision", "Build Increment 7G final closeout receipt")
    assert increment7["if"] == "needs.route.outputs.service_required == 'true'"
    for expected in (
        "scripts.sdlc.increment7g_closeout_receipt",
        "--core-transport-bundle-root .sdlc-run/decision-input/core-transport",
        "--service-transport-bundle-root .sdlc-run/decision-input/service-transport",
        "--decision .sdlc-run/decision.json",
        "--output .sdlc-run/increment7g-final-closeout.json",
    ):
        assert expected in increment7["run"]
    increment8 = _step("decision", "Build Increment 8F final closeout receipt")
    assert increment8["if"] == "needs.route.outputs.service_required == 'true'"
    for expected in (
        "scripts.sdlc.increment8f_closeout_receipt",
        "--core-transport-bundle-root .sdlc-run/decision-input/core-transport",
        "--service-transport-bundle-root .sdlc-run/decision-input/service-transport",
        "--decision .sdlc-run/decision.json",
        "--output .sdlc-run/increment8f-final-closeout.json",
    ):
        assert expected in increment8["run"]


def test_service_boundary_is_exact_authenticated_loopback_and_bounded() -> None:
    job = _jobs()["service"]
    assert job["env"] == {
        "NEO4J_B2_IMAGE": "neo4j:2026.06.0-community-trixie",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_ADMIN_USERNAME": "neo4j",
        "NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED": "1",
        "NEWSROOM_NEO4J_DATABASE": "neo4j",
        "NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED": "1",
        "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",
        "NEWSROOM_NEO4J_USER": "newsroom_projector",
        "NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED": "1",
        "NEWSROOM_NEO4J_SERVICE_REQUIRED": "1",
        "NEWSROOM_NEO4J_URI": "bolt://localhost:7687",
    }
    assert not any("PASSWORD" in name or "TOKEN" in name for name in job["env"])

    start = _step("service", "Generate masked credentials and start Neo4j")["run"]
    assert "GITHUB_ENV" not in start
    for required in (
        "::add-mask::${NEO4J_ADMIN_PASSWORD}",
        "::add-mask::${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}",
        "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env",
        "${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env",
        'chmod 600 "${admin_file}" "${projector_file}"',
        "--publish 127.0.0.1:7687:7687",
        "--pull=never",
        "timeout --signal=TERM --kill-after=5s 220s",
        "timeout --signal=TERM --kill-after=2s 20s",
    ):
        assert required in start

    wait = _step("service", "Wait for authenticated Neo4j")["run"]
    assert 'source "${admin_file}"' in wait
    assert 'source "${projector_file}"' in wait
    assert 'rm -f "${admin_file}"' in wait
    execute = _step("service", "Execute evidence lane")["run"]
    assert 'source "${projector_file}"' in execute
    assert 'source "${admin_file}"' not in execute
    assert 'test ! -e "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env"' in execute
    assert "NEO4J_ADMIN_PASSWORD" not in _step(
        "service", "Upload service lane evidence"
    ).get("env", {})
    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in _step(
        "service", "Upload service lane evidence"
    ).get("env", {})
    for required in (
        "time.monotonic() + 50.0",
        "connection_timeout=1.0",
        "CREATE USER newsroom_projector IF NOT EXISTS",
        "verify_connectivity()",
    ):
        assert required in wait

    cleanup = _step("service", "Remove disposable Neo4j state")
    assert cleanup["if"] == "always()"
    assert "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env" in cleanup["run"]
    assert "${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env" in cleanup["run"]
    assert "docker rm --force newsroom-sdlc-neo4j" in cleanup["run"]
    assert "kill-after=2s 20s" in cleanup["run"]
    service_names = [step["name"] for step in _steps("service")]
    assert service_names.index("Execute evidence lane") < service_names.index(
        "Remove disposable Neo4j state"
    )
    assert service_names.index("Remove disposable Neo4j state") < service_names.index(
        "Finalize evidence"
    )
    assert service_names.index("Finalize evidence") < service_names.index(
        "Upload service lane evidence"
    )


def test_repository_owned_gate_budgets_drive_route_lane_and_decision() -> None:
    route = _step("route", "Classify exact change")["run"]
    assert "scripts.sdlc.workflow_budget route" in route
    assert "${RUNNER_TEMP}/route-gate.json" in route
    assert ".sdlc-run/route-gate.json" not in route

    for job_id, lane in (("service", "service"),):
        execute = _step(job_id, "Execute evidence lane")["run"]
        finalize = _step(job_id, "Finalize evidence")
        assert "scripts.sdlc.workflow_lane execute" in execute
        assert f"--lane {lane}" in execute
        assert finalize["if"] == "always()"
        assert "scripts.sdlc.workflow_budget finalize-lane" in finalize["run"]
        assert f"--lane {lane}" in finalize["run"]
        assert "${RUNNER_TEMP}" in finalize["run"]

    shard = _step("core_shard", "Execute bounded core shard")["run"]
    assert "scripts.sdlc.workflow_lane execute-core-shard" in shard
    assert "--shard-index ${{ matrix.shard }}" in shard
    source = _step("source", "Execute source integrity")["run"]
    assert "scripts.sdlc.workflow_lane execute-source" in source
    reduce = _step("core", "Reduce exact core fragments")["run"]
    assert "scripts.sdlc.workflow_lane reduce-core" in reduce
    assert "--fragment-root .sdlc-run/core-fragments" in reduce
    core_finalize = _step("core", "Finalize evidence")
    assert core_finalize["if"] == "always()"
    assert "scripts.sdlc.workflow_budget finalize-lane" in core_finalize["run"]
    assert "--lane core" in core_finalize["run"]

    collect = _step("decision", "Collect exact lane evidence")
    assert collect["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}
    assert "timeout --signal=TERM --kill-after=2s 220s" in collect["run"]
    assert "scripts.sdlc.workflow_orchestrator collect" in collect["run"]
    finalize = _step("decision", "Finalize decision")
    assert finalize["if"] == "always()"
    assert "scripts.sdlc.workflow_orchestrator decide" in finalize["run"]
    closeout = _step("decision", "Build Increment 5E2 final closeout receipt")
    assert closeout["if"] == "needs.route.outputs.service_required == 'true'"
    for expected in (
        "scripts.sdlc.increment5e2_closeout_receipt final",
        "--core-transport-bundle-root .sdlc-run/decision-input/core-transport",
        "--service-transport-bundle-root .sdlc-run/decision-input/service-transport",
        "--decision .sdlc-run/decision.json",
        "--output .sdlc-run/increment5e2-final-closeout.json",
    ):
        assert expected in closeout["run"]
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


def test_setup_uv_never_receives_the_github_token() -> None:
    for job_id in ("source", "core_shard", "core", "service", "decision"):
        setup = _uses_steps(job_id, SETUP_UV)
        assert len(setup) == 1
        assert setup[0]["with"]["github-token"] == ""


def test_service_credentials_are_removed_before_untrusted_finalization_or_actions() -> (
    None
):
    rendered = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "GITHUB_ENV" not in rendered
    admin_file = "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env"
    projector_file = "${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env"
    assert rendered.count(admin_file) == 4
    assert rendered.count(projector_file) == 4
    service_steps = _steps("service")
    cleanup_index = next(
        index
        for index, step in enumerate(service_steps)
        if step["name"] == "Remove disposable Neo4j state"
    )
    assert cleanup_index < next(
        index
        for index, step in enumerate(service_steps)
        if step["name"] == "Finalize evidence"
    )
    assert cleanup_index < next(
        index
        for index, step in enumerate(service_steps)
        if step["name"] == "Upload service lane evidence"
    )
    assert all(
        "PASSWORD" not in str(name) and "TOKEN" not in str(name)
        for step in service_steps
        if step.get("uses")
        for name in step.get("env", {})
    )


def test_service_test_child_has_no_admin_credential_file() -> None:
    execute = _step("service", "Execute evidence lane")["run"]
    assert 'source "${projector_file}"' in execute
    assert 'source "${admin_file}"' not in execute
    assert 'test ! -e "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env"' in execute
