from __future__ import annotations

from ._event_store import _EventAuthorityStore
from ._extraction_store_commit import _ExtractionCommitMixin
from ._extraction_store_common import _ExtractionStoreSupport
from ._extraction_store_integrity import _ExtractionIntegrityMixin
from ._extraction_store_read import _ExtractionReadMixin


class _ExtractionAuthorityStore(
    _ExtractionIntegrityMixin,
    _ExtractionReadMixin,
    _ExtractionCommitMixin,
    _ExtractionStoreSupport,
    _EventAuthorityStore,
):
    """Private single-writer Extraction Run authority over the SQLite ledger."""


__all__ = ["_ExtractionAuthorityStore"]
