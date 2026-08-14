"""Checked v32 Increment 8 recovery-authority migration and v31 backup gate."""

# fmt: off
# ruff: noqa: I001
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import increment8_operational_migrations as predecessor
from .canonical import digest_canonical

INCREMENT8_RECOVERY_SCHEMA_VERSION = 32
INCREMENT8_RECOVERY_MIGRATION_NAME = "increment8_recovery_authority_v32"
INCREMENT8_RECOVERY_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:b3a9535516836d7a0023cc0c030926edd8036b0fd8b31b9647342a9612152342"
)
INCREMENT8_RECOVERY_PREDECESSOR_FINGERPRINT = (
    "sha256:8a8f2aafc484a4d0270b0fbc582c2c22fc83e545570e3117b0b2be8eee874bc5"
)
Increment8RecoveryBackupError = predecessor.Increment8OperationalBackupError
Increment8RecoveryBackupReceipt = predecessor.Increment8OperationalBackupReceipt
Increment8RecoveryMigrationRecord = predecessor.Increment8OperationalMigrationRecord
_helpers = predecessor._helpers


def increment8_recovery_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v32.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> Increment8RecoveryBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = _helpers._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise Increment8RecoveryBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 31
            or _helpers._schema_fingerprint(target) != INCREMENT8_RECOVERY_PREDECESSOR_FINGERPRINT
            or _helpers._logical_database_digest(target) != logical
        ):
            raise Increment8RecoveryBackupError("backup differs from source")
    finally:
        target.close()
    return Increment8RecoveryBackupReceipt(path, digest_path, digest, logical)


def prepare_increment8_recovery_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> Increment8RecoveryBackupReceipt:
    fingerprint = _helpers._schema_fingerprint
    logical_digest = _helpers._logical_database_digest
    file_digest = _helpers._file_digest
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 31
        or fingerprint(connection) != INCREMENT8_RECOVERY_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise Increment8RecoveryBackupError("backup requires checked schema v31")
    source = Path(next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"))
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical = logical_digest(connection)
    if not source or source.resolve() == backup_path.resolve() or backup_path.exists() != digest_path.exists():
        raise Increment8RecoveryBackupError("backup boundary differs")
    if not backup_path.exists():
        backup_path.open("xb").close()
        target = sqlite3.connect(backup_path, isolation_level=None)
        try:
            connection.backup(target)
        finally:
            target.close()
        digest_path.write_text(file_digest(backup_path) + "\n", encoding="ascii")
    receipt = _checked_backup(backup_path, logical)
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS increment8_recovery_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM increment8_recovery_backup_gate")
    connection.execute(
        "INSERT INTO increment8_recovery_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_increment8_recovery_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> Increment8RecoveryBackupReceipt:
    logical_digest = _helpers._logical_database_digest
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest FROM temp.increment8_recovery_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise Increment8RecoveryBackupError("v31 to v32 requires prepared backup") from exc
    if row is None or logical_digest(connection) != row[2]:
        raise Increment8RecoveryBackupError("v31 to v32 requires prepared backup")
    receipt = _checked_backup(Path(row[0]), str(row[2]))
    target = sqlite3.connect(f"file:{receipt.backup_path}?mode=ro", uri=True, isolation_level=None)
    try:
        history = target.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
    finally:
        target.close()
    if receipt.backup_digest != row[1] or history != list(expected_history):
        raise Increment8RecoveryBackupError("prepared backup is not exact v31")
    return receipt


_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
INCREMENT8_RECOVERY_TABLES = (
    "reconciliation_runs",
    "backup_manifests",
    "restore_runs",
    "purge_receipts",
    "fault_injection_runs",
)
INCREMENT8_RECOVERY_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE reconciliation_runs(
        reconciliation_id TEXT PRIMARY KEY,
        reconciliation_bytes BLOB NOT NULL,
        reconciliation_digest TEXT NOT NULL UNIQUE CHECK({_D.format('reconciliation_digest')}),
        profile_digest TEXT NOT NULL CHECK({_D.format('profile_digest')}),
        started_at TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN('PASS','FAIL')),
        automatic_operation_blocked INTEGER NOT NULL CHECK(automatic_operation_blocked IN(0,1)),
        CHECK(length(reconciliation_bytes)>0),
        CHECK((status='PASS' AND automatic_operation_blocked=0) OR (status='FAIL' AND automatic_operation_blocked=1))
    ) STRICT""",
    f"""CREATE TABLE backup_manifests(
        backup_id TEXT PRIMARY KEY,
        manifest_bytes BLOB NOT NULL,
        manifest_digest TEXT NOT NULL UNIQUE CHECK({_D.format('manifest_digest')}),
        authority_logical_digest TEXT NOT NULL CHECK({_D.format('authority_logical_digest')}),
        backup_file_digest TEXT NOT NULL CHECK({_D.format('backup_file_digest')}),
        created_at TEXT NOT NULL,
        retain_until TEXT NOT NULL,
        integrity_status TEXT NOT NULL CHECK(integrity_status='PASS'),
        CHECK(length(manifest_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE restore_runs(
        restore_id TEXT PRIMARY KEY,
        restore_bytes BLOB NOT NULL,
        restore_digest TEXT NOT NULL UNIQUE CHECK({_D.format('restore_digest')}),
        backup_id TEXT NOT NULL REFERENCES backup_manifests(backup_id),
        restored_logical_digest TEXT NOT NULL CHECK({_D.format('restored_logical_digest')}),
        completed_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN('RECONCILIATION_REQUIRED','READY','FAIL')),
        automatic_operation_resumed INTEGER NOT NULL CHECK(automatic_operation_resumed=0),
        CHECK(length(restore_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE purge_receipts(
        purge_id TEXT PRIMARY KEY,
        purge_bytes BLOB NOT NULL,
        purge_digest TEXT NOT NULL UNIQUE CHECK({_D.format('purge_digest')}),
        scope_digest TEXT NOT NULL CHECK({_D.format('scope_digest')}),
        before_digest TEXT NOT NULL CHECK({_D.format('before_digest')}),
        after_digest TEXT NOT NULL CHECK({_D.format('after_digest')}),
        authorised_by_digest TEXT NOT NULL CHECK({_D.format('authorised_by_digest')}),
        purged_at TEXT NOT NULL,
        rebuild_required INTEGER NOT NULL CHECK(rebuild_required=1),
        CHECK(length(purge_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE fault_injection_runs(
        fault_run_id TEXT PRIMARY KEY,
        fault_bytes BLOB NOT NULL,
        fault_digest TEXT NOT NULL UNIQUE CHECK({_D.format('fault_digest')}),
        profile_digest TEXT NOT NULL CHECK({_D.format('profile_digest')}),
        scenario TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN('PASS','FAIL')),
        live_effect_authorised INTEGER NOT NULL CHECK(live_effect_authorised=0),
        CHECK(length(fault_bytes)>0)
    ) STRICT""",
    *tuple(
        f"CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable Increment 8 recovery record'); END"
        for table in INCREMENT8_RECOVERY_TABLES
    ),
    *tuple(
        f"CREATE TRIGGER retained_{table} BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'retained Increment 8 recovery record'); END"
        for table in INCREMENT8_RECOVERY_TABLES
    ),
)
INCREMENT8_RECOVERY_MIGRATION_CHECKSUM = digest_canonical({
    "version": INCREMENT8_RECOVERY_SCHEMA_VERSION,
    "name": INCREMENT8_RECOVERY_MIGRATION_NAME,
    "statements": list(INCREMENT8_RECOVERY_MIGRATION_STATEMENTS),
})
INCREMENT8_RECOVERY_MIGRATION = Increment8RecoveryMigrationRecord(
    INCREMENT8_RECOVERY_SCHEMA_VERSION,
    INCREMENT8_RECOVERY_MIGRATION_NAME,
    INCREMENT8_RECOVERY_MIGRATION_CHECKSUM,
)
__all__ = [name for name in globals() if name.startswith(("INCREMENT8_RECOVERY_", "Increment8Recovery", "increment8_recovery_", "prepare_", "require_"))]
# fmt: on
