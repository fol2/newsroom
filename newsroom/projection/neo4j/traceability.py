"""Increment 1B2 requirement-to-module traceability and retained exclusions."""

INCREMENT_1B2_TRACEABILITY = {
    "GRAG-001": (
        "newsroom.projection.neo4j.models",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.tests.test_projection_b2_contracts",
    ),
    "GRAG-004-GRAG-006": (
        "newsroom.projection.neo4j._adapter",
        "newsroom.tests.test_projection_b2_adapter_unit",
    ),
    "GRAG-010-GRAG-016": (
        "newsroom.authority._projection_store",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.tests.test_projection_b2_authority",
    ),
    "GRAG-020-GRAG-028": (
        "newsroom.projection.mapping",
        "newsroom.projection.neo4j._adapter",
        "newsroom.tests.test_projection_b2_contracts",
    ),
    "GRAG-030": (
        "newsroom.projection.neo4j.models",
        "newsroom.authority._neo4j_projection_system",
    ),
    "GRAG-034-GRAG-035": (
        "newsroom.tests.test_projection_b2_boundaries",
        "docs.operations.neo4j-b2-qualification",
    ),
    "GRAG-042-GRAG-046": (
        "newsroom.projection.neo4j._adapter",
        "newsroom.tests.test_projection_b2_neo4j_service",
    ),
    "GRAG-050-GRAG-058": (
        ".github.workflows.projection-b2-neo4j",
        "newsroom.tests.test_projection_b2_neo4j_service",
    ),
    "GRPROD-001-GRPROD-005": (
        "docs.operations.neo4j-b2-qualification",
        ".github.workflows.projection-b2-neo4j",
    ),
    "GRPROD-010-GRPROD-016": (
        "newsroom.projection.neo4j.models",
        "newsroom.projection.neo4j._adapter",
        "newsroom.tests.test_projection_b2_boundaries",
    ),
    "GRPROD-020-GRPROD-024": (
        "newsroom.authority._neo4j_projection_system",
        "newsroom.tests.test_projection_b2_authority",
    ),
    "GRPROD-031-GRPROD-032": (
        "docs.operations.neo4j-b2-qualification",
        "newsroom.tests.test_projection_b2_neo4j_service",
    ),
}

INCREMENT_1B2_EXCLUSIONS = frozenset(
    {
        "GRAPHITI_EXECUTION",
        "MODEL_OR_EMBEDDING_CALLS",
        "LIVE_SOURCE_ACCESS",
        "PROTECTED_CONTENT_VECTOR_GENERATION",
        "FULL_TEXT_VECTOR_OR_HYBRID_RETRIEVAL",
        "ENTITY_OR_EDITORIAL_RELATION_ADMISSION",
        "CANDIDATE_TRIAGE_OR_EVIDENCE_INTAKE",
        "PUBLICATION_SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
        "SPENDING_OR_PUBLIC_EFFECTS",
        "B3_DESTRUCTIVE_REBUILD_AND_GENERATION_PROMOTION",
    }
)

INCREMENT_1B2_DEFERRED = frozenset(
    {
        "FINAL_NEO4J_RELEASE_PRODUCTION_ADMISSION",
        "IMMUTABLE_CONTAINER_MANIFEST_QUALIFICATION",
        "COMMUNITY_FINE_GRAINED_CONTROL_COMPENSATION",
        "PRODUCTION_SECRET_NETWORK_AND_PROCESS_IDENTITY",
        "INTENDED_HARDWARE_LOAD_CAPACITY_AND_LICENCE",
        "BACKUP_RESTORE_RPO_RTO_AND_KEY_CUSTODY",
        "GRAPHITI_MODEL_PROMPT_AND_EMBEDDING_VERSIONS",
        "VECTOR_FULL_TEXT_AND_HYBRID_THRESHOLDS",
    }
)

__all__ = [
    "INCREMENT_1B2_DEFERRED",
    "INCREMENT_1B2_EXCLUSIONS",
    "INCREMENT_1B2_TRACEABILITY",
]
