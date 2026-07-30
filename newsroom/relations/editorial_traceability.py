"""Exact Increment 4C requirement, boundary and deferral traceability.

A row states what issue #227 delivers at the governed editorial-relation seam.
It deliberately does not claim the isolated Graphiti proposal workspace from
Increment 4D or the bilingual actual-Neo4j projection proof from Increment 4E.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EditorialRelationTraceabilityRow:
    requirement_id: str
    implementation_symbol: str
    test_node: str
    status: str


_ROWS = (
    (
        "DREC-001",
        "newsroom.relations.editorial_types:EditorialRelationProposalId",
        "newsroom/tests/test_editorial_relation_4c_contracts.py",
        "IMPLEMENTED_STABLE_PROPOSAL_DECISION_ASSERTION_AND_SUPERSESSION_IDENTITIES",
    ),
    (
        "DREC-003",
        "newsroom.relations.editorial_models:EditorialRelationProposalRequest",
        "newsroom/tests/test_editorial_relation_4c_contracts.py",
        "IMPLEMENTED_DIGESTS_FOR_INTEGRITY_NOT_DOMAIN_IDENTITY",
    ),
    (
        "DREC-004",
        "newsroom.authority._editorial_relation_store_common:_EditorialRelationStoreSupport._editorial_ensure_identifier_absent",
        "newsroom/tests/test_editorial_relation_4c_proposals.py",
        "IMPLEMENTED_NO_IDENTIFIER_REUSE",
    ),
    (
        "DREC-005",
        "newsroom.relations.editorial_types:EditorialRelationDecisionAction.HOLD",
        "newsroom/tests/test_editorial_relation_4c_authority.py",
        "IMPLEMENTED_HOLD_AND_UNRESOLVED_WITHOUT_GUESSED_ADMISSION",
    ),
    (
        "DREC-006",
        "newsroom.relations.editorial_models:EditorialRelationDecision",
        "newsroom/tests/test_editorial_relation_4c_integrity.py",
        "IMPLEMENTED_IMMUTABLE_PROPOSAL_VERSION_DECISION_AND_ASSERTION_HISTORY",
    ),
    (
        "DREC-007",
        "newsroom.authority.editorial_relation_projection_rebuild:rebuild_governed_editorial_relation_current_projection",
        "newsroom/tests/test_editorial_relation_4c_projection_rebuild.py",
        "IMPLEMENTED_REBUILDABLE_CURRENT_ASSERTION_PROJECTION",
    ),
    (
        "DREC-016",
        "newsroom.authority._editorial_relation_store_common:_EditorialRelationStoreSupport._require_editorial_assertion_rights_current",
        "newsroom/tests/test_editorial_relation_4c_rights.py",
        "IMPLEMENTED_RIGHTS_LIMITED_CURRENT_RELATION_USE",
    ),
    (
        "DREC-041",
        "newsroom.relations.editorial_models:EditorialRelationProposalVersion",
        "newsroom/tests/test_editorial_relation_4c_authority.py",
        "IMPLEMENTED_PROPOSAL_SEPARATE_FROM_COMMITTED_DECISION",
    ),
    (
        "DREC-042",
        "newsroom.relations.editorial_models:EditorialRelationProducer",
        "newsroom/tests/test_editorial_relation_4c_security.py",
        "IMPLEMENTED_RETRIEVAL_CONFIDENCE_AND_GRAPH_CONTEXT_NON_AUTHORITY",
    ),
    (
        "DREC-043",
        "newsroom.relations.editorial_models:EventHypothesisRelationEndpoint",
        "newsroom/tests/test_editorial_relation_4c_proposals.py",
        "IMPLEMENTED_RETAINED_UNVERIFIED_HYPOTHESIS_ENDPOINT_ONLY",
    ),
    (
        "DREC-054",
        "newsroom.authority._editorial_relation_store_commit:_EditorialRelationCommitMixin.commit_editorial_relation_decision",
        "newsroom/tests/test_editorial_relation_4c_concurrency.py",
        "IMPLEMENTED_EQUIVALENT_ADMISSION_COLLISION_AND_CONCURRENT_REPLAY",
    ),
    (
        "DREC-070",
        "newsroom.relations.editorial_models:EditorialRelationProposalRequest",
        "newsroom/tests/test_editorial_relation_4c_authority.py",
        "IMPLEMENTED_EXACT_ENTITY_VERSION_EXTRACTION_AND_WORKFLOW_REFERENCES",
    ),
    (
        "DREC-071",
        "newsroom.authority._editorial_relation_store_commit:_EditorialRelationCommitMixin.commit_editorial_relation_decision",
        "newsroom/tests/test_authority_a2a_editorial_relation.py",
        "IMPLEMENTED_ORDERED_PROPOSAL_DECISION_ASSERTION_CAUSATION",
    ),
    (
        "DREC-073",
        "newsroom.relations.editorial_types:EditorialRelationDecisionAction.SUPERSEDE",
        "newsroom/tests/test_editorial_relation_4c_lifecycle.py",
        "IMPLEMENTED_DIRECTIONAL_ATTRIBUTABLE_SUPERSESSION",
    ),
    (
        "DREC-074",
        "newsroom.relations.editorial_models:EditorialRelationTemporalScope",
        "newsroom/tests/test_editorial_relation_4c_contracts.py",
        "IMPLEMENTED_VALID_OBSERVED_PROPOSAL_DECISION_AND_INVALIDATION_TIME_SEPARATION",
    ),
    (
        "DREC-076",
        "newsroom.relations.editorial_models:EditorialRelationProducer",
        "newsroom/tests/test_editorial_relation_4c_policy.py",
        "IMPLEMENTED_EXACT_PRODUCER_PREDICATE_REGISTRY_AND_POLICY_PROVENANCE",
    ),
    (
        "DREC-077",
        "newsroom.authority.editorial_relation_projection_rebuild:rebuild_governed_editorial_relation_current_projection",
        "newsroom/tests/test_editorial_relation_4c_projection_rebuild.py",
        "IMPLEMENTED_RIGHTS_SAFE_REPLAYABLE_CURRENT_VIEW",
    ),
    (
        "GRAG-010",
        "newsroom.relations.editorial_models:EditorialRelationAssertion",
        "newsroom/tests/test_editorial_relation_4c_security.py",
        "IMPLEMENTED_PROPOSED_ADMITTED_AND_PROJECTION_SCOPE_SEPARATION",
    ),
    (
        "GRAG-011",
        "newsroom.relations.editorial_models:EditorialRelationProposalRequest",
        "newsroom/tests/test_editorial_relation_4c_authority.py",
        "IMPLEMENTED_CONFIDENCE_NEVER_ADMITS_RELATION",
    ),
    (
        "GRAG-012",
        "newsroom.relations.editorial_models:EditorialPredicateContract",
        "newsroom/tests/test_editorial_relation_4c_contracts.py",
        "IMPLEMENTED_REIFIED_EDITORIAL_AUTHORITY_SEPARATE_FROM_STRUCTURAL_RELATIONS",
    ),
    (
        "GRAG-013",
        "newsroom.relations.editorial_models:EditorialRelationAssertion",
        "newsroom/tests/test_editorial_relation_4c_lifecycle.py",
        "IMPLEMENTED_SUBJECT_OBJECT_PREDICATE_PROVENANCE_TIME_AND_HISTORY",
    ),
    (
        "GRAG-014",
        "newsroom.relations.editorial_models:CanonicalEntityRelationEndpoint",
        "newsroom/tests/test_editorial_relation_4c_proposals.py",
        "CONSUMES_EXPLICIT_VERSIONED_INCREMENT_4B_ENTITY_AUTHORITY",
    ),
    (
        "GRAG-015",
        "newsroom.authority._editorial_relation_store_common:_EditorialRelationStoreSupport._editorial_dependencies_from_ids",
        "newsroom/tests/test_editorial_relation_4c_authority.py",
        "IMPLEMENTED_MATERIAL_UNRESOLVED_IDENTITY_ADMISSION_BLOCK",
    ),
    (
        "GRAG-016",
        "newsroom.relations.editorial_models:EditorialRelationProjectionEvent",
        "newsroom/tests/test_projection_b1_editorial_relation.py",
        "IMPLEMENTED_TRUST_LABELLED_PROVENANCE_CONTEXT",
    ),
    (
        "GRAG-020",
        "newsroom.authority._editorial_relation_boundary:_EditorialRelationBoundary.propose",
        "newsroom/tests/test_editorial_relation_4c_authority.py",
        "IMPLEMENTED_PROPOSAL_ONLY_PRODUCER_PATH_EXPLICIT_DECISION_REQUIRED",
    ),
    (
        "GRAG-021",
        "newsroom.authority._editorial_relation_boundary:_EditorialRelationBoundary",
        "newsroom/tests/test_editorial_relation_4c_security.py",
        "GOVERNED_AUTHORITY_ISOLATED_GRAPHITI_WORKSPACE_DEFERRED_4D",
    ),
    (
        "GRAG-022",
        "newsroom.relations.editorial_models:ExtractionRelationEvidence",
        "newsroom/tests/test_editorial_relation_4c_integrity.py",
        "IMPLEMENTED_EXACT_RETAINED_EXTRACTION_PROVENANCE_BEFORE_ADMISSION",
    ),
    (
        "GRAG-023",
        "newsroom.relations.editorial_models:EditorialRelationDecisionRequest",
        "newsroom/tests/test_editorial_relation_4c_authority.py",
        "IMPLEMENTED_ACCEPT_REJECT_HOLD_UNRESOLVED_REVOKE_INVALIDATE_SUPERSEDE",
    ),
    (
        "GRAG-024",
        "newsroom.relations.editorial_models:EditorialRelationProjectionEvent",
        "newsroom/tests/test_projection_b1_editorial_relation.py",
        "IMPLEMENTED_ORDERED_IDEMPOTENT_ADMITTED_ONLY_EVENT_SEAM",
    ),
    (
        "GRAG-025",
        "newsroom.authority._editorial_relation_store_read:_EditorialRelationReadMixin.editorial_projection_events_after",
        "newsroom/tests/test_projection_b1_editorial_relation.py",
        "EVENT_STREAM_CUTOFF_IMPLEMENTED_GRAPH_CONTIGUOUS_CHECKPOINT_DEFERRED_4E",
    ),
    (
        "GRAG-026",
        "newsroom.authority.editorial_relation_projection_rebuild:rebuild_governed_editorial_relation_current_projection",
        "newsroom/tests/test_editorial_relation_4c_projection_rebuild.py",
        "IMPLEMENTED_REBUILD_FROM_RETAINED_DECISIONS_WITHOUT_EXTRACTION",
    ),
    (
        "GRAG-027",
        "newsroom.relations.editorial_models:EditorialRelationProjectionEvent",
        "newsroom/tests/test_editorial_relation_4c_traceability.py",
        "PROJECTION_EVENT_INTERFACE_ONLY_BLUE_GREEN_GENERATION_DEFERRED_4E",
    ),
    (
        "GRAG-028",
        "newsroom.authority.editorial_relation_projection_rebuild:rebuild_governed_editorial_relation_current_projection",
        "newsroom/tests/test_editorial_relation_4c_projection_rebuild.py",
        "IMPLEMENTED_RIGHTS_SAFE_ATOMIC_NO_RESURRECTION_REBUILD",
    ),
    (
        "GRAG-030",
        "newsroom.relations.editorial_models:EditorialRelationTemporalScope",
        "newsroom/tests/test_editorial_relation_4c_lifecycle.py",
        "IMPLEMENTED_DISTINCT_VALID_OBSERVED_PROPOSAL_ADMISSION_AND_REMOVAL_TIMES",
    ),
    (
        "GRAG-031",
        "newsroom.relations.editorial_models:EditorialRelationProjectionEvent",
        "newsroom/tests/test_editorial_relation_4c_traceability.py",
        "HYBRID_RETRIEVAL_DEFERRED_AFTER_ADMITTED_GRAPH_PROJECTION",
    ),
    (
        "GRAG-032",
        "newsroom.authority._editorial_relation_store_common:_EditorialRelationStoreSupport._require_editorial_assertion_current",
        "newsroom/tests/test_editorial_relation_4c_rights.py",
        "IMPLEMENTED_LEDGER_HYDRATED_CURRENT_AUTHORITY_GRAPH_RESPONSE_HYDRATION_DEFERRED_4E",
    ),
    (
        "GRAG-033",
        "newsroom.relations.editorial_models:EditorialRelationReadPolicy",
        "newsroom/tests/test_editorial_relation_4c_security.py",
        "IMPLEMENTED_BOUNDED_PURPOSE_SCOPED_READS_GRAPH_NAMED_TOOLS_DEFERRED_4E",
    ),
    (
        "GRAG-034",
        "newsroom.authority._editorial_relation_facade:GovernedEditorialRelations",
        "newsroom/tests/test_editorial_relation_4c_security.py",
        "IMPLEMENTED_NO_CYPHER_GRAPH_CREDENTIAL_OR_GENERAL_MUTATION_SURFACE",
    ),
    (
        "GRAG-035",
        "newsroom.relations.editorial_models:EditorialRelationProjectionEvent",
        "newsroom/tests/test_editorial_relation_4c_traceability.py",
        "ADMITTED_EVENT_METADATA_IMPLEMENTED_GRAPH_QUERY_METADATA_DEFERRED_4E",
    ),
    (
        "GRPROD-003",
        "newsroom.authority._editorial_relation_system:open_governed_editorial_relation_authority_system",
        "newsroom/tests/test_editorial_relation_4c_security.py",
        "IMPLEMENTED_NATIVE_REPOSITORY_RELATION_AUTHORITY",
    ),
    (
        "GRPROD-005",
        "newsroom.relations.editorial_models:EditorialRelationAssertion",
        "newsroom/tests/test_editorial_relation_4c_contracts.py",
        "IMPLEMENTED_SHARED_CANONICAL_IDENTITY_TRUST_TIME_AND_EVENT_CONTRACT",
    ),
    (
        "GRPROD-013",
        "newsroom.relations.editorial_models:EditorialRelationAssertion",
        "newsroom/tests/test_editorial_relation_4c_security.py",
        "IMPLEMENTED_ENGINE_NEUTRAL_NO_NEO4J_OR_GRAPHITI_INTERNAL_ID",
    ),
    (
        "GRPROD-016",
        "newsroom.relations.editorial_models:EditorialRelationProjectionEvent",
        "newsroom/tests/test_editorial_relation_4c_traceability.py",
        "ACTUAL_GRAPH_RELATION_INTEGRATION_PROOF_DEFERRED_4E",
    ),
    (
        "GRPROD-020",
        "newsroom.relations.editorial_models:EditorialRelationProjectionEvent",
        "newsroom/tests/test_projection_b1_editorial_relation.py",
        "IMPLEMENTED_RELATION_PROJECTION_EVENT_MAPPING_NEO4J_MAPPING_DEFERRED_4E",
    ),
)

INCREMENT_4C_TRACEABILITY = tuple(
    EditorialRelationTraceabilityRow(*row) for row in _ROWS
)

INCREMENT_4C_ADR_ANCHORS = frozenset(
    {"ADR-0001", "ADR-0002", "ADR-0004", "ADR-0005"}
)

INCREMENT_4C_EXCLUSIONS = (
    "real Graphiti, model or embedding execution",
    "live source access, search, schedules, provider credentials and spending",
    "arbitrary predicates, unrestricted SQL or Cypher and graph write credentials",
    "isolated Graphiti proposal-workspace execution (Increment 4D)",
    "actual-Neo4j bilingual admitted-only projection and rebuild proof (Increment 4E)",
    "Candidate, Evidence Intake, publication, canary, production activation or public effect",
)

INCREMENT_4C_DEFERRED = (
    "isolated proposal-only Graphiti adapter and disposable workspace qualification",
    "actual-Neo4j bilingual entity and relation projection, purge and rebuild proof",
    "graph projector contiguous watermark, generation switch and serving metadata",
    "hybrid retrieval, hydration tools and ablation evidence",
    "owner-approved real Graphiti and model runtime decision packet",
)

__all__ = [
    "EditorialRelationTraceabilityRow",
    "INCREMENT_4C_ADR_ANCHORS",
    "INCREMENT_4C_DEFERRED",
    "INCREMENT_4C_EXCLUSIONS",
    "INCREMENT_4C_TRACEABILITY",
]
