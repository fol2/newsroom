from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from ._capability import _CapabilityIssuer
from ._complete_projection_store import _CompleteProjectionAuthorityStore
from ._event_system import _ReadBoundary
from ._projection_system import NativeProjections, _ProjectionBoundary
from .auth import AuthenticationProof
from .canonical import digest_canonical
from .models import SemanticCommand
from .objects import ObjectLimits
from .persistence import (
    AuthorityCommands,
    AuthorityEvents,
    CommittedCommand,
    EventReadPolicy,
)
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp
from newsroom.projection import (
    CompleteProjectionProfile,
    INTEGRATED_FIXTURE_V2_PROJECTION,
)
from newsroom.projection.models import (
    DeliveryRecordView,
    ProjectionDeliveryOutcome,
    ProjectionDeliveryRequest,
    ProjectionFamilyRegistrationRequest,
    ProjectionFamilyView,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationPromotionView,
    ProjectionGenerationState,
    ProjectionGenerationTransitionRequest,
    ProjectionGenerationView,
    ProjectionGenerationValidationRequest,
    ProjectionGenerationValidationView,
    ProjectionReadPolicy,
    ProjectionStateError,
)
from newsroom.projection.neo4j._complete_adapter import (
    _open_complete_neo4j_adapter,
)
from newsroom.projection.neo4j.complete_models import (
    CompleteDeliveryRequest,
    CompleteGenerationQualificationRequest,
    CompleteGenerationValidationRequest,
    CompleteProjectionApplyResult,
    CompleteProjectionBatch,
    CompleteProjectionIdentity,
    CompleteProjectionQualification,
    CompleteQueryKind,
    CompleteRebuildRequest,
    CompleteRebuildResult,
)
from newsroom.projection.neo4j.models import (
    Neo4jAuthorityCommitPending,
    Neo4jCompatibility,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jWriteError,
)
from newsroom.projection.neo4j.qualification import neo4j_compatibility_digest
from newsroom.projection.policy import (
    PROJECTION_COMMAND_TYPES,
    ProjectionContractRegistry,
    merge_projection_authority_registries,
)
from newsroom.relations.policy import (
    RELATION_COMMAND_TYPES,
    merge_relation_authority_registries,
)


class _CompleteGraphAdapter(Protocol):
    def verify_compatibility(self) -> Neo4jCompatibility:
        ...

    def bootstrap_schema(self) -> None:
        ...

    def bootstrap_generation_indexes(
        self,
        identity: CompleteProjectionIdentity,
        *,
        fulltext: Any,
        vector: Any,
        profile: CompleteProjectionProfile,
        timeout_seconds: int = 120,
    ) -> tuple[Any, ...]:
        ...

    def apply_complete(
        self,
        batch: CompleteProjectionBatch,
        *,
        fulltext: Any,
        vector: Any,
        profile: CompleteProjectionProfile,
    ) -> CompleteProjectionApplyResult:
        ...

    def reconcile_complete_generation(
        self,
        *,
        identity: CompleteProjectionIdentity,
        checkpoint_ledger_seq: int,
        expected_batches: tuple[CompleteProjectionBatch, ...],
        fulltext: Any,
        vector: Any,
        profile: CompleteProjectionProfile,
    ) -> str:
        ...

    def qualify_complete_generation(
        self,
        *,
        identity: CompleteProjectionIdentity,
        checkpoint_ledger_seq: int,
        expected_batches: tuple[CompleteProjectionBatch, ...],
        fixture: Any,
        profile: CompleteProjectionProfile,
        recorded_at: UtcTimestamp,
    ) -> CompleteProjectionQualification:
        ...

    def cleanup_complete_generation(
        self,
        identity: CompleteProjectionIdentity,
        *,
        fulltext: Any,
        vector: Any,
    ) -> int:
        ...

    def close(self) -> None:
        ...


class CompleteNeo4jProjector:
    """Typed Increment 2B projector facade; no caller-selected query surface."""

    __slots__ = (
        "__deliver",
        "__rebuild",
        "__validate",
        "__qualify",
    )

    def __init__(
        self,
        *,
        deliver: Callable[
            [CompleteDeliveryRequest, AuthenticationProof], DeliveryRecordView
        ],
        rebuild: Callable[
            [CompleteRebuildRequest, AuthenticationProof], CompleteRebuildResult
        ],
        validate_generation: Callable[
            [CompleteGenerationValidationRequest, AuthenticationProof],
            ProjectionGenerationValidationView,
        ],
        qualify_generation: Callable[
            [CompleteGenerationQualificationRequest, AuthenticationProof],
            CompleteProjectionQualification,
    CompleteQueryKind,
        ],
    ) -> None:
        self.__deliver = deliver
        self.__rebuild = rebuild
        self.__validate = validate_generation
        self.__qualify = qualify_generation

    def deliver(
        self,
        request: CompleteDeliveryRequest,
        *,
        proof: AuthenticationProof,
    ) -> DeliveryRecordView:
        return self.__deliver(request, proof)

    def rebuild(
        self,
        request: CompleteRebuildRequest,
        *,
        proof: AuthenticationProof,
    ) -> CompleteRebuildResult:
        return self.__rebuild(request, proof)

    def validate_generation(
        self,
        request: CompleteGenerationValidationRequest,
        *,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationValidationView:
        return self.__validate(request, proof)

    def qualify_generation(
        self,
        request: CompleteGenerationQualificationRequest,
        *,
        proof: AuthenticationProof,
    ) -> CompleteProjectionQualification:
        return self.__qualify(request, proof)


class CompleteProjectionAuthoritySystem:
    __slots__ = (
        "commands",
        "events",
        "projections",
        "complete",
        "compatibility",
        "__close",
    )

    def __init__(
        self,
        *,
        commands: AuthorityCommands,
        events: AuthorityEvents,
        projections: NativeProjections,
        complete: CompleteNeo4jProjector,
        compatibility: Neo4jCompatibility,
        close: Callable[[], None],
    ) -> None:
        self.commands = commands
        self.events = events
        self.projections = projections
        self.complete = complete
        self.compatibility = compatibility
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> CompleteProjectionAuthoritySystem:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _CompleteProjectionBoundary:
    def __init__(
        self,
        *,
        store: _CompleteProjectionAuthorityStore,
        projection_boundary: _ProjectionBoundary,
        contracts: ProjectionContractRegistry,
        adapter: _CompleteGraphAdapter,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._projection_boundary = projection_boundary
        self._contracts = contracts
        self._adapter = adapter
        self._clock = clock
        self._operation_lock = RLock()

    def register_family(
        self,
        request: ProjectionFamilyRegistrationRequest,
        proof: AuthenticationProof,
    ) -> ProjectionFamilyView:
        if not isinstance(request, ProjectionFamilyRegistrationRequest):
            raise TypeError("complete family registration requires a typed request")
        definition = self._contracts.family(request.family_id)
        if definition.complete_projection_contract_digest is None:
            raise ProjectionStateError(
                "complete authority cannot register a structural-only family"
            )
        return self._projection_boundary.register_family(request, proof)

    def create_generation(
        self,
        request: ProjectionGenerationCreateRequest,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationView:
        if not isinstance(request, ProjectionGenerationCreateRequest):
            raise TypeError("complete generation creation requires a typed request")
        definition = self._contracts.family(request.family_id)
        if definition.complete_projection_contract_digest is None:
            raise ProjectionStateError(
                "complete authority cannot create a structural-only generation"
            )
        return self._projection_boundary.create_generation(request, proof)

    def transition_generation(
        self,
        request: ProjectionGenerationTransitionRequest,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationView:
        if not isinstance(request, ProjectionGenerationTransitionRequest):
            raise TypeError("complete generation transition requires a typed request")
        if request.target_state in {
            ProjectionGenerationState.VALIDATING,
            ProjectionGenerationState.ACTIVE,
        }:
            self._projection_boundary._authenticate(proof)
            raise ProjectionStateError(
                "complete generation validation and activation require complete evidence"
            )
        return self._projection_boundary.transition_generation(request, proof)

    def deliver(
        self,
        request: CompleteDeliveryRequest,
        proof: AuthenticationProof,
    ) -> DeliveryRecordView:
        with self._operation_lock:
            return self._deliver_locked(request, proof)

    def _deliver_locked(
        self,
        request: CompleteDeliveryRequest,
        proof: AuthenticationProof,
    ) -> DeliveryRecordView:
        if not isinstance(request, CompleteDeliveryRequest):
            raise TypeError("complete delivery requires a typed request")
        applied = ProjectionDeliveryRequest(
            generation_id=request.generation_id,
            expected_authority_version=request.expected_authority_version,
            ledger_seq=request.ledger_seq,
            outcome=ProjectionDeliveryOutcome.APPLIED,
            idempotency_key=request.idempotency_key,
        )
        grant = self._projection_boundary._authorize_delivery(applied, proof)
        source = self._store.projection_delivery_source(
            request.generation_id,
            request.ledger_seq,
        )
        if (
            grant.replay_of_command_id is None
            and source.generation.authority_aggregate_version
            != request.expected_authority_version
        ):
            raise ProjectionStateError(
                "complete generation authority changed before graph apply"
            )
        if source.generation.state in {
            ProjectionGenerationState.RETIRED,
            ProjectionGenerationState.FAILED,
        }:
            raise ProjectionStateError(
                "terminal complete generation cannot accept delivery"
            )
        identity, _contract, fulltext, vector, _manifest = (
            self._store.complete_projection_contracts(request.generation_id)
        )
        batch = self._store.complete_projection_batch(
            request.generation_id,
            request.ledger_seq,
            now=self._clock(),
        )
        if batch.identity != identity:
            raise ProjectionStateError(
                "complete batch identity differs from generation authority"
            )
        try:
            self._adapter.apply_complete(
                batch,
                fulltext=fulltext,
                vector=vector,
                profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
            )
        except Neo4jIdentityConflict:
            try:
                return self._record_failure(
                    request,
                    proof,
                    error_code="NEO4J_COMPLETE_IDENTITY_CONFLICT",
                )
            except ProjectionStateError as exc:
                if "already finalized" not in str(exc):
                    raise
                raise Neo4jIdentityConflict(
                    "complete graph identity conflicts with finalized authority"
                ) from None
        except Neo4jWriteError:
            return self._record_failure(
                request,
                proof,
                error_code="NEO4J_COMPLETE_WRITE_FAILURE",
            )
        try:
            return self._projection_boundary._commit_delivery(grant, applied)
        except Exception:
            raise Neo4jAuthorityCommitPending(
                "complete Neo4j delivery committed but SQLite transition is pending"
            ) from None

    def _record_failure(
        self,
        request: CompleteDeliveryRequest,
        proof: AuthenticationProof,
        *,
        error_code: str,
    ) -> DeliveryRecordView:
        return self._projection_boundary.record_delivery(
            ProjectionDeliveryRequest(
                generation_id=request.generation_id,
                expected_authority_version=request.expected_authority_version,
                ledger_seq=request.ledger_seq,
                outcome=ProjectionDeliveryOutcome.RETRYABLE_FAILURE,
                error_code=error_code,
                idempotency_key=request.idempotency_key,
            ),
            proof,
        )

    def rebuild(
        self,
        request: CompleteRebuildRequest,
        proof: AuthenticationProof,
    ) -> CompleteRebuildResult:
        with self._operation_lock:
            if not isinstance(request, CompleteRebuildRequest):
                raise TypeError("complete rebuild requires a typed request")
            latest = self._store.latest_complete_source_ledger_seq()
            if request.through_ledger_seq != latest:
                raise ProjectionStateError(
                    "complete rebuild must bind the exact current authority watermark"
                )
            receipt = self._projection_boundary._begin_rebuild(request, proof)
            if receipt.generation.state is not ProjectionGenerationState.BUILDING:
                raise ProjectionStateError(
                    "only a building complete generation can be rebuilt"
                )
            identity, _contract, fulltext, vector, _manifest = (
                self._store.complete_projection_contracts(request.generation_id)
            )
            deleted = self._adapter.cleanup_complete_generation(
                identity,
                fulltext=fulltext,
                vector=vector,
            )
            self._adapter.bootstrap_generation_indexes(
                identity,
                fulltext=fulltext,
                vector=vector,
                profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
            )
            reapplied = 0
            recorded = 0
            blocked = 0
            for ledger_seq in range(1, request.through_ledger_seq + 1):
                state = self._store.projection_rebuild_delivery_state(
                    request.generation_id,
                    ledger_seq,
                )
                if state is not None and state.finalized:
                    if state.outcome is ProjectionDeliveryOutcome.APPLIED:
                        batch = self._store.complete_projection_batch(
                            request.generation_id,
                            ledger_seq,
                            now=self._clock(),
                        )
                        self._adapter.apply_complete(
                            batch,
                            fulltext=fulltext,
                            vector=vector,
                            profile=(
                                CompleteProjectionProfile.FIXTURE_QUALIFICATION
                            ),
                        )
                        reapplied += 1
                    else:
                        blocked += 1
                    continue
                attempt = 1 if state is None else state.attempt_count + 1
                current = self._store.projection_generation(request.generation_id)
                key = "complete-rebuild-delivery:" + digest_canonical(
                    {
                        "rebuild_idempotency_key": request.idempotency_key,
                        "generation_id": str(request.generation_id),
                        "ledger_seq": ledger_seq,
                        "attempt_number": attempt,
                    }
                )
                result = self._deliver_locked(
                    CompleteDeliveryRequest(
                        generation_id=request.generation_id,
                        expected_authority_version=(
                            current.authority_aggregate_version
                        ),
                        ledger_seq=ledger_seq,
                        idempotency_key=key,
                    ),
                    proof,
                )
                if result.outcome is ProjectionDeliveryOutcome.APPLIED:
                    recorded += 1
                else:
                    blocked += 1
            metadata = self._store.projection_generation_metadata(
                request.generation_id
            )
            return CompleteRebuildResult(
                identity=identity,
                through_ledger_seq=request.through_ledger_seq,
                checkpoint_ledger_seq=metadata.contiguous_ledger_seq,
                rebuild_authority_event_id=receipt.authority_event_id,
                authority_command_replayed=receipt.replayed,
                deleted_record_count=deleted,
                reapplied_delivery_count=reapplied,
                recorded_delivery_count=recorded,
                blocked_delivery_count=blocked,
                serving_time=metadata.serving_time,
            )

    def validate_generation(
        self,
        request: CompleteGenerationValidationRequest,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationValidationView:
        with self._operation_lock:
            if not isinstance(request, CompleteGenerationValidationRequest):
                raise TypeError("complete validation requires a typed request")
            authenticated = self._projection_boundary._authenticate(proof)
            metadata = self._store.projection_generation_metadata(
                request.generation_id
            )
            self._projection_boundary._authorize_management_operation(
                family_id=metadata.family.family_id,
                aggregate_id=str(request.generation_id),
                operation="neo4j-complete-generation-reconcile",
                semantic_value={
                    "generation_id": str(request.generation_id),
                    "checkpoint_ledger_seq": request.checkpoint_ledger_seq,
                    "reason_code": request.reason_code,
                },
                authenticated=authenticated,
            )
            self._require_current_source_checkpoint(
                request.checkpoint_ledger_seq
            )
            if metadata.generation.state not in {
                ProjectionGenerationState.BUILDING,
                ProjectionGenerationState.VALIDATING,
                ProjectionGenerationState.ACTIVE,
            }:
                raise ProjectionStateError(
                    "complete validation requires a non-terminal generation"
                )
            self._require_exact_checkpoint(metadata, request.checkpoint_ledger_seq)
            batches = self._expected_batches(
                request.generation_id,
                request.checkpoint_ledger_seq,
            )
            identity, _contract, fulltext, vector, _manifest = (
                self._store.complete_projection_contracts(request.generation_id)
            )
            compatibility = self._adapter.verify_compatibility()
            state_digest = self._adapter.reconcile_complete_generation(
                identity=identity,
                checkpoint_ledger_seq=request.checkpoint_ledger_seq,
                expected_batches=batches,
                fulltext=fulltext,
                vector=vector,
                profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
            )
            qualification = self._adapter.qualify_complete_generation(
                identity=identity,
                checkpoint_ledger_seq=request.checkpoint_ledger_seq,
                expected_batches=batches,
                fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
                profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
                recorded_at=self._clock(),
            )
            self._require_exact_qualification_evidence(
                qualification,
                identity=identity,
                checkpoint_ledger_seq=request.checkpoint_ledger_seq,
            )
            if qualification.projection_state_digest != state_digest:
                raise Neo4jIdentityConflict(
                    "complete qualification differs from reconciled generation state"
                )
            authoritative = ProjectionGenerationValidationRequest(
                generation_id=request.generation_id,
                expected_authority_version=request.expected_authority_version,
                checkpoint_ledger_seq=request.checkpoint_ledger_seq,
                service_compatibility_digest=neo4j_compatibility_digest(
                    compatibility
                ),
                projection_state_digest=state_digest,
                reason_code=request.reason_code,
                idempotency_key=request.idempotency_key,
            )
            return self._projection_boundary.validate_generation(
                authoritative,
                proof,
                required_source_ledger_seq=request.checkpoint_ledger_seq,
            )

    def promote_generation(
        self,
        request: ProjectionGenerationPromotionRequest,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationPromotionView:
        with self._operation_lock:
            if not isinstance(request, ProjectionGenerationPromotionRequest):
                raise TypeError("complete promotion requires a typed request")
            target_grant, prior_grant = (
                self._projection_boundary._authorize_promotion(request, proof)
            )
            self._require_current_source_checkpoint(
                request.checkpoint_ledger_seq
            )
            metadata = self._store.projection_generation_metadata(
                request.generation_id
            )
            replaying = target_grant.replay_of_command_id is not None
            if replaying:
                if metadata.generation.state not in {
                    ProjectionGenerationState.ACTIVE,
                    ProjectionGenerationState.RETIRED,
                }:
                    raise ProjectionStateError(
                        "complete promotion replay requires active or retired state"
                    )
                checkpoint = metadata.contiguous_ledger_seq
            else:
                if metadata.generation.state is not ProjectionGenerationState.VALIDATING:
                    raise ProjectionStateError(
                        "only a validating complete generation can be promoted"
                    )
                checkpoint = request.checkpoint_ledger_seq
                self._require_exact_checkpoint(metadata, checkpoint)
            validation = self._store.projection_generation_validation(
                request.generation_id
            )
            if not replaying and (
                validation.validation_digest != request.validation_digest
                or validation.checkpoint_ledger_seq != checkpoint
            ):
                raise ProjectionStateError(
                    "complete promotion requires exact validation evidence"
                )
            if replaying and (
                validation.checkpoint_ledger_seq != checkpoint
                or metadata.generation.validated_through_ledger_seq != checkpoint
            ):
                raise ProjectionStateError(
                    "complete promotion replay validation is stale"
                )
            compatibility_digest = neo4j_compatibility_digest(
                self._adapter.verify_compatibility()
            )
            if compatibility_digest != validation.service_compatibility_digest:
                raise Neo4jIdentityConflict(
                    "Neo4j compatibility differs from complete validation"
                )
            batches = self._expected_batches(request.generation_id, checkpoint)
            identity, _contract, fulltext, vector, _manifest = (
                self._store.complete_projection_contracts(request.generation_id)
            )
            state_digest = self._adapter.reconcile_complete_generation(
                identity=identity,
                checkpoint_ledger_seq=checkpoint,
                expected_batches=batches,
                fulltext=fulltext,
                vector=vector,
                profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
            )
            if state_digest != validation.projection_state_digest:
                raise Neo4jIdentityConflict(
                    "Neo4j complete state differs from retained validation"
                )
            return self._projection_boundary._commit_promotion(
                target_grant,
                prior_grant,
                request,
                required_source_ledger_seq=checkpoint,
            )

    def qualify_generation(
        self,
        request: CompleteGenerationQualificationRequest,
        proof: AuthenticationProof,
    ) -> CompleteProjectionQualification:
        with self._operation_lock:
            if not isinstance(request, CompleteGenerationQualificationRequest):
                raise TypeError("complete qualification requires a typed request")
            authenticated = self._projection_boundary._authenticate(proof)
            metadata = self._store.projection_generation_metadata(
                request.generation_id
            )
            self._projection_boundary._authorize_management_operation(
                family_id=metadata.family.family_id,
                aggregate_id=str(request.generation_id),
                operation="neo4j-complete-generation-qualify",
                semantic_value={
                    "generation_id": str(request.generation_id),
                    "checkpoint_ledger_seq": request.checkpoint_ledger_seq,
                    "profile": request.profile.value,
                },
                authenticated=authenticated,
            )
            self._require_current_source_checkpoint(
                request.checkpoint_ledger_seq
            )
            self._require_exact_checkpoint(metadata, request.checkpoint_ledger_seq)
            if metadata.generation.state not in {
                ProjectionGenerationState.VALIDATING,
                ProjectionGenerationState.ACTIVE,
            }:
                raise ProjectionStateError(
                    "complete qualification requires retained validation authority"
                )
            validation = self._store.projection_generation_validation(
                request.generation_id
            )
            if validation.checkpoint_ledger_seq != request.checkpoint_ledger_seq:
                raise ProjectionStateError(
                    "complete qualification validation evidence is stale"
                )
            batches = self._expected_batches(
                request.generation_id,
                request.checkpoint_ledger_seq,
            )
            identity, _contract, _fulltext, _vector, _manifest = (
                self._store.complete_projection_contracts(request.generation_id)
            )
            qualification = self._adapter.qualify_complete_generation(
                identity=identity,
                checkpoint_ledger_seq=request.checkpoint_ledger_seq,
                expected_batches=batches,
                fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
                profile=request.profile,
                recorded_at=self._clock(),
            )
            self._require_current_source_checkpoint(
                request.checkpoint_ledger_seq
            )
            self._require_exact_qualification_evidence(
                qualification,
                identity=identity,
                checkpoint_ledger_seq=request.checkpoint_ledger_seq,
            )
            if (
                qualification.projection_state_digest
                != validation.projection_state_digest
            ):
                raise Neo4jIdentityConflict(
                    "complete qualification differs from retained validation"
                )
            return qualification

    def reject_direct_validation(
        self,
        request: ProjectionGenerationValidationRequest,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationValidationView:
        if not isinstance(request, ProjectionGenerationValidationRequest):
            raise TypeError("projection validation requires a typed request")
        self._projection_boundary._authenticate(proof)
        raise ProjectionStateError(
            "complete generation validation requires complete reconciliation"
        )

    def reject_direct_delivery(
        self,
        request: ProjectionDeliveryRequest,
        proof: AuthenticationProof,
    ) -> DeliveryRecordView:
        if not isinstance(request, ProjectionDeliveryRequest):
            raise TypeError("projection delivery requires a typed request")
        self._projection_boundary._authenticate(proof)
        raise ProjectionStateError(
            "complete generation delivery requires the typed complete projector"
        )

    @staticmethod
    def _require_exact_checkpoint(metadata: Any, checkpoint: int) -> None:
        if metadata.contiguous_ledger_seq != checkpoint:
            raise ProjectionStateError(
                "complete operation must bind the exact authority checkpoint"
            )
        if metadata.open_gap_count or metadata.dead_letter_count:
            raise ProjectionStateError(
                "complete operation requires zero gaps and dead letters"
            )

    @staticmethod
    def _require_exact_qualification_evidence(
        qualification: CompleteProjectionQualification,
        *,
        identity: CompleteProjectionIdentity,
        checkpoint_ledger_seq: int,
    ) -> None:
        if qualification.identity != identity:
            raise Neo4jIdentityConflict(
                "complete qualification identity differs from authority"
            )
        if qualification.checkpoint_ledger_seq != checkpoint_ledger_seq:
            raise Neo4jIdentityConflict(
                "complete qualification checkpoint differs from authority"
            )
        fixture = INTEGRATED_FIXTURE_V2_PROJECTION
        expected_tombstones = tuple(
            sorted(fixture.expected_tombstoned_passage_ids)
        )
        if qualification.expected_tombstoned_passage_ids != expected_tombstones:
            raise Neo4jIdentityConflict(
                "complete qualification tombstone evidence differs from fixture"
            )

        fulltext_by_query: dict[str, list[Any]] = {}
        for hit in qualification.fulltext_hits:
            if hit.query_kind is not CompleteQueryKind.FULL_TEXT:
                raise Neo4jIdentityConflict(
                    "complete qualification full-text evidence has wrong kind"
                )
            fulltext_by_query.setdefault(hit.query_id, []).append(hit)
        expected_fulltext = {
            query_id: query.expected_first_passage_id
            for query in fixture.fulltext_queries
            for query_id in (
                query.query_id,
                f"{query.query_id}.normalized",
            )
        }
        if set(fulltext_by_query) != set(expected_fulltext):
            raise Neo4jIdentityConflict(
                "complete qualification full-text query evidence is incomplete"
            )
        for query_id, expected_passage_id in expected_fulltext.items():
            hits = sorted(fulltext_by_query[query_id], key=lambda item: item.rank)
            if (
                not hits
                or [item.rank for item in hits]
                != list(range(1, len(hits) + 1))
                or hits[0].passage_id != expected_passage_id
            ):
                raise Neo4jIdentityConflict(
                    "complete qualification full-text evidence differs from fixture"
                )

        vector_by_query: dict[str, list[Any]] = {}
        for hit in qualification.vector_hits:
            if hit.query_kind is not CompleteQueryKind.VECTOR:
                raise Neo4jIdentityConflict(
                    "complete qualification vector evidence has wrong kind"
                )
            vector_by_query.setdefault(hit.query_id, []).append(hit)
        expected_vector = {
            query.query_id: query.expected_active_prefix
            for query in fixture.vector_queries
        }
        if set(vector_by_query) != set(expected_vector):
            raise Neo4jIdentityConflict(
                "complete qualification vector query evidence is incomplete"
            )
        for query_id, expected_prefix in expected_vector.items():
            hits = sorted(vector_by_query[query_id], key=lambda item: item.rank)
            if (
                [item.rank for item in hits]
                != list(range(1, len(hits) + 1))
                or tuple(
                    item.passage_id for item in hits[: len(expected_prefix)]
                )
                != expected_prefix
            ):
                raise Neo4jIdentityConflict(
                    "complete qualification vector evidence differs from fixture"
                )

        returned_passages = {
            hit.passage_id
            for hit in (*qualification.fulltext_hits, *qualification.vector_hits)
        }
        if returned_passages & set(expected_tombstones):
            raise Neo4jIdentityConflict(
                "complete qualification returned tombstoned fixture material"
            )

    def _require_current_source_checkpoint(self, checkpoint: int) -> None:
        latest = self._store.latest_complete_source_ledger_seq()
        if latest != checkpoint:
            raise ProjectionStateError(
                "complete operation must bind the exact current source watermark"
            )

    def _expected_batches(
        self,
        generation_id: Any,
        checkpoint: int,
    ) -> tuple[CompleteProjectionBatch, ...]:
        batches = self._store.complete_projection_batches(
            generation_id,
            checkpoint,
            now=self._clock(),
        )
        for batch in batches:
            state = self._store.projection_rebuild_delivery_state(
                generation_id,
                batch.ledger_seq,
            )
            if state is None:
                raise ProjectionStateError(
                    "complete checkpoint lacks a delivery state"
                )
            if (
                str(state.source_event_id) != str(batch.source_event_id)
                or state.source_event_digest != batch.source_event_digest
                or not state.finalized
                or state.outcome is not ProjectionDeliveryOutcome.APPLIED
            ):
                raise ProjectionStateError(
                    "complete delivery state differs from retained authority"
                )
        return batches


def _open_complete_with_adapter(
    *,
    path: Path,
    object_root: Path,
    object_limits: ObjectLimits,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    contracts: ProjectionContractRegistry,
    authenticator: Any,
    authorizer: Any,
    event_read_policy: EventReadPolicy,
    projection_read_policy: ProjectionReadPolicy,
    adapter: _CompleteGraphAdapter,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> CompleteProjectionAuthoritySystem:
    relation_registry, relation_schemas = merge_relation_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    merged_registry, merged_schemas = merge_projection_authority_registries(
        command_registry=relation_registry,
        payload_schemas=relation_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _CompleteProjectionAuthorityStore | None = None
    try:
        compatibility = adapter.verify_compatibility()
        adapter.bootstrap_schema()
        store = _CompleteProjectionAuthorityStore(
            path,
            object_root=object_root,
            object_limits=object_limits,
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
        event_boundary = _ReadBoundary(
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
        complete_boundary = _CompleteProjectionBoundary(
            store=store,
            projection_boundary=projection_boundary,
            contracts=contracts,
            adapter=adapter,
            clock=clock,
        )

        def execute(
            command: SemanticCommand,
            proof: AuthenticationProof,
        ) -> CommittedCommand:
            if command.command_type in PROJECTION_COMMAND_TYPES | RELATION_COMMAND_TYPES:
                raise PermissionError(
                    "projection and relation commands are internal authority operations"
                )
            grant = command_service._authorize_for_commit(command, proof=proof)
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

        return CompleteProjectionAuthoritySystem(
            commands=AuthorityCommands(execute),
            events=AuthorityEvents(
                policy_id=event_read_policy.policy_id,
                read=event_boundary.events_after,
                provenance=event_boundary.provenance,
                result=event_boundary.command_result,
            ),
            projections=NativeProjections(
                register_family=complete_boundary.register_family,
                create_generation=complete_boundary.create_generation,
                transition_generation=complete_boundary.transition_generation,
                validate_generation=complete_boundary.reject_direct_validation,
                promote_generation=complete_boundary.promote_generation,
                record_delivery=complete_boundary.reject_direct_delivery,
                resolve_gap=projection_boundary.resolve_gap,
                status=projection_boundary.status,
                generations=projection_boundary.generations,
                validation=projection_boundary.validation,
                promotions=projection_boundary.promotions,
                gaps=projection_boundary.gaps,
                dead_letters=projection_boundary.dead_letters,
            ),
            complete=CompleteNeo4jProjector(
                deliver=complete_boundary.deliver,
                rebuild=complete_boundary.rebuild,
                validate_generation=complete_boundary.validate_generation,
                qualify_generation=complete_boundary.qualify_generation,
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


def open_complete_projection_authority_system(
    *,
    path: Path,
    object_root: Path,
    object_limits: ObjectLimits,
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
) -> CompleteProjectionAuthoritySystem:
    adapter = _open_complete_neo4j_adapter(neo4j_config)
    return _open_complete_with_adapter(
        path=path,
        object_root=object_root,
        object_limits=object_limits,
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
    "CompleteNeo4jProjector",
    "CompleteProjectionAuthoritySystem",
    "_open_complete_with_adapter",
    "open_complete_projection_authority_system",
]
