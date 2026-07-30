from __future__ import annotations

from ._entity_store_commit import _EntityCommitMixin
from ._entity_store_common import _EntityStoreSupport
from ._entity_store_integrity import _EntityIntegrityMixin
from ._entity_store_read import _EntityReadMixin
from ._extraction_store import _ExtractionAuthorityStore


class _EntityAuthorityStore(
    _EntityIntegrityMixin,
    _EntityReadMixin,
    _EntityCommitMixin,
    _EntityStoreSupport,
    _ExtractionAuthorityStore,
):
    """Private single-writer entity authority over the checked SQLite ledger."""


__all__ = ["_EntityAuthorityStore"]
