from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority import migrations
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    prepare_pending_migration_backup,
    schema_fingerprint,
)
from newsroom.authority.triage_disposition_migrations import (
    TRIAGE_DISPOSITION_MIGRATION_CHECKSUM,
    TRIAGE_DISPOSITION_MIGRATION_NAME,
    TRIAGE_DISPOSITION_PREDECESSOR_FINGERPRINT,
    TRIAGE_DISPOSITION_SCHEMA_VERSION,
    TriageDispositionBackupError,
    prepare_triage_disposition_backup,
    triage_disposition_backup_paths,
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
    apply_pending_migrations(connection, applied_at="2042-03-12T10:00:00Z")
    return connection


def _downgrade_to_v18(connection: sqlite3.Connection) -> None:
    drop_empty_v22_relationship_schema(connection)
    connection.execute("PRAGMA foreign_keys=OFF")
    guard = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    connection.execute("DROP TABLE event_hypothesis_heads_v2")
    connection.execute("DROP TABLE event_hypothesis_versions_v2")
    connection.execute("DROP TABLE event_hypotheses_v2")
    connection.execute("DROP TABLE triage_work_item_leases")
    connection.execute("DROP TABLE triage_worker_attempts")
    connection.execute("DROP TABLE triage_execution_batches")
    connection.execute("DROP TABLE triage_proposal_dispositions")
    connection.execute("DROP TABLE triage_proposal_validation_findings")
    connection.execute("DELETE FROM authority_migrations WHERE version>=19")
    connection.execute(guard)
    connection.execute("PRAGMA user_version=18")
    connection.execute("PRAGMA foreign_keys=ON")


def test_fresh_v19_history_fingerprint_guards_and_integrity_are_exact() -> None:
    connection = _fresh()
    assert TRIAGE_DISPOSITION_SCHEMA_VERSION == 19
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert EXPECTED_MIGRATION_HISTORY[TRIAGE_DISPOSITION_SCHEMA_VERSION - 1] == (
        19,
        TRIAGE_DISPOSITION_MIGRATION_NAME,
        TRIAGE_DISPOSITION_MIGRATION_CHECKSUM,
    )
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
    assert connection.execute(
        "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
    ).fetchall() == list(EXPECTED_MIGRATION_HISTORY)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    for table in (
        "triage_proposal_validation_findings",
        "triage_proposal_dispositions",
    ):
        unique_columns = {
            tuple(
                str(column[2])
                for column in connection.execute(
                    f"PRAGMA index_info('{index[1]}')"
                )
            )
            for index in connection.execute(f"PRAGMA index_list('{table}')")
            if index[2]
        }
        assert ("work_item_version_id", "decision_lead_id") in unique_columns
    assert {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'triage_proposal_%'"
        )
    } == {
        "triage_proposal_validation_findings",
        "triage_proposal_dispositions",
    }


def test_exact_v18_backup_upgrade_reuse_and_tamper_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    connection = _fresh(database)
    _downgrade_to_v18(connection)
    assert schema_fingerprint(connection) == TRIAGE_DISPOSITION_PREDECESSOR_FINGERPRINT
    receipt = prepare_pending_migration_backup(connection)
    assert receipt is not None
    assert prepare_triage_disposition_backup(
        connection, triage_disposition_backup_paths(database)[0]
    ) == receipt
    apply_pending_migrations(connection, applied_at="2042-03-12T10:00:01Z")
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    backup, digest = triage_disposition_backup_paths(database)
    assert backup.is_file() and digest.is_file()
    connection.close()

    tampered = tmp_path / "tampered.sqlite3"
    tampered.write_bytes(backup.read_bytes())
    tampered_connection = _open(tampered)
    tampered_connection.execute("DROP TABLE triage_work_item_heads")
    with pytest.raises(TriageDispositionBackupError, match="checked v18"):
        prepare_triage_disposition_backup(
            tampered_connection, tmp_path / "tampered.backup.sqlite3"
        )


def test_v19_injected_failure_restores_exact_v18_and_v20_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "rollback.sqlite3"
    connection = _fresh(database)
    _downgrade_to_v18(connection)
    prepare_pending_migration_backup(connection)
    before = schema_fingerprint(connection)
    monkeypatch.setattr(
        migrations,
        "TRIAGE_DISPOSITION_MIGRATION_STATEMENTS",
        migrations.TRIAGE_DISPOSITION_MIGRATION_STATEMENTS
        + ("CREATE TABLE injected_failure(",),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at="2042-03-12T10:00:01Z")
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 18
    assert schema_fingerprint(connection) == before
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'triage_proposal_%'"
    ).fetchall() == []

    newer = _open(":memory:")
    newer.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(sqlite3.DatabaseError, match="newer"):
        apply_pending_migrations(newer, applied_at="2042-03-12T10:00:00Z")

_DIGEST = "sha256:" + "a" * 64
_OTHER_DIGEST = "sha256:" + "b" * 64


def _finding_row(canonical_bytes: bytes | None = None) -> tuple[object, ...]:
    finding = {
        "schema_version": "newsroom.increment6.triage-proposal-finding.v1",
        "finding": {
            "finding_id": _DIGEST,
            "proposal_id": "proposal:1",
            "proposal_content_identity": _DIGEST,
            "proposal_canonical_digest": _DIGEST,
            "evidence_reference_id": "lead:1",
            "validator_input_binding": {"input_digest": _DIGEST},
            "severity": "INFO",
            "authority": "NONE",
        },
    }
    raw = canonical_bytes or canonical_json_bytes(finding)
    return (
        _DIGEST, "work-item:missing", "version:missing", _DIGEST,
        "proposal:1", _DIGEST, _DIGEST, "lead:1", _DIGEST, _DIGEST,
        "INFO", raw, digest_bytes(raw), "2042-03-12T10:00:00Z",
    )


def _insert_finding(connection: sqlite3.Connection, row: tuple[object, ...]) -> None:
    connection.execute(
        "INSERT INTO triage_proposal_validation_findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        row,
    )


def _insert_disposition(connection: sqlite3.Connection) -> None:
    disposition = {
        "schema_version": "newsroom.increment6.triage-proposal-disposition.v1",
        "disposition": {
            "disposition_id": _OTHER_DIGEST,
            "work_item_id": "work-item:missing",
            "work_item_version_id": "version:missing",
            "work_item_version_digest": _DIGEST,
            "proposal_id": "proposal:1",
            "proposal_content_identity": _DIGEST,
            "proposal_canonical_digest": _DIGEST,
            "lead_head_binding": {
                "decision_lead_id": "lead:1",
                "current_disposition_head_id": "head:1",
                "current_disposition_head_digest": _DIGEST,
            },
            "validator_input_binding": {"input_digest": _DIGEST},
            "finding_set_digest": _DIGEST,
            "authority": "NONE",
        },
    }
    raw = canonical_json_bytes(disposition)
    connection.execute(
        "INSERT INTO triage_proposal_dispositions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            _OTHER_DIGEST, "work-item:missing", "version:missing", _DIGEST,
            "proposal:1", _DIGEST, _DIGEST, "lead:1", "head:1", _DIGEST,
            _DIGEST, _DIGEST, _DIGEST, _DIGEST, raw,
            digest_bytes(raw), "2042-03-12T10:00:00Z",
        ),
    )


def test_v19_checksum_and_schema_fingerprint_are_literal_release_pins() -> None:
    assert TRIAGE_DISPOSITION_MIGRATION_CHECKSUM == (
        "sha256:d5f9702d359836e3b564ba1cadbad27e5fc17ba79e5155e2b34382ec30681177"
    )
    assert (
        EXPECTED_MIGRATION_HISTORY[TRIAGE_DISPOSITION_SCHEMA_VERSION - 1][2]
        == TRIAGE_DISPOSITION_MIGRATION_CHECKSUM
    )


def test_exact_v18_apply_without_prepared_backup_preserves_history_and_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _fresh(tmp_path / "unprepared.sqlite3")
    _downgrade_to_v18(connection)
    before_fingerprint = schema_fingerprint(connection)
    before_history = connection.execute(
        "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
    ).fetchall()
    monkeypatch.setattr(
        migrations, "prepare_triage_disposition_backup", lambda *_args: None
    )
    with pytest.raises(TriageDispositionBackupError, match="prepared backup"):
        apply_pending_migrations(connection, applied_at="2042-03-12T10:00:01Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (18,)
    assert schema_fingerprint(connection) == before_fingerprint
    assert connection.execute(
        "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
    ).fetchall() == before_history


def test_v19_foreign_keys_json_coherence_and_both_tables_are_immutable() -> None:
    connection = _fresh()
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        _insert_finding(connection, _finding_row())
    for malformed in (b"{}", b"{"):
        with pytest.raises(sqlite3.IntegrityError, match="scalars differ"):
            _insert_finding(connection, _finding_row(malformed))

    connection.execute("PRAGMA foreign_keys=OFF")
    _insert_finding(connection, _finding_row())
    _insert_disposition(connection)
    connection.execute("PRAGMA foreign_keys=ON")
    for table in (
        "triage_proposal_validation_findings",
        "triage_proposal_dispositions",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(f"UPDATE {table} SET recorded_at=recorded_at")
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute(f"DELETE FROM {table}")
