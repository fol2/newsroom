"""Increment 3E requirement traceability, exclusions, and deferred authority."""

INCREMENT_3E_TRACEABILITY = {
    "3E-01-STRUCTURAL-LINEAGE/COV-020-COV-025/FLOW-030-FLOW-040/DREC-030-DREC-035": (
        "newsroom.projection.discovery_lineage",
        "newsroom.projection.mapping",
        "newsroom.tests.test_discovery_projection_3e_contracts",
        "newsroom.tests.test_discovery_projection_3e_authority",
        "newsroom.tests.test_check_3c_model_policies",
        "newsroom.tests.test_check_3c_transitions",
        "docs.research.2026-07-29-increment-3e-design-record",
    ),
    "3E-02-ORDERED-CHECKPOINT-GAP-DEADLETTER/GRAG-024-GRAG-025": (
        "newsroom.authority._projection_store",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.tests.test_discovery_projection_3e_lifecycle",
        "docs.operations.increment-3e-discovery-lineage-health",
    ),
    "3E-03-REBUILD-RECONCILE-ACTIVATE/GRAG-026-GRAG-028": (
        "newsroom.projection.neo4j._state",
        "newsroom.projection.neo4j._adapter",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.tests.test_discovery_projection_3e_lifecycle",
        "newsroom.tests.test_discovery_projection_3e_neo4j_service",
    ),
    "3E-04-ATTRIBUTABLE-HEALTH/DOUT-001-DOUT-012/DOPS-001-DOPS-012": (
        "newsroom.projection.health",
        "newsroom.projection.neo4j.discovery_health_reads",
        "newsroom.authority._projection_store",
        "newsroom.tests.test_discovery_projection_3e_health",
        "newsroom.tests.test_discovery_projection_3e_health_authority",
    ),
    "3E-05-COVERAGE-PATH-HONESTY/COV-040-COV-045/SRC-010": (
        "newsroom.authority._projection_store",
        "newsroom.projection.health",
        "newsroom.tests.test_discovery_projection_3e_health",
        "newsroom.tests.test_discovery_projection_3e_health_authority",
        "docs.operations.increment-3e-discovery-lineage-health",
    ),
    "3E-06-BOUNDED-AUTHENTICATED-READS/GRAG-035/FLOW-001-FLOW-006": (
        "newsroom.projection.neo4j.discovery_lineage_reads",
        "newsroom.projection.neo4j.discovery_health_reads",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.tests.test_discovery_projection_3e_reads",
        "newsroom.tests.test_discovery_projection_3e_health_authority",
    ),
    "3E-07-ACTUAL-NEO4J-EVIDENCE/GRAG-042-GRAG-045": (
        ".github.workflows.projection-b2-neo4j",
        "scripts.sdlc.workflow_lane",
        "newsroom.tests.test_discovery_projection_3e_neo4j_service",
        "newsroom.tests.test_sdlc_workflow_lane",
        "docs.operations.increment-3e-discovery-lineage-health",
    ),
    "3E-08-BOUNDARY-ROLLBACK/ADR-0001-ADR-0002-ADR-0004-ADR-0005": (
        "newsroom.tests.test_discovery_projection_3e_traceability",
        "docs.research.2026-07-29-increment-3e-design-record",
        "docs.operations.increment-3e-discovery-lineage-health",
    ),
}

INCREMENT_3E_EXCLUSIONS = frozenset(
    {
        "NAMED_LIVE_SOURCE",
        "SOURCE_CREDENTIAL_OR_SCHEDULE",
        "EXTERNAL_NETWORK_OR_BROWSER_COLLECTION",
        "MODEL_GRAPHITI_EMBEDDING_OR_SEARCH_EXECUTION",
        "TRIAGE_WORK_ITEM_OR_RETRIEVAL_CONTEXT",
        "EVENT_HYPOTHESIS_CANDIDATE_OR_EVIDENCE_HANDOFF",
        "EDITORIAL_MATERIALITY_OR_REJECTION_AUTHORITY",
        "PUBLICATION_SPENDING_PRODUCTION_ACTIVATION_OR_PUBLIC_EFFECT",
        "LEGACY_LINK_EVENT_CLUSTER_IDENTITY_IMPORT",
        "ARBITRARY_CYPHER_DRIVER_OR_MUTATION_SURFACE",
    }
)

INCREMENT_3E_DEFERRED = frozenset(
    {
        "NAMED_SOURCE_ACTIVATION_AND_SHADOW_CANARY",
        "PRODUCTION_SOURCE_CREDENTIAL_AND_SCHEDULER",
        "GRAPHITI_MODEL_PROMPT_EMBEDDING_AND_COST_AUTHORITY",
        "TRIAGE_AND_CANDIDATE_AUTHORITY",
        "FINAL_PRODUCTION_NEO4J_ADMISSION",
        "PRODUCTION_SECRET_NETWORK_SUPERVISION_AND_ROTATION",
        "BACKUP_RESTORE_RPO_RTO_AND_KEY_CUSTODY",
        "FULL_LOCALITY_COVERAGE_BOUNDARY",
    }
)

__all__ = [
    "INCREMENT_3E_DEFERRED",
    "INCREMENT_3E_EXCLUSIONS",
    "INCREMENT_3E_TRACEABILITY",
]
