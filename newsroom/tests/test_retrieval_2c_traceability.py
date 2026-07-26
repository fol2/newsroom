from __future__ import annotations

from pathlib import Path

from newsroom.retrieval import (
    INCREMENT_2C_DEFERRED,
    INCREMENT_2C_EXCLUSIONS,
    INCREMENT_2C_TRACEABILITY,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_OPERATION_GUIDE = (
    _REPOSITORY_ROOT
    / "docs/operations/increment-2c-bounded-hybrid-retrieval.md"
)
_SUBSTANTIVE_REVIEW = (
    _REPOSITORY_ROOT
    / "docs/research/2026-07-26-increment-2c-substantive-review.md"
)


def test_increment_2c_traceability_covers_every_authorised_deliverable() -> None:
    expected = {
        "2C-01-FIXED-NAMED-TOOL-AND-POLICY/GRAG-040-GRAG-046",
        "2C-02-FOUR-BOUNDED-BRANCHES/GRAG-031-GRAG-034",
        "2C-03-DETERMINISTIC-FUSION-AND-DEPENDENCY-DEDUP/DREC-042",
        "2C-04-RETRIEVAL-CONTEXT-V2-SQLITE-AUTHORITY/DREC-040-DREC-042-DREC-076",
        "2C-05-GOVERNED-HYDRATION-RIGHTS-AND-LIFECYCLE/GRAG-028",
        "2C-06-ACTIVE-WATERMARK-GAP-FRESHNESS-AND-TEMPORAL-BOUNDS/GRAG-024-GRAG-025",
        "2C-07-PRIVATE-FIXED-QUERY-SECURITY/GRAG-034-GRAG-035",
        "2C-08-ACTUAL-NEO4J-AND-SDLC-EVIDENCE/GRPROD-015-GRPROD-016",
        "2C-09-EXPLICIT-OUTCOMES-OPERATIONS-AND-ROLLBACK/GRPROD-020-GRPROD-024",
    }
    assert set(INCREMENT_2C_TRACEABILITY) == expected
    assert all(len(references) >= 5 for references in INCREMENT_2C_TRACEABILITY.values())

    flattened = {
        reference
        for references in INCREMENT_2C_TRACEABILITY.values()
        for reference in references
    }
    assert {
        ".github.workflows.evidence",
        ".github.workflows.projection-b2-neo4j",
        "docs.operations.increment-2c-bounded-hybrid-retrieval",
        "docs.research.2026-07-26-increment-2c-substantive-review",
        "newsroom.authority._retrieval_store",
        "newsroom.authority._retrieval_system",
        "newsroom.authority.retrieval_migrations",
        "newsroom.projection.neo4j._retrieval_adapter",
        "newsroom.retrieval.fixture_v2",
        "newsroom.retrieval.fusion",
        "newsroom.retrieval.models",
        "newsroom.retrieval.policy",
        "newsroom.tests.test_retrieval_2c_authority",
        "newsroom.tests.test_retrieval_2c_neo4j_service",
    } <= flattened


def test_increment_2c_exclusions_preserve_the_authorised_stop_boundary() -> None:
    assert INCREMENT_2C_EXCLUSIONS == frozenset(
        {
            "INCREMENT_2D_OR_LATER_IMPLEMENTATION",
            "CANDIDATE_ADMISSION_OR_IDENTITY_ALLOCATION",
            "ARBITRARY_CYPHER_PUBLIC_DRIVER_OR_CALLER_SELECTED_GRAPH_SCOPE",
            "GRAPHITI_EXECUTION_OR_RELATION_PROPOSAL_GENERATION",
            "EXTERNAL_MODEL_PROMPT_OR_EMBEDDING_CALL",
            "LIVE_SOURCE_RSS_JSON_BRAVE_GDELT_OR_SEARCH_EXECUTION",
            "PRODUCTION_PROTECTED_CONTENT_VECTOR_GENERATION",
            "GENERAL_PURPOSE_OR_CALLER_CONFIGURABLE_RETRIEVAL",
            "FULL_TRIAGE_WORK_ITEM_PROPOSAL_OR_EVIDENCE_INTAKE",
            "SCHEDULER_SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
            "PUBLICATION_SPENDING_OR_PUBLIC_EFFECT",
        }
    )


def test_increment_2c_deferred_register_keeps_later_units_blocked() -> None:
    assert INCREMENT_2C_DEFERRED == frozenset(
        {
            "COMPLETE_ACTUAL_NEO4J_FIXTURE_TO_CANDIDATE_PROOF_INCREMENT_2D",
            "GENERALIZED_MULTI_SOURCE_RETRIEVAL_TOOLS",
            "FINAL_PRODUCTION_FULLTEXT_VECTOR_FUSION_THRESHOLDS",
            "PRODUCTION_EMBEDDING_PROVIDER_AND_PROTECTED_CONTENT_POLICY",
            "GRAPHITI_PROPOSAL_GENERATION_AND_GENERAL_RELATION_ADMISSION_INCREMENT_4",
            "FULL_TRIAGE_WORK_ITEMS_PROPOSALS_AND_CANDIDATE_ADMISSION_INCREMENT_6",
            "EVALUATION_SHADOW_CANARY_AND_ACTIVATION_INCREMENTS_8_11",
        }
    )


def test_increment_2c_operations_record_authority_bounds_and_rollback() -> None:
    text = _OPERATION_GUIDE.read_text(encoding="utf-8")
    for required in (
        "SQLite ledger records, immutable decisions, governed objects and Retrieval Contexts remain authoritative",
        "find_related_event_candidates",
        "contains no result limit, generation identifier, label, relationship type, predicate, query text, Cypher or policy object",
        "date window `31 days`",
        "maximum projection-validation age `1 hour`",
        "transaction timeout `5 seconds`",
        "exactly Neo4j `2026.06.0` Community",
        "Every successful context retains exactly one execution of each branch",
        "Neo4j text or snippets are never substituted for governed bytes",
        "distinct current blob lifecycle state",
        "None is represented as `no prior match`",
        "Expired authority creates no attempt record",
        "Passage and dependency identifiers cannot belong to more than one root",
        "Successful branch evidence must cover every checked root",
        "retained sum of branch elapsed evidence cannot exceed five seconds",
        "live server to be exactly Neo4j `2026.06.0` Community",
        "schema version 8",
        "do not delete migration rows",
        "Issue #158 remains blocked",
    ):
        assert required in text


def test_increment_2c_review_records_zero_unresolved_p1_p2() -> None:
    text = _SUBSTANTIVE_REVIEW.read_text(encoding="utf-8")
    for required in (
        "P1 findings: 2",
        "P2 findings: 20",
        "Remaining unresolved P1/P2 after correction: 0",
        "Retrieval initially opened a second SQLite authority writer",
        "Authentication could expire while Neo4j work was in flight",
        "The exact branch lacked explicit prior-revision authority",
        "Public composition exposed replaceable policy and retrieval contracts",
        "Date-window and projection-freshness contracts were implicit",
        "Neo4j reads initially had no transaction timeout",
        "Permanent actual-service and SDLC evidence did not include 2C",
        "Each branch could consume a fresh five-second timeout",
        "Branch score domains were not independently bound",
        "Hydrated lifecycle metadata recorded admission state as blob state",
        "Actual-service evidence covered full-text loss but not vector-index loss",
        "The retrieval adapter imported Neo4j outside the single driver seam",
        "Fixture dependency roots could overlap or change identity",
        "Authority-clock rollback could make retained evidence appear current",
        "Bounded subprocess evidence raced interpreter readiness",
        "A typed adapter could omit the mandatory fixture neighbourhood",
        "Typed branch timing evidence could exceed the shared deadline",
        "Retrieval serving trusted constructor-time driver compatibility only",
        "Canonical score syntax confused significant digits with decimal places",
        "Retrieval re-derived a graph key without the fixture binding",
        "Deterministic core evidence exhausted the accepted shared lane margin",
        "Sequential core execution still lacked robust hosted-runner margin",
        "155 passed, 4 intentional no-service skips, 0 failed",
        "116 passed, 4 intentional no-service skips, 0 failed",
        "122 passed, 4 intentional no-service skips, 0 failed",
        "46 passed, 0 skipped, 0 failed",
        "1,178 passed, 23 skipped, 0 failed",
        "merged report test outcomes: 1,201",
        "Issue #158 remains blocked",
    ):
        assert required in text


def test_increment_2c_public_surface_and_service_boundary_remain_fixed() -> None:
    public_source = (
        _REPOSITORY_ROOT / "newsroom/authority/_retrieval_system.py"
    ).read_text(encoding="utf-8")
    adapter_source = (
        _REPOSITORY_ROOT / "newsroom/projection/neo4j/_retrieval_adapter.py"
    ).read_text(encoding="utf-8")
    service_source = (
        _REPOSITORY_ROOT / "newsroom/tests/test_retrieval_2c_neo4j_service.py"
    ).read_text(encoding="utf-8")

    public_signature = public_source.split(
        "def open_hybrid_retrieval_authority_system(", 1
    )[1].split(") -> HybridRetrievalAuthoritySystem:", 1)[0]
    for prohibited in (
        "policy:",
        "retrieval_contract:",
        "result_limit",
        "generation_id",
        "cypher",
        "driver",
    ):
        assert prohibited not in public_signature.lower()

    driver_source = (
        _REPOSITORY_ROOT / "newsroom/projection/neo4j/_adapter.py"
    ).read_text(encoding="utf-8")
    assert "unit_of_work" in adapter_source
    assert "remaining_timeout_seconds" in adapter_source
    assert "deadline_ns" in adapter_source
    assert "_COMPONENT_QUERY" in adapter_source
    assert "NEO4J_B2_SERVER_VERSION" in adapter_source
    assert "from neo4j" not in adapter_source
    assert "_neo4j_unit_of_work_factory" in driver_source
    assert 'NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED' in service_source
