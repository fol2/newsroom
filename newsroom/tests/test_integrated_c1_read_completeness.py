from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.integrated import IntegratedRetrievalContextId
from newsroom.projection.neo4j import Neo4jIdentityConflict

from .integrated_c1_helpers import candidate_request, proof
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)


def test_caller_cannot_truncate_fixture_relations_with_a_smaller_read_limit(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    assert len(graph.context.relations) > len(graph.context.nodes)
    retained_relations = graph.context.relations[: len(graph.context.nodes)]
    assert len(retained_relations) < len(graph.context.relations)
    assert any(
        relation.source_event_id == str(graph.context.fixture_event_id)
        and relation.object_admission_id == str(graph.context.admission_id)
        for relation in retained_relations
    )
    truncated = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
        relations=retained_relations,
    )

    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(
            Neo4jIdentityConflict,
            match="current Neo4j read differs",
        ):
            system.candidates.admit(
                candidate_request(
                    truncated,
                    key="integrated-truncated-relations",
                ),
                context=truncated,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()
