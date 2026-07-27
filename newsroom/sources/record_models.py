from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from newsroom.authority.types import EventId, UUIDv4Id, UtcTimestamp

from .definition_models import SourceDefinitionRequest, SourceDefinitionVersionRequest
from .item_models import LocatorContinuityDecisionRequest, SourceItemRequest
from .observation_models import (
    DiscoveryOccurrenceRequest,
    DiscoveryRepresentationRequest,
    SourceRevisionRequest,
)
from .types import (
    EXECUTION_AUTHORITY_DISABLED,
    ObservationModel,
    PortfolioFunction,
    SourceContractError,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceLifecycleStage,
    SourceRole,
    bounded_text_tuple,
    canonical_digest,
    typed_enum_tuple,
)


class _DigestRequest(Protocol):
    @property
    def digest(self) -> str: ...


def _validate_committed(
    *,
    request: _DigestRequest,
    event_id: EventId,
    aggregate_version: int,
    recorded_at: UtcTimestamp,
    record_digest: str,
    replayed: bool,
) -> None:
    if not isinstance(event_id, EventId):
        raise SourceContractError("source authority event identity must be typed")
    if (
        isinstance(aggregate_version, bool)
        or not isinstance(aggregate_version, int)
        or aggregate_version != 1
    ):
        raise SourceContractError(
            "immutable source records must have aggregate version one"
        )
    if not isinstance(recorded_at, UtcTimestamp):
        raise SourceContractError("source recording time must be typed")
    canonical_digest(record_digest, field="source_record_digest")
    if record_digest != request.digest:
        raise SourceContractError("source record digest differs from request")
    if not isinstance(replayed, bool):
        raise SourceContractError("source replay flag must be boolean")


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    request: SourceDefinitionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, SourceDefinitionRequest):
            raise SourceContractError("source definition request must be retained")
        _validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )

    @property
    def definition_id(self) -> SourceDefinitionId:
        return self.request.definition_id


@dataclass(frozen=True, slots=True)
class SourceDefinitionVersion:
    request: SourceDefinitionVersionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, SourceDefinitionVersionRequest):
            raise SourceContractError("source version request must be retained")
        _validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )

    @property
    def version_id(self) -> SourceDefinitionVersionId:
        return self.request.version_id


@dataclass(frozen=True, slots=True)
class SourceDefinitionVersionSummary:
    version_id: SourceDefinitionVersionId
    definition_id: SourceDefinitionId
    version_number: int
    lifecycle_stage: SourceLifecycleStage
    observation_model: ObservationModel
    roles: tuple[SourceRole, ...]
    portfolio_functions: tuple[PortfolioFunction, ...]
    coverage_obligation_ids: tuple[str, ...]
    explicit_gap_ids: tuple[str, ...]
    locator_digest: str
    rights_decision_id: str
    execution_authority: str
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, SourceDefinitionVersionId):
            raise SourceContractError("source version summary identity must be typed")
        if not isinstance(self.definition_id, SourceDefinitionId):
            raise SourceContractError("source summary definition must be typed")
        if (
            isinstance(self.version_number, bool)
            or not isinstance(self.version_number, int)
            or self.version_number <= 0
        ):
            raise SourceContractError("source summary version must be positive")
        if not isinstance(self.lifecycle_stage, SourceLifecycleStage):
            raise SourceContractError("source summary lifecycle must be typed")
        if not isinstance(self.observation_model, ObservationModel):
            raise SourceContractError("source summary observation must be typed")
        typed_enum_tuple(
            self.roles,
            enum_type=SourceRole,
            field="source_summary_roles",
        )
        typed_enum_tuple(
            self.portfolio_functions,
            enum_type=PortfolioFunction,
            field="source_summary_portfolio_functions",
        )
        bounded_text_tuple(
            self.coverage_obligation_ids,
            field="source_summary_coverage",
            allow_empty=True,
            maximum_items=128,
            maximum_item_bytes=128,
        )
        bounded_text_tuple(
            self.explicit_gap_ids,
            field="source_summary_gaps",
            allow_empty=True,
            maximum_items=128,
            maximum_item_bytes=128,
        )
        canonical_digest(self.locator_digest, field="source_locator_digest")
        UUIDv4Id.parse(self.rights_decision_id)
        if self.execution_authority != EXECUTION_AUTHORITY_DISABLED:
            raise SourceContractError("source summary exposes unexpected execution")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise SourceContractError("source summary recording time must be typed")


@dataclass(frozen=True, slots=True)
class SourceItem:
    request: SourceItemRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, SourceItemRequest):
            raise SourceContractError("source item request must be retained")
        _validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class LocatorContinuityDecision:
    request: LocatorContinuityDecisionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, LocatorContinuityDecisionRequest):
            raise SourceContractError("locator decision request must be retained")
        _validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class SourceRevision:
    request: SourceRevisionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, SourceRevisionRequest):
            raise SourceContractError("source revision request must be retained")
        _validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class DiscoveryRepresentation:
    request: DiscoveryRepresentationRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, DiscoveryRepresentationRequest):
            raise SourceContractError("representation request must be retained")
        _validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class DiscoveryOccurrence:
    request: DiscoveryOccurrenceRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, DiscoveryOccurrenceRequest):
            raise SourceContractError("occurrence request must be retained")
        _validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


__all__ = [
    "DiscoveryOccurrence",
    "DiscoveryRepresentation",
    "LocatorContinuityDecision",
    "SourceDefinition",
    "SourceDefinitionVersion",
    "SourceDefinitionVersionSummary",
    "SourceItem",
    "SourceRevision",
]
