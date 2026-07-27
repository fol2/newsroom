"""Typed immutable source-registry requests and retained records."""

from newsroom.authority.types import TrustScope

from .definition_models import SourceDefinitionRequest, SourceDefinitionVersionRequest
from .item_models import LocatorContinuityDecisionRequest, SourceItemRequest
from .observation_models import (
    DiscoveryOccurrenceRequest,
    DiscoveryRepresentationRequest,
    SourceRevisionRequest,
)
from .record_models import (
    DiscoveryOccurrence,
    DiscoveryRepresentation,
    LocatorContinuityDecision,
    SourceDefinition,
    SourceDefinitionVersion,
    SourceDefinitionVersionSummary,
    SourceItem,
    SourceRevision,
)

SOURCE_RECORD_TRUST = {
    SourceDefinitionRequest: TrustScope.ADMITTED,
    SourceDefinitionVersionRequest: TrustScope.ADMITTED,
    SourceItemRequest: TrustScope.OBSERVED,
    LocatorContinuityDecisionRequest: TrustScope.ADMITTED,
    SourceRevisionRequest: TrustScope.OBSERVED,
    DiscoveryRepresentationRequest: TrustScope.OBSERVED,
    DiscoveryOccurrenceRequest: TrustScope.OBSERVED,
}

__all__ = [
    "DiscoveryOccurrence",
    "DiscoveryOccurrenceRequest",
    "DiscoveryRepresentation",
    "DiscoveryRepresentationRequest",
    "LocatorContinuityDecision",
    "LocatorContinuityDecisionRequest",
    "SOURCE_RECORD_TRUST",
    "SourceDefinition",
    "SourceDefinitionRequest",
    "SourceDefinitionVersion",
    "SourceDefinitionVersionRequest",
    "SourceDefinitionVersionSummary",
    "SourceItem",
    "SourceItemRequest",
    "SourceRevision",
    "SourceRevisionRequest",
]
