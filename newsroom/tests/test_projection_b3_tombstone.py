from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import digest_canonical
from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionIdentitySource,
    ProjectionNodeType,
    ProjectionRelationType,
    StructuralIdentityContext,
    StructuralNodeBinding,
    canonical_node_id,
)
from newsroom.projection.neo4j import (
    Neo4jIdentityConflict,
    StructuralGenerationValidationRequest,
    StructuralReadRequest,
    StructuralRebuildRequest,
)

from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import FAMILY_ID, proof
from .projection_b2_helpers import structural_batch
from .projection_b3_tombstone_helpers import (
    TombstoneMemoryNeo4jAdapter,
    TombstonedStructuralHistory,
    create_tombstoned_structural_history,
    open_tombstone_memory_system,
)



def _canonical_id(event, node_type, identity_source) -> str:
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


def _register_generation(system):
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(FAMILY_ID, "b3-tombstone-family"),
        proof=proof(),
    )
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "B3_TOMBSTONE_REBUILD",
            "b3-tombstone-generation",
        ),
        proof=proof(),
    )


def _read(system, generation_id, history: TombstonedStructuralHistory):
    original = _canonical_id(
        history.source_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE,
    )
    deletion = _canonical_id(
        history.tombstone_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE,
    )
    event = _canonical_id(
        history.tombstone_event,
        ProjectionNodeType.LEDGER_EVENT,
        ProjectionIdentitySource.EVENT,
    )
    return original, system.structural.read(
        StructuralReadRequest(
            generation_id,
            (original, deletion, event),
            FIXED_NOW,
            limit=100,
        ),
        proof=proof(),
    )


def _assert_non_resurrection(history, original_id: str, response) -> None:
    assert original_id not in {item.canonical_id for item in response.nodes}
    assert all(
        item.object_admission_id != str(history.admission_id)
        for item in response.relations
    )
    marker = [
        item
        for item in response.relations
        if item.source_event_type == "governed_blob.deletion.tombstoned"
    ]
    assert len(marker) == 1
    assert marker[0].relation_type is ProjectionRelationType.PROJECTED_FROM_EVENT
    assert marker[0].source_event_id == history.tombstone_event.event_id


def test_tombstone_survives_wipe_rebuild_duplicate_and_promotion(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    commands, schemas, history = create_tombstoned_structural_history(
        database,
        tmp_path / "objects",
    )
    adapter = TombstoneMemoryNeo4jAdapter()
    system = open_tombstone_memory_system(
        database,
        adapter,
        commands,
        schemas,
    )
    try:
        generation = _register_generation(system)
        current = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == generation.generation_id
        )
        request = StructuralRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            through_ledger_seq=history.tombstone_event.ledger_seq,
            reason_code="B3_TOMBSTONE_REBUILD",
            idempotency_key="b3-tombstone-rebuild",
        )
        first = system.structural.rebuild(request, proof=proof())
        assert first.recorded_delivery_count == 2
        original_id, initial = _read(system, generation.generation_id, history)
        _assert_non_resurrection(history, original_id, initial)

        adapter.deliveries.clear()
        replay = system.structural.rebuild(request, proof=proof())
        assert replay.authority_command_replayed is True
        assert replay.reapplied_delivery_count == 2
        original_id, rebuilt = _read(system, generation.generation_id, history)
        _assert_non_resurrection(history, original_id, rebuilt)

        current = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == generation.generation_id
        )
        validation = system.structural.validate_generation(
            StructuralGenerationValidationRequest(
                current.generation_id,
                current.authority_aggregate_version,
                rebuilt.metadata.contiguous_ledger_seq,
                "B3_TOMBSTONE_VALIDATE",
                "b3-tombstone-validate",
            ),
            proof=proof(),
        )
        validating = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == generation.generation_id
        )
        promotion = system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                validating.generation_id,
                validating.authority_aggregate_version,
                validation.checkpoint_ledger_seq,
                validation.validation_digest,
                "B3_TOMBSTONE_PROMOTE",
                "b3-tombstone-promote",
            ),
            proof=proof(),
        )
        assert promotion.generation.state.value == "ACTIVE"
        original_id, promoted = _read(system, generation.generation_id, history)
        _assert_non_resurrection(history, original_id, promoted)
    finally:
        system.close()

def test_tombstone_duplicate_repairs_but_conflict_has_no_destructive_effect() -> None:
    admission_id = "00000000-0000-4000-8000-000000000123"
    generation_id = ProjectionGenerationId.new()
    source = structural_batch(
        generation_id=generation_id,
        ledger_seq=1,
        object_admission_id=admission_id,
    )
    raw_marker = structural_batch(
        generation_id=generation_id,
        ledger_seq=2,
    )
    marker_relations = tuple(
        replace(
            item,
            source_event_type="governed_blob.deletion.tombstoned",
        )
        for item in raw_marker.relations
    )
    marker = replace(
        raw_marker,
        source_event_type="governed_blob.deletion.tombstoned",
        relations=marker_relations,
        tombstoned_object_admission_ids=(admission_id,),
    )
    adapter = TombstoneMemoryNeo4jAdapter()
    adapter.apply(source)
    adapter.apply(marker)
    source_key = (str(generation_id), 1)
    marker_key = (str(generation_id), 2)
    assert source_key not in adapter.deliveries
    assert marker_key in adapter.deliveries

    adapter.deliveries[source_key] = source
    duplicate = adapter.apply(marker)
    assert duplicate.outcome.value == "DUPLICATE"
    assert source_key not in adapter.deliveries

    adapter.deliveries[source_key] = source
    conflict_digest = digest_canonical({"conflict": "tombstone-delivery"})
    conflict = replace(
        marker,
        source_event_digest=conflict_digest,
        relations=tuple(
            replace(item, source_event_digest=conflict_digest)
            for item in marker.relations
        ),
    )
    with pytest.raises(Neo4jIdentityConflict):
        adapter.apply(conflict)
    assert source_key in adapter.deliveries
    assert adapter.deliveries[marker_key] == marker
