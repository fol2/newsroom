from __future__ import annotations

from pathlib import Path

from ._editorial_relation_store import _EditorialRelationAuthorityStore
from ._graphiti_adapter_store_commit import _GraphitiAdapterCommitMixin
from ._graphiti_adapter_store_common import _GraphitiAdapterStoreSupport
from ._graphiti_adapter_store_integrity import _GraphitiAdapterIntegrityMixin
from ._graphiti_adapter_store_read import _GraphitiAdapterReadMixin


class _GraphitiAdapterAuthorityStore(
    _GraphitiAdapterIntegrityMixin,
    _GraphitiAdapterReadMixin,
    _GraphitiAdapterCommitMixin,
    _GraphitiAdapterStoreSupport,
    _EditorialRelationAuthorityStore,
):
    """Private sole-writer authority for proposal-only adapter attempts."""

    def __init__(self, *args, workspace_root: Path, **kwargs) -> None:
        if not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
            raise ValueError("Graphiti workspace root must be an absolute Path")
        self._workspace_root = workspace_root
        super().__init__(*args, **kwargs)


__all__ = ["_GraphitiAdapterAuthorityStore"]
