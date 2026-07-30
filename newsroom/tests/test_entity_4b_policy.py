from __future__ import annotations

from copy import deepcopy

import pytest

from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.entities.policy import (
    ENTITY_COMMAND_TYPES,
    ENTITY_MENTION_ADMIT_COMMAND,
    ENTITY_RESOLUTION_DECIDE_COMMAND,
    entity_command_definitions,
    entity_payload_contracts,
    merge_entity_authority_registries,
)
from newsroom.authority.object_policy import merge_authority_registries
from newsroom.sources.policy import merge_source_registry_authority_registries
from newsroom.tests.source_3a_helpers import base_registries


def test_entity_command_and_payload_contracts_are_exact_and_closed() -> None:
    contracts = entity_payload_contracts()
    definitions = entity_command_definitions()
    assert len(contracts) == len(definitions) == 6
    assert {item.command_type for item in definitions} == ENTITY_COMMAND_TYPES
    assert {item.payload_mode for item in definitions} == {PayloadMode.INLINE}
    assert {item.security_scope for item in definitions} == {"authority.entity"}
    assert {item.retention_scope for item in definitions} == {"authority.audit"}
    assert next(
        item for item in definitions if item.command_type == ENTITY_MENTION_ADMIT_COMMAND
    ).trust_scope is TrustScope.PROPOSED
    assert next(
        item for item in definitions if item.command_type == ENTITY_RESOLUTION_DECIDE_COMMAND
    ).trust_scope is TrustScope.ADMITTED
    for contract in contracts:
        golden = contract.golden_vectors[0]
        assert contract.canonicalize(golden.value) == golden.expected_bytes


def test_entity_payload_contracts_reject_extra_fields_and_noncanonical_arrays() -> None:
    for contract in entity_payload_contracts():
        golden = contract.golden_vectors[0]
        extra = deepcopy(golden.value)
        extra["unauthorised"] = True
        with pytest.raises(PayloadSchemaValidationError, match="field set"):
            contract.canonicalize(extra)

    proposal = entity_payload_contracts()[1]
    value = deepcopy(proposal.golden_vectors[0].value)
    value["uncertainty_codes"] = ["Z", "A"]
    with pytest.raises(PayloadSchemaValidationError, match="sorted|canonical"):
        proposal.canonicalize(value)


def test_entity_registry_merge_retains_extraction_horizon_and_is_idempotent() -> None:
    registry, schemas = base_registries()
    registry, schemas = merge_source_registry_authority_registries(
        command_registry=registry,
        payload_schemas=schemas,
    )
    registry, schemas = merge_authority_registries(
        command_registry=registry,
        payload_schemas=schemas,
    )
    merged_registry, merged_schemas = merge_entity_authority_registries(
        command_registry=registry,
        payload_schemas=schemas,
    )
    for command_type in ENTITY_COMMAND_TYPES:
        assert merged_registry.resolve(command_type).security_scope == "authority.entity"
    for contract in entity_payload_contracts():
        assert (
            merged_schemas.resolve(contract.schema_version, PayloadMode.INLINE)
            .contract_digest
            == contract.contract_digest
        )

    second_registry, second_schemas = merge_entity_authority_registries(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    assert [item.digest for item in second_registry.definitions()] == [
        item.digest for item in merged_registry.definitions()
    ]
    assert [item.contract_digest for item in second_schemas.contracts()] == [
        item.contract_digest for item in merged_schemas.contracts()
    ]
