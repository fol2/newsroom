"""Increment 2A requirement traceability, exclusions, and deferred work."""

INCREMENT_2A_TRACEABILITY = {
    "2A-01-TYPED-IMMUTABLE-RELATION-RECORDS/DREC-001-DREC-007": (
        "newsroom.relations.models",
        "newsroom.authority.relation_migrations",
        "newsroom.authority._relation_store",
        "newsroom.tests.test_relation_2a_contracts",
        "newsroom.tests.test_relation_2a_lifecycle_integrity",
    ),
    "2A-02-EXACT-GOVERNED-DEVELOPMENT-RELATION/TRI-041-GRAG-012-GRAG-013": (
        "newsroom.fixtures.integrated_fixture_v2",
        "newsroom.relations.fixture_v2",
        "newsroom.authority._relation_store",
        "newsroom.tests.test_relation_2a_authority",
        "docs.operations.increment-2a-governed-relation-authority",
    ),
    "2A-03-AUTHENTICATED-SEPARATE-PROPOSAL-AND-ADMISSION/GRAG-011-GRAG-023": (
        "newsroom.relations.policy",
        "newsroom.authority._relation_system",
        "newsroom.authority._relation_store",
        "newsroom.tests.test_relation_2a_authority",
        "newsroom.tests.test_relation_2a_contracts",
    ),
    "2A-04-CHECKED-SQLITE-MIGRATION-AND-STARTUP-INTEGRITY/ADR-0001-ADR-0002": (
        "newsroom.authority.relation_migrations",
        "newsroom.authority.migrations",
        "newsroom.authority._relation_store",
        "newsroom.tests.test_projection_b1_migrations",
        "newsroom.tests.test_relation_2a_lifecycle_integrity",
    ),
    "2A-05-IDEMPOTENCY-COLLISION-CONFLICT-AND-STALE-DECISION/DREC-003-DREC-006-TRI-034-TRI-073": (
        "newsroom.relations.models",
        "newsroom.relations.policy",
        "newsroom.authority._relation_store",
        "newsroom.tests.test_relation_2a_authority",
        "docs.operations.increment-2a-governed-relation-authority",
    ),
    "2A-06-HOLD-REJECT-INVALIDATE-REVOKE-SUPERSEDE/DREC-073": (
        "newsroom.relations.models",
        "newsroom.authority.relation_migrations",
        "newsroom.authority._relation_store",
        "newsroom.tests.test_relation_2a_authority",
        "newsroom.tests.test_relation_2a_lifecycle_integrity",
    ),
    "2A-07-ADMITTED-ONLY-PROJECTION-SEAM/GRAG-010-GRAG-020-GRAG-023-GRPROD-013": (
        "newsroom.relations.models",
        "newsroom.authority._relation_system",
        "newsroom.authority._relation_store",
        "newsroom.tests.test_relation_2a_authority",
        "newsroom.tests.test_relation_2a_lifecycle_integrity",
    ),
    "2A-08-GOVERNED-OBJECT-RIGHTS-LIFECYCLE-AND-TOMBSTONE/GRAG-028": (
        "newsroom.authority._relation_store",
        "newsroom.authority._object_store_lifecycle",
        "newsroom.fixtures.integrated_fixture_v2",
        "newsroom.tests.test_relation_2a_authority",
        "newsroom.tests.test_relation_2a_lifecycle_integrity",
        "docs.operations.increment-2a-governed-relation-authority",
    ),
    "2A-09-EXACT-PROVENANCE-TEMPORAL-AND-PRODUCER-LINKAGE/DREC-070-DREC-074-DREC-076-GRAG-030": (
        "newsroom.relations.models",
        "newsroom.relations.fixture_v2",
        "newsroom.authority._relation_store",
        "newsroom.tests.test_relation_2a_authority",
        "newsroom.tests.test_relation_2a_lifecycle_integrity",
    ),
    "2A-10-SYNTHETIC-ENGLISH-AND-HK-TRADITIONAL-CHINESE-FIXTURE": (
        "newsroom.fixtures.integrated_fixture_v2",
        "newsroom.fixtures.integrated_fixture_v2.schema",
        "newsroom.relations.fixture_v2",
        "newsroom.tests.test_relation_2a_contracts",
        "docs.operations.increment-2a-governed-relation-authority",
    ),
    "2A-11-NO-RAW-CYPHER-OR-CALLER-GRAPH-MUTATION/GRAG-034-ADR-0005": (
        "newsroom.relations.policy",
        "newsroom.authority.relation_system",
        "newsroom.authority._relation_system",
        "newsroom.tests.test_relation_2a_contracts",
        "docs.operations.increment-2a-governed-relation-authority",
    ),
    "2A-12-ROLLBACK-EXCLUSIONS-AND-STOP-BOUNDARY/GRPROD-020-GRPROD-023": (
        "newsroom.relations.traceability",
        "docs.operations.increment-2a-governed-relation-authority",
        "docs.research.2026-07-25-increment-2a-substantive-review",
        "docs.plans.2026-07-24-008-increment-2-complete-fixture-readiness",
        "docs.plans.2026-07-24-010-increments-2-11-owner-acceptance",
        "newsroom.tests.test_relation_2a_traceability",
    ),
}

INCREMENT_2A_EXCLUSIONS = frozenset(
    {
        "INCREMENT_2B_OR_LATER_IMPLEMENTATION",
        "NEO4J_RELATION_WRITE_FULLTEXT_VECTOR_OR_INDEX_CHANGE",
        "ARBITRARY_CYPHER_OR_CALLER_SELECTED_GRAPH_MUTATION",
        "GRAPHITI_EXECUTION_OR_PROPOSAL_WORKSPACE",
        "EXTERNAL_MODEL_PROMPT_OR_EMBEDDING_CALL",
        "LIVE_SOURCE_RSS_JSON_SEARCH_BRAVE_OR_GDELT_EXECUTION",
        "GENERAL_ENTITY_RESOLUTION_MERGE_SPLIT_OR_REVERSAL",
        "HYBRID_RETRIEVAL_FUSION_OR_RETRIEVAL_CONTEXT_V2",
        "FULL_TRIAGE_CANDIDATE_OR_EVIDENCE_INTAKE",
        "SCHEDULER_SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
        "PUBLICATION_PUBLIC_EFFECT_OR_SPENDING",
    }
)

INCREMENT_2A_DEFERRED = frozenset(
    {
        "ACTUAL_NEO4J_ADMITTED_RELATION_FULLTEXT_VECTOR_PROJECTION_2B",
        "BOUNDED_HYBRID_RETRIEVAL_AND_AUTHORITATIVE_CONTEXT_2C",
        "COMPLETE_ACTUAL_NEO4J_FIXTURE_PROOF_2D",
        "GRAPHITI_AND_GENERAL_RELATION_ENTITY_ADMISSION_INCREMENT_4",
        "PRODUCTION_EMBEDDING_AND_HYBRID_THRESHOLDS_INCREMENT_5",
        "FULL_TRIAGE_HYPOTHESES_CANDIDATES_AND_HANDOFF_INCREMENT_6",
        "EVALUATION_OPERATIONS_SHADOW_CANARY_AND_ACTIVATION_INCREMENTS_8_11",
    }
)


__all__ = [
    "INCREMENT_2A_DEFERRED",
    "INCREMENT_2A_EXCLUSIONS",
    "INCREMENT_2A_TRACEABILITY",
]
