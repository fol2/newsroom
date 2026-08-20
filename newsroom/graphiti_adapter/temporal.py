"""Versioned Graphiti reference_time mapping (GING-003)."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.evaluation_packet import TEMPORAL_POLICY_VERSION

SOURCE_UPDATED = "SOURCE_UPDATED"
SOURCE_PUBLISHED = "SOURCE_PUBLISHED"
OBSERVED_FALLBACK = "OBSERVED_FALLBACK"


@dataclass(frozen=True, slots=True)
class TemporalMapping:
    policy_version: str
    basis: str
    reference_time: UtcTimestamp
    published_at: str | None
    updated_at: str | None
    observed_at: str


def _parse(value: str) -> UtcTimestamp | None:
    text = value.strip()
    if not text:
        return None
    try:
        return UtcTimestamp.parse(text)
    except ValueError:
        return None


def map_reference_time(
    *,
    published_at: str | None,
    updated_at: str | None,
    observed_at: str,
) -> TemporalMapping:
    updated = _parse(updated_at) if updated_at else None
    if updated is not None:
        return TemporalMapping(
            TEMPORAL_POLICY_VERSION,
            SOURCE_UPDATED,
            updated,
            published_at,
            updated_at,
            observed_at,
        )
    published = _parse(published_at) if published_at else None
    if published is not None:
        return TemporalMapping(
            TEMPORAL_POLICY_VERSION,
            SOURCE_PUBLISHED,
            published,
            published_at,
            updated_at,
            observed_at,
        )
    observed = _parse(observed_at)
    if observed is None:
        raise ValueError("observed_at must be a UTC timestamp")
    return TemporalMapping(
        TEMPORAL_POLICY_VERSION,
        OBSERVED_FALLBACK,
        observed,
        published_at,
        updated_at,
        observed_at,
    )
