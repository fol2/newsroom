from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority import migrations
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.authority.triage_execution_migrations import (
    TRIAGE_EXECUTION_MIGRATION_CHECKSUM,
    TRIAGE_EXECUTION_MIGRATION_NAME,
    TRIAGE_EXECUTION_PREDECESSOR_FINGERPRINT,
    TRIAGE_EXECUTION_PREDECESSOR_MIGRATION_CHECKSUM,
    TRIAGE_EXECUTION_SCHEMA_VERSION,
    TriageExecutionBackupError,
    prepare_triage_execution_backup,
    triage_execution_backup_paths,
)

from .graphiti_adapter_4d_migration_helpers import (
    drop_empty_v22_relationship_schema,
)


def _open(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _fresh(path: str | Path = ":memory:") -> sqlite3.Connection:
    connection = _open(path)
    apply_pending_migrations(
        connection, applied_at="2042-03-12T10:00:00.000000Z"
    )
    return connection


def _downgrade_to_v19(connection: sqlite3.Connection) -> None:
    drop_empty_v22_relationship_schema(connection)
    connection.execute("PRAGMA foreign_keys=OFF")
    guard = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    connection.execute("DROP TABLE event_hypothesis_heads_v2")
    connection.execute("DROP TABLE event_hypothesis_versions_v2")
    connection.execute("DROP TABLE event_hypotheses_v2")
    for trigger in (
        "triage_execution_batch_coherence",
        "triage_worker_attempt_coherence",
        "triage_lease_insert_coherence",
        "triage_lease_update_guard",
        "retained_execution_batch_update",
        "retained_execution_batch_delete",
        "retained_worker_attempt_update",
        "retained_worker_attempt_delete",
        "retained_work_item_lease_delete",
    ):
        connection.execute(f"DROP TRIGGER {trigger}")
    connection.execute("DROP INDEX one_claimed_triage_lease_per_work_item")
    connection.execute("DROP TABLE triage_work_item_leases")
    connection.execute("DROP TABLE triage_worker_attempts")
    connection.execute("DROP TABLE triage_execution_batches")
    connection.execute("DELETE FROM authority_migrations WHERE version>=20")
    connection.execute(guard)
    connection.execute("PRAGMA user_version=19")
    connection.execute("PRAGMA foreign_keys=ON")


def test_fresh_v20_history_fingerprint_and_exact_three_table_allocation() -> None:
    connection = _fresh()
    assert TRIAGE_EXECUTION_SCHEMA_VERSION == 20
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert EXPECTED_MIGRATION_HISTORY[TRIAGE_EXECUTION_SCHEMA_VERSION - 1] == (
        20,
        TRIAGE_EXECUTION_MIGRATION_NAME,
        TRIAGE_EXECUTION_MIGRATION_CHECKSUM,
    )
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
    assert connection.execute(
        "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
    ).fetchall() == list(EXPECTED_MIGRATION_HISTORY)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    assert {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'triage_%execution%' OR name='triage_worker_attempts' "
            "OR name='triage_work_item_leases'"
        )
    } == {
        "triage_execution_batches",
        "triage_worker_attempts",
        "triage_work_item_leases",
    }


def test_v20_literal_predecessor_pins_are_exact() -> None:
    assert TRIAGE_EXECUTION_PREDECESSOR_MIGRATION_CHECKSUM == (
        "sha256:d5f9702d359836e3b564ba1cadbad27e5fc17ba79e5155e2b34382ec30681177"
    )
    assert TRIAGE_EXECUTION_PREDECESSOR_FINGERPRINT == (
        "sha256:542bd9c351094cf4d56905fa92aa042924b5dab877cc04374a097c48fe6b6003"
    )
    assert TRIAGE_EXECUTION_MIGRATION_CHECKSUM == (
        "sha256:6eb04f981f650bbb4956f148d11f1656bcd2b7c510117db96602dd9d83ab9bd3"
    )
    assert EXPECTED_MIGRATION_HISTORY[TRIAGE_EXECUTION_SCHEMA_VERSION - 1] == (
        20,
        "triage_execution_authority_v20",
        "sha256:6eb04f981f650bbb4956f148d11f1656bcd2b7c510117db96602dd9d83ab9bd3",
    )


def test_exact_v19_backup_upgrade_reuse_and_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    connection = _fresh(database)
    _downgrade_to_v19(connection)
    assert schema_fingerprint(connection) == TRIAGE_EXECUTION_PREDECESSOR_FINGERPRINT
    backup, digest = triage_execution_backup_paths(database)
    receipt = prepare_triage_execution_backup(connection, backup)
    assert prepare_triage_execution_backup(connection, backup) == receipt
    apply_pending_migrations(connection, applied_at="2042-03-12T10:00:01Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
    assert backup.is_file() and digest.is_file()

    digest.write_text("sha256:" + "0" * 64 + "\n", encoding="ascii")
    _downgrade_to_v19(connection)
    with pytest.raises(TriageExecutionBackupError, match="digest"):
        prepare_triage_execution_backup(connection, backup)


def test_injected_v20_failure_rolls_back_exact_v19_and_v21_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _fresh(tmp_path / "rollback.sqlite3")
    _downgrade_to_v19(connection)
    prepare_triage_execution_backup(
        connection,
        triage_execution_backup_paths(tmp_path / "rollback.sqlite3")[0],
    )
    before = schema_fingerprint(connection)
    monkeypatch.setattr(
        migrations,
        "TRIAGE_EXECUTION_MIGRATION_STATEMENTS",
        migrations.TRIAGE_EXECUTION_MIGRATION_STATEMENTS
        + ("CREATE TABLE injected_failure(",),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at="2042-03-12T10:00:01Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (19,)
    assert schema_fingerprint(connection) == before
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'triage_execution_%'"
    ).fetchall() == []

    newer = _open(":memory:")
    newer.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(sqlite3.DatabaseError, match="newer"):
        apply_pending_migrations(newer, applied_at="2042-03-12T10:00:00Z")
