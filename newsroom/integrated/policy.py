from __future__ import annotations

from typing import Any

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.models import (
    CommandDefinition,
    ObjectAdmissionDescriptor,
)
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
)
from newsroom.authority.types import (
    ObjectAdmissionId,
    PayloadMode,
    TrustScope,
)
from newsroom.projection.models import ProjectionContractError
from newsroom.projection.policy import merge_projection_authority_registries


INTEGRATED_FIXTURE_COMMAND = "integrated.fixture.record"
CANDIDATE_ADMISSION_COMMAND = "integrated.candidate.admit"
INTEGRATED_COMMAND_TYPES = frozenset(
    {INTEGRATED_FIXTURE_COMMAND, CANDIDATE_ADMISSION_COMMAND}
)

_FIXTURE_SCHEMA_VERSION = "integrated_fixture_object_v1"
_CANDIDATE_SCHEMA_VERSION = "integrated_candidate_admission_v1"
_CONTRACT_VERSION = "integrated-foundation-schema-v1"

_CANDIDATE_PAYLOAD_FIELDS = frozenset(
    {
        "proposal_id",
        "route",
        "fixture_id",
        "retrieval_context_digest",
        "manifest_digest",
        "semantic_collision_digest",
    }
)


def _object_reference_bytes(value: Any) -> bytes:
    if not isinstance(value, ObjectAdmissionDescriptor):
        raise PayloadSchemaValidationError(
            "integrated fixture requires an object-admission descriptor"
        )
    return canonical_json_bytes(
        {
            "admission_id": str(value.admission_id),
            "blob_digest": value.blob_digest,
            "object_class": value.object_class,
            "allowed_use": value.allowed_use,
            "security_scope": value.security_scope,
            "retention_scope": value.retention_scope,
        }
    )


def _candidate_payload_bytes(value: Any) -> bytes:
    if not isinstance(value, dict) or set(value) != set(
        _CANDIDATE_PAYLOAD_FIELDS
    ):
        raise PayloadSchemaValidationError(
            "candidate admission payload fields differ from retained schema"
        )
    if any(not isinstance(value[field], str) for field in value):
        raise PayloadSchemaValidationError(
            "candidate admission payload values must be strings"
        )
    return canonical_json_bytes(value)


def integrated_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    fixture_vector = ObjectAdmissionDescriptor(
        admission_id=ObjectAdmissionId.parse(
            "00000000-0000-4000-8000-000000000201"
        ),
        blob_digest="sha256:" + "a" * 64,
        object_class="source_capture",
        allowed_use="project.discovery",
        security_scope="authority.protected",
        retention_scope="source.short",
        active=True,
    )
    candidate_vector = {
        field: f"fixture-{field.replace('_', '-')}"
        for field in sorted(_CANDIDATE_PAYLOAD_FIELDS)
    }
    return (
        PayloadSchemaContract(
            schema_version=_FIXTURE_SCHEMA_VERSION,
            payload_mode=PayloadMode.OBJECT_ADMISSION,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                "integrated-object-reference-canonicalizer-v1"
            ),
            canonicalizer=_object_reference_bytes,
            golden_vectors=(
                PayloadGoldenVector(
                    name="integrated-object-reference",
                    input_identity="integrated-object-reference-v1",
                    value=fixture_vector,
                    expected_bytes=_object_reference_bytes(fixture_vector),
                ),
            ),
        ),
        PayloadSchemaContract(
            schema_version=_CANDIDATE_SCHEMA_VERSION,
            payload_mode=PayloadMode.INLINE,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                "integrated-candidate-canonical-json-v1"
            ),
            canonicalizer=_candidate_payload_bytes,
            golden_vectors=(
                PayloadGoldenVector(
                    name="candidate-exact-fields",
                    input_identity="candidate-exact-fields-v1",
                    value=candidate_vector,
                    expected_bytes=_candidate_payload_bytes(candidate_vector),
                ),
            ),
        ),
    )


def integrated_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {
        item.schema_version: item for item in integrated_payload_contracts()
    }
    fixture = contracts[_FIXTURE_SCHEMA_VERSION]
    candidate = contracts[_CANDIDATE_SCHEMA_VERSION]
    return (
        CommandDefinition(
            command_type=INTEGRATED_FIXTURE_COMMAND,
            definition_version="integrated-foundation-command-v1",
            aggregate_type="integrated_fixture",
            event_type="authority.aggregate.versioned",
            event_schema_version=1,
            payload_mode=PayloadMode.OBJECT_ADMISSION,
            payload_schema_version=fixture.schema_version,
            payload_schema_contract_version=fixture.contract_version,
            payload_schema_contract_digest=fixture.contract_digest,
            payload_canonicalizer_version=(
                fixture.canonicalizer_implementation_version
            ),
            trust_scope=TrustScope.OBSERVED,
            security_scope="authority.protected",
            retention_scope="source.short",
            required_scope="authority.observed.write",
            required_object_class="source_capture",
            required_allowed_use="project.discovery",
        ),
        CommandDefinition(
            command_type=CANDIDATE_ADMISSION_COMMAND,
            definition_version="integrated-foundation-command-v1",
            aggregate_type="candidate_admission_proposal",
            event_type="candidate.admission.decided",
            event_schema_version=1,
            payload_mode=PayloadMode.INLINE,
            payload_schema_version=candidate.schema_version,
            payload_schema_contract_version=candidate.contract_version,
            payload_schema_contract_digest=candidate.contract_digest,
            payload_canonicalizer_version=(
                candidate.canonicalizer_implementation_version
            ),
            trust_scope=TrustScope.ADMITTED,
            security_scope="authority.integrated",
            retention_scope="authority.audit",
            required_scope="authority.candidate.admit",
            max_inline_bytes=32 * 1024,
        ),
    )


def merge_integrated_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    commands, schemas = merge_projection_authority_registries(
        command_registry=command_registry,
        payload_schemas=payload_schemas,
    )

    definitions = list(commands.definitions())
    by_key = {
        (item.command_type, item.definition_version): item
        for item in definitions
    }
    for definition in integrated_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ProjectionContractError(
                f"integrated command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition

    current_commands = {
        item.command_type: commands.resolve(item.command_type).definition_version
        for item in definitions
        if item.command_type not in INTEGRATED_COMMAND_TYPES
    }
    current_commands.update(
        {
            command_type: "integrated-foundation-command-v1"
            for command_type in INTEGRATED_COMMAND_TYPES
        }
    )

    contracts = list(schemas.contracts())
    schema_keys = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    integrated_contracts = integrated_payload_contracts()
    for contract in integrated_contracts:
        key = (
            contract.schema_version,
            contract.payload_mode,
            contract.contract_version,
        )
        existing = schema_keys.get(key)
        if (
            existing is not None
            and existing.contract_digest != contract.contract_digest
        ):
            raise ProjectionContractError(
                f"integrated payload identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            schema_keys[key] = contract

    integrated_schema_versions = {
        item.schema_version for item in integrated_contracts
    }
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in integrated_schema_versions:
            current_schemas[(schema_version, mode)] = _CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = schemas.resolve(
                schema_version, mode
            ).contract_version

    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "CANDIDATE_ADMISSION_COMMAND",
    "INTEGRATED_COMMAND_TYPES",
    "INTEGRATED_FIXTURE_COMMAND",
    "integrated_command_definitions",
    "integrated_payload_contracts",
    "merge_integrated_authority_registries",
]
