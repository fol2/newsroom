"""Requirement evidence for Increment 1B1 graph contracts and projection authority."""

from __future__ import annotations


INCREMENT_1B1_TRACEABILITY: dict[str, tuple[str, ...]] = {
    "newsroom.authority.projection_migrations": (
        "ADR-0001",
        "ADR-0002",
        "GRAG-002",
        "GRAG-003",
        "GRAG-005",
        "GRAG-030",
        "GRPROD-020",
    ),
    "newsroom.projection.ontology": (
        "ADR-0004",
        "GRAG-001",
        "GRAG-003",
        "GRAG-010",
        "GRAG-011",
    ),
    "newsroom.projection.mapping": (
        "ADR-0004",
        "DREC-040",
        "DREC-041",
        "GRAG-003",
        "GRAG-010",
        "GRAG-012",
    ),
    "newsroom.projection.policy": (
        "ADR-0001",
        "ADR-0002",
        "GRAG-002",
        "GRAG-005",
        "GRPROD-005",
    ),
    "newsroom.authority._projection_store": (
        "ADR-0001",
        "ADR-0002",
        "DREC-070",
        "DREC-073",
        "DREC-074",
        "GRAG-002",
        "GRAG-003",
        "GRAG-004",
        "GRAG-005",
        "GRAG-030",
        "GRPROD-020",
    ),
    "newsroom.authority.projection_system": (
        "ADR-0001",
        "ADR-0004",
        "DREC-076",
        "GRAG-002",
        "GRAG-005",
        "GRAG-010",
        "GRPROD-005",
    ),
    "newsroom.tests.test_projection_b1_contracts": (
        "GRAG-001",
        "GRAG-003",
        "GRAG-010",
        "GRAG-011",
        "GRAG-012",
    ),
    "newsroom.tests.test_projection_b1_authority": (
        "DREC-070",
        "DREC-073",
        "DREC-074",
        "GRAG-002",
        "GRAG-004",
        "GRAG-005",
        "GRAG-030",
    ),
    "newsroom.tests.test_projection_b1_migrations": (
        "ADR-0002",
        "DREC-006",
        "DREC-070",
        "GRAG-002",
        "GRAG-005",
    ),
    "newsroom.tests.test_projection_b1_boundaries": (
        "ADR-0004",
        "GRAG-002",
        "GRAG-010",
        "GRPROD-005",
    ),
}


INCREMENT_1B1_EXCLUSIONS: tuple[str, ...] = (
    "NEO4J_CLIENT_OR_SERVICE",
    "GOVERNED_GRAPH_WRITES",
    "GRAPHITI_EXECUTION",
    "EMBEDDINGS",
    "VECTOR_INDEX_IMPLEMENTATION",
    "FULL_TEXT_INDEX_IMPLEMENTATION",
    "LIVE_SOURCES",
    "MODEL_CALLS",
    "CANDIDATE_OR_TRIAGE",
    "SHADOW_CANARY_OR_PRODUCTION",
    "SPENDING",
)


INCREMENT_1B1_DEFERRED: tuple[str, ...] = (
    "NEO4J_IMAGE_AND_RELEASE_QUALIFICATION",
    "GRAPH_BACKUP_AND_RESTORE_PROCEDURE",
    "PROJECTOR_THROUGHPUT_AND_LAG_THRESHOLDS",
    "SUCCESSFUL_PROJECTION_READ_AUDIT_RETENTION",
)


__all__ = [
    "INCREMENT_1B1_DEFERRED",
    "INCREMENT_1B1_EXCLUSIONS",
    "INCREMENT_1B1_TRACEABILITY",
]
