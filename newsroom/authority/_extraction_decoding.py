from __future__ import annotations

from typing import Any, Mapping

from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import ObjectAdmissionId
from newsroom.extraction.models import (
    ExtractionInputBinding,
    ExtractionPassageInput,
    ExtractionRunRequest,
    ExtractorContractRequest,
)
from newsroom.extraction.types import (
    ExtractionBudget,
    ExtractionExecutionProfile,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractorContractId,
    VersionedExtractionComponent,
)
from newsroom.sources import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)


def _mapping(value: Any, *, identity: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise AuthorityPersistenceError(f"{identity} must be a canonical object")
    return value


def _component(value: Any, *, identity: str) -> VersionedExtractionComponent:
    item = _mapping(value, identity=identity)
    try:
        return VersionedExtractionComponent(
            component_id=str(item["component_id"]),
            component_version=str(item["component_version"]),
            contract_digest=str(item["contract_digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError(f"{identity} is invalid") from exc


def decode_extractor_contract(
    value: Mapping[str, Any], *, idempotency_key: str
) -> ExtractorContractRequest:
    try:
        return ExtractorContractRequest(
            contract_id=ExtractorContractId.parse(str(value["contract_id"])),
            framework=_component(value["framework"], identity="framework component"),
            model=_component(value["model"], identity="model component"),
            prompt=_component(value["prompt"], identity="prompt component"),
            output_schema=_component(
                value["output_schema"], identity="output schema component"
            ),
            code=_component(value["code"], identity="code component"),
            normalisation=_component(
                value["normalisation"], identity="normalisation component"
            ),
            policy=_component(value["policy"], identity="policy component"),
            execution_profile=ExtractionExecutionProfile(
                str(value["execution_profile"])
            ),
            producer_kind=str(value["producer_kind"]),
            idempotency_key=idempotency_key,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError("retained extractor contract is invalid") from exc


def _passage(value: Any) -> ExtractionPassageInput:
    item = _mapping(value, identity="extraction passage")
    try:
        return ExtractionPassageInput(
            passage_id=ExtractionPassageId.parse(str(item["passage_id"])),
            admission_id=ObjectAdmissionId.parse(str(item["admission_id"])),
            access_decision_id=ObjectAccessDecisionId.parse(
                str(item["access_decision_id"])
            ),
            hydration_policy_contract_digest=str(
                item["hydration_policy_contract_digest"]
            ),
            principal_id=str(item["principal_id"]),
            authority_domain=str(item["authority_domain"]),
            purpose=str(item["purpose"]),
            object_class=str(item["object_class"]),
            allowed_use=str(item["allowed_use"]),
            security_scope=str(item["security_scope"]),
            retention_scope=str(item["retention_scope"]),
            byte_offset=int(item["byte_offset"]),
            byte_length=int(item["byte_length"]),
            blob_digest=str(item["blob_digest"]),
            text_digest=str(item["text_digest"]),
            language=str(item["language"]),
            text=None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError("retained extraction passage is invalid") from exc


def decode_extraction_run(
    value: Mapping[str, Any], *, idempotency_key: str
) -> ExtractionRunRequest:
    try:
        binding = _mapping(value["input_binding"], identity="extraction input")
        passages_value = binding["passages"]
        if not isinstance(passages_value, list):
            raise TypeError("passages must be a list")
        budget = _mapping(value["budget"], identity="extraction budget")
        previous = value["expected_previous_version_id"]
        return ExtractionRunRequest(
            run_id=ExtractionRunId.parse(str(value["run_id"])),
            run_version_id=ExtractionRunVersionId.parse(
                str(value["run_version_id"])
            ),
            version_number=int(value["version_number"]),
            expected_previous_version_id=(
                None
                if previous is None
                else ExtractionRunVersionId.parse(str(previous))
            ),
            contract_id=ExtractorContractId.parse(str(value["contract_id"])),
            input_binding=ExtractionInputBinding(
                definition_id=SourceDefinitionId.parse(
                    str(binding["definition_id"])
                ),
                definition_version_id=SourceDefinitionVersionId.parse(
                    str(binding["definition_version_id"])
                ),
                item_id=SourceItemId.parse(str(binding["item_id"])),
                revision_id=SourceRevisionId.parse(str(binding["revision_id"])),
                representation_id=DiscoveryRepresentationId.parse(
                    str(binding["representation_id"])
                ),
                passages=tuple(_passage(item) for item in passages_value),
            ),
            budget=ExtractionBudget(
                timeout_ms=int(budget["timeout_ms"]),
                max_input_bytes=int(budget["max_input_bytes"]),
                max_output_bytes=int(budget["max_output_bytes"]),
                max_proposals=int(budget["max_proposals"]),
                max_evidence_ranges=int(budget["max_evidence_ranges"]),
                max_request_tokens=int(budget["max_request_tokens"]),
                max_response_tokens=int(budget["max_response_tokens"]),
                max_cost_microunits=int(budget["max_cost_microunits"]),
            ),
            idempotency_key=idempotency_key,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError("retained extraction run is invalid") from exc


__all__ = ["decode_extraction_run", "decode_extractor_contract"]
