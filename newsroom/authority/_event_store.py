from __future__ import annotations

from ._event_store_base import _EventStoreBase
from ._event_store_commit import _EventStoreCommitMixin
from ._event_store_read import _EventStoreReadMixin


class _EventAuthorityStore(
    _EventStoreCommitMixin, _EventStoreReadMixin, _EventStoreBase
):
    """Private SQLite authority writer and policy-bounded metadata source."""


__all__ = ["_EventAuthorityStore"]
