from __future__ import annotations

from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    DISCOVERY_LINEAGE_FAMILY_VERSION,
    DISCOVERY_LINEAGE_MAPPING_ID,
    DISCOVERY_LINEAGE_ONTOLOGY_ID,
    ProjectionIdentitySource,
    ProjectionNodeType,
    ProjectionRelationType,
    discovery_lineage_contract_registry,
    discovery_lineage_family_v1,
    discovery_lineage_mapping_v1,
    discovery_lineage_ontology_v1,
    native_ontology_v1,
    native_structural_mapping_v1,
)


EXPECTED_EVENTS = frozenset(
    {
        "source.definition.registered",
        "source.definition.version.recorded",
        "check.request.registered",
        "check.attempt.started",
        "check.outcome.recorded",
        "source.item.registered",
        "source.revision.recorded",
        "discovery.representation.recorded",
        "discovery.occurrence.recorded",
        "source.observable_transition.recorded",
        "discovery.signal.admitted",
        "discovery.gate.decided",
        "discovery.lead.opened",
    }
)


def test_later_discovery_enums_do_not_mutate_retained_native_v1_contract() -> None:
    ontology = native_ontology_v1()
    mapping = native_structural_mapping_v1(ontology)

    assert ontology.contract_digest == (
        "sha256:71910afd7c818b650c1b5031ff982af1"
        "e2bc9c9bd13b09feb31934a6fc9a7dae"
    )
    assert mapping.contract_digest == (
        "sha256:a27b330984960706f560d2ad4edc588d"
        "6177ccf54b14118c05436909e7037899"
    )
    assert ProjectionNodeType.GATE_DECISION not in ontology.node_types
    assert ProjectionRelationType.DECIDED_BY_GATE not in ontology.relation_types


def test_discovery_lineage_contract_is_separate_complete_and_versioned() -> None:
    ontology = discovery_lineage_ontology_v1()
    mapping = discovery_lineage_mapping_v1(ontology)
    family = discovery_lineage_family_v1(ontology, mapping)

    assert ontology.ontology_id == DISCOVERY_LINEAGE_ONTOLOGY_ID
    assert mapping.mapping_id == DISCOVERY_LINEAGE_MAPPING_ID
    assert family.family_id == DISCOVERY_LINEAGE_FAMILY_ID
    assert family.definition_version == DISCOVERY_LINEAGE_FAMILY_VERSION
    assert family.ontology_contract_digest == ontology.contract_digest
    assert family.mapping_contract_digest == mapping.contract_digest

    assert {
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
    } <= ontology.node_types
    assert {
        ProjectionRelationType.HAS_DEFINITION_VERSION,
        ProjectionRelationType.DEFINES_ITEM,
        ProjectionRelationType.REQUESTED_CHECK,
        ProjectionRelationType.ATTEMPTED_AS,
        ProjectionRelationType.PRODUCED_CHECK_OUTCOME,
        ProjectionRelationType.HAS_REVISION,
        ProjectionRelationType.HAS_REPRESENTATION,
        ProjectionRelationType.OBSERVED_AS,
        ProjectionRelationType.PRODUCED_OCCURRENCE,
        ProjectionRelationType.TRANSITION_OF_ITEM,
        ProjectionRelationType.CLASSIFIED_BY_TRANSITION,
        ProjectionRelationType.EMITTED_SIGNAL,
        ProjectionRelationType.DECIDED_BY_GATE,
        ProjectionRelationType.PROMOTED_TO_LEAD,
        ProjectionRelationType.OPENED_LEAD,
    } <= ontology.relation_types


def test_mapping_covers_exact_increment_3_authority_events() -> None:
    ontology = discovery_lineage_ontology_v1()
    mapping = discovery_lineage_mapping_v1(ontology)

    assert frozenset(item.event_type for item in mapping.mappings) == EXPECTED_EVENTS
    assert all(item.required for item in mapping.mappings)
    assert mapping.resolve("candidate.derived") is None

    for event_mapping in mapping.mappings:
        assert any(
            node.identity_source is ProjectionIdentitySource.EVENT
            and node.node_type is ProjectionNodeType.LEDGER_EVENT
            for node in event_mapping.nodes
        )
        assert ProjectionRelationType.PROJECTED_FROM_EVENT in (
            relation.relation_type for relation in event_mapping.relations
        )


def test_mapping_uses_governed_identity_fields_not_titles_locators_or_digests() -> None:
    mapping = discovery_lineage_mapping_v1(discovery_lineage_ontology_v1())
    payload_fields = {
        binding.payload_field
        for event_mapping in mapping.mappings
        for binding in event_mapping.nodes
        if binding.identity_source is ProjectionIdentitySource.PAYLOAD_FIELD
    }

    assert payload_fields == {
        "attempt_id",
        "check_outcome_id",
        "definition_id",
        "definition_version_id",
        "item_id",
        "promoting_gate_decision_id",
        "representation_id",
        "request_id",
        "revision_id",
        "signal_id",
        "transition_id",
    }
    assert not {
        "name",
        "title",
        "locator",
        "representation_digest",
        "permitted_state_digest",
        "payload_digest",
    } & payload_fields


def test_registry_composes_discovery_family_without_replacing_existing_families() -> None:
    registry = discovery_lineage_contract_registry()

    family = registry.family(DISCOVERY_LINEAGE_FAMILY_ID)
    assert family.definition_version == DISCOVERY_LINEAGE_FAMILY_VERSION
    assert registry.ontologies.resolve(DISCOVERY_LINEAGE_ONTOLOGY_ID).contract_digest == (
        family.ontology_contract_digest
    )
