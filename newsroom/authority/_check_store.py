from __future__ import annotations

from ._check_store_commit import _CheckStoreCommitMixin
from ._check_store_integrity import _CheckIntegrityMixin
from ._check_store_read import _CheckStoreReadMixin
from ._check_store_support import _CheckStoreSupport
from ._source_registry_store import _SourceRegistryAuthorityStore


class _CheckAuthorityStore(
    _CheckIntegrityMixin,
    _CheckStoreReadMixin,
    _CheckStoreCommitMixin,
    _CheckStoreSupport,
    _SourceRegistryAuthorityStore,
):
    """Private single-writer Check and source-lineage authority store."""


__all__ = ["_CheckAuthorityStore"]
