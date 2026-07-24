from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from newsroom.authority import AggregateId, InlinePayload, SemanticCommand, digest_canonical
from newsroom.integrated import (
    IntegratedExactIndexEntry,
    IntegratedRetrievalContextId,
)
from newsroom.projection.neo4j import (
    StructuralActiveReadRequest,
    StructuralDeliveryRequest,
    StructuralGenerationValidationRequest,
)

from .integrated_c1_helpers import open_graph_system, proof
from .test_integrated_c1_context_integrity_faults import (
    _insert_context,
    _open_candidate_system,
    _seed,
)
from .projection_b1_helpers import FAMILY_ID


def _generation(system, generation_id):
    return next(
        item
        for item in system.projections.generations(FAMILY_ID, proof=proof())
        if item.generation_id == generation_id
    )


def test_retained_context_accepts_post_promotion_active_revalidation(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    system = open_graph_system(database, state, graph.adapter)
    try:
        committed = system.commands.execute(
            SemanticCommand(
                command_type="source.item.write",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=InlinePayload(
                    {"headline": "Integrated active revalidation", "count": 2}
                ),
                idempotency_key="integrated-active-revalidation-source",
            ),
            proof=proof(),
        )
        source = next(
            event
            for event in system.events.after(0, limit=1000, proof=proof())
            if event.command_id == str(committed.command_id)
        )
        current = _generation(system, graph.generation_id)
        system.structural.deliver(
            StructuralDeliveryRequest(
                generation_id=graph.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                ledger_seq=source.ledger_seq,
                idempotency_key="integrated-active-revalidation-delivery",
            ),
            proof=proof(),
        )
        status = system.projections.status(FAMILY_ID, proof=proof())
        current = _generation(system, graph.generation_id)
        system.structural.validate_generation(
            StructuralGenerationValidationRequest(
                generation_id=graph.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=status.contiguous_ledger_seq,
                reason_code="INTEGRATED_ACTIVE_REVALIDATION",
                idempotency_key="integrated-active-revalidation-validate",
            ),
            proof=proof(),
        )
        canonical_ids = tuple(item.canonical_id for item in graph.context.nodes)
        response = system.structural.read_active(
            StructuralActiveReadRequest(
                family_id=FAMILY_ID,
                canonical_ids=canonical_ids,
                query_valid_time=graph.context.metadata.query_valid_time,
                limit=1000,
            ),
            proof=proof(),
        )
    finally:
        system.close()

    assert response.metadata.contiguous_ledger_seq > (
        graph.context.metadata.contiguous_ledger_seq
    )
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
    current_context = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
        metadata=response.metadata,
        nodes=response.nodes,
        relations=response.relations,
        exact_index=exact_index,
        query_digest=digest_canonical(
            {
                "contract": "newsroom-integrated-query-v1",
                "family_id": response.metadata.family_id,
                "generation_id": str(response.metadata.generation_id),
                "canonical_ids": list(canonical_ids),
                "query_valid_time": (
                    response.metadata.query_valid_time.to_text()
                ),
                "authority_watermark": (
                    response.metadata.contiguous_ledger_seq
                ),
            }
        ),
        recorded_at=response.metadata.serving_time,
    )
    current_graph = replace(graph, context=current_context)
    _insert_context(database, current_graph, current_context.canonical_value())

    reopened = _open_candidate_system(database, state, current_graph)
    reopened.close()
