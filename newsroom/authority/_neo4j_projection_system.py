from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from ._capability import _CapabilityIssuer
from ._event_system import _ReadBoundary
from ._projection_store import (
    _ProjectionAuthorityStore,
    _ProjectionDeliverySource,
)
from ._projection_system import NativeProjections, _ProjectionBoundary
from .auth import AuthenticationProof
from .canonical import digest_canonical
from .models import SemanticCommand
from .persistence import (
    AuthorityCommands,
    AuthorityEvents,
    CommittedCommand,
    EventReadPolicy,
)
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import TrustScope, UtcTimestamp
from newsroom.projection.mapping import (
    ProjectionIdentitySource,
    StructuralIdentityContext,
    canonical_node_id,
)
from newsroom.projection.models import (
    DeliveryRecordView,
    ProjectionContractError,
    ProjectionDeliveryOutcome,
    ProjectionDeliveryRequest,
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionGenerationValidationRequest,
    ProjectionGenerationValidationView,
    ProjectionReadPolicy,
    ProjectionStateError,
)
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter
from newsroom.projection.neo4j.models import (
    Neo4jApplyResult,
    Neo4jAuthorityCommitPending,
    Neo4jCompatibility,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jReadError,
    Neo4jStructuralRead,
    Neo4jWriteError,
    StructuralBatch,
    StructuralDeliveryRequest,
    StructuralGenerationValidationRequest,
    StructuralNode,
    StructuralRebuildRequest,
    StructuralRebuildResult,
    StructuralReadMetadata,
    StructuralReadRequest,
    StructuralReadResponse,
    StructuralRelation,
)
from newsroom.projection.neo4j.qualification import (
    neo4j_compatibility_digest,
)
from newsroom.projection.policy import (
    PROJECTION_COMMAND_TYPES,
    ProjectionContractRegistry,
    merge_projection_authority_registries,
)


class _StructuralGraphAdapter(Protocol):
    def verify_compatibility(self) -> Neo4jCompatibility:
        ...

    def bootstrap_schema(self) -> None:
        ...

    def apply(self, batch: StructuralBatch) -> Neo4jApplyResult:
        ...

    def read(
        self,
        *,
        generation_id: str,
        canonical_ids: tuple[str, ...],
        maximum_ledger_seq: int,
        limit: int,
    ) -> Neo4jStructuralRead:
        ...

    def reconcile_generation(
        self,
        *,
        generation_id: str,
        expected_batches: tuple[StructuralBatch, ...],
    ) -> str:
        ...

    def cleanup_generation(self, generation_id: str) -> int:
        ...

    def close(self) -> None:
        ...


class Neo4jStructuralProjector:
    """Public B2 facade: exact delivery plus bounded non-authoritative read."""

    __slots__ = ("__deliver", "__read", "__rebuild", "__validate")

    def __init__(
        self,
        *,
        deliver: Callable[
            [StructuralDeliveryRequest, AuthenticationProof],
            DeliveryRecordView,
        ],
        read: Callable[
            [StructuralReadRequest, AuthenticationProof],
            StructuralReadResponse,
        ],
        rebuild: Callable[
            [StructuralRebuildRequest, AuthenticationProof],
            StructuralRebuildResult,
        ],
        validate_generation: Callable[
            [StructuralGenerationValidationRequest, AuthenticationProof],
            ProjectionGenerationValidationView,
        ],
    ) -> None:
        self.__deliver = deliver
        self.__read = read
        self.__rebuild = rebuild
        self.__validate = validate_generation

    def deliver(
        self,
        request: StructuralDeliveryRequest,
        *,
        proof: AuthenticationProof,
    ) -> DeliveryRecordView:
        return self.__deliver(request, proof)

    def read(
        self,
        request: StructuralReadRequest,
        *,
        proof: AuthenticationProof,
    ) -> StructuralReadResponse:
        return self.__read(request, proof)

    def rebuild(
        self,
        request: StructuralRebuildRequest,
        *,
        proof: AuthenticationProof,
    ) -> StructuralRebuildResult:
        return self.__rebuild(request, proof)

    def validate_generation(
        self,
        request: StructuralGenerationValidationRequest,
        *,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationValidationView:
        return self.__validate(request, proof)


class Neo4jProjectionAuthoritySystem:
    __slots__ = (
        "commands",
        "events",
        "projections",
        "structural",
        "compatibility",
        "__close",
    )

    def __init__(
        self,
        *,
        commands: AuthorityCommands,
        events: AuthorityEvents,
        projections: NativeProjections,
        structural: Neo4jStructuralProjector,
        compatibility: Neo4jCompatibility,
        close: Callable[[], None],
    ) -> None:
        self.commands = commands
        self.events = events
        self.projections = projections
        self.structural = structural
        self.compatibility = compatibility
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> Neo4jProjectionAuthoritySystem:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _Neo4jProjectionBoundary:
    def __init__(
        self,
        *,
        store: _ProjectionAuthorityStore,
        projection_boundary: _ProjectionBoundary,
        adapter: _StructuralGraphAdapter,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._projection_boundary = projection_boundary
        self._adapter = adapter
        self._clock = clock
        self._operation_lock = RLock()

    def deliver(
        self,
        request: StructuralDeliveryRequest,
        proof: AuthenticationProof,
    ) -> DeliveryRecordView:
        with self._operation_lock:
            return self._deliver_locked(request, proof)

    def _deliver_locked(
        self,
        request: StructuralDeliveryRequest,
        proof: AuthenticationProof,
    ) -> DeliveryRecordView:
        if not isinstance(request, StructuralDeliveryRequest):
            raise TypeError("structural delivery requires a typed request")

        applied_request = ProjectionDeliveryRequest(
            generation_id=request.generation_id,
            expected_authority_version=request.expected_authority_version,
            ledger_seq=request.ledger_seq,
            outcome=ProjectionDeliveryOutcome.APPLIED,
            idempotency_key=request.idempotency_key,
        )
        # Authentication and exact command authorization happen before any graph
        # effect.  The returned grant remains bound to the APPLIED transition.
        applied_grant = self._projection_boundary._authorize_delivery(
            applied_request,
            proof,
        )
        source = self._store.projection_delivery_source(
            request.generation_id,
            request.ledger_seq,
        )
        if (
            applied_grant.replay_of_command_id is None
            and source.generation.authority_aggregate_version
            != request.expected_authority_version
        ):
            raise ProjectionStateError(
                "projection generation authority version changed before graph apply"
            )
        if source.generation.state in {
            ProjectionGenerationState.RETIRED,
            ProjectionGenerationState.FAILED,
        }:
            raise ProjectionStateError(
                "terminal projection generation cannot accept graph delivery"
            )

        if source.mapping is None:
            return self._record_without_graph(
                request=request,
                proof=proof,
                outcome=ProjectionDeliveryOutcome.IGNORED_OPTIONAL,
                error_code=None,
            )

        try:
            batch = _build_structural_batch(source)
        except ProjectionContractError:
            if source.mapping.required:
                return self._record_without_graph(
                    request=request,
                    proof=proof,
                    outcome=ProjectionDeliveryOutcome.REQUIRED_UNSUPPORTED,
                    error_code="STRUCTURAL_MAPPING_UNSUPPORTED",
                )
            return self._record_without_graph(
                request=request,
                proof=proof,
                outcome=ProjectionDeliveryOutcome.IGNORED_OPTIONAL,
                error_code=None,
            )

        try:
            self._adapter.apply(batch)
        except Neo4jIdentityConflict:
            try:
                return self._record_without_graph(
                    request=request,
                    proof=proof,
                    outcome=ProjectionDeliveryOutcome.RETRYABLE_FAILURE,
                    error_code="NEO4J_IDENTITY_CONFLICT",
                )
            except ProjectionStateError as exc:
                if "already finalized" not in str(exc):
                    raise
                raise Neo4jIdentityConflict(
                    "Neo4j delivery identity conflicts with finalized B1 authority"
                ) from None
        except Neo4jWriteError:
            return self._record_without_graph(
                request=request,
                proof=proof,
                outcome=ProjectionDeliveryOutcome.RETRYABLE_FAILURE,
                error_code="NEO4J_WRITE_FAILURE",
            )

        try:
            return self._projection_boundary._commit_delivery(
                applied_grant,
                applied_request,
            )
        except Exception:
            # The graph marker is durable, but B1 did not confirm authoritative
            # progress.  A retry will observe a DUPLICATE graph delivery and
            # retry only the exact SQLite transition.
            raise Neo4jAuthorityCommitPending(
                "Neo4j delivery committed but B1 authority transition is pending"
            ) from None

    def rebuild(
        self,
        request: StructuralRebuildRequest,
        proof: AuthenticationProof,
    ) -> StructuralRebuildResult:
        with self._operation_lock:
            return self._rebuild_locked(request, proof)

    def _rebuild_locked(
        self,
        request: StructuralRebuildRequest,
        proof: AuthenticationProof,
    ) -> StructuralRebuildResult:
        if not isinstance(request, StructuralRebuildRequest):
            raise TypeError("structural rebuild requires a typed request")
        receipt = self._projection_boundary._begin_rebuild(request, proof)
        if receipt.generation.state is not ProjectionGenerationState.BUILDING:
            raise ProjectionStateError(
                "only a building generation can be destructively rebuilt"
            )

        deleted = self._adapter.cleanup_generation(str(request.generation_id))
        reapplied = 0
        recorded = 0
        ignored = 0
        blocked = 0
        for ledger_seq in range(1, request.through_ledger_seq + 1):
            source = self._store.projection_delivery_source(
                request.generation_id, ledger_seq
            )
            state = self._store.projection_rebuild_delivery_state(
                request.generation_id, ledger_seq
            )
            if source.mapping is None:
                ignored += 1
                continue
            if state is not None:
                if (
                    state.finalized
                    and state.outcome is ProjectionDeliveryOutcome.APPLIED
                ):
                    self._adapter.apply(_build_structural_batch(source))
                    reapplied += 1
                    continue
                if state.outcome is ProjectionDeliveryOutcome.IGNORED_OPTIONAL:
                    ignored += 1
                    continue
                if state.finalized:
                    blocked += 1
                    continue
                attempt_number = state.attempt_count + 1
            else:
                attempt_number = 1

            current = self._store.projection_generation(request.generation_id)
            delivery_key = "rebuild-delivery:" + digest_canonical(
                {
                    "rebuild_idempotency_key": request.idempotency_key,
                    "generation_id": str(request.generation_id),
                    "ledger_seq": ledger_seq,
                    "attempt_number": attempt_number,
                }
            )
            result = self.deliver(
                StructuralDeliveryRequest(
                    generation_id=request.generation_id,
                    expected_authority_version=(
                        current.authority_aggregate_version
                    ),
                    ledger_seq=ledger_seq,
                    idempotency_key=delivery_key,
                ),
                proof,
            )
            if result.outcome is ProjectionDeliveryOutcome.APPLIED:
                recorded += 1
            elif result.outcome is ProjectionDeliveryOutcome.IGNORED_OPTIONAL:
                ignored += 1
            else:
                blocked += 1

        metadata = self._store.projection_generation_metadata(
            request.generation_id
        )
        return StructuralRebuildResult(
            generation_id=request.generation_id,
            through_ledger_seq=request.through_ledger_seq,
            checkpoint_ledger_seq=metadata.contiguous_ledger_seq,
            rebuild_authority_event_id=receipt.authority_event_id,
            authority_command_replayed=receipt.replayed,
            deleted_graph_record_count=deleted,
            reapplied_delivery_count=reapplied,
            recorded_delivery_count=recorded,
            ignored_optional_count=ignored,
            blocked_delivery_count=blocked,
            serving_time=metadata.serving_time,
        )

    def reject_direct_validation(
        self,
        request: ProjectionGenerationValidationRequest,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationValidationView:
        if not isinstance(request, ProjectionGenerationValidationRequest):
            raise TypeError("projection validation requires a typed request")
        self._projection_boundary._authenticate(proof)
        raise ProjectionStateError(
            "Neo4j generation validation requires structural reconciliation"
        )

    def validate_generation(
        self,
        request: StructuralGenerationValidationRequest,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationValidationView:
        with self._operation_lock:
            return self._validate_generation_locked(request, proof)

    def _validate_generation_locked(
        self,
        request: StructuralGenerationValidationRequest,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationValidationView:
        if not isinstance(request, StructuralGenerationValidationRequest):
            raise TypeError("structural validation requires a typed request")
        authenticated = self._projection_boundary._authenticate(proof)
        metadata = self._store.projection_generation_metadata(
            request.generation_id
        )
        self._projection_boundary._authorize_management_operation(
            family_id=metadata.family.family_id,
            aggregate_id=str(request.generation_id),
            operation="neo4j-generation-reconcile",
            semantic_value={
                "generation_id": str(request.generation_id),
                "checkpoint_ledger_seq": request.checkpoint_ledger_seq,
                "reason_code": request.reason_code,
            },
            authenticated=authenticated,
        )
        if metadata.generation.state not in {
            ProjectionGenerationState.BUILDING,
            ProjectionGenerationState.VALIDATING,
        }:
            raise ProjectionStateError(
                "only building or validating generations can be reconciled"
            )
        if metadata.contiguous_ledger_seq != request.checkpoint_ledger_seq:
            raise ProjectionStateError(
                "structural validation must bind the exact authority checkpoint"
            )
        if metadata.open_gap_count or metadata.dead_letter_count:
            raise ProjectionStateError(
                "structural validation requires zero gaps and dead letters"
            )
        batches = self._expected_validation_batches(
            request.generation_id,
            request.checkpoint_ledger_seq,
        )
        compatibility = self._adapter.verify_compatibility()
        compatibility_digest = neo4j_compatibility_digest(compatibility)
        state_digest = self._adapter.reconcile_generation(
            generation_id=str(request.generation_id),
            expected_batches=batches,
        )
        authoritative_request = ProjectionGenerationValidationRequest(
            generation_id=request.generation_id,
            expected_authority_version=request.expected_authority_version,
            checkpoint_ledger_seq=request.checkpoint_ledger_seq,
            service_compatibility_digest=compatibility_digest,
            projection_state_digest=state_digest,
            reason_code=request.reason_code,
            idempotency_key=request.idempotency_key,
        )
        return self._projection_boundary.validate_generation(
            authoritative_request,
            proof,
        )

    def _expected_validation_batches(
        self,
        generation_id: ProjectionGenerationId,
        checkpoint_ledger_seq: int,
    ) -> tuple[StructuralBatch, ...]:
        batches: list[StructuralBatch] = []
        for ledger_seq in range(1, checkpoint_ledger_seq + 1):
            source = self._store.projection_delivery_source(
                generation_id,
                ledger_seq,
            )
            state = self._store.projection_rebuild_delivery_state(
                generation_id,
                ledger_seq,
            )
            if state is None:
                if source.mapping is None:
                    continue
                raise ProjectionStateError(
                    "authoritative checkpoint lacks a structural delivery state"
                )
            if (
                str(state.source_event_id) != source.event.event_id
                or state.source_event_digest != source.source_event_digest
            ):
                raise ProjectionStateError(
                    "structural delivery provenance differs from retained authority"
                )
            if not state.finalized:
                raise ProjectionStateError(
                    "structural validation encountered an unfinished delivery"
                )
            if state.outcome is ProjectionDeliveryOutcome.APPLIED:
                if source.mapping is None:
                    raise ProjectionStateError(
                        "applied delivery has no retained structural mapping"
                    )
                batches.append(_build_structural_batch(source))
                continue
            if state.outcome is ProjectionDeliveryOutcome.IGNORED_OPTIONAL:
                if source.mapping is not None and source.mapping.required:
                    raise ProjectionStateError(
                        "required structural mapping was ignored"
                    )
                continue
            raise ProjectionStateError(
                "structural validation encountered a failed delivery"
            )
        return tuple(batches)

    def read(
        self,
        request: StructuralReadRequest,
        proof: AuthenticationProof,
    ) -> StructuralReadResponse:
        if not isinstance(request, StructuralReadRequest):
            raise TypeError("structural read requires a typed request")
        self._projection_boundary._read_policy.require_limit(request.limit)
        authenticated = self._projection_boundary._authenticate_read(proof)
        metadata = self._store.projection_generation_metadata(
            request.generation_id
        )
        self._projection_boundary._authorize_read(
            family_id=metadata.family.family_id,
            operation="neo4j-structural",
            semantic_value={
                "generation_id": str(request.generation_id),
                "canonical_ids": list(request.canonical_ids),
                "query_valid_time": request.query_valid_time.to_text(),
                "limit": request.limit,
            },
            authenticated=authenticated,
        )
        if request.query_valid_time.value > metadata.serving_time.value:
            raise ProjectionContractError(
                "query_valid_time cannot be later than serving_time"
            )
        graph = self._adapter.read(
            generation_id=str(request.generation_id),
            canonical_ids=request.canonical_ids,
            maximum_ledger_seq=metadata.contiguous_ledger_seq,
            limit=request.limit,
        )
        if any(
            relation.ledger_seq > metadata.contiguous_ledger_seq
            for relation in graph.relations
        ):
            raise Neo4jReadError(
                "Neo4j returned relation beyond the authoritative watermark"
            )
        return StructuralReadResponse(
            metadata=StructuralReadMetadata(
                family_id=metadata.family.family_id,
                family_definition_version=(
                    metadata.family.definition_version
                ),
                projector_version=metadata.family.projector_version,
                ontology_contract_digest=(
                    metadata.family.ontology_contract_digest
                ),
                mapping_contract_digest=(
                    metadata.family.mapping_contract_digest
                ),
                generation_id=metadata.generation.generation_id,
                generation_state=metadata.generation.state,
                contiguous_ledger_seq=metadata.contiguous_ledger_seq,
                open_gap_count=metadata.open_gap_count,
                dead_letter_count=metadata.dead_letter_count,
                trust_scope=TrustScope.ADMITTED,
                query_valid_time=request.query_valid_time,
                serving_time=metadata.serving_time,
            ),
            nodes=graph.nodes,
            relations=graph.relations,
        )

    def _record_without_graph(
        self,
        *,
        request: StructuralDeliveryRequest,
        proof: AuthenticationProof,
        outcome: ProjectionDeliveryOutcome,
        error_code: str | None,
    ) -> DeliveryRecordView:
        return self._projection_boundary.record_delivery(
            ProjectionDeliveryRequest(
                generation_id=request.generation_id,
                expected_authority_version=(
                    request.expected_authority_version
                ),
                ledger_seq=request.ledger_seq,
                outcome=outcome,
                idempotency_key=request.idempotency_key,
                error_code=error_code,
            ),
            proof,
        )


def _build_structural_batch(
    source: _ProjectionDeliverySource,
) -> StructuralBatch:
    mapping = source.mapping
    if mapping is None:
        raise ProjectionContractError("structural source event is unmapped")
    if not source.payload_is_mapping and any(
        binding.identity_source is ProjectionIdentitySource.PAYLOAD_FIELD
        for binding in mapping.nodes
    ):
        raise ProjectionContractError(
            "structural event requires retained inline mapping payload"
        )
    event = source.event
    context = StructuralIdentityContext(
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        aggregate_version=event.aggregate_version,
        event_id=event.event_id,
        payload_id=event.payload_id,
        payload=source.payload,
    )
    node_by_alias: dict[str, StructuralNode] = {}
    for binding in mapping.nodes:
        canonical_id = canonical_node_id(binding, context)
        node_by_alias[binding.alias] = StructuralNode(
            canonical_id=canonical_id,
            node_type=binding.node_type,
            identity_source=binding.identity_source.value,
            identity_reference_digest=digest_canonical(
                {
                    "identity_contract": "newsroom-neo4j-node-reference-v1",
                    "canonical_id": canonical_id,
                    "node_type": binding.node_type.value,
                    "identity_source": binding.identity_source.value,
                    "payload_field": binding.payload_field,
                }
            ),
            first_ledger_seq=event.ledger_seq,
            first_source_event_id=event.event_id,
            first_source_event_digest=source.source_event_digest,
        )
    recorded_at = UtcTimestamp.parse(event.recorded_at)
    trust_scope = TrustScope(event.trust_scope)
    relations: list[StructuralRelation] = []
    for binding in mapping.relations:
        source_node = node_by_alias[binding.source_alias]
        target_node = node_by_alias[binding.target_alias]
        relation_key = digest_canonical(
            {
                "relation_contract": "newsroom-neo4j-structural-relation-v1",
                "generation_id": str(source.generation.generation_id),
                "relation_type": binding.relation_type.value,
                "source_canonical_id": source_node.canonical_id,
                "target_canonical_id": target_node.canonical_id,
                "ledger_seq": event.ledger_seq,
                "source_event_id": event.event_id,
                "source_event_digest": source.source_event_digest,
            }
        )
        relations.append(
            StructuralRelation(
                relation_key=relation_key,
                relation_type=binding.relation_type,
                source_canonical_id=source_node.canonical_id,
                target_canonical_id=target_node.canonical_id,
                ledger_seq=event.ledger_seq,
                source_event_id=event.event_id,
                source_event_type=event.event_type,
                source_event_digest=source.source_event_digest,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                aggregate_version=event.aggregate_version,
                payload_id=event.payload_id,
                payload_digest=event.payload_digest,
                object_admission_id=event.object_admission_id,
                principal_id=event.principal_id,
                trust_scope=trust_scope,
                security_scope=event.security_scope,
                retention_scope=event.retention_scope,
                recorded_at=recorded_at,
            )
        )
    return StructuralBatch(
        generation_id=source.generation.generation_id,
        family_id=source.family.family_id,
        family_definition_version=source.family.definition_version,
        projector_version=source.family.projector_version,
        ontology_contract_digest=source.family.ontology_contract_digest,
        mapping_contract_digest=source.family.mapping_contract_digest,
        ledger_seq=event.ledger_seq,
        source_event_id=event.event_id,
        source_event_type=event.event_type,
        source_event_digest=source.source_event_digest,
        nodes=tuple(node_by_alias[key] for key in sorted(node_by_alias)),
        relations=tuple(
            sorted(relations, key=lambda value: value.relation_key)
        ),
        tombstoned_object_admission_ids=(
            source.tombstoned_object_admission_ids
        ),
    )


def _open_with_adapter(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    contracts: ProjectionContractRegistry,
    authenticator: Any,
    authorizer: Any,
    event_read_policy: EventReadPolicy,
    projection_read_policy: ProjectionReadPolicy,
    adapter: _StructuralGraphAdapter,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> Neo4jProjectionAuthoritySystem:
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
        compatibility = adapter.verify_compatibility()
        adapter.bootstrap_schema()
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
        graph_boundary = _Neo4jProjectionBoundary(
            store=store,
            projection_boundary=projection_boundary,
            adapter=adapter,
            clock=clock,
        )

        def execute(
            command: SemanticCommand,
            proof: AuthenticationProof,
        ) -> CommittedCommand:
            if command.command_type in PROJECTION_COMMAND_TYPES:
                raise PermissionError(
                    "projection commands are internal authority operations"
                )
            grant = command_service._authorize_for_commit(
                command,
                proof=proof,
            )
            return store.commit(grant)  # type: ignore[union-attr]

        closed = False

        def close() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            try:
                adapter.close()
            finally:
                store.close()  # type: ignore[union-attr]

        return Neo4jProjectionAuthoritySystem(
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
                transition_generation=(
                    projection_boundary.transition_generation
                ),
                validate_generation=graph_boundary.reject_direct_validation,
                promote_generation=projection_boundary.promote_generation,
                record_delivery=projection_boundary.record_delivery,
                resolve_gap=projection_boundary.resolve_gap,
                status=projection_boundary.status,
                generations=projection_boundary.generations,
                validation=projection_boundary.validation,
                promotions=projection_boundary.promotions,
                gaps=projection_boundary.gaps,
                dead_letters=projection_boundary.dead_letters,
            ),
            structural=Neo4jStructuralProjector(
                deliver=graph_boundary.deliver,
                read=graph_boundary.read,
                rebuild=graph_boundary.rebuild,
                validate_generation=graph_boundary.validate_generation,
            ),
            compatibility=compatibility,
            close=close,
        )
    except Exception:
        try:
            adapter.close()
        finally:
            if store is not None:
                store.close()
        raise


def open_neo4j_projection_authority_system(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    contracts: ProjectionContractRegistry,
    authenticator: Any,
    authorizer: Any,
    event_read_policy: EventReadPolicy,
    projection_read_policy: ProjectionReadPolicy,
    neo4j_config: Neo4jProjectorConfig,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> Neo4jProjectionAuthoritySystem:
    adapter = _open_neo4j_adapter(neo4j_config)
    return _open_with_adapter(
        path=path,
        registry=registry,
        payload_schemas=payload_schemas,
        contracts=contracts,
        authenticator=authenticator,
        authorizer=authorizer,
        event_read_policy=event_read_policy,
        projection_read_policy=projection_read_policy,
        adapter=adapter,
        command_service_version=command_service_version,
        busy_timeout_ms=busy_timeout_ms,
        clock=clock,
    )


__all__ = [
    "Neo4jProjectionAuthoritySystem",
    "Neo4jStructuralProjector",
    "open_neo4j_projection_authority_system",
]
