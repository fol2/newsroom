"""Engine-neutral native GraphRAG projection contracts and authority facades.

Neo4j and Graphiti execution adapters are intentionally absent from Increment
1B1. The public surface exposes typed contracts, authenticated projection
facades and non-authoritative views only.
"""

from .mapping import (
    ProjectionIdentitySource,
    StructuralEventMapping,
    StructuralIdentityContext,
    StructuralMappingContract,
    StructuralMappingRegistry,
    StructuralNodeBinding,
    StructuralRelationBinding,
    canonical_node_id,
    native_structural_mapping_v1,
)
from .models import (
    DeliveryRecordView,
    GraphitiProposalWorkspaceContract,
    GraphitiWorkspaceMode,
    ProjectionAuthorizationError,
    ProjectionCheckpointView,
    ProjectionContractError,
    ProjectionDeadLetterId,
    ProjectionDeadLetterView,
    ProjectionDeliveryAttemptId,
    ProjectionDeliveryOutcome,
    ProjectionDeliveryRequest,
    ProjectionFamilyDefinition,
    ProjectionFamilyKind,
    ProjectionFamilyRegistrationRequest,
    ProjectionFamilyView,
    ProjectionGapId,
    ProjectionGapResolutionRequest,
    ProjectionGapState,
    ProjectionGapView,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionGenerationTransitionRequest,
    ProjectionGenerationView,
    ProjectionReadPolicy,
    ProjectionStateError,
    ProjectionStatusMetadata,
)
from .ontology import (
    OntologyContract,
    OntologyNodeDefinition,
    OntologyRegistry,
    OntologyRelationDefinition,
    ProjectionNodeType,
    ProjectionRelationType,
    native_ontology_v1,
)
from .policy import (
    PROJECTION_COMMAND_TYPES,
    ProjectionContractRegistry,
    merge_projection_authority_registries,
    projection_command_definitions,
    projection_payload_contracts,
)
from .registry import ProjectionFamilyRegistry
from .traceability import (
    INCREMENT_1B1_DEFERRED,
    INCREMENT_1B1_EXCLUSIONS,
    INCREMENT_1B1_TRACEABILITY,
)

def __getattr__(name: str):
    if name in {
        "NativeProjectionAuthoritySystem",
        "NativeProjections",
        "open_native_projection_authority_system",
    }:
        from . import system as _system

        return getattr(_system, name)
    raise AttributeError(name)


__all__ = [
    "DeliveryRecordView",
    "GraphitiProposalWorkspaceContract",
    "GraphitiWorkspaceMode",
    "INCREMENT_1B1_DEFERRED",
    "INCREMENT_1B1_EXCLUSIONS",
    "INCREMENT_1B1_TRACEABILITY",
    "OntologyContract",
    "OntologyNodeDefinition",
    "OntologyRegistry",
    "NativeProjectionAuthoritySystem",
    "NativeProjections",
    "OntologyRelationDefinition",
    "PROJECTION_COMMAND_TYPES",
    "ProjectionAuthorizationError",
    "ProjectionCheckpointView",
    "ProjectionContractError",
    "ProjectionContractRegistry",
    "ProjectionDeadLetterId",
    "ProjectionDeadLetterView",
    "ProjectionDeliveryAttemptId",
    "ProjectionDeliveryOutcome",
    "ProjectionDeliveryRequest",
    "ProjectionFamilyDefinition",
    "ProjectionFamilyKind",
    "ProjectionFamilyRegistrationRequest",
    "ProjectionFamilyRegistry",
    "ProjectionFamilyView",
    "ProjectionGapId",
    "ProjectionGapResolutionRequest",
    "ProjectionGapState",
    "ProjectionGapView",
    "ProjectionGenerationCreateRequest",
    "ProjectionGenerationId",
    "ProjectionGenerationState",
    "ProjectionGenerationTransitionRequest",
    "ProjectionGenerationView",
    "ProjectionIdentitySource",
    "ProjectionNodeType",
    "ProjectionReadPolicy",
    "ProjectionRelationType",
    "ProjectionStateError",
    "ProjectionStatusMetadata",
    "StructuralEventMapping",
    "StructuralIdentityContext",
    "StructuralMappingContract",
    "StructuralMappingRegistry",
    "StructuralNodeBinding",
    "StructuralRelationBinding",
    "canonical_node_id",
    "merge_projection_authority_registries",
    "native_ontology_v1",
    "native_structural_mapping_v1",
    "open_native_projection_authority_system",
    "projection_command_definitions",
    "projection_payload_contracts",
]
