from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsroom.authority import (
    AuthorizationDenied,
    ExpectedVersionConflict,
    InlinePayload,
    SemanticCommand,
    digest_bytes,
)

from .authority_event_helpers import open_test_system, registry_with_upgrade
from .authority_helpers import command, proof


def test_command_persists_event_result_and_resolvable_provenance(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        request = command()
        committed = system.commands.execute(request, proof=proof())
        assert committed.aggregate_version == 1
        events = system.events.after(0, proof=proof())
        assert len(events) == 1
        assert events[0].command_id == committed.command_id
        assert events[0].ledger_seq == committed.ledger_seq
        provenance = system.events.provenance(committed.event_id, proof=proof())
        assert provenance.authentication.principal_id == "principal.alpha"
        assert provenance.authentication.authority_domain == "newsroom.authority"
        assert provenance.authorization.allowed is True
        assert provenance.authorization.authorization_request_digest
        result = system.events.command_result(committed.command_id, proof=proof())
        assert result.result_digest == committed.result_digest
        assert digest_bytes(result.result_bytes) == result.result_digest
        value = json.loads(result.result_bytes)
        assert "result_digest" not in value
        assert value["command_id"] == committed.command_id


def test_idempotent_replay_returns_exact_result_without_second_event(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        request = command()
        first = system.commands.execute(request, proof=proof())
        second = system.commands.execute(request, proof=proof())
        assert second.replayed is True
        assert second.command_id == first.command_id
        assert second.event_id == first.event_id
        assert second.result_digest == first.result_digest
        assert len(system.events.after(0, proof=proof())) == 1


def test_lost_response_replay_uses_historical_definition_after_upgrade(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    request = command()
    with open_test_system(database) as system:
        first = system.commands.execute(request, proof=proof())
    with open_test_system(
        database,
        registry=registry_with_upgrade(),
        policy_version="authz-v2",
    ) as upgraded:
        replay = upgraded.commands.execute(request, proof=proof())
        assert replay.replayed is True
        assert replay.command_id == first.command_id
        assert len(upgraded.events.after(0, proof=proof())) == 1


def test_lost_response_replay_is_denied_when_current_authority_is_removed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    request = command()
    with open_test_system(database) as system:
        system.commands.execute(request, proof=proof())
    with open_test_system(
        database,
        policy_version="authz-v2",
        scopes=frozenset({"authority.events.read", "authority.audit.read"}),
    ) as denied:
        with pytest.raises(AuthorizationDenied):
            denied.commands.execute(request, proof=proof())


def test_expected_version_fencing_and_append_only_versions(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    aggregate_id = command().aggregate_id
    with open_test_system(database) as system:
        first = system.commands.execute(
            command(aggregate_id=aggregate_id, expected_version=0, key="create"),
            proof=proof(),
        )
        second_request = SemanticCommand(
            command_type="record.observed",
            aggregate_id=aggregate_id,
            expected_aggregate_version=1,
            payload=InlinePayload({"headline": "Updated", "count": 2}),
            idempotency_key="update",
        )
        second = system.commands.execute(second_request, proof=proof())
        assert first.aggregate_version == 1
        assert second.aggregate_version == 2
        assert [event.aggregate_version for event in system.events.after(0, proof=proof())] == [1, 2]
        with pytest.raises(ExpectedVersionConflict):
            system.commands.execute(
                command(
                    aggregate_id=aggregate_id,
                    expected_version=1,
                    key="stale",
                ),
                proof=proof(),
            )
