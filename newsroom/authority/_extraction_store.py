from __future__ import annotations

from ._discovery_store import _DiscoveryAuthorityStore
from ._extraction_store_commit import _ExtractionStoreCommitMixin
from ._extraction_store_integrity import _ExtractionIntegrityMixin
from ._extraction_store_read import _ExtractionStoreReadMixin
from ._extraction_store_support import _ExtractionStoreSupport


class _ExtractionAuthorityStore(
    _ExtractionIntegrityMixin,
    _ExtractionStoreReadMixin,
    _ExtractionStoreCommitMixin,
    _ExtractionStoreSupport,
    _DiscoveryAuthorityStore,
):
    """Private single-writer Extraction Run and proposal authority store."""


__all__ = ["_ExtractionAuthorityStore"]
