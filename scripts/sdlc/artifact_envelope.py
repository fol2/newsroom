from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Iterable, Mapping, Sequence

from .classify_change import GitRouteError, resolve_commit, resolve_tree
from .emit_evidence import EvidenceError, canonical_json_bytes, sha256_identity


CONTEXT_SCHEMA_VERSION = "newsroom.sdlc.github-run-context.v1"
ENTRY_SCHEMA_VERSION = "newsroom.sdlc.artifact-entry.v1"
ENVELOPE_SCHEMA_VERSION = "newsroom.sdlc.artifact-envelope.v1"
_REPOSITORY = "fol2/newsroom"
_MAX_EVENT_BYTES = 4 * 1024 * 1024
_MAX_ARTIFACT_FILES = 16
_MAX_ARTIFACT_FILE_BYTES = 32 * 1024 * 1024
_MAX_ARTIFACT_TOTAL_BYTES = 96 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_SCHEMA_BY_ROLE = {
    "route": "newsroom.sdlc.route.v1",
    "command_run": "newsroom.sdlc.command-run.v1",
    "junit_summary": "newsroom.sdlc.junit-summary.v1",
    "gate_evidence": "newsroom.sdlc.evidence.v1",
}
_ALLOWED_EVENTS = frozenset({"pull_request", "merge_group", "workflow_dispatch", "push"})
_CONTEXT_KEYS = frozenset(
    {
        "schema_version",
        "repository",
        "repository_id",
        "head_repository",
        "head_repository_id",
        "run_id",
        "run_attempt",
        "job_id",
        "workflow_ref",
        "workflow_sha",
        "event_name",
        "event_sha",
        "evaluated_sha",
        "evaluated_tree_sha",
        "ref",
        "runner_environment",
    }
)
_ENTRY_KEYS = frozenset(
    {
        "schema_version",
        "role",
        "path",
        "content_schema_version",
        "size_bytes",
        "digest",
    }
)


class ArtifactProvenanceError(ValueError):
    """Raised when a job cannot produce trustworthy artifact provenance."""


@dataclass(frozen=True)
class GithubRunContext:
    repository: str
    repository_id: int
    head_repository: str
    head_repository_id: int
    run_id: int
    run_attempt: int
    job_id: str
    workflow_ref: str
    workflow_sha: str
    event_name: str
    event_sha: str
    evaluated_sha: str
    evaluated_tree_sha: str
    ref: str
    runner_environment: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "repository": self.repository,
            "repository_id": self.repository_id,
            "head_repository": self.head_repository,
            "head_repository_id": self.head_repository_id,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "job_id": self.job_id,
            "workflow_ref": self.workflow_ref,
            "workflow_sha": self.workflow_sha,
            "event_name": self.event_name,
            "event_sha": self.event_sha,
            "evaluated_sha": self.evaluated_sha,
            "evaluated_tree_sha": self.evaluated_tree_sha,
            "ref": self.ref,
            "runner_environment": self.runner_environment,
        }


@dataclass(frozen=True)
class ArtifactEntry:
    role: str
    path: str
    schema_version: str
    size_bytes: int
    digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": ENTRY_SCHEMA_VERSION,
            "role": self.role,
            "path": self.path,
            "content_schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_name: str
    context: GithubRunContext
    entries: tuple[ArtifactEntry, ...]
    envelope_identity: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "envelope_identity": self.envelope_identity,
            "artifact_name": self.artifact_name,
            "context": self.context.as_dict(),
            "entries": [entry.as_dict() for entry in self.entries],
        }


def _positive_integer(value: object, code: str) -> int:
    if isinstance(value, bool):
        raise ArtifactProvenanceError(code)
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ArtifactProvenanceError(code) from exc
    if result <= 0 or str(result) != str(value):
        raise ArtifactProvenanceError(code)
    return result


def _text(value: object, code: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ArtifactProvenanceError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ArtifactProvenanceError(code)
    return value


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=40)
    if _GIT_SHA.fullmatch(text) is None:
        raise ArtifactProvenanceError(code)
    return text


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ArtifactProvenanceError(code)
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if name in value:
            raise ArtifactProvenanceError("json_duplicate_key")
        value[name] = item
    return value


def _validate_json_depth(value: object, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ArtifactProvenanceError("json_depth")
    if isinstance(value, dict):
        for item in value.values():
            _validate_json_depth(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_json_depth(item, depth=depth + 1)


def _safe_machine_file(path: str | Path, *, maximum: int, code: str) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ArtifactProvenanceError(code)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ArtifactProvenanceError(f"{code}_symlink")
    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise ArtifactProvenanceError(code) from exc
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= maximum:
        raise ArtifactProvenanceError(code)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ArtifactProvenanceError(code) from exc
    try:
        current_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(current_metadata.st_mode)
            or not 0 < current_metadata.st_size <= maximum
        ):
            raise ArtifactProvenanceError(code)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(maximum + 1)
    finally:
        os.close(descriptor)
    if not payload or len(payload) > maximum:
        raise ArtifactProvenanceError(code)
    return payload


def _load_event(path: str | Path) -> Mapping[str, object]:
    payload = _safe_machine_file(path, maximum=_MAX_EVENT_BYTES, code="event_file")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactProvenanceError("event_json") from exc
    _validate_json_depth(value)
    return _mapping(value, "event_mapping")


def _derived_head(
    event_name: str,
    event: Mapping[str, object],
    *,
    repository: str,
    repository_id: int,
    event_sha: str,
) -> tuple[str, str, int]:
    if event_name == "pull_request":
        pull_request = _mapping(event.get("pull_request"), "event_pull_request")
        head = _mapping(pull_request.get("head"), "event_pull_request_head")
        head_repository = _mapping(head.get("repo"), "event_head_repository")
        return (
            _sha(head.get("sha"), "event_head_sha"),
            _text(head_repository.get("full_name"), "event_head_repository_name"),
            _positive_integer(head_repository.get("id"), "event_head_repository_id"),
        )
    if event_name == "merge_group":
        merge_group = _mapping(event.get("merge_group"), "event_merge_group")
        return (
            _sha(merge_group.get("head_sha"), "event_head_sha"),
            repository,
            repository_id,
        )
    if event_name == "push":
        after = _sha(event.get("after"), "event_after_sha")
        if after != event_sha:
            raise ArtifactProvenanceError("event_sha_mismatch")
        return after, repository, repository_id
    if event_name == "workflow_dispatch":
        return event_sha, repository, repository_id
    raise ArtifactProvenanceError("event_name")


def _validate_context(context: GithubRunContext) -> GithubRunContext:
    if context.repository != _REPOSITORY:
        raise ArtifactProvenanceError("repository")
    _positive_integer(context.repository_id, "repository_id")
    _text(context.head_repository, "head_repository")
    _positive_integer(context.head_repository_id, "head_repository_id")
    _positive_integer(context.run_id, "run_id")
    _positive_integer(context.run_attempt, "run_attempt")
    job_id = _text(context.job_id, "job_id", maximum=128)
    if _SAFE_ID.fullmatch(job_id) is None:
        raise ArtifactProvenanceError("job_id")
    workflow_ref = _text(context.workflow_ref, "workflow_ref", maximum=2048)
    if not workflow_ref.startswith(f"{context.repository}/.github/workflows/"):
        raise ArtifactProvenanceError("workflow_ref")
    _sha(context.workflow_sha, "workflow_sha")
    if _text(context.event_name, "event_name", maximum=64) not in _ALLOWED_EVENTS:
        raise ArtifactProvenanceError("event_name")
    _sha(context.event_sha, "event_sha")
    _sha(context.evaluated_sha, "evaluated_sha")
    _sha(context.evaluated_tree_sha, "evaluated_tree_sha")
    _text(context.ref, "ref", maximum=2048)
    if _text(
        context.runner_environment, "runner_environment", maximum=64
    ) not in {"github-hosted", "self-hosted"}:
        raise ArtifactProvenanceError("runner_environment")
    return context


def context_from_environment(
    repo_root: str | Path,
    environment: Mapping[str, str] | None = None,
) -> GithubRunContext:
    root = Path(repo_root).resolve()
    env = os.environ if environment is None else environment
    if env.get("GITHUB_ACTIONS") != "true":
        raise ArtifactProvenanceError("github_actions_required")
    repository = _text(env.get("GITHUB_REPOSITORY"), "repository")
    if repository != _REPOSITORY:
        raise ArtifactProvenanceError("repository")
    repository_id = _positive_integer(env.get("GITHUB_REPOSITORY_ID"), "repository_id")
    event_name = _text(env.get("GITHUB_EVENT_NAME"), "event_name", maximum=64)
    if event_name not in _ALLOWED_EVENTS:
        raise ArtifactProvenanceError("event_name")
    event_sha = _sha(env.get("GITHUB_SHA"), "event_sha")
    event = _load_event(_text(env.get("GITHUB_EVENT_PATH"), "event_path", maximum=4096))
    event_repository = _mapping(event.get("repository"), "event_repository")
    if (
        event_repository.get("full_name") != repository
        or _positive_integer(event_repository.get("id"), "event_repository_id")
        != repository_id
    ):
        raise ArtifactProvenanceError("event_repository")
    evaluated_sha, head_repository, head_repository_id = _derived_head(
        event_name,
        event,
        repository=repository,
        repository_id=repository_id,
        event_sha=event_sha,
    )
    current_head = resolve_commit(root, "HEAD")
    if current_head != evaluated_sha:
        raise ArtifactProvenanceError("checkout_head_mismatch")
    evaluated_tree_sha = resolve_tree(root, evaluated_sha)
    completed = subprocess.run(
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=no"),
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise ArtifactProvenanceError("checkout_status")
    if completed.stdout:
        raise ArtifactProvenanceError("tracked_checkout_drift")
    job_id = _text(env.get("GITHUB_JOB"), "job_id", maximum=128)
    if _SAFE_ID.fullmatch(job_id) is None:
        raise ArtifactProvenanceError("job_id")
    workflow_sha = _sha(env.get("GITHUB_WORKFLOW_SHA"), "workflow_sha")
    workflow_ref = _text(env.get("GITHUB_WORKFLOW_REF"), "workflow_ref", maximum=2048)
    if not workflow_ref.startswith(f"{repository}/.github/workflows/"):
        raise ArtifactProvenanceError("workflow_ref")
    runner_environment = _text(
        env.get("RUNNER_ENVIRONMENT"), "runner_environment", maximum=64
    )
    context = GithubRunContext(
        repository=repository,
        repository_id=repository_id,
        head_repository=head_repository,
        head_repository_id=head_repository_id,
        run_id=_positive_integer(env.get("GITHUB_RUN_ID"), "run_id"),
        run_attempt=_positive_integer(env.get("GITHUB_RUN_ATTEMPT"), "run_attempt"),
        job_id=job_id,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
        event_name=event_name,
        event_sha=event_sha,
        evaluated_sha=evaluated_sha,
        evaluated_tree_sha=evaluated_tree_sha,
        ref=_text(env.get("GITHUB_REF"), "ref", maximum=2048),
        runner_environment=runner_environment,
    )
    return _validate_context(context)


def artifact_name(context: GithubRunContext) -> str:
    _validate_context(context)
    value = (
        f"newsroom-sdlc-{context.run_id}-{context.run_attempt}-"
        f"{context.job_id}-{context.evaluated_sha}"
    )
    if len(value) > 255:
        raise ArtifactProvenanceError("artifact_name")
    return value


def _relative_parts(repository_root: Path, candidate: Path, code: str) -> tuple[str, ...]:
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(repository_root)
        except ValueError as exc:
            raise ArtifactProvenanceError(code) from exc
    else:
        relative = candidate
    if (
        not relative.parts
        or ".." in relative.parts
        or "\\" in str(candidate)
    ):
        raise ArtifactProvenanceError(code)
    return relative.parts


def _artifact_root(repository_root: Path, value: str | Path) -> Path:
    parts = _relative_parts(repository_root, Path(value), "artifact_root")
    current = repository_root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise ArtifactProvenanceError("artifact_root")
    resolved = current.resolve()
    if not resolved.is_relative_to(repository_root) or not resolved.is_dir():
        raise ArtifactProvenanceError("artifact_root")
    return resolved


def _safe_artifact_path(root: Path, relative: str | Path) -> tuple[str, Path]:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
    ):
        raise ArtifactProvenanceError("artifact_path")
    current = root
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise ArtifactProvenanceError("artifact_symlink")
    resolved = current.resolve()
    if not resolved.is_relative_to(root):
        raise ArtifactProvenanceError("artifact_path")
    return resolved.relative_to(root).as_posix(), current


def _normalized_artifact_path(value: object) -> str:
    text = _text(value, "entry_path", maximum=1024)
    candidate = Path(text)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in text
        or candidate.as_posix() != text
        or text == "envelope.json"
    ):
        raise ArtifactProvenanceError("entry_path")
    return text


def _read_artifact_file(root: Path, relative: str) -> tuple[bytes, str]:
    normalized, path = _safe_artifact_path(root, relative)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ArtifactProvenanceError("artifact_file") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not 0 < metadata.st_size <= _MAX_ARTIFACT_FILE_BYTES
    ):
        raise ArtifactProvenanceError("artifact_file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactProvenanceError("artifact_file") from exc
    try:
        current = os.fstat(descriptor)
        if (
            not stat.S_ISREG(current.st_mode)
            or not 0 < current.st_size <= _MAX_ARTIFACT_FILE_BYTES
        ):
            raise ArtifactProvenanceError("artifact_file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(_MAX_ARTIFACT_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if not payload or len(payload) > _MAX_ARTIFACT_FILE_BYTES:
        raise ArtifactProvenanceError("artifact_file")
    return payload, normalized


def _load_json_artifact(payload: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactProvenanceError("artifact_json") from exc
    _validate_json_depth(value)
    return _mapping(value, "artifact_json")


def _cross_check_artifact(
    role: str,
    value: Mapping[str, object],
    context: GithubRunContext,
) -> str:
    expected_schema = _SCHEMA_BY_ROLE.get(role)
    if expected_schema is None or value.get("schema_version") != expected_schema:
        raise ArtifactProvenanceError("artifact_schema")
    if role == "route":
        if (
            value.get("head_sha") != context.evaluated_sha
            or value.get("head_tree_sha") != context.evaluated_tree_sha
        ):
            raise ArtifactProvenanceError("artifact_identity")
    elif role == "gate_evidence":
        if (
            value.get("repository") != context.repository
            or value.get("head_sha") != context.evaluated_sha
            or value.get("tree_sha") != context.evaluated_tree_sha
        ):
            raise ArtifactProvenanceError("artifact_identity")
    elif role == "command_run":
        gate_run = _mapping(value.get("gate_run"), "artifact_gate_run")
        if gate_run.get("schema_version") != "newsroom.sdlc.gate-run.v1":
            raise ArtifactProvenanceError("artifact_schema")
        digest = value.get("command_spec_digest")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ArtifactProvenanceError("artifact_identity")
    return expected_schema


def create_envelope(
    *,
    repo_root: str | Path,
    artifact_root: str | Path,
    context: GithubRunContext,
    files: Iterable[tuple[str, str]],
) -> ArtifactEnvelope:
    repository_root = Path(repo_root).resolve()
    _validate_context(context)
    root = _artifact_root(repository_root, artifact_root)
    selected = tuple(files)
    if not 0 < len(selected) <= _MAX_ARTIFACT_FILES:
        raise ArtifactProvenanceError("artifact_count")
    paths: set[str] = set()
    entries: list[ArtifactEntry] = []
    total = 0
    for role_value, path_value in selected:
        role = _text(role_value, "artifact_role", maximum=64)
        if _SAFE_ID.fullmatch(role) is None:
            raise ArtifactProvenanceError("artifact_role")
        payload, normalized = _read_artifact_file(root, path_value)
        if normalized == "envelope.json" or normalized in paths:
            raise ArtifactProvenanceError("artifact_path")
        value = _load_json_artifact(payload)
        schema_version = _cross_check_artifact(role, value, context)
        total += len(payload)
        if total > _MAX_ARTIFACT_TOTAL_BYTES:
            raise ArtifactProvenanceError("artifact_total_size")
        paths.add(normalized)
        entries.append(
            ArtifactEntry(
                role=role,
                path=normalized,
                schema_version=schema_version,
                size_bytes=len(payload),
                digest="sha256:" + hashlib.sha256(payload).hexdigest(),
            )
        )
    ordered = tuple(sorted(entries, key=lambda entry: (entry.role, entry.path)))
    identity_inputs = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "artifact_name": artifact_name(context),
        "context": context.as_dict(),
        "entries": [entry.as_dict() for entry in ordered],
    }
    try:
        identity = sha256_identity(identity_inputs)
    except EvidenceError as exc:
        raise ArtifactProvenanceError("envelope_identity") from exc
    return ArtifactEnvelope(
        artifact_name=artifact_name(context),
        context=context,
        entries=ordered,
        envelope_identity=identity,
    )


def _context_from_mapping(value: object) -> GithubRunContext:
    context_value = _mapping(value, "envelope_context")
    if frozenset(context_value) != _CONTEXT_KEYS:
        raise ArtifactProvenanceError("envelope_context")
    if context_value.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        raise ArtifactProvenanceError("envelope_context")
    return _validate_context(
        GithubRunContext(
            repository=_text(context_value.get("repository"), "repository"),
            repository_id=_positive_integer(
                context_value.get("repository_id"), "repository_id"
            ),
            head_repository=_text(
                context_value.get("head_repository"), "head_repository"
            ),
            head_repository_id=_positive_integer(
                context_value.get("head_repository_id"), "head_repository_id"
            ),
            run_id=_positive_integer(context_value.get("run_id"), "run_id"),
            run_attempt=_positive_integer(
                context_value.get("run_attempt"), "run_attempt"
            ),
            job_id=_text(context_value.get("job_id"), "job_id", maximum=128),
            workflow_ref=_text(
                context_value.get("workflow_ref"), "workflow_ref", maximum=2048
            ),
            workflow_sha=_sha(context_value.get("workflow_sha"), "workflow_sha"),
            event_name=_text(
                context_value.get("event_name"), "event_name", maximum=64
            ),
            event_sha=_sha(context_value.get("event_sha"), "event_sha"),
            evaluated_sha=_sha(
                context_value.get("evaluated_sha"), "evaluated_sha"
            ),
            evaluated_tree_sha=_sha(
                context_value.get("evaluated_tree_sha"), "evaluated_tree_sha"
            ),
            ref=_text(context_value.get("ref"), "ref", maximum=2048),
            runner_environment=_text(
                context_value.get("runner_environment"),
                "runner_environment",
                maximum=64,
            ),
        )
    )


def validate_envelope(value: object) -> ArtifactEnvelope:
    mapping = _mapping(value, "envelope")
    if frozenset(mapping) != {
        "schema_version",
        "envelope_identity",
        "artifact_name",
        "context",
        "entries",
    }:
        raise ArtifactProvenanceError("envelope_shape")
    if mapping.get("schema_version") != ENVELOPE_SCHEMA_VERSION:
        raise ArtifactProvenanceError("envelope_schema")
    context = _context_from_mapping(mapping.get("context"))
    raw_entries = mapping.get("entries")
    if not isinstance(raw_entries, list) or not 0 < len(raw_entries) <= _MAX_ARTIFACT_FILES:
        raise ArtifactProvenanceError("envelope_entries")
    entries: list[ArtifactEntry] = []
    total = 0
    for raw in raw_entries:
        item = _mapping(raw, "envelope_entry")
        if frozenset(item) != _ENTRY_KEYS or item.get("schema_version") != ENTRY_SCHEMA_VERSION:
            raise ArtifactProvenanceError("envelope_entry")
        role = _text(item.get("role"), "entry_role", maximum=64)
        expected_schema = _SCHEMA_BY_ROLE.get(role)
        if expected_schema is None or item.get("content_schema_version") != expected_schema:
            raise ArtifactProvenanceError("entry_schema")
        digest = _text(item.get("digest"), "entry_digest", maximum=71)
        if _SHA256.fullmatch(digest) is None:
            raise ArtifactProvenanceError("entry_digest")
        size = _positive_integer(item.get("size_bytes"), "entry_size")
        if size > _MAX_ARTIFACT_FILE_BYTES:
            raise ArtifactProvenanceError("entry_size")
        total += size
        if total > _MAX_ARTIFACT_TOTAL_BYTES:
            raise ArtifactProvenanceError("artifact_total_size")
        entries.append(
            ArtifactEntry(
                role=role,
                path=_normalized_artifact_path(item.get("path")),
                schema_version=expected_schema,
                size_bytes=size,
                digest=digest,
            )
        )
    ordered = tuple(sorted(entries, key=lambda entry: (entry.role, entry.path)))
    if tuple(entries) != ordered or len({entry.path for entry in ordered}) != len(ordered):
        raise ArtifactProvenanceError("envelope_entries")
    name = _text(mapping.get("artifact_name"), "artifact_name", maximum=255)
    if name != artifact_name(context):
        raise ArtifactProvenanceError("artifact_name")
    identity_inputs = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "artifact_name": name,
        "context": context.as_dict(),
        "entries": [entry.as_dict() for entry in ordered],
    }
    expected = sha256_identity(identity_inputs)
    if mapping.get("envelope_identity") != expected:
        raise ArtifactProvenanceError("envelope_identity")
    return ArtifactEnvelope(name, context, ordered, expected)


def _safe_output(root: Path, relative: str | Path) -> Path:
    normalized, path = _safe_artifact_path(root, relative)
    if normalized != "envelope.json":
        raise ArtifactProvenanceError("envelope_output")
    if path.exists() or path.is_symlink():
        raise ArtifactProvenanceError("output_exists")
    return path


def _publish(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".envelope.", suffix=".tmp", dir=path.parent
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
            raise ArtifactProvenanceError("output_exists") from exc
        except OSError as exc:
            if linked:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise ArtifactProvenanceError("output_publish") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _file_argument(value: str) -> tuple[str, str]:
    role, separator, path = value.partition("=")
    if not separator or not role or not path:
        raise argparse.ArgumentTypeError("expected ROLE=PATH")
    return role, path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create exact Newsroom artifact envelope")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--file", action="append", type=_file_argument, required=True)
    parser.add_argument("--output", default="envelope.json")
    arguments = parser.parse_args(argv)
    repository_root = Path(arguments.repo_root).resolve()
    try:
        root = _artifact_root(repository_root, arguments.artifact_root)
        context = context_from_environment(repository_root)
        envelope = create_envelope(
            repo_root=repository_root,
            artifact_root=root,
            context=context,
            files=arguments.file,
        )
        rendered = canonical_json_bytes(envelope.as_dict()) + b"\n"
        _publish(_safe_output(root, arguments.output), rendered)
    except (
        ArtifactProvenanceError,
        EvidenceError,
        GitRouteError,
        OSError,
        UnicodeError,
    ) as exc:
        reason = (
            str(exc)
            if isinstance(exc, ArtifactProvenanceError) and str(exc)
            else type(exc).__name__
        )
        print(f"EVIDENCE_MISMATCH:artifact-envelope:{reason}", file=sys.stderr)
        return 2
    sys.stdout.write(
        json.dumps(
            {
                "artifact_name": envelope.artifact_name,
                "envelope_identity": envelope.envelope_identity,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
