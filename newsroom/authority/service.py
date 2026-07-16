from __future__ import annotations

from typing import Callable

from .auth import (
    AuthenticationProof,
    Authenticator,
    AuthorizationRequest,
    Authorizer,
)
from .canonical import digest_canonical
from .models import CommittedCommand, SemanticCommand
from .objects import GovernedObjectStore
from .store import AuthorityStore, UnknownObjectReference
from .types import UtcTimestamp


class CommandService:
    """Authenticated and authorised command boundary.

    The caller never supplies an authoritative principal or scope. Those values
    come only from the authenticator and server-side authoriser passed to this
    service. There is intentionally no anonymous or local-writer fallback.
    """

    def __init__(
        self,
        *,
        store: AuthorityStore,
        authenticator: Authenticator,
        authorizer: Authorizer,
        object_store: GovernedObjectStore | None = None,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        if store is None or authenticator is None or authorizer is None:
            raise ValueError(
                "command service requires store, authenticator and authorizer"
            )
        self._store = store
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._object_store = object_store
        self._clock = clock

    def execute(
        self, command: SemanticCommand, *, proof: AuthenticationProof
    ) -> CommittedCommand:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        authorization = self._authorizer.authorize(
            authentication,
            AuthorizationRequest(
                command_type=command.command_type,
                aggregate_type=command.aggregate_type,
                aggregate_id=str(command.aggregate_id),
            ),
        )
        authorization.require_allowed()

        if command.payload_object_ref is not None:
            if self._object_store is None:
                raise UnknownObjectReference(
                    "object-backed command requires a governed object store"
                )
            object_path = self._object_store.path_for(command.payload_object_ref)
            if not object_path.exists():
                raise UnknownObjectReference(
                    "object-backed command references missing governed bytes"
                )
            self._object_store.verify(command.payload_object_ref)
            if not self._store.has_governed_object(command.payload_object_ref):
                raise UnknownObjectReference(
                    "object-backed command references an unregistered object"
                )

        idempotency_namespace = digest_canonical(
            {
                "authority_domain": authentication.authority_domain,
                "principal_id": authentication.principal_id,
                "command_type": command.command_type,
            }
        )
        semantic_request_digest = digest_canonical(
            {
                "command_type": command.command_type,
                "aggregate_type": command.aggregate_type,
                "aggregate_id": str(command.aggregate_id),
                "expected_aggregate_version": command.expected_aggregate_version,
                "payload_schema_version": command.payload_schema_version,
                "payload_digest": command.payload_digest,
                "payload_object_ref": command.payload_object_ref,
                "event_type": command.event_type,
                "event_schema_version": command.event_schema_version,
                "trust_scope": command.trust_scope.value,
                "security_scope": command.security_scope,
                "retention_scope": command.retention_scope,
                "correlation_id": command.correlation_id,
                "causation_id": command.causation_id,
                "producer_version": command.producer_version,
                "issued_at": command.issued_at.to_text(),
                "principal_id": authentication.principal_id,
                "authority_domain": authentication.authority_domain,
                "authorization_policy_version": (
                    authorization.authorization_policy_version
                ),
                "effective_scope_digest": authorization.effective_scope_digest,
            }
        )
        return self._store.commit_command(
            command=command,
            authentication=authentication,
            authorization=authorization,
            idempotency_namespace=idempotency_namespace,
            semantic_request_digest=semantic_request_digest,
        )
