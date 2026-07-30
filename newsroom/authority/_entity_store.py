from __future__ import annotations

from ._entity_store_commit import _EntityCommitMixin
from ._entity_store_common import _EntityStoreSupport
from ._entity_store_integrity import _EntityIntegrityMixin
from ._entity_store_lineage import _EntityLineageMixin
from ._entity_store_projection import _EntityProjectionMixin
from ._entity_store_read import _EntityReadMixin
from ._extraction_store import _ExtractionAuthorityStore


class _EntityAuthorityStore(
    _EntityIntegrityMixin,
    _EntityReadMixin,
    _EntityProjectionMixin,
    _EntityLineageMixin,
    _EntityCommitMixin,
    _EntityStoreSupport,
    _ExtractionAuthorityStore,
):
    """Private single-writer entity authority over the checked SQLite ledger."""

    def __init__(self, *args, allow_projection_rebuild: bool = False, **kwargs):
        self._allow_projection_rebuild = allow_projection_rebuild
        super().__init__(*args, **kwargs)


__all__ = ["_EntityAuthorityStore"]
