from __future__ import annotations

from typing import Any

from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityResolutionDependencyId,
)
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ProposalEnvelopeId,
)
from newsroom.integrated.models import (
    IntegratedHypothesisVersionId,
    StoryCandidateId,
    StoryCandidateVersionId,
)
from newsroom.relations.editorial_models import (
    CanonicalEntityRelationEndpoint,
    EditorialRelationDecisionRequest,
    EditorialRelationProducer,
    EditorialRelationProposalRequest,
    EditorialRelationTemporalScope,
    EventHypothesisRelationEndpoint,
    ExtractionRelationEvidence,
    RelationAssertionRelationEndpoint,
    SourceRevisionRelationEndpoint,
    StoryCandidateRelationEndpoint,
    WorkflowRelationEvidence,
)
from newsroom.relations.editorial_types import (
    EditorialPredicateCode,
    EditorialRelationAssertionId,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionId,
    EditorialRelationEndpointKind,
    EditorialRelationEvidenceKind,
    EditorialRelationProducerKind,
    EditorialRelationProposalId,
    EditorialRelationProposalVersionId,
    EditorialRelationSupersessionId,
)
from newsroom.sources.types import SourceItemId, SourceRevisionId


def _required(value: Any, key: str) -> Any:
    if not isinstance(value, dict) or key not in value:
        raise ValueError(f"missing editorial relation field {key}")
    return value[key]


def _endpoint(value: Any):
    if not isinstance(value, dict):
        raise ValueError("editorial relation endpoint must be an object")
    kind = EditorialRelationEndpointKind(str(_required(value, "kind")))
    if kind is EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION:
        return CanonicalEntityRelationEndpoint(
            entity_id=CanonicalEntityId.parse(str(_required(value, "entity_id"))),
            entity_version_id=CanonicalEntityVersionId.parse(
                str(_required(value, "entity_version_id"))
            ),
        )
    if kind is EditorialRelationEndpointKind.SOURCE_REVISION:
        return SourceRevisionRelationEndpoint(
            source_item_id=SourceItemId.parse(
                str(_required(value, "source_item_id"))
            ),
            source_revision_id=SourceRevisionId.parse(
                str(_required(value, "source_revision_id"))
            ),
        )
    if kind is EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION:
        return EventHypothesisRelationEndpoint(
            hypothesis_version_id=IntegratedHypothesisVersionId.parse(
                str(_required(value, "hypothesis_version_id"))
            )
        )
    if kind is EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION:
        return StoryCandidateRelationEndpoint(
            candidate_id=StoryCandidateId.parse(str(_required(value, "candidate_id"))),
            candidate_version_id=StoryCandidateVersionId.parse(
                str(_required(value, "candidate_version_id"))
            ),
        )
    return RelationAssertionRelationEndpoint(
        assertion_id=EditorialRelationAssertionId.parse(
            str(_required(value, "assertion_id"))
        )
    )


def _temporal(value: Any) -> EditorialRelationTemporalScope:
    if not isinstance(value, dict):
        raise ValueError("editorial relation temporal scope must be an object")
    return EditorialRelationTemporalScope(
        valid_from=(
            None
            if value.get("valid_from") is None
            else UtcTimestamp.parse(str(value["valid_from"]))
        ),
        valid_until=(
            None
            if value.get("valid_until") is None
            else UtcTimestamp.parse(str(value["valid_until"]))
        ),
        observed_at=UtcTimestamp.parse(str(_required(value, "observed_at"))),
    )


def _evidence(value: Any):
    if not isinstance(value, list):
        raise ValueError("editorial relation evidence must be a list")
    items = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("editorial relation evidence item must be an object")
        kind = EditorialRelationEvidenceKind(str(_required(raw, "kind")))
        if kind is EditorialRelationEvidenceKind.EXTRACTION_PROPOSAL:
            items.append(
                ExtractionRelationEvidence(
                    source_proposal_id=ProposalEnvelopeId.parse(
                        str(_required(raw, "source_proposal_id"))
                    ),
                    source_proposal_digest=str(
                        _required(raw, "source_proposal_digest")
                    ),
                    run_id=ExtractionRunId.parse(str(_required(raw, "run_id"))),
                    run_version_id=ExtractionRunVersionId.parse(
                        str(_required(raw, "run_version_id"))
                    ),
                    output_id=ExtractionOutputId.parse(
                        str(_required(raw, "output_id"))
                    ),
                    passage_id=ExtractionPassageId.parse(
                        str(_required(raw, "passage_id"))
                    ),
                    source_evidence_ordinal=int(
                        _required(raw, "source_evidence_ordinal")
                    ),
                    start_byte=int(_required(raw, "start_byte")),
                    end_byte=int(_required(raw, "end_byte")),
                    evidence_text_digest=str(
                        _required(raw, "evidence_text_digest")
                    ),
                )
            )
        else:
            items.append(
                WorkflowRelationEvidence(
                    authority_event_id=EventId.parse(
                        str(_required(raw, "authority_event_id"))
                    ),
                    aggregate_type=str(_required(raw, "aggregate_type")),
                    aggregate_id=str(_required(raw, "aggregate_id")),
                    aggregate_version=int(_required(raw, "aggregate_version")),
                    event_digest=str(_required(raw, "event_digest")),
                )
            )
    return tuple(items)


def _producer(value: Any) -> EditorialRelationProducer:
    if not isinstance(value, dict):
        raise ValueError("editorial relation producer must be an object")
    return EditorialRelationProducer(
        kind=EditorialRelationProducerKind(str(_required(value, "kind"))),
        producer_id=str(_required(value, "producer_id")),
        producer_version=str(_required(value, "producer_version")),
        contract_digest=str(_required(value, "contract_digest")),
    )


def decode_editorial_relation_proposal_request(
    value: Any, *, idempotency_key: str
) -> EditorialRelationProposalRequest:
    if not isinstance(value, dict):
        raise ValueError("editorial relation proposal request must be an object")
    previous = value.get("expected_previous_version_id")
    return EditorialRelationProposalRequest(
        proposal_id=EditorialRelationProposalId.parse(
            str(_required(value, "proposal_id"))
        ),
        proposal_version_id=EditorialRelationProposalVersionId.parse(
            str(_required(value, "proposal_version_id"))
        ),
        version_number=int(_required(value, "version_number")),
        expected_previous_version_id=(
            None
            if previous is None
            else EditorialRelationProposalVersionId.parse(str(previous))
        ),
        predicate_registry_digest=str(
            _required(value, "predicate_registry_digest")
        ),
        predicate_contract_digest=str(
            _required(value, "predicate_contract_digest")
        ),
        predicate=EditorialPredicateCode(str(_required(value, "predicate"))),
        subject=_endpoint(_required(value, "subject")),
        object=_endpoint(_required(value, "object")),
        temporal_scope=_temporal(_required(value, "temporal_scope")),
        evidence=_evidence(_required(value, "evidence")),
        resolution_dependency_ids=tuple(
            EntityResolutionDependencyId.parse(str(item))
            for item in _required(value, "resolution_dependency_ids")
        ),
        producer=_producer(_required(value, "producer")),
        statement=str(_required(value, "statement")),
        confidence_basis_points=(
            None
            if value.get("confidence_basis_points") is None
            else int(value["confidence_basis_points"])
        ),
        uncertainty_codes=tuple(str(item) for item in value["uncertainty_codes"]),
        basis_codes=tuple(str(item) for item in value["basis_codes"]),
        idempotency_key=idempotency_key,
    )


def decode_editorial_relation_decision_request(
    value: Any, *, idempotency_key: str
) -> EditorialRelationDecisionRequest:
    if not isinstance(value, dict):
        raise ValueError("editorial relation decision request must be an object")

    def optional(identifier_type: type, key: str):
        raw = value.get(key)
        return None if raw is None else identifier_type.parse(str(raw))

    return EditorialRelationDecisionRequest(
        decision_id=EditorialRelationDecisionId.parse(
            str(_required(value, "decision_id"))
        ),
        action=EditorialRelationDecisionAction(str(_required(value, "action"))),
        proposal_id=EditorialRelationProposalId.parse(
            str(_required(value, "proposal_id"))
        ),
        proposal_version_id=EditorialRelationProposalVersionId.parse(
            str(_required(value, "proposal_version_id"))
        ),
        expected_proposal_version_digest=str(
            _required(value, "expected_proposal_version_digest")
        ),
        expected_previous_decision_id=optional(
            EditorialRelationDecisionId, "expected_previous_decision_id"
        ),
        expected_previous_decision_version=int(
            _required(value, "expected_previous_decision_version")
        ),
        assertion_id=optional(EditorialRelationAssertionId, "assertion_id"),
        target_assertion_id=optional(
            EditorialRelationAssertionId, "target_assertion_id"
        ),
        successor_assertion_id=optional(
            EditorialRelationAssertionId, "successor_assertion_id"
        ),
        supersession_id=optional(
            EditorialRelationSupersessionId, "supersession_id"
        ),
        reason_code=str(_required(value, "reason_code")),
        decision_policy_version=str(
            _required(value, "decision_policy_version")
        ),
        idempotency_key=idempotency_key,
    )


__all__ = [
    "decode_editorial_relation_decision_request",
    "decode_editorial_relation_proposal_request",
]
