from __future__ import annotations

from pathlib import Path

import pytest

import newsroom.authority._increment4_projection_store as projection_store_module
from newsroom.entities import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityLineageVersion,
    EntityMergeDecisionId,
    EntityMergeDecisionRequest,
)
from newsroom.increment4 import Increment4Neo4jBuildRequest, sorted_snapshot
from newsroom.projection import ProjectionGenerationId, ProjectionGenerationState
from newsroom.relations import EditorialRelationStaleDecision

from .editorial_relation_4c_helpers import (
    RELATION_ASSERTION_ID,
    ZH_ENTITY_ID,
    ZH_ENTITY_VERSION_ID,
    open_entity_system_after_relation,
    open_relation_system,
)
from .entity_4b_helpers import ENTITY_ID, ENTITY_VERSION_ID
from .extraction_4a_helpers import extraction_proof
from .increment4e_helpers import (
    _ledger_events,
    admitted_increment4_fixture,
    open_increment4_neo4j_system,
)
from .projection_b2_helpers import MemoryNeo4jAdapter


GENERATION_ID = ProjectionGenerationId.parse(
    "00000000-0000-4000-8000-000000005101"
)


def _id(identifier_type: type, suffix: int):
    return identifier_type.parse(
        f"00000000-0000-4000-8000-{suffix:012d}"
    )


def test_increment4_rebuild_omits_relation_stale_after_entity_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, initial_snapshot = admitted_increment4_fixture(tmp_path)
    retained_current = next(
        item.current
        for item in initial_snapshot.relations
        if item.current.assertion.assertion_id == RELATION_ASSERTION_ID
    )
    merge_decision_id = _id(EntityMergeDecisionId, 5102)
    successor_entity_id = _id(CanonicalEntityId, 5103)
    successor_version_id = _id(CanonicalEntityVersionId, 5104)
    merge_request = EntityMergeDecisionRequest(
        merge_decision_id=merge_decision_id,
        predecessors=tuple(
            sorted(
                (
                    EntityLineageVersion(ENTITY_ID, ENTITY_VERSION_ID),
                    EntityLineageVersion(ZH_ENTITY_ID, ZH_ENTITY_VERSION_ID),
                ),
                key=lambda item: str(item.entity_id),
            )
        ),
        successor_entity_id=successor_entity_id,
        successor_entity_version_id=successor_version_id,
        preferred_continuation_entity_id=ENTITY_ID,
        basis_resolution_proposal_ids=tuple(
            sorted(
                (
                    state.en_resolution_proposal.proposal_id,
                    state.zh_resolution_proposal.proposal_id,
                ),
                key=str,
            )
        ),
        reason_code="INCREMENT4_STALE_RELATION_ENDPOINT_MERGE",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="increment4-stale-relation-endpoint-merge-v1",
    )

    with open_entity_system_after_relation(state) as entities:
        merged = entities.entities.merge_entities(
            merge_request,
            proof=extraction_proof(),
        )
        for predecessor_id in (ENTITY_ID, ZH_ENTITY_ID):
            preferred = entities.entities.preferred(
                predecessor_id,
                proof=extraction_proof(),
            )
            assert preferred.preferred_entity_id == successor_entity_id

    with open_relation_system(state) as relations:
        with pytest.raises(EditorialRelationStaleDecision):
            relations.relations.current(
                RELATION_ASSERTION_ID,
                proof=extraction_proof(),
            )

    events = _ledger_events(state.entity.extraction.database)
    snapshot = sorted_snapshot(
        entities=(),
        relations=(),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    store_type = projection_store_module._Increment4ProjectionAuthorityStore
    original_entity = store_type.entity
    original_editorial_current = store_type.editorial_current

    def entity(self, entity_id):
        if entity_id == successor_entity_id:
            raise PermissionError("fixed merge-successor rights denial")
        return original_entity(self, entity_id)

    def editorial_current(self, assertion_id):
        if assertion_id == RELATION_ASSERTION_ID:
            return retained_current
        return original_editorial_current(self, assertion_id)

    monkeypatch.setattr(store_type, "entity", entity)
    monkeypatch.setattr(store_type, "editorial_current", editorial_current)

    adapter = MemoryNeo4jAdapter()
    with open_increment4_neo4j_system(state, adapter) as projection:
        rebuilt = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=GENERATION_ID,
                snapshot=snapshot,
                reason_code="INCREMENT4_STALE_RELATION_REBUILD",
                idempotency_key="increment4-stale-relation-rebuild-v1",
            ),
            proof=extraction_proof(),
        )

    assert rebuilt.generation.state is ProjectionGenerationState.ACTIVE
    assert not any(
        node.identity_source == "CANONICAL_ENTITY_ID"
        for (generation, _ledger_seq), batch in adapter.deliveries.items()
        if generation == str(GENERATION_ID)
        for node in batch.nodes
    )
    assert not any(
        node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
        for (generation, _ledger_seq), batch in adapter.deliveries.items()
        if generation == str(GENERATION_ID)
        for node in batch.nodes
    )
