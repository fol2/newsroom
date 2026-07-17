from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ._blob_store import _BlobStore
from ._capability import _CapabilityIssuer
from ._event_system import _ReadBoundary
from ._object_service import _ObjectLifecycleService
from ._object_store import _ObjectAuthorityStore
from .auth import AuthenticationProof
from .models import SemanticCommand
from .objects import (
    AuthorityObjects,
    ObjectAdmissionRegistry,
    ObjectLimits,
    StaticRightsResolver,
)
from .persistence import AuthorityCommands, AuthorityEvents, CommittedCommand
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp


class AuthorityObjectSystem:
    """Composed A2b facades without exposing blob or SQLite mutation objects."""

    __slots__ = ("commands", "events", "objects", "__close")

    def __init__(
        self,
        *,
        commands: AuthorityCommands,
        events: AuthorityEvents,
        objects: AuthorityObjects,
        close: Callable[[], None],
    ) -> None:
        self.commands = commands
        self.events = events
        self.objects = objects
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> AuthorityObjectSystem:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def open_authority_object_system(
    *,
    database_path: Path,
    object_root: Path,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    admission_registry: ObjectAdmissionRegistry,
    rights_resolver: StaticRightsResolver,
    limits: ObjectLimits,
    authenticator: Any,
    authorizer: Any,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    blob_store_factory: Callable[..., _BlobStore] = _BlobStore,
) -> AuthorityObjectSystem:
    issuer = _CapabilityIssuer()
    store: _ObjectAuthorityStore | None = None
    try:
        blob_store = blob_store_factory(object_root, limits=limits)
        store = _ObjectAuthorityStore(
            database_path,
            issuer=issuer,
            blob_store=blob_store,
            command_service_version=command_service_version,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
        )
        command_boundary = CommandService(
            registry=command_registry,
            payload_schemas=payload_schemas,
            authenticator=authenticator,
            authorizer=authorizer,
            admission_lookup=store,
            committed_lookup=store,
            clock=clock,
            _issuer=issuer,
        )
        object_boundary = _ObjectLifecycleService(
            store=store,
            admission_registry=admission_registry,
            rights_resolver=rights_resolver,
            limits=limits,
            authenticator=authenticator,
            authorizer=authorizer,
            issuer=issuer,
            clock=clock,
        )
        read_boundary = _ReadBoundary(
            store=store,
            authenticator=authenticator,
            authorizer=authorizer,
            clock=clock,
        )

        def execute(
            command: SemanticCommand, proof: AuthenticationProof
        ) -> CommittedCommand:
            grant = command_boundary._authorize_for_commit(command, proof=proof)
            return store.commit(grant)  # type: ignore[union-attr]

        return AuthorityObjectSystem(
            commands=AuthorityCommands(execute),
            events=AuthorityEvents(
                read_boundary.events_after,
                read_boundary.provenance,
                read_boundary.command_result,
            ),
            objects=AuthorityObjects(
                admit=object_boundary.admit,
                hydrate=object_boundary.hydrate,
                revoke=object_boundary.revoke,
                delete=object_boundary.delete_blob,
                pin=object_boundary.pin_recovery,
                release_pin=object_boundary.release_recovery_pin,
                collect=object_boundary.collect_garbage,
            ),
            close=store.close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise
