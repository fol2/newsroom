from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.projection.complete import (
    CompleteProjectionProfile,
    FullTextIndexContract,
    VectorIndexContract,
)
from newsroom.projection.fixture_v2_projection import IntegratedFixtureV2Projection
from newsroom.projection.models import ProjectionContractError

from ._adapter import _Neo4jAdapter, _open_neo4j_driver
from ._complete_state import (
    _ADMITTED_ENDPOINT_LABEL,
    _ADMITTED_RELATION_IDENTITY_LABEL,
    _COMPLETE_DELIVERY_LABEL,
    _COMPLETE_DOCUMENT_BASE_LABEL,
    _complete_state_digest_from_parts,
    _delivery_from_properties,
    _delivery_properties,
    _document_from_properties,
    _document_properties,
    _endpoint_from_properties,
    _endpoint_properties,
    _relation_from_properties,
    _relation_identity_from_properties,
    _relation_identity_properties,
    _relation_properties,
)
from .complete_models import (
    CompleteDerivativeType,
    CompleteGenerationNames,
    CompleteProjectionApplyResult,
    CompleteProjectionBatch,
    CompleteProjectionIdentity,
    CompleteProjectionQualification,
    CompleteQualificationResult,
    CompleteQueryHit,
    CompleteQueryKind,
    Neo4jIndexState,
    Neo4jIndexType,
    complete_generation_names,
)
from .complete_state import expected_complete_projection_state
from .models import (
    Neo4jApplyOutcome,
    Neo4jConfigurationError,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jReadError,
    Neo4jWriteError,
)


_COMPLETE_SCHEMA_QUERIES = (
    f"""
    CREATE CONSTRAINT newsroom_complete_document_identity IF NOT EXISTS
    FOR (d:{_COMPLETE_DOCUMENT_BASE_LABEL})
    REQUIRE (d.generation_id, d.passage_id) IS UNIQUE
    """,
    f"""
    CREATE CONSTRAINT newsroom_complete_delivery_identity IF NOT EXISTS
    FOR (d:{_COMPLETE_DELIVERY_LABEL})
    REQUIRE (d.generation_id, d.ledger_seq) IS UNIQUE
    """,
    f"""
    CREATE CONSTRAINT newsroom_admitted_endpoint_identity IF NOT EXISTS
    FOR (e:{_ADMITTED_ENDPOINT_LABEL})
    REQUIRE (e.generation_id, e.record_type, e.record_id) IS UNIQUE
    """,
    f"""
    CREATE CONSTRAINT newsroom_admitted_relation_identity IF NOT EXISTS
    FOR (r:{_ADMITTED_RELATION_IDENTITY_LABEL})
    REQUIRE (r.generation_id, r.relation_key) IS UNIQUE
    """,
)

_FIND_DELIVERY_QUERY = f"""
MATCH (d:{_COMPLETE_DELIVERY_LABEL} {{
  generation_id: $generation_id,
  ledger_seq: $ledger_seq
}})
RETURN properties(d) AS properties
"""

_CREATE_DELIVERY_QUERY = f"""
CREATE (d:{_COMPLETE_DELIVERY_LABEL})
SET d = $properties
RETURN properties(d) AS properties
"""

_DELETE_DOCUMENT_QUERY = f"""
MATCH (d:{_COMPLETE_DOCUMENT_BASE_LABEL} {{
  generation_id: $generation_id,
  passage_id: $passage_id
}})
WITH collect(d) AS documents
FOREACH (value IN documents | DETACH DELETE value)
RETURN size(documents) AS deleted_count
"""

_DELETE_RELATION_QUERY_TEMPLATE = f"""
MATCH (source:{_ADMITTED_ENDPOINT_LABEL})-[relation:%s]->(target:{_ADMITTED_ENDPOINT_LABEL})
WHERE relation.generation_id = $generation_id
  AND relation.relation_key = $relation_key
WITH collect(relation) AS relations,
     collect(DISTINCT source) + collect(DISTINCT target) AS endpoints
FOREACH (value IN relations | DELETE value)
WITH size(relations) AS deleted_count, endpoints
UNWIND CASE WHEN size(endpoints)=0 THEN [null] ELSE endpoints END AS endpoint
WITH deleted_count, endpoint
WHERE endpoint IS NULL OR NOT (endpoint)--()
FOREACH (_ IN CASE WHEN endpoint IS NULL THEN [] ELSE [1] END | DELETE endpoint)
RETURN deleted_count
"""

_DELETE_RELATION_IDENTITY_QUERY = f"""
MATCH (value:{_ADMITTED_RELATION_IDENTITY_LABEL} {{
  generation_id: $generation_id,
  relation_key: $relation_key
}})
WITH collect(value) AS identities
FOREACH (item IN identities | DELETE item)
RETURN size(identities) AS deleted_count
"""

_MERGE_ENDPOINT_QUERY = f"""
MERGE (e:{_ADMITTED_ENDPOINT_LABEL} {{
  generation_id: $generation_id,
  record_type: $record_type,
  record_id: $record_id
}})
ON CREATE SET e = $properties
RETURN properties(e) AS properties
"""

_MERGE_RELATION_IDENTITY_QUERY = f"""
MERGE (value:{_ADMITTED_RELATION_IDENTITY_LABEL} {{
  generation_id: $generation_id,
  relation_key: $relation_key
}})
ON CREATE SET value = $properties
RETURN properties(value) AS properties
"""

_DOCUMENTS_STATE_QUERY = f"""
MATCH (value:{_COMPLETE_DOCUMENT_BASE_LABEL} {{generation_id: $generation_id}})
RETURN labels(value) AS labels, properties(value) AS properties
ORDER BY value.passage_id
"""

_DELIVERIES_STATE_QUERY = f"""
MATCH (value:{_COMPLETE_DELIVERY_LABEL} {{generation_id: $generation_id}})
RETURN labels(value) AS labels, properties(value) AS properties
ORDER BY value.ledger_seq
"""

_ENDPOINTS_STATE_QUERY = f"""
MATCH (value:{_ADMITTED_ENDPOINT_LABEL} {{generation_id: $generation_id}})
RETURN labels(value) AS labels, properties(value) AS properties
ORDER BY value.record_type, value.record_id
"""

_RELATION_IDENTITIES_STATE_QUERY = f"""
MATCH (value:{_ADMITTED_RELATION_IDENTITY_LABEL} {{generation_id: $generation_id}})
RETURN labels(value) AS labels, properties(value) AS properties
ORDER BY value.relation_key
"""

_COMPLETE_RELATIONSHIPS_QUERY_TEMPLATE = f"""
MATCH (source:{_ADMITTED_ENDPOINT_LABEL})-[relation:%s]->(target:{_ADMITTED_ENDPOINT_LABEL})
WHERE relation.generation_id = $generation_id
RETURN properties(source) AS source_properties,
       type(relation) AS relation_type,
       properties(relation) AS relation_properties,
       properties(target) AS target_properties
ORDER BY relation.relation_key
"""

_CLEANUP_COMPLETE_QUERY = f"""
MATCH (value)
WHERE value.generation_id = $generation_id
  AND (value:{_COMPLETE_DOCUMENT_BASE_LABEL}
       OR value:{_COMPLETE_DELIVERY_LABEL}
       OR value:{_ADMITTED_ENDPOINT_LABEL}
       OR value:{_ADMITTED_RELATION_IDENTITY_LABEL})
WITH collect(value) AS values
FOREACH (item IN values | DETACH DELETE item)
RETURN size(values) AS deleted_count
"""

_SHOW_INDEXES_QUERY = """
SHOW INDEXES
YIELD name, type, state, entityType, labelsOrTypes, properties, indexProvider, options
WHERE name IN $index_names
RETURN name, type, state, entityType, labelsOrTypes, properties, indexProvider, options
ORDER BY name
"""

_FULLTEXT_QUERY = """
CALL db.index.fulltext.queryNodes($index_name, $query, {limit: $limit})
YIELD node, score
WHERE node.generation_id = $generation_id
RETURN node.passage_id AS passage_id, score
ORDER BY score DESC, passage_id
LIMIT $limit
"""

_VECTOR_QUERY = """
CALL db.index.vector.queryNodes($index_name, $limit, $vector)
YIELD node, score
WHERE node.generation_id = $generation_id
RETURN node.passage_id AS passage_id, score
ORDER BY score DESC, passage_id
LIMIT $limit
"""

_AWAIT_INDEXES_QUERY = "CALL db.awaitIndexes($timeout_seconds)"


@dataclass(frozen=True, slots=True)
class _IndexInventory:
    index_type: Neo4jIndexType
    name: str
    state: Neo4jIndexState
    provider: str
    labels_or_types: tuple[str, ...]
    properties: tuple[str, ...]
    index_config: tuple[tuple[str, object], ...]

    @property
    def config(self) -> dict[str, object]:
        return dict(self.index_config)


class _CompleteNeo4jAdapter(_Neo4jAdapter):
    """Private complete-generation adapter with fixed, server-derived Cypher."""

    __slots__ = ("_complete_lock",)

    def __init__(
        self,
        *,
        driver: Any,
        config: Neo4jProjectorConfig,
        driver_version: str,
    ) -> None:
        super().__init__(
            driver=driver,
            config=config,
            driver_version=driver_version,
        )
        self._complete_lock = RLock()

    def bootstrap_schema(self) -> None:
        super().bootstrap_schema()
        self._require_open()
        try:
            with self._driver.session(database=self._config.database) as session:
                for query in _COMPLETE_SCHEMA_QUERIES:
                    session.execute_write(
                        lambda transaction, statement=query: transaction.run(
                            statement
                        ).consume()
                    )
        except Exception:
            raise Neo4jWriteError(
                "Neo4j complete schema bootstrap failed"
            ) from None

    def bootstrap_generation_indexes(
        self,
        identity: CompleteProjectionIdentity,
        *,
        fulltext: FullTextIndexContract,
        vector: VectorIndexContract,
        profile: CompleteProjectionProfile,
        timeout_seconds: int = 120,
    ) -> tuple[_IndexInventory, ...]:
        self._require_open()
        names = _require_generation_contracts(
            identity,
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds <= 0
            or timeout_seconds > 600
        ):
            raise ProjectionContractError(
                "complete index timeout must be between 1 and 600 seconds"
            )
        fulltext_query = _fulltext_index_create_query(names, fulltext)
        vector_query = _vector_index_create_query(names, vector)
        with self._complete_lock:
            try:
                with self._driver.session(database=self._config.database) as session:
                    session.execute_write(
                        lambda transaction: transaction.run(
                            fulltext_query
                        ).consume()
                    )
                    session.execute_write(
                        lambda transaction: transaction.run(vector_query).consume()
                    )
                    session.execute_read(
                        lambda transaction: transaction.run(
                            _AWAIT_INDEXES_QUERY,
                            {"timeout_seconds": timeout_seconds},
                        ).consume()
                    )
                    inventory = session.execute_read(
                        self._index_inventory_transaction,
                        names,
                        fulltext,
                        vector,
                    )
            except Neo4jIdentityConflict:
                raise
            except Exception:
                raise Neo4jWriteError(
                    "Neo4j complete generation index bootstrap failed"
                ) from None
        return inventory

    def apply_complete(
        self,
        batch: CompleteProjectionBatch,
        *,
        fulltext: FullTextIndexContract,
        vector: VectorIndexContract,
        profile: CompleteProjectionProfile,
    ) -> CompleteProjectionApplyResult:
        self._require_open()
        if not isinstance(batch, CompleteProjectionBatch):
            raise TypeError("complete projection apply requires a typed batch")
        names = _require_generation_contracts(
            batch.identity,
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        if batch.structural_batch is not None:
            super().apply(batch.structural_batch)
        with self._complete_lock:
            try:
                with self._driver.session(database=self._config.database) as session:
                    outcome, affected = session.execute_write(
                        self._apply_complete_transaction,
                        batch,
                        names,
                    )
            except Neo4jIdentityConflict:
                raise
            except Exception:
                raise Neo4jWriteError(
                    "Neo4j complete projection transaction failed"
                ) from None
        return CompleteProjectionApplyResult(
            outcome=outcome,
            identity=batch.identity,
            ledger_seq=batch.ledger_seq,
            source_event_id=batch.source_event_id,
            source_event_digest=batch.source_event_digest,
            batch_digest=batch.batch_digest,
            affected_record_count=affected,
        )

    def reconcile_complete_generation(
        self,
        *,
        identity: CompleteProjectionIdentity,
        checkpoint_ledger_seq: int,
        expected_batches: tuple[CompleteProjectionBatch, ...],
        fulltext: FullTextIndexContract,
        vector: VectorIndexContract,
        profile: CompleteProjectionProfile,
    ) -> str:
        self._require_open()
        names = _require_generation_contracts(
            identity,
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        expected = expected_complete_projection_state(
            identity,
            checkpoint_ledger_seq,
            expected_batches,
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        structural_batches = tuple(
            batch.structural_batch
            for batch in expected_batches
            if batch.structural_batch is not None
        )
        structural_digest = super().reconcile_generation(
            generation_id=str(identity.generation_id),
            expected_batches=structural_batches,
        )
        if structural_digest != expected.structural_state_digest:
            raise Neo4jIdentityConflict(
                "complete structural state differs from retained authority"
            )
        with self._complete_lock:
            try:
                with self._driver.session(database=self._config.database) as session:
                    records = session.execute_read(
                        self._complete_state_transaction,
                        identity,
                        names,
                        fulltext,
                        vector,
                    )
                actual_digest = self._actual_complete_state_digest(
                    identity=identity,
                    checkpoint_ledger_seq=checkpoint_ledger_seq,
                    structural_state_digest=structural_digest,
                    names=names,
                    fulltext=fulltext,
                    vector=vector,
                    records=records,
                )
            except Neo4jIdentityConflict:
                raise
            except Exception:
                raise Neo4jReadError(
                    "Neo4j complete generation reconciliation failed"
                ) from None
        if actual_digest != expected.state_digest:
            raise Neo4jIdentityConflict(
                "Neo4j complete generation differs from retained authority"
            )
        return actual_digest

    def qualify_complete_generation(
        self,
        *,
        identity: CompleteProjectionIdentity,
        checkpoint_ledger_seq: int,
        expected_batches: tuple[CompleteProjectionBatch, ...],
        fixture: IntegratedFixtureV2Projection,
        profile: CompleteProjectionProfile,
        recorded_at: UtcTimestamp,
    ) -> CompleteProjectionQualification:
        if not isinstance(fixture, IntegratedFixtureV2Projection):
            raise TypeError("complete qualification fixture must be typed")
        if not isinstance(recorded_at, UtcTimestamp):
            raise TypeError("complete qualification time must be typed")
        fulltext = fixture.fulltext_contract
        vector = fixture.vector_contract
        names = _require_generation_contracts(
            identity,
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        state_digest = self.reconcile_complete_generation(
            identity=identity,
            checkpoint_ledger_seq=checkpoint_ledger_seq,
            expected_batches=expected_batches,
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        expected_state = expected_complete_projection_state(
            identity,
            checkpoint_ledger_seq,
            expected_batches,
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        active_ids = {item.passage_id for item in expected_state.documents}
        if active_ids != set(fixture.expected_active_passage_ids):
            raise Neo4jIdentityConflict(
                "complete qualification active document set differs from fixture"
            )
        fulltext_hits: list[CompleteQueryHit] = []
        vector_hits: list[CompleteQueryHit] = []
        try:
            with self._driver.session(database=self._config.database) as session:
                for query in fixture.fulltext_queries:
                    rows = session.execute_read(
                        lambda transaction, current=query: list(
                            transaction.run(
                                _FULLTEXT_QUERY,
                                {
                                    "index_name": names.fulltext_index_name,
                                    "query": current.query,
                                    "generation_id": str(identity.generation_id),
                                    "limit": 8,
                                },
                            )
                        )
                    )
                    hits = _query_hits(
                        rows,
                        query_id=query.query_id,
                        query_kind=CompleteQueryKind.FULL_TEXT,
                    )
                    if (
                        not hits
                        or hits[0].passage_id
                        != query.expected_first_passage_id
                    ):
                        raise Neo4jIdentityConflict(
                            "Neo4j full-text qualification result differs from fixture"
                        )
                    fulltext_hits.extend(hits)
                documents = fixture.document_by_id
                for query in fixture.vector_queries:
                    source = documents[query.passage_id]
                    query_vector = vector.vector_from_components(source.components)
                    rows = session.execute_read(
                        lambda transaction, current=query, values=query_vector: list(
                            transaction.run(
                                _VECTOR_QUERY,
                                {
                                    "index_name": names.vector_index_name,
                                    "vector": list(values),
                                    "generation_id": str(identity.generation_id),
                                    "limit": 8,
                                },
                            )
                        )
                    )
                    hits = _query_hits(
                        rows,
                        query_id=query.query_id,
                        query_kind=CompleteQueryKind.VECTOR,
                    )
                    prefix = tuple(
                        item.passage_id
                        for item in hits[: len(query.expected_active_prefix)]
                    )
                    if prefix != query.expected_active_prefix:
                        raise Neo4jIdentityConflict(
                            "Neo4j vector qualification result differs from fixture"
                        )
                    vector_hits.extend(hits)
        except Neo4jIdentityConflict:
            raise
        except Exception:
            raise Neo4jReadError(
                "Neo4j complete qualification query failed"
            ) from None
        tombstoned = set(fixture.expected_tombstoned_passage_ids)
        if tombstoned & {
            hit.passage_id for hit in (*fulltext_hits, *vector_hits)
        }:
            raise Neo4jIdentityConflict(
                "tombstoned fixture material returned from complete indexes"
            )
        return CompleteProjectionQualification(
            identity=identity,
            checkpoint_ledger_seq=checkpoint_ledger_seq,
            projection_state_digest=state_digest,
            result=CompleteQualificationResult.PASSED,
            fulltext_hits=tuple(fulltext_hits),
            vector_hits=tuple(vector_hits),
            expected_tombstoned_passage_ids=tuple(
                sorted(fixture.expected_tombstoned_passage_ids)
            ),
            recorded_at=recorded_at,
        )

    def cleanup_complete_generation(
        self,
        identity: CompleteProjectionIdentity,
        *,
        fulltext: FullTextIndexContract,
        vector: VectorIndexContract,
    ) -> int:
        self._require_open()
        names = complete_generation_names(identity, fulltext, vector)
        with self._complete_lock:
            try:
                with self._driver.session(database=self._config.database) as session:
                    session.execute_write(
                        lambda transaction: transaction.run(
                            f"DROP INDEX `{names.fulltext_index_name}` IF EXISTS"
                        ).consume()
                    )
                    session.execute_write(
                        lambda transaction: transaction.run(
                            f"DROP INDEX `{names.vector_index_name}` IF EXISTS"
                        ).consume()
                    )
                    record = session.execute_write(
                        lambda transaction: transaction.run(
                            _CLEANUP_COMPLETE_QUERY,
                            {"generation_id": str(identity.generation_id)},
                        ).single()
                    )
                    complete_deleted = (
                        0 if record is None else int(record["deleted_count"])
                    )
            except Exception:
                raise Neo4jWriteError(
                    "Neo4j complete generation cleanup failed"
                ) from None
            structural_deleted = super().cleanup_generation(
                str(identity.generation_id)
            )
        return complete_deleted + structural_deleted

    @staticmethod
    def _apply_complete_transaction(
        transaction: Any,
        batch: CompleteProjectionBatch,
        names: CompleteGenerationNames,
    ) -> tuple[Neo4jApplyOutcome, int]:
        expected_delivery = _delivery_properties(batch)
        existing = transaction.run(
            _FIND_DELIVERY_QUERY,
            {
                "generation_id": str(batch.identity.generation_id),
                "ledger_seq": batch.ledger_seq,
            },
        ).single()
        if existing is not None:
            _require_exact(
                _record_mapping(existing, "properties"),
                expected_delivery,
                "complete delivery marker",
            )
            return Neo4jApplyOutcome.DUPLICATE, 0

        affected = 0
        relation_query = _DELETE_RELATION_QUERY_TEMPLATE % names.admitted_relation_type
        for removal in batch.removals:
            if removal.derivative_type in {
                CompleteDerivativeType.FULL_TEXT,
                CompleteDerivativeType.VECTOR,
            }:
                record = transaction.run(
                    _DELETE_DOCUMENT_QUERY,
                    {
                        "generation_id": str(batch.identity.generation_id),
                        "passage_id": removal.stable_key,
                    },
                ).single()
                affected += 0 if record is None else int(record["deleted_count"])
            elif removal.derivative_type is CompleteDerivativeType.ADMITTED_RELATION:
                record = transaction.run(
                    relation_query,
                    {
                        "generation_id": str(batch.identity.generation_id),
                        "relation_key": removal.stable_key,
                    },
                ).single()
                affected += 0 if record is None else int(record["deleted_count"])
                identity_record = transaction.run(
                    _DELETE_RELATION_IDENTITY_QUERY,
                    {
                        "generation_id": str(batch.identity.generation_id),
                        "relation_key": removal.stable_key,
                    },
                ).single()
                affected += (
                    0
                    if identity_record is None
                    else int(identity_record["deleted_count"])
                )

        merge_document_query = _merge_document_query(names)
        for document in batch.documents:
            expected = _document_properties(document)
            record = transaction.run(
                merge_document_query,
                {
                    "generation_id": str(batch.identity.generation_id),
                    "passage_id": document.passage_id,
                    "properties": expected,
                },
            ).single()
            if record is None:
                raise Neo4jIdentityConflict(
                    "Neo4j complete document upsert returned no state"
                )
            _require_exact(
                _record_mapping(record, "properties"),
                expected,
                "complete document",
            )
            affected += 1

        merge_relation_query = _merge_relation_query(names)
        for relation in batch.relations:
            for endpoint in (relation.subject, relation.object):
                expected_endpoint = _endpoint_properties(
                    relation.identity,
                    endpoint,
                )
                record = transaction.run(
                    _MERGE_ENDPOINT_QUERY,
                    {
                        **expected_endpoint,
                        "properties": expected_endpoint,
                    },
                ).single()
                if record is None:
                    raise Neo4jIdentityConflict(
                        "Neo4j admitted endpoint upsert returned no state"
                    )
                _require_exact(
                    _record_mapping(record, "properties"),
                    expected_endpoint,
                    "admitted relation endpoint",
                )
            expected_identity = _relation_identity_properties(relation)
            identity_record = transaction.run(
                _MERGE_RELATION_IDENTITY_QUERY,
                {
                    "generation_id": str(batch.identity.generation_id),
                    "relation_key": relation.relation_key,
                    "properties": expected_identity,
                },
            ).single()
            if identity_record is None:
                raise Neo4jIdentityConflict(
                    "Neo4j admitted relation identity returned no state"
                )
            _require_exact(
                _record_mapping(identity_record, "properties"),
                expected_identity,
                "admitted relation identity",
            )
            expected_relation = _relation_properties(relation)
            relation_record = transaction.run(
                merge_relation_query,
                {
                    "generation_id": str(batch.identity.generation_id),
                    "subject_record_type": relation.subject.record_type.value,
                    "subject_record_id": relation.subject.record_id,
                    "object_record_type": relation.object.record_type.value,
                    "object_record_id": relation.object.record_id,
                    "relation_key": relation.relation_key,
                    "properties": expected_relation,
                },
            ).single()
            if relation_record is None:
                raise Neo4jIdentityConflict(
                    "Neo4j admitted relation endpoints are absent"
                )
            _require_exact(
                _record_mapping(relation_record, "properties"),
                expected_relation,
                "admitted relation",
            )
            affected += 1

        delivery = transaction.run(
            _CREATE_DELIVERY_QUERY,
            {"properties": expected_delivery},
        ).single()
        if delivery is None:
            raise Neo4jIdentityConflict(
                "Neo4j complete delivery marker was not created"
            )
        _require_exact(
            _record_mapping(delivery, "properties"),
            expected_delivery,
            "complete delivery marker",
        )
        affected += 1
        return Neo4jApplyOutcome.APPLIED, affected

    @staticmethod
    def _complete_state_transaction(
        transaction: Any,
        identity: CompleteProjectionIdentity,
        names: CompleteGenerationNames,
        fulltext: FullTextIndexContract,
        vector: VectorIndexContract,
    ) -> tuple[list[Any], list[Any], list[Any], list[Any], list[Any], tuple[_IndexInventory, ...]]:
        parameters = {"generation_id": str(identity.generation_id)}
        return (
            list(transaction.run(_DOCUMENTS_STATE_QUERY, parameters)),
            list(transaction.run(_DELIVERIES_STATE_QUERY, parameters)),
            list(transaction.run(_ENDPOINTS_STATE_QUERY, parameters)),
            list(transaction.run(_RELATION_IDENTITIES_STATE_QUERY, parameters)),
            list(
                transaction.run(
                    _COMPLETE_RELATIONSHIPS_QUERY_TEMPLATE
                    % names.admitted_relation_type,
                    parameters,
                )
            ),
            _CompleteNeo4jAdapter._index_inventory_transaction(
                transaction,
                names,
                fulltext,
                vector,
            ),
        )

    @staticmethod
    def _index_inventory_transaction(
        transaction: Any,
        names: CompleteGenerationNames,
        fulltext: FullTextIndexContract,
        vector: VectorIndexContract,
    ) -> tuple[_IndexInventory, ...]:
        rows = list(
            transaction.run(
                _SHOW_INDEXES_QUERY,
                {
                    "index_names": [
                        names.fulltext_index_name,
                        names.vector_index_name,
                    ]
                },
            )
        )
        inventory = tuple(_index_inventory(row) for row in rows)
        expected = {
            names.fulltext_index_name: (
                Neo4jIndexType.FULL_TEXT,
                fulltext.provider,
                (names.document_label,),
                (fulltext.retrieval_property,),
                {
                    "fulltext.analyzer": fulltext.analyzer.casefold(),
                    "fulltext.eventually_consistent": (
                        fulltext.eventually_consistent
                    ),
                },
            ),
            names.vector_index_name: (
                Neo4jIndexType.VECTOR,
                vector.provider,
                (names.document_label,),
                (vector.vector_property,),
                {
                    "vector.dimensions": vector.dimensions,
                    "vector.similarity_function": (
                        vector.similarity_function.value.casefold()
                    ),
                    "vector.quantization.type": (
                        vector.quantization.value.casefold()
                    ),
                },
            ),
        }
        by_name = {item.name: item for item in inventory}
        if set(by_name) != set(expected):
            raise Neo4jIdentityConflict(
                "complete generation mandatory index inventory is incomplete"
            )
        for name, (kind, provider, labels, properties, config) in expected.items():
            item = by_name[name]
            actual_config = item.config
            if (
                item.index_type is not kind
                or item.state is not Neo4jIndexState.ONLINE
                or item.provider != provider
                or item.labels_or_types != labels
                or item.properties != properties
                or any(actual_config.get(key) != value for key, value in config.items())
            ):
                raise Neo4jIdentityConflict(
                    "complete generation index differs from retained contract"
                )
        return tuple(by_name[name] for name in sorted(by_name))

    @staticmethod
    def _actual_complete_state_digest(
        *,
        identity: CompleteProjectionIdentity,
        checkpoint_ledger_seq: int,
        structural_state_digest: str,
        names: CompleteGenerationNames,
        fulltext: FullTextIndexContract,
        vector: VectorIndexContract,
        records: tuple[
            list[Any],
            list[Any],
            list[Any],
            list[Any],
            list[Any],
            tuple[_IndexInventory, ...],
        ],
    ) -> str:
        (
            document_rows,
            delivery_rows,
            endpoint_rows,
            identity_rows,
            relation_rows,
            indexes,
        ) = records
        documents = tuple(
            _document_from_properties(
                identity,
                _record_mapping(row, "properties"),
            )
            for row in document_rows
        )
        deliveries = tuple(
            _delivery_from_properties(
                identity,
                _record_mapping(row, "properties"),
            )
            for row in delivery_rows
        )
        endpoints = {
            endpoint
            for endpoint in (
                _endpoint_from_properties(
                    identity,
                    _record_mapping(row, "properties"),
                )
                for row in endpoint_rows
            )
        }
        relation_identities = {
            str(value["relation_key"]): value
            for value in (
                _relation_identity_from_properties(
                    identity,
                    _record_mapping(row, "properties"),
                )
                for row in identity_rows
            )
        }
        relations = []
        expected_endpoints = set()
        for row in relation_rows:
            if str(row["relation_type"]) != names.admitted_relation_type:
                raise Neo4jIdentityConflict(
                    "Neo4j admitted relationship type differs from fixed contract"
                )
            source = _endpoint_from_properties(
                identity,
                _record_mapping(row, "source_properties"),
            )
            target = _endpoint_from_properties(
                identity,
                _record_mapping(row, "target_properties"),
            )
            relation = _relation_from_properties(
                identity,
                _record_mapping(row, "relation_properties"),
            )
            if relation.subject != source or relation.object != target:
                raise Neo4jIdentityConflict(
                    "Neo4j admitted relation endpoints differ from properties"
                )
            retained_identity = relation_identities.pop(
                relation.relation_key,
                None,
            )
            if retained_identity is None or (
                str(retained_identity["assertion_id"])
                != str(relation.assertion_id)
                or str(retained_identity["proposal_id"])
                != str(relation.proposal_id)
                or str(retained_identity["admission_decision_id"])
                != str(relation.admission_decision_id)
                or str(retained_identity["relation_digest"])
                != relation.relation_digest
            ):
                raise Neo4jIdentityConflict(
                    "Neo4j admitted relation identity differs from relationship"
                )
            expected_endpoints.update({source, target})
            relations.append(relation)
        if relation_identities:
            raise Neo4jIdentityConflict(
                "Neo4j contains orphan admitted relation identities"
            )
        if endpoints != expected_endpoints:
            raise Neo4jIdentityConflict(
                "Neo4j admitted relation endpoint state is incomplete or orphaned"
            )
        by_type = {item.index_type: item for item in indexes}
        return _complete_state_digest_from_parts(
            identity=identity,
            checkpoint_ledger_seq=checkpoint_ledger_seq,
            structural_state_digest=structural_state_digest,
            documents=documents,
            relations=relations,
            deliveries=deliveries,
            fulltext_index_state=by_type[Neo4jIndexType.FULL_TEXT].state,
            vector_index_state=by_type[Neo4jIndexType.VECTOR].state,
            fulltext_index_provider=by_type[Neo4jIndexType.FULL_TEXT].provider,
            vector_index_provider=by_type[Neo4jIndexType.VECTOR].provider,
        )


def _require_generation_contracts(
    identity: CompleteProjectionIdentity,
    *,
    fulltext: FullTextIndexContract,
    vector: VectorIndexContract,
    profile: CompleteProjectionProfile,
) -> CompleteGenerationNames:
    if not isinstance(identity, CompleteProjectionIdentity):
        raise TypeError("complete Neo4j identity must be typed")
    if not isinstance(fulltext, FullTextIndexContract):
        raise TypeError("complete Neo4j full-text contract must be typed")
    if not isinstance(vector, VectorIndexContract):
        raise TypeError("complete Neo4j vector contract must be typed")
    vector.require_profile(profile)
    return complete_generation_names(identity, fulltext, vector)


def _fulltext_index_create_query(
    names: CompleteGenerationNames,
    contract: FullTextIndexContract,
) -> str:
    analyzer = _safe_literal_token(contract.analyzer, "full-text analyzer")
    return f"""
    CREATE FULLTEXT INDEX `{names.fulltext_index_name}` IF NOT EXISTS
    FOR (node:`{names.document_label}`)
    ON EACH [node.`{contract.retrieval_property}`]
    OPTIONS {{indexConfig: {{
      `fulltext.analyzer`: '{analyzer}',
      `fulltext.eventually_consistent`: false
    }}}}
    """


def _vector_index_create_query(
    names: CompleteGenerationNames,
    contract: VectorIndexContract,
) -> str:
    similarity = contract.similarity_function.value.lower()
    if contract.quantization.value != "NONE":
        raise ProjectionContractError(
            "Increment 2B supports only unquantized deterministic vectors"
        )
    return f"""
    CREATE VECTOR INDEX `{names.vector_index_name}` IF NOT EXISTS
    FOR (node:`{names.document_label}`)
    ON (node.`{contract.vector_property}`)
    OPTIONS {{indexConfig: {{
      `vector.dimensions`: {contract.dimensions},
      `vector.similarity_function`: '{similarity}',
      `vector.quantization.type`: 'none'
    }}}}
    """


def _merge_document_query(names: CompleteGenerationNames) -> str:
    return f"""
    MERGE (value:{_COMPLETE_DOCUMENT_BASE_LABEL}:`{names.document_label}` {{
      generation_id: $generation_id,
      passage_id: $passage_id
    }})
    ON CREATE SET value = $properties
    RETURN properties(value) AS properties
    """


def _merge_relation_query(names: CompleteGenerationNames) -> str:
    return f"""
    MATCH (source:{_ADMITTED_ENDPOINT_LABEL} {{
      generation_id: $generation_id,
      record_type: $subject_record_type,
      record_id: $subject_record_id
    }})
    MATCH (target:{_ADMITTED_ENDPOINT_LABEL} {{
      generation_id: $generation_id,
      record_type: $object_record_type,
      record_id: $object_record_id
    }})
    MERGE (source)-[relation:{names.admitted_relation_type} {{
      generation_id: $generation_id,
      relation_key: $relation_key
    }}]->(target)
    ON CREATE SET relation = $properties
    RETURN properties(relation) AS properties
    """


def _index_inventory(row: Any) -> _IndexInventory:
    try:
        name = str(row["name"])
        raw_type = str(row["type"]).upper().replace("-", "")
        index_type = (
            Neo4jIndexType.FULL_TEXT
            if raw_type == "FULLTEXT"
            else Neo4jIndexType.VECTOR
            if raw_type == "VECTOR"
            else None
        )
        if index_type is None:
            raise ValueError
        state = Neo4jIndexState(str(row["state"]).upper())
        if str(row["entityType"]).upper() != "NODE":
            raise ValueError
        labels = tuple(str(item) for item in (row["labelsOrTypes"] or []))
        properties = tuple(str(item) for item in (row["properties"] or []))
        provider = str(row["indexProvider"])
        options = dict(row["options"] or {})
        raw_config = dict(options.get("indexConfig") or {})
        index_config = tuple(
            sorted(
                (str(key), _normalize_index_config_value(str(key), value))
                for key, value in raw_config.items()
            )
        )
    except Exception:
        raise Neo4jIdentityConflict(
            "Neo4j returned malformed complete index inventory"
        ) from None
    return _IndexInventory(
        index_type=index_type,
        name=name,
        state=state,
        provider=provider,
        labels_or_types=labels,
        properties=properties,
        index_config=index_config,
    )


def _normalize_index_config_value(key: str, value: object) -> object:
    if key in {
        "fulltext.analyzer",
        "vector.similarity_function",
        "vector.quantization.type",
    }:
        if not isinstance(value, str):
            raise ValueError("index configuration text must be a string")
        return value.casefold()
    if key == "fulltext.eventually_consistent":
        if not isinstance(value, bool):
            raise ValueError("full-text consistency configuration must be boolean")
        return value
    if key == "vector.dimensions":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("vector dimensions configuration must be integer")
        return value
    return value


def _query_hits(
    rows: list[Any],
    *,
    query_id: str,
    query_kind: CompleteQueryKind,
) -> tuple[CompleteQueryHit, ...]:
    hits = []
    for rank, row in enumerate(rows, start=1):
        try:
            passage_id = str(row["passage_id"])
            score = float(row["score"])
        except Exception:
            raise Neo4jIdentityConflict(
                "Neo4j returned malformed qualification hit"
            ) from None
        hits.append(
            CompleteQueryHit(
                query_id=query_id,
                query_kind=query_kind,
                passage_id=passage_id,
                score=score,
                rank=rank,
            )
        )
    return tuple(hits)


def _record_mapping(record: Any, key: str) -> Mapping[str, object]:
    try:
        value = record[key]
    except Exception:
        raise Neo4jIdentityConflict(
            "Neo4j complete record is missing fixed properties"
        ) from None
    if value is None:
        return {}
    try:
        return dict(value)
    except Exception:
        raise Neo4jIdentityConflict(
            "Neo4j complete record properties are malformed"
        ) from None


def _require_exact(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
    identity: str,
) -> None:
    if dict(actual) != dict(expected):
        raise Neo4jIdentityConflict(
            f"Neo4j {identity} differs from retained authority"
        )


def _safe_literal_token(value: str, identity: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if not value or any(character not in allowed for character in value):
        raise Neo4jConfigurationError(
            f"{identity} is outside the fixed safe token vocabulary"
        )
    return value


def _open_complete_neo4j_adapter(
    config: Neo4jProjectorConfig,
) -> _CompleteNeo4jAdapter:
    driver, driver_version = _open_neo4j_driver(config)
    return _CompleteNeo4jAdapter(
        driver=driver,
        config=config,
        driver_version=driver_version,
    )


__all__ = [
    "_CompleteNeo4jAdapter",
    "_open_complete_neo4j_adapter",
]
