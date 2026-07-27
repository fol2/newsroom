from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import TimePrecision, UtcTimestamp
from newsroom.discovery_adapters import ParsedItem
from newsroom.checks.baseline_models import BaselineDecisionRequest
from newsroom.checks.record_models import BaselineDecision, ObservableTransition
from newsroom.checks.transition_models import ObservableTransitionRequest
from newsroom.sources import (
    DiscoveryOccurrence,
    DiscoveryOccurrenceRequest,
    DiscoveryRepresentation,
    DiscoveryRepresentationRequest,
    IdentityComponent,
    SourceItem,
    SourceItemRequest,
    SourceRevision,
    SourceRevisionRequest,
    SourceTime,
)



@dataclass(frozen=True, slots=True)
class _DecisionPlan:
    baseline: BaselineDecision | None
    baseline_request: BaselineDecisionRequest | None
    transitions: tuple[ObservableTransition, ...]
    transition_requests: tuple[ObservableTransitionRequest, ...]


@dataclass(frozen=True, slots=True)
class _AuthorizedDecisionPlan:
    plan: _DecisionPlan
    baseline_grant: _AuthorizedCommandGrant | None
    transition_grants: tuple[_AuthorizedCommandGrant, ...]


@dataclass(frozen=True, slots=True)
class _ObservationPlan:
    parsed_item: ParsedItem
    item: SourceItem | None
    item_request: SourceItemRequest | None
    revision: SourceRevision | None
    revision_request: SourceRevisionRequest | None
    representation: DiscoveryRepresentation | None
    representation_request: DiscoveryRepresentationRequest | None
    occurrence: DiscoveryOccurrence | None
    occurrence_request: DiscoveryOccurrenceRequest


@dataclass(frozen=True, slots=True)
class _AuthorizedPlan:
    plan: _ObservationPlan
    item_grant: _AuthorizedCommandGrant | None
    revision_grant: _AuthorizedCommandGrant | None
    representation_grant: _AuthorizedCommandGrant | None
    occurrence_grant: _AuthorizedCommandGrant | None


def _version_token(prefix: str, value: object) -> str:
    return f"{prefix}-{digest_canonical(value).removeprefix('sha256:')[:24]}"


def _field_map(item: ParsedItem) -> dict[str, str]:
    return {field.name: field.value for field in item.fields}


def _identity_component_name(name: str) -> str:
    selected = f"identity_{name}"
    if len(selected) <= 128:
        return selected
    return _version_token("identity", name)


def _source_time(item: ParsedItem, field_name: str) -> SourceTime:
    value = _field_map(item).get(field_name)
    if value is None:
        return SourceTime.unknown()
    try:
        exact = UtcTimestamp.parse(value)
    except ValueError:
        exact = None
    if exact is not None and exact.to_text() == value:
        return SourceTime.exact(exact)
    try:
        selected_date = date.fromisoformat(value)
    except ValueError:
        return SourceTime.unknown()
    if selected_date.isoformat() != value:
        return SourceTime.unknown()
    return SourceTime(TimePrecision.DATE_ONLY, value)



__all__ = [
    "_AuthorizedDecisionPlan",
    "_AuthorizedPlan",
    "_DecisionPlan",
    "_ObservationPlan",
    "_field_map",
    "_identity_component_name",
    "_source_time",
    "_version_token",
]
