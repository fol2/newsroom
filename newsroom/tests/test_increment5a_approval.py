from __future__ import annotations

from copy import deepcopy
import inspect
import json
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
import newsroom.increment5.approval as approval_module
import newsroom.increment5.profiles as profiles_module
from newsroom.increment5 import (
    APPROVAL_ATTESTATION_SCHEMA_DIGEST,
    APPROVAL_ATTESTATION_SCHEMA_PATH,
    APPROVAL_NON_EFFECTS,
    APPROVAL_RECORD_DIGEST,
    APPROVAL_RECORD_PATH,
    INCREMENT5_TRACEABILITY_BY_REQUIREMENT,
    INCREMENT_5A_DECISION_AUTHORITY,
    INCREMENT_5A_DECISION_PACKET,
    Increment5ADecisionAuthority,
    Increment5ContractError,
    Increment5DeliveryTrace,
    Increment5ProfileError,
    PRODUCTION_PROFILE_SCHEMA,
    PRODUCTION_PROFILE_SCHEMA_DIGEST,
    PRODUCTION_PROFILE_SCHEMA_PATH,
    PROPOSAL_PRODUCTION_PROFILE_SCHEMA,
    PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST,
    PROPOSAL_PRODUCTION_PROFILE_SCHEMA_PATH,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH,
    RetrievalProfileKind,
    approval_attestation_value,
    build_production_qualification_manifest,
    decision_authority,
    expected_increment5a_owner_approval_body,
    load_increment5a_approval_attestation,
    repository_approval_record,
    validate_profile_manifest,
)


_COMMENT_ID = 123456789
_APPROVED_AT = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
_OWNER_BODY = expected_increment5a_owner_approval_body()
_OWNER_BODY_DIGEST = digest_bytes(_OWNER_BODY.encode("utf-8"))


def _approval_value() -> dict[str, object]:
    return approval_attestation_value(
        proposal=INCREMENT_5A_DECISION_PACKET,
        approved_at=_APPROVED_AT,
        comment_id=_COMMENT_ID,
        approval_comment_body_digest=_OWNER_BODY_DIGEST,
    )


def _write_approval(
    tmp_path: Path,
    value: dict[str, object],
) -> Path:
    path = tmp_path / "approval.json"
    path.write_bytes(canonical_json_bytes(value))
    return path


def test_approval_and_qualification_schema_artifacts_are_canonical() -> None:
    for path, expected_digest in (
        (
            APPROVAL_ATTESTATION_SCHEMA_PATH,
            APPROVAL_ATTESTATION_SCHEMA_DIGEST,
        ),
        (
            QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH,
            QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
        ),
    ):
        data = path.read_bytes()
        assert data == canonical_json_bytes(
            json.loads(data.decode("utf-8"))
        )
        assert digest_bytes(data) == expected_digest


def test_generic_production_schema_is_only_the_hardened_v2_surface() -> None:
    assert PRODUCTION_PROFILE_SCHEMA is QUALIFICATION_PRODUCTION_PROFILE_SCHEMA
    assert (
        PRODUCTION_PROFILE_SCHEMA_DIGEST
        == QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST
    )
    assert PRODUCTION_PROFILE_SCHEMA_PATH == (
        QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH
    )
    assert PRODUCTION_PROFILE_SCHEMA is not PROPOSAL_PRODUCTION_PROFILE_SCHEMA
    assert PRODUCTION_PROFILE_SCHEMA_DIGEST != (
        PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST
    )
    assert PRODUCTION_PROFILE_SCHEMA_PATH != (
        PROPOSAL_PRODUCTION_PROFILE_SCHEMA_PATH
    )
    rights = PRODUCTION_PROFILE_SCHEMA["properties"]["rights"]["properties"]
    assert rights["protected_content_allowed"] == {"const": False}


def test_pending_repository_record_is_fail_closed() -> None:
    assert APPROVAL_RECORD_DIGEST is None
    assert not APPROVAL_RECORD_PATH.exists()
    assert repository_approval_record() is None
    assert not INCREMENT_5A_DECISION_AUTHORITY.production_authorized
    assert decision_authority() is INCREMENT_5A_DECISION_AUTHORITY
    assert INCREMENT_5A_DECISION_AUTHORITY.proposal is INCREMENT_5A_DECISION_PACKET

    with pytest.raises(
        Increment5ProfileError,
        match="admitted repository owner approval record",
    ):
        INCREMENT_5A_DECISION_AUTHORITY.require_profile(
            RetrievalProfileKind.PRODUCTION
        )
    with pytest.raises(
        Increment5ProfileError,
        match="admitted repository owner approval record",
    ):
        build_production_qualification_manifest()


def test_parsed_external_record_is_evidence_not_runtime_authority(
    tmp_path: Path,
) -> None:
    record = load_increment5a_approval_attestation(
        _write_approval(tmp_path, _approval_value())
    )

    assert record.evidence.comment_id == _COMMENT_ID
    assert record.evidence.body_digest == _OWNER_BODY_DIGEST
    assert record.approved_at == _APPROVED_AT
    assert record.proposal_payload_digest == INCREMENT_5A_DECISION_PACKET.payload_digest
    assert repository_approval_record() is None
    with pytest.raises(
        Increment5ProfileError,
        match="admitted repository owner approval record",
    ):
        build_production_qualification_manifest()


def test_public_constant_or_loader_reassignment_cannot_admit_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_approval(tmp_path, _approval_value())
    digest = digest_bytes(path.read_bytes())
    record = load_increment5a_approval_attestation(path)

    monkeypatch.setattr(approval_module, "APPROVAL_RECORD_PATH", path)
    monkeypatch.setattr(approval_module, "APPROVAL_RECORD_DIGEST", digest)
    monkeypatch.setattr(
        approval_module,
        "_LOAD_REPOSITORY_APPROVAL",
        lambda: record,
    )
    monkeypatch.setattr(
        approval_module,
        "repository_approval_record",
        lambda: record,
    )
    monkeypatch.setattr(
        approval_module,
        "require_repository_approval_record",
        lambda: record,
    )
    monkeypatch.setattr(
        approval_module,
        "load_increment5a_approval_attestation",
        lambda _path: record,
    )
    monkeypatch.setattr(
        approval_module,
        "INCREMENT_5A_DECISION_AUTHORITY",
        Increment5ADecisionAuthority(),
    )
    monkeypatch.setattr(
        profiles_module,
        "_bind_repository_authority_once",
        lambda **_kwargs: None,
    )

    # Production gates retain their one-time source binding; replacing public
    # module attributes after import cannot substitute caller evidence.
    assert repository_approval_record() is None
    with pytest.raises(
        Increment5ProfileError,
        match="admitted repository owner approval record",
    ):
        build_production_qualification_manifest()
    with pytest.raises(
        Increment5ProfileError,
        match="admitted repository owner approval record",
    ):
        INCREMENT_5A_DECISION_AUTHORITY.require_profile(
            RetrievalProfileKind.PRODUCTION
        )


def test_caller_created_authority_objects_cannot_cross_profile_gate() -> None:
    forged = Increment5ADecisionAuthority()
    forged_via_object = object.__new__(Increment5ADecisionAuthority)

    for candidate in (forged, forged_via_object):
        assert candidate is not INCREMENT_5A_DECISION_AUTHORITY
        with pytest.raises(
            Increment5ProfileError,
            match="canonical repository authority",
        ):
            validate_profile_manifest(
                {
                    "profile": RetrievalProfileKind.PRODUCTION.value,
                },
                packet=candidate,
            )

    assert not hasattr(forged, "__dict__")
    assert Increment5ADecisionAuthority.__slots__ == ()
    with pytest.raises(AttributeError):
        object.__setattr__(forged, "approval", object())


def test_production_builder_accepts_no_caller_authority() -> None:
    assert tuple(
        inspect.signature(build_production_qualification_manifest).parameters
    ) == ()
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        build_production_qualification_manifest(  # type: ignore[call-arg]
            authority=object()
        )


def test_approval_module_has_no_runtime_transport_or_capability_minting() -> None:
    source = Path(approval_module.__file__).read_text(encoding="utf-8")

    assert "import requests" not in source
    assert "GitHubIssueCommentApprovalVerifier" not in source
    assert "GitHubApprovalComment" not in source
    assert "verify_increment5a_approval" not in source
    assert "object.__new__(Increment5ADecisionAuthority)" not in source
    assert "object.__setattr__(authority" not in source
    assert "_make_verified_approval" not in source
    assert "_verified_approval_factory" not in source
    assert tuple(inspect.signature(decision_authority).parameters) == ()


def test_owner_statement_and_non_effects_are_exact() -> None:
    assert _OWNER_BODY_DIGEST == (
        "sha256:600c6b43c645d8c26d234c7a29d325650ab164791cdde457ac96b55b1b99cacd"
    )
    assert tuple(APPROVAL_NON_EFFECTS) == (
        "CANARY",
        "EXTERNAL_EMBEDDING_API_CALLS",
        "LIVE_SOURCE_EXECUTION",
        "PROTECTED_CONTENT_VECTORS",
        "PROVIDER_SPENDING",
        "PUBLICATION",
        "PUBLIC_EFFECT",
        "PRODUCTION_ACTIVATION",
        "SHADOW",
    )


def test_approval_record_tampering_cannot_bind_another_proposal(
    tmp_path: Path,
) -> None:
    value = _approval_value()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    proposal["payload_digest"] = "sha256:" + "b" * 64

    with pytest.raises(
        Increment5ContractError,
        match="does not bind the exact proposal",
    ):
        load_increment5a_approval_attestation(
            _write_approval(tmp_path, value)
        )


def test_approval_record_cannot_drop_non_effects(tmp_path: Path) -> None:
    value = _approval_value()
    non_effects = value["non_effects"]
    assert isinstance(non_effects, list)
    non_effects.remove("PROTECTED_CONTENT_VECTORS")

    with pytest.raises(
        Increment5ContractError,
        match="schema validation failed",
    ):
        load_increment5a_approval_attestation(
            _write_approval(tmp_path, value)
        )


def test_approval_record_requires_canonical_utc_text(tmp_path: Path) -> None:
    value = _approval_value()
    value["approved_at"] = "2042-03-12T12:00:00Z"

    with pytest.raises(
        Increment5ContractError,
        match="canonical UTC text",
    ):
        load_increment5a_approval_attestation(
            _write_approval(tmp_path, value)
        )


def test_approval_record_rejects_wrong_comment_digest(tmp_path: Path) -> None:
    with pytest.raises(
        Increment5ContractError,
        match="differs from the exact owner statement",
    ):
        approval_attestation_value(
            proposal=INCREMENT_5A_DECISION_PACKET,
            approved_at=_APPROVED_AT,
            comment_id=_COMMENT_ID,
            approval_comment_body_digest="sha256:" + "a" * 64,
        )


def test_protected_content_cannot_be_enabled_in_effective_schema() -> None:
    schema = deepcopy(PRODUCTION_PROFILE_SCHEMA)
    rights = schema["properties"]["rights"]["properties"]
    assert rights["protected_content_allowed"] == {"const": False}


def test_completed_run_decision_ownership_and_rollback_remain_in_5e() -> None:
    for requirement in ("DEVAL-073", "DOPS-064", "DOPS-072"):
        row = INCREMENT5_TRACEABILITY_BY_REQUIREMENT[requirement]
        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
        assert row.delivery_issue == 254
