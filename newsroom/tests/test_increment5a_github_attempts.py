from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import inspect
import json
from pathlib import Path

import pytest

import newsroom.increment5.approval as approval_module
import newsroom.increment5.github_attempts as github_attempts_module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
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
from scripts.sdlc.increment5_github_admission import (
    validate_authenticated_decision_artifact,
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


def _decision_artifact(
    tmp_path: Path,
) -> tuple[
    Path,
    dict[str, object],
    Increment5AMainQualificationRecord,
]:
    context = {
        "repository": MAIN_QUALIFICATION_REPOSITORY,
        "repository_id": MAIN_QUALIFICATION_REPOSITORY_ID,
    }
    event = {
        "repository": MAIN_QUALIFICATION_REPOSITORY,
        "repository_id": MAIN_QUALIFICATION_REPOSITORY_ID,
    }
    decision = {
        "context": context,
        "event": event,
    }
    document_digest = digest_bytes(canonical_json_bytes(decision))
    record = replace(
        _record(),
        decision_document_digest=document_digest,
    )
    record_value = {
        "signed_decision": {
            "decision_document_digest": document_digest,
            "decision_document": decision,
        }
    }
    root = tmp_path / "artifact"
    (root / "decision-input").mkdir(parents=True)
    (root / "decision.json").write_bytes(
        canonical_json_bytes(decision) + b"\n"
    )
    (root / "decision-input" / "context.json").write_bytes(
        canonical_json_bytes(context) + b"\n"
    )
    collection = {
        "schema_version": "newsroom.sdlc.decision-collection.v1",
        "context": context,
        "event": event,
        "failure_code": None,
        "failure_result": None,
        "status": "READY",
    }
    (root / "decision-input" / "collection.json").write_bytes(
        canonical_json_bytes(collection) + b"\n"
    )
    return root, record_value, record


def _authentication_certificate(
    record: Increment5AMainQualificationRecord,
    *,
    verifier_source_digest: str,
) -> dict[str, object]:
    sdlc = record.workflow_attempt_by_name["SDLC_EVIDENCE_SHADOW"]
    value: dict[str, object] = {
        "schema_version": (
            "newsroom.increment5."
            "github-main-admission-authentication.v1"
        ),
        "record_digest": record.record_digest,
        "qualified_main_commit_sha": record.qualified_main_commit_sha,
        "qualified_main_tree_sha": record.qualified_main_tree_sha,
        "workflow_attempts": [
            {
                "key": attempt.key,
                "run_id": attempt.run_id,
                "run_attempt": attempt.run_attempt,
            }
            for attempt in record.workflow_attempts
        ],
        "sdlc_artifact": {
            "artifact_id": 9001,
            "name": (
                "newsroom-sdlc-decision-"
                f"{sdlc.run_id}-{sdlc.run_attempt}-"
                f"{record.qualified_main_commit_sha}"
            ),
            "archive_digest": "sha256:" + "3" * 64,
            "transport_identity": "sha256:" + "4" * 64,
        },
        "decision_document_digest": record.decision_document_digest,
        "decision_file_digest": "sha256:" + "5" * 64,
        "context_file_digest": "sha256:" + "6" * 64,
        "collection_file_digest": "sha256:" + "7" * 64,
        "verifier_source_digest": verifier_source_digest,
    }
    value["authentication_identity"] = digest_bytes(
        canonical_json_bytes(value)
    )
    return value


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


def test_exact_authenticated_decision_artifact_is_accepted(
    tmp_path: Path,
) -> None:
    root, value, record = _decision_artifact(tmp_path)
    digests = validate_authenticated_decision_artifact(
        extracted_root=root,
        record_value=value,
        record=record,
    )
    assert set(digests) == {
        "decision_file_digest",
        "context_file_digest",
        "collection_file_digest",
    }
    assert digests["decision_file_digest"] == digest_bytes(
        (root / "decision.json").read_bytes()
    )


def test_locally_fabricated_decision_bytes_are_rejected(
    tmp_path: Path,
) -> None:
    root, value, record = _decision_artifact(tmp_path)
    (root / "decision.json").write_bytes(
        canonical_json_bytes(
            {
                "context": {
                    "repository": MAIN_QUALIFICATION_REPOSITORY,
                },
                "event": {
                    "repository": MAIN_QUALIFICATION_REPOSITORY,
                },
                "locally_fabricated": True,
            }
        )
        + b"\n"
    )
    with pytest.raises(
        Increment5ContractError,
        match="decision bytes differ",
    ):
        validate_authenticated_decision_artifact(
            extracted_root=root,
            record_value=value,
            record=record,
        )


def test_decision_artifact_rejects_extra_or_changed_evidence(
    tmp_path: Path,
) -> None:
    root, value, record = _decision_artifact(tmp_path)
    (root / "extra.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        Increment5ContractError,
        match="inventory differs",
    ):
        validate_authenticated_decision_artifact(
            extracted_root=root,
            record_value=value,
            record=record,
        )

    (root / "extra.json").unlink()
    collection_path = root / "decision-input" / "collection.json"
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    collection["status"] = "FAILED"
    collection_path.write_bytes(
        canonical_json_bytes(collection) + b"\n"
    )
    with pytest.raises(
        Increment5ContractError,
        match="collection differs",
    ):
        validate_authenticated_decision_artifact(
            extracted_root=root,
            record_value=value,
            record=record,
        )


def test_authentication_certificate_binds_artifact_and_record() -> None:
    record = _record()
    verifier_digest = "sha256:" + "8" * 64
    certificate = _authentication_certificate(
        record,
        verifier_source_digest=verifier_digest,
    )
    github_attempts_module._validate_authentication_certificate(
        record=record,
        value=certificate,
        verifier_source_digest=verifier_digest,
    )

    tampered = deepcopy(certificate)
    artifact = tampered["sdlc_artifact"]
    assert isinstance(artifact, dict)
    artifact["archive_digest"] = "sha256:" + "9" * 64
    with pytest.raises(
        Increment5ContractError,
        match="certificate digest differs",
    ):
        github_attempts_module._validate_authentication_certificate(
            record=record,
            value=tampered,
            verifier_source_digest=verifier_digest,
        )


def test_transport_authentication_runs_out_of_process() -> None:
    source = inspect.getsource(github_attempts_module)
    assert "GitHubActionsClient" not in source
    assert "fetch_run_attempt(" not in source
    assert '"-I"' in source
    assert "increment5_github_admission.py" in source
    assert "captured_run_process" in source
    assert "verifier_source_digest" in source
    assert "PYTHONPATH" not in source
    assert "SSL_CERT_FILE" not in source

    verifier_source = (
        github_attempts_module._VERIFIER_PATH.read_text(
            encoding="utf-8"
        )
    )
    assert "fetch_artifact_bundle(" in verifier_source
    assert "validate_authenticated_decision_artifact(" in verifier_source
    assert "newsroom-sdlc-decision-" in verifier_source
    assert "_EXPECTED_DECISION_ARTIFACT_FILES" in verifier_source


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
