from __future__ import annotations

from pathlib import Path

from newsroom.relations import (
    INCREMENT_2A_DEFERRED,
    INCREMENT_2A_EXCLUSIONS,
    INCREMENT_2A_TRACEABILITY,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_OPERATION_GUIDE = (
    _REPOSITORY_ROOT
    / "docs/operations/increment-2a-governed-relation-authority.md"
)
_SUBSTANTIVE_REVIEW = (
    _REPOSITORY_ROOT
    / "docs/research/2026-07-25-increment-2a-substantive-review.md"
)


def test_increment_2a_traceability_covers_issue_155_deliverables() -> None:
    expected = {
        "2A-01-TYPED-IMMUTABLE-RELATION-RECORDS/DREC-001-DREC-007",
        "2A-02-EXACT-GOVERNED-DEVELOPMENT-RELATION/TRI-041-GRAG-012-GRAG-013",
        "2A-03-AUTHENTICATED-SEPARATE-PROPOSAL-AND-ADMISSION/GRAG-011-GRAG-023",
        "2A-04-CHECKED-SQLITE-MIGRATION-AND-STARTUP-INTEGRITY/ADR-0001-ADR-0002",
        "2A-05-IDEMPOTENCY-COLLISION-CONFLICT-AND-STALE-DECISION/DREC-003-DREC-006-TRI-034-TRI-073",
        "2A-06-HOLD-REJECT-INVALIDATE-REVOKE-SUPERSEDE/DREC-073",
        "2A-07-ADMITTED-ONLY-PROJECTION-SEAM/GRAG-010-GRAG-020-GRAG-023-GRPROD-013",
        "2A-08-GOVERNED-OBJECT-RIGHTS-LIFECYCLE-AND-TOMBSTONE/GRAG-028",
        "2A-09-EXACT-PROVENANCE-TEMPORAL-AND-PRODUCER-LINKAGE/DREC-070-DREC-074-DREC-076-GRAG-030",
        "2A-10-SYNTHETIC-ENGLISH-AND-HK-TRADITIONAL-CHINESE-FIXTURE",
        "2A-11-NO-RAW-CYPHER-OR-CALLER-GRAPH-MUTATION/GRAG-034-ADR-0005",
        "2A-12-ROLLBACK-EXCLUSIONS-AND-STOP-BOUNDARY/GRPROD-020-GRPROD-023",
    }
    assert set(INCREMENT_2A_TRACEABILITY) == expected
    assert all(
        len(references) >= 5
        for references in INCREMENT_2A_TRACEABILITY.values()
    )

    flattened = {
        reference
        for references in INCREMENT_2A_TRACEABILITY.values()
        for reference in references
    }
    assert {
        "newsroom.authority._relation_store",
        "newsroom.authority._relation_system",
        "newsroom.authority.relation_migrations",
        "newsroom.fixtures.integrated_fixture_v2",
        "newsroom.relations.fixture_v2",
        "newsroom.relations.models",
        "newsroom.relations.policy",
        "newsroom.tests.test_relation_2a_authority",
        "newsroom.tests.test_relation_2a_contracts",
        "newsroom.tests.test_relation_2a_lifecycle_integrity",
        "docs.operations.increment-2a-governed-relation-authority",
        "docs.research.2026-07-25-increment-2a-substantive-review",
    } <= flattened


def test_increment_2a_exclusions_preserve_the_authorised_stop_boundary() -> None:
    assert INCREMENT_2A_EXCLUSIONS == frozenset(
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


def test_increment_2a_deferred_register_keeps_later_units_blocked() -> None:
    assert INCREMENT_2A_DEFERRED == frozenset(
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


def test_increment_2a_operations_guide_records_authority_and_rollback() -> None:
    text = _OPERATION_GUIDE.read_text(encoding="utf-8")
    for required in (
        "SQLite ledger records, immutable decisions and governed objects remain authoritative",
        "governed_relation_authority_v6",
        "governed_blob.deletion.tombstoned",
        "Proposal-only records never appear in this seam",
        "authority.relation.metadata.read",
        "authority.relation.project",
        "it never emits the earlier assertion `UPSERT` first",
        "hard current-state scan ceiling",
        "recorded strictly later in authority history",
        "exact admission time",
        "Do not perform an ad hoc down-migration",
        "Issue #156 remains blocked",
    ):
        assert required in text
    assert "arbitrary Cypher" in text
    assert "Increment 2B implementation" in text


def test_increment_2a_substantive_review_records_zero_unresolved_p1_p2() -> None:
    text = _SUBSTANTIVE_REVIEW.read_text(encoding="utf-8")
    for required in (
        "Reviewed pre-correction head: `d4877f47e9399964ebaea75bd7fc56daa09258c4`",
        "P1 findings: 0",
        "P2 findings: 8",
        "### P2-8 — Repeated fixture construction consumed the SDLC evidence margin",
        "Remaining unresolved P1/P2 after correction: 0",
        "1,031 passed, 11 skipped, 0 failed",
        "Issue #156 remains blocked",
    ):
        assert required in text
