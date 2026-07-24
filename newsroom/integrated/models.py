from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.types import (
    AggregateId,
    EventId,
    ObjectAdmissionId,
    TrustScope,
    UUIDv4Id,
    UtcTimestamp,
    require_token,
)
from newsroom.projection.models import ProjectionGenerationState
from newsroom.projection.neo4j.models import (
    StructuralGraphNodeView,
    StructuralGraphRelationView,
    StructuralReadAuthoritySelection,
    StructuralReadMetadata,
)
from newsroom.projection.ontology import ProjectionNodeType


class IntegratedFoundationError(RuntimeError):
    """Base error for the non-activating Increment 1C proof boundary."""


class IntegratedContractError(ValueError):
    """An integrated fixture, retrieval, or admission contract is malformed."""


class IntegratedStateError(IntegratedFoundationError):
    """Current authority or projection state cannot support the proof."""


class CandidateAdmissionOutcome(StrEnum):
    ADMITTED = "ADMITTED"
    DEDUPLICATED = "DEDUPLICATED"


class CandidateRoute(StrEnum):
    NEW_EVENT = "NEW_EVENT"
    DEVELOPMENT = "DEVELOPMENT"
    CORRECTION = "CORRECTION"


class IntegratedUrgency(StrEnum):
    URGENT = "URGENT"
    TIME_SENSITIVE = "TIME_SENSITIVE"
    PLANNED = "PLANNED"
    ROUTINE = "ROUTINE"


@dataclass(frozen=True, slots=True)
class IntegratedFixtureId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class IntegratedSignalId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class IntegratedLeadId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class IntegratedHypothesisVersionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class IntegratedRetrievalContextId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class IntegratedTriageProposalId(UUIDv4Id):
    def as_aggregate_id(self) -> AggregateId:
        return AggregateId(self.value)


@dataclass(frozen=True, slots=True)
class StoryCandidateId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class StoryCandidateVersionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class CandidateAdmissionDecisionId(UUIDv4Id):
    pass


def _require_text(value: str, *, field: str, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise IntegratedContractError(f"{field} must be bounded canonical text")
    return value


def _require_text_tuple(
    value: tuple[str, ...],
    *,
    field: str,
    maximum_items: int = 64,
    maximum_item_bytes: int = 1024,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise IntegratedContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not value:
        raise IntegratedContractError(f"{field} cannot be empty")
    if len(value) > maximum_items:
        raise IntegratedContractError(f"{field} exceeds its item bound")
    normalized = tuple(
        _require_text(item, field=field, maximum_bytes=maximum_item_bytes)
        for item in value
    )
    if len(set(normalized)) != len(normalized):
        raise IntegratedContractError(f"{field} must not contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class IntegratedFixtureManifest:
    """Synthetic, deterministic Candidate hand-off content for Increment 1C only."""

    fixture_id: IntegratedFixtureId
    signal_id: IntegratedSignalId
    lead_id: IntegratedLeadId
    hypothesis_version_id: IntegratedHypothesisVersionId
    coverage_basis: str
    geography: str
    category: str
    urgency: IntegratedUrgency
    hypothesis_statement: str
    hypothesis_trust_scope: TrustScope
    likely_new_information: str
    reader_utility_basis: str
    uncertainties: tuple[str, ...]
    evidence_objectives: tuple[str, ...]
    policy_version: str
    retrieval_version: str
    admission_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.fixture_id, IntegratedFixtureId):
            raise IntegratedContractError("fixture identity must be typed")
        if not isinstance(self.signal_id, IntegratedSignalId):
            raise IntegratedContractError("signal identity must be typed")
        if not isinstance(self.lead_id, IntegratedLeadId):
            raise IntegratedContractError("lead identity must be typed")
        if not isinstance(
            self.hypothesis_version_id, IntegratedHypothesisVersionId
        ):
            raise IntegratedContractError("hypothesis version identity must be typed")
        for field_name in (
            "coverage_basis",
            "geography",
            "category",
            "policy_version",
            "retrieval_version",
            "admission_version",
        ):
            require_token(getattr(self, field_name), field=field_name)
        if not isinstance(self.urgency, IntegratedUrgency):
            raise IntegratedContractError("urgency must be typed")
        _require_text(
            self.hypothesis_statement,
            field="hypothesis_statement",
        )
        if self.hypothesis_trust_scope is not TrustScope.PROPOSED:
            raise IntegratedContractError(
                "integrated fixture hypothesis must remain explicitly PROPOSED"
            )
        _require_text(
            self.likely_new_information,
            field="likely_new_information",
        )
        _require_text(
            self.reader_utility_basis,
            field="reader_utility_basis",
        )
        object.__setattr__(
            self,
            "uncertainties",
            _require_text_tuple(
                self.uncertainties,
                field="uncertainties",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "evidence_objectives",
            _require_text_tuple(
                self.evidence_objectives,
                field="evidence_objectives",
            ),
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom-integrated-fixture-manifest-v1",
            "fixture_id": str(self.fixture_id),
            "signal_id": str(self.signal_id),
            "lead_id": str(self.lead_id),
            "hypothesis_version_id": str(self.hypothesis_version_id),
            "coverage_basis": self.coverage_basis,
            "geography": self.geography,
            "category": self.category,
            "urgency": self.urgency.value,
            "hypothesis_statement": self.hypothesis_statement,
            "hypothesis_trust_scope": self.hypothesis_trust_scope.value,
            "likely_new_information": self.likely_new_information,
            "reader_utility_basis": self.reader_utility_basis,
            "uncertainties": list(self.uncertainties),
            "evidence_objectives": list(self.evidence_objectives),
            "policy_version": self.policy_version,
            "retrieval_version": self.retrieval_version,
            "admission_version": self.admission_version,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def manifest_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class IntegratedExactIndexEntry:
    canonical_id: str
    node_type: ProjectionNodeType
    first_ledger_seq: int
    first_source_event_id: str
    first_source_event_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.canonical_id, str)
            or not self.canonical_id.startswith("npid:v1:")
            or self.canonical_id != self.canonical_id.strip()
            or len(self.canonical_id.encode("utf-8")) > 256
        ):
            raise IntegratedContractError("exact index canonical ID is invalid")
        if not isinstance(self.node_type, ProjectionNodeType):
            raise IntegratedContractError("exact index node type must be typed")
        if (
            isinstance(self.first_ledger_seq, bool)
            or not isinstance(self.first_ledger_seq, int)
            or self.first_ledger_seq <= 0
        ):
            raise IntegratedContractError(
                "exact index first ledger sequence must be positive"
            )
        _require_text(
            self.first_source_event_id,
            field="first_source_event_id",
            maximum_bytes=256,
        )
        validate_sha256_digest(
            self.first_source_event_digest,
            field="first_source_event_digest",
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "canonical_id": self.canonical_id,
            "node_type": self.node_type.value,
            "first_ledger_seq": self.first_ledger_seq,
            "first_source_event_id": self.first_source_event_id,
            "first_source_event_digest": self.first_source_event_digest,
        }


@dataclass(frozen=True, slots=True)
class IntegratedRetrievalContext:
    """Bounded graph context whose exact bytes are re-hydrated from authority."""

    context_id: IntegratedRetrievalContextId
    fixture_id: IntegratedFixtureId
    fixture_aggregate_id: AggregateId
    fixture_event_id: EventId
    admission_id: ObjectAdmissionId
    metadata: StructuralReadMetadata
    nodes: tuple[StructuralGraphNodeView, ...]
    relations: tuple[StructuralGraphRelationView, ...]
    exact_index: tuple[IntegratedExactIndexEntry, ...]
    hydrated_blob_digest: str
    hydration_policy_contract_digest: str
    hydration_access_decision_id: ObjectAccessDecisionId
    manifest_digest: str
    retrieval_version: str
    query_digest: str
    known_omissions: tuple[str, ...]
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.context_id, IntegratedRetrievalContextId):
            raise IntegratedContractError("retrieval context identity must be typed")
        if not isinstance(self.fixture_id, IntegratedFixtureId):
            raise IntegratedContractError("retrieval fixture identity must be typed")
        if not isinstance(self.fixture_aggregate_id, AggregateId):
            raise IntegratedContractError("fixture aggregate identity must be typed")
        if not isinstance(self.fixture_event_id, EventId):
            raise IntegratedContractError("fixture event identity must be typed")
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise IntegratedContractError("object admission identity must be typed")
        if not isinstance(self.metadata, StructuralReadMetadata):
            raise IntegratedContractError("structural metadata must be typed")
        if (
            self.metadata.authority_selection
            is not StructuralReadAuthoritySelection.AUTHORITY_SELECTED_ACTIVE
        ):
            raise IntegratedStateError(
                "integrated context requires authority-selected ACTIVE graph read"
            )
        if self.metadata.generation_state is not ProjectionGenerationState.ACTIVE:
            raise IntegratedStateError(
                "integrated context requires an ACTIVE projection generation"
            )
        if self.metadata.open_gap_count or self.metadata.dead_letter_count:
            raise IntegratedStateError(
                "integrated context cannot conceal graph gaps or dead letters"
            )
        if self.metadata.trust_scope is not TrustScope.ADMITTED:
            raise IntegratedStateError(
                "integrated context requires admitted structural trust"
            )
        if (
            self.metadata.authoritative_system
            != "sqlite-ledger-and-governed-objects"
            or self.metadata.graph_role
            != "non-authoritative-rebuildable-context"
        ):
            raise IntegratedStateError(
                "integrated context must return to non-graph authority"
            )
        if not isinstance(self.nodes, tuple) or not self.nodes:
            raise IntegratedContractError("integrated context requires graph nodes")
        node_ids = tuple(item.canonical_id for item in self.nodes)
        if node_ids != tuple(sorted(set(node_ids))):
            raise IntegratedContractError(
                "integrated graph nodes must be sorted and unique"
            )
        if not isinstance(self.relations, tuple) or not self.relations:
            raise IntegratedContractError("integrated context requires graph relations")
        relation_keys = tuple(item.relation_key for item in self.relations)
        if relation_keys != tuple(sorted(set(relation_keys))):
            raise IntegratedContractError(
                "integrated graph relations must be sorted and unique"
            )
        known_node_ids = set(node_ids)
        if any(
            relation.source_canonical_id not in known_node_ids
            or relation.target_canonical_id not in known_node_ids
            for relation in self.relations
        ):
            raise IntegratedContractError(
                "integrated graph relation endpoint is absent from returned nodes"
            )
        if not isinstance(self.exact_index, tuple) or not self.exact_index:
            raise IntegratedContractError("integrated context requires an exact index")
        indexed = tuple(item.canonical_id for item in self.exact_index)
        if indexed != tuple(sorted(set(indexed))):
            raise IntegratedContractError(
                "integrated exact index must be sorted and unique"
            )
        graph_ids = {item.canonical_id for item in self.nodes}
        if set(indexed) != graph_ids:
            raise IntegratedContractError(
                "integrated exact index must cover the returned graph nodes exactly"
            )
        if not any(
            item.source_event_id == str(self.fixture_event_id)
            and item.object_admission_id == str(self.admission_id)
            for item in self.relations
        ):
            raise IntegratedStateError(
                "graph context lacks exact fixture event/object provenance"
            )
        for field_name in (
            "hydrated_blob_digest",
            "hydration_policy_contract_digest",
            "manifest_digest",
            "query_digest",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if not isinstance(
            self.hydration_access_decision_id, ObjectAccessDecisionId
        ):
            raise IntegratedContractError(
                "hydration access decision identity must be typed"
            )
        require_token(self.retrieval_version, field="retrieval_version")
        object.__setattr__(
            self,
            "known_omissions",
            _require_text_tuple(
                self.known_omissions,
                field="known_omissions",
                allow_empty=True,
            ),
        )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise IntegratedContractError("retrieval context time must be typed")

    def _metadata_value(self) -> dict[str, object]:
        return {
            "family_id": self.metadata.family_id,
            "family_definition_version": self.metadata.family_definition_version,
            "projector_version": self.metadata.projector_version,
            "ontology_contract_digest": self.metadata.ontology_contract_digest,
            "mapping_contract_digest": self.metadata.mapping_contract_digest,
            "generation_id": str(self.metadata.generation_id),
            "generation_state": self.metadata.generation_state.value,
            "authority_selection": self.metadata.authority_selection.value,
            "contiguous_ledger_seq": self.metadata.contiguous_ledger_seq,
            "open_gap_count": self.metadata.open_gap_count,
            "dead_letter_count": self.metadata.dead_letter_count,
            "trust_scope": self.metadata.trust_scope.value,
            "query_valid_time": self.metadata.query_valid_time.to_text(),
            "authoritative_system": self.metadata.authoritative_system,
            "graph_role": self.metadata.graph_role,
        }

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom-integrated-retrieval-context-v1",
            "fixture_id": str(self.fixture_id),
            "fixture_aggregate_id": str(self.fixture_aggregate_id),
            "fixture_event_id": str(self.fixture_event_id),
            "admission_id": str(self.admission_id),
            "metadata": self._metadata_value(),
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
            "exact_index": [item.canonical_value() for item in self.exact_index],
            "hydrated_blob_digest": self.hydrated_blob_digest,
            "hydration_policy_contract_digest": (
                self.hydration_policy_contract_digest
            ),
            "manifest_digest": self.manifest_digest,
            "retrieval_version": self.retrieval_version,
            "query_digest": self.query_digest,
            "known_omissions": list(self.known_omissions),
        }

    @property
    def context_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class CandidateAdmissionRequest:
    proposal_id: IntegratedTriageProposalId
    route: CandidateRoute
    fixture_id: IntegratedFixtureId
    expected_context_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, IntegratedTriageProposalId):
            raise IntegratedContractError("triage proposal identity must be typed")
        if not isinstance(self.route, CandidateRoute):
            raise IntegratedContractError("candidate route must be typed")
        if not isinstance(self.fixture_id, IntegratedFixtureId):
            raise IntegratedContractError("fixture identity must be typed")
        normalized = validate_sha256_digest(
            self.expected_context_digest,
            field="expected_context_digest",
        )
        if normalized != self.expected_context_digest:
            raise IntegratedContractError(
                "expected context digest must be canonical lowercase"
            )
        _require_text(
            self.idempotency_key,
            field="idempotency_key",
            maximum_bytes=256,
        )


@dataclass(frozen=True, slots=True)
class CandidateAdmissionView:
    decision_id: CandidateAdmissionDecisionId
    outcome: CandidateAdmissionOutcome
    proposal_id: IntegratedTriageProposalId
    candidate_id: StoryCandidateId
    candidate_version_id: StoryCandidateVersionId
    candidate_version: int
    route: CandidateRoute
    fixture_id: IntegratedFixtureId
    fixture_event_id: EventId
    admission_id: ObjectAdmissionId
    retrieval_context_id: IntegratedRetrievalContextId
    retrieval_context_digest: str
    manifest_digest: str
    semantic_collision_digest: str
    authority_event_id: EventId
    authority_aggregate_version: int
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, CandidateAdmissionDecisionId):
            raise IntegratedContractError("candidate decision identity must be typed")
        if not isinstance(self.outcome, CandidateAdmissionOutcome):
            raise IntegratedContractError("candidate outcome must be typed")
        if not isinstance(self.proposal_id, IntegratedTriageProposalId):
            raise IntegratedContractError("proposal identity must be typed")
        if not isinstance(self.candidate_id, StoryCandidateId):
            raise IntegratedContractError("candidate identity must be typed")
        if not isinstance(self.candidate_version_id, StoryCandidateVersionId):
            raise IntegratedContractError("candidate version identity must be typed")
        if (
            isinstance(self.candidate_version, bool)
            or not isinstance(self.candidate_version, int)
            or self.candidate_version <= 0
        ):
            raise IntegratedContractError("candidate version must be positive")
        if not isinstance(self.route, CandidateRoute):
            raise IntegratedContractError("candidate route must be typed")
        if not isinstance(self.fixture_id, IntegratedFixtureId):
            raise IntegratedContractError("fixture identity must be typed")
        if not isinstance(self.fixture_event_id, EventId):
            raise IntegratedContractError("fixture event identity must be typed")
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise IntegratedContractError("admission identity must be typed")
        if not isinstance(
            self.retrieval_context_id, IntegratedRetrievalContextId
        ):
            raise IntegratedContractError(
                "retrieval context identity must be typed"
            )
        for field_name in (
            "retrieval_context_digest",
            "manifest_digest",
            "semantic_collision_digest",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if not isinstance(self.authority_event_id, EventId):
            raise IntegratedContractError("authority event identity must be typed")
        if (
            isinstance(self.authority_aggregate_version, bool)
            or not isinstance(self.authority_aggregate_version, int)
            or self.authority_aggregate_version <= 0
        ):
            raise IntegratedContractError(
                "candidate authority aggregate version must be positive"
            )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise IntegratedContractError("candidate decision time must be typed")


__all__ = [
    "CandidateAdmissionDecisionId",
    "CandidateAdmissionOutcome",
    "CandidateAdmissionRequest",
    "CandidateAdmissionView",
    "CandidateRoute",
    "IntegratedContractError",
    "IntegratedExactIndexEntry",
    "IntegratedFixtureId",
    "IntegratedFixtureManifest",
    "IntegratedFoundationError",
    "IntegratedHypothesisVersionId",
    "IntegratedLeadId",
    "IntegratedRetrievalContext",
    "IntegratedRetrievalContextId",
    "IntegratedSignalId",
    "IntegratedStateError",
    "IntegratedTriageProposalId",
    "IntegratedUrgency",
    "StoryCandidateId",
    "StoryCandidateVersionId",
]
