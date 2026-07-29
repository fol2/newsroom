from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    ProjectionDeliveryOutcome,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionStateError,
)
from newsroom.projection.neo4j import (
    Neo4jIdentityConflict,
    StructuralActiveReadRequest,
    StructuralDeliveryRequest,
    StructuralGenerationValidationRequest,
    StructuralRebuildRequest,
)

from .discovery_projection_3e_helpers import (
    MemoryNeo4jAdapter,
    open_lineage_projection_system,
    proof,
)
from .test_discovery_projection_3e_authority import (
    register_generation,
    seed_complete_lineage,
)


def _generation(system, generation_id: ProjectionGenerationId):
    return next(
        item
        for item in system.projections.generations(
            DISCOVERY_LINEAGE_FAMILY_ID,
            proof=proof(),
        )
        if item.generation_id == generation_id
    )


def _source_watermark(system) -> int:
    events = system.events.after(0, limit=1_000, proof=proof())
    source = tuple(
        event
        for event in events
        if not event.event_type.startswith("projection.")
    )
    assert source
    return source[-1].ledger_seq


def _rebuild(system, generation, *, key: str):
    current = _generation(system, generation.generation_id)
    return system.structural.rebuild(
        StructuralRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            through_ledger_seq=_source_watermark(system),
            reason_code="INCREMENT_3E_REBUILD",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _validate(system, generation_id: ProjectionGenerationId, checkpoint: int, *, key: str):
    current = _generation(system, generation_id)
    return system.structural.validate_generation(
        StructuralGenerationValidationRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=checkpoint,
            reason_code="INCREMENT_3E_RECONCILE",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _promote(
    system,
    generation_id: ProjectionGenerationId,
    validation,
    *,
    key: str,
    prior_generation_id: ProjectionGenerationId | None = None,
):
    current = _generation(system, generation_id)
    prior = (
        None
        if prior_generation_id is None
        else _generation(system, prior_generation_id)
    )
    return system.projections.promote_generation(
        ProjectionGenerationPromotionRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=validation.checkpoint_ledger_seq,
            validation_digest=validation.validation_digest,
            reason_code="INCREMENT_3E_ACTIVATE",
            idempotency_key=key,
            prior_generation_id=prior_generation_id,
            expected_prior_authority_version=(
                None if prior is None else prior.authority_aggregate_version
            ),
        ),
        proof=proof(),
    )


def _canonical_ids(adapter: MemoryNeo4jAdapter, generation_id: ProjectionGenerationId):
    return tuple(
        sorted(
            {
                node.canonical_id
                for (stored_generation, _sequence), batch in adapter.deliveries.items()
                if stored_generation == str(generation_id)
                for node in batch.nodes
            }
        )
    )


def test_replacement_generation_rebuilds_from_sqlite_and_promotes_atomically(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        first = register_generation(system)
        rebuilt_first = _rebuild(system, first, key="3e-rebuild-first")
        validation_first = _validate(
            system,
            first.generation_id,
            rebuilt_first.checkpoint_ledger_seq,
            key="3e-validate-first",
        )
        promoted_first = _promote(
            system,
            first.generation_id,
            validation_first,
            key="3e-promote-first",
        )
        assert promoted_first.generation.state is ProjectionGenerationState.ACTIVE

        first_ids = _canonical_ids(adapter, first.generation_id)
        first_active = system.structural.read_active(
            StructuralActiveReadRequest(
                family_id=DISCOVERY_LINEAGE_FAMILY_ID,
                canonical_ids=first_ids,
                query_valid_time=UtcTimestamp.now(),
                limit=1_000,
            ),
            proof=proof(),
        )
        assert first_active.nodes
        assert first_active.relations

        replacement = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                ProjectionGenerationId.new(),
                DISCOVERY_LINEAGE_FAMILY_ID,
                "INCREMENT_3E_GRAPH_LOSS_RECOVERY",
                "3e-create-replacement",
            ),
            proof=proof(),
        )
        rebuilt_replacement = _rebuild(
            system,
            replacement,
            key="3e-rebuild-replacement",
        )
        validation_replacement = _validate(
            system,
            replacement.generation_id,
            rebuilt_replacement.checkpoint_ledger_seq,
            key="3e-validate-replacement",
        )
        promoted_replacement = _promote(
            system,
            replacement.generation_id,
            validation_replacement,
            key="3e-promote-replacement",
            prior_generation_id=first.generation_id,
        )

        assert promoted_replacement.generation.state is ProjectionGenerationState.ACTIVE
        assert promoted_replacement.prior_generation is not None
        assert promoted_replacement.prior_generation.generation_id == first.generation_id
        assert promoted_replacement.prior_generation.state is ProjectionGenerationState.RETIRED
        assert _canonical_ids(adapter, replacement.generation_id) == first_ids

        active = system.structural.read_active(
            StructuralActiveReadRequest(
                family_id=DISCOVERY_LINEAGE_FAMILY_ID,
                canonical_ids=first_ids,
                query_valid_time=UtcTimestamp.now(),
                limit=1_000,
            ),
            proof=proof(),
        )
        assert active.metadata.generation_id == replacement.generation_id
        assert active.metadata.generation_state is ProjectionGenerationState.ACTIVE
    finally:
        system.close()


def test_rebuild_replay_recovers_graph_loss_without_new_authority_events(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        generation = register_generation(system)
        request = StructuralRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=generation.authority_aggregate_version,
            through_ledger_seq=_source_watermark(system),
            reason_code="INCREMENT_3E_REBUILD_REPLAY",
            idempotency_key="3e-rebuild-replay",
        )
        first = system.structural.rebuild(request, proof=proof())
        events_before = system.events.after(0, limit=1_000, proof=proof())
        expected_ids = _canonical_ids(adapter, generation.generation_id)

        adapter.cleanup_generation(str(generation.generation_id))
        assert _canonical_ids(adapter, generation.generation_id) == ()

        replay = system.structural.rebuild(request, proof=proof())
        assert replay.authority_command_replayed is True
        assert replay.rebuild_authority_event_id == first.rebuild_authority_event_id
        assert replay.recorded_delivery_count == 0
        assert replay.reapplied_delivery_count > 0
        assert _canonical_ids(adapter, generation.generation_id) == expected_ids
        assert system.events.after(0, limit=1_000, proof=proof()) == events_before
    finally:
        system.close()


def test_active_generation_requires_replacement_instead_of_rebuild_replay(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        generation = register_generation(system)
        request = StructuralRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=generation.authority_aggregate_version,
            through_ledger_seq=_source_watermark(system),
            reason_code="INCREMENT_3E_ACTIVE_REBUILD_REPLAY",
            idempotency_key="3e-active-rebuild-replay",
        )
        rebuilt = system.structural.rebuild(request, proof=proof())
        validation = _validate(
            system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="3e-active-rebuild-validate",
        )
        promoted = _promote(
            system,
            generation.generation_id,
            validation,
            key="3e-active-rebuild-promote",
        )
        assert promoted.generation.state is ProjectionGenerationState.ACTIVE
        events_before = system.events.after(0, limit=1_000, proof=proof())

        with pytest.raises(
            ProjectionStateError,
            match="only a building generation can be destructively rebuilt",
        ):
            system.structural.rebuild(request, proof=proof())

        assert system.events.after(0, limit=1_000, proof=proof()) == events_before
        assert (
            _generation(system, generation.generation_id).state
            is ProjectionGenerationState.ACTIVE
        )
    finally:
        system.close()


def test_required_gap_and_dead_letter_block_lineage_validation(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter(fail_writes=True)
    system = open_lineage_projection_system(database, adapter)
    try:
        generation = register_generation(system)
        source_event = next(
            event
            for event in system.events.after(0, limit=1_000, proof=proof())
            if event.event_type == "discovery.signal.admitted"
        )
        for attempt in range(1, 4):
            current = _generation(system, generation.generation_id)
            record = system.structural.deliver(
                StructuralDeliveryRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=current.authority_aggregate_version,
                    ledger_seq=source_event.ledger_seq,
                    idempotency_key=f"3e-failed-signal-{attempt}",
                ),
                proof=proof(),
            )
            assert record.outcome is ProjectionDeliveryOutcome.RETRYABLE_FAILURE

        status = system.projections.status(
            DISCOVERY_LINEAGE_FAMILY_ID,
            proof=proof(),
        )
        assert status.open_gap_count >= 1
        assert status.dead_letter_count == 1
        current = _generation(system, generation.generation_id)
        with pytest.raises(ProjectionStateError, match="gap|dead letter"):
            system.structural.validate_generation(
                StructuralGenerationValidationRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=current.authority_aggregate_version,
                    checkpoint_ledger_seq=status.contiguous_ledger_seq,
                    reason_code="INCREMENT_3E_BLOCKED_VALIDATION",
                    idempotency_key="3e-blocked-validation",
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_server_reconciliation_rejects_graph_tamper(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        generation = register_generation(system)
        rebuilt = _rebuild(system, generation, key="3e-tamper-rebuild")
        adapter.reconciliation_mismatch = True
        with pytest.raises(Neo4jIdentityConflict, match="differs"):
            _validate(
                system,
                generation.generation_id,
                rebuilt.checkpoint_ledger_seq,
                key="3e-tamper-validate",
            )
        assert _generation(system, generation.generation_id).state is ProjectionGenerationState.BUILDING
    finally:
        system.close()
