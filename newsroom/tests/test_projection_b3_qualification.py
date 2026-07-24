from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority import EventId, TrustScope, UtcTimestamp
from newsroom.authority.canonical import digest_canonical
from newsroom.projection import (
    ProjectionFamilyKind,
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionGenerationValidationView,
    ProjectionStatusMetadata,
)
from newsroom.projection.neo4j import (
    GraphRAGQualificationError,
    GraphRAGQualificationEvidence,
    GraphRAGRuntimeConfig,
    GraphRuntimeKind,
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
    Neo4jCompatibility,
    Neo4jConfigurationError,
    Neo4jProjectorConfig,
    RuntimeProfile,
    StructuralReadAuthoritySelection,
    StructuralReadMetadata,
    neo4j_compatibility_digest,
    require_qualified_graphrag,
)


NOW = UtcTimestamp.parse("2026-07-21T20:00:00.000000Z")
GENERATION_ID = ProjectionGenerationId.new()
ONTOLOGY_DIGEST = digest_canonical({"ontology": "v1"})
MAPPING_DIGEST = digest_canonical({"mapping": "v1"})
DEFINITION_DIGEST = digest_canonical({"family": "v1"})
GRAPH_DIGEST = digest_canonical({"graph": "exact"})


def config(
    *,
    profile: RuntimeProfile = RuntimeProfile.PRODUCTION,
    enabled: bool = True,
    runtime_kind: GraphRuntimeKind = GraphRuntimeKind.NATIVE_NEO4J,
    projector_config: Neo4jProjectorConfig | None = None,
) -> GraphRAGRuntimeConfig:
    return GraphRAGRuntimeConfig(
        profile,
        enabled,
        runtime_kind,
        projector_config
        if projector_config is not None
        else Neo4jProjectorConfig(
            "bolt://localhost:7687",
            "neo4j",
            "newsroom_projector",
            "disposable-secret",
        ),
    )


def evidence() -> GraphRAGQualificationEvidence:
    compatibility = Neo4jCompatibility(
        NEO4J_B2_SERVER_VERSION,
        "community",
        NEO4J_B2_DRIVER_VERSION,
    )
    compatibility_digest = neo4j_compatibility_digest(compatibility)
    status = ProjectionStatusMetadata(
        family_id="native-structural",
        family_kind=ProjectionFamilyKind.GRAPH,
        projector_version="neo4j-projector-v1",
        ontology_contract_digest=ONTOLOGY_DIGEST,
        mapping_contract_digest=MAPPING_DIGEST,
        generation_id=GENERATION_ID,
        generation_state=ProjectionGenerationState.ACTIVE,
        contiguous_ledger_seq=42,
        open_gap_count=0,
        dead_letter_count=0,
        trust_scope=TrustScope.ADMITTED,
        serving_time=NOW,
    )
    validation = ProjectionGenerationValidationView(
        validation_digest=digest_canonical({"validation": "exact"}),
        generation_id=GENERATION_ID,
        validation_version=1,
        lifecycle_version=2,
        checkpoint_ledger_seq=42,
        definition_digest=DEFINITION_DIGEST,
        ontology_contract_digest=ONTOLOGY_DIGEST,
        mapping_contract_digest=MAPPING_DIGEST,
        projector_version="neo4j-projector-v1",
        service_compatibility_digest=compatibility_digest,
        projection_state_digest=GRAPH_DIGEST,
        authority_aggregate_version=4,
        authority_event_id=EventId.new(),
        recorded_at=NOW,
    )
    metadata = StructuralReadMetadata(
        family_id="native-structural",
        family_definition_version="family-v1",
        projector_version="neo4j-projector-v1",
        ontology_contract_digest=ONTOLOGY_DIGEST,
        mapping_contract_digest=MAPPING_DIGEST,
        generation_id=GENERATION_ID,
        generation_state=ProjectionGenerationState.ACTIVE,
        authority_selection=(
            StructuralReadAuthoritySelection.AUTHORITY_SELECTED_ACTIVE
        ),
        contiguous_ledger_seq=42,
        open_gap_count=0,
        dead_letter_count=0,
        trust_scope=TrustScope.ADMITTED,
        query_valid_time=NOW,
        serving_time=NOW,
    )
    return GraphRAGQualificationEvidence(
        compatibility=compatibility,
        compatibility_digest=compatibility_digest,
        projection_state_digest=GRAPH_DIGEST,
        status=status,
        validation=validation,
        read_metadata=metadata,
        required_authority_watermark=42,
    )


@pytest.mark.parametrize(
    "profile",
    (
        RuntimeProfile.PRODUCTION,
        RuntimeProfile.EVALUATION,
        RuntimeProfile.COMPLETE_LIVE_SHADOW,
    ),
)
def test_qualifying_profiles_accept_only_exact_active_native_graph(profile) -> None:
    receipt = require_qualified_graphrag(config(profile=profile), evidence())
    assert receipt.qualifying_profile is True
    assert receipt.generation_id == GENERATION_ID
    assert receipt.authority_watermark == 42


@pytest.mark.parametrize(
    ("runtime_kind", "message"),
    (
        (GraphRuntimeKind.FAKE, "native Neo4j"),
        (GraphRuntimeKind.NO_OP, "native Neo4j"),
        (GraphRuntimeKind.IN_MEMORY, "native Neo4j"),
    ),
)
def test_qualifying_profiles_reject_graph_substitutes(runtime_kind, message) -> None:
    with pytest.raises(GraphRAGQualificationError, match=message):
        require_qualified_graphrag(config(runtime_kind=runtime_kind), evidence())


def test_qualifying_profile_rejects_disabled_or_missing_configuration() -> None:
    with pytest.raises(GraphRAGQualificationError, match="cannot disable"):
        require_qualified_graphrag(config(enabled=False), evidence())
    missing = GraphRAGRuntimeConfig(
        RuntimeProfile.PRODUCTION,
        True,
        GraphRuntimeKind.NATIVE_NEO4J,
        None,
    )
    with pytest.raises(GraphRAGQualificationError, match="authenticated"):
        require_qualified_graphrag(missing, evidence())


def test_default_administrator_cannot_form_qualifying_config() -> None:
    with pytest.raises(Neo4jConfigurationError, match="bootstrap administrator"):
        Neo4jProjectorConfig(
            "bolt://localhost:7687",
            "neo4j",
            "neo4j",
            "secret",
        )


@pytest.mark.parametrize(
    "compatibility",
    (
        Neo4jCompatibility("2026.05.0", "community", NEO4J_B2_DRIVER_VERSION),
        Neo4jCompatibility(NEO4J_B2_SERVER_VERSION, "community", "6.1.0"),
        Neo4jCompatibility(
            NEO4J_B2_SERVER_VERSION,
            "enterprise",
            NEO4J_B2_DRIVER_VERSION,
        ),
    ),
)
def test_qualifying_profile_rejects_incompatible_service_or_driver(compatibility) -> None:
    current = evidence()
    changed = replace(
        current,
        compatibility=compatibility,
        compatibility_digest=neo4j_compatibility_digest(compatibility),
    )
    with pytest.raises(GraphRAGQualificationError, match="qualified target"):
        require_qualified_graphrag(config(), changed)


def test_qualifying_profile_rejects_missing_or_non_active_generation() -> None:
    current = evidence()
    assert current.status is not None
    with pytest.raises(GraphRAGQualificationError, match="active generation"):
        require_qualified_graphrag(config(), replace(current, status=None))
    building = replace(
        current.status,
        generation_state=ProjectionGenerationState.BUILDING,
    )
    with pytest.raises(GraphRAGQualificationError, match="not ACTIVE"):
        require_qualified_graphrag(config(), replace(current, status=building))


def test_required_gap_or_dead_letter_blocks_qualification() -> None:
    current = evidence()
    assert current.status is not None
    for status, message in (
        (replace(current.status, open_gap_count=1), "gap"),
        (replace(current.status, dead_letter_count=1), "dead letter"),
    ):
        with pytest.raises(GraphRAGQualificationError, match=message):
            require_qualified_graphrag(config(), replace(current, status=status))


def test_stale_validation_or_graph_watermark_blocks_qualification() -> None:
    current = evidence()
    assert current.validation is not None
    stale = replace(current.validation, checkpoint_ledger_seq=41)
    with pytest.raises(GraphRAGQualificationError, match="validation is stale"):
        require_qualified_graphrag(config(), replace(current, validation=stale))

    behind = replace(current, required_authority_watermark=43)
    with pytest.raises(GraphRAGQualificationError, match="behind"):
        require_qualified_graphrag(config(), behind)


def test_changed_service_or_graph_digest_invalidates_validation() -> None:
    current = evidence()
    changed_service = replace(
        current,
        compatibility_digest=digest_canonical({"compatibility": "changed"}),
    )
    with pytest.raises(GraphRAGQualificationError, match="stale or inconsistent"):
        require_qualified_graphrag(config(), changed_service)

    changed_graph = replace(
        current,
        projection_state_digest=digest_canonical({"graph": "changed"}),
    )
    with pytest.raises(GraphRAGQualificationError, match="another graph state"):
        require_qualified_graphrag(config(), changed_graph)


def test_exact_generation_read_cannot_qualify_as_active_serving_evidence() -> None:
    current = evidence()
    assert current.read_metadata is not None
    exact_generation = replace(
        current.read_metadata,
        authority_selection=(
            StructuralReadAuthoritySelection.EXACT_GENERATION
        ),
    )
    with pytest.raises(
        GraphRAGQualificationError,
        match="authority-selected ACTIVE read",
    ):
        require_qualified_graphrag(
            config(), replace(current, read_metadata=exact_generation)
        )


def test_graph_read_must_match_active_authority_and_remain_non_authoritative() -> None:
    current = evidence()
    assert current.read_metadata is not None
    other_generation = replace(
        current.read_metadata,
        generation_id=ProjectionGenerationId.new(),
    )
    with pytest.raises(GraphRAGQualificationError, match="authority-selected"):
        require_qualified_graphrag(
            config(), replace(current, read_metadata=other_generation)
        )

    authoritative_claim = replace(
        current.read_metadata,
        graph_role="authoritative",
    )
    with pytest.raises(GraphRAGQualificationError, match="claims authority"):
        require_qualified_graphrag(
            config(), replace(current, read_metadata=authoritative_claim)
        )


def test_development_and_unit_profiles_are_explicitly_non_qualifying() -> None:
    empty = GraphRAGQualificationEvidence(
        compatibility=None,
        compatibility_digest=None,
        projection_state_digest=None,
        status=None,
        validation=None,
        read_metadata=None,
        required_authority_watermark=0,
    )
    for profile in (RuntimeProfile.DEVELOPMENT, RuntimeProfile.UNIT):
        receipt = require_qualified_graphrag(
            GraphRAGRuntimeConfig(
                profile,
                False,
                GraphRuntimeKind.NO_OP,
                None,
            ),
            empty,
        )
        assert receipt.qualifying_profile is False
        assert receipt.generation_id is None
