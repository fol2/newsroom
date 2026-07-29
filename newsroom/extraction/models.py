from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import ObjectAdmissionId, UtcTimestamp, UUIDv4Id, require_scope, require_token
from newsroom.sources import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    VersionedPolicyRef,
)

from .types import (
    MAX_PROPOSAL_ATTRIBUTES_BYTES,
    MAX_STRUCTURED_OUTPUT_BYTES,
    RUNTIME_AUTHORITY_DISABLED,
    ExtractionAttemptId,
    ExtractionAttemptOutcome,
    ExtractionContractError,
    ExtractionExecutionProfile,
    ExtractionOutputId,
    ExtractionOutputKind,
    ExtractionProducerKind,
    ExtractionRunId,
    ExtractorContractId,
    ProposalEndpointKind,
    ProposalEnvelopeId,
    ProposalKind,
    ProposalSetCompleteness,
    ProposalSetId,
    ProposalUncertainty,
    bounded_text,
    bounded_text_tuple,
    canonical_digest,
    canonical_json_value,
    non_negative_int,
    positive_int,
    require_version_token,
    semantic_digest,
)


def _policy(value: VersionedPolicyRef, *, field: str) -> VersionedPolicyRef:
    if not isinstance(value, VersionedPolicyRef):
        raise ExtractionContractError(f"{field} must be a versioned policy reference")
    return value


def _utc(value: UtcTimestamp, *, field: str) -> UtcTimestamp:
    if not isinstance(value, UtcTimestamp):
        raise ExtractionContractError(f"{field} must be typed UTC")
    return value


def _idempotency(value: str) -> str:
    return bounded_text(value, field="idempotency_key", maximum_bytes=256)


@dataclass(frozen=True, slots=True)
class ExtractionResourceBounds:
    max_input_bytes: int
    max_output_bytes: int
    max_proposals: int
    max_attempts: int
    max_duration_ms: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_microunits: int

    def __post_init__(self) -> None:
        positive_int(self.max_input_bytes, field="max_input_bytes", maximum=8 * 1024 * 1024)
        positive_int(self.max_output_bytes, field="max_output_bytes", maximum=MAX_STRUCTURED_OUTPUT_BYTES)
        positive_int(self.max_proposals, field="max_proposals", maximum=4096)
        positive_int(self.max_attempts, field="max_attempts", maximum=16)
        positive_int(self.max_duration_ms, field="max_duration_ms", maximum=60 * 60 * 1000)
        non_negative_int(self.max_input_tokens, field="max_input_tokens", maximum=10_000_000)
        non_negative_int(self.max_output_tokens, field="max_output_tokens", maximum=10_000_000)
        non_negative_int(self.max_cost_microunits, field="max_cost_microunits", maximum=10**12)

    def canonical_value(self) -> dict[str, int]:
        return {
            "max_attempts": self.max_attempts,
            "max_cost_microunits": self.max_cost_microunits,
            "max_duration_ms": self.max_duration_ms,
            "max_input_bytes": self.max_input_bytes,
            "max_input_tokens": self.max_input_tokens,
            "max_output_bytes": self.max_output_bytes,
            "max_output_tokens": self.max_output_tokens,
            "max_proposals": self.max_proposals,
        }


@dataclass(frozen=True, slots=True)
class ExtractorContractRequest:
    contract_id: ExtractorContractId
    contract_family: str
    version_number: int
    previous_contract_id: ExtractorContractId | None
    framework: VersionedPolicyRef
    model_placeholder: VersionedPolicyRef
    prompt_contract: VersionedPolicyRef
    output_schema_contract: VersionedPolicyRef
    code_contract: VersionedPolicyRef
    normalization_contract: VersionedPolicyRef
    extraction_policy: VersionedPolicyRef
    producer_kind: ExtractionProducerKind
    execution_profile: ExtractionExecutionProfile
    resource_bounds: ExtractionResourceBounds
    runtime_authority: str
    registered_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.contract_id, ExtractorContractId):
            raise ExtractionContractError("extractor contract identity must be typed")
        require_token(self.contract_family, field="extractor_contract_family")
        positive_int(self.version_number, field="contract_version_number", maximum=1_000_000)
        if self.version_number == 1 and self.previous_contract_id is not None:
            raise ExtractionContractError("initial extractor contract cannot have a predecessor")
        if self.version_number > 1 and not isinstance(self.previous_contract_id, ExtractorContractId):
            raise ExtractionContractError("later extractor contract requires exact predecessor")
        if self.previous_contract_id == self.contract_id:
            raise ExtractionContractError("extractor contract cannot precede itself")
        for field in (
            "framework",
            "model_placeholder",
            "prompt_contract",
            "output_schema_contract",
            "code_contract",
            "normalization_contract",
            "extraction_policy",
        ):
            _policy(getattr(self, field), field=field)
        if not isinstance(self.producer_kind, ExtractionProducerKind):
            raise ExtractionContractError("producer kind must be typed")
        if not isinstance(self.execution_profile, ExtractionExecutionProfile):
            raise ExtractionContractError("execution profile must be typed")
        if not isinstance(self.resource_bounds, ExtractionResourceBounds):
            raise ExtractionContractError("resource bounds must be typed")
        if self.runtime_authority != RUNTIME_AUTHORITY_DISABLED:
            raise ExtractionContractError("Increment 4A cannot authorise real runtime execution")
        if (
            self.execution_profile is ExtractionExecutionProfile.FIXTURE
            and self.producer_kind is not ExtractionProducerKind.DETERMINISTIC_FAKE
        ) or (
            self.execution_profile is ExtractionExecutionProfile.REPLAY
            and self.producer_kind is not ExtractionProducerKind.APPROVED_REPLAY
        ):
            raise ExtractionContractError("profile and producer kind are incompatible")
        _utc(self.registered_at, field="contract registration time")
        _idempotency(self.idempotency_key)

    def semantic_value(self) -> dict[str, Any]:
        return {
            "code_contract": self.code_contract.canonical_value(),
            "contract_family": self.contract_family,
            "execution_profile": self.execution_profile.value,
            "extraction_policy": self.extraction_policy.canonical_value(),
            "framework": self.framework.canonical_value(),
            "model_placeholder": self.model_placeholder.canonical_value(),
            "normalization_contract": self.normalization_contract.canonical_value(),
            "output_schema_contract": self.output_schema_contract.canonical_value(),
            "producer_kind": self.producer_kind.value,
            "prompt_contract": self.prompt_contract.canonical_value(),
            "resource_bounds": self.resource_bounds.canonical_value(),
            "runtime_authority": self.runtime_authority,
            "version_number": self.version_number,
        }

    @property
    def semantic_digest(self) -> str:
        return semantic_digest(self.semantic_value())

    def canonical_value(self) -> dict[str, Any]:
        return {
            "contract_id": str(self.contract_id),
            "previous_contract_id": None if self.previous_contract_id is None else str(self.previous_contract_id),
            "registered_at": self.registered_at.to_text(),
            "semantic": self.semantic_value(),
            "semantic_digest": self.semantic_digest,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ExtractionPassageRef:
    passage_id: str
    ordinal: int
    source_field: str
    start_offset: int
    end_offset: int
    text_digest: str
    language: str
    object_admission_id: ObjectAdmissionId | None = None
    hydration_digest: str | None = None

    def __post_init__(self) -> None:
        require_token(self.passage_id, field="passage_id")
        non_negative_int(self.ordinal, field="passage_ordinal", maximum=1_000_000)
        require_token(self.source_field, field="passage_source_field")
        non_negative_int(self.start_offset, field="passage_start_offset", maximum=100_000_000)
        positive_int(self.end_offset, field="passage_end_offset", maximum=100_000_000)
        if self.end_offset <= self.start_offset:
            raise ExtractionContractError("passage end must follow start")
        canonical_digest(self.text_digest, field="passage_text_digest")
        require_token(self.language, field="passage_language")
        if (self.object_admission_id is None) != (self.hydration_digest is None):
            raise ExtractionContractError("passage object admission and hydration digest are paired")
        if self.object_admission_id is not None and not isinstance(self.object_admission_id, ObjectAdmissionId):
            raise ExtractionContractError("passage object admission must be typed")
        if self.hydration_digest is not None:
            canonical_digest(self.hydration_digest, field="passage_hydration_digest")

    def canonical_value(self) -> dict[str, Any]:
        return {
            "end_offset": self.end_offset,
            "hydration_digest": self.hydration_digest,
            "language": self.language,
            "object_admission_id": None if self.object_admission_id is None else str(self.object_admission_id),
            "ordinal": self.ordinal,
            "passage_id": self.passage_id,
            "source_field": self.source_field,
            "start_offset": self.start_offset,
            "text_digest": self.text_digest,
        }


@dataclass(frozen=True, slots=True)
class ExtractionRunRequest:
    run_id: ExtractionRunId
    contract_id: ExtractorContractId
    contract_digest: str
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    item_id: SourceItemId
    revision_id: SourceRevisionId
    representation_id: DiscoveryRepresentationId
    rights_decision_id: str
    rights_policy_version: str
    allowed_use: str
    retention_scope: str
    passages: tuple[ExtractionPassageRef, ...]
    input_manifest_digest: str
    producer_id: str
    producer_version: str
    requested_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        typed = (
            (self.run_id, ExtractionRunId, "run"),
            (self.contract_id, ExtractorContractId, "contract"),
            (self.definition_id, SourceDefinitionId, "source definition"),
            (self.definition_version_id, SourceDefinitionVersionId, "source version"),
            (self.item_id, SourceItemId, "source item"),
            (self.revision_id, SourceRevisionId, "source revision"),
            (self.representation_id, DiscoveryRepresentationId, "representation"),
        )
        for value, expected, name in typed:
            if not isinstance(value, expected):
                raise ExtractionContractError(f"{name} identity must be typed")
        canonical_digest(self.contract_digest, field="extractor_contract_digest")
        try:
            UUIDv4Id.parse(self.rights_decision_id)
        except ValueError as exc:
            raise ExtractionContractError("rights decision must be canonical UUIDv4") from exc
        require_version_token(self.rights_policy_version, field="rights_policy_version")
        require_scope(self.allowed_use, field="extraction_allowed_use")
        require_scope(self.retention_scope, field="extraction_retention_scope")
        if not isinstance(self.passages, tuple) or not self.passages:
            raise ExtractionContractError("run requires retained permitted passages")
        if len(self.passages) > 1024 or any(not isinstance(item, ExtractionPassageRef) for item in self.passages):
            raise ExtractionContractError("run passages exceed the typed bound")
        if tuple(item.ordinal for item in self.passages) != tuple(range(len(self.passages))):
            raise ExtractionContractError("passage ordinals must be contiguous from zero")
        passage_ids = tuple(item.passage_id for item in self.passages)
        if len(passage_ids) != len(set(passage_ids)):
            raise ExtractionContractError("passage identities must be unique")
        canonical_digest(self.input_manifest_digest, field="input_manifest_digest")
        if self.input_manifest_digest != self.derived_input_manifest_digest:
            raise ExtractionContractError("input manifest digest differs from exact lineage")
        require_token(self.producer_id, field="extraction_producer_id")
        require_version_token(self.producer_version, field="extraction_producer_version")
        _utc(self.requested_at, field="run request time")
        _idempotency(self.idempotency_key)

    def input_manifest_value(self) -> dict[str, Any]:
        return {
            "allowed_use": self.allowed_use,
            "contract_digest": self.contract_digest,
            "contract_id": str(self.contract_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "item_id": str(self.item_id),
            "passages": [item.canonical_value() for item in self.passages],
            "representation_id": str(self.representation_id),
            "retention_scope": self.retention_scope,
            "revision_id": str(self.revision_id),
            "rights_decision_id": self.rights_decision_id,
            "rights_policy_version": self.rights_policy_version,
        }

    @property
    def derived_input_manifest_digest(self) -> str:
        return semantic_digest(self.input_manifest_value())

    @property
    def semantic_digest(self) -> str:
        return semantic_digest(
            {
                "input_manifest_digest": self.input_manifest_digest,
                "producer_id": self.producer_id,
                "producer_version": self.producer_version,
            }
        )

    def canonical_value(self) -> dict[str, Any]:
        return {
            "input_manifest": self.input_manifest_value(),
            "input_manifest_digest": self.input_manifest_digest,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "requested_at": self.requested_at.to_text(),
            "run_id": str(self.run_id),
            "semantic_digest": self.semantic_digest,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ExtractionAttemptRequest:
    attempt_id: ExtractionAttemptId
    run_id: ExtractionRunId
    attempt_number: int
    previous_attempt_id: ExtractionAttemptId | None
    outcome: ExtractionAttemptOutcome
    producer_execution_id: str
    started_at: UtcTimestamp
    ended_at: UtcTimestamp
    input_bytes: int
    output_bytes: int
    input_tokens: int
    output_tokens: int
    cost_microunits: int
    error_code: str | None
    error_summary: str | None
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, ExtractionAttemptId) or not isinstance(self.run_id, ExtractionRunId):
            raise ExtractionContractError("attempt and run identities must be typed")
        positive_int(self.attempt_number, field="attempt_number", maximum=16)
        if self.attempt_number == 1 and self.previous_attempt_id is not None:
            raise ExtractionContractError("initial attempt cannot have a predecessor")
        if self.attempt_number > 1 and not isinstance(self.previous_attempt_id, ExtractionAttemptId):
            raise ExtractionContractError("later attempt requires exact predecessor")
        if self.previous_attempt_id == self.attempt_id:
            raise ExtractionContractError("attempt cannot precede itself")
        if not isinstance(self.outcome, ExtractionAttemptOutcome):
            raise ExtractionContractError("attempt outcome must be typed")
        require_token(self.producer_execution_id, field="producer_execution_id")
        _utc(self.started_at, field="attempt start time")
        _utc(self.ended_at, field="attempt end time")
        if self.ended_at.value < self.started_at.value:
            raise ExtractionContractError("attempt cannot end before it starts")
        non_negative_int(self.input_bytes, field="attempt_input_bytes", maximum=8 * 1024 * 1024)
        non_negative_int(self.output_bytes, field="attempt_output_bytes", maximum=MAX_STRUCTURED_OUTPUT_BYTES)
        non_negative_int(self.input_tokens, field="attempt_input_tokens", maximum=10_000_000)
        non_negative_int(self.output_tokens, field="attempt_output_tokens", maximum=10_000_000)
        non_negative_int(self.cost_microunits, field="attempt_cost_microunits", maximum=10**12)
        failure = self.outcome in {ExtractionAttemptOutcome.RETRYABLE_FAILURE, ExtractionAttemptOutcome.BLOCKING_FAILURE}
        if failure:
            require_token(self.error_code or "", field="attempt_error_code")
            bounded_text(self.error_summary or "", field="attempt_error_summary", maximum_bytes=2048)
            if self.output_bytes != 0:
                raise ExtractionContractError(
                    "failed extraction attempt cannot claim output bytes"
                )
        elif self.error_code is not None or self.error_summary is not None:
            raise ExtractionContractError("non-failure attempt cannot carry an error")
        _idempotency(self.idempotency_key)

    @property
    def semantic_digest(self) -> str:
        return semantic_digest(self.canonical_value(exclude_identity=True))

    def canonical_value(self, *, exclude_identity: bool = False) -> dict[str, Any]:
        value = {
            "attempt_number": self.attempt_number,
            "cost_microunits": self.cost_microunits,
            "ended_at": self.ended_at.to_text(),
            "error_code": self.error_code,
            "error_summary": self.error_summary,
            "input_bytes": self.input_bytes,
            "input_tokens": self.input_tokens,
            "outcome": self.outcome.value,
            "output_bytes": self.output_bytes,
            "output_tokens": self.output_tokens,
            "previous_attempt_id": None if self.previous_attempt_id is None else str(self.previous_attempt_id),
            "producer_execution_id": self.producer_execution_id,
            "run_id": str(self.run_id),
            "started_at": self.started_at.to_text(),
        }
        if not exclude_identity:
            value["attempt_id"] = str(self.attempt_id)
            value["semantic_digest"] = self.semantic_digest
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ExtractionOutputRequest:
    output_id: ExtractionOutputId
    run_id: ExtractionRunId
    attempt_id: ExtractionAttemptId
    output_kind: ExtractionOutputKind
    output_schema_digest: str
    structured_output: dict[str, Any] | list[Any] | None
    object_admission_id: ObjectAdmissionId | None
    hydration_digest: str | None
    valid: bool
    validation_errors: tuple[str, ...]
    retained_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.output_id, ExtractionOutputId) or not isinstance(self.run_id, ExtractionRunId) or not isinstance(self.attempt_id, ExtractionAttemptId):
            raise ExtractionContractError("output lineage identities must be typed")
        if not isinstance(self.output_kind, ExtractionOutputKind):
            raise ExtractionContractError("output kind must be typed")
        canonical_digest(self.output_schema_digest, field="output_schema_digest")
        if self.output_kind is ExtractionOutputKind.INLINE_STRUCTURED:
            if not isinstance(self.structured_output, (dict, list)):
                raise ExtractionContractError("inline output must be a structured object or array")
            canonical_json_value(
                self.structured_output,
                field="structured_output",
                maximum_bytes=MAX_STRUCTURED_OUTPUT_BYTES,
            )
            if self.object_admission_id is not None or self.hydration_digest is not None:
                raise ExtractionContractError("inline output cannot carry object authority")
        else:
            if self.structured_output is not None:
                raise ExtractionContractError("object output cannot duplicate inline bytes")
            if not isinstance(self.object_admission_id, ObjectAdmissionId) or self.hydration_digest is None:
                raise ExtractionContractError("object output requires exact admission and hydration digest")
            canonical_digest(self.hydration_digest, field="output_hydration_digest")
        if not isinstance(self.valid, bool):
            raise ExtractionContractError("output validity must be boolean")
        bounded_text_tuple(
            self.validation_errors,
            field="output_validation_errors",
            allow_empty=True,
            maximum_items=64,
            maximum_item_bytes=1024,
        )
        if self.valid and self.validation_errors:
            raise ExtractionContractError("valid output cannot carry validation errors")
        if not self.valid and not self.validation_errors:
            raise ExtractionContractError("invalid output requires retained validation errors")
        _utc(self.retained_at, field="output retention time")
        _idempotency(self.idempotency_key)

    @property
    def output_bytes(self) -> bytes | None:
        if self.structured_output is None:
            return None
        return canonical_json_bytes(self.structured_output)

    @property
    def output_digest(self) -> str:
        if self.output_bytes is not None:
            return digest_bytes(self.output_bytes)
        assert self.hydration_digest is not None
        return self.hydration_digest

    def canonical_value(self) -> dict[str, Any]:
        return {
            "attempt_id": str(self.attempt_id),
            "hydration_digest": self.hydration_digest,
            "object_admission_id": None if self.object_admission_id is None else str(self.object_admission_id),
            "output_digest": self.output_digest,
            "output_id": str(self.output_id),
            "output_kind": self.output_kind.value,
            "output_schema_digest": self.output_schema_digest,
            "retained_at": self.retained_at.to_text(),
            "run_id": str(self.run_id),
            "structured_output": self.structured_output,
            "valid": self.valid,
            "validation_errors": list(self.validation_errors),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ProposalEndpoint:
    placeholder_id: str
    kind: ProposalEndpointKind
    surface_text: str
    language: str
    normalized_hint: str | None = None

    def __post_init__(self) -> None:
        require_token(self.placeholder_id, field="proposal_placeholder_id")
        if not isinstance(self.kind, ProposalEndpointKind):
            raise ExtractionContractError("proposal endpoint kind must be typed")
        bounded_text(self.surface_text, field="proposal_surface_text", maximum_bytes=4096)
        require_token(self.language, field="proposal_language")
        if self.normalized_hint is not None:
            bounded_text(self.normalized_hint, field="proposal_normalized_hint", maximum_bytes=2048)

    def canonical_value(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "language": self.language,
            "normalized_hint": self.normalized_hint,
            "placeholder_id": self.placeholder_id,
            "surface_text": self.surface_text,
        }


@dataclass(frozen=True, slots=True)
class ProposalEnvelope:
    proposal_id: ProposalEnvelopeId
    proposal_kind: ProposalKind
    producer_local_id: str
    subject: ProposalEndpoint
    object: ProposalEndpoint | None
    predicate_hint: str | None
    passage_ids: tuple[str, ...]
    confidence_basis_points: int
    uncertainty: ProposalUncertainty
    uncertainty_reasons: tuple[str, ...]
    attributes: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, ProposalEnvelopeId):
            raise ExtractionContractError("proposal identity must be typed")
        if not isinstance(self.proposal_kind, ProposalKind):
            raise ExtractionContractError("proposal kind must be typed")
        require_token(self.producer_local_id, field="proposal_producer_local_id")
        if not isinstance(self.subject, ProposalEndpoint):
            raise ExtractionContractError("proposal subject must be typed")
        if self.object is not None and not isinstance(self.object, ProposalEndpoint):
            raise ExtractionContractError("proposal object must be typed")
        if self.predicate_hint is not None:
            require_token(self.predicate_hint, field="proposal_predicate_hint")
        if self.proposal_kind is ProposalKind.RELATION and (self.object is None or self.predicate_hint is None):
            raise ExtractionContractError("relation proposal requires object and predicate hint")
        if self.proposal_kind is not ProposalKind.RELATION and self.predicate_hint is not None:
            raise ExtractionContractError("only relation proposals carry predicate hints")
        bounded_text_tuple(self.passage_ids, field="proposal_passage_ids", maximum_items=64)
        non_negative_int(self.confidence_basis_points, field="proposal_confidence_basis_points", maximum=10_000)
        if not isinstance(self.uncertainty, ProposalUncertainty):
            raise ExtractionContractError("proposal uncertainty must be typed")
        bounded_text_tuple(
            self.uncertainty_reasons,
            field="proposal_uncertainty_reasons",
            allow_empty=True,
            maximum_items=32,
            maximum_item_bytes=1024,
        )
        if self.uncertainty is ProposalUncertainty.LOW and self.uncertainty_reasons:
            raise ExtractionContractError("LOW uncertainty cannot carry unresolved reasons")
        if self.uncertainty is not ProposalUncertainty.LOW and not self.uncertainty_reasons:
            raise ExtractionContractError("non-LOW uncertainty requires exact reasons")
        canonical_json_value(
            self.attributes,
            field="proposal_attributes",
            maximum_bytes=MAX_PROPOSAL_ATTRIBUTES_BYTES,
        )

    def canonical_value(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes,
            "confidence_basis_points": self.confidence_basis_points,
            "object": None if self.object is None else self.object.canonical_value(),
            "passage_ids": list(self.passage_ids),
            "predicate_hint": self.predicate_hint,
            "producer_local_id": self.producer_local_id,
            "proposal_id": str(self.proposal_id),
            "proposal_kind": self.proposal_kind.value,
            "subject": self.subject.canonical_value(),
            "uncertainty": self.uncertainty.value,
            "uncertainty_reasons": list(self.uncertainty_reasons),
        }

    @property
    def digest(self) -> str:
        return semantic_digest(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ProposalSetRequest:
    proposal_set_id: ProposalSetId
    run_id: ExtractionRunId
    attempt_id: ExtractionAttemptId
    output_id: ExtractionOutputId
    completeness: ProposalSetCompleteness
    proposals: tuple[ProposalEnvelope, ...]
    retained_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        typed = (
            (self.proposal_set_id, ProposalSetId),
            (self.run_id, ExtractionRunId),
            (self.attempt_id, ExtractionAttemptId),
            (self.output_id, ExtractionOutputId),
        )
        if any(not isinstance(value, expected) for value, expected in typed):
            raise ExtractionContractError("proposal set lineage identities must be typed")
        if not isinstance(self.completeness, ProposalSetCompleteness):
            raise ExtractionContractError("proposal set completeness must be typed")
        if not isinstance(self.proposals, tuple) or len(self.proposals) > 4096 or any(not isinstance(item, ProposalEnvelope) for item in self.proposals):
            raise ExtractionContractError("proposal set must be a bounded typed tuple")
        ids = tuple(str(item.proposal_id) for item in self.proposals)
        local_ids = tuple(item.producer_local_id for item in self.proposals)
        if len(ids) != len(set(ids)) or len(local_ids) != len(set(local_ids)):
            raise ExtractionContractError("proposal identities must be unique within a set")
        if ids != tuple(sorted(ids)):
            raise ExtractionContractError("proposals must be sorted by stable proposal identity")
        _utc(self.retained_at, field="proposal set retention time")
        _idempotency(self.idempotency_key)

    @property
    def semantic_digest(self) -> str:
        return semantic_digest(
            {
                "attempt_id": str(self.attempt_id),
                "completeness": self.completeness.value,
                "output_id": str(self.output_id),
                "proposal_digests": [item.digest for item in self.proposals],
                "run_id": str(self.run_id),
            }
        )

    def canonical_value(self) -> dict[str, Any]:
        return {
            "attempt_id": str(self.attempt_id),
            "completeness": self.completeness.value,
            "output_id": str(self.output_id),
            "proposal_set_id": str(self.proposal_set_id),
            "proposals": [item.canonical_value() for item in self.proposals],
            "retained_at": self.retained_at.to_text(),
            "run_id": str(self.run_id),
            "semantic_digest": self.semantic_digest,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


__all__ = [
    "ExtractionAttemptRequest",
    "ExtractionPassageRef",
    "ExtractionResourceBounds",
    "ExtractionRunRequest",
    "ExtractionOutputRequest",
    "ExtractorContractRequest",
    "ProposalEndpoint",
    "ProposalEnvelope",
    "ProposalSetRequest",
]
