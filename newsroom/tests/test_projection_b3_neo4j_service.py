from __future__ import annotations

import os
from pathlib import Path

import pytest

from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionStateError,
    StructuralIdentityContext,
    canonical_node_id,
)
from newsroom.projection.neo4j import (
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    StructuralActiveReadRequest,
    StructuralGenerationValidationRequest,
    StructuralReadRequest,
    StructuralRebuildRequest,
)
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter

from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import FAMILY_ID, projection_contracts
from .projection_b2_helpers import (
    open_b2_service_system,
    proof,
    source_command,
)


_REQUIRED_FLAG = "NEWSROOM_NEO4J_SERVICE_REQUIRED"


def _service_config() -> Neo4jProjectorConfig:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("actual Neo4j service is required only by the permanent graph gate")
    return Neo4jProjectorConfig.from_environment()


def _register(system) -> None:
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(
            FAMILY_ID,
            "b3-service-family-register",
        ),
        proof=proof(),
    )


def _create_generation(system, *, suffix: str):
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "B3_ACTUAL_SERVICE_REBUILD",
            f"b3-service-generation-{suffix}",
        ),
        proof=proof(),
    )


def _source_event(system, *, key: str):
    command = system.commands.execute(source_command(key=key), proof=proof())
    return next(
        event
        for event in system.events.after(0, limit=1000, proof=proof())
        if event.command_id == str(command.command_id)
    )


def _canonical_ids_for_source_event(event) -> tuple[str, ...]:
    contracts = projection_contracts()
    family = contracts.family(FAMILY_ID)
    mapping_contract = contracts.mappings.resolve_digest(
        family.mapping_contract_digest
    )
    mapping = mapping_contract.resolve(event.event_type)
    assert mapping is not None
    context = StructuralIdentityContext(
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        aggregate_version=event.aggregate_version,
        event_id=event.event_id,
        payload_id=event.payload_id,
        payload={"headline": "B2 fixture", "count": 1},
    )
    return tuple(canonical_node_id(binding, context) for binding in mapping.nodes)


def _rebuild_request(system, generation, *, key: str) -> StructuralRebuildRequest:
    through = system.events.after(0, limit=1000, proof=proof())[-1].ledger_seq
    current = next(
        item
        for item in system.projections.generations(FAMILY_ID, proof=proof())
        if item.generation_id == generation.generation_id
    )
    return StructuralRebuildRequest(
        generation_id=generation.generation_id,
        expected_authority_version=current.authority_aggregate_version,
        through_ledger_seq=through,
        reason_code="B3_ACTUAL_SERVICE_GRAPH_LOSS",
        idempotency_key=key,
    )


def _read(system, generation_id, canonical_ids):
    return system.structural.read(
        StructuralReadRequest(
            generation_id,
            canonical_ids,
            FIXED_NOW,
            limit=100,
        ),
        proof=proof(),
    )


def _cleanup(config: Neo4jProjectorConfig, *generation_ids: ProjectionGenerationId) -> None:
    adapter = _open_neo4j_adapter(config)
    try:
        adapter.verify_compatibility()
        for generation_id in generation_ids:
            adapter.cleanup_generation(str(generation_id))
    finally:
        adapter.close()



def test_actual_service_active_read_resolves_only_authority_promoted_generation(
    tmp_path: Path,
) -> None:
    config = _service_config()
    authority_path = tmp_path / "authority.sqlite3"
    generations: list[ProjectionGenerationId] = []
    system = open_b2_service_system(authority_path, config)
    try:
        source = _source_event(system, key="b3-service-active-source")
        canonical_ids = _canonical_ids_for_source_event(source)
        _register(system)
        active = _create_generation(system, suffix="active-serving")
        generations.append(active.generation_id)
        rebuilt = system.structural.rebuild(
            _rebuild_request(
                system,
                active,
                key="b3-service-active-rebuild",
            ),
            proof=proof(),
        )
        request = StructuralActiveReadRequest(
            family_id=FAMILY_ID,
            canonical_ids=canonical_ids,
            query_valid_time=FIXED_NOW,
            limit=100,
        )

        with pytest.raises(
            ProjectionStateError,
            match="no authority-selected active generation",
        ):
            system.structural.read_active(request, proof=proof())

        current = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == active.generation_id
        )
        validation = system.structural.validate_generation(
            StructuralGenerationValidationRequest(
                generation_id=current.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                reason_code="B3_ACTUAL_SERVICE_ACTIVE_VALIDATE",
                idempotency_key="b3-service-active-validate",
            ),
            proof=proof(),
        )
        validating = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == active.generation_id
        )
        promoted = system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                generation_id=validating.generation_id,
                expected_authority_version=(
                    validating.authority_aggregate_version
                ),
                checkpoint_ledger_seq=validation.checkpoint_ledger_seq,
                validation_digest=validation.validation_digest,
                reason_code="B3_ACTUAL_SERVICE_ACTIVE_PROMOTE",
                idempotency_key="b3-service-active-promote",
            ),
            proof=proof(),
        )
        assert promoted.generation.state is ProjectionGenerationState.ACTIVE

        response = system.structural.read_active(request, proof=proof())
        assert response.metadata.generation_id == active.generation_id
        assert response.metadata.generation_state is ProjectionGenerationState.ACTIVE
        assert response.nodes
        assert response.relations

        newer = _create_generation(system, suffix="newer-building")
        generations.append(newer.generation_id)
        assert newer.state is ProjectionGenerationState.BUILDING
        still_active = system.structural.read_active(request, proof=proof())
        assert still_active.metadata.generation_id == active.generation_id
        assert still_active == response
    finally:
        system.close()
        if generations:
            _cleanup(config, *generations)

def test_actual_service_graph_loss_and_process_restart_rebuild_from_authority(
    tmp_path: Path,
) -> None:
    config = _service_config()
    authority_path = tmp_path / "authority.sqlite3"
    generation_id: ProjectionGenerationId | None = None
    request: StructuralRebuildRequest | None = None
    canonical_ids: tuple[str, ...] = ()
    before_events = ()

    system = open_b2_service_system(authority_path, config)
    try:
        source = _source_event(system, key="b3-service-loss-source")
        canonical_ids = _canonical_ids_for_source_event(source)
        _register(system)
        generation = _create_generation(system, suffix="loss")
        generation_id = generation.generation_id
        request = _rebuild_request(
            system,
            generation,
            key="b3-service-loss-rebuild",
        )
        first = system.structural.rebuild(request, proof=proof())
        assert first.recorded_delivery_count == 1
        initial = _read(system, generation_id, canonical_ids)
        assert initial.nodes
        assert initial.relations
        before_events = system.events.after(0, limit=1000, proof=proof())
    finally:
        system.close()

    assert generation_id is not None
    assert request is not None
    try:
        _cleanup(config, generation_id)
        restarted = open_b2_service_system(authority_path, config)
        try:
            missing = _read(restarted, generation_id, canonical_ids)
            assert missing.nodes == ()
            assert missing.relations == ()
            current = next(
                item
                for item in restarted.projections.generations(
                    FAMILY_ID, proof=proof()
                )
                if item.generation_id == generation_id
            )
            validation_request = StructuralGenerationValidationRequest(
                generation_id=current.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=missing.metadata.contiguous_ledger_seq,
                reason_code="B3_ACTUAL_SERVICE_RECONCILE",
                idempotency_key="b3-service-loss-validation",
            )
            with pytest.raises(Neo4jIdentityConflict, match="differs"):
                restarted.structural.validate_generation(
                    validation_request,
                    proof=proof(),
                )

            replay = restarted.structural.rebuild(request, proof=proof())
            assert replay.authority_command_replayed is True
            assert replay.recorded_delivery_count == 0
            assert replay.reapplied_delivery_count == 1
            assert restarted.events.after(0, limit=1000, proof=proof()) == before_events

            restored = _read(restarted, generation_id, canonical_ids)
            assert restored.nodes == initial.nodes
            assert restored.relations == initial.relations
            validation = restarted.structural.validate_generation(
                validation_request,
                proof=proof(),
            )
            assert validation.checkpoint_ledger_seq == (
                restored.metadata.contiguous_ledger_seq
            )
        finally:
            restarted.close()
    finally:
        _cleanup(config, generation_id)


def test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace(
    tmp_path: Path,
) -> None:
    config = _service_config()
    authority_path = tmp_path / "authority.sqlite3"
    generations: list[ProjectionGenerationId] = []
    system = open_b2_service_system(authority_path, config)
    try:
        source = _source_event(system, key="b3-service-isolation-source")
        canonical_ids = _canonical_ids_for_source_event(source)
        _register(system)
        first = _create_generation(system, suffix="isolation-first")
        second = _create_generation(system, suffix="isolation-second")
        generations.extend((first.generation_id, second.generation_id))
        first_request = _rebuild_request(
            system,
            first,
            key="b3-service-isolation-first-rebuild",
        )
        second_request = _rebuild_request(
            system,
            second,
            key="b3-service-isolation-second-rebuild",
        )
        system.structural.rebuild(first_request, proof=proof())
        system.structural.rebuild(second_request, proof=proof())
        second_before = _read(system, second.generation_id, canonical_ids)
        assert second_before.nodes
        assert second_before.relations
    finally:
        system.close()

    try:
        _cleanup(config, first.generation_id)
        restarted = open_b2_service_system(authority_path, config)
        try:
            first_missing = _read(restarted, first.generation_id, canonical_ids)
            assert first_missing.nodes == ()
            assert first_missing.relations == ()
            second_after_loss = _read(restarted, second.generation_id, canonical_ids)
            assert second_after_loss == second_before

            replay = restarted.structural.rebuild(first_request, proof=proof())
            assert replay.authority_command_replayed is True
            assert replay.reapplied_delivery_count == 1
            assert _read(restarted, second.generation_id, canonical_ids) == second_before
        finally:
            restarted.close()
    finally:
        _cleanup(config, *generations)


def test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild(
    tmp_path: Path,
) -> None:
    from newsroom.projection import (
        ProjectionIdentitySource,
        ProjectionNodeType,
        StructuralNodeBinding,
    )
    from .projection_b3_tombstone_helpers import (
        create_tombstoned_structural_history,
        open_tombstone_service_system,
    )

    config = _service_config()
    authority_path = tmp_path / "authority.sqlite3"
    commands, schemas, history = create_tombstoned_structural_history(
        authority_path,
        tmp_path / "objects",
    )
    generation_id: ProjectionGenerationId | None = None
    request: StructuralRebuildRequest | None = None

    def canonical(event, node_type, identity_source):
        return canonical_node_id(
            StructuralNodeBinding("fixture", node_type, identity_source),
            StructuralIdentityContext(
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                aggregate_version=event.aggregate_version,
                event_id=event.event_id,
                payload_id=event.payload_id,
                payload={},
            ),
        )

    original_id = canonical(
        history.source_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE,
    )
    deletion_id = canonical(
        history.tombstone_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE,
    )
    tombstone_event_id = canonical(
        history.tombstone_event,
        ProjectionNodeType.LEDGER_EVENT,
        ProjectionIdentitySource.EVENT,
    )
    canonical_ids = (original_id, deletion_id, tombstone_event_id)

    system = open_tombstone_service_system(
        authority_path,
        config,
        commands,
        schemas,
    )
    try:
        _register(system)
        generation = _create_generation(system, suffix="tombstone")
        generation_id = generation.generation_id
        current = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == generation_id
        )
        request = StructuralRebuildRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            through_ledger_seq=history.tombstone_event.ledger_seq,
            reason_code="B3_ACTUAL_SERVICE_TOMBSTONE",
            idempotency_key="b3-service-tombstone-rebuild",
        )
        first = system.structural.rebuild(request, proof=proof())
        assert first.recorded_delivery_count == 2
        initial = _read(system, generation_id, canonical_ids)
        assert original_id not in {item.canonical_id for item in initial.nodes}
        assert all(
            item.object_admission_id != str(history.admission_id)
            for item in initial.relations
        )
        assert any(
            item.source_event_type == "governed_blob.deletion.tombstoned"
            for item in initial.relations
        )
    finally:
        system.close()

    assert generation_id is not None
    assert request is not None
    try:
        _cleanup(config, generation_id)
        restarted = open_tombstone_service_system(
            authority_path,
            config,
            commands,
            schemas,
        )
        try:
            replay = restarted.structural.rebuild(request, proof=proof())
            assert replay.authority_command_replayed is True
            assert replay.reapplied_delivery_count == 2
            rebuilt = _read(restarted, generation_id, canonical_ids)
            assert original_id not in {
                item.canonical_id for item in rebuilt.nodes
            }
            assert all(
                item.object_admission_id != str(history.admission_id)
                for item in rebuilt.relations
            )
            assert any(
                item.source_event_type == "governed_blob.deletion.tombstoned"
                for item in rebuilt.relations
            )
        finally:
            restarted.close()
    finally:
        _cleanup(config, generation_id)
