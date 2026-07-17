from __future__ import annotations

import json
from pathlib import Path

from newsroom.authority import (
    AggregateId,
    CommandDefinition,
    CommandRegistry,
    NO_PAYLOAD,
    PayloadMode,
    SemanticCommand,
    TrustScope,
    digest_bytes,
)

from .authority_event_helpers import (
    no_payload_contract,
    open_test_system,
    payload_schemas,
)
from .authority_helpers import (
    FIXED_NOW,
    command,
    fixture_payload_contract,
    proof,
)


def test_event_envelope_and_exact_provenance_are_complete(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    contract = fixture_payload_contract()
    with open_test_system(database) as system:
        committed = system.commands.execute(
            command(), proof=proof()
        )
        events = system.events.after(0, proof=proof())
        assert len(events) == 1
        event = events[0]

        assert event.ledger_seq == committed.ledger_seq == 1
        assert event.event_id == committed.event_id
        assert event.event_type == "fixture.observed.recorded"
        assert event.event_schema_version == 1
        assert event.aggregate_type == "fixture_record"
        assert event.aggregate_version == 1
        assert event.recorded_at == FIXED_NOW.to_text()
        assert event.producer_version == "authority-command-v1"
        assert event.command_definition_version == "cmd-v1"
        assert event.command_definition_digest.startswith("sha256:")
        assert event.payload_id
        assert event.payload_mode == "INLINE"
        assert event.payload_schema_version == contract.schema_version
        assert (
            event.payload_schema_contract_version
            == contract.contract_version
        )
        assert (
            event.payload_schema_contract_digest
            == contract.contract_digest
        )
        assert (
            event.payload_canonicalizer_version
            == contract.canonicalizer_implementation_version
        )
        assert event.payload_digest.startswith("sha256:")
        assert event.object_admission_id is None
        assert event.principal_id == "principal.alpha"
        assert event.authentication_context_id
        assert event.authorization_request_digest
        assert event.authorization_decision_id
        assert event.security_scope == "authority.internal"
        assert event.retention_scope == "authority.default"
        assert event.trust_scope == "OBSERVED"
        assert not hasattr(event, "payload_bytes")

        provenance = system.events.provenance(
            event.event_id, proof=proof()
        )
        assert provenance.event == event
        assert (
            provenance.authentication.authentication_context_id
            == provenance.authorization_request.authentication_context_id
            == provenance.authorization_decision.authentication_context_id
            == event.authentication_context_id
        )
        assert (
            provenance.authorization_request.request_digest
            == provenance.authorization_decision.authorization_request_digest
            == event.authorization_request_digest
        )
        assert (
            provenance.authorization_decision.authorization_decision_id
            == event.authorization_decision_id
        )
        assert (
            digest_bytes(
                provenance.authentication.canonical_bytes
            )
            == provenance.authentication.canonical_digest
        )
        assert (
            digest_bytes(
                provenance.authorization_request.canonical_bytes
            )
            == provenance.authorization_request.canonical_record_digest
        )
        assert (
            digest_bytes(
                provenance.authorization_decision.canonical_bytes
            )
            == provenance.authorization_decision.canonical_digest
        )
        assert (
            digest_bytes(
                provenance.command_definition.canonical_bytes
            )
            == provenance.command_definition.definition_digest
        )
        assert (
            digest_bytes(
                provenance.payload_schema_contract.canonical_bytes
            )
            == provenance.payload_schema_contract.contract_digest
        )
        assert (
            provenance.authorization_request.operation_type
            == "command:record.observed"
        )
        assert (
            provenance.authorization_request.required_scope
            == "authority.observed.write"
        )

        result = system.events.command_result(
            committed.command_id, proof=proof()
        )
        assert result.result_digest == committed.result_digest
        assert digest_bytes(result.result_bytes) == result.result_digest
        result_value = json.loads(result.result_bytes)
        assert "result_digest" not in result_value
        assert result_value["command_id"] == committed.command_id


def test_no_payload_event_retains_explicit_empty_authority(
    tmp_path: Path,
) -> None:
    contract = no_payload_contract()
    definition = CommandDefinition(
        command_type="fixture.ping",
        definition_version="cmd-v1",
        aggregate_type="fixture_ping",
        event_type="fixture.ping.recorded",
        event_schema_version=1,
        payload_mode=PayloadMode.NO_PAYLOAD,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=(
            contract.canonicalizer_implementation_version
        ),
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="authority.default",
        required_scope="authority.observed.write",
    )
    with open_test_system(
        tmp_path / "authority.sqlite3",
        registry=CommandRegistry([definition]),
        payload_schema_registry=payload_schemas(contract),
    ) as system:
        committed = system.commands.execute(
            SemanticCommand(
                command_type="fixture.ping",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=NO_PAYLOAD,
                idempotency_key="ping-1",
            ),
            proof=proof(),
        )
        event = system.events.after(0, proof=proof())[0]
        assert event.command_id == committed.command_id
        assert event.payload_mode == "NO_PAYLOAD"
        assert event.payload_digest == digest_bytes(b"")
        assert event.object_admission_id is None
