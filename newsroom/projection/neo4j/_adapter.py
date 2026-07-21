from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from newsroom.authority.types import TrustScope, UtcTimestamp
from newsroom.projection.ontology import ProjectionNodeType, ProjectionRelationType

from .models import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
    Neo4jApplyOutcome,
    Neo4jApplyResult,
    Neo4jCompatibility,
    Neo4jCompatibilityError,
    Neo4jConnectionError,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jReadError,
    Neo4jStructuralRead,
    Neo4jWriteError,
    StructuralBatch,
    StructuralGraphNodeView,
    StructuralGraphRelationView,
)


_COMPONENT_QUERY = """
CALL dbms.components() YIELD name, versions, edition
WHERE name = 'Neo4j Kernel'
RETURN versions[0] AS version, toLower(edition) AS edition
"""

_SCHEMA_QUERIES = (
    """
    CREATE CONSTRAINT newsroom_projection_node_identity IF NOT EXISTS
    FOR (n:NewsroomProjectionNode)
    REQUIRE (n.generation_id, n.canonical_id) IS UNIQUE
    """,
    """
    CREATE CONSTRAINT newsroom_projection_delivery_identity IF NOT EXISTS
    FOR (d:NewsroomProjectionDelivery)
    REQUIRE (d.generation_id, d.ledger_seq) IS UNIQUE
    """,
    """
    CREATE CONSTRAINT newsroom_projection_relation_identity IF NOT EXISTS
    FOR (r:NewsroomProjectionRelationIdentity)
    REQUIRE (r.generation_id, r.relation_key) IS UNIQUE
    """,
    """
    CREATE INDEX newsroom_projection_node_first_sequence IF NOT EXISTS
    FOR (n:NewsroomProjectionNode)
    ON (n.generation_id, n.first_ledger_seq)
    """,
)

_FIND_DELIVERY_QUERY = """
MATCH (d:NewsroomProjectionDelivery {
  generation_id: $generation_id,
  ledger_seq: $ledger_seq
})
RETURN properties(d) AS properties
"""

_CREATE_DELIVERY_QUERY = """
CREATE (d:NewsroomProjectionDelivery)
SET d = $properties
RETURN properties(d) AS properties
"""

_MERGE_NODE_QUERY = """
MERGE (n:NewsroomProjectionNode {
  generation_id: $generation_id,
  canonical_id: $canonical_id
})
ON CREATE SET n = $properties
RETURN properties(n) AS properties
"""

_UPDATE_NODE_FIRST_PROVENANCE_QUERY = """
MATCH (n:NewsroomProjectionNode {
  generation_id: $generation_id,
  canonical_id: $canonical_id
})
SET n.first_ledger_seq = $first_ledger_seq,
    n.first_source_event_id = $first_source_event_id,
    n.first_source_event_digest = $first_source_event_digest
RETURN properties(n) AS properties
"""

_MERGE_RELATION_IDENTITY_QUERY = """
MERGE (i:NewsroomProjectionRelationIdentity {
  generation_id: $generation_id,
  relation_key: $relation_key
})
ON CREATE SET i = $properties
RETURN properties(i) AS properties
"""

_RELATION_QUERY_TEMPLATE = """
MATCH (source:NewsroomProjectionNode {
  generation_id: $generation_id,
  canonical_id: $source_canonical_id
})
MATCH (target:NewsroomProjectionNode {
  generation_id: $generation_id,
  canonical_id: $target_canonical_id
})
MERGE (source)-[r:%s {
  generation_id: $generation_id,
  relation_key: $relation_key
}]->(target)
ON CREATE SET r = $properties
RETURN properties(r) AS properties
"""

_RELATION_QUERIES = {
    relation_type: _RELATION_QUERY_TEMPLATE % relation_type.value
    for relation_type in ProjectionRelationType
}

_READ_NODES_QUERY = """
MATCH (n:NewsroomProjectionNode {generation_id: $generation_id})
WHERE n.canonical_id IN $canonical_ids
  AND n.first_ledger_seq <= $maximum_ledger_seq
RETURN properties(n) AS properties
ORDER BY n.canonical_id
LIMIT $limit
"""

_READ_RELATIONS_QUERY = """
MATCH (source:NewsroomProjectionNode {generation_id: $generation_id})
      -[r]->
      (target:NewsroomProjectionNode {generation_id: $generation_id})
WHERE (source.canonical_id IN $canonical_ids OR target.canonical_id IN $canonical_ids)
  AND r.ledger_seq <= $maximum_ledger_seq
RETURN properties(source) AS source_properties,
       type(r) AS relation_type,
       properties(r) AS relation_properties,
       properties(target) AS target_properties
ORDER BY r.ledger_seq, r.relation_key
LIMIT $limit
"""

_CLEANUP_GENERATION_QUERY = """
MATCH (value)
WHERE value.generation_id = $generation_id
  AND (value:NewsroomProjectionNode
       OR value:NewsroomProjectionDelivery
       OR value:NewsroomProjectionRelationIdentity)
DETACH DELETE value
RETURN count(value) AS deleted_count
"""


_NODE_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "canonical_id",
        "entity_type",
        "identity_source",
        "identity_reference_digest",
        "family_id",
        "family_definition_version",
        "projector_version",
        "ontology_contract_digest",
        "mapping_contract_digest",
        "first_ledger_seq",
        "first_source_event_id",
        "first_source_event_digest",
    }
)

_RELATION_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "relation_key",
        "relation_type",
        "source_canonical_id",
        "target_canonical_id",
        "ledger_seq",
        "source_event_id",
        "source_event_type",
        "source_event_digest",
        "aggregate_type",
        "aggregate_id",
        "aggregate_version",
        "payload_id",
        "payload_digest",
        "object_admission_id",
        "principal_id",
        "trust_scope",
        "security_scope",
        "retention_scope",
        "recorded_at",
    }
)

_RELATION_IDENTITY_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "relation_key",
        "relation_type",
        "source_canonical_id",
        "target_canonical_id",
        "ledger_seq",
        "source_event_id",
        "source_event_digest",
    }
)

_DELIVERY_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "ledger_seq",
        "source_event_id",
        "source_event_type",
        "source_event_digest",
        "family_id",
        "family_definition_version",
        "projector_version",
        "ontology_contract_digest",
        "mapping_contract_digest",
        "batch_digest",
    }
)


class _Neo4jAdapter:
    """Private fixed-query adapter. It is never returned by a public facade."""

    __slots__ = ("_driver", "_config", "_driver_version", "_closed")

    def __init__(self, *, driver: Any, config: Neo4jProjectorConfig, driver_version: str) -> None:
        self._driver = driver
        self._config = config
        self._driver_version = driver_version
        self._closed = False

    def verify_compatibility(self) -> Neo4jCompatibility:
        self._require_open()
        try:
            self._driver.verify_connectivity()
            with self._driver.session(database=self._config.database) as session:
                record = session.execute_read(
                    lambda transaction: transaction.run(_COMPONENT_QUERY).single()
                )
        except Exception as exc:
            raise Neo4jConnectionError(
                "Neo4j authenticated compatibility check failed"
            ) from None
        if record is None:
            raise Neo4jCompatibilityError("Neo4j service did not identify its component")
        try:
            server_version = str(record["version"])
            edition = str(record["edition"]).lower()
        except Exception:
            raise Neo4jCompatibilityError("Neo4j service returned malformed compatibility metadata") from None
        compatibility = Neo4jCompatibility(
            server_version=server_version,
            edition=edition,
            driver_version=self._driver_version,
        )
        if compatibility.server_version != NEO4J_B2_SERVER_VERSION:
            raise Neo4jCompatibilityError("Neo4j server is not the exact B2 qualification target")
        if compatibility.edition != "community":
            raise Neo4jCompatibilityError("Neo4j edition is not the exact Community qualification target")
        if compatibility.driver_version != NEO4J_B2_DRIVER_VERSION:
            raise Neo4jCompatibilityError("Neo4j driver is not the exact B2 qualification target")
        return compatibility

    def bootstrap_schema(self) -> None:
        self._require_open()
        try:
            with self._driver.session(database=self._config.database) as session:
                for query in _SCHEMA_QUERIES:
                    session.execute_write(
                        lambda transaction, statement=query: transaction.run(statement).consume()
                    )
        except Exception:
            raise Neo4jWriteError("Neo4j structural schema bootstrap failed") from None

    def apply(self, batch: StructuralBatch) -> Neo4jApplyResult:
        self._require_open()
        if not isinstance(batch, StructuralBatch):
            raise TypeError("Neo4j structural apply requires a typed batch")
        try:
            with self._driver.session(database=self._config.database) as session:
                outcome = session.execute_write(self._apply_transaction, batch)
        except Neo4jIdentityConflict:
            raise
        except Exception:
            raise Neo4jWriteError("Neo4j structural transaction failed") from None
        return Neo4jApplyResult(
            outcome=outcome,
            generation_id=batch.generation_id,
            ledger_seq=batch.ledger_seq,
            source_event_id=batch.source_event_id,
            source_event_digest=batch.source_event_digest,
            batch_digest=batch.batch_digest,
        )

    def read(
        self,
        *,
        generation_id: str,
        canonical_ids: tuple[str, ...],
        maximum_ledger_seq: int,
        limit: int,
    ) -> Neo4jStructuralRead:
        self._require_open()
        parameters = {
            "generation_id": generation_id,
            "canonical_ids": list(canonical_ids),
            "maximum_ledger_seq": maximum_ledger_seq,
            "limit": limit,
        }
        try:
            with self._driver.session(database=self._config.database) as session:
                node_rows = session.execute_read(
                    lambda transaction: list(
                        transaction.run(_READ_NODES_QUERY, parameters)
                    )
                )
                relation_rows = session.execute_read(
                    lambda transaction: list(
                        transaction.run(_READ_RELATIONS_QUERY, parameters)
                    )
                )
            nodes: dict[str, StructuralGraphNodeView] = {}
            for row in node_rows:
                node = _node_view(_record_mapping(row, "properties"))
                nodes[node.canonical_id] = node
            relations: list[StructuralGraphRelationView] = []
            for row in relation_rows:
                source = _node_view(_record_mapping(row, "source_properties"))
                target = _node_view(_record_mapping(row, "target_properties"))
                nodes[source.canonical_id] = source
                nodes[target.canonical_id] = target
                relation_type = ProjectionRelationType(str(row["relation_type"]))
                relation = _relation_view(
                    _record_mapping(row, "relation_properties"),
                    relation_type=relation_type,
                )
                relations.append(relation)
        except (Neo4jReadError, ValueError):
            raise Neo4jReadError("Neo4j returned malformed structural projection data") from None
        except Exception:
            raise Neo4jReadError("Neo4j structural read failed") from None
        return Neo4jStructuralRead(
            nodes=tuple(nodes[key] for key in sorted(nodes)),
            relations=tuple(relations),
        )

    def cleanup_generation(self, generation_id: str) -> int:
        """Private deterministic cleanup for disposable development/CI state."""

        self._require_open()
        try:
            with self._driver.session(database=self._config.database) as session:
                record = session.execute_write(
                    lambda transaction: transaction.run(
                        _CLEANUP_GENERATION_QUERY,
                        {"generation_id": generation_id},
                    ).single()
                )
            return 0 if record is None else int(record["deleted_count"])
        except Exception:
            raise Neo4jWriteError("Neo4j generation cleanup failed") from None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._driver.close()

    def _require_open(self) -> None:
        if self._closed:
            raise Neo4jConnectionError("Neo4j projector adapter is closed")

    @staticmethod
    def _apply_transaction(transaction: Any, batch: StructuralBatch) -> Neo4jApplyOutcome:
        delivery_properties = _delivery_properties(batch)
        existing_delivery = transaction.run(
            _FIND_DELIVERY_QUERY,
            {
                "generation_id": str(batch.generation_id),
                "ledger_seq": batch.ledger_seq,
            },
        ).single()
        if existing_delivery is not None:
            _require_exact_properties(
                _record_mapping(existing_delivery, "properties"),
                delivery_properties,
                allowed_keys=_DELIVERY_PROPERTY_KEYS,
                identity="Neo4j delivery marker",
            )
            return Neo4jApplyOutcome.DUPLICATE

        node_by_id = {item.canonical_id: item for item in batch.nodes}
        for canonical_id in sorted(node_by_id):
            node = node_by_id[canonical_id]
            expected = _node_properties(batch, node)
            record = transaction.run(
                _MERGE_NODE_QUERY,
                {
                    "generation_id": str(batch.generation_id),
                    "canonical_id": node.canonical_id,
                    "properties": expected,
                },
            ).single()
            if record is None:
                raise Neo4jIdentityConflict("Neo4j node upsert returned no exact state")
            current = _record_mapping(record, "properties")
            _require_node_identity(current, expected)
            _require_node_properties(current)
            current_first = int(current["first_ledger_seq"])
            if node.first_ledger_seq == current_first:
                _require_same_sequence_node_provenance(current, expected)
            elif node.first_ledger_seq < current_first:
                updated = transaction.run(
                    _UPDATE_NODE_FIRST_PROVENANCE_QUERY,
                    {
                        "generation_id": str(batch.generation_id),
                        "canonical_id": node.canonical_id,
                        "first_ledger_seq": node.first_ledger_seq,
                        "first_source_event_id": node.first_source_event_id,
                        "first_source_event_digest": node.first_source_event_digest,
                    },
                ).single()
                if updated is None:
                    raise Neo4jIdentityConflict("Neo4j node provenance update returned no exact state")
                current = _record_mapping(updated, "properties")
                _require_node_properties(current)
                _require_same_sequence_node_provenance(current, expected)

        for relation in sorted(batch.relations, key=lambda value: value.relation_key):
            identity_properties = _relation_identity_properties(batch, relation)
            identity_record = transaction.run(
                _MERGE_RELATION_IDENTITY_QUERY,
                {
                    "generation_id": str(batch.generation_id),
                    "relation_key": relation.relation_key,
                    "properties": identity_properties,
                },
            ).single()
            if identity_record is None:
                raise Neo4jIdentityConflict("Neo4j relation identity returned no exact state")
            _require_exact_properties(
                _record_mapping(identity_record, "properties"),
                identity_properties,
                allowed_keys=_RELATION_IDENTITY_PROPERTY_KEYS,
                identity="Neo4j relation identity",
            )
            relation_properties = _relation_properties(batch, relation)
            relation_record = transaction.run(
                _RELATION_QUERIES[relation.relation_type],
                {
                    "generation_id": str(batch.generation_id),
                    "source_canonical_id": relation.source_canonical_id,
                    "target_canonical_id": relation.target_canonical_id,
                    "relation_key": relation.relation_key,
                    "properties": relation_properties,
                },
            ).single()
            if relation_record is None:
                raise Neo4jIdentityConflict("Neo4j relation endpoints are absent")
            _require_exact_properties(
                _record_mapping(relation_record, "properties"),
                relation_properties,
                allowed_keys=_RELATION_PROPERTY_KEYS,
                identity="Neo4j structural relation",
            )

        delivery_record = transaction.run(
            _CREATE_DELIVERY_QUERY,
            {"properties": delivery_properties},
        ).single()
        if delivery_record is None:
            raise Neo4jIdentityConflict("Neo4j delivery marker was not created")
        _require_exact_properties(
            _record_mapping(delivery_record, "properties"),
            delivery_properties,
            allowed_keys=_DELIVERY_PROPERTY_KEYS,
            identity="Neo4j delivery marker",
        )
        return Neo4jApplyOutcome.APPLIED


def _open_neo4j_adapter(config: Neo4jProjectorConfig) -> _Neo4jAdapter:
    """Open the official driver only inside the private adapter module."""

    try:
        import neo4j
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            config.uri,
            auth=(config.username, config.password),
        )
    except Exception:
        raise Neo4jConnectionError("Neo4j projector driver creation failed") from None
    return _Neo4jAdapter(
        driver=driver,
        config=config,
        driver_version=str(neo4j.__version__),
    )


def _node_properties(batch: StructuralBatch, node: Any) -> dict[str, object]:
    return {
        "generation_id": str(batch.generation_id),
        "canonical_id": node.canonical_id,
        "entity_type": node.node_type.value,
        "identity_source": node.identity_source,
        "identity_reference_digest": node.identity_reference_digest,
        "family_id": batch.family_id,
        "family_definition_version": batch.family_definition_version,
        "projector_version": batch.projector_version,
        "ontology_contract_digest": batch.ontology_contract_digest,
        "mapping_contract_digest": batch.mapping_contract_digest,
        "first_ledger_seq": node.first_ledger_seq,
        "first_source_event_id": node.first_source_event_id,
        "first_source_event_digest": node.first_source_event_digest,
    }


def _relation_identity_properties(batch: StructuralBatch, relation: Any) -> dict[str, object]:
    return {
        "generation_id": str(batch.generation_id),
        "relation_key": relation.relation_key,
        "relation_type": relation.relation_type.value,
        "source_canonical_id": relation.source_canonical_id,
        "target_canonical_id": relation.target_canonical_id,
        "ledger_seq": relation.ledger_seq,
        "source_event_id": relation.source_event_id,
        "source_event_digest": relation.source_event_digest,
    }


def _relation_properties(batch: StructuralBatch, relation: Any) -> dict[str, object]:
    return {
        **_relation_identity_properties(batch, relation),
        "source_event_type": relation.source_event_type,
        "aggregate_type": relation.aggregate_type,
        "aggregate_id": relation.aggregate_id,
        "aggregate_version": relation.aggregate_version,
        "payload_id": relation.payload_id,
        "payload_digest": relation.payload_digest,
        "object_admission_id": relation.object_admission_id or "",
        "principal_id": relation.principal_id,
        "trust_scope": relation.trust_scope.value,
        "security_scope": relation.security_scope,
        "retention_scope": relation.retention_scope,
        "recorded_at": relation.recorded_at.to_text(),
    }


def _delivery_properties(batch: StructuralBatch) -> dict[str, object]:
    return {
        "generation_id": str(batch.generation_id),
        "ledger_seq": batch.ledger_seq,
        "source_event_id": batch.source_event_id,
        "source_event_type": batch.source_event_type,
        "source_event_digest": batch.source_event_digest,
        "family_id": batch.family_id,
        "family_definition_version": batch.family_definition_version,
        "projector_version": batch.projector_version,
        "ontology_contract_digest": batch.ontology_contract_digest,
        "mapping_contract_digest": batch.mapping_contract_digest,
        "batch_digest": batch.batch_digest,
    }


def _record_mapping(record: Any, key: str) -> Mapping[str, object]:
    try:
        value = record[key]
    except Exception:
        raise Neo4jReadError("Neo4j record is missing fixed projection properties") from None
    if not isinstance(value, Mapping):
        try:
            value = dict(value)
        except Exception:
            raise Neo4jReadError("Neo4j projection properties are malformed") from None
    return dict(value)


def _require_exact_properties(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
    *,
    allowed_keys: frozenset[str],
    identity: str,
) -> None:
    if set(actual) != set(allowed_keys) or dict(actual) != dict(expected):
        raise Neo4jIdentityConflict(f"{identity} belongs to another exact projection state")


def _require_node_identity(actual: Mapping[str, object], expected: Mapping[str, object]) -> None:
    if set(actual) != set(_NODE_PROPERTY_KEYS):
        raise Neo4jIdentityConflict("Neo4j node contains properties outside the fixed contract")
    stable_keys = _NODE_PROPERTY_KEYS - {
        "first_ledger_seq",
        "first_source_event_id",
        "first_source_event_digest",
    }
    if any(actual.get(key) != expected.get(key) for key in stable_keys):
        raise Neo4jIdentityConflict("Neo4j canonical node belongs to another exact identity")


def _require_same_sequence_node_provenance(
    actual: Mapping[str, object], expected: Mapping[str, object]
) -> None:
    provenance_keys = {
        "first_ledger_seq",
        "first_source_event_id",
        "first_source_event_digest",
    }
    if any(actual.get(key) != expected.get(key) for key in provenance_keys):
        raise Neo4jIdentityConflict(
            "Neo4j canonical node has conflicting provenance at the same sequence"
        )


def _require_node_properties(actual: Mapping[str, object]) -> None:
    if set(actual) != set(_NODE_PROPERTY_KEYS):
        raise Neo4jIdentityConflict("Neo4j node contains properties outside the fixed contract")
    try:
        ProjectionNodeType(str(actual["entity_type"]))
        int(actual["first_ledger_seq"])
    except Exception:
        raise Neo4jIdentityConflict("Neo4j node contains malformed fixed properties") from None


def _node_view(properties: Mapping[str, object]) -> StructuralGraphNodeView:
    if set(properties) != set(_NODE_PROPERTY_KEYS):
        raise Neo4jReadError("Neo4j node properties do not match the fixed contract")
    return StructuralGraphNodeView(
        canonical_id=str(properties["canonical_id"]),
        node_type=ProjectionNodeType(str(properties["entity_type"])),
        identity_source=str(properties["identity_source"]),
        identity_reference_digest=str(properties["identity_reference_digest"]),
        first_ledger_seq=int(properties["first_ledger_seq"]),
        first_source_event_id=str(properties["first_source_event_id"]),
        first_source_event_digest=str(properties["first_source_event_digest"]),
    )


def _relation_view(
    properties: Mapping[str, object],
    *,
    relation_type: ProjectionRelationType,
) -> StructuralGraphRelationView:
    if set(properties) != set(_RELATION_PROPERTY_KEYS):
        raise Neo4jReadError("Neo4j relation properties do not match the fixed contract")
    if str(properties["relation_type"]) != relation_type.value:
        raise Neo4jReadError("Neo4j relation type conflicts with retained properties")
    return StructuralGraphRelationView(
        relation_key=str(properties["relation_key"]),
        relation_type=relation_type,
        source_canonical_id=str(properties["source_canonical_id"]),
        target_canonical_id=str(properties["target_canonical_id"]),
        ledger_seq=int(properties["ledger_seq"]),
        source_event_id=str(properties["source_event_id"]),
        source_event_type=str(properties["source_event_type"]),
        source_event_digest=str(properties["source_event_digest"]),
        aggregate_type=str(properties["aggregate_type"]),
        aggregate_id=str(properties["aggregate_id"]),
        aggregate_version=int(properties["aggregate_version"]),
        payload_id=str(properties["payload_id"]),
        payload_digest=str(properties["payload_digest"]),
        object_admission_id=(
            None
            if properties["object_admission_id"] == ""
            else str(properties["object_admission_id"])
        ),
        principal_id=str(properties["principal_id"]),
        trust_scope=TrustScope(str(properties["trust_scope"])),
        security_scope=str(properties["security_scope"]),
        retention_scope=str(properties["retention_scope"]),
        recorded_at=UtcTimestamp.parse(str(properties["recorded_at"])),
    )


__all__ = ["_Neo4jAdapter", "_open_neo4j_adapter"]
