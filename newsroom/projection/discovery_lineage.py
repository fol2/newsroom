from __future__ import annotations

from newsroom.authority import AggregateId

from .mapping import (
    ProjectionIdentitySource,
    StructuralEventMapping,
    StructuralMappingContract,
    StructuralMappingRegistry,
    StructuralNodeBinding,
    StructuralRelationBinding,
)
from .models import ProjectionFamilyDefinition, ProjectionFamilyKind
from .ontology import (
    OntologyContract,
    OntologyNodeDefinition,
    OntologyRegistry,
    OntologyRelationDefinition,
    ProjectionNodeType,
    ProjectionRelationType,
)
from .policy import ProjectionContractRegistry
from .registry import ProjectionFamilyRegistry


DISCOVERY_LINEAGE_FAMILY_ID = "graph.discovery_lineage"
DISCOVERY_LINEAGE_FAMILY_VERSION = "discovery-lineage-family-v1"
DISCOVERY_LINEAGE_ONTOLOGY_ID = "newsroom.discovery-lineage"
DISCOVERY_LINEAGE_ONTOLOGY_VERSION = "discovery-lineage-ontology-v1"
DISCOVERY_LINEAGE_MAPPING_ID = "newsroom.discovery-lineage"
DISCOVERY_LINEAGE_MAPPING_VERSION = "discovery-lineage-mapping-v1"
DISCOVERY_LINEAGE_PROJECTOR_VERSION = "discovery-lineage-projector-v1"
DISCOVERY_LINEAGE_FAMILY_AGGREGATE_ID = AggregateId.parse(
    "33333333-3333-4333-8333-333333333333"
)

_DISCOVERY_NODE_TYPES = frozenset(
    {
        ProjectionNodeType.SOURCE_DEFINITION,
        ProjectionNodeType.SOURCE_DEFINITION_VERSION,
        ProjectionNodeType.SOURCE_ITEM,
        ProjectionNodeType.SOURCE_REVISION,
        ProjectionNodeType.SOURCE_REPRESENTATION,
        ProjectionNodeType.DISCOVERY_OCCURRENCE,
        ProjectionNodeType.CHECK_REQUEST,
        ProjectionNodeType.CHECK_ATTEMPT,
        ProjectionNodeType.CHECK_OUTCOME,
        ProjectionNodeType.OBSERVABLE_TRANSITION,
        ProjectionNodeType.SIGNAL,
        ProjectionNodeType.GATE_DECISION,
        ProjectionNodeType.LEAD,
        ProjectionNodeType.LEDGER_EVENT,
    }
)


def _node(
    alias: str,
    node_type: ProjectionNodeType,
    identity_source: ProjectionIdentitySource,
    payload_field: str | None = None,
    *,
    optional: bool = False,
) -> StructuralNodeBinding:
    return StructuralNodeBinding(
        alias=alias,
        node_type=node_type,
        identity_source=identity_source,
        payload_field=payload_field,
        identity_namespace=(
            None
            if node_type is ProjectionNodeType.LEDGER_EVENT
            else node_type.value.lower()
        ),
        optional=optional,
    )


def _relation(
    relation_type: ProjectionRelationType,
    source_alias: str,
    target_alias: str,
) -> StructuralRelationBinding:
    return StructuralRelationBinding(
        relation_type=relation_type,
        source_alias=source_alias,
        target_alias=target_alias,
    )


def _event_node() -> StructuralNodeBinding:
    return _node(
        "event",
        ProjectionNodeType.LEDGER_EVENT,
        ProjectionIdentitySource.EVENT,
    )


def discovery_lineage_ontology_v1() -> OntologyContract:
    common_identity = frozenset({"canonical_id", "entity_type"})
    provenance = frozenset({"authority_event_id", "ledger_seq"})
    nodes = tuple(
        OntologyNodeDefinition(item, common_identity)
        for item in sorted(_DISCOVERY_NODE_TYPES, key=lambda value: value.value)
    )
    relations = (
        OntologyRelationDefinition(
            ProjectionRelationType.HAS_DEFINITION_VERSION,
            frozenset({ProjectionNodeType.SOURCE_DEFINITION}),
            frozenset({ProjectionNodeType.SOURCE_DEFINITION_VERSION}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.DEFINES_ITEM,
            frozenset({ProjectionNodeType.SOURCE_DEFINITION_VERSION}),
            frozenset({ProjectionNodeType.SOURCE_ITEM}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.REQUESTED_CHECK,
            frozenset({ProjectionNodeType.SOURCE_DEFINITION_VERSION}),
            frozenset({ProjectionNodeType.CHECK_REQUEST}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.ATTEMPTED_AS,
            frozenset({ProjectionNodeType.CHECK_REQUEST}),
            frozenset({ProjectionNodeType.CHECK_ATTEMPT}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.PRODUCED_CHECK_OUTCOME,
            frozenset({ProjectionNodeType.CHECK_ATTEMPT}),
            frozenset({ProjectionNodeType.CHECK_OUTCOME}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.HAS_REVISION,
            frozenset({ProjectionNodeType.SOURCE_ITEM}),
            frozenset({ProjectionNodeType.SOURCE_REVISION}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.HAS_REPRESENTATION,
            frozenset({ProjectionNodeType.SOURCE_REVISION}),
            frozenset({ProjectionNodeType.SOURCE_REPRESENTATION}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.OBSERVED_AS,
            frozenset({ProjectionNodeType.SOURCE_REPRESENTATION}),
            frozenset({ProjectionNodeType.DISCOVERY_OCCURRENCE}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.PRODUCED_OCCURRENCE,
            frozenset({ProjectionNodeType.CHECK_OUTCOME}),
            frozenset({ProjectionNodeType.DISCOVERY_OCCURRENCE}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.TRANSITION_OF_ITEM,
            frozenset({ProjectionNodeType.SOURCE_ITEM}),
            frozenset({ProjectionNodeType.OBSERVABLE_TRANSITION}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.CLASSIFIED_BY_TRANSITION,
            frozenset({ProjectionNodeType.CHECK_OUTCOME}),
            frozenset({ProjectionNodeType.OBSERVABLE_TRANSITION}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.PRODUCED_SIGNAL,
            frozenset({ProjectionNodeType.SOURCE_REPRESENTATION}),
            frozenset({ProjectionNodeType.SIGNAL}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.EMITTED_SIGNAL,
            frozenset({ProjectionNodeType.OBSERVABLE_TRANSITION}),
            frozenset({ProjectionNodeType.SIGNAL}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.DECIDED_BY_GATE,
            frozenset({ProjectionNodeType.SIGNAL}),
            frozenset({ProjectionNodeType.GATE_DECISION}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.PROMOTED_TO_LEAD,
            frozenset({ProjectionNodeType.SIGNAL}),
            frozenset({ProjectionNodeType.LEAD}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.OPENED_LEAD,
            frozenset({ProjectionNodeType.GATE_DECISION}),
            frozenset({ProjectionNodeType.LEAD}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.DUPLICATE_OF_SIGNAL,
            frozenset({ProjectionNodeType.SIGNAL}),
            frozenset({ProjectionNodeType.SIGNAL}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.REPLACED_BY_ITEM,
            frozenset({ProjectionNodeType.SOURCE_ITEM}),
            frozenset({ProjectionNodeType.SOURCE_ITEM}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.PROJECTED_FROM_EVENT,
            frozenset(
                item
                for item in _DISCOVERY_NODE_TYPES
                if item is not ProjectionNodeType.LEDGER_EVENT
            ),
            frozenset({ProjectionNodeType.LEDGER_EVENT}),
            provenance,
        ),
    )
    return OntologyContract(
        ontology_id=DISCOVERY_LINEAGE_ONTOLOGY_ID,
        ontology_version=DISCOVERY_LINEAGE_ONTOLOGY_VERSION,
        implementation_version="discovery-lineage-ontology-python-v1",
        nodes=nodes,
        relations=relations,
    )


def discovery_lineage_mapping_v1(
    ontology: OntologyContract,
) -> StructuralMappingContract:
    mappings = (
        StructuralEventMapping(
            "source.definition.registered",
            True,
            (
                _node(
                    "definition",
                    ProjectionNodeType.SOURCE_DEFINITION,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "definition",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "source.definition.version.recorded",
            True,
            (
                _node(
                    "definition",
                    ProjectionNodeType.SOURCE_DEFINITION,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "definition_id",
                ),
                _node(
                    "definition_version",
                    ProjectionNodeType.SOURCE_DEFINITION_VERSION,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.HAS_DEFINITION_VERSION,
                    "definition",
                    "definition_version",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "definition_version",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "check.request.registered",
            True,
            (
                _node(
                    "definition_version",
                    ProjectionNodeType.SOURCE_DEFINITION_VERSION,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "definition_version_id",
                ),
                _node(
                    "check_request",
                    ProjectionNodeType.CHECK_REQUEST,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.REQUESTED_CHECK,
                    "definition_version",
                    "check_request",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "check_request",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "check.attempt.started",
            True,
            (
                _node(
                    "check_request",
                    ProjectionNodeType.CHECK_REQUEST,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "request_id",
                ),
                _node(
                    "check_attempt",
                    ProjectionNodeType.CHECK_ATTEMPT,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.ATTEMPTED_AS,
                    "check_request",
                    "check_attempt",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "check_attempt",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "check.outcome.recorded",
            True,
            (
                _node(
                    "check_attempt",
                    ProjectionNodeType.CHECK_ATTEMPT,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "attempt_id",
                ),
                _node(
                    "check_outcome",
                    ProjectionNodeType.CHECK_OUTCOME,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.PRODUCED_CHECK_OUTCOME,
                    "check_attempt",
                    "check_outcome",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "check_outcome",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "source.item.registered",
            True,
            (
                _node(
                    "definition_version",
                    ProjectionNodeType.SOURCE_DEFINITION_VERSION,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "definition_version_id",
                ),
                _node(
                    "item",
                    ProjectionNodeType.SOURCE_ITEM,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.DEFINES_ITEM,
                    "definition_version",
                    "item",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "item",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "source.revision.recorded",
            True,
            (
                _node(
                    "item",
                    ProjectionNodeType.SOURCE_ITEM,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "item_id",
                ),
                _node(
                    "revision",
                    ProjectionNodeType.SOURCE_REVISION,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.HAS_REVISION,
                    "item",
                    "revision",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "revision",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "discovery.representation.recorded",
            True,
            (
                _node(
                    "revision",
                    ProjectionNodeType.SOURCE_REVISION,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "revision_id",
                ),
                _node(
                    "representation",
                    ProjectionNodeType.SOURCE_REPRESENTATION,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.HAS_REPRESENTATION,
                    "revision",
                    "representation",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "representation",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "discovery.occurrence.recorded",
            True,
            (
                _node(
                    "representation",
                    ProjectionNodeType.SOURCE_REPRESENTATION,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "representation_id",
                ),
                _node(
                    "check_outcome",
                    ProjectionNodeType.CHECK_OUTCOME,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "check_outcome_id",
                ),
                _node(
                    "occurrence",
                    ProjectionNodeType.DISCOVERY_OCCURRENCE,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.OBSERVED_AS,
                    "representation",
                    "occurrence",
                ),
                _relation(
                    ProjectionRelationType.PRODUCED_OCCURRENCE,
                    "check_outcome",
                    "occurrence",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "occurrence",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "source.observable_transition.recorded",
            True,
            (
                _node(
                    "item",
                    ProjectionNodeType.SOURCE_ITEM,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "item_id",
                ),
                _node(
                    "related_item",
                    ProjectionNodeType.SOURCE_ITEM,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "related_item_id",
                    optional=True,
                ),
                _node(
                    "check_outcome",
                    ProjectionNodeType.CHECK_OUTCOME,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "check_outcome_id",
                ),
                _node(
                    "transition",
                    ProjectionNodeType.OBSERVABLE_TRANSITION,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.TRANSITION_OF_ITEM,
                    "item",
                    "transition",
                ),
                _relation(
                    ProjectionRelationType.REPLACED_BY_ITEM,
                    "item",
                    "related_item",
                ),
                _relation(
                    ProjectionRelationType.CLASSIFIED_BY_TRANSITION,
                    "check_outcome",
                    "transition",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "transition",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "discovery.signal.admitted",
            True,
            (
                _node(
                    "representation",
                    ProjectionNodeType.SOURCE_REPRESENTATION,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "representation_id",
                ),
                _node(
                    "transition",
                    ProjectionNodeType.OBSERVABLE_TRANSITION,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "transition_id",
                ),
                _node(
                    "signal",
                    ProjectionNodeType.SIGNAL,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.PRODUCED_SIGNAL,
                    "representation",
                    "signal",
                ),
                _relation(
                    ProjectionRelationType.EMITTED_SIGNAL,
                    "transition",
                    "signal",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "signal",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "discovery.gate.decided",
            True,
            (
                _node(
                    "signal",
                    ProjectionNodeType.SIGNAL,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "signal_id",
                ),
                _node(
                    "duplicate_signal",
                    ProjectionNodeType.SIGNAL,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "basis.duplicate_signal_id",
                    optional=True,
                ),
                _node(
                    "gate",
                    ProjectionNodeType.GATE_DECISION,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.DECIDED_BY_GATE,
                    "signal",
                    "gate",
                ),
                _relation(
                    ProjectionRelationType.DUPLICATE_OF_SIGNAL,
                    "signal",
                    "duplicate_signal",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "gate",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "discovery.lead.opened",
            True,
            (
                _node(
                    "signal",
                    ProjectionNodeType.SIGNAL,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "signal_id",
                ),
                _node(
                    "gate",
                    ProjectionNodeType.GATE_DECISION,
                    ProjectionIdentitySource.PAYLOAD_FIELD,
                    "promoting_gate_decision_id",
                ),
                _node(
                    "lead",
                    ProjectionNodeType.LEAD,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _event_node(),
            ),
            (
                _relation(
                    ProjectionRelationType.PROMOTED_TO_LEAD,
                    "signal",
                    "lead",
                ),
                _relation(
                    ProjectionRelationType.OPENED_LEAD,
                    "gate",
                    "lead",
                ),
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "lead",
                    "event",
                ),
            ),
        ),
    )
    contract = StructuralMappingContract(
        mapping_id=DISCOVERY_LINEAGE_MAPPING_ID,
        mapping_version=DISCOVERY_LINEAGE_MAPPING_VERSION,
        implementation_version="discovery-lineage-mapping-python-v1",
        ontology_contract_digest=ontology.contract_digest,
        mappings=mappings,
    )
    contract.validate_against(ontology)
    return contract


def discovery_lineage_family_v1(
    ontology: OntologyContract,
    mapping: StructuralMappingContract,
) -> ProjectionFamilyDefinition:
    return ProjectionFamilyDefinition(
        family_id=DISCOVERY_LINEAGE_FAMILY_ID,
        authority_aggregate_id=DISCOVERY_LINEAGE_FAMILY_AGGREGATE_ID,
        family_kind=ProjectionFamilyKind.GRAPH,
        definition_version=DISCOVERY_LINEAGE_FAMILY_VERSION,
        projector_version=DISCOVERY_LINEAGE_PROJECTOR_VERSION,
        ontology_contract_digest=ontology.contract_digest,
        mapping_contract_digest=mapping.contract_digest,
        max_delivery_attempts=3,
        max_gap_span=10_000,
    )


def discovery_lineage_contract_registry(
    base: ProjectionContractRegistry | None = None,
) -> ProjectionContractRegistry:
    ontology = discovery_lineage_ontology_v1()
    mapping = discovery_lineage_mapping_v1(ontology)
    family = discovery_lineage_family_v1(ontology, mapping)

    ontologies = list(base.ontologies.contracts()) if base is not None else []
    mappings = list(base.mappings.contracts()) if base is not None else []
    families = list(base.families.definitions()) if base is not None else []
    ontologies.append(ontology)
    mappings.append(mapping)
    families.append(family)

    ontology_registry = OntologyRegistry(ontologies)
    mapping_registry = StructuralMappingRegistry(mappings)
    family_registry = ProjectionFamilyRegistry(
        families,
        ontologies=ontology_registry,
        mappings=mapping_registry,
    )
    return ProjectionContractRegistry(
        ontologies=ontology_registry,
        mappings=mapping_registry,
        families=family_registry,
        graphiti_workspaces=(base.graphiti_workspaces if base is not None else ()),
        complete_projections=(base.complete_projections if base is not None else None),
    )


__all__ = [
    "DISCOVERY_LINEAGE_FAMILY_AGGREGATE_ID",
    "DISCOVERY_LINEAGE_FAMILY_ID",
    "DISCOVERY_LINEAGE_FAMILY_VERSION",
    "DISCOVERY_LINEAGE_MAPPING_ID",
    "DISCOVERY_LINEAGE_MAPPING_VERSION",
    "DISCOVERY_LINEAGE_ONTOLOGY_ID",
    "DISCOVERY_LINEAGE_ONTOLOGY_VERSION",
    "DISCOVERY_LINEAGE_PROJECTOR_VERSION",
    "discovery_lineage_contract_registry",
    "discovery_lineage_family_v1",
    "discovery_lineage_mapping_v1",
    "discovery_lineage_ontology_v1",
]
