"""Public composition seam for checked Hypothesis relationship authority."""

from ._event_hypothesis_relationship_system import (
    EventHypothesisRelationshipAuthority as EventHypothesisRelationshipAuthoritySystem,
)
from ._event_hypothesis_relationship_system import (
    open_relationship_authority as open_event_hypothesis_relationship_authority_system,
)

__all__ = [
    "EventHypothesisRelationshipAuthoritySystem",
    "open_event_hypothesis_relationship_authority_system",
]
