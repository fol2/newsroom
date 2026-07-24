from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionStateError,
)
from newsroom.projection.neo4j import (
    StructuralRebuildRequest,
    StructuralReadRequest,
)

from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import FAMILY_ID
from .projection_b2_helpers import (
    MemoryNeo4jAdapter,
    open_b2_system,
    proof,
    source_command,
)


def _register_and_create(system, *, suffix: str):
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(
            FAMILY_ID, f"b3-rebuild-family-{suffix}"
        ),
        proof=proof(),
    )
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "B3_REBUILD",
            f"b3-rebuild-generation-{suffix}",
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


def _request(system, generation, *, key: str) -> StructuralRebuildRequest:
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
        reason_code="B3_DESTRUCTIVE_REBUILD",
        idempotency_key=key,
    )


def test_rebuild_clears_target_and_replays_retained_authority(
    tmp_path: Path,
) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        source = _source_event(system, key="b3-rebuild-source")
        generation = _register_and_create(system, suffix="first")
        request = _request(system, generation, key="b3-rebuild-first")

        rebuilt = system.structural.rebuild(request, proof=proof())

        assert rebuilt.generation_id == generation.generation_id
        assert rebuilt.recorded_delivery_count == 1
        assert rebuilt.reapplied_delivery_count == 0
        assert rebuilt.blocked_delivery_count == 0
        assert rebuilt.checkpoint_ledger_seq >= request.through_ledger_seq
        assert adapter.cleanup_count == 1
        assert (str(generation.generation_id), source.ledger_seq) in adapter.deliveries
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        assert current.state is ProjectionGenerationState.BUILDING
    finally:
        system.close()


def test_exact_rebuild_replay_restores_graph_without_new_authority_events(
    tmp_path: Path,
) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        source = _source_event(system, key="b3-rebuild-restart-source")
        generation = _register_and_create(system, suffix="restart")
        request = _request(system, generation, key="b3-rebuild-restart")
        first = system.structural.rebuild(request, proof=proof())
        before = system.events.after(0, limit=1000, proof=proof())

        adapter.cleanup_generation(str(generation.generation_id))
        assert (str(generation.generation_id), source.ledger_seq) not in adapter.deliveries
        replay = system.structural.rebuild(request, proof=proof())

        assert replay.authority_command_replayed is True
        assert replay.rebuild_authority_event_id == first.rebuild_authority_event_id
        assert replay.reapplied_delivery_count == 1
        assert replay.recorded_delivery_count == 0
        assert system.events.after(0, limit=1000, proof=proof()) == before
        assert (str(generation.generation_id), source.ledger_seq) in adapter.deliveries
    finally:
        system.close()


def test_rebuild_cleanup_is_generation_scoped(tmp_path: Path) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        source = _source_event(system, key="b3-rebuild-isolation-source")
        first = _register_and_create(system, suffix="isolation-first")
        first_request = _request(system, first, key="b3-rebuild-isolation-first")
        system.structural.rebuild(first_request, proof=proof())

        second = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                ProjectionGenerationId.new(),
                FAMILY_ID,
                "B3_REBUILD_ISOLATION",
                "b3-rebuild-isolation-second",
            ),
            proof=proof(),
        )
        second_request = _request(
            system, second, key="b3-rebuild-isolation-second-request"
        )
        system.structural.rebuild(second_request, proof=proof())
        second_key = (str(second.generation_id), source.ledger_seq)
        assert second_key in adapter.deliveries

        first_current = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == first.generation_id
        )
        replay = StructuralRebuildRequest(
            first.generation_id,
            first_request.expected_authority_version,
            first_request.through_ledger_seq,
            first_request.reason_code,
            first_request.idempotency_key,
        )
        assert first_current.state is ProjectionGenerationState.BUILDING
        system.structural.rebuild(replay, proof=proof())
        assert second_key in adapter.deliveries
    finally:
        system.close()


def test_rebuild_target_cannot_precede_authoritative_checkpoint(
    tmp_path: Path,
) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        _source_event(system, key="b3-rebuild-stale-source")
        generation = _register_and_create(system, suffix="stale")
        system.structural.rebuild(
            _request(system, generation, key="b3-rebuild-stale-first"),
            proof=proof(),
        )
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        before = system.events.after(0, limit=1000, proof=proof())
        cleanup_count = adapter.cleanup_count

        with pytest.raises(ProjectionStateError, match="authoritative checkpoint"):
            system.structural.rebuild(
                StructuralRebuildRequest(
                    generation.generation_id,
                    current.authority_aggregate_version,
                    0,
                    "B3_STALE_REBUILD",
                    "b3-rebuild-stale-rejected",
                ),
                proof=proof(),
            )

        assert system.events.after(0, limit=1000, proof=proof()) == before
        assert adapter.cleanup_count == cleanup_count
    finally:
        system.close()


def test_rebuild_result_and_request_are_bounded_typed_contracts() -> None:
    with pytest.raises(Exception):
        StructuralRebuildRequest(
            generation_id=ProjectionGenerationId.new(),
            expected_authority_version=1,
            through_ledger_seq=-1,
            reason_code="B3_REBUILD",
            idempotency_key="negative-through",
        )
