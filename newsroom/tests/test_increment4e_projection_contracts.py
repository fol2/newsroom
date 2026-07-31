from __future__ import annotations

import sqlite3
from pathlib import Path

from newsroom.authority.persistence import LedgerEventRecord
from newsroom.authority.types import TrustScope
from newsroom.increment4 import (
    INCREMENT4_ADMITTED_FAMILY_ID,
    Increment4EntityProjectionState,
    Increment4RelationProjectionState,
    build_increment4_admitted_batches,
    increment4_admitted_contract_registry,
    sorted_snapshot,
)
from newsroom.projection import ProjectionGenerationId, ProjectionNodeType, ProjectionRelationType
from newsroom.relations import EditorialRelationDecisionAction

from .editorial_relation_4c_helpers import (
    ENTITY_ID,
    ENTITY_VERSION_ID,
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    ZH_ENTITY_ID,
    ZH_ENTITY_VERSION_ID,
    open_entity_system_after_relation,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_proof


def _ledger_events(path: Path) -> tuple[LedgerEventRecord, ...]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM ledger_events ORDER BY ledger_seq").fetchall()
    finally:
        conn.close()
    return tuple(
        LedgerEventRecord(
            ledger_seq=int(row["ledger_seq"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            event_schema_version=int(row["event_schema_version"]),
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=str(row["aggregate_id"]),
            aggregate_version=int(row["aggregate_version"]),
            recorded_at=str(row["recorded_at"]),
            command_id=str(row["command_id"]),
            producer_version=str(row["producer_version"]),
            command_definition_version=str(row["command_definition_version"]),
            command_definition_digest=str(row["command_definition_digest"]),
            payload_id=str(row["payload_id"]),
            payload_mode=str(row["payload_mode"]),
            payload_schema_version=str(row["payload_schema_version"]),
            payload_schema_contract_version=str(row["payload_schema_contract_version"]),
            payload_schema_contract_digest=str(row["payload_schema_contract_digest"]),
            payload_canonicalizer_version=str(row["payload_canonicalizer_version"]),
            payload_digest=str(row["payload_digest"]),
            object_admission_id=(
                None if row["object_admission_id"] is None else str(row["object_admission_id"])
            ),
            principal_id=str(row["principal_id"]),
            authentication_context_id=str(row["authentication_context_id"]),
            authorization_request_digest=str(row["authorization_request_digest"]),
            authorization_decision_id=str(row["authorization_decision_id"]),
            correlation_id=None if row["correlation_id"] is None else str(row["correlation_id"]),
            causation_kind=None if row["causation_kind"] is None else str(row["causation_kind"]),
            causation_identifier=(
                None if row["causation_identifier"] is None else str(row["causation_identifier"])
            ),
            causation_external_system=(
                None
                if row["causation_external_system"] is None
                else str(row["causation_external_system"])
            ),
            security_scope=str(row["security_scope"]),
            retention_scope=str(row["retention_scope"]),
            trust_scope=str(row["trust_scope"]),
        )
        for row in rows
    )


def _entity_state(system, entity_id, version_id):
    projection = [
        item
        for item in system.entities.projection_events_after(
            0, limit=100, proof=extraction_proof()
        )
        if item.entity_id == entity_id and item.preferred_entity_id is not None
    ][-1]
    return Increment4EntityProjectionState(
        entity=system.entities.entity(entity_id, proof=extraction_proof()),
        version=system.entities.entity_version(version_id, proof=extraction_proof()),
        preferred=system.entities.preferred(entity_id, proof=extraction_proof()),
        aliases=tuple(
            sorted(
                system.entities.aliases(entity_id, limit=100, proof=extraction_proof()),
                key=lambda item: str(item.alias_id),
            )
        ),
        projection_event=projection,
    )


def _admitted_fixture(tmp_path: Path):
    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="increment-4e-relation-accept-v1",
            ),
            proof=extraction_proof(),
        )
        current = system.relations.current(
            RELATION_ASSERTION_ID, proof=extraction_proof()
        )
        relation_event = [
            item
            for item in system.relations.projection_events_after(
                after_ledger_seq=0, limit=100, proof=extraction_proof()
            )
            if item.assertion_id == RELATION_ASSERTION_ID and item.assertion is not None
        ][-1]
    with open_entity_system_after_relation(state) as system:
        entities = (
            _entity_state(system, ENTITY_ID, ENTITY_VERSION_ID),
            _entity_state(system, ZH_ENTITY_ID, ZH_ENTITY_VERSION_ID),
        )
    events = _ledger_events(state.entity.extraction.database)
    snapshot = sorted_snapshot(
        entities=entities,
        relations=(Increment4RelationProjectionState(current, relation_event),),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    return state, snapshot


def test_increment4_admitted_contract_is_versioned_and_closed() -> None:
    contracts = increment4_admitted_contract_registry()
    family = contracts.family(INCREMENT4_ADMITTED_FAMILY_ID)
    ontology = contracts.ontologies.resolve_digest(family.ontology_contract_digest)
    mapping = contracts.mappings.resolve_digest(family.mapping_contract_digest)

    assert family.family_id == INCREMENT4_ADMITTED_FAMILY_ID
    assert ontology.node_types == frozenset(
        {
            ProjectionNodeType.AUTHORITY_AGGREGATE,
            ProjectionNodeType.AUTHORITY_VERSION,
            ProjectionNodeType.PAYLOAD,
            ProjectionNodeType.LEDGER_EVENT,
        }
    )
    assert ontology.relation_types == frozenset(
        {
            ProjectionRelationType.HAS_VERSION,
            ProjectionRelationType.CONTAINS_PAYLOAD,
            ProjectionRelationType.DERIVED_FROM,
            ProjectionRelationType.PROJECTED_FROM_EVENT,
        }
    )
    assert {item.event_type for item in mapping.mappings} == {
        "entity.merge.decided",
        "entity.resolution.decided",
        "entity.reversal.decided",
        "entity.split.decided",
        "editorial.relation.decided",
    }
    assert not any(item.required for item in mapping.mappings)


def test_increment4_mapper_projects_only_admitted_bilingual_current_state(tmp_path: Path) -> None:
    _, snapshot = _admitted_fixture(tmp_path)
    contracts = increment4_admitted_contract_registry()
    family = contracts.family(INCREMENT4_ADMITTED_FAMILY_ID)
    generation = ProjectionGenerationId.parse("00000000-0000-4000-8000-000000004901")

    batches = build_increment4_admitted_batches(
        snapshot, generation_id=generation, family=family
    )

    assert batches
    assert tuple(item.ledger_seq for item in batches) == tuple(
        sorted(item.ledger_seq for item in batches)
    )
    nodes = {node.canonical_id: node for batch in batches for node in batch.nodes}
    relations = [relation for batch in batches for relation in batch.relations]
    node_types = {item.node_type for item in nodes.values()}
    assert ProjectionNodeType.AUTHORITY_AGGREGATE in node_types
    assert ProjectionNodeType.AUTHORITY_VERSION in node_types
    assert ProjectionNodeType.PAYLOAD in node_types
    assert len(
        [item for item in nodes.values() if item.identity_source == "CANONICAL_ENTITY_ID"]
    ) == 2
    assert len(
        [item for item in nodes.values() if item.identity_source == "ENTITY_ALIAS_ID"]
    ) == 2
    assert len(
        [
            item
            for item in nodes.values()
            if item.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
        ]
    ) == 1
    relation_types = {item.relation_type for item in relations}
    assert ProjectionRelationType.HAS_VERSION in relation_types
    assert ProjectionRelationType.CONTAINS_PAYLOAD in relation_types
    assert ProjectionRelationType.DERIVED_FROM in relation_types
    assert all(item.trust_scope is TrustScope.ADMITTED for item in relations)
    assert all(item.generation_id == generation for item in batches)


def test_increment4_relation_is_reified_and_false_merge_entities_stay_distinct(tmp_path: Path) -> None:
    _, snapshot = _admitted_fixture(tmp_path)
    family = increment4_admitted_contract_registry().family(
        INCREMENT4_ADMITTED_FAMILY_ID
    )
    generation = ProjectionGenerationId.parse("00000000-0000-4000-8000-000000004902")
    batches = build_increment4_admitted_batches(
        snapshot, generation_id=generation, family=family
    )

    nodes = [node for batch in batches for node in batch.nodes]
    entity_nodes = {
        node.canonical_id
        for node in nodes
        if node.identity_source == "CANONICAL_ENTITY_ID"
    }
    assert len(entity_nodes) == 2
    assertion_nodes = {
        node.canonical_id
        for node in nodes
        if node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
    }
    assert len(assertion_nodes) == 1
    relations = [relation for batch in batches for relation in batch.relations]
    subject = [
        item for item in relations if item.relation_type is ProjectionRelationType.DERIVED_FROM and item.payload_id.endswith(":subject")
    ]
    object_ = [
        item for item in relations if item.relation_type is ProjectionRelationType.DERIVED_FROM and item.payload_id.endswith(":object")
    ]
    assert len(subject) == 1
    assert len(object_) == 1
    assert subject[0].source_canonical_id == object_[0].source_canonical_id
    assert subject[0].target_canonical_id != object_[0].target_canonical_id
    assert subject[0].source_canonical_id in assertion_nodes
