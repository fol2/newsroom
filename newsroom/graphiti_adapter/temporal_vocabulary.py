"""Shared typed vocabulary for Graphiti temporal mapping."""

from __future__ import annotations

from enum import StrEnum

from newsroom.authority.canonical import digest_canonical

TEMPORAL_POLICY_VERSION = "graphiti-source-reference-time-v2"
TEMPORAL_POLICY_VERSION_V1 = "graphiti-source-reference-time-v1"
TEMPORAL_POLICY_DIGEST_V1 = digest_canonical(TEMPORAL_POLICY_VERSION_V1)
TEMPORAL_POLICY_DIGEST_V2 = digest_canonical(TEMPORAL_POLICY_VERSION)


class TemporalBasis(StrEnum):
    UNSET = "UNSET"
    SOURCE_UPDATED = "SOURCE_UPDATED"
    SOURCE_PUBLISHED = "SOURCE_PUBLISHED"
    OBSERVED_FALLBACK = "OBSERVED_FALLBACK"


def parse_temporal_basis(value: object) -> TemporalBasis:
    if isinstance(value, TemporalBasis):
        return value
    if isinstance(value, str):
        try:
            return TemporalBasis(value)
        except ValueError:
            pass
    raise ValueError("temporal_basis must be a labelled mapping")


__all__ = [
    "TEMPORAL_POLICY_DIGEST_V1",
    "TEMPORAL_POLICY_DIGEST_V2",
    "TEMPORAL_POLICY_VERSION",
    "TEMPORAL_POLICY_VERSION_V1",
    "TemporalBasis",
    "parse_temporal_basis",
]
