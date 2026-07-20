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
    """A governed-object contract or request is malformed."""


class ObjectAdmissionDenied(PermissionError):
    """Current authentication, authorisation, or rights policy denies admission."""


class ObjectHydrationDenied(PermissionError):
    """Current authority does not permit governed-byte hydration."""


class ObjectIntegrityError(RuntimeError):
    """Object bytes do not match their immutable content identity."""


class ObjectLimitError(ValueError):
    """A hard staging, object-class, read, range, or disk limit was exceeded."""


class ObjectLifecycleError(RuntimeError):
    """A lifecycle transition is inconsistent with authoritative current state."""


@dataclass(frozen=True, slots=True)
class ObjectPreflightId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ObjectOperationId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class GovernedDeletionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ObjectAccessDecisionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryPinId(UUIDv4Id):
    pass


class BlobLifecycleState(StrEnum):
    STAGING = "STAGING"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    DELETION_PENDING = "DELETION_PENDING"
    DELETED = "DELETED"
    FAILED = "FAILED"


# Compatibility name retained for callers of the initial Draft contract.  State
# no longer lives on BlobIdentity; it belongs to BlobLifecycleView/SQLite.
BlobState = BlobLifecycleState


class BlobIntegrityState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    MISSING = "MISSING"
    CORRUPT = "CORRUPT"


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


class RecoveryPinState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ObjectLifecycleEventType(StrEnum):
    ADMISSION_ACTIVATED = "governed_object.admission.activated"
    ADMISSION_REVOKED = "governed_object.admission.revoked"
    DELETION_REQUESTED = "governed_blob.deletion.requested"
    DELETION_TOMBSTONED = "governed_blob.deletion.tombstoned"
    DELETION_COMPLETED = "governed_blob.deletion.completed"
    DELETION_FAILED = "governed_blob.deletion.failed"
    RECOVERY_PIN_CREATED = "governed_blob.recovery_pin.created"
    RECOVERY_PIN_RELEASED = "governed_blob.recovery_pin.released"
    ORPHAN_REMOVED = "governed_blob.orphan.removed"


@dataclass(frozen=True, slots=True)
class ObjectLimits:
    """Immutable hard limits for streaming CAS and hydration.

    ``class_max_bytes`` is defensively copied into a read-only mapping.  These
    values are technical safety limits, not rights authority.
    """

    global_max_bytes: int
    class_max_bytes: Mapping[str, int]
    max_read_bytes: int
    min_free_bytes: int = 0
    io_chunk_bytes: int = 64 * 1024
    max_staging_bytes: int | None = None
    max_range_bytes: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("global_max_bytes", "max_read_bytes", "io_chunk_bytes"):
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
        if self.max_range_bytes is not None and (
            isinstance(self.max_range_bytes, bool)
            or not isinstance(self.max_range_bytes, int)
            or self.max_range_bytes <= 0
        ):
            raise ObjectLimitError("max_range_bytes must be positive when set")
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
        range_limit = self.max_range_bytes or self.max_read_bytes
        if range_limit > self.max_read_bytes:
            raise ObjectLimitError("range maximum cannot exceed read maximum")
        object.__setattr__(self, "max_range_bytes", range_limit)

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
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
        ):
            raise ObjectLimitError("object size must be a non-negative integer")
        if size_bytes > self.maximum_for(object_class):
            raise ObjectLimitError("object exceeds its configured hard limit")

    def require_range(self, *, total_size: int, offset: int, length: int) -> None:
        for field_name, value in (("total_size", total_size), ("offset", offset), ("length", length)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ObjectLimitError(f"{field_name} must be a non-negative integer")
        if offset > total_size or length > total_size - offset:
            raise ObjectLimitError("requested range exceeds object size")
        if length > self.max_read_bytes or length > int(self.max_range_bytes):
            raise ObjectLimitError("requested range exceeds configured read limits")

    def canonical_value(self) -> dict[str, object]:
        return {
            "global_max_bytes": self.global_max_bytes,
            "class_max_bytes": dict(self.class_max_bytes),
            "max_read_bytes": self.max_read_bytes,
            "min_free_bytes": self.min_free_bytes,
            "io_chunk_bytes": self.io_chunk_bytes,
            "max_staging_bytes": self.max_staging_bytes,
            "max_range_bytes": self.max_range_bytes,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class RightsPolicyContract:
    """Exact retained deterministic rights-policy identity for Increment 1A2b."""

    policy_key: str
    contract_version: str
    implementation_version: str
    preflight_allowed: bool
    reason_code: str
    valid_from_delay_seconds: int = 0
    validity_seconds: int | None = None
    preflight_ttl_seconds: int = 60

    def __post_init__(self) -> None:
        for field_name in (
            "policy_key",
            "contract_version",
            "implementation_version",
            "reason_code",
        ):
            require_token(getattr(self, field_name), field=field_name)
        if not isinstance(self.preflight_allowed, bool):
            raise ObjectPolicyError("rights preflight result must be boolean")
        for field_name in ("valid_from_delay_seconds", "preflight_ttl_seconds"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ObjectPolicyError(f"{field_name} must be non-negative")
        if self.preflight_ttl_seconds <= 0:
            raise ObjectPolicyError("preflight_ttl_seconds must be positive")
        if self.validity_seconds is not None and (
            isinstance(self.validity_seconds, bool)
            or not isinstance(self.validity_seconds, int)
            or self.validity_seconds <= 0
        ):
            raise ObjectPolicyError(
                "rights validity_seconds must be positive when set"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_key": self.policy_key,
            "contract_version": self.contract_version,
            "implementation_version": self.implementation_version,
            "preflight_allowed": self.preflight_allowed,
            "reason_code": self.reason_code,
            "valid_from_delay_seconds": self.valid_from_delay_seconds,
            "validity_seconds": self.validity_seconds,
            "preflight_ttl_seconds": self.preflight_ttl_seconds,
        }

    @property
    def contract_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class HydrationPolicyContract:
    """Exact retained purpose-bound byte access policy."""

    policy_id: str
    contract_version: str
    implementation_version: str
    purpose: str
    required_scope: str
    allowed_principal_ids: frozenset[str]
    allowed_authority_domains: frozenset[str]
    allowed_object_classes: frozenset[str]
    allowed_uses: frozenset[str]
    allowed_security_scopes: frozenset[str]
    allowed_retention_scopes: frozenset[str]
    max_bytes: int
    allow_ranges: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "policy_id",
            "contract_version",
            "implementation_version",
            "purpose",
        ):
            require_token(getattr(self, field_name), field=field_name)
        require_scope(self.required_scope, field="hydration_required_scope")
        token_sets = (
            "allowed_principal_ids",
            "allowed_authority_domains",
            "allowed_object_classes",
            "allowed_uses",
        )
        scope_sets = (
            "allowed_security_scopes",
            "allowed_retention_scopes",
        )
        for field_name in (*token_sets, *scope_sets):
            values = getattr(self, field_name)
            if not isinstance(values, frozenset) or not values:
                raise ObjectPolicyError(f"{field_name} must be a non-empty frozenset")
        for field_name in token_sets:
            for value in getattr(self, field_name):
                require_token(value, field=field_name)
        for field_name in scope_sets:
            for value in getattr(self, field_name):
                require_scope(value, field=field_name)
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or self.max_bytes <= 0:
            raise ObjectPolicyError("hydration max_bytes must be positive")
        if not isinstance(self.allow_ranges, bool):
            raise ObjectPolicyError("allow_ranges must be boolean")

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "contract_version": self.contract_version,
            "implementation_version": self.implementation_version,
            "purpose": self.purpose,
            "required_scope": self.required_scope,
            "allowed_principal_ids": sorted(self.allowed_principal_ids),
            "allowed_authority_domains": sorted(self.allowed_authority_domains),
            "allowed_object_classes": sorted(self.allowed_object_classes),
            "allowed_uses": sorted(self.allowed_uses),
            "allowed_security_scopes": sorted(self.allowed_security_scopes),
            "allowed_retention_scopes": sorted(self.allowed_retention_scopes),
            "max_bytes": self.max_bytes,
            "allow_ranges": self.allow_ranges,
        }

    @property
    def contract_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ObjectAdmissionDefinition:
    """Versioned server semantics bound to exact rights/hydration contracts."""

    admission_type: str
    definition_version: str
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    required_write_scope: str
    required_read_scope: str
    required_manage_scope: str
    rights_policy_contract_digest: str
    hydration_policy_contract_digests: frozenset[str]

    def __post_init__(self) -> None:
        for field_name in (
            "admission_type",
            "definition_version",
            "object_class",
            "allowed_use",
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
        if validate_sha256_digest(
            self.rights_policy_contract_digest,
            field="rights_policy_contract_digest",
        ) != self.rights_policy_contract_digest:
            raise ObjectPolicyError("rights policy digest must be canonical lowercase")
        if not isinstance(self.hydration_policy_contract_digests, frozenset) or not self.hydration_policy_contract_digests:
            raise ObjectPolicyError("admission requires hydration policy contracts")
        for digest in self.hydration_policy_contract_digests:
            if validate_sha256_digest(
                digest, field="hydration_policy_contract_digest"
            ) != digest:
                raise ObjectPolicyError("hydration policy digest must be canonical")

    def canonical_value(self) -> dict[str, object]:
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
            "rights_policy_contract_digest": (
                self.rights_policy_contract_digest
            ),
            "hydration_policy_contract_digests": sorted(
                self.hydration_policy_contract_digests
            ),
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


# Preferred name: immutable identity contains no lifecycle state.
@dataclass(frozen=True, slots=True)
class BlobIdentity:
    blob_digest: str
    size_bytes: int

    def __post_init__(self) -> None:
        normalized = validate_sha256_digest(self.blob_digest, field="blob_digest")
        if normalized != self.blob_digest:
            raise ObjectIntegrityError("blob digest must be canonical lowercase")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ObjectIntegrityError("blob size must be a non-negative integer")

    def canonical_value(self) -> dict[str, object]:
        return {
            "blob_digest": self.blob_digest,
            "size_bytes": self.size_bytes,
        }


# Backward-compatible alias, now correctly state-free.
ImmutableBlobIdentity = BlobIdentity


@dataclass(frozen=True, slots=True)
class BlobLifecycleView:
    """Non-authoritative snapshot; callers must re-resolve current state."""

    blob: BlobIdentity
    lifecycle_version: int
    state: BlobLifecycleState
    integrity_state: BlobIntegrityState
    recorded_at: UtcTimestamp
    event_id: EventId | None

    def __post_init__(self) -> None:
        if not isinstance(self.blob, BlobIdentity):
            raise ObjectLifecycleError("blob lifecycle view requires identity")
        if isinstance(self.lifecycle_version, bool) or not isinstance(
            self.lifecycle_version, int
        ) or self.lifecycle_version <= 0:
            raise ObjectLifecycleError("blob lifecycle version must be positive")
        if not isinstance(self.state, BlobLifecycleState) or not isinstance(
            self.integrity_state, BlobIntegrityState
        ):
            raise ObjectLifecycleError("blob lifecycle values must be typed")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise ObjectLifecycleError("blob lifecycle time must be typed")
        if self.event_id is not None and not isinstance(self.event_id, EventId):
            raise ObjectLifecycleError("blob lifecycle event must be typed")


@dataclass(frozen=True, slots=True)
class RightsDecisionView:
    """Immutable persisted decision view; only SQLite allocates its identity."""

    rights_decision_id: RightsDecisionId
    authentication_context_id: AuthenticationContextId
    authorization_request_digest: str
    authorization_decision_id: AuthorizationDecisionId
    rights_request_digest: str
    policy_contract_digest: str
    admission_definition_digest: str
    blob: BlobIdentity
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    allowed: bool
    reason_code: str
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp | None
    decided_at: UtcTimestamp
    canonical_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "authorization_request_digest",
            "rights_request_digest",
            "policy_contract_digest",
            "admission_definition_digest",
            "canonical_digest",
        ):
            value = getattr(self, field_name)
            normalized = validate_sha256_digest(value, field=field_name)
            if normalized != value:
                raise ObjectPolicyError(f"{field_name} must be canonical lowercase")
        if not isinstance(self.blob, BlobIdentity):
            raise ObjectPolicyError("rights view requires blob identity")
        for field_name in ("object_class", "allowed_use", "reason_code"):
            require_token(getattr(self, field_name), field=field_name)
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        if not isinstance(self.allowed, bool):
            raise ObjectPolicyError("rights decision must carry a boolean result")
        if self.decided_at.value > self.valid_from.value:
            raise ObjectPolicyError("rights invariant requires decided_at <= valid_from")
        if self.valid_until is not None and self.valid_until.value <= self.valid_from.value:
            raise ObjectPolicyError("rights invariant requires valid_from < valid_until")


@dataclass(frozen=True, slots=True)
class ObjectAdmissionView:
    """Non-authoritative admission snapshot allocated by the SQLite writer."""

    admission_id: ObjectAdmissionId
    admission_type: str
    definition_version: str
    definition_digest: str
    blob: BlobIdentity
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    rights_decision_id: RightsDecisionId
    rights_decision_digest: str
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp | None
    lifecycle_version: int
    state: AdmissionState
    activation_event_id: EventId | None

    def __post_init__(self) -> None:
        if not isinstance(self.blob, BlobIdentity):
            raise ObjectPolicyError("admission requires immutable blob identity")
        for field_name in ("admission_type", "definition_version", "object_class", "allowed_use"):
            require_token(getattr(self, field_name), field=field_name)
        for field_name in ("definition_digest", "rights_decision_digest"):
            value = getattr(self, field_name)
            if validate_sha256_digest(value, field=field_name) != value:
                raise ObjectPolicyError(f"{field_name} must be canonical lowercase")
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        if self.valid_until is not None and self.valid_until.value <= self.valid_from.value:
            raise ObjectPolicyError("admission validity must end after it starts")
        if isinstance(self.lifecycle_version, bool) or not isinstance(
            self.lifecycle_version, int
        ) or self.lifecycle_version <= 0:
            raise ObjectLifecycleError("admission lifecycle version must be positive")
        if self.state is AdmissionState.ACTIVE and self.activation_event_id is None:
            raise ObjectLifecycleError(
                "ACTIVE admission requires committed activation-event identity"
            )

    @property
    def active(self) -> bool:
        return self.state is AdmissionState.ACTIVE


# Compatibility alias: still a non-authoritative view.
ObjectAdmissionReceipt = ObjectAdmissionView


@dataclass(frozen=True, slots=True)
class HydrationRequest:
    admission_id: ObjectAdmissionId
    purpose: str
    offset: int = 0
    length: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise ObjectPolicyError("hydration request requires admission identity")
        require_token(self.purpose, field="hydration_purpose")
        if isinstance(self.offset, bool) or not isinstance(self.offset, int) or self.offset < 0:
            raise ObjectPolicyError("hydration offset must be non-negative")
        if self.length is not None and (
            isinstance(self.length, bool)
            or not isinstance(self.length, int)
            or self.length < 0
        ):
            raise ObjectPolicyError("hydration length must be non-negative")



@dataclass(frozen=True, slots=True)
class ObjectAccessDecisionView:
    access_decision_id: ObjectAccessDecisionId
    policy_contract_digest: str
    authentication_context_id: AuthenticationContextId
    authorization_request_digest: str
    authorization_decision_id: AuthorizationDecisionId
    principal_id: str
    authority_domain: str
    purpose: str
    admission_id: ObjectAdmissionId
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    offset: int
    allowed_bytes: int
    state_cutoff_digest: str
    decided_at: UtcTimestamp
    canonical_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "policy_contract_digest",
            "authorization_request_digest",
            "state_cutoff_digest",
            "canonical_digest",
        ):
            if validate_sha256_digest(
                getattr(self, field_name), field=field_name
            ) != getattr(self, field_name):
                raise ObjectPolicyError(f"{field_name} must be canonical")
        require_token(self.principal_id, field="principal_id")
        require_token(self.authority_domain, field="authority_domain")
        require_token(self.purpose, field="purpose")
        require_token(self.object_class, field="object_class")
        require_token(self.allowed_use, field="allowed_use")
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        for field_name in ("offset", "allowed_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ObjectPolicyError(f"{field_name} must be non-negative")


# Compatibility alias for persisted non-authoritative view only.
ObjectAccessDecision = ObjectAccessDecisionView


@dataclass(frozen=True, slots=True)
class AdmissionRevocationView:
    admission_id: ObjectAdmissionId
    lifecycle_version: int
    reason_code: str
    revoked_at: UtcTimestamp
    event_id: EventId

    def __post_init__(self) -> None:
        require_token(self.reason_code, field="revocation_reason")
        if self.lifecycle_version <= 0:
            raise ObjectLifecycleError("revocation lifecycle version must be positive")


@dataclass(frozen=True, slots=True)
class GovernedDeletionView:
    deletion_id: GovernedDeletionId
    blob: BlobIdentity
    reason_code: str
    lifecycle_version: int
    state: DeletionState
    requested_at: UtcTimestamp
    updated_at: UtcTimestamp
    event_id: EventId

    def __post_init__(self) -> None:
        require_token(self.reason_code, field="deletion_reason")
        if self.lifecycle_version <= 0:
            raise ObjectLifecycleError("deletion lifecycle version must be positive")
        if self.updated_at.value < self.requested_at.value:
            raise ObjectLifecycleError("deletion update cannot predate request")


@dataclass(frozen=True, slots=True)
class RecoveryPinView:
    pin_id: RecoveryPinId
    blob: BlobIdentity
    reason_code: str
    lifecycle_version: int
    state: RecoveryPinState
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    event_id: EventId

    def __post_init__(self) -> None:
        require_token(self.reason_code, field="recovery_pin_reason")
        if self.lifecycle_version <= 0:
            raise ObjectLifecycleError("pin lifecycle version must be positive")
        if self.updated_at.value < self.created_at.value:
            raise ObjectLifecycleError("pin update cannot predate creation")

    @property
    def active(self) -> bool:
        return self.state is RecoveryPinState.ACTIVE


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
        if self.deletion_state is DeletionState.TOMBSTONED:
            return True
        if self.deletion_state is DeletionState.PHYSICALLY_REMOVED:
            return True
        if self.deletion_state in {
            DeletionState.REQUESTED,
            DeletionState.FAILED,
        }:
            return False
        # Ordinary orphan GC is a separate no-deletion workflow.
        return self.deletion_state is None and not (
            self.active_admissions
            or self.pending_admissions
            or self.authority_references
        )


# Compatibility view names; none is current authority.
RightsDecision = RightsDecisionView
AdmissionRevocationReceipt = AdmissionRevocationView
GovernedDeletionReceipt = GovernedDeletionView
RecoveryPinReceipt = RecoveryPinView


__all__ = [name for name in globals() if not name.startswith("_")]
