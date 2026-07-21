from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest
from newsroom.authority.types import TrustScope, UtcTimestamp, require_token
from newsroom.projection.models import (
    ProjectionContractError,
    ProjectionGenerationId,
    ProjectionGenerationState,
)
from newsroom.projection.ontology import ProjectionNodeType, ProjectionRelationType


NEO4J_B2_IMAGE = "neo4j:2026.06.0-community-trixie"
NEO4J_B2_SERVER_VERSION = "2026.06.0"
NEO4J_B2_DRIVER_VERSION = "6.2.0"


class Neo4jProjectionError(RuntimeError):
    """Base error for the non-authoritative Neo4j projection boundary."""


class Neo4jConfigurationError(Neo4jProjectionError, ValueError):
    """Raised before connection when projector configuration is unsafe."""


class Neo4jCompatibilityError(Neo4jProjectionError):
    """Raised when the service or driver is not the exact B2 target."""


class Neo4jConnectionError(Neo4jProjectionError):
    """Raised with a fixed, credential-free connectivity message."""


class Neo4jWriteError(Neo4jProjectionError):
    """Raised with a fixed, credential-free graph write message."""


class Neo4jReadError(Neo4jProjectionError):
    """Raised with a fixed, credential-free graph read message."""


class Neo4jIdentityConflict(Neo4jProjectionError):
    """Raised when an existing graph identity has different exact provenance."""


class Neo4jAuthorityCommitPending(Neo4jProjectionError):
    """Graph commit exists but the authoritative B1 transition did not commit."""


class Neo4jApplyOutcome(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True, repr=False)
class Neo4jProjectorConfig:
    uri: str
    database: str
    username: str
    password: str

    def __post_init__(self) -> None:
        if not isinstance(self.uri, str) or not self.uri.strip():
            raise Neo4jConfigurationError("Neo4j URI is required")
        if self.uri != self.uri.strip() or len(self.uri.encode("utf-8")) > 512:
            raise Neo4jConfigurationError("Neo4j URI must be bounded canonical text")
        parsed = urlsplit(self.uri)
        if parsed.scheme not in {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}:
            raise Neo4jConfigurationError("Neo4j URI must use an authenticated Bolt-compatible scheme")
        if parsed.username is not None or parsed.password is not None:
            raise Neo4jConfigurationError("Neo4j credentials must not be embedded in the URI")
        if parsed.query or parsed.fragment:
            raise Neo4jConfigurationError(
                "Neo4j URI must not contain query or fragment data"
            )
        if parsed.path not in {"", "/"}:
            raise Neo4jConfigurationError(
                "Neo4j URI must not contain a database path"
            )
        if not parsed.hostname:
            raise Neo4jConfigurationError("Neo4j URI requires a host")
        try:
            parsed.port
        except ValueError:
            raise Neo4jConfigurationError("Neo4j URI port is invalid") from None
        require_token(self.database, field="neo4j_database")
        require_token(self.username, field="neo4j_projector_username")
        if not isinstance(self.password, str) or not self.password:
            raise Neo4jConfigurationError("Neo4j projector password is required")
        if self.password.strip().lower() == "none":
            raise Neo4jConfigurationError("Neo4j authentication cannot be disabled")
        if len(self.password.encode("utf-8")) > 4096:
            raise Neo4jConfigurationError("Neo4j projector password is too large")

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> Neo4jProjectorConfig:
        values = os.environ if environment is None else environment
        required = {
            "uri": "NEWSROOM_NEO4J_URI",
            "database": "NEWSROOM_NEO4J_DATABASE",
            "username": "NEWSROOM_NEO4J_PROJECTOR_USERNAME",
            "password": "NEWSROOM_NEO4J_PROJECTOR_PASSWORD",
        }
        missing = [name for name in required.values() if not values.get(name)]
        if missing:
            raise Neo4jConfigurationError(
                "Neo4j projector configuration is incomplete: " + ", ".join(sorted(missing))
            )
        return cls(**{field: values[name] for field, name in required.items()})

    def __repr__(self) -> str:
        return (
            "Neo4jProjectorConfig("
            f"uri={self.uri!r}, database={self.database!r}, "
            f"username={self.username!r}, password='<redacted>')"
        )


@dataclass(frozen=True, slots=True)
class Neo4jCompatibility:
    server_version: str
    edition: str
    driver_version: str

    def __post_init__(self) -> None:
        _require_text(self.server_version, field="neo4j_server_version")
        require_token(self.edition, field="neo4j_edition")
        _require_text(self.driver_version, field="neo4j_driver_version")


@dataclass(frozen=True, slots=True)
class StructuralNode:
    canonical_id: str
    node_type: ProjectionNodeType
    identity_source: str
    identity_reference_digest: str
    first_ledger_seq: int
    first_source_event_id: str
    first_source_event_digest: str

    def __post_init__(self) -> None:
        _require_canonical_id(self.canonical_id)
        if not isinstance(self.node_type, ProjectionNodeType):
            raise ProjectionContractError("Neo4j structural node type must be typed")
        require_token(self.identity_source, field="projection_identity_source")
        validate_sha256_digest(
            self.identity_reference_digest,
            field="identity_reference_digest",
        )
        _require_positive_int(self.first_ledger_seq, field="first_ledger_seq")
        _require_text(self.first_source_event_id, field="first_source_event_id")
        validate_sha256_digest(
            self.first_source_event_digest,
            field="first_source_event_digest",
        )


@dataclass(frozen=True, slots=True)
class StructuralRelation:
    relation_key: str
    relation_type: ProjectionRelationType
    source_canonical_id: str
    target_canonical_id: str
    ledger_seq: int
    source_event_id: str
    source_event_type: str
    source_event_digest: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    payload_id: str
    payload_digest: str
    object_admission_id: str | None
    principal_id: str
    trust_scope: TrustScope
    security_scope: str
    retention_scope: str
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        validate_sha256_digest(self.relation_key, field="relation_key")
        if not isinstance(self.relation_type, ProjectionRelationType):
            raise ProjectionContractError("Neo4j relation type must be typed")
        _require_canonical_id(self.source_canonical_id)
        _require_canonical_id(self.target_canonical_id)
        if self.source_canonical_id == self.target_canonical_id:
            raise ProjectionContractError("Neo4j structural relation endpoints must differ")
        _require_positive_int(self.ledger_seq, field="ledger_seq")
        _require_text(self.source_event_id, field="source_event_id")
        require_token(self.source_event_type, field="source_event_type")
        validate_sha256_digest(self.source_event_digest, field="source_event_digest")
        require_token(self.aggregate_type, field="aggregate_type")
        _require_text(self.aggregate_id, field="aggregate_id")
        _require_positive_int(self.aggregate_version, field="aggregate_version")
        _require_text(self.payload_id, field="payload_id")
        validate_sha256_digest(self.payload_digest, field="payload_digest")
        if self.object_admission_id is not None:
            _require_text(self.object_admission_id, field="object_admission_id")
        require_token(self.principal_id, field="principal_id")
        if not isinstance(self.trust_scope, TrustScope):
            raise ProjectionContractError("relation trust scope must be typed")
        require_token(self.security_scope, field="security_scope")
        require_token(self.retention_scope, field="retention_scope")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise ProjectionContractError("relation recorded_at must be UtcTimestamp")


@dataclass(frozen=True, slots=True)
class StructuralBatch:
    generation_id: ProjectionGenerationId
    family_id: str
    family_definition_version: str
    projector_version: str
    ontology_contract_digest: str
    mapping_contract_digest: str
    ledger_seq: int
    source_event_id: str
    source_event_type: str
    source_event_digest: str
    nodes: tuple[StructuralNode, ...]
    relations: tuple[StructuralRelation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.generation_id, ProjectionGenerationId):
            raise ProjectionContractError("Neo4j batch generation identity must be typed")
        require_token(self.family_id, field="projection_family_id")
        require_token(
            self.family_definition_version,
            field="projection_family_definition_version",
        )
        require_token(self.projector_version, field="projector_version")
        validate_sha256_digest(
            self.ontology_contract_digest,
            field="ontology_contract_digest",
        )
        validate_sha256_digest(
            self.mapping_contract_digest,
            field="mapping_contract_digest",
        )
        _require_positive_int(self.ledger_seq, field="ledger_seq")
        _require_text(self.source_event_id, field="source_event_id")
        require_token(self.source_event_type, field="source_event_type")
        validate_sha256_digest(self.source_event_digest, field="source_event_digest")
        if not isinstance(self.nodes, tuple) or not self.nodes:
            raise ProjectionContractError("Neo4j structural batch requires nodes")
        if not isinstance(self.relations, tuple) or not self.relations:
            raise ProjectionContractError("Neo4j structural batch requires relations")
        canonical_ids = [item.canonical_id for item in self.nodes]
        if len(canonical_ids) != len(set(canonical_ids)):
            raise ProjectionContractError("Neo4j batch canonical node IDs must be unique")
        known = set(canonical_ids)
        for relation in self.relations:
            if (
                relation.source_canonical_id not in known
                or relation.target_canonical_id not in known
            ):
                raise ProjectionContractError("Neo4j relation references an absent batch node")
            if (
                relation.ledger_seq != self.ledger_seq
                or relation.source_event_id != self.source_event_id
                or relation.source_event_digest != self.source_event_digest
            ):
                raise ProjectionContractError("Neo4j relation provenance does not match its batch")

    @property
    def batch_digest(self) -> str:
        return digest_canonical(
            {
                "generation_id": str(self.generation_id),
                "family_id": self.family_id,
                "family_definition_version": self.family_definition_version,
                "projector_version": self.projector_version,
                "ontology_contract_digest": self.ontology_contract_digest,
                "mapping_contract_digest": self.mapping_contract_digest,
                "ledger_seq": self.ledger_seq,
                "source_event_id": self.source_event_id,
                "source_event_type": self.source_event_type,
                "source_event_digest": self.source_event_digest,
                "nodes": [
                    {
                        "canonical_id": item.canonical_id,
                        "node_type": item.node_type.value,
                        "identity_source": item.identity_source,
                        "identity_reference_digest": item.identity_reference_digest,
                        "first_ledger_seq": item.first_ledger_seq,
                        "first_source_event_id": item.first_source_event_id,
                        "first_source_event_digest": item.first_source_event_digest,
                    }
                    for item in self.nodes
                ],
                "relations": [
                    {
                        "relation_key": item.relation_key,
                        "relation_type": item.relation_type.value,
                        "source_canonical_id": item.source_canonical_id,
                        "target_canonical_id": item.target_canonical_id,
                        "ledger_seq": item.ledger_seq,
                        "source_event_id": item.source_event_id,
                        "source_event_type": item.source_event_type,
                        "source_event_digest": item.source_event_digest,
                        "aggregate_type": item.aggregate_type,
                        "aggregate_id": item.aggregate_id,
                        "aggregate_version": item.aggregate_version,
                        "payload_id": item.payload_id,
                        "payload_digest": item.payload_digest,
                        "object_admission_id": item.object_admission_id,
                        "principal_id": item.principal_id,
                        "trust_scope": item.trust_scope.value,
                        "security_scope": item.security_scope,
                        "retention_scope": item.retention_scope,
                        "recorded_at": item.recorded_at.to_text(),
                    }
                    for item in self.relations
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class Neo4jApplyResult:
    outcome: Neo4jApplyOutcome
    generation_id: ProjectionGenerationId
    ledger_seq: int
    source_event_id: str
    source_event_digest: str
    batch_digest: str


@dataclass(frozen=True, slots=True)
class StructuralGraphNodeView:
    canonical_id: str
    node_type: ProjectionNodeType
    identity_source: str
    identity_reference_digest: str
    first_ledger_seq: int
    first_source_event_id: str
    first_source_event_digest: str


@dataclass(frozen=True, slots=True)
class StructuralGraphRelationView:
    relation_key: str
    relation_type: ProjectionRelationType
    source_canonical_id: str
    target_canonical_id: str
    ledger_seq: int
    source_event_id: str
    source_event_type: str
    source_event_digest: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    payload_id: str
    payload_digest: str
    object_admission_id: str | None
    principal_id: str
    trust_scope: TrustScope
    security_scope: str
    retention_scope: str
    recorded_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class Neo4jStructuralRead:
    nodes: tuple[StructuralGraphNodeView, ...]
    relations: tuple[StructuralGraphRelationView, ...]


@dataclass(frozen=True, slots=True)
class StructuralDeliveryRequest:
    generation_id: ProjectionGenerationId
    expected_authority_version: int
    ledger_seq: int
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.generation_id, ProjectionGenerationId):
            raise ProjectionContractError(
                "structural delivery generation identity must be typed"
            )
        _require_positive_int(
            self.expected_authority_version,
            field="expected_authority_version",
        )
        _require_positive_int(self.ledger_seq, field="ledger_seq")
        if (
            not isinstance(self.idempotency_key, str)
            or not self.idempotency_key.strip()
            or len(self.idempotency_key.encode("utf-8")) > 256
        ):
            raise ProjectionContractError(
                "structural delivery idempotency key is invalid"
            )


@dataclass(frozen=True, slots=True)
class StructuralReadRequest:
    generation_id: ProjectionGenerationId
    canonical_ids: tuple[str, ...]
    query_valid_time: UtcTimestamp
    limit: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.generation_id, ProjectionGenerationId):
            raise ProjectionContractError("structural read generation identity must be typed")
        if not isinstance(self.canonical_ids, tuple) or not self.canonical_ids:
            raise ProjectionContractError("structural read requires canonical IDs")
        if len(self.canonical_ids) > 1000:
            raise ProjectionContractError("structural read canonical ID window is too large")
        for item in self.canonical_ids:
            _require_canonical_id(item)
        if len(set(self.canonical_ids)) != len(self.canonical_ids):
            raise ProjectionContractError("structural read canonical IDs must be unique")
        if not isinstance(self.query_valid_time, UtcTimestamp):
            raise ProjectionContractError("query_valid_time must be UtcTimestamp")
        _require_positive_int(self.limit, field="structural_read_limit")


@dataclass(frozen=True, slots=True)
class StructuralReadMetadata:
    family_id: str
    family_definition_version: str
    projector_version: str
    ontology_contract_digest: str
    mapping_contract_digest: str
    generation_id: ProjectionGenerationId
    generation_state: ProjectionGenerationState
    contiguous_ledger_seq: int
    open_gap_count: int
    dead_letter_count: int
    trust_scope: TrustScope
    query_valid_time: UtcTimestamp
    serving_time: UtcTimestamp
    authoritative_system: str = "sqlite-ledger-and-governed-objects"
    graph_role: str = "non-authoritative-rebuildable-context"


@dataclass(frozen=True, slots=True)
class StructuralReadResponse:
    metadata: StructuralReadMetadata
    nodes: tuple[StructuralGraphNodeView, ...]
    relations: tuple[StructuralGraphRelationView, ...]


_ALLOWED_GRAPH_PROPERTY_TYPES = (str, int, bool, type(None))


def immutable_properties(value: Mapping[str, object]) -> Mapping[str, object]:
    """Validate fixed adapter output before exposing an immutable mapping."""

    if not isinstance(value, Mapping):
        raise Neo4jReadError("Neo4j returned malformed projection properties")
    copied = dict(value)
    if any(not isinstance(item, _ALLOWED_GRAPH_PROPERTY_TYPES) for item in copied.values()):
        raise Neo4jReadError("Neo4j returned unsupported projection property values")
    return MappingProxyType(copied)


def _require_canonical_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("npid:v1:")
        or value != value.strip()
        or len(value.encode("utf-8")) > 256
    ):
        raise ProjectionContractError("canonical newsroom projection ID is invalid")
    return value


def _require_text(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 1024
    ):
        raise ProjectionContractError(f"{field} must be bounded canonical text")
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProjectionContractError(f"{field} must be a positive integer")
    return value


__all__ = [
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
    "Neo4jProjectionError",
    "Neo4jProjectorConfig",
    "Neo4jReadError",
    "Neo4jStructuralRead",
    "Neo4jWriteError",
    "StructuralBatch",
    "StructuralDeliveryRequest",
    "StructuralGraphNodeView",
    "StructuralGraphRelationView",
    "StructuralNode",
    "StructuralReadMetadata",
    "StructuralReadRequest",
    "StructuralReadResponse",
    "StructuralRelation",
]
