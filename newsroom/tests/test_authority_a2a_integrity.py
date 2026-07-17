from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    AuthoritySchemaError,
    AuthorityWriterBusy,
    CausationKind,
    CausationRef,
    CommandId,
    EventId,
    ExpectedVersionConflict,
    InlinePayload,
    SemanticCommand,
    UnknownCausation,
)
from newsroom.authority.migrations import apply_migration

from .authority_event_helpers import open_test_system
from .authority_helpers import command, proof


def test_partial_migration_failure_is_atomic() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        faulty = (
            "CREATE TABLE partial_table(id INTEGER PRIMARY KEY) STRICT",
            "CREATE TABLE broken(",
        )
        with pytest.raises(sqlite3.DatabaseError):
            apply_migration(
                conn,
                applied_at="2026-07-17T00:00:00.000000Z",
                statements=faulty,
            )
        names = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "partial_table" not in names
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 0
    finally:
        conn.close()


def test_reopen_validates_history_schema_and_relational_integrity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        system.commands.execute(command(), proof=proof())
    with open_test_system(database) as reopened:
        assert len(reopened.events.after(0, proof=proof())) == 1


def test_schema_tamper_fails_and_constructor_releases_writer_lock(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database):
        pass

    conn = sqlite3.connect(database)
    try:
        conn.execute("DROP INDEX idx_ledger_events_recorded")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthoritySchemaError, match="fingerprint"):
        open_test_system(database)

    # A failed constructor must not retain the lifetime writer lock.
    conn = sqlite3.connect(database)
    try:
        conn.execute(
            "CREATE INDEX idx_ledger_events_recorded "
            "ON ledger_events(recorded_at, ledger_seq)"
        )
        conn.commit()
    finally:
        conn.close()
    with open_test_system(database):
        pass


def test_raw_sql_cannot_mutate_append_only_records(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        committed = system.commands.execute(command(), proof=proof())
        conn = sqlite3.connect(database, timeout=1)
        try:
            mutations = (
                (
                    "UPDATE authority_commands "
                    "SET command_type='tampered' WHERE command_id=?",
                    (committed.command_id,),
                ),
                (
                    "DELETE FROM authority_payloads WHERE payload_id=("
                    "SELECT payload_id FROM ledger_events WHERE event_id=?)",
                    (committed.event_id,),
                ),
                (
                    "UPDATE authority_audit_events "
                    "SET event_type='tampered' WHERE command_id=?",
                    (committed.command_id,),
                ),
                ("DELETE FROM authorization_requests", ()),
                (
                    "UPDATE payload_schema_contracts "
                    "SET contract_version='tampered'",
                    (),
                ),
            )
            for sql, parameters in mutations:
                with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                    conn.execute(sql, parameters)
        finally:
            conn.close()


def test_aggregate_head_tamper_is_detected_on_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        system.commands.execute(command(), proof=proof())

    # Simulate an out-of-contract raw writer, then restore the exact schema so
    # startup relational validation—not fingerprint drift—detects the damage.
    conn = sqlite3.connect(database)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DROP TRIGGER authority_aggregates_update_guard")
        conn.execute(
            "UPDATE authority_aggregates SET current_version=current_version+1"
        )
        conn.execute(
            """CREATE TRIGGER authority_aggregates_update_guard
            BEFORE UPDATE ON authority_aggregates
            WHEN NEW.aggregate_type != OLD.aggregate_type
              OR NEW.aggregate_id != OLD.aggregate_id
              OR NEW.current_version != OLD.current_version + 1
              OR NEW.created_at != OLD.created_at
            BEGIN SELECT RAISE(ABORT,'invalid aggregate-head update'); END"""
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="aggregate head"):
        open_test_system(database)


def test_every_command_has_one_version_audit_and_event(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        for index in range(3):
            system.commands.execute(
                command(key=f"command-{index}"), proof=proof()
            )
    conn = sqlite3.connect(database)
    try:
        counts = conn.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM authority_commands),"
            "(SELECT COUNT(*) FROM authority_aggregate_versions),"
            "(SELECT COUNT(*) FROM authority_audit_events),"
            "(SELECT COUNT(*) FROM ledger_events)"
        ).fetchone()
        assert counts == (3, 3, 3, 3)
    finally:
        conn.close()


def test_second_lifetime_writer_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database):
        with pytest.raises(AuthorityWriterBusy):
            open_test_system(database)


def test_symlink_and_broad_parent_permissions_fail_closed(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real.sqlite3"
    with open_test_system(real):
        pass
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(real)
    with pytest.raises(AuthoritySchemaError, match="symlink"):
        open_test_system(alias)

    broad = tmp_path / "broad"
    broad.mkdir(mode=0o700)
    os.chmod(broad, 0o755)
    with pytest.raises(AuthoritySchemaError, match="permissions"):
        open_test_system(broad / "authority.sqlite3")


def test_command_and_event_causation_must_resolve(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        first = system.commands.execute(command(key="first"), proof=proof())
        second = system.commands.execute(
            SemanticCommand(
                command_type="record.observed",
                aggregate_id=command().aggregate_id,
                expected_aggregate_version=0,
                payload=command().payload,
                idempotency_key="command-caused",
                causation=CausationRef(CausationKind.COMMAND, first.command_id),
            ),
            proof=proof(),
        )
        system.commands.execute(
            SemanticCommand(
                command_type="record.observed",
                aggregate_id=command().aggregate_id,
                expected_aggregate_version=0,
                payload=command().payload,
                idempotency_key="event-caused",
                causation=CausationRef(CausationKind.EVENT, second.event_id),
            ),
            proof=proof(),
        )

        with pytest.raises(UnknownCausation):
            system.commands.execute(
                SemanticCommand(
                    command_type="record.observed",
                    aggregate_id=command().aggregate_id,
                    expected_aggregate_version=0,
                    payload=command().payload,
                    idempotency_key="missing-command",
                    causation=CausationRef(
                        CausationKind.COMMAND, str(CommandId.new())
                    ),
                ),
                proof=proof(),
            )
        with pytest.raises(UnknownCausation):
            system.commands.execute(
                SemanticCommand(
                    command_type="record.observed",
                    aggregate_id=command().aggregate_id,
                    expected_aggregate_version=0,
                    payload=command().payload,
                    idempotency_key="missing-event",
                    causation=CausationRef(
                        CausationKind.EVENT, str(EventId.new())
                    ),
                ),
                proof=proof(),
            )


def test_expected_version_fencing_is_atomic(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    aggregate_id = command().aggregate_id
    with open_test_system(database) as system:
        system.commands.execute(
            command(
                aggregate_id=aggregate_id,
                expected_version=0,
                key="create",
            ),
            proof=proof(),
        )
        system.commands.execute(
            SemanticCommand(
                command_type="record.observed",
                aggregate_id=aggregate_id,
                expected_aggregate_version=1,
                payload=InlinePayload({"headline": "Updated", "count": 2}),
                idempotency_key="update",
            ),
            proof=proof(),
        )
        with pytest.raises(ExpectedVersionConflict):
            system.commands.execute(
                command(
                    aggregate_id=aggregate_id,
                    expected_version=1,
                    key="stale",
                ),
                proof=proof(),
            )
        assert [
            event.aggregate_version
            for event in system.events.after(0, proof=proof())
        ] == [1, 2]


def test_shared_connection_reads_and_writes_are_serialized(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        def write(index: int) -> str:
            return system.commands.execute(
                command(key=f"parallel-{index}"),
                proof=proof(),
            ).command_id

        def read(_: int) -> int:
            return len(system.events.after(0, limit=100, proof=proof()))

        with ThreadPoolExecutor(max_workers=8) as executor:
            command_ids = list(executor.map(write, range(20)))
            read_counts = list(executor.map(read, range(20)))
        assert len(set(command_ids)) == 20
        assert len(system.events.after(0, limit=100, proof=proof())) == 20
        assert all(count >= 0 for count in read_counts)


def test_read_time_provenance_validation_fails_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        committed = system.commands.execute(command(), proof=proof())

        # Simulate an out-of-contract raw writer while the accepted process is
        # alive. Read-time canonical verification must still fail closed.
        conn = sqlite3.connect(database)
        try:
            conn.execute(
                "DROP TRIGGER immutable_authorization_requests_update"
            )
            conn.execute(
                "UPDATE authorization_requests SET canonical_bytes=?",
                (b'{"tampered":true}',),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(AuthorityPersistenceError, match="request"):
            system.events.provenance(committed.event_id, proof=proof())
