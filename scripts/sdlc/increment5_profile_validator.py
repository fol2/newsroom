#!/usr/bin/env python3
"""Validate one canonical Increment 5 profile from an exact Git tree.

The receipt proves only that exact manifest bytes passed the reviewed profile
structure and semantic checks loaded from a cache-free materialization of the
stated Git commit/tree. It grants no qualification, production, component,
source, model, provider, spend, write, or public-effect authority.
"""

from __future__ import annotations

import sys

# This executable is an evidence boundary, not an importable convenience. The
# isolated-interpreter requirement is checked before any dependency import, so
# PYTHONPATH, user site packages, and caller-selected import roots cannot supply
# jsonschema or another transitive validator dependency.
if not sys.flags.isolated:
    sys.stderr.write(
        "increment5 profile validation failed: isolated Python mode is required\n"
    )
    raise SystemExit(2)

from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import tarfile
import tempfile
import time
from typing import Any, Iterator


_MAX_INPUT_BYTES = 1_048_576
_MAX_GIT_OUTPUT_BYTES = 65_536
_MAX_ARCHIVE_BYTES = 67_108_864
_MAX_ARCHIVE_MEMBER_BYTES = 16_777_216
_STREAM_CHUNK_BYTES = 65_536
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")
_TRUSTED_GIT_PARENTS = (Path("/usr"), Path("/usr/bin"))
_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
_EXPECTED_FLAGS = frozenset(
    {
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
    }
)
_REQUIRED_MATERIALIZED_FILES = frozenset(
    {
        "newsroom/__init__.py",
        "newsroom/authority/canonical.py",
        "newsroom/increment5/__init__.py",
        "newsroom/increment5/profiles.py",
    }
)


class ProfileInputError(ValueError):
    """The isolated validator input or exact-code identity is invalid."""


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ProfileInputError(f"duplicate JSON object name: {name}")
        result[name] = value
    return result


def _fail(message: str) -> int:
    sys.stderr.write(f"increment5 profile validation failed: {message}\n")
    return 2


def _canonical_git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise ProfileInputError(f"{field} must be 40 lowercase hexadecimal characters")
    return value


def _parse_code_identity_args(argv: list[str]) -> tuple[str, str]:
    if len(argv) != 4:
        raise ProfileInputError(
            "exact code identity arguments are required: "
            "--expected-code-commit-sha <sha> "
            "--expected-code-tree-sha <sha>"
        )
    values: dict[str, str] = {}
    for index in range(0, len(argv), 2):
        flag = argv[index]
        if flag not in _EXPECTED_FLAGS:
            raise ProfileInputError(f"unsupported argument: {flag}")
        if flag in values:
            raise ProfileInputError(f"duplicate argument: {flag}")
        values[flag] = argv[index + 1]
    if frozenset(values) != _EXPECTED_FLAGS:
        raise ProfileInputError("exact code identity arguments are incomplete")
    return (
        _canonical_git_sha(
            values["--expected-code-commit-sha"],
            "expected code commit SHA",
        ),
        _canonical_git_sha(
            values["--expected-code-tree-sha"],
            "expected code tree SHA",
        ),
    )


class _TrustedGitProducer:
    """Exact root-owned Git producer; never selected from caller PATH."""

    __slots__ = ("path", "_identity")

    def __init__(self) -> None:
        self.path = _TRUSTED_GIT_EXECUTABLE
        self._identity = self._capture_identity()

    @staticmethod
    def _require_root_owned_path(path: Path, *, directory: bool) -> os.stat_result:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ProfileInputError("trusted Git producer is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ProfileInputError("trusted Git producer path cannot be a symlink")
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected_type(info.st_mode):
            raise ProfileInputError("trusted Git producer path has the wrong type")
        if info.st_uid != 0 or info.st_gid != 0:
            raise ProfileInputError("trusted Git producer path is not root owned")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ProfileInputError("trusted Git producer path is writable")
        return info

    @staticmethod
    def _binary_identity(path: Path) -> tuple[int, int, int, int, int, int, int, str]:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ProfileInputError("trusted Git producer cannot be opened") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ProfileInputError("trusted Git producer is not a regular file")
            if info.st_uid != 0 or info.st_gid != 0:
                raise ProfileInputError("trusted Git producer is not root owned")
            if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise ProfileInputError("trusted Git producer is writable")
            if not info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                raise ProfileInputError("trusted Git producer is not executable")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1_048_576)
                if not chunk:
                    break
                digest.update(chunk)
            return (
                info.st_dev,
                info.st_ino,
                stat.S_IMODE(info.st_mode),
                info.st_uid,
                info.st_gid,
                info.st_size,
                info.st_mtime_ns,
                digest.hexdigest(),
            )
        finally:
            os.close(descriptor)

    def _capture_identity(self) -> tuple[int, int, int, int, int, int, int, str]:
        for parent in _TRUSTED_GIT_PARENTS:
            self._require_root_owned_path(parent, directory=True)
        self._require_root_owned_path(self.path, directory=False)
        return self._binary_identity(self.path)

    def require_unchanged(self) -> None:
        if self._capture_identity() != self._identity:
            raise ProfileInputError("trusted Git producer identity changed")

    def command(self, *arguments: str) -> list[str]:
        self.require_unchanged()
        return [
            str(self.path),
            "-C",
            str(_REPOSITORY_ROOT),
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            *arguments,
        ]


def _git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PAGER": "cat",
        "PATH": "/usr/bin:/bin",
    }


def _run_git(git: _TrustedGitProducer, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            git.command(*arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            env=_git_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfileInputError("cannot inspect the exact Git code tree") from exc
    finally:
        git.require_unchanged()
    if (
        completed.returncode != 0
        or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES
        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES
    ):
        raise ProfileInputError("cannot inspect the exact Git code tree")
    return completed.stdout


def _git_sha(
    git: _TrustedGitProducer,
    revision: str,
    field: str,
) -> str:
    raw = _run_git(git, "rev-parse", "--verify", revision)
    try:
        value = raw.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise ProfileInputError(f"{field} is not canonical Git text") from exc
    return _canonical_git_sha(value, field)


def _require_stable_clean_code_tree(
    git: _TrustedGitProducer,
    expected_commit: str,
    expected_tree: str,
) -> tuple[str, str]:
    """Require one exact commit/tree and a clean tracked checkout now."""

    actual_commit = _git_sha(git, "HEAD^{commit}", "code commit SHA")
    actual_tree = _git_sha(git, "HEAD^{tree}", "code tree SHA")
    if actual_commit != expected_commit:
        raise ProfileInputError("code commit SHA differs from expected identity")
    if actual_tree != expected_tree:
        raise ProfileInputError("code tree SHA differs from expected identity")
    tracked_status = _run_git(
        git,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    if tracked_status:
        raise ProfileInputError("tracked repository checkout differs from HEAD")
    return actual_commit, actual_tree


def _require_exact_code_tree(
    expected_commit: str,
    expected_tree: str,
) -> tuple[_TrustedGitProducer, str, str]:
    """Bind HEAD and reject tracked changes before repository imports exist."""

    git = _TrustedGitProducer()
    actual_commit, actual_tree = _require_stable_clean_code_tree(
        git,
        expected_commit,
        expected_tree,
    )
    return git, actual_commit, actual_tree


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _stream_bounded_process_to_file(
    command: list[str],
    output_path: Path,
    *,
    env: dict[str, str],
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    failure_message: str,
) -> bytes:
    """Stream both pipes and kill before stdout can exceed the disk cap."""

    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            bufsize=0,
            env=env,
        )
        if process.stdout is None or process.stderr is None:
            raise ProfileInputError(failure_message)
        deadline = time.monotonic() + timeout_seconds
        stderr = bytearray()
        written = 0
        with output_path.open("xb", buffering=0) as output:
            with selectors.DefaultSelector() as selector:
                for stream, stream_name in (
                    (process.stdout, "stdout"),
                    (process.stderr, "stderr"),
                ):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, stream_name)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProfileInputError(failure_message)
                    events = selector.select(min(remaining, 0.25))
                    if not events:
                        continue
                    for key, _ in events:
                        try:
                            chunk = os.read(key.fd, _STREAM_CHUNK_BYTES)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if key.data == "stdout":
                            if written + len(chunk) > max_stdout_bytes:
                                raise ProfileInputError(
                                    "Git archive exceeds the generation limit"
                                )
                            output.write(chunk)
                            written += len(chunk)
                        else:
                            if len(stderr) + len(chunk) > max_stderr_bytes:
                                raise ProfileInputError(failure_message)
                            stderr.extend(chunk)
        wait_remaining = deadline - time.monotonic()
        if wait_remaining <= 0:
            raise ProfileInputError(failure_message)
        try:
            return_code = process.wait(timeout=wait_remaining)
        except subprocess.TimeoutExpired as exc:
            raise ProfileInputError(failure_message) from exc
        if return_code != 0 or written == 0:
            raise ProfileInputError(failure_message)
        return bytes(stderr)
    except ProfileInputError:
        if process is not None:
            _terminate_process(process)
        output_path.unlink(missing_ok=True)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            _terminate_process(process)
        output_path.unlink(missing_ok=True)
        raise ProfileInputError(failure_message) from exc
    finally:
        if process is not None and process.poll() is None:
            _terminate_process(process)


def _write_git_archive(
    git: _TrustedGitProducer,
    commit: str,
    archive_path: Path,
) -> None:
    git.require_unchanged()
    try:
        _stream_bounded_process_to_file(
            git.command(
                "archive",
                "--format=tar",
                commit,
                "--",
                "newsroom",
            ),
            archive_path,
            env=_git_environment(),
            timeout_seconds=30,
            max_stdout_bytes=_MAX_ARCHIVE_BYTES,
            max_stderr_bytes=_MAX_GIT_OUTPUT_BYTES,
            failure_message="cannot materialize the exact Git code tree",
        )
    finally:
        git.require_unchanged()


def _canonical_archive_name(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise ProfileInputError("Git archive contains an unsafe path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ProfileInputError("Git archive contains an unsafe path")
    if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
        raise ProfileInputError("Git archive contains executable bytecode")
    return path


def _extract_exact_archive(archive_path: Path, destination: Path) -> None:
    seen: set[str] = set()
    total_size = 0
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            for member in archive:
                relative = _canonical_archive_name(member.name)
                canonical_name = relative.as_posix()
                if canonical_name in seen:
                    raise ProfileInputError("Git archive contains a duplicate path")
                seen.add(canonical_name)
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile() or member.size < 0:
                    raise ProfileInputError("Git archive contains a non-regular entry")
                if member.size > _MAX_ARCHIVE_MEMBER_BYTES:
                    raise ProfileInputError("Git archive member exceeds the size limit")
                total_size += member.size
                if total_size > _MAX_ARCHIVE_BYTES:
                    raise ProfileInputError("Git archive exceeds the extraction limit")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ProfileInputError("Git archive path already exists")
                source = archive.extractfile(member)
                if source is None:
                    raise ProfileInputError("Git archive member cannot be read")
                remaining = member.size
                with target.open("xb") as output:
                    while remaining:
                        chunk = source.read(min(1_048_576, remaining))
                        if not chunk:
                            raise ProfileInputError("Git archive member is truncated")
                        output.write(chunk)
                        remaining -= len(chunk)
                    if source.read(1):
                        raise ProfileInputError("Git archive member exceeds its size")
    except (OSError, tarfile.TarError) as exc:
        raise ProfileInputError("cannot extract the exact Git code tree") from exc
    if not _REQUIRED_MATERIALIZED_FILES.issubset(seen):
        raise ProfileInputError("Git archive omits required validator source")


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _verify_newsroom_import_origins(root: Path) -> None:
    for name, module in tuple(sys.modules.items()):
        if name != "newsroom" and not name.startswith("newsroom."):
            continue
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str):
            raise ProfileInputError(f"reviewed module has no source path: {name}")
        path = Path(raw_path)
        if path.suffix != ".py" or not _path_is_within(path, root):
            raise ProfileInputError(f"reviewed module did not load from exact tree: {name}")


@contextmanager
def _materialized_repository_api(
    git: _TrustedGitProducer,
    commit: str,
) -> Iterator[tuple[Any, Any, Any, Any, Any]]:
    """Load every Newsroom module from a cache-free exact Git materialization."""

    if any(name == "newsroom" or name.startswith("newsroom.") for name in sys.modules):
        raise ProfileInputError("Newsroom modules loaded before exact-tree materialization")
    with tempfile.TemporaryDirectory(prefix="newsroom-increment5-profile-") as raw_temp:
        temp_root = Path(raw_temp).resolve(strict=True)
        if _path_is_within(temp_root, _REPOSITORY_ROOT):
            raise ProfileInputError("exact Git materialization cannot use the checkout")
        archive_path = temp_root / "tree.tar"
        source_root = temp_root / "source"
        source_root.mkdir(mode=0o700)
        _write_git_archive(git, commit, archive_path)
        _extract_exact_archive(archive_path, source_root)
        archive_path.unlink()

        original_path = list(sys.path)
        original_dont_write = sys.dont_write_bytecode
        filtered_path = [
            entry
            for entry in original_path
            if entry
            and Path(entry).resolve() not in {_REPOSITORY_ROOT, _SCRIPT_DIRECTORY}
        ]
        sys.path[:] = [str(source_root), *filtered_path]
        sys.dont_write_bytecode = True
        importlib.invalidate_caches()
        try:
            canonical_module = importlib.import_module("newsroom.authority.canonical")
            profiles_module = importlib.import_module("newsroom.increment5.profiles")
            _verify_newsroom_import_origins(source_root)
            yield (
                canonical_module.CanonicalizationError,
                canonical_module.canonical_json_bytes,
                canonical_module.digest_bytes,
                profiles_module.Increment5ProfileError,
                profiles_module._check_profile_manifest,
            )
        finally:
            for name in tuple(sys.modules):
                if name == "newsroom" or name.startswith("newsroom."):
                    del sys.modules[name]
            sys.path[:] = original_path
            sys.dont_write_bytecode = original_dont_write
            importlib.invalidate_caches()


def main() -> int:
    try:
        expected_commit, expected_tree = _parse_code_identity_args(sys.argv[1:])
        git, actual_commit, actual_tree = _require_exact_code_tree(
            expected_commit,
            expected_tree,
        )
    except ProfileInputError as exc:
        return _fail(str(exc))

    raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(raw) > _MAX_INPUT_BYTES:
        return _fail("input exceeds 1048576 bytes")

    try:
        with _materialized_repository_api(git, actual_commit) as repository_api:
            (
                canonicalization_error_type,
                canonical_json_bytes,
                digest_bytes,
                profile_error_type,
                check_profile_manifest,
            ) = repository_api
            try:
                value = json.loads(
                    raw.decode("utf-8", errors="strict"),
                    object_pairs_hook=_without_duplicate_names,
                )
                canonical = canonical_json_bytes(value)
            except (
                UnicodeError,
                json.JSONDecodeError,
                canonicalization_error_type,
                ProfileInputError,
            ) as exc:
                return _fail(str(exc))

            if raw != canonical:
                return _fail("input is not canonical JSON")
            if not isinstance(value, dict):
                return _fail("profile manifest must be an object")

            try:
                check_profile_manifest(value)
            except profile_error_type as exc:
                return _fail(str(exc))

            profile_kind = value.get("profile_kind")
            if not isinstance(profile_kind, str):
                return _fail("profile kind is not canonical text")

            receipt = {
                "authority_effect": "NONE",
                "code_commit_sha": actual_commit,
                "code_tree_sha": actual_tree,
                "manifest_digest": digest_bytes(raw),
                "production_activation_authorized": False,
                "profile_kind": profile_kind,
                "qualification_authority_granted": False,
                "schema_version": "newsroom.increment5.profile-validation-receipt.v3",
                "tracked_checkout_clean": True,
                "validation_code_origin": "CACHE_FREE_EXACT_GIT_ARCHIVE",
                "validation_scope": (
                    "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
                ),
                "worktree_imports_used": False,
            }
            receipt_bytes = canonical_json_bytes(receipt) + b"\n"
            _require_stable_clean_code_tree(
                git,
                actual_commit,
                actual_tree,
            )
            sys.stdout.buffer.write(receipt_bytes)
            return 0
    except ProfileInputError as exc:
        return _fail(str(exc))
    except Exception as exc:  # pragma: no cover - fail-closed import boundary
        return _fail(f"cannot load reviewed profile validator: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
