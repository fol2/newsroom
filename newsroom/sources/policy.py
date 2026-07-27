from __future__ import annotations

from collections.abc import Callable
from typing import Any

from newsroom.authority.models import CommandDefinition
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
)
from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.projection.models import ProjectionContractError

from ._definition_payloads import _definition_payload, _version_payload
from ._lineage_payloads import (
    _item_payload,
    _locator_payload,
    _occurrence_payload,
    _representation_payload,
    _revision_payload,
)
from .types import EXECUTION_AUTHORITY_DISABLED

SOURCE_DEFINITION_REGISTER_COMMAND = "source.definition.register"
SOURCE_DEFINITION_VERSION_RECORD_COMMAND = "source.definition.version.record"
SOURCE_ITEM_REGISTER_COMMAND = "source.item.register"
SOURCE_LOCATOR_CONTINUITY_DECIDE_COMMAND = "source.locator.continuity.decide"
SOURCE_REVISION_RECORD_COMMAND = "source.revision.record"
DISCOVERY_REPRESENTATION_RECORD_COMMAND = "discovery.representation.record"
DISCOVERY_OCCURRENCE_RECORD_COMMAND = "discovery.occurrence.record"
SOURCE_REGISTRY_COMMAND_TYPES = frozenset(
    {
        SOURCE_DEFINITION_REGISTER_COMMAND,
        SOURCE_DEFINITION_VERSION_RECORD_COMMAND,
        SOURCE_ITEM_REGISTER_COMMAND,
        SOURCE_LOCATOR_CONTINUITY_DECIDE_COMMAND,
        SOURCE_REVISION_RECORD_COMMAND,
        DISCOVERY_REPRESENTATION_RECORD_COMMAND,
        DISCOVERY_OCCURRENCE_RECORD_COMMAND,
    }
)

_DEFINITION_SCHEMA = "source_definition_v1"
_VERSION_SCHEMA = "source_definition_version_v1"
_ITEM_SCHEMA = "source_item_v1"
_LOCATOR_SCHEMA = "source_locator_continuity_decision_v1"
_REVISION_SCHEMA = "source_revision_v1"
_REPRESENTATION_SCHEMA = "discovery_representation_v1"
_OCCURRENCE_SCHEMA = "discovery_occurrence_v1"
_CONTRACT_VERSION = "source-registry-contract-v1"
_DEFINITION_VERSION = "source-registry-command-v1"


def source_registry_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    digest = "sha256:" + "a" * 64
    definition = {
        "definition_id": "00000000-0000-4000-8000-000000003001",
        "name": "Fixture maintained guidance",
        "editorial_purpose": "Exercise immutable source and revision contracts.",
    }
    version = {
        "version_id": "00000000-0000-4000-8000-000000003002",
        "definition_id": definition["definition_id"],
        "version_number": 1,
        "expected_previous_version_id": None,
        "locator": "fixture://increment-3a/maintained-guidance",
        "adapter_contract": {
            "policy_id": "fixture-adapter",
            "policy_version": "v1",
        },
        "extraction_scope": ["body", "source_updated_time", "title"],
        "rights": {
            "rights_decision_id": "00000000-0000-4000-8000-000000003099",
            "rights_policy_version": "fixture-rights-v1",
            "allowed_use": "discovery.fixture",
            "retention_scope": "authority.audit",
        },
        "roles": [
            {
                "role": "ORIGINATING_AUTHORITY",
                "purpose": "Observe fixture guidance revisions.",
                "limitations": ["Fixture and approved replay only."],
            }
        ],
        "portfolio_functions": ["ANCHOR"],
        "coverage_mappings": [
            {
                "obligation_id": "COV-021",
                "responsibility": "ACTIVE",
                "contribution": "REVISION_VISIBILITY",
                "geographies": ["FIXTURE"],
                "languages": ["en-GB"],
                "limitations": ["No live-source execution."],
                "explicit_gap_id": None,
            }
        ],
        "dependencies": [],
        "explicit_gaps": [],
        "observation_model": "MUTABLE_ITEM",
        "baseline_policy": {
            "reference": {
                "policy_id": "maintained-baseline",
                "policy_version": "v1",
            },
            "kind": "MAINTAINED_DOCUMENT",
            "freshness_window_seconds": None,
            "reset_requires_decision": True,
            "notes": "Initial capture is baseline only.",
        },
        "item_identity_policy": {
            "policy_id": "fixture-item-identity",
            "policy_version": "v1",
        },
        "revision_policy": {
            "policy_id": "fixture-revision-rule",
            "policy_version": "v1",
        },
        "canonicalization_policy": {
            "policy_id": "fixture-canonicalizer",
            "policy_version": "v1",
        },
        "lifecycle_stage": "RESEARCH_CANDIDATE",
        "change_reason": "Initial fixture contract.",
        "execution_authority": EXECUTION_AUTHORITY_DISABLED,
    }
    item = {
        "item_id": "00000000-0000-4000-8000-000000003003",
        "definition_id": definition["definition_id"],
        "definition_version_id": version["version_id"],
        "identity_kind": "COMPOSITE",
        "identity_policy": {
            "policy_id": "fixture-item-identity",
            "policy_version": "v1",
        },
        "source_native_id": None,
        "identity_components": [
            {"name": "document_class", "value": "guidance"},
            {"name": "publisher_key", "value": "fixture-authority"},
        ],
        "uncertainties": [],
    }
    locator = {
        "decision_id": "00000000-0000-4000-8000-000000003004",
        "definition_id": definition["definition_id"],
        "definition_version_id": version["version_id"],
        "prior_item_id": item["item_id"],
        "prior_locator": "fixture://increment-3a/old-guidance",
        "observed_locator": version["locator"],
        "outcome": "SAME_ITEM",
        "related_item_id": item["item_id"],
        "rationale": "Fixture identity rule proves continuity.",
        "decision_policy": {
            "policy_id": "fixture-locator-continuity",
            "policy_version": "v1",
        },
        "observed_at": "2042-03-12T10:00:00.000000Z",
    }
    unknown_time = {
        "precision": "UNKNOWN",
        "value": None,
        "conflicting_values": [],
    }
    revision = {
        "revision_id": "00000000-0000-4000-8000-000000003005",
        "item_id": item["item_id"],
        "definition_version_id": version["version_id"],
        "prior_revision_id": None,
        "source_native_revision_token": "fixture-revision-1",
        "permitted_state_digest": digest,
        "revision_policy": {
            "policy_id": "fixture-revision-rule",
            "policy_version": "v1",
        },
        "canonicalizer_version": "fixture-canonicalizer-v1",
        "source_published_time": unknown_time,
        "source_updated_time": unknown_time,
        "observed_at": "2042-03-12T10:00:00.000000Z",
    }
    representation = {
        "representation_id": "00000000-0000-4000-8000-000000003006",
        "revision_id": revision["revision_id"],
        "definition_version_id": version["version_id"],
        "adapter_version": "fixture-adapter-v1",
        "parser_version": "fixture-parser-v1",
        "normalizer_version": "fixture-normalizer-v1",
        "extraction_scope_version": "fixture-scope-v1",
        "permitted_fields_digest": digest,
        "representation_digest": "sha256:" + "b" * 64,
        "produced_at": "2042-03-12T10:00:01.000000Z",
    }
    occurrence = {
        "occurrence_id": "00000000-0000-4000-8000-000000003007",
        "check_outcome_id": "00000000-0000-4000-8000-000000003008",
        "revision_id": revision["revision_id"],
        "representation_id": representation["representation_id"],
        "definition_version_id": version["version_id"],
        "kind": "FIRST_OBSERVED",
        "observed_at": "2042-03-12T10:00:02.000000Z",
        "receipt_digest": "sha256:" + "c" * 64,
        "source_asserted_time": unknown_time,
    }
    specs: tuple[
        tuple[str, Callable[[Any], bytes], dict[str, Any]], ...
    ] = (
        (_DEFINITION_SCHEMA, _definition_payload, definition),
        (_VERSION_SCHEMA, _version_payload, version),
        (_ITEM_SCHEMA, _item_payload, item),
        (_LOCATOR_SCHEMA, _locator_payload, locator),
        (_REVISION_SCHEMA, _revision_payload, revision),
        (_REPRESENTATION_SCHEMA, _representation_payload, representation),
        (_OCCURRENCE_SCHEMA, _occurrence_payload, occurrence),
    )
    return tuple(
        PayloadSchemaContract(
            schema_version=schema_version,
            payload_mode=PayloadMode.INLINE,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                f"{schema_version}-canonical-json-v1"
            ),
            canonicalizer=canonicalizer,
            golden_vectors=(
                PayloadGoldenVector(
                    name=f"{schema_version}-exact-fields",
                    input_identity=f"{schema_version}-golden-v1",
                    value=vector,
                    expected_bytes=canonicalizer(vector),
                ),
            ),
        )
        for schema_version, canonicalizer, vector in specs
    )


def source_registry_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {
        item.schema_version: item for item in source_registry_payload_contracts()
    }
    specs = (
        (
            SOURCE_DEFINITION_REGISTER_COMMAND,
            "source_definition",
            "source.definition.registered",
            _DEFINITION_SCHEMA,
            TrustScope.ADMITTED,
            "authority.sources.manage",
        ),
        (
            SOURCE_DEFINITION_VERSION_RECORD_COMMAND,
            "source_definition_version",
            "source.definition.version.recorded",
            _VERSION_SCHEMA,
            TrustScope.ADMITTED,
            "authority.sources.manage",
        ),
        (
            SOURCE_ITEM_REGISTER_COMMAND,
            "source_item",
            "source.item.registered",
            _ITEM_SCHEMA,
            TrustScope.OBSERVED,
            "authority.sources.observe",
        ),
        (
            SOURCE_LOCATOR_CONTINUITY_DECIDE_COMMAND,
            "source_locator_continuity",
            "source.locator.continuity.decided",
            _LOCATOR_SCHEMA,
            TrustScope.ADMITTED,
            "authority.sources.manage",
        ),
        (
            SOURCE_REVISION_RECORD_COMMAND,
            "source_revision",
            "source.revision.recorded",
            _REVISION_SCHEMA,
            TrustScope.OBSERVED,
            "authority.sources.observe",
        ),
        (
            DISCOVERY_REPRESENTATION_RECORD_COMMAND,
            "discovery_representation",
            "discovery.representation.recorded",
            _REPRESENTATION_SCHEMA,
            TrustScope.OBSERVED,
            "authority.sources.observe",
        ),
        (
            DISCOVERY_OCCURRENCE_RECORD_COMMAND,
            "discovery_occurrence",
            "discovery.occurrence.recorded",
            _OCCURRENCE_SCHEMA,
            TrustScope.OBSERVED,
            "authority.sources.observe",
        ),
    )
    definitions: list[CommandDefinition] = []
    for (
        command_type,
        aggregate_type,
        event_type,
        schema_version,
        trust,
        scope,
    ) in specs:
        contract = contracts[schema_version]
        definitions.append(
            CommandDefinition(
                command_type=command_type,
                definition_version=_DEFINITION_VERSION,
                aggregate_type=aggregate_type,
                event_type=event_type,
                event_schema_version=1,
                payload_mode=PayloadMode.INLINE,
                payload_schema_version=contract.schema_version,
                payload_schema_contract_version=contract.contract_version,
                payload_schema_contract_digest=contract.contract_digest,
                payload_canonicalizer_version=(
                    contract.canonicalizer_implementation_version
                ),
                trust_scope=trust,
                security_scope="authority.source_registry",
                retention_scope="authority.audit",
                required_scope=scope,
                max_inline_bytes=256 * 1024,
            )
        )
    return tuple(definitions)


def merge_source_registry_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    definitions = list(command_registry.definitions())
    by_key = {
        (item.command_type, item.definition_version): item
        for item in definitions
    }
    for definition in source_registry_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ProjectionContractError(
                f"source command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands = {
        item.command_type: command_registry.resolve(
            item.command_type
        ).definition_version
        for item in definitions
        if item.command_type not in SOURCE_REGISTRY_COMMAND_TYPES
    }
    current_commands.update(
        {
            command_type: _DEFINITION_VERSION
            for command_type in SOURCE_REGISTRY_COMMAND_TYPES
        }
    )

    contracts = list(payload_schemas.contracts())
    by_schema = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    source_contracts = source_registry_payload_contracts()
    for contract in source_contracts:
        key = (
            contract.schema_version,
            contract.payload_mode,
            contract.contract_version,
        )
        existing = by_schema.get(key)
        if (
            existing is not None
            and existing.contract_digest != contract.contract_digest
        ):
            raise ProjectionContractError(
                f"source payload identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            by_schema[key] = contract
    source_versions = {item.schema_version for item in source_contracts}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in source_versions:
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
    "DISCOVERY_OCCURRENCE_RECORD_COMMAND",
    "DISCOVERY_REPRESENTATION_RECORD_COMMAND",
    "SOURCE_DEFINITION_REGISTER_COMMAND",
    "SOURCE_DEFINITION_VERSION_RECORD_COMMAND",
    "SOURCE_ITEM_REGISTER_COMMAND",
    "SOURCE_LOCATOR_CONTINUITY_DECIDE_COMMAND",
    "SOURCE_REGISTRY_COMMAND_TYPES",
    "SOURCE_REVISION_RECORD_COMMAND",
    "merge_source_registry_authority_registries",
    "source_registry_command_definitions",
    "source_registry_payload_contracts",
]
