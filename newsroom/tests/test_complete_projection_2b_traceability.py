from __future__ import annotations

from pathlib import Path

from newsroom.projection.neo4j import (
    INCREMENT_2B_DEFERRED,
    INCREMENT_2B_EXCLUSIONS,
    INCREMENT_2B_TRACEABILITY,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_OPERATION_GUIDE = (
    _REPOSITORY_ROOT / "docs/operations/increment-2b-complete-projection.md"
)
_SUBSTANTIVE_REVIEW = (
    _REPOSITORY_ROOT
    / "docs/research/2026-07-25-increment-2b-substantive-review.md"
)


def test_increment_2b_traceability_covers_every_authorised_deliverable() -> None:
    expected = {
        "2B-01-COMPLETE-GENERATION-CONTRACTS/GRAG-024/GRAG-027/GRPROD-013",
        "2B-02-CHECKED-SQLITE-AUTHORITY/GRAG-024/GRAG-025/GRAG-027",
        "2B-03-FIXED-PRIVATE-NEO4J-ADAPTER/GRAG-034/GRPROD-013/GRPROD-015",
        "2B-04-BILINGUAL-FULLTEXT-AND-DETERMINISTIC-VECTOR/GRAG-031",
        "2B-05-ORDERED-IDEMPOTENT-DELIVERY-GAPS-DEADLETTERS/GRAG-024/GRAG-025",
        "2B-06-COMPLETE-RECONCILIATION-VALIDATION-PROMOTION/GRAG-027/GRPROD-015",
        "2B-07-ATOMIC-SOURCE-WATERMARK-GUARD/GRAG-025/GRAG-043",
        "2B-08-RAW-AND-NORMALIZED-FULLTEXT-EVIDENCE/GRAG-031/GRPROD-016",
        "2B-09-VECTOR-DIMENSION-SIMILARITY-PROVIDER-EVIDENCE/GRAG-031/GRPROD-015",
        "2B-10-RIGHTS-REVOCATION-DELETION-TOMBSTONE/GRAG-028",
        "2B-11-AUTHENTICATED-ACTUAL-SERVICE-EVIDENCE/GRPROD-016",
        "2B-12-EXCLUSIONS-ROLLBACK-STOP-BOUNDARY/GRAG-034/GRPROD-024",
    }
    assert set(INCREMENT_2B_TRACEABILITY) == expected
    assert all(len(references) >= 5 for references in INCREMENT_2B_TRACEABILITY.values())

    flattened = {
        reference
        for references in INCREMENT_2B_TRACEABILITY.values()
        for reference in references
    }
    assert {
        ".github.workflows.projection-b2-neo4j",
        "docs.operations.increment-2b-complete-projection",
        "docs.research.2026-07-25-increment-2b-substantive-review",
        "newsroom.authority._complete_projection_system",
        "newsroom.authority._projection_store",
        "newsroom.projection.fixture_v2_projection",
        "newsroom.projection.neo4j._complete_adapter",
        "newsroom.tests.test_complete_projection_2b_authority",
        "newsroom.tests.test_complete_projection_2b_neo4j_service",
    } <= flattened


def test_increment_2b_exclusions_preserve_the_stop_boundary() -> None:
    assert INCREMENT_2B_EXCLUSIONS == frozenset(
        {
            "INCREMENT_2C_OR_LATER_IMPLEMENTATION",
            "PUBLIC_DRIVER_ARBITRARY_CYPHER_OR_CALLER_SELECTED_GRAPH_MUTATION",
            "CALLER_DEFINED_LABEL_RELATIONSHIP_INDEX_OR_ADMINISTRATION",
            "GRAPHITI_RUNTIME_EXECUTION",
            "EXTERNAL_MODEL_PROMPT_OR_EMBEDDING_CALL",
            "LIVE_SOURCE_RSS_JSON_SEARCH_BRAVE_OR_GDELT_EXECUTION",
            "PRODUCTION_PROTECTED_CONTENT_VECTOR_GENERATION",
            "HYBRID_RETRIEVAL_FUSION_OR_RETRIEVAL_CONTEXT_V2",
            "FULL_TRIAGE_CANDIDATE_OR_EVIDENCE_INTAKE",
            "SCHEDULER_SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
            "PUBLICATION_SPENDING_OR_PUBLIC_EFFECT",
        }
    )


def test_increment_2b_deferred_register_keeps_later_units_blocked() -> None:
    assert INCREMENT_2B_DEFERRED == frozenset(
        {
            "BOUNDED_HYBRID_RETRIEVAL_AND_AUTHORITATIVE_CONTEXT_INCREMENT_2C",
            "COMPLETE_ACTUAL_NEO4J_FIXTURE_PROOF_INCREMENT_2D",
            "SOURCE_ADAPTERS_AND_DISCOVERY_LINEAGE_INCREMENT_3",
            "GRAPHITI_ENTITY_RESOLUTION_AND_GENERIC_RELATION_ADMISSION_INCREMENT_4",
            "PRODUCTION_EMBEDDING_PROVIDER_AND_RETRIEVAL_THRESHOLDS_INCREMENT_5",
            "FULL_TRIAGE_HYPOTHESES_CANDIDATES_AND_HANDOFF_INCREMENT_6",
            "EVALUATION_OPERATIONS_SHADOW_CANARY_AND_ACTIVATION_INCREMENTS_8_11",
        }
    )


def test_increment_2b_operations_record_authority_queries_and_rollback() -> None:
    text = _OPERATION_GUIDE.read_text(encoding="utf-8")
    for required in (
        "SQLite ledger records, immutable decisions and governed objects remain authoritative",
        "Every retained full-text query executes twice",
        "an atomic `BEGIN IMMEDIATE` SQLite comparison",
        "Never perform graph-to-ledger recovery",
        "runtime-generated masked credentials",
        "runner-loopback Bolt exposure",
        "Issue #157 remains blocked",
        "No caller supplies Cypher",
        "no external embedding provider or model call",
        "The accepted deterministic core lane remains a complete repository suite",
        "optional only in that no-service lane",
        "NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED=1",
    ):
        assert required in text


def test_increment_2b_review_records_zero_unresolved_p1_p2() -> None:
    text = _SUBSTANTIVE_REVIEW.read_text(encoding="utf-8")
    for required in (
        "P1 findings: 1",
        "P2 findings: 10",
        "Remaining unresolved P1/P2 after correction: 0",
        "A source event could arrive during reconciliation",
        "The normalized full-text query contract was retained but not executed",
        "The authority boundary trusted adapter query evidence completeness",
        "Startup integrity did not compare every normalized contract column",
        "Deterministic core evidence exceeded the accepted lane budget",
        "Complete actual-service cases were not optional in the deterministic core manifest",
        "The SDLC service lane selected complete tests without enabling them",
        "1,094 passed, 19 skipped, 0 failed",
        "Issue #157 remains blocked",
    ):
        assert required in text
