from __future__ import annotations

from pathlib import Path

from newsroom.projection.neo4j import (
    INCREMENT_1B3_DEFERRED,
    INCREMENT_1B3_EXCLUSIONS,
    INCREMENT_1B3_TRACEABILITY,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_OPERATION_GUIDE = (
    _REPOSITORY_ROOT / "docs/operations/neo4j-b3-rebuild-promotion.md"
)


def test_b3_traceability_covers_every_accepted_deliverable() -> None:
    expected = {
        "B3-01-AUTHORITY-OWNED-REBUILD/GRAG-024/GRAG-026",
        "B3-02-GRAPH-LOSS-RECOVERY/GRAG-004/GRAG-056",
        "B3-03-GENERATION-VALIDATION/GRAG-025/GRAG-027",
        "B3-04-ATOMIC-PROMOTION-ACTIVE-SERVING/GRAG-027/GRPROD-031",
        "B3-05-TOMBSTONE-NON-RESURRECTION/GRAG-028",
        "B3-06-QUALIFYING-GRAPHRAG/GRPROD-004/GRPROD-015",
        "B3-07-ACTUAL-SERVICE-OPERATIONS/GRPROD-016",
        "B3-08-BOUNDARY-AND-EXCLUSIONS/GRAG-034/GRAG-058/GRPROD-032",
    }
    assert set(INCREMENT_1B3_TRACEABILITY) == expected
    assert all(len(references) >= 3 for references in INCREMENT_1B3_TRACEABILITY.values())

    flattened = {
        reference
        for references in INCREMENT_1B3_TRACEABILITY.values()
        for reference in references
    }
    assert {
        ".github.workflows.projection-b2-neo4j",
        "docs.operations.neo4j-b3-rebuild-promotion",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.authority._projection_store",
        "newsroom.projection.neo4j._adapter",
        "newsroom.projection.neo4j._state",
        "newsroom.projection.neo4j.qualification",
        "newsroom.tests.test_projection_b3_active_serving_adversarial",
        "newsroom.tests.test_projection_b3_neo4j_service",
        "newsroom.tests.test_projection_b3_reconciliation",
        "newsroom.tests.test_projection_b3_tombstone",
        "scripts.sdlc.workflow_lane",
    } <= flattened


def test_b3_exclusions_preserve_the_fixed_scope_boundary() -> None:
    assert INCREMENT_1B3_EXCLUSIONS == frozenset(
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


def test_b3_deferred_register_does_not_overclaim_production_admission() -> None:
    assert INCREMENT_1B3_DEFERRED == frozenset(
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


def test_b3_operation_guide_preserves_authority_recovery_and_serving_rules() -> None:
    text = _OPERATION_GUIDE.read_text(encoding="utf-8")
    required = (
        "SQLite ledger records and governed-object decisions are authoritative",
        "Never perform graph-to-ledger recovery",
        "Graph loss or tampering after validation therefore blocks promotion",
        "Do not directly reactivate a `RETIRED` generation",
        "AUTHORITY_SELECTED_ACTIVE",
        "EXACT_GENERATION",
        "Until this active revalidation succeeds, qualifying GraphRAG must fail closed",
        "runtime-generated masked credentials",
        "runner-loopback Bolt exposure",
        "No live source access",
    )
    for statement in required:
        assert statement in text
