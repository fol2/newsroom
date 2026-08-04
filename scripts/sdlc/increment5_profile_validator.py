#!/usr/bin/env python3
"""Validate one canonical Increment 5 profile from an exact Git blob.

The signed outer launcher—not this Python process—authenticates and streams the
validator bytes from the expected commit before Python executes them. This stdlib-only inner process then binds the exact repository, validator
blob, manifest bytes, runtime, and a bounded prewrite checkout snapshot into a
non-authoritative receipt. It does not attest mutable checkout, index, or HEAD
state at completion or after handoff. The receipt cannot authenticate its own
executed source and grants no authority without the separately signed
outer-launch evidence.
"""

from __future__ import annotations

import sys

if (
    not sys.flags.isolated
    or not sys.flags.no_site
    or sys.argv[0] != "-"
):
    sys.stderr.write(
        "increment5 profile validation failed: signed outer Git-blob launcher "
        "with trusted isolated no-site Python is required\n"
    )
    raise SystemExit(2)

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import time
from typing import Any, BinaryIO


_MIN_SAFE_INTEGER = -9_007_199_254_740_991
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_INPUT_BYTES = 1_048_576
_MAX_GIT_OUTPUT_BYTES = 65_536
_MAX_INDEX_LIST_BYTES = 16_777_216
_MAX_TRACKED_TREE_BYTES = 16_777_216
_MAX_TRACKED_FILE_BYTES = 67_108_864
_MAX_TRACKED_TOTAL_BYTES = 536_870_912
_MAX_TRACKED_PATHS = 100_000
_MAX_REVIEWED_BLOB_BYTES = 16_777_216
_MAX_REVIEWED_TOTAL_BYTES = 67_108_864
_STREAM_CHUNK_BYTES = 65_536
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_TRUSTED_PYTHON_EXECUTABLE = Path("/usr/bin/python3")
_TRUSTED_PYTHON_PARENTS = (Path("/usr"), Path("/usr/bin"))
_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")
_TRUSTED_GIT_PARENTS = (Path("/usr"), Path("/usr/bin"))
_INVOCATION_FLAGS = frozenset(
    {
        "--repository-root",
        "--git-dir",
        "--index-file",
        "--manifest-fd",
        "--expected-validator-blob-sha",
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
    }
)
_VALIDATOR_PATH = "scripts/sdlc/increment5_profile_validator.py"
_CONTRACT_PATH = "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"
_FIXTURE_STRUCTURAL_PATH = (
    "newsroom/increment5/data/"
    "increment5_fixture_replay_profile_structural_v1.schema.json"
)
_QUALIFICATION_STRUCTURAL_PATH = (
    "newsroom/increment5/data/"
    "increment5_qualification_profile_structural_v1.schema.json"
)
_FIXTURE_BINDING_PATH = (
    "newsroom/increment5/data/increment5_fixture_replay_profile_v1.schema.json"
)
_QUALIFICATION_BINDING_PATH = (
    "newsroom/increment5/data/increment5_qualification_profile_v1.schema.json"
)
_REVIEWED_BLOBS = {
    _CONTRACT_PATH: "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c",
    _FIXTURE_STRUCTURAL_PATH: "sha256:7c2e50d952109d834d944c120b8f9a5adcc59c6f39106430fa8728c5ad25c9a0",
    _QUALIFICATION_STRUCTURAL_PATH: "sha256:7b055832c33f9d9bf25f3401fce936bba3a2310da8f272038de4f0625356685b",
    _FIXTURE_BINDING_PATH: "sha256:6783030456d1d4ba5744a70932ee2982c099a3cf324ad98e2d05413216d7d571",
    _QUALIFICATION_BINDING_PATH: "sha256:5d48af523da006bec804893f0bd42b411a466ca29103a8dde8fc46db49ced354",
}
_SAFE_RUNTIME_EFFECTS = {
    "external_calls": 0,
    "live_sources": False,
    "model_load": False,
    "protected_content": False,
    "provider_credentials": False,
    "provider_spend_microunits": 0,
    "public_effect": False,
    "write_authority": False,
}


class ProfileInputError(ValueError):
    """The evidence input or repository boundary is invalid."""


def _fail(message: str) -> int:
    sys.stderr.write(f"increment5 profile validation failed: {message}\n")
    return 2


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ProfileInputError(f"duplicate JSON object name: {name}")
        result[name] = value
    return result


def _validate_restricted_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not _MIN_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER:
            raise ProfileInputError(
                f"integer outside the interoperable safe range at {path}"
            )
        return
    if isinstance(value, float):
        raise ProfileInputError(f"floating-point values are unsupported at {path}")
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ProfileInputError(f"lone surrogate is unsupported at {path}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProfileInputError(f"object names must be strings at {path}")
            _validate_restricted_value(key, f"{path}.<key>")
            _validate_restricted_value(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_restricted_value(item, f"{path}[{index}]")
        return
    raise ProfileInputError(
        f"unsupported value type at {path}: {type(value).__name__}"
    )


def _canonical_json_bytes(value: Any) -> bytes:
    _validate_restricted_value(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProfileInputError(f"canonical JSON encoding failed: {exc}") from exc


def _digest_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _validate_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or value != value.strip().lower():
        raise ProfileInputError(f"{field} must be a canonical digest")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ProfileInputError(f"{field} must be a canonical digest")
    return value


def _parse_canonical_object(raw: bytes, field: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
    except (UnicodeError, json.JSONDecodeError, ProfileInputError) as exc:
        raise ProfileInputError(f"{field} cannot be reconstructed") from exc
    if not isinstance(value, dict):
        raise ProfileInputError(f"{field} must be an object")
    if raw != _canonical_json_bytes(value):
        raise ProfileInputError(f"{field} is not canonical JSON")
    return value


def _parse_input_manifest(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileInputError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ProfileInputError("profile manifest must be an object")
    if raw != _canonical_json_bytes(value):
        raise ProfileInputError("input is not canonical JSON")
    return value


class _TrustedGitBinary:
    __slots__ = ("path", "_identity")

    def __init__(self) -> None:
        self.path = _TRUSTED_GIT_EXECUTABLE
        self._identity = self._capture_identity()

    @staticmethod
    def _require_path(path: Path, *, directory: bool) -> os.stat_result:
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
            self._require_path(parent, directory=True)
        self._require_path(self.path, directory=False)
        return self._binary_identity(self.path)

    def require_unchanged(self) -> None:
        if self._capture_identity() != self._identity:
            raise ProfileInputError("trusted Git producer identity changed")


class _TrustedPythonRuntime:
    __slots__ = ("launcher", "target", "_identity")

    def __init__(self) -> None:
        self.launcher = _TRUSTED_PYTHON_EXECUTABLE
        self.target = self._resolve_target()
        try:
            invoked = Path(sys.executable).absolute()
            actual_target = Path(sys.executable).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProfileInputError(
                "trusted system Python executable cannot be resolved"
            ) from exc
        if invoked != self.launcher or actual_target != self.target:
            raise ProfileInputError(
                "trusted system Python executable is required"
            )
        self._identity = self._binary_identity(self.target)

    @staticmethod
    def _require_secure_path(
        path: Path,
        *,
        directory: bool,
        symlink_allowed: bool = False,
    ) -> os.stat_result:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ProfileInputError(
                "trusted system Python path is unavailable"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            if not symlink_allowed:
                raise ProfileInputError(
                    "trusted system Python path cannot be a symlink"
                )
            if info.st_uid != 0 or info.st_gid != 0:
                raise ProfileInputError(
                    "trusted system Python path is not root owned"
                )
            # POSIX symlink permission bits are not access controls and are
            # commonly reported as 0777. The resolved target is checked below.
            return info
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected_type(info.st_mode):
            raise ProfileInputError(
                "trusted system Python path has the wrong type"
            )
        if info.st_uid != 0 or info.st_gid != 0:
            raise ProfileInputError(
                "trusted system Python path is not root owned"
            )
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ProfileInputError(
                "trusted system Python path is writable"
            )
        return info

    @staticmethod
    def _binary_identity(
        path: Path,
    ) -> tuple[int, int, int, int, int, int, int, str]:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ProfileInputError(
                "trusted system Python executable cannot be opened"
            ) from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ProfileInputError(
                    "trusted system Python executable is not a regular file"
                )
            if info.st_uid != 0 or info.st_gid != 0:
                raise ProfileInputError(
                    "trusted system Python executable is not root owned"
                )
            if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise ProfileInputError(
                    "trusted system Python executable is writable"
                )
            if not info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                raise ProfileInputError(
                    "trusted system Python executable is not executable"
                )
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

    def _resolve_target(self) -> Path:
        for parent in _TRUSTED_PYTHON_PARENTS:
            self._require_secure_path(parent, directory=True)
        self._require_secure_path(
            self.launcher,
            directory=False,
            symlink_allowed=True,
        )
        try:
            target = self.launcher.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProfileInputError(
                "trusted system Python executable cannot be resolved"
            ) from exc
        if target.parent != Path("/usr/bin"):
            raise ProfileInputError(
                "trusted system Python target is outside /usr/bin"
            )
        self._require_secure_path(target, directory=False)
        return target

    def require_unchanged(self) -> None:
        try:
            invoked = Path(sys.executable).absolute()
            actual_target = Path(sys.executable).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProfileInputError(
                "trusted system Python executable cannot be resolved"
            ) from exc
        if invoked != self.launcher or actual_target != self.target:
            raise ProfileInputError(
                "trusted system Python executable changed"
            )
        if self._resolve_target() != self.target:
            raise ProfileInputError(
                "trusted system Python executable changed"
            )
        if self._binary_identity(self.target) != self._identity:
            raise ProfileInputError(
                "trusted system Python executable identity changed"
            )


def _base_git_environment() -> dict[str, str]:
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


def _capture_bounded_process(
    command: list[str],
    *,
    env: dict[str, str],
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    failure_message: str,
) -> bytes:
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=env,
        )
        if process.stdout is None or process.stderr is None:
            raise ProfileInputError(failure_message)
        stdout = bytearray()
        stderr = bytearray()
        deadline = time.monotonic() + timeout_seconds
        with selectors.DefaultSelector() as selector:
            for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
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
                    target = stdout if key.data == "stdout" else stderr
                    maximum = (
                        max_stdout_bytes if key.data == "stdout" else max_stderr_bytes
                    )
                    if len(target) + len(chunk) > maximum:
                        raise ProfileInputError(failure_message)
                    target.extend(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProfileInputError(failure_message)
        try:
            return_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise ProfileInputError(failure_message) from exc
        if return_code != 0:
            raise ProfileInputError(failure_message)
        return bytes(stdout)
    except ProfileInputError:
        if process is not None:
            _terminate_process(process)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            _terminate_process(process)
        raise ProfileInputError(failure_message) from exc
    finally:
        if process is not None and process.poll() is None:
            _terminate_process(process)


class _TrustedRepositoryView:
    __slots__ = ("root", "git", "git_dir", "index_path", "_environment")

    def __init__(self, root: Path, git_dir: Path, index_path: Path) -> None:
        try:
            self.root = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProfileInputError("repository root is unavailable") from exc
        try:
            current_root = Path.cwd().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProfileInputError("current repository root is unavailable") from exc
        if current_root != self.root:
            raise ProfileInputError("repository root differs from current checkout")

        expected_git_dir = self.root / ".git"
        expected_index = expected_git_dir / "index"
        if git_dir != expected_git_dir or index_path != expected_index:
            raise ProfileInputError("outer launcher repository paths differ")
        self._require_repository_path(expected_git_dir, directory=True)
        self._require_repository_path(expected_index, directory=False)
        self.git_dir = expected_git_dir
        self.index_path = expected_index
        self.git = _TrustedGitBinary()

        environment = _base_git_environment()
        environment.update(
            {
                "GIT_DIR": str(self.git_dir),
                "GIT_INDEX_FILE": str(self.index_path),
                "GIT_WORK_TREE": str(self.root),
            }
        )
        self._environment = environment

    @staticmethod
    def _require_repository_path(path: Path, *, directory: bool) -> None:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ProfileInputError("repository metadata path is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ProfileInputError("repository metadata path cannot be a symlink")
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected_type(info.st_mode):
            raise ProfileInputError("repository metadata path has the wrong type")
        if info.st_uid not in {0, os.getuid()}:
            raise ProfileInputError("repository metadata path has an unexpected owner")
        if info.st_mode & stat.S_IWOTH:
            raise ProfileInputError("repository metadata path is world writable")

    def command(self, *arguments: str) -> list[str]:
        self.git.require_unchanged()
        return [
            str(self.git.path),
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.root}",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.trustctime=true",
            "-c",
            "core.checkStat=default",
            "-c",
            "core.ignoreStat=false",
            "-c",
            "core.fileMode=true",
            *arguments,
        ]

    def run(
        self,
        *arguments: str,
        max_stdout_bytes: int = _MAX_GIT_OUTPUT_BYTES,
        timeout_seconds: float = 10,
        failure_message: str = "cannot inspect the exact Git code tree",
    ) -> bytes:
        self.git.require_unchanged()
        try:
            return _capture_bounded_process(
                self.command(*arguments),
                env=dict(self._environment),
                timeout_seconds=timeout_seconds,
                max_stdout_bytes=max_stdout_bytes,
                max_stderr_bytes=_MAX_GIT_OUTPUT_BYTES,
                failure_message=failure_message,
            )
        finally:
            self.git.require_unchanged()

    def _require_commit_tree_identity(self, commit: str, tree: str) -> None:
        actual_commit = _git_sha(self, "HEAD^{commit}", "code commit SHA")
        actual_tree = _git_sha(self, "HEAD^{tree}", "code tree SHA")
        if actual_commit != commit:
            raise ProfileInputError("code commit SHA differs from expected identity")
        if actual_tree != tree:
            raise ProfileInputError("code tree SHA differs from expected identity")

    def require_stable_clean_tree(self, commit: str, tree: str) -> None:
        self._require_commit_tree_identity(commit, tree)
        self._reject_hidden_index_flags()
        expected = self._read_expected_tree(commit)
        self._require_index_matches_tree(expected)
        self._require_worktree_matches_tree(expected)

        # The worktree traversal is intentionally bounded but can be long. A
        # concurrent HEAD or index change during that traversal must not leave
        # the prewrite snapshot associated with stale repository metadata.
        self._require_commit_tree_identity(commit, tree)
        self._reject_hidden_index_flags()
        self._require_index_matches_tree(expected)

    @staticmethod
    def _parse_tree_record(
        record: bytes,
        *,
        index: bool,
    ) -> tuple[str, str, str]:
        try:
            metadata, raw_path = record.split(b"\t", 1)
            fields = metadata.split(b" ")
            if index:
                if len(fields) != 3 or fields[2] != b"0":
                    raise ValueError
                mode_raw, oid_raw = fields[:2]
            else:
                if len(fields) != 3 or fields[1] != b"blob":
                    raise ValueError
                mode_raw, oid_raw = fields[0], fields[2]
            mode = mode_raw.decode("ascii", errors="strict")
            oid = oid_raw.decode("ascii", errors="strict")
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeError) as exc:
            raise ProfileInputError("tracked tree inventory is malformed") from exc
        if mode not in {"100644", "100755", "120000"}:
            raise ProfileInputError("tracked tree contains an unsupported entry")
        if not _GIT_SHA.fullmatch(oid):
            raise ProfileInputError("tracked tree contains a malformed blob identity")
        pure = PurePosixPath(path)
        if (
            not path
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ProfileInputError("tracked tree contains an unsafe path")
        return path, mode, oid

    def _read_expected_tree(self, commit: str) -> dict[str, tuple[str, str]]:
        raw = self.run(
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            commit,
            max_stdout_bytes=_MAX_TRACKED_TREE_BYTES,
            timeout_seconds=30,
            failure_message="cannot inspect exact tracked tree",
        )
        result: dict[str, tuple[str, str]] = {}
        for record in raw.split(b"\0"):
            if not record:
                continue
            path, mode, oid = self._parse_tree_record(record, index=False)
            if path in result:
                raise ProfileInputError("tracked tree contains a duplicate path")
            result[path] = (mode, oid)
            if len(result) > _MAX_TRACKED_PATHS:
                raise ProfileInputError("tracked tree exceeds the path limit")
        if not result:
            raise ProfileInputError("tracked tree is empty")
        return result

    def _require_index_matches_tree(
        self,
        expected: dict[str, tuple[str, str]],
    ) -> None:
        raw = self.run(
            "ls-files",
            "-s",
            "-z",
            "--",
            max_stdout_bytes=_MAX_TRACKED_TREE_BYTES,
            timeout_seconds=30,
            failure_message="cannot inspect exact tracked index",
        )
        actual: dict[str, tuple[str, str]] = {}
        for record in raw.split(b"\0"):
            if not record:
                continue
            path, mode, oid = self._parse_tree_record(record, index=True)
            if path in actual:
                raise ProfileInputError("tracked index contains a duplicate path")
            actual[path] = (mode, oid)
        if actual != expected:
            raise ProfileInputError("tracked repository index differs from HEAD")

    def _tracked_path(
        self,
        relative: str,
        directories: set[Path],
    ) -> Path:
        pure = PurePosixPath(relative)
        current = self.root
        for part in pure.parts[:-1]:
            current = current / part
            if current in directories:
                continue
            try:
                info = current.lstat()
            except OSError as exc:
                raise ProfileInputError(
                    "tracked repository checkout differs from HEAD"
                ) from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ProfileInputError(
                    "tracked repository checkout differs from HEAD"
                )
            directories.add(current)
        return current / pure.parts[-1]

    @staticmethod
    def _blob_digest_for_bytes(data: bytes) -> str:
        digest = hashlib.sha1(usedforsecurity=False)
        digest.update(f"blob {len(data)}\0".encode("ascii"))
        digest.update(data)
        return digest.hexdigest()

    @staticmethod
    def _stable_stat_identity(info: os.stat_result) -> tuple[int, ...]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def _regular_blob_digest(
        self,
        path: Path,
        before: os.stat_result,
    ) -> tuple[str, int]:
        if before.st_size > _MAX_TRACKED_FILE_BYTES:
            raise ProfileInputError("tracked file exceeds the verification limit")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ProfileInputError(
                "tracked repository checkout differs from HEAD"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if self._stable_stat_identity(opened) != self._stable_stat_identity(before):
                raise ProfileInputError(
                    "tracked repository checkout changed during verification"
                )
            digest = hashlib.sha1(usedforsecurity=False)
            digest.update(f"blob {opened.st_size}\0".encode("ascii"))
            consumed = 0
            while True:
                chunk = os.read(descriptor, 1_048_576)
                if not chunk:
                    break
                consumed += len(chunk)
                if consumed > opened.st_size:
                    raise ProfileInputError(
                        "tracked repository checkout changed during verification"
                    )
                digest.update(chunk)
            after = os.fstat(descriptor)
            if (
                consumed != opened.st_size
                or self._stable_stat_identity(after)
                != self._stable_stat_identity(opened)
            ):
                raise ProfileInputError(
                    "tracked repository checkout changed during verification"
                )
            return digest.hexdigest(), consumed
        finally:
            os.close(descriptor)

    def _require_worktree_matches_tree(
        self,
        expected: dict[str, tuple[str, str]],
    ) -> None:
        directories: set[Path] = {self.root}
        total = 0
        for relative in sorted(expected):
            mode, oid = expected[relative]
            path = self._tracked_path(relative, directories)
            try:
                before = path.lstat()
            except OSError as exc:
                raise ProfileInputError(
                    "tracked repository checkout differs from HEAD"
                ) from exc
            if mode == "120000":
                if not stat.S_ISLNK(before.st_mode):
                    raise ProfileInputError(
                        "tracked repository checkout differs from HEAD"
                    )
                try:
                    target = os.readlink(os.fsencode(path))
                    after = path.lstat()
                except OSError as exc:
                    raise ProfileInputError(
                        "tracked repository checkout differs from HEAD"
                    ) from exc
                if self._stable_stat_identity(after) != self._stable_stat_identity(before):
                    raise ProfileInputError(
                        "tracked repository checkout changed during verification"
                    )
                actual_oid = self._blob_digest_for_bytes(target)
                size = len(target)
            else:
                if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                    raise ProfileInputError(
                        "tracked repository checkout differs from HEAD"
                    )
                executable = bool(stat.S_IMODE(before.st_mode) & 0o111)
                if executable != (mode == "100755"):
                    raise ProfileInputError(
                        "tracked repository checkout differs from HEAD"
                    )
                actual_oid, size = self._regular_blob_digest(path, before)
            total += size
            if total > _MAX_TRACKED_TOTAL_BYTES:
                raise ProfileInputError("tracked tree exceeds the verification limit")
            if actual_oid != oid:
                raise ProfileInputError(
                    "tracked repository checkout differs from HEAD"
                )

    def require_validator_blob(self, commit: str, expected_blob: str) -> None:
        actual_blob = _git_sha(
            self,
            f"{commit}:{_VALIDATOR_PATH}",
            "validator blob SHA",
        )
        if actual_blob != expected_blob:
            raise ProfileInputError("validator blob SHA differs from expected identity")

    def _reject_hidden_index_flags(self) -> None:
        raw = self.run(
            "ls-files",
            "-v",
            "-z",
            "--",
            max_stdout_bytes=_MAX_INDEX_LIST_BYTES,
            failure_message="cannot inspect tracked index flags",
        )
        for record in raw.split(b"\0"):
            if not record:
                continue
            if len(record) < 3 or record[1:2] != b" ":
                raise ProfileInputError("tracked index flag inventory is malformed")
            tag = record[0]
            if tag == ord("S") or ord("a") <= tag <= ord("z"):
                raise ProfileInputError(
                    "tracked index flags can hide checkout changes"
                )

    def read_reviewed_blob(self, commit: str, path: str) -> bytes:
        return self.run(
            "cat-file",
            "blob",
            f"{commit}:{path}",
            max_stdout_bytes=_MAX_REVIEWED_BLOB_BYTES,
            timeout_seconds=20,
            failure_message=f"cannot read reviewed profile data: {path}",
        )


def _git_sha(repository: _TrustedRepositoryView, revision: str, field: str) -> str:
    raw = repository.run("rev-parse", "--verify", revision)
    try:
        value = raw.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise ProfileInputError(f"{field} is not canonical Git text") from exc
    if not _GIT_SHA.fullmatch(value):
        raise ProfileInputError(f"{field} is not a canonical Git SHA")
    return value


def _parse_invocation(
    arguments: list[str],
) -> tuple[Path, Path, Path, int, str, str, str]:
    if len(arguments) != 14:
        raise ProfileInputError("exact outer launch arguments are required")
    values: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        name = arguments[index]
        value = arguments[index + 1]
        if name not in _INVOCATION_FLAGS or name in values:
            raise ProfileInputError("exact outer launch arguments are malformed")
        values[name] = value
    if frozenset(values) != _INVOCATION_FLAGS:
        raise ProfileInputError("exact outer launch arguments are required")

    for field in (
        "--expected-validator-blob-sha",
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
    ):
        if not _GIT_SHA.fullmatch(values[field]):
            raise ProfileInputError("expected code identity is not a canonical Git SHA")

    paths: list[Path] = []
    for field in ("--repository-root", "--git-dir", "--index-file"):
        path = Path(values[field])
        if not path.is_absolute() or str(path) != values[field]:
            raise ProfileInputError("outer launcher paths must be canonical absolute paths")
        paths.append(path)

    fd_text = values["--manifest-fd"]
    try:
        manifest_fd = int(fd_text, 10)
    except ValueError as exc:
        raise ProfileInputError("manifest descriptor is malformed") from exc
    if str(manifest_fd) != fd_text or not 3 <= manifest_fd <= 1024:
        raise ProfileInputError("manifest descriptor is malformed")

    return (
        paths[0],
        paths[1],
        paths[2],
        manifest_fd,
        values["--expected-validator-blob-sha"],
        values["--expected-code-commit-sha"],
        values["--expected-code-tree-sha"],
    )


def _read_manifest_descriptor(descriptor: int) -> bytes:
    try:
        duplicate = os.dup(descriptor)
    except OSError as exc:
        raise ProfileInputError("manifest descriptor is unavailable") from exc
    try:
        info = os.fstat(duplicate)
        if not stat.S_ISREG(info.st_mode):
            raise ProfileInputError("manifest descriptor must reference a regular file")
        if info.st_size > _MAX_INPUT_BYTES:
            raise ProfileInputError("input exceeds 1048576 bytes")
        with os.fdopen(duplicate, "rb", closefd=True) as stream:
            duplicate = -1
            raw = stream.read(_MAX_INPUT_BYTES + 1)
    finally:
        if duplicate >= 0:
            os.close(duplicate)
    if len(raw) > _MAX_INPUT_BYTES:
        raise ProfileInputError("input exceeds 1048576 bytes")
    return raw


def _load_reviewed_profile_data(
    repository: _TrustedRepositoryView,
    commit: str,
) -> dict[str, Any]:
    documents: dict[str, dict[str, Any]] = {}
    total = 0
    for path, expected_digest in _REVIEWED_BLOBS.items():
        raw = repository.read_reviewed_blob(commit, path)
        total += len(raw)
        if total > _MAX_REVIEWED_TOTAL_BYTES:
            raise ProfileInputError("reviewed profile data exceeds the total limit")
        if _digest_bytes(raw) != expected_digest:
            raise ProfileInputError(f"reviewed profile data digest differs: {path}")
        documents[path] = _parse_canonical_object(raw, path)

    contract = documents[_CONTRACT_PATH]
    try:
        payload = contract["payload"]
        components = contract["component_digests"]
        budgets = payload["budgets"]
        contract_version = payload["contract_version"]
        approved_profiles = payload["approved_profiles"]
        structural_digests = payload["profile_schema_digests"]
    except (KeyError, TypeError) as exc:
        raise ProfileInputError("reviewed contract shape differs") from exc
    if not isinstance(payload, dict) or not isinstance(components, dict):
        raise ProfileInputError("reviewed contract shape differs")
    if not isinstance(budgets, dict) or not isinstance(contract_version, str):
        raise ProfileInputError("reviewed contract shape differs")
    if approved_profiles != ["FIXTURE_REPLAY", "PRODUCTION_SHAPED_QUALIFICATION"]:
        raise ProfileInputError("reviewed profile inventory differs")
    if structural_digests != {
        "FIXTURE_REPLAY": _REVIEWED_BLOBS[_FIXTURE_STRUCTURAL_PATH],
        "PRODUCTION_SHAPED_QUALIFICATION": _REVIEWED_BLOBS[
            _QUALIFICATION_STRUCTURAL_PATH
        ],
    }:
        raise ProfileInputError("reviewed structural profile identities differ")
    for kind, digest in components.items():
        if not isinstance(kind, str):
            raise ProfileInputError("reviewed component inventory differs")
        _validate_digest(digest, f"component digest {kind}")

    for path in (_FIXTURE_BINDING_PATH, _QUALIFICATION_BINDING_PATH):
        schema = documents[path]
        try:
            properties = schema["properties"]
            contract_const = properties["contract_digest"]["const"]
            component_properties = properties["components"]["properties"]
        except (KeyError, TypeError) as exc:
            raise ProfileInputError("reviewed binding schema shape differs") from exc
        if contract_const != _REVIEWED_BLOBS[_CONTRACT_PATH]:
            raise ProfileInputError("reviewed binding contract identity differs")
        if set(component_properties) != set(components):
            raise ProfileInputError("reviewed binding component inventory differs")
        for kind, digest in components.items():
            if component_properties.get(kind) != {"const": digest}:
                raise ProfileInputError("reviewed binding component identity differs")

    return {
        "budgets_bytes": _canonical_json_bytes(budgets),
        "component_bytes": _canonical_json_bytes(components),
        "contract_digest": _REVIEWED_BLOBS[_CONTRACT_PATH],
        "contract_version": contract_version,
        "runtime_effects_bytes": _canonical_json_bytes(_SAFE_RUNTIME_EFFECTS),
    }


def _require_identifier(value: object, field: str) -> str:
    first = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    remaining = first + "0123456789_.:-"
    if not isinstance(value, str):
        raise ProfileInputError(f"{field} must be canonical text")
    if not 1 <= len(value) <= 128:
        raise ProfileInputError(f"{field} must contain 1 to 128 characters")
    if value[0] not in first:
        raise ProfileInputError(f"{field} must begin with an ASCII letter")
    if any(character not in remaining for character in value[1:]):
        raise ProfileInputError(f"{field} contains an unsupported character")
    return value


def _require_exact_keys(
    value: object,
    expected: frozenset[str],
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileInputError(f"{field} must be an object")
    if frozenset(value) != expected:
        raise ProfileInputError(f"{field} fields differ from the reviewed profile")
    return value


def _require_exact_object(value: object, expected: bytes, field: str) -> None:
    if not isinstance(value, dict):
        raise ProfileInputError(f"{field} must be an object")
    if _canonical_json_bytes(value) != expected:
        raise ProfileInputError(f"{field} differs from the reviewed profile")


def _validate_profile_manifest(
    manifest: dict[str, Any],
    reviewed: dict[str, Any],
) -> str:
    common = frozenset(
        {
            "schema_version",
            "profile_kind",
            "contract_digest",
            "contract_version",
            "components",
            "budgets",
            "runtime_effects",
            "vector_source",
            "qualification_eligible",
            "production_activation_authorized",
        }
    )
    profile_kind = manifest.get("profile_kind")
    if profile_kind == "FIXTURE_REPLAY":
        root_keys = common | frozenset({"fixture"})
        schema_version = "newsroom.increment5.fixture-replay-profile.v1"
        eligibility = False
    elif profile_kind == "PRODUCTION_SHAPED_QUALIFICATION":
        root_keys = common | frozenset(
            {
                "dataset",
                "actual_neo4j_required",
                "signed_dataset_manifest_required",
                "embedding_quality_qualified",
                "expected_outcome_scope",
            }
        )
        schema_version = (
            "newsroom.increment5.production-shaped-qualification-profile.v1"
        )
        eligibility = True
    else:
        raise ProfileInputError("profile kind is unsupported")

    _require_exact_keys(manifest, root_keys, "profile")
    if manifest.get("schema_version") != schema_version:
        raise ProfileInputError("profile schema version differs")
    if manifest.get("contract_digest") != reviewed["contract_digest"]:
        raise ProfileInputError("profile contract digest differs")
    if manifest.get("contract_version") != reviewed["contract_version"]:
        raise ProfileInputError("profile contract version differs")
    _require_exact_object(
        manifest.get("components"), reviewed["component_bytes"],
        "profile component identities",
    )
    _require_exact_object(
        manifest.get("budgets"), reviewed["budgets_bytes"], "profile budgets"
    )
    _require_exact_object(
        manifest.get("runtime_effects"), reviewed["runtime_effects_bytes"],
        "profile runtime effects",
    )
    if manifest.get("vector_source") != "DETERMINISTIC_FIXED_POINT_FIXTURE":
        raise ProfileInputError("profile vector source differs")
    if manifest.get("qualification_eligible") is not eligibility:
        raise ProfileInputError("profile qualification eligibility differs")
    if manifest.get("production_activation_authorized") is not False:
        raise ProfileInputError("Increment 5 profiles cannot activate production")

    if profile_kind == "FIXTURE_REPLAY":
        fixture = _require_exact_keys(
            manifest.get("fixture"),
            frozenset(
                {
                    "fixture_id",
                    "fixture_manifest_digest",
                    "production_substitution_allowed",
                }
            ),
            "fixture",
        )
        _require_identifier(fixture.get("fixture_id"), "fixture_id")
        _validate_digest(
            fixture.get("fixture_manifest_digest"), "fixture_manifest_digest"
        )
        if fixture.get("production_substitution_allowed") is not False:
            raise ProfileInputError(
                "fixture replay cannot substitute for production qualification"
            )
        return profile_kind

    dataset = _require_exact_keys(
        manifest.get("dataset"),
        frozenset(
            {
                "dataset_id",
                "dataset_manifest_digest",
                "rights_cleared",
                "repository_safe",
                "contains_protected_content",
            }
        ),
        "dataset",
    )
    _require_identifier(dataset.get("dataset_id"), "dataset_id")
    _validate_digest(dataset.get("dataset_manifest_digest"), "dataset_manifest_digest")
    if dataset.get("rights_cleared") is not True:
        raise ProfileInputError("qualification dataset must be rights cleared")
    if dataset.get("repository_safe") is not True:
        raise ProfileInputError("qualification dataset must be repository safe")
    if dataset.get("contains_protected_content") is not False:
        raise ProfileInputError("qualification dataset cannot contain protected content")
    if manifest.get("actual_neo4j_required") is not True:
        raise ProfileInputError("qualification requires an actual Neo4j service")
    if manifest.get("signed_dataset_manifest_required") is not True:
        raise ProfileInputError("qualification requires a signed dataset manifest")
    if manifest.get("embedding_quality_qualified") is not False:
        raise ProfileInputError(
            "fixed-point fixture vectors cannot qualify embedding quality"
        )
    if manifest.get("expected_outcome_scope") != (
        "RETRIEVER_INDEX_FUSION_DEDUPLICATION_HYDRATION_DEGRADATION_AND_RECOVERY_ONLY"
    ):
        raise ProfileInputError("qualification outcome scope differs")
    return profile_kind


def _emit_receipt(
    runtime: _TrustedPythonRuntime,
    repository: _TrustedRepositoryView,
    commit: str,
    tree: str,
    validator_blob: str,
    receipt: dict[str, Any],
    output: BinaryIO,
) -> None:
    raw = _canonical_json_bytes(receipt) + b"\n"
    runtime.require_unchanged()
    repository.require_stable_clean_tree(commit, tree)
    repository.require_validator_blob(commit, validator_blob)
    output.write(raw)
    output.flush()


def main() -> int:
    try:
        (
            repository_root,
            git_dir,
            index_path,
            manifest_fd,
            expected_validator_blob,
            expected_commit,
            expected_tree,
        ) = _parse_invocation(sys.argv[1:])
        runtime = _TrustedPythonRuntime()
        repository = _TrustedRepositoryView(repository_root, git_dir, index_path)
        repository.require_stable_clean_tree(expected_commit, expected_tree)
        repository.require_validator_blob(expected_commit, expected_validator_blob)

        raw = _read_manifest_descriptor(manifest_fd)
        manifest = _parse_input_manifest(raw)
        reviewed = _load_reviewed_profile_data(repository, expected_commit)
        profile_kind = _validate_profile_manifest(manifest, reviewed)
        receipt = {
            "authority_effect": "NONE",
            "code_commit_sha": expected_commit,
            "code_tree_sha": expected_tree,
            "executed_source_identity_attested": False,
            "external_python_packages_used": False,
            "manifest_digest": _digest_bytes(raw),
            "outer_signed_workflow_binding_required": True,
            "production_activation_authorized": False,
            "profile_kind": profile_kind,
            "python_runtime_executable": "/usr/bin/python3",
            "python_runtime_origin": "ROOT_OWNED_SYSTEM_PYTHON_NO_SITE",
            "qualification_authority_granted": False,
            "schema_version": "newsroom.increment5.profile-validation-receipt.v7",
            "site_initialization_used": False,
            "checkout_snapshot_verified_before_receipt_write": True,
            "completion_time_checkout_state_attested": False,
            "validation_code_delivery": "EXACT_COMMIT_GIT_BLOB_STDIN",
            "validation_code_identity_claim_effect": "NONE",
            "validation_code_origin": "OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED",
            "validation_data_origin": "EXACT_REVIEWED_GIT_BLOBS",
            "validation_scope": (
                "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_PREWRITE_CODE_TREE_SNAPSHOT"
            ),
            "validator_blob_sha": expected_validator_blob,
            "worktree_imports_used": False,
        }
        _emit_receipt(
            runtime,
            repository,
            expected_commit,
            expected_tree,
            expected_validator_blob,
            receipt,
            sys.stdout.buffer,
        )
        return 0
    except ProfileInputError as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
if __name__ == "__main__":
    raise SystemExit(main())
