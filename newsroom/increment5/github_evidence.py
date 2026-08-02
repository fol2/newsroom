from __future__ import annotations

from typing import Any, Mapping

from newsroom.authority.types import UtcTimestamp

from .contracts import Increment5ContractError
from .main_qualification import (
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
