from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ._capability import _CapabilityIssuer
from ._event_store import _EventAuthorityStore
from ._security import _AuthorizationRequest
from .auth import AuthenticationProof
from .canonical import digest_canonical
from .models import SemanticCommand
from .persistence import (
    AuthorityCommands,
    AuthorityEvents,
    CommittedCommand,
    EventProvenanceRecord,
    LedgerEventRecord,
    CommandResultRecord,
)
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp


@dataclass(frozen=True, slots=True)
class _ReadDefinition:
    operation_type: str
    required_scope: str
    event_type: str

    @property
    def digest(self) -> str:
        return digest_canonical(
            {
                "version": "authority-read-v1",
                "operation_type": self.operation_type,
                "required_scope": self.required_scope,
                "event_type": self.event_type,
                "security_scope": "authority.metadata",
                "retention_scope": "authority.audit",
            }
        )


_EVENTS_READ = _ReadDefinition(
    operation_type="read:ledger_events",
    required_scope="authority.events.read",
    event_type="ledger.events.read",
)
_AUDIT_READ = _ReadDefinition(
    operation_type="read:authority_audit",
    required_scope="authority.audit.read",
    event_type="authority.audit.read",
)


class _ReadBoundary:
    def __init__(
        self,
        *,
        store: _EventAuthorityStore,
        authenticator: Any,
        authorizer: Any,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._clock = clock

    def _authorize(
        self,
        proof: AuthenticationProof,
        definition: _ReadDefinition,
        *,
        semantic_value: dict[str, object],
    ) -> None:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        stable_digest = digest_canonical(
            {
                "read_definition_digest": definition.digest,
                "semantic_value": semantic_value,
            }
        )
        unsigned = {
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": definition.operation_type,
            "required_scope": definition.required_scope,
            "stable_semantic_request_digest": stable_digest,
            "command_definition_digest": definition.digest,
            "aggregate_type": "authority_metadata",
            "aggregate_id": "authority-metadata",
            "event_type": definition.event_type,
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "authority_read_v1",
            "trust_scope": "OBSERVED",
            "security_scope": "authority.metadata",
            "retention_scope": "authority.audit",
            "object_class": None,
            "allowed_use": None,
        }
        request = _AuthorizationRequest(
            authentication_context_id=authentication.authentication_context_id,
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type=definition.operation_type,
            required_scope=definition.required_scope,
            stable_semantic_request_digest=stable_digest,
            command_definition_digest=definition.digest,
            aggregate_type="authority_metadata",
            aggregate_id="authority-metadata",
            event_type=definition.event_type,
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="authority_read_v1",
            trust_scope="OBSERVED",
            security_scope="authority.metadata",
            retention_scope="authority.audit",
            object_class=None,
            allowed_use=None,
            request_digest=digest_canonical(unsigned),
        )
        decision = self._authorizer.authorize(authentication, request, now=now)
        if decision.authentication_context_id != authentication.authentication_context_id:
            raise PermissionError("reader authorization context mismatch")
        if decision.authorization_request_digest != request.request_digest:
            raise PermissionError("reader authorization request mismatch")
        decision.require_allowed()

    def events_after(
        self, ledger_seq: int, limit: int, proof: AuthenticationProof
    ) -> tuple[LedgerEventRecord, ...]:
        self._authorize(
            proof,
            _EVENTS_READ,
            semantic_value={"after_ledger_seq": ledger_seq, "limit": limit},
        )
        return self._store.events_after(ledger_seq, limit=limit)

    def provenance(
        self, event_id: str, proof: AuthenticationProof
    ) -> EventProvenanceRecord:
        self._authorize(
            proof,
            _AUDIT_READ,
            semantic_value={"event_id": event_id},
        )
        return self._store.event_provenance(event_id)

    def command_result(
        self, command_id: str, proof: AuthenticationProof
    ) -> CommandResultRecord:
        self._authorize(
            proof,
            _AUDIT_READ,
            semantic_value={"command_id": command_id},
        )
        return self._store.command_result(command_id)


class AuthorityEventSystem:
    """Composed public facades without a public mutation store."""

    __slots__ = ("commands", "events", "__close")

    def __init__(
        self,
        *,
        commands: AuthorityCommands,
        events: AuthorityEvents,
        close: Callable[[], None],
    ) -> None:
        self.commands = commands
        self.events = events
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> AuthorityEventSystem:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def open_authority_event_system(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    authenticator: Any,
    authorizer: Any,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> AuthorityEventSystem:
    """Open the single-writer A2a authority system.

    The returned object exposes authenticated command and metadata facades only.
    The SQLite store, capability issuer and direct mutation methods remain private.
    """

    issuer = _CapabilityIssuer()
    store: _EventAuthorityStore | None = None
    try:
        store = _EventAuthorityStore(
            path,
            issuer=issuer,
            command_service_version=command_service_version,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
        )
        command_boundary = CommandService(
            registry=registry,
            payload_schemas=payload_schemas,
            authenticator=authenticator,
            authorizer=authorizer,
            committed_lookup=store,
            clock=clock,
            _issuer=issuer,
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

        return AuthorityEventSystem(
            commands=AuthorityCommands(execute),
            events=AuthorityEvents(
                read_boundary.events_after,
                read_boundary.provenance,
                read_boundary.command_result,
            ),
            close=store.close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise
