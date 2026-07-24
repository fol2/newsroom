"""Increment 1B2/B3 requirement traceability, exclusions and deferrals."""

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

INCREMENT_1B3_TRACEABILITY = {
    "B3-01-AUTHORITY-OWNED-REBUILD/GRAG-024/GRAG-026": (
        "newsroom.authority._projection_store",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.tests.test_projection_b3_rebuild",
        "docs.operations.neo4j-b3-rebuild-promotion",
    ),
    "B3-02-GRAPH-LOSS-RECOVERY/GRAG-004/GRAG-056": (
        "newsroom.projection.neo4j._state",
        "newsroom.projection.neo4j._adapter",
        "newsroom.tests.test_projection_b3_reconciliation",
        "newsroom.tests.test_projection_b3_neo4j_service",
    ),
    "B3-03-GENERATION-VALIDATION/GRAG-025/GRAG-027": (
        "newsroom.authority.projection_promotion_migrations",
        "newsroom.authority._projection_store",
        "newsroom.projection.neo4j._state",
        "newsroom.tests.test_projection_b3_authority",
        "newsroom.tests.test_projection_b3_reconciliation",
    ),
    "B3-04-ATOMIC-PROMOTION-ACTIVE-SERVING/GRAG-027/GRPROD-031": (
        "newsroom.authority._projection_system",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.tests.test_projection_b3_active_serving",
        "newsroom.tests.test_projection_b3_active_serving_adversarial",
    ),
    "B3-05-TOMBSTONE-NON-RESURRECTION/GRAG-028": (
        "newsroom.projection.mapping",
        "newsroom.projection.neo4j._adapter",
        "newsroom.tests.projection_b3_tombstone_helpers",
        "newsroom.tests.test_projection_b3_tombstone",
        "newsroom.tests.test_projection_b3_neo4j_service",
    ),
    "B3-06-QUALIFYING-GRAPHRAG/GRPROD-004/GRPROD-015": (
        "newsroom.projection.neo4j.models",
        "newsroom.projection.neo4j.qualification",
        "newsroom.tests.test_projection_b3_qualification",
    ),
    "B3-07-ACTUAL-SERVICE-OPERATIONS/GRPROD-016": (
        ".github.workflows.projection-b2-neo4j",
        "scripts.sdlc.workflow_lane",
        "newsroom.tests.test_sdlc_workflow_lane",
        "newsroom.tests.test_projection_b3_neo4j_service",
        "docs.operations.neo4j-b3-rebuild-promotion",
    ),
    "B3-08-BOUNDARY-AND-EXCLUSIONS/GRAG-034/GRAG-058/GRPROD-032": (
        "newsroom.tests.test_projection_b2_boundaries",
        "newsroom.tests.test_projection_b3_qualification",
        "docs.operations.neo4j-b3-rebuild-promotion",
    ),
}

INCREMENT_1B3_EXCLUSIONS = frozenset(
    {
        "GRAPHITI_RUNTIME_EXECUTION",
        "MODEL_OR_EMBEDDING_CALLS",
        "LIVE_SOURCE_OR_SEARCH_ACCESS",
        "PROTECTED_CONTENT_VECTOR_GENERATION",
        "FINAL_VECTOR_FULL_TEXT_OR_HYBRID_RETRIEVAL",
        "ENTITY_RESOLUTION_OR_EDITORIAL_RELATION_ADMISSION",
        "FULL_CANDIDATE_TRIAGE_OR_EVIDENCE_INTAKE",
        "PUBLICATION_SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
        "SPENDING_OR_PUBLIC_EFFECTS",
        "ISSUE_82_INCREMENT_1C",
    }
)

INCREMENT_1B3_DEFERRED = frozenset(
    {
        "FINAL_NEO4J_RELEASE_PRODUCTION_ADMISSION",
        "IMMUTABLE_CONTAINER_MANIFEST_QUALIFICATION",
        "INTENDED_HARDWARE_LOAD_CAPACITY_AND_LICENCE",
        "COMMUNITY_COMPENSATING_CONTROL_OWNER_ACCEPTANCE",
        "PRODUCTION_TLS_NETWORK_SUPERVISION_CREDENTIAL_ROTATION_AND_MONITORING",
        "OFFLINE_DUMP_LOAD_BACKUP_ENCRYPTION_KEY_CUSTODY_RESTORE_RPO_RTO",
        "GRAPHITI_MODEL_PROMPT_EMBEDDING_VERSIONS_AND_EXECUTION",
        "FINAL_VECTOR_FULL_TEXT_HYBRID_THRESHOLDS_AND_BILINGUAL_QUALITY",
    }
)

__all__ = [
    "INCREMENT_1B2_DEFERRED",
    "INCREMENT_1B2_EXCLUSIONS",
    "INCREMENT_1B2_TRACEABILITY",
    "INCREMENT_1B3_DEFERRED",
    "INCREMENT_1B3_EXCLUSIONS",
    "INCREMENT_1B3_TRACEABILITY",
]
