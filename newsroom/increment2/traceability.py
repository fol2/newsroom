"""Increment 2D requirement traceability, exclusions and deferred work."""

INCREMENT_2D_TRACEABILITY = {
    "2D-01-PUBLIC-COMPLETE-PROOF-CONTROLLER/GRPROD-015-GRPROD-016": (
        "newsroom.increment2.proof",
        "newsroom.increment2.models",
        "newsroom.authority.development_candidate_system",
        "newsroom.tests.test_increment_2d_proof_controller",
        "newsroom.tests.test_increment_2d_neo4j_service",
    ),
    "2D-02-SQLITE-CANDIDATE-AUTHORITY-AND-MINIMUM-HANDOFF/DREC-040-DREC-076": (
        "newsroom.authority.development_candidate_migrations",
        "newsroom.authority._development_candidate_store",
        "newsroom.authority._development_candidate_system",
        "newsroom.increment2.models",
        "newsroom.tests.test_increment_2d_candidate_authority",
        "newsroom.tests.test_increment_2d_migrations",
    ),
    "2D-03-AUTHENTICATED-REPLAY-COLLISION-AND-SEMANTIC-DEDUP/DREC-003-DREC-006": (
        "newsroom.authority._development_candidate_system",
        "newsroom.authority._development_candidate_store",
        "newsroom.increment2.policy",
        "newsroom.tests.test_increment_2d_candidate_authority",
        "newsroom.tests.test_increment_2d_proof_controller",
    ),
    "2D-04-COMPLETE-ACTUAL-NEO4J-FOUR-BRANCH-PROOF/GRAG-031-GRAG-040": (
        "newsroom.increment2.proof",
        "newsroom.projection.neo4j._complete_adapter",
        "newsroom.projection.neo4j._retrieval_adapter",
        "newsroom.tests.test_increment_2d_neo4j_service",
        ".github.workflows.projection-b2-neo4j",
    ),
    "2D-05-GRAPH-INDEX-GAP-AND-DEAD-LETTER-FAIL-CLOSED/GRAG-024-GRAG-025": (
        "newsroom.authority._development_candidate_store",
        "newsroom.authority._retrieval_store",
        "newsroom.tests.increment_2d_helpers",
        "newsroom.tests.test_increment_2d_candidate_authority",
        "newsroom.tests.test_increment_2d_neo4j_service",
    ),
    "2D-06-REPLACEMENT-GENERATION-RESTART-AND-AUTHORITY-ONLY-RECOVERY/GRPROD-020": (
        "newsroom.increment2.proof",
        "newsroom.authority._complete_projection_store",
        "newsroom.authority._development_candidate_store",
        "newsroom.tests.test_increment_2d_candidate_authority",
        "newsroom.tests.test_increment_2d_neo4j_service",
    ),
    "2D-07-RELATION-REVOCATION-WITHOUT-HISTORY-REWRITE/GRAG-028": (
        "newsroom.authority._relation_store",
        "newsroom.authority._development_candidate_store",
        "newsroom.tests.increment_2d_helpers",
        "newsroom.tests.test_increment_2d_candidate_authority",
        "newsroom.tests.test_increment_2d_neo4j_service",
    ),
    "2D-08-GOVERNED-DELETION-DERIVATIVE-PURGE-AND-NON-RESURRECTION/GRAG-028": (
        "newsroom.authority._object_store",
        "newsroom.authority._complete_projection_store",
        "newsroom.authority._development_candidate_store",
        "newsroom.tests.test_increment_2d_candidate_authority",
        "newsroom.tests.test_increment_2d_neo4j_service",
    ),
    "2D-09-PERMANENT-ACTUAL-SERVICE-AND-SDLC-EVIDENCE/GRPROD-015-GRPROD-024": (
        ".github.workflows.projection-b2-neo4j",
        ".github.workflows.evidence",
        "scripts.sdlc.workflow_lane",
        "newsroom.tests.test_integrated_c1_sdlc_contract",
        "newsroom.tests.test_sdlc_evidence_workflow",
        "newsroom.tests.test_sdlc_workflow_lane",
    ),
    "2D-10-OPERATIONS-TRACEABILITY-ROLLBACK-AND-INCREMENT-STOP-GATE": (
        "newsroom.increment2.traceability",
        "newsroom.tests.test_increment_2d_traceability",
        "docs.operations.increment-2d-complete-actual-neo4j-proof",
        "docs.research.2026-07-27-increment-2d-substantive-review",
        "docs.plans.2026-07-24-008-increment-2-complete-fixture-readiness",
        "docs.plans.2026-07-24-010-increments-2-11-owner-acceptance",
    ),
}

INCREMENT_2D_EXCLUSIONS = frozenset(
    {
        "INCREMENT_3_OR_LATER_IMPLEMENTATION",
        "LIVE_SOURCE_RSS_JSON_BRAVE_GDELT_OR_SEARCH_EXECUTION",
        "GRAPHITI_EXECUTION_OR_GENERAL_RELATION_PROPOSAL_GENERATION",
        "EXTERNAL_MODEL_PROMPT_OR_EMBEDDING_CALL",
        "PRODUCTION_PROTECTED_CONTENT_VECTOR_GENERATION",
        "GENERAL_PURPOSE_OR_CALLER_CONFIGURABLE_RETRIEVAL",
        "GENERALIZED_NON_FIXTURE_CANDIDATE_ADMISSION_OR_FULL_TRIAGE",
        "NEO4J_GRAPH_INDEX_OR_SCORE_AS_IDENTITY_OR_CANDIDATE_AUTHORITY",
        "CALLER_SELECTED_CYPHER_LABEL_PREDICATE_INDEX_GENERATION_OR_LIMIT",
        "SCHEDULER_SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
        "PUBLICATION_SPENDING_OR_PUBLIC_EFFECT",
    }
)

INCREMENT_2D_DEFERRED = frozenset(
    {
        "SOURCE_REGISTRY_AND_IMMUTABLE-SOURCE-IDENTITY-INCREMENT_3",
        "GENERIC-SOURCE-ADAPTERS-AND-DISCOVERY-LINEAGE-INCREMENT_3",
        "GRAPHITI-PROPOSAL-GENERATION-AND-GENERAL-RELATION-ADMISSION-INCREMENT_4",
        "PRODUCTION-EMBEDDING-PROVIDER-AND-THRESHOLDS-INCREMENT_5",
        "GENERALIZED-TRIAGE-WORK-ITEMS-PROPOSALS-AND-CANDIDATES-INCREMENT_6",
        "EVALUATION-OPERATIONS-SHADOW-CANARY-AND-ACTIVATION-INCREMENTS_8_11",
        "LIVE-PUBLICATION-SPENDING-OR-PUBLIC-EFFECT",
    }
)

__all__ = [
    "INCREMENT_2D_DEFERRED",
    "INCREMENT_2D_EXCLUSIONS",
    "INCREMENT_2D_TRACEABILITY",
]
