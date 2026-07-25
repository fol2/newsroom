from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from newsroom.projection import CompleteProjectionProfile, INTEGRATED_FIXTURE_V2_PROJECTION
from newsroom.projection.neo4j import (
    CompleteQueryKind,
    Neo4jIdentityConflict,
    Neo4jIndexState,
    Neo4jIndexType,
    complete_generation_names,
)
from newsroom.projection.neo4j._complete_adapter import (
    _AWAIT_INDEXES_QUERY,
    _COMPLETE_DOCUMENT_BASE_LABEL,
    _CompleteNeo4jAdapter,
    _IndexInventory,
    _fulltext_index_create_query,
    _index_inventory,
    _merge_document_query,
    _merge_relation_query,
    _query_hits,
    _require_generation_contracts,
    _safe_literal_token,
    _vector_index_create_query,
)
from newsroom.projection.neo4j._complete_state import (
    _delivery_properties,
    _document_from_properties,
    _document_properties,
    _endpoint_properties,
    _relation_from_properties,
    _relation_identity_properties,
    _relation_properties,
)
from newsroom.projection.neo4j.models import Neo4jConfigurationError

from .complete_projection_2b_helpers import (
    admitted_relation,
    complete_batch,
    complete_document,
    complete_identity,
)


class _RowsTransaction:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, dict[str, object]]] = []

    def run(self, statement: str, parameters: dict[str, object] | None = None):
        self.statements.append((statement, parameters or {}))
        return list(self.rows)


class _Single:
    def __init__(self, value: dict[str, object] | None) -> None:
        self.value = value

    def single(self) -> dict[str, object] | None:
        return self.value


class _DuplicateDeliveryTransaction:
    def __init__(self, batch) -> None:
        self.batch = batch
        self.calls = 0

    def run(self, statement: str, parameters: dict[str, object] | None = None):
        self.calls += 1
        return _Single({"properties": _delivery_properties(self.batch)})


class _DocumentTamperTransaction:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, statement: str, parameters: dict[str, object] | None = None):
        self.calls += 1
        values = parameters or {}
        if self.calls == 1:
            return _Single(None)
        properties = dict(values.get("properties", {}))
        properties["blob_digest"] = "sha256:" + "0" * 64
        return _Single({"properties": properties})


def _inventory_rows(*, fulltext_provider="fulltext-2.0", vector_provider="vector-2026.06"):
    identity = complete_identity()
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    names = complete_generation_names(
        identity,
        fixture.fulltext_contract,
        fixture.vector_contract,
    )
    return names, [
        {
            "name": names.fulltext_index_name,
            "type": "FULLTEXT",
            "state": "ONLINE",
            "entityType": "NODE",
            "labelsOrTypes": [names.document_label],
            "properties": [fixture.fulltext_contract.retrieval_property],
            "indexProvider": fulltext_provider,
            "options": {
                "indexConfig": {
                    "fulltext.analyzer": "standard-no-stop-words",
                    "fulltext.eventually_consistent": False,
                }
            },
        },
        {
            "name": names.vector_index_name,
            "type": "VECTOR",
            "state": "ONLINE",
            "entityType": "NODE",
            "labelsOrTypes": [names.document_label],
            "properties": [fixture.vector_contract.vector_property],
            "indexProvider": vector_provider,
            "options": {
                "indexConfig": {
                    "vector.dimensions": 16,
                    "vector.similarity_function": "COSINE",
                    "vector.quantization.type": "NONE",
                    "vector.hnsw.m": 16,
                }
            },
        },
    ]


def test_generation_index_ddl_is_fixed_and_does_not_select_provider() -> None:
    identity = complete_identity()
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    names = complete_generation_names(
        identity,
        fixture.fulltext_contract,
        fixture.vector_contract,
    )

    fulltext = _fulltext_index_create_query(names, fixture.fulltext_contract)
    vector = _vector_index_create_query(names, fixture.vector_contract)

    assert names.fulltext_index_name in fulltext
    assert names.vector_index_name in vector
    assert names.document_label in fulltext and names.document_label in vector
    assert "indexProvider" not in fulltext
    assert "indexProvider" not in vector
    assert "fulltext-2.0" not in fulltext
    assert "vector-2026.06" not in vector
    assert "`vector.dimensions`: 16" in vector
    assert "`vector.similarity_function`: 'cosine'" in vector
    assert "`vector.quantization.type`: 'none'" in vector
    assert "vector.quantization.enabled" not in vector
    assert _AWAIT_INDEXES_QUERY == "CALL db.awaitIndexes($timeout_seconds)"


def test_safe_literal_token_rejects_cypher_injection_vocabulary() -> None:
    assert _safe_literal_token("standard-no-stop-words", "analyzer") == (
        "standard-no-stop-words"
    )
    with pytest.raises(Neo4jConfigurationError, match="safe token"):
        _safe_literal_token("standard' }) MATCH (n)", "analyzer")


def test_complete_merge_queries_use_server_derived_names_and_fixed_relation() -> None:
    identity = complete_identity()
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    names = complete_generation_names(
        identity,
        fixture.fulltext_contract,
        fixture.vector_contract,
    )

    document_query = _merge_document_query(names)
    relation_query = _merge_relation_query(names)

    assert f":{_COMPLETE_DOCUMENT_BASE_LABEL}:`{names.document_label}`" in document_query
    assert "relation:DEVELOPMENT_OF" in relation_query
    assert "$relation_key" in relation_query
    assert "caller" not in relation_query.lower()


def test_index_inventory_requires_exact_provider_state_label_and_property() -> None:
    names, rows = _inventory_rows()
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    transaction = _RowsTransaction(rows)

    inventory = _CompleteNeo4jAdapter._index_inventory_transaction(
        transaction,
        names,
        fixture.fulltext_contract,
        fixture.vector_contract,
    )

    assert tuple(item.name for item in inventory) == tuple(
        sorted({names.fulltext_index_name, names.vector_index_name})
    )
    assert {item.index_type for item in inventory} == {
        Neo4jIndexType.FULL_TEXT,
        Neo4jIndexType.VECTOR,
    }

    _, wrong_dimension = _inventory_rows()
    wrong_dimension[1]["options"] = {
        "indexConfig": {
            "vector.dimensions": 15,
            "vector.similarity_function": "COSINE",
            "vector.quantization.type": "NONE",
        }
    }
    with pytest.raises(Neo4jIdentityConflict, match="retained contract"):
        _CompleteNeo4jAdapter._index_inventory_transaction(
            _RowsTransaction(wrong_dimension),
            names,
            fixture.fulltext_contract,
            fixture.vector_contract,
        )

    _, wrong_provider = _inventory_rows(fulltext_provider="fulltext-1.0")
    with pytest.raises(Neo4jIdentityConflict, match="retained contract"):
        _CompleteNeo4jAdapter._index_inventory_transaction(
            _RowsTransaction(wrong_provider),
            names,
            fixture.fulltext_contract,
            fixture.vector_contract,
        )

    with pytest.raises(Neo4jIdentityConflict, match="incomplete"):
        _CompleteNeo4jAdapter._index_inventory_transaction(
            _RowsTransaction(rows[:1]),
            names,
            fixture.fulltext_contract,
            fixture.vector_contract,
        )


def test_index_inventory_parser_rejects_malformed_rows() -> None:
    with pytest.raises(Neo4jIdentityConflict, match="malformed"):
        _index_inventory({"name": "x", "type": "RANGE"})


def test_document_and_relation_properties_round_trip_exact_authority() -> None:
    identity = complete_identity()
    document = complete_document(identity=identity)
    relation = admitted_relation(identity=identity)

    document_roundtrip = _document_from_properties(
        identity,
        _document_properties(document),
    )
    relation_roundtrip = _relation_from_properties(
        identity,
        _relation_properties(relation),
    )

    assert document_roundtrip == document
    assert relation_roundtrip == relation
    assert _endpoint_properties(identity, relation.subject)["record_id"] == (
        relation.subject.record_id
    )
    relation_identity = _relation_identity_properties(relation)
    assert relation_identity["relation_digest"] == relation.relation_digest


def test_nullable_properties_follow_neo4j_absent_property_semantics() -> None:
    identity = complete_identity()
    document = complete_document(
        "ifv2-distinct-jurisdiction",
        identity=identity,
    )
    relation = admitted_relation(identity=identity)

    document_properties = _document_properties(document)
    relation_properties = _relation_properties(relation)

    assert document.revision_id is None
    assert "revision_id" not in document_properties
    assert relation.temporal_scope.valid_until is None
    assert "valid_until" not in relation_properties
    assert _document_from_properties(identity, document_properties) == document
    assert _relation_from_properties(identity, relation_properties) == relation

    missing_required = dict(document_properties)
    missing_required.pop("passage_id")
    with pytest.raises(Neo4jIdentityConflict, match="fixed complete contract"):
        _document_from_properties(identity, missing_required)

    unexpected = dict(relation_properties)
    unexpected["caller_selected_property"] = "forbidden"
    with pytest.raises(Neo4jIdentityConflict, match="fixed complete contract"):
        _relation_from_properties(identity, unexpected)


def test_duplicate_complete_delivery_is_idempotent_without_later_writes() -> None:
    batch = complete_batch(documents=(complete_document(),))
    transaction = _DuplicateDeliveryTransaction(batch)
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    names = _require_generation_contracts(
        batch.identity,
        fulltext=fixture.fulltext_contract,
        vector=fixture.vector_contract,
        profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
    )

    outcome, affected = _CompleteNeo4jAdapter._apply_complete_transaction(
        transaction,
        batch,
        names,
    )

    assert outcome.value == "DUPLICATE"
    assert affected == 0
    assert transaction.calls == 1


def test_document_identity_tamper_fails_before_delivery_marker() -> None:
    batch = complete_batch(documents=(complete_document(),))
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    names = complete_generation_names(
        batch.identity,
        fixture.fulltext_contract,
        fixture.vector_contract,
    )
    transaction = _DocumentTamperTransaction()

    with pytest.raises(Neo4jIdentityConflict, match="complete document"):
        _CompleteNeo4jAdapter._apply_complete_transaction(
            transaction,
            batch,
            names,
        )
    assert transaction.calls == 2


def test_query_hits_are_ranked_typed_and_reject_malformed_score() -> None:
    hits = _query_hits(
        [
            {"passage_id": "ifv2-new-en", "score": 1.0},
            {"passage_id": "ifv2-new-zh-hk", "score": 0.9},
        ],
        query_id="fixture-query",
        query_kind=CompleteQueryKind.VECTOR,
    )
    assert tuple(item.rank for item in hits) == (1, 2)
    assert all(item.query_kind is CompleteQueryKind.VECTOR for item in hits)

    with pytest.raises(Neo4jIdentityConflict, match="malformed"):
        _query_hits(
            [{"passage_id": "ifv2-new-en", "score": "not-a-number"}],
            query_id="fixture-query",
            query_kind=CompleteQueryKind.FULL_TEXT,
        )
