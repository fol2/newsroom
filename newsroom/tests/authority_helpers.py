from __future__ import annotations

from datetime import UTC, datetime

from newsroom.authority import (
    AggregateId,
    AuthenticationProof,
    CommandDefinition,
    CommandRegistry,
    CommandService,
    InlinePayload,
    PayloadMode,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    UtcTimestamp,
)

FIXED_NOW = UtcTimestamp(datetime(2026, 7, 16, 12, 0, tzinfo=UTC))


def observed_definition(*, version: str = "cmd-v1") -> CommandDefinition:
    return CommandDefinition(
        command_type="record.observed",
        definition_version=version,
        aggregate_type="fixture_record",
        event_type="fixture.observed.recorded",
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
        payload_schema_version="fixture_payload_v1",
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="authority.default",
        required_scope="authority.observed.write",
        max_inline_bytes=4096,
    )


def admitted_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="record.admitted",
        definition_version="cmd-v1",
        aggregate_type="fixture_record",
        event_type="fixture.admitted.recorded",
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
        payload_schema_version="fixture_payload_v1",
        trust_scope=TrustScope.ADMITTED,
        security_scope="authority.restricted",
        retention_scope="authority.long",
        required_scope="authority.admitted.write",
        max_inline_bytes=4096,
    )


def make_service(
    *,
    policy_version: str = "authz-v1",
    scopes: frozenset[str] = frozenset({"authority.observed.write"}),
    credential: str = "token-1",
    definition_version: str = "cmd-v1",
) -> CommandService:
    registry = CommandRegistry([observed_definition(version=definition_version), admitted_definition()])
    authenticator = StaticAuthenticator(
        credentials={credential: StaticPrincipal("principal.alpha")},
        authority_domain="newsroom.authority",
    )
    authorizer = StaticAuthorizer(
        policy_version=policy_version,
        grants_by_principal={"principal.alpha": scopes},
    )
    return CommandService(
        registry=registry,
        authenticator=authenticator,
        authorizer=authorizer,
        clock=lambda: FIXED_NOW,
    )


def command(
    *,
    command_type: str = "record.observed",
    aggregate_id: AggregateId | None = None,
    expected_version: int = 0,
    key: str = "idem-1",
) -> SemanticCommand:
    return SemanticCommand(
        command_type=command_type,
        aggregate_id=aggregate_id or AggregateId.new(),
        expected_aggregate_version=expected_version,
        payload=InlinePayload({"headline": "Example", "count": 1}),
        idempotency_key=key,
    )


def proof(*, credential: str = "token-1") -> AuthenticationProof:
    return AuthenticationProof(
        method="STATIC_TOKEN",
        credential=credential,
        untrusted_claims={
            "principal_id": "attacker",
            "scope": "authority.admitted.write",
        },
    )
