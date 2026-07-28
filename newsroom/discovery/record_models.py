from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.checks._model_common import validate_committed

from .models import (
    DiscoverySignalRequest,
    GateDecisionRequest,
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
    WatchConditionRequest,
)
from .types import DiscoveryContractError


@dataclass(frozen=True, slots=True)
class DiscoverySignal:
    request: DiscoverySignalRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, DiscoverySignalRequest):
            raise DiscoveryContractError("Discovery Signal payload must be retained")
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class GateDecision:
    request: GateDecisionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, GateDecisionRequest):
            raise DiscoveryContractError("Gate Decision payload must be retained")
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class NewsLead:
    request: NewsLeadRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, NewsLeadRequest):
            raise DiscoveryContractError("News Lead payload must be retained")
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class WatchCondition:
    request: WatchConditionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, WatchConditionRequest):
            raise DiscoveryContractError("Watch Condition payload must be retained")
        validate_committed(
            request=self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class LeadDispositionDecision:
    request: LeadDispositionDecisionRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, LeadDispositionDecisionRequest):
            raise DiscoveryContractError(
                "Lead Disposition Decision payload must be retained"
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
    "DiscoverySignal",
    "GateDecision",
    "LeadDispositionDecision",
    "NewsLead",
    "WatchCondition",
]
