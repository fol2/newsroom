from __future__ import annotations

from ._check_store_read_core import _CheckStoreReadCoreMixin
from ._check_store_read_decisions import _CheckStoreReadDecisionMixin


class _CheckStoreReadMixin(
    _CheckStoreReadDecisionMixin,
    _CheckStoreReadCoreMixin,
):
    """Exact canonical rehydration for Increment 3C authority records."""


__all__ = ["_CheckStoreReadMixin"]
