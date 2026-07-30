from __future__ import annotations

from ._editorial_relation_store_commit import _EditorialRelationCommitMixin
from ._editorial_relation_store_common import _EditorialRelationStoreSupport
from ._editorial_relation_store_integrity import _EditorialRelationIntegrityMixin
from ._editorial_relation_store_projection import _EditorialRelationProjectionMixin
from ._editorial_relation_store_read import _EditorialRelationReadMixin
from ._entity_store import _EntityAuthorityStore


class _EditorialRelationAuthorityStore(
    _EditorialRelationIntegrityMixin,
    _EditorialRelationReadMixin,
    _EditorialRelationProjectionMixin,
    _EditorialRelationCommitMixin,
    _EditorialRelationStoreSupport,
    _EntityAuthorityStore,
):
    """Private single-writer editorial relation authority over checked SQLite."""

    def __init__(
        self,
        *args,
        allow_current_projection_rebuild: bool = False,
        **kwargs,
    ):
        self._allow_editorial_relation_projection_rebuild = (
            allow_current_projection_rebuild
        )
        super().__init__(*args, **kwargs)


__all__ = ["_EditorialRelationAuthorityStore"]
