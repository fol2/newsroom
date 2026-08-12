from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority import migrations
from newsroom.authority.event_hypothesis_lineage_migrations import (
    EVENT_HYPOTHESIS_LINEAGE_MIGRATION_CHECKSUM,
    EVENT_HYPOTHESIS_LINEAGE_MIGRATION_NAME,
    EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT,
    EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_MIGRATION_CHECKSUM,
    EventHypothesisLineageBackupError,
    event_hypothesis_lineage_backup_paths,
    prepare_event_hypothesis_lineage_backup,
)
from newsroom.authority.migrations import (
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.tests.graphiti_adapter_4d_migration_helpers import (
    drop_empty_v23_lineage_schema,
)


def _fresh(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at="2042-01-01T00:00:00.000000Z")
    return connection


def test_literal_v23_predecessor_and_schema_pins(tmp_path: Path) -> None:
    connection = _fresh(tmp_path / "fresh.sqlite3")
    assert (
        EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_MIGRATION_CHECKSUM
        == "sha256:e59eb222a95e2901ccaae29ce1b9e8eded797306e9796718a6d2c4fa505a6636"
    )
    assert (
        EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT
        == "sha256:2118fa893fb7fd2911bbde3056b79b1d0e26ccd6903e1c4228616f342898eaad"
    )
    assert (
        EVENT_HYPOTHESIS_LINEAGE_MIGRATION_CHECKSUM
        == "sha256:6c24d402f246f4e82a49a9772d70677d922282aae3b6dde93c62c0ef9b1b7a72"
    )
    assert connection.execute(
        "SELECT name FROM authority_migrations WHERE version=23"
    ).fetchone() == (EVENT_HYPOTHESIS_LINEAGE_MIGRATION_NAME,)
    assert {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'event_hypothesis_lineage%'"
        )
    } == {"event_hypothesis_lineage", "event_hypothesis_lineage_heads"}


def test_exact_v22_default_connection_backup_upgrade_and_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "upgrade.sqlite3"
    initial = _fresh(database)
    drop_empty_v23_lineage_schema(initial)
    assert (
        schema_fingerprint(initial) == EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT
    )
    initial.close()
    connection = sqlite3.connect(database)
    backup, _ = event_hypothesis_lineage_backup_paths(database)
    prepare_event_hypothesis_lineage_backup(connection, backup)
    assert connection.in_transaction is False
    monkeypatch.setattr(
        migrations,
        "EVENT_HYPOTHESIS_LINEAGE_MIGRATION_STATEMENTS",
        migrations.EVENT_HYPOTHESIS_LINEAGE_MIGRATION_STATEMENTS
        + ("CREATE TABLE injected_failure(",),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at="2042-01-02T00:00:00.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (22,)
    monkeypatch.undo()
    apply_pending_migrations(connection, applied_at="2042-01-02T00:00:00.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)


def test_v22_requires_backup_and_v24_fails_closed(tmp_path: Path) -> None:
    connection = _fresh(tmp_path / "required.sqlite3")
    drop_empty_v23_lineage_schema(connection)
    with pytest.raises(EventHypothesisLineageBackupError, match="prepared backup"):
        apply_pending_migrations(connection, applied_at="2042-01-02T00:00:00.000000Z")
    newer = sqlite3.connect(":memory:", isolation_level=None)
    newer.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(sqlite3.DatabaseError, match="newer"):
        apply_pending_migrations(newer, applied_at="2042-01-02T00:00:00.000000Z")


def _downgrade_snapshot(connection: sqlite3.Connection) -> tuple[object, ...]:
    return (
        connection.execute("PRAGMA user_version").fetchone(),
        connection.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall(),
        connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall(),
        connection.execute("SELECT COUNT(*) FROM event_hypothesis_lineage").fetchone(),
        connection.execute(
            "SELECT COUNT(*) FROM event_hypothesis_lineage_heads"
        ).fetchone(),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-trigger",
        "tampered-sql",
        "corrupt-history",
        "version-mismatch",
        "nonempty",
    ),
)
def test_checked_v23_downgrade_failure_is_atomic(tmp_path: Path, mutation: str) -> None:
    connection = _fresh(tmp_path / f"{mutation}.sqlite3")
    if mutation == "missing-trigger":
        connection.execute("DROP TRIGGER event_hypothesis_lineage_head_update_guard")
    elif mutation == "tampered-sql":
        connection.execute("DROP TRIGGER event_hypothesis_lineage_coherence")
        connection.execute(
            "CREATE TRIGGER event_hypothesis_lineage_coherence BEFORE INSERT "
            "ON event_hypothesis_lineage BEGIN SELECT 1; END"
        )
    elif mutation == "corrupt-history":
        connection.execute("DROP TRIGGER immutable_authority_migrations_update")
        connection.execute(
            "UPDATE authority_migrations SET checksum=? WHERE version=23",
            ("sha256:" + "0" * 64,),
        )
    elif mutation == "version-mismatch":
        connection.execute("PRAGMA user_version=22")
    else:
        receipt_bytes = (
            b'{"expected_generation":0,"kind":"HYPOTHESIS_CONSOLIDATION",'
            b'"lineage_id":"fixture-lineage","reversal_target":null,'
            b'"schema_version":"newsroom.increment6.hypothesis-lineage.v1"}'
        )
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO event_hypothesis_lineage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "fixture-lineage",
                "00000000-0000-4000-8000-000000000001",
                "fixture-event",
                "HYPOTHESIS_CONSOLIDATION",
                0,
                receipt_bytes,
                "sha256:" + "1" * 64,
                None,
                None,
                "sha256:" + "2" * 64,
                "2042-01-01T00:00:00.000000Z",
            ),
        )
    before = _downgrade_snapshot(connection)
    with pytest.raises(sqlite3.DatabaseError):
        drop_empty_v23_lineage_schema(connection)
    assert _downgrade_snapshot(connection) == before
