from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from newsroom.authority.canonical import digest_canonical
from newsroom.projection.ontology import ProjectionRelationType

from .models import Neo4jIdentityConflict, StructuralBatch

_STATE_CONTRACT = "newsroom-neo4j-structural-state-v1"
_NODE_LABEL = "NewsroomProjectionNode"
_DELIVERY_LABEL = "NewsroomProjectionDelivery"
_RELATION_IDENTITY_LABEL = "NewsroomProjectionRelationIdentity"

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


def _relation_identity_properties(
    batch: StructuralBatch, relation: Any
) -> dict[str, object]:
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


def _canonical_state_digest(
    generation_id: str,
    *,
    nodes: Mapping[str, Mapping[str, object]],
    relations: Mapping[str, Mapping[str, object]],
    relation_identities: Mapping[str, Mapping[str, object]],
    deliveries: Mapping[int, Mapping[str, object]],
) -> str:
    return digest_canonical(
        {
            "state_contract": _STATE_CONTRACT,
            "generation_id": generation_id,
            "nodes": [dict(nodes[key]) for key in sorted(nodes)],
            "relations": [dict(relations[key]) for key in sorted(relations)],
            "relation_identities": [
                dict(relation_identities[key])
                for key in sorted(relation_identities)
            ],
            "deliveries": [dict(deliveries[key]) for key in sorted(deliveries)],
        }
    )


def _require_exact_keys(
    value: Mapping[str, object], expected: frozenset[str], identity: str
) -> dict[str, object]:
    copied = dict(value)
    if set(copied) != set(expected):
        raise Neo4jIdentityConflict(
            f"{identity} properties differ from the fixed structural contract"
        )
    return copied


def _require_generation(
    properties: Mapping[str, object], generation_id: str, identity: str
) -> None:
    if properties.get("generation_id") != generation_id:
        raise Neo4jIdentityConflict(
            f"{identity} belongs to another generation namespace"
        )


def _apply_expected_batch(
    generation_id: str,
    batch: StructuralBatch,
    *,
    nodes: dict[str, dict[str, object]],
    relations: dict[str, dict[str, object]],
    relation_identities: dict[str, dict[str, object]],
    deliveries: dict[int, dict[str, object]],
) -> None:
    if str(batch.generation_id) != generation_id:
        raise Neo4jIdentityConflict(
            "retained structural batch belongs to another generation"
        )

    if batch.tombstoned_object_admission_ids:
        covered = set(batch.tombstoned_object_admission_ids)
        removed_keys = {
            key
            for key, properties in relations.items()
            if properties["object_admission_id"] in covered
        }
        candidate_nodes: set[str] = set()
        for key in removed_keys:
            relation = relations.pop(key)
            relation_identities.pop(key, None)
            candidate_nodes.update(
                {
                    str(relation["source_canonical_id"]),
                    str(relation["target_canonical_id"]),
                }
            )
        referenced = {
            str(properties[endpoint])
            for properties in relations.values()
            for endpoint in ("source_canonical_id", "target_canonical_id")
        }
        for canonical_id in candidate_nodes - referenced:
            nodes.pop(canonical_id, None)

    for node in batch.nodes:
        expected = _node_properties(batch, node)
        canonical_id = node.canonical_id
        current = nodes.get(canonical_id)
        if current is None:
            nodes[canonical_id] = expected
            continue
        stable_keys = _NODE_PROPERTY_KEYS - {
            "first_ledger_seq",
            "first_source_event_id",
            "first_source_event_digest",
        }
        if any(current[key] != expected[key] for key in stable_keys):
            raise Neo4jIdentityConflict(
                "retained canonical node belongs to another exact identity"
            )
        current_sequence = int(current["first_ledger_seq"])
        expected_sequence = int(expected["first_ledger_seq"])
        if expected_sequence == current_sequence:
            provenance = {
                "first_ledger_seq",
                "first_source_event_id",
                "first_source_event_digest",
            }
            if any(current[key] != expected[key] for key in provenance):
                raise Neo4jIdentityConflict(
                    "retained canonical node has conflicting first provenance"
                )
        elif expected_sequence < current_sequence:
            current.update(
                {
                    "first_ledger_seq": expected["first_ledger_seq"],
                    "first_source_event_id": expected["first_source_event_id"],
                    "first_source_event_digest": expected[
                        "first_source_event_digest"
                    ],
                }
            )

    for relation in batch.relations:
        key = relation.relation_key
        identity = _relation_identity_properties(batch, relation)
        properties = _relation_properties(batch, relation)
        existing_identity = relation_identities.get(key)
        existing_relation = relations.get(key)
        if existing_identity is not None and existing_identity != identity:
            raise Neo4jIdentityConflict(
                "retained relation identity conflicts with another state"
            )
        if existing_relation is not None and existing_relation != properties:
            raise Neo4jIdentityConflict(
                "retained structural relation conflicts with another state"
            )
        relation_identities[key] = identity
        relations[key] = properties

    delivery = _delivery_properties(batch)
    existing_delivery = deliveries.get(batch.ledger_seq)
    if existing_delivery is not None and existing_delivery != delivery:
        raise Neo4jIdentityConflict(
            "retained delivery sequence conflicts with another graph batch"
        )
    deliveries[batch.ledger_seq] = delivery


def _expected_projection_state_digest(
    generation_id: str,
    batches: Iterable[StructuralBatch],
) -> str:
    nodes: dict[str, dict[str, object]] = {}
    relations: dict[str, dict[str, object]] = {}
    relation_identities: dict[str, dict[str, object]] = {}
    deliveries: dict[int, dict[str, object]] = {}
    previous_sequence = 0
    for batch in batches:
        if not isinstance(batch, StructuralBatch):
            raise TypeError("projection reconciliation requires typed batches")
        if batch.ledger_seq <= previous_sequence:
            raise Neo4jIdentityConflict(
                "retained reconciliation batches must be strictly ordered"
            )
        previous_sequence = batch.ledger_seq
        _apply_expected_batch(
            generation_id,
            batch,
            nodes=nodes,
            relations=relations,
            relation_identities=relation_identities,
            deliveries=deliveries,
        )
    return _canonical_state_digest(
        generation_id,
        nodes=nodes,
        relations=relations,
        relation_identities=relation_identities,
        deliveries=deliveries,
    )


def _actual_projection_state_digest(
    generation_id: str,
    *,
    node_records: Iterable[tuple[Iterable[str], Mapping[str, object]]],
    relationship_records: Iterable[
        tuple[
            Iterable[str],
            Mapping[str, object],
            str,
            Mapping[str, object],
            Iterable[str],
            Mapping[str, object],
        ]
    ],
) -> str:
    nodes: dict[str, dict[str, object]] = {}
    relations: dict[str, dict[str, object]] = {}
    relation_identities: dict[str, dict[str, object]] = {}
    deliveries: dict[int, dict[str, object]] = {}

    for labels_value, raw_properties in node_records:
        labels = tuple(sorted(str(item) for item in labels_value))
        properties = dict(raw_properties)
        if labels == (_NODE_LABEL,):
            properties = _require_exact_keys(
                properties, _NODE_PROPERTY_KEYS, "Neo4j projection node"
            )
            _require_generation(properties, generation_id, "Neo4j projection node")
            key = str(properties["canonical_id"])
            target = nodes
        elif labels == (_RELATION_IDENTITY_LABEL,):
            properties = _require_exact_keys(
                properties,
                _RELATION_IDENTITY_PROPERTY_KEYS,
                "Neo4j relation identity",
            )
            _require_generation(properties, generation_id, "Neo4j relation identity")
            key = str(properties["relation_key"])
            target = relation_identities
        elif labels == (_DELIVERY_LABEL,):
            properties = _require_exact_keys(
                properties, _DELIVERY_PROPERTY_KEYS, "Neo4j delivery marker"
            )
            _require_generation(properties, generation_id, "Neo4j delivery marker")
            try:
                key = int(properties["ledger_seq"])
            except Exception:
                raise Neo4jIdentityConflict(
                    "Neo4j delivery marker sequence is malformed"
                ) from None
            target = deliveries
        else:
            raise Neo4jIdentityConflict(
                "Neo4j generation contains a node outside the fixed labels"
            )
        if key in target:
            raise Neo4jIdentityConflict(
                "Neo4j generation contains a duplicate structural identity"
            )
        target[key] = properties

    for (
        source_labels_value,
        source_raw,
        relation_type_value,
        relation_raw,
        target_labels_value,
        target_raw,
    ) in relationship_records:
        source_labels = tuple(sorted(str(item) for item in source_labels_value))
        target_labels = tuple(sorted(str(item) for item in target_labels_value))
        if source_labels != (_NODE_LABEL,) or target_labels != (_NODE_LABEL,):
            raise Neo4jIdentityConflict(
                "Neo4j generation relationship escapes the fixed node labels"
            )
        source = _require_exact_keys(
            source_raw, _NODE_PROPERTY_KEYS, "Neo4j relation source node"
        )
        target = _require_exact_keys(
            target_raw, _NODE_PROPERTY_KEYS, "Neo4j relation target node"
        )
        _require_generation(source, generation_id, "Neo4j relation source node")
        _require_generation(target, generation_id, "Neo4j relation target node")
        try:
            relation_type = ProjectionRelationType(str(relation_type_value))
        except ValueError:
            raise Neo4jIdentityConflict(
                "Neo4j generation contains a relationship outside the ontology"
            ) from None
        properties = _require_exact_keys(
            relation_raw, _RELATION_PROPERTY_KEYS, "Neo4j structural relation"
        )
        _require_generation(properties, generation_id, "Neo4j structural relation")
        if properties["relation_type"] != relation_type.value:
            raise Neo4jIdentityConflict(
                "Neo4j relationship type differs from retained properties"
            )
        if (
            properties["source_canonical_id"] != source["canonical_id"]
            or properties["target_canonical_id"] != target["canonical_id"]
        ):
            raise Neo4jIdentityConflict(
                "Neo4j relationship endpoints differ from retained properties"
            )
        relation_key = str(properties["relation_key"])
        if relation_key in relations:
            raise Neo4jIdentityConflict(
                "Neo4j generation contains a duplicate relationship identity"
            )
        relations[relation_key] = properties

        source_id = str(source["canonical_id"])
        target_id = str(target["canonical_id"])
        if nodes.get(source_id) != source or nodes.get(target_id) != target:
            raise Neo4jIdentityConflict(
                "Neo4j relationship endpoint state differs from node inventory"
            )

    return _canonical_state_digest(
        generation_id,
        nodes=nodes,
        relations=relations,
        relation_identities=relation_identities,
        deliveries=deliveries,
    )


__all__ = [
    "_DELIVERY_PROPERTY_KEYS",
    "_NODE_PROPERTY_KEYS",
    "_RELATION_IDENTITY_PROPERTY_KEYS",
    "_RELATION_PROPERTY_KEYS",
    "_actual_projection_state_digest",
    "_delivery_properties",
    "_expected_projection_state_digest",
    "_node_properties",
    "_relation_identity_properties",
    "_relation_properties",
]
