from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp

from .contracts import Increment5ContractError
from .decision_validation import object_without_duplicate_names
from .main_qualification import (
    MAIN_QUALIFICATION_RECORD_PATH,
    MAIN_QUALIFICATION_REF,
    MAIN_QUALIFICATION_REPOSITORY,
    MAIN_QUALIFICATION_REPOSITORY_ID,
    MAIN_QUALIFICATION_WORKFLOW_PATHS,
    Increment5AMainQualificationRecord,
    WorkflowAttemptEvidence,
)


_API_PREFIX = (
    "https://api.github.com/repos/"
    + MAIN_QUALIFICATION_REPOSITORY
)
_AUTHENTICATION_SCHEMA_VERSION = (
    "newsroom.increment5.github-main-admission-authentication.v1"
)
_MAX_AUTHENTICATION_OUTPUT_BYTES = 64 * 1024
_AUTHENTICATION_TIMEOUT_SECONDS = 90.0


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment5ContractError(f"{field} must be an object")
    return value


def _canonical_github_time(value: object, *, field: str) -> UtcTimestamp:
    if not isinstance(value, str) or not value:
        raise Increment5ContractError(f"{field} must be timestamp text")
    try:
        return UtcTimestamp.parse(value)
    except (TypeError, ValueError) as exc:
        raise Increment5ContractError(
            f"{field} is not valid UTC text"
        ) from exc


def _workflow_path(value: object, *, expected: str) -> str:
    if not isinstance(value, str) or not value:
        raise Increment5ContractError(
            "authenticated workflow path is absent"
        )
    path, separator, ref = value.partition("@")
    if path != expected or (separator and ref != MAIN_QUALIFICATION_REF):
        raise Increment5ContractError(
            "authenticated workflow path differs"
        )
    return path


def validate_github_workflow_attempt_payload(
    *,
    attempt: WorkflowAttemptEvidence,
    payload: Mapping[str, Any],
) -> None:
    if not isinstance(attempt, WorkflowAttemptEvidence):
        raise Increment5ContractError(
            "GitHub verification requires typed workflow evidence"
        )
    value = _mapping(payload, field="github.workflow_attempt")
    repository = _mapping(
        value.get("repository"),
        field="github.workflow_attempt.repository",
    )
    head_repository = _mapping(
        value.get("head_repository"),
        field="github.workflow_attempt.head_repository",
    )
    expected_path = MAIN_QUALIFICATION_WORKFLOW_PATHS[attempt.key]
    expected_workflow_ref = (
        f"{MAIN_QUALIFICATION_REPOSITORY}/{expected_path}"
        f"@{MAIN_QUALIFICATION_REF}"
    )
    expected_run_url = f"{_API_PREFIX}/actions/runs/{attempt.run_id}"
    expected_attempt_url = (
        expected_run_url + f"/attempts/{attempt.run_attempt}"
    )
    expected = {
        "id": attempt.run_id,
        "workflow_id": attempt.workflow_id,
        "name": attempt.workflow_name,
        "run_number": attempt.run_number,
        "run_attempt": attempt.run_attempt,
        "event": attempt.event,
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": attempt.head_sha,
        "head_repository_id": MAIN_QUALIFICATION_REPOSITORY_ID,
        "url": expected_run_url,
        "html_url": attempt.html_url,
    }
    actual = {key: value.get(key) for key in expected}
    if actual != expected:
        raise Increment5ContractError(
            "authenticated workflow attempt metadata differs"
        )
    if attempt.api_url != expected_attempt_url:
        raise Increment5ContractError(
            "workflow attempt API URL differs from authenticated endpoint"
        )
    if (
        repository.get("id") != MAIN_QUALIFICATION_REPOSITORY_ID
        or repository.get("full_name")
        != MAIN_QUALIFICATION_REPOSITORY
        or head_repository.get("id")
        != MAIN_QUALIFICATION_REPOSITORY_ID
        or head_repository.get("full_name")
        != MAIN_QUALIFICATION_REPOSITORY
    ):
        raise Increment5ContractError(
            "authenticated workflow repository identity differs"
        )
    _workflow_path(value.get("path"), expected=expected_path)
    if attempt.workflow_ref != expected_workflow_ref:
        raise Increment5ContractError(
            "workflow attempt ref differs from permanent workflow"
        )
    for field_name in (
        "created_at",
        "run_started_at",
        "updated_at",
    ):
        authenticated = _canonical_github_time(
            value.get(field_name),
            field=f"github.workflow_attempt.{field_name}",
        )
        if authenticated != getattr(attempt, field_name):
            raise Increment5ContractError(
                "authenticated workflow attempt timestamp differs"
            )


def validate_github_commit_payload(
    *,
    record: Increment5AMainQualificationRecord,
    payload: Mapping[str, Any],
) -> None:
    if not isinstance(record, Increment5AMainQualificationRecord):
        raise Increment5ContractError(
            "GitHub verification requires typed main admission"
        )
    value = _mapping(payload, field="github.commit")
    tree = _mapping(value.get("tree"), field="github.commit.tree")
    expected_url = (
        f"{_API_PREFIX}/git/commits/"
        f"{record.qualified_main_commit_sha}"
    )
    if (
        value.get("sha") != record.qualified_main_commit_sha
        or value.get("url") != expected_url
        or tree.get("sha") != record.qualified_main_tree_sha
    ):
        raise Increment5ContractError(
            "authenticated GitHub commit/tree identity differs"
        )


def _require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise Increment5ContractError(f"{field} must be a digest")
    try:
        return validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise Increment5ContractError(
            f"{field} is not canonical"
        ) from exc


def _require_positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Increment5ContractError(
            f"{field} must be a positive integer"
        )
    return value


def _validate_authentication_certificate(
    *,
    record: Increment5AMainQualificationRecord,
    value: object,
    verifier_source_digest: str,
) -> None:
    certificate = _mapping(
        value,
        field="github.authentication_certificate",
    )
    expected_keys = {
        "schema_version",
        "authentication_identity",
        "record_digest",
        "qualified_main_commit_sha",
        "qualified_main_tree_sha",
        "workflow_attempts",
        "sdlc_artifact",
        "decision_document_digest",
        "decision_file_digest",
        "context_file_digest",
        "collection_file_digest",
        "verifier_source_digest",
    }
    if set(certificate) != expected_keys:
        raise Increment5ContractError(
            "GitHub authentication certificate shape differs"
        )
    if certificate.get("schema_version") != _AUTHENTICATION_SCHEMA_VERSION:
        raise Increment5ContractError(
            "GitHub authentication certificate version differs"
        )
    if (
        certificate.get("record_digest") != record.record_digest
        or certificate.get("qualified_main_commit_sha")
        != record.qualified_main_commit_sha
        or certificate.get("qualified_main_tree_sha")
        != record.qualified_main_tree_sha
        or certificate.get("decision_document_digest")
        != record.decision_document_digest
        or certificate.get("verifier_source_digest")
        != verifier_source_digest
    ):
        raise Increment5ContractError(
            "GitHub authentication certificate identity differs"
        )

    attempts = certificate.get("workflow_attempts")
    if not isinstance(attempts, list):
        raise Increment5ContractError(
            "GitHub authentication attempt certificate differs"
        )
    expected_attempts = [
        {
            "key": attempt.key,
            "run_id": attempt.run_id,
            "run_attempt": attempt.run_attempt,
        }
        for attempt in record.workflow_attempts
    ]
    if attempts != expected_attempts:
        raise Increment5ContractError(
            "GitHub authentication attempt certificate differs"
        )

    artifact = _mapping(
        certificate.get("sdlc_artifact"),
        field="github.authentication_certificate.sdlc_artifact",
    )
    expected_artifact_keys = {
        "artifact_id",
        "name",
        "archive_digest",
        "transport_identity",
    }
    if set(artifact) != expected_artifact_keys:
        raise Increment5ContractError(
            "GitHub authentication artifact certificate differs"
        )
    sdlc_attempt = record.workflow_attempt_by_name[
        "SDLC_EVIDENCE_SHADOW"
    ]
    expected_name = (
        "newsroom-sdlc-decision-"
        f"{sdlc_attempt.run_id}-{sdlc_attempt.run_attempt}-"
        f"{record.qualified_main_commit_sha}"
    )
    if (
        artifact.get("name") != expected_name
        or _require_positive_integer(
            artifact.get("artifact_id"),
            field="sdlc_artifact.artifact_id",
        )
        <= 0
    ):
        raise Increment5ContractError(
            "GitHub authentication artifact certificate differs"
        )
    for field_name in (
        "archive_digest",
        "transport_identity",
    ):
        _require_digest(
            artifact.get(field_name),
            field=f"sdlc_artifact.{field_name}",
        )
    for field_name in (
        "decision_file_digest",
        "context_file_digest",
        "collection_file_digest",
    ):
        _require_digest(
            certificate.get(field_name),
            field=field_name,
        )

    identity = _require_digest(
        certificate.get("authentication_identity"),
        field="authentication_identity",
    )
    identity_inputs = dict(certificate)
    del identity_inputs["authentication_identity"]
    if identity != digest_bytes(canonical_json_bytes(identity_inputs)):
        raise Increment5ContractError(
            "GitHub authentication certificate digest differs"
        )


def _isolated_authenticator_factory(
    *,
    verifier_path: Path,
    record_path: Path,
    executable: str = sys.executable,
    run_process: Callable[..., subprocess.CompletedProcess[bytes]] = (
        subprocess.run
    ),
    read_bytes: Callable[[Path], bytes] = Path.read_bytes,
) -> Callable[
    [Increment5AMainQualificationRecord],
    Increment5AMainQualificationRecord,
]:
    if verifier_path.is_symlink():
        raise Increment5ContractError(
            "isolated GitHub admission verifier is missing"
        )
    captured_verifier_path = verifier_path.resolve()
    captured_record_path = record_path.resolve()
    captured_executable = str(Path(executable).resolve())
    captured_run_process = run_process
    captured_read_bytes = read_bytes
    if not captured_verifier_path.is_file():
        raise Increment5ContractError(
            "isolated GitHub admission verifier is missing"
        )
    verifier_source_digest = digest_bytes(
        captured_read_bytes(captured_verifier_path)
    )
    repository_root = Path(__file__).resolve().parents[2]
    authenticated_record_digest: str | None = None

    def authenticate(
        record: Increment5AMainQualificationRecord,
    ) -> Increment5AMainQualificationRecord:
        nonlocal authenticated_record_digest
        if not isinstance(record, Increment5AMainQualificationRecord):
            raise Increment5ContractError(
                "repository admission requires typed main qualification"
            )
        if authenticated_record_digest == record.record_digest:
            return record
        token = os.environ.get("GITHUB_TOKEN")
        if (
            not isinstance(token, str)
            or not token
            or any(character.isspace() for character in token)
        ):
            raise Increment5ContractError(
                "authenticated GitHub workflow evidence is unavailable"
            )
        try:
            current_digest = digest_bytes(
                captured_read_bytes(captured_verifier_path)
            )
        except OSError as exc:
            raise Increment5ContractError(
                "isolated GitHub admission verifier is unavailable"
            ) from exc
        if current_digest != verifier_source_digest:
            raise Increment5ContractError(
                "isolated GitHub admission verifier source differs"
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
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=_AUTHENTICATION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Increment5ContractError(
                "authenticated GitHub workflow evidence is unavailable"
            ) from exc
        if completed.returncode != 0:
            raise Increment5ContractError(
                "authenticated GitHub workflow evidence is unavailable"
            )
        payload = completed.stdout
        if (
            not isinstance(payload, bytes)
            or not 0 < len(payload) <= _MAX_AUTHENTICATION_OUTPUT_BYTES
        ):
            raise Increment5ContractError(
                "GitHub authentication certificate is unavailable"
            )
        try:
            certificate = json.loads(
                payload.decode("utf-8", errors="strict"),
                object_pairs_hook=object_without_duplicate_names,
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise Increment5ContractError(
                "GitHub authentication certificate is invalid"
            ) from exc
        if payload != canonical_json_bytes(certificate) + b"\n":
            raise Increment5ContractError(
                "GitHub authentication certificate is not canonical"
            )
        _validate_authentication_certificate(
            record=record,
            value=certificate,
            verifier_source_digest=verifier_source_digest,
        )
        authenticated_record_digest = record.record_digest
        return record

    return authenticate


_VERIFIER_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "sdlc"
    / "increment5_github_admission.py"
)
_AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION = (
    _isolated_authenticator_factory(
        verifier_path=_VERIFIER_PATH,
        record_path=MAIN_QUALIFICATION_RECORD_PATH,
    )
)
del _isolated_authenticator_factory


def authenticate_repository_main_qualification_record(
    record: Increment5AMainQualificationRecord,
) -> Increment5AMainQualificationRecord:
    """Authenticate source-pinned main admission in an isolated process."""

    return _AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION(record)
