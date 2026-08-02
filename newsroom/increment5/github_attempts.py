from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

from . import _github_attempts_v1 as _reviewed_v1
from .contracts import Increment5ContractError
from .decision_validation import object_without_duplicate_names
from .main_qualification import (
    MAIN_QUALIFICATION_RECORD_PATH,
    Increment5AMainQualificationRecord,
)


validate_github_workflow_attempt_payload = (
    _reviewed_v1.validate_github_workflow_attempt_payload
)
validate_github_commit_payload = _reviewed_v1.validate_github_commit_payload
_validate_authentication_certificate = (
    _reviewed_v1._validate_authentication_certificate
)

_AUTHENTICATION_TIMEOUT_SECONDS = 90.0
_MAX_AUTHENTICATION_OUTPUT_BYTES = 64 * 1024
_SOURCE_MANIFEST_SCHEMA = (
    "newsroom.increment5.admission-source-manifest.v1"
)
_REVIEWED_SOURCE_MANIFEST_DIGEST = (
    "sha256:3d52cdab7a57f855d571e5b26c0c3dcd1eb704f9dfa75de6dd35ff00e7036c87"
)
_GIT_BLOB_PATTERN = re.compile(r"[0-9a-f]{40}")
_MAX_SOURCE_MANIFEST_BYTES = 64 * 1024
_MAX_REVIEWED_SOURCE_FILES = 64


def _git_blob_sha(
    data: bytes,
    *,
    sha1: Callable[[bytes], Any] = hashlib.sha1,
) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return sha1(header + data).hexdigest()  # noqa: S324 - Git object identity


def _safe_reviewed_source_path(
    *,
    repository_root: Path,
    relative: object,
    pure_path_type: type[PurePosixPath] = PurePosixPath,
    error_type: type[Exception] = Increment5ContractError,
) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise error_type("reviewed admission source path is invalid")
    lexical = pure_path_type(relative)
    if lexical.is_absolute() or any(
        part in {"", ".", ".."} for part in lexical.parts
    ):
        raise error_type("reviewed admission source path escapes repository")
    current = repository_root
    for part in lexical.parts:
        current /= part
        if current.is_symlink():
            raise error_type("reviewed admission source path is symlinked")
    resolved = current.resolve()
    if not resolved.is_relative_to(repository_root) or not resolved.is_file():
        raise error_type("reviewed admission source file is unavailable")
    return resolved


def _verify_reviewed_source_bundle(
    *,
    manifest_path: Path,
    expected_manifest_digest: str,
    implementation_path: Path,
    repository_root: Path,
    read_bytes: Callable[[Path], bytes] = Path.read_bytes,
    loads: Callable[..., Any] = json.loads,
    duplicate_name_hook: Callable[[list[tuple[str, Any]]], dict[str, Any]] = (
        object_without_duplicate_names
    ),
    canonical_bytes: Callable[[object], bytes] = canonical_json_bytes,
    digest: Callable[[bytes], str] = digest_bytes,
    git_blob_sha: Callable[[bytes], str] = _git_blob_sha,
    safe_source_path: Callable[..., Path] = _safe_reviewed_source_path,
    error_type: type[Exception] = Increment5ContractError,
    git_blob_pattern: re.Pattern[str] = _GIT_BLOB_PATTERN,
    manifest_schema: str = _SOURCE_MANIFEST_SCHEMA,
    maximum_manifest_bytes: int = _MAX_SOURCE_MANIFEST_BYTES,
    maximum_source_files: int = _MAX_REVIEWED_SOURCE_FILES,
    validate_digest: Callable[..., str] = validate_sha256_digest,
    json_error_type: type[Exception] = json.JSONDecodeError,
    mapping_type: type = Mapping,
) -> tuple[str, str]:
    root = repository_root.resolve()
    expected_path = root / "scripts/sdlc/increment5_admission_source_v1.json"
    if manifest_path.resolve() != expected_path:
        raise error_type("reviewed admission source manifest path differs")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise error_type("reviewed admission source manifest is unavailable")
    try:
        data = read_bytes(manifest_path)
    except OSError as exc:
        raise error_type("reviewed admission source manifest is unreadable") from exc
    if not 0 < len(data) <= maximum_manifest_bytes:
        raise error_type("reviewed admission source manifest size differs")
    try:
        validate_digest(
            expected_manifest_digest,
            field="reviewed_source_manifest_digest",
        )
    except ValueError as exc:
        raise error_type(
            "reviewed admission source manifest digest is invalid"
        ) from exc
    if digest(data) != expected_manifest_digest:
        raise error_type("reviewed admission source manifest digest differs")
    try:
        value = loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=duplicate_name_hook,
        )
    except (UnicodeError, json_error_type, ValueError) as exc:
        raise error_type("reviewed admission source manifest is invalid") from exc
    if data != canonical_bytes(value):
        raise error_type("reviewed admission source manifest is not canonical")
    if not isinstance(value, mapping_type):
        raise error_type("reviewed admission source manifest must be an object")
    manifest = value
    if set(manifest) != {"schema_version", "source_bundle_identity", "files"}:
        raise error_type("reviewed admission source manifest shape differs")
    if manifest.get("schema_version") != manifest_schema:
        raise error_type("reviewed admission source manifest version differs")
    files_value = manifest.get("files")
    if not isinstance(files_value, mapping_type):
        raise error_type("reviewed admission source files must be an object")
    if not 0 < len(files_value) <= maximum_source_files:
        raise error_type("reviewed admission source inventory differs")
    files: dict[str, str] = {}
    for relative, expected_blob in files_value.items():
        if (
            not isinstance(relative, str)
            or not isinstance(expected_blob, str)
            or git_blob_pattern.fullmatch(expected_blob) is None
        ):
            raise error_type("reviewed admission source identity is invalid")
        files[relative] = expected_blob
    required_paths = {
        "newsroom/increment5/_github_attempts_v1.py",
        "scripts/sdlc/increment5_github_admission.py",
        "scripts/sdlc/_increment5_github_admission_impl.py",
        "scripts/sdlc/collection_binding.py",
    }
    if not required_paths.issubset(files):
        raise error_type("reviewed admission verifier source is absent")
    identity = digest(
        canonical_bytes(
            {
                "schema_version": manifest_schema,
                "files": files,
            }
        )
    )
    if manifest.get("source_bundle_identity") != identity:
        raise error_type("reviewed admission source bundle identity differs")
    for relative, expected_blob in files.items():
        source = safe_source_path(
            repository_root=root,
            relative=relative,
        )
        try:
            source_data = read_bytes(source)
        except OSError as exc:
            raise error_type("reviewed admission source is unreadable") from exc
        if git_blob_sha(source_data) != expected_blob:
            raise error_type(f"reviewed admission source differs: {relative}")
    expected_implementation = (
        root / "scripts/sdlc/_increment5_github_admission_impl.py"
    )
    if implementation_path.resolve() != expected_implementation:
        raise error_type("reviewed admission implementation path differs")
    try:
        implementation_digest = digest(read_bytes(implementation_path))
    except OSError as exc:
        raise error_type("reviewed admission implementation is unreadable") from exc
    return identity, implementation_digest


def _isolated_authenticator_factory(
    *,
    verifier_path: Path,
    verifier_implementation_path: Path,
    source_manifest_path: Path,
    expected_source_manifest_digest: str,
    record_path: Path,
    executable: str = sys.executable,
    run_process: Callable[..., subprocess.CompletedProcess[bytes]] = (
        subprocess.run
    ),
    validate_certificate: Callable[..., None] = (
        _validate_authentication_certificate
    ),
    canonical_bytes: Callable[[object], bytes] = canonical_json_bytes,
    loads: Callable[..., Any] = json.loads,
    duplicate_name_hook: Callable[[list[tuple[str, Any]]], dict[str, Any]] = (
        object_without_duplicate_names
    ),
    token_getter: Callable[[str], str | None] = os.environ.get,
    record_type: type = Increment5AMainQualificationRecord,
    contract_error_type: type[Exception] = Increment5ContractError,
    json_error_type: type[Exception] = json.JSONDecodeError,
    timeout_error_type: type[Exception] = subprocess.TimeoutExpired,
    process_devnull: int = subprocess.DEVNULL,
    process_pipe: int = subprocess.PIPE,
    timeout_seconds: float = _AUTHENTICATION_TIMEOUT_SECONDS,
    maximum_output_bytes: int = _MAX_AUTHENTICATION_OUTPUT_BYTES,
    verify_source_bundle: Callable[..., tuple[str, str]] = (
        _verify_reviewed_source_bundle
    ),
) -> Callable[
    [Increment5AMainQualificationRecord],
    Increment5AMainQualificationRecord,
]:
    if verifier_path.is_symlink() or not verifier_path.is_file():
        raise Increment5ContractError(
            "isolated GitHub admission verifier is missing"
        )
    captured_verifier_path = verifier_path.resolve()
    captured_implementation_path = verifier_implementation_path.resolve()
    captured_source_manifest_path = source_manifest_path.resolve()
    captured_source_manifest_digest = expected_source_manifest_digest
    captured_record_path = record_path.resolve()
    captured_executable = str(Path(executable).resolve())
    captured_run_process = run_process
    captured_validate_certificate = validate_certificate
    captured_canonical_bytes = canonical_bytes
    captured_loads = loads
    captured_duplicate_name_hook = duplicate_name_hook
    captured_token_getter = token_getter
    captured_record_type = record_type
    captured_contract_error_type = contract_error_type
    captured_json_error_type = json_error_type
    captured_timeout_error_type = timeout_error_type
    captured_process_devnull = process_devnull
    captured_process_pipe = process_pipe
    captured_timeout_seconds = timeout_seconds
    captured_maximum_output_bytes = maximum_output_bytes
    captured_verify_source_bundle = verify_source_bundle
    repository_root = Path(__file__).resolve().parents[2]
    source_bundle_identity, verifier_source_digest = (
        captured_verify_source_bundle(
            manifest_path=captured_source_manifest_path,
            expected_manifest_digest=captured_source_manifest_digest,
            implementation_path=captured_implementation_path,
            repository_root=repository_root,
        )
    )
    authenticated_record_digest: str | None = None

    def authenticate(
        record: Increment5AMainQualificationRecord,
    ) -> Increment5AMainQualificationRecord:
        nonlocal authenticated_record_digest
        if type(record) is not captured_record_type:
            raise captured_contract_error_type(
                "repository admission requires typed main qualification"
            )
        if authenticated_record_digest == record.record_digest:
            return record
        token = captured_token_getter("GITHUB_TOKEN")
        if (
            not isinstance(token, str)
            or not token
            or any(character.isspace() for character in token)
        ):
            raise captured_contract_error_type(
                "authenticated GitHub workflow evidence is unavailable"
            )
        current_source_identity, current_verifier_digest = (
            captured_verify_source_bundle(
                manifest_path=captured_source_manifest_path,
                expected_manifest_digest=captured_source_manifest_digest,
                implementation_path=captured_implementation_path,
                repository_root=repository_root,
            )
        )
        if (
            current_source_identity != source_bundle_identity
            or current_verifier_digest != verifier_source_digest
        ):
            raise captured_contract_error_type(
                "reviewed GitHub admission source differs"
            )
        environment = {
            "GITHUB_TOKEN": token,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        command = (
            captured_executable,
            "-I",
            captured_verifier_path.as_posix(),
            "--source-manifest-path",
            captured_source_manifest_path.as_posix(),
            "--expected-source-manifest-digest",
            captured_source_manifest_digest,
            "--record-path",
            captured_record_path.as_posix(),
            "--expected-record-digest",
            record.record_digest,
            "--approval-record-digest",
            record.approval_record_digest,
        )
        try:
            completed = captured_run_process(
                command,
                cwd=repository_root,
                env=environment,
                stdin=captured_process_devnull,
                stdout=captured_process_pipe,
                stderr=captured_process_pipe,
                check=False,
                timeout=captured_timeout_seconds,
            )
        except (OSError, captured_timeout_error_type) as exc:
            raise captured_contract_error_type(
                "authenticated GitHub workflow evidence is unavailable"
            ) from exc
        if completed.returncode != 0:
            raise captured_contract_error_type(
                "authenticated GitHub workflow evidence is unavailable"
            )
        payload = completed.stdout
        if (
            not isinstance(payload, bytes)
            or not 0 < len(payload) <= captured_maximum_output_bytes
        ):
            raise captured_contract_error_type(
                "GitHub authentication certificate is unavailable"
            )
        try:
            certificate = captured_loads(
                payload.decode("utf-8", errors="strict"),
                object_pairs_hook=captured_duplicate_name_hook,
            )
        except (UnicodeError, captured_json_error_type) as exc:
            raise captured_contract_error_type(
                "GitHub authentication certificate is invalid"
            ) from exc
        if payload != captured_canonical_bytes(certificate) + b"\n":
            raise captured_contract_error_type(
                "GitHub authentication certificate is not canonical"
            )
        captured_validate_certificate(
            record=record,
            value=certificate,
            verifier_source_digest=verifier_source_digest,
        )
        authenticated_record_digest = record.record_digest
        return record

    authenticate.__name__ = "authenticate_repository_main_qualification_record"
    authenticate.__qualname__ = (
        "authenticate_repository_main_qualification_record"
    )
    authenticate.__doc__ = (
        "Authenticate source-pinned main admission in an isolated process."
    )
    return authenticate


_VERIFIER_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "sdlc"
    / "increment5_github_admission.py"
)
_VERIFIER_IMPLEMENTATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "sdlc"
    / "_increment5_github_admission_impl.py"
)
_SOURCE_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "sdlc"
    / "increment5_admission_source_v1.json"
)
authenticate_repository_main_qualification_record = (
    _isolated_authenticator_factory(
        verifier_path=_VERIFIER_PATH,
        verifier_implementation_path=_VERIFIER_IMPLEMENTATION_PATH,
        source_manifest_path=_SOURCE_MANIFEST_PATH,
        expected_source_manifest_digest=(
            _REVIEWED_SOURCE_MANIFEST_DIGEST
        ),
        record_path=MAIN_QUALIFICATION_RECORD_PATH,
    )
)
del _isolated_authenticator_factory
