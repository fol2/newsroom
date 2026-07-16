from __future__ import annotations

import os
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthoritySchemaError, AuthorityWriterBusy
from newsroom.authority.migrations import MIGRATION_STATEMENTS, apply_migration

from .authority_event_helpers import open_test_system
from .authority_helpers import command, proof


def test_partial_migration_failure_rolls_back_all_schema() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        faulty = (
            "CREATE TABLE partial_table(id INTEGER PRIMARY KEY) STRICT",
            "CREATE TABLE broken(",
        )
        with pytest.raises(sqlite3.DatabaseError):
            apply_migration(
                conn,
                applied_at="2026-07-16T12:00:00.000000Z",
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


def test_migration_history_reopens_by_explicit_values(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database):
        pass
    with open_test_system(database):
        pass


def test_schema_tamper_is_detected_on_reopen(tmp_path: Path) -> None:
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


def test_raw_sql_cannot_mutate_immutable_authority_records(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        committed = system.commands.execute(command(), proof=proof())
        conn = sqlite3.connect(database, timeout=1)
        try:
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                conn.execute(
                    "UPDATE authority_commands SET command_type='tampered' "
                    "WHERE command_id=?",
                    (committed.command_id,),
                )
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                conn.execute(
                    "DELETE FROM authority_payloads WHERE payload_id=("
                    "SELECT payload_id FROM ledger_events WHERE event_id=?)",
                    (committed.event_id,),
                )
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                conn.execute(
                    "UPDATE authority_audit_events SET event_type='tampered' "
                    "WHERE command_id=?",
                    (committed.command_id,),
                )
        finally:
            conn.close()


def test_second_authority_writer_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database):
        with pytest.raises(AuthorityWriterBusy):
            open_test_system(database)


def test_database_symlink_and_broad_parent_permissions_fail_closed(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real.sqlite3"
    with open_test_system(real):
        pass
    symlink = tmp_path / "alias.sqlite3"
    symlink.symlink_to(real)
    with pytest.raises(AuthoritySchemaError, match="symlink"):
        open_test_system(symlink)

    broad = tmp_path / "broad"
    broad.mkdir(mode=0o700)
    os.chmod(broad, 0o755)
    with pytest.raises(AuthoritySchemaError, match="permissions"):
        open_test_system(broad / "authority.sqlite3")
