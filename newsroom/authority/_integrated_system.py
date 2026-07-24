from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from ._capability import _CapabilityIssuer
from ._event_system import _ReadBoundary
from ._integrated_store import _IntegratedCandidateStore
from ._neo4j_projection_system import (
    _build_structural_batch,
    _open_structural_graph_adapter,
)
from ._projection_system import _ProjectionBoundary
from .auth import AuthenticationProof
from .models import InlinePayload, SemanticCommand
from .persistence import AuthorityEvents, EventReadPolicy
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp
from newsroom.integrated.models import (
    CandidateAdmissionRequest,
    CandidateAdmissionView,
    IntegratedFixtureManifest,
    IntegratedRetrievalContext,
    IntegratedStateError,
)
from newsroom.integrated.policy import (
    CANDIDATE_ADMISSION_COMMAND,
    merge_integrated_authority_registries,
)
from newsroom.projection.models import (
    ProjectionDeliveryOutcome,
    ProjectionReadPolicy,
    ProjectionStateError,
)
from newsroom.projection.neo4j.models import (
    Neo4jCompatibility,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jStructuralRead,
    StructuralBatch,
)
from newsroom.projection.neo4j.qualification import (
    neo4j_compatibility_digest,
)
from newsroom.projection.policy import ProjectionContractRegistry


class _IntegratedGraphAdapter(Protocol):
    def verify_compatibility(self) -> Neo4jCompatibility:
        ...

    def bootstrap_schema(self) -> None:
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

    def close(self) -> None:
        ...


class CandidateAdmissions:
    """Authenticated deterministic Candidate authority; no model write path."""

    __slots__ = ("__admit",)

    def __init__(
        self,
        admit: Callable[
            [
                CandidateAdmissionRequest,
                IntegratedRetrievalContext,
                IntegratedFixtureManifest,
                AuthenticationProof,
            ],
            CandidateAdmissionView,
        ],
    ) -> None:
        self.__admit = admit

    def admit(
        self,
        request: CandidateAdmissionRequest,
        *,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        proof: AuthenticationProof,
    ) -> CandidateAdmissionView:
        return self.__admit(request, context, manifest, proof)


class IntegratedCandidateAuthoritySystem:
    """Candidate authority over one exact authenticated native-graph runtime."""

    __slots__ = ("events", "candidates", "compatibility", "__close")

    def __init__(
        self,
        *,
        events: AuthorityEvents,
        candidates: CandidateAdmissions,
        compatibility: Neo4jCompatibility,
        close: Callable[[], None],
    ) -> None:
        self.events = events
        self.candidates = candidates
        self.compatibility = compatibility
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> IntegratedCandidateAuthoritySystem:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _CandidateAdmissionBoundary:
    def __init__(
        self,
        *,
        store: _IntegratedCandidateStore,
        command_service: CommandService,
        projection_boundary: _ProjectionBoundary,
        projection_read_policy: ProjectionReadPolicy,
        adapter: _IntegratedGraphAdapter,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._projection_boundary = projection_boundary
        self._projection_read_policy = projection_read_policy
        self._adapter = adapter
        self._clock = clock
        self._operation_lock = RLock()

    def admit(
        self,
        request: CandidateAdmissionRequest,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        proof: AuthenticationProof,
    ) -> CandidateAdmissionView:
        if not isinstance(request, CandidateAdmissionRequest):
            raise TypeError("candidate admission requires a typed request")
        if not isinstance(context, IntegratedRetrievalContext):
            raise TypeError(
                "candidate admission requires a typed retrieval context"
            )
        if not isinstance(manifest, IntegratedFixtureManifest):
            raise TypeError(
                "candidate admission requires a typed fixture manifest"
            )

        collision_digest = self._store.semantic_collision_digest(
            request,
            manifest,
            context,
        )
        payload = {
            "proposal_id": str(request.proposal_id),
            "route": request.route.value,
            "fixture_id": str(request.fixture_id),
            "retrieval_context_digest": context.context_digest,
            "manifest_digest": manifest.manifest_digest,
            "semantic_collision_digest": collision_digest,
        }
        command = SemanticCommand(
            command_type=CANDIDATE_ADMISSION_COMMAND,
            aggregate_id=request.proposal_id.as_aggregate_id(),
            expected_aggregate_version=0,
            payload=InlinePayload(payload),
            idempotency_key=request.idempotency_key,
        )
        # Authentication and Candidate-authority authorization happen before any
        # Neo4j inventory, so this facade cannot become a graph-existence oracle.
        grant = self._command_service._authorize_for_commit(
            command,
            proof=proof,
        )
        with self._operation_lock:
            self._verify_current_graph(grant, context)
            return self._store.commit_candidate_admission(
                grant,
                request=request,
                context=context,
                manifest=manifest,
                semantic_collision_digest=collision_digest,
            )

    def _verify_current_graph(
        self,
        grant: Any,
        context: IntegratedRetrievalContext,
    ) -> None:
        checked_at = self._clock()
        grant.authentication.require_current(checked_at)
        self._projection_read_policy.require_principal(
            grant.authentication.principal_id
        )
        self._projection_boundary._authorize_read(
            family_id=context.metadata.family_id,
            operation="integrated-candidate-context-reconcile",
            semantic_value={
                "context_id": str(context.context_id),
                "context_digest": context.context_digest,
                "generation_id": str(context.metadata.generation_id),
                "canonical_ids": [
                    item.canonical_id for item in context.nodes
                ],
                "authority_watermark": (
                    context.metadata.contiguous_ledger_seq
                ),
            },
            authenticated=(checked_at, grant.authentication),
        )

        metadata = self._store.projection_active_generation_metadata(
            context.metadata.family_id
        )
        expected_metadata = (
            metadata.family.family_id,
            metadata.family.definition_version,
            metadata.family.projector_version,
            metadata.family.ontology_contract_digest,
            metadata.family.mapping_contract_digest,
            metadata.generation.generation_id,
            metadata.generation.state,
            metadata.contiguous_ledger_seq,
            metadata.open_gap_count,
            metadata.dead_letter_count,
        )
        retained_metadata = (
            context.metadata.family_id,
            context.metadata.family_definition_version,
            context.metadata.projector_version,
            context.metadata.ontology_contract_digest,
            context.metadata.mapping_contract_digest,
            context.metadata.generation_id,
            context.metadata.generation_state,
            context.metadata.contiguous_ledger_seq,
            context.metadata.open_gap_count,
            context.metadata.dead_letter_count,
        )
        if (
            expected_metadata != retained_metadata
            or metadata.serving_time.value
            < context.metadata.serving_time.value
        ):
            raise IntegratedStateError(
                "retrieval context is stale against active projection authority"
            )

        validation = self._store.projection_generation_validation(
            context.metadata.generation_id
        )
        if (
            validation.checkpoint_ledger_seq
            != context.metadata.contiguous_ledger_seq
        ):
            raise IntegratedStateError(
                "retrieval context validation is stale"
            )

        compatibility = self._adapter.verify_compatibility()
        compatibility_digest = neo4j_compatibility_digest(compatibility)
        if (
            compatibility_digest
            != validation.service_compatibility_digest
        ):
            raise Neo4jIdentityConflict(
                "Neo4j compatibility differs from retained validation"
            )

        batches = self._expected_batches(
            context.metadata.generation_id,
            context.metadata.contiguous_ledger_seq,
        )
        state_digest = self._adapter.reconcile_generation(
            generation_id=str(context.metadata.generation_id),
            expected_batches=batches,
        )
        if state_digest != validation.projection_state_digest:
            raise Neo4jIdentityConflict(
                "Neo4j graph state differs from retained validation"
            )

        canonical_ids = tuple(item.canonical_id for item in context.nodes)
        actual = self._adapter.read(
            generation_id=str(context.metadata.generation_id),
            canonical_ids=canonical_ids,
            maximum_ledger_seq=context.metadata.contiguous_ledger_seq,
            limit=max(len(context.nodes), len(context.relations), 1),
        )
        if actual.nodes != context.nodes or actual.relations != context.relations:
            raise Neo4jIdentityConflict(
                "current Neo4j read differs from retained retrieval context"
            )

    def _expected_batches(
        self,
        generation_id: Any,
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
                    "authority checkpoint lacks a structural delivery state"
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
                    "structural reconciliation encountered unfinished delivery"
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
                "structural reconciliation encountered a failed delivery"
            )
        return tuple(batches)


def _open_candidate_with_adapter(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    contracts: ProjectionContractRegistry,
    authenticator: Any,
    authorizer: Any,
    event_read_policy: EventReadPolicy,
    projection_read_policy: ProjectionReadPolicy,
    adapter: _IntegratedGraphAdapter,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> IntegratedCandidateAuthoritySystem:
    merged_registry, merged_schemas = merge_integrated_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _IntegratedCandidateStore | None = None
    try:
        compatibility = adapter.verify_compatibility()
        adapter.bootstrap_schema()
        store = _IntegratedCandidateStore(
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
        read_boundary = _ReadBoundary(
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
        boundary = _CandidateAdmissionBoundary(
            store=store,
            command_service=command_service,
            projection_boundary=projection_boundary,
            projection_read_policy=projection_read_policy,
            adapter=adapter,
            clock=clock,
        )
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

        return IntegratedCandidateAuthoritySystem(
            events=AuthorityEvents(
                policy_id=event_read_policy.policy_id,
                read=read_boundary.events_after,
                provenance=read_boundary.provenance,
                result=read_boundary.command_result,
            ),
            candidates=CandidateAdmissions(boundary.admit),
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


def open_candidate_admission_authority_system(
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
) -> IntegratedCandidateAuthoritySystem:
    """Open Candidate authority with mandatory current native-Neo4j evidence."""

    adapter = _open_structural_graph_adapter(neo4j_config)
    return _open_candidate_with_adapter(
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
    "CandidateAdmissions",
    "IntegratedCandidateAuthoritySystem",
    "open_candidate_admission_authority_system",
]
