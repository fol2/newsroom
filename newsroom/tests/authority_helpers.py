from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from newsroom.authority import (
    AggregateId,
    AuthenticationProof,
    CommandDefinition,
    CommandRegistry,
    CommandService,
    CommittedCommandLookup,
    InlinePayload,
    PayloadGoldenVector,
    PayloadMode,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    UtcTimestamp,
    canonical_json_bytes,
)

FIXED_NOW = UtcTimestamp(datetime(2026, 7, 16, 12, 0, tzinfo=UTC))
FIXTURE_SCHEMA_VERSION = "fixture_payload_v1"
FIXTURE_SCHEMA_CONTRACT_VERSION = "fixture-contract-v1"
FIXTURE_CANONICALIZER_VERSION = "fixture-canonicalizer-v1"
FIXTURE_VECTOR_VALUE = {"headline": "Golden", "count": 1}


def fixture_payload_bytes(value: Any) -> bytes:
    if not isinstance(value, dict):
        raise PayloadSchemaValidationError("fixture payload must be an object")
    if set(value) != {"headline", "count"}:
        raise PayloadSchemaValidationError(
            "fixture payload requires exactly headline and count"
        )
    if not isinstance(value["headline"], str) or not value["headline"]:
        raise PayloadSchemaValidationError(
            "fixture headline must be non-empty"
        )
    if isinstance(value["count"], bool) or not isinstance(
        value["count"], int
    ):
        raise PayloadSchemaValidationError(
            "fixture count must be an integer"
        )
    return canonical_json_bytes(value)


def fixture_payload_contract(
    *,
    contract_version: str = FIXTURE_SCHEMA_CONTRACT_VERSION,
    canonicalizer_version: str = FIXTURE_CANONICALIZER_VERSION,
    canonicalizer: Callable[[Any], bytes] = fixture_payload_bytes,
) -> PayloadSchemaContract:
    expected = fixture_payload_bytes(FIXTURE_VECTOR_VALUE)
    return PayloadSchemaContract(
        schema_version=FIXTURE_SCHEMA_VERSION,
        payload_mode=PayloadMode.INLINE,
        contract_version=contract_version,
        canonicalizer_implementation_version=canonicalizer_version,
        canonicalizer=canonicalizer,
        golden_vectors=(
            PayloadGoldenVector(
                name="fixture_basic",
                input_identity="fixture-basic-v1",
                value=FIXTURE_VECTOR_VALUE,
                expected_bytes=expected,
            ),
        ),
    )


def observed_definition(
    *,
    version: str = "cmd-v1",
    schema_contract: PayloadSchemaContract | None = None,
) -> CommandDefinition:
    contract = schema_contract or fixture_payload_contract()
    return CommandDefinition(
        command_type="record.observed",
        definition_version=version,
        aggregate_type="fixture_record",
        event_type="fixture.observed.recorded",
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
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
        max_inline_bytes=4096,
    )


def admitted_definition(
    *,
    schema_contract: PayloadSchemaContract | None = None,
) -> CommandDefinition:
    contract = schema_contract or fixture_payload_contract()
    return CommandDefinition(
        command_type="record.admitted",
        definition_version="cmd-v1",
        aggregate_type="fixture_record",
        event_type="fixture.admitted.recorded",
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=(
            contract.canonicalizer_implementation_version
        ),
        trust_scope=TrustScope.ADMITTED,
        security_scope="authority.restricted",
        retention_scope="authority.long",
        required_scope="authority.admitted.write",
        max_inline_bytes=4096,
    )


def default_payload_schemas(
    *contracts: PayloadSchemaContract,
) -> PayloadSchemaRegistry:
    selected = contracts or (fixture_payload_contract(),)
    return PayloadSchemaRegistry(selected)


def make_service(
    *,
    policy_version: str = "authz-v1",
    scopes: frozenset[str] = frozenset({"authority.observed.write"}),
    credential: str = "token-1",
    definition_version: str = "cmd-v1",
    registry: CommandRegistry | None = None,
    payload_schemas: PayloadSchemaRegistry | None = None,
    committed_lookup: CommittedCommandLookup | None = None,
) -> CommandService:
    contract = fixture_payload_contract()
    selected_registry = registry or CommandRegistry(
        [
            observed_definition(
                version=definition_version,
                schema_contract=contract,
            ),
            admitted_definition(schema_contract=contract),
        ]
    )
    authenticator = StaticAuthenticator(
        credentials={credential: StaticPrincipal("principal.alpha")},
        authority_domain="newsroom.authority",
    )
    authorizer = StaticAuthorizer(
        policy_version=policy_version,
        grants_by_principal={"principal.alpha": scopes},
    )
    return CommandService(
        registry=selected_registry,
        payload_schemas=(
            payload_schemas or default_payload_schemas(contract)
        ),
        authenticator=authenticator,
        authorizer=authorizer,
        committed_lookup=committed_lookup,
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
