from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from newsroom.authority import (
    AggregateId,
    AuthenticationProof,
    AuthorityStore,
    AuthorizationRule,
    CommandService,
    GovernedObjectStore,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    UtcTimestamp,
    digest_bytes,
)

FIXED_TIME = UtcTimestamp(datetime(2026, 7, 16, 18, 0, tzinfo=UTC))


def clock() -> UtcTimestamp:
    return FIXED_TIME


def components(
    tmp_path: Path,
    *,
    grants: frozenset[str] = frozenset({"authority.write"}),
) -> tuple[AuthorityStore, GovernedObjectStore, CommandService]:
    store = AuthorityStore(tmp_path / "authority.sqlite3", clock=clock)
    object_store = GovernedObjectStore(tmp_path / "objects")
    authenticator = StaticAuthenticator(
        credentials={
            "writer-token": StaticPrincipal("writer-service"),
            "reader-token": StaticPrincipal("reader-service"),
        },
        authority_domain="newsroom.test.authority",
    )
    authorizer = StaticAuthorizer(
        policy_version="authority-test-policy-v1",
        grants_by_principal={
            "writer-service": grants,
            "reader-service": frozenset({"authority.read"}),
        },
        rules_by_command={
            "CREATE_RECORD": AuthorizationRule(
                "authority.write", frozenset({"fixture"})
            ),
            "UPDATE_RECORD": AuthorizationRule(
                "authority.write", frozenset({"fixture"})
            ),
        },
    )
    service = CommandService(
        store=store,
        authenticator=authenticator,
        authorizer=authorizer,
        object_store=object_store,
        clock=clock,
    )
    return store, object_store, service


def command(
    *,
    aggregate_id: AggregateId,
    key: str,
    expected: int = 0,
    command_type: str = "CREATE_RECORD",
    payload: bytes = b'{"fixture":"one"}',
    payload_object_ref: str | None = None,
) -> SemanticCommand:
    return SemanticCommand(
        command_type=command_type,
        aggregate_type="fixture",
        aggregate_id=aggregate_id,
        expected_aggregate_version=expected,
        payload_schema_version="fixture_v1",
        payload_digest=digest_bytes(payload),
        payload_object_ref=payload_object_ref,
        idempotency_key=key,
        issued_at=FIXED_TIME,
        producer_version="test-suite-v1",
        event_type="FIXTURE_RECORDED",
        trust_scope=TrustScope.OBSERVED,
        correlation_id="corr-fixture",
    )


def proof(
    credential: str = "writer-token",
    *,
    claims: dict[str, str] | None = None,
) -> AuthenticationProof:
    return AuthenticationProof(
        method="STATIC_TOKEN",
        credential=credential,
        untrusted_claims=claims or {},
    )
