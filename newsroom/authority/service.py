from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ._capability import (
    _AuthorizedCommandGrant,
    _CapabilityIssuer,
    _ResolvedPayload,
    _derive_idempotency_namespace,
    _derive_stable_semantic_request_digest,
)
from ._security import _AuthorizationRequest
from .auth import AuthenticationProof
from .canonical import digest_bytes, digest_canonical
from .models import (
    CommandDefinition,
    CommittedCommandIdentity,
    InlinePayload,
    NoPayload,
    ObjectAdmissionDescriptor,
    ObjectAdmissionPayload,
    SemanticCommand,
)
from .policy import CommandRegistry, PayloadSchemaRegistry
from .types import PayloadMode, UtcTimestamp


class ObjectAdmissionLookup(Protocol):
    def resolve(self, admission_id: object) -> ObjectAdmissionDescriptor:
        ...


class CommittedCommandLookup(Protocol):
    """Read-only lookup used before current-definition selection on a retry."""

    def find(
        self, *, idempotency_namespace: str, idempotency_key: str
    ) -> CommittedCommandIdentity | None:
        ...


class IdempotencyIdentityConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthorizationReceipt:
    authentication_context_id: str
    authorization_decision_id: str
    authorization_request_digest: str
    authorization_policy_version: str
    effective_scope_digest: str
    idempotency_namespace: str
    stable_semantic_request_digest: str
    command_definition_version: str
    command_definition_digest: str
    aggregate_type: str
    event_type: str
    event_schema_version: int
    payload_mode: str
    payload_schema_version: str
    payload_schema_contract_version: str
    payload_schema_contract_digest: str
    payload_canonicalizer_version: str
    payload_digest: str
    trust_scope: str
    security_scope: str
    retention_scope: str
    replay_of_command_id: str | None


class CommandService:
    """The only public authority-bearing command boundary in Increment 1A."""

    def __init__(
        self,
        *,
        registry: CommandRegistry,
        payload_schemas: PayloadSchemaRegistry,
        authenticator: object,
        authorizer: object,
        admission_lookup: ObjectAdmissionLookup | None = None,
        committed_lookup: CommittedCommandLookup | None = None,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
        _issuer: _CapabilityIssuer | None = None,
    ) -> None:
        if (
            registry is None
            or payload_schemas is None
            or authenticator is None
            or authorizer is None
        ):
            raise ValueError(
                "command service requires definition, payload-schema and "
                "security adapters"
            )
        self._registry = registry
        self._payload_schemas = payload_schemas
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._admission_lookup = admission_lookup
        self._committed_lookup = committed_lookup
        self._clock = clock
        self._issuer = _issuer or _CapabilityIssuer(
            command_registry=registry, payload_schemas=payload_schemas
        )
        if _issuer is not None:
            self._issuer.bind_contracts(registry, payload_schemas)
        self._validate_replay_horizon()

    def _validate_replay_horizon(self) -> None:
        """Fail composition when any retained definition lost its schema contract."""

        for definition in self._registry.definitions():
            self._payload_schemas.resolve_exact(
                definition.payload_schema_version,
                definition.payload_mode,
                definition.payload_schema_contract_version,
                definition.payload_schema_contract_digest,
                definition.payload_canonicalizer_version,
            )

    def authorize(
        self, command: SemanticCommand, *, proof: AuthenticationProof
    ) -> AuthorizationReceipt:
        grant = self._authorize_for_commit(command, proof=proof)
        return AuthorizationReceipt(
            authentication_context_id=str(
                grant.authentication.authentication_context_id
            ),
            authorization_decision_id=str(
                grant.authorization.authorization_decision_id
            ),
            authorization_request_digest=(
                grant.authorization_request.request_digest
            ),
            authorization_policy_version=(
                grant.authorization.authorization_policy_version
            ),
            effective_scope_digest=grant.authorization.effective_scope_digest,
            idempotency_namespace=grant.idempotency_namespace,
            stable_semantic_request_digest=(
                grant.stable_semantic_request_digest
            ),
            command_definition_version=grant.definition.definition_version,
            command_definition_digest=grant.definition.digest,
            aggregate_type=grant.definition.aggregate_type,
            event_type=grant.definition.event_type,
            event_schema_version=grant.definition.event_schema_version,
            payload_mode=grant.payload.kind,
            payload_schema_version=grant.payload.schema_version,
            payload_schema_contract_version=(
                grant.payload.schema_contract_version
            ),
            payload_schema_contract_digest=(
                grant.payload.schema_contract_digest
            ),
            payload_canonicalizer_version=grant.payload.canonicalizer_version,
            payload_digest=grant.payload.digest,
            trust_scope=grant.definition.trust_scope.value,
            security_scope=grant.definition.security_scope,
            retention_scope=grant.definition.retention_scope,
            replay_of_command_id=grant.replay_of_command_id,
        )

    def _authorize_for_commit(
        self, command: SemanticCommand, *, proof: AuthenticationProof
    ) -> _AuthorizedCommandGrant:
        if not isinstance(command, SemanticCommand):
            raise TypeError("command must be SemanticCommand")
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)

        current_definition = self._registry.resolve(command.command_type)
        idempotency_namespace = _derive_idempotency_namespace(
            authentication, current_definition
        )
        existing = (
            None
            if self._committed_lookup is None
            else self._committed_lookup.find(
                idempotency_namespace=idempotency_namespace,
                idempotency_key=command.idempotency_key,
            )
        )
        if existing is None:
            definition = current_definition
        else:
            self._validate_existing_identity(
                existing,
                authentication_domain=authentication.authority_domain,
                principal_id=authentication.principal_id,
                command=command,
                idempotency_namespace=idempotency_namespace,
            )
            definition = self._registry.resolve_exact(
                command.command_type,
                existing.command_definition_version,
                existing.command_definition_digest,
            )
            retained_namespace = _derive_idempotency_namespace(
                authentication, definition
            )
            if retained_namespace != idempotency_namespace:
                raise IdempotencyIdentityConflict(
                    "retained definition changed the durable idempotency namespace"
                )

        payload = self._resolve_payload(command, definition)
        stable_semantic_request_digest = (
            _derive_stable_semantic_request_digest(
                definition=definition,
                aggregate_id=str(command.aggregate_id),
                expected_aggregate_version=command.expected_aggregate_version,
                payload=payload,
            )
        )
        if (
            existing is not None
            and existing.stable_semantic_request_digest
            != stable_semantic_request_digest
        ):
            raise IdempotencyIdentityConflict(
                "idempotency identity belongs to a different semantic command"
            )

        request_value = {
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": f"command:{definition.command_type}",
            "required_scope": definition.required_scope,
            "stable_semantic_request_digest": (
                stable_semantic_request_digest
            ),
            "command_definition_digest": definition.digest,
            "aggregate_type": definition.aggregate_type,
            "aggregate_id": str(command.aggregate_id),
            "event_type": definition.event_type,
            "event_schema_version": definition.event_schema_version,
            "payload_mode": definition.payload_mode.value,
            "payload_schema_version": definition.payload_schema_version,
            "payload_schema_contract_version": (
                definition.payload_schema_contract_version
            ),
            "payload_schema_contract_digest": (
                definition.payload_schema_contract_digest
            ),
            "payload_canonicalizer_version": (
                definition.payload_canonicalizer_version
            ),
            "trust_scope": definition.trust_scope.value,
            "security_scope": definition.security_scope,
            "retention_scope": definition.retention_scope,
            "object_class": definition.required_object_class,
            "allowed_use": definition.required_allowed_use,
        }
        request_digest = digest_canonical(request_value)
        authorization_request = _AuthorizationRequest(
            authentication_context_id=(
                authentication.authentication_context_id
            ),
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type=f"command:{definition.command_type}",
            required_scope=definition.required_scope,
            stable_semantic_request_digest=(
                stable_semantic_request_digest
            ),
            command_definition_digest=definition.digest,
            aggregate_type=definition.aggregate_type,
            aggregate_id=str(command.aggregate_id),
            event_type=definition.event_type,
            event_schema_version=definition.event_schema_version,
            payload_mode=definition.payload_mode.value,
            payload_schema_version=definition.payload_schema_version,
            payload_schema_contract_version=(
                definition.payload_schema_contract_version
            ),
            payload_schema_contract_digest=(
                definition.payload_schema_contract_digest
            ),
            payload_canonicalizer_version=(
                definition.payload_canonicalizer_version
            ),
            trust_scope=definition.trust_scope.value,
            security_scope=definition.security_scope,
            retention_scope=definition.retention_scope,
            object_class=definition.required_object_class,
            allowed_use=definition.required_allowed_use,
            request_digest=request_digest,
        )
        authorization = self._authorizer.authorize(
            authentication, authorization_request, now=now
        )
        if (
            authorization.authentication_context_id
            != authentication.authentication_context_id
        ):
            raise PermissionError(
                "authorizer returned a context-mismatched decision"
            )
        if authorization.authorization_request_digest != request_digest:
            raise PermissionError(
                "authorizer returned a request-mismatched decision"
            )
        authorization.require_allowed()

        correlation_id = (
            None
            if command.correlation_id is None
            else str(command.correlation_id)
        )
        causation_kind = (
            None
            if command.causation is None
            else command.causation.kind.value
        )
        causation_identifier = (
            None
            if command.causation is None
            else command.causation.identifier
        )
        causation_external_system = (
            None
            if command.causation is None
            else command.causation.external_system
        )
        return self._issuer.issue(
            command_type=definition.command_type,
            aggregate_id=str(command.aggregate_id),
            expected_aggregate_version=command.expected_aggregate_version,
            definition=definition,
            payload=payload,
            authentication=authentication,
            authorization_request=authorization_request,
            authorization=authorization,
            idempotency_namespace=idempotency_namespace,
            idempotency_key=command.idempotency_key,
            stable_semantic_request_digest=(
                stable_semantic_request_digest
            ),
            correlation_id=correlation_id,
            causation_kind=causation_kind,
            causation_identifier=causation_identifier,
            causation_external_system=causation_external_system,
            replay_of_command_id=(
                None if existing is None else existing.command_id
            ),
        )

    @staticmethod
    def _validate_existing_identity(
        existing: CommittedCommandIdentity,
        *,
        authentication_domain: str,
        principal_id: str,
        command: SemanticCommand,
        idempotency_namespace: str,
    ) -> None:
        if existing.authority_domain != authentication_domain:
            raise IdempotencyIdentityConflict(
                "existing command authority domain differs"
            )
        if existing.principal_id != principal_id:
            raise IdempotencyIdentityConflict(
                "existing command principal differs"
            )
        if existing.command_type != command.command_type:
            raise IdempotencyIdentityConflict(
                "existing command type differs"
            )
        if existing.idempotency_namespace != idempotency_namespace:
            raise IdempotencyIdentityConflict(
                "existing idempotency namespace differs"
            )
        if existing.idempotency_key != command.idempotency_key:
            raise IdempotencyIdentityConflict(
                "existing idempotency key differs"
            )

    def _resolve_payload(
        self, command: SemanticCommand, definition: CommandDefinition
    ) -> _ResolvedPayload:
        payload = command.payload
        schema = self._payload_schemas.resolve_exact(
            definition.payload_schema_version,
            definition.payload_mode,
            definition.payload_schema_contract_version,
            definition.payload_schema_contract_digest,
            definition.payload_canonicalizer_version,
        )
        common = {
            "schema_version": definition.payload_schema_version,
            "schema_contract_version": schema.contract_version,
            "schema_contract_digest": schema.contract_digest,
            "canonicalizer_version": (
                schema.canonicalizer_implementation_version
            ),
        }
        if definition.payload_mode is PayloadMode.INLINE:
            if not isinstance(payload, InlinePayload):
                raise ValueError("command requires bounded inline payload")
            inline_bytes = schema.canonicalize(payload.value)
            if len(inline_bytes) > definition.max_inline_bytes:
                raise ValueError(
                    "inline payload exceeds command-definition limit"
                )
            return _ResolvedPayload(
                kind=PayloadMode.INLINE.value,
                digest=digest_bytes(inline_bytes),
                inline_bytes=inline_bytes,
                object_admission_id=None,
                blob_digest=None,
                object_class=None,
                allowed_use=None,
                **common,
            )
        if definition.payload_mode is PayloadMode.NO_PAYLOAD:
            if not isinstance(payload, NoPayload):
                raise ValueError("command requires explicit NO_PAYLOAD")
            canonical = schema.canonicalize(None)
            if canonical != b"":
                raise ValueError(
                    "NO_PAYLOAD schema must canonicalize to empty bytes"
                )
            return _ResolvedPayload(
                kind=PayloadMode.NO_PAYLOAD.value,
                digest=digest_bytes(b""),
                inline_bytes=b"",
                object_admission_id=None,
                blob_digest=None,
                object_class=None,
                allowed_use=None,
                **common,
            )
        if not isinstance(payload, ObjectAdmissionPayload):
            raise ValueError(
                "command requires governed object-admission payload"
            )
        if self._admission_lookup is None:
            raise ValueError(
                "object-admission command requires an admission resolver"
            )
        descriptor = self._admission_lookup.resolve(payload.admission_id)
        if not descriptor.active:
            raise ValueError("object admission is not active")
        if descriptor.object_class != definition.required_object_class:
            raise ValueError(
                "object admission class is not permitted by command definition"
            )
        if descriptor.allowed_use != definition.required_allowed_use:
            raise ValueError(
                "object admission use is not permitted by command definition"
            )
        if descriptor.security_scope != definition.security_scope:
            raise ValueError(
                "object admission security scope does not match command policy"
            )
        if descriptor.retention_scope != definition.retention_scope:
            raise ValueError(
                "object admission retention scope does not match command policy"
            )
        schema.canonicalize(descriptor)
        return _ResolvedPayload(
            kind=PayloadMode.OBJECT_ADMISSION.value,
            digest=descriptor.blob_digest,
            inline_bytes=None,
            object_admission_id=descriptor.admission_id,
            blob_digest=descriptor.blob_digest,
            object_class=descriptor.object_class,
            allowed_use=descriptor.allowed_use,
            **common,
        )
