from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

import scripts.sdlc.artifact_envelope as envelope_module
from scripts.sdlc.artifact_envelope import (
    ArtifactProvenanceError,
    artifact_name,
    context_from_environment,
    create_envelope,
    main as envelope_main,
    validate_envelope,
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


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "sdlc@example.invalid")
    _git(repo, "config", "user.name", "SDLC Test")
    (repo / "tracked.txt").write_text("exact\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "exact")
    head = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    return repo, head, tree


def _event(
    repo: Path,
    head: str,
    *,
    event_name: str = "pull_request",
    head_repository: str = "fol2/newsroom",
    head_repository_id: int = int(REPOSITORY_ID),
) -> Path:
    path = repo / "event.json"
    if event_name == "pull_request":
        value: dict[str, object] = {
            "repository": {"full_name": "fol2/newsroom", "id": int(REPOSITORY_ID)},
            "pull_request": {
                "head": {
                    "sha": head,
                    "repo": {
                        "full_name": head_repository,
                        "id": head_repository_id,
                    },
                }
            },
        }
    elif event_name == "merge_group":
        value = {
            "repository": {"full_name": "fol2/newsroom", "id": int(REPOSITORY_ID)},
            "merge_group": {"head_sha": head},
        }
    elif event_name == "push":
        value = {
            "repository": {"full_name": "fol2/newsroom", "id": int(REPOSITORY_ID)},
            "after": head,
        }
    else:
        value = {
            "repository": {"full_name": "fol2/newsroom", "id": int(REPOSITORY_ID)}
        }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _environment(
    repo: Path,
    head: str,
    *,
    event_name: str = "pull_request",
    job: str = "route",
    head_repository: str = "fol2/newsroom",
    head_repository_id: int = int(REPOSITORY_ID),
) -> dict[str, str]:
    event = _event(
        repo,
        head,
        event_name=event_name,
        head_repository=head_repository,
        head_repository_id=head_repository_id,
    )
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "fol2/newsroom",
        "GITHUB_REPOSITORY_ID": REPOSITORY_ID,
        "GITHUB_RUN_ID": "123456",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_JOB": job,
        "GITHUB_WORKFLOW_REF": (
            "fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge"
        ),
        "GITHUB_WORKFLOW_SHA": "a" * 40,
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_SHA": head if event_name in {"push", "workflow_dispatch"} else "b" * 40,
        "GITHUB_REF": "refs/pull/10/merge",
        "RUNNER_ENVIRONMENT": "github-hosted",
    }


def _write_json(root: Path, name: str, value: dict[str, object]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _route(head: str, tree: str) -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.route.v1",
        "head_sha": head,
        "head_tree_sha": tree,
    }


def _command_run(result: str = "PASS") -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.command-run.v1",
        "command_spec_digest": "sha256:" + "1" * 64,
        "gate_run": {
            "schema_version": "newsroom.sdlc.gate-run.v1",
            "result": result,
        },
    }


def _junit() -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.junit-summary.v1",
        "outcome": "PASS",
    }


def _evidence(head: str, tree: str) -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.evidence.v1",
        "repository": "fol2/newsroom",
        "head_sha": head,
        "tree_sha": tree,
    }


def test_pull_request_context_uses_event_head_not_merge_sha(tmp_path: Path) -> None:
    repo, head, tree = _repository(tmp_path)
    environment = _environment(repo, head)

    context = context_from_environment(repo, environment)

    assert context.event_sha == "b" * 40
    assert context.evaluated_sha == head
    assert context.evaluated_tree_sha == tree
    assert context.repository_id == int(REPOSITORY_ID)
    assert context.head_repository == "fol2/newsroom"
    assert context.run_id == 123456
    assert context.run_attempt == 2
    assert artifact_name(context) == f"newsroom-sdlc-route-{head}"


def test_fork_head_identity_is_retained_without_changing_base_repository(
    tmp_path: Path,
) -> None:
    repo, head, _ = _repository(tmp_path)
    context = context_from_environment(
        repo,
        _environment(
            repo,
            head,
            head_repository="contributor/newsroom",
            head_repository_id=999,
        ),
    )

    assert context.repository == "fol2/newsroom"
    assert context.repository_id == int(REPOSITORY_ID)
    assert context.head_repository == "contributor/newsroom"
    assert context.head_repository_id == 999


def test_merge_group_and_push_heads_are_derived_from_event(tmp_path: Path) -> None:
    for event_name in ("merge_group", "push", "workflow_dispatch"):
        repo, head, _ = _repository(tmp_path / event_name)
        context = context_from_environment(
            repo,
            _environment(repo, head, event_name=event_name),
        )
        assert context.evaluated_sha == head


def test_context_fails_closed_on_wrong_checkout_or_tracked_drift(tmp_path: Path) -> None:
    repo, head, _ = _repository(tmp_path)
    environment = _environment(repo, head)
    (repo / "tracked.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(ArtifactProvenanceError, match="tracked_checkout_drift"):
        context_from_environment(repo, environment)

    _git(repo, "checkout", "--", "tracked.txt")
    (repo / "untracked.json").write_text("{}", encoding="utf-8")
    assert context_from_environment(repo, environment).evaluated_sha == head

    environment = _environment(repo, "c" * 40)
    with pytest.raises(ArtifactProvenanceError, match="checkout_head_mismatch"):
        context_from_environment(repo, environment)


def test_context_rejects_non_github_or_inconsistent_machine_identity(
    tmp_path: Path,
) -> None:
    repo, head, _ = _repository(tmp_path)
    baseline = _environment(repo, head)
    cases: list[tuple[str, str, str]] = [
        ("GITHUB_ACTIONS", "false", "github_actions_required"),
        ("GITHUB_REPOSITORY", "other/repo", "repository"),
        ("GITHUB_RUN_ID", "01", "run_id"),
        ("GITHUB_JOB", "bad:job", "job_id"),
        ("GITHUB_WORKFLOW_REF", "other.yml@main", "workflow_ref"),
        ("RUNNER_ENVIRONMENT", "mystery", "runner_environment"),
    ]
    for name, value, reason in cases:
        environment = dict(baseline)
        environment[name] = value
        with pytest.raises(ArtifactProvenanceError, match=reason):
            context_from_environment(repo, environment)


def test_event_repository_identity_must_match_machine_environment(
    tmp_path: Path,
) -> None:
    repo, head, _ = _repository(tmp_path)
    environment = _environment(repo, head)
    event_path = Path(environment["GITHUB_EVENT_PATH"])
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["repository"] = {"full_name": "other/repo", "id": 77}
    event_path.write_text(json.dumps(event), encoding="utf-8")

    with pytest.raises(ArtifactProvenanceError, match="event_repository"):
        context_from_environment(repo, environment)


def test_envelope_is_deterministic_and_binds_exact_file_bytes(tmp_path: Path) -> None:
    repo, head, tree = _repository(tmp_path)
    context = context_from_environment(repo, _environment(repo, head, job="core"))
    artifact_root = repo / "artifact"
    _write_json(artifact_root, "run-a.json", _command_run())
    _write_json(artifact_root, "run-b.json", _command_run("FAIL"))
    _write_json(artifact_root, "junit.json", _junit())
    _write_json(artifact_root, "evidence.json", _evidence(head, tree))

    files = (
        ("command_run", "run-a.json"),
        ("command_run", "run-b.json"),
        ("junit_summary", "junit.json"),
        ("gate_evidence", "evidence.json"),
    )
    first = create_envelope(
        repo_root=repo,
        artifact_root=artifact_root,
        context=context,
        files=files,
    )
    second = create_envelope(
        repo_root=repo,
        artifact_root=artifact_root,
        context=context,
        files=reversed(files),
    )

    assert first == second
    assert len(first.entries) == 4
    assert [entry.role for entry in first.entries].count("command_run") == 2
    assert validate_envelope(first.as_dict()) == first
    original_identity = first.envelope_identity

    _write_json(artifact_root, "run-a.json", _command_run("FAIL"))
    changed = create_envelope(
        repo_root=repo,
        artifact_root=artifact_root,
        context=context,
        files=files,
    )
    assert changed.envelope_identity != original_identity


def test_route_and_gate_evidence_must_match_evaluated_tree(tmp_path: Path) -> None:
    repo, head, tree = _repository(tmp_path)
    context = context_from_environment(repo, _environment(repo, head))
    artifact_root = repo / "artifact"
    _write_json(artifact_root, "route.json", _route("0" * 40, tree))
    with pytest.raises(ArtifactProvenanceError, match="artifact_identity"):
        create_envelope(
            repo_root=repo,
            artifact_root=artifact_root,
            context=context,
            files=(("route", "route.json"),),
        )

    _write_json(artifact_root, "evidence.json", _evidence(head, "0" * 40))
    with pytest.raises(ArtifactProvenanceError, match="artifact_identity"):
        create_envelope(
            repo_root=repo,
            artifact_root=artifact_root,
            context=context,
            files=(("gate_evidence", "evidence.json"),),
        )


def test_unknown_role_duplicate_path_and_envelope_output_are_rejected(
    tmp_path: Path,
) -> None:
    repo, head, tree = _repository(tmp_path)
    context = context_from_environment(repo, _environment(repo, head))
    artifact_root = repo / "artifact"
    _write_json(artifact_root, "route.json", _route(head, tree))
    _write_json(artifact_root, "envelope.json", _route(head, tree))

    with pytest.raises(ArtifactProvenanceError, match="artifact_schema"):
        create_envelope(
            repo_root=repo,
            artifact_root=artifact_root,
            context=context,
            files=(("unknown", "route.json"),),
        )
    with pytest.raises(ArtifactProvenanceError, match="artifact_path"):
        create_envelope(
            repo_root=repo,
            artifact_root=artifact_root,
            context=context,
            files=(("route", "route.json"), ("route", "route.json")),
        )
    with pytest.raises(ArtifactProvenanceError, match="artifact_path"):
        create_envelope(
            repo_root=repo,
            artifact_root=artifact_root,
            context=context,
            files=(("route", "envelope.json"),),
        )


@pytest.mark.skipif(os.name != "posix", reason="filesystem type evidence is POSIX-specific")
def test_artifact_root_entry_symlinks_and_fifo_are_rejected(tmp_path: Path) -> None:
    repo, head, tree = _repository(tmp_path)
    context = context_from_environment(repo, _environment(repo, head))
    real_root = repo / "real-artifact"
    _write_json(real_root, "route.json", _route(head, tree))
    linked_root = repo / "linked-artifact"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(ArtifactProvenanceError, match="artifact_root"):
        create_envelope(
            repo_root=repo,
            artifact_root=linked_root,
            context=context,
            files=(("route", "route.json"),),
        )

    outside = repo / "outside.json"
    outside.write_text(json.dumps(_route(head, tree)), encoding="utf-8")
    (real_root / "link.json").symlink_to(outside)
    with pytest.raises(ArtifactProvenanceError, match="artifact_symlink"):
        create_envelope(
            repo_root=repo,
            artifact_root=real_root,
            context=context,
            files=(("route", "link.json"),),
        )

    fifo = real_root / "fifo.json"
    os.mkfifo(fifo)
    with pytest.raises(ArtifactProvenanceError, match="artifact_file"):
        create_envelope(
            repo_root=repo,
            artifact_root=real_root,
            context=context,
            files=(("route", "fifo.json"),),
        )


def test_envelope_validation_rejects_context_entry_and_identity_tampering(
    tmp_path: Path,
) -> None:
    repo, head, tree = _repository(tmp_path)
    context = context_from_environment(repo, _environment(repo, head))
    artifact_root = repo / "artifact"
    _write_json(artifact_root, "route.json", _route(head, tree))
    envelope = create_envelope(
        repo_root=repo,
        artifact_root=artifact_root,
        context=context,
        files=(("route", "route.json"),),
    ).as_dict()

    tampered = deepcopy(envelope)
    tampered["context"]["repository"] = "other/repo"  # type: ignore[index]
    with pytest.raises(ArtifactProvenanceError):
        validate_envelope(tampered)

    tampered = deepcopy(envelope)
    tampered["entries"][0]["content_schema_version"] = "wrong"  # type: ignore[index]
    with pytest.raises(ArtifactProvenanceError):
        validate_envelope(tampered)

    tampered = deepcopy(envelope)
    tampered["envelope_identity"] = "sha256:" + "0" * 64
    with pytest.raises(ArtifactProvenanceError, match="envelope_identity"):
        validate_envelope(tampered)


def test_cli_publishes_private_non_overwriting_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, head, tree = _repository(tmp_path)
    environment = _environment(repo, head)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    artifact_root = repo / "artifact"
    _write_json(artifact_root, "route.json", _route(head, tree))

    arguments = (
        "--repo-root",
        str(repo),
        "--artifact-root",
        "artifact",
        "--file",
        "route=route.json",
    )
    assert envelope_main(arguments) == 0
    output = json.loads(capsys.readouterr().out)
    envelope_path = artifact_root / "envelope.json"
    assert output["artifact_name"] == f"newsroom-sdlc-route-{head}"
    assert output["envelope_identity"].startswith("sha256:")
    assert stat.S_IMODE(envelope_path.stat().st_mode) == 0o600
    validate_envelope(json.loads(envelope_path.read_text(encoding="utf-8")))

    original = envelope_path.read_bytes()
    assert envelope_main(arguments) == 2
    assert envelope_path.read_bytes() == original
    assert capsys.readouterr().err.strip() == (
        "EVIDENCE_MISMATCH:artifact-envelope:output_exists"
    )


def test_publish_failure_does_not_leave_authoritative_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "envelope.json"
    original_fsync = os.fsync
    calls = 0

    def fail_directory_sync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated")
        original_fsync(descriptor)

    monkeypatch.setattr(envelope_module.os, "fsync", fail_directory_sync)
    with pytest.raises(ArtifactProvenanceError, match="output_publish"):
        envelope_module._publish(output, b"{}\n")
    assert not output.exists()
