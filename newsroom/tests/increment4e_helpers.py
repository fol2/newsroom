from __future__ import annotations

import sqlite3
from pathlib import Path

from newsroom.authority import StaticAuthorizer
from newsroom.authority._neo4j_projection_system import _open_with_adapter
from newsroom.authority.persistence import LedgerEventRecord
from newsroom.increment4 import (
    Increment4EntityProjectionState,
    Increment4RelationProjectionState,
    increment4_admitted_contract_registry,
    sorted_snapshot,
)
from newsroom.projection import (
    ProjectionFamilyKind,
    ProjectionReadPolicy,
)
from newsroom.relations import EditorialRelationDecisionAction
from newsroom.relations.editorial_policy import (
    merge_editorial_relation_authority_registries,
)

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
from .extraction_4a_helpers import (
    extraction_authenticator,
    extraction_proof,
)
from .projection_b1_helpers import event_read_policy
from .source_3a_helpers import SOURCE_NOW


INCREMENT4_PROJECTION_SCOPES = frozenset(
    {
        "authority.observed.write",
        "authority.admitted.write",
        "authority.projection.manage",
        "authority.projection.write",
        "authority.projection.read",
    }
)


def increment4_projection_read_policy() -> ProjectionReadPolicy:
    return ProjectionReadPolicy(
        policy_id="increment4-admitted-reader-v1",
        purpose="increment4.admitted.proof",
        required_scope="authority.projection.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_family_ids=frozenset({"graph.increment4.admitted"}),
        allowed_family_kinds=frozenset({ProjectionFamilyKind.GRAPH}),
        max_results=1000,
    )


def increment4_projection_authorizer(
    *, scopes: frozenset[str] | None = None
) -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="increment4-admitted-projection-authz-v1",
        grants_by_principal={
            "principal.alpha": (
                INCREMENT4_PROJECTION_SCOPES if scopes is None else scopes
            )
        },
    )


def open_increment4_neo4j_system(
    state,
    adapter,
    *,
    scopes: frozenset[str] | None = None,
    authorizer=None,
    clock=lambda: SOURCE_NOW,
):
    registry, schemas = merge_editorial_relation_authority_registries(
        command_registry=state.entity.extraction.commands,
        payload_schemas=state.entity.extraction.schemas,
    )
    return _open_with_adapter(
        path=state.entity.extraction.database,
        registry=registry,
        payload_schemas=schemas,
        contracts=increment4_admitted_contract_registry(),
        authenticator=extraction_authenticator(),
        authorizer=(
            increment4_projection_authorizer(scopes=scopes)
            if authorizer is None
            else authorizer
        ),
        event_read_policy=event_read_policy(),
        projection_read_policy=increment4_projection_read_policy(),
        adapter=adapter,
        clock=clock,
    )


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
            payload_schema_contract_version=str(
                row["payload_schema_contract_version"]
            ),
            payload_schema_contract_digest=str(
                row["payload_schema_contract_digest"]
            ),
            payload_canonicalizer_version=str(
                row["payload_canonicalizer_version"]
            ),
            payload_digest=str(row["payload_digest"]),
            object_admission_id=(
                None
                if row["object_admission_id"] is None
                else str(row["object_admission_id"])
            ),
            principal_id=str(row["principal_id"]),
            authentication_context_id=str(row["authentication_context_id"]),
            authorization_request_digest=str(
                row["authorization_request_digest"]
            ),
            authorization_decision_id=str(row["authorization_decision_id"]),
            correlation_id=(
                None if row["correlation_id"] is None else str(row["correlation_id"])
            ),
            causation_kind=(
                None if row["causation_kind"] is None else str(row["causation_kind"])
            ),
            causation_identifier=(
                None
                if row["causation_identifier"] is None
                else str(row["causation_identifier"])
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
        version=system.entities.entity_version(
            version_id, proof=extraction_proof()
        ),
        preferred=system.entities.preferred(entity_id, proof=extraction_proof()),
        aliases=tuple(
            sorted(
                system.entities.aliases(
                    entity_id, limit=100, proof=extraction_proof()
                ),
                key=lambda item: str(item.alias_id),
            )
        ),
        projection_event=projection,
    )


def admitted_increment4_fixture(root: Path):
    state = seed_relation_fixture(root)
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
            if item.assertion_id == RELATION_ASSERTION_ID
            and item.assertion is not None
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


__all__ = [
    "INCREMENT4_PROJECTION_SCOPES",
    "admitted_increment4_fixture",
    "increment4_projection_authorizer",
    "increment4_projection_read_policy",
    "open_increment4_neo4j_system",
]
