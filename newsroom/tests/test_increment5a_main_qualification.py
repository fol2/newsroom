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
    MAIN_QUALIFICATION_RECORD_DIGEST,
    MAIN_QUALIFICATION_RECORD_PATH,
    MAIN_QUALIFICATION_RECORD_SCHEMA,
    MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST,
    MAIN_QUALIFICATION_RECORD_SCHEMA_PATH,
    MAIN_QUALIFICATION_WORKFLOW_NAMES,
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
_QUALIFIED_AT = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
_WORKFLOW_RUNS = {
    "CI": 101,
    "AUTHORITY_A2A": 102,
    "AUTHORITY_A2B": 103,
    "PROJECTION_B1": 104,
    "PROJECTION_B2_B3_C1_NEO4J": 105,
    "SDLC_EVIDENCE_SHADOW": 106,
}
_DECISION_DIGEST = "sha256:" + "b" * 64


def _value() -> dict[str, object]:
    return main_qualification_record_value(
        proposal=INCREMENT_5A_DECISION_PACKET,
        approval_record_digest=_APPROVAL_DIGEST,
        qualified_main_commit_sha=_COMMIT_SHA,
        qualified_main_tree_sha=_TREE_SHA,
        qualified_at=_QUALIFIED_AT,
        workflow_run_ids=_WORKFLOW_RUNS,
        signed_sdlc_decision_digest=_DECISION_DIGEST,
        test_count=1911,
        skip_count=38,
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


def test_main_qualification_record_binds_exact_approval_and_main_evidence(
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
    assert record.workflow_run_id_by_name == _WORKFLOW_RUNS
    assert record.signed_sdlc_decision_digest == _DECISION_DIGEST
    assert record.test_count == 1911
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


def test_main_qualification_record_rejects_incomplete_or_reused_runs(
    tmp_path: Path,
) -> None:
    missing = _value()
    evidence = missing["evidence"]
    assert isinstance(evidence, dict)
    workflow_runs = evidence["workflow_runs"]
    assert isinstance(workflow_runs, dict)
    workflow_runs.pop("CI")
    with pytest.raises(
        Increment5ContractError,
        match="schema validation failed",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, missing),
            approval_record_digest=_APPROVAL_DIGEST,
        )

    reused = deepcopy(_WORKFLOW_RUNS)
    reused["CI"] = reused["AUTHORITY_A2A"]
    with pytest.raises(
        Increment5ContractError,
        match="must be distinct",
    ):
        main_qualification_record_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approval_record_digest=_APPROVAL_DIGEST,
            qualified_main_commit_sha=_COMMIT_SHA,
            qualified_main_tree_sha=_TREE_SHA,
            qualified_at=_QUALIFIED_AT,
            workflow_run_ids=reused,
            signed_sdlc_decision_digest=_DECISION_DIGEST,
            test_count=1911,
            skip_count=38,
        )


def test_main_qualification_record_requires_canonical_utc(
    tmp_path: Path,
) -> None:
    value = _value()
    value["qualified_at"] = "2042-03-12T12:00:00Z"
    with pytest.raises(
        Increment5ContractError,
        match="canonical UTC text",
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


def test_workflow_inventory_is_exact() -> None:
    assert MAIN_QUALIFICATION_WORKFLOW_NAMES == (
        "CI",
        "AUTHORITY_A2A",
        "AUTHORITY_A2B",
        "PROJECTION_B1",
        "PROJECTION_B2_B3_C1_NEO4J",
        "SDLC_EVIDENCE_SHADOW",
    )
