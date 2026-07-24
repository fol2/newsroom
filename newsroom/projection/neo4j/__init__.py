"""Typed B2 Neo4j projection contracts without a public driver or Cypher API."""

from .models import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_IMAGE,
    NEO4J_B2_SERVER_VERSION,
    Neo4jApplyOutcome,
    Neo4jApplyResult,
    Neo4jAuthorityCommitPending,
    Neo4jCompatibility,
    Neo4jCompatibilityError,
    Neo4jConfigurationError,
    Neo4jConnectionError,
    Neo4jIdentityConflict,
    Neo4jProjectionError,
    Neo4jProjectorConfig,
    Neo4jReadError,
    Neo4jStructuralRead,
    Neo4jWriteError,
    StructuralActiveReadRequest,
    StructuralBatch,
    StructuralDeliveryRequest,
    StructuralGraphNodeView,
    StructuralGraphRelationView,
    StructuralGenerationValidationRequest,
    StructuralNode,
    StructuralRebuildRequest,
    StructuralRebuildResult,
    StructuralReadMetadata,
    StructuralReadRequest,
    StructuralReadResponse,
    StructuralRelation,
)
from .qualification import (
    GraphRAGQualificationError,
    GraphRAGQualificationEvidence,
    GraphRAGQualificationReceipt,
    GraphRAGRuntimeConfig,
    GraphRuntimeKind,
    QUALIFYING_PROFILES,
    RuntimeProfile,
    neo4j_compatibility_digest,
    require_qualified_graphrag,
)
from .traceability import (
    INCREMENT_1B2_DEFERRED,
    INCREMENT_1B2_EXCLUSIONS,
    INCREMENT_1B2_TRACEABILITY,
)


def __getattr__(name: str):
    if name in {
        "Neo4jProjectionAuthoritySystem",
        "Neo4jStructuralProjector",
        "open_neo4j_projection_authority_system",
    }:
        from newsroom.authority import neo4j_projection_system as _system

        return getattr(_system, name)
    raise AttributeError(name)


__all__ = [
    "require_qualified_graphrag",
    "neo4j_compatibility_digest",
    "RuntimeProfile",
    "QUALIFYING_PROFILES",
    "GraphRuntimeKind",
    "GraphRAGRuntimeConfig",
    "GraphRAGQualificationReceipt",
    "GraphRAGQualificationEvidence",
    "GraphRAGQualificationError",
    "INCREMENT_1B2_DEFERRED",
    "INCREMENT_1B2_EXCLUSIONS",
    "INCREMENT_1B2_TRACEABILITY",
    "NEO4J_B2_DRIVER_VERSION",
    "NEO4J_B2_IMAGE",
    "NEO4J_B2_SERVER_VERSION",
    "Neo4jApplyOutcome",
    "Neo4jApplyResult",
    "Neo4jAuthorityCommitPending",
    "Neo4jCompatibility",
    "Neo4jCompatibilityError",
    "Neo4jConfigurationError",
    "Neo4jConnectionError",
    "Neo4jIdentityConflict",
    "Neo4jProjectionAuthoritySystem",
    "Neo4jProjectionError",
    "Neo4jProjectorConfig",
    "Neo4jReadError",
    "Neo4jStructuralProjector",
    "Neo4jStructuralRead",
    "Neo4jWriteError",
    "StructuralActiveReadRequest",
    "StructuralBatch",
    "StructuralDeliveryRequest",
    "StructuralGraphNodeView",
    "StructuralGraphRelationView",
    "StructuralGenerationValidationRequest",
    "StructuralNode",
    "StructuralRebuildRequest",
    "StructuralRebuildResult",
    "StructuralReadMetadata",
    "StructuralReadRequest",
    "StructuralReadResponse",
    "StructuralRelation",
    "open_neo4j_projection_authority_system",
]
