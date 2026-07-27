"""Increment 3B requirement traceability and explicit authority exclusions."""

INCREMENT_3B_TRACEABILITY = {
    "3B-01-TYPED-FIXTURE-TRANSPORT-AND-CAPTURE/FLOW-020-FLOW-022-DREC-DOUT": (
        "newsroom.discovery_adapters.models",
        "newsroom.discovery_adapters.runner",
        "newsroom.tests.test_discovery_adapter_3b_runner",
    ),
    "3B-02-STRICT-ENDPOINT-DNS-TLS-REDIRECT/DOPS-020-DOPS-026-SRC-020-SRC-026": (
        "newsroom.discovery_adapters.security",
        "newsroom.tests.test_discovery_adapter_3b_security",
    ),
    "3B-03-BOUNDED-TIME-SIZE-ENCODING-AND-DECOMPRESSION/DOPS-020-DOPS-023": (
        "newsroom.discovery_adapters.compression",
        "newsroom.discovery_adapters.types",
        "newsroom.tests.test_discovery_adapter_3b_security",
    ),
    "3B-04-SAFE-RSS-ATOM-JSON-AND-DOCUMENT-PARSING/FLOW-013-FLOW-022-DOPS-023": (
        "newsroom.discovery_adapters.parsers",
        "newsroom.tests.test_discovery_adapter_3b_parsers",
    ),
    "3B-05-HONEST-OUTCOME-SEPARATION/FLOW-021-FLOW-023-FLOW-024-DOPS-021-DOPS-022": (
        "newsroom.discovery_adapters.runner",
        "newsroom.discovery_adapters.types",
        "newsroom.tests.test_discovery_adapter_3b_runner",
    ),
    "3B-06-EXACT-BASELINE-AND-VALIDATOR/FLOW-021-FLOW-025-DOPS-021": (
        "newsroom.discovery_adapters.models",
        "newsroom.discovery_adapters.runner",
        "newsroom.tests.test_discovery_adapter_3b_runner",
    ),
    "3B-07-REPRESENTATION-NOT-REVISION/CHG-001-CHG-019-DREC": (
        "newsroom.discovery_adapters.parsers",
        "newsroom.discovery_adapters.models",
        "newsroom.tests.test_discovery_adapter_3b_parsers",
    ),
    "3B-08-SHAPE-DRIFT-PARTIAL-AND-NO-CLEARANCE/FLOW-024-DOPS-024": (
        "newsroom.discovery_adapters.parsers",
        "newsroom.discovery_adapters.runner",
        "newsroom.tests.test_discovery_adapter_3b_parsers",
        "newsroom.tests.test_discovery_adapter_3b_runner",
    ),
    "3B-09-UNTRUSTED-CONTENT-CANNOT-ALTER-POLICY/FLOW-002-DOPS-026-ADR-0004": (
        "newsroom.discovery_adapters.models",
        "newsroom.discovery_adapters.parsers",
        "newsroom.tests.test_discovery_adapter_3b_contracts",
    ),
    "3B-10-NO-EXTERNAL-ACCESS-OR-LATER-AUTHORITY/FLOW-010-FLOW-011-ADR-0001-ADR-0002": (
        "newsroom.discovery_adapters.traceability",
        "newsroom.tests.test_discovery_adapter_3b_traceability",
        "docs.operations.increment-3b-fixture-adapters",
    ),
}

INCREMENT_3B_EXCLUSIONS = frozenset(
    {
        "REAL_NETWORK_OR_SOCKET_ACCESS",
        "NAMED_LIVE_SOURCE_OR_CREDENTIAL",
        "SCHEDULER_OR_RECURRING_TRIGGER",
        "BROWSER_ADAPTER_OR_JAVASCRIPT_EXECUTION",
        "CHECK_REQUEST_ATTEMPT_OR_OUTCOME_AUTHORITY_INCREMENT_3C",
        "BASELINE_DECISION_OR_OBSERVABLE_TRANSITION_AUTHORITY_INCREMENT_3C",
        "SIGNAL_GATE_LEAD_OR_CANDIDATE_AUTHORITY_INCREMENT_3D",
        "NEO4J_DISCOVERY_LINEAGE_OR_HEALTH_INCREMENT_3E",
        "MODEL_GRAPHITI_EMBEDDING_SEARCH_OR_ARBITRARY_CYPHER",
        "SHADOW_CANARY_PRODUCTION_PUBLICATION_SPENDING_OR_PUBLIC_EFFECT",
        "LEGACY_LINK_EVENT_CLUSTER_OR_IDENTITY_IMPORT",
    }
)

INCREMENT_3B_DEFERRED = frozenset(
    {
        "AUTHORITATIVE_CHECK_AND_BASELINE_STATE_INCREMENT_3C",
        "OPERATIONAL_FINDING_AND_RETRY_STATE_INCREMENT_3C",
        "SIGNAL_DETERMINISTIC_GATE_AND_LEAD_INCREMENT_3D",
        "DISCOVERY_LINEAGE_PROJECTION_AND_HEALTH_INCREMENT_3E",
        "LIVE_SOURCE_QUALIFICATION_AND_NUMERIC_OPERATIONAL_PROFILES_LATER_INCREMENT",
    }
)

__all__ = [
    "INCREMENT_3B_DEFERRED",
    "INCREMENT_3B_EXCLUSIONS",
    "INCREMENT_3B_TRACEABILITY",
]
