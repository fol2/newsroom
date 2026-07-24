from __future__ import annotations

import os
from pathlib import Path

import pytest

from newsroom.authority import (
    HydrationRequest,
    ObjectAdmissionDenied,
    ObjectHydrationDenied,
    ObjectLimits,
    UtcTimestamp,
)
from newsroom.integrated import (
    CandidateAdmissionOutcome,
    CandidateAdmissionRequest,
    CandidateRoute,
    IntegratedFoundationProofController,
    IntegratedProofEnvironment,
    IntegratedProofKeys,
    IntegratedRetrievalContextId,
    IntegratedStateError,
)
from newsroom.projection import ProjectionGenerationId
from newsroom.projection.neo4j import Neo4jProjectorConfig
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter

from .authority_a2b_helpers import _policy_registries, open_object_system
from .integrated_c1_helpers import (
    PROPOSAL_ID,
    SECOND_PROPOSAL_ID,
    authenticator,
    authorizer,
    event_policy,
    integrated_registries,
    manifest,
    proof,
    scopes,
)
from .projection_b1_helpers import (
    FAMILY_ID,
    projection_contracts,
    projection_read_policy,
)


_REQUIRED_FLAG = "NEWSROOM_NEO4J_SERVICE_REQUIRED"


def _service_config() -> Neo4jProjectorConfig:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip(
            "actual Neo4j service is required only by the permanent graph gate"
        )
    return Neo4jProjectorConfig.from_environment()


def _limits() -> ObjectLimits:
    return ObjectLimits(
        global_max_bytes=1024 * 1024,
        class_max_bytes={"source_capture": 1024 * 1024},
        max_read_bytes=1024 * 1024,
        min_free_bytes=0,
        io_chunk_bytes=64,
        max_staging_bytes=1024 * 1024,
        max_range_bytes=1024 * 1024,
    )


def _environment(
    tmp_path: Path,
    config: Neo4jProjectorConfig,
) -> IntegratedProofEnvironment:
    rights, hydration, admissions = _policy_registries()
    commands, schemas = integrated_registries()
    return IntegratedProofEnvironment(
        path=tmp_path / "authority.sqlite3",
        object_root=tmp_path / "objects",
        command_registry=commands,
        payload_schemas=schemas,
        admission_registry=admissions,
        rights_policies=rights,
        hydration_policies=hydration,
        authenticator=authenticator(),
        authorizer=authorizer(),
        event_read_policy=event_policy(),
        projection_read_policy=projection_read_policy(),
        projection_contracts=projection_contracts(),
        object_limits=_limits(),
        neo4j_config=config,
        family_id=FAMILY_ID,
        fixture_admission_type="source.capture",
        fixture_hydration_purpose="project.discovery",
        clock=UtcTimestamp.now,
    )


def _cleanup(
    config: Neo4jProjectorConfig,
    *generation_ids: ProjectionGenerationId,
) -> None:
    adapter = _open_neo4j_adapter(config)
    try:
        adapter.verify_compatibility()
        for generation_id in generation_ids:
            adapter.cleanup_generation(str(generation_id))
    finally:
        adapter.close()


def test_actual_service_integrated_foundation_replay_recovery_and_tombstone(
    tmp_path: Path,
) -> None:
    config = _service_config()
    environment = _environment(tmp_path, config)
    controller = IntegratedFoundationProofController(environment)
    current_manifest = manifest()
    primary_generation = ProjectionGenerationId.new()
    recovery_generation = ProjectionGenerationId.new()
    tombstone_generation = ProjectionGenerationId.new()
    primary_context = IntegratedRetrievalContextId.new()
    keys = IntegratedProofKeys("integrated-actual-primary")

    try:
        initial = controller.run(
            current_manifest,
            generation_id=primary_generation,
            context_id=primary_context,
            proposal_id=PROPOSAL_ID,
            route=CandidateRoute.NEW_EVENT,
            query_valid_time=UtcTimestamp.now(),
            proof=proof(),
            keys=keys,
        )
        assert initial.candidate.outcome is CandidateAdmissionOutcome.ADMITTED
        assert initial.fixture.command_replayed is False
        assert initial.fixture.admission_replayed is False
        assert initial.projection.rebuilt is True
        assert initial.projection.promoted is True
        assert initial.context.metadata.generation_id == primary_generation
        assert initial.context.hydrated_blob_digest == (
            current_manifest.manifest_digest
        )

        replay = controller.run(
            current_manifest,
            generation_id=primary_generation,
            context_id=primary_context,
            proposal_id=PROPOSAL_ID,
            route=CandidateRoute.NEW_EVENT,
            query_valid_time=initial.context.metadata.query_valid_time,
            proof=proof(),
            keys=keys,
        )
        assert replay.fixture.command_replayed is True
        assert replay.fixture.admission_replayed is True
        assert replay.projection.rebuilt is False
        assert replay.projection.promoted is False
        assert replay.candidate == initial.candidate

        _cleanup(config, primary_generation)
        with pytest.raises(
            IntegratedStateError,
            match="lacks exact fixture provenance",
        ):
            controller.ensure_projection(
                initial.fixture,
                current_manifest,
                generation_id=primary_generation,
                query_valid_time=UtcTimestamp.now(),
                through_ledger_seq=None,
                proof=proof(),
                keys=keys,
            )

        recovery_keys = IntegratedProofKeys("integrated-actual-recovery")
        recovered_projection = controller.ensure_projection(
            initial.fixture,
            current_manifest,
            generation_id=recovery_generation,
            query_valid_time=UtcTimestamp.now(),
            through_ledger_seq=None,
            proof=proof(),
            keys=recovery_keys,
        )
        recovered_context = controller.build_context(
            initial.fixture,
            current_manifest,
            recovered_projection,
            context_id=IntegratedRetrievalContextId.new(),
            proof=proof(),
        )
        deduplicated = controller.admit_candidate(
            CandidateAdmissionRequest(
                proposal_id=SECOND_PROPOSAL_ID,
                route=CandidateRoute.NEW_EVENT,
                fixture_id=current_manifest.fixture_id,
                expected_context_digest=recovered_context.context_digest,
                idempotency_key="integrated-actual-recovery-candidate",
            ),
            recovered_context,
            current_manifest,
            proof=proof(),
        )
        assert deduplicated.outcome is CandidateAdmissionOutcome.DEDUPLICATED
        assert deduplicated.candidate_id == initial.candidate.candidate_id
        assert recovered_context.metadata.generation_id == recovery_generation
        assert controller.retained_context(
            recovered_context.context_id,
            proof=proof(),
        ) == recovered_context

        rights, hydration, admissions = _policy_registries()
        object_system = open_object_system(
            environment.path,
            object_root=environment.object_root,
            scopes=scopes(),
            policy_registries=(rights, hydration, admissions),
            object_limits=environment.object_limits,
            authenticator=environment.authenticator,
            authorizer=environment.authorizer,
            clock=environment.clock,
            command_registry=environment.command_registry,
            payload_schema_registry=environment.payload_schemas,
        )
        try:
            object_system.objects.revoke(
                initial.fixture.admission_id,
                reason_code="INTEGRATED_TOMBSTONE_REVOKE",
                idempotency_key="integrated-actual-revoke",
                proof=proof(),
            )
            deletion = object_system.objects.request_deletion(
                current_manifest.manifest_digest,
                reason_code="INTEGRATED_TOMBSTONE_REQUEST",
                idempotency_key="integrated-actual-delete",
                proof=proof(),
            )
            object_system.objects.tombstone(
                deletion.deletion_id,
                reason_code="INTEGRATED_TOMBSTONE_COMMIT",
                idempotency_key="integrated-actual-tombstone",
                proof=proof(),
            )
            tombstone_ledger_seq = object_system.events.after(
                0,
                limit=1000,
                proof=proof(),
            )[-1].ledger_seq
            with pytest.raises((ObjectAdmissionDenied, ObjectHydrationDenied)):
                object_system.objects.hydrate(
                    HydrationRequest(
                        initial.fixture.admission_id,
                        "project.discovery",
                    ),
                    proof=proof(),
                )
        finally:
            object_system.close()

        with pytest.raises(
            IntegratedStateError,
            match="lacks exact fixture provenance",
        ):
            controller.ensure_projection(
                initial.fixture,
                current_manifest,
                generation_id=tombstone_generation,
                query_valid_time=UtcTimestamp.now(),
                through_ledger_seq=tombstone_ledger_seq,
                proof=proof(),
                keys=IntegratedProofKeys("integrated-actual-tombstone"),
            )
    finally:
        _cleanup(
            config,
            primary_generation,
            recovery_generation,
            tombstone_generation,
        )
