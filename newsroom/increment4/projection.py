from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.persistence import LedgerEventRecord
from newsroom.authority.types import TrustScope, UtcTimestamp
from newsroom.entities.models import EntityAlias
from newsroom.projection.mapping import (
    canonical_governed_node_id,
    governed_identity_reference,
)
from newsroom.projection.models import ProjectionFamilyDefinition, ProjectionGenerationId
from newsroom.projection.neo4j.models import StructuralBatch, StructuralNode, StructuralRelation
from newsroom.projection.ontology import ProjectionNodeType, ProjectionRelationType
from newsroom.relations.editorial_models import (
    CanonicalEntityRelationEndpoint,
    RelationAssertionRelationEndpoint,
)

from .contracts import INCREMENT4_ADMITTED_FAMILY_ID
from .models import (
    Increment4AdmittedProjectionSnapshot,
    Increment4EntityProjectionState,
    Increment4ProofContractError,
    Increment4RelationProjectionState,
)


_ENTITY_NAMESPACE = "canonical_entity_id"
_ENTITY_VERSION_NAMESPACE = "canonical_entity_version_id"
_ALIAS_NAMESPACE = "entity_alias_id"
_ASSERTION_NAMESPACE = "editorial_relation_assertion_id"
_EVENT_NAMESPACE = "authority_event_id"


def _event_digest(event: LedgerEventRecord) -> str:
    return digest_canonical(asdict(event))


def _node(
    *,
    node_type: ProjectionNodeType,
    namespace: str,
    value: str,
    event: LedgerEventRecord,
) -> StructuralNode:
    reference = governed_identity_reference(node_type, namespace, value)
    return StructuralNode(
        canonical_id=canonical_governed_node_id(node_type, namespace, value),
        node_type=node_type,
        identity_source=namespace.upper(),
        identity_reference_digest=digest_canonical(reference),
        first_ledger_seq=event.ledger_seq,
        first_source_event_id=event.event_id,
        first_source_event_digest=_event_digest(event),
    )


def _relation(
    *,
    generation_id: ProjectionGenerationId,
    relation_type: ProjectionRelationType,
    source: StructuralNode,
    target: StructuralNode,
    event: LedgerEventRecord,
    semantic_digest: str,
    semantic_id: str,
) -> StructuralRelation:
    event_digest = _event_digest(event)
    relation_key = digest_canonical(
        {
            "relation_contract": "newsroom.increment4.admitted-relation.v1",
            "generation_id": str(generation_id),
            "relation_type": relation_type.value,
            "source_canonical_id": source.canonical_id,
            "target_canonical_id": target.canonical_id,
            "source_event_id": event.event_id,
            "source_event_digest": event_digest,
            "semantic_id": semantic_id,
            "semantic_digest": semantic_digest,
        }
    )
    return StructuralRelation(
        relation_key=relation_key,
        relation_type=relation_type,
        source_canonical_id=source.canonical_id,
        target_canonical_id=target.canonical_id,
        ledger_seq=event.ledger_seq,
        source_event_id=event.event_id,
        source_event_type=event.event_type,
        source_event_digest=event_digest,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        aggregate_version=event.aggregate_version,
        payload_id=semantic_id,
        payload_digest=semantic_digest,
        object_admission_id=event.object_admission_id,
        principal_id=event.principal_id,
        trust_scope=TrustScope(event.trust_scope),
        security_scope=event.security_scope,
        retention_scope=event.retention_scope,
        recorded_at=UtcTimestamp.parse(event.recorded_at),
    )


def _event_node(event: LedgerEventRecord) -> StructuralNode:
    return _node(
        node_type=ProjectionNodeType.LEDGER_EVENT,
        namespace=_EVENT_NAMESPACE,
        value=event.event_id,
        event=event,
    )


def _entity_nodes(
    state: Increment4EntityProjectionState,
    events: dict[str, LedgerEventRecord],
) -> tuple[
    StructuralNode,
    StructuralNode,
    tuple[tuple[EntityAlias, StructuralNode, StructuralNode], ...],
]:
    entity_event = events[str(state.entity.authority_event_id)]
    version_event = events[str(state.version.authority_event_id)]
    entity = _node(
        node_type=ProjectionNodeType.AUTHORITY_AGGREGATE,
        namespace=_ENTITY_NAMESPACE,
        value=str(state.entity.entity_id),
        event=entity_event,
    )
    version = _node(
        node_type=ProjectionNodeType.AUTHORITY_VERSION,
        namespace=_ENTITY_VERSION_NAMESPACE,
        value=str(state.version.entity_version_id),
        event=version_event,
    )
    historical_version_events: dict[str, LedgerEventRecord] = {}
    for alias in state.aliases:
        if alias.entity_version_id == state.version.entity_version_id:
            continue
        event = events[str(alias.authority_event_id)]
        key = str(alias.entity_version_id)
        existing = historical_version_events.get(key)
        if existing is None or (event.ledger_seq, event.event_id) < (
            existing.ledger_seq,
            existing.event_id,
        ):
            historical_version_events[key] = event
    aliases = tuple(
        (
            alias,
            _node(
                node_type=ProjectionNodeType.PAYLOAD,
                namespace=_ALIAS_NAMESPACE,
                value=str(alias.alias_id),
                event=events[str(alias.authority_event_id)],
            ),
            (
                version
                if alias.entity_version_id == state.version.entity_version_id
                else _node(
                    node_type=ProjectionNodeType.AUTHORITY_VERSION,
                    namespace=_ENTITY_VERSION_NAMESPACE,
                    value=str(alias.entity_version_id),
                    event=historical_version_events[str(alias.entity_version_id)],
                )
            ),
        )
        for alias in state.aliases
    )
    return entity, version, aliases


def _entity_batch_parts(
    state: Increment4EntityProjectionState,
    *,
    generation_id: ProjectionGenerationId,
    events: dict[str, LedgerEventRecord],
    nodes: dict[str, StructuralNode],
    relations: list[StructuralRelation],
) -> None:
    source_event = events[str(state.projection_event.source_event_id)]
    event_node = _event_node(source_event)
    entity_node, version_node, alias_nodes = _entity_nodes(state, events)
    for node in (
        event_node,
        entity_node,
        version_node,
        *(item[1] for item in alias_nodes),
        *(item[2] for item in alias_nodes),
    ):
        existing = nodes.get(node.canonical_id)
        if existing is not None and existing != node:
            raise Increment4ProofContractError(
                "canonical graph node has conflicting provenance"
            )
        nodes[node.canonical_id] = node
    relations.extend(
        (
            _relation(
                generation_id=generation_id,
                relation_type=ProjectionRelationType.HAS_VERSION,
                source=entity_node,
                target=version_node,
                event=source_event,
                semantic_digest=state.version.canonical_digest,
                semantic_id=str(state.version.entity_version_id),
            ),
            _relation(
                generation_id=generation_id,
                relation_type=ProjectionRelationType.PROJECTED_FROM_EVENT,
                source=version_node,
                target=event_node,
                event=source_event,
                semantic_digest=state.projection_event.canonical_digest,
                semantic_id=str(state.projection_event.projection_event_id),
            ),
        )
    )
    historical_versions: set[str] = set()
    for alias, alias_node, alias_version_node in alias_nodes:
        if alias_version_node.canonical_id != version_node.canonical_id:
            if alias_version_node.canonical_id not in historical_versions:
                relations.append(
                    _relation(
                        generation_id=generation_id,
                        relation_type=ProjectionRelationType.HAS_VERSION,
                        source=entity_node,
                        target=alias_version_node,
                        event=source_event,
                        semantic_digest=alias.canonical_digest,
                        semantic_id=f"{alias.entity_version_id}:historical",
                    )
                )
                historical_versions.add(alias_version_node.canonical_id)
        relations.append(
            _relation(
                generation_id=generation_id,
                relation_type=ProjectionRelationType.CONTAINS_PAYLOAD,
                source=alias_version_node,
                target=alias_node,
                event=source_event,
                semantic_digest=alias.canonical_digest,
                semantic_id=str(alias.alias_id),
            )
        )
    preferred = state.preferred.preferred_entity_id
    if preferred != state.entity.entity_id:
        # The target node is inserted by its own state in the same grouped batch
        # or a prior batch. StructuralBatch nevertheless requires it locally, so
        # add an identity-stable reference using the current source event.
        target_node = _node(
            node_type=ProjectionNodeType.AUTHORITY_AGGREGATE,
            namespace=_ENTITY_NAMESPACE,
            value=str(preferred),
            event=source_event,
        )
        nodes.setdefault(target_node.canonical_id, target_node)
        relations.append(
            _relation(
                generation_id=generation_id,
                relation_type=ProjectionRelationType.DERIVED_FROM,
                source=version_node,
                target=target_node,
                event=source_event,
                semantic_digest=state.canonical_digest,
                semantic_id=str(preferred),
            )
        )


def _relation_batch_parts(
    state: Increment4RelationProjectionState,
    *,
    generation_id: ProjectionGenerationId,
    events: dict[str, LedgerEventRecord],
    entity_by_version: dict[str, Increment4EntityProjectionState],
    nodes: dict[str, StructuralNode],
    relations: list[StructuralRelation],
) -> None:
    source_event = events[str(state.projection_event.source_event_id)]
    event_node = _event_node(source_event)
    assertion = state.current.assertion
    assertion_node = _node(
        node_type=ProjectionNodeType.AUTHORITY_VERSION,
        namespace=_ASSERTION_NAMESPACE,
        value=str(assertion.assertion_id),
        event=source_event,
    )
    subject = assertion.subject
    object_ = assertion.object
    if isinstance(subject, CanonicalEntityRelationEndpoint) and isinstance(
        object_, CanonicalEntityRelationEndpoint
    ):
        subject_state = entity_by_version[str(subject.entity_version_id)]
        object_state = entity_by_version[str(object_.entity_version_id)]
        subject_node = _node(
            node_type=ProjectionNodeType.AUTHORITY_VERSION,
            namespace=_ENTITY_VERSION_NAMESPACE,
            value=str(subject.entity_version_id),
            event=events[str(subject_state.version.authority_event_id)],
        )
        object_node = _node(
            node_type=ProjectionNodeType.AUTHORITY_VERSION,
            namespace=_ENTITY_VERSION_NAMESPACE,
            value=str(object_.entity_version_id),
            event=events[str(object_state.version.authority_event_id)],
        )
    elif isinstance(subject, RelationAssertionRelationEndpoint) and isinstance(
        object_, RelationAssertionRelationEndpoint
    ):
        # A current correction/supersession assertion may reference a retained
        # predecessor that is no longer current. The endpoint node is an
        # identity-stable lineage reference; the current assertion and edge
        # retain the exact source event and admitted trust.
        subject_node = _node(
            node_type=ProjectionNodeType.AUTHORITY_VERSION,
            namespace=_ASSERTION_NAMESPACE,
            value=str(subject.assertion_id),
            event=source_event,
        )
        object_node = _node(
            node_type=ProjectionNodeType.AUTHORITY_VERSION,
            namespace=_ASSERTION_NAMESPACE,
            value=str(object_.assertion_id),
            event=source_event,
        )
    else:
        raise Increment4ProofContractError(
            "relation endpoint pair is outside the admitted projection contract"
        )
    for node in (event_node, assertion_node, subject_node, object_node):
        existing = nodes.get(node.canonical_id)
        if existing is not None and existing != node:
            raise Increment4ProofContractError("canonical relation endpoint has conflicting provenance")
        nodes[node.canonical_id] = node
    for relation_type, target, role in (
        (ProjectionRelationType.DERIVED_FROM, subject_node, "subject"),
        (ProjectionRelationType.DERIVED_FROM, object_node, "object"),
    ):
        relations.append(
            _relation(
                generation_id=generation_id,
                relation_type=relation_type,
                source=assertion_node,
                target=target,
                event=source_event,
                semantic_digest=assertion.canonical_digest,
                semantic_id=f"{assertion.assertion_id}:{role}",
            )
        )
    relations.append(
        _relation(
            generation_id=generation_id,
            relation_type=ProjectionRelationType.PROJECTED_FROM_EVENT,
            source=assertion_node,
            target=event_node,
            event=source_event,
            semantic_digest=state.projection_event.canonical_digest,
            semantic_id=str(state.projection_event.projection_event_id),
        )
    )


def build_increment4_admitted_batches(
    snapshot: Increment4AdmittedProjectionSnapshot,
    *,
    generation_id: ProjectionGenerationId,
    family: ProjectionFamilyDefinition,
) -> tuple[StructuralBatch, ...]:
    if not isinstance(snapshot, Increment4AdmittedProjectionSnapshot):
        raise TypeError("Increment 4 mapper requires a typed admitted snapshot")
    if not isinstance(generation_id, ProjectionGenerationId):
        raise TypeError("Increment 4 mapper requires a typed generation")
    if not isinstance(family, ProjectionFamilyDefinition):
        raise TypeError("Increment 4 mapper requires a typed family")
    if family.family_id != INCREMENT4_ADMITTED_FAMILY_ID:
        raise Increment4ProofContractError("projection family is not the Increment 4 admitted family")

    events = snapshot.event_by_id
    entity_by_version = {
        str(item.version.entity_version_id): item for item in snapshot.entities
    }
    entities_by_seq: dict[int, list[Increment4EntityProjectionState]] = defaultdict(list)
    relations_by_seq: dict[int, list[Increment4RelationProjectionState]] = defaultdict(list)
    for state in snapshot.entities:
        entities_by_seq[state.projection_event.source_ledger_seq].append(state)
    for state in snapshot.relations:
        relations_by_seq[state.projection_event.source_ledger_seq].append(state)

    batches: list[StructuralBatch] = []
    all_sequences = sorted(set(entities_by_seq) | set(relations_by_seq))
    for ledger_seq in all_sequences:
        source_ids = {
            str(item.projection_event.source_event_id)
            for item in (*entities_by_seq[ledger_seq], *relations_by_seq[ledger_seq])
        }
        if len(source_ids) != 1:
            raise Increment4ProofContractError(
                "one projection sequence must bind one exact authority event"
            )
        source_event = events[next(iter(source_ids))]
        if source_event.ledger_seq != ledger_seq:
            raise Increment4ProofContractError("projection sequence differs from retained event")
        if source_event.trust_scope != TrustScope.ADMITTED.value:
            raise Increment4ProofContractError("only ADMITTED source events may project")
        nodes: dict[str, StructuralNode] = {}
        relations: list[StructuralRelation] = []
        for state in sorted(
            entities_by_seq[ledger_seq], key=lambda item: str(item.entity.entity_id)
        ):
            _entity_batch_parts(
                state,
                generation_id=generation_id,
                events=events,
                nodes=nodes,
                relations=relations,
            )
        for state in sorted(
            relations_by_seq[ledger_seq],
            key=lambda item: str(item.current.assertion.assertion_id),
        ):
            _relation_batch_parts(
                state,
                generation_id=generation_id,
                events=events,
                entity_by_version=entity_by_version,
                nodes=nodes,
                relations=relations,
            )
        if not relations:
            raise Increment4ProofContractError("projection batch has no admitted relation state")
        relation_keys = [item.relation_key for item in relations]
        if len(relation_keys) != len(set(relation_keys)):
            raise Increment4ProofContractError("projection relation keys are not unique")
        batches.append(
            StructuralBatch(
                generation_id=generation_id,
                family_id=family.family_id,
                family_definition_version=family.definition_version,
                projector_version=family.projector_version,
                ontology_contract_digest=family.ontology_contract_digest,
                mapping_contract_digest=family.mapping_contract_digest,
                ledger_seq=source_event.ledger_seq,
                source_event_id=source_event.event_id,
                source_event_type=source_event.event_type,
                source_event_digest=_event_digest(source_event),
                nodes=tuple(nodes[key] for key in sorted(nodes)),
                relations=tuple(sorted(relations, key=lambda item: item.relation_key)),
            )
        )
    return tuple(batches)


__all__ = ["build_increment4_admitted_batches"]
