"""Public composition seam for checked Event Hypothesis authority."""

from __future__ import annotations

from ._event_hypothesis_system import (
    EventHypothesisAuthority as EventHypothesisAuthoritySystem,
)


def open_event_hypothesis_authority_system(
    *args: object, **kwargs: object
) -> EventHypothesisAuthoritySystem:
    """Open the checked v21 authority without exposing its SQLite store."""

    return EventHypothesisAuthoritySystem.open(*args, **kwargs)


__all__ = [
    "EventHypothesisAuthoritySystem",
    "open_event_hypothesis_authority_system",
]
