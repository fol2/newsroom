from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from newsroom.authority import (
    AdmissionState,
    BlobState,
    DeletionState,
    HydrationPolicy,
    ImmutableBlobIdentity,
    ObjectAdmissionDefinition,
    ObjectAdmissionId,
    ObjectAdmissionReceipt,
    ObjectAdmissionRequest,
    ObjectHydrationDenied,
    ObjectLimits,
    ObjectLimitError,
    ObjectLivenessSnapshot,
    ObjectPolicyError,
    RightsDecisionId,
    UtcTimestamp,
    digest_canonical,
)

from .authority_helpers import FIXED_NOW


BLOB_DIGEST = "sha256:" + "a" * 64


def definition(*, allowed_use: str = "project.discovery") -> ObjectAdmissionDefinition:
    return ObjectAdmissionDefinition(
        admission_type="source.capture",
        definition_version="admission-v1",
        object_class="source_capture",
        allowed_use=allowed_use,
        security_scope="authority.protected",
        retention_scope="source.short",
        required_write_scope="authority.objects.admit",
        required_read_scope="authority.objects.read",
        required_manage_scope="authority.objects.manage",
        rights_policy_key="source-permitted",
    )


def receipt(
    *,
    allowed_use: str = "project.discovery",
    state: AdmissionState = AdmissionState.ACTIVE,
    blob_state: BlobState = BlobState.ACTIVE,
    valid_until: UtcTimestamp | None = None,
) -> ObjectAdmissionReceipt:
    selected = definition(allowed_use=allowed_use)
    return ObjectAdmissionReceipt(
        admission_id=ObjectAdmissionId.new(),
        admission_type=selected.admission_type,
        definition_version=selected.definition_version,
        definition_digest=selected.digest,
        blob=ImmutableBlobIdentity(
            blob_digest=BLOB_DIGEST,
            size_bytes=128,
            state=blob_state,
        ),
        object_class=selected.object_class,
        allowed_use=selected.allowed_use,
        security_scope=selected.security_scope,
        retention_scope=selected.retention_scope,
        rights_decision_id=RightsDecisionId.new(),
        rights_decision_digest=digest_canonical({"rights": allowed_use}),
        valid_from=FIXED_NOW,
        valid_until=valid_until,
        state=state,
    )


def test_caller_admission_request_contains_no_authority_fields() -> None:
    fields = {field.name for field in dataclasses.fields(ObjectAdmissionRequest)}
    assert fields == {"admission_type", "idempotency_key"}
    prohibited = {
        "rights_status",
        "allowed",
        "allowed_use",
        "object_class",
        "security_scope",
        "retention_scope",
        "policy_version",
        "blob_digest",
        "size_bytes",
    }
    assert prohibited.isdisjoint(fields)


def test_server_definition_derives_use_and_scope_semantics() -> None:
    selected = definition()
    assert selected.object_class == "source_capture"
    assert selected.allowed_use == "project.discovery"
    assert selected.security_scope == "authority.protected"
    assert selected.retention_scope == "source.short"
    assert selected.required_write_scope == "authority.objects.admit"
    assert selected.digest.startswith("sha256:")


def test_blob_identity_contains_no_universal_rights_or_use_metadata() -> None:
    fields = {field.name for field in dataclasses.fields(ImmutableBlobIdentity)}
    assert fields == {"blob_digest", "size_bytes", "state"}
    assert "rights_status" not in fields
    assert "allowed_use" not in fields
    assert "security_scope" not in fields
    assert "retention_scope" not in fields


def test_object_limits_are_defensively_copied_and_hard_bounded() -> None:
    source = {"source_capture": 512}
    limits = ObjectLimits(
        global_max_bytes=1024,
        class_max_bytes=source,
        max_read_bytes=256,
        min_free_bytes=128,
        io_chunk_bytes=64,
        max_staging_bytes=768,
    )
    source["source_capture"] = 999
    assert limits.maximum_for("source_capture") == 512
    with pytest.raises(TypeError):
        limits.class_max_bytes["source_capture"] = 1  # type: ignore[index]
    limits.require_object_size("source_capture", 512)
    with pytest.raises(ObjectLimitError):
        limits.require_object_size("source_capture", 513)
    limits.require_read_size(256)
    with pytest.raises(ObjectLimitError):
        limits.require_read_size(257)
    with pytest.raises(ObjectLimitError, match="configured"):
        limits.maximum_for("unknown_class")


def test_hydration_policy_is_deeply_immutable() -> None:
    base = {
        "policy_id": "hydration-v1",
        "purpose": "projector.structural",
        "required_scope": "authority.objects.read",
        "allowed_principal_ids": frozenset({"projector.structural"}),
        "allowed_object_classes": frozenset({"source_capture"}),
        "allowed_uses": frozenset({"project.discovery"}),
        "allowed_security_scopes": frozenset({"authority.protected"}),
        "max_bytes": 256,
    }
    HydrationPolicy(**base)
    for field_name in (
        "allowed_principal_ids",
        "allowed_object_classes",
        "allowed_uses",
        "allowed_security_scopes",
    ):
        changed = dict(base)
        changed[field_name] = set(changed[field_name])
        with pytest.raises(ObjectPolicyError, match="frozenset"):
            HydrationPolicy(**changed)  # type: ignore[arg-type]


def test_hydration_policy_enforces_principal_use_scope_state_and_size() -> None:
    policy = HydrationPolicy(
        policy_id="hydration-v1",
        purpose="projector.structural",
        required_scope="authority.objects.read",
        allowed_principal_ids=frozenset({"projector.structural"}),
        allowed_object_classes=frozenset({"source_capture"}),
        allowed_uses=frozenset({"project.discovery"}),
        allowed_security_scopes=frozenset({"authority.protected"}),
        max_bytes=64,
    )
    active = receipt()
    decision = policy.authorize(
        principal_id="projector.structural",
        admission=active,
        requested_bytes=64,
        now=FIXED_NOW,
    )
    assert decision.admission_id == active.admission_id
    assert decision.allowed_bytes == 64
    assert decision.purpose == "projector.structural"

    with pytest.raises(ObjectHydrationDenied, match="principal"):
        policy.authorize(
            principal_id="other.principal",
            admission=active,
            requested_bytes=1,
            now=FIXED_NOW,
        )
    with pytest.raises(ObjectHydrationDenied, match="requested"):
        policy.authorize(
            principal_id="projector.structural",
            admission=active,
            requested_bytes=65,
            now=FIXED_NOW,
        )
    with pytest.raises(ObjectHydrationDenied, match="not active"):
        policy.authorize(
            principal_id="projector.structural",
            admission=receipt(state=AdmissionState.REVOKED),
            requested_bytes=1,
            now=FIXED_NOW,
        )
    with pytest.raises(ObjectHydrationDenied, match="not hydratable"):
        policy.authorize(
            principal_id="projector.structural",
            admission=receipt(blob_state=BlobState.DELETION_PENDING),
            requested_bytes=1,
            now=FIXED_NOW,
        )
    expired = receipt(
        valid_until=UtcTimestamp(FIXED_NOW.value + timedelta(seconds=1))
    )
    with pytest.raises(ObjectHydrationDenied, match="expired"):
        policy.authorize(
            principal_id="projector.structural",
            admission=expired,
            requested_bytes=1,
            now=UtcTimestamp(FIXED_NOW.value + timedelta(seconds=1)),
        )


def test_server_computed_liveness_controls_physical_removal() -> None:
    referenced = ObjectLivenessSnapshot(
        active_admissions=1,
        pending_admissions=0,
        authority_references=4,
        active_recovery_pins=0,
        deletion_state=None,
    )
    assert not referenced.may_physically_remove

    ordinary_orphan = ObjectLivenessSnapshot(
        active_admissions=0,
        pending_admissions=0,
        authority_references=0,
        active_recovery_pins=0,
        deletion_state=None,
    )
    assert ordinary_orphan.may_physically_remove

    tombstoned_referenced = ObjectLivenessSnapshot(
        active_admissions=0,
        pending_admissions=0,
        authority_references=4,
        active_recovery_pins=0,
        deletion_state=DeletionState.TOMBSTONED,
    )
    assert tombstoned_referenced.may_physically_remove

    pinned_tombstone = ObjectLivenessSnapshot(
        active_admissions=0,
        pending_admissions=0,
        authority_references=4,
        active_recovery_pins=1,
        deletion_state=DeletionState.TOMBSTONED,
    )
    assert not pinned_tombstone.may_physically_remove
