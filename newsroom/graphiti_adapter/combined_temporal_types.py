"""Shared types for combined-temporal extraction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CombinedTemporalFailureCode(StrEnum):
    NONE = "NONE"
    MALFORMED_OBJECT = "MALFORMED_OBJECT"
    TEMPORAL_INVALID = "TEMPORAL_INVALID"
    EVIDENCE_UNRESOLVED = "EVIDENCE_UNRESOLVED"
    IDENTITY_INVALID = "IDENTITY_INVALID"
    PIPELINE_FAILED = "PIPELINE_FAILED"


class CombinedTemporalError(ValueError):
    def __init__(self, code: CombinedTemporalFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class EvidenceSegment:
    segment_id: int
    start_byte: int
    end_byte: int
    text: str


__all__ = [
    "CombinedTemporalError",
    "CombinedTemporalFailureCode",
    "EvidenceSegment",
]
