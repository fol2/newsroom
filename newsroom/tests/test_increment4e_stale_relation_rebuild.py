from __future__ import annotations

from pathlib import Path

import pytest

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
)
from .entity_4b_helpers import ENTITY_ID, ENTITY_VERSION_ID
from .extraction_4a_helpers import extraction_proof
from .increment4e_governed_path_helpers import (
    admit_increment4_graphiti_path,
    open_graphiti_path_entity_system,
    open_graphiti_path_increment4_neo4j_system,
    open_graphiti_path_relation_system,
    seed_increment4_graphiti_path,
)
from .increment4e_helpers import _entity_state, _ledger_events
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
) -> None:
    admitted = admit_increment4_graphiti_path(
        seed_increment4_graphiti_path(tmp_path)
    )
    state = admitted.path
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
                    state.relation.en_resolution_proposal.proposal_id,
                    state.relation.zh_resolution_proposal.proposal_id,
                ),
                key=str,
            )
        ),
        reason_code="INCREMENT4_STALE_RELATION_ENDPOINT_MERGE",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="increment4-stale-relation-endpoint-merge-v1",
    )

    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        merged = entities.entities.merge_entities(
            merge_request,
            proof=extraction_proof(),
        )
        merged_versions = {
            item.entity_id: item.merged_entity_version_id
            for item in merged.predecessors
        }
        current_entities = (
            _entity_state(entities, ENTITY_ID, merged_versions[ENTITY_ID]),
            _entity_state(
                entities,
                ZH_ENTITY_ID,
                merged_versions[ZH_ENTITY_ID],
            ),
            _entity_state(
                entities,
                successor_entity_id,
                successor_version_id,
            ),
        )

    with open_graphiti_path_relation_system(state.relation) as relations:
        with pytest.raises(EditorialRelationStaleDecision):
            relations.relations.current(
                RELATION_ASSERTION_ID,
                proof=extraction_proof(),
            )

    events = _ledger_events(state.extraction.database)
    snapshot = sorted_snapshot(
        entities=current_entities,
        relations=(),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    adapter = MemoryNeo4jAdapter()
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
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
        node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
        for (generation, _ledger_seq), batch in adapter.deliveries.items()
        if generation == str(GENERATION_ID)
        for node in batch.nodes
    )
