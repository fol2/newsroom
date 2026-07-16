from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority import (
    AggregateId,
    AuthenticationContextId,
    AuthenticationError,
    AuthenticationProof,
    AuthorityStore,
    AuthorizationDenied,
    AuthorizationRule,
    CommandService,
    StaticAuthorizer,
    VerifiedAuthenticationContext,
    UtcTimestamp,
    digest_bytes,
)

from authority_helpers import clock, command, components, proof


def test_caller_principal_and_scope_claims_have_no_authority(tmp_path: Path) -> None:
    store, _, service = components(tmp_path)
    try:
        result = service.execute(
            command(aggregate_id=AggregateId.new(), key="spoof-test"),
            proof=proof(
                claims={
                    "principal_id": "attacker",
                    "principal_scopes": "authority.admin",
                }
            ),
        )
        event = store.read_events()[0]
        audit = store.read_audit_for_command(result.command_id)
        assert event.principal_id == "writer-service"
        assert event.principal_id != "attacker"
        assert audit is not None
        assert audit.principal_id == "writer-service"
        assert audit.authentication_context_id == event.authentication_context_id
        assert audit.authorization_decision_id == event.authorization_decision_id
        assert audit.effective_scope_digest.startswith("sha256:")
    finally:
        store.close()


def test_server_side_authorization_denial_creates_no_authority(tmp_path: Path) -> None:
    store, _, service = components(tmp_path)
    try:
        with pytest.raises(AuthorizationDenied) as denied:
            service.execute(
                command(aggregate_id=AggregateId.new(), key="denied"),
                proof=proof(
                    "reader-token", claims={"principal_scopes": "authority.write"}
                ),
            )
        assert denied.value.decision.reason_code == "AUTHZ_SCOPE_MISSING"
        assert store.table_count("authority_commands") == 0
        assert store.table_count("ledger_events") == 0
    finally:
        store.close()


def test_command_service_has_no_unauthenticated_fallback(tmp_path: Path) -> None:
    store = AuthorityStore(tmp_path / "authority.sqlite3", clock=clock)
    try:
        with pytest.raises(ValueError):
            CommandService(  # type: ignore[arg-type]
                store=store,
                authenticator=None,
                authorizer=None,
                clock=clock,
            )
    finally:
        store.close()


def test_invalid_or_unsupported_authentication_fails_before_authority(
    tmp_path: Path,
) -> None:
    store, _, service = components(tmp_path)
    semantic_command = command(
        aggregate_id=AggregateId.new(), key="auth-failure"
    )
    try:
        with pytest.raises(AuthenticationError):
            service.execute(
                semantic_command, proof=proof("not-a-server-credential")
            )
        with pytest.raises(AuthenticationError):
            service.execute(
                semantic_command,
                proof=AuthenticationProof(
                    method="UNSUPPORTED", credential="writer-token"
                ),
            )
        assert store.table_count("authority_commands") == 0
    finally:
        store.close()


def test_expired_verified_context_is_rejected(tmp_path: Path) -> None:
    store = AuthorityStore(tmp_path / "authority.sqlite3", clock=clock)
    authorizer = StaticAuthorizer(
        policy_version="authority-test-policy-v1",
        grants_by_principal={"writer-service": frozenset({"authority.write"})},
        rules_by_command={
            "CREATE_RECORD": AuthorizationRule(
                "authority.write", frozenset({"fixture"})
            )
        },
    )

    class ExpiredAuthenticator:
        def authenticate(
            self, authentication_proof: AuthenticationProof, *, now: UtcTimestamp
        ) -> VerifiedAuthenticationContext:
            return VerifiedAuthenticationContext(
                authentication_context_id=AuthenticationContextId.new(),
                principal_id="writer-service",
                authority_domain="newsroom.test.authority",
                authentication_method="EXPIRED_TEST",
                assurance_class="TEST",
                credential_binding_digest=digest_bytes(b"expired-binding"),
                authenticated_at=UtcTimestamp(
                    datetime(2026, 7, 16, 17, 0, tzinfo=UTC)
                ),
                expires_at=UtcTimestamp(
                    datetime(2026, 7, 16, 17, 1, tzinfo=UTC)
                ),
            )

    late_time = UtcTimestamp(datetime(2026, 7, 16, 18, 0, tzinfo=UTC))
    service = CommandService(
        store=store,
        authenticator=ExpiredAuthenticator(),
        authorizer=authorizer,
        clock=lambda: late_time,
    )
    try:
        with pytest.raises(AuthenticationError):
            service.execute(
                command(aggregate_id=AggregateId.new(), key="expired"),
                proof=proof(),
            )
        assert store.table_count("authority_commands") == 0
    finally:
        store.close()
