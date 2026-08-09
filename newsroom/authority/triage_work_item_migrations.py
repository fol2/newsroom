"""Checked v18 persistence for immutable Triage Work Items."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .canonical import digest_canonical

TRIAGE_WORK_ITEM_SCHEMA_VERSION = 18
TRIAGE_WORK_ITEM_MIGRATION_NAME = "triage_work_item_authority_v18"
TRIAGE_WORK_ITEM_PREDECESSOR_FINGERPRINT = (
    "sha256:aaa9544bc6f90dce5831452cffb227967175901e4f7b085e17056ac4194109f5"
)
TRIAGE_WORK_ITEM_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:c15b3a3fc90833048938b591291d16f59ee1f36b54a6d72dbd04b63877682e7f"
)


class TriageWorkItemBackupError(sqlite3.DatabaseError):
    """The exact retained v17 backup boundary is absent or differs."""


@dataclass(frozen=True, slots=True)
class TriageWorkItemBackupReceipt:
    backup_path: Path
    digest_path: Path
    backup_digest: str
    logical_digest: str


@dataclass(frozen=True, slots=True)
class TriageWorkItemMigrationRecord:
    version: int
    name: str
    checksum: str


def triage_work_item_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v18.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _logical_database_digest(connection: sqlite3.Connection) -> str:
    return digest_canonical(list(connection.iterdump()))


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    return digest_canonical(
        [
            [str(r[0]), str(r[1]), str(r[2]), " ".join(str(r[3] or "").split())]
            for r in rows
        ]
    )


def prepare_triage_work_item_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> TriageWorkItemBackupReceipt:
    """Retain an exact v17 SQLite backup and SHA-256 receipt."""
    if connection.in_transaction:
        raise TriageWorkItemBackupError("backup requires no active transaction")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 17:
        raise TriageWorkItemBackupError("backup requires exact schema v17")
    if _schema_fingerprint(connection) != TRIAGE_WORK_ITEM_PREDECESSOR_FINGERPRINT:
        raise TriageWorkItemBackupError("backup requires checked v17 schema")
    if not isinstance(backup_path, Path) or not backup_path.is_absolute():
        raise TriageWorkItemBackupError("backup path must be absolute")
    source_path = Path(
        next(r[2] for r in connection.execute("PRAGMA database_list") if r[1] == "main")
    )
    if not source_path or source_path.resolve() == backup_path.resolve():
        raise TriageWorkItemBackupError("backup path must differ from source")
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical_digest = _logical_database_digest(connection)
    if backup_path.exists() != digest_path.exists():
        raise TriageWorkItemBackupError("backup receipt is incomplete")
    if not backup_path.exists():
        backup_path.open("xb").close()
        target = sqlite3.connect(backup_path, isolation_level=None)
        try:
            connection.backup(target)
        finally:
            target.close()
        backup_digest = _file_digest(backup_path)
        with digest_path.open("x", encoding="ascii") as receipt:
            receipt.write(backup_digest + "\n")
    else:
        backup_digest = _file_digest(backup_path)
    if digest_path.read_text(encoding="ascii") != backup_digest + "\n":
        raise TriageWorkItemBackupError("retained backup digest differs")
    target = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 17
            or _schema_fingerprint(target) != TRIAGE_WORK_ITEM_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
        ):
            raise TriageWorkItemBackupError("retained backup differs from source")
    finally:
        target.close()
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS triage_work_item_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM triage_work_item_backup_gate")
    connection.execute(
        "INSERT INTO triage_work_item_backup_gate VALUES(?,?,?)",
        (str(backup_path), backup_digest, logical_digest),
    )
    if connection.in_transaction:
        connection.commit()
    return TriageWorkItemBackupReceipt(
        backup_path, digest_path, backup_digest, logical_digest
    )


def require_triage_work_item_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> TriageWorkItemBackupReceipt:
    """Revalidate the prepared v17 backup while holding the migration lock."""
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest FROM temp.triage_work_item_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise TriageWorkItemBackupError(
            "v17 to v18 upgrade requires a prepared backup"
        ) from exc
    if row is None:
        raise TriageWorkItemBackupError("v17 to v18 upgrade requires a prepared backup")
    backup_path, backup_digest, logical_digest = (
        Path(str(row[0])),
        str(row[1]),
        str(row[2]),
    )
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    if (
        not backup_path.is_file()
        or not digest_path.is_file()
        or _file_digest(backup_path) != backup_digest
        or digest_path.read_text(encoding="ascii") != backup_digest + "\n"
        or _logical_database_digest(connection) != logical_digest
    ):
        raise TriageWorkItemBackupError("prepared backup identity differs")
    target = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        history = target.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 17
            or _schema_fingerprint(target) != TRIAGE_WORK_ITEM_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
            or history != list(expected_history)
        ):
            raise TriageWorkItemBackupError("prepared backup is not exact v17")
    finally:
        target.close()
    return TriageWorkItemBackupReceipt(
        backup_path, digest_path, backup_digest, logical_digest
    )


TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE triage_work_items(
        work_item_id TEXT PRIMARY KEY,
        schema_identity TEXT NOT NULL CHECK(schema_identity='newsroom.increment6.triage-work-item.v1'),
        decision_scope_digest TEXT NOT NULL UNIQUE,
        decision_lead_count INTEGER NOT NULL CHECK(decision_lead_count BETWEEN 1 AND 32),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE triage_work_item_versions(
        version_id TEXT PRIMARY KEY,
        schema_identity TEXT NOT NULL CHECK(schema_identity='newsroom.increment6.triage-work-item-version.v1'),
        work_item_id TEXT NOT NULL REFERENCES triage_work_items(work_item_id),
        ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 1000000),
        previous_version_id TEXT REFERENCES triage_work_item_versions(version_id),
        decision_scope_digest TEXT NOT NULL,
        retrieval_outcome TEXT NOT NULL,
        watch_causality_digest TEXT UNIQUE,
        supplemental_causality_digest TEXT UNIQUE,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL,
        UNIQUE(work_item_id,ordinal),
        UNIQUE(version_id,work_item_id),
        CHECK((ordinal=1 AND previous_version_id IS NULL) OR (ordinal>1 AND previous_version_id IS NOT NULL)),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE triage_work_item_heads(
        work_item_id TEXT PRIMARY KEY REFERENCES triage_work_items(work_item_id),
        current_version_id TEXT NOT NULL UNIQUE,
        current_ordinal INTEGER NOT NULL CHECK(current_ordinal>0),
        current_version_digest TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_version_id,work_item_id) REFERENCES triage_work_item_versions(version_id,work_item_id)
    ) STRICT""",
    """CREATE TRIGGER immutable_triage_work_items_update BEFORE UPDATE ON triage_work_items
        BEGIN SELECT RAISE(ABORT,'immutable Triage Work Item'); END""",
    """CREATE TRIGGER retained_triage_work_items_delete BEFORE DELETE ON triage_work_items
        BEGIN SELECT RAISE(ABORT,'retained Triage Work Item'); END""",
    """CREATE TRIGGER immutable_triage_work_item_versions_update BEFORE UPDATE ON triage_work_item_versions
        BEGIN SELECT RAISE(ABORT,'immutable Triage Work Item Version'); END""",
    """CREATE TRIGGER triage_work_item_version_scope_guard BEFORE INSERT ON triage_work_item_versions
        WHEN NOT EXISTS(SELECT 1 FROM triage_work_items i
            WHERE i.work_item_id=NEW.work_item_id
              AND i.decision_scope_digest=NEW.decision_scope_digest)
        BEGIN SELECT RAISE(ABORT,'Work Item Version scope differs'); END""",
    """CREATE TRIGGER triage_work_item_version_causality_guard BEFORE INSERT ON triage_work_item_versions
        WHEN (json_type(CAST(NEW.canonical_bytes AS TEXT),'$.watch')!='null')
             !=(NEW.watch_causality_digest IS NOT NULL)
          OR (json_type(CAST(NEW.canonical_bytes AS TEXT),'$.supplemental_reentry')!='null')
             !=(NEW.supplemental_causality_digest IS NOT NULL)
        BEGIN SELECT RAISE(ABORT,'Work Item Version causality differs'); END""",
    """CREATE TRIGGER retained_triage_work_item_versions_delete BEFORE DELETE ON triage_work_item_versions
        BEGIN SELECT RAISE(ABORT,'retained Triage Work Item Version'); END""",
    """CREATE TRIGGER triage_work_item_head_insert_guard BEFORE INSERT ON triage_work_item_heads
        WHEN NEW.current_ordinal!=1 OR NOT EXISTS(
            SELECT 1 FROM triage_work_item_versions v WHERE v.version_id=NEW.current_version_id
            AND v.work_item_id=NEW.work_item_id AND v.ordinal=1 AND v.previous_version_id IS NULL
            AND v.canonical_digest=NEW.current_version_digest)
        BEGIN SELECT RAISE(ABORT,'invalid initial Work Item head'); END""",
    """CREATE TRIGGER triage_work_item_head_forward_guard BEFORE UPDATE ON triage_work_item_heads
        WHEN NEW.work_item_id!=OLD.work_item_id OR NEW.current_ordinal!=OLD.current_ordinal+1
        OR NOT EXISTS(SELECT 1 FROM triage_work_item_versions v
            WHERE v.version_id=NEW.current_version_id AND v.work_item_id=NEW.work_item_id
            AND v.ordinal=NEW.current_ordinal AND v.previous_version_id=OLD.current_version_id
            AND v.canonical_digest=NEW.current_version_digest)
        BEGIN SELECT RAISE(ABORT,'Work Item head must advance to immediate successor'); END""",
    """CREATE TRIGGER retained_triage_work_item_heads_delete BEFORE DELETE ON triage_work_item_heads
        BEGIN SELECT RAISE(ABORT,'retained Triage Work Item head'); END""",
)

TRIAGE_WORK_ITEM_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": TRIAGE_WORK_ITEM_SCHEMA_VERSION,
        "name": TRIAGE_WORK_ITEM_MIGRATION_NAME,
        "statements": list(TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS),
    }
)
TRIAGE_WORK_ITEM_MIGRATION = TriageWorkItemMigrationRecord(
    TRIAGE_WORK_ITEM_SCHEMA_VERSION,
    TRIAGE_WORK_ITEM_MIGRATION_NAME,
    TRIAGE_WORK_ITEM_MIGRATION_CHECKSUM,
)


__all__ = [
    "TRIAGE_WORK_ITEM_MIGRATION",
    "TRIAGE_WORK_ITEM_MIGRATION_CHECKSUM",
    "TRIAGE_WORK_ITEM_MIGRATION_NAME",
    "TRIAGE_WORK_ITEM_MIGRATION_STATEMENTS",
    "TRIAGE_WORK_ITEM_PREDECESSOR_FINGERPRINT",
    "TRIAGE_WORK_ITEM_PREDECESSOR_MIGRATION_CHECKSUM",
    "TRIAGE_WORK_ITEM_SCHEMA_VERSION",
    "TriageWorkItemBackupError",
    "TriageWorkItemBackupReceipt",
    "prepare_triage_work_item_backup",
    "require_triage_work_item_backup",
    "triage_work_item_backup_paths",
]
