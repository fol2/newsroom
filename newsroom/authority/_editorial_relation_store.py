from __future__ import annotations

from ._editorial_relation_store_commit import _EditorialRelationCommitMixin
from ._editorial_relation_store_common import _EditorialRelationStoreSupport
from ._editorial_relation_store_integrity import _EditorialRelationIntegrityMixin
from ._editorial_relation_store_read import _EditorialRelationReadMixin
from ._entity_store import _EntityAuthorityStore


class _EditorialRelationAuthorityStore(
    _EditorialRelationIntegrityMixin,
    _EditorialRelationReadMixin,
    _EditorialRelationCommitMixin,
    _EditorialRelationStoreSupport,
    _EntityAuthorityStore,
):
    """Private single-writer editorial relation authority over checked SQLite."""


__all__ = ["_EditorialRelationAuthorityStore"]
