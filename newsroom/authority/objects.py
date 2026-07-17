from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .canonical import digest_canonical, validate_sha256_digest
from .types import (
    AuthenticationContextId,
    AuthorizationDecisionId,
    EventId,
    ObjectAdmissionId,
    RightsDecisionId,
    UUIDv4Id,
    UtcTimestamp,
    require_scope,
    require_token,
)


class ObjectPolicyError(ValueError):
    """A governed-object policy or request is malformed."""


class ObjectAdmissionDenied(PermissionError):
    """Server-owned authorization or rights policy denies admission."""


class ObjectHydrationDenied(PermissionError):
    """Server-owned hydration policy denies byte access."""


class ObjectIntegrityError(RuntimeError):
    """Blob bytes do not match their immutable identity."""


class ObjectLimitError(ValueError):
    """A hard staging, object-class, read, or disk limit was exceeded."""


class ObjectLifecycleError(RuntimeError):
    """A lifecycle transition is inconsistent with authoritative state."""


@dataclass(frozen=True, slots=True)
class GovernedDeletionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ObjectAccessDecisionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryPinId(UUIDv4Id):
    pass


class BlobState(StrEnum):
    ACTIVE = "ACTIVE"
    DELETION_PENDING = "DELETION_PENDING"
    DELETED = "DELETED"
    FAILED = "FAILED"


class AdmissionState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    FAILED = "FAILED"


class DeletionState(StrEnum):
    REQUESTED = "REQUESTED"
    TOMBSTONED = "TOMBSTONED"
    PHYSICALLY_REMOVED = "PHYSICALLY_REMOVED"
    FAILED = "FAILED"


class ObjectLifecycleEventType(StrEnum):
    ADMISSION_ACTIVATED = "governed_object.admission.activated"
    ADMISSION_REVOKED = "governed_object.admission.revoked"
    DELETION_REQUESTED = "governed_blob.deletion.requested"
    DELETION_TOMBSTONED = "governed_blob.deletion.tombstoned"
    DELETION_COMPLETED = "governed_blob.deletion.completed"


@dataclass(frozen=True, slots=True)
class ObjectLimits:
    """Hard limits used by the future streaming CAS implementation.

    ``class_max_bytes`` is defensively copied into a read-only mapping so a
    caller cannot widen a composed policy after system startup.
    """

    global_max_bytes: int
    class_max_bytes: Mapping[str, int]
    max_read_bytes: int
    min_free_bytes: int = 0
    io_chunk_bytes: int = 64 * 1024
    max_staging_bytes: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "global_max_bytes",
            "max_read_bytes",
            "io_chunk_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ObjectLimitError(f"{field_name} must be positive")
        if (
            isinstance(self.min_free_bytes, bool)
            or not isinstance(self.min_free_bytes, int)
            or self.min_free_bytes < 0
        ):
            raise ObjectLimitError("min_free_bytes must be non-negative")
        if self.max_staging_bytes is not None and (
            isinstance(self.max_staging_bytes, bool)
            or not isinstance(self.max_staging_bytes, int)
            or self.max_staging_bytes <= 0
        ):
            raise ObjectLimitError("max_staging_bytes must be positive when set")
        if not isinstance(self.class_max_bytes, Mapping):
            raise ObjectLimitError("class_max_bytes must be a mapping")
        copied: dict[str, int] = {}
        for object_class, limit in self.class_max_bytes.items():
            require_token(object_class, field="object_class")
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise ObjectLimitError("object-class limits must be positive")
            if limit > self.global_max_bytes:
                raise ObjectLimitError(
                    "object-class limit cannot exceed global hard maximum"
                )
            copied[object_class] = limit
        if not copied:
            raise ObjectLimitError("at least one object-class limit is required")
        object.__setattr__(
            self,
            "class_max_bytes",
            MappingProxyType(dict(sorted(copied.items()))),
        )
        staging_limit = self.max_staging_bytes or self.global_max_bytes
        if staging_limit < max(copied.values()):
            raise ObjectLimitError(
                "staging maximum cannot be below an object-class maximum"
            )
        object.__setattr__(self, "max_staging_bytes", staging_limit)

    def maximum_for(self, object_class: str) -> int:
        require_token(object_class, field="object_class")
        try:
            return min(
                self.global_max_bytes,
                int(self.class_max_bytes[object_class]),
                int(self.max_staging_bytes),
            )
        except KeyError as exc:
            raise ObjectLimitError(
                f"no hard byte limit is configured for {object_class}"
            ) from exc

    def require_object_size(self, object_class: str, size_bytes: int) -> None:
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise ObjectLimitError("object size must be a non-negative integer")
        if size_bytes > self.maximum_for(object_class):
            raise ObjectLimitError("object exceeds its configured hard limit")

    def require_read_size(self, size_bytes: int) -> None:
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or size_bytes > self.max_read_bytes
        ):
            raise ObjectLimitError("read exceeds the configured hard limit")

    def canonical_value(self) -> dict[str, object]:
        return {
            "global_max_bytes": self.global_max_bytes,
            "class_max_bytes": dict(self.class_max_bytes),
            "max_read_bytes": self.max_read_bytes,
            "min_free_bytes": self.min_free_bytes,
            "io_chunk_bytes": self.io_chunk_bytes,
            "max_staging_bytes": self.max_staging_bytes,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ObjectAdmissionDefinition:
    """Versioned server-side semantics for one governed object use."""

    admission_type: str
    definition_version: str
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    required_write_scope: str
    required_read_scope: str
    required_manage_scope: str
    rights_policy_key: str

    def __post_init__(self) -> None:
        for field_name in (
            "admission_type",
            "definition_version",
            "object_class",
            "allowed_use",
            "rights_policy_key",
        ):
            require_token(getattr(self, field_name), field=field_name)
        for field_name in (
            "security_scope",
            "retention_scope",
            "required_write_scope",
            "required_read_scope",
            "required_manage_scope",
        ):
            require_scope(getattr(self, field_name), field=field_name)

    def canonical_value(self) -> dict[str, str]:
        return {
            "admission_type": self.admission_type,
            "definition_version": self.definition_version,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "required_write_scope": self.required_write_scope,
            "required_read_scope": self.required_read_scope,
            "required_manage_scope": self.required_manage_scope,
            "rights_policy_key": self.rights_policy_key,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ObjectAdmissionRequest:
    """Caller-minimal request with no rights, use, or scope authority."""

    admission_type: str
    idempotency_key: str

    def __post_init__(self) -> None:
        require_token(self.admission_type, field="admission_type")
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise ObjectPolicyError("idempotency_key must be non-empty")
        if len(self.idempotency_key.encode("utf-8")) > 256:
            raise ObjectPolicyError("idempotency_key exceeds 256 UTF-8 bytes")


@dataclass(frozen=True, slots=True)
class ImmutableBlobIdentity:
    blob_digest: str
    size_bytes: int
    state: BlobState = BlobState.ACTIVE

    def __post_init__(self) -> None:
        normalized = validate_sha256_digest(self.blob_digest, field="blob_digest")
        if normalized != self.blob_digest:
            raise ObjectIntegrityError("blob digest must be canonical lowercase")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ObjectIntegrityError("blob size must be a non-negative integer")
        if not isinstance(self.state, BlobState):
            raise ObjectLifecycleError("blob state must be typed")

    def canonical_value(self) -> dict[str, object]:
        return {
            "blob_digest": self.blob_digest,
            "size_bytes": self.size_bytes,
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class RightsDecision:
    rights_decision_id: RightsDecisionId
    authentication_context_id: AuthenticationContextId
    authorization_request_digest: str
    authorization_decision_id: AuthorizationDecisionId
    rights_request_digest: str
    policy_version: str
    admission_definition_digest: str
    blob_digest: str
    size_bytes: int
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    allowed: bool
    reason_code: str
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp | None
    decided_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.rights_decision_id, RightsDecisionId):
            raise ObjectPolicyError("rights decision identity must be typed")
        if not isinstance(self.authentication_context_id, AuthenticationContextId):
            raise ObjectPolicyError("authentication context identity must be typed")
        if not isinstance(self.authorization_decision_id, AuthorizationDecisionId):
            raise ObjectPolicyError("authorization decision identity must be typed")
        for field_name in (
            "authorization_request_digest",
            "rights_request_digest",
            "admission_definition_digest",
            "blob_digest",
        ):
            value = getattr(self, field_name)
            normalized = validate_sha256_digest(value, field=field_name)
            if normalized != value:
                raise ObjectPolicyError(f"{field_name} must be canonical lowercase")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ObjectPolicyError("rights decision size must be non-negative")
        for field_name in (
            "policy_version",
            "object_class",
            "allowed_use",
            "reason_code",
        ):
            require_token(getattr(self, field_name), field=field_name)
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        if not isinstance(self.allowed, bool):
            raise ObjectPolicyError("rights decision must carry a boolean result")
        for field_name in ("valid_from", "decided_at"):
            if not isinstance(getattr(self, field_name), UtcTimestamp):
                raise ObjectPolicyError(f"{field_name} must be typed UTC")
        if self.valid_until is not None:
            if not isinstance(self.valid_until, UtcTimestamp):
                raise ObjectPolicyError("valid_until must be typed UTC")
            if self.valid_until.value <= self.valid_from.value:
                raise ObjectPolicyError("rights validity must end after it starts")
        if self.decided_at.value < self.valid_from.value:
            raise ObjectPolicyError("rights decision cannot predate its validity")

    def canonical_value(self) -> dict[str, object]:
        return {
            "rights_decision_id": str(self.rights_decision_id),
            "authentication_context_id": str(self.authentication_context_id),
            "authorization_request_digest": self.authorization_request_digest,
            "authorization_decision_id": str(self.authorization_decision_id),
            "rights_request_digest": self.rights_request_digest,
            "policy_version": self.policy_version,
            "admission_definition_digest": self.admission_definition_digest,
            "blob_digest": self.blob_digest,
            "size_bytes": self.size_bytes,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "valid_from": self.valid_from.to_text(),
            "valid_until": (
                None if self.valid_until is None else self.valid_until.to_text()
            ),
            "decided_at": self.decided_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_current(self, now: UtcTimestamp) -> None:
        if not isinstance(now, UtcTimestamp):
            raise ObjectPolicyError("current rights time must be typed UTC")
        if not self.allowed:
            raise ObjectAdmissionDenied(self.reason_code)
        if now.value < self.valid_from.value:
            raise ObjectAdmissionDenied("RIGHTS_NOT_YET_VALID")
        if self.valid_until is not None and now.value >= self.valid_until.value:
            raise ObjectAdmissionDenied("RIGHTS_EXPIRED")


@dataclass(frozen=True, slots=True)
class ObjectAdmissionReceipt:
    admission_id: ObjectAdmissionId
    admission_type: str
    definition_version: str
    definition_digest: str
    blob: ImmutableBlobIdentity
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    rights_decision_id: RightsDecisionId
    rights_decision_digest: str
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp | None
    state: AdmissionState
    activation_event_id: EventId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise ObjectPolicyError("admission identity must be typed")
        if not isinstance(self.blob, ImmutableBlobIdentity):
            raise ObjectPolicyError("admission requires immutable blob identity")
        if not isinstance(self.rights_decision_id, RightsDecisionId):
            raise ObjectPolicyError("admission rights identity must be typed")
        for field_name in (
            "admission_type",
            "definition_version",
            "object_class",
            "allowed_use",
        ):
            require_token(getattr(self, field_name), field=field_name)
        for field_name in ("definition_digest", "rights_decision_digest"):
            value = getattr(self, field_name)
            if validate_sha256_digest(value, field=field_name) != value:
                raise ObjectPolicyError(f"{field_name} must be canonical lowercase")
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        if not isinstance(self.valid_from, UtcTimestamp):
            raise ObjectPolicyError("admission valid_from must be typed UTC")
        if self.valid_until is not None and not isinstance(self.valid_until, UtcTimestamp):
            raise ObjectPolicyError("admission valid_until must be typed UTC")
        if not isinstance(self.state, AdmissionState):
            raise ObjectPolicyError("admission state must be typed")
        if self.activation_event_id is not None and not isinstance(
            self.activation_event_id, EventId
        ):
            raise ObjectPolicyError("activation event identity must be typed")

    @property
    def active(self) -> bool:
        return self.state is AdmissionState.ACTIVE

    def require_current(self, now: UtcTimestamp) -> None:
        if self.state is not AdmissionState.ACTIVE:
            raise ObjectHydrationDenied("object admission is not active")
        if now.value < self.valid_from.value:
            raise ObjectHydrationDenied("object admission is not yet valid")
        if self.valid_until is not None and now.value >= self.valid_until.value:
            raise ObjectHydrationDenied("object admission has expired")
        if self.blob.state is not BlobState.ACTIVE:
            raise ObjectHydrationDenied("governed blob is not hydratable")


@dataclass(frozen=True, slots=True)
class HydrationPolicy:
    policy_id: str
    purpose: str
    required_scope: str
    allowed_principal_ids: frozenset[str]
    allowed_object_classes: frozenset[str]
    allowed_uses: frozenset[str]
    allowed_security_scopes: frozenset[str]
    max_bytes: int

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="hydration_policy_id")
        require_token(self.purpose, field="hydration_purpose")
        require_scope(self.required_scope, field="hydration_required_scope")
        for field_name in (
            "allowed_principal_ids",
            "allowed_object_classes",
            "allowed_uses",
            "allowed_security_scopes",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, frozenset) or not values:
                raise ObjectPolicyError(f"{field_name} must be a non-empty frozenset")
        for principal in self.allowed_principal_ids:
            require_token(principal, field="hydration_principal")
        for object_class in self.allowed_object_classes:
            require_token(object_class, field="hydration_object_class")
        for allowed_use in self.allowed_uses:
            require_token(allowed_use, field="hydration_allowed_use")
        for scope in self.allowed_security_scopes:
            require_scope(scope, field="hydration_security_scope")
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or self.max_bytes <= 0:
            raise ObjectPolicyError("hydration max_bytes must be positive")

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "purpose": self.purpose,
            "required_scope": self.required_scope,
            "allowed_principal_ids": sorted(self.allowed_principal_ids),
            "allowed_object_classes": sorted(self.allowed_object_classes),
            "allowed_uses": sorted(self.allowed_uses),
            "allowed_security_scopes": sorted(self.allowed_security_scopes),
            "max_bytes": self.max_bytes,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def authorize(
        self,
        *,
        principal_id: str,
        admission: ObjectAdmissionReceipt,
        requested_bytes: int,
        now: UtcTimestamp,
    ) -> ObjectAccessDecision:
        if principal_id not in self.allowed_principal_ids:
            raise ObjectHydrationDenied("principal is outside hydration policy")
        admission.require_current(now)
        if admission.object_class not in self.allowed_object_classes:
            raise ObjectHydrationDenied("object class is outside hydration policy")
        if admission.allowed_use not in self.allowed_uses:
            raise ObjectHydrationDenied("object use is outside hydration policy")
        if admission.security_scope not in self.allowed_security_scopes:
            raise ObjectHydrationDenied("security scope is outside hydration policy")
        if (
            isinstance(requested_bytes, bool)
            or not isinstance(requested_bytes, int)
            or requested_bytes < 0
            or requested_bytes > self.max_bytes
            or requested_bytes > admission.blob.size_bytes
        ):
            raise ObjectHydrationDenied("requested bytes exceed hydration policy")
        return ObjectAccessDecision(
            access_decision_id=ObjectAccessDecisionId.new(),
            policy_digest=self.digest,
            principal_id=principal_id,
            purpose=self.purpose,
            admission_id=admission.admission_id,
            allowed_use=admission.allowed_use,
            security_scope=admission.security_scope,
            allowed_bytes=requested_bytes,
            decided_at=now,
        )


@dataclass(frozen=True, slots=True)
class ObjectAccessDecision:
    access_decision_id: ObjectAccessDecisionId
    policy_digest: str
    principal_id: str
    purpose: str
    admission_id: ObjectAdmissionId
    allowed_use: str
    security_scope: str
    allowed_bytes: int
    decided_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.access_decision_id, ObjectAccessDecisionId):
            raise ObjectPolicyError("access decision identity must be typed")
        if validate_sha256_digest(self.policy_digest, field="policy_digest") != self.policy_digest:
            raise ObjectPolicyError("policy digest must be canonical lowercase")
        require_token(self.principal_id, field="principal_id")
        require_token(self.purpose, field="purpose")
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise ObjectPolicyError("access decision admission identity must be typed")
        require_token(self.allowed_use, field="allowed_use")
        require_scope(self.security_scope, field="security_scope")
        if isinstance(self.allowed_bytes, bool) or not isinstance(self.allowed_bytes, int) or self.allowed_bytes < 0:
            raise ObjectPolicyError("allowed bytes must be non-negative")
        if not isinstance(self.decided_at, UtcTimestamp):
            raise ObjectPolicyError("access decision time must be typed UTC")


@dataclass(frozen=True, slots=True)
class AdmissionRevocationReceipt:
    admission_id: ObjectAdmissionId
    reason_code: str
    revoked_at: UtcTimestamp
    event_id: EventId

    def __post_init__(self) -> None:
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise ObjectLifecycleError("revocation admission identity must be typed")
        require_token(self.reason_code, field="revocation_reason")
        if not isinstance(self.revoked_at, UtcTimestamp):
            raise ObjectLifecycleError("revocation time must be typed UTC")
        if not isinstance(self.event_id, EventId):
            raise ObjectLifecycleError("revocation event identity must be typed")


@dataclass(frozen=True, slots=True)
class GovernedDeletionReceipt:
    deletion_id: GovernedDeletionId
    blob_digest: str
    reason_code: str
    state: DeletionState
    requested_at: UtcTimestamp
    updated_at: UtcTimestamp
    event_id: EventId

    def __post_init__(self) -> None:
        if not isinstance(self.deletion_id, GovernedDeletionId):
            raise ObjectLifecycleError("deletion identity must be typed")
        if validate_sha256_digest(self.blob_digest, field="blob_digest") != self.blob_digest:
            raise ObjectLifecycleError("blob digest must be canonical lowercase")
        require_token(self.reason_code, field="deletion_reason")
        if not isinstance(self.state, DeletionState):
            raise ObjectLifecycleError("deletion state must be typed")
        if not isinstance(self.requested_at, UtcTimestamp) or not isinstance(
            self.updated_at, UtcTimestamp
        ):
            raise ObjectLifecycleError("deletion times must be typed UTC")
        if self.updated_at.value < self.requested_at.value:
            raise ObjectLifecycleError("deletion update cannot predate request")
        if not isinstance(self.event_id, EventId):
            raise ObjectLifecycleError("deletion event identity must be typed")


@dataclass(frozen=True, slots=True)
class RecoveryPinReceipt:
    pin_id: RecoveryPinId
    blob_digest: str
    reason_code: str
    created_at: UtcTimestamp
    released_at: UtcTimestamp | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.pin_id, RecoveryPinId):
            raise ObjectLifecycleError("recovery pin identity must be typed")
        if validate_sha256_digest(self.blob_digest, field="blob_digest") != self.blob_digest:
            raise ObjectLifecycleError("blob digest must be canonical lowercase")
        require_token(self.reason_code, field="recovery_pin_reason")
        if not isinstance(self.created_at, UtcTimestamp):
            raise ObjectLifecycleError("pin created_at must be typed UTC")
        if self.released_at is not None:
            if not isinstance(self.released_at, UtcTimestamp):
                raise ObjectLifecycleError("pin released_at must be typed UTC")
            if self.released_at.value < self.created_at.value:
                raise ObjectLifecycleError("pin release cannot predate creation")

    @property
    def active(self) -> bool:
        return self.released_at is None


@dataclass(frozen=True, slots=True)
class ObjectLivenessSnapshot:
    """Server-computed counts; never a caller-provided digest liveness set."""

    active_admissions: int
    pending_admissions: int
    authority_references: int
    active_recovery_pins: int
    deletion_state: DeletionState | None

    def __post_init__(self) -> None:
        for field_name in (
            "active_admissions",
            "pending_admissions",
            "authority_references",
            "active_recovery_pins",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ObjectLifecycleError(f"{field_name} must be non-negative")
        if self.deletion_state is not None and not isinstance(
            self.deletion_state, DeletionState
        ):
            raise ObjectLifecycleError("deletion state must be typed")

    @property
    def may_physically_remove(self) -> bool:
        if self.active_recovery_pins:
            return False
        if self.deletion_state in {
            DeletionState.TOMBSTONED,
            DeletionState.PHYSICALLY_REMOVED,
        }:
            return True
        return not (
            self.active_admissions
            or self.pending_admissions
            or self.authority_references
        )
