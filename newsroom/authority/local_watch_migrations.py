"""Checked v29 Event-Scoped Local Watch migration and exact v28 backup gate."""

# fmt: off
# ruff: noqa: I001
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import coverage_audit_migrations as predecessor
from .canonical import digest_canonical

LOCAL_WATCH_SCHEMA_VERSION = 29
LOCAL_WATCH_MIGRATION_NAME = "event_scoped_local_watch_authority_v29"
LOCAL_WATCH_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:c923daf18aed10bb9c197bfd588d816223d978668bda56c157438d1a4b7cc487"
)
LOCAL_WATCH_PREDECESSOR_FINGERPRINT = (
    "sha256:a613b28a765b36fa9110bcdc2b9bc565c6e2bc0ed8b8381d77f5fcd734c39c48"
)
LocalWatchBackupError = predecessor.CoverageAuditBackupError
LocalWatchBackupReceipt = predecessor.CoverageAuditBackupReceipt
LocalWatchMigrationRecord = predecessor.CoverageAuditMigrationRecord
_helpers = predecessor._helpers


def local_watch_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v29.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> LocalWatchBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = _helpers._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise LocalWatchBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 28
            or _helpers._schema_fingerprint(target) != LOCAL_WATCH_PREDECESSOR_FINGERPRINT
            or _helpers._logical_database_digest(target) != logical
        ):
            raise LocalWatchBackupError("backup differs from source")
    finally:
        target.close()
    return LocalWatchBackupReceipt(path, digest_path, digest, logical)


def prepare_local_watch_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> LocalWatchBackupReceipt:
    fingerprint = _helpers._schema_fingerprint
    logical_digest = _helpers._logical_database_digest
    file_digest = _helpers._file_digest
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 28
        or fingerprint(connection) != LOCAL_WATCH_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise LocalWatchBackupError("backup requires checked schema v28")
    source = Path(
        next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main")
    )
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical = logical_digest(connection)
    if (
        not source
        or source.resolve() == backup_path.resolve()
        or backup_path.exists() != digest_path.exists()
    ):
        raise LocalWatchBackupError("backup boundary differs")
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
        "CREATE TEMP TABLE IF NOT EXISTS local_watch_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,"
        "logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM local_watch_backup_gate")
    connection.execute(
        "INSERT INTO local_watch_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_local_watch_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> LocalWatchBackupReceipt:
    logical_digest = _helpers._logical_database_digest
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.local_watch_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise LocalWatchBackupError("v28 to v29 requires prepared backup") from exc
    if row is None or logical_digest(connection) != row[2]:
        raise LocalWatchBackupError("v28 to v29 requires prepared backup")
    receipt = _checked_backup(Path(row[0]), str(row[2]))
    target = sqlite3.connect(
        f"file:{receipt.backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        history = target.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
    finally:
        target.close()
    if receipt.backup_digest != row[1] or history != list(expected_history):
        raise LocalWatchBackupError("prepared backup is not exact v28")
    return receipt


_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
LOCAL_WATCH_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE event_scoped_local_watches(
        watch_id TEXT PRIMARY KEY,
        watch_bytes BLOB NOT NULL,
        watch_digest TEXT NOT NULL UNIQUE CHECK({_D.format('watch_digest')}),
        subject_kind TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        subject_version_digest TEXT NOT NULL CHECK({_D.format('subject_version_digest')}),
        owner_identity_digest TEXT NOT NULL CHECK({_D.format('owner_identity_digest')}),
        created_at TEXT NOT NULL,
        UNIQUE(subject_kind,subject_id,subject_version_digest,watch_digest),
        CHECK(length(watch_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE event_scoped_local_watch_versions(
        watch_version_id TEXT PRIMARY KEY,
        watch_id TEXT NOT NULL REFERENCES event_scoped_local_watches(watch_id),
        version_ordinal INTEGER NOT NULL CHECK(version_ordinal BETWEEN 1 AND 10000),
        previous_version_digest TEXT CHECK(previous_version_digest IS NULL OR {_D.format('previous_version_digest')}),
        version_bytes BLOB NOT NULL,
        version_digest TEXT NOT NULL UNIQUE CHECK({_D.format('version_digest')}),
        status TEXT NOT NULL CHECK(status IN ('PLANNED','OPEN','PAUSED','EXTENDED')),
        starts_at TEXT NOT NULL,
        review_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        command_bytes BLOB NOT NULL,
        command_digest TEXT NOT NULL UNIQUE CHECK({_D.format('command_digest')}),
        command_id TEXT NOT NULL UNIQUE,
        request_id TEXT NOT NULL UNIQUE,
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL,
        UNIQUE(watch_id,version_ordinal),
        UNIQUE(watch_id,version_digest),
        UNIQUE(watch_version_id,watch_id,version_digest),
        FOREIGN KEY(watch_id,previous_version_digest)
            REFERENCES event_scoped_local_watch_versions(watch_id,version_digest),
        CHECK(length(version_bytes)>0 AND length(command_bytes)>0),
        CHECK((version_ordinal=1 AND previous_version_digest IS NULL)
           OR (version_ordinal>1 AND previous_version_digest IS NOT NULL))
    ) STRICT""",
    f"""CREATE TABLE event_scoped_local_watch_heads(
        watch_id TEXT PRIMARY KEY REFERENCES event_scoped_local_watches(watch_id),
        current_version_id TEXT NOT NULL,
        current_version_digest TEXT NOT NULL CHECK({_D.format('current_version_digest')}),
        current_version_ordinal INTEGER NOT NULL CHECK(current_version_ordinal BETWEEN 1 AND 10000),
        closed INTEGER NOT NULL CHECK(closed IN (0,1)),
        closure_digest TEXT CHECK(closure_digest IS NULL OR {_D.format('closure_digest')}),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_version_id,watch_id,current_version_digest)
            REFERENCES event_scoped_local_watch_versions(watch_version_id,watch_id,version_digest),
        CHECK((closed=0 AND closure_digest IS NULL) OR (closed=1 AND closure_digest IS NOT NULL))
    ) STRICT""",
    f"""CREATE TABLE event_scoped_local_watch_closures(
        closure_id TEXT PRIMARY KEY,
        watch_id TEXT NOT NULL UNIQUE REFERENCES event_scoped_local_watches(watch_id),
        watch_version_id TEXT NOT NULL,
        watch_version_digest TEXT NOT NULL CHECK({_D.format('watch_version_digest')}),
        closure_bytes BLOB NOT NULL,
        closure_digest TEXT NOT NULL UNIQUE CHECK({_D.format('closure_digest')}),
        outcome TEXT NOT NULL CHECK(outcome IN ('EXPIRED','CLOSED_BY_OWNER','EVENT_RESOLVED','CANCELLED','CONVERSION_PROPOSED','SUPERSEDED')),
        effective_at TEXT NOT NULL,
        locality_coverage_proposal_digest TEXT CHECK(locality_coverage_proposal_digest IS NULL OR {_D.format('locality_coverage_proposal_digest')}),
        reentry_bytes BLOB,
        reentry_digest TEXT UNIQUE CHECK(reentry_digest IS NULL OR {_D.format('reentry_digest')}),
        reentry_id TEXT UNIQUE,
        command_bytes BLOB NOT NULL,
        command_digest TEXT NOT NULL UNIQUE CHECK({_D.format('command_digest')}),
        command_id TEXT NOT NULL UNIQUE,
        request_id TEXT NOT NULL UNIQUE,
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(watch_version_id,watch_id,watch_version_digest)
            REFERENCES event_scoped_local_watch_versions(watch_version_id,watch_id,version_digest),
        CHECK(length(closure_bytes)>0 AND length(command_bytes)>0),
        CHECK((reentry_bytes IS NULL AND reentry_digest IS NULL AND reentry_id IS NULL)
           OR (reentry_bytes IS NOT NULL AND length(reentry_bytes)>0 AND reentry_digest IS NOT NULL AND reentry_id IS NOT NULL))
    ) STRICT""",
    "CREATE TRIGGER immutable_event_scoped_local_watches BEFORE UPDATE ON event_scoped_local_watches BEGIN SELECT RAISE(ABORT,'immutable Event-Scoped Local Watch'); END",
    "CREATE TRIGGER retained_event_scoped_local_watches BEFORE DELETE ON event_scoped_local_watches BEGIN SELECT RAISE(ABORT,'retained Event-Scoped Local Watch'); END",
    "CREATE TRIGGER immutable_event_scoped_local_watch_versions BEFORE UPDATE ON event_scoped_local_watch_versions BEGIN SELECT RAISE(ABORT,'immutable Local Watch Version'); END",
    "CREATE TRIGGER retained_event_scoped_local_watch_versions BEFORE DELETE ON event_scoped_local_watch_versions BEGIN SELECT RAISE(ABORT,'retained Local Watch Version'); END",
    "CREATE TRIGGER immutable_event_scoped_local_watch_closures BEFORE UPDATE ON event_scoped_local_watch_closures BEGIN SELECT RAISE(ABORT,'immutable Local Watch Closure'); END",
    "CREATE TRIGGER retained_event_scoped_local_watch_closures BEFORE DELETE ON event_scoped_local_watch_closures BEGIN SELECT RAISE(ABORT,'retained Local Watch Closure'); END",
    "CREATE TRIGGER retained_event_scoped_local_watch_heads BEFORE DELETE ON event_scoped_local_watch_heads BEGIN SELECT RAISE(ABORT,'retained Local Watch head'); END",
    """CREATE TRIGGER local_watch_version_predecessor_guard
       BEFORE INSERT ON event_scoped_local_watch_versions WHEN NEW.version_ordinal>1 AND NOT EXISTS(
          SELECT 1 FROM event_scoped_local_watch_heads h
          WHERE h.watch_id=NEW.watch_id AND h.closed=0
            AND h.current_version_ordinal=NEW.version_ordinal-1
            AND h.current_version_digest=NEW.previous_version_digest)
       BEGIN SELECT RAISE(ABORT,'Local Watch Version predecessor differs'); END""",
    """CREATE TRIGGER local_watch_closure_head_guard
       BEFORE INSERT ON event_scoped_local_watch_closures WHEN NOT EXISTS(
          SELECT 1 FROM event_scoped_local_watch_heads h
          WHERE h.watch_id=NEW.watch_id AND h.closed=0
            AND h.current_version_id=NEW.watch_version_id
            AND h.current_version_digest=NEW.watch_version_digest)
       BEGIN SELECT RAISE(ABORT,'Local Watch Closure head differs'); END""",
    """CREATE TRIGGER local_watch_head_progress_guard
       BEFORE UPDATE ON event_scoped_local_watch_heads WHEN
          OLD.closed=1
          OR NEW.current_version_ordinal NOT BETWEEN OLD.current_version_ordinal AND OLD.current_version_ordinal+1
          OR (NEW.current_version_ordinal=OLD.current_version_ordinal+1 AND (
                NEW.closed!=0 OR NEW.closure_digest IS NOT NULL
                OR NOT EXISTS(SELECT 1 FROM event_scoped_local_watch_versions v
                    WHERE v.watch_id=NEW.watch_id
                      AND v.watch_version_id=NEW.current_version_id
                      AND v.version_digest=NEW.current_version_digest
                      AND v.version_ordinal=NEW.current_version_ordinal)))
          OR (NEW.current_version_ordinal=OLD.current_version_ordinal AND (
                NEW.current_version_id!=OLD.current_version_id
                OR NEW.current_version_digest!=OLD.current_version_digest
                OR NEW.closed!=1 OR NEW.closure_digest IS NULL
                OR NOT EXISTS(SELECT 1 FROM event_scoped_local_watch_closures c
                    WHERE c.watch_id=NEW.watch_id
                      AND c.closure_digest=NEW.closure_digest)))
       BEGIN SELECT RAISE(ABORT,'Local Watch head progression differs'); END""",
)
LOCAL_WATCH_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": LOCAL_WATCH_SCHEMA_VERSION,
        "name": LOCAL_WATCH_MIGRATION_NAME,
        "statements": list(LOCAL_WATCH_MIGRATION_STATEMENTS),
    }
)
LOCAL_WATCH_MIGRATION = LocalWatchMigrationRecord(
    LOCAL_WATCH_SCHEMA_VERSION,
    LOCAL_WATCH_MIGRATION_NAME,
    LOCAL_WATCH_MIGRATION_CHECKSUM,
)
__all__ = [
    name for name in globals()
    if name.startswith(("LOCAL_WATCH_", "LocalWatch", "local_watch_", "prepare_", "require_"))
]
# fmt: on
