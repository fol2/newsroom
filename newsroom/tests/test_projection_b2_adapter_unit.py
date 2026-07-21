from __future__ import annotations

from typing import Any

import pytest

from newsroom.projection import ProjectionNodeType
from newsroom.projection.neo4j import (
    Neo4jIdentityConflict,
    Neo4jReadError,
    StructuralGraphNodeView,
)
from newsroom.projection.neo4j._adapter import (
    _CLEANUP_GENERATION_QUERY,
    _FIND_DELIVERY_QUERY,
    _MERGE_NODE_QUERY,
    _READ_RELATIONS_QUERY,
    _Neo4jAdapter,
    _node_properties,
    _require_node_within_watermark,
    _relation_properties,
    _relation_view,
)

from .projection_b2_helpers import structural_batch


class _SingleResult:
    def __init__(self, record: dict[str, object] | None) -> None:
        self._record = record

    def single(self) -> dict[str, object] | None:
        return self._record


class _SameSequenceTamperTransaction:
    def run(
        self,
        statement: str,
        parameters: dict[str, object] | None = None,
    ) -> _SingleResult:
        values = parameters or {}
        if statement == _FIND_DELIVERY_QUERY:
            return _SingleResult(None)
        if statement == _MERGE_NODE_QUERY:
            properties = dict(values["properties"])
            properties["first_source_event_id"] = "tampered-event"
            return _SingleResult({"properties": properties})
        raise AssertionError("same-sequence conflict must fail before later writes")


def test_none_object_admission_uses_explicit_storage_sentinel() -> None:
    batch = structural_batch(object_admission_id=None)
    relation = batch.relations[0]
    properties = _relation_properties(batch, relation)

    assert properties["object_admission_id"] == ""
    assert all(value is not None for value in properties.values())

    view = _relation_view(properties, relation_type=relation.relation_type)
    assert view.object_admission_id is None


def test_present_object_admission_round_trips_without_rewriting() -> None:
    batch = structural_batch(object_admission_id="admission-b2-fixture")
    relation = batch.relations[0]
    properties = _relation_properties(batch, relation)

    assert properties["object_admission_id"] == "admission-b2-fixture"
    view = _relation_view(properties, relation_type=relation.relation_type)
    assert view.object_admission_id == "admission-b2-fixture"


def test_same_sequence_node_provenance_conflict_fails_before_relation_write() -> None:
    batch = structural_batch()
    with pytest.raises(Neo4jIdentityConflict, match="same sequence"):
        _Neo4jAdapter._apply_transaction(
            _SameSequenceTamperTransaction(),
            batch,
        )


def test_cleanup_is_limited_to_repository_owned_projection_labels() -> None:
    assert "value:NewsroomProjectionNode" in _CLEANUP_GENERATION_QUERY
    assert "value:NewsroomProjectionDelivery" in _CLEANUP_GENERATION_QUERY
    assert "value:NewsroomProjectionRelationIdentity" in _CLEANUP_GENERATION_QUERY
    assert "AND (value:" in _CLEANUP_GENERATION_QUERY
    assert "MATCH (value)\nWHERE value.generation_id" in _CLEANUP_GENERATION_QUERY


def test_node_properties_never_include_driver_internal_identity() -> None:
    batch = structural_batch()
    properties = _node_properties(batch, batch.nodes[0])
    assert "id" not in properties
    assert "element_id" not in properties
    assert "neo4j_id" not in properties


def test_relation_reads_cannot_return_future_endpoint_nodes() -> None:
    assert "source.first_ledger_seq <= $maximum_ledger_seq" in _READ_RELATIONS_QUERY
    assert "target.first_ledger_seq <= $maximum_ledger_seq" in _READ_RELATIONS_QUERY
    node = StructuralGraphNodeView(
        canonical_id="npid:v1:fixture:future",
        node_type=ProjectionNodeType.AUTHORITY_AGGREGATE,
        identity_source="AUTHORITY_AGGREGATE",
        identity_reference_digest="sha256:" + "a" * 64,
        first_ledger_seq=11,
        first_source_event_id="event-future",
        first_source_event_digest="sha256:" + "b" * 64,
    )
    with pytest.raises(Neo4jReadError, match="watermark"):
        _require_node_within_watermark(node, 10)
