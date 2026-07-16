from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from .canonical import canonical_json_bytes, digest_bytes
from .types import (
    AggregateId,
    CausationRef,
    CorrelationId,
    ObjectAdmissionId,
    PayloadMode,
    TrustScope,
    require_scope,
    require_token,
)


class CommandValidationError(ValueError):
    """Raised when a caller command or server command definition is malformed."""


@dataclass(frozen=True, slots=True)
class InlinePayload:
    value: Any


@dataclass(frozen=True, slots=True)
class ObjectAdmissionPayload:
    admission_id: ObjectAdmissionId

    def __post_init__(self) -> None:
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise CommandValidationError("object payload requires ObjectAdmissionId")


@dataclass(frozen=True, slots=True)
class NoPayload:
    """Explicit schema-defined no-payload request."""


NO_PAYLOAD: Final = NoPayload()
PayloadRequest = InlinePayload | ObjectAdmissionPayload | NoPayload


@dataclass(frozen=True, slots=True)
class SemanticCommand:
    """Caller request with no authority-bearing event, trust or scope fields."""

    command_type: str
    aggregate_id: AggregateId
    expected_aggregate_version: int
    payload: PayloadRequest
    idempotency_key: str
    correlation_id: CorrelationId | None = None
    causation: CausationRef | None = None

    def __post_init__(self) -> None:
        require_token(self.command_type, field="command_type")
        if not isinstance(self.aggregate_id, AggregateId):
            raise CommandValidationError("aggregate_id must be AggregateId")
        if (
            isinstance(self.expected_aggregate_version, bool)
            or not isinstance(self.expected_aggregate_version, int)
            or self.expected_aggregate_version < 0
        ):
            raise CommandValidationError(
                "expected_aggregate_version must be a non-negative integer"
            )
        if not isinstance(self.payload, (InlinePayload, ObjectAdmissionPayload, NoPayload)):
            raise CommandValidationError("payload must use a closed payload request type")
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise CommandValidationError("idempotency_key must be non-empty")
        if len(self.idempotency_key.encode("utf-8")) > 256:
            raise CommandValidationError("idempotency_key exceeds 256 UTF-8 bytes")
        if self.correlation_id is not None and not isinstance(
            self.correlation_id, CorrelationId
        ):
            raise CommandValidationError("correlation_id must be CorrelationId")
        if self.causation is not None and not isinstance(self.causation, CausationRef):
            raise CommandValidationError("causation must be CausationRef")


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    """Versioned server-side authority semantics for one command type."""

    command_type: str
    definition_version: str
    aggregate_type: str
    event_type: str
    event_schema_version: int
    payload_mode: PayloadMode
    payload_schema_version: str
    trust_scope: TrustScope
    security_scope: str
    retention_scope: str
    required_scope: str
    max_inline_bytes: int = 0
    required_object_class: str | None = None
    required_allowed_use: str | None = None

    def __post_init__(self) -> None:
        require_token(self.command_type, field="command_type")
        require_token(self.definition_version, field="definition_version")
        require_token(self.aggregate_type, field="aggregate_type")
        require_token(self.event_type, field="event_type")
        require_token(self.payload_schema_version, field="payload_schema_version")
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        require_scope(self.required_scope, field="required_scope")
        if not isinstance(self.payload_mode, PayloadMode):
            raise CommandValidationError("payload_mode must be typed")
        if not isinstance(self.trust_scope, TrustScope):
            raise CommandValidationError("trust_scope must be typed")
        if (
            isinstance(self.event_schema_version, bool)
            or not isinstance(self.event_schema_version, int)
            or self.event_schema_version <= 0
        ):
            raise CommandValidationError("event_schema_version must be positive")
        if (
            isinstance(self.max_inline_bytes, bool)
            or not isinstance(self.max_inline_bytes, int)
            or self.max_inline_bytes < 0
        ):
            raise CommandValidationError("max_inline_bytes must be non-negative")
        if self.payload_mode is PayloadMode.INLINE and self.max_inline_bytes <= 0:
            raise CommandValidationError("inline commands require a positive byte limit")
        if self.payload_mode is not PayloadMode.INLINE and self.max_inline_bytes != 0:
            raise CommandValidationError(
                "non-inline commands cannot declare an inline byte limit"
            )
        if self.payload_mode is PayloadMode.OBJECT_ADMISSION:
            require_token(self.required_object_class or "", field="required_object_class")
            require_token(self.required_allowed_use or "", field="required_allowed_use")
        elif self.required_object_class is not None or self.required_allowed_use is not None:
            raise CommandValidationError(
                "object class/use constraints apply only to object-admission payloads"
            )

    def canonical_value(self) -> dict[str, Any]:
        return {
            "command_type": self.command_type,
            "definition_version": self.definition_version,
            "aggregate_type": self.aggregate_type,
            "event_type": self.event_type,
            "event_schema_version": self.event_schema_version,
            "payload_mode": self.payload_mode.value,
            "payload_schema_version": self.payload_schema_version,
            "trust_scope": self.trust_scope.value,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "required_scope": self.required_scope,
            "max_inline_bytes": self.max_inline_bytes,
            "required_object_class": self.required_object_class,
            "required_allowed_use": self.required_allowed_use,
        }

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class ObjectAdmissionDescriptor:
    """Read-only server-resolved object-use authority used by command policy."""

    admission_id: ObjectAdmissionId
    blob_digest: str
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    active: bool

    def __post_init__(self) -> None:
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise CommandValidationError("admission descriptor requires typed identity")
        require_token(self.object_class, field="object_class")
        require_token(self.allowed_use, field="allowed_use")
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        if not isinstance(self.active, bool):
            raise CommandValidationError("admission active flag must be boolean")
