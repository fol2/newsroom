from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.increment5 import (
    APPROVAL_ATTESTATION_SCHEMA_DIGEST,
    APPROVAL_ATTESTATION_SCHEMA_PATH,
    APPROVAL_NON_EFFECTS,
    INCREMENT5_TRACEABILITY_BY_REQUIREMENT,
    INCREMENT_5A_DECISION_AUTHORITY,
    INCREMENT_5A_DECISION_PACKET,
    Increment5ContractError,
    Increment5DeliveryTrace,
    Increment5ProfileError,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH,
    RetrievalProfileKind,
    approval_attestation_value,
    build_production_qualification_manifest,
    decision_authority,
    load_increment5a_approval_attestation,
    validate_profile_manifest,
)


def _approval_value() -> dict[str, object]:
    return approval_attestation_value(
        proposal=INCREMENT_5A_DECISION_PACKET,
        approved_at=UtcTimestamp.parse(
            "2042-03-12T12:00:00.000000Z"
        ),
        comment_id=123456789,
        approval_comment_body_digest=(
            "sha256:"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
    )


def _write_approval(
    tmp_path: Path,
    value: dict[str, object],
) -> Path:
    path = tmp_path / "approval.json"
    path.write_bytes(canonical_json_bytes(value))
    return path


def _approved_authority(tmp_path: Path):
    approval = load_increment5a_approval_attestation(
        _write_approval(tmp_path, _approval_value())
    )
    return decision_authority(approval=approval)


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


def test_pending_proposal_remains_immutable_and_non_authorizing() -> None:
    assert not INCREMENT_5A_DECISION_AUTHORITY.production_authorized
    assert (
        INCREMENT_5A_DECISION_AUTHORITY.proposal
        is INCREMENT_5A_DECISION_PACKET
    )
    with pytest.raises(
        Increment5ProfileError,
        match="PRODUCTION is not authorized",
    ):
        INCREMENT_5A_DECISION_AUTHORITY.require_profile(
            RetrievalProfileKind.PRODUCTION
        )


def test_historical_proposal_schema_has_no_generic_public_validator() -> None:
    import newsroom.increment5 as increment5
    import newsroom.increment5.profiles as profiles

    assert not hasattr(increment5, "PRODUCTION_PROFILE_SCHEMA")
    assert not hasattr(increment5, "PRODUCTION_PROFILE_SCHEMA_ID")
    assert not hasattr(increment5, "PRODUCTION_PROFILE_SCHEMA_VERSION")
    assert not hasattr(profiles, "PRODUCTION_PROFILE_SCHEMA")
    assert not hasattr(profiles, "PRODUCTION_PROFILE_SCHEMA_ID")
    assert not hasattr(profiles, "PRODUCTION_PROFILE_SCHEMA_VERSION")
    assert increment5.PRODUCTION_PROFILE_SCHEMA_DIGEST == (
        increment5.PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST
    )
    assert increment5.PRODUCTION_PROFILE_SCHEMA_PATH == (
        increment5.PROPOSAL_PRODUCTION_PROFILE_SCHEMA_PATH
    )


def test_separate_attestation_authorizes_exact_proposal_without_mutation(
    tmp_path: Path,
) -> None:
    authority = _approved_authority(tmp_path)

    assert authority.production_authorized
    assert authority.proposal is INCREMENT_5A_DECISION_PACKET
    assert authority.proposal.status.value == "PENDING_OWNER_REVIEW"
    assert authority.approval is not None
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
    authority.require_profile(RetrievalProfileKind.PRODUCTION)


def test_production_manifest_requires_attestation_and_denies_protected_content(
    tmp_path: Path,
) -> None:
    authority = _approved_authority(tmp_path)
    manifest = build_production_qualification_manifest(
        authority=authority
    )
    validated = validate_profile_manifest(
        manifest,
        packet=authority,
    )

    assert validated.profile is RetrievalProfileKind.PRODUCTION
    assert validated.qualification_eligible
    assert validated.approval_attestation_digest == (
        authority.approval_attestation_digest
    )
    assert manifest["rights"]["protected_content_allowed"] is False

    tampered = deepcopy(manifest)
    tampered["rights"]["protected_content_allowed"] = True
    with pytest.raises(
        Increment5ProfileError,
        match="schema validation failed",
    ):
        validate_profile_manifest(tampered, packet=authority)


def test_production_manifest_cannot_use_bare_pending_proposal(
    tmp_path: Path,
) -> None:
    authority = _approved_authority(tmp_path)
    manifest = build_production_qualification_manifest(
        authority=authority
    )
    with pytest.raises(
        Increment5ProfileError,
        match="owner approval authority",
    ):
        validate_profile_manifest(
            manifest,
            packet=INCREMENT_5A_DECISION_PACKET,
        )


def test_attestation_tampering_cannot_approve_another_proposal(
    tmp_path: Path,
) -> None:
    value = _approval_value()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    proposal["payload_digest"] = (
        "sha256:"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )
    with pytest.raises(
        Increment5ContractError,
        match="does not bind the exact proposal",
    ):
        load_increment5a_approval_attestation(
            _write_approval(tmp_path, value)
        )


def test_attestation_cannot_drop_non_effects(
    tmp_path: Path,
) -> None:
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


def test_dops_072_remains_deferred_to_5e_qualification() -> None:
    row = INCREMENT5_TRACEABILITY_BY_REQUIREMENT["DOPS-072"]
    assert (
        row.delivery_trace
        is Increment5DeliveryTrace.DEFERRED_TO_5E
    )
    assert row.delivery_issue == 254
