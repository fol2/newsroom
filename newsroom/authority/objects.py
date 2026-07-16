from __future__ import annotations

from collections.abc import BinaryIO, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from .types import (
    ObjectAdmissionId,
    RightsDecisionId,
    UtcTimestamp,
    require_scope,
    require_token,
)


class ObjectPolicyError(ValueError):
    pass


class ObjectAdmissionDenied(PermissionError):
    pass


class ObjectIntegrityError(RuntimeError):
    pass


class ObjectLimitError(ValueError):
    pass


class ObjectLifecycleError(RuntimeError):
    pass


class ObjectHydrationDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectLimits:
    global_max_bytes: int
    class_max_bytes: Mapping[str, int]
    max_read_bytes: int
    min_free_bytes: int = 0
    io_chunk_bytes: int = 64 * 1024

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
        if not isinstance(self.class_max_bytes, Mapping):
            raise ObjectLimitError("class limits must be a mapping")
        for object_class, limit in self.class_max_bytes.items():
            require_token(object_class, field="object_class")
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise ObjectLimitError("object-class limits must be positive")
            if limit > self.global_max_bytes:
                raise ObjectLimitError(
                    "object-class limit cannot exceed the global hard maximum"
                )

    def maximum_for(self, object_class: str) -> int:
        require_token(object_class, field="object_class")
        try:
            return min(self.global_max_bytes, int(self.class_max_bytes[object_class]))
        except KeyError as exc:
            raise ObjectLimitError(
                f"no hard byte limit is configured for object class {object_class}"
            ) from exc


@dataclass(frozen=True, slots=True)
class ObjectAdmissionDefinition:
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


class ObjectAdmissionRegistry:
    def __init__(self, definitions: Iterable[ObjectAdmissionDefinition]) -> None:
        values: dict[str, ObjectAdmissionDefinition] = {}
        for definition in definitions:
            if definition.admission_type in values:
                raise ObjectPolicyError(
                    f"duplicate object admission definition: {definition.admission_type}"
                )
            values[definition.admission_type] = definition
        if not values:
            raise ObjectPolicyError("object admission registry cannot be empty")
        self._values = values

    def resolve(self, admission_type: str) -> ObjectAdmissionDefinition:
        try:
            return self._values[admission_type]
        except KeyError as exc:
            raise ObjectPolicyError(
                f"unknown object admission type: {admission_type}"
            ) from exc


@dataclass(frozen=True, slots=True)
class StaticRightsRule:
    policy_version: str
    allowed: bool
    reason_code: str
    validity_seconds: int | None = None

    def __post_init__(self) -> None:
        require_token(self.policy_version, field="rights_policy_version")
        if not isinstance(self.allowed, bool):
            raise ObjectPolicyError("rights allowed value must be boolean")
        require_token(self.reason_code, field="rights_reason_code")
        if self.validity_seconds is not None and (
            isinstance(self.validity_seconds, bool)
            or not isinstance(self.validity_seconds, int)
            or self.validity_seconds <= 0
        ):
            raise ObjectPolicyError("rights validity must be positive")


class StaticRightsResolver:
    """Server-owned deterministic rights policy for tests and local integration."""

    def __init__(self, rules: Mapping[str, StaticRightsRule]) -> None:
        if not rules:
            raise ObjectPolicyError("rights resolver requires policy rules")
        self._rules = dict(rules)
        for key in self._rules:
            require_token(key, field="rights_policy_key")

    def rule_for(self, policy_key: str) -> StaticRightsRule:
        try:
            return self._rules[policy_key]
        except KeyError as exc:
            raise ObjectPolicyError(
                f"unknown rights policy key: {policy_key}"
            ) from exc

    def preflight(self, definition: ObjectAdmissionDefinition) -> None:
        rule = self.rule_for(definition.rights_policy_key)
        if not rule.allowed:
            raise ObjectAdmissionDenied(rule.reason_code)

    @staticmethod
    def validity_window(
        rule: StaticRightsRule, *, now: UtcTimestamp
    ) -> tuple[UtcTimestamp, UtcTimestamp | None]:
        valid_until = (
            None
            if rule.validity_seconds is None
            else UtcTimestamp(now.value + timedelta(seconds=rule.validity_seconds))
        )
        return now, valid_until


@dataclass(frozen=True, slots=True)
class ObjectAdmissionRequest:
    admission_type: str
    idempotency_key: str

    def __post_init__(self) -> None:
        require_token(self.admission_type, field="admission_type")
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise ObjectPolicyError("idempotency_key must be non-empty")
        if len(self.idempotency_key.encode("utf-8")) > 256:
            raise ObjectPolicyError("idempotency_key exceeds 256 UTF-8 bytes")


@dataclass(frozen=True, slots=True)
class ObjectAdmissionReceipt:
    admission_id: ObjectAdmissionId
    blob_digest: str
    size_bytes: int
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    rights_decision_id: RightsDecisionId
    rights_policy_version: str
    valid_from: str
    valid_until: str | None
    ledger_seq: int
    event_id: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class HydratedObject:
    admission_id: ObjectAdmissionId
    blob_digest: str
    purpose: str
    bytes_value: bytes
    access_decision_id: str


@dataclass(frozen=True, slots=True)
class ObjectDeletionReceipt:
    deletion_id: str
    blob_digest: str
    requested_ledger_seq: int
    completed_ledger_seq: int | None
    completed: bool


class AuthorityObjects:
    """Authenticated governed-object facade; direct blob/store APIs stay private."""

    __slots__ = (
        "__admit",
        "__hydrate",
        "__revoke",
        "__delete",
        "__pin",
        "__release_pin",
        "__gc",
    )

    def __init__(
        self,
        *,
        admit: Callable[[ObjectAdmissionRequest, BinaryIO, object], ObjectAdmissionReceipt],
        hydrate: Callable[[ObjectAdmissionId, str, int, object], HydratedObject],
        revoke: Callable[[ObjectAdmissionId, object], int],
        delete: Callable[[str, str, object], ObjectDeletionReceipt],
        pin: Callable[[str, str, object], str],
        release_pin: Callable[[str, object], None],
        collect: Callable[[int, object], tuple[str, ...]],
    ) -> None:
        self.__admit = admit
        self.__hydrate = hydrate
        self.__revoke = revoke
        self.__delete = delete
        self.__pin = pin
        self.__release_pin = release_pin
        self.__gc = collect

    def admit(
        self,
        request: ObjectAdmissionRequest,
        source: BinaryIO,
        *,
        proof: object,
    ) -> ObjectAdmissionReceipt:
        return self.__admit(request, source, proof)

    def hydrate(
        self,
        admission_id: ObjectAdmissionId,
        *,
        purpose: str,
        max_bytes: int,
        proof: object,
    ) -> HydratedObject:
        return self.__hydrate(admission_id, purpose, max_bytes, proof)

    def revoke(self, admission_id: ObjectAdmissionId, *, proof: object) -> int:
        return self.__revoke(admission_id, proof)

    def delete_blob(
        self, blob_digest: str, *, reason_code: str, proof: object
    ) -> ObjectDeletionReceipt:
        return self.__delete(blob_digest, reason_code, proof)

    def pin_recovery(
        self, blob_digest: str, *, reason_code: str, proof: object
    ) -> str:
        return self.__pin(blob_digest, reason_code, proof)

    def release_recovery_pin(self, pin_id: str, *, proof: object) -> None:
        self.__release_pin(pin_id, proof)

    def collect_garbage(
        self, *, grace_seconds: int, proof: object
    ) -> tuple[str, ...]:
        return self.__gc(grace_seconds, proof)
