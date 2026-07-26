from __future__ import annotations

from collections.abc import Iterable

from newsroom.projection.complete import (
    CompleteProjectionProfile,
    FullTextIndexContract,
    VectorIndexContract,
)

from ._complete_state import _expected_complete_projection_state
from .complete_models import (
    CompleteProjectionBatch,
    CompleteProjectionIdentity,
    CompleteProjectionState,
)


def expected_complete_projection_state(
    identity: CompleteProjectionIdentity,
    checkpoint_ledger_seq: int,
    expected_batches: Iterable[CompleteProjectionBatch],
    *,
    fulltext: FullTextIndexContract,
    vector: VectorIndexContract,
    profile: CompleteProjectionProfile,
) -> CompleteProjectionState:
    """Build the exact complete derivative state from retained authority batches."""

    return _expected_complete_projection_state(
        identity,
        checkpoint_ledger_seq,
        expected_batches,
        fulltext=fulltext,
        vector=vector,
        profile=profile,
    )


__all__ = ["expected_complete_projection_state"]
