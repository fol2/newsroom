from __future__ import annotations

from collections.abc import Callable
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.models import CommandDefinition
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
)
from newsroom.authority.types import PayloadMode, TrustScope

from .decoding import (
    extraction_attempt_from_value,
    extraction_output_from_value,
    extraction_run_from_value,
    extractor_contract_from_value,
    proposal_set_from_value,
)
from .types import ExtractionContractError

from .fixtures import (
    fixture_attempt_request,
    fixture_contract_request,
    fixture_output_request,
    fixture_proposal_set_request,
    fixture_run_request,
)

EXTRACTOR_CONTRACT_REGISTER_COMMAND = "extraction.contract.register"
EXTRACTION_RUN_REGISTER_COMMAND = "extraction.run.register"
EXTRACTION_ATTEMPT_RECORD_COMMAND = "extraction.attempt.record"
EXTRACTION_OUTPUT_RETAIN_COMMAND = "extraction.output.retain"
EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND = "extraction.proposal_set.retain"
EXTRACTION_COMMAND_TYPES = frozenset(
    {
        EXTRACTOR_CONTRACT_REGISTER_COMMAND,
        EXTRACTION_RUN_REGISTER_COMMAND,
        EXTRACTION_ATTEMPT_RECORD_COMMAND,
        EXTRACTION_OUTPUT_RETAIN_COMMAND,
        EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND,
    }
)

_CONTRACT_SCHEMA = "extractor_contract_v1"
_RUN_SCHEMA = "extraction_run_v1"
_ATTEMPT_SCHEMA = "extraction_attempt_v1"
_OUTPUT_SCHEMA = "extraction_output_v1"
_PROPOSAL_SET_SCHEMA = "extraction_proposal_set_v1"
_PAYLOAD_CONTRACT_VERSION = "increment-4a-extraction-contract-v1"
_COMMAND_DEFINITION_VERSION = "increment-4a-extraction-command-v1"


def _canonicalizer(decoder: Callable[..., Any]) -> Callable[[Any], bytes]:
    def canonicalize(value: Any) -> bytes:
        request = decoder(value, idempotency_key="payload-schema-validation")
        return canonical_json_bytes(request.canonical_value())

    return canonicalize


def _fixture_specs() -> tuple[
    tuple[str, Callable[..., Any], Any], ...
]:
    return (
        (_CONTRACT_SCHEMA, extractor_contract_from_value, fixture_contract_request()),
        (_RUN_SCHEMA, extraction_run_from_value, fixture_run_request()),
        (_ATTEMPT_SCHEMA, extraction_attempt_from_value, fixture_attempt_request()),
        (_OUTPUT_SCHEMA, extraction_output_from_value, fixture_output_request()),
        (_PROPOSAL_SET_SCHEMA, proposal_set_from_value, fixture_proposal_set_request()),
    )


def extraction_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    contracts: list[PayloadSchemaContract] = []
    for schema, decoder, request in _fixture_specs():
        canonicalizer = _canonicalizer(decoder)
        vector = request.canonical_value()
        contracts.append(
            PayloadSchemaContract(
                schema_version=schema,
                payload_mode=PayloadMode.INLINE,
                contract_version=_PAYLOAD_CONTRACT_VERSION,
                canonicalizer_implementation_version=f"{schema}-canonical-json-v1",
                canonicalizer=canonicalizer,
                golden_vectors=(
                    PayloadGoldenVector(
                        name=f"{schema}-exact-fields",
                        input_identity=f"{schema}-golden-v1",
                        value=vector,
                        expected_bytes=canonicalizer(vector),
                    ),
                ),
            )
        )
    return tuple(contracts)


def extraction_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {item.schema_version: item for item in extraction_payload_contracts()}
    specs = (
        (
            EXTRACTOR_CONTRACT_REGISTER_COMMAND,
            "extractor_contract",
            "extraction.contract.registered",
            _CONTRACT_SCHEMA,
            TrustScope.ADMITTED,
            "authority.extraction.contracts.manage",
        ),
        (
            EXTRACTION_RUN_REGISTER_COMMAND,
            "extraction_run",
            "extraction.run.registered",
            _RUN_SCHEMA,
            TrustScope.OBSERVED,
            "authority.extraction.runs.create",
        ),
        (
            EXTRACTION_ATTEMPT_RECORD_COMMAND,
            "extraction_attempt",
            "extraction.attempt.recorded",
            _ATTEMPT_SCHEMA,
            TrustScope.OBSERVED,
            "authority.extraction.attempts.record",
        ),
        (
            EXTRACTION_OUTPUT_RETAIN_COMMAND,
            "extraction_output",
            "extraction.output.retained",
            _OUTPUT_SCHEMA,
            TrustScope.OBSERVED,
            "authority.extraction.outputs.retain",
        ),
        (
            EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND,
            "extraction_proposal_set",
            "extraction.proposal_set.retained",
            _PROPOSAL_SET_SCHEMA,
            TrustScope.PROPOSED,
            "authority.extraction.proposals.retain",
        ),
    )
    return tuple(
        CommandDefinition(
            command_type=command_type,
            definition_version=_COMMAND_DEFINITION_VERSION,
            aggregate_type=aggregate_type,
            event_type=event_type,
            event_schema_version=1,
            payload_mode=PayloadMode.INLINE,
            payload_schema_version=contracts[schema].schema_version,
            payload_schema_contract_version=contracts[schema].contract_version,
            payload_schema_contract_digest=contracts[schema].contract_digest,
            payload_canonicalizer_version=contracts[schema].canonicalizer_implementation_version,
            trust_scope=trust_scope,
            security_scope="authority.extraction",
            retention_scope="authority.audit",
            required_scope=required_scope,
            max_inline_bytes=2 * 1024 * 1024,
        )
        for command_type, aggregate_type, event_type, schema, trust_scope, required_scope in specs
    )


def merge_extraction_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    definitions = list(command_registry.definitions())
    by_key = {
        (item.command_type, item.definition_version): item
        for item in definitions
    }
    for definition in extraction_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ExtractionContractError(
                f"Extraction command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands = {
        item.command_type: command_registry.resolve(item.command_type).definition_version
        for item in definitions
        if item.command_type not in EXTRACTION_COMMAND_TYPES
    }
    current_commands.update(
        {command_type: _COMMAND_DEFINITION_VERSION for command_type in EXTRACTION_COMMAND_TYPES}
    )

    contracts = list(payload_schemas.contracts())
    by_schema = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    extraction_contracts = extraction_payload_contracts()
    for contract in extraction_contracts:
        key = (contract.schema_version, contract.payload_mode, contract.contract_version)
        existing = by_schema.get(key)
        if existing is not None and existing.contract_digest != contract.contract_digest:
            raise ExtractionContractError(
                f"Extraction payload identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            by_schema[key] = contract
    extraction_versions = {item.schema_version for item in extraction_contracts}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in extraction_versions:
            current_schemas[(schema_version, mode)] = _PAYLOAD_CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = payload_schemas.resolve(
                schema_version, mode
            ).contract_version
    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "EXTRACTION_ATTEMPT_RECORD_COMMAND",
    "EXTRACTION_COMMAND_TYPES",
    "EXTRACTION_OUTPUT_RETAIN_COMMAND",
    "EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND",
    "EXTRACTION_RUN_REGISTER_COMMAND",
    "EXTRACTOR_CONTRACT_REGISTER_COMMAND",
    "extraction_command_definitions",
    "extraction_payload_contracts",
    "merge_extraction_authority_registries",
]
