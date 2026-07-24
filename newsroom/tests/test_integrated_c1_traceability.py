from __future__ import annotations

from pathlib import Path

from newsroom.integrated import (
    INCREMENT_1C_DEFERRED,
    INCREMENT_1C_EXCLUSIONS,
    INCREMENT_1C_TRACEABILITY,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_OPERATION_GUIDE = (
    _REPOSITORY_ROOT / "docs/operations/increment-1c-integrated-foundation.md"
)


def test_increment_1c_traceability_covers_every_issue_82_deliverable() -> None:
    expected = {
        "C1-01-AUTHENTICATED-FIXTURE-COMMAND/DREC-001-DREC-007",
        "C1-02-SQLITE-AGGREGATE-EVENT-AUDIT/DREC-040-DREC-056",
        "C1-03-GOVERNED-FIXTURE-OBJECT/DREC-070-DREC-077",
        "C1-04-STRUCTURAL-GRAPH-AND-EXACT-INDEX/GRAG-001-GRAG-016",
        "C1-05-TRUST-LABELLED-RETRIEVAL-CONTEXT/GRAG-024-GRAG-035",
        "C1-06-AUTHORITATIVE-HYDRATION/GRAG-040-GRAG-046",
        "C1-07-DETERMINISTIC-CANDIDATE-COLLISION-AND-IDEMPOTENCY",
        "C1-08-DESTRUCTIVE-GRAPH-LOSS-RECOVERY/GRPROD-020-GRPROD-024",
        "C1-09-TOMBSTONE-NON-RESURRECTION/GRAG-028",
        "C1-10-QUALIFYING-GRAPHRAG-NEGATIVE/GRPROD-013-GRPROD-016",
        "C1-11-NO-GRAPH-FREE-PASSING-VARIANT/ADR-0005",
        "C1-12-OPERATING-EVIDENCE-AND-FIXED-BOUNDARIES/GRPROD-031-GRPROD-032",
    }
    assert set(INCREMENT_1C_TRACEABILITY) == expected
    assert all(
        len(references) >= 4
        for references in INCREMENT_1C_TRACEABILITY.values()
    )

    flattened = {
        reference
        for references in INCREMENT_1C_TRACEABILITY.values()
        for reference in references
    }
    assert {
        ".github.workflows.projection-b2-neo4j",
        "docs.operations.increment-1c-integrated-foundation",
        "newsroom.authority._integrated_store",
        "newsroom.authority._integrated_system",
        "newsroom.authority._neo4j_projection_system",
        "newsroom.authority._object_store_hydration",
        "newsroom.integrated.models",
        "newsroom.integrated.policy",
        "newsroom.integrated.proof",
        "newsroom.projection.neo4j.qualification",
        "newsroom.tests.test_integrated_c1_candidate_authority",
        "newsroom.tests.test_integrated_c1_context_history",
        "newsroom.tests.test_integrated_c1_context_integrity_faults",
        "newsroom.tests.test_integrated_c1_context_semantics",
        "newsroom.tests.test_integrated_c1_derived_identity_faults",
        "newsroom.tests.test_integrated_c1_hydration_commit",
        "newsroom.tests.test_integrated_c1_integrity_faults",
        "newsroom.tests.test_integrated_c1_neo4j_service",
        "newsroom.tests.test_integrated_c1_proof_integrity",
        "newsroom.tests.test_integrated_c1_read_completeness",
        "newsroom.tests.test_integrated_c1_recovery_integrity",
        "newsroom.tests.test_integrated_c1_temporal_authority",
        "newsroom.tests.test_integrated_c1_temporal_integrity",
    } <= flattened


def test_increment_1c_exclusions_preserve_the_synthetic_non_activating_scope() -> None:
    assert INCREMENT_1C_EXCLUSIONS == frozenset(
        {
            "LIVE_SOURCE_RSS_SEARCH_GDELT_OR_BRAVE_EXECUTION",
            "GRAPHITI_EXECUTION",
            "MODEL_OR_EMBEDDING_CALLS",
            "PRODUCTION_VECTOR_GENERATION",
            "COMPLETE_ENTITY_RESOLUTION",
            "EDITORIAL_RELATION_ADMISSION",
            "FULL_TRIAGE_EVENT_HYPOTHESIS_OR_EVIDENCE_INTAKE",
            "PUBLICATION_BUNDLE_OR_TARGET_OPERATIONS",
            "TARGET_CREDENTIALS",
            "BACKGROUND_SCHEDULER",
            "SHADOW_CANARY_OR_PRODUCTION_ACTIVATION",
            "SPENDING_OR_PUBLIC_EFFECTS",
        }
    )


def test_increment_1c_deferred_register_does_not_overclaim_product_readiness() -> None:
    assert INCREMENT_1C_DEFERRED == frozenset(
        {
            "PRODUCTION_SOURCES_AND_SOURCE_RIGHTS_APPROVALS",
            "GRAPHITI_MODEL_PROMPT_AND_EMBEDDING_VERSIONS",
            "FULL_ENTITY_RESOLUTION_AND_EDITORIAL_RELATION_ADMISSION",
            "PRODUCTION_HYBRID_RETRIEVAL_QUALITY_AND_THRESHOLDS",
            "EVIDENCE_INTAKE_TRANSPORT",
            "EVALUATION_PLAN_AND_OPERATIONAL_ADMISSION",
            "SHADOW_CANARY_AND_PRODUCTION_ACTIVATION",
            "INTENDED_HARDWARE_PERFORMANCE_CAPACITY_LICENCE_AND_RECOVERY",
        }
    )


def test_increment_1c_operation_guide_preserves_final_authority_rules() -> None:
    text = _OPERATION_GUIDE.read_text(encoding="utf-8")
    required = (
        "Neo4j is a non-authoritative, rebuildable projection",
        "Never perform graph-to-ledger, graph-to-object or graph-to-Candidate recovery",
        "AUTHORITY_SELECTED_ACTIVE",
        "EXACT_GENERATION",
        "No vector, full-text, Graphiti, model, embedding or live-source retrieval was executed.",
        "Query-valid time is business-valid time",
        "The read limit comes from the trusted `ProjectionReadPolicy`",
        "allowed bytes equal the immutable blob size",
        "the hydration decision time equals the context record time",
        "the selected generation was ACTIVE at serving time",
        "Schema v5 permits exactly one immutable Candidate Version per Candidate",
        "A recovered equivalent proposal must deduplicate to the retained Candidate",
        "must never be interpreted as “no prior match”",
        "a later graph rebuild cannot restore covered fixture relations",
        "runtime-generated masked credentials",
        "runner-loopback Bolt exposure",
        "test_actual_service_integrated_foundation_replay_recovery_and_tombstone",
        "no production state or public effect",
    )
    for statement in required:
        assert statement in text
