from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority import migrations
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.event_hypothesis_lineage_migrations import (
    EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT,
)
from newsroom.authority.event_hypothesis_relationship_migrations import (
    EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_CHECKSUM,
    EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_NAME,
    EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_STATEMENTS,
    EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_FINGERPRINT,
    EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_MIGRATION_CHECKSUM,
    EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION,
    EventHypothesisRelationshipBackupError,
    event_hypothesis_relationship_backup_paths,
    prepare_event_hypothesis_relationship_backup,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.tests.graphiti_adapter_4d_migration_helpers import (
    drop_empty_v23_lineage_schema,
)


def _open(path: str | Path = ":memory:") -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _fresh(path: str | Path = ":memory:") -> sqlite3.Connection:
    connection = _open(path)
    apply_pending_migrations(connection, applied_at="2042-01-01T00:00:00.000000Z")
    drop_empty_v23_lineage_schema(connection)
    return connection


def _downgrade_to_v21(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=OFF")
    guard = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    connection.execute("DROP TRIGGER retained_event_hypothesis_relationship_delete")
    connection.execute("DROP TRIGGER immutable_event_hypothesis_relationship_update")
    connection.execute("DROP TRIGGER event_hypothesis_relationship_coherence")
    connection.execute("DROP TABLE event_hypothesis_relationship_decisions")
    connection.execute("DELETE FROM authority_migrations WHERE version=22")
    connection.execute(guard)
    connection.execute("PRAGMA user_version=21")
    connection.execute("PRAGMA foreign_keys=ON")


def test_fresh_v22_has_exact_single_table_history_and_pins() -> None:
    connection = _fresh()
    assert (
        EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_CHECKSUM
        == "sha256:e59eb222a95e2901ccaae29ce1b9e8eded797306e9796718a6d2c4fa505a6636"
    )
    assert (
        EXPECTED_SCHEMA_FINGERPRINT
        == "sha256:353900bf5804f0b770489982541f3cff4fd30ea36fc75d19b9c63315d1b6ec06"
    )
    assert next(item for item in EXPECTED_MIGRATION_HISTORY if item[0] == 22) == (
        22,
        EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_NAME,
        EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_CHECKSUM,
    )
    assert (
        EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_MIGRATION_CHECKSUM
        == "sha256:42009475669a475af8e3e24bbcd02e6fcd9fbb71a800e18d83624e34e79e5e21"
    )
    assert (
        EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_FINGERPRINT
        == "sha256:d314d06118a25f8a32a0f9d8acb1af5383abd6b30be682cb5f65943ae15c213f"
    )
    assert connection.execute("PRAGMA user_version").fetchone() == (22,)
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'event_hypothesis_relationship%'"
    ).fetchall() == [("event_hypothesis_relationship_decisions",)]
    assert (
        schema_fingerprint(connection)
        == EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT
    )


def test_v22_migration_pin_detects_one_byte_statement_drift() -> None:
    drifted = list(EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_STATEMENTS)
    drifted[-1] += " "
    assert (
        digest_canonical(
            {
                "version": EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION,
                "name": EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_NAME,
                "statements": drifted,
            }
        )
        != EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_CHECKSUM
    )


def test_exact_v21_backup_upgrade_and_injected_rollback(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "authority.sqlite3"
    connection = _fresh(database)
    _downgrade_to_v21(connection)
    assert (
        schema_fingerprint(connection)
        == EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_FINGERPRINT
    )
    backup, digest = event_hypothesis_relationship_backup_paths(database)
    receipt = prepare_event_hypothesis_relationship_backup(connection, backup)
    assert receipt.backup_path == backup and receipt.digest_path == digest
    monkeypatch.setattr(
        migrations,
        "EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_STATEMENTS",
        migrations.EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_STATEMENTS
        + ("CREATE TABLE injected_failure(",),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (21,)
    assert (
        schema_fingerprint(connection)
        == EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_FINGERPRINT
    )
    monkeypatch.undo()
    apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)


def test_standard_sqlite_connection_v22_backup_gate_closes_implicit_transaction(
    tmp_path: Path,
) -> None:
    database = tmp_path / "standard-connection.sqlite3"
    initial = _fresh(database)
    _downgrade_to_v21(initial)
    initial.close()

    connection = sqlite3.connect(database)
    try:
        backup, _ = event_hypothesis_relationship_backup_paths(database)
        prepare_event_hypothesis_relationship_backup(connection, backup)
        assert connection.in_transaction is False

        apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")

        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
    finally:
        connection.close()


def test_v21_backup_required_and_v24_fails_closed(tmp_path: Path) -> None:
    connection = _fresh(tmp_path / "authority.sqlite3")
    _downgrade_to_v21(connection)
    with pytest.raises(EventHypothesisRelationshipBackupError, match="prepared backup"):
        apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")
    newer = _open()
    newer.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(sqlite3.DatabaseError, match="newer"):
        apply_pending_migrations(newer, applied_at="2042-01-01T00:00:00.000000Z")
