from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import zipfile

import pytest

from scripts.sdlc.emit_evidence import canonical_json_bytes, sha256_identity
from scripts.sdlc.github_transport import DownloadedArtifact, TransportBundle
from scripts.sdlc.transport_replay import (
    TransportReplayError,
    load_verified_transport,
    validate_transport_replay,
)


RUN_ID = 123
RUN_ATTEMPT = 2
REPOSITORY_ID = 1153895518
HEAD_REPOSITORY_ID = 999
HEAD_SHA = "a" * 40
ARTIFACT_ID = 456
ARTIFACT_NAME = f"newsroom-sdlc-{RUN_ID}-{RUN_ATTEMPT}-core-{HEAD_SHA}"
TRANSPORT_SCHEMA = "newsroom.sdlc.github-transport.v1"


def _json_bytes(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _transport_identity(value: dict[str, object]) -> str:
    return sha256_identity(
        {
            "schema_version": TRANSPORT_SCHEMA,
            "run_id": value["run_id"],
            "run_attempt": value["run_attempt"],
            "artifact": value["artifact"],
            "run_digest": value["run_digest"],
            "jobs_digest": value["jobs_digest"],
            "metadata_digest": value["metadata_digest"],
        }
    )


def _archive(root: Path) -> tuple[bytes, str]:
    archive_path = root / "artifact.zip"
    info = zipfile.ZipInfo("envelope.json", date_time=(2026, 7, 22, 12, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, b'{"schema_version":"example"}\n')
    archive_path.chmod(0o600)
    payload = archive_path.read_bytes()
    return payload, "sha256:" + hashlib.sha256(payload).hexdigest()


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    artifact_root = root / "artifact"
    artifact_root.mkdir(mode=0o700)
    artifact_root.chmod(0o700)
    _write_private(
        artifact_root / "envelope.json",
        b'{"schema_version":"example"}\n',
    )
    archive_bytes, archive_digest = _archive(root)

    run = {
        "id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "status": "completed",
        "conclusion": "success",
        "event": "pull_request",
        "head_sha": HEAD_SHA,
        "repository": {"id": REPOSITORY_ID, "full_name": "fol2/newsroom"},
        "head_repository": {
            "id": HEAD_REPOSITORY_ID,
            "full_name": "contributor/newsroom",
        },
    }
    jobs = {
        "total_count": 1,
        "jobs": [
            {
                "id": 789,
                "run_id": RUN_ID,
                "run_attempt": RUN_ATTEMPT,
                "name": "core",
                "status": "completed",
                "conclusion": "success",
                "steps": [],
            }
        ],
    }
    metadata = {
        "id": ARTIFACT_ID,
        "name": ARTIFACT_NAME,
        "size_in_bytes": len(archive_bytes),
        "digest": archive_digest,
        "expired": False,
        "url": (
            "https://api.github.com/repos/fol2/newsroom/actions/artifacts/"
            f"{ARTIFACT_ID}"
        ),
        "archive_download_url": (
            "https://api.github.com/repos/fol2/newsroom/actions/artifacts/"
            f"{ARTIFACT_ID}/zip"
        ),
        "workflow_run": {
            "id": RUN_ID,
            "repository_id": REPOSITORY_ID,
            "head_repository_id": HEAD_REPOSITORY_ID,
            "head_sha": HEAD_SHA,
        },
    }
    run_payload = _json_bytes(run)
    jobs_payload = _json_bytes(jobs)
    metadata_payload = _json_bytes(metadata)
    _write_private(root / "run.json", run_payload)
    _write_private(root / "jobs.json", jobs_payload)
    _write_private(root / "metadata.json", metadata_payload)

    artifact = DownloadedArtifact(
        artifact_id=ARTIFACT_ID,
        name=ARTIFACT_NAME,
        size_bytes=len(archive_bytes),
        digest=archive_digest,
        archive_path="artifact.zip",
        extracted_path="artifact",
    )
    identity_inputs: dict[str, object] = {
        "schema_version": TRANSPORT_SCHEMA,
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "artifact": artifact.as_dict(),
        "run_digest": "sha256:" + hashlib.sha256(run_payload).hexdigest(),
        "jobs_digest": "sha256:" + hashlib.sha256(jobs_payload).hexdigest(),
        "metadata_digest": "sha256:" + hashlib.sha256(metadata_payload).hexdigest(),
    }
    bundle = TransportBundle(
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        artifact=artifact,
        run_digest=str(identity_inputs["run_digest"]),
        jobs_digest=str(identity_inputs["jobs_digest"]),
        metadata_digest=str(identity_inputs["metadata_digest"]),
        transport_identity=sha256_identity(identity_inputs),
    )
    _write_private(root / "transport.json", _json_bytes(bundle.as_dict()))
    return root


def _rewrite_snapshot(root: Path, name: str, value: dict[str, object]) -> None:
    payload = _json_bytes(value)
    _write_private(root / name, payload)
    transport_path = root / "transport.json"
    transport = json.loads(transport_path.read_text(encoding="utf-8"))
    field = {
        "run.json": "run_digest",
        "jobs.json": "jobs_digest",
        "metadata.json": "metadata_digest",
    }[name]
    transport[field] = "sha256:" + hashlib.sha256(payload).hexdigest()
    transport["transport_identity"] = _transport_identity(transport)
    _write_private(transport_path, _json_bytes(transport))


def test_verified_transport_replays_exact_snapshots_and_archive(tmp_path: Path) -> None:
    root = _fixture(tmp_path)

    verified = load_verified_transport(root)

    assert verified.bundle.run_id == RUN_ID
    assert verified.replay.head_sha == HEAD_SHA
    assert verified.replay.repository_id == REPOSITORY_ID
    assert verified.replay.head_repository_id == HEAD_REPOSITORY_ID
    assert verified.archive_path == root / "artifact.zip"
    assert verified.artifact_root == root / "artifact"
    assert validate_transport_replay(verified.replay.as_dict()) == verified.replay


def test_snapshot_bytes_must_match_transport_digests(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    (root / "run.json").write_bytes(b"{}\n")
    (root / "run.json").chmod(0o600)

    with pytest.raises(TransportReplayError, match="snapshot_digest"):
        load_verified_transport(root)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("id",), True),
        (("run_attempt",), True),
        (("repository", "id"), True),
        (("head_repository", "id"), True),
    ],
)
def test_run_identity_is_revalidated_after_digest_replay(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    root = _fixture(tmp_path)
    run = json.loads((root / "run.json").read_text(encoding="utf-8"))
    target = run
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    _rewrite_snapshot(root, "run.json", run)

    with pytest.raises(TransportReplayError, match="run_identity"):
        load_verified_transport(root)


def test_jobs_must_belong_to_exact_run_and_attempt(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    jobs = json.loads((root / "jobs.json").read_text(encoding="utf-8"))
    jobs["jobs"][0]["run_attempt"] = RUN_ATTEMPT + 1
    _rewrite_snapshot(root, "jobs.json", jobs)

    with pytest.raises(TransportReplayError, match="job_run_attempt"):
        load_verified_transport(root)


def test_artifact_metadata_is_cross_bound_to_run_and_bundle(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    metadata["workflow_run"]["head_sha"] = "b" * 40
    _rewrite_snapshot(root, "metadata.json", metadata)

    with pytest.raises(TransportReplayError, match="artifact_run_identity"):
        load_verified_transport(root)

    root = _fixture(tmp_path / "artifact")
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    metadata["id"] = ARTIFACT_ID + 1
    _rewrite_snapshot(root, "metadata.json", metadata)
    with pytest.raises(TransportReplayError, match="artifact_metadata"):
        load_verified_transport(root)


def test_archive_bytes_must_match_transport_manifest(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    archive = root / "artifact.zip"
    archive.write_bytes(archive.read_bytes() + b"changed")
    archive.chmod(0o600)

    with pytest.raises(TransportReplayError, match="archive_digest"):
        load_verified_transport(root)


def test_bundle_inventory_symlinks_and_permissions_fail_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    extra = root / "extra"
    _write_private(extra, b"extra")
    with pytest.raises(TransportReplayError, match="bundle_inventory"):
        load_verified_transport(root)

    root = _fixture(tmp_path / "symlink")
    (root / "run.json").unlink()
    (root / "run.json").symlink_to(root / "jobs.json")
    with pytest.raises(TransportReplayError, match="bundle_symlink"):
        load_verified_transport(root)

    root = _fixture(tmp_path / "mode")
    (root / "jobs.json").chmod(0o644)
    with pytest.raises(TransportReplayError, match="bundle_inventory"):
        load_verified_transport(root)

    real = _fixture(tmp_path / "root-link")
    linked = tmp_path / "linked-bundle"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(TransportReplayError, match="bundle_symlink"):
        load_verified_transport(linked)


def test_replay_record_rejects_shape_and_identity_tampering(tmp_path: Path) -> None:
    replay = load_verified_transport(_fixture(tmp_path)).replay.as_dict()

    changed = deepcopy(replay)
    changed["replay_identity"] = "sha256:" + "0" * 64
    with pytest.raises(TransportReplayError, match="replay_identity"):
        validate_transport_replay(changed)

    changed = deepcopy(replay)
    changed["unknown"] = True
    with pytest.raises(TransportReplayError, match="replay_shape"):
        validate_transport_replay(changed)
