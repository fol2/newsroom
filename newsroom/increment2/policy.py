from __future__ import annotations

from typing import Any

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.models import CommandDefinition
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
)
from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.projection.models import ProjectionContractError


DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND = (
    "integrated.development_candidate.admit.v2"
)
DEVELOPMENT_CANDIDATE_COMMAND_TYPES = frozenset(
    {DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND}
)
_SCHEMA_VERSION = "development_candidate_admission_v2"
_CONTRACT_VERSION = "complete-fixture-proof-schema-v1"
_DEFINITION_VERSION = "complete-fixture-proof-command-v1"
_PAYLOAD_FIELDS = frozenset(
    {
        "proposal_id",
        "retrieval_context_id",
        "expected_context_digest",
        "candidate_manifest_digest",
        "semantic_collision_digest",
    }
)


def _payload_bytes(value: Any) -> bytes:
    if not isinstance(value, dict) or set(value) != set(_PAYLOAD_FIELDS):
        raise PayloadSchemaValidationError(
            "development Candidate payload fields differ from retained schema"
        )
    if any(not isinstance(value[field], str) for field in value):
        raise PayloadSchemaValidationError(
            "development Candidate payload values must be strings"
        )
    return canonical_json_bytes(value)


def development_candidate_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    vector = {field: f"fixture-{field.replace('_', '-')}" for field in sorted(_PAYLOAD_FIELDS)}
    contract = PayloadSchemaContract(
        schema_version=_SCHEMA_VERSION,
        payload_mode=PayloadMode.INLINE,
        contract_version=_CONTRACT_VERSION,
        canonicalizer_implementation_version=(
            "development-candidate-canonical-json-v1"
        ),
        canonicalizer=_payload_bytes,
        golden_vectors=(
            PayloadGoldenVector(
                name="development-candidate-exact-fields",
                input_identity="development-candidate-exact-fields-v1",
                value=vector,
                expected_bytes=_payload_bytes(vector),
            ),
        ),
    )
    return (contract,)


def development_candidate_command_definitions() -> tuple[CommandDefinition, ...]:
    contract = development_candidate_payload_contracts()[0]
    return (
        CommandDefinition(
            command_type=DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND,
            definition_version=_DEFINITION_VERSION,
            aggregate_type="development_candidate_admission_proposal",
            event_type="candidate.development.admission.decided",
            event_schema_version=2,
            payload_mode=PayloadMode.INLINE,
            payload_schema_version=contract.schema_version,
            payload_schema_contract_version=contract.contract_version,
            payload_schema_contract_digest=contract.contract_digest,
            payload_canonicalizer_version=(
                contract.canonicalizer_implementation_version
            ),
            trust_scope=TrustScope.ADMITTED,
            security_scope="authority.candidate",
            retention_scope="authority.audit",
            required_scope="authority.candidate.admit",
            max_inline_bytes=32 * 1024,
        ),
    )


def merge_development_candidate_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    definitions = list(command_registry.definitions())
    by_key = {
        (item.command_type, item.definition_version): item
        for item in definitions
    }
    for definition in development_candidate_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ProjectionContractError(
                "development Candidate command identity conflict"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition

    current_commands = {
        item.command_type: command_registry.resolve(
            item.command_type
        ).definition_version
        for item in definitions
        if item.command_type not in DEVELOPMENT_CANDIDATE_COMMAND_TYPES
    }
    current_commands[DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND] = (
        _DEFINITION_VERSION
    )

    contracts = list(payload_schemas.contracts())
    keys = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    added = development_candidate_payload_contracts()
    for contract in added:
        key = (
            contract.schema_version,
            contract.payload_mode,
            contract.contract_version,
        )
        existing = keys.get(key)
        if existing is not None and existing.contract_digest != contract.contract_digest:
            raise ProjectionContractError(
                "development Candidate payload identity conflict"
            )
        if existing is None:
            contracts.append(contract)
            keys[key] = contract

    added_versions = {item.schema_version for item in added}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in added_versions:
            current_schemas[(schema_version, mode)] = _CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = payload_schemas.resolve(
                schema_version, mode
            ).contract_version

    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND",
    "DEVELOPMENT_CANDIDATE_COMMAND_TYPES",
    "development_candidate_command_definitions",
    "development_candidate_payload_contracts",
    "merge_development_candidate_authority_registries",
]
