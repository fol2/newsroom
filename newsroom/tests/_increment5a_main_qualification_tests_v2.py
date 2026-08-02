from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
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
from newsroom.increment5.main_qualification import (
    MAIN_QUALIFICATION_WORKFLOW_EVENTS,
)
from newsroom.tests.test_sdlc_shadow_decision import (
    _Route,
    _lane as _sdlc_lane,
    _patch_lane_validator,
)
from scripts.sdlc.artifact_envelope import GithubRunContext
from scripts.sdlc.contracts import load_contract
from scripts.sdlc.shadow_decision import aggregate_shadow_decision
from scripts.sdlc.workflow_event import WorkflowEvent


_APPROVAL_DIGEST = "sha256:" + "a" * 64
_COMMIT_SHA = "1" * 40
_TREE_SHA = "2" * 40
_BASE_SHA = "3" * 40
_BASE_TREE_SHA = "4" * 40
_QUALIFIED_AT = UtcTimestamp.parse("2042-03-12T12:30:00.000000Z")
_CREATED_AT = "2042-03-12T12:00:00.000000Z"
_STARTED_AT = "2042-03-12T12:00:01.000000Z"
_UPDATED_AT = "2042-03-12T12:20:00.000000Z"
_WORKFLOW_FILE_BY_KEY = {
    "CI": "ci.yml",
    "AUTHORITY_A2A": "authority-a2a.yml",
    "AUTHORITY_A2B": "authority-a2b.yml",
    "PROJECTION_B1": "projection-b1.yml",
    "PROJECTION_B2_B3_C1_NEO4J": "projection-b2-neo4j.yml",
    "SDLC_EVIDENCE_SHADOW": "evidence.yml",
}


def _contract():
    return load_contract(Path(__file__).resolve().parents[2])


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
            "event": MAIN_QUALIFICATION_WORKFLOW_EVENTS[key],
            "ref": MAIN_QUALIFICATION_REF,
            "head_branch": "main",
            "head_sha": _COMMIT_SHA,
            "head_tree_sha": _TREE_SHA,
            "workflow_sha": _COMMIT_SHA,
            "workflow_ref": (
                f"{MAIN_QUALIFICATION_REPOSITORY}/.github/workflows/"
                f"{_WORKFLOW_FILE_BY_KEY[key]}@{MAIN_QUALIFICATION_REF}"
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


def _canonical_decision_document(
    monkeypatch: pytest.MonkeyPatch,
    *,
    attempts: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    selected = _workflow_attempts() if attempts is None else attempts
    sdlc = selected["SDLC_EVIDENCE_SHADOW"]
    route = _Route(
        risk_tier="R1_LOCAL_CODE",
        service_required=False,
        owner_authority_required=False,
        base_sha=_BASE_SHA,
        base_tree_sha=_BASE_TREE_SHA,
    )
    core = _sdlc_lane("core", route)
    core = replace(
        core,
        receipt=replace(
            core.receipt,
            metadata=replace(
                core.receipt.metadata,
                run_id=int(sdlc["run_id"]),
            ),
            run_attempt=int(sdlc["run_attempt"]),
            workflow_ref=str(sdlc["workflow_ref"]),
            workflow_sha=_COMMIT_SHA,
            event_name="workflow_dispatch",
            event_sha=_COMMIT_SHA,
            evaluated_sha=_COMMIT_SHA,
            evaluated_tree_sha=_TREE_SHA,
            ref=MAIN_QUALIFICATION_REF,
        ),
        replay=replace(
            core.replay,
            run_id=int(sdlc["run_id"]),
            run_attempt=int(sdlc["run_attempt"]),
            head_sha=_COMMIT_SHA,
        ),
        run_event="workflow_dispatch",
    )
    _patch_lane_validator(monkeypatch, core)

    context = GithubRunContext(
        repository=MAIN_QUALIFICATION_REPOSITORY,
        repository_id=MAIN_QUALIFICATION_REPOSITORY_ID,
        head_repository=MAIN_QUALIFICATION_REPOSITORY,
        head_repository_id=MAIN_QUALIFICATION_REPOSITORY_ID,
        run_id=int(sdlc["run_id"]),
        run_attempt=int(sdlc["run_attempt"]),
        job_id="decision",
        workflow_ref=str(sdlc["workflow_ref"]),
        workflow_sha=_COMMIT_SHA,
        event_name="workflow_dispatch",
        event_sha=_COMMIT_SHA,
        evaluated_sha=_COMMIT_SHA,
        evaluated_tree_sha=_TREE_SHA,
        ref=MAIN_QUALIFICATION_REF,
        runner_environment="github-hosted",
    )
    event = WorkflowEvent(
        repository=MAIN_QUALIFICATION_REPOSITORY,
        repository_id=MAIN_QUALIFICATION_REPOSITORY_ID,
        head_repository=MAIN_QUALIFICATION_REPOSITORY,
        head_repository_id=MAIN_QUALIFICATION_REPOSITORY_ID,
        event_name="workflow_dispatch",
        event_sha=_COMMIT_SHA,
        base_sha=_BASE_SHA,
        base_tree_sha=_BASE_TREE_SHA,
        evaluated_sha=_COMMIT_SHA,
        evaluated_tree_sha=_TREE_SHA,
        ref=MAIN_QUALIFICATION_REF,
    )
    return aggregate_shadow_decision(
        context=context,
        event=event,
        core=core,  # type: ignore[arg-type]
        service=None,
        contract=_contract(),
    ).as_dict()


def _fabricated_minimal_pass(
    *,
    attempts: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    selected = _workflow_attempts() if attempts is None else attempts
    sdlc = selected["SDLC_EVIDENCE_SHADOW"]
    return {
        "schema_version": "newsroom.sdlc.shadow-decision.v1",
        "decision_identity": "sha256:" + "b" * 64,
        "result": "PASS",
        "result_reason": "PASS:decision",
        "first_failure": None,
        "context": {
            "repository": MAIN_QUALIFICATION_REPOSITORY,
            "event_name": "workflow_dispatch",
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
            "event_name": "workflow_dispatch",
            "ref": MAIN_QUALIFICATION_REF,
            "evaluated_sha": _COMMIT_SHA,
            "evaluated_tree_sha": _TREE_SHA,
        },
        "lanes": [
            {
                "lane_id": "core",
                "receipt": {
                    "gate_decisions": [
                        {"gate_id": "core-deterministic", "result": "PASS"},
                        {"gate_id": "source-integrity", "result": "PASS"},
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


def _value(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    attempts = _workflow_attempts()
    return main_qualification_record_value(
        proposal=INCREMENT_5A_DECISION_PACKET,
        approval_record_digest=_APPROVAL_DIGEST,
        qualified_main_commit_sha=_COMMIT_SHA,
        qualified_main_tree_sha=_TREE_SHA,
        qualified_at=_QUALIFIED_AT,
        workflow_attempts=attempts,
        decision_document=_canonical_decision_document(
            monkeypatch,
            attempts=attempts,
        ),
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
    workflow_properties = MAIN_QUALIFICATION_RECORD_SCHEMA["properties"][
        "workflow_attempts"
    ]["properties"]
    for key in MAIN_QUALIFICATION_WORKFLOW_NAMES:
        assert workflow_properties[key]["properties"]["event"] == {
            "const": MAIN_QUALIFICATION_WORKFLOW_EVENTS[key]
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


def test_main_qualification_record_binds_attempts_and_canonical_signed_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _value(monkeypatch)
    record = load_increment5a_main_qualification_record(
        _write(tmp_path, value),
        approval_record_digest=_APPROVAL_DIGEST,
    )
    signed = value["signed_decision"]
    assert isinstance(signed, dict)
    assert record.qualified_main_commit_sha == _COMMIT_SHA
    assert record.qualified_main_tree_sha == _TREE_SHA
    assert record.qualified_at == _QUALIFIED_AT
    assert record.approval_record_digest == _APPROVAL_DIGEST
    assert tuple(record.workflow_attempt_by_name) == (
        MAIN_QUALIFICATION_WORKFLOW_NAMES
    )
    assert record.decision_identity == signed["decision_identity"]
    assert record.test_count == signed["test_count"]
    assert record.skip_count == signed["skip_count"]


def test_main_qualification_record_rejects_wrong_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        Increment5ContractError,
        match="approval digest differs",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, _value(monkeypatch)),
            approval_record_digest="sha256:" + "c" * 64,
        )


def test_main_qualification_record_rejects_wrong_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _value(monkeypatch)
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = _value(monkeypatch)
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
            decision_document=_canonical_decision_document(
                monkeypatch,
                attempts=reused,
            ),
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("head_sha", "3" * 40, "not bound to qualified main"),
        ("head_tree_sha", "3" * 40, "not bound to qualified main"),
        ("workflow_sha", "3" * 40, "not bound to qualified main"),
        ("conclusion", "failure", "event|schema|successfully"),
        ("ref", "refs/pull/255/merge", "ref differs"),
    ),
)
def test_workflow_attempts_must_be_successful_exact_main(
    field: str,
    replacement: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = _workflow_attempts()
    attempts["CI"][field] = replacement
    with pytest.raises(Increment5ContractError, match=message):
        main_qualification_record_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approval_record_digest=_APPROVAL_DIGEST,
            qualified_main_commit_sha=_COMMIT_SHA,
            qualified_main_tree_sha=_TREE_SHA,
            qualified_at=_QUALIFIED_AT,
            workflow_attempts=attempts,
            decision_document=_canonical_decision_document(monkeypatch),
        )


def test_workflow_events_are_specialised_and_truthful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert MAIN_QUALIFICATION_WORKFLOW_EVENTS == {
        "CI": "push",
        "AUTHORITY_A2A": "push",
        "AUTHORITY_A2B": "push",
        "PROJECTION_B1": "push",
        "PROJECTION_B2_B3_C1_NEO4J": "push",
        "SDLC_EVIDENCE_SHADOW": "workflow_dispatch",
    }

    bad_sdlc = _workflow_attempts()
    bad_sdlc["SDLC_EVIDENCE_SHADOW"]["event"] = "push"
    with pytest.raises(Increment5ContractError, match="event differs"):
        main_qualification_record_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approval_record_digest=_APPROVAL_DIGEST,
            qualified_main_commit_sha=_COMMIT_SHA,
            qualified_main_tree_sha=_TREE_SHA,
            qualified_at=_QUALIFIED_AT,
            workflow_attempts=bad_sdlc,
            decision_document=_canonical_decision_document(monkeypatch),
        )

    bad_ci = _workflow_attempts()
    bad_ci["CI"]["event"] = "workflow_dispatch"
    with pytest.raises(Increment5ContractError, match="event differs"):
        main_qualification_record_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approval_record_digest=_APPROVAL_DIGEST,
            qualified_main_commit_sha=_COMMIT_SHA,
            qualified_main_tree_sha=_TREE_SHA,
            qualified_at=_QUALIFIED_AT,
            workflow_attempts=bad_ci,
            decision_document=_canonical_decision_document(monkeypatch),
        )


def test_signed_decision_requires_complete_repository_and_event_identity() -> None:
    source = Path(approval_module.__file__).with_name(
        "main_qualification.py"
    ).read_text(encoding="utf-8")
    for field_name in (
        "repository_id",
        "head_repository",
        "head_repository_id",
        "event_sha",
    ):
        assert f'("{field_name}",' in source


def test_main_qualification_record_rejects_noncanonical_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _value(monkeypatch)
    value["qualified_at"] = "2042-03-12T12:30:00Z"
    with pytest.raises(
        Increment5ContractError,
        match="canonical UTC text",
    ):
        load_increment5a_main_qualification_record(
            _write(tmp_path, value),
            approval_record_digest=_APPROVAL_DIGEST,
        )


def test_fabricated_minimal_pass_document_is_rejected() -> None:
    attempts = _workflow_attempts()
    with pytest.raises(
        Increment5ContractError,
        match="canonical SDLC evidence",
    ):
        main_qualification_record_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approval_record_digest=_APPROVAL_DIGEST,
            qualified_main_commit_sha=_COMMIT_SHA,
            qualified_main_tree_sha=_TREE_SHA,
            qualified_at=_QUALIFIED_AT,
            workflow_attempts=attempts,
            decision_document=_fabricated_minimal_pass(attempts=attempts),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "fake_totals",
        "missing_context",
        "arbitrary_identity",
    ),
)
def test_canonical_sdlc_document_rejects_fabricated_claims(
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = _workflow_attempts()
    document = _canonical_decision_document(monkeypatch, attempts=attempts)
    if mutation == "fake_totals":
        totals = document["totals"]
        assert isinstance(totals, dict)
        totals["test_count"] = int(totals["test_count"]) + 1
    elif mutation == "missing_context":
        document.pop("context")
    else:
        document["decision_identity"] = "sha256:" + "c" * 64

    with pytest.raises(
        Increment5ContractError,
        match="canonical SDLC evidence",
    ):
        main_qualification_record_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approval_record_digest=_APPROVAL_DIGEST,
            qualified_main_commit_sha=_COMMIT_SHA,
            qualified_main_tree_sha=_TREE_SHA,
            qualified_at=_QUALIFIED_AT,
            workflow_attempts=attempts,
            decision_document=document,
        )


def test_invalid_lane_receipt_is_rejected() -> None:
    attempts = _workflow_attempts()
    document = _fabricated_minimal_pass(attempts=attempts)
    lanes = document["lanes"]
    assert isinstance(lanes, list)
    lane = lanes[0]
    assert isinstance(lane, dict)
    lane["receipt"] = {"gate_decisions": []}
    with pytest.raises(
        Increment5ContractError,
        match="canonical SDLC evidence",
    ):
        main_qualification_record_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approval_record_digest=_APPROVAL_DIGEST,
            qualified_main_commit_sha=_COMMIT_SHA,
            qualified_main_tree_sha=_TREE_SHA,
            qualified_at=_QUALIFIED_AT,
            workflow_attempts=attempts,
            decision_document=document,
        )


def test_signed_decision_summary_must_match_canonical_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _value(monkeypatch)
    signed = value["signed_decision"]
    assert isinstance(signed, dict)
    signed["test_count"] = int(signed["test_count"]) + 1
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _value(monkeypatch)
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
