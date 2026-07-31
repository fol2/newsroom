from __future__ import annotations

from newsroom.authority import AggregateId
from newsroom.projection.mapping import (
    ProjectionIdentitySource,
    StructuralEventMapping,
    StructuralMappingContract,
    StructuralMappingRegistry,
    StructuralNodeBinding,
    StructuralRelationBinding,
)
from newsroom.projection.models import ProjectionFamilyDefinition, ProjectionFamilyKind
from newsroom.projection.ontology import (
    OntologyContract,
    OntologyNodeDefinition,
    OntologyRegistry,
    OntologyRelationDefinition,
    ProjectionNodeType,
    ProjectionRelationType,
)
from newsroom.projection.policy import ProjectionContractRegistry
from newsroom.projection.registry import ProjectionFamilyRegistry


INCREMENT4_ADMITTED_FAMILY_ID = "graph.increment4.admitted"
INCREMENT4_ADMITTED_FAMILY_VERSION = "increment4-admitted-family-v1"
INCREMENT4_ADMITTED_ONTOLOGY_ID = "newsroom.increment4.admitted"
INCREMENT4_ADMITTED_ONTOLOGY_VERSION = "increment4-admitted-ontology-v1"
INCREMENT4_ADMITTED_MAPPING_ID = "newsroom.increment4.admitted"
INCREMENT4_ADMITTED_MAPPING_VERSION = "increment4-admitted-mapping-v1"
INCREMENT4_ADMITTED_PROJECTOR_VERSION = "increment4-admitted-snapshot-projector-v1"
INCREMENT4_ADMITTED_FAMILY_AGGREGATE_ID = AggregateId.parse(
    "44444444-4444-4444-8444-444444444444"
)

_INCREMENT4_NODE_TYPES = frozenset(
    {
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionNodeType.AUTHORITY_VERSION,
        ProjectionNodeType.PAYLOAD,
        ProjectionNodeType.LEDGER_EVENT,
    }
)

_INCREMENT4_EVENT_TYPES = (
    "entity.merge.decided",
    "entity.resolution.decided",
    "entity.reversal.decided",
    "entity.split.decided",
    "editorial.relation.decided",
)


def increment4_admitted_ontology_v1() -> OntologyContract:
    common_identity = frozenset({"canonical_id", "entity_type"})
    provenance = frozenset({"authority_event_id", "ledger_seq"})
    nodes = tuple(
        OntologyNodeDefinition(item, common_identity)
        for item in sorted(_INCREMENT4_NODE_TYPES, key=lambda value: value.value)
    )
    relations = (
        OntologyRelationDefinition(
            ProjectionRelationType.HAS_VERSION,
            frozenset({ProjectionNodeType.AUTHORITY_AGGREGATE}),
            frozenset({ProjectionNodeType.AUTHORITY_VERSION}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.CONTAINS_PAYLOAD,
            frozenset({ProjectionNodeType.AUTHORITY_VERSION}),
            frozenset({ProjectionNodeType.PAYLOAD}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.DERIVED_FROM,
            frozenset({ProjectionNodeType.AUTHORITY_VERSION}),
            frozenset({ProjectionNodeType.AUTHORITY_AGGREGATE, ProjectionNodeType.AUTHORITY_VERSION}),
            provenance,
        ),
        OntologyRelationDefinition(
            ProjectionRelationType.PROJECTED_FROM_EVENT,
            frozenset(
                item
                for item in _INCREMENT4_NODE_TYPES
                if item is not ProjectionNodeType.LEDGER_EVENT
            ),
            frozenset({ProjectionNodeType.LEDGER_EVENT}),
            provenance,
        ),
    )
    return OntologyContract(
        ontology_id=INCREMENT4_ADMITTED_ONTOLOGY_ID,
        ontology_version=INCREMENT4_ADMITTED_ONTOLOGY_VERSION,
        implementation_version="increment4-admitted-ontology-python-v1",
        nodes=nodes,
        relations=relations,
    )


def increment4_admitted_mapping_v1(
    ontology: OntologyContract,
) -> StructuralMappingContract:
    mappings = tuple(
        StructuralEventMapping(
            event_type=event_type,
            required=False,
            nodes=(
                StructuralNodeBinding(
                    alias="authority",
                    node_type=ProjectionNodeType.AUTHORITY_AGGREGATE,
                    identity_source=ProjectionIdentitySource.AGGREGATE,
                ),
                StructuralNodeBinding(
                    alias="event",
                    node_type=ProjectionNodeType.LEDGER_EVENT,
                    identity_source=ProjectionIdentitySource.EVENT,
                ),
            ),
            relations=(
                StructuralRelationBinding(
                    relation_type=ProjectionRelationType.PROJECTED_FROM_EVENT,
                    source_alias="authority",
                    target_alias="event",
                ),
            ),
        )
        for event_type in _INCREMENT4_EVENT_TYPES
    )
    contract = StructuralMappingContract(
        mapping_id=INCREMENT4_ADMITTED_MAPPING_ID,
        mapping_version=INCREMENT4_ADMITTED_MAPPING_VERSION,
        implementation_version=INCREMENT4_ADMITTED_PROJECTOR_VERSION,
        ontology_contract_digest=ontology.contract_digest,
        mappings=mappings,
    )
    contract.validate_against(ontology)
    return contract


def increment4_admitted_family_v1(
    ontology: OntologyContract,
    mapping: StructuralMappingContract,
) -> ProjectionFamilyDefinition:
    return ProjectionFamilyDefinition(
        family_id=INCREMENT4_ADMITTED_FAMILY_ID,
        authority_aggregate_id=INCREMENT4_ADMITTED_FAMILY_AGGREGATE_ID,
        family_kind=ProjectionFamilyKind.GRAPH,
        definition_version=INCREMENT4_ADMITTED_FAMILY_VERSION,
        projector_version=INCREMENT4_ADMITTED_PROJECTOR_VERSION,
        ontology_contract_digest=ontology.contract_digest,
        mapping_contract_digest=mapping.contract_digest,
        max_delivery_attempts=3,
        max_gap_span=10_000,
        required_manage_scope="authority.projection.manage",
        required_write_scope="authority.projection.write",
        required_read_scope="authority.projection.read",
        security_scope="authority.projection",
        retention_scope="authority.default",
    )


def increment4_admitted_contract_registry() -> ProjectionContractRegistry:
    ontology = increment4_admitted_ontology_v1()
    mapping = increment4_admitted_mapping_v1(ontology)
    family = increment4_admitted_family_v1(ontology, mapping)
    ontologies = OntologyRegistry((ontology,))
    mappings = StructuralMappingRegistry((mapping,))
    families = ProjectionFamilyRegistry(
        (family,), ontologies=ontologies, mappings=mappings
    )
    return ProjectionContractRegistry(
        ontologies=ontologies,
        mappings=mappings,
        families=families,
    )


__all__ = [
    "INCREMENT4_ADMITTED_FAMILY_AGGREGATE_ID",
    "INCREMENT4_ADMITTED_FAMILY_ID",
    "INCREMENT4_ADMITTED_FAMILY_VERSION",
    "INCREMENT4_ADMITTED_MAPPING_ID",
    "INCREMENT4_ADMITTED_MAPPING_VERSION",
    "INCREMENT4_ADMITTED_ONTOLOGY_ID",
    "INCREMENT4_ADMITTED_ONTOLOGY_VERSION",
    "INCREMENT4_ADMITTED_PROJECTOR_VERSION",
    "increment4_admitted_contract_registry",
    "increment4_admitted_family_v1",
    "increment4_admitted_mapping_v1",
    "increment4_admitted_ontology_v1",
]
