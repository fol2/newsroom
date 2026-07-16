from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .canonical import validate_sha256_digest
from .types import AggregateId, AggregateVersion, TrustScope, UtcTimestamp

_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,255}$")


class CommandValidationError(ValueError):
    """Raised when a semantic command is malformed before authentication."""


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise CommandValidationError(f"{field} is not a valid authority token")
    return value


def _require_scope(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SCOPE.fullmatch(value) is None:
        raise CommandValidationError(f"{field} is not a valid scope token")
    return value


@dataclass(frozen=True, slots=True)
class SemanticCommand:
    """Caller-supplied semantic command with no authoritative identity claims."""

    command_type: str
    aggregate_type: str
    aggregate_id: AggregateId
    expected_aggregate_version: int
    payload_schema_version: str
    payload_digest: str
    idempotency_key: str
    issued_at: UtcTimestamp
    producer_version: str
    event_type: str
    event_schema_version: int = 1
    payload_object_ref: str | None = None
    trust_scope: TrustScope = TrustScope.OBSERVED
    security_scope: str = "authority.internal"
    retention_scope: str = "authority.default"
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        _require_token(self.command_type, field="command_type")
        _require_token(self.aggregate_type, field="aggregate_type")
        _require_token(self.payload_schema_version, field="payload_schema_version")
        _require_token(self.producer_version, field="producer_version")
        _require_token(self.event_type, field="event_type")
        if (
            isinstance(self.expected_aggregate_version, bool)
            or not isinstance(self.expected_aggregate_version, int)
            or self.expected_aggregate_version < 0
        ):
            raise CommandValidationError(
                "expected_aggregate_version must be a non-negative integer"
            )
        if (
            isinstance(self.event_schema_version, bool)
            or not isinstance(self.event_schema_version, int)
            or self.event_schema_version <= 0
        ):
            raise CommandValidationError("event_schema_version must be positive")
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise CommandValidationError("idempotency_key must be non-empty")
        if len(self.idempotency_key.encode("utf-8")) > 256:
            raise CommandValidationError("idempotency_key exceeds 256 UTF-8 bytes")
        validate_sha256_digest(self.payload_digest, field="payload_digest")
        if self.payload_object_ref is not None:
            validate_sha256_digest(
                self.payload_object_ref, field="payload_object_ref"
            )
            if self.payload_object_ref != self.payload_digest:
                raise CommandValidationError(
                    "payload_object_ref must equal the exact payload_digest"
                )
        _require_scope(self.security_scope, field="security_scope")
        _require_scope(self.retention_scope, field="retention_scope")
        for field_name in ("correlation_id", "causation_id"):
            value = getattr(self, field_name)
            if value is not None:
                _require_token(value, field=field_name)


@dataclass(frozen=True, slots=True)
class CommittedCommand:
    command_id: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: AggregateVersion
    ledger_seq: int
    event_id: str
    result_digest: str
    replayed: bool = False

    def to_canonical_value(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_version": int(self.aggregate_version),
            "ledger_seq": self.ledger_seq,
            "event_id": self.event_id,
        }


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    ledger_seq: int
    event_id: str
    event_type: str
    event_schema_version: int
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    recorded_at: str
    command_id: str
    principal_id: str
    authentication_context_id: str
    authorization_decision_id: str
    correlation_id: str | None
    causation_id: str | None
    producer_version: str
    payload_digest: str
    payload_object_ref: str | None
    security_scope: str
    retention_scope: str
    trust_scope: TrustScope


@dataclass(frozen=True, slots=True)
class AuditRecord:
    audit_id: str
    command_id: str
    event_type: str
    principal_id: str
    authentication_context_id: str
    authorization_decision_id: str
    authorization_policy_version: str
    effective_scope_digest: str
    semantic_request_digest: str
    detail_digest: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    schema_version: int
    journal_mode: str
    synchronous: int
    foreign_keys: bool
    busy_timeout_ms: int
