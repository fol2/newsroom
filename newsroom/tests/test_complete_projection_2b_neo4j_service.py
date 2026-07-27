from __future__ import annotations

import atexit
from functools import lru_cache
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest
from newsroom.projection import (
    CompleteProjectionProfile,
    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    INTEGRATED_FIXTURE_V2_PROJECTION,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionStateError,
)
from newsroom.projection.neo4j import (
    CompleteDeliveryRequest,
    CompleteGenerationQualificationRequest,
    CompleteGenerationValidationRequest,
    CompleteRebuildRequest,
    Neo4jConfigurationError,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    complete_generation_names,
)
from newsroom.projection.neo4j._complete_adapter import (
    _open_complete_neo4j_adapter,
)
from newsroom.relations import INTEGRATED_FIXTURE_V2

from .authority_a2b_helpers import open_object_system
from .authority_event_helpers import payload_schemas
from .complete_projection_2b_helpers import (
    COMPLETE_NOW,
    complete_identity,
    complete_scopes,
    open_complete_test_system,
    proof,
    register_complete_generation,
    seed_complete_fixture_authority,
)
from .projection_b1_helpers import source_command_registry
from newsroom.projection.policy import merge_projection_authority_registries
from newsroom.relations.policy import merge_relation_authority_registries


_REQUIRED_FLAG = "NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED"


@lru_cache(maxsize=1)
def _service_config() -> Neo4jProjectorConfig:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("actual complete Neo4j service is required only by the 2B gate")
    return Neo4jProjectorConfig.from_environment()


_PROJECTOR_ADMIN_DRIVER = None


def _projector_driver():
    global _PROJECTOR_ADMIN_DRIVER
    if _PROJECTOR_ADMIN_DRIVER is None:
        from neo4j import GraphDatabase

        config = _service_config()
        _PROJECTOR_ADMIN_DRIVER = GraphDatabase.driver(
            config.uri,
            auth=(config.username, config.password),
        )
        _PROJECTOR_ADMIN_DRIVER.verify_connectivity()
    return _PROJECTOR_ADMIN_DRIVER


def _close_projector_driver() -> None:
    global _PROJECTOR_ADMIN_DRIVER
    if _PROJECTOR_ADMIN_DRIVER is not None:
        _PROJECTOR_ADMIN_DRIVER.close()
        _PROJECTOR_ADMIN_DRIVER = None


atexit.register(_close_projector_driver)


def _latest_source(database: Path) -> int:
    with sqlite3.connect(database) as conn:
        return int(
            conn.execute(
                "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events "
                "WHERE security_scope != 'authority.projection'"
            ).fetchone()[0]
        )


def _current(system, generation_id):
    return next(
        item
        for item in system.projections.generations(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        )
        if item.generation_id == generation_id
    )


def _setup(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seeded, proposal, decision = seed_complete_fixture_authority(
        database,
        object_root=object_root,
    )
    adapter = _open_complete_neo4j_adapter(_service_config())
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    generation = register_complete_generation(
        system,
        suffix=f"service-{uuid4().hex}",
    )
    return database, object_root, seeded, proposal, decision, system, generation


def _rebuild(system, generation, database: Path, *, key: str):
    return system.complete.rebuild(
        CompleteRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=generation.authority_aggregate_version,
            through_ledger_seq=_latest_source(database),
            reason_code="INCREMENT_2B_ACTUAL_SERVICE_REBUILD",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _validate(system, generation_id, checkpoint: int, *, key: str):
    current = _current(system, generation_id)
    return system.complete.validate_generation(
        CompleteGenerationValidationRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=checkpoint,
            reason_code="INCREMENT_2B_ACTUAL_SERVICE_VALIDATE",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _qualify(system, generation_id, checkpoint: int):
    return system.complete.qualify_generation(
        CompleteGenerationQualificationRequest(
            generation_id=generation_id,
            checkpoint_ledger_seq=checkpoint,
            profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
        ),
        proof=proof(),
    )


def _names(generation_id):
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    return complete_generation_names(
        complete_identity(generation_id),
        fixture.fulltext_contract,
        fixture.vector_contract,
    )


def _projector_write(statement: str, **parameters) -> None:
    driver = _projector_driver()
    with driver.session(database=_service_config().database) as session:
        session.run(statement, parameters).consume()


def _projector_scalar(statement: str, **parameters) -> int:
    driver = _projector_driver()
    with driver.session(database=_service_config().database) as session:
        record = session.run(statement, parameters).single(strict=True)
        return int(record[0])


def _cleanup_generation(generation_id) -> None:
    names = _names(generation_id)
    for index_name in (names.fulltext_index_name, names.vector_index_name):
        _projector_write(f"DROP INDEX `{index_name}` IF EXISTS")
    _projector_write(
        "MATCH (value) WHERE value.generation_id=$generation_id "
        "DETACH DELETE value",
        generation_id=str(generation_id),
    )


def _assert_exact_query_evidence(qualification) -> None:
    fulltext_first = {}
    for hit in qualification.fulltext_hits:
        fulltext_first.setdefault(hit.query_id, hit.passage_id)
    assert fulltext_first == {
        query_id: query.expected_first_passage_id
        for query in INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_queries
        for query_id in (
            query.query_id,
            f"{query.query_id}.normalized",
        )
    }
    vector_by_query: dict[str, list[str]] = {}
    for hit in qualification.vector_hits:
        vector_by_query.setdefault(hit.query_id, []).append(hit.passage_id)
    for query in INTEGRATED_FIXTURE_V2_PROJECTION.vector_queries:
        assert tuple(
            vector_by_query[query.query_id][
                : len(query.expected_active_prefix)
            ]
        ) == query.expected_active_prefix


def test_actual_service_complete_generation_queries_and_promotes_exact_state(
    tmp_path: Path,
) -> None:
    database, _root, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    try:
        rebuilt = _rebuild(
            system,
            generation,
            database,
            key="actual-complete-rebuild",
        )
        validation = _validate(
            system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="actual-complete-validate",
        )
        qualification = _qualify(
            system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
        )
        assert qualification.projection_state_digest == (
            validation.projection_state_digest
        )
        _assert_exact_query_evidence(qualification)

        current = _current(system, generation.generation_id)
        promoted = system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                generation_id=generation.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                validation_digest=validation.validation_digest,
                reason_code="INCREMENT_2B_ACTUAL_SERVICE_PROMOTE",
                idempotency_key="actual-complete-promote",
            ),
            proof=proof(),
        )
        assert promoted.generation.state is ProjectionGenerationState.ACTIVE
        assert _projector_scalar(
            "MATCH ()-[relation:DEVELOPMENT_OF {generation_id:$generation_id}]->() "
            "RETURN count(relation)",
            generation_id=str(generation.generation_id),
        ) == 1
        assert _projector_scalar(
            "MATCH (document {generation_id:$generation_id, passage_id:$passage}) "
            "RETURN count(document)",
            generation_id=str(generation.generation_id),
            passage=INTEGRATED_FIXTURE_V2.tombstoned_negative_passage_id,
        ) == 0
    finally:
        system.close()
        _cleanup_generation(generation.generation_id)


@pytest.mark.parametrize(
    "tamper",
    (
        "missing-vector-index",
        "wrong-vector-dimensions",
        "wrong-fulltext-analyzer",
        "deleted-document",
    ),
)
def test_actual_service_partial_or_contract_mismatched_state_fails_closed(
    tmp_path: Path,
    tamper: str,
) -> None:
    root = tmp_path / tamper
    database, _objects, _seeded, _proposal, _decision, system, generation = _setup(
        root
    )
    names = _names(generation.generation_id)
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    try:
        rebuilt = _rebuild(
            system,
            generation,
            database,
            key=f"actual-tamper-rebuild-{tamper}",
        )
        if tamper == "missing-vector-index":
            _projector_write(f"DROP INDEX `{names.vector_index_name}`")
        elif tamper == "wrong-vector-dimensions":
            _projector_write(f"DROP INDEX `{names.vector_index_name}`")
            _projector_write(
                f"""
                CREATE VECTOR INDEX `{names.vector_index_name}`
                FOR (node:`{names.document_label}`)
                ON (node.`{fixture.vector_contract.vector_property}`)
                OPTIONS {{indexConfig: {{
                  `vector.dimensions`: 15,
                  `vector.similarity_function`: 'cosine',
                  `vector.quantization.type`: 'none'
                }}}}
                """
            )
            _projector_write("CALL db.awaitIndexes(120)")
        elif tamper == "wrong-fulltext-analyzer":
            _projector_write(f"DROP INDEX `{names.fulltext_index_name}`")
            _projector_write(
                f"""
                CREATE FULLTEXT INDEX `{names.fulltext_index_name}`
                FOR (node:`{names.document_label}`)
                ON EACH [node.`{fixture.fulltext_contract.retrieval_property}`]
                OPTIONS {{indexConfig: {{
                  `fulltext.analyzer`: 'english',
                  `fulltext.eventually_consistent`: false
                }}}}
                """
            )
            _projector_write("CALL db.awaitIndexes(120)")
        else:
            _projector_write(
                "MATCH (document {generation_id:$generation_id, passage_id:$passage}) "
                "DETACH DELETE document",
                generation_id=str(generation.generation_id),
                passage="ifv2-new-en",
            )

        with pytest.raises(Neo4jIdentityConflict):
            _validate(
                system,
                generation.generation_id,
                rebuilt.checkpoint_ledger_seq,
                key=f"actual-tamper-validate-{tamper}",
            )
    finally:
        system.close()
        _cleanup_generation(generation.generation_id)


def test_actual_service_wrong_watermark_generation_and_vector_dimension_fail_closed(
    tmp_path: Path,
) -> None:
    database, _objects, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    names = _names(generation.generation_id)
    try:
        latest = _latest_source(database)
        with pytest.raises(ProjectionStateError, match="exact current authority watermark"):
            system.complete.rebuild(
                CompleteRebuildRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=generation.authority_aggregate_version,
                    through_ledger_seq=latest - 1,
                    reason_code="ACTUAL_STALE_WATERMARK",
                    idempotency_key="actual-stale-watermark",
                ),
                proof=proof(),
            )
        rebuilt = _rebuild(
            system,
            generation,
            database,
            key="actual-dimension-rebuild",
        )
        from neo4j.exceptions import Neo4jError

        with pytest.raises(Neo4jError):
            _projector_write(
                "CALL db.index.vector.queryNodes($index_name, 3, $vector) "
                "YIELD node, score RETURN count(node)",
                index_name=names.vector_index_name,
                vector=[0.25] * 15,
            )
        with pytest.raises(ProjectionStateError, match="does not exist"):
            _qualify(
                system,
                type(generation.generation_id).new(),
                rebuilt.checkpoint_ledger_seq,
            )
        projector = _service_config()
        with pytest.raises(Neo4jConfigurationError, match="bootstrap administrator"):
            Neo4jProjectorConfig(
                uri=projector.uri,
                database=projector.database,
                username="neo4j",
                password="bootstrap-credential-not-used",
            )
    finally:
        system.close()
        _cleanup_generation(generation.generation_id)


def test_actual_service_replacement_generation_recovers_from_authority_only(
    tmp_path: Path,
) -> None:
    database, _objects, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    replacement = None
    try:
        rebuilt = _rebuild(
            system,
            generation,
            database,
            key="actual-primary-rebuild",
        )
        names = _names(generation.generation_id)
        _projector_write(f"DROP INDEX `{names.fulltext_index_name}`")
        _projector_write(
            "MATCH (value {generation_id:$generation_id}) DETACH DELETE value",
            generation_id=str(generation.generation_id),
        )
        with pytest.raises(Neo4jIdentityConflict):
            _validate(
                system,
                generation.generation_id,
                rebuilt.checkpoint_ledger_seq,
                key="actual-primary-damaged-validate",
            )

        replacement = register_complete_generation(
            system,
            suffix=f"replacement-{uuid4().hex}",
            register_family=False,
        )
        recovered = _rebuild(
            system,
            replacement,
            database,
            key="actual-replacement-rebuild",
        )
        validation = _validate(
            system,
            replacement.generation_id,
            recovered.checkpoint_ledger_seq,
            key="actual-replacement-validate",
        )
        qualification = _qualify(
            system,
            replacement.generation_id,
            recovered.checkpoint_ledger_seq,
        )
        assert qualification.projection_state_digest == (
            validation.projection_state_digest
        )
        _assert_exact_query_evidence(qualification)
    finally:
        system.close()
        _cleanup_generation(generation.generation_id)
        if replacement is not None:
            _cleanup_generation(replacement.generation_id)


def _complete_object_registries():
    relation_commands, relation_schemas = merge_relation_authority_registries(
        command_registry=source_command_registry(),
        payload_schemas=payload_schemas(),
    )
    return merge_projection_authority_registries(
        command_registry=relation_commands,
        payload_schemas=relation_schemas,
    )


def test_actual_service_revocation_and_tombstone_remove_current_derivatives(
    tmp_path: Path,
) -> None:
    database, object_root, seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    try:
        rebuilt = _rebuild(
            system,
            generation,
            database,
            key="actual-lifecycle-initial-rebuild",
        )
        validation = _validate(
            system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="actual-lifecycle-initial-validate",
        )
        current = _current(system, generation.generation_id)
        system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                generation_id=generation.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                validation_digest=validation.validation_digest,
                reason_code="ACTUAL_LIFECYCLE_PROMOTE",
                idempotency_key="actual-lifecycle-promote",
            ),
            proof=proof(),
        )
    finally:
        system.close()

    active_passage = INTEGRATED_FIXTURE_V2.passage_by_id["ifv2-new-en"]
    admission_id = seeded.admission_by_passage_id[active_passage.passage_id]
    commands, schemas = _complete_object_registries()
    object_system = open_object_system(
        database,
        object_root=object_root,
        scopes=complete_scopes(),
        command_registry=commands,
        payload_schema_registry=schemas,
        clock=lambda: COMPLETE_NOW,
    )
    try:
        object_system.objects.revoke(
            admission_id,
            reason_code="ACTUAL_FIXTURE_PASSAGE_REVOKED",
            idempotency_key="actual-fixture-passage-revoke",
            proof=proof(),
        )
        deletion = object_system.objects.request_deletion(
            active_passage.blob_digest,
            reason_code="ACTUAL_FIXTURE_PASSAGE_DELETE",
            idempotency_key="actual-fixture-passage-delete",
            proof=proof(),
        )
        object_system.objects.tombstone(
            deletion.deletion_id,
            reason_code="ACTUAL_FIXTURE_PASSAGE_TOMBSTONE",
            idempotency_key="actual-fixture-passage-tombstone",
            proof=proof(),
        )
    finally:
        object_system.close()

    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=_open_complete_neo4j_adapter(_service_config()),
    )
    try:
        start = system.projections.status(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        ).contiguous_ledger_seq
        target = _latest_source(database)
        for ledger_seq in range(start + 1, target + 1):
            current = _current(system, generation.generation_id)
            system.complete.deliver(
                CompleteDeliveryRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=current.authority_aggregate_version,
                    ledger_seq=ledger_seq,
                    idempotency_key=f"actual-lifecycle-delivery-{ledger_seq}",
                ),
                proof=proof(),
            )
        assert _projector_scalar(
            "MATCH (document {generation_id:$generation_id, passage_id:$passage}) "
            "RETURN count(document)",
            generation_id=str(generation.generation_id),
            passage=active_passage.passage_id,
        ) == 0
        assert _projector_scalar(
            "MATCH ()-[relation:DEVELOPMENT_OF {generation_id:$generation_id}]->() "
            "RETURN count(relation)",
            generation_id=str(generation.generation_id),
        ) == 0
        with pytest.raises(Neo4jIdentityConflict):
            _validate(
                system,
                generation.generation_id,
                target,
                key="actual-lifecycle-incomplete-validate",
            )
    finally:
        system.close()
        _cleanup_generation(generation.generation_id)
