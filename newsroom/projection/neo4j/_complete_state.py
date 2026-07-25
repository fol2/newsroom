from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import EventId, ObjectAdmissionId, UtcTimestamp
from newsroom.projection.complete import (
    CompleteProjectionProfile,
    FullTextIndexContract,
    VectorIndexContract,
)
from newsroom.projection.models import ProjectionContractError
from newsroom.relations.models import (
    FixturePassageObject,
    RelationAdmissionDecisionId,
    RelationAssertionId,
    RelationEndpoint,
    RelationPredicate,
    RelationProducer,
    RelationProducerKind,
    RelationProposalId,
    RelationRecordType,
    RelationTemporalScope,
)

from ._state import _expected_projection_state_digest
from .complete_models import (
    AdmittedRelationProjection,
    CompleteDerivativeType,
    CompleteProjectionBatch,
    CompleteProjectionDeliveryRecord,
    CompleteProjectionDocument,
    CompleteProjectionIdentity,
    CompleteProjectionRemoval,
    CompleteProjectionState,
    Neo4jIndexState,
)
from .models import Neo4jIdentityConflict, StructuralBatch


_COMPLETE_STATE_CONTRACT = "newsroom-complete-projection-state-v1"
_COMPLETE_DOCUMENT_BASE_LABEL = "NewsroomCompleteProjectionDocument"
_COMPLETE_DELIVERY_LABEL = "NewsroomCompleteProjectionDelivery"
_ADMITTED_ENDPOINT_LABEL = "NewsroomAdmittedRelationEndpoint"
_ADMITTED_RELATION_IDENTITY_LABEL = "NewsroomAdmittedRelationIdentity"

_DOCUMENT_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "family_id",
        "family_definition_version",
        "projector_version",
        "ontology_contract_digest",
        "mapping_contract_digest",
        "complete_contract_digest",
        "fulltext_contract_digest",
        "vector_contract_digest",
        "fixture_vector_manifest_digest",
        "passage_id",
        "admission_id",
        "blob_digest",
        "language",
        "revision_id",
        "retrieval_text",
        "normalized_text_digest",
        "vector_components",
        "fixture_vector",
        "vector_digest",
        "vector_dimensions",
        "vector_component_scale",
        "source_event_id",
        "source_ledger_seq",
        "recorded_at",
        "document_digest",
    }
)

_ENDPOINT_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "record_type",
        "record_id",
    }
)

_RELATION_IDENTITY_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "relation_key",
        "assertion_id",
        "proposal_id",
        "admission_decision_id",
        "relation_digest",
    }
)

_RELATION_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "family_id",
        "family_definition_version",
        "projector_version",
        "complete_contract_digest",
        "relation_key",
        "assertion_id",
        "proposal_id",
        "admission_decision_id",
        "subject_record_type",
        "subject_record_id",
        "predicate",
        "object_record_type",
        "object_record_id",
        "trust_scope",
        "valid_from",
        "valid_until",
        "temporal_precision",
        "evidence_objects_json",
        "producer_kind",
        "producer_id",
        "producer_version",
        "rule_version",
        "statement",
        "uncertainties_json",
        "proposal_digest",
        "source_event_id",
        "source_ledger_seq",
        "recorded_at",
        "relation_digest",
    }
)

_DELIVERY_PROPERTY_KEYS = frozenset(
    {
        "generation_id",
        "ledger_seq",
        "source_event_id",
        "source_event_digest",
        "batch_digest",
    }
)


def _identity_properties(identity: CompleteProjectionIdentity) -> dict[str, object]:
    return {
        "generation_id": str(identity.generation_id),
        "family_id": identity.family_id,
        "family_definition_version": identity.family_definition_version,
        "projector_version": identity.projector_version,
        "ontology_contract_digest": identity.ontology_contract_digest,
        "mapping_contract_digest": identity.mapping_contract_digest,
        "complete_contract_digest": identity.complete_contract_digest,
        "fulltext_contract_digest": identity.fulltext_contract_digest,
        "vector_contract_digest": identity.vector_contract_digest,
        "fixture_vector_manifest_digest": identity.fixture_vector_manifest_digest,
    }


def _document_properties(document: CompleteProjectionDocument) -> dict[str, object]:
    return {
        **_identity_properties(document.identity),
        "passage_id": document.passage_id,
        "admission_id": str(document.admission_id),
        "blob_digest": document.blob_digest,
        "language": document.language,
        "revision_id": document.revision_id,
        "retrieval_text": document.retrieval_text,
        "normalized_text_digest": document.normalized_text_digest,
        "vector_components": list(document.vector_components),
        "fixture_vector": list(document.vector),
        "vector_digest": document.vector_digest,
        "vector_dimensions": document.vector_dimensions,
        "vector_component_scale": document.vector_component_scale,
        "source_event_id": str(document.source_event_id),
        "source_ledger_seq": document.source_ledger_seq,
        "recorded_at": document.recorded_at.to_text(),
        "document_digest": document.document_digest,
    }


def _endpoint_properties(
    identity: CompleteProjectionIdentity,
    endpoint: RelationEndpoint,
) -> dict[str, object]:
    return {
        "generation_id": str(identity.generation_id),
        "record_type": endpoint.record_type.value,
        "record_id": endpoint.record_id,
    }


def _relation_identity_properties(
    relation: AdmittedRelationProjection,
) -> dict[str, object]:
    return {
        "generation_id": str(relation.identity.generation_id),
        "relation_key": relation.relation_key,
        "assertion_id": str(relation.assertion_id),
        "proposal_id": str(relation.proposal_id),
        "admission_decision_id": str(relation.admission_decision_id),
        "relation_digest": relation.relation_digest,
    }


def _relation_properties(
    relation: AdmittedRelationProjection,
) -> dict[str, object]:
    temporal = relation.temporal_scope
    producer = relation.producer
    return {
        "generation_id": str(relation.identity.generation_id),
        "family_id": relation.identity.family_id,
        "family_definition_version": relation.identity.family_definition_version,
        "projector_version": relation.identity.projector_version,
        "complete_contract_digest": relation.identity.complete_contract_digest,
        "relation_key": relation.relation_key,
        "assertion_id": str(relation.assertion_id),
        "proposal_id": str(relation.proposal_id),
        "admission_decision_id": str(relation.admission_decision_id),
        "subject_record_type": relation.subject.record_type.value,
        "subject_record_id": relation.subject.record_id,
        "predicate": relation.predicate.value,
        "object_record_type": relation.object.record_type.value,
        "object_record_id": relation.object.record_id,
        "trust_scope": relation.trust_scope.value,
        "valid_from": temporal.valid_from.to_text(),
        "valid_until": (
            None if temporal.valid_until is None else temporal.valid_until.to_text()
        ),
        "temporal_precision": temporal.precision,
        "evidence_objects_json": canonical_json_bytes(
            [item.canonical_value() for item in relation.evidence_objects]
        ).decode("utf-8"),
        "producer_kind": producer.kind.value,
        "producer_id": producer.producer_id,
        "producer_version": producer.producer_version,
        "rule_version": producer.rule_version,
        "statement": relation.statement,
        "uncertainties_json": canonical_json_bytes(
            list(relation.uncertainties)
        ).decode("utf-8"),
        "proposal_digest": relation.proposal_digest,
        "source_event_id": str(relation.source_event_id),
        "source_ledger_seq": relation.source_ledger_seq,
        "recorded_at": relation.recorded_at.to_text(),
        "relation_digest": relation.relation_digest,
    }


def _delivery_properties(batch: CompleteProjectionBatch) -> dict[str, object]:
    return {
        "generation_id": str(batch.identity.generation_id),
        "ledger_seq": batch.ledger_seq,
        "source_event_id": str(batch.source_event_id),
        "source_event_digest": batch.source_event_digest,
        "batch_digest": batch.batch_digest,
    }


def _expected_complete_projection_state(
    identity: CompleteProjectionIdentity,
    checkpoint_ledger_seq: int,
    expected_batches: Iterable[CompleteProjectionBatch],
    *,
    fulltext: FullTextIndexContract,
    vector: VectorIndexContract,
    profile: CompleteProjectionProfile,
) -> CompleteProjectionState:
    if not isinstance(identity, CompleteProjectionIdentity):
        raise TypeError("complete state identity must be typed")
    if (
        isinstance(checkpoint_ledger_seq, bool)
        or not isinstance(checkpoint_ledger_seq, int)
        or checkpoint_ledger_seq < 0
    ):
        raise ProjectionContractError(
            "complete state checkpoint must be non-negative"
        )
    if not isinstance(fulltext, FullTextIndexContract):
        raise TypeError("complete state full-text contract must be typed")
    if not isinstance(vector, VectorIndexContract):
        raise TypeError("complete state vector contract must be typed")
    if not isinstance(profile, CompleteProjectionProfile):
        raise TypeError("complete state profile must be typed")
    vector.require_profile(profile)
    if (
        identity.fulltext_contract_digest != fulltext.contract_digest
        or identity.vector_contract_digest != vector.contract_digest
    ):
        raise Neo4jIdentityConflict(
            "complete state contracts differ from generation identity"
        )

    batches = tuple(expected_batches)
    previous = 0
    documents: dict[str, CompleteProjectionDocument] = {}
    relations: dict[str, AdmittedRelationProjection] = {}
    deliveries: dict[int, CompleteProjectionDeliveryRecord] = {}
    structural_batches: list[StructuralBatch] = []

    for batch in batches:
        if not isinstance(batch, CompleteProjectionBatch):
            raise TypeError("complete state requires typed batches")
        if batch.identity != identity:
            raise Neo4jIdentityConflict(
                "complete batch belongs to another generation identity"
            )
        if batch.ledger_seq <= previous:
            raise Neo4jIdentityConflict(
                "complete batches must be strictly ordered"
            )
        if batch.ledger_seq > checkpoint_ledger_seq:
            raise Neo4jIdentityConflict(
                "complete batch exceeds requested checkpoint"
            )
        previous = batch.ledger_seq
        if batch.structural_batch is not None:
            structural_batches.append(batch.structural_batch)
        for removal in batch.removals:
            if removal.derivative_type in {
                CompleteDerivativeType.FULL_TEXT,
                CompleteDerivativeType.VECTOR,
            }:
                documents.pop(removal.stable_key, None)
            elif removal.derivative_type is CompleteDerivativeType.ADMITTED_RELATION:
                relations.pop(removal.stable_key, None)
            elif removal.derivative_type is not CompleteDerivativeType.STRUCTURAL:
                raise Neo4jIdentityConflict(
                    "unknown complete removal derivative"
                )
        for document in batch.documents:
            existing = documents.get(document.passage_id)
            if existing is not None and existing != document:
                raise Neo4jIdentityConflict(
                    "complete document identity conflicts with retained state"
                )
            documents[document.passage_id] = document
        for relation in batch.relations:
            existing = relations.get(relation.relation_key)
            if existing is not None and existing != relation:
                raise Neo4jIdentityConflict(
                    "admitted relation identity conflicts with retained state"
                )
            relations[relation.relation_key] = relation
        delivery = CompleteProjectionDeliveryRecord(
            identity=identity,
            ledger_seq=batch.ledger_seq,
            source_event_id=batch.source_event_id,
            source_event_digest=batch.source_event_digest,
            batch_digest=batch.batch_digest,
        )
        existing_delivery = deliveries.get(batch.ledger_seq)
        if existing_delivery is not None and existing_delivery != delivery:
            raise Neo4jIdentityConflict(
                "complete delivery sequence conflicts with retained state"
            )
        deliveries[batch.ledger_seq] = delivery

    if batches and batches[-1].ledger_seq != checkpoint_ledger_seq:
        raise Neo4jIdentityConflict(
            "complete batches do not reach the exact checkpoint"
        )
    if not batches and checkpoint_ledger_seq != 0:
        raise Neo4jIdentityConflict(
            "non-zero complete checkpoint requires retained batches"
        )

    structural_digest = _expected_projection_state_digest(
        str(identity.generation_id), structural_batches
    )
    return CompleteProjectionState(
        identity=identity,
        checkpoint_ledger_seq=checkpoint_ledger_seq,
        structural_state_digest=structural_digest,
        documents=tuple(documents[key] for key in sorted(documents)),
        relations=tuple(relations[key] for key in sorted(relations)),
        deliveries=tuple(deliveries[key] for key in sorted(deliveries)),
        fulltext_index_state=Neo4jIndexState.ONLINE,
        vector_index_state=Neo4jIndexState.ONLINE,
        fulltext_index_provider=fulltext.provider,
        vector_index_provider=vector.provider,
    )


def _document_from_properties(
    identity: CompleteProjectionIdentity,
    raw: Mapping[str, object],
) -> CompleteProjectionDocument:
    value = _require_exact_properties(
        raw, _DOCUMENT_PROPERTY_KEYS, "complete document"
    )
    _require_identity_properties(identity, value, "complete document")
    components = tuple(int(item) for item in _require_list(value["vector_components"]))
    fixture_vector = tuple(float(item) for item in _require_list(value["fixture_vector"]))
    document = CompleteProjectionDocument(
        identity=identity,
        passage_id=str(value["passage_id"]),
        admission_id=ObjectAdmissionId.parse(str(value["admission_id"])),
        blob_digest=str(value["blob_digest"]),
        language=str(value["language"]),
        revision_id=(
            None if value["revision_id"] is None else str(value["revision_id"])
        ),
        retrieval_text=str(value["retrieval_text"]),
        normalized_text_digest=str(value["normalized_text_digest"]),
        vector_components=components,
        vector_digest=str(value["vector_digest"]),
        vector_dimensions=int(value["vector_dimensions"]),
        vector_component_scale=int(value["vector_component_scale"]),
        source_event_id=EventId.parse(str(value["source_event_id"])),
        source_ledger_seq=int(value["source_ledger_seq"]),
        recorded_at=UtcTimestamp.parse(str(value["recorded_at"])),
    )
    if tuple(document.vector) != fixture_vector:
        raise Neo4jIdentityConflict(
            "complete document vector floats differ from fixed-point authority"
        )
    if str(value["document_digest"]) != document.document_digest:
        raise Neo4jIdentityConflict(
            "complete document digest differs from retained properties"
        )
    return document


def _relation_from_properties(
    identity: CompleteProjectionIdentity,
    raw: Mapping[str, object],
) -> AdmittedRelationProjection:
    value = _require_exact_properties(
        raw, _RELATION_PROPERTY_KEYS, "admitted relation"
    )
    for key, expected in (
        ("generation_id", str(identity.generation_id)),
        ("family_id", identity.family_id),
        ("family_definition_version", identity.family_definition_version),
        ("projector_version", identity.projector_version),
        ("complete_contract_digest", identity.complete_contract_digest),
    ):
        if value[key] != expected:
            raise Neo4jIdentityConflict(
                "admitted relation belongs to another complete identity"
            )
    evidence_value = json.loads(str(value["evidence_objects_json"]))
    if not isinstance(evidence_value, list):
        raise Neo4jIdentityConflict("admitted relation evidence is malformed")
    evidence = tuple(
        FixturePassageObject(
            passage_id=str(item["passage_id"]),
            admission_id=ObjectAdmissionId.parse(str(item["admission_id"])),
            blob_digest=str(item["blob_digest"]),
        )
        for item in evidence_value
    )
    uncertainties_value = json.loads(str(value["uncertainties_json"]))
    if not isinstance(uncertainties_value, list):
        raise Neo4jIdentityConflict(
            "admitted relation uncertainties are malformed"
        )
    relation = AdmittedRelationProjection(
        identity=identity,
        assertion_id=RelationAssertionId.parse(str(value["assertion_id"])),
        proposal_id=RelationProposalId.parse(str(value["proposal_id"])),
        admission_decision_id=RelationAdmissionDecisionId.parse(
            str(value["admission_decision_id"])
        ),
        relation_key=str(value["relation_key"]),
        subject=RelationEndpoint(
            RelationRecordType(str(value["subject_record_type"])),
            str(value["subject_record_id"]),
        ),
        predicate=RelationPredicate(str(value["predicate"])),
        object=RelationEndpoint(
            RelationRecordType(str(value["object_record_type"])),
            str(value["object_record_id"]),
        ),
        temporal_scope=RelationTemporalScope(
            valid_from=UtcTimestamp.parse(str(value["valid_from"])),
            valid_until=(
                None
                if value["valid_until"] is None
                else UtcTimestamp.parse(str(value["valid_until"]))
            ),
            precision=str(value["temporal_precision"]),
        ),
        evidence_objects=evidence,
        producer=RelationProducer(
            kind=RelationProducerKind(str(value["producer_kind"])),
            producer_id=str(value["producer_id"]),
            producer_version=str(value["producer_version"]),
            rule_version=str(value["rule_version"]),
        ),
        statement=str(value["statement"]),
        uncertainties=tuple(str(item) for item in uncertainties_value),
        proposal_digest=str(value["proposal_digest"]),
        source_event_id=EventId.parse(str(value["source_event_id"])),
        source_ledger_seq=int(value["source_ledger_seq"]),
        recorded_at=UtcTimestamp.parse(str(value["recorded_at"])),
    )
    if value["trust_scope"] != relation.trust_scope.value:
        raise Neo4jIdentityConflict(
            "admitted relation trust scope differs from authority"
        )
    if str(value["relation_digest"]) != relation.relation_digest:
        raise Neo4jIdentityConflict(
            "admitted relation digest differs from retained properties"
        )
    return relation


def _delivery_from_properties(
    identity: CompleteProjectionIdentity,
    raw: Mapping[str, object],
) -> CompleteProjectionDeliveryRecord:
    value = _require_exact_properties(
        raw, _DELIVERY_PROPERTY_KEYS, "complete delivery"
    )
    if value["generation_id"] != str(identity.generation_id):
        raise Neo4jIdentityConflict(
            "complete delivery belongs to another generation"
        )
    return CompleteProjectionDeliveryRecord(
        identity=identity,
        ledger_seq=int(value["ledger_seq"]),
        source_event_id=EventId.parse(str(value["source_event_id"])),
        source_event_digest=str(value["source_event_digest"]),
        batch_digest=str(value["batch_digest"]),
    )


def _endpoint_from_properties(
    identity: CompleteProjectionIdentity,
    raw: Mapping[str, object],
) -> RelationEndpoint:
    value = _require_exact_properties(
        raw, _ENDPOINT_PROPERTY_KEYS, "admitted relation endpoint"
    )
    if value["generation_id"] != str(identity.generation_id):
        raise Neo4jIdentityConflict(
            "admitted relation endpoint belongs to another generation"
        )
    return RelationEndpoint(
        RelationRecordType(str(value["record_type"])),
        str(value["record_id"]),
    )


def _relation_identity_from_properties(
    identity: CompleteProjectionIdentity,
    raw: Mapping[str, object],
) -> dict[str, object]:
    value = _require_exact_properties(
        raw,
        _RELATION_IDENTITY_PROPERTY_KEYS,
        "admitted relation identity",
    )
    if value["generation_id"] != str(identity.generation_id):
        raise Neo4jIdentityConflict(
            "admitted relation identity belongs to another generation"
        )
    return value


def _complete_state_digest_from_parts(
    *,
    identity: CompleteProjectionIdentity,
    checkpoint_ledger_seq: int,
    structural_state_digest: str,
    documents: Iterable[CompleteProjectionDocument],
    relations: Iterable[AdmittedRelationProjection],
    deliveries: Iterable[CompleteProjectionDeliveryRecord],
    fulltext_index_state: Neo4jIndexState,
    vector_index_state: Neo4jIndexState,
    fulltext_index_provider: str,
    vector_index_provider: str,
) -> str:
    state = CompleteProjectionState(
        identity=identity,
        checkpoint_ledger_seq=checkpoint_ledger_seq,
        structural_state_digest=structural_state_digest,
        documents=tuple(sorted(documents, key=lambda item: item.passage_id)),
        relations=tuple(sorted(relations, key=lambda item: item.relation_key)),
        deliveries=tuple(sorted(deliveries, key=lambda item: item.ledger_seq)),
        fulltext_index_state=fulltext_index_state,
        vector_index_state=vector_index_state,
        fulltext_index_provider=fulltext_index_provider,
        vector_index_provider=vector_index_provider,
    )
    return state.state_digest


def _require_exact_properties(
    value: Mapping[str, object],
    expected: frozenset[str],
    identity: str,
) -> dict[str, object]:
    copied = dict(value)
    if set(copied) != set(expected):
        raise Neo4jIdentityConflict(
            f"{identity} properties differ from the fixed complete contract"
        )
    return copied


def _require_identity_properties(
    identity: CompleteProjectionIdentity,
    value: Mapping[str, object],
    record_name: str,
) -> None:
    expected = _identity_properties(identity)
    if any(value[key] != expected[key] for key in expected):
        raise Neo4jIdentityConflict(
            f"{record_name} belongs to another complete identity"
        )


def _require_list(value: object) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise Neo4jIdentityConflict("Neo4j complete list property is malformed")
    return list(value)


__all__ = [
    "_ADMITTED_ENDPOINT_LABEL",
    "_ADMITTED_RELATION_IDENTITY_LABEL",
    "_COMPLETE_DELIVERY_LABEL",
    "_COMPLETE_DOCUMENT_BASE_LABEL",
    "_DELIVERY_PROPERTY_KEYS",
    "_DOCUMENT_PROPERTY_KEYS",
    "_ENDPOINT_PROPERTY_KEYS",
    "_RELATION_IDENTITY_PROPERTY_KEYS",
    "_RELATION_PROPERTY_KEYS",
    "_complete_state_digest_from_parts",
    "_delivery_from_properties",
    "_delivery_properties",
    "_document_from_properties",
    "_document_properties",
    "_endpoint_from_properties",
    "_endpoint_properties",
    "_expected_complete_projection_state",
    "_relation_from_properties",
    "_relation_identity_from_properties",
    "_relation_identity_properties",
    "_relation_properties",
]
