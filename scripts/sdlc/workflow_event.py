from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Mapping, Sequence

from .artifact_envelope import (
    ArtifactProvenanceError,
    GithubRunContext,
    _mapping,
    _safe_machine_file,
    _unique_object,
    _validate_json_depth,
    context_from_environment,
)
from .classify_change import GitRouteError, resolve_commit, resolve_tree
from .emit_evidence import EvidenceError, canonical_json_bytes, sha256_identity


EVENT_SCHEMA_VERSION = "newsroom.sdlc.workflow-event.v1"
TELEMETRY_SCHEMA_VERSION = "newsroom.sdlc.job-telemetry.v1"
_MAX_JOBS_JSON_BYTES = 8 * 1024 * 1024
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SAFE_ID = re.compile(r"[A-Za-z0-9_. -]{1,256}")
_ZERO_SHA = "0" * 40


class WorkflowEvidenceError(ValueError):
    """Raised when GitHub event or job timing evidence is not trustworthy."""


@dataclass(frozen=True)
class WorkflowEvent:
    repository: str
    repository_id: int
    head_repository: str
    head_repository_id: int
    event_name: str
    event_sha: str
    base_sha: str
    base_tree_sha: str
    evaluated_sha: str
    evaluated_tree_sha: str
    ref: str

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_identity": "",
            "repository": self.repository,
            "repository_id": self.repository_id,
            "head_repository": self.head_repository,
            "head_repository_id": self.head_repository_id,
            "event_name": self.event_name,
            "event_sha": self.event_sha,
            "base_sha": self.base_sha,
            "base_tree_sha": self.base_tree_sha,
            "evaluated_sha": self.evaluated_sha,
            "evaluated_tree_sha": self.evaluated_tree_sha,
            "ref": self.ref,
        }
        value["event_identity"] = sha256_identity(
            {key: item for key, item in value.items() if key != "event_identity"}
        )
        return value


@dataclass(frozen=True)
class JobTelemetry:
    run_id: int
    run_attempt: int
    job_id: int
    job_name: str
    queue_ms: int
    bootstrap_ms: int
    finalize_ms: int
    job_created_at: str
    job_started_at: str
    bootstrap_completed_at: str
    finalization_started_at: str
    finalization_completed_at: str

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "telemetry_identity": "",
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "queue_ms": self.queue_ms,
            "bootstrap_ms": self.bootstrap_ms,
            "finalize_ms": self.finalize_ms,
            "job_created_at": self.job_created_at,
            "job_started_at": self.job_started_at,
            "bootstrap_completed_at": self.bootstrap_completed_at,
            "finalization_started_at": self.finalization_started_at,
            "finalization_completed_at": self.finalization_completed_at,
        }
        value["telemetry_identity"] = sha256_identity(
            {key: item for key, item in value.items() if key != "telemetry_identity"}
        )
        return value


def _positive(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkflowEvidenceError(code)
    return value


def _text(value: object, code: str, *, maximum: int = 2048) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise WorkflowEvidenceError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise WorkflowEvidenceError(code)
    return value


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=40)
    if _GIT_SHA.fullmatch(text) is None:
        raise WorkflowEvidenceError(code)
    return text


def _timestamp(value: object, code: str) -> tuple[str, datetime]:
    text = _text(value, code, maximum=64)
    if not text.endswith("Z"):
        raise WorkflowEvidenceError(code)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise WorkflowEvidenceError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise WorkflowEvidenceError(code)
    return text, parsed


def _milliseconds(start: datetime, end: datetime, code: str) -> int:
    if end < start:
        raise WorkflowEvidenceError(code)
    value = int((end - start).total_seconds() * 1000)
    if value > 86_400_000:
        raise WorkflowEvidenceError(code)
    return value


def _event_mapping(path: str | Path) -> Mapping[str, object]:
    try:
        payload = _safe_machine_file(path, maximum=4 * 1024 * 1024, code="event_file")
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        _validate_json_depth(value)
        return _mapping(value, "event_mapping")
    except (ArtifactProvenanceError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowEvidenceError("event_file") from exc


def _base_identity(context: GithubRunContext, event: Mapping[str, object]) -> str:
    if context.event_name == "pull_request":
        pull = _mapping(event.get("pull_request"), "event_pull_request")
        base = _mapping(pull.get("base"), "event_pull_request_base")
        repository = _mapping(base.get("repo"), "event_base_repository")
        if (
            repository.get("full_name") != context.repository
            or repository.get("id") != context.repository_id
        ):
            raise WorkflowEvidenceError("event_base_repository")
        return _sha(base.get("sha"), "event_base_sha")
    if context.event_name == "merge_group":
        group = _mapping(event.get("merge_group"), "event_merge_group")
        if _sha(group.get("head_sha"), "event_head_sha") != context.evaluated_sha:
            raise WorkflowEvidenceError("event_head_sha")
        return _sha(group.get("base_sha"), "event_base_sha")
    if context.event_name == "push":
        if _sha(event.get("after"), "event_after_sha") != context.evaluated_sha:
            raise WorkflowEvidenceError("event_head_sha")
        before = _sha(event.get("before"), "event_base_sha")
        if before == _ZERO_SHA:
            raise WorkflowEvidenceError("event_base_unavailable")
        return before
    if context.event_name == "workflow_dispatch":
        inputs = event.get("inputs")
        if inputs is None:
            return context.evaluated_sha
        mapping = _mapping(inputs, "event_inputs")
        value = mapping.get("base_sha")
        return context.evaluated_sha if value in {None, ""} else _sha(value, "event_base_sha")
    raise WorkflowEvidenceError("event_name")


def derive_workflow_event(
    repo_root: str | Path,
    environment: Mapping[str, str] | None = None,
) -> WorkflowEvent:
    root = Path(repo_root).resolve()
    env = os.environ if environment is None else environment
    try:
        context = context_from_environment(root, env)
    except (ArtifactProvenanceError, GitRouteError, OSError) as exc:
        raise WorkflowEvidenceError("run_context") from exc
    event_path = env.get("GITHUB_EVENT_PATH")
    if not isinstance(event_path, str):
        raise WorkflowEvidenceError("event_file")
    event = _event_mapping(event_path)
    base_sha = _base_identity(context, event)
    try:
        if resolve_commit(root, base_sha) != base_sha:
            raise WorkflowEvidenceError("base_commit")
        base_tree = resolve_tree(root, base_sha)
    except (GitRouteError, OSError) as exc:
        raise WorkflowEvidenceError("base_commit") from exc
    return WorkflowEvent(
        repository=context.repository,
        repository_id=context.repository_id,
        head_repository=context.head_repository,
        head_repository_id=context.head_repository_id,
        event_name=context.event_name,
        event_sha=context.event_sha,
        base_sha=base_sha,
        base_tree_sha=base_tree,
        evaluated_sha=context.evaluated_sha,
        evaluated_tree_sha=context.evaluated_tree_sha,
        ref=context.ref,
    )


def _load_jobs(path: str | Path) -> Mapping[str, object]:
    try:
        payload = _safe_machine_file(
            Path(path).resolve(), maximum=_MAX_JOBS_JSON_BYTES, code="jobs_file"
        )
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        _validate_json_depth(value)
        return _mapping(value, "jobs_mapping")
    except (ArtifactProvenanceError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowEvidenceError("jobs_file") from exc


def measure_job_telemetry(
    jobs_value: object,
    *,
    run_id: int,
    run_attempt: int,
    job_name: str,
    bootstrap_end_step: str,
    finalization_step: str,
) -> JobTelemetry:
    expected_run = _positive(run_id, "run_id")
    expected_attempt = _positive(run_attempt, "run_attempt")
    expected_name = _text(job_name, "job_name", maximum=256)
    if _SAFE_ID.fullmatch(expected_name) is None:
        raise WorkflowEvidenceError("job_name")
    bootstrap_name = _text(bootstrap_end_step, "bootstrap_step", maximum=256)
    final_name = _text(finalization_step, "finalization_step", maximum=256)

    payload = _mapping(jobs_value, "jobs_mapping")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list) or len(jobs) > 100:
        raise WorkflowEvidenceError("jobs_shape")
    matches = [job for job in jobs if isinstance(job, dict) and job.get("name") == expected_name]
    if len(matches) != 1:
        raise WorkflowEvidenceError("job_identity")
    job = _mapping(matches[0], "job")
    if job.get("run_id") not in {None, expected_run}:
        raise WorkflowEvidenceError("job_run_id")
    if job.get("run_attempt") not in {None, expected_attempt}:
        raise WorkflowEvidenceError("job_run_attempt")
    job_id = _positive(job.get("id"), "job_id")
    created_text, created = _timestamp(job.get("created_at"), "job_created_at")
    started_text, started = _timestamp(job.get("started_at"), "job_started_at")
    if started < created:
        raise WorkflowEvidenceError("job_queue_time")

    steps_value = job.get("steps")
    if not isinstance(steps_value, list) or len(steps_value) > 256:
        raise WorkflowEvidenceError("job_steps")
    steps: dict[str, Mapping[str, object]] = {}
    for raw in steps_value:
        step = _mapping(raw, "job_step")
        name = _text(step.get("name"), "step_name", maximum=256)
        if name in steps:
            raise WorkflowEvidenceError("step_duplicate")
        steps[name] = step
    if bootstrap_name not in steps or final_name not in steps:
        raise WorkflowEvidenceError("step_missing")

    bootstrap = steps[bootstrap_name]
    finalization = steps[final_name]
    if bootstrap.get("status") != "completed" or finalization.get("status") != "completed":
        raise WorkflowEvidenceError("step_incomplete")
    bootstrap_text, bootstrap_completed = _timestamp(
        bootstrap.get("completed_at"), "bootstrap_completed_at"
    )
    final_started_text, final_started = _timestamp(
        finalization.get("started_at"), "finalization_started_at"
    )
    final_completed_text, final_completed = _timestamp(
        finalization.get("completed_at"), "finalization_completed_at"
    )
    if bootstrap_completed < started or final_started < bootstrap_completed:
        raise WorkflowEvidenceError("job_phase_order")

    return JobTelemetry(
        run_id=expected_run,
        run_attempt=expected_attempt,
        job_id=job_id,
        job_name=expected_name,
        queue_ms=_milliseconds(created, started, "queue_ms"),
        bootstrap_ms=_milliseconds(started, bootstrap_completed, "bootstrap_ms"),
        finalize_ms=_milliseconds(final_started, final_completed, "finalize_ms"),
        job_created_at=created_text,
        job_started_at=started_text,
        bootstrap_completed_at=bootstrap_text,
        finalization_started_at=final_started_text,
        finalization_completed_at=final_completed_text,
    )


def _safe_output(root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
        or candidate.suffix != ".json"
    ):
        raise WorkflowEvidenceError("output_path")
    current = root
    for part in candidate.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise WorkflowEvidenceError("output_parent")
    parent = current.resolve()
    if not parent.is_relative_to(root) or not parent.is_dir():
        raise WorkflowEvidenceError("output_parent")
    path = current / candidate.name
    if path.exists() or path.is_symlink():
        raise WorkflowEvidenceError("output_exists")
    return path


def _publish(path: Path, value: object) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
            linked = True
            directory = os.open(
                path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except FileExistsError as exc:
            raise WorkflowEvidenceError("output_exists") from exc
        except OSError as exc:
            if linked:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise WorkflowEvidenceError("output_publish") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive exact GitHub workflow evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)

    event_parser = subparsers.add_parser("event")
    event_parser.add_argument("--repo-root", default=".")
    event_parser.add_argument("--output")

    telemetry_parser = subparsers.add_parser("telemetry")
    telemetry_parser.add_argument("--repo-root", default=".")
    telemetry_parser.add_argument("--jobs-json", required=True)
    telemetry_parser.add_argument("--run-id", type=int, required=True)
    telemetry_parser.add_argument("--run-attempt", type=int, required=True)
    telemetry_parser.add_argument("--job-name", required=True)
    telemetry_parser.add_argument("--bootstrap-end-step", required=True)
    telemetry_parser.add_argument("--finalization-step", required=True)
    telemetry_parser.add_argument("--output")

    arguments = parser.parse_args(argv)
    root = Path(arguments.repo_root).resolve()
    try:
        if arguments.command == "event":
            value = derive_workflow_event(root).as_dict()
        else:
            value = measure_job_telemetry(
                _load_jobs(arguments.jobs_json),
                run_id=arguments.run_id,
                run_attempt=arguments.run_attempt,
                job_name=arguments.job_name,
                bootstrap_end_step=arguments.bootstrap_end_step,
                finalization_step=arguments.finalization_step,
            ).as_dict()
        if arguments.output:
            _publish(_safe_output(root, arguments.output), value)
        else:
            sys.stdout.write(canonical_json_bytes(value).decode("utf-8") + "\n")
    except (
        WorkflowEvidenceError,
        ArtifactProvenanceError,
        EvidenceError,
        GitRouteError,
        OSError,
        UnicodeError,
    ) as exc:
        reason = str(exc) if isinstance(exc, WorkflowEvidenceError) and str(exc) else type(exc).__name__
        print(f"EVIDENCE_MISMATCH:workflow-event:{reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
