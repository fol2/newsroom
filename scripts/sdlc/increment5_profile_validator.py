#!/usr/bin/env python3
"""Validate one canonical Increment 5 profile without external Python packages.

The executable is an evidence boundary. It uses only the Python standard
library, binds one explicit Git directory/index/work tree, reads exact reviewed
contract and schema blobs from the supplied commit, and emits a non-authoritative
receipt only after the repository state is revalidated at completion.
"""

from __future__ import annotations

import sys

if not sys.flags.isolated:
    sys.stderr.write(
        "increment5 profile validation failed: isolated Python mode is required\n"
    )
    raise SystemExit(2)

import hashlib
import json
import os
from pathlib import Path
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
_MAX_REVIEWED_BLOB_BYTES = 16_777_216
_MAX_REVIEWED_TOTAL_BYTES = 67_108_864
_STREAM_CHUNK_BYTES = 65_536
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")
_TRUSTED_GIT_PARENTS = (Path("/usr"), Path("/usr/bin"))
_EXPECTED_FLAGS = frozenset(
    {
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
    }
)
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

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        self.git = _TrustedGitBinary()
        self.git_dir = self._discover_git_dir()
        self.index_path = self.git_dir / "index"
        self._require_repository_path(self.git_dir, directory=True)
        self._require_repository_path(self.index_path, directory=False)
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

    def _discover_git_dir(self) -> Path:
        self.git.require_unchanged()
        try:
            raw = _capture_bounded_process(
                [
                    str(self.git.path),
                    "-C",
                    str(self.root),
                    "--no-replace-objects",
                    "-c",
                    "core.fsmonitor=false",
                    "rev-parse",
                    "--absolute-git-dir",
                ],
                env=_base_git_environment(),
                timeout_seconds=10,
                max_stdout_bytes=_MAX_GIT_OUTPUT_BYTES,
                max_stderr_bytes=_MAX_GIT_OUTPUT_BYTES,
                failure_message="cannot bind the exact Git repository",
            )
        finally:
            self.git.require_unchanged()
        try:
            text = raw.decode("utf-8", errors="strict").strip()
        except UnicodeError as exc:
            raise ProfileInputError("cannot bind the exact Git repository") from exc
        if not text or "\n" in text or "\r" in text:
            raise ProfileInputError("cannot bind the exact Git repository")
        path = Path(text)
        if not path.is_absolute():
            raise ProfileInputError("Git directory is not absolute")
        return path.resolve(strict=True)

    def command(self, *arguments: str) -> list[str]:
        self.git.require_unchanged()
        return [
            str(self.git.path),
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.root}",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
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

    def require_stable_clean_tree(self, commit: str, tree: str) -> None:
        actual_commit = _git_sha(self, "HEAD^{commit}", "code commit SHA")
        actual_tree = _git_sha(self, "HEAD^{tree}", "code tree SHA")
        if actual_commit != commit:
            raise ProfileInputError("code commit SHA differs from expected identity")
        if actual_tree != tree:
            raise ProfileInputError("code tree SHA differs from expected identity")
        self._reject_hidden_index_flags()
        status = self.run(
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
            "--ignore-submodules=none",
        )
        if status:
            raise ProfileInputError("tracked repository checkout differs from HEAD")

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


def _parse_expected_identities(arguments: list[str]) -> tuple[str, str]:
    if len(arguments) != 4:
        raise ProfileInputError("exact code identity arguments are required")
    values: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        name = arguments[index]
        value = arguments[index + 1]
        if name not in _EXPECTED_FLAGS or name in values:
            raise ProfileInputError("exact code identity arguments are malformed")
        if not _GIT_SHA.fullmatch(value):
            raise ProfileInputError("expected code identity is not a canonical Git SHA")
        values[name] = value
    if frozenset(values) != _EXPECTED_FLAGS:
        raise ProfileInputError("exact code identity arguments are required")
    return (
        values["--expected-code-commit-sha"],
        values["--expected-code-tree-sha"],
    )


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
    repository: _TrustedRepositoryView,
    commit: str,
    tree: str,
    receipt: dict[str, Any],
    output: BinaryIO,
) -> None:
    raw = _canonical_json_bytes(receipt) + b"\n"
    repository.require_stable_clean_tree(commit, tree)
    output.write(raw)


def main() -> int:
    try:
        expected_commit, expected_tree = _parse_expected_identities(sys.argv[1:])
        repository = _TrustedRepositoryView(_REPOSITORY_ROOT)
        repository.require_stable_clean_tree(expected_commit, expected_tree)

        raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        if len(raw) > _MAX_INPUT_BYTES:
            raise ProfileInputError("input exceeds 1048576 bytes")
        manifest = _parse_input_manifest(raw)

        reviewed = _load_reviewed_profile_data(repository, expected_commit)
        profile_kind = _validate_profile_manifest(manifest, reviewed)
        receipt = {
            "authority_effect": "NONE",
            "code_commit_sha": expected_commit,
            "code_tree_sha": expected_tree,
            "external_python_packages_used": False,
            "manifest_digest": _digest_bytes(raw),
            "production_activation_authorized": False,
            "profile_kind": profile_kind,
            "qualification_authority_granted": False,
            "schema_version": "newsroom.increment5.profile-validation-receipt.v4",
            "tracked_checkout_clean": True,
            "validation_code_origin": "EXACT_TRACKED_EXECUTABLE_STDLIB_ONLY",
            "validation_data_origin": "EXACT_REVIEWED_GIT_BLOBS",
            "validation_scope": (
                "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
            ),
            "worktree_imports_used": False,
        }
        _emit_receipt(
            repository,
            expected_commit,
            expected_tree,
            receipt,
            sys.stdout.buffer,
        )
        return 0
    except ProfileInputError as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
