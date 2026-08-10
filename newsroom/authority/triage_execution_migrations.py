"""Checked v20 persistence for triage execution authority."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_json_bytes, digest_canonical

TRIAGE_EXECUTION_SCHEMA_VERSION = 20
TRIAGE_EXECUTION_MIGRATION_NAME = "triage_execution_authority_v20"
TRIAGE_EXECUTION_PREDECESSOR_FINGERPRINT = (
    "sha256:542bd9c351094cf4d56905fa92aa042924b5dab877cc04374a097c48fe6b6003"
)
TRIAGE_EXECUTION_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:d5f9702d359836e3b564ba1cadbad27e5fc17ba79e5155e2b34382ec30681177"
)


class TriageExecutionBackupError(sqlite3.DatabaseError):
    """The exact retained v19 backup boundary is absent or differs."""


@dataclass(frozen=True, slots=True)
class TriageExecutionBackupReceipt:
    backup_path: Path
    digest_path: Path
    backup_digest: str
    logical_digest: str


@dataclass(frozen=True, slots=True)
class TriageExecutionMigrationRecord:
    version: int
    name: str
    checksum: str


def triage_execution_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v20.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _logical_database_digest(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for statement in connection.iterdump():
        if not first:
            digest.update(b",")
        digest.update(canonical_json_bytes(statement))
        first = False
    digest.update(b"]")
    return "sha256:" + digest.hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    return digest_canonical(
        [[str(r[0]), str(r[1]), str(r[2]), " ".join(str(r[3] or "").split())] for r in rows]
    )


def prepare_triage_execution_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> TriageExecutionBackupReceipt:
    if connection.in_transaction:
        raise TriageExecutionBackupError("backup requires no active transaction")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 19:
        raise TriageExecutionBackupError("backup requires exact schema v19")
    if _schema_fingerprint(connection) != TRIAGE_EXECUTION_PREDECESSOR_FINGERPRINT:
        raise TriageExecutionBackupError("backup requires checked v19 schema")
    if not isinstance(backup_path, Path) or not backup_path.is_absolute():
        raise TriageExecutionBackupError("backup path must be absolute")
    source_path = Path(next(r[2] for r in connection.execute("PRAGMA database_list") if r[1] == "main"))
    if not source_path or source_path.resolve() == backup_path.resolve():
        raise TriageExecutionBackupError("backup path must differ from source")
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical_digest = _logical_database_digest(connection)
    if backup_path.exists() != digest_path.exists():
        raise TriageExecutionBackupError("backup receipt is incomplete")
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
        raise TriageExecutionBackupError("retained backup digest differs")
    target = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (target.execute("PRAGMA user_version").fetchone()[0] != 19
            or _schema_fingerprint(target) != TRIAGE_EXECUTION_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest):
            raise TriageExecutionBackupError("retained backup differs from source")
    finally:
        target.close()
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS triage_execution_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM triage_execution_backup_gate")
    connection.execute("INSERT INTO triage_execution_backup_gate VALUES(?,?,?)", (str(backup_path), backup_digest, logical_digest))
    if connection.in_transaction:
        connection.commit()
    return TriageExecutionBackupReceipt(backup_path, digest_path, backup_digest, logical_digest)


def require_triage_execution_backup(
    connection: sqlite3.Connection, *, expected_history: tuple[tuple[int, str, str], ...]
) -> TriageExecutionBackupReceipt:
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest FROM temp.triage_execution_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise TriageExecutionBackupError("v19 to v20 upgrade requires a prepared backup") from exc
    if row is None:
        raise TriageExecutionBackupError("v19 to v20 upgrade requires a prepared backup")
    backup_path, backup_digest, logical_digest = Path(str(row[0])), str(row[1]), str(row[2])
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    if (not backup_path.is_file() or not digest_path.is_file()
        or _file_digest(backup_path) != backup_digest
        or digest_path.read_text(encoding="ascii") != backup_digest + "\n"
        or _logical_database_digest(connection) != logical_digest):
        raise TriageExecutionBackupError("prepared backup identity differs")
    target = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True, isolation_level=None)
    try:
        history = target.execute("SELECT version,name,checksum FROM authority_migrations ORDER BY version").fetchall()
        if (target.execute("PRAGMA user_version").fetchone()[0] != 19
            or _schema_fingerprint(target) != TRIAGE_EXECUTION_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
            or history != list(expected_history)):
            raise TriageExecutionBackupError("prepared backup is not exact v19")
    finally:
        target.close()
    return TriageExecutionBackupReceipt(backup_path, digest_path, backup_digest, logical_digest)


_DIGEST_CHECK = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"

TRIAGE_EXECUTION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE triage_execution_batches(
        batch_id TEXT PRIMARY KEY,
        member_count INTEGER NOT NULL CHECK(member_count BETWEEN 1 AND 48),
        canonical_bytes BLOB NOT NULL CHECK(length(canonical_bytes) BETWEEN 1 AND 69632),
        canonical_digest TEXT NOT NULL UNIQUE CHECK({_DIGEST_CHECK.format('canonical_digest')}),
        actor_identity_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('actor_identity_digest')}),
        authority_event_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(batch_id,canonical_digest)
    ) STRICT""",
    f"""CREATE TABLE triage_worker_attempts(
        attempt_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES triage_execution_batches(batch_id),
        work_item_id TEXT NOT NULL,
        work_item_version_id TEXT NOT NULL,
        work_item_version_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('work_item_version_digest')}),
        retrieval_context_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('retrieval_context_digest')}),
        priority_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('priority_digest')}),
        ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
        previous_attempt_id TEXT REFERENCES triage_worker_attempts(attempt_id),
        previous_attempt_digest TEXT CHECK(previous_attempt_digest IS NULL OR {_DIGEST_CHECK.format('previous_attempt_digest')}),
        semantic_request_key TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL CHECK(length(canonical_bytes) BETWEEN 1 AND 69632),
        canonical_digest TEXT NOT NULL UNIQUE CHECK({_DIGEST_CHECK.format('canonical_digest')}),
        actor_identity_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('actor_identity_digest')}),
        authority_event_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(work_item_id,work_item_version_id,ordinal),
        UNIQUE(previous_attempt_id),
        UNIQUE(attempt_id,batch_id,work_item_id,work_item_version_id),
        FOREIGN KEY(work_item_version_id,work_item_id)
            REFERENCES triage_work_item_versions(version_id,work_item_id),
        CHECK((ordinal=1 AND previous_attempt_id IS NULL AND previous_attempt_digest IS NULL)
           OR (ordinal>1 AND previous_attempt_id IS NOT NULL AND previous_attempt_digest IS NOT NULL))
    ) STRICT""",
    f"""CREATE TABLE triage_work_item_leases(
        lease_id TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL UNIQUE,
        attempt_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('attempt_digest')}),
        batch_id TEXT NOT NULL,
        work_item_id TEXT NOT NULL,
        work_item_version_id TEXT NOT NULL,
        work_item_version_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('work_item_version_digest')}),
        owner_id TEXT NOT NULL,
        owner_profile_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('owner_profile_digest')}),
        capability_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('capability_digest')}),
        fence INTEGER NOT NULL CHECK(fence BETWEEN 1 AND 9007199254740991),
        lifecycle TEXT NOT NULL CHECK(lifecycle IN ('CLAIMED','RELEASED','EXPIRED')),
        issued_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL CHECK(length(canonical_bytes) BETWEEN 1 AND 69632),
        canonical_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('canonical_digest')}),
        actor_identity_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('actor_identity_digest')}),
        authority_event_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(work_item_id,fence),
        FOREIGN KEY(attempt_id,batch_id,work_item_id,work_item_version_id)
            REFERENCES triage_worker_attempts(attempt_id,batch_id,work_item_id,work_item_version_id)
    ) STRICT""",
    """CREATE UNIQUE INDEX one_claimed_triage_lease_per_work_item
        ON triage_work_item_leases(work_item_id) WHERE lifecycle='CLAIMED'""",
    """CREATE TRIGGER triage_execution_batch_coherence BEFORE INSERT ON triage_execution_batches
        WHEN NOT json_valid(CAST(NEW.canonical_bytes AS TEXT))
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.batch_id') IS NOT NEW.batch_id
          OR json_array_length(json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.members')) IS NOT NEW.member_count
        BEGIN SELECT RAISE(ABORT,'execution Batch scalars differ from canonical bytes'); END""",
    """CREATE TRIGGER triage_worker_attempt_coherence BEFORE INSERT ON triage_worker_attempts
        WHEN NOT json_valid(CAST(NEW.canonical_bytes AS TEXT))
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.attempt_id') IS NOT NEW.attempt_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.work_item_id') IS NOT NEW.work_item_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.work_item_version_id') IS NOT NEW.work_item_version_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.work_item_version_digest') IS NOT NEW.work_item_version_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.retrieval_context_digest') IS NOT NEW.retrieval_context_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.priority_digest') IS NOT NEW.priority_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.ordinal') IS NOT NEW.ordinal
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.previous_attempt_id') IS NOT NEW.previous_attempt_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.previous_attempt_digest') IS NOT NEW.previous_attempt_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.semantic_request_key') IS NOT NEW.semantic_request_key
          OR (NEW.ordinal>1 AND NOT EXISTS(
              SELECT 1 FROM triage_worker_attempts p
              WHERE p.attempt_id=NEW.previous_attempt_id
                AND p.batch_id=NEW.batch_id
                AND p.canonical_digest=NEW.previous_attempt_digest))
          OR (NEW.ordinal>1 AND NOT EXISTS(
              SELECT 1 FROM triage_work_item_leases l
              WHERE l.attempt_id=NEW.previous_attempt_id
                AND l.lifecycle IN ('RELEASED','EXPIRED')))
          OR NOT EXISTS(
              SELECT 1 FROM triage_execution_batches b, json_each(CAST(b.canonical_bytes AS TEXT),'$.members') m
              WHERE b.batch_id=NEW.batch_id
                AND json_extract(m.value,'$.work_item_id')=NEW.work_item_id
                AND json_extract(m.value,'$.work_item_version_id')=NEW.work_item_version_id
                AND json_extract(m.value,'$.work_item_version_digest')=NEW.work_item_version_digest
                AND json_extract(m.value,'$.retrieval_context_digest')=NEW.retrieval_context_digest
                AND json_extract(m.value,'$.priority_digest')=NEW.priority_digest)
        BEGIN SELECT RAISE(ABORT,'Worker Attempt scalars or Batch membership differ'); END""",
    """CREATE TRIGGER triage_lease_insert_coherence BEFORE INSERT ON triage_work_item_leases
        WHEN NOT json_valid(CAST(NEW.canonical_bytes AS TEXT))
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.lease_id') IS NOT NEW.lease_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.attempt_id') IS NOT NEW.attempt_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.attempt_digest') IS NOT NEW.attempt_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.work_item_id') IS NOT NEW.work_item_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.work_item_version_id') IS NOT NEW.work_item_version_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.work_item_version_digest') IS NOT NEW.work_item_version_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.owner_id') IS NOT NEW.owner_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.owner_profile_digest') IS NOT NEW.owner_profile_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.capability_digest') IS NOT NEW.capability_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.fence') IS NOT NEW.fence
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.lifecycle') IS NOT NEW.lifecycle
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.issued_at') IS NOT NEW.issued_at
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.expires_at') IS NOT NEW.expires_at
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.transitions[#-1].actor_identity_digest')
             IS NOT NEW.actor_identity_digest
        BEGIN SELECT RAISE(ABORT,'Lease scalars differ from canonical bytes'); END""",
    """CREATE TRIGGER triage_lease_update_guard BEFORE UPDATE ON triage_work_item_leases
        WHEN NEW.lease_id IS NOT OLD.lease_id OR NEW.attempt_id IS NOT OLD.attempt_id
          OR NEW.attempt_digest IS NOT OLD.attempt_digest OR NEW.batch_id IS NOT OLD.batch_id
          OR NEW.work_item_id IS NOT OLD.work_item_id OR NEW.work_item_version_id IS NOT OLD.work_item_version_id
          OR NEW.work_item_version_digest IS NOT OLD.work_item_version_digest
          OR NEW.owner_id IS NOT OLD.owner_id OR NEW.owner_profile_digest IS NOT OLD.owner_profile_digest
          OR NEW.capability_digest IS NOT OLD.capability_digest OR NEW.fence IS NOT OLD.fence
          OR NEW.issued_at IS NOT OLD.issued_at OR NEW.expires_at IS NOT OLD.expires_at
          OR OLD.lifecycle!='CLAIMED' OR NEW.lifecycle NOT IN ('RELEASED','EXPIRED')
          OR NOT json_valid(CAST(NEW.canonical_bytes AS TEXT))
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.lifecycle') IS NOT NEW.lifecycle
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.lease_id') IS NOT NEW.lease_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.attempt_digest') IS NOT NEW.attempt_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.fence') IS NOT NEW.fence
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.transitions[#-1].actor_identity_digest')
             IS NOT NEW.actor_identity_digest
        BEGIN SELECT RAISE(ABORT,'illegal Lease CAS update'); END""",
    """CREATE TRIGGER retained_execution_batch_update BEFORE UPDATE ON triage_execution_batches BEGIN SELECT RAISE(ABORT,'immutable execution Batch'); END""",
    """CREATE TRIGGER retained_execution_batch_delete BEFORE DELETE ON triage_execution_batches BEGIN SELECT RAISE(ABORT,'retained execution Batch'); END""",
    """CREATE TRIGGER retained_worker_attempt_update BEFORE UPDATE ON triage_worker_attempts BEGIN SELECT RAISE(ABORT,'immutable Worker Attempt'); END""",
    """CREATE TRIGGER retained_worker_attempt_delete BEFORE DELETE ON triage_worker_attempts BEGIN SELECT RAISE(ABORT,'retained Worker Attempt'); END""",
    """CREATE TRIGGER retained_work_item_lease_delete BEFORE DELETE ON triage_work_item_leases BEGIN SELECT RAISE(ABORT,'retained Work Item Lease'); END""",
)

TRIAGE_EXECUTION_MIGRATION_CHECKSUM = digest_canonical({
    "version": TRIAGE_EXECUTION_SCHEMA_VERSION,
    "name": TRIAGE_EXECUTION_MIGRATION_NAME,
    "statements": list(TRIAGE_EXECUTION_MIGRATION_STATEMENTS),
})
TRIAGE_EXECUTION_MIGRATION = TriageExecutionMigrationRecord(
    TRIAGE_EXECUTION_SCHEMA_VERSION,
    TRIAGE_EXECUTION_MIGRATION_NAME,
    TRIAGE_EXECUTION_MIGRATION_CHECKSUM,
)

__all__ = [
    "TRIAGE_EXECUTION_MIGRATION", "TRIAGE_EXECUTION_MIGRATION_CHECKSUM",
    "TRIAGE_EXECUTION_MIGRATION_NAME", "TRIAGE_EXECUTION_MIGRATION_STATEMENTS",
    "TRIAGE_EXECUTION_PREDECESSOR_FINGERPRINT",
    "TRIAGE_EXECUTION_PREDECESSOR_MIGRATION_CHECKSUM",
    "TRIAGE_EXECUTION_SCHEMA_VERSION", "TriageExecutionBackupError",
    "TriageExecutionBackupReceipt", "prepare_triage_execution_backup",
    "require_triage_execution_backup", "triage_execution_backup_paths",
]
