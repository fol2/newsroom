#!/usr/bin/env python3
"""Validate one canonical Increment 5 profile from exact Git blobs only.

This program is not run from the checkout. A signed exact-head workflow streams
this file's exact Git blob to ``python -I -S -`` and supplies a separate bounded
manifest file. The validator reads the reviewed contract and profile schemas as
exact blobs from the same commit and uses only the Python standard library.

The emitted receipt has authority effect ``NONE``. It grants no qualification,
production, component, source, model, provider, spend, write, or public effect.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Any


_MAX_INPUT_BYTES = 1_048_576
_MAX_BLOB_BYTES = 4_194_304
_MAX_EXECUTABLE_BYTES = 268_435_456
_MAX_GIT_TEXT_BYTES = 65_536
_READ_CHUNK_BYTES = 65_536
_PROCESS_TIMEOUT_SECONDS = 30.0
_PROCESS_STOP_TIMEOUT_SECONDS = 2.0
_MIN_SAFE_INTEGER = -9_007_199_254_740_991
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_TRUSTED_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))
_TRUSTED_SYSTEM_PATH = "/usr/bin:/bin"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_VALIDATOR_PATH = "scripts/sdlc/increment5_profile_validator.py"
_CONTRACT_PATH = "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"
_FIXTURE_STRUCTURAL_PATH = (
    "newsroom/increment5/data/"
    "increment5_fixture_replay_profile_structural_v1.schema.json"
)
_FIXTURE_PUBLIC_PATH = (
    "newsroom/increment5/data/increment5_fixture_replay_profile_v1.schema.json"
)
_QUALIFICATION_STRUCTURAL_PATH = (
    "newsroom/increment5/data/"
    "increment5_qualification_profile_structural_v1.schema.json"
)
_QUALIFICATION_PUBLIC_PATH = (
    "newsroom/increment5/data/increment5_qualification_profile_v1.schema.json"
)
_CONTRACT_DIGEST = (
    "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
)
_FIXTURE_STRUCTURAL_DIGEST = (
    "sha256:7c2e50d952109d834d944c120b8f9a5adcc59c6f39106430fa8728c5ad25c9a0"
)
_QUALIFICATION_STRUCTURAL_DIGEST = (
    "sha256:7b055832c33f9d9bf25f3401fce936bba3a2310da8f272038de4f0625356685b"
)
_FIXTURE_PUBLIC_DIGEST = (
    "sha256:6783030456d1d4ba5744a70932ee2982c099a3cf324ad98e2d05413216d7d571"
)
_QUALIFICATION_PUBLIC_DIGEST = (
    "sha256:5d48af523da006bec804893f0bd42b411a466ca29103a8dde8fc46db49ced354"
)
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
_COMMON_ROOT_KEYS = frozenset(
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
_FIXTURE_ROOT_KEYS = _COMMON_ROOT_KEYS | frozenset({"fixture"})
_QUALIFICATION_ROOT_KEYS = _COMMON_ROOT_KEYS | frozenset(
    {
        "dataset",
        "actual_neo4j_required",
        "signed_dataset_manifest_required",
        "embedding_quality_qualified",
        "expected_outcome_scope",
    }
)
_FIXTURE_KEYS = frozenset(
    {
        "fixture_id",
        "fixture_manifest_digest",
        "production_substitution_allowed",
    }
)
_DATASET_KEYS = frozenset(
    {
        "dataset_id",
        "dataset_manifest_digest",
        "rights_cleared",
        "repository_safe",
        "contains_protected_content",
    }
)
_EXPECTED_ARGUMENTS = frozenset(
    {
        "--repository-root",
        "--manifest-path",
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
        "--expected-validator-blob-digest",
    }
)


class ProfileInputError(ValueError):
    """The exact-blob validator input is malformed or outside its boundary."""


def _fail(message: str) -> int:
    sys.stderr.write(f"increment5 profile validation failed: {message}\n")
    return 2


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _validate_string(value: str, path: str) -> None:
    for character in value:
        if 0xD800 <= ord(character) <= 0xDFFF:
            raise ProfileInputError(f"lone surrogate is unsupported at {path}")


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
        _validate_string(value, path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProfileInputError(f"object names must be strings at {path}")
            _validate_string(key, f"{path}.<key>")
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


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ProfileInputError(f"duplicate JSON object name: {name}")
        result[name] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ProfileInputError(f"unsupported JSON constant: {value}")


def _load_canonical_object(
    raw: bytes,
    *,
    label: str,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileInputError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProfileInputError(f"{label} must be an object")
    if raw != _canonical_json_bytes(value):
        raise ProfileInputError(f"{label} is not canonical JSON")
    if expected_digest is not None and _digest_bytes(raw) != expected_digest:
        raise ProfileInputError(f"{label} digest differs from reviewed identity")
    return value


def _canonical_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise ProfileInputError(f"{field} must be 40 lowercase hexadecimal characters")
    return value


def _canonical_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_DIGEST.fullmatch(value) is None:
        raise ProfileInputError(f"{field} must be a canonical sha256 digest")
    return value


def _canonical_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ProfileInputError(f"{field} must be a canonical identifier")
    return value


def _parse_arguments(argv: list[str]) -> dict[str, str]:
    if len(argv) != 10:
        raise ProfileInputError(
            "exact validator arguments are required: repository root, manifest "
            "path, commit SHA, tree SHA, and validator blob digest"
        )
    values: dict[str, str] = {}
    for index in range(0, len(argv), 2):
        flag = argv[index]
        if flag not in _EXPECTED_ARGUMENTS:
            raise ProfileInputError(f"unsupported argument: {flag}")
        if flag in values:
            raise ProfileInputError(f"duplicate argument: {flag}")
        values[flag] = argv[index + 1]
    if frozenset(values) != _EXPECTED_ARGUMENTS:
        raise ProfileInputError("exact validator arguments are incomplete")
    _canonical_sha(values["--expected-code-commit-sha"], "expected code commit SHA")
    _canonical_sha(values["--expected-code-tree-sha"], "expected code tree SHA")
    _canonical_digest(
        values["--expected-validator-blob-digest"],
        "expected validator blob digest",
    )
    return values


def _root_owned_non_writable(path: Path) -> bool:
    try:
        for candidate in (path, *path.parents):
            metadata = candidate.stat()
            if metadata.st_uid != 0:
                return False
            if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return False
    except OSError:
        return False
    return True


def _digest_regular_file(path: Path) -> str:
    try:
        metadata = path.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_EXECUTABLE_BYTES
        ):
            raise ProfileInputError("trusted executable has an invalid size")
        remaining = metadata.st_size
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while remaining:
                chunk = source.read(min(1_048_576, remaining))
                if not chunk:
                    raise ProfileInputError("trusted executable is truncated")
                digest.update(chunk)
                remaining -= len(chunk)
            if source.read(1):
                raise ProfileInputError("trusted executable changed while reading")
    except OSError as exc:
        raise ProfileInputError("cannot digest trusted executable") from exc
    return "sha256:" + digest.hexdigest()


def _trusted_python() -> tuple[Path, str, Path]:
    try:
        executable = Path(sys.executable).resolve(strict=True)
        runtime_root = Path(sys.base_prefix).resolve(strict=True)
    except OSError as exc:
        raise ProfileInputError("cannot resolve the Python runtime") from exc
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ProfileInputError("Python executable is not a regular executable")
    if not _root_owned_non_writable(executable):
        raise ProfileInputError("Python executable is outside the trusted runtime policy")
    if not runtime_root.is_dir() or not _root_owned_non_writable(runtime_root):
        raise ProfileInputError("Python runtime root is outside the trusted policy")
    return executable, _digest_regular_file(executable), runtime_root


def _trusted_git(repository_root: Path) -> tuple[Path, str]:
    seen: set[Path] = set()
    for candidate in _TRUSTED_GIT_CANDIDATES:
        try:
            executable = candidate.resolve(strict=True)
        except OSError:
            continue
        if executable in seen:
            continue
        seen.add(executable)
        try:
            executable.relative_to(repository_root)
        except ValueError:
            pass
        else:
            continue
        if not executable.is_file() or not os.access(executable, os.X_OK):
            continue
        if not _root_owned_non_writable(executable):
            continue
        return executable, _digest_regular_file(executable)
    raise ProfileInputError(
        "no root-owned non-writable system Git executable is available"
    )


def _git_environment() -> dict[str, str]:
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


def _git_command(
    git: Path,
    repository_root: Path,
    *arguments: str,
) -> list[str]:
    git_directory = repository_root / ".git"
    if not git_directory.is_dir():
        raise ProfileInputError("repository Git directory is unavailable")
    return [
        str(git),
        f"--git-dir={git_directory}",
        "--no-replace-objects",
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


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise ProfileInputError("cannot stop Git object reader") from exc


def _read_git_output(
    git: Path,
    repository_root: Path,
    arguments: tuple[str, ...],
    *,
    maximum_bytes: int,
    label: str,
) -> bytes:
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    try:
        process = subprocess.Popen(
            _git_command(git, repository_root, *arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            env=_git_environment(),
        )
        if process.stdout is None:
            raise ProfileInputError(f"{label} output is unavailable")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        output = bytearray()
        while selector.get_map():
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise ProfileInputError(f"{label} timed out")
            events = selector.select(timeout=remaining_time)
            if not events:
                raise ProfileInputError(f"{label} timed out")
            for key, _ in events:
                chunk = os.read(key.fd, _READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if len(output) + len(chunk) > maximum_bytes:
                    raise ProfileInputError(f"{label} exceeds the byte limit")
                output.extend(chunk)
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            raise ProfileInputError(f"{label} timed out")
        if process.wait(timeout=remaining_time) != 0:
            raise ProfileInputError(f"{label} failed")
        return bytes(output)
    except ProfileInputError:
        if process is not None:
            _stop_process_group(process)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            _stop_process_group(process)
        raise ProfileInputError(f"{label} failed") from exc
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            _stop_process_group(process)
            if process.stdout is not None:
                process.stdout.close()


def _git_text(
    git: Path,
    repository_root: Path,
    *arguments: str,
    label: str,
) -> str:
    raw = _read_git_output(
        git,
        repository_root,
        tuple(arguments),
        maximum_bytes=_MAX_GIT_TEXT_BYTES,
        label=label,
    )
    try:
        return raw.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise ProfileInputError(f"{label} is not canonical Git text") from exc


def _read_git_blob(
    git: Path,
    repository_root: Path,
    commit: str,
    path: str,
    *,
    label: str,
) -> bytes:
    return _read_git_output(
        git,
        repository_root,
        ("cat-file", "blob", f"{commit}:{path}"),
        maximum_bytes=_MAX_BLOB_BYTES,
        label=label,
    )


def _read_manifest(path_text: str) -> bytes:
    path = Path(path_text)
    if not path.is_absolute():
        raise ProfileInputError("manifest path must be absolute")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ProfileInputError("manifest must be a regular file")
            if metadata.st_size < 1 or metadata.st_size > _MAX_INPUT_BYTES:
                raise ProfileInputError("manifest exceeds the byte limit")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
                if not chunk:
                    raise ProfileInputError("manifest is truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise ProfileInputError("manifest changed while reading")
        finally:
            os.close(descriptor)
    except ProfileInputError:
        raise
    except OSError as exc:
        raise ProfileInputError("cannot read manifest file") from exc
    return b"".join(chunks)


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


def _require_exact_object(value: object, expected: object, field: str) -> None:
    if not isinstance(value, dict) or value != expected:
        raise ProfileInputError(f"{field} differs from the reviewed profile")


def _verify_public_binding(
    structural: dict[str, Any],
    public: dict[str, Any],
    *,
    binding_id: str,
    contract_digest: str,
    component_digests: dict[str, Any],
) -> None:
    expected = deepcopy(structural)
    try:
        expected["$id"] = binding_id
        expected["title"] = f"{structural['title']} — reviewed identity binding"
        properties = expected["properties"]
        properties["contract_digest"] = {"const": contract_digest}
        component_properties = properties["components"]["properties"]
        if set(component_properties) != set(component_digests):
            raise ProfileInputError("structural component inventory differs")
        for kind, identity_digest in component_digests.items():
            component_properties[kind] = {"const": identity_digest}
    except (KeyError, TypeError) as exc:
        raise ProfileInputError("structural profile schema shape differs") from exc
    if public != expected:
        raise ProfileInputError("public profile schema binding differs")


def _validate_profile(
    manifest: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[str, str, str]:
    try:
        payload = contract["payload"]
        component_digests = contract["component_digests"]
        contract_version = payload["contract_version"]
        budgets = payload["budgets"]
        approved_profiles = payload["approved_profiles"]
    except (KeyError, TypeError) as exc:
        raise ProfileInputError("reviewed contract profile semantics are malformed") from exc
    if not isinstance(payload, dict):
        raise ProfileInputError("reviewed contract payload is malformed")
    if not isinstance(component_digests, dict):
        raise ProfileInputError("reviewed component identities are malformed")
    if not isinstance(contract_version, str):
        raise ProfileInputError("reviewed contract version is malformed")
    if not isinstance(budgets, dict):
        raise ProfileInputError("reviewed profile budgets are malformed")
    if not isinstance(approved_profiles, list):
        raise ProfileInputError("reviewed profile inventory is malformed")

    profile_kind = manifest.get("profile_kind")
    if profile_kind not in approved_profiles:
        raise ProfileInputError("profile kind is not admitted by Increment 5A")
    if profile_kind == "FIXTURE_REPLAY":
        root_keys = _FIXTURE_ROOT_KEYS
        schema_version = "newsroom.increment5.fixture-replay-profile.v1"
        eligibility = False
        structural_digest = _FIXTURE_STRUCTURAL_DIGEST
        public_digest = _FIXTURE_PUBLIC_DIGEST
    elif profile_kind == "PRODUCTION_SHAPED_QUALIFICATION":
        root_keys = _QUALIFICATION_ROOT_KEYS
        schema_version = (
            "newsroom.increment5.production-shaped-qualification-profile.v1"
        )
        eligibility = True
        structural_digest = _QUALIFICATION_STRUCTURAL_DIGEST
        public_digest = _QUALIFICATION_PUBLIC_DIGEST
    else:
        raise ProfileInputError("profile kind is unsupported")

    _require_exact_keys(manifest, root_keys, "profile")
    if manifest.get("schema_version") != schema_version:
        raise ProfileInputError("profile schema version differs")
    if manifest.get("contract_digest") != _CONTRACT_DIGEST:
        raise ProfileInputError("profile contract digest differs")
    if manifest.get("contract_version") != contract_version:
        raise ProfileInputError("profile contract version differs")
    _require_exact_object(
        manifest.get("components"),
        component_digests,
        "profile component identities",
    )
    _require_exact_object(manifest.get("budgets"), budgets, "profile budgets")
    _require_exact_object(
        manifest.get("runtime_effects"),
        _SAFE_RUNTIME_EFFECTS,
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
            _FIXTURE_KEYS,
            "fixture",
        )
        _canonical_identifier(fixture.get("fixture_id"), "fixture_id")
        _canonical_digest(
            fixture.get("fixture_manifest_digest"),
            "fixture_manifest_digest",
        )
        if fixture.get("production_substitution_allowed") is not False:
            raise ProfileInputError(
                "fixture replay cannot substitute for production qualification"
            )
    else:
        dataset = _require_exact_keys(
            manifest.get("dataset"),
            _DATASET_KEYS,
            "dataset",
        )
        _canonical_identifier(dataset.get("dataset_id"), "dataset_id")
        _canonical_digest(
            dataset.get("dataset_manifest_digest"),
            "dataset_manifest_digest",
        )
        if dataset.get("rights_cleared") is not True:
            raise ProfileInputError("qualification dataset must be rights cleared")
        if dataset.get("repository_safe") is not True:
            raise ProfileInputError("qualification dataset must be repository safe")
        if dataset.get("contains_protected_content") is not False:
            raise ProfileInputError(
                "qualification dataset cannot contain protected content"
            )
        if manifest.get("actual_neo4j_required") is not True:
            raise ProfileInputError("qualification requires an actual Neo4j service")
        if manifest.get("signed_dataset_manifest_required") is not True:
            raise ProfileInputError(
                "qualification requires a signed dataset manifest"
            )
        if manifest.get("embedding_quality_qualified") is not False:
            raise ProfileInputError(
                "fixed-point fixture vectors cannot qualify embedding quality"
            )
        if manifest.get("expected_outcome_scope") != (
            "RETRIEVER_INDEX_FUSION_DEDUPLICATION_HYDRATION_"
            "DEGRADATION_AND_RECOVERY_ONLY"
        ):
            raise ProfileInputError("qualification outcome scope differs")

    return profile_kind, structural_digest, public_digest


def _require_exact_blob_launch() -> None:
    if sys.argv[0] != "-":
        raise ProfileInputError(
            "validator must execute from an exact Git blob through python -I -S -"
        )
    if (
        sys.flags.isolated != 1
        or sys.flags.no_site != 1
        or sys.flags.ignore_environment != 1
        or getattr(sys.flags, "safe_path", 0) != 1
    ):
        raise ProfileInputError(
            "validator requires isolated no-site Python with safe-path semantics"
        )
    if any(
        "site-packages" in entry or "dist-packages" in entry
        for entry in sys.path
    ):
        raise ProfileInputError("third-party import paths are forbidden")
    if "site" in sys.modules or "jsonschema" in sys.modules:
        raise ProfileInputError("third-party or site initialization is forbidden")


def main() -> int:
    try:
        _require_exact_blob_launch()
        arguments = _parse_arguments(sys.argv[1:])
        repository_root_text = arguments["--repository-root"]
        repository_root_input = Path(repository_root_text)
        if not repository_root_input.is_absolute():
            raise ProfileInputError("repository root must be absolute")
        repository_root = repository_root_input.resolve(strict=True)
        if not repository_root.is_dir():
            raise ProfileInputError("repository root must be a directory")

        expected_commit = arguments["--expected-code-commit-sha"]
        expected_tree = arguments["--expected-code-tree-sha"]
        expected_validator_digest = arguments[
            "--expected-validator-blob-digest"
        ]
        manifest_raw = _read_manifest(arguments["--manifest-path"])

        python, python_digest, python_root = _trusted_python()
        git, git_digest = _trusted_git(repository_root)
        actual_commit = _git_text(
            git,
            repository_root,
            "rev-parse",
            "--verify",
            f"{expected_commit}^{{commit}}",
            label="code commit resolution",
        )
        actual_tree = _git_text(
            git,
            repository_root,
            "rev-parse",
            "--verify",
            f"{expected_commit}^{{tree}}",
            label="code tree resolution",
        )
        if actual_commit != expected_commit:
            raise ProfileInputError("code commit SHA differs from expected identity")
        if actual_tree != expected_tree:
            raise ProfileInputError("code tree SHA differs from expected identity")

        validator_blob = _read_git_blob(
            git,
            repository_root,
            actual_commit,
            _VALIDATOR_PATH,
            label="validator source blob",
        )
        validator_digest = _digest_bytes(validator_blob)
        if validator_digest != expected_validator_digest:
            raise ProfileInputError("validator blob digest differs from expected identity")

        contract_raw = _read_git_blob(
            git,
            repository_root,
            actual_commit,
            _CONTRACT_PATH,
            label="reviewed contract blob",
        )
        fixture_structural_raw = _read_git_blob(
            git,
            repository_root,
            actual_commit,
            _FIXTURE_STRUCTURAL_PATH,
            label="fixture structural schema blob",
        )
        fixture_public_raw = _read_git_blob(
            git,
            repository_root,
            actual_commit,
            _FIXTURE_PUBLIC_PATH,
            label="fixture public schema blob",
        )
        qualification_structural_raw = _read_git_blob(
            git,
            repository_root,
            actual_commit,
            _QUALIFICATION_STRUCTURAL_PATH,
            label="qualification structural schema blob",
        )
        qualification_public_raw = _read_git_blob(
            git,
            repository_root,
            actual_commit,
            _QUALIFICATION_PUBLIC_PATH,
            label="qualification public schema blob",
        )

        contract = _load_canonical_object(
            contract_raw,
            label="reviewed contract",
            expected_digest=_CONTRACT_DIGEST,
        )
        fixture_structural = _load_canonical_object(
            fixture_structural_raw,
            label="fixture structural schema",
            expected_digest=_FIXTURE_STRUCTURAL_DIGEST,
        )
        fixture_public = _load_canonical_object(
            fixture_public_raw,
            label="fixture public schema",
            expected_digest=_FIXTURE_PUBLIC_DIGEST,
        )
        qualification_structural = _load_canonical_object(
            qualification_structural_raw,
            label="qualification structural schema",
            expected_digest=_QUALIFICATION_STRUCTURAL_DIGEST,
        )
        qualification_public = _load_canonical_object(
            qualification_public_raw,
            label="qualification public schema",
            expected_digest=_QUALIFICATION_PUBLIC_DIGEST,
        )
        component_digests = contract.get("component_digests")
        if not isinstance(component_digests, dict):
            raise ProfileInputError("reviewed component identities are malformed")
        _verify_public_binding(
            fixture_structural,
            fixture_public,
            binding_id=(
                "urn:newsroom:increment5:fixture-replay-profile:"
                "reviewed-binding:v1"
            ),
            contract_digest=_CONTRACT_DIGEST,
            component_digests=component_digests,
        )
        _verify_public_binding(
            qualification_structural,
            qualification_public,
            binding_id=(
                "urn:newsroom:increment5:production-shaped-qualification-"
                "profile:reviewed-binding:v1"
            ),
            contract_digest=_CONTRACT_DIGEST,
            component_digests=component_digests,
        )

        manifest = _load_canonical_object(manifest_raw, label="profile manifest")
        profile_kind, structural_digest, public_digest = _validate_profile(
            manifest,
            contract,
        )
        receipt = {
            "authority_effect": "NONE",
            "executed_source_identity_attested": False,
            "git_executable_digest_observed": git_digest,
            "git_executable_path_observed": str(git),
            "git_runtime_trust_attested": False,
            "inner_receipt_only": True,
            "manifest_digest": _digest_bytes(manifest_raw),
            "outer_runtime_binding_required": True,
            "outer_signed_workflow_binding_required": True,
            "profile_kind": profile_kind,
            "profile_public_schema_digest": public_digest,
            "profile_structural_schema_digest": structural_digest,
            "production_activation_authorized": False,
            "python_executable_digest_observed": python_digest,
            "python_executable_path_observed": str(python),
            "python_runtime_root_observed": str(python_root),
            "qualification_authority_granted": False,
            "reviewed_code_commit_sha": actual_commit,
            "reviewed_code_tree_sha": actual_tree,
            "reviewed_contract_digest": _CONTRACT_DIGEST,
            "reviewed_validator_blob_digest": validator_digest,
            "runtime_closure_identity_attested": False,
            "runtime_identity_claim_effect": "NONE",
            "schema_version": "newsroom.increment5.profile-validation-inner-receipt.v6",
            "self_reported_isolated_no_site": True,
            "self_reported_repository_object_access": "EXACT_COMMIT_BLOBS_ONLY",
            "self_reported_third_party_import_paths_absent": True,
            "self_reported_validator_launch_mode": (
                "PYTHON_ISOLATED_NO_SITE_STDIN"
            ),
            "self_reported_worktree_or_index_used": False,
            "source_identity_claim_effect": "NONE",
            "validation_evidence_admissible": False,
            "validation_scope": "INNER_PROFILE_STRUCTURE_AND_SEMANTICS_ONLY",
        }
        sys.stdout.buffer.write(_canonical_json_bytes(receipt) + b"\n")
        return 0
    except ProfileInputError as exc:
        return _fail(str(exc))
    except Exception as exc:  # pragma: no cover - fail closed at the process edge
        return _fail(f"exact-blob validation failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
