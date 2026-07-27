from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.sources import (
    BaselinePolicy,
    BaselinePolicyKind,
    EXECUTION_AUTHORITY_DISABLED,
    IdentityComponent,
    ObservationModel,
    PortfolioFunction,
    SourceContractError,
    SourceItemIdentityKind,
    SourceItemRequest,
    VersionedPolicyRef,
    source_registry_command_definitions,
    source_registry_payload_contracts,
)

from .source_3a_helpers import (
    DEFINITION_ID,
    ITEM_ID,
    VERSION_1_ID,
    item_request,
    version_request,
)


def test_source_payload_contracts_execute_exact_golden_vectors() -> None:
    contracts = source_registry_payload_contracts()
    definitions = source_registry_command_definitions()

    assert len(contracts) == 7
    assert len(definitions) == 7
    assert len({item.command_type for item in definitions}) == 7
    by_schema = {item.schema_version: item for item in contracts}
    for definition in definitions:
        contract = by_schema[definition.payload_schema_version]
        assert definition.payload_schema_contract_digest == contract.contract_digest
        for vector in contract.golden_vectors:
            assert contract.canonicalize(vector.value) == vector.expected_bytes

    definition_contract = by_schema["source_definition_v1"]
    invalid = dict(definition_contract.golden_vectors[0].value)
    invalid["unexpected"] = True
    with pytest.raises(PayloadSchemaValidationError):
        definition_contract.canonicalize(invalid)


def test_source_definition_version_cannot_gain_execution_authority() -> None:
    request = version_request()
    assert request.execution_authority == EXECUTION_AUTHORITY_DISABLED

    with pytest.raises(SourceContractError, match="execution authority"):
        replace(request, execution_authority="LIVE_NETWORK_ENABLED")


def test_observation_model_and_baseline_policy_are_one_contract() -> None:
    request = version_request()
    with pytest.raises(SourceContractError, match="baseline policy"):
        replace(
            request,
            observation_model=ObservationModel.APPEND_ONLY,
            baseline_policy=BaselinePolicy(
                reference=VersionedPolicyRef("bad-baseline", "v1"),
                kind=BaselinePolicyKind.MAINTAINED_DOCUMENT,
            ),
        )


def test_manual_only_cannot_masquerade_as_automated_source() -> None:
    request = version_request()
    with pytest.raises(SourceContractError, match="MANUAL_ONLY"):
        replace(
            request,
            portfolio_functions=(PortfolioFunction.MANUAL_ONLY,),
        )


def test_external_locator_cannot_be_the_sole_source_item_identity() -> None:
    with pytest.raises(SourceContractError, match="sole item identity"):
        SourceItemRequest(
            item_id=ITEM_ID,
            definition_id=DEFINITION_ID,
            definition_version_id=VERSION_1_ID,
            identity_kind=SourceItemIdentityKind.COMPOSITE,
            identity_policy=VersionedPolicyRef(
                "fixture-item-identity", "v1"
            ),
            source_native_id=None,
            identity_components=(
                IdentityComponent(
                    "locator", "fixture://increment-3a/item"
                ),
                IdentityComponent("url", "https://example.invalid/item"),
            ),
            uncertainties=(),
            idempotency_key="locator-only-item",
        )


def test_idempotency_key_matches_authority_command_bound() -> None:
    with pytest.raises(SourceContractError, match="byte bound"):
        replace(item_request(), idempotency_key="x" * 257)
