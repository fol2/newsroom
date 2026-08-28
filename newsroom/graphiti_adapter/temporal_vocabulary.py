"""Shared typed vocabulary for Graphiti temporal mapping."""

from __future__ import annotations

from enum import StrEnum

TEMPORAL_POLICY_VERSION = "graphiti-source-reference-time-v2"


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


__all__ = ["TEMPORAL_POLICY_VERSION", "TemporalBasis", "parse_temporal_basis"]
