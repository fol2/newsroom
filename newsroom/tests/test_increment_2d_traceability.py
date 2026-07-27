from __future__ import annotations

from pathlib import Path

from newsroom.increment2 import (
    INCREMENT_2D_DEFERRED,
    INCREMENT_2D_EXCLUSIONS,
    INCREMENT_2D_TRACEABILITY,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_OPERATION_GUIDE = (
    _REPOSITORY_ROOT
    / "docs/operations/increment-2d-complete-actual-neo4j-proof.md"
)
_SUBSTANTIVE_REVIEW = (
    _REPOSITORY_ROOT
    / "docs/research/2026-07-27-increment-2d-substantive-review.md"
)


def test_increment_2d_traceability_covers_every_authorised_deliverable() -> None:
    expected = {
        "2D-01-PUBLIC-COMPLETE-PROOF-CONTROLLER/GRPROD-015-GRPROD-016",
        "2D-02-SQLITE-CANDIDATE-AUTHORITY-AND-MINIMUM-HANDOFF/DREC-040-DREC-076",
        "2D-03-AUTHENTICATED-REPLAY-COLLISION-AND-SEMANTIC-DEDUP/DREC-003-DREC-006",
        "2D-04-COMPLETE-ACTUAL-NEO4J-FOUR-BRANCH-PROOF/GRAG-031-GRAG-040",
        "2D-05-GRAPH-INDEX-GAP-AND-DEAD-LETTER-FAIL-CLOSED/GRAG-024-GRAG-025",
        "2D-06-REPLACEMENT-GENERATION-RESTART-AND-AUTHORITY-ONLY-RECOVERY/GRPROD-020",
        "2D-07-RELATION-REVOCATION-WITHOUT-HISTORY-REWRITE/GRAG-028",
        "2D-08-GOVERNED-DELETION-DERIVATIVE-PURGE-AND-NON-RESURRECTION/GRAG-028",
        "2D-09-PERMANENT-ACTUAL-SERVICE-AND-SDLC-EVIDENCE/GRPROD-015-GRPROD-024",
        "2D-10-OPERATIONS-TRACEABILITY-ROLLBACK-AND-INCREMENT-STOP-GATE",
    }
    assert set(INCREMENT_2D_TRACEABILITY) == expected
    assert all(len(refs) >= 5 for refs in INCREMENT_2D_TRACEABILITY.values())
    flattened = {
        ref
        for references in INCREMENT_2D_TRACEABILITY.values()
        for ref in references
    }
    assert {
        ".github.workflows.evidence",
        ".github.workflows.projection-b2-neo4j",
        "docs.operations.increment-2d-complete-actual-neo4j-proof",
        "docs.research.2026-07-27-increment-2d-substantive-review",
        "newsroom.authority._development_candidate_store",
        "newsroom.authority.development_candidate_migrations",
        "newsroom.increment2.proof",
        "newsroom.tests.test_increment_2d_candidate_authority",
        "newsroom.tests.test_increment_2d_neo4j_service",
        "scripts.sdlc.workflow_lane",
    } <= flattened


def test_increment_2d_exclusions_preserve_increment_3_stop_boundary() -> None:
    assert INCREMENT_2D_EXCLUSIONS == frozenset(
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


def test_increment_2d_deferred_register_keeps_later_work_blocked() -> None:
    assert INCREMENT_2D_DEFERRED == frozenset(
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


def test_increment_2d_operations_record_authority_and_rollback() -> None:
    text = _OPERATION_GUIDE.read_text(encoding="utf-8")
    for required in (
        "SQLite ledger records, immutable relation and Candidate decisions, governed objects and retained Retrieval Contexts remain authoritative",
        "schema version `9`",
        "hypothesis remains `PROPOSED`",
        "Exact replay creates no duplicate event, Candidate, Candidate Version or decision",
        "Candidate admission therefore cannot make its own source context stale",
        "requires exactly these Increment 2D cases without skip, failure or error",
        "Revoking the admitted `DEVELOPMENT_OF` relation does not mutate or delete the Candidate",
        "delivery removes the passage derivative from the active generation",
        "zero open required gaps and zero dead letters",
        "It independently derives first-admission versus later-deduplication order",
        "do not delete migration rows",
        "Do not start Increment 3 issue #143",
    ):
        assert required in text


def test_increment_2d_review_records_zero_unresolved_p1_p2() -> None:
    text = _SUBSTANTIVE_REVIEW.read_text(encoding="utf-8")
    for required in (
        "P1 findings: 0",
        "P2 findings: 14",
        "Remaining unresolved P1/P2 after correction: 0",
        "The Candidate fixture initially lacked the minimum development handoff",
        "The complete proof was test composition rather than a public bounded controller",
        "Graph, full-text and vector loss were not tested at the integrated Candidate boundary",
        "Tombstone evidence did not directly prove derivative purge",
        "Proposal-only relation exclusion was inferred rather than retained",
        "normalized Candidate tamper regression stopped at schema fingerprint validation",
        "Complete proof preparation did not use the caller-supplied authentication proof",
        "Candidate decision reads used the broader integrated security scope",
        "Candidate restart integrity did not independently bind chronology and command payload",
        "Actual-service preparation supplied the fixture alias instead of its canonical identity",
        "1,208 passed, 32 skipped, 0 failed",
        "merged report outcomes: 1,240",
        "Do not begin Increment 3",
    ):
        assert required in text
