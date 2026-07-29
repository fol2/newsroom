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
from newsroom.projection.mapping import (
    StructuralIdentityContext,
    StructuralNodeBinding,
    canonical_governed_node_id,
    canonical_identity_reference,
    canonical_node_id,
    canonical_node_identity_source,
    structural_node_identity_available,
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
        ProjectionRelationType.DUPLICATE_OF_SIGNAL,
        ProjectionRelationType.REPLACED_BY_ITEM,
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
        "basis.duplicate_signal_id",
        "definition_version_id",
        "item_id",
        "related_item_id",
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


def test_governed_identity_converges_aggregate_and_payload_references() -> None:
    aggregate = StructuralNodeBinding(
        "signal",
        ProjectionNodeType.SIGNAL,
        ProjectionIdentitySource.AGGREGATE,
        identity_namespace="signal",
    )
    reference = StructuralNodeBinding(
        "signal",
        ProjectionNodeType.SIGNAL,
        ProjectionIdentitySource.PAYLOAD_FIELD,
        "signal_id",
        identity_namespace="signal",
    )
    context = StructuralIdentityContext(
        aggregate_type="discovery_signal",
        aggregate_id="00000000-0000-4000-8000-000000007009",
        aggregate_version=1,
        event_id="00000000-0000-4000-8000-000000009001",
        payload_id="00000000-0000-4000-8000-000000009002",
        payload={"signal_id": "00000000-0000-4000-8000-000000007009"},
    )

    assert canonical_node_id(aggregate, context) == canonical_node_id(
        reference, context
    )
    assert canonical_identity_reference(
        aggregate, context
    ) == canonical_identity_reference(reference, context)
    assert canonical_node_identity_source(aggregate) == "GOVERNED_ID"
    assert canonical_node_identity_source(reference) == "GOVERNED_ID"


def test_optional_nested_governed_id_bindings_are_fail_closed_and_exact() -> None:
    mapping = discovery_lineage_mapping_v1(discovery_lineage_ontology_v1())
    gate = mapping.resolve("discovery.gate.decided")
    transition = mapping.resolve("source.observable_transition.recorded")
    assert gate is not None and transition is not None

    duplicate = next(node for node in gate.nodes if node.alias == "duplicate_signal")
    related = next(node for node in transition.nodes if node.alias == "related_item")
    assert duplicate.optional is True
    assert duplicate.payload_field == "basis.duplicate_signal_id"
    assert related.optional is True
    assert related.payload_field == "related_item_id"

    duplicate_id = "00000000-0000-4000-8000-000000007010"
    related_id = "00000000-0000-4000-8000-000000006010"
    context = StructuralIdentityContext(
        aggregate_type="discovery_gate_decision",
        aggregate_id="00000000-0000-4000-8000-000000007011",
        aggregate_version=1,
        event_id="00000000-0000-4000-8000-000000009011",
        payload_id="00000000-0000-4000-8000-000000009012",
        payload={
            "basis": {"duplicate_signal_id": duplicate_id},
            "related_item_id": related_id,
        },
    )
    assert structural_node_identity_available(duplicate, context) is True
    assert structural_node_identity_available(related, context) is True
    assert canonical_node_id(duplicate, context) == canonical_governed_node_id(
        ProjectionNodeType.SIGNAL, "signal", duplicate_id
    )
    assert canonical_node_id(related, context) == canonical_governed_node_id(
        ProjectionNodeType.SOURCE_ITEM, "source_item", related_id
    )

    absent = StructuralIdentityContext(
        aggregate_type=context.aggregate_type,
        aggregate_id=context.aggregate_id,
        aggregate_version=context.aggregate_version,
        event_id=context.event_id,
        payload_id=context.payload_id,
        payload={"basis": {"duplicate_signal_id": None}, "related_item_id": None},
    )
    assert structural_node_identity_available(duplicate, absent) is False
    assert structural_node_identity_available(related, absent) is False


def test_duplicate_and_replacement_relations_are_optional_but_allow_listed() -> None:
    mapping = discovery_lineage_mapping_v1(discovery_lineage_ontology_v1())
    gate = mapping.resolve("discovery.gate.decided")
    transition = mapping.resolve("source.observable_transition.recorded")
    assert gate is not None and transition is not None
    assert any(
        relation.relation_type is ProjectionRelationType.DUPLICATE_OF_SIGNAL
        and relation.source_alias == "signal"
        and relation.target_alias == "duplicate_signal"
        for relation in gate.relations
    )
    assert any(
        relation.relation_type is ProjectionRelationType.REPLACED_BY_ITEM
        and relation.source_alias == "item"
        and relation.target_alias == "related_item"
        for relation in transition.relations
    )


def _synthetic_batch(event_type: str, payload: dict[str, object]):
    from newsroom.authority import EventId, UtcTimestamp, digest_canonical
    from newsroom.authority._neo4j_projection_system import _build_structural_batch
    from newsroom.authority._projection_store import _ProjectionDeliverySource
    from newsroom.authority.persistence import LedgerEventRecord
    from newsroom.projection import (
        ProjectionGenerationId,
        ProjectionGenerationState,
        ProjectionGenerationView,
    )

    ontology = discovery_lineage_ontology_v1()
    mapping_contract = discovery_lineage_mapping_v1(ontology)
    family = discovery_lineage_family_v1(ontology, mapping_contract)
    mapping = mapping_contract.resolve(event_type)
    assert mapping is not None
    generation = ProjectionGenerationView(
        generation_id=ProjectionGenerationId.parse(
            "00000000-0000-4000-8000-000000009100"
        ),
        family_id=family.family_id,
        state=ProjectionGenerationState.BUILDING,
        lifecycle_version=1,
        authority_aggregate_version=1,
        validated_through_ledger_seq=None,
        created_at=UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
        updated_at=UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
    )
    event = LedgerEventRecord(
        ledger_seq=10,
        event_id="00000000-0000-4000-8000-000000009101",
        event_type=event_type,
        event_schema_version=1,
        aggregate_type="fixture_aggregate",
        aggregate_id="00000000-0000-4000-8000-000000009102",
        aggregate_version=1,
        recorded_at="2042-01-01T00:00:00.000000Z",
        command_id="00000000-0000-4000-8000-000000009103",
        producer_version="fixture-producer-v1",
        command_definition_version="fixture-command-v1",
        command_definition_digest="sha256:" + "a" * 64,
        payload_id="00000000-0000-4000-8000-000000009104",
        payload_mode="INLINE",
        payload_schema_version="fixture-schema-v1",
        payload_schema_contract_version="fixture-contract-v1",
        payload_schema_contract_digest="sha256:" + "b" * 64,
        payload_canonicalizer_version="fixture-canonicalizer-v1",
        payload_digest="sha256:" + "c" * 64,
        object_admission_id=None,
        principal_id="principal.alpha",
        authentication_context_id="00000000-0000-4000-8000-000000009105",
        authorization_request_digest="sha256:" + "d" * 64,
        authorization_decision_id="00000000-0000-4000-8000-000000009106",
        correlation_id=None,
        causation_kind=None,
        causation_identifier=None,
        causation_external_system=None,
        security_scope="authority.discovery",
        retention_scope="authority.audit",
        trust_scope="ADMITTED",
    )
    return _build_structural_batch(
        _ProjectionDeliverySource(
            generation=generation,
            family=family,
            mapping_contract=mapping_contract,
            mapping=mapping,
            policy_omitted=False,
            event=event,
            source_event_digest=digest_canonical(
                {"event": str(EventId.parse(event.event_id))}
            ),
            payload=payload,
            payload_is_mapping=True,
            tombstoned_object_admission_ids=(),
        )
    )


def test_optional_duplicate_and_replacement_relations_materialize_only_with_evidence() -> None:
    signal_id = "00000000-0000-4000-8000-000000007001"
    duplicate_id = "00000000-0000-4000-8000-000000007002"
    gate_id = "00000000-0000-4000-8000-000000007003"
    duplicate = _synthetic_batch(
        "discovery.gate.decided",
        {
            "signal_id": signal_id,
            "decision_id": gate_id,
            "basis": {"duplicate_signal_id": duplicate_id},
        },
    )
    ordinary = _synthetic_batch(
        "discovery.gate.decided",
        {
            "signal_id": signal_id,
            "decision_id": gate_id,
            "basis": {"duplicate_signal_id": None},
        },
    )
    assert sum(
        relation.relation_type is ProjectionRelationType.DUPLICATE_OF_SIGNAL
        for relation in duplicate.relations
    ) == 1
    assert not any(
        relation.relation_type is ProjectionRelationType.DUPLICATE_OF_SIGNAL
        for relation in ordinary.relations
    )

    item_id = "00000000-0000-4000-8000-000000006001"
    related_item_id = "00000000-0000-4000-8000-000000006002"
    transition_payload = {
        "item_id": item_id,
        "related_item_id": related_item_id,
        "check_outcome_id": "00000000-0000-4000-8000-000000006003",
        "transition_id": "00000000-0000-4000-8000-000000006004",
    }
    replacement = _synthetic_batch(
        "source.observable_transition.recorded", transition_payload
    )
    nonreplacement = _synthetic_batch(
        "source.observable_transition.recorded",
        {**transition_payload, "related_item_id": None},
    )
    assert sum(
        relation.relation_type is ProjectionRelationType.REPLACED_BY_ITEM
        for relation in replacement.relations
    ) == 1
    assert not any(
        relation.relation_type is ProjectionRelationType.REPLACED_BY_ITEM
        for relation in nonreplacement.relations
    )
