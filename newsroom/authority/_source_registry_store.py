from __future__ import annotations

from ._event_store import _EventAuthorityStore
from ._source_registry_store_common import _SourceRegistryStoreSupport
from ._source_registry_store_definitions import (
    _SourceRegistryDefinitionCommitMixin,
)
from ._source_registry_store_integrity import _SourceRegistryIntegrityMixin
from ._source_registry_store_lineage import _SourceRegistryLineageCommitMixin
from ._source_registry_store_read import _SourceRegistryReadMixin


class _SourceRegistryAuthorityStore(
    _SourceRegistryIntegrityMixin,
    _SourceRegistryReadMixin,
    _SourceRegistryLineageCommitMixin,
    _SourceRegistryDefinitionCommitMixin,
    _SourceRegistryStoreSupport,
    _EventAuthorityStore,
):
    """Private single-writer source registry over the authoritative ledger."""


__all__ = ["_SourceRegistryAuthorityStore"]
