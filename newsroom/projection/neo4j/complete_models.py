from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re
from typing import Any
from uuid import UUID

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import (
    EventId,
    ObjectAdmissionId,
    TrustScope,
    UtcTimestamp,
    require_token,
)
from newsroom.projection.complete import (
    CompleteProjectionProfile,
    FullTextIndexContract,
    VectorIndexContract,
)
from newsroom.projection.models import (
    ProjectionContractError,
    ProjectionGenerationId,
)
from newsroom.relations.models import (
    FixturePassageObject,
    RelationAdmissionDecisionId,
    RelationAssertionId,
    RelationEndpoint,
    RelationPredicate,
    RelationProducer,
    RelationProposalId,
    RelationTemporalScope,
)

from .models import Neo4jApplyOutcome, StructuralBatch


_NEO4J_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")


class CompleteDerivativeType(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    ADMITTED_RELATION = "ADMITTED_RELATION"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"


class CompleteProjectionAction(StrEnum):
    UPSERT = "UPSERT"
    REMOVE = "REMOVE"


class CompleteQueryKind(StrEnum):
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"


class CompleteQualificationResult(StrEnum):
    PASSED = "PASSED"


class Neo4jIndexType(StrEnum):
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"


class Neo4jIndexState(StrEnum):
    ONLINE = "ONLINE"
    POPULATING = "POPULATING"
    FAILED = "FAILED"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class CompleteProjectionIdentity:
    generation_id: ProjectionGenerationId
    family_id: str
    family_definition_version: str
    projector_version: str
    ontology_contract_digest: str
    mapping_contract_digest: str
    complete_contract_digest: str
    fulltext_contract_digest: str
    vector_contract_digest: str
    fixture_vector_manifest_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.generation_id, ProjectionGenerationId):
            raise ProjectionContractError(
                "complete projection generation identity must be typed"
            )
        for field_name in (
            "family_id",
            "family_definition_version",
            "projector_version",
        ):
            require_token(getattr(self, field_name), field=field_name)
        for field_name in (
            "ontology_contract_digest",
            "mapping_contract_digest",
            "complete_contract_digest",
            "fulltext_contract_digest",
            "vector_contract_digest",
            "fixture_vector_manifest_digest",
        ):
            value = getattr(self, field_name)
            if validate_sha256_digest(value, field=field_name) != value:
                raise ProjectionContractError(f"{field_name} must be canonical")

    def canonical_value(self) -> dict[str, object]:
        return {
            "generation_id": str(self.generation_id),
            "family_id": self.family_id,
            "family_definition_version": self.family_definition_version,
            "projector_version": self.projector_version,
            "ontology_contract_digest": self.ontology_contract_digest,
            "mapping_contract_digest": self.mapping_contract_digest,
            "complete_contract_digest": self.complete_contract_digest,
            "fulltext_contract_digest": self.fulltext_contract_digest,
            "vector_contract_digest": self.vector_contract_digest,
            "fixture_vector_manifest_digest": (
                self.fixture_vector_manifest_digest
            ),
        }

    @property
    def identity_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class CompleteGenerationNames:
    generation_id: ProjectionGenerationId
    generation_suffix: str
    document_label: str
    admitted_relation_type: str
    fulltext_index_name: str
    vector_index_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.generation_id, ProjectionGenerationId):
            raise ProjectionContractError(
                "complete generation names require a typed generation"
            )
        require_token(self.generation_suffix, field="complete_generation_suffix")
        for field_name in (
            "document_label",
            "admitted_relation_type",
            "fulltext_index_name",
            "vector_index_name",
        ):
            value = getattr(self, field_name)
            if _NEO4J_NAME.fullmatch(value) is None:
                raise ProjectionContractError(
                    f"{field_name} is not a bounded server-derived Neo4j name"
                )
        if self.fulltext_index_name == self.vector_index_name:
            raise ProjectionContractError(
                "complete full-text and vector index names must differ"
            )

    def canonical_value(self) -> dict[str, str]:
        return {
            "generation_id": str(self.generation_id),
            "generation_suffix": self.generation_suffix,
            "document_label": self.document_label,
            "admitted_relation_type": self.admitted_relation_type,
            "fulltext_index_name": self.fulltext_index_name,
            "vector_index_name": self.vector_index_name,
        }


@dataclass(frozen=True, slots=True)
class CompleteProjectionDocument:
    identity: CompleteProjectionIdentity
    passage_id: str
    admission_id: ObjectAdmissionId
    blob_digest: str
    language: str
    revision_id: str | None
    retrieval_text: str
    normalized_text_digest: str
    vector_components: tuple[int, ...]
    vector_digest: str
    vector_dimensions: int
    vector_component_scale: int
    source_event_id: EventId
    source_ledger_seq: int
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError(
                "complete document identity must be typed"
            )
        require_token(self.passage_id, field="complete_document_passage_id")
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise ProjectionContractError(
                "complete document admission identity must be typed"
            )
        for field_name in (
            "blob_digest",
            "normalized_text_digest",
            "vector_digest",
        ):
            value = getattr(self, field_name)
            if validate_sha256_digest(value, field=field_name) != value:
                raise ProjectionContractError(f"{field_name} must be canonical")
        if self.language not in {"en-GB", "zh-HK"}:
            raise ProjectionContractError("complete document language is invalid")
        if self.revision_id is not None:
            try:
                revision_id = UUID(self.revision_id)
            except (ValueError, AttributeError) as exc:
                raise ProjectionContractError(
                    "complete document revision identity must be canonical UUID text"
                ) from exc
            if str(revision_id) != self.revision_id:
                raise ProjectionContractError(
                    "complete document revision identity must be canonical UUID text"
                )
        _require_bounded_text(
            self.retrieval_text,
            field="complete_document_retrieval_text",
            maximum_bytes=256 * 1024,
        )
        _require_positive_int(self.vector_dimensions, field="vector_dimensions")
        _require_positive_int(
            self.vector_component_scale,
            field="vector_component_scale",
        )
        if (
            not isinstance(self.vector_components, tuple)
            or len(self.vector_components) != self.vector_dimensions
        ):
            raise ProjectionContractError(
                "complete document vector has the wrong dimension"
            )
        if all(component == 0 for component in self.vector_components):
            raise ProjectionContractError(
                "complete cosine document vector cannot be all zero"
            )
        for component in self.vector_components:
            if isinstance(component, bool) or not isinstance(component, int):
                raise ProjectionContractError(
                    "complete document vectors use fixed-point integers"
                )
            if abs(component) > self.vector_component_scale:
                raise ProjectionContractError(
                    "complete document vector component exceeds its scale"
                )
        if not isinstance(self.source_event_id, EventId):
            raise ProjectionContractError(
                "complete document source event must be typed"
            )
        _require_positive_int(self.source_ledger_seq, field="source_ledger_seq")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise ProjectionContractError(
                "complete document recorded_at must be typed"
            )

    @property
    def vector(self) -> tuple[float, ...]:
        return tuple(
            component / self.vector_component_scale
            for component in self.vector_components
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "identity": self.identity.canonical_value(),
            "passage_id": self.passage_id,
            "admission_id": str(self.admission_id),
            "blob_digest": self.blob_digest,
            "language": self.language,
            "revision_id": self.revision_id,
            "retrieval_text": self.retrieval_text,
            "normalized_text_digest": self.normalized_text_digest,
            "vector_components": list(self.vector_components),
            "vector_digest": self.vector_digest,
            "vector_dimensions": self.vector_dimensions,
            "vector_component_scale": self.vector_component_scale,
            "source_event_id": str(self.source_event_id),
            "source_ledger_seq": self.source_ledger_seq,
            "recorded_at": self.recorded_at.to_text(),
        }

    @property
    def document_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class AdmittedRelationProjection:
    identity: CompleteProjectionIdentity
    assertion_id: RelationAssertionId
    proposal_id: RelationProposalId
    admission_decision_id: RelationAdmissionDecisionId
    relation_key: str
    subject: RelationEndpoint
    predicate: RelationPredicate
    object: RelationEndpoint
    temporal_scope: RelationTemporalScope
    evidence_objects: tuple[FixturePassageObject, ...]
    producer: RelationProducer
    statement: str
    uncertainties: tuple[str, ...]
    proposal_digest: str
    source_event_id: EventId
    source_ledger_seq: int
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError(
                "admitted relation projection identity must be typed"
            )
        if not isinstance(self.assertion_id, RelationAssertionId):
            raise ProjectionContractError(
                "admitted relation assertion identity must be typed"
            )
        if not isinstance(self.proposal_id, RelationProposalId):
            raise ProjectionContractError(
                "admitted relation proposal identity must be typed"
            )
        if not isinstance(
            self.admission_decision_id, RelationAdmissionDecisionId
        ):
            raise ProjectionContractError(
                "admitted relation decision identity must be typed"
            )
        if validate_sha256_digest(self.relation_key, field="relation_key") != self.relation_key:
            raise ProjectionContractError("relation key must be canonical")
        if not isinstance(self.subject, RelationEndpoint) or not isinstance(
            self.object, RelationEndpoint
        ):
            raise ProjectionContractError(
                "admitted relation endpoints must be typed"
            )
        if self.subject == self.object:
            raise ProjectionContractError(
                "admitted relation endpoints must be distinct"
            )
        if not isinstance(self.predicate, RelationPredicate):
            raise ProjectionContractError(
                "admitted relation predicate must be typed"
            )
        if not isinstance(self.temporal_scope, RelationTemporalScope):
            raise ProjectionContractError(
                "admitted relation temporal scope must be typed"
            )
        if (
            not isinstance(self.evidence_objects, tuple)
            or not self.evidence_objects
            or not all(
                isinstance(item, FixturePassageObject)
                for item in self.evidence_objects
            )
        ):
            raise ProjectionContractError(
                "admitted relation evidence must be a non-empty typed tuple"
            )
        passage_ids = tuple(item.passage_id for item in self.evidence_objects)
        if passage_ids != tuple(sorted(set(passage_ids))):
            raise ProjectionContractError(
                "admitted relation evidence must be sorted and unique"
            )
        if not isinstance(self.producer, RelationProducer):
            raise ProjectionContractError(
                "admitted relation producer must be typed"
            )
        _require_bounded_text(
            self.statement,
            field="admitted_relation_statement",
            maximum_bytes=16 * 1024,
        )
        if not isinstance(self.uncertainties, tuple):
            raise ProjectionContractError(
                "admitted relation uncertainties must be immutable"
            )
        for uncertainty in self.uncertainties:
            _require_bounded_text(
                uncertainty,
                field="admitted_relation_uncertainty",
                maximum_bytes=2048,
            )
        if validate_sha256_digest(
            self.proposal_digest, field="proposal_digest"
        ) != self.proposal_digest:
            raise ProjectionContractError("proposal digest must be canonical")
        if not isinstance(self.source_event_id, EventId):
            raise ProjectionContractError(
                "admitted relation source event must be typed"
            )
        _require_positive_int(self.source_ledger_seq, field="source_ledger_seq")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise ProjectionContractError(
                "admitted relation recorded_at must be typed"
            )

    @property
    def trust_scope(self) -> TrustScope:
        return TrustScope.ADMITTED

    def canonical_value(self) -> dict[str, object]:
        return {
            "identity": self.identity.canonical_value(),
            "assertion_id": str(self.assertion_id),
            "proposal_id": str(self.proposal_id),
            "admission_decision_id": str(self.admission_decision_id),
            "relation_key": self.relation_key,
            "subject": self.subject.canonical_value(),
            "predicate": self.predicate.value,
            "object": self.object.canonical_value(),
            "trust_scope": self.trust_scope.value,
            "temporal_scope": self.temporal_scope.canonical_value(),
            "evidence_objects": [
                item.canonical_value() for item in self.evidence_objects
            ],
            "producer": self.producer.canonical_value(),
            "statement": self.statement,
            "uncertainties": list(self.uncertainties),
            "proposal_digest": self.proposal_digest,
            "source_event_id": str(self.source_event_id),
            "source_ledger_seq": self.source_ledger_seq,
            "recorded_at": self.recorded_at.to_text(),
        }

    @property
    def relation_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class CompleteProjectionRemoval:
    identity: CompleteProjectionIdentity
    derivative_type: CompleteDerivativeType
    stable_key: str
    source_event_id: EventId
    source_ledger_seq: int
    reason_code: str
    object_admission_ids: tuple[ObjectAdmissionId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError(
                "complete removal identity must be typed"
            )
        if not isinstance(self.derivative_type, CompleteDerivativeType):
            raise ProjectionContractError(
                "complete removal derivative type must be typed"
            )
        _require_bounded_text(
            self.stable_key,
            field="complete_removal_stable_key",
            maximum_bytes=512,
        )
        if not isinstance(self.source_event_id, EventId):
            raise ProjectionContractError(
                "complete removal source event must be typed"
            )
        _require_positive_int(self.source_ledger_seq, field="source_ledger_seq")
        require_token(self.reason_code, field="complete_removal_reason_code")
        if not isinstance(self.object_admission_ids, tuple):
            raise ProjectionContractError(
                "complete removal object identities must be immutable"
            )
        if not all(
            isinstance(item, ObjectAdmissionId)
            for item in self.object_admission_ids
        ):
            raise ProjectionContractError(
                "complete removal object identities must be typed"
            )
        if self.object_admission_ids != tuple(
            sorted(set(self.object_admission_ids), key=str)
        ):
            raise ProjectionContractError(
                "complete removal object identities must be sorted and unique"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "identity": self.identity.canonical_value(),
            "derivative_type": self.derivative_type.value,
            "stable_key": self.stable_key,
            "source_event_id": str(self.source_event_id),
            "source_ledger_seq": self.source_ledger_seq,
            "reason_code": self.reason_code,
            "object_admission_ids": [
                str(item) for item in self.object_admission_ids
            ],
        }


@dataclass(frozen=True, slots=True)
class CompleteProjectionBatch:
    identity: CompleteProjectionIdentity
    ledger_seq: int
    source_event_id: EventId
    source_event_digest: str
    structural_batch: StructuralBatch | None
    documents: tuple[CompleteProjectionDocument, ...]
    relations: tuple[AdmittedRelationProjection, ...]
    removals: tuple[CompleteProjectionRemoval, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError("complete batch identity must be typed")
        _require_positive_int(self.ledger_seq, field="ledger_seq")
        if not isinstance(self.source_event_id, EventId):
            raise ProjectionContractError(
                "complete batch source event must be typed"
            )
        if validate_sha256_digest(
            self.source_event_digest, field="source_event_digest"
        ) != self.source_event_digest:
            raise ProjectionContractError(
                "complete batch source event digest must be canonical"
            )
        if self.structural_batch is not None:
            if not isinstance(self.structural_batch, StructuralBatch):
                raise ProjectionContractError(
                    "complete structural batch must be typed"
                )
            structural = self.structural_batch
            if (
                structural.generation_id != self.identity.generation_id
                or structural.family_id != self.identity.family_id
                or structural.family_definition_version
                != self.identity.family_definition_version
                or structural.projector_version != self.identity.projector_version
                or structural.ontology_contract_digest
                != self.identity.ontology_contract_digest
                or structural.mapping_contract_digest
                != self.identity.mapping_contract_digest
                or structural.ledger_seq != self.ledger_seq
                or structural.source_event_id != str(self.source_event_id)
                or structural.source_event_digest != self.source_event_digest
            ):
                raise ProjectionContractError(
                    "complete structural batch differs from complete identity"
                )
        for field_name, expected_type in (
            ("documents", CompleteProjectionDocument),
            ("relations", AdmittedRelationProjection),
            ("removals", CompleteProjectionRemoval),
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, expected_type) for item in values
            ):
                raise ProjectionContractError(
                    f"complete batch {field_name} must be a typed tuple"
                )
            if any(item.identity != self.identity for item in values):
                raise ProjectionContractError(
                    f"complete batch {field_name} identity differs"
                )
        document_keys = tuple(item.passage_id for item in self.documents)
        if document_keys != tuple(sorted(set(document_keys))):
            raise ProjectionContractError(
                "complete documents must be sorted and unique"
            )
        relation_keys = tuple(item.relation_key for item in self.relations)
        if relation_keys != tuple(sorted(set(relation_keys))):
            raise ProjectionContractError(
                "complete relations must be sorted and unique"
            )
        removal_keys = tuple(
            (item.derivative_type.value, item.stable_key)
            for item in self.removals
        )
        if removal_keys != tuple(sorted(set(removal_keys))):
            raise ProjectionContractError(
                "complete removals must be sorted and unique"
            )
        if any(item.source_ledger_seq != self.ledger_seq for item in self.documents):
            raise ProjectionContractError(
                "complete document source sequence differs from batch"
            )
        if any(item.source_ledger_seq != self.ledger_seq for item in self.relations):
            raise ProjectionContractError(
                "complete relation source sequence differs from batch"
            )
        if any(item.source_ledger_seq != self.ledger_seq for item in self.removals):
            raise ProjectionContractError(
                "complete removal source sequence differs from batch"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "identity": self.identity.canonical_value(),
            "ledger_seq": self.ledger_seq,
            "source_event_id": str(self.source_event_id),
            "source_event_digest": self.source_event_digest,
            "structural_batch_digest": (
                None
                if self.structural_batch is None
                else self.structural_batch.batch_digest
            ),
            "documents": [item.canonical_value() for item in self.documents],
            "relations": [item.canonical_value() for item in self.relations],
            "removals": [item.canonical_value() for item in self.removals],
        }

    @property
    def batch_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))

    @property
    def is_empty(self) -> bool:
        structural_empty = (
            self.structural_batch is None
            or (
                not self.structural_batch.nodes
                and not self.structural_batch.relations
                and not self.structural_batch.tombstoned_object_admission_ids
            )
        )
        return structural_empty and not self.documents and not self.relations and not self.removals


@dataclass(frozen=True, slots=True)
class CompleteProjectionDeliveryRecord:
    identity: CompleteProjectionIdentity
    ledger_seq: int
    source_event_id: EventId
    source_event_digest: str
    batch_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError(
                "complete delivery identity must be typed"
            )
        _require_positive_int(self.ledger_seq, field="ledger_seq")
        if not isinstance(self.source_event_id, EventId):
            raise ProjectionContractError(
                "complete delivery source event must be typed"
            )
        for field_name in ("source_event_digest", "batch_digest"):
            value = getattr(self, field_name)
            if validate_sha256_digest(value, field=field_name) != value:
                raise ProjectionContractError(f"{field_name} must be canonical")

    def canonical_value(self) -> dict[str, object]:
        return {
            "identity": self.identity.canonical_value(),
            "ledger_seq": self.ledger_seq,
            "source_event_id": str(self.source_event_id),
            "source_event_digest": self.source_event_digest,
            "batch_digest": self.batch_digest,
        }


@dataclass(frozen=True, slots=True)
class CompleteProjectionApplyResult:
    outcome: Neo4jApplyOutcome
    identity: CompleteProjectionIdentity
    ledger_seq: int
    source_event_id: EventId
    source_event_digest: str
    batch_digest: str
    affected_record_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, Neo4jApplyOutcome):
            raise ProjectionContractError(
                "complete apply outcome must be typed"
            )
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError(
                "complete apply identity must be typed"
            )
        _require_positive_int(self.ledger_seq, field="ledger_seq")
        if not isinstance(self.source_event_id, EventId):
            raise ProjectionContractError(
                "complete apply source event must be typed"
            )
        for field_name in ("source_event_digest", "batch_digest"):
            value = getattr(self, field_name)
            if validate_sha256_digest(value, field=field_name) != value:
                raise ProjectionContractError(f"{field_name} must be canonical")
        _require_non_negative_int(
            self.affected_record_count,
            field="affected_record_count",
        )


@dataclass(frozen=True, slots=True)
class CompleteQueryHit:
    query_id: str
    query_kind: CompleteQueryKind
    passage_id: str
    score: float
    rank: int

    def __post_init__(self) -> None:
        require_token(self.query_id, field="complete_query_id")
        if not isinstance(self.query_kind, CompleteQueryKind):
            raise ProjectionContractError("complete query kind must be typed")
        require_token(self.passage_id, field="complete_query_passage_id")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise ProjectionContractError("complete query score must be numeric")
        normalized = float(self.score)
        if not math.isfinite(normalized):
            raise ProjectionContractError("complete query score must be finite")
        object.__setattr__(self, "score", normalized)
        _require_positive_int(self.rank, field="complete_query_rank")

    def canonical_value(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "query_kind": self.query_kind.value,
            "passage_id": self.passage_id,
            "score": self.score,
            "rank": self.rank,
        }


@dataclass(frozen=True, slots=True)
class CompleteProjectionState:
    identity: CompleteProjectionIdentity
    checkpoint_ledger_seq: int
    structural_state_digest: str
    documents: tuple[CompleteProjectionDocument, ...]
    relations: tuple[AdmittedRelationProjection, ...]
    deliveries: tuple[CompleteProjectionDeliveryRecord, ...]
    fulltext_index_state: Neo4jIndexState
    vector_index_state: Neo4jIndexState
    fulltext_index_provider: str
    vector_index_provider: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError("complete state identity must be typed")
        _require_non_negative_int(
            self.checkpoint_ledger_seq,
            field="checkpoint_ledger_seq",
        )
        if validate_sha256_digest(
            self.structural_state_digest,
            field="structural_state_digest",
        ) != self.structural_state_digest:
            raise ProjectionContractError(
                "structural state digest must be canonical"
            )
        for field_name, expected_type in (
            ("documents", CompleteProjectionDocument),
            ("relations", AdmittedRelationProjection),
            ("deliveries", CompleteProjectionDeliveryRecord),
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, expected_type) for item in values
            ):
                raise ProjectionContractError(
                    f"complete state {field_name} must be a typed tuple"
                )
            if any(item.identity != self.identity for item in values):
                raise ProjectionContractError(
                    f"complete state {field_name} identity differs"
                )
        if tuple(item.passage_id for item in self.documents) != tuple(
            sorted({item.passage_id for item in self.documents})
        ):
            raise ProjectionContractError(
                "complete state documents must be sorted and unique"
            )
        if tuple(item.relation_key for item in self.relations) != tuple(
            sorted({item.relation_key for item in self.relations})
        ):
            raise ProjectionContractError(
                "complete state relations must be sorted and unique"
            )
        sequences = tuple(item.ledger_seq for item in self.deliveries)
        if sequences != tuple(sorted(set(sequences))):
            raise ProjectionContractError(
                "complete state deliveries must be sorted and unique"
            )
        if not isinstance(self.fulltext_index_state, Neo4jIndexState) or not isinstance(
            self.vector_index_state, Neo4jIndexState
        ):
            raise ProjectionContractError("complete index states must be typed")
        require_token(
            self.fulltext_index_provider,
            field="fulltext_index_provider",
        )
        require_token(self.vector_index_provider, field="vector_index_provider")

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom-complete-projection-state-v1",
            "identity": self.identity.canonical_value(),
            "checkpoint_ledger_seq": self.checkpoint_ledger_seq,
            "structural_state_digest": self.structural_state_digest,
            "documents": [item.canonical_value() for item in self.documents],
            "relations": [item.canonical_value() for item in self.relations],
            "deliveries": [item.canonical_value() for item in self.deliveries],
            "fulltext_index_state": self.fulltext_index_state.value,
            "vector_index_state": self.vector_index_state.value,
            "fulltext_index_provider": self.fulltext_index_provider,
            "vector_index_provider": self.vector_index_provider,
        }

    @property
    def state_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class CompleteProjectionQualification:
    identity: CompleteProjectionIdentity
    checkpoint_ledger_seq: int
    projection_state_digest: str
    result: CompleteQualificationResult
    fulltext_hits: tuple[CompleteQueryHit, ...]
    vector_hits: tuple[CompleteQueryHit, ...]
    expected_tombstoned_passage_ids: tuple[str, ...]
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError(
                "complete qualification identity must be typed"
            )
        _require_non_negative_int(
            self.checkpoint_ledger_seq,
            field="checkpoint_ledger_seq",
        )
        if validate_sha256_digest(
            self.projection_state_digest,
            field="projection_state_digest",
        ) != self.projection_state_digest:
            raise ProjectionContractError(
                "qualification state digest must be canonical"
            )
        if self.result is not CompleteQualificationResult.PASSED:
            raise ProjectionContractError(
                "only successful complete qualifications are returned"
            )
        for field_name, kind in (
            ("fulltext_hits", CompleteQueryKind.FULL_TEXT),
            ("vector_hits", CompleteQueryKind.VECTOR),
        ):
            hits = getattr(self, field_name)
            if not isinstance(hits, tuple) or not hits:
                raise ProjectionContractError(
                    f"complete qualification {field_name} must be non-empty"
                )
            if any(
                not isinstance(hit, CompleteQueryHit)
                or hit.query_kind is not kind
                for hit in hits
            ):
                raise ProjectionContractError(
                    f"complete qualification {field_name} has wrong kind"
                )
        if not isinstance(self.expected_tombstoned_passage_ids, tuple):
            raise ProjectionContractError(
                "qualification tombstone expectations must be immutable"
            )
        for passage_id in self.expected_tombstoned_passage_ids:
            require_token(passage_id, field="tombstoned_passage_id")
        if self.expected_tombstoned_passage_ids != tuple(
            sorted(set(self.expected_tombstoned_passage_ids))
        ):
            raise ProjectionContractError(
                "qualification tombstone expectations must be sorted and unique"
            )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise ProjectionContractError(
                "complete qualification time must be typed"
            )


@dataclass(frozen=True, slots=True)
class CompleteDeliveryRequest:
    generation_id: ProjectionGenerationId
    expected_authority_version: int
    ledger_seq: int
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_generation(self.generation_id, field="complete delivery")
        _require_positive_int(
            self.expected_authority_version,
            field="expected_authority_version",
        )
        _require_positive_int(self.ledger_seq, field="ledger_seq")
        _require_idempotency_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class CompleteRebuildRequest:
    generation_id: ProjectionGenerationId
    expected_authority_version: int
    through_ledger_seq: int
    reason_code: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_generation(self.generation_id, field="complete rebuild")
        _require_positive_int(
            self.expected_authority_version,
            field="expected_authority_version",
        )
        _require_non_negative_int(
            self.through_ledger_seq,
            field="through_ledger_seq",
        )
        require_token(self.reason_code, field="complete_rebuild_reason_code")
        _require_idempotency_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class CompleteGenerationValidationRequest:
    generation_id: ProjectionGenerationId
    expected_authority_version: int
    checkpoint_ledger_seq: int
    reason_code: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_generation(self.generation_id, field="complete validation")
        _require_positive_int(
            self.expected_authority_version,
            field="expected_authority_version",
        )
        _require_non_negative_int(
            self.checkpoint_ledger_seq,
            field="checkpoint_ledger_seq",
        )
        require_token(self.reason_code, field="complete_validation_reason_code")
        _require_idempotency_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class CompleteGenerationQualificationRequest:
    generation_id: ProjectionGenerationId
    checkpoint_ledger_seq: int
    profile: CompleteProjectionProfile

    def __post_init__(self) -> None:
        _require_generation(self.generation_id, field="complete qualification")
        _require_non_negative_int(
            self.checkpoint_ledger_seq,
            field="checkpoint_ledger_seq",
        )
        if not isinstance(self.profile, CompleteProjectionProfile):
            raise ProjectionContractError(
                "complete qualification profile must be typed"
            )


@dataclass(frozen=True, slots=True)
class CompleteRebuildResult:
    identity: CompleteProjectionIdentity
    through_ledger_seq: int
    checkpoint_ledger_seq: int
    rebuild_authority_event_id: EventId
    authority_command_replayed: bool
    deleted_record_count: int
    reapplied_delivery_count: int
    recorded_delivery_count: int
    blocked_delivery_count: int
    serving_time: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CompleteProjectionIdentity):
            raise ProjectionContractError(
                "complete rebuild identity must be typed"
            )
        for field_name in (
            "through_ledger_seq",
            "checkpoint_ledger_seq",
            "deleted_record_count",
            "reapplied_delivery_count",
            "recorded_delivery_count",
            "blocked_delivery_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field=field_name)
        if not isinstance(self.rebuild_authority_event_id, EventId):
            raise ProjectionContractError(
                "complete rebuild authority event must be typed"
            )
        if not isinstance(self.authority_command_replayed, bool):
            raise ProjectionContractError(
                "complete rebuild replay flag must be boolean"
            )
        if not isinstance(self.serving_time, UtcTimestamp):
            raise ProjectionContractError(
                "complete rebuild serving time must be typed"
            )


def complete_generation_names(
    identity: CompleteProjectionIdentity,
    fulltext: FullTextIndexContract,
    vector: VectorIndexContract,
) -> CompleteGenerationNames:
    if not isinstance(identity, CompleteProjectionIdentity):
        raise ProjectionContractError(
            "complete generation names require a typed identity"
        )
    if not isinstance(fulltext, FullTextIndexContract):
        raise ProjectionContractError(
            "complete generation names require a full-text contract"
        )
    if not isinstance(vector, VectorIndexContract):
        raise ProjectionContractError(
            "complete generation names require a vector contract"
        )
    if (
        identity.fulltext_contract_digest != fulltext.contract_digest
        or identity.vector_contract_digest != vector.contract_digest
    ):
        raise ProjectionContractError(
            "complete generation index contracts differ from identity"
        )
    suffix = f"g{identity.generation_id.value.hex}"
    return CompleteGenerationNames(
        generation_id=identity.generation_id,
        generation_suffix=suffix,
        document_label=f"NewsroomRetrievalDocument_{suffix}",
        admitted_relation_type="DEVELOPMENT_OF",
        fulltext_index_name=f"{fulltext.index_name}_{suffix}",
        vector_index_name=f"{vector.index_name}_{suffix}",
    )


def _require_generation(value: Any, *, field: str) -> None:
    if not isinstance(value, ProjectionGenerationId):
        raise ProjectionContractError(f"{field} generation identity must be typed")


def _require_bounded_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise ProjectionContractError(f"{field} must be bounded canonical text")
    return value


def _require_idempotency_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value.encode("utf-8")) > 256
    ):
        raise ProjectionContractError(
            "complete projection idempotency key is invalid"
        )
    return value


def _require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProjectionContractError(f"{field} must be a non-negative integer")
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    _require_non_negative_int(value, field=field)
    if value <= 0:
        raise ProjectionContractError(f"{field} must be positive")
    return value


__all__ = [
    "AdmittedRelationProjection",
    "CompleteDeliveryRequest",
    "CompleteDerivativeType",
    "CompleteGenerationNames",
    "CompleteGenerationQualificationRequest",
    "CompleteGenerationValidationRequest",
    "CompleteProjectionAction",
    "CompleteProjectionApplyResult",
    "CompleteProjectionBatch",
    "CompleteProjectionDeliveryRecord",
    "CompleteProjectionDocument",
    "CompleteProjectionIdentity",
    "CompleteProjectionQualification",
    "CompleteProjectionRemoval",
    "CompleteProjectionState",
    "CompleteQualificationResult",
    "CompleteQueryHit",
    "CompleteQueryKind",
    "CompleteRebuildRequest",
    "CompleteRebuildResult",
    "Neo4jIndexState",
    "Neo4jIndexType",
    "complete_generation_names",
]
