from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    prepare_pending_migration_backup,
    schema_fingerprint,
)
from newsroom.authority.triage_work_item_migrations import (
    TRIAGE_WORK_ITEM_MIGRATION_CHECKSUM,
    TRIAGE_WORK_ITEM_MIGRATION_NAME,
    TRIAGE_WORK_ITEM_PREDECESSOR_FINGERPRINT,
    TRIAGE_WORK_ITEM_SCHEMA_VERSION,
    triage_work_item_backup_paths,
)


def _open(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def test_current_schema_retains_exact_v18_and_is_integral() -> None:
    connection = _open(":memory:")
    apply_pending_migrations(connection, applied_at="2042-03-12T10:00:00Z")
    assert SCHEMA_VERSION == 19 and TRIAGE_WORK_ITEM_SCHEMA_VERSION == 18
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
    assert connection.execute(
        "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
    ).fetchall() == list(EXPECTED_MIGRATION_HISTORY)
    assert EXPECTED_MIGRATION_HISTORY[-2] == (
        18,
        TRIAGE_WORK_ITEM_MIGRATION_NAME,
        TRIAGE_WORK_ITEM_MIGRATION_CHECKSUM,
    )
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(triage_work_item_versions)")
    }
    assert {"watch_condition_id", "source_lead_disposition_id"} <= columns
    unique_columns = {
        tuple(
            row[2]
            for row in connection.execute(
                f"PRAGMA index_info({index[1]!r})"
            )
        )
        for index in connection.execute(
            "PRAGMA index_list(triage_work_item_versions)"
        )
        if index[2]
    }
    assert ("watch_condition_id",) in unique_columns
    assert ("source_lead_disposition_id",) in unique_columns
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(
            "INSERT INTO triage_work_items VALUES(?,?,?,?,?,?,?)",
            (
                "00000000-0000-4000-8000-000000000001",
                "newsroom.increment6.triage-work-item.v1",
                "sha256:" + "1" * 64,
                1,
                b"x" * (32 * 1024 + 1),
                "sha256:" + "2" * 64,
                "2042-03-12T10:00:00Z",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(
            "INSERT INTO triage_work_items VALUES(?,?,?,?,?,?,?)",
            (
                "00000000-0000-4000-8000-000000000002",
                "newsroom.increment6.triage-work-item.v1",
                "sha256:" + "3" * 64,
                1,
                b"{}",
                "sha256:not-a-digest",
                "2042-03-12T10:00:00Z",
            ),
        )


def test_exact_v17_upgrade_retains_pre_v18_backup(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    connection = _open(database)
    apply_pending_migrations(connection, applied_at="2042-03-12T10:00:00Z")
    connection.execute("PRAGMA foreign_keys=OFF")
    delete_guard = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    for table in (
        "triage_proposal_dispositions",
        "triage_proposal_validation_findings",
        "triage_work_item_heads",
        "triage_work_item_versions",
        "triage_work_items",
    ):
        connection.execute(f'DROP TABLE "{table}"')
    connection.execute("DELETE FROM authority_migrations WHERE version>=18")
    connection.execute(delete_guard)
    connection.execute("PRAGMA user_version=17")
    connection.execute("PRAGMA foreign_keys=ON")
    assert schema_fingerprint(connection) == TRIAGE_WORK_ITEM_PREDECESSOR_FINGERPRINT

    receipt = prepare_pending_migration_backup(connection)
    assert receipt is not None
    apply_pending_migrations(connection, applied_at="2042-03-12T10:00:01Z")
    backup, digest = triage_work_item_backup_paths(database)
    assert backup.is_file() and digest.is_file()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 19


def test_newer_schema_and_injected_v18_failure_fail_closed() -> None:
    newer = _open(":memory:")
    newer.execute("PRAGMA user_version=20")
    with pytest.raises(sqlite3.DatabaseError, match="newer"):
        apply_pending_migrations(newer, applied_at="2042-03-12T10:00:00Z")

    fresh = _open(":memory:")
    from newsroom.authority import migrations

    original = migrations.TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS
    migrations.TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS = original + ("INVALID SQL",)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            apply_pending_migrations(fresh, applied_at="2042-03-12T10:00:00Z")
    finally:
        migrations.TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS = original
    assert fresh.execute("PRAGMA user_version").fetchone()[0] == 0
    assert (
        fresh.execute(
            "SELECT name FROM sqlite_master WHERE name='triage_work_items'"
        ).fetchall()
        == []
    )
