"""Increment 1C requirement traceability, exclusions and deferred work."""

INCREMENT_1C_TRACEABILITY = {
    "C1-01-AUTHENTICATED-FIXTURE-COMMAND/DREC-001-DREC-007": (
        "newsroom.integrated.policy",
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_policy",
        "newsroom.tests.test_integrated_c1_proof_integrity",
    ),
    "C1-02-SQLITE-AGGREGATE-EVENT-AUDIT/DREC-040-DREC-056": (
        "newsroom.authority.integrated_migrations",
        "newsroom.authority._integrated_store",
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_candidate_authority",
        "newsroom.tests.test_integrated_c1_integrity_faults",
        "newsroom.tests.test_integrated_c1_recovery_integrity",
    ),
    "C1-03-GOVERNED-FIXTURE-OBJECT/DREC-070-DREC-077": (
        "newsroom.authority._object_store_hydration",
        "newsroom.authority._integrated_store",
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_hydration_commit",
        "newsroom.tests.test_integrated_c1_proof_integrity",
        "newsroom.tests.test_integrated_c1_temporal_authority",
    ),
    "C1-04-STRUCTURAL-GRAPH-AND-EXACT-INDEX/GRAG-001-GRAG-016": (
        "newsroom.authority._neo4j_projection_system",
        "newsroom.authority._integrated_system",
        "newsroom.integrated.models",
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_context_semantics",
        "newsroom.tests.test_integrated_c1_derived_identity_faults",
        "newsroom.tests.test_integrated_c1_read_completeness",
        "newsroom.tests.test_integrated_c1_neo4j_service",
    ),
    "C1-05-TRUST-LABELLED-RETRIEVAL-CONTEXT/GRAG-024-GRAG-035": (
        "newsroom.authority._integrated_store",
        "newsroom.integrated.models",
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_context_history",
        "newsroom.tests.test_integrated_c1_context_integrity_faults",
        "newsroom.tests.test_integrated_c1_context_semantics",
        "newsroom.tests.test_integrated_c1_temporal_authority",
        "newsroom.tests.test_integrated_c1_temporal_integrity",
    ),
    "C1-06-AUTHORITATIVE-HYDRATION/GRAG-040-GRAG-046": (
        "newsroom.authority._object_store_hydration",
        "newsroom.authority._integrated_store",
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_hydration_commit",
        "newsroom.tests.test_integrated_c1_proof_integrity",
        "newsroom.tests.test_integrated_c1_temporal_authority",
    ),
    "C1-07-DETERMINISTIC-CANDIDATE-COLLISION-AND-IDEMPOTENCY": (
        "newsroom.authority._integrated_store",
        "newsroom.authority._integrated_system",
        "newsroom.integrated.policy",
        "newsroom.tests.test_integrated_c1_candidate_authority",
        "newsroom.tests.test_integrated_c1_integrity_faults",
        "newsroom.tests.test_integrated_c1_recovery_integrity",
    ),
    "C1-08-DESTRUCTIVE-GRAPH-LOSS-RECOVERY/GRPROD-020-GRPROD-024": (
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_neo4j_service",
        "newsroom.tests.test_integrated_c1_recovery_integrity",
        ".github.workflows.projection-b2-neo4j",
        "docs.operations.increment-1c-integrated-foundation",
    ),
    "C1-09-TOMBSTONE-NON-RESURRECTION/GRAG-028": (
        "newsroom.authority._projection_store",
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_neo4j_service",
        "newsroom.tests.test_integrated_c1_proof_integrity",
        "docs.operations.increment-1c-integrated-foundation",
    ),
    "C1-10-QUALIFYING-GRAPHRAG-NEGATIVE/GRPROD-013-GRPROD-016": (
        "newsroom.projection.neo4j.qualification",
        "newsroom.tests.test_projection_b3_qualification",
        "newsroom.tests.test_integrated_c1_candidate_authority",
        "newsroom.tests.test_integrated_c1_context_semantics",
        ".github.workflows.projection-b2-neo4j",
    ),
    "C1-11-NO-GRAPH-FREE-PASSING-VARIANT/ADR-0005": (
        "newsroom.authority._integrated_system",
        "newsroom.integrated.proof",
        "newsroom.tests.test_integrated_c1_candidate_authority",
        "newsroom.tests.test_integrated_c1_read_completeness",
        "newsroom.tests.test_integrated_c1_neo4j_service",
    ),
    "C1-12-OPERATING-EVIDENCE-AND-FIXED-BOUNDARIES/GRPROD-031-GRPROD-032": (
        ".github.workflows.projection-b2-neo4j",
        "docs.operations.increment-1c-integrated-foundation",
        "newsroom.integrated.traceability",
        "newsroom.tests.test_integrated_c1_sdlc_contract",
        "newsroom.tests.test_integrated_c1_traceability",
        "newsroom.tests.test_integrated_c1_workflow_contract",
        "scripts.sdlc.classify_change",
        "scripts.sdlc.workflow_lane",
    ),
}

INCREMENT_1C_EXCLUSIONS = frozenset(
    {
        "LIVE_SOURCE_RSS_SEARCH_GDELT_OR_BRAVE_EXECUTION",
        "GRAPHITI_EXECUTION",
        "MODEL_OR_EMBEDDING_CALLS",
        "PRODUCTION_VECTOR_GENERATION",
        "COMPLETE_ENTITY_RESOLUTION",
        "EDITORIAL_RELATION_ADMISSION",
        "FULL_TRIAGE_EVENT_HYPOTHESIS_OR_EVIDENCE_INTAKE",
        "PUBLICATION_BUNDLE_OR_TARGET_OPERATIONS",
        "TARGET_CREDENTIALS",
        "BACKGROUND_SCHEDULER",
        "SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
        "SPENDING_OR_PUBLIC_EFFECTS",
    }
)

INCREMENT_1C_DEFERRED = frozenset(
    {
        "PRODUCTION_SOURCES_AND_SOURCE_RIGHTS_APPROVALS",
        "GRAPHITI_MODEL_PROMPT_AND_EMBEDDING_VERSIONS",
        "FULL_ENTITY_RESOLUTION_AND_EDITORIAL_RELATION_ADMISSION",
        "PRODUCTION_HYBRID_RETRIEVAL_QUALITY_AND_THRESHOLDS",
        "EVIDENCE_INTAKE_TRANSPORT",
        "EVALUATION_PLAN_AND_OPERATIONAL_ADMISSION",
        "SHADOW_CANARY_AND_PRODUCTION_ACTIVATION",
        "INTENDED_HARDWARE_PERFORMANCE_CAPACITY_LICENCE_AND_RECOVERY",
    }
)


__all__ = [
    "INCREMENT_1C_DEFERRED",
    "INCREMENT_1C_EXCLUSIONS",
    "INCREMENT_1C_TRACEABILITY",
]
