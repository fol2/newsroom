from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import (
    AggregateId,
    AuthorizationRule,
    CommandService,
    ExpectedVersionConflict,
    IdempotencyConflict,
    RightsStatus,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    UnknownObjectReference,
    digest_bytes,
)

from authority_helpers import FIXED_TIME, clock, command, components, proof


def test_idempotent_replay_returns_one_committed_result(tmp_path: Path) -> None:
    store, _, service = components(tmp_path)
    aggregate_id = AggregateId.new()
    semantic_command = command(aggregate_id=aggregate_id, key="stable-key")
    try:
        first = service.execute(semantic_command, proof=proof())
        second = service.execute(semantic_command, proof=proof())
        assert first.replayed is False
        assert second.replayed is True
        assert second.command_id == first.command_id
        assert second.event_id == first.event_id
        assert second.ledger_seq == first.ledger_seq == 1
        assert store.table_count("authority_commands") == 1
        assert store.table_count("authority_aggregate_versions") == 1
        assert store.table_count("ledger_events") == 1
        assert store.table_count("authority_audit_events") == 1
    finally:
        store.close()


def test_same_key_cannot_cross_aggregate_or_expected_version(tmp_path: Path) -> None:
    store, _, service = components(tmp_path)
    aggregate_id = AggregateId.new()
    try:
        service.execute(command(aggregate_id=aggregate_id, key="collision-key"), proof=proof())
        with pytest.raises(IdempotencyConflict):
            service.execute(
                command(aggregate_id=AggregateId.new(), key="collision-key"),
                proof=proof(),
            )
        with pytest.raises(IdempotencyConflict):
            service.execute(
                command(aggregate_id=aggregate_id, key="collision-key", expected=1),
                proof=proof(),
            )
        assert store.get_current_version("fixture", str(aggregate_id)) == 1
        assert store.table_count("authority_commands") == 1
    finally:
        store.close()


def test_different_command_type_has_a_distinct_server_namespace(tmp_path: Path) -> None:
    store, _, service = components(tmp_path)
    aggregate_id = AggregateId.new()
    try:
        created = service.execute(
            command(aggregate_id=aggregate_id, key="same-client-key"), proof=proof()
        )
        updated = service.execute(
            command(
                aggregate_id=aggregate_id,
                key="same-client-key",
                expected=1,
                command_type="UPDATE_RECORD",
                payload=b'{"fixture":"two"}',
            ),
            proof=proof(),
        )
        assert int(created.aggregate_version) == 1
        assert int(updated.aggregate_version) == 2
        assert updated.ledger_seq == 2
        assert store.table_count("authority_commands") == 2
    finally:
        store.close()


def test_stale_expected_version_fails_without_mutation(tmp_path: Path) -> None:
    store, _, service = components(tmp_path)
    aggregate_id = AggregateId.new()
    try:
        service.execute(command(aggregate_id=aggregate_id, key="create"), proof=proof())
        tables = (
            "authority_commands",
            "authority_aggregate_versions",
            "authority_audit_events",
            "ledger_events",
        )
        counts_before = {table: store.table_count(table) for table in tables}
        with pytest.raises(ExpectedVersionConflict):
            service.execute(
                command(
                    aggregate_id=aggregate_id,
                    key="stale-update",
                    expected=0,
                    command_type="UPDATE_RECORD",
                ),
                proof=proof(),
            )
        assert store.get_current_version("fixture", str(aggregate_id)) == 1
        assert {table: store.table_count(table) for table in tables} == counts_before
    finally:
        store.close()


def test_object_backed_command_requires_verified_registered_object(
    tmp_path: Path,
) -> None:
    store, object_store, service = components(tmp_path)
    payload = b"governed fixture bytes"
    digest = digest_bytes(payload)
    aggregate_id = AggregateId.new()
    try:
        with pytest.raises(UnknownObjectReference):
            service.execute(
                command(
                    aggregate_id=aggregate_id,
                    key="missing-object",
                    payload=payload,
                    payload_object_ref=digest,
                ),
                proof=proof(),
            )
        governed_object = object_store.install(
            payload,
            object_class="fixture.capture",
            rights_status=RightsStatus.PERMITTED,
            security_scope="authority.internal",
            retention_scope="test.short",
            installed_at=FIXED_TIME,
        )
        store.register_governed_object(governed_object, object_store=object_store)
        result = service.execute(
            command(
                aggregate_id=aggregate_id,
                key="registered-object",
                payload=payload,
                payload_object_ref=digest,
            ),
            proof=proof(),
        )
        assert int(result.aggregate_version) == 1
        assert store.referenced_object_digests() == frozenset({digest})
    finally:
        store.close()


def test_same_key_conflicts_when_authority_policy_context_changes(
    tmp_path: Path,
) -> None:
    store, object_store, service_v1 = components(tmp_path)
    aggregate_id = AggregateId.new()
    semantic_command = command(aggregate_id=aggregate_id, key="policy-sensitive")
    try:
        service_v1.execute(semantic_command, proof=proof())
        authenticator = StaticAuthenticator(
            credentials={"writer-token": StaticPrincipal("writer-service")},
            authority_domain="newsroom.test.authority",
        )
        authorizer_v2 = StaticAuthorizer(
            policy_version="authority-test-policy-v2",
            grants_by_principal={
                "writer-service": frozenset({"authority.write"})
            },
            rules_by_command={
                "CREATE_RECORD": AuthorizationRule(
                    "authority.write", frozenset({"fixture"})
                )
            },
        )
        service_v2 = CommandService(
            store=store,
            authenticator=authenticator,
            authorizer=authorizer_v2,
            object_store=object_store,
            clock=clock,
        )
        with pytest.raises(IdempotencyConflict):
            service_v2.execute(semantic_command, proof=proof())
        assert store.table_count("authority_commands") == 1
    finally:
        store.close()
