from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest

from ..models import (
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionGenerationValidationView,
    ProjectionStatusMetadata,
)
from .models import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
    Neo4jCompatibility,
    Neo4jProjectorConfig,
    StructuralReadAuthoritySelection,
    StructuralReadMetadata,
)


class GraphRAGQualificationError(RuntimeError):
    """A qualifying runtime attempted to proceed without exact native GraphRAG."""


class RuntimeProfile(StrEnum):
    DEVELOPMENT = "development"
    UNIT = "unit"
    EVALUATION = "evaluation"
    COMPLETE_LIVE_SHADOW = "complete-live-shadow"
    PRODUCTION = "production"


class GraphRuntimeKind(StrEnum):
    NATIVE_NEO4J = "native-neo4j"
    FAKE = "fake"
    NO_OP = "no-op"
    IN_MEMORY = "in-memory"


QUALIFYING_PROFILES = frozenset(
    {
        RuntimeProfile.EVALUATION,
        RuntimeProfile.COMPLETE_LIVE_SHADOW,
        RuntimeProfile.PRODUCTION,
    }
)


@dataclass(frozen=True, slots=True)
class GraphRAGRuntimeConfig:
    profile: RuntimeProfile
    enabled: bool
    runtime_kind: GraphRuntimeKind
    projector_config: Neo4jProjectorConfig | None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, RuntimeProfile):
            raise GraphRAGQualificationError("runtime profile must be typed")
        if not isinstance(self.enabled, bool):
            raise GraphRAGQualificationError("GraphRAG enabled flag must be boolean")
        if not isinstance(self.runtime_kind, GraphRuntimeKind):
            raise GraphRAGQualificationError("graph runtime kind must be typed")
        if self.projector_config is not None and not isinstance(
            self.projector_config, Neo4jProjectorConfig
        ):
            raise GraphRAGQualificationError("projector configuration must be typed")


@dataclass(frozen=True, slots=True)
class GraphRAGQualificationEvidence:
    compatibility: Neo4jCompatibility | None
    compatibility_digest: str | None
    projection_state_digest: str | None
    status: ProjectionStatusMetadata | None
    validation: ProjectionGenerationValidationView | None
    read_metadata: StructuralReadMetadata | None
    required_authority_watermark: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.required_authority_watermark, bool)
            or not isinstance(self.required_authority_watermark, int)
            or self.required_authority_watermark < 0
        ):
            raise GraphRAGQualificationError(
                "required authority watermark must be non-negative"
            )
        for field_name in ("compatibility_digest", "projection_state_digest"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = validate_sha256_digest(value, field=field_name)
                if normalized != value:
                    raise GraphRAGQualificationError(
                        f"{field_name} must be canonical lowercase"
                    )


@dataclass(frozen=True, slots=True)
class GraphRAGQualificationReceipt:
    profile: RuntimeProfile
    generation_id: ProjectionGenerationId | None
    authority_watermark: int
    compatibility_digest: str | None
    projection_state_digest: str | None
    qualifying_profile: bool


def neo4j_compatibility_digest(value: Neo4jCompatibility) -> str:
    if not isinstance(value, Neo4jCompatibility):
        raise GraphRAGQualificationError("Neo4j compatibility must be typed")
    return digest_canonical(
        {
            "server_version": value.server_version,
            "edition": value.edition,
            "driver_version": value.driver_version,
        }
    )


def require_qualified_graphrag(
    config: GraphRAGRuntimeConfig,
    evidence: GraphRAGQualificationEvidence,
) -> GraphRAGQualificationReceipt:
    """Fail closed for every profile that can qualify product behaviour.

    Development and unit profiles remain explicit non-qualifying environments.
    They may use a fake or disable graph access, but their receipt cannot be
    presented as evaluation, complete-shadow, or production evidence.
    """

    if not isinstance(config, GraphRAGRuntimeConfig):
        raise GraphRAGQualificationError("GraphRAG runtime config must be typed")
    if not isinstance(evidence, GraphRAGQualificationEvidence):
        raise GraphRAGQualificationError("GraphRAG evidence must be typed")

    if config.profile not in QUALIFYING_PROFILES:
        return GraphRAGQualificationReceipt(
            profile=config.profile,
            generation_id=(
                None if evidence.status is None else evidence.status.generation_id
            ),
            authority_watermark=(
                0 if evidence.status is None else evidence.status.contiguous_ledger_seq
            ),
            compatibility_digest=evidence.compatibility_digest,
            projection_state_digest=evidence.projection_state_digest,
            qualifying_profile=False,
        )

    if not config.enabled:
        raise GraphRAGQualificationError(
            "qualifying profile cannot disable GraphRAG"
        )
    if config.runtime_kind is not GraphRuntimeKind.NATIVE_NEO4J:
        raise GraphRAGQualificationError(
            "qualifying profile requires the native Neo4j runtime"
        )
    if config.projector_config is None:
        raise GraphRAGQualificationError(
            "qualifying profile requires authenticated Neo4j configuration"
        )

    compatibility = evidence.compatibility
    if compatibility is None or evidence.compatibility_digest is None:
        raise GraphRAGQualificationError(
            "qualifying profile requires current Neo4j compatibility evidence"
        )
    if (
        compatibility.server_version != NEO4J_B2_SERVER_VERSION
        or compatibility.driver_version != NEO4J_B2_DRIVER_VERSION
        or compatibility.edition.casefold() != "community"
    ):
        raise GraphRAGQualificationError(
            "Neo4j service or driver differs from the qualified target"
        )
    if neo4j_compatibility_digest(compatibility) != evidence.compatibility_digest:
        raise GraphRAGQualificationError(
            "Neo4j compatibility digest is stale or inconsistent"
        )

    status = evidence.status
    if status is None or status.generation_id is None:
        raise GraphRAGQualificationError(
            "qualifying profile requires an authority-selected active generation"
        )
    if status.generation_state is not ProjectionGenerationState.ACTIVE:
        raise GraphRAGQualificationError(
            "authority-selected generation is not ACTIVE"
        )
    if status.open_gap_count:
        raise GraphRAGQualificationError(
            "required projection gap blocks qualifying GraphRAG"
        )
    if status.dead_letter_count:
        raise GraphRAGQualificationError(
            "projection dead letter blocks qualifying GraphRAG"
        )
    if status.contiguous_ledger_seq < evidence.required_authority_watermark:
        raise GraphRAGQualificationError(
            "active generation is behind the required authority watermark"
        )

    validation = evidence.validation
    if validation is None:
        raise GraphRAGQualificationError(
            "active generation lacks retained validation evidence"
        )
    if validation.generation_id != status.generation_id:
        raise GraphRAGQualificationError(
            "validation belongs to another generation"
        )
    if validation.checkpoint_ledger_seq != status.contiguous_ledger_seq:
        raise GraphRAGQualificationError(
            "active generation validation is stale"
        )
    if validation.service_compatibility_digest != evidence.compatibility_digest:
        raise GraphRAGQualificationError(
            "validation binds another service compatibility target"
        )
    if evidence.projection_state_digest is None:
        raise GraphRAGQualificationError(
            "qualifying profile requires current graph-state evidence"
        )
    if validation.projection_state_digest != evidence.projection_state_digest:
        raise GraphRAGQualificationError(
            "validation binds another graph state"
        )
    if (
        validation.ontology_contract_digest != status.ontology_contract_digest
        or validation.mapping_contract_digest != status.mapping_contract_digest
        or validation.projector_version != status.projector_version
    ):
        raise GraphRAGQualificationError(
            "validation contract identities differ from active authority"
        )

    metadata = evidence.read_metadata
    if metadata is None:
        raise GraphRAGQualificationError(
            "qualifying profile requires a current bounded graph read"
        )
    if (
        metadata.authority_selection
        is not StructuralReadAuthoritySelection.AUTHORITY_SELECTED_ACTIVE
    ):
        raise GraphRAGQualificationError(
            "qualifying profile requires an authority-selected ACTIVE read"
        )
    if (
        metadata.generation_id != status.generation_id
        or metadata.generation_state is not ProjectionGenerationState.ACTIVE
    ):
        raise GraphRAGQualificationError(
            "graph read does not use the authority-selected active generation"
        )
    if (
        metadata.family_id != status.family_id
        or metadata.projector_version != status.projector_version
        or metadata.ontology_contract_digest != status.ontology_contract_digest
        or metadata.mapping_contract_digest != status.mapping_contract_digest
    ):
        raise GraphRAGQualificationError(
            "graph read metadata differs from active authority contracts"
        )
    if metadata.contiguous_ledger_seq != status.contiguous_ledger_seq:
        raise GraphRAGQualificationError(
            "graph read watermark differs from active authority"
        )
    if metadata.contiguous_ledger_seq < evidence.required_authority_watermark:
        raise GraphRAGQualificationError(
            "graph state is behind the required authority watermark"
        )
    if metadata.open_gap_count or metadata.dead_letter_count:
        raise GraphRAGQualificationError(
            "graph read reports unresolved projection failure state"
        )
    if metadata.authoritative_system != "sqlite-ledger-and-governed-objects":
        raise GraphRAGQualificationError(
            "graph read does not return to the authoritative systems"
        )
    if metadata.graph_role != "non-authoritative-rebuildable-context":
        raise GraphRAGQualificationError(
            "graph read incorrectly claims authority"
        )

    return GraphRAGQualificationReceipt(
        profile=config.profile,
        generation_id=status.generation_id,
        authority_watermark=status.contiguous_ledger_seq,
        compatibility_digest=evidence.compatibility_digest,
        projection_state_digest=evidence.projection_state_digest,
        qualifying_profile=True,
    )


__all__ = [
    "GraphRAGQualificationError",
    "GraphRAGQualificationEvidence",
    "GraphRAGQualificationReceipt",
    "GraphRAGRuntimeConfig",
    "GraphRuntimeKind",
    "QUALIFYING_PROFILES",
    "RuntimeProfile",
    "neo4j_compatibility_digest",
    "require_qualified_graphrag",
]
