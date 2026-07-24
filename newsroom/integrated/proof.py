from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from newsroom.authority import (
    AggregateId,
    AuthenticationProof,
    CommandId,
    CommandRegistry,
    EventId,
    EventReadPolicy,
    HydratedObject,
    HydrationPolicyRegistry,
    HydrationRequest,
    ObjectAdmissionId,
    ObjectAdmissionPayload,
    ObjectAdmissionRegistry,
    ObjectAdmissionRequest,
    ObjectLimits,
    PayloadSchemaRegistry,
    RightsPolicyRegistry,
    SemanticCommand,
    UtcTimestamp,
    digest_canonical,
    open_governed_object_authority_system,
)
from newsroom.authority.integrated_system import (
    open_candidate_admission_authority_system,
)
from newsroom.authority.neo4j_projection_system import (
    open_neo4j_projection_authority_system,
)
from newsroom.projection import (
    ProjectionContractRegistry,
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionGenerationView,
    ProjectionIdentitySource,
    ProjectionReadPolicy,
    ProjectionStateError,
    StructuralIdentityContext,
    canonical_node_id,
)
from newsroom.projection.neo4j import (
    Neo4jProjectorConfig,
    StructuralActiveReadRequest,
    StructuralGenerationValidationRequest,
    StructuralReadResponse,
    StructuralRebuildRequest,
)

from .models import (
    CandidateAdmissionRequest,
    CandidateAdmissionView,
    CandidateRoute,
    IntegratedExactIndexEntry,
    IntegratedFixtureId,
    IntegratedFixtureManifest,
    IntegratedRetrievalContext,
    IntegratedRetrievalContextId,
    IntegratedStateError,
    IntegratedTriageProposalId,
)
from .policy import (
    INTEGRATED_FIXTURE_COMMAND,
    merge_integrated_authority_registries,
)


@dataclass(frozen=True, slots=True)
class IntegratedProofEnvironment:
    """Trusted composition inputs for the synthetic integrated proof only."""

    path: Path
    object_root: Path
    command_registry: CommandRegistry
    payload_schemas: PayloadSchemaRegistry
    admission_registry: ObjectAdmissionRegistry
    rights_policies: RightsPolicyRegistry
    hydration_policies: HydrationPolicyRegistry
    authenticator: Any = field(repr=False)
    authorizer: Any = field(repr=False)
    event_read_policy: EventReadPolicy
    projection_read_policy: ProjectionReadPolicy
    projection_contracts: ProjectionContractRegistry
    object_limits: ObjectLimits
    neo4j_config: Neo4jProjectorConfig = field(repr=False)
    family_id: str
    fixture_admission_type: str
    fixture_hydration_purpose: str
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not isinstance(
            self.object_root, Path
        ):
            raise TypeError("integrated proof paths must be pathlib.Path values")
        if not isinstance(self.command_registry, CommandRegistry):
            raise TypeError("integrated proof requires a command registry")
        if not isinstance(self.payload_schemas, PayloadSchemaRegistry):
            raise TypeError("integrated proof requires a payload-schema registry")
        if not isinstance(self.admission_registry, ObjectAdmissionRegistry):
            raise TypeError("integrated proof requires an admission registry")
        if not isinstance(self.rights_policies, RightsPolicyRegistry):
            raise TypeError("integrated proof requires a rights-policy registry")
        if not isinstance(self.hydration_policies, HydrationPolicyRegistry):
            raise TypeError("integrated proof requires a hydration-policy registry")
        if not isinstance(self.event_read_policy, EventReadPolicy):
            raise TypeError("integrated proof requires an event read policy")
        if not isinstance(self.projection_read_policy, ProjectionReadPolicy):
            raise TypeError("integrated proof requires a projection read policy")
        if not isinstance(self.projection_contracts, ProjectionContractRegistry):
            raise TypeError("integrated proof requires projection contracts")
        if not isinstance(self.object_limits, ObjectLimits):
            raise TypeError("integrated proof requires object limits")
        if not isinstance(self.neo4j_config, Neo4jProjectorConfig):
            raise TypeError("integrated proof requires native Neo4j configuration")
        if not callable(self.clock):
            raise TypeError("integrated proof clock must be callable")
        family = self.projection_contracts.family(self.family_id)
        if family.family_id != self.family_id:
            raise IntegratedStateError(
                "integrated proof family does not resolve exactly"
            )
        try:
            definition = self.admission_registry.resolve(
                self.fixture_admission_type
            )
            hydration = self.hydration_policies.resolve_for_purpose(
                self.fixture_hydration_purpose
            )
        except Exception as exc:
            raise IntegratedStateError(
                "integrated fixture admission or hydration policy is not registered"
            ) from exc
        if hydration.contract_digest not in (
            definition.hydration_policy_contract_digests
        ):
            raise IntegratedStateError(
                "integrated fixture hydration policy is outside the admission contract"
            )


@dataclass(frozen=True, slots=True)
class IntegratedProofKeys:
    prefix: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.prefix, str)
            or not self.prefix.strip()
            or len(self.prefix.encode("utf-8")) > 128
        ):
            raise ValueError("integrated proof key prefix is invalid")

    def value(self, operation: str) -> str:
        if not isinstance(operation, str) or not operation:
            raise ValueError("integrated proof operation name is invalid")
        return f"{self.prefix}:{operation}"


@dataclass(frozen=True, slots=True)
class IntegratedFixtureAuthority:
    fixture_id: IntegratedFixtureId
    fixture_aggregate_id: AggregateId
    fixture_event_id: EventId
    fixture_command_id: CommandId
    fixture_ledger_seq: int
    admission_id: ObjectAdmissionId
    manifest_digest: str
    command_replayed: bool
    admission_replayed: bool


@dataclass(frozen=True, slots=True)
class IntegratedProjectionAuthority:
    generation: ProjectionGenerationView
    response: StructuralReadResponse
    rebuilt: bool
    promoted: bool


@dataclass(frozen=True, slots=True)
class IntegratedFoundationProofResult:
    fixture: IntegratedFixtureAuthority
    projection: IntegratedProjectionAuthority
    context: IntegratedRetrievalContext
    candidate: CandidateAdmissionView


class IntegratedFoundationProofController:
    """Run the bounded synthetic A→B→C proof through public authority facades.

    The controller owns no database, graph or object authority. Each stage opens
    the repository's one SQLite writer, commits or reads through typed public
    facades, closes it, and hands exact identities to the next stage. No source,
    Graphiti, model, embedding, Evidence Intake or publication interface exists.
    """

    __slots__ = ("_environment", "_commands", "_schemas")

    def __init__(self, environment: IntegratedProofEnvironment) -> None:
        if not isinstance(environment, IntegratedProofEnvironment):
            raise TypeError("integrated proof requires a typed environment")
        self._environment = environment
        self._commands, self._schemas = merge_integrated_authority_registries(
            command_registry=environment.command_registry,
            payload_schemas=environment.payload_schemas,
        )

    def record_fixture(
        self,
        manifest: IntegratedFixtureManifest,
        *,
        proof: AuthenticationProof,
        keys: IntegratedProofKeys,
    ) -> IntegratedFixtureAuthority:
        if not isinstance(manifest, IntegratedFixtureManifest):
            raise TypeError("integrated proof requires a typed fixture manifest")
        system = open_governed_object_authority_system(
            path=self._environment.path,
            object_root=self._environment.object_root,
            registry=self._commands,
            payload_schemas=self._schemas,
            admission_registry=self._environment.admission_registry,
            rights_policies=self._environment.rights_policies,
            hydration_policies=self._environment.hydration_policies,
            authenticator=self._environment.authenticator,
            authorizer=self._environment.authorizer,
            event_read_policy=self._environment.event_read_policy,
            object_limits=self._environment.object_limits,
            clock=self._environment.clock,
        )
        try:
            admission = system.objects.admit(
                ObjectAdmissionRequest(
                    self._environment.fixture_admission_type,
                    keys.value("object-admission"),
                ),
                manifest.canonical_bytes,
                proof=proof,
            )
            if admission.admission.blob.blob_digest != manifest.manifest_digest:
                raise IntegratedStateError(
                    "governed fixture bytes differ from the canonical manifest"
                )
            aggregate_id = AggregateId(manifest.fixture_id.value)
            committed = system.commands.execute(
                SemanticCommand(
                    command_type=INTEGRATED_FIXTURE_COMMAND,
                    aggregate_id=aggregate_id,
                    expected_aggregate_version=0,
                    payload=ObjectAdmissionPayload(
                        admission.admission.admission_id
                    ),
                    idempotency_key=keys.value("fixture-command"),
                ),
                proof=proof,
            )
            page = system.events.after(
                committed.ledger_seq - 1,
                limit=1,
                proof=proof,
            )
            if len(page) != 1:
                raise IntegratedStateError(
                    "fixture command lacks one exact authority event"
                )
            event = page[0]
            if (
                event.event_id != committed.event_id
                or event.command_id != committed.command_id
                or event.aggregate_type != "integrated_fixture"
                or event.aggregate_id != str(aggregate_id)
                or event.aggregate_version != committed.aggregate_version
                or event.object_admission_id
                != str(admission.admission.admission_id)
                or event.payload_digest != manifest.manifest_digest
                or event.trust_scope != "OBSERVED"
            ):
                raise IntegratedStateError(
                    "fixture event differs from committed governed authority"
                )
            hydrated = system.objects.hydrate(
                HydrationRequest(
                    admission.admission.admission_id,
                    self._environment.fixture_hydration_purpose,
                ),
                proof=proof,
            )
            self._require_hydrated_manifest(hydrated, manifest)
            return IntegratedFixtureAuthority(
                fixture_id=manifest.fixture_id,
                fixture_aggregate_id=aggregate_id,
                fixture_event_id=EventId.parse(committed.event_id),
                fixture_command_id=CommandId.parse(committed.command_id),
                fixture_ledger_seq=committed.ledger_seq,
                admission_id=admission.admission.admission_id,
                manifest_digest=manifest.manifest_digest,
                command_replayed=committed.replayed,
                admission_replayed=admission.replayed,
            )
        finally:
            system.close()

    def ensure_projection(
        self,
        fixture: IntegratedFixtureAuthority,
        manifest: IntegratedFixtureManifest,
        *,
        generation_id: ProjectionGenerationId,
        query_valid_time: UtcTimestamp,
        through_ledger_seq: int | None,
        proof: AuthenticationProof,
        keys: IntegratedProofKeys,
    ) -> IntegratedProjectionAuthority:
        if fixture.fixture_id != manifest.fixture_id:
            raise IntegratedStateError(
                "fixture authority and manifest identities differ"
            )
        if not isinstance(generation_id, ProjectionGenerationId):
            raise TypeError("integrated projection generation must be typed")
        if not isinstance(query_valid_time, UtcTimestamp):
            raise TypeError("integrated query-valid time must be typed")
        through = fixture.fixture_ledger_seq if through_ledger_seq is None else through_ledger_seq
        if (
            isinstance(through, bool)
            or not isinstance(through, int)
            or through < fixture.fixture_ledger_seq
        ):
            raise IntegratedStateError(
                "projection cutoff must cover the exact fixture event"
            )

        system = open_neo4j_projection_authority_system(
            path=self._environment.path,
            registry=self._commands,
            payload_schemas=self._schemas,
            contracts=self._environment.projection_contracts,
            authenticator=self._environment.authenticator,
            authorizer=self._environment.authorizer,
            event_read_policy=self._environment.event_read_policy,
            projection_read_policy=self._environment.projection_read_policy,
            neo4j_config=self._environment.neo4j_config,
            clock=self._environment.clock,
        )
        rebuilt = False
        promoted = False
        try:
            system.projections.register_family(
                ProjectionFamilyRegistrationRequest(
                    self._environment.family_id,
                    f"integrated-family-register:{self._environment.family_id}",
                ),
                proof=proof,
            )
            generation = self._find_generation(
                system,
                generation_id,
                proof=proof,
            )
            if generation is None:
                generation = system.projections.create_generation(
                    ProjectionGenerationCreateRequest(
                        generation_id,
                        self._environment.family_id,
                        "INTEGRATED_FOUNDATION_PROOF",
                        keys.value("generation-create"),
                    ),
                    proof=proof,
                )

            validation = None
            if generation.state is ProjectionGenerationState.BUILDING:
                rebuild = system.structural.rebuild(
                    StructuralRebuildRequest(
                        generation_id=generation_id,
                        expected_authority_version=(
                            generation.authority_aggregate_version
                        ),
                        through_ledger_seq=through,
                        reason_code="INTEGRATED_FOUNDATION_REBUILD",
                        idempotency_key=keys.value("generation-rebuild"),
                    ),
                    proof=proof,
                )
                rebuilt = True
                generation = self._require_generation(
                    system,
                    generation_id,
                    proof=proof,
                )
                validation = system.structural.validate_generation(
                    StructuralGenerationValidationRequest(
                        generation_id=generation_id,
                        expected_authority_version=(
                            generation.authority_aggregate_version
                        ),
                        checkpoint_ledger_seq=rebuild.checkpoint_ledger_seq,
                        reason_code="INTEGRATED_FOUNDATION_VALIDATE",
                        idempotency_key=keys.value("generation-validate"),
                    ),
                    proof=proof,
                )
                generation = self._require_generation(
                    system,
                    generation_id,
                    proof=proof,
                )
            elif generation.state is ProjectionGenerationState.VALIDATING:
                validation = system.projections.validation(
                    generation_id,
                    proof=proof,
                )
            elif generation.state is not ProjectionGenerationState.ACTIVE:
                raise ProjectionStateError(
                    "integrated proof generation is terminal and cannot serve"
                )

            if generation.state is ProjectionGenerationState.VALIDATING:
                if validation is None:
                    raise IntegratedStateError(
                        "validating generation lacks retained validation"
                    )
                active = tuple(
                    item
                    for item in system.projections.generations(
                        self._environment.family_id,
                        limit=100,
                        proof=proof,
                    )
                    if item.state is ProjectionGenerationState.ACTIVE
                    and item.generation_id != generation_id
                )
                if len(active) > 1:
                    raise IntegratedStateError(
                        "projection authority contains multiple prior ACTIVE generations"
                    )
                prior = active[0] if active else None
                promotion = system.projections.promote_generation(
                    ProjectionGenerationPromotionRequest(
                        generation_id=generation_id,
                        expected_authority_version=(
                            generation.authority_aggregate_version
                        ),
                        checkpoint_ledger_seq=(
                            validation.checkpoint_ledger_seq
                        ),
                        validation_digest=validation.validation_digest,
                        reason_code="INTEGRATED_FOUNDATION_PROMOTE",
                        idempotency_key=keys.value("generation-promote"),
                        prior_generation_id=(
                            None if prior is None else prior.generation_id
                        ),
                        expected_prior_authority_version=(
                            None
                            if prior is None
                            else prior.authority_aggregate_version
                        ),
                    ),
                    proof=proof,
                )
                generation = promotion.generation
                promoted = True

            if generation.state is not ProjectionGenerationState.ACTIVE:
                raise IntegratedStateError(
                    "integrated proof generation is not ACTIVE"
                )
            active = tuple(
                item
                for item in system.projections.generations(
                    self._environment.family_id,
                    limit=100,
                    proof=proof,
                )
                if item.state is ProjectionGenerationState.ACTIVE
            )
            if len(active) != 1 or active[0].generation_id != generation_id:
                raise IntegratedStateError(
                    "integrated proof target is not the sole authority-selected ACTIVE generation"
                )

            fixture_event = self._fixture_event(system, fixture, proof=proof)
            canonical_ids = self._fixture_canonical_ids(
                fixture_event,
                manifest,
            )
            response = system.structural.read_active(
                StructuralActiveReadRequest(
                    family_id=self._environment.family_id,
                    canonical_ids=canonical_ids,
                    query_valid_time=query_valid_time,
                    limit=max(len(canonical_ids) * 4, 32),
                ),
                proof=proof,
            )
            if response.metadata.generation_id != generation_id:
                raise IntegratedStateError(
                    "ACTIVE read selected another generation"
                )
            if not any(
                relation.source_event_id == str(fixture.fixture_event_id)
                and relation.aggregate_type == "integrated_fixture"
                and relation.aggregate_id == str(fixture.fixture_aggregate_id)
                and relation.object_admission_id == str(fixture.admission_id)
                for relation in response.relations
            ):
                raise IntegratedStateError(
                    "ACTIVE structural read lacks exact fixture provenance"
                )
            return IntegratedProjectionAuthority(
                generation=generation,
                response=response,
                rebuilt=rebuilt,
                promoted=promoted,
            )
        finally:
            system.close()

    def build_context(
        self,
        fixture: IntegratedFixtureAuthority,
        manifest: IntegratedFixtureManifest,
        projection: IntegratedProjectionAuthority,
        *,
        context_id: IntegratedRetrievalContextId,
        proof: AuthenticationProof,
    ) -> IntegratedRetrievalContext:
        if not isinstance(context_id, IntegratedRetrievalContextId):
            raise TypeError("integrated retrieval-context identity must be typed")
        system = open_governed_object_authority_system(
            path=self._environment.path,
            object_root=self._environment.object_root,
            registry=self._commands,
            payload_schemas=self._schemas,
            admission_registry=self._environment.admission_registry,
            rights_policies=self._environment.rights_policies,
            hydration_policies=self._environment.hydration_policies,
            authenticator=self._environment.authenticator,
            authorizer=self._environment.authorizer,
            event_read_policy=self._environment.event_read_policy,
            object_limits=self._environment.object_limits,
            clock=self._environment.clock,
        )
        try:
            hydrated = system.objects.hydrate(
                HydrationRequest(
                    fixture.admission_id,
                    self._environment.fixture_hydration_purpose,
                ),
                proof=proof,
            )
            self._require_hydrated_manifest(hydrated, manifest)
        finally:
            system.close()

        response = projection.response
        exact_index = tuple(
            IntegratedExactIndexEntry(
                canonical_id=node.canonical_id,
                node_type=node.node_type,
                first_ledger_seq=node.first_ledger_seq,
                first_source_event_id=node.first_source_event_id,
                first_source_event_digest=node.first_source_event_digest,
            )
            for node in response.nodes
        )
        query_digest = digest_canonical(
            {
                "contract": "newsroom-integrated-query-v1",
                "family_id": response.metadata.family_id,
                "generation_id": str(response.metadata.generation_id),
                "canonical_ids": [
                    item.canonical_id for item in response.nodes
                ],
                "query_valid_time": (
                    response.metadata.query_valid_time.to_text()
                ),
                "authority_watermark": (
                    response.metadata.contiguous_ledger_seq
                ),
            }
        )
        return IntegratedRetrievalContext(
            context_id=context_id,
            fixture_id=fixture.fixture_id,
            fixture_aggregate_id=fixture.fixture_aggregate_id,
            fixture_event_id=fixture.fixture_event_id,
            admission_id=fixture.admission_id,
            metadata=response.metadata,
            nodes=response.nodes,
            relations=response.relations,
            exact_index=exact_index,
            hydrated_blob_digest=manifest.manifest_digest,
            hydration_policy_contract_digest=(
                hydrated.decision.policy_contract_digest
            ),
            hydration_access_decision_id=(
                hydrated.decision.access_decision_id
            ),
            manifest_digest=manifest.manifest_digest,
            retrieval_version=manifest.retrieval_version,
            query_digest=query_digest,
            known_omissions=(
                "No vector, full-text, Graphiti, model, embedding or live-source retrieval was executed.",
            ),
            recorded_at=hydrated.decision.decided_at,
        )

    def retained_context(
        self,
        context_id: IntegratedRetrievalContextId,
        *,
        proof: AuthenticationProof,
    ) -> IntegratedRetrievalContext | None:
        if not isinstance(context_id, IntegratedRetrievalContextId):
            raise TypeError("integrated retrieval-context identity must be typed")
        system = open_candidate_admission_authority_system(
            path=self._environment.path,
            registry=self._commands,
            payload_schemas=self._schemas,
            contracts=self._environment.projection_contracts,
            authenticator=self._environment.authenticator,
            authorizer=self._environment.authorizer,
            event_read_policy=self._environment.event_read_policy,
            projection_read_policy=self._environment.projection_read_policy,
            neo4j_config=self._environment.neo4j_config,
            clock=self._environment.clock,
        )
        try:
            try:
                return system.candidates.context(context_id, proof=proof)
            except KeyError:
                return None
        finally:
            system.close()

    def admit_candidate(
        self,
        request: CandidateAdmissionRequest,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        *,
        proof: AuthenticationProof,
    ) -> CandidateAdmissionView:
        system = open_candidate_admission_authority_system(
            path=self._environment.path,
            registry=self._commands,
            payload_schemas=self._schemas,
            contracts=self._environment.projection_contracts,
            authenticator=self._environment.authenticator,
            authorizer=self._environment.authorizer,
            event_read_policy=self._environment.event_read_policy,
            projection_read_policy=self._environment.projection_read_policy,
            neo4j_config=self._environment.neo4j_config,
            clock=self._environment.clock,
        )
        try:
            return system.candidates.admit(
                request,
                context=context,
                manifest=manifest,
                proof=proof,
            )
        finally:
            system.close()

    def run(
        self,
        manifest: IntegratedFixtureManifest,
        *,
        generation_id: ProjectionGenerationId,
        context_id: IntegratedRetrievalContextId,
        proposal_id: IntegratedTriageProposalId,
        route: CandidateRoute,
        query_valid_time: UtcTimestamp,
        through_ledger_seq: int | None = None,
        proof: AuthenticationProof,
        keys: IntegratedProofKeys,
    ) -> IntegratedFoundationProofResult:
        fixture = self.record_fixture(manifest, proof=proof, keys=keys)
        projection = self.ensure_projection(
            fixture,
            manifest,
            generation_id=generation_id,
            query_valid_time=query_valid_time,
            through_ledger_seq=through_ledger_seq,
            proof=proof,
            keys=keys,
        )
        context = self.retained_context(context_id, proof=proof)
        if context is None:
            context = self.build_context(
                fixture,
                manifest,
                projection,
                context_id=context_id,
                proof=proof,
            )
        elif (
            context.fixture_id != fixture.fixture_id
            or context.fixture_aggregate_id != fixture.fixture_aggregate_id
            or context.fixture_event_id != fixture.fixture_event_id
            or context.admission_id != fixture.admission_id
            or context.manifest_digest != manifest.manifest_digest
            or context.metadata.generation_id
            != projection.generation.generation_id
            or context.metadata.contiguous_ledger_seq
            != projection.response.metadata.contiguous_ledger_seq
            or context.metadata.query_valid_time != query_valid_time
        ):
            raise IntegratedStateError(
                "retrieval context identity belongs to different proof evidence"
            )
        candidate = self.admit_candidate(
            CandidateAdmissionRequest(
                proposal_id=proposal_id,
                route=route,
                fixture_id=manifest.fixture_id,
                expected_context_digest=context.context_digest,
                idempotency_key=keys.value("candidate-admission"),
            ),
            context,
            manifest,
            proof=proof,
        )
        return IntegratedFoundationProofResult(
            fixture=fixture,
            projection=projection,
            context=context,
            candidate=candidate,
        )

    def _find_generation(
        self,
        system: Any,
        generation_id: ProjectionGenerationId,
        *,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationView | None:
        return next(
            (
                item
                for item in system.projections.generations(
                    self._environment.family_id,
                    limit=100,
                    proof=proof,
                )
                if item.generation_id == generation_id
            ),
            None,
        )

    def _require_generation(
        self,
        system: Any,
        generation_id: ProjectionGenerationId,
        *,
        proof: AuthenticationProof,
    ) -> ProjectionGenerationView:
        generation = self._find_generation(
            system,
            generation_id,
            proof=proof,
        )
        if generation is None:
            raise IntegratedStateError(
                "integrated proof generation is absent"
            )
        return generation

    def _fixture_event(
        self,
        system: Any,
        fixture: IntegratedFixtureAuthority,
        *,
        proof: AuthenticationProof,
    ) -> Any:
        page = system.events.after(
            fixture.fixture_ledger_seq - 1,
            limit=1,
            proof=proof,
        )
        if len(page) != 1 or page[0].event_id != str(
            fixture.fixture_event_id
        ):
            raise IntegratedStateError(
                "integrated fixture event is absent from authority"
            )
        return page[0]

    def _fixture_canonical_ids(
        self,
        event: Any,
        manifest: IntegratedFixtureManifest,
    ) -> tuple[str, ...]:
        family = self._environment.projection_contracts.family(
            self._environment.family_id
        )
        mapping_contract = (
            self._environment.projection_contracts.mappings.resolve_digest(
                family.mapping_contract_digest
            )
        )
        mapping = mapping_contract.resolve(event.event_type)
        if mapping is None:
            raise IntegratedStateError(
                "fixture event lacks a structural mapping"
            )
        if any(
            binding.identity_source is ProjectionIdentitySource.PAYLOAD_FIELD
            for binding in mapping.nodes
        ):
            raise IntegratedStateError(
                "object-backed fixture mapping cannot require caller-decoded payload fields"
            )
        context = StructuralIdentityContext(
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            aggregate_version=event.aggregate_version,
            event_id=event.event_id,
            payload_id=event.payload_id,
            payload=manifest.canonical_value(),
        )
        return tuple(
            sorted(
                {
                    canonical_node_id(binding, context)
                    for binding in mapping.nodes
                }
            )
        )

    @staticmethod
    def _require_hydrated_manifest(
        hydrated: HydratedObject,
        manifest: IntegratedFixtureManifest,
    ) -> None:
        if hydrated.data != manifest.canonical_bytes:
            raise IntegratedStateError(
                "authoritative hydration differs from the fixture manifest"
            )
        if hydrated.decision.allowed_bytes != len(hydrated.data):
            raise IntegratedStateError(
                "hydration decision byte range differs from returned authority"
            )
        if hydrated.decision.offset != 0:
            raise IntegratedStateError(
                "integrated fixture hydration must begin at byte zero"
            )


__all__ = [
    "IntegratedFixtureAuthority",
    "IntegratedFoundationProofController",
    "IntegratedFoundationProofResult",
    "IntegratedProjectionAuthority",
    "IntegratedProofEnvironment",
    "IntegratedProofKeys",
]
