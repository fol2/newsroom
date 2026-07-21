from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._capability import _CapabilityIssuer
from ._event_system import _ReadBoundary
from ._projection_store import _ProjectionAuthorityStore
from ._security import _AuthorizationRequest
from .auth import AuthenticationProof
from .canonical import digest_canonical
from .models import InlinePayload, SemanticCommand
from .persistence import (
    AuthorityCommands,
    AuthorityEvents,
    CommittedCommand,
    EventReadPolicy,
)
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp
from newsroom.projection.models import (
    DeliveryRecordView,
    ProjectionDeadLetterView,
    ProjectionDeliveryRequest,
    ProjectionFamilyRegistrationRequest,
    ProjectionFamilyView,
    ProjectionGapResolutionRequest,
    ProjectionGapView,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationTransitionRequest,
    ProjectionGenerationView,
    ProjectionReadPolicy,
    ProjectionStatusMetadata,
    ProjectionStateError,
)
from newsroom.projection.policy import (
    PROJECTION_COMMAND_TYPES,
    ProjectionContractRegistry,
    merge_projection_authority_registries,
)


_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "projection-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
        "golden_vectors": [{"name": "empty", "size": 0}],
    }
)


class NativeProjections:
    """Authenticated projection authority facade; no direct store is exposed."""

    __slots__ = (
        "__register_family",
        "__create_generation",
        "__transition_generation",
        "__record_delivery",
        "__resolve_gap",
        "__status",
        "__generations",
        "__gaps",
        "__dead_letters",
    )

    def __init__(
        self,
        *,
        register_family: Callable[[ProjectionFamilyRegistrationRequest, AuthenticationProof], ProjectionFamilyView],
        create_generation: Callable[[ProjectionGenerationCreateRequest, AuthenticationProof], ProjectionGenerationView],
        transition_generation: Callable[[ProjectionGenerationTransitionRequest, AuthenticationProof], ProjectionGenerationView],
        record_delivery: Callable[[ProjectionDeliveryRequest, AuthenticationProof], DeliveryRecordView],
        resolve_gap: Callable[[ProjectionGapResolutionRequest, AuthenticationProof], ProjectionGapView],
        status: Callable[[str, AuthenticationProof], ProjectionStatusMetadata],
        generations: Callable[[str, int, AuthenticationProof], tuple[ProjectionGenerationView, ...]],
        gaps: Callable[[ProjectionGenerationId, int, AuthenticationProof], tuple[ProjectionGapView, ...]],
        dead_letters: Callable[[ProjectionGenerationId, int, AuthenticationProof], tuple[ProjectionDeadLetterView, ...]],
    ) -> None:
        self.__register_family = register_family
        self.__create_generation = create_generation
        self.__transition_generation = transition_generation
        self.__record_delivery = record_delivery
        self.__resolve_gap = resolve_gap
        self.__status = status
        self.__generations = generations
        self.__gaps = gaps
        self.__dead_letters = dead_letters

    def register_family(self, request: ProjectionFamilyRegistrationRequest, *, proof: AuthenticationProof) -> ProjectionFamilyView:
        return self.__register_family(request, proof)

    def create_generation(self, request: ProjectionGenerationCreateRequest, *, proof: AuthenticationProof) -> ProjectionGenerationView:
        return self.__create_generation(request, proof)

    def transition_generation(self, request: ProjectionGenerationTransitionRequest, *, proof: AuthenticationProof) -> ProjectionGenerationView:
        return self.__transition_generation(request, proof)

    def record_delivery(self, request: ProjectionDeliveryRequest, *, proof: AuthenticationProof) -> DeliveryRecordView:
        return self.__record_delivery(request, proof)

    def resolve_gap(self, request: ProjectionGapResolutionRequest, *, proof: AuthenticationProof) -> ProjectionGapView:
        return self.__resolve_gap(request, proof)

    def status(self, family_id: str, *, proof: AuthenticationProof) -> ProjectionStatusMetadata:
        return self.__status(family_id, proof)

    def generations(self, family_id: str, *, limit: int = 100, proof: AuthenticationProof) -> tuple[ProjectionGenerationView, ...]:
        return self.__generations(family_id, limit, proof)

    def gaps(self, generation_id: ProjectionGenerationId, *, limit: int = 100, proof: AuthenticationProof) -> tuple[ProjectionGapView, ...]:
        return self.__gaps(generation_id, limit, proof)

    def dead_letters(self, generation_id: ProjectionGenerationId, *, limit: int = 100, proof: AuthenticationProof) -> tuple[ProjectionDeadLetterView, ...]:
        return self.__dead_letters(generation_id, limit, proof)


class NativeProjectionAuthoritySystem:
    __slots__ = ("commands", "events", "projections", "__close")

    def __init__(
        self,
        *,
        commands: AuthorityCommands,
        events: AuthorityEvents,
        projections: NativeProjections,
        close: Callable[[], None],
    ) -> None:
        self.commands = commands
        self.events = events
        self.projections = projections
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> NativeProjectionAuthoritySystem:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _ProjectionBoundary:
    def __init__(
        self,
        *,
        store: _ProjectionAuthorityStore,
        contracts: ProjectionContractRegistry,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        read_policy: ProjectionReadPolicy,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._contracts = contracts
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._read_policy = read_policy
        self._clock = clock

    def _grant(
        self,
        *,
        command_type: str,
        aggregate_id: Any,
        expected_version: int,
        payload: dict[str, object],
        idempotency_key: str,
        proof: AuthenticationProof,
    ):
        command = SemanticCommand(
            command_type=command_type,
            aggregate_id=aggregate_id,
            expected_aggregate_version=expected_version,
            payload=InlinePayload(payload),
            idempotency_key=idempotency_key,
        )
        return self._command_service._authorize_for_commit(command, proof=proof)

    def register_family(self, request: ProjectionFamilyRegistrationRequest, proof: AuthenticationProof) -> ProjectionFamilyView:
        # Authenticate before consulting retained authority so an invalid proof
        # cannot use the mutation surface as an existence oracle.  A retry after
        # a registry rollout must use the exact definition originally registered,
        # otherwise the same idempotency key would describe a different payload.
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        try:
            definition = self._store.projection_family_definition(
                request.family_id
            )
        except ProjectionStateError:
            definition = self._contracts.family(request.family_id)
        grant = self._grant(
            command_type="projection.family.register",
            aggregate_id=definition.authority_aggregate_id,
            expected_version=0,
            payload={
                "family_id": definition.family_id,
                "definition_digest": definition.digest,
            },
            idempotency_key=request.idempotency_key,
            proof=proof,
        )
        if (
            grant.authentication.principal_id != authentication.principal_id
            or grant.authentication.authority_domain
            != authentication.authority_domain
        ):
            raise PermissionError(
                "projection family registration authority changed during lookup"
            )
        return self._store.register_family(grant, definition)

    def create_generation(self, request: ProjectionGenerationCreateRequest, proof: AuthenticationProof) -> ProjectionGenerationView:
        self._contracts.family(request.family_id)
        grant = self._grant(
            command_type="projection.generation.create",
            aggregate_id=request.generation_id.as_aggregate_id(),
            expected_version=0,
            payload={
                "generation_id": str(request.generation_id),
                "family_id": request.family_id,
                "reason_code": request.reason_code,
            },
            idempotency_key=request.idempotency_key,
            proof=proof,
        )
        return self._store.create_generation(
            grant,
            generation_id=request.generation_id,
            family_id=request.family_id,
            reason_code=request.reason_code,
        )

    def transition_generation(self, request: ProjectionGenerationTransitionRequest, proof: AuthenticationProof) -> ProjectionGenerationView:
        grant = self._grant(
            command_type="projection.generation.transition",
            aggregate_id=request.generation_id.as_aggregate_id(),
            expected_version=request.expected_authority_version,
            payload={
                "generation_id": str(request.generation_id),
                "target_state": request.target_state.value,
                "validated_through_ledger_seq": request.validated_through_ledger_seq,
                "reason_code": request.reason_code,
            },
            idempotency_key=request.idempotency_key,
            proof=proof,
        )
        return self._store.transition_generation(
            grant,
            generation_id=request.generation_id,
            target_state=request.target_state,
            validated_through_ledger_seq=request.validated_through_ledger_seq,
            reason_code=request.reason_code,
        )

    def record_delivery(self, request: ProjectionDeliveryRequest, proof: AuthenticationProof) -> DeliveryRecordView:
        grant = self._grant(
            command_type="projection.delivery.record",
            aggregate_id=request.generation_id.as_aggregate_id(),
            expected_version=request.expected_authority_version,
            payload={
                "generation_id": str(request.generation_id),
                "ledger_seq": request.ledger_seq,
                "outcome": request.outcome.value,
                "error_code": request.error_code,
            },
            idempotency_key=request.idempotency_key,
            proof=proof,
        )
        return self._store.record_delivery(
            grant,
            generation_id=request.generation_id,
            ledger_seq=request.ledger_seq,
            outcome=request.outcome,
            error_code=request.error_code,
        )

    def resolve_gap(self, request: ProjectionGapResolutionRequest, proof: AuthenticationProof) -> ProjectionGapView:
        grant = self._grant(
            command_type="projection.gap.resolve",
            aggregate_id=request.generation_id.as_aggregate_id(),
            expected_version=request.expected_authority_version,
            payload={
                "generation_id": str(request.generation_id),
                "gap_id": str(request.gap_id),
                "reason_code": request.reason_code,
            },
            idempotency_key=request.idempotency_key,
            proof=proof,
        )
        return self._store.resolve_gap(
            grant,
            generation_id=request.generation_id,
            gap_id=request.gap_id,
            reason_code=request.reason_code,
        )

    def _authenticate_read(self, proof: AuthenticationProof):
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        self._read_policy.require_principal(authentication.principal_id)
        return now, authentication

    def _authorize_read(
        self,
        *,
        family_id: str,
        operation: str,
        semantic_value: dict[str, object],
        proof: AuthenticationProof | None = None,
        authenticated: tuple[UtcTimestamp, Any] | None = None,
    ) -> None:
        if authenticated is None:
            if proof is None:
                raise TypeError("projection read requires authentication proof")
            now, authentication = self._authenticate_read(proof)
        else:
            now, authentication = authenticated
        definition = self._store.projection_family_definition(family_id)
        self._read_policy.require_family(definition)
        stable_digest = digest_canonical(
            {
                "projection_read_policy_digest": self._read_policy.digest,
                "operation": operation,
                "semantic_value": semantic_value,
            }
        )
        operation_type = f"read:{self._read_policy.purpose}:{operation}"
        unsigned = {
            "authentication_context_id": str(authentication.authentication_context_id),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": operation_type,
            "required_scope": self._read_policy.required_scope,
            "stable_semantic_request_digest": stable_digest,
            "command_definition_digest": self._read_policy.digest,
            "aggregate_type": "projection_metadata",
            "aggregate_id": family_id,
            "event_type": "projection.metadata.read",
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "projection_read_v1",
            "payload_schema_contract_version": "projection-read-contract-v1",
            "payload_schema_contract_digest": _READ_SCHEMA_DIGEST,
            "payload_canonicalizer_version": "projection-read-none-v1",
            "trust_scope": "ADMITTED",
            "security_scope": definition.security_scope,
            "retention_scope": definition.retention_scope,
            "object_class": None,
            "allowed_use": None,
        }
        request = _AuthorizationRequest(
            authentication_context_id=authentication.authentication_context_id,
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type=operation_type,
            required_scope=self._read_policy.required_scope,
            stable_semantic_request_digest=stable_digest,
            command_definition_digest=self._read_policy.digest,
            aggregate_type="projection_metadata",
            aggregate_id=family_id,
            event_type="projection.metadata.read",
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="projection_read_v1",
            payload_schema_contract_version="projection-read-contract-v1",
            payload_schema_contract_digest=_READ_SCHEMA_DIGEST,
            payload_canonicalizer_version="projection-read-none-v1",
            trust_scope="ADMITTED",
            security_scope=definition.security_scope,
            retention_scope=definition.retention_scope,
            object_class=None,
            allowed_use=None,
            request_digest=digest_canonical(unsigned),
        )
        decision = self._authorizer.authorize(authentication, request, now=now)
        if decision.authentication_context_id != authentication.authentication_context_id:
            raise PermissionError("projection read authorization context mismatch")
        if decision.authorization_request_digest != request.request_digest:
            raise PermissionError("projection read authorization request mismatch")
        decision.require_allowed()

    def status(self, family_id: str, proof: AuthenticationProof) -> ProjectionStatusMetadata:
        self._authorize_read(
            family_id=family_id,
            operation="status",
            semantic_value={"family_id": family_id},
            proof=proof,
        )
        return self._store.projection_status(family_id)

    def generations(self, family_id: str, limit: int, proof: AuthenticationProof) -> tuple[ProjectionGenerationView, ...]:
        self._read_policy.require_limit(limit)
        self._authorize_read(
            family_id=family_id,
            operation="generations",
            semantic_value={"family_id": family_id, "limit": limit},
            proof=proof,
        )
        return self._store.projection_generations(family_id, limit)

    def gaps(self, generation_id: ProjectionGenerationId, limit: int, proof: AuthenticationProof) -> tuple[ProjectionGapView, ...]:
        self._read_policy.require_limit(limit)
        authenticated = self._authenticate_read(proof)
        generation = self._store.projection_generation(generation_id)
        self._authorize_read(
            family_id=generation.family_id,
            operation="gaps",
            semantic_value={"generation_id": str(generation_id), "limit": limit},
            authenticated=authenticated,
        )
        return self._store.projection_gaps(generation_id, limit)

    def dead_letters(self, generation_id: ProjectionGenerationId, limit: int, proof: AuthenticationProof) -> tuple[ProjectionDeadLetterView, ...]:
        self._read_policy.require_limit(limit)
        authenticated = self._authenticate_read(proof)
        generation = self._store.projection_generation(generation_id)
        self._authorize_read(
            family_id=generation.family_id,
            operation="dead_letters",
            semantic_value={"generation_id": str(generation_id), "limit": limit},
            authenticated=authenticated,
        )
        return self._store.projection_dead_letters(generation_id, limit)


def open_native_projection_authority_system(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    contracts: ProjectionContractRegistry,
    authenticator: Any,
    authorizer: Any,
    event_read_policy: EventReadPolicy,
    projection_read_policy: ProjectionReadPolicy,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> NativeProjectionAuthoritySystem:
    merged_registry, merged_schemas = merge_projection_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _ProjectionAuthorityStore | None = None
    try:
        store = _ProjectionAuthorityStore(
            path,
            issuer=issuer,
            command_registry=merged_registry,
            payload_schemas=merged_schemas,
            command_service_version=command_service_version,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
            contracts=contracts,
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
        event_read_boundary = _ReadBoundary(
            store=store,
            policy=event_read_policy,
            authenticator=authenticator,
            authorizer=authorizer,
            clock=clock,
        )
        projection_boundary = _ProjectionBoundary(
            store=store,
            contracts=contracts,
            command_service=command_service,
            authenticator=authenticator,
            authorizer=authorizer,
            read_policy=projection_read_policy,
            clock=clock,
        )

        def execute(command: SemanticCommand, proof: AuthenticationProof) -> CommittedCommand:
            if command.command_type in PROJECTION_COMMAND_TYPES:
                raise PermissionError("projection commands are internal authority operations")
            grant = command_service._authorize_for_commit(command, proof=proof)
            return store.commit(grant)  # type: ignore[union-attr]

        return NativeProjectionAuthoritySystem(
            commands=AuthorityCommands(execute),
            events=AuthorityEvents(
                policy_id=event_read_policy.policy_id,
                read=event_read_boundary.events_after,
                provenance=event_read_boundary.provenance,
                result=event_read_boundary.command_result,
            ),
            projections=NativeProjections(
                register_family=projection_boundary.register_family,
                create_generation=projection_boundary.create_generation,
                transition_generation=projection_boundary.transition_generation,
                record_delivery=projection_boundary.record_delivery,
                resolve_gap=projection_boundary.resolve_gap,
                status=projection_boundary.status,
                generations=projection_boundary.generations,
                gaps=projection_boundary.gaps,
                dead_letters=projection_boundary.dead_letters,
            ),
            close=store.close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise


__all__ = [
    "NativeProjectionAuthoritySystem",
    "NativeProjections",
    "open_native_projection_authority_system",
]
