"""Increment 2C requirement traceability, exclusions and deferred work."""

INCREMENT_2C_TRACEABILITY = {
    "2C-01-FIXED-NAMED-TOOL-AND-POLICY/GRAG-040-GRAG-046": (
        "newsroom.retrieval.models",
        "newsroom.retrieval.policy",
        "newsroom.authority._retrieval_security",
        "newsroom.authority._retrieval_system",
        "newsroom.tests.test_retrieval_2c_contracts",
    ),
    "2C-02-FOUR-BOUNDED-BRANCHES/GRAG-031-GRAG-034": (
        "newsroom.projection.neo4j._retrieval_adapter",
        "newsroom.retrieval.fixture_v2",
        "newsroom.tests.test_retrieval_2c_adapter_unit",
        "newsroom.tests.test_retrieval_2c_neo4j_service",
        "docs.operations.increment-2c-bounded-hybrid-retrieval",
    ),
    "2C-03-DETERMINISTIC-FUSION-AND-DEPENDENCY-DEDUP/DREC-042": (
        "newsroom.retrieval.fusion",
        "newsroom.retrieval.fixture_v2",
        "newsroom.tests.test_retrieval_2c_fusion",
        "newsroom.tests.test_retrieval_2c_contracts",
        "docs.operations.increment-2c-bounded-hybrid-retrieval",
    ),
    "2C-04-RETRIEVAL-CONTEXT-V2-SQLITE-AUTHORITY/DREC-040-DREC-042-DREC-076": (
        "newsroom.authority.retrieval_migrations",
        "newsroom.authority._retrieval_store",
        "newsroom.retrieval.models",
        "newsroom.tests.test_retrieval_2c_migrations",
        "newsroom.tests.test_retrieval_2c_authority",
    ),
    "2C-05-GOVERNED-HYDRATION-RIGHTS-AND-LIFECYCLE/GRAG-028": (
        "newsroom.authority._retrieval_system",
        "newsroom.authority._retrieval_store",
        "newsroom.authority._object_store_hydration",
        "newsroom.tests.test_retrieval_2c_authority",
        "docs.operations.increment-2c-bounded-hybrid-retrieval",
    ),
    "2C-06-ACTIVE-WATERMARK-GAP-FRESHNESS-AND-TEMPORAL-BOUNDS/GRAG-024-GRAG-025": (
        "newsroom.retrieval.policy",
        "newsroom.retrieval.fixture_v2",
        "newsroom.authority._retrieval_store",
        "newsroom.tests.test_retrieval_2c_authority",
        "newsroom.tests.test_retrieval_2c_fusion",
    ),
    "2C-07-PRIVATE-FIXED-QUERY-SECURITY/GRAG-034-GRAG-035": (
        "newsroom.projection.neo4j._retrieval_adapter",
        "newsroom.authority._retrieval_security",
        "newsroom.authority.retrieval_system",
        "newsroom.tests.test_retrieval_2c_adapter_unit",
        "newsroom.tests.test_retrieval_2c_contracts",
    ),
    "2C-08-ACTUAL-NEO4J-AND-SDLC-EVIDENCE/GRPROD-015-GRPROD-016": (
        ".github.workflows.projection-b2-neo4j",
        ".github.workflows.evidence",
        "scripts.sdlc.workflow_lane",
        "newsroom.tests.test_retrieval_2c_neo4j_service",
        "newsroom.tests.test_sdlc_watchdog",
        "newsroom.tests.test_sdlc_workflow_lane",
    ),
    "2C-09-EXPLICIT-OUTCOMES-OPERATIONS-AND-ROLLBACK/GRPROD-020-GRPROD-024": (
        "newsroom.retrieval.models",
        "newsroom.authority._retrieval_system",
        "newsroom.tests.test_retrieval_2c_authority",
        "docs.operations.increment-2c-bounded-hybrid-retrieval",
        "docs.research.2026-07-26-increment-2c-substantive-review",
    ),
}

INCREMENT_2C_EXCLUSIONS = frozenset(
    {
        "INCREMENT_2D_OR_LATER_IMPLEMENTATION",
        "CANDIDATE_ADMISSION_OR_IDENTITY_ALLOCATION",
        "ARBITRARY_CYPHER_PUBLIC_DRIVER_OR_CALLER_SELECTED_GRAPH_SCOPE",
        "GRAPHITI_EXECUTION_OR_RELATION_PROPOSAL_GENERATION",
        "EXTERNAL_MODEL_PROMPT_OR_EMBEDDING_CALL",
        "LIVE_SOURCE_RSS_JSON_BRAVE_GDELT_OR_SEARCH_EXECUTION",
        "PRODUCTION_PROTECTED_CONTENT_VECTOR_GENERATION",
        "GENERAL_PURPOSE_OR_CALLER_CONFIGURABLE_RETRIEVAL",
        "FULL_TRIAGE_WORK_ITEM_PROPOSAL_OR_EVIDENCE_INTAKE",
        "SCHEDULER_SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
        "PUBLICATION_SPENDING_OR_PUBLIC_EFFECT",
    }
)

INCREMENT_2C_DEFERRED = frozenset(
    {
        "COMPLETE_ACTUAL_NEO4J_FIXTURE_TO_CANDIDATE_PROOF_INCREMENT_2D",
        "GENERALIZED_MULTI_SOURCE_RETRIEVAL_TOOLS",
        "FINAL_PRODUCTION_FULLTEXT_VECTOR_FUSION_THRESHOLDS",
        "PRODUCTION_EMBEDDING_PROVIDER_AND_PROTECTED_CONTENT_POLICY",
        "GRAPHITI_PROPOSAL_GENERATION_AND_GENERAL_RELATION_ADMISSION_INCREMENT_4",
        "FULL_TRIAGE_WORK_ITEMS_PROPOSALS_AND_CANDIDATE_ADMISSION_INCREMENT_6",
        "EVALUATION_SHADOW_CANARY_AND_ACTIVATION_INCREMENTS_8_11",
    }
)

__all__ = [
    "INCREMENT_2C_DEFERRED",
    "INCREMENT_2C_EXCLUSIONS",
    "INCREMENT_2C_TRACEABILITY",
]
