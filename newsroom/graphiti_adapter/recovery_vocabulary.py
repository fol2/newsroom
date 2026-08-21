"""Typed recovery classifications shared across Graphiti execution and accounting."""

from __future__ import annotations

from enum import StrEnum


class GraphitiRecoveryClassification(StrEnum):
    RECOVERED_AMBIGUOUS = "RECOVERED_AMBIGUOUS"
    RECOVERED_IMMUTABLE_COMPLETE = "RECOVERED_IMMUTABLE_COMPLETE"
    RECOVERED_PENDING_PROCESS_DEATH = "RECOVERED_PENDING_PROCESS_DEATH"
    ROLLED_BACK_AMBIGUOUS_EFFECT = "ROLLED_BACK_AMBIGUOUS_EFFECT"


DURABLE_NO_DISPATCH_RECOVERIES = frozenset(
    {
        GraphitiRecoveryClassification.RECOVERED_AMBIGUOUS,
        GraphitiRecoveryClassification.RECOVERED_IMMUTABLE_COMPLETE,
        GraphitiRecoveryClassification.RECOVERED_PENDING_PROCESS_DEATH,
    }
)


__all__ = [
    "DURABLE_NO_DISPATCH_RECOVERIES",
    "GraphitiRecoveryClassification",
]
