from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import BinaryIO, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

from .artifact_envelope import (
    ArtifactProvenanceError,
    _unique_object,
    _validate_json_depth,
)
from .emit_evidence import canonical_json_bytes, sha256_identity


SCHEMA_VERSION = "newsroom.sdlc.github-transport.v1"
_API_VERSION = "2022-11-28"
_REPOSITORY = "fol2/newsroom"
_API_ORIGIN = "https://api.github.com"
_API_PREFIX = f"{_API_ORIGIN}/repos/{_REPOSITORY}"
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_FILES = 128
_MAX_REDIRECTS = 3
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,255}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_TRANSPORT_KEYS = frozenset(
    {
        "schema_version",
        "transport_identity",
        "run_id",
        "run_attempt",
        "artifact",
        "run_digest",
        "jobs_digest",
        "metadata_digest",
    }
)
_ARTIFACT_KEYS = frozenset(
    {"artifact_id", "name", "size_bytes", "digest", "archive_path", "extracted_path"}
)
_ALLOWED_DOWNLOAD_HOST_SUFFIXES = (
    ".blob.core.windows.net",
    ".amazonaws.com",
    ".githubusercontent.com",
)


class GitHubTransportError(ValueError):
    """Raised when GitHub transport bytes cannot satisfy the SDLC boundary."""


class _Response(Protocol):
    headers: Mapping[str, str]

    def read(self, amount: int = -1) -> bytes: ...

    def geturl(self) -> str: ...

    def close(self) -> None: ...


OpenRequest = Callable[[Request, float], _Response]


@dataclass(frozen=True)
class DownloadedArtifact:
    artifact_id: int
    name: str
    size_bytes: int
    digest: str
    archive_path: str
    extracted_path: str

    def __post_init__(self) -> None:
        _positive(self.artifact_id, "artifact_id")
        _safe_name(self.name, "artifact_name")
        if self.size_bytes > _MAX_ARCHIVE_BYTES:
            raise GitHubTransportError("artifact_size")
        _positive(self.size_bytes, "artifact_size")
        _sha(self.digest, "artifact_digest")
        if self.archive_path != "artifact.zip" or self.extracted_path != "artifact":
            raise GitHubTransportError("artifact_path")

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
            "archive_path": self.archive_path,
            "extracted_path": self.extracted_path,
        }


@dataclass(frozen=True)
class TransportBundle:
    run_id: int
    run_attempt: int
    artifact: DownloadedArtifact
    run_digest: str
    jobs_digest: str
    metadata_digest: str
    transport_identity: str

    def __post_init__(self) -> None:
        _positive(self.run_id, "run_id")
        _positive(self.run_attempt, "run_attempt")
        if not isinstance(self.artifact, DownloadedArtifact):
            raise GitHubTransportError("artifact")
        for value, code in (
            (self.run_digest, "run_digest"),
            (self.jobs_digest, "jobs_digest"),
            (self.metadata_digest, "metadata_digest"),
            (self.transport_identity, "transport_identity"),
        ):
            _sha(value, code)
        expected = sha256_identity(_transport_identity_inputs(self))
        if self.transport_identity != expected:
            raise GitHubTransportError("transport_identity")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "transport_identity": self.transport_identity,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "artifact": self.artifact.as_dict(),
            "run_digest": self.run_digest,
            "jobs_digest": self.jobs_digest,
            "metadata_digest": self.metadata_digest,
        }


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise HTTPError(newurl, code, "unsafe redirect", headers, fp)
        count = int(getattr(req, "_newsroom_redirect_count", 0))
        if count >= _MAX_REDIRECTS:
            raise HTTPError(newurl, code, "redirect limit", headers, fp)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        setattr(redirected, "_newsroom_redirect_count", count + 1)
        old_host = (urlparse(req.full_url).hostname or "").lower()
        new_host = (parsed.hostname or "").lower()
        if new_host != old_host:
            if not _is_allowed_download_url(newurl):
                raise HTTPError(newurl, code, "unsafe redirect host", headers, fp)
            for container in (redirected.headers, redirected.unredirected_hdrs):
                for name in tuple(container):
                    if name.lower() == "authorization":
                        del container[name]
        return redirected


def _default_open(request: Request, timeout: float) -> _Response:
    return build_opener(_SafeRedirectHandler()).open(request, timeout=timeout)


def _positive(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GitHubTransportError(code)
    return value


def _text(value: object, code: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise GitHubTransportError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise GitHubTransportError(code)
    return value


def _safe_name(value: object, code: str) -> str:
    text = _text(value, code, maximum=255)
    if _SAFE_NAME.fullmatch(text) is None:
        raise GitHubTransportError(code)
    return text


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=71)
    if _SHA256.fullmatch(text) is None:
        raise GitHubTransportError(code)
    return text


def _token(value: object) -> str:
    text = _text(value, "token", maximum=4096)
    if any(character.isspace() for character in text):
        raise GitHubTransportError("token")
    return text


def _json_bytes(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise GitHubTransportError(code)
    return value


def _transport_identity_inputs(bundle: TransportBundle) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": bundle.run_id,
        "run_attempt": bundle.run_attempt,
        "artifact": bundle.artifact.as_dict(),
        "run_digest": bundle.run_digest,
        "jobs_digest": bundle.jobs_digest,
        "metadata_digest": bundle.metadata_digest,
    }


def validate_transport_bundle(value: object) -> TransportBundle:
    mapping = _mapping(value, "transport")
    if frozenset(mapping) != _TRANSPORT_KEYS or mapping.get("schema_version") != SCHEMA_VERSION:
        raise GitHubTransportError("transport_shape")
    artifact_value = _mapping(mapping.get("artifact"), "artifact")
    if frozenset(artifact_value) != _ARTIFACT_KEYS:
        raise GitHubTransportError("artifact_shape")
    artifact = DownloadedArtifact(
        artifact_id=_positive(artifact_value.get("artifact_id"), "artifact_id"),
        name=_safe_name(artifact_value.get("name"), "artifact_name"),
        size_bytes=_positive(artifact_value.get("size_bytes"), "artifact_size"),
        digest=_sha(artifact_value.get("digest"), "artifact_digest"),
        archive_path=_text(artifact_value.get("archive_path"), "artifact_path", maximum=64),
        extracted_path=_text(artifact_value.get("extracted_path"), "artifact_path", maximum=64),
    )
    return TransportBundle(
        run_id=_positive(mapping.get("run_id"), "run_id"),
        run_attempt=_positive(mapping.get("run_attempt"), "run_attempt"),
        artifact=artifact,
        run_digest=_sha(mapping.get("run_digest"), "run_digest"),
        jobs_digest=_sha(mapping.get("jobs_digest"), "jobs_digest"),
        metadata_digest=_sha(mapping.get("metadata_digest"), "metadata_digest"),
        transport_identity=_sha(mapping.get("transport_identity"), "transport_identity"),
    )


def _bounded_read(stream: BinaryIO, *, maximum: int, code: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while payload := stream.read(min(1024 * 1024, maximum + 1 - total)):
        total += len(payload)
        if total > maximum:
            raise GitHubTransportError(code)
        chunks.append(payload)
    return b"".join(chunks)


def _unique_json(payload: bytes, code: str) -> Mapping[str, object]:
    if not payload or len(payload) > _MAX_JSON_BYTES:
        raise GitHubTransportError(code)
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        _validate_json_depth(value)
    except (UnicodeError, json.JSONDecodeError, ArtifactProvenanceError) as exc:
        raise GitHubTransportError(code) from exc
    if not isinstance(value, dict):
        raise GitHubTransportError(code)
    return value


def _content_length(headers: Mapping[str, str]) -> int | None:
    raw = headers.get("Content-Length") or headers.get("content-length")
    if raw is None:
        return None
    if not raw.isdigit():
        raise GitHubTransportError("content_length")
    return int(raw)


def _content_type(headers: Mapping[str, str]) -> str | None:
    raw = headers.get("Content-Type") or headers.get("content-type")
    if raw is None:
        return None
    return raw.split(";", 1)[0].strip().lower()


def _is_allowed_download_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower()
    return host == "api.github.com" or any(
        host.endswith(suffix) for suffix in _ALLOWED_DOWNLOAD_HOST_SUFFIXES
    )


def _api_url(path: str, query: Sequence[tuple[str, str]] = ()) -> str:
    if not path.startswith("/") or ".." in PurePosixPath(path).parts:
        raise GitHubTransportError("api_path")
    return urlunparse(("https", "api.github.com", path, "", urlencode(query), ""))


class GitHubActionsClient:
    def __init__(
        self,
        token: str,
        *,
        open_request: OpenRequest | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._token = _token(token)
        if not 0 < timeout_seconds <= 30:
            raise GitHubTransportError("timeout")
        self._timeout = float(timeout_seconds)
        self._open = open_request or _default_open

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> "GitHubActionsClient":
        env = os.environ if environment is None else environment
        value = env.get("GITHUB_TOKEN")
        if value is None:
            raise GitHubTransportError("token_missing")
        return cls(value, **kwargs)  # type: ignore[arg-type]

    def _request(self, url: str, *, download: bool = False) -> _Response:
        if not url.startswith(_API_PREFIX + "/"):
            raise GitHubTransportError("api_url")
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": _API_VERSION,
                "User-Agent": "newsroom-sdlc-evidence",
            },
        )
        try:
            response = self._open(request, self._timeout)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            raise GitHubTransportError("github_request") from exc
        final_url = response.geturl()
        if download:
            if not _is_allowed_download_url(final_url):
                response.close()
                raise GitHubTransportError("download_redirect")
        elif final_url != url:
            response.close()
            raise GitHubTransportError("api_redirect")
        return response

    def _get_json(self, url: str) -> Mapping[str, object]:
        response = self._request(url)
        with closing(response):
            content_type = _content_type(response.headers)
            if content_type is not None and content_type not in {
                "application/json",
                "application/vnd.github+json",
            }:
                raise GitHubTransportError("json_content_type")
            length = _content_length(response.headers)
            if length is not None and not 0 < length <= _MAX_JSON_BYTES:
                raise GitHubTransportError("json_size")
            payload = _bounded_read(response, maximum=_MAX_JSON_BYTES, code="json_size")
        return _unique_json(payload, "json_response")

    def fetch_run(self, run_id: int) -> Mapping[str, object]:
        run = _positive(run_id, "run_id")
        value = self._get_json(f"{_API_PREFIX}/actions/runs/{run}")
        repository = _mapping(value.get("repository"), "run_repository")
        head_repository = _mapping(value.get("head_repository"), "run_head_repository")
        if (
            value.get("id") != run
            or repository.get("full_name") != _REPOSITORY
            or not isinstance(repository.get("id"), int)
            or not isinstance(head_repository.get("full_name"), str)
            or not isinstance(head_repository.get("id"), int)
            or _GIT_SHA.fullmatch(str(value.get("head_sha", ""))) is None
            or not isinstance(value.get("run_attempt"), int)
            or value.get("run_attempt", 0) <= 0
        ):
            raise GitHubTransportError("run_identity")
        return value

    def fetch_jobs(self, run_id: int, run_attempt: int) -> Mapping[str, object]:
        run = _positive(run_id, "run_id")
        attempt = _positive(run_attempt, "run_attempt")
        url = _api_url(
            f"/repos/{_REPOSITORY}/actions/runs/{run}/attempts/{attempt}/jobs",
            (("filter", "all"), ("per_page", "100")),
        )
        value = self._get_json(url)
        jobs = value.get("jobs")
        total = value.get("total_count")
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or not isinstance(jobs, list)
            or total != len(jobs)
            or total > 100
        ):
            raise GitHubTransportError("jobs_pagination")
        return value

    def list_artifacts(self, run_id: int) -> Mapping[str, object]:
        run = _positive(run_id, "run_id")
        url = _api_url(
            f"/repos/{_REPOSITORY}/actions/runs/{run}/artifacts",
            (("per_page", "100"),),
        )
        value = self._get_json(url)
        artifacts = value.get("artifacts")
        total = value.get("total_count")
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or not isinstance(artifacts, list)
            or total != len(artifacts)
            or total > 100
        ):
            raise GitHubTransportError("artifact_pagination")
        return value

    def select_artifact(self, run_id: int, expected_name: str) -> Mapping[str, object]:
        name = _safe_name(expected_name, "artifact_name")
        listed = self.list_artifacts(run_id)
        matches = [
            item
            for item in listed["artifacts"]  # type: ignore[index]
            if isinstance(item, dict) and item.get("name") == name
        ]
        if len(matches) != 1 or matches[0].get("expired") is not False:
            raise GitHubTransportError("artifact_identity")
        artifact_id = _positive(matches[0].get("id"), "artifact_id")
        metadata = self._get_json(f"{_API_PREFIX}/actions/artifacts/{artifact_id}")
        expected_url = f"{_API_PREFIX}/actions/artifacts/{artifact_id}"
        if (
            metadata.get("id") != artifact_id
            or metadata.get("name") != name
            or metadata.get("expired") is not False
            or metadata.get("url") != expected_url
            or metadata.get("archive_download_url") != expected_url + "/zip"
        ):
            raise GitHubTransportError("artifact_identity")
        size = _positive(metadata.get("size_in_bytes"), "artifact_size")
        if size > _MAX_ARCHIVE_BYTES:
            raise GitHubTransportError("artifact_size")
        _sha(metadata.get("digest"), "artifact_digest")
        workflow_run = metadata.get("workflow_run")
        if (
            not isinstance(workflow_run, dict)
            or workflow_run.get("id") != run_id
            or _GIT_SHA.fullmatch(str(workflow_run.get("head_sha", ""))) is None
        ):
            raise GitHubTransportError("artifact_run_identity")
        return metadata

    def download_artifact(
        self,
        metadata: Mapping[str, object],
        output_path: Path,
    ) -> tuple[int, str]:
        artifact_id = _positive(metadata.get("id"), "artifact_id")
        size = _positive(metadata.get("size_in_bytes"), "artifact_size")
        if size > _MAX_ARCHIVE_BYTES:
            raise GitHubTransportError("artifact_size")
        expected_digest = _sha(metadata.get("digest"), "artifact_digest")
        expected_url = f"{_API_PREFIX}/actions/artifacts/{artifact_id}/zip"
        if metadata.get("archive_download_url") != expected_url:
            raise GitHubTransportError("artifact_download_url")
        if output_path.exists() or output_path.is_symlink():
            raise GitHubTransportError("output_exists")
        response = self._request(expected_url, download=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        total = 0
        linked = False
        try:
            os.fchmod(descriptor, 0o600)
            with closing(response), os.fdopen(descriptor, "wb", closefd=True) as stream:
                length = _content_length(response.headers)
                if length is not None and length != size:
                    raise GitHubTransportError("artifact_size")
                while payload := response.read(1024 * 1024):
                    total += len(payload)
                    if total > size or total > _MAX_ARCHIVE_BYTES:
                        raise GitHubTransportError("artifact_size")
                    digest.update(payload)
                    stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            rendered_digest = "sha256:" + digest.hexdigest()
            if total != size:
                raise GitHubTransportError("artifact_size")
            if rendered_digest != expected_digest:
                raise GitHubTransportError("artifact_digest")
            try:
                os.link(temporary, output_path, follow_symlinks=False)
                linked = True
                _fsync_directory(output_path.parent)
            except FileExistsError as exc:
                raise GitHubTransportError("output_exists") from exc
            except OSError as exc:
                if linked:
                    output_path.unlink(missing_ok=True)
                raise GitHubTransportError("output_publish") from exc
            return total, rendered_digest
        finally:
            temporary.unlink(missing_ok=True)


def _member_path(value: str) -> PurePosixPath:
    if (
        not value
        or len(value) > 1024
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise GitHubTransportError("archive_member")
    candidate = PurePosixPath(value.rstrip("/"))
    if not candidate.parts or candidate.is_absolute() or ".." in candidate.parts:
        raise GitHubTransportError("archive_member")
    if candidate.as_posix() != value.rstrip("/"):
        raise GitHubTransportError("archive_member")
    return candidate


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_output_root(parent: Path, name: str) -> Path:
    normalized = _safe_name(name, "output_name")
    absolute = parent if parent.is_absolute() else parent.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise GitHubTransportError("output_parent")
    root = absolute.resolve()
    if not root.is_dir():
        raise GitHubTransportError("output_parent")
    target = root / normalized
    if target.exists() or target.is_symlink():
        raise GitHubTransportError("output_exists")
    return target


def _validated_zip_members(
    archive: zipfile.ZipFile,
) -> tuple[tuple[zipfile.ZipInfo, PurePosixPath], ...]:
    members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    kinds: dict[str, str] = {}
    total_uncompressed = 0
    for info in archive.infolist():
        member = _member_path(info.filename)
        normalized = member.as_posix()
        if normalized in kinds:
            raise GitHubTransportError("archive_duplicate")
        is_directory = info.is_dir()
        mode = info.external_attr >> 16
        if (
            info.flag_bits & 0x1
            or info.compress_type not in _ALLOWED_COMPRESSION
            or (is_directory and info.file_size != 0)
            or (is_directory and mode and not stat.S_ISDIR(mode))
            or (not is_directory and mode and not stat.S_ISREG(mode))
        ):
            raise GitHubTransportError("archive_member")
        if not is_directory and not 0 < info.file_size <= _MAX_MEMBER_BYTES:
            raise GitHubTransportError("archive_member")
        parent = PurePosixPath()
        for part in member.parts[:-1]:
            parent /= part
            if kinds.get(parent.as_posix()) == "file":
                raise GitHubTransportError("archive_member_conflict")
        if not is_directory and any(
            path.startswith(normalized + "/") for path in kinds
        ):
            raise GitHubTransportError("archive_member_conflict")
        kinds[normalized] = "directory" if is_directory else "file"
        if len(kinds) > _MAX_FILES:
            raise GitHubTransportError("archive_file_count")
        if not is_directory:
            total_uncompressed += info.file_size
            if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
                raise GitHubTransportError("archive_uncompressed_size")
        members.append((info, member))
    if not members:
        raise GitHubTransportError("archive_empty")
    return tuple(members)


def _fsync_tree(root: Path) -> None:
    directories = [root]
    directories.extend(path for path in root.rglob("*") if path.is_dir())
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(directory)


def _rename_directory_noreplace(source: Path, target: Path) -> None:
    if os.name != "posix" or not sys.platform.startswith("linux"):
        raise GitHubTransportError("noreplace_rename_unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise GitHubTransportError("noreplace_rename_unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(target),
        1,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise GitHubTransportError("output_exists")
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise GitHubTransportError("noreplace_rename_unavailable")
    raise GitHubTransportError("output_publish")


def _publish_directory(source: Path, target: Path, code: str) -> None:
    published = False
    try:
        _rename_directory_noreplace(source, target)
        published = True
        _fsync_directory(target.parent)
    except GitHubTransportError:
        if published:
            shutil.rmtree(target, ignore_errors=True)
        raise
    except OSError as exc:
        if published:
            shutil.rmtree(target, ignore_errors=True)
        raise GitHubTransportError(code) from exc


def _safe_extract(archive_path: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise GitHubTransportError("output_exists")
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    published = False
    try:
        os.chmod(temporary, 0o700)
        try:
            archive = zipfile.ZipFile(archive_path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise GitHubTransportError("archive_zip") from exc
        with archive:
            members = _validated_zip_members(archive)
            for info, member in members:
                destination = temporary.joinpath(*member.parts)
                if info.is_dir():
                    try:
                        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
                    except FileExistsError:
                        if not destination.is_dir() or destination.is_symlink():
                            raise GitHubTransportError("archive_member_conflict")
                    continue
                try:
                    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                except OSError as exc:
                    raise GitHubTransportError("archive_extract") from exc
                current = temporary
                for part in member.parts[:-1]:
                    current /= part
                    if current.is_symlink() or not current.is_dir():
                        raise GitHubTransportError("archive_member_conflict")
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    descriptor = os.open(destination, flags, 0o600)
                except OSError as exc:
                    raise GitHubTransportError("archive_extract") from exc
                total = 0
                try:
                    with archive.open(info, "r") as source, os.fdopen(
                        descriptor, "wb", closefd=True
                    ) as output:
                        while payload := source.read(1024 * 1024):
                            total += len(payload)
                            if total > info.file_size or total > _MAX_MEMBER_BYTES:
                                raise GitHubTransportError("archive_member_size")
                            output.write(payload)
                        output.flush()
                        os.fsync(output.fileno())
                except GitHubTransportError:
                    raise
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    raise GitHubTransportError("archive_extract") from exc
                if total != info.file_size:
                    raise GitHubTransportError("archive_member_size")
        _fsync_tree(temporary)
        _publish_directory(temporary, target, "archive_publish")
        published = True
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


def _write_private(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise GitHubTransportError("output_exists")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise GitHubTransportError("output_open") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def fetch_artifact_bundle(
    *,
    client: GitHubActionsClient,
    output_parent: str | Path,
    output_name: str,
    run_id: int,
    run_attempt: int,
    artifact_name: str,
) -> TransportBundle:
    run = _positive(run_id, "run_id")
    attempt = _positive(run_attempt, "run_attempt")
    name = _safe_name(artifact_name, "artifact_name")
    parent = Path(output_parent)
    target = _safe_output_root(parent, output_name)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    published = False
    try:
        os.chmod(temporary, 0o700)
        run_value = client.fetch_run(run)
        if run_value.get("run_attempt") != attempt:
            raise GitHubTransportError("run_attempt")
        jobs_value = client.fetch_jobs(run, attempt)
        metadata = client.select_artifact(run, name)
        run_payload = _json_bytes(run_value)
        jobs_payload = _json_bytes(jobs_value)
        metadata_payload = _json_bytes(metadata)
        _write_private(temporary / "run.json", run_payload)
        _write_private(temporary / "jobs.json", jobs_payload)
        _write_private(temporary / "metadata.json", metadata_payload)
        archive_path = temporary / "artifact.zip"
        size, digest = client.download_artifact(metadata, archive_path)
        extracted_path = temporary / "artifact"
        _safe_extract(archive_path, extracted_path)
        artifact_id = _positive(metadata.get("id"), "artifact_id")
        artifact = DownloadedArtifact(
            artifact_id=artifact_id,
            name=name,
            size_bytes=size,
            digest=digest,
            archive_path="artifact.zip",
            extracted_path="artifact",
        )
        identity_inputs = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run,
            "run_attempt": attempt,
            "artifact": artifact.as_dict(),
            "run_digest": "sha256:" + hashlib.sha256(run_payload).hexdigest(),
            "jobs_digest": "sha256:" + hashlib.sha256(jobs_payload).hexdigest(),
            "metadata_digest": "sha256:" + hashlib.sha256(metadata_payload).hexdigest(),
        }
        bundle = TransportBundle(
            run_id=run,
            run_attempt=attempt,
            artifact=artifact,
            run_digest=str(identity_inputs["run_digest"]),
            jobs_digest=str(identity_inputs["jobs_digest"]),
            metadata_digest=str(identity_inputs["metadata_digest"]),
            transport_identity=sha256_identity(identity_inputs),
        )
        validate_transport_bundle(bundle.as_dict())
        _write_private(temporary / "transport.json", _json_bytes(bundle.as_dict()))
        _fsync_tree(temporary)
        _publish_directory(temporary, target, "bundle_publish")
        published = True
        return bundle
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch exact GitHub Actions evidence")
    parser.add_argument("--output-parent", default=".")
    parser.add_argument("--output-name", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--artifact-name", required=True)
    arguments = parser.parse_args(argv)
    try:
        client = GitHubActionsClient.from_environment()
        bundle = fetch_artifact_bundle(
            client=client,
            output_parent=arguments.output_parent,
            output_name=arguments.output_name,
            run_id=arguments.run_id,
            run_attempt=arguments.run_attempt,
            artifact_name=arguments.artifact_name,
        )
        sys.stdout.write(canonical_json_bytes(bundle.as_dict()).decode("utf-8") + "\n")
    except (GitHubTransportError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        reason = (
            str(exc)
            if isinstance(exc, GitHubTransportError) and str(exc)
            else type(exc).__name__
        )
        print(f"EVIDENCE_MISMATCH:github-transport:{reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
