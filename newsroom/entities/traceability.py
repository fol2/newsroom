"""Exact Increment 4B requirement, boundary and deferral traceability.

A row states what issue #226 delivers at the entity-resolution seam.  It does not
claim relation admission, Graphiti workspace execution or actual-Neo4j end-to-end
qualification that remains dependency-ordered in 4C through 4E.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityTraceabilityRow:
    requirement_id: str
    implementation_symbol: str
    test_node: str
    status: str


_ROWS = (
    (
        "DREC-001",
        "newsroom.entities.types:CanonicalEntityId",
        "newsroom/tests/test_entity_4b_contracts.py",
        "IMPLEMENTED_STABLE_ENTITY_AND_DECISION_IDENTITIES",
    ),
    (
        "DREC-002",
        "newsroom.entities.models:CanonicalEntity",
        "newsroom/tests/test_entity_4b_contracts.py",
        "IMPLEMENTED_IDENTITY_INDEPENDENT_OF_NAMES_LOCATORS_AND_GRAPH_IDS",
    ),
    (
        "DREC-003",
        "newsroom.entities.models:CanonicalEntity",
        "newsroom/tests/test_entity_4b_contracts.py",
        "IMPLEMENTED_DIGEST_NOT_DOMAIN_IDENTITY",
    ),
    (
        "DREC-004",
        "newsroom.authority._entity_store_common:_EntityStoreSupport._ensure_identifier_absent",
        "newsroom/tests/test_entity_4b_authority.py",
        "IMPLEMENTED_NO_IDENTIFIER_REUSE",
    ),
    (
        "DREC-005",
        "newsroom.entities.types:EntityResolutionState",
        "newsroom/tests/test_entity_4b_authority.py",
        "IMPLEMENTED_HOLD_UNRESOLVED_AND_SEPARATE_IDENTITIES",
    ),
    (
        "DREC-006",
        "newsroom.entities.models:EntityResolutionDecision",
        "newsroom/tests/test_entity_4b_integrity.py",
        "IMPLEMENTED_IMMUTABLE_DECISIONS_AND_VERSIONS",
    ),
    (
        "DREC-007",
        "newsroom.authority._entity_store_projection:_EntityProjectionMixin.rebuild_preferred_projection",
        "newsroom/tests/test_entity_4b_projection_rebuild.py",
        "IMPLEMENTED_REBUILDABLE_CURRENT_IDENTITY_VIEW",
    ),
    (
        "DREC-016",
        "newsroom.authority._entity_store_common:_EntityStoreSupport._require_mention_current",
        "newsroom/tests/test_entity_4b_lifecycle.py",
        "IMPLEMENTED_RIGHTS_LIMITED_IDENTITY_USE",
    ),
    (
        "DREC-041",
        "newsroom.entities.models:EntityResolutionProposalVersion",
        "newsroom/tests/test_entity_4b_authority.py",
        "IMPLEMENTED_PROPOSAL_SEPARATE_FROM_DECISION",
    ),
    (
        "DREC-045",
        "newsroom.entities.models:EntityMergeDecision",
        "newsroom/tests/test_entity_4b_lineage.py",
        "IMPLEMENTED_EXPLICIT_MERGE_SPLIT_AND_SUCCESSORS",
    ),
    (
        "DREC-070",
        "newsroom.entities.models:EntityMention",
        "newsroom/tests/test_entity_4b_authority.py",
        "IMPLEMENTED_EXACT_4A_PROPOSAL_AND_EVIDENCE_REFERENCES",
    ),
    (
        "DREC-071",
        "newsroom.authority._entity_store_commit:_EntityCommitMixin.commit_entity_resolution_decision",
        "newsroom/tests/test_entity_4b_authority.py",
        "IMPLEMENTED_ORDERED_PROPOSAL_DECISION_ENTITY_CAUSATION",
    ),
    (
        "DREC-073",
        "newsroom.entities.models:EntityReversalDecision",
        "newsroom/tests/test_entity_4b_lineage.py",
        "IMPLEMENTED_DIRECTIONAL_APPEND_ONLY_LINEAGE",
    ),
    (
        "DREC-074",
        "newsroom.entities.models:EntityAlias",
        "newsroom/tests/test_entity_4b_contracts.py",
        "IMPLEMENTED_VALIDITY_AND_RECORDING_TIME_SEPARATION",
    ),
    (
        "DREC-076",
        "newsroom.entities.models:EntityResolutionDecision",
        "newsroom/tests/test_entity_4b_policy.py",
        "IMPLEMENTED_POLICY_AND_PRODUCER_VERSION_PROVENANCE",
    ),
    (
        "DREC-077",
        "newsroom.authority.entity_projection_rebuild:rebuild_governed_entity_preferred_projection",
        "newsroom/tests/test_entity_4b_projection_rebuild.py",
        "IMPLEMENTED_RIGHTS_SAFE_REPLAYABLE_CURRENT_VIEW",
    ),
    (
        "GRAG-010",
        "newsroom.entities.models:EntityResolutionProposalVersion",
        "newsroom/tests/test_entity_4b_security.py",
        "IMPLEMENTED_PROPOSED_ADMITTED_PROJECTION_SCOPE_SEPARATION",
    ),
    (
        "GRAG-011",
        "newsroom.authority._entity_store_commit:_EntityCommitMixin.commit_entity_resolution_proposal",
        "newsroom/tests/test_entity_4b_false_merge.py",
        "IMPLEMENTED_CONFIDENCE_AND_SAME_NAME_NEVER_ALLOCATE_OR_MERGE_IDENTITY",
    ),
    (
        "GRAG-012",
        "newsroom.entities.models:EntityResolutionDependency",
        "newsroom/tests/test_entity_4b_dependencies.py",
        "BOUNDARY_ONLY_RELATION_CLASSIFICATION_DEFERRED_4C",
    ),
    (
        "GRAG-013",
        "newsroom.entities.models:EntityResolutionDependency",
        "newsroom/tests/test_entity_4b_dependencies.py",
        "ENTITY_PRECONDITION_ONLY_RELATION_AUTHORITY_DEFERRED_4C",
    ),
    (
        "GRAG-014",
        "newsroom.entities.models:CanonicalEntity",
        "newsroom/tests/test_entity_4b_lineage.py",
        "IMPLEMENTED_FIRST_CLASS_MENTION_ALIAS_ENTITY_MERGE_SPLIT_REVERSAL",
    ),
    (
        "GRAG-015",
        "newsroom.entities.models:EntityDependentAdmissionGuard",
        "newsroom/tests/test_entity_4b_dependencies.py",
        "IMPLEMENTED_MATERIAL_UNRESOLVED_ADMISSION_BLOCK",
    ),
    (
        "GRAG-016",
        "newsroom.entities.models:EntityProjectionEvent",
        "newsroom/tests/test_entity_4b_projection_rebuild.py",
        "IMPLEMENTED_TRUST_LABELLED_PROVENANCE_CONTEXT",
    ),
    (
        "GRAG-020",
        "newsroom.authority._entity_store_commit:_EntityCommitMixin.commit_entity_mention",
        "newsroom/tests/test_entity_4b_authority.py",
        "INHERITED_PROPOSAL_ONLY_EXTRACTION_AND_EXPLICIT_ENTITY_ADMISSION",
    ),
    (
        "GRAG-021",
        "newsroom.authority._entity_boundary:_EntityBoundary",
        "newsroom/tests/test_entity_4b_security.py",
        "ENTITY_AUTHORITY_ISOLATED_GRAPHITI_WORKSPACE_DEFERRED_4D",
    ),
    (
        "GRAG-022",
        "newsroom.entities.models:EntityMention",
        "newsroom/tests/test_entity_4b_authority.py",
        "INHERITED_RETAINED_4A_PROVENANCE_CONSUMED_EXACTLY",
    ),
    (
        "GRAG-023",
        "newsroom.entities.models:EntityResolutionDecision",
        "newsroom/tests/test_entity_4b_authority.py",
        "IMPLEMENTED_ENTITY_DECISIONS_RELATION_DECISIONS_DEFERRED_4C",
    ),
    (
        "GRAG-024",
        "newsroom.entities.models:EntityProjectionEvent",
        "newsroom/tests/test_entity_4b_projection_rebuild.py",
        "IMPLEMENTED_ORDERED_ENTITY_PROJECTION_EVENT_SEAM",
    ),
    (
        "GRAG-025",
        "newsroom.authority._entity_store_projection:_EntityProjectionMixin.projection_events_after",
        "newsroom/tests/test_entity_4b_projection_rebuild.py",
        "IMPLEMENTED_CONTIGUOUS_ENTITY_EVENT_STREAM_GRAPH_CHECKPOINT_DEFERRED_4E",
    ),
    (
        "GRAG-026",
        "newsroom.authority.entity_projection_rebuild:rebuild_governed_entity_preferred_projection",
        "newsroom/tests/test_entity_4b_projection_rebuild.py",
        "IMPLEMENTED_REBUILD_FROM_RETAINED_DECISIONS_WITHOUT_EXTRACTION",
    ),
    (
        "GRAG-027",
        "newsroom.entities.models:EntityProjectionEvent",
        "newsroom/tests/test_entity_4b_traceability.py",
        "ENTITY_EVENT_INTERFACE_ONLY_BLUE_GREEN_GENERATION_DEFERRED_4E",
    ),
    (
        "GRAG-028",
        "newsroom.authority.entity_projection_rebuild:rebuild_governed_entity_preferred_projection",
        "newsroom/tests/test_entity_4b_projection_rebuild.py",
        "IMPLEMENTED_RIGHTS_SAFE_ENTITY_REBUILD",
    ),
    (
        "GRAG-030",
        "newsroom.entities.models:EntityAlias",
        "newsroom/tests/test_entity_4b_contracts.py",
        "IMPLEMENTED_SOURCE_VALIDITY_DECISION_RECORDING_TIME_SEPARATION",
    ),
    (
        "GRPROD-003",
        "newsroom.authority._entity_system:open_governed_entity_authority_system",
        "newsroom/tests/test_entity_4b_security.py",
        "IMPLEMENTED_NATIVE_REPOSITORY_ENTITY_AUTHORITY",
    ),
    (
        "GRPROD-005",
        "newsroom.entities.types:CanonicalEntityId",
        "newsroom/tests/test_entity_4b_contracts.py",
        "IMPLEMENTED_SHARED_CANONICAL_IDENTITY_AND_TRUST_CONTRACT",
    ),
    (
        "GRPROD-013",
        "newsroom.entities.models:CanonicalEntity",
        "newsroom/tests/test_entity_4b_security.py",
        "IMPLEMENTED_ENGINE_NEUTRAL_NO_NEO4J_OR_GRAPHITI_INTERNAL_ID",
    ),
    (
        "GRPROD-016",
        "newsroom.entities.models:EntityProjectionEvent",
        "newsroom/tests/test_entity_4b_traceability.py",
        "ACTUAL_GRAPH_SERVICE_END_TO_END_PROOF_DEFERRED_4E",
    ),
    (
        "GRPROD-020",
        "newsroom.entities.models:EntityProjectionEvent",
        "newsroom/tests/test_entity_4b_projection_rebuild.py",
        "IMPLEMENTED_ENTITY_PROJECTION_EVENT_MAPPING_GRAPH_BOUNDARY_DEFERRED_4D_4E",
    ),
)

INCREMENT_4B_TRACEABILITY = tuple(EntityTraceabilityRow(*row) for row in _ROWS)

INCREMENT_4B_ADR_ANCHORS = frozenset(
    {"ADR-0001", "ADR-0002", "ADR-0004", "ADR-0005"}
)

INCREMENT_4B_EXCLUSIONS = (
    "real Graphiti, model or embedding execution",
    "live source access, search, schedules, provider credentials and spending",
    "editorial relation admission, assertions, revocation and supersession (Increment 4C)",
    "disposable Graphiti proposal-workspace adapter execution (Increment 4D)",
    "actual-Neo4j bilingual admitted-only end-to-end proof (Increment 4E)",
    "Candidate, Evidence Intake, publication, canary, production activation or public effect",
)

INCREMENT_4B_DEFERRED = (
    "versioned editorial predicate registry and governed relation decisions",
    "isolated proposal-only Graphiti adapter and workspace-loss qualification",
    "actual-Neo4j bilingual projection, purge and complete rebuild proof",
    "owner-approved real Graphiti/model runtime decision packet",
)

__all__ = [
    "EntityTraceabilityRow",
    "INCREMENT_4B_ADR_ANCHORS",
    "INCREMENT_4B_DEFERRED",
    "INCREMENT_4B_EXCLUSIONS",
    "INCREMENT_4B_TRACEABILITY",
]
