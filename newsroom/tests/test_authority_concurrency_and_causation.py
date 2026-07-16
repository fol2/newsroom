from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from newsroom.authority import (
    AuthorizationDenied,
    CausationKind,
    CausationRef,
    CommandId,
    EventId,
    SemanticCommand,
    UnknownCausation,
)

from .authority_event_helpers import open_test_system
from .authority_helpers import command, proof


def test_command_and_event_causation_must_resolve(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        first = system.commands.execute(command(key="first"), proof=proof())
        command_caused = SemanticCommand(
            command_type="record.observed",
            aggregate_id=command().aggregate_id,
            expected_aggregate_version=0,
            payload=command().payload,
            idempotency_key="command-caused",
            causation=CausationRef(
                CausationKind.COMMAND, first.command_id
            ),
        )
        second = system.commands.execute(command_caused, proof=proof())
        event_caused = SemanticCommand(
            command_type="record.observed",
            aggregate_id=command().aggregate_id,
            expected_aggregate_version=0,
            payload=command().payload,
            idempotency_key="event-caused",
            causation=CausationRef(CausationKind.EVENT, second.event_id),
        )
        system.commands.execute(event_caused, proof=proof())

        unresolved_command = SemanticCommand(
            command_type="record.observed",
            aggregate_id=command().aggregate_id,
            expected_aggregate_version=0,
            payload=command().payload,
            idempotency_key="missing-command",
            causation=CausationRef(
                CausationKind.COMMAND, str(CommandId.new())
            ),
        )
        with pytest.raises(UnknownCausation):
            system.commands.execute(unresolved_command, proof=proof())

        unresolved_event = SemanticCommand(
            command_type="record.observed",
            aggregate_id=command().aggregate_id,
            expected_aggregate_version=0,
            payload=command().payload,
            idempotency_key="missing-event",
            causation=CausationRef(CausationKind.EVENT, str(EventId.new())),
        )
        with pytest.raises(UnknownCausation):
            system.commands.execute(unresolved_event, proof=proof())


def test_shared_connection_operations_are_serialized(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        def write(index: int) -> str:
            result = system.commands.execute(
                command(key=f"parallel-{index}"), proof=proof()
            )
            return result.command_id

        def read(_: int) -> int:
            return len(system.events.after(0, limit=1000, proof=proof()))

        with ThreadPoolExecutor(max_workers=8) as executor:
            command_ids = list(executor.map(write, range(20)))
            read_counts = list(executor.map(read, range(20)))
        assert len(set(command_ids)) == 20
        assert len(system.events.after(0, limit=1000, proof=proof())) == 20
        assert all(count >= 0 for count in read_counts)


def test_metadata_reader_requires_current_authorization(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(
        database,
        scopes=frozenset({"authority.observed.write"}),
    ) as system:
        system.commands.execute(command(), proof=proof())
        with pytest.raises(AuthorizationDenied):
            system.events.after(0, proof=proof())
