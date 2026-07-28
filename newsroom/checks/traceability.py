"""Increment 3C requirement traceability and explicit authority exclusions."""

INCREMENT_3C_TRACEABILITY = {
    "3C-01-CHECK-REQUEST-ATTEMPT-OUTCOME/FLOW-010-FLOW-024-DREC-010-DREC-014": (
        "newsroom.checks.check_models",
        "newsroom.checks.policy",
        "newsroom.tests.test_check_3c_contracts",
    ),
    "3C-02-EXACT-VERSION-RIGHTS-COVERAGE/FLOW-001-FLOW-005-FLOW-011-FLOW-012": (
        "newsroom.checks.check_models",
        "newsroom.checks.types",
        "newsroom.tests.test_check_3c_contracts",
    ),
    "3C-03-SOURCE-ITEM-REVISION-REPRESENTATION-OCCURRENCE/DREC-001-DREC-023-CHG-001-CHG-006": (
        "newsroom.checks.check_models",
        "newsroom.checks.transition_models",
        "newsroom.authority.proposal_admission",
        "newsroom.tests.test_check_3c_admission",
    ),
    "3C-04-EXPLICIT-BASELINE-DECISIONS/FLOW-025-DREC-060-DREC-061-CHG-024-CHG-026": (
        "newsroom.checks.baseline_models",
        "newsroom.checks.transition_planning",
        "newsroom.tests.test_check_3c_baselines",
        "newsroom.tests.test_check_3c_model_policies",
    ),
    "3C-05-OBSERVABLE-TRANSITION-CATALOGUE/CHG-007-CHG-023-CHG-030-CHG-045": (
        "newsroom.checks.transition_models",
        "newsroom.checks.transition_planning",
        "newsroom.tests.test_check_3c_transitions",
        "newsroom.tests.test_check_3c_model_policies",
    ),
    "3C-06-COMPLETE-SNAPSHOT-ABSENCE-GUARD/CHG-013-CHG-018-DOPS-021-DOPS-024": (
        "newsroom.checks.baseline_models",
        "newsroom.checks.transition_models",
        "newsroom.authority.proposal_admission_decisions",
        "newsroom.tests.test_check_3c_model_policies",
    ),
    "3C-07-PLANNED-AGENDA-EXPECTATION-ONLY/AGEN-001-AGEN-016-FLOW-014": (
        "newsroom.checks.baseline_models",
        "newsroom.checks.transition_models",
        "newsroom.authority.proposal_admission_decisions",
        "newsroom.tests.test_check_3c_agenda",
        "newsroom.tests.test_check_3c_model_policies",
    ),
    "3C-08-OPERATIONAL-FINDING-SEPARATION/FLOW-012-FLOW-023-FLOW-024-DOPS-010-DOPS-037": (
        "newsroom.checks.finding_models",
        "newsroom.authority.proposal_admission_findings",
        "newsroom.tests.test_check_3c_findings",
        "newsroom.tests.test_check_3c_admission_findings",
    ),
    "3C-09-IDEMPOTENCY-REPLAY-CONCURRENCY/DREC-070-DREC-077-FLOW-031-FLOW-032": (
        "newsroom.checks.check_models",
        "newsroom.checks.baseline_models",
        "newsroom.checks.transition_models",
        "newsroom.authority.proposal_admission_commit",
        "newsroom.tests.test_check_3c_concurrency",
    ),
    "3C-10-SOURCE-OBSERVATION-RECORD-TIME-SEPARATION/DREC-021-DREC-023-CHG-034-CHG-036": (
        "newsroom.checks.transition_models",
        "newsroom.tests.test_check_3c_transitions",
    ),
    "3C-11-NO-SIGNAL-LEAD-EDITORIAL-AUTHORITY/FLOW-002-FLOW-004-FLOW-030-FLOW-037-ADR-0004": (
        "newsroom.checks.traceability",
        "newsroom.tests.test_check_3c_traceability",
        "docs.research.2026-07-27-increment-3c-design-record",
    ),
    "3C-12-CHECKED-SCHEMA-TAMPER-STARTUP-INTEGRITY/DREC-070-DREC-077-DOPS-047-DOPS-050": (
        "newsroom.authority.check_migrations",
        "newsroom.authority.check_store",
        "newsroom.tests.test_check_3c_migrations",
        "newsroom.tests.test_check_3c_authority_integrity",
    ),
    "3C-13-AUTHENTICATED-COMMANDS-AND-REDACTED-READS/DOUT-DOPS-067-DOPS-068": (
        "newsroom.checks.policy",
        "newsroom.checks.types",
        "newsroom.authority.check_system",
        "newsroom.tests.test_check_3c_authority_store",
        "newsroom.tests.test_check_3c_authority_integrity",
    ),
}

INCREMENT_3C_EXCLUSIONS = frozenset(
    {
        "REAL_NETWORK_OR_SOCKET_ACCESS",
        "NAMED_LIVE_SOURCE_OR_CREDENTIAL",
        "SCHEDULER_OR_RECURRING_TRIGGER",
        "BROWSER_COLLECTION_OR_JAVASCRIPT_EXECUTION",
        "DISCOVERY_SIGNAL_GATE_OR_LEAD_AUTHORITY_INCREMENT_3D",
        "STORY_CANDIDATE_OR_EVIDENCE_AUTHORITY",
        "NEO4J_DISCOVERY_LINEAGE_OR_HEALTH_INCREMENT_3E",
        "MODEL_GRAPHITI_EMBEDDING_SEARCH_OR_ARBITRARY_CYPHER",
        "SOURCE_SHADOW_CANARY_PRODUCTION_PUBLICATION_OR_SPENDING",
        "LEGACY_LINK_EVENT_CLUSTER_OR_IDENTITY_IMPORT",
        "EDITORIAL_MATERIALITY_TRUTH_OR_NEWSWORTHINESS_DECISION",
        "PUBLIC_EFFECT",
    }
)

INCREMENT_3C_DEFERRED = frozenset(
    {
        "DISCOVERY_SIGNAL_ADMISSION_INCREMENT_3D",
        "DETERMINISTIC_GATE_DECISIONS_INCREMENT_3D",
        "NEWS_LEAD_URGENCY_AND_WATCH_CONDITIONS_INCREMENT_3D",
        "DISCOVERY_LINEAGE_PROJECTION_AND_HEALTH_INCREMENT_3E",
        "LIVE_SOURCE_QUALIFICATION_AND_NUMERIC_OPERATIONAL_PROFILES_LATER_INCREMENT",
        "PRODUCTION_SCHEDULER_RETRY_CIRCUIT_AND_CANARY_LATER_INCREMENT",
    }
)

__all__ = [
    "INCREMENT_3C_DEFERRED",
    "INCREMENT_3C_EXCLUSIONS",
    "INCREMENT_3C_TRACEABILITY",
]
