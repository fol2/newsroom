from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority import migrations
from newsroom.authority.event_hypothesis_migrations import (
    EVENT_HYPOTHESIS_MIGRATION_CHECKSUM,
    EVENT_HYPOTHESIS_MIGRATION_NAME,
    EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT,
    EVENT_HYPOTHESIS_PREDECESSOR_MIGRATION_CHECKSUM,
    EventHypothesisBackupError,
    event_hypothesis_backup_paths,
    prepare_event_hypothesis_backup,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)


def _open(path: str | Path = ":memory:") -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _fresh(path: str | Path = ":memory:") -> sqlite3.Connection:
    connection = _open(path)
    apply_pending_migrations(connection, applied_at="2042-01-01T00:00:00.000000Z")
    return connection


def _downgrade_to_v20(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=OFF")
    immutable = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    for trigger in (
        "event_hypothesis_identity_coherence",
        "event_hypothesis_version_coherence",
        "event_hypothesis_head_insert_guard",
        "event_hypothesis_head_update_guard",
        "immutable_event_hypothesis_update",
        "retained_event_hypothesis_delete",
        "immutable_event_hypothesis_version_update",
        "retained_event_hypothesis_version_delete",
        "retained_event_hypothesis_head_delete",
    ):
        connection.execute(f"DROP TRIGGER {trigger}")
    connection.execute("DROP TABLE event_hypothesis_heads_v2")
    connection.execute("DROP TABLE event_hypothesis_versions_v2")
    connection.execute("DROP TABLE event_hypotheses_v2")
    connection.execute("DELETE FROM authority_migrations WHERE version=21")
    connection.execute(immutable)
    connection.execute("PRAGMA user_version=20")
    connection.execute("PRAGMA foreign_keys=ON")


def _history(connection: sqlite3.Connection) -> list[tuple[int, str, str]]:
    return connection.execute(
        "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
    ).fetchall()


def test_fresh_v21_has_exact_allocation_history_and_integrity() -> None:
    connection = _fresh()
    assert SCHEMA_VERSION == 21
    assert EXPECTED_MIGRATION_HISTORY[-1] == (
        21,
        EVENT_HYPOTHESIS_MIGRATION_NAME,
        EVENT_HYPOTHESIS_MIGRATION_CHECKSUM,
    )
    assert _history(connection) == list(EXPECTED_MIGRATION_HISTORY)
    assert {
        r[0]
        for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'event_hypoth%_v2'"
        )
    } == {
        "event_hypotheses_v2",
        "event_hypothesis_versions_v2",
        "event_hypothesis_heads_v2",
    }
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT


def test_literal_v21_and_predecessor_pins() -> None:
    assert (
        EVENT_HYPOTHESIS_PREDECESSOR_MIGRATION_CHECKSUM
        == "sha256:6eb04f981f650bbb4956f148d11f1656bcd2b7c510117db96602dd9d83ab9bd3"
    )
    assert (
        EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT
        == "sha256:36a7c9910775ede9c29113a43e08bba261a5a98c4fab5225dd2cae9448689389"
    )
    assert (
        EVENT_HYPOTHESIS_MIGRATION_CHECKSUM
        == "sha256:42009475669a475af8e3e24bbcd02e6fcd9fbb71a800e18d83624e34e79e5e21"
    )
    assert (
        EXPECTED_SCHEMA_FINGERPRINT
        == "sha256:d314d06118a25f8a32a0f9d8acb1af5383abd6b30be682cb5f65943ae15c213f"
    )


def test_exact_v20_predecessor_backup_receipt_reuse_and_upgrade(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    connection = _fresh(database)
    _downgrade_to_v20(connection)
    assert _history(connection) == list(EXPECTED_MIGRATION_HISTORY[:-1])
    assert schema_fingerprint(connection) == EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT
    backup, digest = event_hypothesis_backup_paths(database)
    receipt = prepare_event_hypothesis_backup(connection, backup)
    assert prepare_event_hypothesis_backup(connection, backup) == receipt
    assert receipt.backup_path == backup and receipt.digest_path == digest
    apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (21,)
    assert _history(connection) == list(EXPECTED_MIGRATION_HISTORY)
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT


@pytest.mark.parametrize(
    "damage",
    ("missing-backup", "missing-sidecar", "tampered-backup", "tampered-sidecar"),
)
def test_incomplete_or_tampered_v20_backup_is_rejected(
    tmp_path: Path, damage: str
) -> None:
    database = tmp_path / f"{damage}.sqlite3"
    connection = _fresh(database)
    _downgrade_to_v20(connection)
    backup, digest = event_hypothesis_backup_paths(database)
    prepare_event_hypothesis_backup(connection, backup)
    if damage == "missing-backup":
        backup.unlink()
    elif damage == "missing-sidecar":
        digest.unlink()
    elif damage == "tampered-backup":
        with backup.open("ab") as target:
            target.write(b"tamper")
    else:
        digest.write_text("sha256:" + "0" * 64 + "\n", encoding="ascii")
    with pytest.raises(EventHypothesisBackupError):
        apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (20,)
    assert _history(connection) == list(EXPECTED_MIGRATION_HISTORY[:-1])
    assert schema_fingerprint(connection) == EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT


def test_direct_v20_apply_requires_prepared_backup_and_v22_rejects(
    tmp_path: Path,
) -> None:
    connection = _fresh(tmp_path / "direct.sqlite3")
    _downgrade_to_v20(connection)
    with pytest.raises(EventHypothesisBackupError, match="prepared backup"):
        apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (20,)
    assert schema_fingerprint(connection) == EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT
    newer = _open()
    newer.execute("PRAGMA user_version=22")
    with pytest.raises(sqlite3.DatabaseError, match="newer"):
        apply_pending_migrations(newer, applied_at="2042-01-01T00:00:00.000000Z")


def test_injected_v21_failure_rolls_back_exact_v20(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "rollback.sqlite3"
    connection = _fresh(database)
    _downgrade_to_v20(connection)
    prepare_event_hypothesis_backup(
        connection, event_hypothesis_backup_paths(database)[0]
    )
    before = schema_fingerprint(connection)
    monkeypatch.setattr(
        migrations,
        "EVENT_HYPOTHESIS_MIGRATION_STATEMENTS",
        migrations.EVENT_HYPOTHESIS_MIGRATION_STATEMENTS
        + ("CREATE TABLE injected_failure(",),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (20,)
    assert _history(connection) == list(EXPECTED_MIGRATION_HISTORY[:-1])
    assert schema_fingerprint(connection) == before
    assert (
        connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'event_hypothesis%'"
        ).fetchall()
        == []
    )


def test_older_file_backed_multihop_retains_each_stage_backup(tmp_path: Path) -> None:
    # A v19 predecessor must cross the separately retained v20 and v21 backup gates.
    from newsroom.tests.test_increment6b1_execution_migrations import _downgrade_to_v19

    database = tmp_path / "multihop.sqlite3"
    connection = _fresh(database)
    _downgrade_to_v19(connection)
    migrations.prepare_pending_migration_backup(connection)
    apply_pending_migrations(connection, applied_at="2042-01-01T00:00:01.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (21,)
    assert (tmp_path / "multihop.sqlite3.pre-v20.sqlite3").is_file()
    assert (tmp_path / "multihop.sqlite3.pre-v20.sqlite3.sha256").is_file()
    assert (tmp_path / "multihop.sqlite3.pre-v21.sqlite3").is_file()
    assert (tmp_path / "multihop.sqlite3.pre-v21.sqlite3.sha256").is_file()


def test_v21_sql_guards_are_sensitive() -> None:
    connection = _fresh()
    # Checks are executable, not merely present in the migration text.
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO event_hypotheses_v2 VALUES(?,?,?,?,?,?)",
            ("id", b"{}", "sha256:" + "0" * 64, "sha256:" + "1" * 64, "event", "time"),
        )
