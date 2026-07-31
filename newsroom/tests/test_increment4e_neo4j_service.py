from __future__ import annotations

import atexit
from functools import lru_cache
import os
from pathlib import Path
import sqlite3

import pytest

from newsroom.increment4 import (
    Increment4Neo4jActiveReadRequest,
    Increment4Neo4jBuildRequest,
    build_increment4_admitted_batches,
    increment4_admitted_contract_registry,
    sorted_snapshot,
)
from newsroom.projection import ProjectionGenerationId, ProjectionGenerationState
from newsroom.projection.neo4j import Neo4jIdentityConflict, Neo4jProjectorConfig
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter

from .editorial_relation_4c_helpers import (
    RELATION_PROPOSAL_ID,
    RELATION_PROPOSAL_V1_ID,
)
from .authority_a2b_helpers import open_object_system
from .authority_helpers import proof as object_proof
from .extraction_4a_helpers import extraction_proof
from .increment4e_governed_path_helpers import (
    admit_increment4_graphiti_path,
    graphiti_path_registries,
    open_graphiti_path_increment4_neo4j_system,
    seed_increment4_graphiti_path,
)
from .increment4e_helpers import _ledger_events
from .source_3a_helpers import SOURCE_NOW


_REQUIRED_FLAG = "NEWSROOM_NEO4J_SERVICE_REQUIRED"
_PROJECTOR_DRIVER = None


@lru_cache(maxsize=1)
def _service_config() -> Neo4jProjectorConfig:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("actual Neo4j service is required only by the permanent graph gate")
    return Neo4jProjectorConfig.from_environment()


def _projector_driver():
    global _PROJECTOR_DRIVER
    if _PROJECTOR_DRIVER is None:
        from neo4j import GraphDatabase

        config = _service_config()
        _PROJECTOR_DRIVER = GraphDatabase.driver(
            config.uri,
            auth=(config.username, config.password),
        )
        _PROJECTOR_DRIVER.verify_connectivity()
    return _PROJECTOR_DRIVER


def _close_projector_driver() -> None:
    global _PROJECTOR_DRIVER
    if _PROJECTOR_DRIVER is not None:
        _PROJECTOR_DRIVER.close()
        _PROJECTOR_DRIVER = None


atexit.register(_close_projector_driver)


def _request(generation_id, snapshot, *, key: str, purge: bool = True):
    return Increment4Neo4jBuildRequest(
        generation_id=generation_id,
        snapshot=snapshot,
        reason_code="INCREMENT4E_ACTUAL_NEO4J_PROOF",
        idempotency_key=key,
        purge_retired_generation=purge,
    )


def _expected(snapshot, generation_id):
    family = increment4_admitted_contract_registry().family(
        "graph.increment4.admitted"
    )
    batches = build_increment4_admitted_batches(
        snapshot,
        generation_id=generation_id,
        family=family,
    )
    node_ids = {
        node.canonical_id
        for batch in batches
        for node in batch.nodes
    }
    # Structural reads are explicit-ID bounded and expand only one relationship hop.
    # Bind the exact admitted generation inventory when asserting complete state.
    canonical_ids = tuple(sorted(node_ids))
    relation_keys = {
        relation.relation_key
        for batch in batches
        for relation in batch.relations
    }
    return batches, canonical_ids, node_ids, relation_keys


def _scalar(statement: str, **parameters) -> int:
    with _projector_driver().session(database=_service_config().database) as session:
        record = session.run(statement, parameters).single(strict=True)
        return int(record[0])


def _values(statement: str, **parameters) -> tuple[str, ...]:
    with _projector_driver().session(database=_service_config().database) as session:
        return tuple(str(record[0]) for record in session.run(statement, parameters))


def _cleanup(
    config: Neo4jProjectorConfig,
    *generation_ids: ProjectionGenerationId,
) -> None:
    adapter = _open_neo4j_adapter(config)
    try:
        adapter.verify_compatibility()
        for generation_id in generation_ids:
            adapter.cleanup_generation(str(generation_id))
    finally:
        adapter.close()


def _event_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0])


def test_actual_service_increment4_admitted_state_projects_exactly_and_replays(
    tmp_path: Path,
) -> None:
    config = _service_config()
    state = seed_increment4_graphiti_path(tmp_path / "authority")
    admitted = admit_increment4_graphiti_path(state)
    snapshot = admitted.snapshot
    generation_id = ProjectionGenerationId.new()
    batches, canonical_ids, node_ids, relation_keys = _expected(
        snapshot, generation_id
    )
    request = _request(
        generation_id,
        snapshot,
        key="increment4e-actual-service-build-v1",
    )
    before_events = _event_count(state.extraction.database)
    adapter = _open_neo4j_adapter(config)
    system = open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    )
    try:
        built = system.increment4.build_and_promote(
            request,
            proof=extraction_proof(),
        )
        response = system.increment4.read_active(
            Increment4Neo4jActiveReadRequest(
                canonical_ids=canonical_ids,
                query_valid_time=SOURCE_NOW,
                limit=100,
            ),
            proof=extraction_proof(),
        )
        after_first = _event_count(state.extraction.database)
        replay = system.increment4.build_and_promote(
            request,
            proof=extraction_proof(),
        )
        after_replay = _event_count(state.extraction.database)
    finally:
        system.close()

    try:
        assert built.generation.state is ProjectionGenerationState.ACTIVE
        assert replay.promotion.promotion_digest == built.promotion.promotion_digest
        assert replay.validation.validation_digest == built.validation.validation_digest
        assert after_first > before_events
        assert after_replay == after_first
        assert response.metadata.generation_id == generation_id
        assert {item.canonical_id for item in response.nodes} == node_ids
        assert {item.relation_key for item in response.relations} == relation_keys
        assert all(item.trust_scope.value == "ADMITTED" for item in response.relations)
        assert _scalar(
            "MATCH (n:NewsroomProjectionNode {generation_id:$generation_id}) "
            "RETURN count(n)",
            generation_id=str(generation_id),
        ) == len(node_ids)
        assert _scalar(
            "MATCH (:NewsroomProjectionNode {generation_id:$generation_id})"
            "-[r]->(:NewsroomProjectionNode {generation_id:$generation_id}) "
            "WHERE r.generation_id=$generation_id RETURN count(r)",
            generation_id=str(generation_id),
        ) == len(relation_keys)
        assert _scalar(
            "MATCH (d:NewsroomProjectionDelivery {generation_id:$generation_id}) "
            "RETURN count(d)",
            generation_id=str(generation_id),
        ) == len(batches)

        projected_ids = _values(
            "MATCH (n:NewsroomProjectionNode {generation_id:$generation_id}) "
            "RETURN n.canonical_id ORDER BY n.canonical_id",
            generation_id=str(generation_id),
        )
        prohibited = {
            str(RELATION_PROPOSAL_ID),
            str(RELATION_PROPOSAL_V1_ID),
        }
        assert prohibited.isdisjoint(projected_ids)
        assert not _values(
            "MATCH (n {generation_id:$generation_id}) "
            "UNWIND labels(n) AS label "
            "WITH DISTINCT label WHERE label CONTAINS 'Proposal' "
            "OR label CONTAINS 'Graphiti' RETURN label ORDER BY label",
            generation_id=str(generation_id),
        )
        assert not state.workspace_root.exists() or not any(
            state.workspace_root.iterdir()
        )
        with sqlite3.connect(state.extraction.database) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM graphiti_adapter_attempts"
            ).fetchone()[0] == 2
            assert conn.execute(
                "SELECT COUNT(*) FROM extraction_proposals"
            ).fetchone()[0] >= 4
            assert conn.execute(
                "SELECT COUNT(*) FROM canonical_entities"
            ).fetchone()[0] == 2
            assert conn.execute(
                "SELECT COUNT(*) FROM editorial_relation_assertions"
            ).fetchone()[0] == 1
    finally:
        _cleanup(config, generation_id)


def test_actual_service_increment4_graph_loss_requires_isolated_replacement(
    tmp_path: Path,
) -> None:
    config = _service_config()
    state = seed_increment4_graphiti_path(tmp_path / "authority")
    admitted = admit_increment4_graphiti_path(state)
    snapshot = admitted.snapshot
    first_id = ProjectionGenerationId.new()
    replacement_id = ProjectionGenerationId.new()
    _first_batches, first_canonical_ids, _node_ids, _relation_keys = _expected(
        snapshot, first_id
    )
    _replacement_batches, replacement_canonical_ids, _node_ids2, _relation_keys2 = (
        _expected(snapshot, replacement_id)
    )
    first_request = _request(
        first_id,
        snapshot,
        key="increment4e-actual-service-loss-v1",
    )
    database = state.extraction.database

    system = open_graphiti_path_increment4_neo4j_system(
        state.relation,
        _open_neo4j_adapter(config),
    )
    try:
        first = system.increment4.build_and_promote(
            first_request,
            proof=extraction_proof(),
        )
        initial = system.increment4.read_active(
            Increment4Neo4jActiveReadRequest(
                canonical_ids=first_canonical_ids,
                query_valid_time=SOURCE_NOW,
                limit=100,
            ),
            proof=extraction_proof(),
        )
        before_events = _event_count(database)
    finally:
        system.close()

    try:
        _cleanup(config, first_id)
        restarted = open_graphiti_path_increment4_neo4j_system(
            state.relation,
            _open_neo4j_adapter(config),
        )
        try:
            missing = restarted.increment4.read_active(
                Increment4Neo4jActiveReadRequest(
                    canonical_ids=first_canonical_ids,
                    query_valid_time=SOURCE_NOW,
                    limit=100,
                ),
                proof=extraction_proof(),
            )
            assert missing.nodes == ()
            assert missing.relations == ()
            with pytest.raises(Neo4jIdentityConflict):
                restarted.increment4.build_and_promote(
                    first_request,
                    proof=extraction_proof(),
                )
            still_active = restarted.increment4.generation_status(
                first_id,
                proof=extraction_proof(),
            )
            replacement = restarted.increment4.build_and_promote(
                _request(
                    replacement_id,
                    snapshot,
                    key="increment4e-actual-service-loss-replacement-v1",
                ),
                proof=extraction_proof(),
            )
            retired = restarted.increment4.generation_status(
                first_id,
                proof=extraction_proof(),
            )
            after = restarted.increment4.read_active(
                Increment4Neo4jActiveReadRequest(
                    canonical_ids=replacement_canonical_ids,
                    query_valid_time=SOURCE_NOW,
                    limit=100,
                ),
                proof=extraction_proof(),
            )
        finally:
            restarted.close()

        assert first.generation.state is ProjectionGenerationState.ACTIVE
        assert still_active.generation.state is ProjectionGenerationState.ACTIVE
        assert replacement.generation.state is ProjectionGenerationState.ACTIVE
        assert replacement.prior_generation is not None
        assert replacement.prior_generation.generation_id == first_id
        assert retired.generation.state is ProjectionGenerationState.RETIRED
        assert after.metadata.generation_id == replacement_id
        assert {item.canonical_id for item in after.nodes} == {
            item.canonical_id for item in initial.nodes
        }
        assert {
            (item.relation_type, item.source_canonical_id, item.target_canonical_id)
            for item in after.relations
        } == {
            (item.relation_type, item.source_canonical_id, item.target_canonical_id)
            for item in initial.relations
        }
        assert _event_count(database) > before_events
    finally:
        _cleanup(config, first_id, replacement_id)



def test_actual_service_increment4_replacement_generation_is_only_serving_state(
    tmp_path: Path,
) -> None:
    config = _service_config()
    state = seed_increment4_graphiti_path(tmp_path / "authority")
    admitted = admit_increment4_graphiti_path(state)
    snapshot = admitted.snapshot
    first_id = ProjectionGenerationId.new()
    second_id = ProjectionGenerationId.new()
    _first_batches, first_canonical_ids, _nodes, _relations = _expected(
        snapshot, first_id
    )
    _second_batches, second_canonical_ids, _nodes2, _relations2 = _expected(
        snapshot, second_id
    )

    system = open_graphiti_path_increment4_neo4j_system(
        state.relation,
        _open_neo4j_adapter(config),
    )
    try:
        first = system.increment4.build_and_promote(
            _request(first_id, snapshot, key="increment4e-service-first-v1"),
            proof=extraction_proof(),
        )
        second = system.increment4.build_and_promote(
            _request(second_id, snapshot, key="increment4e-service-second-v1"),
            proof=extraction_proof(),
        )
        first_status = system.increment4.generation_status(
            first_id,
            proof=extraction_proof(),
        )
        active = system.increment4.read_active(
            Increment4Neo4jActiveReadRequest(
                canonical_ids=second_canonical_ids,
                query_valid_time=SOURCE_NOW,
                limit=100,
            ),
            proof=extraction_proof(),
        )
    finally:
        system.close()

    try:
        assert first.generation.state is ProjectionGenerationState.ACTIVE
        assert second.generation.state is ProjectionGenerationState.ACTIVE
        assert second.prior_generation is not None
        assert second.prior_generation.generation_id == first_id
        assert first_status.generation.state is ProjectionGenerationState.RETIRED
        assert active.metadata.generation_id == second_id
        assert active.nodes and active.relations
        assert _scalar(
            "MATCH (n {generation_id:$generation_id}) RETURN count(n)",
            generation_id=str(first_id),
        ) == 0
        assert _scalar(
            "MATCH (n {generation_id:$generation_id}) RETURN count(n)",
            generation_id=str(second_id),
        ) > 0
        assert first_canonical_ids == second_canonical_ids
    finally:
        _cleanup(config, first_id, second_id)


def test_actual_service_increment4_tombstone_purges_and_never_resurrects(
    tmp_path: Path,
) -> None:
    config = _service_config()
    state = seed_increment4_graphiti_path(tmp_path / "authority")
    admitted = admit_increment4_graphiti_path(state)
    first_id = ProjectionGenerationId.new()
    purge_id = ProjectionGenerationId.new()
    _batches, canonical_ids, _node_ids, _relation_keys = _expected(
        admitted.snapshot, first_id
    )

    system = open_graphiti_path_increment4_neo4j_system(
        state.relation,
        _open_neo4j_adapter(config),
    )
    try:
        first = system.increment4.build_and_promote(
            _request(
                first_id,
                admitted.snapshot,
                key="increment4e-service-tombstone-base-v1",
            ),
            proof=extraction_proof(),
        )
    finally:
        system.close()

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
            reason_code="INCREMENT4E_ACTUAL_SOURCE_DELETE",
            idempotency_key="increment4e-actual-source-delete-v1",
            proof=object_proof(),
        )
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="INCREMENT4E_ACTUAL_SOURCE_TOMBSTONE",
            idempotency_key="increment4e-actual-source-tombstone-v1",
            proof=object_proof(),
        )

    events = _ledger_events(state.extraction.database)
    empty = sorted_snapshot(
        entities=(),
        relations=(),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    purge_request = _request(
        purge_id,
        empty,
        key="increment4e-actual-source-purge-v1",
    )
    restarted = open_graphiti_path_increment4_neo4j_system(
        state.relation,
        _open_neo4j_adapter(config),
    )
    try:
        purged = restarted.increment4.build_and_promote(
            purge_request,
            proof=extraction_proof(),
        )
        read = restarted.increment4.read_active(
            Increment4Neo4jActiveReadRequest(
                canonical_ids=canonical_ids,
                query_valid_time=SOURCE_NOW,
                limit=100,
            ),
            proof=extraction_proof(),
        )
        replay = restarted.increment4.build_and_promote(
            purge_request,
            proof=extraction_proof(),
        )
    finally:
        restarted.close()

    try:
        assert first.generation.state is ProjectionGenerationState.ACTIVE
        assert purged.generation.state is ProjectionGenerationState.ACTIVE
        assert purged.prior_generation is not None
        assert purged.prior_generation.generation_id == first_id
        assert purged.projected_batch_count == 0
        assert purged.purged_retired_graph_record_count > 0
        assert read.nodes == ()
        assert read.relations == ()
        assert replay.validation.validation_digest == purged.validation.validation_digest
        assert replay.promotion.promotion_digest == purged.promotion.promotion_digest
        assert _scalar(
            "MATCH (n {generation_id:$generation_id}) RETURN count(n)",
            generation_id=str(first_id),
        ) == 0
        assert _scalar(
            "MATCH (n {generation_id:$generation_id}) RETURN count(n)",
            generation_id=str(purge_id),
        ) == 0
        with sqlite3.connect(state.extraction.database) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM graphiti_adapter_attempts"
            ).fetchone()[0] == 2
            assert conn.execute(
                "SELECT COUNT(*) FROM editorial_relation_assertions"
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM object_deletion_heads h "
                "JOIN object_deletion_versions v "
                "ON v.deletion_id=h.deletion_id "
                "AND v.lifecycle_version=h.current_version "
                "WHERE h.deletion_id=? AND v.state='TOMBSTONED'",
                (str(deletion.deletion_id),),
            ).fetchone()[0] == 1
    finally:
        _cleanup(config, first_id, purge_id)
