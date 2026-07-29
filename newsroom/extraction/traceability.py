"""Exact Increment 4A requirement and deferral traceability.

The matrix is intentionally narrow. It distinguishes authority delivered by issue
#225 from inherited source/object contracts and from dependency-ordered work that
remains in 4B through 4E. A listed requirement is therefore not automatically a
claim of complete Increment 4 implementation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExtractionTraceabilityRow:
    requirement_id: str
    implementation_symbol: str
    test_node: str
    status: str


_ROWS = (
    # Identity, immutable versions, exact source lineage and rights-safe inputs.
    (
        "DREC-001",
        "newsroom.extraction.types:ExtractionRunId",
        "newsroom/tests/test_extraction_4a_contracts.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-002",
        "newsroom.extraction.models:ExtractionRunRequest",
        "newsroom/tests/test_extraction_4a_contracts.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-003",
        "newsroom.extraction.models:ExtractionRunRequest",
        "newsroom/tests/test_extraction_4a_contracts.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-004",
        "newsroom.authority._extraction_store_commit:_ExtractionCommitMixin.commit_extraction_run",
        "newsroom/tests/test_extraction_4a_integrity.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-005",
        "newsroom.extraction.models:ProposalDraft",
        "newsroom/tests/test_extraction_4a_contracts.py",
        "PROPOSAL_UNCERTAINTY_ONLY_DEFERRED_4B",
    ),
    (
        "DREC-006",
        "newsroom.extraction.models:ExtractionRunVersion",
        "newsroom/tests/test_extraction_4a_integrity.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-007",
        "newsroom.authority._extraction_store_integrity:_ExtractionIntegrityMixin._validate_extraction_run_heads",
        "newsroom/tests/test_extraction_4a_integrity.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-010",
        "newsroom.extraction.models:ExtractionInputBinding",
        "newsroom/tests/test_extraction_4a_authority.py",
        "INHERITED_EXACT_INPUT_CONTRACT",
    ),
    (
        "DREC-011",
        "newsroom.extraction.models:ExtractionInputBinding",
        "newsroom/tests/test_extraction_4a_authority.py",
        "INHERITED_EXACT_INPUT_CONTRACT",
    ),
    (
        "DREC-013",
        "newsroom.extraction.models:ExtractionInputBinding",
        "newsroom/tests/test_extraction_4a_authority.py",
        "INHERITED_EXACT_INPUT_CONTRACT",
    ),
    (
        "DREC-014",
        "newsroom.extraction.models:ProposalEnvelope",
        "newsroom/tests/test_extraction_4a_security.py",
        "IMPLEMENTED_NONAUTHORITY_BOUNDARY",
    ),
    (
        "DREC-015",
        "newsroom.extraction.models:ExtractionInputBinding",
        "newsroom/tests/test_extraction_4a_authority.py",
        "INHERITED_EXACT_INPUT_CONTRACT",
    ),
    (
        "DREC-016",
        "newsroom.authority._extraction_store_common:_ExtractionStoreSupport._require_current_input",
        "newsroom/tests/test_extraction_4a_authority.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-020",
        "newsroom.extraction.models:ExtractionRunVersion",
        "newsroom/tests/test_extraction_4a_authority.py",
        "IMPLEMENTED_EXTRACTION_ANALOGUE",
    ),
    (
        "DREC-021",
        "newsroom.extraction.models:ExtractionRunVersion",
        "newsroom/tests/test_extraction_4a_integrity.py",
        "IMPLEMENTED_EXTRACTION_ANALOGUE",
    ),
    (
        "DREC-070",
        "newsroom.extraction.models:ExtractionInputBinding",
        "newsroom/tests/test_extraction_4a_authority.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-071",
        "newsroom.extraction.models:ExtractionRunRequest",
        "newsroom/tests/test_extraction_4a_integrity.py",
        "IMPLEMENTED_AT_EXTRACTION_SEAM",
    ),
    (
        "DREC-073",
        "newsroom.extraction.models:ProposalDraft",
        "newsroom/tests/test_extraction_4a_contracts.py",
        "PROPOSAL_ONLY_DEFERRED_4C",
    ),
    (
        "DREC-074",
        "newsroom.extraction.models:ExtractionRunVersion",
        "newsroom/tests/test_extraction_4a_integrity.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-076",
        "newsroom.extraction.models:ExtractorContractRequest",
        "newsroom/tests/test_extraction_4a_contracts.py",
        "IMPLEMENTED",
    ),
    (
        "DREC-077",
        "newsroom.authority._extraction_store_integrity:_ExtractionIntegrityMixin._validate_extraction_run_heads",
        "newsroom/tests/test_extraction_4a_integrity.py",
        "IMPLEMENTED",
    ),
    # Governed GraphRAG trust and extraction boundary.
    (
        "GRAG-010",
        "newsroom.extraction.models:ProposalEnvelope",
        "newsroom/tests/test_extraction_4a_security.py",
        "IMPLEMENTED",
    ),
    (
        "GRAG-011",
        "newsroom.extraction.models:ProposalDraft",
        "newsroom/tests/test_extraction_4a_security.py",
        "IMPLEMENTED",
    ),
    (
        "GRAG-012",
        "newsroom.extraction.types:ExtractionProposalKind",
        "newsroom/tests/test_extraction_4a_contracts.py",
        "BOUNDARY_ONLY_DEFERRED_4C",
    ),
    (
        "GRAG-013",
        "newsroom.extraction.models:ProposalEnvelope",
        "newsroom/tests/test_extraction_4a_contracts.py",
        "PROPOSAL_ONLY_DEFERRED_4C",
    ),
    (
        "GRAG-014",
        "newsroom.extraction.types:ExtractionProposalKind",
        "newsroom/tests/test_extraction_4a_traceability.py",
        "DEFERRED_4B",
    ),
    (
        "GRAG-015",
        "newsroom.extraction.types:ExtractionProposalKind",
        "newsroom/tests/test_extraction_4a_traceability.py",
        "DEFERRED_4B_4C",
    ),
    (
        "GRAG-016",
        "newsroom.authority._extraction_boundary:_ExtractionBoundary.proposals",
        "newsroom/tests/test_extraction_4a_security.py",
        "IMPLEMENTED_PROPOSAL_CONTEXT",
    ),
    (
        "GRAG-020",
        "newsroom.extraction.producer:DeterministicFixtureExtractor",
        "newsroom/tests/test_extraction_4a_security.py",
        "IMPLEMENTED",
    ),
    (
        "GRAG-021",
        "newsroom.authority._extraction_boundary:_ExtractionBoundary",
        "newsroom/tests/test_extraction_4a_security.py",
        "INTERFACE_ONLY_DEFERRED_4D",
    ),
    (
        "GRAG-022",
        "newsroom.authority._extraction_store_commit:_ExtractionCommitMixin.commit_extraction_run",
        "newsroom/tests/test_extraction_4a_authority.py",
        "IMPLEMENTED",
    ),
    (
        "GRAG-023",
        "newsroom.authority._extraction_boundary:_ExtractionBoundary",
        "newsroom/tests/test_extraction_4a_security.py",
        "NO_ADMISSION_SURFACE_DECISIONS_DEFERRED_4B_4C",
    ),
    (
        "GRAG-030",
        "newsroom.extraction.models:ExtractionRunVersion",
        "newsroom/tests/test_extraction_4a_integrity.py",
        "IMPLEMENTED",
    ),
    (
        "GRAG-034",
        "newsroom.authority._extraction_boundary:_ExtractionBoundary",
        "newsroom/tests/test_extraction_4a_security.py",
        "IMPLEMENTED",
    ),
    # Accepted production programme controls. 4A records boundaries; it does not
    # claim real Graphiti or actual-Neo4j qualification.
    (
        "GRPROD-010",
        "newsroom.extraction.fixtures:FIXTURE_MODEL_COMPONENT",
        "newsroom/tests/test_extraction_4a_security.py",
        "TARGET_RETAINED_RUNTIME_DISABLED",
    ),
    (
        "GRPROD-011",
        "newsroom.extraction.models:ExtractorContractRequest",
        "newsroom/tests/test_extraction_4a_traceability.py",
        "RUNTIME_QUALIFICATION_DEFERRED",
    ),
    (
        "GRPROD-012",
        "newsroom.extraction.types:ExtractionExecutionProfile",
        "newsroom/tests/test_extraction_4a_security.py",
        "ACTIVATION_BLOCKED",
    ),
    (
        "GRPROD-013",
        "newsroom.extraction.models:ProposalEnvelope",
        "newsroom/tests/test_extraction_4a_security.py",
        "IMPLEMENTED",
    ),
    (
        "GRPROD-014",
        "newsroom.authority._extraction_system:open_governed_extraction_authority_system",
        "newsroom/tests/test_extraction_4a_security.py",
        "INHERITED_REPOSITORY_DEPLOYMENT_CONTRACT",
    ),
    (
        "GRPROD-015",
        "newsroom.extraction.types:ExtractionExecutionProfile",
        "newsroom/tests/test_extraction_4a_security.py",
        "IMPLEMENTED_FAIL_CLOSED_PROFILE",
    ),
    (
        "GRPROD-016",
        "newsroom.authority._extraction_system:open_governed_extraction_authority_system",
        "newsroom/tests/test_extraction_4a_traceability.py",
        "ACTUAL_SERVICE_PROOF_DEFERRED_4E",
    ),
)

INCREMENT_4A_TRACEABILITY = tuple(
    ExtractionTraceabilityRow(*row) for row in _ROWS
)

INCREMENT_4A_ADR_ANCHORS = frozenset(
    {"ADR-0001", "ADR-0002", "ADR-0004", "ADR-0005"}
)

INCREMENT_4A_EXCLUSIONS = (
    "real Graphiti, model or embedding execution",
    "live source access, search, schedules, credentials and external spend",
    "Canonical Entity allocation or entity-resolution decisions (Increment 4B)",
    "relation admission, assertion or governed relation projection (Increment 4C)",
    "Graphiti proposal-workspace integration (Increment 4D)",
    "actual-Neo4j bilingual end-to-end proof (Increment 4E)",
    "Candidate, Evidence Intake, publication, production activation or public effect",
)

INCREMENT_4A_DEFERRED = (
    "owner-approved real Graphiti/model runtime decision packet",
    "entity mention, alias and Canonical Entity authority",
    "editorial predicate registry and relation admission authority",
    "isolated disposable proposal-workspace qualification",
    "authenticated actual-Neo4j admitted-only projection proof",
)

__all__ = [
    "ExtractionTraceabilityRow",
    "INCREMENT_4A_ADR_ANCHORS",
    "INCREMENT_4A_DEFERRED",
    "INCREMENT_4A_EXCLUSIONS",
    "INCREMENT_4A_TRACEABILITY",
]
