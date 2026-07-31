from __future__ import annotations

from contextlib import closing
import sqlite3

from newsroom.increment4 import (
    build_increment4_admitted_batches,
    increment4_admitted_contract_registry,
)
from newsroom.projection import ProjectionGenerationId

from .increment4e_governed_path_helpers import (
    admit_increment4_graphiti_path,
    seed_increment4_graphiti_path,
)


def test_increment4e_projection_contains_only_admitted_governed_identity(tmp_path) -> None:
    state = seed_increment4_graphiti_path(tmp_path)
    admitted = admit_increment4_graphiti_path(state)
    family = increment4_admitted_contract_registry().family(
        "graph.increment4.admitted"
    )
    generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004989"
    )
    batches = build_increment4_admitted_batches(
        admitted.snapshot,
        generation_id=generation_id,
        family=family,
    )

    nodes = [node for batch in batches for node in batch.nodes]
    relations = [relation for batch in batches for relation in batch.relations]
    assert nodes
    assert relations
    assert all(relation.trust_scope.value == "ADMITTED" for relation in relations)
    assert {node.identity_source for node in nodes} <= {
        "AUTHORITY_EVENT_ID",
        "CANONICAL_ENTITY_ID",
        "CANONICAL_ENTITY_VERSION_ID",
        "ENTITY_ALIAS_ID",
        "EDITORIAL_RELATION_ASSERTION_ID",
    }
    canonical_text = repr((batches, admitted.snapshot.canonical_digest)).upper()
    for prohibited in (
        "GRAPHITI_WORKSPACE",
        "GRAPHITI_NODE",
        "GRAPHITI_RELATION",
        "PROPOSAL_SET",
        "PROPOSAL_ENVELOPE",
        "PRIVATE_NODE_ID",
        "PRIVATE_RELATION_ID",
    ):
        assert prohibited not in canonical_text

    with closing(sqlite3.connect(state.extraction.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_proposals"
        ).fetchone()[0] >= 4
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_workspaces"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_cleanup_receipts"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_projection_events"
        ).fetchone()[0] >= 2
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_relation_projection_events"
        ).fetchone()[0] == 1
