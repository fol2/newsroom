from __future__ import annotations

from typing import Any

from newsroom.authority.types import ObjectAdmissionId, UtcTimestamp
from newsroom.sources import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    VersionedPolicyRef,
)

from .models import (
    ExtractionAttemptRequest,
    ExtractionOutputRequest,
    ExtractionPassageRef,
    ExtractionResourceBounds,
    ExtractionRunRequest,
    ExtractorContractRequest,
    ProposalEndpoint,
    ProposalEnvelope,
    ProposalSetRequest,
)
from .types import (
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
)


def _dict(value: Any, *, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ExtractionContractError(f"{name} fields differ from retained schema")
    return value


def _list(value: Any, *, name: str, maximum: int = 4096) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ExtractionContractError(f"{name} must be a bounded array")
    return value


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str):
        raise ExtractionContractError(f"{name} must be text")
    return value


def _integer(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExtractionContractError(f"{name} must be an integer")
    return value


def _boolean(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise ExtractionContractError(f"{name} must be boolean")
    return value


def _optional_text(value: Any, *, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name=name)


def _policy(value: Any, *, name: str) -> VersionedPolicyRef:
    item = _dict(value, fields=frozenset({"policy_id", "policy_version"}), name=name)
    return VersionedPolicyRef(
        _text(item["policy_id"], name=f"{name}.policy_id"),
        _text(item["policy_version"], name=f"{name}.policy_version"),
    )


def _object_id(value: Any, *, name: str) -> ObjectAdmissionId | None:
    if value is None:
        return None
    return ObjectAdmissionId.parse(_text(value, name=name))


def _passage(value: Any) -> ExtractionPassageRef:
    item = _dict(
        value,
        fields=frozenset(
            {
                "end_offset",
                "hydration_digest",
                "language",
                "object_admission_id",
                "ordinal",
                "passage_id",
                "source_field",
                "start_offset",
                "text_digest",
            }
        ),
        name="extraction passage",
    )
    return ExtractionPassageRef(
        passage_id=_text(item["passage_id"], name="passage_id"),
        ordinal=_integer(item["ordinal"], name="passage_ordinal"),
        source_field=_text(item["source_field"], name="source_field"),
        start_offset=_integer(item["start_offset"], name="start_offset"),
        end_offset=_integer(item["end_offset"], name="end_offset"),
        text_digest=_text(item["text_digest"], name="text_digest"),
        language=_text(item["language"], name="language"),
        object_admission_id=_object_id(item["object_admission_id"], name="object_admission_id"),
        hydration_digest=_optional_text(item["hydration_digest"], name="hydration_digest"),
    )


def extractor_contract_from_value(value: Any, *, idempotency_key: str) -> ExtractorContractRequest:
    item = _dict(
        value,
        fields=frozenset(
            {
                "contract_id",
                "previous_contract_id",
                "registered_at",
                "semantic",
                "semantic_digest",
            }
        ),
        name="extractor contract",
    )
    semantic = _dict(
        item["semantic"],
        fields=frozenset(
            {
                "code_contract",
                "contract_family",
                "execution_profile",
                "extraction_policy",
                "framework",
                "model_placeholder",
                "normalization_contract",
                "output_schema_contract",
                "producer_kind",
                "prompt_contract",
                "resource_bounds",
                "runtime_authority",
                "version_number",
            }
        ),
        name="extractor contract semantic",
    )
    bounds = _dict(
        semantic["resource_bounds"],
        fields=frozenset(
            {
                "max_attempts",
                "max_cost_microunits",
                "max_duration_ms",
                "max_input_bytes",
                "max_input_tokens",
                "max_output_bytes",
                "max_output_tokens",
                "max_proposals",
            }
        ),
        name="extractor resource bounds",
    )
    previous = item["previous_contract_id"]
    result = ExtractorContractRequest(
        contract_id=ExtractorContractId.parse(_text(item["contract_id"], name="contract_id")),
        contract_family=_text(semantic["contract_family"], name="contract_family"),
        version_number=_integer(semantic["version_number"], name="version_number"),
        previous_contract_id=None if previous is None else ExtractorContractId.parse(_text(previous, name="previous_contract_id")),
        framework=_policy(semantic["framework"], name="framework"),
        model_placeholder=_policy(semantic["model_placeholder"], name="model_placeholder"),
        prompt_contract=_policy(semantic["prompt_contract"], name="prompt_contract"),
        output_schema_contract=_policy(semantic["output_schema_contract"], name="output_schema_contract"),
        code_contract=_policy(semantic["code_contract"], name="code_contract"),
        normalization_contract=_policy(semantic["normalization_contract"], name="normalization_contract"),
        extraction_policy=_policy(semantic["extraction_policy"], name="extraction_policy"),
        producer_kind=ExtractionProducerKind(_text(semantic["producer_kind"], name="producer_kind")),
        execution_profile=ExtractionExecutionProfile(_text(semantic["execution_profile"], name="execution_profile")),
        resource_bounds=ExtractionResourceBounds(
            max_input_bytes=_integer(bounds["max_input_bytes"], name="max_input_bytes"),
            max_output_bytes=_integer(bounds["max_output_bytes"], name="max_output_bytes"),
            max_proposals=_integer(bounds["max_proposals"], name="max_proposals"),
            max_attempts=_integer(bounds["max_attempts"], name="max_attempts"),
            max_duration_ms=_integer(bounds["max_duration_ms"], name="max_duration_ms"),
            max_input_tokens=_integer(bounds["max_input_tokens"], name="max_input_tokens"),
            max_output_tokens=_integer(bounds["max_output_tokens"], name="max_output_tokens"),
            max_cost_microunits=_integer(bounds["max_cost_microunits"], name="max_cost_microunits"),
        ),
        runtime_authority=_text(semantic["runtime_authority"], name="runtime_authority"),
        registered_at=UtcTimestamp.parse(_text(item["registered_at"], name="registered_at")),
        idempotency_key=idempotency_key,
    )
    if result.semantic_digest != _text(item["semantic_digest"], name="semantic_digest"):
        raise ExtractionContractError("extractor contract semantic digest mismatch")
    return result


def extraction_run_from_value(value: Any, *, idempotency_key: str) -> ExtractionRunRequest:
    item = _dict(
        value,
        fields=frozenset(
            {
                "input_manifest",
                "input_manifest_digest",
                "producer_id",
                "producer_version",
                "requested_at",
                "run_id",
                "semantic_digest",
            }
        ),
        name="extraction run",
    )
    manifest = _dict(
        item["input_manifest"],
        fields=frozenset(
            {
                "allowed_use",
                "contract_digest",
                "contract_id",
                "definition_id",
                "definition_version_id",
                "item_id",
                "passages",
                "representation_id",
                "retention_scope",
                "revision_id",
                "rights_decision_id",
                "rights_policy_version",
            }
        ),
        name="extraction input manifest",
    )
    result = ExtractionRunRequest(
        run_id=ExtractionRunId.parse(_text(item["run_id"], name="run_id")),
        contract_id=ExtractorContractId.parse(_text(manifest["contract_id"], name="contract_id")),
        contract_digest=_text(manifest["contract_digest"], name="contract_digest"),
        definition_id=SourceDefinitionId.parse(_text(manifest["definition_id"], name="definition_id")),
        definition_version_id=SourceDefinitionVersionId.parse(_text(manifest["definition_version_id"], name="definition_version_id")),
        item_id=SourceItemId.parse(_text(manifest["item_id"], name="item_id")),
        revision_id=SourceRevisionId.parse(_text(manifest["revision_id"], name="revision_id")),
        representation_id=DiscoveryRepresentationId.parse(_text(manifest["representation_id"], name="representation_id")),
        rights_decision_id=_text(manifest["rights_decision_id"], name="rights_decision_id"),
        rights_policy_version=_text(manifest["rights_policy_version"], name="rights_policy_version"),
        allowed_use=_text(manifest["allowed_use"], name="allowed_use"),
        retention_scope=_text(manifest["retention_scope"], name="retention_scope"),
        passages=tuple(_passage(entry) for entry in _list(manifest["passages"], name="passages", maximum=1024)),
        input_manifest_digest=_text(item["input_manifest_digest"], name="input_manifest_digest"),
        producer_id=_text(item["producer_id"], name="producer_id"),
        producer_version=_text(item["producer_version"], name="producer_version"),
        requested_at=UtcTimestamp.parse(_text(item["requested_at"], name="requested_at")),
        idempotency_key=idempotency_key,
    )
    if result.semantic_digest != _text(item["semantic_digest"], name="semantic_digest"):
        raise ExtractionContractError("extraction run semantic digest mismatch")
    return result


def extraction_attempt_from_value(value: Any, *, idempotency_key: str) -> ExtractionAttemptRequest:
    item = _dict(
        value,
        fields=frozenset(
            {
                "attempt_id",
                "attempt_number",
                "cost_microunits",
                "ended_at",
                "error_code",
                "error_summary",
                "input_bytes",
                "input_tokens",
                "outcome",
                "output_bytes",
                "output_tokens",
                "previous_attempt_id",
                "producer_execution_id",
                "run_id",
                "semantic_digest",
                "started_at",
            }
        ),
        name="extraction attempt",
    )
    previous = item["previous_attempt_id"]
    result = ExtractionAttemptRequest(
        attempt_id=ExtractionAttemptId.parse(_text(item["attempt_id"], name="attempt_id")),
        run_id=ExtractionRunId.parse(_text(item["run_id"], name="run_id")),
        attempt_number=_integer(item["attempt_number"], name="attempt_number"),
        previous_attempt_id=None if previous is None else ExtractionAttemptId.parse(_text(previous, name="previous_attempt_id")),
        outcome=ExtractionAttemptOutcome(_text(item["outcome"], name="outcome")),
        producer_execution_id=_text(item["producer_execution_id"], name="producer_execution_id"),
        started_at=UtcTimestamp.parse(_text(item["started_at"], name="started_at")),
        ended_at=UtcTimestamp.parse(_text(item["ended_at"], name="ended_at")),
        input_bytes=_integer(item["input_bytes"], name="input_bytes"),
        output_bytes=_integer(item["output_bytes"], name="output_bytes"),
        input_tokens=_integer(item["input_tokens"], name="input_tokens"),
        output_tokens=_integer(item["output_tokens"], name="output_tokens"),
        cost_microunits=_integer(item["cost_microunits"], name="cost_microunits"),
        error_code=_optional_text(item["error_code"], name="error_code"),
        error_summary=_optional_text(item["error_summary"], name="error_summary"),
        idempotency_key=idempotency_key,
    )
    if result.semantic_digest != _text(item["semantic_digest"], name="semantic_digest"):
        raise ExtractionContractError("extraction attempt semantic digest mismatch")
    return result


def extraction_output_from_value(value: Any, *, idempotency_key: str) -> ExtractionOutputRequest:
    item = _dict(
        value,
        fields=frozenset(
            {
                "attempt_id",
                "hydration_digest",
                "object_admission_id",
                "output_digest",
                "output_id",
                "output_kind",
                "output_schema_digest",
                "retained_at",
                "run_id",
                "structured_output",
                "valid",
                "validation_errors",
            }
        ),
        name="extraction output",
    )
    errors = _list(item["validation_errors"], name="validation_errors", maximum=64)
    if any(not isinstance(entry, str) for entry in errors):
        raise ExtractionContractError("validation errors must be text")
    result = ExtractionOutputRequest(
        output_id=ExtractionOutputId.parse(_text(item["output_id"], name="output_id")),
        run_id=ExtractionRunId.parse(_text(item["run_id"], name="run_id")),
        attempt_id=ExtractionAttemptId.parse(_text(item["attempt_id"], name="attempt_id")),
        output_kind=ExtractionOutputKind(_text(item["output_kind"], name="output_kind")),
        output_schema_digest=_text(item["output_schema_digest"], name="output_schema_digest"),
        structured_output=item["structured_output"],
        object_admission_id=_object_id(item["object_admission_id"], name="object_admission_id"),
        hydration_digest=_optional_text(item["hydration_digest"], name="hydration_digest"),
        valid=_boolean(item["valid"], name="valid"),
        validation_errors=tuple(errors),
        retained_at=UtcTimestamp.parse(_text(item["retained_at"], name="retained_at")),
        idempotency_key=idempotency_key,
    )
    if result.output_digest != _text(item["output_digest"], name="output_digest"):
        raise ExtractionContractError("extraction output digest mismatch")
    return result


def _endpoint(value: Any, *, name: str) -> ProposalEndpoint:
    item = _dict(
        value,
        fields=frozenset({"kind", "language", "normalized_hint", "placeholder_id", "surface_text"}),
        name=name,
    )
    return ProposalEndpoint(
        placeholder_id=_text(item["placeholder_id"], name=f"{name}.placeholder_id"),
        kind=ProposalEndpointKind(_text(item["kind"], name=f"{name}.kind")),
        surface_text=_text(item["surface_text"], name=f"{name}.surface_text"),
        language=_text(item["language"], name=f"{name}.language"),
        normalized_hint=_optional_text(item["normalized_hint"], name=f"{name}.normalized_hint"),
    )


def _proposal(value: Any) -> ProposalEnvelope:
    item = _dict(
        value,
        fields=frozenset(
            {
                "attributes",
                "confidence_basis_points",
                "object",
                "passage_ids",
                "predicate_hint",
                "producer_local_id",
                "proposal_id",
                "proposal_kind",
                "subject",
                "uncertainty",
                "uncertainty_reasons",
            }
        ),
        name="proposal envelope",
    )
    passage_ids = _list(item["passage_ids"], name="proposal passage ids", maximum=64)
    reasons = _list(item["uncertainty_reasons"], name="uncertainty reasons", maximum=32)
    if any(not isinstance(entry, str) for entry in passage_ids + reasons):
        raise ExtractionContractError("proposal passage/reason values must be text")
    attributes = item["attributes"]
    if not isinstance(attributes, dict):
        raise ExtractionContractError("proposal attributes must be an object")
    return ProposalEnvelope(
        proposal_id=ProposalEnvelopeId.parse(_text(item["proposal_id"], name="proposal_id")),
        proposal_kind=ProposalKind(_text(item["proposal_kind"], name="proposal_kind")),
        producer_local_id=_text(item["producer_local_id"], name="producer_local_id"),
        subject=_endpoint(item["subject"], name="proposal subject"),
        object=None if item["object"] is None else _endpoint(item["object"], name="proposal object"),
        predicate_hint=_optional_text(item["predicate_hint"], name="predicate_hint"),
        passage_ids=tuple(passage_ids),
        confidence_basis_points=_integer(item["confidence_basis_points"], name="confidence_basis_points"),
        uncertainty=ProposalUncertainty(_text(item["uncertainty"], name="uncertainty")),
        uncertainty_reasons=tuple(reasons),
        attributes=attributes,
    )


def proposal_set_from_value(value: Any, *, idempotency_key: str) -> ProposalSetRequest:
    item = _dict(
        value,
        fields=frozenset(
            {
                "attempt_id",
                "completeness",
                "output_id",
                "proposal_set_id",
                "proposals",
                "retained_at",
                "run_id",
                "semantic_digest",
            }
        ),
        name="proposal set",
    )
    result = ProposalSetRequest(
        proposal_set_id=ProposalSetId.parse(_text(item["proposal_set_id"], name="proposal_set_id")),
        run_id=ExtractionRunId.parse(_text(item["run_id"], name="run_id")),
        attempt_id=ExtractionAttemptId.parse(_text(item["attempt_id"], name="attempt_id")),
        output_id=ExtractionOutputId.parse(_text(item["output_id"], name="output_id")),
        completeness=ProposalSetCompleteness(_text(item["completeness"], name="completeness")),
        proposals=tuple(_proposal(entry) for entry in _list(item["proposals"], name="proposals")),
        retained_at=UtcTimestamp.parse(_text(item["retained_at"], name="retained_at")),
        idempotency_key=idempotency_key,
    )
    if result.semantic_digest != _text(item["semantic_digest"], name="semantic_digest"):
        raise ExtractionContractError("proposal set semantic digest mismatch")
    return result


__all__ = [
    "extraction_attempt_from_value",
    "extraction_output_from_value",
    "extraction_run_from_value",
    "extractor_contract_from_value",
    "proposal_set_from_value",
]
