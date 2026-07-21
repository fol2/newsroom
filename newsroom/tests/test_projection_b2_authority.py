from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import AuthenticationProof
from newsroom.projection import (
    ProjectionDeliveryOutcome,
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
)
from newsroom.projection.neo4j import (
    Neo4jIdentityConflict,
    StructuralDeliveryRequest,
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


def _register_and_create(system):
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(FAMILY_ID, "b2-family-register"),
        proof=proof(),
    )
    generation_id = ProjectionGenerationId.new()
    generation = system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            generation_id,
            FAMILY_ID,
            "B2_INITIAL_BUILD",
            "b2-generation-create",
        ),
        proof=proof(),
    )
    return generation


def _source_event(system, *, key: str):
    command = system.commands.execute(source_command(key=key), proof=proof())
    return next(
        event
        for event in system.events.after(0, limit=1000, proof=proof())
        if event.command_id == str(command.command_id)
    )


def test_structural_delivery_commits_graph_then_b1_authority(tmp_path: Path) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        generation = _register_and_create(system)
        source = _source_event(system, key="b2-source-1")
        request = StructuralDeliveryRequest(
            generation.generation_id,
            generation.authority_aggregate_version,
            source.ledger_seq,
            "b2-deliver-1",
        )
        delivered = system.structural.deliver(request, proof=proof())
        assert delivered.outcome is ProjectionDeliveryOutcome.APPLIED
        assert delivered.finalized is True
        assert adapter.apply_count == 1
        batch = adapter.deliveries[
            (str(generation.generation_id), source.ledger_seq)
        ]
        assert batch.source_event_id == source.event_id
        assert batch.source_event_digest == delivered.source_event_digest
        assert all(node.canonical_id.startswith("npid:v1:") for node in batch.nodes)
        assert all(
            relation.source_event_id == source.event_id
            for relation in batch.relations
        )
        assert system.projections.status(FAMILY_ID, proof=proof()).contiguous_ledger_seq >= source.ledger_seq

        selected = (batch.nodes[0].canonical_id,)
        response = system.structural.read(
            StructuralReadRequest(
                generation.generation_id,
                selected,
                FIXED_NOW,
                limit=100,
            ),
            proof=proof(),
        )
        assert response.metadata.generation_id == generation.generation_id
        assert response.metadata.family_id == FAMILY_ID
        assert response.metadata.contiguous_ledger_seq >= source.ledger_seq
        assert response.metadata.authoritative_system == "sqlite-ledger-and-governed-objects"
        assert response.metadata.graph_role == "non-authoritative-rebuildable-context"
        assert response.nodes
        assert response.relations
        assert not any(hasattr(node, "element_id") for node in response.nodes)
        assert not any(hasattr(node, "neo4j_id") for node in response.nodes)
    finally:
        system.close()
    assert adapter.closed is True


def test_exact_duplicate_graph_delivery_replays_authority_result(tmp_path: Path) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        generation = _register_and_create(system)
        source = _source_event(system, key="b2-source-duplicate")
        request = StructuralDeliveryRequest(
            generation.generation_id,
            generation.authority_aggregate_version,
            source.ledger_seq,
            "b2-deliver-duplicate",
        )
        first = system.structural.deliver(request, proof=proof())
        replay = system.structural.deliver(request, proof=proof())
        assert replay == first
        assert adapter.apply_count == 2
        assert len(adapter.deliveries) == 1
    finally:
        system.close()


def test_graph_identity_conflict_is_visible_b1_failure(tmp_path: Path) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        generation = _register_and_create(system)
        source = _source_event(system, key="b2-source-conflict")
        current = generation
        first = system.structural.deliver(
            StructuralDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                source.ledger_seq,
                "b2-deliver-conflict-first",
            ),
            proof=proof(),
        )
        assert first.outcome is ProjectionDeliveryOutcome.APPLIED
        adapter.corrupt_delivery_digest(generation.generation_id, source.ledger_seq)
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(Neo4jIdentityConflict, match="finalized B1"):
            system.structural.deliver(
                StructuralDeliveryRequest(
                    generation.generation_id,
                    current.authority_aggregate_version,
                    source.ledger_seq,
                    "b2-deliver-conflict-second",
                ),
                proof=proof(),
            )
        after = system.events.after(0, limit=1000, proof=proof())
        assert after == before
    finally:
        system.close()


def test_wrong_proof_cannot_reach_graph_writer(tmp_path: Path) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        generation = _register_and_create(system)
        source = _source_event(system, key="b2-source-denied")
        with pytest.raises(Exception):
            system.structural.deliver(
                StructuralDeliveryRequest(
                    generation.generation_id,
                    generation.authority_aggregate_version,
                    source.ledger_seq,
                    "b2-deliver-denied",
                ),
                proof=AuthenticationProof(
                    method="STATIC_TOKEN",
                    credential="wrong-token",
                ),
            )
        assert adapter.apply_count == 0
        assert adapter.deliveries == {}
    finally:
        system.close()


def test_graph_write_failures_exhaust_through_b1_dead_letter(tmp_path: Path) -> None:
    adapter = MemoryNeo4jAdapter(fail_writes=True)
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        generation = _register_and_create(system)
        source = _source_event(system, key="b2-source-failure")
        for attempt in range(1, 4):
            current = system.projections.generations(FAMILY_ID, proof=proof())[0]
            record = system.structural.deliver(
                StructuralDeliveryRequest(
                    generation.generation_id,
                    current.authority_aggregate_version,
                    source.ledger_seq,
                    f"b2-deliver-failure-{attempt}",
                ),
                proof=proof(),
            )
            assert record.outcome is ProjectionDeliveryOutcome.RETRYABLE_FAILURE
            assert record.attempt_count == attempt
            assert record.finalized is (attempt == 3)
        assert len(system.projections.dead_letters(
            generation.generation_id, proof=proof()
        )) == 1
        status = system.projections.status(FAMILY_ID, proof=proof())
        assert status.open_gap_count == 1
        assert status.contiguous_ledger_seq < source.ledger_seq
    finally:
        system.close()


def test_unmapped_control_event_uses_explicit_optional_semantics(tmp_path: Path) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        generation = _register_and_create(system)
        family_event = next(
            event
            for event in system.events.after(0, limit=100, proof=proof())
            if event.event_type == "projection.family.registered"
        )
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        record = system.structural.deliver(
            StructuralDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                family_event.ledger_seq,
                "b2-ignore-control-event",
            ),
            proof=proof(),
        )
        assert record.outcome is ProjectionDeliveryOutcome.IGNORED_OPTIONAL
        assert adapter.apply_count == 0
    finally:
        system.close()
