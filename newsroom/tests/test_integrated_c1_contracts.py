from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority import (
    AggregateId,
    EventId,
    ObjectAdmissionId,
    TrustScope,
    UtcTimestamp,
    digest_canonical,
)
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.integrated import (
    CandidateAdmissionRequest,
    CandidateRoute,
    IntegratedContractError,
    IntegratedExactIndexEntry,
    IntegratedFixtureId,
    IntegratedFixtureManifest,
    IntegratedHypothesisVersionId,
    IntegratedLeadId,
    IntegratedRetrievalContext,
    IntegratedRetrievalContextId,
    IntegratedSignalId,
    IntegratedStateError,
    IntegratedTriageProposalId,
    IntegratedUrgency,
)
from newsroom.projection import (
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionNodeType,
    ProjectionRelationType,
)
from newsroom.projection.neo4j import (
    StructuralGraphNodeView,
    StructuralGraphRelationView,
    StructuralReadAuthoritySelection,
    StructuralReadMetadata,
)


NOW = UtcTimestamp.parse("2026-07-24T08:00:00.000000Z")
FIXTURE_ID = IntegratedFixtureId.parse(
    "00000000-0000-4000-8000-000000000101"
)
SIGNAL_ID = IntegratedSignalId.parse(
    "00000000-0000-4000-8000-000000000102"
)
LEAD_ID = IntegratedLeadId.parse(
    "00000000-0000-4000-8000-000000000103"
)
HYPOTHESIS_ID = IntegratedHypothesisVersionId.parse(
    "00000000-0000-4000-8000-000000000104"
)
CONTEXT_ID = IntegratedRetrievalContextId.parse(
    "00000000-0000-4000-8000-000000000105"
)
PROPOSAL_ID = IntegratedTriageProposalId.parse(
    "00000000-0000-4000-8000-000000000106"
)
AGGREGATE_ID = AggregateId.parse("00000000-0000-4000-8000-000000000107")
EVENT_ID = EventId.parse("00000000-0000-4000-8000-000000000108")
ADMISSION_ID = ObjectAdmissionId.parse(
    "00000000-0000-4000-8000-000000000109"
)
ACCESS_ID = ObjectAccessDecisionId.parse(
    "00000000-0000-4000-8000-000000000110"
)
GENERATION_ID = ProjectionGenerationId.parse(
    "00000000-0000-4000-8000-000000000111"
)
SOURCE_DIGEST = digest_canonical({"event": str(EVENT_ID)})
PAYLOAD_DIGEST = digest_canonical({"fixture": str(FIXTURE_ID)})
ONTOLOGY_DIGEST = digest_canonical({"ontology": "v1"})
MAPPING_DIGEST = digest_canonical({"mapping": "v1"})
POLICY_DIGEST = digest_canonical({"hydration": "v1"})
QUERY_DIGEST = digest_canonical({"canonical_ids": ["aggregate", "event"]})


def manifest() -> IntegratedFixtureManifest:
    return IntegratedFixtureManifest(
        fixture_id=FIXTURE_ID,
        signal_id=SIGNAL_ID,
        lead_id=LEAD_ID,
        hypothesis_version_id=HYPOTHESIS_ID,
        coverage_basis="active_public_interest",
        geography="hong_kong",
        category="public_policy",
        urgency=IntegratedUrgency.TIME_SENSITIVE,
        hypothesis_statement=(
            "The synthetic fixture may represent a material policy development."
        ),
        hypothesis_trust_scope=TrustScope.PROPOSED,
        likely_new_information=(
            "A versioned synthetic authority record changed under a fixed fixture."
        ),
        reader_utility_basis=(
            "The fixture proves an evidence-acquisition boundary without factual use."
        ),
        uncertainties=("No real-world claim is verified.",),
        evidence_objectives=(
            "Hydrate the exact governed fixture bytes.",
            "Confirm complete authority and projection lineage.",
        ),
        policy_version="fixture_policy_v1",
        retrieval_version="integrated_retrieval_v1",
        admission_version="candidate_admission_v1",
    )


def graph_parts():
    aggregate_id = "npid:v1:authority-aggregate:fixture"
    event_id = "npid:v1:ledger-event:fixture"
    nodes = (
        StructuralGraphNodeView(
            canonical_id=aggregate_id,
            node_type=ProjectionNodeType.AUTHORITY_AGGREGATE,
            identity_source="AGGREGATE_ID",
            identity_reference_digest=digest_canonical(
                {"canonical_id": aggregate_id}
            ),
            first_ledger_seq=1,
            first_source_event_id=str(EVENT_ID),
            first_source_event_digest=SOURCE_DIGEST,
        ),
        StructuralGraphNodeView(
            canonical_id=event_id,
            node_type=ProjectionNodeType.LEDGER_EVENT,
            identity_source="EVENT_ID",
            identity_reference_digest=digest_canonical(
                {"canonical_id": event_id}
            ),
            first_ledger_seq=1,
            first_source_event_id=str(EVENT_ID),
            first_source_event_digest=SOURCE_DIGEST,
        ),
    )
    relation = StructuralGraphRelationView(
        relation_key=digest_canonical(
            {"source": aggregate_id, "target": event_id}
        ),
        relation_type=ProjectionRelationType.PROJECTED_FROM_EVENT,
        source_canonical_id=aggregate_id,
        target_canonical_id=event_id,
        ledger_seq=1,
        source_event_id=str(EVENT_ID),
        source_event_type="authority.aggregate.versioned",
        source_event_digest=SOURCE_DIGEST,
        aggregate_type="integrated_fixture",
        aggregate_id=str(AGGREGATE_ID),
        aggregate_version=1,
        payload_id="payload-integrated-fixture",
        payload_digest=PAYLOAD_DIGEST,
        object_admission_id=str(ADMISSION_ID),
        principal_id="principal.alpha",
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.protected",
        retention_scope="source.short",
        recorded_at=NOW,
    )
    index = tuple(
        IntegratedExactIndexEntry(
            canonical_id=node.canonical_id,
            node_type=node.node_type,
            first_ledger_seq=node.first_ledger_seq,
            first_source_event_id=node.first_source_event_id,
            first_source_event_digest=node.first_source_event_digest,
        )
        for node in nodes
    )
    return nodes, (relation,), index


def metadata(
    *,
    selection: StructuralReadAuthoritySelection = (
        StructuralReadAuthoritySelection.AUTHORITY_SELECTED_ACTIVE
    ),
) -> StructuralReadMetadata:
    return StructuralReadMetadata(
        family_id="native-structural",
        family_definition_version="family-v1",
        projector_version="neo4j-projector-v1",
        ontology_contract_digest=ONTOLOGY_DIGEST,
        mapping_contract_digest=MAPPING_DIGEST,
        generation_id=GENERATION_ID,
        generation_state=ProjectionGenerationState.ACTIVE,
        authority_selection=selection,
        contiguous_ledger_seq=1,
        open_gap_count=0,
        dead_letter_count=0,
        trust_scope=TrustScope.ADMITTED,
        query_valid_time=NOW,
        serving_time=NOW,
    )


def context() -> IntegratedRetrievalContext:
    nodes, relations, index = graph_parts()
    current_manifest = manifest()
    return IntegratedRetrievalContext(
        context_id=CONTEXT_ID,
        fixture_id=FIXTURE_ID,
        fixture_aggregate_id=AGGREGATE_ID,
        fixture_event_id=EVENT_ID,
        admission_id=ADMISSION_ID,
        metadata=metadata(),
        nodes=nodes,
        relations=relations,
        exact_index=index,
        hydrated_blob_digest=current_manifest.manifest_digest,
        hydration_policy_contract_digest=POLICY_DIGEST,
        hydration_access_decision_id=ACCESS_ID,
        manifest_digest=current_manifest.manifest_digest,
        retrieval_version=current_manifest.retrieval_version,
        query_digest=QUERY_DIGEST,
        known_omissions=(
            "No vector, full-text, model or live-source retrieval was executed.",
        ),
        recorded_at=NOW,
    )


def test_fixture_manifest_is_canonical_proposed_candidate_input() -> None:
    first = manifest()
    second = manifest()
    assert first.canonical_bytes == second.canonical_bytes
    assert first.manifest_digest == second.manifest_digest
    assert first.hypothesis_trust_scope is TrustScope.PROPOSED

    with pytest.raises(IntegratedContractError, match="explicitly PROPOSED"):
        replace(first, hypothesis_trust_scope=TrustScope.ADMITTED)


def test_integrated_context_requires_authority_selected_active_graph() -> None:
    current = context()
    with pytest.raises(IntegratedStateError, match="authority-selected ACTIVE"):
        replace(
            current,
            metadata=metadata(
                selection=StructuralReadAuthoritySelection.EXACT_GENERATION
            ),
        )

    with pytest.raises(IntegratedStateError, match="gaps or dead letters"):
        replace(
            current,
            metadata=replace(metadata(), open_gap_count=1),
        )


def test_integrated_context_binds_exact_index_and_object_provenance() -> None:
    current = context()
    assert {item.canonical_id for item in current.exact_index} == {
        item.canonical_id for item in current.nodes
    }
    assert any(
        relation.source_event_id == str(EVENT_ID)
        and relation.object_admission_id == str(ADMISSION_ID)
        for relation in current.relations
    )

    with pytest.raises(IntegratedContractError, match="cover"):
        replace(current, exact_index=current.exact_index[:-1])

    changed_relations = tuple(
        replace(relation, object_admission_id=None)
        for relation in current.relations
    )
    with pytest.raises(IntegratedStateError, match="event/object provenance"):
        replace(current, relations=changed_relations)


def test_context_digest_is_stable_across_access_attempt_identity() -> None:
    current = context()
    retry = replace(
        current,
        context_id=IntegratedRetrievalContextId.parse(
            "00000000-0000-4000-8000-000000000112"
        ),
        hydration_access_decision_id=ObjectAccessDecisionId.parse(
            "00000000-0000-4000-8000-000000000113"
        ),
        recorded_at=UtcTimestamp.parse("2026-07-24T08:05:00.000000Z"),
    )
    assert retry.context_digest == current.context_digest


def test_candidate_request_is_typed_and_bound_to_context_digest() -> None:
    current = context()
    request = CandidateAdmissionRequest(
        proposal_id=PROPOSAL_ID,
        route=CandidateRoute.NEW_EVENT,
        fixture_id=FIXTURE_ID,
        expected_context_digest=current.context_digest,
        idempotency_key="integrated-candidate-admission",
    )
    assert request.expected_context_digest == current.context_digest

    with pytest.raises(ValueError):
        replace(request, expected_context_digest="not-a-digest")
