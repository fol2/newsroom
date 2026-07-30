from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from newsroom.entities.models import EntityPreferredIdentity
from newsroom.entities.policy import merge_entity_authority_registries

from ._capability import _CapabilityIssuer
from ._entity_store import _EntityAuthorityStore
from .policy import CommandRegistry, PayloadSchemaRegistry
from .types import UtcTimestamp


def rebuild_governed_entity_preferred_projection(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> tuple[EntityPreferredIdentity, ...]:
    """Rebuild missing preferred-identity rows from checked immutable authority.

    This is a dedicated operational seam, not a public proposal or decision API.
    It acquires the sole-writer lock, checks every non-projection authority record,
    revalidates current source/object rights for all entities, and inserts only
    rows absent from the derived projection.  Divergent existing rows fail closed.
    """

    merged_registry, merged_schemas = merge_entity_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store = _EntityAuthorityStore(
        path,
        issuer=issuer,
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
        command_service_version=command_service_version,
        busy_timeout_ms=busy_timeout_ms,
        clock=clock,
        allow_projection_rebuild=True,
    )
    try:
        return store.rebuild_preferred_projection()
    finally:
        store.close()


__all__ = ["rebuild_governed_entity_preferred_projection"]
