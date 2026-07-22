from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Mapping
from urllib.error import HTTPError
from urllib.request import Request
import warnings
import zipfile

import pytest

import scripts.sdlc.github_transport as transport_module
from scripts.sdlc.github_transport import (
    DownloadedArtifact,
    GitHubActionsClient,
    GitHubTransportError,
    _SafeRedirectHandler,
    _publish_directory,
    _safe_extract,
    _write_private,
    fetch_artifact_bundle,
    main as transport_main,
    validate_transport_bundle,
)


RUN_ID = 123
RUN_ATTEMPT = 2
ARTIFACT_ID = 456
HEAD_SHA = "a" * 40
ARTIFACT_NAME = f"newsroom-sdlc-{RUN_ID}-{RUN_ATTEMPT}-core-{HEAD_SHA}"
TOKEN = "github-token-must-never-appear"
API_PREFIX = "https://api.github.com/repos/fol2/newsroom"


class FakeResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        url: str,
        content_type: str | None = "application/json",
        content_length: int | None = None,
    ) -> None:
        self._payload = payload
        self._offset = 0
        self._url = url
        self.closed = False
        self.headers: dict[str, str] = {}
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(
            len(payload) if content_length is None else content_length
        )

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            amount = len(self._payload) - self._offset
        start = self._offset
        self._offset = min(len(self._payload), self._offset + amount)
        return self._payload[start : self._offset]

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self.closed = True


class FakeOpen:
    def __init__(self, responses: Mapping[str, list[FakeResponse]]) -> None:
        self.responses = {url: list(items) for url, items in responses.items()}
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Request, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        values = self.responses.get(request.full_url)
        if not values:
            raise AssertionError(f"unexpected request: {request.full_url}")
        return values.pop(0)


def _json_response(value: object, url: str, **kwargs: object) -> FakeResponse:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return FakeResponse(payload, url=url, **kwargs)  # type: ignore[arg-type]


def _regular_info(
    path: str,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(2026, 7, 22, 12, 0, 0))
    info.compress_type = compression
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def _directory_info(path: str) -> zipfile.ZipInfo:
    name = path if path.endswith("/") else path + "/"
    info = zipfile.ZipInfo(name, date_time=(2026, 7, 22, 12, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (stat.S_IFDIR | 0o700) << 16
    return info


def _archive_bytes() -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(_directory_info("gates"), b"")
        archive.writestr(_directory_info("gates/core"), b"")
        archive.writestr(
            _regular_info("envelope.json"),
            b'{"schema_version":"example"}\n',
        )
        archive.writestr(
            _regular_info("gates/core/evidence.json"),
            b'{"result":"PASS"}\n',
        )
    return stream.getvalue()


def _run_value(*, attempt: int = RUN_ATTEMPT) -> dict[str, object]:
    return {
        "id": RUN_ID,
        "run_attempt": attempt,
        "status": "in_progress",
        "event": "pull_request",
        "head_sha": HEAD_SHA,
        "created_at": "2026-07-22T12:00:00Z",
        "repository": {"id": 1153895518, "full_name": "fol2/newsroom"},
        "head_repository": {"id": 1153895518, "full_name": "fol2/newsroom"},
    }


def _jobs_value() -> dict[str, object]:
    return {
        "total_count": 1,
        "jobs": [
            {
                "id": 999,
                "run_id": RUN_ID,
                "run_attempt": RUN_ATTEMPT,
                "name": "core",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-07-22T12:00:01Z",
                "completed_at": "2026-07-22T12:00:30Z",
                "steps": [],
            }
        ],
    }


def _metadata(archive_bytes: bytes) -> dict[str, object]:
    base = f"{API_PREFIX}/actions/artifacts/{ARTIFACT_ID}"
    return {
        "id": ARTIFACT_ID,
        "name": ARTIFACT_NAME,
        "size_in_bytes": len(archive_bytes),
        "url": base,
        "archive_download_url": base + "/zip",
        "expired": False,
        "created_at": "2026-07-22T12:00:31Z",
        "updated_at": "2026-07-22T12:00:31Z",
        "expires_at": "2026-08-21T12:00:31Z",
        "digest": "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
        "workflow_run": {
            "id": RUN_ID,
            "repository_id": 1153895518,
            "head_repository_id": 1153895518,
            "head_sha": HEAD_SHA,
        },
    }


def _responses(
    archive_bytes: bytes,
    *,
    run: dict[str, object] | None = None,
    jobs: dict[str, object] | None = None,
    listed_artifacts: list[dict[str, object]] | None = None,
    metadata: dict[str, object] | None = None,
    download_payload: bytes | None = None,
    download_final_url: str = (
        "https://newsroom.blob.core.windows.net/evidence/archive.zip?sig=redacted"
    ),
    run_final_url: str | None = None,
    json_content_type: str = "application/json",
) -> dict[str, list[FakeResponse]]:
    artifact_metadata = metadata or _metadata(archive_bytes)
    artifact_list = listed_artifacts or [
        {"id": ARTIFACT_ID, "name": ARTIFACT_NAME, "expired": False}
    ]
    run_url = f"{API_PREFIX}/actions/runs/{RUN_ID}"
    jobs_url = (
        f"{API_PREFIX}/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}/jobs"
        "?filter=all&per_page=100"
    )
    artifacts_url = f"{API_PREFIX}/actions/runs/{RUN_ID}/artifacts?per_page=100"
    metadata_url = f"{API_PREFIX}/actions/artifacts/{ARTIFACT_ID}"
    download_url = metadata_url + "/zip"
    payload = archive_bytes if download_payload is None else download_payload
    return {
        run_url: [
            _json_response(
                run or _run_value(),
                run_final_url or run_url,
                content_type=json_content_type,
            )
        ],
        jobs_url: [_json_response(jobs or _jobs_value(), jobs_url)],
        artifacts_url: [
            _json_response(
                {"total_count": len(artifact_list), "artifacts": artifact_list},
                artifacts_url,
            )
        ],
        metadata_url: [_json_response(artifact_metadata, metadata_url)],
        download_url: [
            FakeResponse(
                payload,
                url=download_final_url,
                content_type="application/zip",
            )
        ],
    }


def _client(
    archive_bytes: bytes,
    **kwargs: object,
) -> tuple[GitHubActionsClient, FakeOpen]:
    opener = FakeOpen(_responses(archive_bytes, **kwargs))
    return GitHubActionsClient(TOKEN, open_request=opener), opener


def test_full_transport_bundle_binds_exact_api_and_archive_bytes(
    tmp_path: Path,
) -> None:
    archive_bytes = _archive_bytes()
    client, opener = _client(archive_bytes)

    bundle = fetch_artifact_bundle(
        client=client,
        output_parent=tmp_path,
        output_name="bundle",
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        artifact_name=ARTIFACT_NAME,
    )

    root = tmp_path / "bundle"
    assert validate_transport_bundle(bundle.as_dict()) == bundle
    assert bundle.artifact.digest == (
        "sha256:" + hashlib.sha256(archive_bytes).hexdigest()
    )
    assert (root / "artifact.zip").read_bytes() == archive_bytes
    assert (root / "artifact/envelope.json").read_bytes().startswith(b"{")
    assert (root / "artifact/gates/core/evidence.json").read_bytes().endswith(
        b"\n"
    )
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "artifact").stat().st_mode) == 0o700
    for name in (
        "run.json",
        "jobs.json",
        "metadata.json",
        "artifact.zip",
        "transport.json",
    ):
        assert stat.S_IMODE((root / name).stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "artifact/envelope.json").stat().st_mode) == 0o600
    assert TOKEN.encode() not in b"".join(
        path.read_bytes() for path in root.rglob("*") if path.is_file()
    )

    requested_urls = [request.full_url for request in opener.requests]
    assert requested_urls == [
        f"{API_PREFIX}/actions/runs/{RUN_ID}",
        (
            f"{API_PREFIX}/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}/jobs"
            "?filter=all&per_page=100"
        ),
        f"{API_PREFIX}/actions/runs/{RUN_ID}/artifacts?per_page=100",
        f"{API_PREFIX}/actions/artifacts/{ARTIFACT_ID}",
        f"{API_PREFIX}/actions/artifacts/{ARTIFACT_ID}/zip",
    ]
    assert all(request.get_method() == "GET" for request in opener.requests)
    assert all(
        request.get_header("X-github-api-version") == "2022-11-28"
        for request in opener.requests
    )
    assert all(
        request.get_header("Authorization") == f"Bearer {TOKEN}"
        for request in opener.requests
    )
    assert all(timeout == 10.0 for timeout in opener.timeouts)


def test_transport_output_is_non_overwriting_and_identity_is_strict(
    tmp_path: Path,
) -> None:
    archive_bytes = _archive_bytes()
    client, _ = _client(archive_bytes)
    bundle = fetch_artifact_bundle(
        client=client,
        output_parent=tmp_path,
        output_name="bundle",
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        artifact_name=ARTIFACT_NAME,
    )
    original = (tmp_path / "bundle/transport.json").read_bytes()

    with pytest.raises(GitHubTransportError, match="output_exists"):
        fetch_artifact_bundle(
            client=client,
            output_parent=tmp_path,
            output_name="bundle",
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            artifact_name=ARTIFACT_NAME,
        )
    assert (tmp_path / "bundle/transport.json").read_bytes() == original

    tampered = bundle.as_dict()
    tampered["run_digest"] = "sha256:" + "0" * 64
    with pytest.raises(GitHubTransportError, match="transport_identity"):
        validate_transport_bundle(tampered)

    with pytest.raises(GitHubTransportError, match="artifact_path"):
        DownloadedArtifact(
            ARTIFACT_ID,
            ARTIFACT_NAME,
            len(archive_bytes),
            bundle.artifact.digest,
            "other.zip",
            "artifact",
        )


def test_run_attempt_json_redirect_content_type_and_pagination_fail_closed(
    tmp_path: Path,
) -> None:
    archive_bytes = _archive_bytes()
    client, _ = _client(archive_bytes, run=_run_value(attempt=3))
    with pytest.raises(GitHubTransportError, match="run_attempt"):
        fetch_artifact_bundle(
            client=client,
            output_parent=tmp_path,
            output_name="attempt",
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            artifact_name=ARTIFACT_NAME,
        )

    client, _ = _client(
        archive_bytes,
        run_final_url="https://api.github.com/redirected",
    )
    with pytest.raises(GitHubTransportError, match="api_redirect"):
        client.fetch_run(RUN_ID)

    client, _ = _client(archive_bytes, json_content_type="text/html")
    with pytest.raises(GitHubTransportError, match="json_content_type"):
        client.fetch_run(RUN_ID)

    jobs = _jobs_value()
    jobs["total_count"] = 2
    client, _ = _client(archive_bytes, jobs=jobs)
    with pytest.raises(GitHubTransportError, match="jobs_pagination"):
        client.fetch_jobs(RUN_ID, RUN_ATTEMPT)


def test_artifact_selection_and_download_digest_fail_closed(tmp_path: Path) -> None:
    archive_bytes = _archive_bytes()
    duplicates = [
        {"id": ARTIFACT_ID, "name": ARTIFACT_NAME, "expired": False},
        {"id": ARTIFACT_ID + 1, "name": ARTIFACT_NAME, "expired": False},
    ]
    client, _ = _client(archive_bytes, listed_artifacts=duplicates)
    with pytest.raises(GitHubTransportError, match="artifact_identity"):
        client.select_artifact(_run_value(), ARTIFACT_NAME)

    expired = [{"id": ARTIFACT_ID, "name": ARTIFACT_NAME, "expired": True}]
    client, _ = _client(archive_bytes, listed_artifacts=expired)
    with pytest.raises(GitHubTransportError, match="artifact_identity"):
        client.select_artifact(_run_value(), ARTIFACT_NAME)

    metadata = _metadata(archive_bytes)
    metadata["digest"] = "sha256:" + "0" * 64
    client, _ = _client(archive_bytes, metadata=metadata)
    with pytest.raises(GitHubTransportError, match="artifact_digest"):
        fetch_artifact_bundle(
            client=client,
            output_parent=tmp_path,
            output_name="digest",
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            artifact_name=ARTIFACT_NAME,
        )
    assert not (tmp_path / "digest").exists()
    assert not any(path.name.startswith(".digest.") for path in tmp_path.iterdir())


def test_redirect_handler_strips_credentials_and_rejects_unsafe_hosts() -> None:
    handler = _SafeRedirectHandler()
    request = Request(
        f"{API_PREFIX}/actions/artifacts/{ARTIFACT_ID}/zip",
        headers={"Authorization": f"Bearer {TOKEN}"},
        method="GET",
    )
    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://newsroom.blob.core.windows.net/evidence/archive.zip?sig=x",
    )
    assert redirected is not None
    assert all(
        name.lower() != "authorization" for name, _ in redirected.header_items()
    )

    with pytest.raises(HTTPError):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://evil.example/archive.zip",
        )
    with pytest.raises(HTTPError):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://newsroom.blob.core.windows.net/archive.zip",
        )
    setattr(request, "_newsroom_redirect_count", 3)
    with pytest.raises(HTTPError):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://newsroom.blob.core.windows.net/evidence/archive.zip",
        )


def _write_unsafe_archive(path: Path, kind: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            if kind == "traversal":
                archive.writestr(_regular_info("../escape"), b"x")
            elif kind == "symlink":
                info = _regular_info("link")
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"target")
            elif kind == "directory_symlink":
                info = _directory_info("linked")
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"")
            elif kind == "duplicate":
                archive.writestr(_regular_info("same"), b"one")
                archive.writestr(_regular_info("same"), b"two")
            elif kind == "conflict":
                archive.writestr(_regular_info("node"), b"file")
                archive.writestr(_regular_info("node/child"), b"child")
            elif kind == "unsupported":
                archive.writestr(
                    _regular_info("bzip", compression=zipfile.ZIP_BZIP2),
                    b"compressed",
                )
            else:
                raise AssertionError(kind)


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("traversal", "archive_member"),
        ("symlink", "archive_member"),
        ("directory_symlink", "archive_member"),
        ("duplicate", "archive_duplicate"),
        ("conflict", "archive_member_conflict"),
        ("unsupported", "archive_member"),
    ],
)
def test_unsafe_archives_fail_before_publication(
    tmp_path: Path,
    kind: str,
    reason: str,
) -> None:
    archive = tmp_path / f"{kind}.zip"
    _write_unsafe_archive(archive, kind)
    target = tmp_path / f"{kind}-output"

    with pytest.raises(GitHubTransportError, match=reason):
        _safe_extract(archive, target)

    assert not target.exists()
    assert not any(
        path.name.startswith(f".{target.name}.") for path in tmp_path.iterdir()
    )


def test_uncompressed_limit_and_existing_target_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "limit.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(_regular_info("one"), b"12")
        output.writestr(_regular_info("two"), b"34")
    monkeypatch.setattr(transport_module, "_MAX_UNCOMPRESSED_BYTES", 3)
    with pytest.raises(GitHubTransportError, match="archive_uncompressed_size"):
        _safe_extract(archive, tmp_path / "limited")

    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep"
    sentinel.write_text("exact", encoding="utf-8")
    with pytest.raises(GitHubTransportError, match="output_exists"):
        _safe_extract(archive, target)
    assert sentinel.read_text(encoding="utf-8") == "exact"


def test_output_parent_symlink_and_cli_missing_token_are_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive_bytes = _archive_bytes()
    client, _ = _client(archive_bytes)
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(GitHubTransportError, match="output_parent"):
        fetch_artifact_bundle(
            client=client,
            output_parent=linked,
            output_name="bundle",
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            artifact_name=ARTIFACT_NAME,
        )

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert transport_main(
        (
            "--output-parent",
            str(tmp_path),
            "--output-name",
            "cli",
            "--run-id",
            str(RUN_ID),
            "--run-attempt",
            str(RUN_ATTEMPT),
            "--artifact-name",
            ARTIFACT_NAME,
        )
    ) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == (
        "EVIDENCE_MISMATCH:github-transport:token_missing"
    )
    assert TOKEN not in captured.err

@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("id",), True),
        (("run_attempt",), True),
        (("repository", "id"), True),
        (("head_repository", "id"), True),
    ],
)
def test_run_identity_rejects_boolean_integer_fields(
    path: tuple[str, ...],
    value: object,
) -> None:
    archive_bytes = _archive_bytes()
    changed = deepcopy(_run_value())
    target = changed
    for part in path[:-1]:
        target = target[part]  # type: ignore[assignment,index]
    target[path[-1]] = value  # type: ignore[index]
    client, _ = _client(archive_bytes, run=changed)
    with pytest.raises(GitHubTransportError, match="run_identity"):
        client.fetch_run(RUN_ID)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", True),
        ("repository_id", True),
        ("repository_id", 77),
        ("head_repository_id", 999),
        ("head_sha", "b" * 40),
    ],
)
def test_artifact_metadata_must_match_fetched_run(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    archive_bytes = _archive_bytes()
    metadata = _metadata(archive_bytes)
    workflow_run = metadata["workflow_run"]
    assert isinstance(workflow_run, dict)
    workflow_run[field] = value
    client, _ = _client(archive_bytes, metadata=metadata)
    with pytest.raises(GitHubTransportError, match="artifact_run_identity"):
        fetch_artifact_bundle(
            client=client,
            output_parent=tmp_path,
            output_name=f"mismatch-{field}",
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            artifact_name=ARTIFACT_NAME,
        )


def test_json_duplicate_keys_and_content_length_mismatch_fail_closed() -> None:
    run_url = f"{API_PREFIX}/actions/runs/{RUN_ID}"
    duplicate = FakeOpen(
        {
            run_url: [
                FakeResponse(
                    b'{"id":123,"id":124}',
                    url=run_url,
                    content_type="application/json",
                )
            ]
        }
    )
    with pytest.raises(GitHubTransportError, match="json_response"):
        GitHubActionsClient(TOKEN, open_request=duplicate).fetch_run(RUN_ID)

    payload = json.dumps(_run_value(), sort_keys=True, separators=(",", ":")).encode()
    wrong_length = FakeOpen(
        {
            run_url: [
                FakeResponse(
                    payload,
                    url=run_url,
                    content_type="application/json",
                    content_length=len(payload) + 1,
                )
            ]
        }
    )
    with pytest.raises(GitHubTransportError, match="json_size"):
        GitHubActionsClient(TOKEN, open_request=wrong_length).fetch_run(RUN_ID)


def test_artifact_content_length_and_setup_failure_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_bytes = _archive_bytes()
    metadata = _metadata(archive_bytes)
    download_url = f"{API_PREFIX}/actions/artifacts/{ARTIFACT_ID}/zip"
    final_url = "https://newsroom.blob.core.windows.net/evidence/archive.zip?sig=x"

    response = FakeResponse(
        archive_bytes,
        url=final_url,
        content_type="application/zip",
        content_length=len(archive_bytes) + 1,
    )
    client = GitHubActionsClient(TOKEN, open_request=FakeOpen({download_url: [response]}))
    with pytest.raises(GitHubTransportError, match="artifact_size"):
        client.download_artifact(metadata, tmp_path / "wrong-length.zip")
    assert response.closed
    assert not (tmp_path / "wrong-length.zip").exists()

    response = FakeResponse(archive_bytes, url=final_url, content_type="application/zip")
    client = GitHubActionsClient(TOKEN, open_request=FakeOpen({download_url: [response]}))
    real_mkstemp = transport_module.tempfile.mkstemp
    holder: dict[str, int] = {}

    def tracked_mkstemp(*args, **kwargs):
        descriptor, name = real_mkstemp(*args, **kwargs)
        holder["descriptor"] = descriptor
        return descriptor, name

    def fail_fdopen(*_args, **_kwargs):
        raise OSError("fdopen failed")

    monkeypatch.setattr(transport_module.tempfile, "mkstemp", tracked_mkstemp)
    monkeypatch.setattr(transport_module.os, "fdopen", fail_fdopen)
    with pytest.raises(GitHubTransportError, match="output_open"):
        client.download_artifact(metadata, tmp_path / "fdopen.zip")
    assert response.closed
    with pytest.raises(OSError):
        os.fstat(holder["descriptor"])
    assert not any(path.name.startswith(".fdopen.zip.") for path in tmp_path.iterdir())


def test_private_writer_closes_descriptor_when_fdopen_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = transport_module.os.open
    holder: dict[str, int] = {}

    def tracked_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        holder["descriptor"] = descriptor
        return descriptor

    def fail_fdopen(*_args, **_kwargs):
        raise OSError("fdopen failed")

    monkeypatch.setattr(transport_module.os, "open", tracked_open)
    monkeypatch.setattr(transport_module.os, "fdopen", fail_fdopen)
    target = tmp_path / "private.json"
    with pytest.raises(GitHubTransportError, match="output_open"):
        _write_private(target, b"{}\n")
    with pytest.raises(OSError):
        os.fstat(holder["descriptor"])
    assert not target.exists()


def test_untrusted_cloud_storage_redirect_is_rejected() -> None:
    handler = _SafeRedirectHandler()
    request = Request(
        f"{API_PREFIX}/actions/artifacts/{ARTIFACT_ID}/zip",
        headers={"Authorization": f"Bearer {TOKEN}"},
        method="GET",
    )
    with pytest.raises(HTTPError):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://attacker.amazonaws.com/archive.zip",
        )


@pytest.mark.skipif(os.name != "posix", reason="symlink evidence is POSIX-specific")
def test_archive_symlink_input_fails_closed(tmp_path: Path) -> None:
    real = tmp_path / "real.zip"
    real.write_bytes(_archive_bytes())
    linked = tmp_path / "linked.zip"
    linked.symlink_to(real)
    with pytest.raises(GitHubTransportError, match="archive_symlink"):
        _safe_extract(linked, tmp_path / "output")


def test_noreplace_race_and_parent_fsync_failure_do_not_replace_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "new").write_text("new", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    sentinel = target / "keep"
    sentinel.write_text("old", encoding="utf-8")
    with pytest.raises(GitHubTransportError, match="output_exists"):
        _publish_directory(source, target, "bundle_publish")
    assert sentinel.read_text(encoding="utf-8") == "old"

    source = tmp_path / "source-two"
    source.mkdir()
    (source / "new").write_text("new", encoding="utf-8")
    target = tmp_path / "target-two"
    real_fsync = transport_module._fsync_directory

    def fail_parent_fsync(path: Path) -> None:
        if path == target.parent:
            raise OSError("fsync failed")
        real_fsync(path)

    monkeypatch.setattr(transport_module, "_fsync_directory", fail_parent_fsync)
    with pytest.raises(GitHubTransportError, match="bundle_publish"):
        _publish_directory(source, target, "bundle_publish")
    assert not target.exists()
