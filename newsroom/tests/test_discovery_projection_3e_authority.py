from __future__ import annotations

from pathlib import Path

from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    ProjectionDeliveryOutcome,
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionNodeType,
    ProjectionRelationType,
)
from newsroom.projection.neo4j import StructuralDeliveryRequest

from .discovery_3d_authority_helpers import (
    exact_admission_request,
    open_discovery_system,
    proof,
    seed_check_lineage,
)
from .discovery_projection_3e_helpers import (
    MemoryNeo4jAdapter,
    open_lineage_projection_system,
)


MAPPED_EVENT_TYPES = frozenset(
    {
        "source.definition.registered",
        "source.definition.version.recorded",
        "check.request.registered",
        "check.attempt.started",
        "check.outcome.recorded",
        "source.item.registered",
        "source.revision.recorded",
        "discovery.representation.recorded",
        "discovery.occurrence.recorded",
        "source.observable_transition.recorded",
        "discovery.signal.admitted",
        "discovery.gate.decided",
        "discovery.lead.opened",
    }
)


def seed_complete_lineage(path: Path) -> None:
    system = open_discovery_system(path)
    try:
        seed_check_lineage(system)
        system.discovery.admit_signal_to_lead(
            exact_admission_request(),
            proof=proof(),
        )
    finally:
        system.close()


def register_generation(system):
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(
            DISCOVERY_LINEAGE_FAMILY_ID,
            "3e-family-register",
        ),
        proof=proof(),
    )
    generation_id = ProjectionGenerationId.new()
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            generation_id,
            DISCOVERY_LINEAGE_FAMILY_ID,
            "INCREMENT_3E_FIXTURE_BUILD",
            "3e-generation-create",
        ),
        proof=proof(),
    )


def deliver_authority_history(system, generation):
    results = []
    source_events = tuple(
        event
        for event in system.events.after(0, limit=1_000, proof=proof())
        if event.event_type not in {
            "projection.family.registered",
            "projection.generation.created",
        }
    )
    current = generation
    for event in source_events:
        current = system.projections.generations(
            DISCOVERY_LINEAGE_FAMILY_ID,
            proof=proof(),
        )[0]
        request = StructuralDeliveryRequest(
            generation.generation_id,
            current.authority_aggregate_version,
            event.ledger_seq,
            f"3e-deliver-{event.ledger_seq}",
        )
        results.append(
            (
                event,
                request,
                system.structural.deliver(request, proof=proof()),
            )
        )
    return tuple(results)


def test_complete_increment3_lineage_projects_through_existing_authority(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        generation = register_generation(system)
        results = deliver_authority_history(system, generation)

        by_type = {event.event_type: result for event, _request, result in results}
        assert MAPPED_EVENT_TYPES <= by_type.keys()
        assert all(
            by_type[event_type].outcome is ProjectionDeliveryOutcome.APPLIED
            for event_type in MAPPED_EVENT_TYPES
        )
        assert all(
            result.outcome is ProjectionDeliveryOutcome.IGNORED_OPTIONAL
            for event, _request, result in results
            if event.event_type not in MAPPED_EVENT_TYPES
        )

        batches = tuple(adapter.deliveries.values())
        node_types = {
            node.node_type for batch in batches for node in batch.nodes
        }
        relation_types = {
            relation.relation_type
            for batch in batches
            for relation in batch.relations
        }
        assert {
            ProjectionNodeType.SOURCE_DEFINITION,
            ProjectionNodeType.SOURCE_DEFINITION_VERSION,
            ProjectionNodeType.SOURCE_ITEM,
            ProjectionNodeType.SOURCE_REVISION,
            ProjectionNodeType.SOURCE_REPRESENTATION,
            ProjectionNodeType.DISCOVERY_OCCURRENCE,
            ProjectionNodeType.CHECK_REQUEST,
            ProjectionNodeType.CHECK_ATTEMPT,
            ProjectionNodeType.CHECK_OUTCOME,
            ProjectionNodeType.OBSERVABLE_TRANSITION,
            ProjectionNodeType.SIGNAL,
            ProjectionNodeType.GATE_DECISION,
            ProjectionNodeType.LEAD,
        } <= node_types
        assert {
            ProjectionRelationType.HAS_DEFINITION_VERSION,
            ProjectionRelationType.DEFINES_ITEM,
            ProjectionRelationType.REQUESTED_CHECK,
            ProjectionRelationType.ATTEMPTED_AS,
            ProjectionRelationType.PRODUCED_CHECK_OUTCOME,
            ProjectionRelationType.HAS_REVISION,
            ProjectionRelationType.HAS_REPRESENTATION,
            ProjectionRelationType.OBSERVED_AS,
            ProjectionRelationType.PRODUCED_OCCURRENCE,
            ProjectionRelationType.TRANSITION_OF_ITEM,
            ProjectionRelationType.CLASSIFIED_BY_TRANSITION,
            ProjectionRelationType.PRODUCED_SIGNAL,
            ProjectionRelationType.EMITTED_SIGNAL,
            ProjectionRelationType.DECIDED_BY_GATE,
            ProjectionRelationType.PROMOTED_TO_LEAD,
            ProjectionRelationType.OPENED_LEAD,
        } <= relation_types

        status = system.projections.status(
            DISCOVERY_LINEAGE_FAMILY_ID,
            proof=proof(),
        )
        assert status.contiguous_ledger_seq >= 15
        assert status.open_gap_count == 0
        assert status.dead_letter_count == 0
    finally:
        system.close()


def test_exact_lineage_replay_does_not_duplicate_graph_authority(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        generation = register_generation(system)
        results = deliver_authority_history(system, generation)
        signal_event, request, first = next(
            (event, request, result)
            for event, request, result in results
            if event.event_type == "discovery.signal.admitted"
        )
        replay = system.structural.deliver(request, proof=proof())
        assert replay == first
        assert len(
            [
                key
                for key in adapter.deliveries
                if key == (
                    str(generation.generation_id),
                    signal_event.ledger_seq,
                )
            ]
        ) == 1
    finally:
        system.close()
