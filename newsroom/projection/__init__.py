"""Engine-neutral native GraphRAG projection contracts.

Neo4j and Graphiti adapters are intentionally absent from Increment 1B1.  The
public surface contains typed immutable contracts, authenticated projection
facades, and non-authoritative views only.
"""

from .mapping import (
    StructuralEventMapping,
    StructuralMappingContract,
    StructuralMappingRegistry,
    native_structural_mapping_v1,
)
from .models import (
    DeliveryRecordView,
    ProjectionCheckpointView,
    ProjectionContractError,
    ProjectionDeadLetterId,
    ProjectionDeadLetterView,
    ProjectionDeliveryOutcome,
    ProjectionFamilyDefinition,
    ProjectionFamilyKind,
    ProjectionGapId,
    ProjectionGapState,
    ProjectionGapView,
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionGenerationView,
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
from .registry import ProjectionFamilyRegistry

__all__ = [
    "DeliveryRecordView",
    "OntologyContract",
    "OntologyNodeDefinition",
    "OntologyRegistry",
    "OntologyRelationDefinition",
    "ProjectionCheckpointView",
    "ProjectionContractError",
    "ProjectionDeadLetterId",
    "ProjectionDeadLetterView",
    "ProjectionDeliveryOutcome",
    "ProjectionFamilyDefinition",
    "ProjectionFamilyKind",
    "ProjectionFamilyRegistry",
    "ProjectionGapId",
    "ProjectionGapState",
    "ProjectionGapView",
    "ProjectionGenerationId",
    "ProjectionGenerationState",
    "ProjectionGenerationView",
    "ProjectionNodeType",
    "ProjectionRelationType",
    "ProjectionStateError",
    "ProjectionStatusMetadata",
    "StructuralEventMapping",
    "StructuralMappingContract",
    "StructuralMappingRegistry",
    "native_ontology_v1",
    "native_structural_mapping_v1",
]
