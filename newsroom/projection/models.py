from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, validate_sha256_digest
from newsroom.authority.types import (
    AggregateId,
    EventId,
    TrustScope,
    UUIDv4Id,
    UtcTimestamp,
    require_scope,
    require_token,
)


class ProjectionContractError(ValueError):
    """Raised when a projection contract or request is malformed."""


class ProjectionStateError(RuntimeError):
    """Raised when an authoritative projection transition is invalid."""


@dataclass(frozen=True, slots=True)
class ProjectionGenerationId(UUIDv4Id):
    def as_aggregate_id(self) -> AggregateId:
        return AggregateId(self.value)


@dataclass(frozen=True, slots=True)
class ProjectionGapId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ProjectionDeadLetterId(UUIDv4Id):
    pass


class ProjectionFamilyKind(StrEnum):
    GRAPH = "GRAPH"
    VECTOR = "VECTOR"
    FULL_TEXT = "FULL_TEXT"


class ProjectionGenerationState(StrEnum):
    BUILDING = "BUILDING"
    VALIDATING = "VALIDATING"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    FAILED = "FAILED"


class ProjectionDeliveryOutcome(StrEnum):
    APPLIED = "APPLIED"
    IGNORED_OPTIONAL = "IGNORED_OPTIONAL"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    REQUIRED_UNSUPPORTED = "REQUIRED_UNSUPPORTED"


class ProjectionGapState(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True, slots=True)
class ProjectionFamilyDefinition:
    family_id: str
    authority_aggregate_id: AggregateId
    family_kind: ProjectionFamilyKind
    definition_version: str
    projector_version: str
    ontology_contract_digest: str
    mapping_contract_digest: str
    required_manage_scope: str = "authority.projection.manage"
    required_write_scope: str = "authority.projection.write"
    required_read_scope: str = "authority.projection.read"
    security_scope: str = "authority.projection"
    retention_scope: str = "authority.audit"

    def __post_init__(self) -> None:
        require_token(self.family_id, field="projection_family_id")
        if not isinstance(self.authority_aggregate_id, AggregateId):
            raise ProjectionContractError("family aggregate identity must be AggregateId")
        if not isinstance(self.family_kind, ProjectionFamilyKind):
            raise ProjectionContractError("projection family kind must be typed")
        require_token(self.definition_version, field="projection_family_version")
        require_token(self.projector_version, field="projector_version")
        for field, value in (
            ("ontology_contract_digest", self.ontology_contract_digest),
            ("mapping_contract_digest", self.mapping_contract_digest),
        ):
            normalized = validate_sha256_digest(value, field=field)
            if normalized != value:
                raise ProjectionContractError(f"{field} must be canonical lowercase")
        require_scope(self.required_manage_scope, field="required_manage_scope")
        require_scope(self.required_write_scope, field="required_write_scope")
        require_scope(self.required_read_scope, field="required_read_scope")
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")

    def canonical_value(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "authority_aggregate_id": str(self.authority_aggregate_id),
            "family_kind": self.family_kind.value,
            "definition_version": self.definition_version,
            "projector_version": self.projector_version,
            "ontology_contract_digest": self.ontology_contract_digest,
            "mapping_contract_digest": self.mapping_contract_digest,
            "required_manage_scope": self.required_manage_scope,
            "required_write_scope": self.required_write_scope,
            "required_read_scope": self.required_read_scope,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
        }

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class ProjectionGenerationView:
    generation_id: ProjectionGenerationId
    family_id: str
    state: ProjectionGenerationState
    lifecycle_version: int
    authority_aggregate_version: int
    validated_through_ledger_seq: int | None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class ProjectionCheckpointView:
    generation_id: ProjectionGenerationId
    checkpoint_version: int
    contiguous_ledger_seq: int
    event_id: EventId
    recorded_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class ProjectionGapView:
    gap_id: ProjectionGapId
    generation_id: ProjectionGenerationId
    ledger_seq_start: int
    ledger_seq_end: int
    state: ProjectionGapState
    lifecycle_version: int
    required: bool
    reason_code: str
    opened_event_id: EventId
    resolved_event_id: EventId | None
    recorded_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class ProjectionDeadLetterView:
    dead_letter_id: ProjectionDeadLetterId
    generation_id: ProjectionGenerationId
    ledger_seq: int
    source_event_id: EventId
    attempts: int
    reason_code: str
    authority_event_id: EventId
    recorded_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class ProjectionStatusMetadata:
    family_id: str
    family_kind: ProjectionFamilyKind
    projector_version: str
    ontology_contract_digest: str
    mapping_contract_digest: str
    generation_id: ProjectionGenerationId | None
    generation_state: ProjectionGenerationState | None
    contiguous_ledger_seq: int
    open_gap_count: int
    dead_letter_count: int
    trust_scope: TrustScope
    serving_time: UtcTimestamp


@dataclass(frozen=True, slots=True)
class DeliveryRecordView:
    generation_id: ProjectionGenerationId
    ledger_seq: int
    source_event_id: EventId
    source_event_digest: str
    outcome: ProjectionDeliveryOutcome
    required: bool
    error_code: str | None
    authority_event_id: EventId
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        validate_sha256_digest(self.source_event_digest, field="source_event_digest")


def require_positive_sequence(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProjectionContractError(f"{field} must be a positive integer")
    return value


def require_non_negative_sequence(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProjectionContractError(f"{field} must be a non-negative integer")
    return value


def require_reason(value: str, *, field: str = "reason_code") -> str:
    return require_token(value, field=field)


def require_exact_keys(value: Any, expected: frozenset[str], *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ProjectionContractError(f"{name} fields differ from retained schema")
    return value
