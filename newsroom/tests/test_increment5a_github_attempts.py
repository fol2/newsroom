from __future__ import annotations

from copy import deepcopy
import inspect

import pytest

import newsroom.increment5.approval as approval_module
from newsroom.authority.types import UtcTimestamp
from newsroom.increment5 import Increment5ContractError
from newsroom.increment5.github_attempts import (
    authenticate_repository_main_qualification_record,
    validate_github_commit_payload,
    validate_github_workflow_attempt_payload,
)
from newsroom.increment5.main_qualification import (
    MAIN_QUALIFICATION_REPOSITORY,
    MAIN_QUALIFICATION_REPOSITORY_ID,
    MAIN_QUALIFICATION_WORKFLOW_PATHS,
    Increment5AMainQualificationRecord,
    WorkflowAttemptEvidence,
)


_COMMIT = "1" * 40
_TREE = "2" * 40
_CREATED = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
_STARTED = UtcTimestamp.parse("2042-03-12T12:00:01.000000Z")
_UPDATED = UtcTimestamp.parse("2042-03-12T12:20:00.000000Z")


def _attempt() -> WorkflowAttemptEvidence:
    return WorkflowAttemptEvidence(
        key="CI",
        workflow_id=232327316,
        workflow_name="CI",
        event="push",
        run_id=1001,
        run_attempt=2,
        run_number=2001,
        head_sha=_COMMIT,
        head_tree_sha=_TREE,
        workflow_sha=_COMMIT,
        workflow_ref=(
            f"{MAIN_QUALIFICATION_REPOSITORY}/"
            f"{MAIN_QUALIFICATION_WORKFLOW_PATHS['CI']}"
            "@refs/heads/main"
        ),
        api_url=(
            "https://api.github.com/repos/fol2/newsroom/"
            "actions/runs/1001/attempts/2"
        ),
        html_url=(
            "https://github.com/fol2/newsroom/actions/runs/1001"
        ),
        created_at=_CREATED,
        run_started_at=_STARTED,
        updated_at=_UPDATED,
    )


def _payload() -> dict[str, object]:
    return {
        "id": 1001,
        "workflow_id": 232327316,
        "name": "CI",
        "run_number": 2001,
        "run_attempt": 2,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": _COMMIT,
        "head_repository_id": MAIN_QUALIFICATION_REPOSITORY_ID,
        "path": MAIN_QUALIFICATION_WORKFLOW_PATHS["CI"],
        "url": (
            "https://api.github.com/repos/fol2/newsroom/"
            "actions/runs/1001"
        ),
        "html_url": (
            "https://github.com/fol2/newsroom/actions/runs/1001"
        ),
        "created_at": "2042-03-12T12:00:00Z",
        "run_started_at": "2042-03-12T12:00:01Z",
        "updated_at": "2042-03-12T12:20:00Z",
        "repository": {
            "id": MAIN_QUALIFICATION_REPOSITORY_ID,
            "full_name": MAIN_QUALIFICATION_REPOSITORY,
        },
        "head_repository": {
            "id": MAIN_QUALIFICATION_REPOSITORY_ID,
            "full_name": MAIN_QUALIFICATION_REPOSITORY,
        },
    }


def _record() -> Increment5AMainQualificationRecord:
    attempt = _attempt()
    return Increment5AMainQualificationRecord(
        qualified_main_commit_sha=_COMMIT,
        qualified_main_tree_sha=_TREE,
        qualified_at=_UPDATED,
        approval_record_digest="sha256:" + "a" * 64,
        proposal_payload_digest="sha256:" + "b" * 64,
        proposal_record_digest="sha256:" + "c" * 64,
        proposal_contract_bundle_digest="sha256:" + "d" * 64,
        qualification_profile_schema_digest="sha256:" + "e" * 64,
        main_qualification_record_schema_digest=(
            __import__(
                "newsroom.increment5.main_qualification",
                fromlist=["MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST"],
            ).MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST
        ),
        workflow_attempts=(
            attempt,
            *(
                WorkflowAttemptEvidence(
                    key=key,
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    event=(
                        "workflow_dispatch"
                        if key == "SDLC_EVIDENCE_SHADOW"
                        else "push"
                    ),
                    run_id=1001 + index,
                    run_attempt=1,
                    run_number=2001 + index,
                    head_sha=_COMMIT,
                    head_tree_sha=_TREE,
                    workflow_sha=_COMMIT,
                    workflow_ref=(
                        f"{MAIN_QUALIFICATION_REPOSITORY}/"
                        f"{MAIN_QUALIFICATION_WORKFLOW_PATHS[key]}"
                        "@refs/heads/main"
                    ),
                    api_url=(
                        "https://api.github.com/repos/fol2/newsroom/"
                        f"actions/runs/{1001 + index}/attempts/1"
                    ),
                    html_url=(
                        "https://github.com/fol2/newsroom/actions/runs/"
                        f"{1001 + index}"
                    ),
                    created_at=_CREATED,
                    run_started_at=_STARTED,
                    updated_at=_UPDATED,
                )
                for index, (key, workflow_id, workflow_name) in enumerate(
                    (
                        ("AUTHORITY_A2A", 315268483, "Authority A2a"),
                        ("AUTHORITY_A2B", 315287552, "Authority A2b"),
                        ("PROJECTION_B1", 317445524, "Projection B1"),
                        (
                            "PROJECTION_B2_B3_C1_NEO4J",
                            317681630,
                            "Projection B2/B3/C1 Neo4j",
                        ),
                        (
                            "SDLC_EVIDENCE_SHADOW",
                            318982302,
                            "SDLC Evidence Shadow",
                        ),
                    ),
                    start=1,
                )
            ),
        ),
        decision_document_digest="sha256:" + "f" * 64,
        decision_identity="sha256:" + "1" * 64,
        test_count=1,
        skip_count=0,
        record_digest="sha256:" + "2" * 64,
    )


def test_exact_authenticated_workflow_attempt_is_accepted() -> None:
    validate_github_workflow_attempt_payload(
        attempt=_attempt(),
        payload=_payload(),
    )


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("id",), 9999),
        (("workflow_id",), 1),
        (("event",), "workflow_dispatch"),
        (("conclusion",), "failure"),
        (("head_sha",), "3" * 40),
        (("head_repository_id",), 1),
        (("path",), ".github/workflows/other.yml"),
        (("repository", "id"), 1),
        (("repository", "full_name"), "other/repo"),
        (("head_repository", "id"), 1),
        (("head_repository", "full_name"), "other/repo"),
        (("created_at",), "2042-03-12T12:00:02Z"),
    ),
)
def test_fabricated_workflow_metadata_is_rejected(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    payload = deepcopy(_payload())
    target: dict[str, object] = payload
    for component in path[:-1]:
        nested = target[component]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = replacement
    with pytest.raises(
        Increment5ContractError,
        match="authenticated workflow",
    ):
        validate_github_workflow_attempt_payload(
            attempt=_attempt(),
            payload=payload,
        )


def test_authenticated_commit_must_bind_exact_tree() -> None:
    record = _record()
    valid = {
        "sha": _COMMIT,
        "url": (
            "https://api.github.com/repos/fol2/newsroom/"
            f"git/commits/{_COMMIT}"
        ),
        "tree": {"sha": _TREE},
    }
    validate_github_commit_payload(record=record, payload=valid)
    tampered = deepcopy(valid)
    tree = tampered["tree"]
    assert isinstance(tree, dict)
    tree["sha"] = "3" * 40
    with pytest.raises(
        Increment5ContractError,
        match="commit/tree identity differs",
    ):
        validate_github_commit_payload(
            record=record,
            payload=tampered,
        )


def test_synthetic_claim_cannot_authenticate_without_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(
        Increment5ContractError,
        match="GitHub workflow evidence is unavailable",
    ):
        authenticate_repository_main_qualification_record(_record())


def test_source_pinned_loader_captures_the_authenticator() -> None:
    source = inspect.getsource(
        approval_module._main_qualification_loader_factory
    )
    assert "captured_authenticator" in source
    assert "captured_authenticator(qualification)" in source
