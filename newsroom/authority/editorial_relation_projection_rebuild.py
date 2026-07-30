from __future__ import annotations

from pathlib import Path
from typing import Callable

from newsroom.relations.editorial_models import EditorialRelationCurrentView
from newsroom.relations.editorial_policy import (
    merge_editorial_relation_authority_registries,
)

from ._capability import _CapabilityIssuer
from ._editorial_relation_store import _EditorialRelationAuthorityStore
from .policy import CommandRegistry, PayloadSchemaRegistry
from .types import UtcTimestamp


def rebuild_governed_editorial_relation_current_projection(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> tuple[EditorialRelationCurrentView, ...]:
    """Rebuild missing current relation rows from checked immutable authority.

    This operational seam is deliberately absent from the public relation facade.
    It validates the complete ledger and immutable relation history, revalidates
    current rights for every assertion, refuses divergent existing rows and
    inserts only missing derivative assertion-head rows in one transaction.
    """

    merged_registry, merged_schemas = merge_editorial_relation_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store = _EditorialRelationAuthorityStore(
        path,
        issuer=issuer,
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
        command_service_version=command_service_version,
        busy_timeout_ms=busy_timeout_ms,
        clock=clock,
        allow_current_projection_rebuild=True,
    )
    try:
        return store.rebuild_editorial_current_projection()
    finally:
        store.close()


__all__ = ["rebuild_governed_editorial_relation_current_projection"]
