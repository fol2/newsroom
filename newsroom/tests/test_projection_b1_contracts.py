from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority import AggregateId
from newsroom.projection import (
    OntologyContract,
    OntologyRegistry,
    ProjectionContractError,
    ProjectionFamilyDefinition,
    ProjectionFamilyKind,
    ProjectionFamilyRegistry,
    ProjectionNodeType,
    ProjectionRelationType,
    StructuralEventMapping,
    StructuralMappingContract,
    StructuralMappingRegistry,
    native_ontology_v1,
    native_structural_mapping_v1,
)


FAMILY_AGGREGATE = AggregateId.parse("11111111-1111-4111-8111-111111111111")


def family_definition() -> ProjectionFamilyDefinition:
    ontology = native_ontology_v1()
    mapping = native_structural_mapping_v1(ontology)
    return ProjectionFamilyDefinition(
        family_id="graph.structural",
        authority_aggregate_id=FAMILY_AGGREGATE,
        family_kind=ProjectionFamilyKind.GRAPH,
        definition_version="family-v1",
        projector_version="structural-projector-v1",
        ontology_contract_digest=ontology.contract_digest,
        mapping_contract_digest=mapping.contract_digest,
    )


def test_native_ontology_is_stable_and_rejects_generic_relations() -> None:
    ontology = native_ontology_v1()
    assert ontology.contract_digest == native_ontology_v1().contract_digest
    assert ProjectionRelationType.PROJECTED_FROM_EVENT in ontology.relation_types
    assert "RELATED_TO" not in {item.value for item in ontology.relation_types}
    assert all(item.name == item.value for item in ProjectionRelationType)


def test_mapping_is_allow_listed_and_validated_against_exact_ontology() -> None:
    ontology = native_ontology_v1()
    mapping = native_structural_mapping_v1(ontology)
    mapping.validate_against(ontology)
    assert mapping.resolve("source.item.revised") is not None
    assert mapping.resolve("caller.related") is None

    changed = replace(ontology, ontology_version="ontology-v2")
    with pytest.raises(ProjectionContractError, match="ontology digest"):
        mapping.validate_against(changed)


def test_mapping_rejects_unknown_relation_and_duplicate_event() -> None:
    ontology = native_ontology_v1()
    valid = native_structural_mapping_v1(ontology).mappings[0]
    with pytest.raises(ProjectionContractError, match="event types"):
        StructuralMappingContract(
            mapping_id="bad.mapping",
            mapping_version="mapping-v1",
            implementation_version="mapping-python-v1",
            ontology_contract_digest=ontology.contract_digest,
            mappings=(valid, valid),
        )

    foreign_ontology = OntologyContract(
        ontology_id="foreign",
        ontology_version="ontology-v1",
        implementation_version="foreign-v1",
        nodes=tuple(item for item in ontology.nodes if item.node_type is not ProjectionNodeType.LEAD),
        relations=tuple(
            item
            for item in ontology.relations
            if ProjectionNodeType.LEAD not in item.source_types
            and ProjectionNodeType.LEAD not in item.target_types
        ),
    )
    lead_mapping = StructuralMappingContract(
        mapping_id="bad.lead",
        mapping_version="mapping-v1",
        implementation_version="mapping-python-v1",
        ontology_contract_digest=foreign_ontology.contract_digest,
        mappings=(
            StructuralEventMapping(
                event_type="lead.promoted",
                required=True,
                node_types=frozenset({ProjectionNodeType.SIGNAL, ProjectionNodeType.LEAD}),
                relation_types=frozenset({ProjectionRelationType.PROMOTED_TO_LEAD}),
            ),
        ),
    )
    with pytest.raises(ProjectionContractError, match="unknown node"):
        lead_mapping.validate_against(foreign_ontology)


def test_family_registry_binds_exact_ontology_and_mapping_contracts() -> None:
    ontology = native_ontology_v1()
    mapping = native_structural_mapping_v1(ontology)
    registry = ProjectionFamilyRegistry(
        (family_definition(),),
        ontologies=OntologyRegistry((ontology,)),
        mappings=StructuralMappingRegistry((mapping,)),
    )
    selected = registry.resolve("graph.structural")
    assert selected.family_kind is ProjectionFamilyKind.GRAPH
    assert selected.digest == family_definition().digest

    broken = replace(selected, mapping_contract_digest="sha256:" + "0" * 64)
    with pytest.raises(ProjectionContractError, match="unknown or ambiguous"):
        ProjectionFamilyRegistry(
            (broken,),
            ontologies=OntologyRegistry((ontology,)),
            mappings=StructuralMappingRegistry((mapping,)),
        )


def test_family_registry_rejects_duplicate_authority_aggregate_identity() -> None:
    ontology = native_ontology_v1()
    mapping = native_structural_mapping_v1(ontology)
    first = family_definition()
    second = replace(
        first,
        family_id="vector.semantic",
        family_kind=ProjectionFamilyKind.VECTOR,
    )
    with pytest.raises(ProjectionContractError, match="aggregate IDs"):
        ProjectionFamilyRegistry(
            (first, second),
            ontologies=OntologyRegistry((ontology,)),
            mappings=StructuralMappingRegistry((mapping,)),
        )
