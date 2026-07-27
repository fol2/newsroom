from __future__ import annotations

from ._check_store_commit_core import _CheckStoreCommitCoreMixin
from ._check_store_commit_decisions import _CheckStoreCommitDecisionMixin
from ._check_store_commit_findings import _CheckStoreCommitFindingMixin


class _CheckStoreCommitMixin(
    _CheckStoreCommitFindingMixin,
    _CheckStoreCommitDecisionMixin,
    _CheckStoreCommitCoreMixin,
):
    """Single-transaction Increment 3C authority commits."""


__all__ = ["_CheckStoreCommitMixin"]
