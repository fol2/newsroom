from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.types import (
    EventId,
    ObjectAdmissionId,
    UtcTimestamp,
)
from newsroom.sources import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from .types import (
    EvidenceRange,
    ExtractionBudget,
    ExtractionContractError,
    ExtractionExecutionProfile,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputId,
    ExtractionOutputValidation,
    ExtractionPassageId,
    ExtractionProposalKind,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractionUsage,
    ExtractorContractId,
    ProposalEnvelopeId,
    ProposalPredicateHint,
    ProposalSetId,
    VersionedExtractionComponent,
    bounded_int,
    bounded_text,
    bounded_token,
    authority_elapsed_ms,
    canonical_digest,
    sorted_text_tuple,
)


@dataclass(frozen=True, slots=True)
class ExtractorContractRequest:
    contract_id: ExtractorContractId
    framework: VersionedExtractionComponent
    model: VersionedExtractionComponent
    prompt: VersionedExtractionComponent
    output_schema: VersionedExtractionComponent
    code: VersionedExtractionComponent
    normalisation: VersionedExtractionComponent
    policy: VersionedExtractionComponent
    execution_profile: ExtractionExecutionProfile
    producer_kind: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.contract_id, ExtractorContractId):
            raise ExtractionContractError("extractor contract identity must be typed")
        for field_name in (
            "framework",
            "model",
            "prompt",
            "output_schema",
            "code",
            "normalisation",
            "policy",
        ):
            if not isinstance(
                getattr(self, field_name), VersionedExtractionComponent
            ):
                raise ExtractionContractError(
                    f"{field_name} component must be typed"
                )
        if not isinstance(self.execution_profile, ExtractionExecutionProfile):
            raise ExtractionContractError("execution profile must be typed")
        bounded_token(self.producer_kind, field="extraction_producer_kind")
        bounded_text(
            self.idempotency_key,
            field="idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract_id": str(self.contract_id),
            "framework": self.framework.canonical_value(),
            "model": self.model.canonical_value(),
            "prompt": self.prompt.canonical_value(),
            "output_schema": self.output_schema.canonical_value(),
            "code": self.code.canonical_value(),
            "normalisation": self.normalisation.canonical_value(),
            "policy": self.policy.canonical_value(),
            "execution_profile": self.execution_profile.value,
            "producer_kind": self.producer_kind,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return digest_canonical(
            {
                key: value
                for key, value in self.canonical_value().items()
                if key != "contract_id"
            }
        )


@dataclass(frozen=True, slots=True)
class ExtractorContract:
    request: ExtractorContractRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExtractorContractRequest):
            raise ExtractionContractError("extractor contract request must be retained")
        if not isinstance(self.event_id, EventId):
            raise ExtractionContractError("extractor contract event must be typed")
        if self.aggregate_version != 1:
            raise ExtractionContractError("extractor contract is immutable version one")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise ExtractionContractError("contract recording time must be typed")
        canonical_digest(self.canonical_digest, field="extractor_contract_digest")
        if self.canonical_digest != self.request.digest:
            raise ExtractionContractError("retained extractor contract digest differs")
        if not isinstance(self.replayed, bool):
            raise ExtractionContractError("contract replay flag must be boolean")


@dataclass(frozen=True, slots=True)
class ExtractionPassageInput:
    passage_id: ExtractionPassageId
    admission_id: ObjectAdmissionId
    access_decision_id: ObjectAccessDecisionId
    hydration_policy_contract_digest: str
    principal_id: str
    authority_domain: str
    purpose: str
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    byte_offset: int
    byte_length: int
    blob_digest: str
    text_digest: str
    language: str
    text: str | None = field(repr=False, default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.passage_id, ExtractionPassageId):
            raise ExtractionContractError("extraction passage identity must be typed")
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise ExtractionContractError("passage admission identity must be typed")
        if not isinstance(self.access_decision_id, ObjectAccessDecisionId):
            raise ExtractionContractError("passage access decision must be typed")
        canonical_digest(
            self.hydration_policy_contract_digest,
            field="hydration_policy_contract_digest",
        )
        bounded_token(self.principal_id, field="passage_principal_id")
        bounded_token(self.authority_domain, field="passage_authority_domain")
        bounded_token(self.purpose, field="passage_purpose")
        bounded_token(self.object_class, field="passage_object_class")
        bounded_token(self.allowed_use, field="passage_allowed_use")
        bounded_text(
            self.security_scope,
            field="passage_security_scope",
            maximum_bytes=256,
        )
        bounded_text(
            self.retention_scope,
            field="passage_retention_scope",
            maximum_bytes=256,
        )
        bounded_int(
            self.byte_offset,
            field="passage_byte_offset",
            minimum=0,
            maximum=16 * 1024 * 1024,
        )
        bounded_int(
            self.byte_length,
            field="passage_byte_length",
            minimum=1,
            maximum=16 * 1024 * 1024,
        )
        canonical_digest(self.blob_digest, field="passage_blob_digest")
        canonical_digest(self.text_digest, field="passage_text_digest")
        if self.byte_offset != 0 or self.text_digest != self.blob_digest:
            raise ExtractionContractError(
                "fixture extraction passage must bind one complete admitted object"
            )
        bounded_text(self.language, field="passage_language", maximum_bytes=35)
        if self.text is not None:
            bounded_text(
                self.text,
                field="passage_text",
                maximum_bytes=16 * 1024 * 1024,
            )
            encoded = self.text.encode("utf-8")
            if self.byte_length != len(encoded):
                raise ExtractionContractError(
                    "fixture extraction passage length differs from governed bytes"
                )
            actual = digest_bytes(encoded)
            if actual != self.text_digest or actual != self.blob_digest:
                raise ExtractionContractError(
                    "fixture passage bytes must match the admitted blob identity"
                )

    def require_text(self) -> str:
        if self.text is None:
            raise ExtractionContractError(
                "retained passage metadata cannot be used as extractor input"
            )
        return self.text

    def canonical_value(self) -> dict[str, object]:
        return {
            "passage_id": str(self.passage_id),
            "admission_id": str(self.admission_id),
            "access_decision_id": str(self.access_decision_id),
            "hydration_policy_contract_digest": (
                self.hydration_policy_contract_digest
            ),
            "principal_id": self.principal_id,
            "authority_domain": self.authority_domain,
            "purpose": self.purpose,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "byte_offset": self.byte_offset,
            "byte_length": self.byte_length,
            "blob_digest": self.blob_digest,
            "text_digest": self.text_digest,
            "language": self.language,
        }


@dataclass(frozen=True, slots=True)
class ExtractionInputBinding:
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    item_id: SourceItemId
    revision_id: SourceRevisionId
    representation_id: DiscoveryRepresentationId
    passages: tuple[ExtractionPassageInput, ...]

    def __post_init__(self) -> None:
        for field_name, expected_type in (
            ("definition_id", SourceDefinitionId),
            ("definition_version_id", SourceDefinitionVersionId),
            ("item_id", SourceItemId),
            ("revision_id", SourceRevisionId),
            ("representation_id", DiscoveryRepresentationId),
        ):
            if not isinstance(getattr(self, field_name), expected_type):
                raise ExtractionContractError(f"{field_name} must be typed")
        if not isinstance(self.passages, tuple) or not self.passages:
            raise ExtractionContractError("extraction input needs retained passages")
        if len(self.passages) > 128:
            raise ExtractionContractError("extraction passage count exceeds 128")
        if any(not isinstance(item, ExtractionPassageInput) for item in self.passages):
            raise ExtractionContractError("extraction passages must be typed")
        expected = tuple(sorted(self.passages, key=lambda item: str(item.passage_id)))
        if self.passages != expected:
            raise ExtractionContractError("extraction passages must be sorted by identity")
        if len({item.passage_id for item in self.passages}) != len(self.passages):
            raise ExtractionContractError("extraction passage identities must be unique")
        if len({item.access_decision_id for item in self.passages}) != len(
            self.passages
        ):
            raise ExtractionContractError("access decisions cannot be reused as passages")

    def canonical_value(self) -> dict[str, object]:
        return {
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "item_id": str(self.item_id),
            "revision_id": str(self.revision_id),
            "representation_id": str(self.representation_id),
            "passages": [item.canonical_value() for item in self.passages],
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    @property
    def input_bytes(self) -> int:
        return sum(item.byte_length for item in self.passages)

    def passage(self, passage_id: ExtractionPassageId) -> ExtractionPassageInput:
        for passage in self.passages:
            if passage.passage_id == passage_id:
                return passage
        raise ExtractionContractError("proposal evidence names an unknown passage")


@dataclass(frozen=True, slots=True)
class ExtractionRunRequest:
    run_id: ExtractionRunId
    run_version_id: ExtractionRunVersionId
    version_number: int
    expected_previous_version_id: ExtractionRunVersionId | None
    contract_id: ExtractorContractId
    input_binding: ExtractionInputBinding
    budget: ExtractionBudget
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, ExtractionRunId):
            raise ExtractionContractError("extraction run identity must be typed")
        if not isinstance(self.run_version_id, ExtractionRunVersionId):
            raise ExtractionContractError("run version identity must be typed")
        bounded_int(
            self.version_number,
            field="extraction_run_version_number",
            minimum=1,
            maximum=1_000_000,
        )
        if self.expected_previous_version_id is not None and not isinstance(
            self.expected_previous_version_id, ExtractionRunVersionId
        ):
            raise ExtractionContractError("previous run version must be typed")
        if self.version_number == 1:
            if self.expected_previous_version_id is not None:
                raise ExtractionContractError(
                    "initial extraction version cannot name a predecessor"
                )
        elif self.expected_previous_version_id is None:
            raise ExtractionContractError(
                "later extraction version requires the exact predecessor"
            )
        if not isinstance(self.contract_id, ExtractorContractId):
            raise ExtractionContractError("extractor contract identity must be typed")
        if not isinstance(self.input_binding, ExtractionInputBinding):
            raise ExtractionContractError("extraction input binding must be typed")
        if not isinstance(self.budget, ExtractionBudget):
            raise ExtractionContractError("extraction budget must be typed")
        if self.input_binding.input_bytes > self.budget.max_input_bytes:
            raise ExtractionContractError("input bytes exceed the fixed extraction budget")
        bounded_text(
            self.idempotency_key,
            field="idempotency_key",
            maximum_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "run_version_id": str(self.run_version_id),
            "version_number": self.version_number,
            "expected_previous_version_id": (
                None
                if self.expected_previous_version_id is None
                else str(self.expected_previous_version_id)
            ),
            "contract_id": str(self.contract_id),
            "input_binding": self.input_binding.canonical_value(),
            "budget": self.budget.canonical_value(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def stable_run_semantic_digest(self) -> str:
        return digest_canonical(
            {
                "contract_id": str(self.contract_id),
                "input_binding": self.input_binding.canonical_value(),
                "budget": self.budget.canonical_value(),
            }
        )


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    local_id: str
    kind: ExtractionProposalKind
    subject_placeholder: str
    object_placeholder: str | None
    predicate_hint: ProposalPredicateHint | None
    confidence_basis_points: int | None
    uncertainty_codes: tuple[str, ...]
    rationale_codes: tuple[str, ...]
    evidence: tuple[EvidenceRange, ...]

    def __post_init__(self) -> None:
        bounded_token(self.local_id, field="proposal_local_id")
        if not isinstance(self.kind, ExtractionProposalKind):
            raise ExtractionContractError("proposal kind must be typed")
        bounded_text(
            self.subject_placeholder,
            field="proposal_subject_placeholder",
            maximum_bytes=4096,
        )
        if self.object_placeholder is not None:
            bounded_text(
                self.object_placeholder,
                field="proposal_object_placeholder",
                maximum_bytes=4096,
            )
        if self.predicate_hint is not None and not isinstance(
            self.predicate_hint, ProposalPredicateHint
        ):
            raise ExtractionContractError("proposal predicate hint must be typed")
        if self.kind is ExtractionProposalKind.ENTITY_MENTION:
            if self.object_placeholder is not None:
                raise ExtractionContractError(
                    "entity mention proposal cannot carry an object placeholder"
                )
        elif self.kind is ExtractionProposalKind.ENTITY_EQUIVALENCE:
            if self.object_placeholder is None:
                raise ExtractionContractError(
                    "entity equivalence proposal needs two placeholders"
                )
        elif self.kind is ExtractionProposalKind.RELATION:
            if self.object_placeholder is None or self.predicate_hint is None:
                raise ExtractionContractError(
                    "relation proposal needs object and predicate placeholders"
                )
        if (
            self.kind is not ExtractionProposalKind.RELATION
            and self.predicate_hint is not None
        ):
            raise ExtractionContractError(
                "only relation proposals can carry predicate hints"
            )
        if self.confidence_basis_points is not None:
            bounded_int(
                self.confidence_basis_points,
                field="proposal_confidence_basis_points",
                minimum=0,
                maximum=10_000,
            )
        normalized_uncertainty = sorted_text_tuple(
            self.uncertainty_codes,
            field="proposal_uncertainty_codes",
            maximum_items=32,
        )
        normalized_rationale = sorted_text_tuple(
            self.rationale_codes,
            field="proposal_rationale_codes",
            maximum_items=32,
        )
        if normalized_uncertainty != self.uncertainty_codes:
            raise ExtractionContractError(
                "proposal uncertainty codes must be sorted and unique"
            )
        if normalized_rationale != self.rationale_codes:
            raise ExtractionContractError(
                "proposal rationale codes must be sorted and unique"
            )
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ExtractionContractError("proposal needs exact passage evidence")
        if any(not isinstance(item, EvidenceRange) for item in self.evidence):
            raise ExtractionContractError("proposal evidence must be typed")
        expected_evidence = tuple(
            sorted(
                self.evidence,
                key=lambda item: (
                    str(item.passage_id),
                    item.start_byte,
                    item.end_byte,
                ),
            )
        )
        if self.evidence != expected_evidence:
            raise ExtractionContractError("proposal evidence must be sorted")
        identities = {
            (item.passage_id, item.start_byte, item.end_byte)
            for item in self.evidence
        }
        if len(identities) != len(self.evidence):
            raise ExtractionContractError("proposal evidence ranges must be unique")

    def canonical_value(self) -> dict[str, object]:
        return {
            "local_id": self.local_id,
            "kind": self.kind.value,
            "subject_placeholder": self.subject_placeholder,
            "object_placeholder": self.object_placeholder,
            "predicate_hint": (
                None if self.predicate_hint is None else self.predicate_hint.value
            ),
            "confidence_basis_points": self.confidence_basis_points,
            "uncertainty_codes": list(self.uncertainty_codes),
            "rationale_codes": list(self.rationale_codes),
            "evidence": [item.canonical_value() for item in self.evidence],
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


_ALLOWED_FAILURE_CODES_BY_OUTCOME: dict[
    ExtractionOutcome, frozenset[ExtractionFailureCode]
] = {
    ExtractionOutcome.SUCCESS: frozenset({ExtractionFailureCode.NONE}),
    ExtractionOutcome.PARTIAL: frozenset({ExtractionFailureCode.FIXTURE_PARTIAL}),
    ExtractionOutcome.RETRYABLE_FAILURE: frozenset(
        {
            ExtractionFailureCode.FIXTURE_RETRYABLE,
            ExtractionFailureCode.PRODUCER_INTERNAL_ERROR,
            ExtractionFailureCode.EXECUTION_TIMEOUT,
        }
    ),
    ExtractionOutcome.BLOCKING_FAILURE: frozenset(
        {
            ExtractionFailureCode.FIXTURE_BLOCKED,
            ExtractionFailureCode.POLICY_BLOCKED,
        }
    ),
    ExtractionOutcome.INVALID_OUTPUT: frozenset(
        {ExtractionFailureCode.OUTPUT_SCHEMA_INVALID}
    ),
}


def _require_outcome_failure_code(
    outcome: ExtractionOutcome, failure_code: ExtractionFailureCode
) -> None:
    allowed = _ALLOWED_FAILURE_CODES_BY_OUTCOME[outcome]
    if failure_code not in allowed:
        raise ExtractionContractError(
            "extraction failure code is incompatible with its outcome"
        )


@dataclass(frozen=True, slots=True)
class ProducedExtraction:
    outcome: ExtractionOutcome
    failure_code: ExtractionFailureCode
    validation: ExtractionOutputValidation | None
    raw_output_value: dict[str, Any] | None
    proposals: tuple[ProposalDraft, ...]
    usage: ExtractionUsage

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ExtractionOutcome):
            raise ExtractionContractError("extraction outcome must be typed")
        if not isinstance(self.failure_code, ExtractionFailureCode):
            raise ExtractionContractError("extraction failure code must be typed")
        _require_outcome_failure_code(self.outcome, self.failure_code)
        if not isinstance(self.usage, ExtractionUsage):
            raise ExtractionContractError("extraction usage must be typed")
        if self.raw_output_value is None:
            if self.validation is not None:
                raise ExtractionContractError(
                    "output validation cannot exist without retained output"
                )
            if self.outcome.may_retain_output:
                raise ExtractionContractError(
                    "complete, partial, or invalid outcome requires retained output"
                )
        else:
            if not isinstance(self.raw_output_value, dict):
                raise ExtractionContractError(
                    "retained structured output must be a canonical object"
                )
            raw = canonical_json_bytes(self.raw_output_value)
            if not raw:
                raise ExtractionContractError("retained structured output is empty")
            if not self.outcome.may_retain_output:
                raise ExtractionContractError(
                    "failure outcome cannot retain structured output"
                )
            if not isinstance(self.validation, ExtractionOutputValidation):
                raise ExtractionContractError("retained output needs validation state")
        if not isinstance(self.proposals, tuple) or any(
            not isinstance(item, ProposalDraft) for item in self.proposals
        ):
            raise ExtractionContractError("produced proposals must be typed")
        expected = tuple(sorted(self.proposals, key=lambda item: item.local_id))
        if self.proposals != expected:
            raise ExtractionContractError("produced proposals must be sorted")
        if len({item.local_id for item in self.proposals}) != len(self.proposals):
            raise ExtractionContractError("proposal local identities must be unique")
        if self.proposals and not self.outcome.may_retain_proposals:
            raise ExtractionContractError(
                "failed or invalid extraction cannot create proposal authority"
            )
        if self.proposals and self.validation is not ExtractionOutputValidation.VALID:
            raise ExtractionContractError("proposals require valid structured output")
        if self.outcome is ExtractionOutcome.SUCCESS and not self.proposals:
            raise ExtractionContractError("successful fixture extraction needs proposals")
        if self.outcome is ExtractionOutcome.INVALID_OUTPUT:
            if self.validation is not ExtractionOutputValidation.INVALID:
                raise ExtractionContractError("invalid outcome needs INVALID validation")
            if self.failure_code is not ExtractionFailureCode.OUTPUT_SCHEMA_INVALID:
                raise ExtractionContractError("invalid output needs schema failure code")
        if self.outcome is ExtractionOutcome.SUCCESS:
            if self.failure_code is not ExtractionFailureCode.NONE:
                raise ExtractionContractError("successful extraction has no failure code")
        elif self.failure_code is ExtractionFailureCode.NONE:
            raise ExtractionContractError("non-success outcome needs a failure code")
        actual_output_bytes = len(self.raw_output_bytes or b"")
        actual_evidence = sum(len(item.evidence) for item in self.proposals)
        if (
            self.usage.output_bytes != actual_output_bytes
            or self.usage.proposal_count != len(self.proposals)
            or self.usage.evidence_range_count != actual_evidence
        ):
            raise ExtractionContractError(
                "reported usage differs from deterministic produced content"
            )

    @property
    def raw_output_bytes(self) -> bytes | None:
        if self.raw_output_value is None:
            return None
        return canonical_json_bytes(self.raw_output_value)

    @property
    def raw_output_digest(self) -> str | None:
        value = self.raw_output_bytes
        return None if value is None else digest_bytes(value)


class ProposalProducer(Protocol):
    producer_kind: str

    def produce(
        self,
        *,
        contract: ExtractorContractRequest,
        request: ExtractionRunRequest,
    ) -> ProducedExtraction: ...


@dataclass(frozen=True, slots=True)
class ExtractionOutputView:
    output_id: ExtractionOutputId
    run_id: ExtractionRunId
    run_version_id: ExtractionRunVersionId
    validation: ExtractionOutputValidation
    schema_contract_digest: str
    byte_length: int
    canonical_digest: str
    retained_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.output_id, ExtractionOutputId):
            raise ExtractionContractError("output identity must be typed")
        if not isinstance(self.run_id, ExtractionRunId):
            raise ExtractionContractError("output run identity must be typed")
        if not isinstance(self.run_version_id, ExtractionRunVersionId):
            raise ExtractionContractError("output run version must be typed")
        if not isinstance(self.validation, ExtractionOutputValidation):
            raise ExtractionContractError("output validation must be typed")
        canonical_digest(
            self.schema_contract_digest, field="output_schema_contract_digest"
        )
        bounded_int(
            self.byte_length,
            field="output_byte_length",
            minimum=1,
            maximum=4 * 1024 * 1024,
        )
        canonical_digest(self.canonical_digest, field="output_canonical_digest")
        if not isinstance(self.retained_at, UtcTimestamp):
            raise ExtractionContractError("output retention time must be typed")


@dataclass(frozen=True, slots=True)
class ExtractionRawOutput:
    view: ExtractionOutputView
    canonical_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.view, ExtractionOutputView):
            raise ExtractionContractError("raw output needs typed metadata")
        if not isinstance(self.canonical_bytes, bytes):
            raise ExtractionContractError("raw output must be immutable bytes")
        if (
            len(self.canonical_bytes) != self.view.byte_length
            or digest_bytes(self.canonical_bytes) != self.view.canonical_digest
        ):
            raise ExtractionContractError("raw output bytes differ from metadata")


@dataclass(frozen=True, slots=True)
class ProposalEnvelope:
    proposal_id: ProposalEnvelopeId
    proposal_set_id: ProposalSetId
    output_id: ExtractionOutputId
    run_id: ExtractionRunId
    run_version_id: ExtractionRunVersionId
    local_id: str
    kind: ExtractionProposalKind
    subject_placeholder: str
    object_placeholder: str | None
    predicate_hint: ProposalPredicateHint | None
    confidence_basis_points: int | None
    uncertainty_codes: tuple[str, ...]
    rationale_codes: tuple[str, ...]
    evidence: tuple[EvidenceRange, ...]
    producer_contract_digest: str
    canonical_digest: str
    retained_at: UtcTimestamp

    def __post_init__(self) -> None:
        for field_name, expected_type in (
            ("proposal_id", ProposalEnvelopeId),
            ("proposal_set_id", ProposalSetId),
            ("output_id", ExtractionOutputId),
            ("run_id", ExtractionRunId),
            ("run_version_id", ExtractionRunVersionId),
        ):
            if not isinstance(getattr(self, field_name), expected_type):
                raise ExtractionContractError(f"{field_name} must be typed")
        draft = ProposalDraft(
            local_id=self.local_id,
            kind=self.kind,
            subject_placeholder=self.subject_placeholder,
            object_placeholder=self.object_placeholder,
            predicate_hint=self.predicate_hint,
            confidence_basis_points=self.confidence_basis_points,
            uncertainty_codes=self.uncertainty_codes,
            rationale_codes=self.rationale_codes,
            evidence=self.evidence,
        )
        canonical_digest(
            self.producer_contract_digest,
            field="proposal_producer_contract_digest",
        )
        canonical_digest(self.canonical_digest, field="proposal_canonical_digest")
        if not isinstance(self.retained_at, UtcTimestamp):
            raise ExtractionContractError("proposal retention time must be typed")
        expected_digest = digest_canonical(
            {
                "proposal_id": str(self.proposal_id),
                "proposal_set_id": str(self.proposal_set_id),
                "output_id": str(self.output_id),
                "run_id": str(self.run_id),
                "run_version_id": str(self.run_version_id),
                "draft": draft.canonical_value(),
                "producer_contract_digest": self.producer_contract_digest,
            }
        )
        if self.canonical_digest != expected_digest:
            raise ExtractionContractError("proposal envelope digest differs")


@dataclass(frozen=True, slots=True)
class ProposalSet:
    proposal_set_id: ProposalSetId
    output_id: ExtractionOutputId
    run_id: ExtractionRunId
    run_version_id: ExtractionRunVersionId
    proposals: tuple[ProposalEnvelope, ...]
    producer_contract_digest: str
    canonical_digest: str
    retained_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_set_id, ProposalSetId):
            raise ExtractionContractError("proposal set identity must be typed")
        if not isinstance(self.output_id, ExtractionOutputId):
            raise ExtractionContractError("proposal set output must be typed")
        if not isinstance(self.run_id, ExtractionRunId):
            raise ExtractionContractError("proposal set run must be typed")
        if not isinstance(self.run_version_id, ExtractionRunVersionId):
            raise ExtractionContractError("proposal set version must be typed")
        if not isinstance(self.proposals, tuple) or not self.proposals:
            raise ExtractionContractError("proposal set cannot be empty")
        if any(not isinstance(item, ProposalEnvelope) for item in self.proposals):
            raise ExtractionContractError("proposal set entries must be typed")
        expected = tuple(sorted(self.proposals, key=lambda item: item.local_id))
        if self.proposals != expected:
            raise ExtractionContractError("proposal set must be sorted")
        if any(
            item.proposal_set_id != self.proposal_set_id
            or item.output_id != self.output_id
            or item.run_id != self.run_id
            or item.run_version_id != self.run_version_id
            for item in self.proposals
        ):
            raise ExtractionContractError("proposal set lineage differs")
        canonical_digest(
            self.producer_contract_digest,
            field="proposal_set_producer_contract_digest",
        )
        if any(
            item.producer_contract_digest != self.producer_contract_digest
            for item in self.proposals
        ):
            raise ExtractionContractError("proposal producer contract differs")
        canonical_digest(self.canonical_digest, field="proposal_set_digest")
        expected_digest = digest_canonical(
            {
                "proposal_set_id": str(self.proposal_set_id),
                "output_id": str(self.output_id),
                "run_id": str(self.run_id),
                "run_version_id": str(self.run_version_id),
                "producer_contract_digest": self.producer_contract_digest,
                "proposal_digests": [
                    item.canonical_digest for item in self.proposals
                ],
            }
        )
        if self.canonical_digest != expected_digest:
            raise ExtractionContractError("proposal set digest differs")
        if not isinstance(self.retained_at, UtcTimestamp):
            raise ExtractionContractError("proposal set retention time must be typed")
        if any(item.retained_at != self.retained_at for item in self.proposals):
            raise ExtractionContractError("proposal retention chronology differs")


@dataclass(frozen=True, slots=True)
class ExtractionRunVersion:
    request: ExtractionRunRequest
    contract_canonical_digest: str
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    started_at: UtcTimestamp
    ended_at: UtcTimestamp
    outcome: ExtractionOutcome
    failure_code: ExtractionFailureCode
    usage: ExtractionUsage
    output: ExtractionOutputView | None
    proposal_set: ProposalSet | None
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExtractionRunRequest):
            raise ExtractionContractError("run request must be retained")
        canonical_digest(
            self.contract_canonical_digest,
            field="run_version_contract_canonical_digest",
        )
        if not isinstance(self.event_id, EventId):
            raise ExtractionContractError("run event must be typed")
        if self.aggregate_version != 1:
            raise ExtractionContractError("run-version authority is immutable")
        for field_name in ("recorded_at", "started_at", "ended_at"):
            if not isinstance(getattr(self, field_name), UtcTimestamp):
                raise ExtractionContractError(f"{field_name} must be typed")
        if self.ended_at.value < self.started_at.value:
            raise ExtractionContractError("extraction cannot end before it starts")
        if self.recorded_at.value < self.ended_at.value:
            raise ExtractionContractError("extraction must be retained after completion")
        if not isinstance(self.outcome, ExtractionOutcome):
            raise ExtractionContractError("run outcome must be typed")
        if not isinstance(self.failure_code, ExtractionFailureCode):
            raise ExtractionContractError("run failure code must be typed")
        _require_outcome_failure_code(self.outcome, self.failure_code)
        if not isinstance(self.usage, ExtractionUsage):
            raise ExtractionContractError("run usage must be typed")
        self.usage.require_within(
            self.request.budget,
            allow_elapsed_timeout=(
                self.failure_code is ExtractionFailureCode.EXECUTION_TIMEOUT
            ),
        )
        if self.output is None:
            if self.outcome.may_retain_output:
                raise ExtractionContractError("run outcome requires retained output")
            if self.proposal_set is not None:
                raise ExtractionContractError("proposal set requires retained output")
        else:
            if (
                self.output.run_id != self.request.run_id
                or self.output.run_version_id != self.request.run_version_id
            ):
                raise ExtractionContractError("output lineage differs from run")
            if self.output.retained_at != self.recorded_at:
                raise ExtractionContractError("output retention chronology differs")
            expected_validation = (
                ExtractionOutputValidation.INVALID
                if self.outcome is ExtractionOutcome.INVALID_OUTPUT
                else ExtractionOutputValidation.VALID
            )
            if self.output.validation is not expected_validation:
                raise ExtractionContractError(
                    "output validation differs from run outcome"
                )
        if self.proposal_set is not None:
            if self.output is None:
                raise ExtractionContractError("proposal set requires output")
            if (
                self.proposal_set.run_id != self.request.run_id
                or self.proposal_set.run_version_id
                != self.request.run_version_id
                or self.proposal_set.output_id != self.output.output_id
            ):
                raise ExtractionContractError("proposal-set lineage differs from run")
            if self.proposal_set.retained_at != self.recorded_at:
                raise ExtractionContractError(
                    "proposal-set retention chronology differs"
                )
        if self.outcome.may_retain_proposals != (self.proposal_set is not None):
            if not (
                self.outcome is ExtractionOutcome.PARTIAL
                and self.proposal_set is None
            ):
                raise ExtractionContractError("run proposal state differs from outcome")
        canonical_digest(self.canonical_digest, field="run_version_digest")
        expected_digest = digest_canonical(
            {
                "request": self.request.canonical_value(),
                "contract_canonical_digest": self.contract_canonical_digest,
                "outcome": self.outcome.value,
                "failure_code": self.failure_code.value,
                "started_at": self.started_at.to_text(),
                "ended_at": self.ended_at.to_text(),
                "usage": self.usage.canonical_value(),
            }
        )
        if self.canonical_digest != expected_digest:
            raise ExtractionContractError("run-version canonical digest differs")
        measured_elapsed_ms = authority_elapsed_ms(
            self.started_at,
            self.ended_at,
        )
        if self.usage.elapsed_ms != measured_elapsed_ms:
            raise ExtractionContractError(
                "run usage elapsed time differs from authority timestamps"
            )
        if not isinstance(self.replayed, bool):
            raise ExtractionContractError("run replay flag must be boolean")


@dataclass(frozen=True, slots=True)
class ExtractionRunMetadata:
    run_id: ExtractionRunId
    run_version_id: ExtractionRunVersionId
    version_number: int
    contract_id: ExtractorContractId
    input_binding_digest: str
    outcome: ExtractionOutcome
    failure_code: ExtractionFailureCode
    started_at: UtcTimestamp
    ended_at: UtcTimestamp
    recorded_at: UtcTimestamp
    usage: ExtractionUsage
    output: ExtractionOutputView | None
    proposal_count: int
    terminal: bool

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, ExtractionRunId):
            raise ExtractionContractError("metadata run identity must be typed")
        if not isinstance(self.run_version_id, ExtractionRunVersionId):
            raise ExtractionContractError("metadata run version must be typed")
        bounded_int(
            self.version_number,
            field="metadata_run_version",
            minimum=1,
            maximum=1_000_000,
        )
        if not isinstance(self.contract_id, ExtractorContractId):
            raise ExtractionContractError("metadata contract identity must be typed")
        canonical_digest(
            self.input_binding_digest, field="metadata_input_binding_digest"
        )
        if not isinstance(self.outcome, ExtractionOutcome):
            raise ExtractionContractError("metadata outcome must be typed")
        if not isinstance(self.failure_code, ExtractionFailureCode):
            raise ExtractionContractError("metadata failure code must be typed")
        for field_name in ("started_at", "ended_at", "recorded_at"):
            if not isinstance(getattr(self, field_name), UtcTimestamp):
                raise ExtractionContractError(f"{field_name} must be typed")
        if not isinstance(self.usage, ExtractionUsage):
            raise ExtractionContractError("metadata usage must be typed")
        if self.output is not None and not isinstance(
            self.output, ExtractionOutputView
        ):
            raise ExtractionContractError("metadata output must be typed")
        bounded_int(
            self.proposal_count,
            field="metadata_proposal_count",
            minimum=0,
            maximum=10_000,
        )
        if not isinstance(self.terminal, bool) or self.terminal != self.outcome.terminal:
            raise ExtractionContractError("metadata terminality differs from outcome")


__all__ = [
    "ExtractionInputBinding",
    "ExtractionOutputView",
    "ExtractionPassageInput",
    "ExtractionRawOutput",
    "ExtractionRunMetadata",
    "ExtractionRunRequest",
    "ExtractionRunVersion",
    "ExtractorContract",
    "ExtractorContractRequest",
    "ProducedExtraction",
    "ProposalDraft",
    "ProposalEnvelope",
    "ProposalProducer",
    "ProposalSet",
]
