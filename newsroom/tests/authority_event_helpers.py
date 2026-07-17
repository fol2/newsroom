from __future__ import annotations

from pathlib import Path
from typing import FrozenSet

from newsroom.authority import (
    AuthorityEventSystem,
    CommandRegistry,
    EventReadPolicy,
    MetadataClass,
    PayloadGoldenVector,
    PayloadMode,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    open_authority_event_system,
)

from .authority_helpers import (
    FIXED_NOW,
    admitted_definition,
    fixture_payload_contract,
    observed_definition,
)


def registry_v1() -> CommandRegistry:
    contract = fixture_payload_contract()
    return CommandRegistry(
        [
            observed_definition(schema_contract=contract),
            admitted_definition(schema_contract=contract),
        ]
    )


def registry_with_upgrade() -> CommandRegistry:
    contract = fixture_payload_contract()
    return CommandRegistry(
        [
            observed_definition(
                version="cmd-v1", schema_contract=contract
            ),
            observed_definition(
                version="cmd-v2", schema_contract=contract
            ),
            admitted_definition(schema_contract=contract),
        ],
        current_versions={
            "record.observed": "cmd-v2",
            "record.admitted": "cmd-v1",
        },
    )


def no_payload_contract() -> PayloadSchemaContract:
    return PayloadSchemaContract(
        schema_version="no_payload_v1",
        payload_mode=PayloadMode.NO_PAYLOAD,
        contract_version="no-payload-contract-v1",
        canonicalizer_implementation_version="no-payload-canonicalizer-v1",
        canonicalizer=lambda value: (
            b""
            if value is None
            else (_ for _ in ()).throw(
                ValueError("no payload accepts None only")
            )
        ),
        golden_vectors=(
            PayloadGoldenVector(
                name="empty",
                input_identity="none-v1",
                value=None,
                expected_bytes=b"",
            ),
        ),
    )


def payload_schemas(
    *extra: PayloadSchemaContract,
) -> PayloadSchemaRegistry:
    return PayloadSchemaRegistry(
        (fixture_payload_contract(), *extra)
    )


def fixture_read_policy(
    *,
    principal_id: str = "principal.alpha",
    allowed_security_scopes: FrozenSet[str] = frozenset(
        {"authority.internal"}
    ),
    allowed_trust_scopes: FrozenSet[TrustScope] = frozenset(
        {TrustScope.OBSERVED}
    ),
    metadata_classes: FrozenSet[MetadataClass] = frozenset(
        {
            MetadataClass.ROUTING,
            MetadataClass.PROVENANCE,
            MetadataClass.RESULT,
        }
    ),
    minimum_ledger_seq: int = 1,
    maximum_ledger_seq: int | None = None,
    max_results: int = 100,
) -> EventReadPolicy:
    return EventReadPolicy(
        policy_id="fixture-consumer-v1",
        purpose="fixture.consumer",
        required_scope="authority.fixture.events.read",
        allowed_principal_ids=frozenset({principal_id}),
        allowed_security_scopes=allowed_security_scopes,
        allowed_trust_scopes=allowed_trust_scopes,
        metadata_classes=metadata_classes,
        minimum_ledger_seq=minimum_ledger_seq,
        maximum_ledger_seq=maximum_ledger_seq,
        max_results=max_results,
    )


def open_test_system(
    path: Path,
    *,
    registry: CommandRegistry | None = None,
    payload_schema_registry: PayloadSchemaRegistry | None = None,
    policy_version: str = "authz-v1",
    credential: str = "token-1",
    principal_id: str = "principal.alpha",
    scopes: frozenset[str] | None = None,
    read_policy: EventReadPolicy | None = None,
    command_service_version: str = "authority-command-v1",
) -> AuthorityEventSystem:
    policy = read_policy or fixture_read_policy(
        principal_id=principal_id
    )
    grants = (
        scopes
        if scopes is not None
        else frozenset(
            {
                "authority.observed.write",
                "authority.admitted.write",
                policy.required_scope,
            }
        )
    )
    return open_authority_event_system(
        path=path,
        registry=registry or registry_v1(),
        payload_schemas=(
            payload_schema_registry or payload_schemas()
        ),
        authenticator=StaticAuthenticator(
            credentials={
                credential: StaticPrincipal(principal_id)
            },
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version=policy_version,
            grants_by_principal={principal_id: grants},
        ),
        event_read_policy=policy,
        command_service_version=command_service_version,
        clock=lambda: FIXED_NOW,
    )
