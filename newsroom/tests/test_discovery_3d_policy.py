from __future__ import annotations

from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.discovery import (
    DISCOVERY_GATE_DECIDE_COMMAND,
    DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND,
    DISCOVERY_LEAD_OPEN_COMMAND,
    DISCOVERY_SIGNAL_ADMIT_COMMAND,
    DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES,
    DISCOVERY_WATCH_CONDITION_RECORD_COMMAND,
    discovery_signal_lead_command_definitions,
    discovery_signal_lead_payload_contracts,
    merge_discovery_signal_lead_registries,
)

from .authority_event_helpers import payload_schemas, registry_v1


_EXPECTED_SCOPES = {
    DISCOVERY_SIGNAL_ADMIT_COMMAND: "authority.discovery.signals.admit",
    DISCOVERY_GATE_DECIDE_COMMAND: "authority.discovery.gates.decide",
    DISCOVERY_LEAD_OPEN_COMMAND: "authority.discovery.leads.open",
    DISCOVERY_WATCH_CONDITION_RECORD_COMMAND: "authority.discovery.watch.manage",
    DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND: (
        "authority.discovery.leads.disposition"
    ),
}


def test_discovery_payload_contracts_have_exact_golden_vectors() -> None:
    contracts = discovery_signal_lead_payload_contracts()
    assert len(contracts) == 5
    assert len({item.contract_digest for item in contracts}) == 5
    for contract in contracts:
        assert contract.payload_mode is PayloadMode.INLINE
        assert len(contract.golden_vectors) == 1
        vector = contract.golden_vectors[0]
        assert contract.canonicalizer(vector.value) == vector.expected_bytes


def test_discovery_commands_use_distinct_scopes_and_admitted_trust() -> None:
    definitions = discovery_signal_lead_command_definitions()
    assert {item.command_type for item in definitions} == (
        DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES
    )
    for definition in definitions:
        assert definition.required_scope == _EXPECTED_SCOPES[definition.command_type]
        assert definition.trust_scope is TrustScope.ADMITTED
        assert definition.security_scope == "authority.discovery"
        assert definition.retention_scope == "authority.audit"
        assert definition.payload_mode is PayloadMode.INLINE


def test_discovery_registry_merge_preserves_existing_authority() -> None:
    commands, schemas = merge_discovery_signal_lead_registries(
        command_registry=registry_v1(),
        payload_schemas=payload_schemas(),
    )
    for command_type in DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES:
        assert commands.resolve(command_type).required_scope == _EXPECTED_SCOPES[
            command_type
        ]
    for contract in discovery_signal_lead_payload_contracts():
        assert (
            schemas.resolve(contract.schema_version, PayloadMode.INLINE).contract_digest
            == contract.contract_digest
        )
    assert commands.resolve("record.observed").command_type == "record.observed"
