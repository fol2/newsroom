from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from newsroom.extraction.policy import merge_extraction_authority_registries
from newsroom.extraction.producer import DeterministicFixtureExtractor
from newsroom.extraction.types import ExtractionReadPolicy

from ._capability import _CapabilityIssuer
from ._extraction_boundary import _ExtractionBoundary
from ._extraction_facade import GovernedExtractionRecords
from ._extraction_store import _ExtractionAuthorityStore
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp


class GovernedExtractionAuthoritySystem:
    __slots__ = ("extraction", "__close")

    def __init__(
        self,
        *,
        extraction: GovernedExtractionRecords,
        close: Callable[[], None],
    ) -> None:
        self.extraction = extraction
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> "GovernedExtractionAuthoritySystem":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> None:
        self.close()


def open_governed_extraction_authority_system(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    authenticator: Any,
    authorizer: Any,
    read_policy: ExtractionReadPolicy,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> GovernedExtractionAuthoritySystem:
    merged_registry, merged_schemas = merge_extraction_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _ExtractionAuthorityStore | None = None
    try:
        store = _ExtractionAuthorityStore(
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
        boundary = _ExtractionBoundary(
            store=store,
            command_service=command_service,
            authenticator=authenticator,
            authorizer=authorizer,
            read_policy=read_policy,
            producer=DeterministicFixtureExtractor(),
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

        return GovernedExtractionAuthoritySystem(
            extraction=GovernedExtractionRecords(
                register_contract=boundary.register_contract,
                execute=boundary.execute,
                contract=boundary.contract,
                metadata=boundary.metadata,
                run_history=boundary.run_history,
                proposals=boundary.proposals,
                raw_output=boundary.raw_output,
            ),
            close=close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise


__all__ = [
    "GovernedExtractionAuthoritySystem",
    "GovernedExtractionRecords",
    "open_governed_extraction_authority_system",
]
