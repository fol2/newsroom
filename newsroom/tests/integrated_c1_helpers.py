from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from newsroom.authority import (
    AggregateId,
    AuthenticationProof,
    EventId,
    EventReadPolicy,
    HydrationRequest,
    MetadataClass,
    ObjectAdmissionPayload,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    UtcTimestamp,
    digest_canonical,
)
from newsroom.authority._neo4j_projection_system import _open_with_adapter
from newsroom.authority.object_policy import merge_authority_registries
from newsroom.authority.policy import CommandRegistry, PayloadSchemaRegistry
from newsroom.integrated import (
    CandidateAdmissionRequest,
    CandidateRoute,
    IntegratedExactIndexEntry,
    IntegratedFixtureId,
    IntegratedFixtureManifest,
    IntegratedHypothesisVersionId,
    IntegratedLeadId,
    IntegratedRetrievalContext,
    IntegratedRetrievalContextId,
    IntegratedSignalId,
    IntegratedTriageProposalId,
    IntegratedUrgency,
    INTEGRATED_FIXTURE_COMMAND,
    merge_integrated_authority_registries,
    open_candidate_admission_authority_system,
)
from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
)
from newsroom.projection.neo4j import (
    StructuralActiveReadRequest,
    StructuralGenerationValidationRequest,
    StructuralRebuildRequest,
)

from .authority_a2b_helpers import admit, open_object_system
from .authority_event_helpers import payload_schemas
from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import (
    FAMILY_ID,
    projection_contracts,
    projection_read_policy,
    source_command_registry,
)
from .projection_b2_helpers import MemoryNeo4jAdapter


FIXTURE_ID = IntegratedFixtureId.parse(
    "00000000-0000-4000-8000-000000000401"
)
SIGNAL_ID = IntegratedSignalId.parse(
    "00000000-0000-4000-8000-000000000402"
)
LEAD_ID = IntegratedLeadId.parse(
    "00000000-0000-4000-8000-000000000403"
)
HYPOTHESIS_ID = IntegratedHypothesisVersionId.parse(
    "00000000-0000-4000-8000-000000000404"
)
PROPOSAL_ID = IntegratedTriageProposalId.parse(
    "00000000-0000-4000-8000-000000000405"
)
SECOND_PROPOSAL_ID = IntegratedTriageProposalId.parse(
    "00000000-0000-4000-8000-000000000406"
)


@dataclass(frozen=True, slots=True)
class IntegratedFixtureState:
    manifest: IntegratedFixtureManifest
    commands: CommandRegistry
    schemas: PayloadSchemaRegistry
    fixture_aggregate_id: AggregateId
    fixture_event_id: EventId
    fixture_ledger_seq: int
    admission_id: object


@dataclass(frozen=True, slots=True)
class IntegratedGraphState:
    context: IntegratedRetrievalContext
    adapter: MemoryNeo4jAdapter
    generation_id: ProjectionGenerationId


def proof() -> AuthenticationProof:
    return AuthenticationProof(method="STATIC_TOKEN", credential="token-1")


def manifest() -> IntegratedFixtureManifest:
    return IntegratedFixtureManifest(
        fixture_id=FIXTURE_ID,
        signal_id=SIGNAL_ID,
        lead_id=LEAD_ID,
        hypothesis_version_id=HYPOTHESIS_ID,
        coverage_basis="active_public_interest",
        geography="hong_kong",
        category="public_policy",
        urgency=IntegratedUrgency.TIME_SENSITIVE,
        hypothesis_statement=(
            "The synthetic fixture may represent a material policy development."
        ),
        hypothesis_trust_scope=TrustScope.PROPOSED,
        likely_new_information=(
            "A versioned synthetic authority record changed under a fixed fixture."
        ),
        reader_utility_basis=(
            "The fixture proves an evidence-acquisition boundary without factual use."
        ),
        uncertainties=("No real-world claim is verified.",),
        evidence_objectives=(
            "Hydrate the exact governed fixture bytes.",
            "Confirm complete authority and projection lineage.",
        ),
        policy_version="fixture_policy_v1",
        retrieval_version="integrated_retrieval_v1",
        admission_version="candidate_admission_v1",
    )


def integrated_registries() -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    object_commands, object_schemas = merge_authority_registries(
        command_registry=source_command_registry(),
        payload_schemas=payload_schemas(),
    )
    return merge_integrated_authority_registries(
        command_registry=object_commands,
        payload_schemas=object_schemas,
    )


def event_policy() -> EventReadPolicy:
    return EventReadPolicy(
        policy_id="integrated-foundation-reader-v1",
        purpose="integrated.foundation.proof",
        required_scope="authority.fixture.events.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_security_scopes=frozenset(
            {
                "authority.internal",
                "authority.protected",
                "authority.object_lifecycle",
                "authority.projection",
                "authority.integrated",
            }
        ),
        allowed_trust_scopes=frozenset(
            {TrustScope.OBSERVED, TrustScope.ADMITTED}
        ),
        metadata_classes=frozenset(
            {
                MetadataClass.ROUTING,
                MetadataClass.PROVENANCE,
                MetadataClass.RESULT,
            }
        ),
        max_results=1000,
    )


def scopes() -> frozenset[str]:
    return frozenset(
        {
            "authority.observed.write",
            "authority.admitted.write",
            "authority.fixture.events.read",
            "authority.objects.admit",
            "authority.objects.read",
            "authority.objects.manage",
            "authority.objects.lifecycle.write",
            "authority.projection.manage",
            "authority.projection.write",
            "authority.projection.read",
            "authority.candidate.admit",
        }
    )


def authenticator() -> StaticAuthenticator:
    return StaticAuthenticator(
        credentials={"token-1": StaticPrincipal("principal.alpha")},
        authority_domain="newsroom.authority",
    )


def authorizer() -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="authz-v1",
        grants_by_principal={"principal.alpha": scopes()},
    )


def seed_fixture_authority(
    database: Path,
    *,
    object_root: Path,
    clock: Callable[[], UtcTimestamp] | None = None,
) -> IntegratedFixtureState:
    commands, schemas = integrated_registries()
    current_manifest = manifest()
    system = open_object_system(
        database,
        object_root=object_root,
        scopes=scopes(),
        authenticator=authenticator(),
        authorizer=authorizer(),
        clock=clock or (lambda: FIXED_NOW),
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        admitted = admit(
            system,
            data=current_manifest.canonical_bytes,
            key="integrated-fixture-object-admission",
        ).admission
        if admitted.blob.blob_digest != current_manifest.manifest_digest:
            raise AssertionError("fixture bytes and manifest digest differ")
        fixture_aggregate_id = AggregateId(FIXTURE_ID.value)
        committed = system.commands.execute(
            SemanticCommand(
                command_type=INTEGRATED_FIXTURE_COMMAND,
                aggregate_id=fixture_aggregate_id,
                expected_aggregate_version=0,
                payload=ObjectAdmissionPayload(admitted.admission_id),
                idempotency_key="integrated-fixture-authority-command",
            ),
            proof=proof(),
        )
        replay = system.commands.execute(
            SemanticCommand(
                command_type=INTEGRATED_FIXTURE_COMMAND,
                aggregate_id=fixture_aggregate_id,
                expected_aggregate_version=0,
                payload=ObjectAdmissionPayload(admitted.admission_id),
                idempotency_key="integrated-fixture-authority-command",
            ),
            proof=proof(),
        )
        if not replay.replayed or replay.event_id != committed.event_id:
            raise AssertionError("fixture authority replay is not exact")
        return IntegratedFixtureState(
            manifest=current_manifest,
            commands=commands,
            schemas=schemas,
            fixture_aggregate_id=fixture_aggregate_id,
            fixture_event_id=EventId.parse(committed.event_id),
            fixture_ledger_seq=committed.ledger_seq,
            admission_id=admitted.admission_id,
        )
    finally:
        system.close()


def _generation(system, generation_id: ProjectionGenerationId):
    return next(
        item
        for item in system.projections.generations(FAMILY_ID, proof=proof())
        if item.generation_id == generation_id
    )


def open_graph_system(
    database: Path,
    state: IntegratedFixtureState,
    adapter: MemoryNeo4jAdapter,
    *,
    clock: Callable[[], UtcTimestamp] | None = None,
):
    return _open_with_adapter(
        path=database,
        registry=state.commands,
        payload_schemas=state.schemas,
        contracts=projection_contracts(),
        authenticator=authenticator(),
        authorizer=authorizer(),
        event_read_policy=event_policy(),
        projection_read_policy=projection_read_policy(),
        adapter=adapter,
        clock=clock or (lambda: FIXED_NOW),
    )


def build_active_graph_context(
    database: Path,
    state: IntegratedFixtureState,
    *,
    object_root: Path,
    adapter: MemoryNeo4jAdapter | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
) -> IntegratedGraphState:
    selected_adapter = adapter or MemoryNeo4jAdapter()
    system = open_graph_system(
        database,
        state,
        selected_adapter,
        clock=clock,
    )
    try:
        system.projections.register_family(
            ProjectionFamilyRegistrationRequest(
                FAMILY_ID,
                "integrated-family-register",
            ),
            proof=proof(),
        )
        generation = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                ProjectionGenerationId.new(),
                FAMILY_ID,
                "INTEGRATED_FOUNDATION_BUILD",
                "integrated-generation-create",
            ),
            proof=proof(),
        )
        through = system.events.after(0, limit=1000, proof=proof())[-1].ledger_seq
        rebuilt = system.structural.rebuild(
            StructuralRebuildRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    generation.authority_aggregate_version
                ),
                through_ledger_seq=through,
                reason_code="INTEGRATED_FOUNDATION_REBUILD",
                idempotency_key="integrated-generation-rebuild",
            ),
            proof=proof(),
        )
        validating = _generation(system, generation.generation_id)
        validation = system.structural.validate_generation(
            StructuralGenerationValidationRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    validating.authority_aggregate_version
                ),
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                reason_code="INTEGRATED_FOUNDATION_VALIDATE",
                idempotency_key="integrated-generation-validate",
            ),
            proof=proof(),
        )
        validating = _generation(system, generation.generation_id)
        system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    validating.authority_aggregate_version
                ),
                checkpoint_ledger_seq=validation.checkpoint_ledger_seq,
                validation_digest=validation.validation_digest,
                reason_code="INTEGRATED_FOUNDATION_PROMOTE",
                idempotency_key="integrated-generation-promote",
            ),
            proof=proof(),
        )
        batches = [
            batch
            for (stored_generation, _), batch in sorted(
                selected_adapter.deliveries.items()
            )
            if stored_generation == str(generation.generation_id)
        ]
        canonical_ids = tuple(
            sorted(
                {
                    node.canonical_id
                    for batch in batches
                    for node in batch.nodes
                }
            )
        )
        response = system.structural.read_active(
            StructuralActiveReadRequest(
                family_id=FAMILY_ID,
                canonical_ids=canonical_ids,
                query_valid_time=FIXED_NOW,
                limit=1000,
            ),
            proof=proof(),
        )
    finally:
        system.close()

    object_system = open_object_system(
        database,
        object_root=object_root,
        scopes=scopes(),
        authenticator=authenticator(),
        authorizer=authorizer(),
        clock=clock or (lambda: FIXED_NOW),
        command_registry=state.commands,
        payload_schema_registry=state.schemas,
    )
    try:
        hydrated = object_system.objects.hydrate(
            HydrationRequest(state.admission_id, "project.discovery"),
            proof=proof(),
        )
        if hydrated.data != state.manifest.canonical_bytes:
            raise AssertionError("hydrated fixture differs from authority bytes")
    finally:
        object_system.close()

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
    context = IntegratedRetrievalContext(
        context_id=IntegratedRetrievalContextId.new(),
        fixture_id=state.manifest.fixture_id,
        fixture_aggregate_id=state.fixture_aggregate_id,
        fixture_event_id=state.fixture_event_id,
        admission_id=state.admission_id,
        metadata=response.metadata,
        nodes=response.nodes,
        relations=response.relations,
        exact_index=exact_index,
        hydrated_blob_digest=state.manifest.manifest_digest,
        hydration_policy_contract_digest=(
            hydrated.decision.policy_contract_digest
        ),
        hydration_access_decision_id=hydrated.decision.access_decision_id,
        manifest_digest=state.manifest.manifest_digest,
        retrieval_version=state.manifest.retrieval_version,
        query_digest=digest_canonical(
            {"canonical_ids": list(canonical_ids)}
        ),
        known_omissions=(
            "No vector, full-text, model or live-source retrieval was executed.",
        ),
        recorded_at=hydrated.decision.decided_at,
    )
    return IntegratedGraphState(
        context=context,
        adapter=selected_adapter,
        generation_id=generation.generation_id,
    )


def open_candidate_system(
    database: Path,
    state: IntegratedFixtureState,
    *,
    clock: Callable[[], UtcTimestamp] | None = None,
):
    return open_candidate_admission_authority_system(
        path=database,
        registry=state.commands,
        payload_schemas=state.schemas,
        contracts=projection_contracts(),
        authenticator=authenticator(),
        authorizer=authorizer(),
        event_read_policy=event_policy(),
        clock=clock or (lambda: FIXED_NOW),
    )


def candidate_request(
    context: IntegratedRetrievalContext,
    *,
    proposal_id: IntegratedTriageProposalId = PROPOSAL_ID,
    key: str = "integrated-candidate-admission",
) -> CandidateAdmissionRequest:
    return CandidateAdmissionRequest(
        proposal_id=proposal_id,
        route=CandidateRoute.NEW_EVENT,
        fixture_id=FIXTURE_ID,
        expected_context_digest=context.context_digest,
        idempotency_key=key,
    )


__all__ = [
    "FIXTURE_ID",
    "PROPOSAL_ID",
    "SECOND_PROPOSAL_ID",
    "IntegratedFixtureState",
    "IntegratedGraphState",
    "build_active_graph_context",
    "candidate_request",
    "manifest",
    "open_candidate_system",
    "open_graph_system",
    "proof",
    "seed_fixture_authority",
]
