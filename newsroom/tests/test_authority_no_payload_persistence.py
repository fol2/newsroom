from __future__ import annotations

from pathlib import Path

from newsroom.authority import (
    AggregateId,
    CommandDefinition,
    CommandRegistry,
    NO_PAYLOAD,
    PayloadMode,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    open_authority_event_system,
)

from .authority_helpers import FIXED_NOW, proof


def test_explicit_no_payload_event_is_replayable(tmp_path: Path) -> None:
    definition = CommandDefinition(
        command_type="fixture.ping",
        definition_version="cmd-v1",
        aggregate_type="fixture_ping",
        event_type="fixture.ping.recorded",
        event_schema_version=1,
        payload_mode=PayloadMode.NO_PAYLOAD,
        payload_schema_version="no_payload_v1",
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="authority.default",
        required_scope="authority.observed.write",
    )
    schemas = PayloadSchemaRegistry(
        [
            PayloadSchemaContract(
                schema_version="no_payload_v1",
                payload_mode=PayloadMode.NO_PAYLOAD,
                canonicalizer=lambda value: b"" if value is None else b"invalid",
            )
        ]
    )
    with open_authority_event_system(
        path=tmp_path / "authority.sqlite3",
        registry=CommandRegistry([definition]),
        payload_schemas=schemas,
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={
                "principal.alpha": frozenset(
                    {
                        "authority.observed.write",
                        "authority.events.read",
                        "authority.audit.read",
                    }
                )
            },
        ),
        clock=lambda: FIXED_NOW,
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
        assert event.event_type == "fixture.ping.recorded"
