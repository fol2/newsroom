from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.types import EventId, UtcTimestamp

from ._model_common import validate_committed
from .baseline_models import BaselineDecisionRequest
from .check_models import (
    CheckAttemptRequest,
    CheckOutcomeRequest,
    CheckRequestRequest,
)
from .finding_models import (
    OperationalFindingOccurrenceRequest,
    OperationalFindingRequest,
)
from .transition_models import ObservableTransitionRequest
from .types import CheckContractError


@dataclass(frozen=True, slots=True)
class CheckRequest:
    request: CheckRequestRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, CheckRequestRequest):
            raise CheckContractError("Check Request payload must be retained")
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class CheckAttempt:
    request: CheckAttemptRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, CheckAttemptRequest):
            raise CheckContractError("Check Attempt payload must be retained")
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    request: CheckOutcomeRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, CheckOutcomeRequest):
            raise CheckContractError("Check Outcome payload must be retained")
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class BaselineDecision:
    request: BaselineDecisionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, BaselineDecisionRequest):
            raise CheckContractError(
                "Baseline Decision payload must be retained"
            )
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class ObservableTransition:
    request: ObservableTransitionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, ObservableTransitionRequest):
            raise CheckContractError(
                "Observable Transition payload must be retained"
            )
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class OperationalFinding:
    request: OperationalFindingRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, OperationalFindingRequest):
            raise CheckContractError(
                "Operational Finding payload must be retained"
            )
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class OperationalFindingOccurrence:
    request: OperationalFindingOccurrenceRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(
            self.request,
            OperationalFindingOccurrenceRequest,
        ):
            raise CheckContractError(
                "Finding occurrence payload must be retained"
            )
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


__all__ = [
    "BaselineDecision",
    "CheckAttempt",
    "CheckOutcome",
    "CheckRequest",
    "ObservableTransition",
    "OperationalFinding",
    "OperationalFindingOccurrence",
]
