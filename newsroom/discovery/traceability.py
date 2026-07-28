"""Increment 3D traceability and explicit authority exclusions."""

INCREMENT_3D_TRACEABILITY = {
    "3D-01-SIGNAL-SOURCE-BASIS/FLOW-030-FLOW-032-DREC-030-DREC-032": (
        "newsroom.discovery.models",
        "newsroom.discovery.policy",
        "newsroom.tests.test_discovery_3d_contracts",
        "newsroom.tests.test_discovery_3d_payloads",
    ),
    "3D-02-DETERMINISTIC-GATE-ORDER/FLOW-033-FLOW-037-DOUT-SIGNAL-GATE": (
        "newsroom.discovery.types",
        "newsroom.discovery.models",
        "newsroom.tests.test_discovery_3d_contracts",
    ),
    "3D-03-AMBIGUITY-PRESERVES-RECALL/FLOW-034-FLOW-035-TRI-035": (
        "newsroom.discovery.types",
        "newsroom.discovery.models",
        "newsroom.tests.test_discovery_3d_contracts",
    ),
    "3D-04-DUPLICATE-NONCHANGE-LINEAGE/FLOW-031-FLOW-036-DREC-035": (
        "newsroom.discovery.models",
        "newsroom.tests.test_discovery_3d_contracts",
    ),
    "3D-05-ONE-LEAD-PER-PROMOTED-SIGNAL/FLOW-040-DREC-033-DREC-034": (
        "newsroom.discovery.models",
        "newsroom.discovery.record_models",
        "newsroom.tests.test_discovery_3d_contracts",
    ),
    "3D-06-QUALITATIVE-URGENCY-NO-SCORE/FLOW-041-FLOW-044-DPRI": (
        "newsroom.discovery.types",
        "newsroom.discovery.models",
        "newsroom.tests.test_discovery_3d_contracts",
    ),
    "3D-07-WATCH-CONDITION-SEAM/DREC-036-DREC-037-TRI-036": (
        "newsroom.discovery.models",
        "newsroom.discovery.types",
        "newsroom.tests.test_discovery_3d_contracts",
    ),
    "3D-08-OUTCOME-REASON-ACTION-SEPARATION/DOUT-DPRI-DREC-076": (
        "newsroom.discovery.types",
        "newsroom.discovery.models",
        "newsroom.discovery.payloads",
        "newsroom.tests.test_discovery_3d_payloads",
    ),
    "3D-09-AUTHENTICATED-COMMAND-CONTRACTS/FLOW-002-DREC-070-DOPS": (
        "newsroom.discovery.policy",
        "newsroom.discovery.payloads",
        "newsroom.tests.test_discovery_3d_policy",
    ),
    "3D-10-IDEMPOTENCY-ORDERED-DECISIONS/FLOW-081-FLOW-090-FLOW-092": (
        "newsroom.discovery.models",
        "newsroom.discovery.record_models",
        "newsroom.tests.test_discovery_3d_contracts",
    ),
    "3D-11-NO-TRIAGE-CANDIDATE-EVIDENCE-BYPASS/FLOW-004-TRI-001-TRI-017": (
        "newsroom.discovery.traceability",
        "newsroom.tests.test_discovery_3d_traceability",
        "docs.research.2026-07-28-increment-3d-design-record",
    ),
    "3D-12-NO-EXTERNAL-IO-MODEL-OR-PROJECTION/FLOW-080-FLOW-086-ADR-0004": (
        "newsroom.discovery.traceability",
        "newsroom.tests.test_discovery_3d_traceability",
    ),
}

INCREMENT_3D_EXCLUSIONS = frozenset(
    {
        "REAL_NETWORK_OR_SOCKET_ACCESS",
        "NAMED_LIVE_SOURCE_OR_CREDENTIAL",
        "SCHEDULER_OR_RECURRING_TRIGGER",
        "BROWSER_COLLECTION_OR_JAVASCRIPT_EXECUTION",
        "TRIAGE_WORK_ITEM_RETRIEVAL_OR_MODEL_PROPOSAL",
        "EDITORIAL_REJECT_ASSOCIATION_OR_SUPPLEMENTAL_DISCOVERY_AUTHORITY",
        "EVENT_HYPOTHESIS_STORY_CANDIDATE_OR_EVIDENCE_HANDOFF_AUTHORITY",
        "NEO4J_DISCOVERY_LINEAGE_OR_HEALTH_INCREMENT_3E",
        "MODEL_GRAPHITI_EMBEDDING_SEARCH_OR_ARBITRARY_CYPHER",
        "NUMERIC_GLOBAL_SCORE_MEDIA_VOLUME_OR_CATEGORY_QUOTA_AUTHORITY",
        "SOURCE_SHADOW_CANARY_PRODUCTION_PUBLICATION_OR_SPENDING",
        "LEGACY_LINK_EVENT_CLUSTER_OR_IDENTITY_IMPORT",
        "FACTUAL_TRUTH_EVIDENCE_OR_PUBLICATION_AUTHORITY",
        "PUBLIC_EFFECT",
    }
)

INCREMENT_3D_DEFERRED = frozenset(
    {
        "DISCOVERY_LINEAGE_PROJECTION_AND_HEALTH_INCREMENT_3E",
        "FULL_TRIAGE_WORK_ITEMS_RETRIEVAL_AND_MODEL_PROPOSALS_LATER_INCREMENT",
        "EVENT_HYPOTHESIS_AND_CANDIDATE_AUTHORITY_LATER_INCREMENT",
        "EDITORIAL_LEAD_DISPOSITIONS_LATER_INCREMENT",
        "EXACT_QUEUE_TIMING_BATCHING_FAIRNESS_AND_NUMERIC_EXPERIMENTS",
        "APPROVED_MANUAL_READER_WEBHOOK_RADAR_AND_SEARCH_CHANNEL_INPUTS",
        "LIVE_SOURCE_QUALIFICATION_AND_PRODUCTION_OPERATION_LATER_INCREMENT",
    }
)

__all__ = [
    "INCREMENT_3D_DEFERRED",
    "INCREMENT_3D_EXCLUSIONS",
    "INCREMENT_3D_TRACEABILITY",
]
