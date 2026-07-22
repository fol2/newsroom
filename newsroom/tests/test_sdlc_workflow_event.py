from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

import scripts.sdlc.workflow_event as workflow_event_module
from scripts.sdlc.workflow_event import (
    WorkflowEvidenceError,
    derive_workflow_event,
    main as workflow_event_main,
    measure_job_telemetry,
    validate_job_telemetry,
    validate_workflow_event,
)


REPOSITORY_ID = "1153895518"


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "sdlc@example.invalid")
    _git(repo, "config", "user.name", "SDLC Test")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    base_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "tracked.txt").write_text("head\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")
    head_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    return repo, base, base_tree, head, head_tree


def _event(
    repo: Path,
    *,
    event_name: str,
    base: str,
    head: str,
    base_repository: str = "fol2/newsroom",
    base_repository_id: int = int(REPOSITORY_ID),
    dispatch_base: str | None = None,
) -> Path:
    value: dict[str, object] = {
        "repository": {"full_name": "fol2/newsroom", "id": int(REPOSITORY_ID)}
    }
    if event_name == "pull_request":
        value["pull_request"] = {
            "base": {
                "sha": base,
                "repo": {
                    "full_name": base_repository,
                    "id": base_repository_id,
                },
            },
            "head": {
                "sha": head,
                "repo": {
                    "full_name": "contributor/newsroom",
                    "id": 999,
                },
            },
        }
    elif event_name == "merge_group":
        value["merge_group"] = {"base_sha": base, "head_sha": head}
    elif event_name == "push":
        value.update({"before": base, "after": head})
    elif event_name == "workflow_dispatch":
        value["inputs"] = {} if dispatch_base is None else {"base_sha": dispatch_base}
    else:
        raise AssertionError(event_name)
    path = repo / "event.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _environment(
    repo: Path,
    *,
    event_name: str,
    base: str,
    head: str,
    dispatch_base: str | None = None,
) -> dict[str, str]:
    event = _event(
        repo,
        event_name=event_name,
        base=base,
        head=head,
        dispatch_base=dispatch_base,
    )
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "fol2/newsroom",
        "GITHUB_REPOSITORY_ID": REPOSITORY_ID,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_JOB": "route",
        "GITHUB_WORKFLOW_REF": (
            "fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge"
        ),
        "GITHUB_WORKFLOW_SHA": "a" * 40,
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_SHA": head if event_name != "pull_request" else "b" * 40,
        "GITHUB_REF": (
            "refs/heads/main" if event_name == "workflow_dispatch" else "refs/pull/10/merge"
        ),
        "RUNNER_ENVIRONMENT": "github-hosted",
    }


def test_pull_request_event_binds_base_and_evaluated_head(tmp_path: Path) -> None:
    repo, base, base_tree, head, head_tree = _repository(tmp_path)

    event = derive_workflow_event(
        repo,
        _environment(repo, event_name="pull_request", base=base, head=head),
    )

    assert event.base_sha == base
    assert event.base_tree_sha == base_tree
    assert event.evaluated_sha == head
    assert event.evaluated_tree_sha == head_tree
    assert event.event_sha == "b" * 40
    assert event.head_repository == "contributor/newsroom"
    assert event.head_repository_id == 999
    rendered = event.as_dict()
    assert rendered["schema_version"] == "newsroom.sdlc.workflow-event.v1"
    assert str(rendered["event_identity"]).startswith("sha256:")


@pytest.mark.parametrize("event_name", ["merge_group", "push"])
def test_merge_group_and_push_bases_are_exact(
    tmp_path: Path,
    event_name: str,
) -> None:
    repo, base, base_tree, head, _ = _repository(tmp_path)

    event = derive_workflow_event(
        repo,
        _environment(repo, event_name=event_name, base=base, head=head),
    )

    assert event.base_sha == base
    assert event.base_tree_sha == base_tree
    assert event.evaluated_sha == head


def test_workflow_dispatch_defaults_to_head_or_accepts_exact_base(tmp_path: Path) -> None:
    repo, base, _, head, head_tree = _repository(tmp_path)

    defaulted = derive_workflow_event(
        repo,
        _environment(
            repo,
            event_name="workflow_dispatch",
            base=base,
            head=head,
        ),
    )
    selected = derive_workflow_event(
        repo,
        _environment(
            repo,
            event_name="workflow_dispatch",
            base=base,
            head=head,
            dispatch_base=base,
        ),
    )

    assert defaulted.base_sha == head
    assert defaulted.base_tree_sha == head_tree
    assert selected.base_sha == base


def test_event_rejects_wrong_base_repository_missing_base_or_head_mismatch(
    tmp_path: Path,
) -> None:
    repo, base, _, head, _ = _repository(tmp_path)
    environment = _environment(repo, event_name="pull_request", base=base, head=head)
    path = Path(environment["GITHUB_EVENT_PATH"])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["pull_request"]["base"]["repo"] = {"full_name": "other/repo", "id": 77}
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(WorkflowEvidenceError, match="event_base_repository"):
        derive_workflow_event(repo, environment)

    environment = _environment(repo, event_name="merge_group", base=base, head=head)
    path = Path(environment["GITHUB_EVENT_PATH"])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["merge_group"]["head_sha"] = "c" * 40
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(WorkflowEvidenceError, match="event_head_sha"):
        derive_workflow_event(repo, environment)

    environment = _environment(repo, event_name="merge_group", base=base, head=head)
    path = Path(environment["GITHUB_EVENT_PATH"])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["merge_group"]["base_sha"] = "d" * 40
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(WorkflowEvidenceError, match="base_commit"):
        derive_workflow_event(repo, environment)


def _jobs() -> dict[str, object]:
    return {
        "total_count": 1,
        "jobs": [
            {
                "id": 987,
                "run_id": 12345,
                "run_attempt": 2,
                "name": "core",
                "created_at": "2026-07-22T12:00:00.000Z",
                "started_at": "2026-07-22T12:00:01.250Z",
                "steps": [
                    {
                        "name": "Sync locked environment",
                        "status": "completed",
                        "started_at": "2026-07-22T12:00:02.000Z",
                        "completed_at": "2026-07-22T12:00:06.500Z",
                    },
                    {
                        "name": "Finalize evidence",
                        "status": "completed",
                        "started_at": "2026-07-22T12:00:40.000Z",
                        "completed_at": "2026-07-22T12:00:41.250Z",
                    },
                ],
            }
        ],
    }


def test_job_telemetry_uses_api_timestamps() -> None:
    telemetry = measure_job_telemetry(
        _jobs(),
        run_id=12345,
        run_attempt=2,
        job_name="core",
        bootstrap_end_step="Sync locked environment",
        finalization_step="Finalize evidence",
    )

    assert telemetry.queue_ms == 1250
    assert telemetry.bootstrap_ms == 5250
    assert telemetry.finalize_ms == 1250
    assert telemetry.as_dict()["telemetry_identity"].startswith("sha256:")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda value: value["jobs"].append(deepcopy(value["jobs"][0])), "job_identity"),
        (
            lambda value: value["jobs"][0]["steps"].append(
                deepcopy(value["jobs"][0]["steps"][0])
            ),
            "step_duplicate",
        ),
        (
            lambda value: value["jobs"][0]["steps"][1].update(status="in_progress"),
            "step_incomplete",
        ),
        (
            lambda value: value["jobs"][0].update(started_at="2026-07-22T11:59:59.000Z"),
            "job_queue_time",
        ),
        (
            lambda value: value["jobs"][0]["steps"][0].update(
                completed_at="2026-07-22T11:59:59.000Z"
            ),
            "job_phase_order",
        ),
    ],
)
def test_job_telemetry_fails_closed_on_ambiguous_or_invalid_api_data(
    mutation,
    reason: str,
) -> None:
    value = _jobs()
    mutation(value)
    with pytest.raises(WorkflowEvidenceError, match=reason):
        measure_job_telemetry(
            value,
            run_id=12345,
            run_attempt=2,
            job_name="core",
            bootstrap_end_step="Sync locked environment",
            finalization_step="Finalize evidence",
        )


def test_serialized_event_and_telemetry_reject_identity_or_duration_tampering(
    tmp_path: Path,
) -> None:
    repo, base, _, head, _ = _repository(tmp_path)
    event = derive_workflow_event(
        repo,
        _environment(repo, event_name="pull_request", base=base, head=head),
    ).as_dict()
    assert validate_workflow_event(event).base_sha == base
    changed_event = deepcopy(event)
    changed_event["base_sha"] = "c" * 40
    with pytest.raises(WorkflowEvidenceError, match="event_identity"):
        validate_workflow_event(changed_event)

    telemetry = measure_job_telemetry(
        _jobs(),
        run_id=12345,
        run_attempt=2,
        job_name="core",
        bootstrap_end_step="Sync locked environment",
        finalization_step="Finalize evidence",
    ).as_dict()
    assert validate_job_telemetry(telemetry).queue_ms == 1250
    changed_telemetry = deepcopy(telemetry)
    changed_telemetry["queue_ms"] = 1251
    with pytest.raises(WorkflowEvidenceError, match="queue_ms"):
        validate_job_telemetry(changed_telemetry)


@pytest.mark.skipif(os.name != "posix", reason="symlink evidence is POSIX-specific")
def test_jobs_input_symlink_is_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps(_jobs()), encoding="utf-8")
    link = tmp_path / "jobs-link.json"
    link.symlink_to(jobs)

    assert workflow_event_main(
        (
            "telemetry",
            "--repo-root",
            str(tmp_path),
            "--jobs-json",
            str(link),
            "--run-id",
            "12345",
            "--run-attempt",
            "2",
            "--job-name",
            "core",
            "--bootstrap-end-step",
            "Sync locked environment",
            "--finalization-step",
            "Finalize evidence",
        )
    ) == 2
    assert capsys.readouterr().err.strip() == (
        "EVIDENCE_MISMATCH:workflow-event:jobs_file"
    )


def test_cli_writes_private_non_overwriting_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, base, _, head, _ = _repository(tmp_path)
    environment = _environment(repo, event_name="pull_request", base=base, head=head)
    monkeypatch.setattr(workflow_event_module.os, "environ", environment)

    arguments = ("event", "--repo-root", str(repo), "--output", "event-output.json")
    assert workflow_event_main(arguments) == 0
    output = repo / "event-output.json"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["base_sha"] == base
    assert payload["evaluated_sha"] == head
    assert capsys.readouterr().err == ""

    original = output.read_bytes()
    assert workflow_event_main(arguments) == 2
    assert output.read_bytes() == original
    assert capsys.readouterr().err.strip() == (
        "EVIDENCE_MISMATCH:workflow-event:output_exists"
    )
