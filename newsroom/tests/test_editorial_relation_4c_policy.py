from __future__ import annotations

from copy import deepcopy

import pytest

from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.relations.editorial_policy import (
    EDITORIAL_RELATION_COMMAND_TYPES,
    EDITORIAL_RELATION_DECISION_COMMAND,
    EDITORIAL_RELATION_PROPOSAL_COMMAND,
    editorial_relation_command_definitions,
    editorial_relation_payload_contracts,
    merge_editorial_relation_authority_registries,
)
from newsroom.tests.source_3a_helpers import base_registries


def test_editorial_relation_commands_and_payloads_are_exact_and_closed() -> None:
    contracts = editorial_relation_payload_contracts()
    definitions = editorial_relation_command_definitions()
    assert len(contracts) == len(definitions) == 2
    assert {item.command_type for item in definitions} == EDITORIAL_RELATION_COMMAND_TYPES
    assert {item.payload_mode for item in definitions} == {PayloadMode.INLINE}
    assert {item.security_scope for item in definitions} == {"authority.relation"}
    assert next(
        item
        for item in definitions
        if item.command_type == EDITORIAL_RELATION_PROPOSAL_COMMAND
    ).trust_scope is TrustScope.PROPOSED
    assert next(
        item
        for item in definitions
        if item.command_type == EDITORIAL_RELATION_DECISION_COMMAND
    ).trust_scope is TrustScope.ADMITTED
    for contract in contracts:
        golden = contract.golden_vectors[0]
        assert contract.canonicalize(golden.value) == golden.expected_bytes


def test_editorial_relation_payloads_reject_extra_and_noncanonical_values() -> None:
    for contract in editorial_relation_payload_contracts():
        value = deepcopy(contract.golden_vectors[0].value)
        value["unauthorised"] = True
        with pytest.raises(PayloadSchemaValidationError, match="field set"):
            contract.canonicalize(value)

    proposal = editorial_relation_payload_contracts()[0]
    value = deepcopy(proposal.golden_vectors[0].value)
    value["uncertainty_codes"] = ["Z", "A"]
    with pytest.raises(PayloadSchemaValidationError, match="sorted|canonical"):
        proposal.canonicalize(value)


def test_editorial_relation_registry_merge_is_idempotent_and_retains_entity_horizon() -> None:
    registry, schemas = base_registries()
    merged_registry, merged_schemas = merge_editorial_relation_authority_registries(
        command_registry=registry,
        payload_schemas=schemas,
    )
    for command_type in EDITORIAL_RELATION_COMMAND_TYPES:
        assert merged_registry.resolve(command_type).security_scope == "authority.relation"
    for contract in editorial_relation_payload_contracts():
        assert (
            merged_schemas.resolve(contract.schema_version, PayloadMode.INLINE)
            .contract_digest
            == contract.contract_digest
        )

    second_registry, second_schemas = merge_editorial_relation_authority_registries(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    assert [item.digest for item in second_registry.definitions()] == [
        item.digest for item in merged_registry.definitions()
    ]
    assert [item.contract_digest for item in second_schemas.contracts()] == [
        item.contract_digest for item in merged_schemas.contracts()
    ]
