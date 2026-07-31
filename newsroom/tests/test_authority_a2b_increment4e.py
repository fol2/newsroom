from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

from newsroom.entities import EntityRightsDenied
from newsroom.graphiti_adapter import GraphitiAdapterRightsDenied
from newsroom.relations import EditorialRelationRightsDenied

from .authority_a2b_helpers import open_object_system
from .authority_helpers import proof as object_proof
from .entity_4b_helpers import ENTITY_ID
from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import open_graphiti_system
from .increment4e_governed_path_helpers import (
    admit_increment4_graphiti_path,
    graphiti_path_registries,
    open_graphiti_path_entity_system,
    open_graphiti_path_relation_system,
    seed_increment4_graphiti_path,
)
from .source_3a_helpers import SOURCE_NOW


def test_increment4e_tombstone_denies_current_surfaces_but_retains_authority(tmp_path) -> None:
    state = seed_increment4_graphiti_path(tmp_path)
    admitted = admit_increment4_graphiti_path(state)
    commands, schemas = graphiti_path_registries(state.extraction)
    passage = state.extraction.input_binding.passages[0]

    with open_object_system(
        state.extraction.database,
        object_root=state.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        deletion = objects.objects.request_deletion(
            passage.blob_digest,
            reason_code="A2B_INCREMENT4_DELETE_REQUESTED",
            idempotency_key="a2b-increment4-delete-v1",
            proof=object_proof(),
        )
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="A2B_INCREMENT4_TOMBSTONED",
            idempotency_key="a2b-increment4-tombstone-v1",
            proof=object_proof(),
        )

    with open_graphiti_system(
        state.extraction,
        workspace_root=state.workspace_root,
    ) as graphiti:
        for operation in (
            lambda: graphiti.graphiti.attempt(
                state.source_attempt.attempt_id,
                proof=extraction_proof(),
            ),
            lambda: graphiti.graphiti.attempt(
                state.replay_attempt.attempt_id,
                proof=extraction_proof(),
            ),
        ):
            with pytest.raises(GraphitiAdapterRightsDenied):
                operation()
    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        with pytest.raises(EntityRightsDenied):
            entities.entities.preferred(ENTITY_ID, proof=extraction_proof())
    with open_graphiti_path_relation_system(state.relation) as relations:
        with pytest.raises(EditorialRelationRightsDenied):
            relations.relations.current(
                admitted.current.assertion.assertion_id,
                proof=extraction_proof(),
            )

    with closing(sqlite3.connect(state.extraction.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_adapter_attempts"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions"
        ).fetchone()[0] >= 2
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_entities"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_relation_assertions"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT state FROM object_deletion_heads h "
            "JOIN object_deletion_versions v "
            "ON v.deletion_id=h.deletion_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE h.deletion_id=?",
            (str(deletion.deletion_id),),
        ).fetchone()[0] == "TOMBSTONED"
