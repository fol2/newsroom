from __future__ import annotations

import dataclasses

import pytest

from newsroom.authority import (
    BlobIdentity,
    DeletionState,
    HydrationPolicyContract,
    ObjectAdmissionRequest,
    ObjectLimitError,
    ObjectLimits,
    ObjectLivenessSnapshot,
    ObjectPolicyError,
    RightsPolicyContract,
)


def test_caller_admission_request_contains_no_authority_fields() -> None:
    fields = {field.name for field in dataclasses.fields(ObjectAdmissionRequest)}
    assert fields == {"admission_type", "idempotency_key"}
    assert {
        "principal_id",
        "authority_domain",
        "now",
        "rights_status",
        "allowed_use",
        "object_class",
        "security_scope",
        "retention_scope",
        "blob_digest",
        "size_bytes",
        "event_id",
    }.isdisjoint(fields)


def test_blob_identity_is_state_free_and_policy_free() -> None:
    fields = {field.name for field in dataclasses.fields(BlobIdentity)}
    assert fields == {"blob_digest", "size_bytes"}


def test_object_limits_are_immutable_and_bound_objects_and_ranges() -> None:
    source = {"source_capture": 512}
    limits = ObjectLimits(
        global_max_bytes=1024,
        class_max_bytes=source,
        max_read_bytes=256,
        min_free_bytes=128,
        io_chunk_bytes=64,
        max_staging_bytes=768,
        max_range_bytes=128,
    )
    source["source_capture"] = 999
    assert limits.maximum_for("source_capture") == 512
    with pytest.raises(TypeError):
        limits.class_max_bytes["source_capture"] = 1  # type: ignore[index]
    limits.require_object_size("source_capture", 512)
    with pytest.raises(ObjectLimitError):
        limits.require_object_size("source_capture", 513)
    limits.require_range(total_size=512, offset=0, length=128)
    with pytest.raises(ObjectLimitError):
        limits.require_range(total_size=512, offset=0, length=129)


def test_retained_policy_contracts_have_exact_identity() -> None:
    rights = RightsPolicyContract(
        policy_key="source-permitted",
        contract_version="rights-v1",
        implementation_version="rights-static-v1",
        preflight_allowed=True,
        reason_code="PERMITTED",
    )
    hydration = HydrationPolicyContract(
        policy_id="project-discovery-v1",
        contract_version="hydration-v1",
        implementation_version="hydration-static-v1",
        purpose="project.discovery",
        required_scope="authority.objects.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_authority_domains=frozenset({"newsroom.authority"}),
        allowed_object_classes=frozenset({"source_capture"}),
        allowed_uses=frozenset({"project.discovery"}),
        allowed_security_scopes=frozenset({"authority.protected"}),
        allowed_retention_scopes=frozenset({"source.short"}),
        max_bytes=256,
    )
    assert rights.contract_digest.startswith("sha256:")
    assert hydration.contract_digest.startswith("sha256:")
    changed = dataclasses.replace(rights, reason_code="OTHER")
    assert changed.contract_digest != rights.contract_digest
    with pytest.raises(ObjectPolicyError, match="frozenset"):
        dataclasses.replace(
            hydration,
            allowed_principal_ids={"principal.alpha"},  # type: ignore[arg-type]
        )


def test_server_computed_liveness_separates_gc_from_governed_deletion() -> None:
    assert ObjectLivenessSnapshot(0, 0, 0, 0, None).may_physically_remove
    assert not ObjectLivenessSnapshot(1, 0, 0, 0, None).may_physically_remove
    assert not ObjectLivenessSnapshot(
        0, 0, 0, 0, DeletionState.REQUESTED
    ).may_physically_remove
    assert not ObjectLivenessSnapshot(
        0, 0, 0, 0, DeletionState.FAILED
    ).may_physically_remove
    assert ObjectLivenessSnapshot(
        0, 0, 4, 0, DeletionState.TOMBSTONED
    ).may_physically_remove
    assert not ObjectLivenessSnapshot(
        0, 0, 4, 1, DeletionState.TOMBSTONED
    ).may_physically_remove
