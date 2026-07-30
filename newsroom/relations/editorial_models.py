from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, TypeAlias

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.authority.types import EventId, TrustScope, UtcTimestamp
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
from newsroom.sources.types import SourceItemId, SourceRevisionId

from .editorial_types import (
    EditorialPredicateCode,
    EditorialPredicateDirectionality,
    EditorialPredicateTemporalSemantics,
    EditorialRelationAssertionId,
    EditorialRelationAssertionLifecycle,
    EditorialRelationContractError,
    EditorialRelationCurrentState,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionId,
    EditorialRelationEndpointKind,
    EditorialRelationEvidenceKind,
    EditorialRelationProducerKind,
    EditorialRelationProjectionAction,
    EditorialRelationProposalId,
    EditorialRelationProposalVersionId,
    EditorialRelationSupersessionId,
    bounded_int,
    bounded_scope,
    bounded_text,
    bounded_token,
    canonical_digest,
    sorted_id_tuple,
    sorted_text_tuple,
)


def _require_typed(value: object, expected: type, *, field: str) -> None:
    if not isinstance(value, expected):
        raise EditorialRelationContractError(f"{field} must be typed")


@dataclass(frozen=True, slots=True)
class CanonicalEntityRelationEndpoint:
    entity_id: CanonicalEntityId
    entity_version_id: CanonicalEntityVersionId
    kind: ClassVar[EditorialRelationEndpointKind] = (
        EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION
    )

    def __post_init__(self) -> None:
        _require_typed(self.entity_id, CanonicalEntityId, field="entity_id")
        _require_typed(
            self.entity_version_id,
            CanonicalEntityVersionId,
            field="entity_version_id",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "entity_id": str(self.entity_id),
            "entity_version_id": str(self.entity_version_id),
        }


@dataclass(frozen=True, slots=True)
class SourceRevisionRelationEndpoint:
    source_item_id: SourceItemId
    source_revision_id: SourceRevisionId
    kind: ClassVar[EditorialRelationEndpointKind] = (
        EditorialRelationEndpointKind.SOURCE_REVISION
    )

    def __post_init__(self) -> None:
        _require_typed(self.source_item_id, SourceItemId, field="source_item_id")
        _require_typed(
            self.source_revision_id,
            SourceRevisionId,
            field="source_revision_id",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "source_item_id": str(self.source_item_id),
            "source_revision_id": str(self.source_revision_id),
        }


@dataclass(frozen=True, slots=True)
class EventHypothesisRelationEndpoint:
    hypothesis_version_id: IntegratedHypothesisVersionId
    kind: ClassVar[EditorialRelationEndpointKind] = (
        EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION
    )

    def __post_init__(self) -> None:
        _require_typed(
            self.hypothesis_version_id,
            IntegratedHypothesisVersionId,
            field="hypothesis_version_id",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "hypothesis_version_id": str(self.hypothesis_version_id),
        }


@dataclass(frozen=True, slots=True)
class StoryCandidateRelationEndpoint:
    candidate_id: StoryCandidateId
    candidate_version_id: StoryCandidateVersionId
    kind: ClassVar[EditorialRelationEndpointKind] = (
        EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION
    )

    def __post_init__(self) -> None:
        _require_typed(self.candidate_id, StoryCandidateId, field="candidate_id")
        _require_typed(
            self.candidate_version_id,
            StoryCandidateVersionId,
            field="candidate_version_id",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "candidate_id": str(self.candidate_id),
            "candidate_version_id": str(self.candidate_version_id),
        }


@dataclass(frozen=True, slots=True)
class RelationAssertionRelationEndpoint:
    assertion_id: EditorialRelationAssertionId
    kind: ClassVar[EditorialRelationEndpointKind] = (
        EditorialRelationEndpointKind.RELATION_ASSERTION
    )

    def __post_init__(self) -> None:
        _require_typed(
            self.assertion_id,
            EditorialRelationAssertionId,
            field="assertion_id",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "assertion_id": str(self.assertion_id),
        }


EditorialRelationEndpoint: TypeAlias = (
    CanonicalEntityRelationEndpoint
    | SourceRevisionRelationEndpoint
    | EventHypothesisRelationEndpoint
    | StoryCandidateRelationEndpoint
    | RelationAssertionRelationEndpoint
)


def endpoint_kind(value: EditorialRelationEndpoint) -> EditorialRelationEndpointKind:
    kind = getattr(value, "kind", None)
    if not isinstance(kind, EditorialRelationEndpointKind):
        raise EditorialRelationContractError("relation endpoint must be typed")
    return kind


def endpoint_canonical_value(value: EditorialRelationEndpoint) -> dict[str, str]:
    if not isinstance(
        value,
        (
            CanonicalEntityRelationEndpoint,
            SourceRevisionRelationEndpoint,
            EventHypothesisRelationEndpoint,
            StoryCandidateRelationEndpoint,
            RelationAssertionRelationEndpoint,
        ),
    ):
        raise EditorialRelationContractError("relation endpoint must be typed")
    return value.canonical_value()


def endpoint_canonical_bytes(value: EditorialRelationEndpoint) -> bytes:
    return canonical_json_bytes(endpoint_canonical_value(value))


@dataclass(frozen=True, slots=True)
class EditorialPredicateEndpointPair:
    subject_kind: EditorialRelationEndpointKind
    object_kind: EditorialRelationEndpointKind

    def __post_init__(self) -> None:
        _require_typed(
            self.subject_kind,
            EditorialRelationEndpointKind,
            field="subject_kind",
        )
        _require_typed(
            self.object_kind,
            EditorialRelationEndpointKind,
            field="object_kind",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "subject_kind": self.subject_kind.value,
            "object_kind": self.object_kind.value,
        }

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.subject_kind.value, self.object_kind.value)


@dataclass(frozen=True, slots=True)
class EditorialPredicateContract:
    predicate: EditorialPredicateCode
    contract_version: str
    directionality: EditorialPredicateDirectionality
    temporal_semantics: EditorialPredicateTemporalSemantics
    allowed_endpoint_pairs: tuple[EditorialPredicateEndpointPair, ...]
    admission_policy_version: str

    def __post_init__(self) -> None:
        _require_typed(self.predicate, EditorialPredicateCode, field="predicate")
        bounded_token(self.contract_version, field="predicate_contract_version")
        _require_typed(
            self.directionality,
            EditorialPredicateDirectionality,
            field="predicate_directionality",
        )
        _require_typed(
            self.temporal_semantics,
            EditorialPredicateTemporalSemantics,
            field="predicate_temporal_semantics",
        )
        bounded_token(
            self.admission_policy_version,
            field="predicate_admission_policy_version",
        )
        if not isinstance(self.allowed_endpoint_pairs, tuple):
            raise EditorialRelationContractError(
                "allowed endpoint pairs must be an immutable tuple"
            )
        if not self.allowed_endpoint_pairs or len(self.allowed_endpoint_pairs) > 64:
            raise EditorialRelationContractError(
                "predicate endpoint pairs must contain between 1 and 64 pairs"
            )
        if any(
            not isinstance(item, EditorialPredicateEndpointPair)
            for item in self.allowed_endpoint_pairs
        ):
            raise EditorialRelationContractError(
                "predicate endpoint pair must be typed"
            )
        keys = tuple(item.sort_key for item in self.allowed_endpoint_pairs)
        if keys != tuple(sorted(set(keys))):
            raise EditorialRelationContractError(
                "predicate endpoint pairs must be sorted and unique"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "predicate": self.predicate.value,
            "contract_version": self.contract_version,
            "directionality": self.directionality.value,
            "temporal_semantics": self.temporal_semantics.value,
            "allowed_endpoint_pairs": [
                item.canonical_value() for item in self.allowed_endpoint_pairs
            ],
            "admission_policy_version": self.admission_policy_version,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    def allows(
        self,
        subject_kind: EditorialRelationEndpointKind,
        object_kind: EditorialRelationEndpointKind,
    ) -> bool:
        direct = EditorialPredicateEndpointPair(subject_kind, object_kind)
        if direct in self.allowed_endpoint_pairs:
            return True
        if self.directionality is EditorialPredicateDirectionality.SYMMETRIC:
            return EditorialPredicateEndpointPair(
                object_kind, subject_kind
            ) in self.allowed_endpoint_pairs
        return False


@dataclass(frozen=True, slots=True)
class EditorialPredicateRegistry:
    registry_version: str
    contracts: tuple[EditorialPredicateContract, ...]

    def __post_init__(self) -> None:
        bounded_token(self.registry_version, field="predicate_registry_version")
        if not isinstance(self.contracts, tuple):
            raise EditorialRelationContractError(
                "predicate contracts must be an immutable tuple"
            )
        if len(self.contracts) != len(EditorialPredicateCode):
            raise EditorialRelationContractError(
                "predicate registry must contain the complete closed vocabulary"
            )
        if any(not isinstance(item, EditorialPredicateContract) for item in self.contracts):
            raise EditorialRelationContractError(
                "predicate registry contains an untyped contract"
            )
        codes = tuple(item.predicate.value for item in self.contracts)
        if codes != tuple(sorted(set(codes))):
            raise EditorialRelationContractError(
                "predicate contracts must be sorted and unique"
            )
        if set(codes) != {item.value for item in EditorialPredicateCode}:
            raise EditorialRelationContractError(
                "predicate registry differs from the closed vocabulary"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "registry_version": self.registry_version,
            "contracts": [item.canonical_value() for item in self.contracts],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    def contract(self, predicate: EditorialPredicateCode) -> EditorialPredicateContract:
        _require_typed(predicate, EditorialPredicateCode, field="predicate")
        for item in self.contracts:
            if item.predicate is predicate:
                return item
        raise EditorialRelationContractError("predicate is absent from the registry")


def _pairs(*pairs: tuple[EditorialRelationEndpointKind, EditorialRelationEndpointKind]) -> tuple[EditorialPredicateEndpointPair, ...]:
    return tuple(
        EditorialPredicateEndpointPair(subject, object_)
        for subject, object_ in sorted(
            pairs,
            key=lambda item: (item[0].value, item[1].value),
        )
    )


_PREDICATE_CONTRACT_VERSION = "editorial-predicate-contract-v1"
EDITORIAL_RELATION_ADMISSION_POLICY_VERSION = "editorial-relation-admission-policy-v1"
_PREDICATE_POLICY_VERSION = EDITORIAL_RELATION_ADMISSION_POLICY_VERSION


def _contract(
    predicate: EditorialPredicateCode,
    *,
    directionality: EditorialPredicateDirectionality,
    temporal: EditorialPredicateTemporalSemantics,
    pairs: tuple[EditorialPredicateEndpointPair, ...],
) -> EditorialPredicateContract:
    return EditorialPredicateContract(
        predicate=predicate,
        contract_version=_PREDICATE_CONTRACT_VERSION,
        directionality=directionality,
        temporal_semantics=temporal,
        allowed_endpoint_pairs=pairs,
        admission_policy_version=_PREDICATE_POLICY_VERSION,
    )


EDITORIAL_PREDICATE_REGISTRY_V1 = EditorialPredicateRegistry(
    registry_version="editorial-predicate-registry-v1",
    contracts=tuple(
        sorted(
            (
                _contract(
                    EditorialPredicateCode.ABOUT_EVENT,
                    directionality=EditorialPredicateDirectionality.DIRECTED,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_OPTIONAL,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                    ),
                ),
                _contract(
                    EditorialPredicateCode.CONTRADICTS,
                    directionality=EditorialPredicateDirectionality.SYMMETRIC,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_OPTIONAL,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                    ),
                ),
                _contract(
                    EditorialPredicateCode.CORRECTS,
                    directionality=EditorialPredicateDirectionality.DIRECTED,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_OPTIONAL,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                        ),
                        (
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                        ),
                    ),
                ),
                _contract(
                    EditorialPredicateCode.DEVELOPMENT_OF,
                    directionality=EditorialPredicateDirectionality.DIRECTED,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_REQUIRED,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                        ),
                        (
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                        ),
                    ),
                ),
                _contract(
                    EditorialPredicateCode.DISPUTES,
                    directionality=EditorialPredicateDirectionality.DIRECTED,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_OPTIONAL,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION,
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                        ),
                    ),
                ),
                _contract(
                    EditorialPredicateCode.SAME_EVENT_AS,
                    directionality=EditorialPredicateDirectionality.SYMMETRIC,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_OPTIONAL,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                        ),
                        (
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                        ),
                    ),
                ),
                _contract(
                    EditorialPredicateCode.SAME_PROCESS_AS,
                    directionality=EditorialPredicateDirectionality.SYMMETRIC,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_OPTIONAL,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION,
                            EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                    ),
                ),
                _contract(
                    EditorialPredicateCode.SUPERSEDES,
                    directionality=EditorialPredicateDirectionality.DIRECTED,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_OPTIONAL,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                        ),
                        (
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                            EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION,
                        ),
                    ),
                ),
                _contract(
                    EditorialPredicateCode.SUPPORTS,
                    directionality=EditorialPredicateDirectionality.DIRECTED,
                    temporal=EditorialPredicateTemporalSemantics.VALID_INTERVAL_OPTIONAL,
                    pairs=_pairs(
                        (
                            EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION,
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
                        ),
                        (
                            EditorialRelationEndpointKind.SOURCE_REVISION,
                            EditorialRelationEndpointKind.RELATION_ASSERTION,
                        ),
                    ),
                ),
            ),
            key=lambda item: item.predicate.value,
        )
    ),
)


@dataclass(frozen=True, slots=True)
class EditorialRelationTemporalScope:
    valid_from: UtcTimestamp | None
    valid_until: UtcTimestamp | None
    observed_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.valid_from is not None:
            _require_typed(self.valid_from, UtcTimestamp, field="valid_from")
        if self.valid_until is not None:
            _require_typed(self.valid_until, UtcTimestamp, field="valid_until")
        _require_typed(self.observed_at, UtcTimestamp, field="observed_at")
        if self.valid_from is None and self.valid_until is not None:
            raise EditorialRelationContractError(
                "valid_until requires a valid_from boundary"
            )
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until.value <= self.valid_from.value
        ):
            raise EditorialRelationContractError(
                "valid_until must be later than valid_from"
            )

    def canonical_value(self) -> dict[str, str | None]:
        return {
            "valid_from": self.valid_from.to_text() if self.valid_from else None,
            "valid_until": self.valid_until.to_text() if self.valid_until else None,
            "observed_at": self.observed_at.to_text(),
        }

    def require_contract(self, contract: EditorialPredicateContract) -> None:
        _require_typed(
            contract,
            EditorialPredicateContract,
            field="predicate_contract",
        )
        if (
            contract.temporal_semantics
            is EditorialPredicateTemporalSemantics.VALID_INTERVAL_REQUIRED
            and self.valid_from is None
        ):
            raise EditorialRelationContractError(
                "predicate requires an explicit valid interval"
            )
        if (
            contract.temporal_semantics
            is EditorialPredicateTemporalSemantics.TIMELESS
            and (self.valid_from is not None or self.valid_until is not None)
        ):
            raise EditorialRelationContractError(
                "timeless predicate cannot carry a valid interval"
            )


@dataclass(frozen=True, slots=True)
class ExtractionRelationEvidence:
    source_proposal_id: ProposalEnvelopeId
    source_proposal_digest: str
    run_id: ExtractionRunId
    run_version_id: ExtractionRunVersionId
    output_id: ExtractionOutputId
    passage_id: ExtractionPassageId
    source_evidence_ordinal: int
    start_byte: int
    end_byte: int
    evidence_text_digest: str
    kind: ClassVar[EditorialRelationEvidenceKind] = (
        EditorialRelationEvidenceKind.EXTRACTION_PROPOSAL
    )

    def __post_init__(self) -> None:
        _require_typed(
            self.source_proposal_id,
            ProposalEnvelopeId,
            field="source_proposal_id",
        )
        canonical_digest(
            self.source_proposal_digest,
            field="source_proposal_digest",
        )
        _require_typed(self.run_id, ExtractionRunId, field="run_id")
        _require_typed(
            self.run_version_id,
            ExtractionRunVersionId,
            field="run_version_id",
        )
        _require_typed(self.output_id, ExtractionOutputId, field="output_id")
        _require_typed(self.passage_id, ExtractionPassageId, field="passage_id")
        bounded_int(
            self.source_evidence_ordinal,
            field="source_evidence_ordinal",
            minimum=0,
            maximum=2**31 - 1,
        )
        bounded_int(self.start_byte, field="start_byte", minimum=0, maximum=2**63 - 1)
        bounded_int(self.end_byte, field="end_byte", minimum=1, maximum=2**63 - 1)
        if self.end_byte <= self.start_byte:
            raise EditorialRelationContractError(
                "relation evidence end byte must follow its start byte"
            )
        canonical_digest(
            self.evidence_text_digest,
            field="evidence_text_digest",
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "source_proposal_id": str(self.source_proposal_id),
            "source_proposal_digest": self.source_proposal_digest,
            "run_id": str(self.run_id),
            "run_version_id": str(self.run_version_id),
            "output_id": str(self.output_id),
            "passage_id": str(self.passage_id),
            "source_evidence_ordinal": self.source_evidence_ordinal,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "evidence_text_digest": self.evidence_text_digest,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class WorkflowRelationEvidence:
    authority_event_id: EventId
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    event_digest: str
    kind: ClassVar[EditorialRelationEvidenceKind] = (
        EditorialRelationEvidenceKind.WORKFLOW_EVENT
    )

    def __post_init__(self) -> None:
        _require_typed(self.authority_event_id, EventId, field="authority_event_id")
        bounded_token(self.aggregate_type, field="aggregate_type")
        bounded_token(self.aggregate_id, field="aggregate_id")
        bounded_int(
            self.aggregate_version,
            field="aggregate_version",
            minimum=1,
            maximum=2**63 - 1,
        )
        canonical_digest(self.event_digest, field="event_digest")

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "authority_event_id": str(self.authority_event_id),
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version,
            "event_digest": self.event_digest,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


EditorialRelationEvidence: TypeAlias = ExtractionRelationEvidence | WorkflowRelationEvidence


def evidence_canonical_value(value: EditorialRelationEvidence) -> dict[str, object]:
    if not isinstance(value, (ExtractionRelationEvidence, WorkflowRelationEvidence)):
        raise EditorialRelationContractError("relation evidence must be typed")
    return value.canonical_value()


def require_sorted_evidence(
    values: tuple[EditorialRelationEvidence, ...],
) -> tuple[EditorialRelationEvidence, ...]:
    if not isinstance(values, tuple) or not values:
        raise EditorialRelationContractError(
            "relation evidence must be a non-empty immutable tuple"
        )
    if len(values) > 128:
        raise EditorialRelationContractError("relation evidence exceeds its bound")
    if any(
        not isinstance(item, (ExtractionRelationEvidence, WorkflowRelationEvidence))
        for item in values
    ):
        raise EditorialRelationContractError("relation evidence must be typed")
    keys = tuple(item.canonical_bytes for item in values)
    if keys != tuple(sorted(set(keys))):
        raise EditorialRelationContractError(
            "relation evidence must be sorted by canonical bytes and unique"
        )
    return values


@dataclass(frozen=True, slots=True)
class EditorialRelationProducer:
    kind: EditorialRelationProducerKind
    producer_id: str
    producer_version: str
    contract_digest: str

    def __post_init__(self) -> None:
        _require_typed(
            self.kind,
            EditorialRelationProducerKind,
            field="producer_kind",
        )
        bounded_token(self.producer_id, field="producer_id")
        bounded_token(self.producer_version, field="producer_version")
        canonical_digest(self.contract_digest, field="producer_contract_digest")

    def canonical_value(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True, slots=True)
class EditorialRelationProposalRequest:
    proposal_id: EditorialRelationProposalId
    proposal_version_id: EditorialRelationProposalVersionId
    version_number: int
    expected_previous_version_id: EditorialRelationProposalVersionId | None
    predicate_registry_digest: str
    predicate_contract_digest: str
    predicate: EditorialPredicateCode
    subject: EditorialRelationEndpoint
    object: EditorialRelationEndpoint
    temporal_scope: EditorialRelationTemporalScope
    evidence: tuple[EditorialRelationEvidence, ...]
    resolution_dependency_ids: tuple[EntityResolutionDependencyId, ...]
    producer: EditorialRelationProducer
    statement: str = field(repr=False)
    confidence_basis_points: int | None = None
    uncertainty_codes: tuple[str, ...] = ()
    basis_codes: tuple[str, ...] = ()
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        _require_typed(
            self.proposal_id,
            EditorialRelationProposalId,
            field="proposal_id",
        )
        _require_typed(
            self.proposal_version_id,
            EditorialRelationProposalVersionId,
            field="proposal_version_id",
        )
        bounded_int(
            self.version_number,
            field="proposal_version_number",
            minimum=1,
            maximum=2**31 - 1,
        )
        if self.version_number == 1:
            if self.expected_previous_version_id is not None:
                raise EditorialRelationContractError(
                    "proposal version one cannot name a predecessor"
                )
        else:
            _require_typed(
                self.expected_previous_version_id,
                EditorialRelationProposalVersionId,
                field="expected_previous_version_id",
            )
        canonical_digest(
            self.predicate_registry_digest,
            field="predicate_registry_digest",
        )
        canonical_digest(
            self.predicate_contract_digest,
            field="predicate_contract_digest",
        )
        _require_typed(self.predicate, EditorialPredicateCode, field="predicate")
        contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(self.predicate)
        if self.predicate_registry_digest != EDITORIAL_PREDICATE_REGISTRY_V1.digest:
            raise EditorialRelationContractError(
                "proposal registry digest differs from the approved registry"
            )
        if self.predicate_contract_digest != contract.digest:
            raise EditorialRelationContractError(
                "proposal predicate digest differs from the approved contract"
            )
        subject_kind = endpoint_kind(self.subject)
        object_kind = endpoint_kind(self.object)
        if not contract.allows(subject_kind, object_kind):
            raise EditorialRelationContractError(
                "predicate does not allow the supplied endpoint pair"
            )
        if endpoint_canonical_bytes(self.subject) == endpoint_canonical_bytes(self.object):
            raise EditorialRelationContractError("relation endpoints must differ")
        if (
            contract.directionality is EditorialPredicateDirectionality.SYMMETRIC
            and endpoint_canonical_bytes(self.subject)
            > endpoint_canonical_bytes(self.object)
        ):
            raise EditorialRelationContractError(
                "symmetric relation endpoints must use canonical order"
            )
        _require_typed(
            self.temporal_scope,
            EditorialRelationTemporalScope,
            field="temporal_scope",
        )
        self.temporal_scope.require_contract(contract)
        require_sorted_evidence(self.evidence)
        sorted_id_tuple(
            self.resolution_dependency_ids,
            EntityResolutionDependencyId,
            field="resolution_dependency_ids",
            allow_empty=True,
        )
        _require_typed(
            self.producer,
            EditorialRelationProducer,
            field="producer",
        )
        bounded_text(self.statement, field="relation_statement", maximum_bytes=8192)
        if self.confidence_basis_points is not None:
            bounded_int(
                self.confidence_basis_points,
                field="confidence_basis_points",
                minimum=0,
                maximum=10_000,
            )
        sorted_text_tuple(
            self.uncertainty_codes,
            field="uncertainty_codes",
            allow_empty=True,
        )
        sorted_text_tuple(
            self.basis_codes,
            field="basis_codes",
            allow_empty=False,
        )
        bounded_token(self.idempotency_key, field="idempotency_key")
        if (
            self.producer.kind is EditorialRelationProducerKind.EXTRACTION_RUN
            and not any(isinstance(item, ExtractionRelationEvidence) for item in self.evidence)
        ):
            raise EditorialRelationContractError(
                "extraction producer requires exact extraction evidence"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "proposal_version_id": str(self.proposal_version_id),
            "version_number": self.version_number,
            "expected_previous_version_id": (
                str(self.expected_previous_version_id)
                if self.expected_previous_version_id
                else None
            ),
            "predicate_registry_digest": self.predicate_registry_digest,
            "predicate_contract_digest": self.predicate_contract_digest,
            "predicate": self.predicate.value,
            "subject": endpoint_canonical_value(self.subject),
            "object": endpoint_canonical_value(self.object),
            "temporal_scope": self.temporal_scope.canonical_value(),
            "evidence": [evidence_canonical_value(item) for item in self.evidence],
            "resolution_dependency_ids": [
                str(item) for item in self.resolution_dependency_ids
            ],
            "producer": self.producer.canonical_value(),
            "statement": self.statement,
            "confidence_basis_points": self.confidence_basis_points,
            "uncertainty_codes": list(self.uncertainty_codes),
            "basis_codes": list(self.basis_codes),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_slot_digest(self) -> str:
        return digest_canonical(
            {
                "predicate_registry_digest": self.predicate_registry_digest,
                "predicate_contract_digest": self.predicate_contract_digest,
                "predicate": self.predicate.value,
                "subject": endpoint_canonical_value(self.subject),
                "object": endpoint_canonical_value(self.object),
                "valid_from": (
                    self.temporal_scope.valid_from.to_text()
                    if self.temporal_scope.valid_from
                    else None
                ),
                "valid_until": (
                    self.temporal_scope.valid_until.to_text()
                    if self.temporal_scope.valid_until
                    else None
                ),
            }
        )

    @property
    def stable_semantic_digest(self) -> str:
        return digest_canonical(
            {
                "semantic_slot_digest": self.semantic_slot_digest,
                "producer": self.producer.canonical_value(),
            }
        )


@dataclass(frozen=True, slots=True)
class EditorialRelationProposal:
    proposal_id: EditorialRelationProposalId
    predicate_registry_digest: str
    predicate_contract_digest: str
    predicate: EditorialPredicateCode
    subject: EditorialRelationEndpoint
    object: EditorialRelationEndpoint
    producer: EditorialRelationProducer
    semantic_slot_digest: str
    stable_semantic_digest: str
    canonical_digest: str
    created_by_event_id: EventId
    created_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class EditorialRelationProposalVersion:
    proposal_version_id: EditorialRelationProposalVersionId
    proposal_id: EditorialRelationProposalId
    version_number: int
    previous_proposal_version_id: EditorialRelationProposalVersionId | None
    temporal_scope: EditorialRelationTemporalScope
    evidence: tuple[EditorialRelationEvidence, ...]
    resolution_dependency_ids: tuple[EntityResolutionDependencyId, ...]
    statement: str = field(repr=False)
    confidence_basis_points: int | None = None
    uncertainty_codes: tuple[str, ...] = ()
    basis_codes: tuple[str, ...] = ()
    request_digest: str = ""
    canonical_digest: str = ""
    authority_event_id: EventId | None = None
    authority_ledger_seq: int = 0
    recorded_at: UtcTimestamp | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class EditorialRelationDecisionRequest:
    decision_id: EditorialRelationDecisionId
    action: EditorialRelationDecisionAction
    proposal_id: EditorialRelationProposalId
    proposal_version_id: EditorialRelationProposalVersionId
    expected_proposal_version_digest: str
    expected_previous_decision_id: EditorialRelationDecisionId | None
    expected_previous_decision_version: int
    assertion_id: EditorialRelationAssertionId | None
    target_assertion_id: EditorialRelationAssertionId | None
    successor_assertion_id: EditorialRelationAssertionId | None
    supersession_id: EditorialRelationSupersessionId | None
    reason_code: str
    decision_policy_version: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_typed(self.decision_id, EditorialRelationDecisionId, field="decision_id")
        _require_typed(self.action, EditorialRelationDecisionAction, field="action")
        _require_typed(self.proposal_id, EditorialRelationProposalId, field="proposal_id")
        _require_typed(
            self.proposal_version_id,
            EditorialRelationProposalVersionId,
            field="proposal_version_id",
        )
        canonical_digest(
            self.expected_proposal_version_digest,
            field="expected_proposal_version_digest",
        )
        bounded_int(
            self.expected_previous_decision_version,
            field="expected_previous_decision_version",
            minimum=0,
            maximum=2**31 - 1,
        )
        if self.expected_previous_decision_version == 0:
            if self.expected_previous_decision_id is not None:
                raise EditorialRelationContractError(
                    "first decision cannot name a predecessor"
                )
        else:
            _require_typed(
                self.expected_previous_decision_id,
                EditorialRelationDecisionId,
                field="expected_previous_decision_id",
            )
        if self.action is EditorialRelationDecisionAction.ACCEPT:
            _require_typed(
                self.assertion_id,
                EditorialRelationAssertionId,
                field="assertion_id",
            )
            if any(
                item is not None
                for item in (
                    self.target_assertion_id,
                    self.successor_assertion_id,
                    self.supersession_id,
                )
            ):
                raise EditorialRelationContractError(
                    "accept decision cannot carry lifecycle assertion fields"
                )
        elif self.action in {
            EditorialRelationDecisionAction.REJECT,
            EditorialRelationDecisionAction.HOLD,
            EditorialRelationDecisionAction.UNRESOLVED,
        }:
            if any(
                item is not None
                for item in (
                    self.assertion_id,
                    self.target_assertion_id,
                    self.successor_assertion_id,
                    self.supersession_id,
                )
            ):
                raise EditorialRelationContractError(
                    "non-admission decision cannot carry assertion fields"
                )
        elif self.action in {
            EditorialRelationDecisionAction.INVALIDATE,
            EditorialRelationDecisionAction.REVOKE,
        }:
            _require_typed(
                self.target_assertion_id,
                EditorialRelationAssertionId,
                field="target_assertion_id",
            )
            if any(
                item is not None
                for item in (
                    self.assertion_id,
                    self.successor_assertion_id,
                    self.supersession_id,
                )
            ):
                raise EditorialRelationContractError(
                    "invalidate/revoke decision has incompatible assertion fields"
                )
        elif self.action is EditorialRelationDecisionAction.SUPERSEDE:
            _require_typed(
                self.target_assertion_id,
                EditorialRelationAssertionId,
                field="target_assertion_id",
            )
            _require_typed(
                self.successor_assertion_id,
                EditorialRelationAssertionId,
                field="successor_assertion_id",
            )
            _require_typed(
                self.supersession_id,
                EditorialRelationSupersessionId,
                field="supersession_id",
            )
            if self.assertion_id is not None:
                raise EditorialRelationContractError(
                    "supersede decision cannot allocate a new assertion"
                )
            if self.target_assertion_id == self.successor_assertion_id:
                raise EditorialRelationContractError(
                    "supersession target and successor must differ"
                )
        bounded_token(self.reason_code, field="decision_reason_code")
        bounded_token(
            self.decision_policy_version,
            field="decision_policy_version",
        )
        if self.decision_policy_version != EDITORIAL_RELATION_ADMISSION_POLICY_VERSION:
            raise EditorialRelationContractError(
                "decision policy version differs from the approved admission policy"
            )
        bounded_token(self.idempotency_key, field="idempotency_key")

    def canonical_value(self) -> dict[str, object]:
        return {
            "decision_id": str(self.decision_id),
            "action": self.action.value,
            "proposal_id": str(self.proposal_id),
            "proposal_version_id": str(self.proposal_version_id),
            "expected_proposal_version_digest": (
                self.expected_proposal_version_digest
            ),
            "expected_previous_decision_id": (
                str(self.expected_previous_decision_id)
                if self.expected_previous_decision_id
                else None
            ),
            "expected_previous_decision_version": (
                self.expected_previous_decision_version
            ),
            "assertion_id": str(self.assertion_id) if self.assertion_id else None,
            "target_assertion_id": (
                str(self.target_assertion_id) if self.target_assertion_id else None
            ),
            "successor_assertion_id": (
                str(self.successor_assertion_id)
                if self.successor_assertion_id
                else None
            ),
            "supersession_id": (
                str(self.supersession_id) if self.supersession_id else None
            ),
            "reason_code": self.reason_code,
            "decision_policy_version": self.decision_policy_version,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


_DECISION_STATE = {
    EditorialRelationDecisionAction.ACCEPT: EditorialRelationCurrentState.ADMITTED,
    EditorialRelationDecisionAction.REJECT: EditorialRelationCurrentState.REJECTED,
    EditorialRelationDecisionAction.HOLD: EditorialRelationCurrentState.HELD,
    EditorialRelationDecisionAction.UNRESOLVED: EditorialRelationCurrentState.UNRESOLVED,
    EditorialRelationDecisionAction.INVALIDATE: EditorialRelationCurrentState.INVALIDATED,
    EditorialRelationDecisionAction.REVOKE: EditorialRelationCurrentState.REVOKED,
    EditorialRelationDecisionAction.SUPERSEDE: EditorialRelationCurrentState.SUPERSEDED,
}


@dataclass(frozen=True, slots=True)
class EditorialRelationDecision:
    decision_id: EditorialRelationDecisionId
    action: EditorialRelationDecisionAction
    proposal_id: EditorialRelationProposalId
    proposal_version_id: EditorialRelationProposalVersionId
    proposal_version_digest: str
    decision_version: int
    previous_decision_id: EditorialRelationDecisionId | None
    assertion_id: EditorialRelationAssertionId | None
    target_assertion_id: EditorialRelationAssertionId | None
    successor_assertion_id: EditorialRelationAssertionId | None
    supersession_id: EditorialRelationSupersessionId | None
    reason_code: str
    decision_policy_version: str
    authority_event_id: EventId
    authority_ledger_seq: int
    canonical_digest: str
    recorded_at: UtcTimestamp
    replayed: bool = False

    @property
    def current_state(self) -> EditorialRelationCurrentState:
        return _DECISION_STATE[self.action]


@dataclass(frozen=True, slots=True)
class EditorialRelationAssertion:
    assertion_id: EditorialRelationAssertionId
    proposal_id: EditorialRelationProposalId
    proposal_version_id: EditorialRelationProposalVersionId
    predicate_registry_digest: str
    predicate_contract_digest: str
    predicate: EditorialPredicateCode
    subject: EditorialRelationEndpoint
    object: EditorialRelationEndpoint
    temporal_scope: EditorialRelationTemporalScope
    evidence: tuple[EditorialRelationEvidence, ...]
    resolution_dependency_ids: tuple[EntityResolutionDependencyId, ...]
    producer: EditorialRelationProducer
    statement: str = field(repr=False)
    uncertainty_codes: tuple[str, ...] = ()
    trust_scope: TrustScope = TrustScope.ADMITTED
    admission_decision_id: EditorialRelationDecisionId | None = None
    admitted_at: UtcTimestamp | None = None
    canonical_digest: str = ""

    def __post_init__(self) -> None:
        _require_typed(
            self.assertion_id,
            EditorialRelationAssertionId,
            field="assertion_id",
        )
        if self.trust_scope is not TrustScope.ADMITTED:
            raise EditorialRelationContractError(
                "relation assertion trust scope must be ADMITTED"
            )
        require_sorted_evidence(self.evidence)
        sorted_id_tuple(
            self.resolution_dependency_ids,
            EntityResolutionDependencyId,
            field="resolution_dependency_ids",
            allow_empty=True,
        )
        bounded_text(self.statement, field="relation_statement", maximum_bytes=8192)
        sorted_text_tuple(
            self.uncertainty_codes,
            field="assertion_uncertainty_codes",
            allow_empty=True,
        )

    @property
    def relation_key(self) -> str:
        return digest_canonical(
            {
                "predicate_registry_digest": self.predicate_registry_digest,
                "predicate_contract_digest": self.predicate_contract_digest,
                "predicate": self.predicate.value,
                "subject": endpoint_canonical_value(self.subject),
                "object": endpoint_canonical_value(self.object),
                "valid_from": (
                    self.temporal_scope.valid_from.to_text()
                    if self.temporal_scope.valid_from
                    else None
                ),
                "valid_until": (
                    self.temporal_scope.valid_until.to_text()
                    if self.temporal_scope.valid_until
                    else None
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class EditorialRelationCurrentView:
    assertion: EditorialRelationAssertion
    lifecycle: EditorialRelationAssertionLifecycle
    current_decision_id: EditorialRelationDecisionId
    current_decision_version: int
    updated_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class EditorialRelationProjectionEvent:
    projection_event_id: EventId
    source_event_id: EventId
    source_ledger_seq: int
    action: EditorialRelationProjectionAction
    assertion_id: EditorialRelationAssertionId
    assertion: EditorialRelationAssertion | None
    lifecycle: EditorialRelationAssertionLifecycle
    canonical_digest: str
    recorded_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class EditorialRelationReadPolicy:
    policy_id: str
    purpose: str
    proposal_required_scope: str
    admitted_required_scope: str
    projection_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        bounded_token(self.policy_id, field="relation_read_policy_id")
        bounded_token(self.purpose, field="relation_read_purpose")
        for name, scope in (
            ("proposal_required_scope", self.proposal_required_scope),
            ("admitted_required_scope", self.admitted_required_scope),
            ("projection_required_scope", self.projection_required_scope),
        ):
            bounded_scope(scope, field=name)
        if len(
            {
                self.proposal_required_scope,
                self.admitted_required_scope,
                self.projection_required_scope,
            }
        ) != 3:
            raise EditorialRelationContractError(
                "relation proposal, admitted and projection reads require distinct scopes"
            )
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise EditorialRelationContractError(
                "relation read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            bounded_token(principal_id, field="relation_reader_principal")
        bounded_int(
            self.max_results,
            field="relation_read_max_results",
            minimum=1,
            maximum=10_000,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "purpose": self.purpose,
            "proposal_required_scope": self.proposal_required_scope,
            "admitted_required_scope": self.admitted_required_scope,
            "projection_required_scope": self.projection_required_scope,
            "allowed_principal_ids": sorted(self.allowed_principal_ids),
            "max_results": self.max_results,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_principal(self, principal_id: str) -> None:
        if principal_id not in self.allowed_principal_ids:
            raise PermissionError(
                "relation reader principal is outside the read policy"
            )

    def require_limit(self, limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self.max_results
        ):
            raise PermissionError("relation read limit exceeds the read policy")


__all__ = [
    "CanonicalEntityRelationEndpoint",
    "EDITORIAL_PREDICATE_REGISTRY_V1",
    "EditorialPredicateContract",
    "EditorialPredicateEndpointPair",
    "EditorialPredicateRegistry",
    "EditorialRelationAssertion",
    "EditorialRelationCurrentView",
    "EditorialRelationDecision",
    "EditorialRelationDecisionRequest",
    "EditorialRelationEndpoint",
    "EditorialRelationEvidence",
    "EditorialRelationProducer",
    "EditorialRelationProjectionEvent",
    "EditorialRelationProposal",
    "EditorialRelationProposalRequest",
    "EditorialRelationProposalVersion",
    "EditorialRelationReadPolicy",
    "EditorialRelationTemporalScope",
    "EventHypothesisRelationEndpoint",
    "ExtractionRelationEvidence",
    "RelationAssertionRelationEndpoint",
    "SourceRevisionRelationEndpoint",
    "StoryCandidateRelationEndpoint",
    "endpoint_canonical_bytes",
    "endpoint_canonical_value",
    "endpoint_kind",
    "evidence_canonical_value",
    "require_sorted_evidence",
]
