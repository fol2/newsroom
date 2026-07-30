from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from newsroom.entities.policy import merge_entity_authority_registries
from newsroom.entities.types import EntityReadPolicy

from ._capability import _CapabilityIssuer
from ._entity_boundary import _EntityBoundary
from ._entity_facade import GovernedEntityRecords
from ._entity_store import _EntityAuthorityStore
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp


class GovernedEntityAuthoritySystem:
    __slots__ = ("entities", "__close")

    def __init__(self, *, entities: GovernedEntityRecords, close: Callable[[], None]) -> None:
        self.entities = entities
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> "GovernedEntityAuthoritySystem":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def open_governed_entity_authority_system(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    authenticator: Any,
    authorizer: Any,
    read_policy: EntityReadPolicy,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> GovernedEntityAuthoritySystem:
    merged_registry, merged_schemas = merge_entity_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _EntityAuthorityStore | None = None
    try:
        store = _EntityAuthorityStore(
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
        boundary = _EntityBoundary(
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

        return GovernedEntityAuthoritySystem(
            entities=GovernedEntityRecords(
                admit_mention=boundary.admit_mention,
                propose_resolution=boundary.propose_resolution,
                decide_resolution=boundary.decide_resolution,
                bind_resolution_dependency=boundary.bind_resolution_dependency,
                merge_entities=boundary.merge_entities,
                split_entity=boundary.split_entity,
                reverse_lineage=boundary.reverse_lineage,
                mention=boundary.mention,
                proposal=boundary.proposal,
                proposal_version=boundary.proposal_version,
                decision=boundary.decision,
                entity=boundary.entity,
                entity_version=boundary.entity_version,
                aliases=boundary.aliases,
                preferred=boundary.preferred,
                projection_events_after=boundary.projection_events_after,
                admission_guard=boundary.admission_guard,
                dependency=boundary.dependency,
                dependent_admission_guard=boundary.dependent_admission_guard,
                merge_decision=boundary.merge_decision,
                split_decision=boundary.split_decision,
                reversal_decision=boundary.reversal_decision,
            ),
            close=close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise


__all__ = [
    "GovernedEntityAuthoritySystem",
    "GovernedEntityRecords",
    "open_governed_entity_authority_system",
]
