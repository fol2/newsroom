from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from newsroom.graphiti_adapter import GraphitiAdapterReadPolicy
from newsroom.graphiti_adapter.policy import (
    merge_graphiti_adapter_authority_registries,
)

from ._capability import _CapabilityIssuer
from ._graphiti_adapter_boundary import _GraphitiAdapterBoundary
from ._graphiti_adapter_facade import GovernedGraphitiProposalAdapter
from ._graphiti_adapter_store import _GraphitiAdapterAuthorityStore
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp


class GovernedGraphitiAdapterAuthoritySystem:
    __slots__ = ("graphiti", "__close")

    def __init__(
        self,
        *,
        graphiti: GovernedGraphitiProposalAdapter,
        close: Callable[[], None],
    ) -> None:
        self.graphiti = graphiti
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> "GovernedGraphitiAdapterAuthoritySystem":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def open_governed_graphiti_adapter_authority_system(
    *,
    path: Path,
    workspace_root: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    authenticator: Any,
    authorizer: Any,
    read_policy: GraphitiAdapterReadPolicy,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> GovernedGraphitiAdapterAuthoritySystem:
    merged_registry, merged_schemas = merge_graphiti_adapter_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _GraphitiAdapterAuthorityStore | None = None
    try:
        store = _GraphitiAdapterAuthorityStore(
            path,
            workspace_root=workspace_root,
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
        boundary = _GraphitiAdapterBoundary(
            store=store,
            command_service=command_service,
            authenticator=authenticator,
            authorizer=authorizer,
            read_policy=read_policy,
            workspace_root=workspace_root,
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

        return GovernedGraphitiAdapterAuthoritySystem(
            graphiti=GovernedGraphitiProposalAdapter(
                register_configuration=boundary.register_configuration,
                execute_attempt=boundary.execute_attempt,
                approve_replay=boundary.approve_replay,
                configuration=boundary.configuration,
                attempt=boundary.attempt,
                attempt_history=boundary.attempt_history,
                manifest_for_attempt=boundary.manifest_for_attempt,
                replay_source=boundary.replay_source,
            ),
            close=close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise


__all__ = [
    "GovernedGraphitiAdapterAuthoritySystem",
    "GovernedGraphitiProposalAdapter",
    "open_governed_graphiti_adapter_authority_system",
]
