from __future__ import annotations

from pathlib import Path
import sqlite3

from newsroom.projection import INTEGRATED_FIXTURE_V2_PROJECTION
from newsroom.projection.neo4j import CompleteDerivativeType, CompleteRebuildRequest
from newsroom.relations import INTEGRATED_FIXTURE_V2

from .complete_projection_2b_helpers import (
    MemoryCompleteNeo4jAdapter,
    open_complete_test_system,
    proof,
    register_complete_generation,
    seed_complete_fixture_authority,
)
from .relation_2a_helpers import (
    bind_fixture_and_propose,
    open_fixture_object_system,
    proof as relation_proof,
    seed_fixture_objects,
)


def _latest(database: Path) -> int:
    with sqlite3.connect(database) as conn:
        return int(
            conn.execute(
                "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events "
                "WHERE security_scope != 'authority.projection'"
            ).fetchone()[0]
        )


def _rebuild(system, generation, database: Path, *, key: str):
    latest = _latest(database)
    return system.complete.rebuild(
        CompleteRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=generation.authority_aggregate_version,
            through_ledger_seq=latest,
            reason_code="INCREMENT_2B_SOURCE_STORE_PROOF",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def test_source_store_derives_six_active_bilingual_documents_and_one_relation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_complete_fixture_authority(database, object_root=object_root)
    adapter = MemoryCompleteNeo4jAdapter()
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        generation = register_complete_generation(system)
        result = _rebuild(system, generation, database, key="source-store-complete")
    finally:
        system.close()

    documents = tuple(
        document
        for batch in adapter.deliveries.values()
        for document in batch.documents
    )
    relations = tuple(
        relation
        for batch in adapter.deliveries.values()
        for relation in batch.relations
    )
    assert result.checkpoint_ledger_seq == result.through_ledger_seq
    assert tuple(sorted(item.passage_id for item in documents)) == (
        INTEGRATED_FIXTURE_V2_PROJECTION.expected_active_passage_ids
    )
    assert {item.language for item in documents} == {"en-GB", "zh-HK"}
    assert all(item.vector_dimensions == 16 for item in documents)
    assert all(item.vector_component_scale == 1_000_000 for item in documents)
    assert len(relations) == 1
    assert relations[0].predicate.value == "DEVELOPMENT_OF"
    assert relations[0].trust_scope.value == "ADMITTED"
    assert "ifv2-tombstoned-negative" not in {
        item.passage_id for item in documents
    }


def test_proposal_only_relation_never_enters_complete_projection_batches(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seeded = seed_fixture_objects(database, object_root=object_root)
    bind_fixture_and_propose(database, seeded)
    adapter = MemoryCompleteNeo4jAdapter()
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        generation = register_complete_generation(system)
        _rebuild(system, generation, database, key="proposal-only-rebuild")
    finally:
        system.close()

    assert sum(len(batch.documents) for batch in adapter.deliveries.values()) == 6
    assert sum(len(batch.relations) for batch in adapter.deliveries.values()) == 0


def test_revoked_evidence_is_never_upserted_and_emits_both_index_removals(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seeded, _proposal, _decision = seed_complete_fixture_authority(
        database,
        object_root=object_root,
    )
    passage_id = "ifv2-new-en"
    admission_id = seeded.admission_by_passage_id[passage_id]
    object_system = open_fixture_object_system(
        database,
        object_root=object_root,
    )
    try:
        object_system.objects.revoke(
            admission_id,
            reason_code="INCREMENT_2B_EVIDENCE_REVOKED",
            idempotency_key="increment-2b-evidence-revoke",
            proof=relation_proof(),
        )
    finally:
        object_system.close()

    adapter = MemoryCompleteNeo4jAdapter()
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        generation = register_complete_generation(system)
        _rebuild(system, generation, database, key="revoked-evidence-rebuild")
    finally:
        system.close()

    documents = tuple(
        document
        for batch in adapter.deliveries.values()
        for document in batch.documents
    )
    relations = tuple(
        relation
        for batch in adapter.deliveries.values()
        for relation in batch.relations
    )
    removals = tuple(
        removal
        for batch in adapter.deliveries.values()
        for removal in batch.removals
        if removal.stable_key == passage_id
    )
    assert passage_id not in {item.passage_id for item in documents}
    assert relations == ()
    assert {item.derivative_type for item in removals} == {
        CompleteDerivativeType.FULL_TEXT,
        CompleteDerivativeType.VECTOR,
    }
    assert all(item.object_admission_ids == (admission_id,) for item in removals)


def test_source_documents_are_derived_from_governed_bytes_not_fixture_snippets(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_complete_fixture_authority(database, object_root=object_root)
    adapter = MemoryCompleteNeo4jAdapter()
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        generation = register_complete_generation(system)
        _rebuild(system, generation, database, key="governed-bytes-rebuild")
    finally:
        system.close()

    by_id = {
        document.passage_id: document
        for batch in adapter.deliveries.values()
        for document in batch.documents
    }
    fulltext = INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_contract
    for passage_id, document in by_id.items():
        governed = INTEGRATED_FIXTURE_V2.passage_by_id[passage_id]
        assert document.retrieval_text == fulltext.normalize(governed.text)
        assert document.blob_digest == governed.blob_digest
        assert document.admission_id is not None
