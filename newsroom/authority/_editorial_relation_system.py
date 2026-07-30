from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from newsroom.relations.editorial_models import EditorialRelationReadPolicy
from newsroom.relations.editorial_policy import (
    merge_editorial_relation_authority_registries,
)

from ._capability import _CapabilityIssuer
from ._editorial_relation_boundary import _EditorialRelationBoundary
from ._editorial_relation_facade import GovernedEditorialRelations
from ._editorial_relation_store import _EditorialRelationAuthorityStore
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp


class GovernedEditorialRelationAuthoritySystem:
    __slots__ = ("relations", "__close")

    def __init__(
        self,
        *,
        relations: GovernedEditorialRelations,
        close: Callable[[], None],
    ) -> None:
        self.relations = relations
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> "GovernedEditorialRelationAuthoritySystem":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def open_governed_editorial_relation_authority_system(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    authenticator: Any,
    authorizer: Any,
    read_policy: EditorialRelationReadPolicy,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> GovernedEditorialRelationAuthoritySystem:
    merged_registry, merged_schemas = merge_editorial_relation_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _EditorialRelationAuthorityStore | None = None
    try:
        store = _EditorialRelationAuthorityStore(
            path,
            issuer=issuer,
            command_registry=merged_registry,
            payload_schemas=merged_schemas,
            command_service_version=command_service_version,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
        )
        command_service = CommandService(
            registry=merged_registry,
            payload_schemas=merged_schemas,
            authenticator=authenticator,
            authorizer=authorizer,
            committed_lookup=store,
            clock=clock,
            _issuer=issuer,
        )
        boundary = _EditorialRelationBoundary(
            store=store,
            command_service=command_service,
            authenticator=authenticator,
            authorizer=authorizer,
            read_policy=read_policy,
            clock=clock,
        )
        closed = False

        def close() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            assert store is not None
            store.close()

        return GovernedEditorialRelationAuthoritySystem(
            relations=GovernedEditorialRelations(
                propose=boundary.propose,
                decide=boundary.decide,
                proposal=boundary.proposal,
                proposal_version=boundary.proposal_version,
                decision=boundary.decision,
                assertion=boundary.assertion,
                current=boundary.current,
                current_relations=boundary.current_relations,
                projection_events_after=boundary.projection_events_after,
            ),
            close=close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise


__all__ = [
    "GovernedEditorialRelationAuthoritySystem",
    "GovernedEditorialRelations",
    "open_governed_editorial_relation_authority_system",
]
