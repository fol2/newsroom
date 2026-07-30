from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)

from .types import (
    ExtractionContractError,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionProposalKind,
    FixtureExtractionCase,
)

if TYPE_CHECKING:
    from .models import (
        ExtractorContractRequest,
        ExtractionRunRequest,
        ProducedExtraction,
        ProposalDraft,
    )

FIXTURE_OUTPUT_SCHEMA_ID = "newsroom.fixture.output-schema"
FIXTURE_OUTPUT_SCHEMA_VERSION = "v1"
FIXTURE_OUTPUT_SCHEMA_NAME = "increment-4a-fixture-output-v1"
HOMONYM_FIXTURE_OUTPUT_SCHEMA_VERSION = "v2-homonym"
HOMONYM_FIXTURE_OUTPUT_SCHEMA_NAME = "increment-4b-homonym-fixture-output-v1"


def _fixture_output_schema(
    *,
    schema_name: str,
    schema_urn: str,
    cases: tuple[FixtureExtractionCase, ...],
    entity_count: int,
    equivalence_count: int,
    relation_minimum: int,
    relation_maximum: int,
) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_urn,
        "type": "object",
        "required": [
            "entities",
            "equivalences",
            "fixture_case",
            "relations",
            "schema_version",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": schema_name},
            "fixture_case": {"enum": [case.value for case in cases]},
            "entities": {
                "type": "array",
                "minItems": entity_count,
                "maxItems": entity_count,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "required": ["local_id", "text"],
                    "additionalProperties": False,
                    "properties": {
                        "local_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 256,
                        },
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                    },
                },
            },
            "equivalences": {
                "type": "array",
                "minItems": equivalence_count,
                "maxItems": equivalence_count,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "required": ["local_id", "object", "subject"],
                    "additionalProperties": False,
                    "properties": {
                        "local_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 256,
                        },
                        "subject": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                        "object": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                    },
                },
            },
            "relations": {
                "type": "array",
                "minItems": relation_minimum,
                "maxItems": relation_maximum,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "required": ["local_id", "object", "predicate", "subject"],
                    "additionalProperties": False,
                    "properties": {
                        "local_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 256,
                        },
                        "subject": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                        "object": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                        "predicate": {
                            "enum": [
                                "ABOUT_EVENT",
                                "CORRECTS",
                                "DEVELOPMENT_OF",
                                "DISPUTES",
                                "SAME_EVENT_AS",
                                "SAME_PROCESS_AS",
                                "SUPERSEDES",
                                "SUPPORTS",
                            ]
                        },
                    },
                },
            },
        },
    }


FIXTURE_OUTPUT_SCHEMA = _fixture_output_schema(
    schema_name=FIXTURE_OUTPUT_SCHEMA_NAME,
    schema_urn="urn:newsroom:increment-4a:fixture-output:v1",
    cases=(
        FixtureExtractionCase.BILINGUAL_COMPLETE,
        FixtureExtractionCase.BILINGUAL_PARTIAL,
    ),
    entity_count=2,
    equivalence_count=1,
    relation_minimum=0,
    relation_maximum=1,
)
HOMONYM_FIXTURE_OUTPUT_SCHEMA = _fixture_output_schema(
    schema_name=HOMONYM_FIXTURE_OUTPUT_SCHEMA_NAME,
    schema_urn="urn:newsroom:increment-4b:homonym-fixture-output:v1",
    cases=(FixtureExtractionCase.BILINGUAL_HOMONYM,),
    entity_count=4,
    equivalence_count=2,
    relation_minimum=0,
    relation_maximum=0,
)

Draft202012Validator.check_schema(FIXTURE_OUTPUT_SCHEMA)
Draft202012Validator.check_schema(HOMONYM_FIXTURE_OUTPUT_SCHEMA)
_FIXTURE_OUTPUT_VALIDATOR = Draft202012Validator(FIXTURE_OUTPUT_SCHEMA)
_HOMONYM_FIXTURE_OUTPUT_VALIDATOR = Draft202012Validator(
    HOMONYM_FIXTURE_OUTPUT_SCHEMA
)
FIXTURE_OUTPUT_SCHEMA_DIGEST = digest_canonical(FIXTURE_OUTPUT_SCHEMA)
HOMONYM_FIXTURE_OUTPUT_SCHEMA_DIGEST = digest_canonical(
    HOMONYM_FIXTURE_OUTPUT_SCHEMA
)


def fixture_output_schema_contract(
    fixture_case: FixtureExtractionCase,
) -> tuple[str, str, str]:
    if not isinstance(fixture_case, FixtureExtractionCase):
        raise ExtractionContractError("fixture case must be typed")
    if fixture_case is FixtureExtractionCase.BILINGUAL_HOMONYM:
        return (
            FIXTURE_OUTPUT_SCHEMA_ID,
            HOMONYM_FIXTURE_OUTPUT_SCHEMA_VERSION,
            HOMONYM_FIXTURE_OUTPUT_SCHEMA_DIGEST,
        )
    return (
        FIXTURE_OUTPUT_SCHEMA_ID,
        FIXTURE_OUTPUT_SCHEMA_VERSION,
        FIXTURE_OUTPUT_SCHEMA_DIGEST,
    )


def _fixture_output_schema_for_case(
    fixture_case: FixtureExtractionCase,
) -> tuple[str, Draft202012Validator]:
    if not isinstance(fixture_case, FixtureExtractionCase):
        raise ExtractionContractError("fixture case must be typed")
    if fixture_case is FixtureExtractionCase.BILINGUAL_HOMONYM:
        return (
            HOMONYM_FIXTURE_OUTPUT_SCHEMA_NAME,
            _HOMONYM_FIXTURE_OUTPUT_VALIDATOR,
        )
    return FIXTURE_OUTPUT_SCHEMA_NAME, _FIXTURE_OUTPUT_VALIDATOR


def fixture_output_schema_name_for_case(
    fixture_case: FixtureExtractionCase,
) -> str:
    """Return the exact retained schema name for one closed fixture case."""

    return _fixture_output_schema_for_case(fixture_case)[0]


def _expected_output(
    *,
    fixture_case: FixtureExtractionCase,
    proposals: tuple["ProposalDraft", ...],
) -> dict[str, object]:
    unsupported = tuple(
        item.local_id
        for item in proposals
        if item.kind is ExtractionProposalKind.CLAIM
    )
    if unsupported:
        raise ExtractionContractError(
            "the fixed Increment 4A output schema does not admit claim proposals"
        )
    schema_name, _ = _fixture_output_schema_for_case(fixture_case)
    return {
        "schema_version": schema_name,
        "fixture_case": fixture_case.value,
        "entities": [
            {"local_id": item.local_id, "text": item.subject_placeholder}
            for item in proposals
            if item.kind is ExtractionProposalKind.ENTITY_MENTION
        ],
        "equivalences": [
            {
                "local_id": item.local_id,
                "subject": item.subject_placeholder,
                "object": item.object_placeholder,
            }
            for item in proposals
            if item.kind is ExtractionProposalKind.ENTITY_EQUIVALENCE
        ],
        "relations": [
            {
                "local_id": item.local_id,
                "subject": item.subject_placeholder,
                "object": item.object_placeholder,
                "predicate": (
                    None
                    if item.predicate_hint is None
                    else item.predicate_hint.value
                ),
            }
            for item in proposals
            if item.kind is ExtractionProposalKind.RELATION
        ],
    }


def _validate_proposal_evidence(
    *,
    request: "ExtractionRunRequest",
    production: "ProducedExtraction",
) -> None:
    for proposal in production.proposals:
        for evidence in proposal.evidence:
            passage = request.input_binding.passage(evidence.passage_id)
            data = passage.require_text().encode("utf-8")
            if evidence.end_byte > len(data):
                raise ExtractionContractError(
                    "proposal evidence exceeds its governed passage"
                )
            if (
                digest_bytes(data[evidence.start_byte : evidence.end_byte])
                != evidence.evidence_text_digest
            ):
                raise ExtractionContractError(
                    "proposal evidence digest differs from governed bytes"
                )


def require_fixture_output_contract(
    contract: "ExtractorContractRequest",
    *,
    fixture_case: FixtureExtractionCase | None = None,
) -> None:
    from .fixtures import fixture_case_for_contract
    from .models import ExtractorContractRequest

    if not isinstance(contract, ExtractorContractRequest):
        raise TypeError("fixture output validation needs a typed extractor contract")
    selected_case = (
        fixture_case_for_contract(contract)
        if fixture_case is None
        else fixture_case
    )
    if not isinstance(selected_case, FixtureExtractionCase):
        raise ExtractionContractError("fixture case must be typed")
    component_id, component_version, component_digest = (
        fixture_output_schema_contract(selected_case)
    )
    if (
        contract.output_schema.component_id != component_id
        or contract.output_schema.component_version != component_version
        or contract.output_schema.contract_digest != component_digest
    ):
        raise ExtractionContractError(
            "extractor output-schema contract is incompatible with its fixture case"
        )


def validate_fixture_production(
    *,
    contract: "ExtractorContractRequest",
    request: "ExtractionRunRequest",
    production: "ProducedExtraction",
) -> None:
    """Independently validate untrusted producer output before authority commit."""

    from .fixtures import fixture_case_for_contract
    from .models import ExtractorContractRequest, ExtractionRunRequest, ProducedExtraction

    if not isinstance(contract, ExtractorContractRequest):
        raise TypeError("fixture output validation needs a typed extractor contract")
    if not isinstance(request, ExtractionRunRequest):
        raise TypeError("fixture output validation needs a typed extraction request")
    if not isinstance(production, ProducedExtraction):
        raise TypeError("fixture output validation needs typed producer output")

    raw = production.raw_output_value
    if raw is None:
        # A producer or policy failure has no structured output to validate.
        # The exact contract was checked before producer invocation and is
        # checked again by the normalisation boundary for defence in depth.
        return
    fixture_case = fixture_case_for_contract(contract)
    require_fixture_output_contract(contract, fixture_case=fixture_case)
    schema_name, validator = _fixture_output_schema_for_case(fixture_case)
    errors = tuple(validator.iter_errors(raw))
    expected = _expected_output(
        fixture_case=fixture_case, proposals=production.proposals
    )
    if production.validation is ExtractionOutputValidation.INVALID:
        if not errors and raw == expected:
            raise ExtractionContractError(
                "output marked INVALID conforms to the approved schema and proposals"
            )
        return
    if production.validation is not ExtractionOutputValidation.VALID:
        raise ExtractionContractError("retained output has no valid validation state")
    if errors:
        raise ExtractionContractError(
            "output marked VALID violates the approved structured-output schema"
        )
    if raw != expected:
        raise ExtractionContractError(
            "valid structured output differs from its retained proposal envelopes"
        )


def normalize_fixture_production(
    *,
    contract: "ExtractorContractRequest",
    request: "ExtractionRunRequest",
    production: "ProducedExtraction",
) -> "ProducedExtraction":
    """Convert malformed untrusted output into retained invalid-output authority."""

    from .fixtures import fixture_case_for_contract
    from .models import ProducedExtraction

    if not isinstance(production, ProducedExtraction):
        raise TypeError("fixture output normalisation needs typed producer output")
    production.usage.require_within(request.budget)
    if production.usage.input_bytes != request.input_binding.input_bytes:
        raise ExtractionContractError(
            "producer input usage differs from exact passage bytes"
        )
    # Every outcome, including no-output failures, remains bound to the exact
    # repository-owned fixture contract. A producer bug cannot make an
    # incompatible framework/prompt/policy contract look like a valid retry.
    fixture_case = fixture_case_for_contract(contract)
    require_fixture_output_contract(contract, fixture_case=fixture_case)
    if production.raw_output_value is None:
        validate_fixture_production(
            contract=contract, request=request, production=production
        )
        return production

    if production.validation is ExtractionOutputValidation.INVALID:
        validate_fixture_production(
            contract=contract, request=request, production=production
        )
        return production
    try:
        validate_fixture_production(
            contract=contract, request=request, production=production
        )
        _validate_proposal_evidence(
            request=request, production=production
        )
    except ExtractionContractError:
        raw_bytes = canonical_json_bytes(production.raw_output_value)
        invalid = replace(
            production,
            outcome=ExtractionOutcome.INVALID_OUTPUT,
            failure_code=ExtractionFailureCode.OUTPUT_SCHEMA_INVALID,
            validation=ExtractionOutputValidation.INVALID,
            proposals=(),
            usage=replace(
                production.usage,
                output_bytes=len(raw_bytes),
                proposal_count=0,
                evidence_range_count=0,
            ),
        )
        validate_fixture_production(
            contract=contract, request=request, production=invalid
        )
        return invalid
    return production


__all__ = [
    "FIXTURE_OUTPUT_SCHEMA",
    "FIXTURE_OUTPUT_SCHEMA_DIGEST",
    "FIXTURE_OUTPUT_SCHEMA_ID",
    "FIXTURE_OUTPUT_SCHEMA_NAME",
    "FIXTURE_OUTPUT_SCHEMA_VERSION",
    "HOMONYM_FIXTURE_OUTPUT_SCHEMA",
    "HOMONYM_FIXTURE_OUTPUT_SCHEMA_DIGEST",
    "HOMONYM_FIXTURE_OUTPUT_SCHEMA_NAME",
    "HOMONYM_FIXTURE_OUTPUT_SCHEMA_VERSION",
    "fixture_output_schema_contract",
    "fixture_output_schema_name_for_case",
    "normalize_fixture_production",
    "require_fixture_output_contract",
    "validate_fixture_production",
]
