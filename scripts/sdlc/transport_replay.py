from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import BinaryIO, Mapping

from .artifact_envelope import (
    ArtifactProvenanceError,
    _unique_object,
    _validate_json_depth,
)
from .emit_evidence import sha256_identity
from .github_transport import (
    GitHubTransportError,
    TransportBundle,
    _open_archive_stream,
    _run_identity,
    validate_transport_bundle,
)


SCHEMA_VERSION = "newsroom.sdlc.transport-replay.v1"
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_EXPECTED_ENTRIES = frozenset(
    {
        "artifact",
        "artifact.zip",
        "jobs.json",
        "metadata.json",
        "run.json",
        "transport.json",
    }
)
_REPLAY_KEYS = frozenset(
    {
        "schema_version",
        "replay_identity",
        "transport_identity",
        "run_id",
        "run_attempt",
        "repository_id",
        "head_repository_id",
        "head_sha",
        "artifact_id",
        "artifact_name",
        "artifact_size_bytes",
        "artifact_digest",
        "run_digest",
        "jobs_digest",
        "metadata_digest",
    }
)


class TransportReplayError(ValueError):
    """Raised when a published transport bundle cannot be replayed exactly."""


@dataclass(frozen=True)
class TransportReplay:
    transport_identity: str
    run_id: int
    run_attempt: int
    repository_id: int
    head_repository_id: int
    head_sha: str
    artifact_id: int
    artifact_name: str
    artifact_size_bytes: int
    artifact_digest: str
    run_digest: str
    jobs_digest: str
    metadata_digest: str
    replay_identity: str

    def __post_init__(self) -> None:
        _positive(self.run_id, "run_id")
        _positive(self.run_attempt, "run_attempt")
        _positive(self.repository_id, "repository_id")
        _positive(self.head_repository_id, "head_repository_id")
        _git_sha(self.head_sha, "head_sha")
        _positive(self.artifact_id, "artifact_id")
        _text(self.artifact_name, "artifact_name", maximum=255)
        _positive(self.artifact_size_bytes, "artifact_size")
        for value, code in (
            (self.transport_identity, "transport_identity"),
            (self.artifact_digest, "artifact_digest"),
            (self.run_digest, "run_digest"),
            (self.jobs_digest, "jobs_digest"),
            (self.metadata_digest, "metadata_digest"),
            (self.replay_identity, "replay_identity"),
        ):
            _sha(value, code)
        if self.replay_identity != sha256_identity(_identity_inputs(self)):
            raise TransportReplayError("replay_identity")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "replay_identity": self.replay_identity,
            "transport_identity": self.transport_identity,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "repository_id": self.repository_id,
            "head_repository_id": self.head_repository_id,
            "head_sha": self.head_sha,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "artifact_size_bytes": self.artifact_size_bytes,
            "artifact_digest": self.artifact_digest,
            "run_digest": self.run_digest,
            "jobs_digest": self.jobs_digest,
            "metadata_digest": self.metadata_digest,
        }


@dataclass(frozen=True)
class VerifiedTransport:
    root: Path
    bundle: TransportBundle
    replay: TransportReplay
    run: Mapping[str, object]
    jobs: Mapping[str, object]
    metadata: Mapping[str, object]

    @property
    def archive_path(self) -> Path:
        return self.root / self.bundle.artifact.archive_path

    @property
    def artifact_root(self) -> Path:
        return self.root / self.bundle.artifact.extracted_path


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TransportReplayError(code)
    return value


def _positive(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TransportReplayError(code)
    return value


def _text(value: object, code: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise TransportReplayError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise TransportReplayError(code)
    return value


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=71)
    if not text.startswith("sha256:") or len(text) != 71:
        raise TransportReplayError(code)
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise TransportReplayError(code) from exc
    if text.lower() != text:
        raise TransportReplayError(code)
    return text


def _git_sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=40)
    if len(text) != 40:
        raise TransportReplayError(code)
    try:
        int(text, 16)
    except ValueError as exc:
        raise TransportReplayError(code) from exc
    if text.lower() != text:
        raise TransportReplayError(code)
    return text


def _identity_inputs(replay: TransportReplay) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "transport_identity": replay.transport_identity,
        "run_id": replay.run_id,
        "run_attempt": replay.run_attempt,
        "repository_id": replay.repository_id,
        "head_repository_id": replay.head_repository_id,
        "head_sha": replay.head_sha,
        "artifact_id": replay.artifact_id,
        "artifact_name": replay.artifact_name,
        "artifact_size_bytes": replay.artifact_size_bytes,
        "artifact_digest": replay.artifact_digest,
        "run_digest": replay.run_digest,
        "jobs_digest": replay.jobs_digest,
        "metadata_digest": replay.metadata_digest,
    }


def validate_transport_replay(value: object) -> TransportReplay:
    item = _mapping(value, "replay")
    if frozenset(item) != _REPLAY_KEYS or item.get("schema_version") != SCHEMA_VERSION:
        raise TransportReplayError("replay_shape")
    return TransportReplay(
        transport_identity=_sha(item.get("transport_identity"), "transport_identity"),
        run_id=_positive(item.get("run_id"), "run_id"),
        run_attempt=_positive(item.get("run_attempt"), "run_attempt"),
        repository_id=_positive(item.get("repository_id"), "repository_id"),
        head_repository_id=_positive(
            item.get("head_repository_id"), "head_repository_id"
        ),
        head_sha=_git_sha(item.get("head_sha"), "head_sha"),
        artifact_id=_positive(item.get("artifact_id"), "artifact_id"),
        artifact_name=_text(item.get("artifact_name"), "artifact_name", maximum=255),
        artifact_size_bytes=_positive(
            item.get("artifact_size_bytes"), "artifact_size"
        ),
        artifact_digest=_sha(item.get("artifact_digest"), "artifact_digest"),
        run_digest=_sha(item.get("run_digest"), "run_digest"),
        jobs_digest=_sha(item.get("jobs_digest"), "jobs_digest"),
        metadata_digest=_sha(item.get("metadata_digest"), "metadata_digest"),
        replay_identity=_sha(item.get("replay_identity"), "replay_identity"),
    )


def _private_mode(metadata: os.stat_result, *, directory: bool, code: str) -> None:
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(metadata.st_mode) or metadata.st_mode & 0o077:
        raise TransportReplayError(code)


def _bundle_root(value: str | Path) -> Path:
    candidate = Path(value)
    absolute = candidate if candidate.is_absolute() else candidate.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise TransportReplayError("bundle_symlink")
    try:
        metadata = os.lstat(absolute)
    except OSError as exc:
        raise TransportReplayError("bundle_root") from exc
    _private_mode(metadata, directory=True, code="bundle_root")
    return absolute


def _secure_read(path: Path, *, maximum: int, code: str) -> bytes:
    absolute = path if path.is_absolute() else path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise TransportReplayError(f"{code}_symlink")
    try:
        initial = os.lstat(absolute)
    except OSError as exc:
        raise TransportReplayError(code) from exc
    _private_mode(initial, directory=False, code=code)
    if not 0 < initial.st_size <= maximum:
        raise TransportReplayError(code)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(absolute, flags)
        current_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(current_metadata.st_mode)
            or current_metadata.st_dev != initial.st_dev
            or current_metadata.st_ino != initial.st_ino
            or current_metadata.st_size != initial.st_size
            or current_metadata.st_mode & 0o077
        ):
            raise TransportReplayError(code)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            payload = stream.read(maximum + 1)
    except TransportReplayError:
        raise
    except OSError as exc:
        raise TransportReplayError(code) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) != initial.st_size or len(payload) > maximum:
        raise TransportReplayError(code)
    return payload


def _load_json(payload: bytes, code: str) -> Mapping[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        _validate_json_depth(value)
    except (UnicodeError, json.JSONDecodeError, ArtifactProvenanceError) as exc:
        raise TransportReplayError(code) from exc
    return _mapping(value, code)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _hash_stream(stream: BinaryIO, *, maximum: int, code: str) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    while payload := stream.read(1024 * 1024):
        total += len(payload)
        if total > maximum:
            raise TransportReplayError(code)
        digest.update(payload)
    return total, "sha256:" + digest.hexdigest()


def _inventory(root: Path) -> None:
    try:
        entries = {entry.name: entry for entry in os.scandir(root)}
    except OSError as exc:
        raise TransportReplayError("bundle_inventory") from exc
    if frozenset(entries) != _EXPECTED_ENTRIES:
        raise TransportReplayError("bundle_inventory")
    for name, entry in entries.items():
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise TransportReplayError("bundle_inventory") from exc
        if entry.is_symlink():
            raise TransportReplayError("bundle_symlink")
        _private_mode(
            metadata,
            directory=name == "artifact",
            code="bundle_inventory",
        )


def _validate_jobs(value: Mapping[str, object], run_id: int, attempt: int) -> None:
    total = value.get("total_count")
    jobs = value.get("jobs")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or total > 100
        or not isinstance(jobs, list)
        or total != len(jobs)
    ):
        raise TransportReplayError("jobs_shape")
    for raw in jobs:
        job = _mapping(raw, "job")
        job_run_id = job.get("run_id")
        job_attempt = job.get("run_attempt")
        if job_run_id is not None and _positive(job_run_id, "job_run_id") != run_id:
            raise TransportReplayError("job_run_id")
        if job_attempt is not None and _positive(job_attempt, "job_run_attempt") != attempt:
            raise TransportReplayError("job_run_attempt")


def load_verified_transport(bundle_root: str | Path) -> VerifiedTransport:
    root = _bundle_root(bundle_root)
    _inventory(root)

    transport_payload = _secure_read(
        root / "transport.json", maximum=_MAX_JSON_BYTES, code="transport_file"
    )
    run_payload = _secure_read(
        root / "run.json", maximum=_MAX_JSON_BYTES, code="run_file"
    )
    jobs_payload = _secure_read(
        root / "jobs.json", maximum=_MAX_JSON_BYTES, code="jobs_file"
    )
    metadata_payload = _secure_read(
        root / "metadata.json", maximum=_MAX_JSON_BYTES, code="metadata_file"
    )

    try:
        bundle = validate_transport_bundle(_load_json(transport_payload, "transport_json"))
    except GitHubTransportError as exc:
        raise TransportReplayError("transport_invalid") from exc
    run_value = _load_json(run_payload, "run_json")
    jobs_value = _load_json(jobs_payload, "jobs_json")
    metadata_value = _load_json(metadata_payload, "metadata_json")

    if (
        _digest(run_payload) != bundle.run_digest
        or _digest(jobs_payload) != bundle.jobs_digest
        or _digest(metadata_payload) != bundle.metadata_digest
    ):
        raise TransportReplayError("snapshot_digest")

    try:
        run_id, attempt, repository_id, head_repository_id, head_sha = _run_identity(
            run_value,
            expected_run_id=bundle.run_id,
        )
    except GitHubTransportError as exc:
        raise TransportReplayError("run_identity") from exc
    if attempt != bundle.run_attempt:
        raise TransportReplayError("run_attempt")
    _validate_jobs(jobs_value, run_id, attempt)

    artifact = bundle.artifact
    try:
        metadata_artifact_id = _positive(metadata_value.get("id"), "artifact_id")
        metadata_size = _positive(metadata_value.get("size_in_bytes"), "artifact_size")
        metadata_name = _text(metadata_value.get("name"), "artifact_name", maximum=255)
        metadata_digest = _sha(metadata_value.get("digest"), "artifact_digest")
    except TransportReplayError as exc:
        raise TransportReplayError("artifact_metadata") from exc
    if (
        metadata_artifact_id != artifact.artifact_id
        or metadata_name != artifact.name
        or metadata_size != artifact.size_bytes
        or metadata_digest != artifact.digest
        or metadata_value.get("expired") is not False
    ):
        raise TransportReplayError("artifact_metadata")
    workflow_run = _mapping(metadata_value.get("workflow_run"), "artifact_workflow_run")
    try:
        metadata_run_id = _positive(workflow_run.get("id"), "artifact_run_id")
        metadata_repository_id = _positive(
            workflow_run.get("repository_id"), "artifact_repository_id"
        )
        metadata_head_repository_id = _positive(
            workflow_run.get("head_repository_id"), "artifact_head_repository_id"
        )
        metadata_head_sha = _git_sha(workflow_run.get("head_sha"), "artifact_head_sha")
    except TransportReplayError as exc:
        raise TransportReplayError("artifact_run_identity") from exc
    if (
        metadata_run_id != run_id
        or metadata_repository_id != repository_id
        or metadata_head_repository_id != head_repository_id
        or metadata_head_sha != head_sha
    ):
        raise TransportReplayError("artifact_run_identity")

    archive_path = root / artifact.archive_path
    try:
        with _open_archive_stream(archive_path) as stream:
            archive_size, archive_digest = _hash_stream(
                stream,
                maximum=_MAX_ARCHIVE_BYTES,
                code="archive_size",
            )
    except (GitHubTransportError, OSError) as exc:
        raise TransportReplayError("archive_file") from exc
    if archive_size != artifact.size_bytes or archive_digest != artifact.digest:
        raise TransportReplayError("archive_digest")

    replay_without_identity = {
        "schema_version": SCHEMA_VERSION,
        "transport_identity": bundle.transport_identity,
        "run_id": run_id,
        "run_attempt": attempt,
        "repository_id": repository_id,
        "head_repository_id": head_repository_id,
        "head_sha": head_sha,
        "artifact_id": artifact.artifact_id,
        "artifact_name": artifact.name,
        "artifact_size_bytes": artifact.size_bytes,
        "artifact_digest": artifact.digest,
        "run_digest": bundle.run_digest,
        "jobs_digest": bundle.jobs_digest,
        "metadata_digest": bundle.metadata_digest,
    }
    replay = TransportReplay(
        transport_identity=bundle.transport_identity,
        run_id=run_id,
        run_attempt=attempt,
        repository_id=repository_id,
        head_repository_id=head_repository_id,
        head_sha=head_sha,
        artifact_id=artifact.artifact_id,
        artifact_name=artifact.name,
        artifact_size_bytes=artifact.size_bytes,
        artifact_digest=artifact.digest,
        run_digest=bundle.run_digest,
        jobs_digest=bundle.jobs_digest,
        metadata_digest=bundle.metadata_digest,
        replay_identity=sha256_identity(replay_without_identity),
    )
    validate_transport_replay(replay.as_dict())
    return VerifiedTransport(
        root=root,
        bundle=bundle,
        replay=replay,
        run=dict(run_value),
        jobs=dict(jobs_value),
        metadata=dict(metadata_value),
    )
