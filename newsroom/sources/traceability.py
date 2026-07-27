"""Increment 3A requirement traceability, exclusions, and deferred work."""

INCREMENT_3A_TRACEABILITY = {
    "3A-01-STABLE-SOURCE-DEFINITION-AND-IMMUTABLE-VERSIONS/DREC-001-DREC-006-DREC-010-SRC-025-SRC-044": (
        "newsroom.sources.models",
        "newsroom.authority.source_registry_migrations",
        "newsroom.authority._source_registry_store",
        "newsroom.tests.test_source_3a_contracts",
        "newsroom.tests.test_source_3a_lifecycle_integrity",
    ),
    "3A-02-EXPLICIT-ROLE-PORTFOLIO-COVERAGE-DEPENDENCY-AND-GAPS/COV-001-COV-006-SRC-001-SRC-005-SRC-018-SRC-024": (
        "newsroom.sources.types",
        "newsroom.sources.models",
        "newsroom.authority.source_registry_migrations",
        "newsroom.tests.test_source_3a_contracts",
        "docs.operations.increment-3a-source-registry",
    ),
    "3A-03-RIGHTS-OBSERVATION-BASELINE-AND-POLICY-IDENTITIES/DREC-010-DREC-016-DREC-023-DREC-076-CHG-001-CHG-030-CHG-035": (
        "newsroom.sources.types",
        "newsroom.sources.models",
        "newsroom.sources.policy",
        "newsroom.authority._source_registry_store",
        "newsroom.tests.test_source_3a_authority",
    ),
    "3A-04-STABLE-SOURCE-ITEM-AND-LOCATOR-CONTINUITY/DREC-002-DREC-005-DREC-011-DREC-012-CHG-017": (
        "newsroom.sources.models",
        "newsroom.authority._source_registry_store",
        "newsroom.tests.test_source_3a_authority",
        "newsroom.tests.test_source_3a_lifecycle_integrity",
    ),
    "3A-05-REVISION-REPRESENTATION-OCCURRENCE-SEPARATION/DREC-013-DREC-015-DREC-022-CHG-003-CHG-011": (
        "newsroom.sources.models",
        "newsroom.authority.source_registry_migrations",
        "newsroom.authority._source_registry_store",
        "newsroom.tests.test_source_3a_authority",
        "newsroom.tests.test_source_3a_lifecycle_integrity",
    ),
    "3A-06-EXACT-TIME-PROVENANCE-TRUST-AND-PRODUCER-VERSIONS/DREC-070-DREC-074-DREC-076": (
        "newsroom.sources.types",
        "newsroom.sources.models",
        "newsroom.sources.policy",
        "newsroom.authority._source_registry_store",
        "newsroom.tests.test_source_3a_authority",
    ),
    "3A-07-AUTHENTICATED-COMMANDS-AND-REDACTED-READS/FLOW-033-FLOW-034-ADR-0001-ADR-0002": (
        "newsroom.sources.policy",
        "newsroom.authority._source_registry_system",
        "newsroom.tests.test_source_3a_authority",
        "newsroom.tests.test_source_3a_contracts",
    ),
    "3A-08-CHECKED-MIGRATION-CANONICAL-BYTES-AND-STARTUP-INTEGRITY/ADR-0001-ADR-0002-DREC-077": (
        "newsroom.authority.source_registry_migrations",
        "newsroom.authority.migrations",
        "newsroom.authority._source_registry_store",
        "newsroom.tests.test_projection_b1_migrations",
        "newsroom.tests.test_source_3a_lifecycle_integrity",
    ),
    "3A-09-IDEMPOTENCY-COLLISION-NO-REUSE-AND-EXACT-HEAD/DREC-003-DREC-004-DREC-006-SRC-025-SRC-026": (
        "newsroom.sources.models",
        "newsroom.authority._source_registry_store",
        "newsroom.tests.test_source_3a_authority",
        "docs.operations.increment-3a-source-registry",
    ),
    "3A-10-FIXTURE-AND-APPROVED-REPLAY-ONLY-BOUNDARY/SRC-020-SRC-021-GRAG-042-GRAG-045": (
        "newsroom.sources.models",
        "newsroom.sources.policy",
        "newsroom.sources.traceability",
        "newsroom.tests.test_source_3a_traceability",
        "docs.operations.increment-3a-source-registry",
    ),
    "3A-11-NO-LEGACY-RUNTIME-BYPASS-OR-SILENT-SOURCE-CHANGE/SRC-025-SRC-026-SRC-044-ADR-0004": (
        "newsroom.sources.traceability",
        "newsroom.tests.test_source_3a_traceability",
        "docs.operations.increment-3a-source-registry",
        "docs.research.2026-07-27-increment-3a-substantive-review",
    ),
    "3A-12-ROLLBACK-STOP-BOUNDARY-AND-3B-DEFERRED": (
        "newsroom.sources.traceability",
        "docs.operations.increment-3a-source-registry",
        "docs.research.2026-07-27-increment-3a-substantive-review",
        "docs.plans.2026-07-24-009-increments-3-11-readiness-ladder",
        "newsroom.tests.test_source_3a_traceability",
    ),
}

INCREMENT_3A_EXCLUSIONS = frozenset(
    {
        "INCREMENT_3B_OR_LATER_IMPLEMENTATION",
        "LIVE_SOURCE_NETWORK_REQUEST_RSS_ATOM_JSON_DOCUMENT_OR_AGENDA_FETCH",
        "SOURCE_CREDENTIAL_SECRET_OR_SCHEDULE",
        "TRANSPORT_TLS_REDIRECT_EGRESS_TIMEOUT_OR_BODY_EXECUTION",
        "PARSER_EXECUTION_OR_EXTERNAL_CONTENT_PROCESSING",
        "CHECK_REQUEST_ATTEMPT_OUTCOME_OR_BASELINE_RUNTIME_AUTHORITY",
        "SIGNAL_GATE_LEAD_WATCH_CONDITION_CANDIDATE_OR_EVIDENCE_INTAKE",
        "MODEL_GRAPHITI_EMBEDDING_SEARCH_OR_ARBITRARY_CYPHER",
        "NEO4J_SOURCE_PROJECTION_OR_PROJECTION_HEALTH",
        "SHADOW_CANARY_PRODUCTION_ACTIVATION_OR_LEGACY_RETIREMENT",
        "PUBLICATION_PUBLIC_EFFECT_OR_SPENDING",
    }
)

INCREMENT_3A_DEFERRED = frozenset(
    {
        "GENERIC_TRANSPORT_AND_PARSER_BOUNDARY_INCREMENT_3B",
        "CHECK_BASELINE_AND_OBSERVABLE_TRANSITION_AUTHORITY_INCREMENT_3C",
        "SIGNAL_GATE_AND_LEAD_FOUNDATION_INCREMENT_3D",
        "DISCOVERY_LINEAGE_PROJECTION_AND_HEALTH_INCREMENT_3E",
        "EXTRACTION_ENTITY_RESOLUTION_AND_RELATION_ADMISSION_INCREMENT_4",
        "PRODUCTION_HYBRID_RETRIEVAL_INCREMENT_5",
        "FULL_TRIAGE_AGENDA_EVALUATION_SHADOW_CANARY_AND_ACTIVATION_INCREMENTS_6_11",
    }
)


__all__ = [
    "INCREMENT_3A_DEFERRED",
    "INCREMENT_3A_EXCLUSIONS",
    "INCREMENT_3A_TRACEABILITY",
]
