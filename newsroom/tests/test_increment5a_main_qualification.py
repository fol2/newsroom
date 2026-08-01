from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import newsroom.increment5.approval as approval_module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.increment5 import (
    APPROVAL_EFFECT,
    INCREMENT_5A_DECISION_AUTHORITY,
    INCREMENT_5A_DECISION_PACKET,
    Increment5ContractError,
    Increment5ProfileError,
    MAIN_QUALIFICATION_EFFECT,
    MAIN_QUALIFICATION_NON_EFFECTS,
    MAIN_QUALIFICATION_RECORD_DIGEST,
    MAIN_QUALIFICATION_RECORD_PATH,
    MAIN_QUALIFICATION_RECORD_SCHEMA,
    MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST,
    MAIN_QUALIFICATION_RECORD_SCHEMA_PATH,
    MAIN_QUALIFICATION_REF,
    MAIN_QUALIFICATION_REPOSITORY,
    MAIN_QUALIFICATION_REPOSITORY_ID,
    MAIN_QUALIFICATION_WORKFLOW_NAMES,
    MAIN_QUALIFICATION_WORKFLOW_SPECS,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
    RetrievalComponentKind,
    RetrievalProfileKind,
    approval_attestation_value,
    expected_increment5a_owner_approval_body,
    load_increment5a_approval_attestation,
    load_increment5a_main_qualification_record,
    main_qualification_record_value,
    repository_main_qualification_record,
)


_APPROVAL_DIGEST = "sha256:" + "a" * 64
_COMMIT_SHA = "1" * 40
_TREE_SHA = "2" * 40
_QUALIFIED_AT = UtcTimestamp.parse("2042-03-12T12:30:00.000000Z")
_CREATED_AT = "2042-03-12T12:00:00.000000Z"
_STARTED_AT = "2042-03-12T12:00:01.000000Z"
_UPDATED_AT = "2042-03-12T12:20:00.000000Z"
_DECISION_IDENTITY = "sha256:" + "b" * 64


def _workflow_attempts() -> dict[str, dict[str, object]]:
    attempts: dict[str, dict[str, object]] = {}
    for index, key in enumerate(MAIN_QUALIFICATION_WORKFLOW_NAMES, start=1):
        workflow_id, workflow_name = MAIN_QUALIFICATION_WORKFLOW_SPECS[key]
        run_id = 1000 + index
        attempts[key] = {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "run_id": run_id,
            "run_attempt": 1,
            "run_number": 2000 + index,
            "repository": MAIN_QUALIFICATION_REPOSITORY,
            "repository_id": MAIN_QUALIFICATION_REPOSITORY_ID,
            "event": "push",
            "ref": MAIN_QUALIFICATION_REF,
            "head_branch": "main",
            "head_sha": _COMMIT_SHA,
            "head_tree_sha": _TREE_SHA,
            "workflow_sha": _COMMIT_SHA,
            "workflow_ref": (
                f"{MAIN_QUALIFICATION_REPOSITORY}/.github/workflows/"
                f"{key.lower()}.yml@{MAIN_QUALIFICATION_REF}"
            ),
            "status": "completed",
            "conclusion": "success",
            "api_url": (
                f"https://api.github.com/repos/"
                f"{MAIN_QUALIFICATION_REPOSITORY}/actions/runs/{run_id}/"
                "attempts/1"
            ),
            "html_url": (
                f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/"
                f"actions/runs/{run_id}"
            ),
            "created_at": _CREATED_AT,
            "run_started_at": _STARTED_AT,
            "updated_at": _UPDATED_AT,
        }
    return attempts


def _decision_document(
    *,
    attempts: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    selected = _workflow_attempts() if attempts is None else attempts
    sdlc = selected["SDLC_EVIDENCE_SHADOW"]
    return {
        "schema_version": "newsroom.sdlc.shadow-decision.v1",
        "decision_identity": _DECISION_IDENTITY,
        "result": "PASS",
        "result_reason": "PASS:decision",
        "first_failure": None,
        "context": {
            "repository": MAIN_QUALIFICATION_REPOSITORY,
            "event_name": "push",
            "ref": MAIN_QUALIFICATION_REF,
            "evaluated_sha": _COMMIT_SHA,
            "evaluated_tree_sha": _TREE_SHA,
            "run_id": sdlc["run_id"],
            "run_attempt": sdlc["run_attempt"],
            "workflow_ref": sdlc["workflow_ref"],
            "workflow_sha": _COMMIT_SHA,
        },
        "event": {
            "repository": MAIN_QUALIFICATION_REPOSITORY,
            "event_name": "push",
            "ref": MAIN_QUALIFICATION_REF,
            "evaluated_sha": _COMMIT_SHA,
            "evaluated_tree_sha": _TREE_SHA,
        },
        "lanes": [
            {
                "lane_id": "core",
                "receipt": {
                    "gate_decisions": [
                        {
                            "gate_id": "core-deterministic",
                            "result": "PASS",
                        },
                        {
                            "gate_id": "source-integrity",
                            "result": "PASS",
                        },
                    ]
                },
            }
        ],
        "totals": {
            "test_count": 1920,
            "skip_count": 38,
            "required_skip_count": 0,
            "failure_count": 0,
            "error_count": 0,
        },
    }


def _value() -> dict[str, object]:
    attempts = _workflow_attempts()
    return main_qualification_record_value(
        proposal=INCREMENT_5A_DECISION_PACKET,
        approval_record_digest=_APPROVAL_DIGEST,
        qualified_main_commit_sha=_COMMIT_SHA,
        qualified_main_tree_sha=_TREE_SHA,
        qualified_at=_QUALIFIED_AT,
        workflow_attempts=attempts,
        decision_document=_decision_document(attempts=attempts),
    )


def _write(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "main-qualification.json"
    path.write_bytes(canonical_json_bytes(value))
    return path


def test_main_qualification_schema_artifact_is_canonical() -> None:
    data = MAIN_QUALIFICATION_RECORD_SCHEMA_PATH.read_bytes()
    assert data == canonical_json_bytes(json.loads(data.decode("utf-8")))
    assert digest_bytes(data) == MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST
    assert MAIN_QUALIFICATION_RECORD_SCHEMA["properties"]["branch"] == {
        "const": "main"
    }


def test_current_branch_has_no_post_merge_implementation_admission() -> None:
    assert MAIN_QUALIFICATION_RECORD_DIGEST is None
    assert not MAIN_QUALIFICATION_RECORD_PATH.exists()
    assert repository_main_qualification_record() is None
    assert not INCREMENT_5A_DECISION_AUTHORITY.production_authorized
    assert not (
        INCREMENT_5A_DECISION_AUTHORITY.downstream_implementation_authorized
    )
    assert INCREMENT_5A_DECISION_AUTHORITY.main_qualification_record_digest is None
    assert INCREMENT_5A_DECISION_AUTHORITY.qualified_main_commit_sha is None


def test_main_qualification_record_binds_attempts_and_signed_pass(
    tmp_path: Path,
) -> None:
    record = load_increment5a_main_qualification_record(
        _write(tmp_path, _value()),
        approval_record_digest=_APPROVAL_DIGEST,
    )
    assert record.qualified_main_commit_sha == _COMMIT_SHA
    assert record.qualified_main_tree_sha == _TREE_SHA
    assert record.qualified_at == _QUALIFIED_AT
    assert record.approval_record_digest == _APPROVAL_DIGEST
    assert tuple(record.workflow_attempt_by_name) == (
        MAIN_QUALIFICATION_WORKFLOW_NAMES
    )
    assert record.decision_identity == _DECISION_IDENTITY
    assert record.test_count == 1920
    assert record.skip_count == 38


def test_main_qualification_record_rejects_wrong_approval(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        Increment5ContractError,
        match="approval digest differs",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, _value()),
            approval_record_digest="sha256:" + "c" * 64,
        )


def test_main_qualification_record_rejects_wrong_proposal(
    tmp_path: Path,
) -> None:
    value = _value()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    proposal["payload_digest"] = "sha256:" + "c" * 64
    with pytest.raises(
        Increment5ContractError,
        match="does not bind the exact proposal",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, value),
            approval_record_digest=_APPROVAL_DIGEST,
        )


def test_main_qualification_record_rejects_incomplete_or_reused_attempts(
    tmp_path: Path,
) -> None:
    missing = _value()
    attempts = missing["workflow_attempts"]
    assert isinstance(attempts, dict)
    attempts.pop("CI")
    with pytest.raises(
        Increment5ContractError,
        match="schema validation failed",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, missing),
            approval_record_digest=_APPROVAL_DIGEST,
        )

    reused = _workflow_attempts()
    reused["CI"]["run_id"] = reused["AUTHORITY_A2A"]["run_id"]
    reused["CI"]["api_url"] = reused["AUTHORITY_A2A"]["api_url"]
    reused["CI"]["html_url"] = reused["AUTHORITY_A2A"]["html_url"]
    with pytest.raises(
        Increment5ContractError,
        match="identities must be distinct",
    ):
        main_qualification_record_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approval_record_digest=_APPROVAL_DIGEST,
            qualified_main_commit_sha=_COMMIT_SHA,
            qualified_main_tree_sha=_TREE_SHA,
            qualified_at=_QUALIFIED_AT,
            workflow_attempts=reused,
            decision_document=_decision_document(attempts=reused),
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("head_sha", "3" * 40, "not bound to qualified main"),
        ("head_tree_sha", "3" * 40, "not bound to qualified main"),
        ("workflow_sha", "3" * 40, "not bound to qualified main"),
        ("conclusion", "failure", "schema validation failed"),
        ("event", "pull_request", "schema validation failed"),
        ("ref", "refs/pull/255/merge", "schema validation failed"),
    ),
)
def test_workflow_attempts_must_be_successful_exact_main(
    tmp_path: Path,
    field: str,
    replacement: str,
    message: str,
) -> None:
    value = _value()
    attempts = value["workflow_attempts"]
    assert isinstance(attempts, dict)
    ci = attempts["CI"]
    assert isinstance(ci, dict)
    ci[field] = replacement
    with pytest.raises(Increment5ContractError, match=message):
        load_increment5a_main_qualification_record(
            _write(tmp_path, value),
            approval_record_digest=_APPROVAL_DIGEST,
        )


def test_main_qualification_record_rejects_noncanonical_time(
    tmp_path: Path,
) -> None:
    value = _value()
    value["qualified_at"] = "2042-03-12T12:30:00Z"
    with pytest.raises(
        Increment5ContractError,
        match="canonical UTC text",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, value),
            approval_record_digest=_APPROVAL_DIGEST,
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("result", "BUDGET_EXCEEDED", "result is not PASS"),
        ("result_reason", "BUDGET_EXCEEDED:decision", "reason is not PASS"),
        ("first_failure", {"gate_id": "core"}, "first failure"),
    ),
)
def test_signed_decision_must_be_pass(
    tmp_path: Path,
    field: str,
    replacement: object,
    message: str,
) -> None:
    value = _value()
    signed = value["signed_decision"]
    assert isinstance(signed, dict)
    document = signed["decision_document"]
    assert isinstance(document, dict)
    document[field] = replacement
    signed["decision_document_digest"] = digest_bytes(
        canonical_json_bytes(document)
    )
    with pytest.raises(Increment5ContractError, match=message):
        load_increment5a_main_qualification_record(
            _write(tmp_path, value),
            approval_record_digest=_APPROVAL_DIGEST,
        )


def test_signed_decision_summary_must_match_canonical_document(
    tmp_path: Path,
) -> None:
    value = _value()
    signed = value["signed_decision"]
    assert isinstance(signed, dict)
    signed["test_count"] = 1919
    with pytest.raises(
        Increment5ContractError,
        match="summary differs",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, value),
            approval_record_digest=_APPROVAL_DIGEST,
        )


def test_signed_decision_document_digest_is_exact(
    tmp_path: Path,
) -> None:
    value = _value()
    signed = value["signed_decision"]
    assert isinstance(signed, dict)
    signed["decision_document_digest"] = "sha256:" + "c" * 64
    with pytest.raises(
        Increment5ContractError,
        match="document digest differs",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, value),
            approval_record_digest=_APPROVAL_DIGEST,
        )


def test_owner_approval_alone_cannot_open_increment5b(
    tmp_path: Path,
) -> None:
    body_digest = digest_bytes(
        expected_increment5a_owner_approval_body().encode("utf-8")
    )
    approval_path = tmp_path / "approval.json"
    approval_path.write_bytes(
        canonical_json_bytes(
            approval_attestation_value(
                proposal=INCREMENT_5A_DECISION_PACKET,
                approved_at=_QUALIFIED_AT,
                comment_id=123456789,
                approval_comment_body_digest=body_digest,
            )
        )
    )
    approval = load_increment5a_approval_attestation(approval_path)
    effective_digest_for = approval_module._effective_contract_digest_factory(
        proposal=INCREMENT_5A_DECISION_PACKET,
        qualification_schema_digest=(
            QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST
        ),
        approval_effect=APPROVAL_EFFECT,
    )
    authority_type = approval_module._decision_authority_class_factory(
        proposal=INCREMENT_5A_DECISION_PACKET,
        load_approval=lambda: approval,
        load_main_qualification=lambda: None,
        effective_contract_digest_for=effective_digest_for,
    )
    authority = authority_type()

    assert authority.production_qualification_authorized
    assert not authority.production_authorized
    assert not authority.downstream_implementation_authorized
    assert authority.main_qualification_record_digest is None
    assert authority.downstream_contract_digest is None
    for kind in RetrievalComponentKind:
        assert not authority.component_authorized(kind)
    with pytest.raises(
        Increment5ProfileError,
        match="post-merge exact-main qualification record",
    ):
        authority.require_profile(RetrievalProfileKind.PRODUCTION)


def test_authority_effects_are_separate_and_exact() -> None:
    assert APPROVAL_EFFECT == "PRODUCTION_EQUIVALENT_QUALIFICATION_ONLY"
    assert MAIN_QUALIFICATION_EFFECT == (
        "IMPLEMENTATION_OF_ISSUES_251_254_ONLY"
    )
    assert "DOWNSTREAM_IMPLEMENTATION" not in MAIN_QUALIFICATION_NON_EFFECTS


def test_workflow_inventory_is_exact() -> None:
    assert MAIN_QUALIFICATION_WORKFLOW_NAMES == (
        "CI",
        "AUTHORITY_A2A",
        "AUTHORITY_A2B",
        "PROJECTION_B1",
        "PROJECTION_B2_B3_C1_NEO4J",
        "SDLC_EVIDENCE_SHADOW",
    )
