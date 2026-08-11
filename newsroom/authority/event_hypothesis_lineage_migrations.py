"""Checked v23 persistence for Event Hypothesis lineage authority."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_json_bytes, digest_canonical

EVENT_HYPOTHESIS_LINEAGE_SCHEMA_VERSION = 23
EVENT_HYPOTHESIS_LINEAGE_MIGRATION_NAME = "event_hypothesis_lineage_authority_v23"
EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:e59eb222a95e2901ccaae29ce1b9e8eded797306e9796718a6d2c4fa505a6636"
)
EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT = (
    "sha256:2118fa893fb7fd2911bbde3056b79b1d0e26ccd6903e1c4228616f342898eaad"
)


class EventHypothesisLineageBackupError(sqlite3.DatabaseError):
    """The exact retained v22 backup boundary is absent or differs."""


@dataclass(frozen=True, slots=True)
class EventHypothesisLineageBackupReceipt:
    backup_path: Path
    digest_path: Path
    backup_digest: str
    logical_digest: str


@dataclass(frozen=True, slots=True)
class EventHypothesisLineageMigrationRecord:
    version: int
    name: str
    checksum: str


def event_hypothesis_lineage_backup_paths(
    database: str | Path,
) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v23.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _logical_database_digest(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    for index, statement in enumerate(connection.iterdump()):
        if index:
            digest.update(b",")
        digest.update(canonical_json_bytes(statement))
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
        [
            [str(r[0]), str(r[1]), str(r[2]), " ".join(str(r[3] or "").split())]
            for r in rows
        ]
    )


def prepare_event_hypothesis_lineage_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> EventHypothesisLineageBackupReceipt:
    if connection.in_transaction:
        raise EventHypothesisLineageBackupError("backup requires no active transaction")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 22:
        raise EventHypothesisLineageBackupError("backup requires exact schema v22")
    if (
        _schema_fingerprint(connection)
        != EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT
    ):
        raise EventHypothesisLineageBackupError("backup requires checked v22 schema")
    if not isinstance(backup_path, Path) or not backup_path.is_absolute():
        raise EventHypothesisLineageBackupError("backup path must be absolute")
    source_path = Path(
        next(r[2] for r in connection.execute("PRAGMA database_list") if r[1] == "main")
    )
    if not source_path or source_path.resolve() == backup_path.resolve():
        raise EventHypothesisLineageBackupError("backup path must differ from source")
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical_digest = _logical_database_digest(connection)
    if backup_path.exists() != digest_path.exists():
        raise EventHypothesisLineageBackupError("backup receipt is incomplete")
    if not backup_path.exists():
        backup_path.open("xb").close()
        target = sqlite3.connect(backup_path, isolation_level=None)
        try:
            connection.backup(target)
        finally:
            target.close()
        backup_digest = _file_digest(backup_path)
        digest_path.write_text(backup_digest + "\n", encoding="ascii")
    else:
        backup_digest = _file_digest(backup_path)
    if digest_path.read_text(encoding="ascii") != backup_digest + "\n":
        raise EventHypothesisLineageBackupError("retained backup digest differs")
    target = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 22
            or _schema_fingerprint(target)
            != EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
        ):
            raise EventHypothesisLineageBackupError(
                "retained backup differs from source"
            )
    finally:
        target.close()
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS event_hypothesis_lineage_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM event_hypothesis_lineage_backup_gate")
    connection.execute(
        "INSERT INTO event_hypothesis_lineage_backup_gate VALUES(?,?,?)",
        (str(backup_path), backup_digest, logical_digest),
    )
    if connection.in_transaction:
        connection.commit()
    return EventHypothesisLineageBackupReceipt(
        backup_path, digest_path, backup_digest, logical_digest
    )


def require_event_hypothesis_lineage_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> EventHypothesisLineageBackupReceipt:
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.event_hypothesis_lineage_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise EventHypothesisLineageBackupError(
            "v22 to v23 upgrade requires a prepared backup"
        ) from exc
    if row is None:
        raise EventHypothesisLineageBackupError(
            "v22 to v23 upgrade requires a prepared backup"
        )
    backup_path, backup_digest, logical_digest = Path(row[0]), str(row[1]), str(row[2])
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    if (
        not backup_path.is_file()
        or not digest_path.is_file()
        or _file_digest(backup_path) != backup_digest
        or digest_path.read_text(encoding="ascii") != backup_digest + "\n"
        or _logical_database_digest(connection) != logical_digest
    ):
        raise EventHypothesisLineageBackupError("prepared backup identity differs")
    target = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        history = target.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 22
            or _schema_fingerprint(target)
            != EVENT_HYPOTHESIS_LINEAGE_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
            or history != list(expected_history)
        ):
            raise EventHypothesisLineageBackupError("prepared backup is not exact v22")
    finally:
        target.close()
    return EventHypothesisLineageBackupReceipt(
        backup_path, digest_path, backup_digest, logical_digest
    )


_DIGEST = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
_UUID = "length({0})=36 AND substr({0},15,1)='4' AND lower(substr({0},20,1)) IN ('8','9','a','b')"

EVENT_HYPOTHESIS_LINEAGE_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE event_hypothesis_lineage(
        lineage_id TEXT PRIMARY KEY,
        authority_aggregate_id TEXT NOT NULL UNIQUE CHECK({_UUID.format("authority_aggregate_id")}),
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        kind TEXT NOT NULL CHECK(kind IN ('HYPOTHESIS_CONSOLIDATION','HYPOTHESIS_SPLIT','HYPOTHESIS_REVERSAL_LINEAGE')),
        expected_generation INTEGER NOT NULL CHECK(expected_generation>=0 AND expected_generation<9007199254740991),
        receipt_bytes BLOB NOT NULL CHECK(length(receipt_bytes) BETWEEN 1 AND 1048576),
        receipt_digest TEXT NOT NULL UNIQUE CHECK({_DIGEST.format("receipt_digest")}),
        reversal_target_lineage_id TEXT REFERENCES event_hypothesis_lineage(lineage_id),
        reversal_target_lineage_digest TEXT CHECK(reversal_target_lineage_digest IS NULL OR {_DIGEST.format("reversal_target_lineage_digest")}),
        actor_identity_digest TEXT NOT NULL CHECK({_DIGEST.format("actor_identity_digest")}),
        recorded_at TEXT NOT NULL,
        CHECK((kind='HYPOTHESIS_REVERSAL_LINEAGE' AND reversal_target_lineage_id IS NOT NULL AND reversal_target_lineage_digest IS NOT NULL) OR (kind!='HYPOTHESIS_REVERSAL_LINEAGE' AND reversal_target_lineage_id IS NULL AND reversal_target_lineage_digest IS NULL))
    ) STRICT""",
    f"""CREATE TABLE event_hypothesis_lineage_heads(
        hypothesis_id TEXT PRIMARY KEY,
        version_id TEXT NOT NULL UNIQUE REFERENCES event_hypothesis_versions_v2(version_id),
        version_digest TEXT NOT NULL CHECK({_DIGEST.format("version_digest")}),
        generation INTEGER NOT NULL CHECK(generation>=0 AND generation<9007199254740991),
        producing_lineage_id TEXT NOT NULL REFERENCES event_hypothesis_lineage(lineage_id),
        updated_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TRIGGER event_hypothesis_lineage_coherence BEFORE INSERT ON event_hypothesis_lineage
      WHEN NOT json_valid(CAST(NEW.receipt_bytes AS TEXT))
        OR json_extract(CAST(NEW.receipt_bytes AS TEXT),'$.schema_version') IS NOT 'newsroom.increment6.hypothesis-lineage.v1'
        OR json_extract(CAST(NEW.receipt_bytes AS TEXT),'$.lineage_id') IS NOT NEW.lineage_id
        OR json_extract(CAST(NEW.receipt_bytes AS TEXT),'$.kind') IS NOT NEW.kind
        OR json_extract(CAST(NEW.receipt_bytes AS TEXT),'$.expected_generation') IS NOT NEW.expected_generation
        OR json_extract(CAST(NEW.receipt_bytes AS TEXT),'$.reversal_target.lineage_id') IS NOT NEW.reversal_target_lineage_id
        OR json_extract(CAST(NEW.receipt_bytes AS TEXT),'$.reversal_target.lineage_digest') IS NOT NEW.reversal_target_lineage_digest
      BEGIN SELECT RAISE(ABORT,'lineage receipt scalars differ'); END""",
    """CREATE TRIGGER event_hypothesis_lineage_head_insert_guard BEFORE INSERT ON event_hypothesis_lineage_heads
      WHEN NOT EXISTS(SELECT 1 FROM event_hypothesis_lineage l WHERE l.lineage_id=NEW.producing_lineage_id)
      BEGIN SELECT RAISE(ABORT,'lineage head producer differs'); END""",
    """CREATE TRIGGER event_hypothesis_lineage_head_update_guard BEFORE UPDATE ON event_hypothesis_lineage_heads
      WHEN NEW.generation<=OLD.generation OR NOT EXISTS(SELECT 1 FROM event_hypothesis_lineage l WHERE l.lineage_id=NEW.producing_lineage_id)
      BEGIN SELECT RAISE(ABORT,'lineage head transition differs'); END""",
    """CREATE TRIGGER immutable_event_hypothesis_lineage_update BEFORE UPDATE ON event_hypothesis_lineage BEGIN SELECT RAISE(ABORT,'immutable lineage receipt'); END""",
    """CREATE TRIGGER retained_event_hypothesis_lineage_delete BEFORE DELETE ON event_hypothesis_lineage BEGIN SELECT RAISE(ABORT,'retained lineage receipt'); END""",
)
EVENT_HYPOTHESIS_LINEAGE_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": EVENT_HYPOTHESIS_LINEAGE_SCHEMA_VERSION,
        "name": EVENT_HYPOTHESIS_LINEAGE_MIGRATION_NAME,
        "statements": list(EVENT_HYPOTHESIS_LINEAGE_MIGRATION_STATEMENTS),
    }
)
EVENT_HYPOTHESIS_LINEAGE_MIGRATION = EventHypothesisLineageMigrationRecord(
    EVENT_HYPOTHESIS_LINEAGE_SCHEMA_VERSION,
    EVENT_HYPOTHESIS_LINEAGE_MIGRATION_NAME,
    EVENT_HYPOTHESIS_LINEAGE_MIGRATION_CHECKSUM,
)

__all__ = [
    name
    for name in globals()
    if name.startswith(("EVENT_", "Event", "event_", "prepare_", "require_"))
]
