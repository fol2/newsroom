#!/usr/bin/env python3
"""Validate one canonical Increment 5 profile from an exact Git tree.

The receipt proves only that exact manifest bytes passed the reviewed profile
structure and semantic checks loaded from a cache-free materialization of the
stated Git commit/tree. It grants no qualification, production, component,
source, model, provider, spend, write, or public-effect authority.
"""

from __future__ import annotations

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
import sys
import tarfile
import tempfile
import time
from typing import Any, Iterator


_MAX_INPUT_BYTES = 1_048_576
_MAX_GIT_OUTPUT_BYTES = 65_536
_MAX_ARCHIVE_BYTES = 67_108_864
_MAX_ARCHIVE_MEMBER_BYTES = 16_777_216
_MAX_GIT_EXECUTABLE_BYTES = 268_435_456
_ARCHIVE_READ_CHUNK_BYTES = 65_536
_ARCHIVE_TIMEOUT_SECONDS = 30.0
_PROCESS_STOP_TIMEOUT_SECONDS = 2.0
_TRUSTED_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))
_TRUSTED_SYSTEM_PATH = "/usr/bin:/bin"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
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


def _root_owned_non_writable(path: Path) -> bool:
    try:
        candidates = (path, *path.parents)
        for candidate in candidates:
            metadata = candidate.stat()
            if metadata.st_uid != 0:
                return False
            if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return False
    except OSError:
        return False
    return True


def _digest_trusted_file(path: Path) -> str:
    try:
        metadata = path.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_GIT_EXECUTABLE_BYTES
        ):
            raise ProfileInputError("trusted Git executable has an invalid size")
        digest = hashlib.sha256()
        remaining = metadata.st_size
        with path.open("rb") as source:
            while remaining:
                chunk = source.read(min(1_048_576, remaining))
                if not chunk:
                    raise ProfileInputError("trusted Git executable is truncated")
                digest.update(chunk)
                remaining -= len(chunk)
            if source.read(1):
                raise ProfileInputError("trusted Git executable changed while reading")
    except OSError as exc:
        raise ProfileInputError("cannot digest the trusted Git executable") from exc
    return "sha256:" + digest.hexdigest()


def _git_executable() -> tuple[Path, str]:
    if os.name != "posix":
        raise ProfileInputError("exact code-tree validation requires POSIX")
    seen: set[Path] = set()
    for candidate in _TRUSTED_GIT_CANDIDATES:
        try:
            path = candidate.resolve(strict=True)
        except OSError:
            continue
        if path in seen:
            continue
        seen.add(path)
        try:
            path.relative_to(_REPOSITORY_ROOT)
        except ValueError:
            pass
        else:
            continue
        try:
            metadata = path.stat()
        except OSError:
            continue
        if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
            continue
        if not _root_owned_non_writable(path):
            continue
        return path, _digest_trusted_file(path)
    raise ProfileInputError(
        "no root-owned non-writable system Git executable is available"
    )


def _git_environment(git: Path) -> dict[str, str]:
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": _TRUSTED_SYSTEM_PATH,
    }


def _git_command(git: Path, *arguments: str) -> list[str]:
    git_directory = _REPOSITORY_ROOT / ".git"
    if not git_directory.is_dir():
        raise ProfileInputError("repository Git directory is unavailable")
    return [
        str(git),
        f"--git-dir={git_directory}",
        f"--work-tree={_REPOSITORY_ROOT}",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "protocol.file.allow=never",
        *arguments,
    ]


def _run_git(git: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            _git_command(git, *arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            close_fds=True,
            timeout=10,
            env=_git_environment(git),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfileInputError("cannot inspect the exact Git code tree") from exc
    if (
        completed.returncode != 0
        or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES
        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES
    ):
        raise ProfileInputError("cannot inspect the exact Git code tree")
    return completed.stdout


def _git_sha(git: Path, revision: str, field: str) -> str:
    raw = _run_git(git, "rev-parse", "--verify", revision)
    try:
        value = raw.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise ProfileInputError(f"{field} is not canonical Git text") from exc
    return _canonical_git_sha(value, field)


def _require_exact_code_tree(
    expected_commit: str,
    expected_tree: str,
) -> tuple[Path, str, str, str]:
    """Bind HEAD and reject tracked changes before repository imports exist."""

    git, git_digest = _git_executable()
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
    return git, git_digest, actual_commit, actual_tree


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise ProfileInputError("cannot stop Git archive generation") from exc


def _write_git_archive(git: Path, commit: str, archive_path: Path) -> None:
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    try:
        with archive_path.open("xb") as output:
            process = subprocess.Popen(
                _git_command(
                    git,
                    "archive",
                    "--format=tar",
                    commit,
                    "--",
                    "newsroom",
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                env=_git_environment(git),
            )
            if process.stdout is None:
                raise ProfileInputError("Git archive stdout is unavailable")
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + _ARCHIVE_TIMEOUT_SECONDS
            total = 0
            while selector.get_map():
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    raise ProfileInputError("Git archive generation timed out")
                events = selector.select(timeout=remaining_time)
                if not events:
                    raise ProfileInputError("Git archive generation timed out")
                for key, _ in events:
                    chunk = os.read(key.fd, _ARCHIVE_READ_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if total + len(chunk) > _MAX_ARCHIVE_BYTES:
                        raise ProfileInputError(
                            "Git archive exceeds the streaming generation limit"
                        )
                    output.write(chunk)
                    total += len(chunk)
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise ProfileInputError("Git archive generation timed out")
            return_code = process.wait(timeout=remaining_time)
            if return_code != 0 or total == 0:
                raise ProfileInputError("Git archive generation failed")
            output.flush()
            os.fsync(output.fileno())
    except ProfileInputError:
        if process is not None:
            _stop_process(process)
        archive_path.unlink(missing_ok=True)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            _stop_process(process)
        archive_path.unlink(missing_ok=True)
        raise ProfileInputError("cannot materialize the exact Git code tree") from exc
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            _stop_process(process)
            if process.stdout is not None:
                process.stdout.close()


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
    git: Path,
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
        git, git_digest, actual_commit, actual_tree = _require_exact_code_tree(
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
                "archive_stream_limit_bytes": _MAX_ARCHIVE_BYTES,
                "archive_streaming_enforced": True,
                "authority_effect": "NONE",
                "code_commit_sha": actual_commit,
                "code_tree_sha": actual_tree,
                "git_executable_digest": git_digest,
                "git_executable_path": str(git),
                "git_producer_policy": "ROOT_OWNED_NON_WRITABLE_SYSTEM_PATH",
                "manifest_digest": digest_bytes(raw),
                "production_activation_authorized": False,
                "profile_kind": profile_kind,
                "qualification_authority_granted": False,
                "schema_version": "newsroom.increment5.profile-validation-receipt.v4",
                "tracked_checkout_clean": True,
                "validation_code_origin": "CACHE_FREE_EXACT_GIT_ARCHIVE",
                "validation_scope": (
                    "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
                ),
                "worktree_imports_used": False,
            }
            sys.stdout.buffer.write(canonical_json_bytes(receipt) + b"\n")
            return 0
    except ProfileInputError as exc:
        return _fail(str(exc))
    except Exception as exc:  # pragma: no cover - fail-closed import boundary
        return _fail(f"cannot load reviewed profile validator: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
