from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import newsroom.authority._increment4_projection_store as projection_store_module
from newsroom.increment4 import Increment4Neo4jBuildRequest, sorted_snapshot
from newsroom.projection import ProjectionGenerationId, ProjectionGenerationState

from .extraction_4a_helpers import extraction_proof
from .increment4e_helpers import (
    admitted_increment4_fixture,
    open_increment4_neo4j_system,
)
from .projection_b2_helpers import MemoryNeo4jAdapter


GENERATION_ID = ProjectionGenerationId.parse(
    "00000000-0000-4000-8000-000000005097"
)


def test_increment4_filters_one_rights_invalid_alias_without_dropping_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    target = snapshot.entities[0]
    revoked_alias_id = target.aliases[0].alias_id
    expected = sorted_snapshot(
        entities=tuple(
            replace(item, aliases=())
            if item.entity.entity_id == target.entity.entity_id
            else item
            for item in snapshot.entities
        ),
        relations=snapshot.relations,
        events=snapshot.events,
        through_ledger_seq=snapshot.through_ledger_seq,
    )

    store_type = projection_store_module._Increment4ProjectionAuthorityStore
    original_alias_from_row = store_type._alias_from_row
    original_require_mention_current = store_type._require_mention_current
    deny_next_alias_use = {"value": False}

    def alias_from_row(self, conn, row):
        alias = original_alias_from_row(self, conn, row)
        deny_next_alias_use["value"] = alias.alias_id == revoked_alias_id
        return alias

    def require_mention_current(self, conn, mention):
        if deny_next_alias_use["value"]:
            deny_next_alias_use["value"] = False
            raise PermissionError("fixed independently revoked alias evidence")
        return original_require_mention_current(self, conn, mention)

    monkeypatch.setattr(store_type, "_alias_from_row", alias_from_row)
    monkeypatch.setattr(
        store_type,
        "_require_mention_current",
        require_mention_current,
    )

    adapter = MemoryNeo4jAdapter()
    with open_increment4_neo4j_system(state, adapter) as system:
        result = system.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=GENERATION_ID,
                snapshot=expected,
                reason_code="INCREMENT4_ALIAS_RIGHTS_FILTER_PROOF",
                idempotency_key="increment4-alias-rights-filter-v1",
            ),
            proof=extraction_proof(),
        )

    assert result.generation.state is ProjectionGenerationState.ACTIVE
    entity_nodes = {
        node.canonical_id
        for batch in adapter.deliveries.values()
        for node in batch.nodes
        if node.identity_source == "CANONICAL_ENTITY_ID"
    }
    alias_nodes = {
        node.canonical_id
        for batch in adapter.deliveries.values()
        for node in batch.nodes
        if node.identity_source == "ENTITY_ALIAS_ID"
    }
    relation_nodes = {
        node.canonical_id
        for batch in adapter.deliveries.values()
        for node in batch.nodes
        if node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
    }
    assert len(entity_nodes) == len(snapshot.entities)
    assert len(alias_nodes) == sum(
        len(item.aliases) for item in snapshot.entities
    ) - 1
    assert relation_nodes
