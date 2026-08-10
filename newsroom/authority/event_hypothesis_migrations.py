"""Checked v21 persistence for Event Hypothesis authority."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_json_bytes, digest_canonical

EVENT_HYPOTHESIS_SCHEMA_VERSION = 21
EVENT_HYPOTHESIS_MIGRATION_NAME = "event_hypothesis_authority_v21"
EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT = (
    "sha256:36a7c9910775ede9c29113a43e08bba261a5a98c4fab5225dd2cae9448689389"
)
EVENT_HYPOTHESIS_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:6eb04f981f650bbb4956f148d11f1656bcd2b7c510117db96602dd9d83ab9bd3"
)


class EventHypothesisBackupError(sqlite3.DatabaseError):
    """The exact retained v20 backup boundary is absent or differs."""


@dataclass(frozen=True, slots=True)
class EventHypothesisBackupReceipt:
    backup_path: Path
    digest_path: Path
    backup_digest: str
    logical_digest: str


@dataclass(frozen=True, slots=True)
class EventHypothesisMigrationRecord:
    version: int
    name: str
    checksum: str


def event_hypothesis_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v21.sqlite3")
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
        [
            [str(r[0]), str(r[1]), str(r[2]), " ".join(str(r[3] or "").split())]
            for r in rows
        ]
    )


def prepare_event_hypothesis_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> EventHypothesisBackupReceipt:
    if connection.in_transaction:
        raise EventHypothesisBackupError("backup requires no active transaction")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 20:
        raise EventHypothesisBackupError("backup requires exact schema v20")
    if _schema_fingerprint(connection) != EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT:
        raise EventHypothesisBackupError("backup requires checked v20 schema")
    if not isinstance(backup_path, Path) or not backup_path.is_absolute():
        raise EventHypothesisBackupError("backup path must be absolute")
    source_path = Path(
        next(r[2] for r in connection.execute("PRAGMA database_list") if r[1] == "main")
    )
    if not source_path or source_path.resolve() == backup_path.resolve():
        raise EventHypothesisBackupError("backup path must differ from source")
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical_digest = _logical_database_digest(connection)
    if backup_path.exists() != digest_path.exists():
        raise EventHypothesisBackupError("backup receipt is incomplete")
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
        raise EventHypothesisBackupError("retained backup digest differs")
    target = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 20
            or _schema_fingerprint(target) != EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
        ):
            raise EventHypothesisBackupError("retained backup differs from source")
    finally:
        target.close()
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS event_hypothesis_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM event_hypothesis_backup_gate")
    connection.execute(
        "INSERT INTO event_hypothesis_backup_gate VALUES(?,?,?)",
        (str(backup_path), backup_digest, logical_digest),
    )
    if connection.in_transaction:
        connection.commit()
    return EventHypothesisBackupReceipt(
        backup_path, digest_path, backup_digest, logical_digest
    )


def require_event_hypothesis_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> EventHypothesisBackupReceipt:
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest FROM temp.event_hypothesis_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise EventHypothesisBackupError(
            "v20 to v21 upgrade requires a prepared backup"
        ) from exc
    if row is None:
        raise EventHypothesisBackupError(
            "v20 to v21 upgrade requires a prepared backup"
        )
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
        raise EventHypothesisBackupError("prepared backup identity differs")
    target = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        history = target.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 20
            or _schema_fingerprint(target) != EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
            or history != list(expected_history)
        ):
            raise EventHypothesisBackupError("prepared backup is not exact v20")
    finally:
        target.close()
    return EventHypothesisBackupReceipt(
        backup_path, digest_path, backup_digest, logical_digest
    )


_DIGEST_CHECK = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"

EVENT_HYPOTHESIS_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE event_hypotheses_v2(
        hypothesis_id TEXT PRIMARY KEY,
        canonical_bytes BLOB NOT NULL CHECK(length(canonical_bytes) BETWEEN 1 AND 4096),
        canonical_digest TEXT NOT NULL UNIQUE CHECK({_DIGEST_CHECK.format("canonical_digest")}),
        actor_identity_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format("actor_identity_digest")}),
        authority_event_id TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL
    ) STRICT""",
    f"""CREATE TABLE event_hypothesis_versions_v2(
        version_id TEXT PRIMARY KEY,
        hypothesis_id TEXT NOT NULL REFERENCES event_hypotheses_v2(hypothesis_id),
        ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
        previous_version_id TEXT REFERENCES event_hypothesis_versions_v2(version_id),
        previous_version_digest TEXT CHECK(previous_version_digest IS NULL OR {_DIGEST_CHECK.format("previous_version_digest")}),
        proposal_id TEXT NOT NULL, proposal_local_id TEXT NOT NULL,
        proposal_content_identity TEXT NOT NULL CHECK({_DIGEST_CHECK.format("proposal_content_identity")}),
        proposal_canonical_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format("proposal_canonical_digest")}),
        proposal_canonical_bytes BLOB NOT NULL CHECK(length(proposal_canonical_bytes) BETWEEN 1 AND 67108864),
        proposed_relationship TEXT NOT NULL CHECK(proposed_relationship IN ('SAME_STATE','DEVELOPMENT_OF','CORRECTION_REVERSAL_OF','RELATED_DISTINCT','NO_ADEQUATE_PRIOR_MATCH','UNCERTAIN')),
        proposed_target_hypothesis_id TEXT,
        target_version_id TEXT REFERENCES event_hypothesis_versions_v2(version_id),
        target_version_digest TEXT CHECK(target_version_digest IS NULL OR {_DIGEST_CHECK.format("target_version_digest")}),
        work_item_id TEXT NOT NULL, work_item_version_id TEXT NOT NULL,
        work_item_version_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format("work_item_version_digest")}),
        retrieval_context_id TEXT NOT NULL,
        retrieval_context_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format("retrieval_context_digest")}),
        actor_identity_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format("actor_identity_digest")}),
        authority_event_id TEXT NOT NULL UNIQUE,
        canonical_bytes BLOB NOT NULL CHECK(length(canonical_bytes) BETWEEN 1 AND 1048576),
        canonical_digest TEXT NOT NULL UNIQUE CHECK({_DIGEST_CHECK.format("canonical_digest")}),
        recorded_at TEXT NOT NULL,
        UNIQUE(hypothesis_id,ordinal), UNIQUE(previous_version_id), UNIQUE(proposal_id,proposal_local_id),
        FOREIGN KEY(work_item_version_id,work_item_id) REFERENCES triage_work_item_versions(version_id,work_item_id),
        CHECK((ordinal=1 AND previous_version_id IS NULL AND previous_version_digest IS NULL)
           OR (ordinal>1 AND previous_version_id IS NOT NULL AND previous_version_digest IS NOT NULL)),
        CHECK((proposed_target_hypothesis_id IS NULL AND target_version_id IS NULL AND target_version_digest IS NULL)
           OR (proposed_target_hypothesis_id IS NOT NULL AND target_version_id IS NOT NULL AND target_version_digest IS NOT NULL))
    ) STRICT""",
    f"""CREATE TABLE event_hypothesis_heads_v2(
        hypothesis_id TEXT PRIMARY KEY REFERENCES event_hypotheses_v2(hypothesis_id),
        version_id TEXT NOT NULL UNIQUE REFERENCES event_hypothesis_versions_v2(version_id),
        ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
        version_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format("version_digest")}), updated_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TRIGGER event_hypothesis_identity_coherence BEFORE INSERT ON event_hypotheses_v2
      WHEN NOT json_valid(CAST(NEW.canonical_bytes AS TEXT))
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.schema_version') IS NOT 'newsroom.increment6.event-hypothesis.v1'
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.hypothesis_id') IS NOT NEW.hypothesis_id
      BEGIN SELECT RAISE(ABORT,'Hypothesis scalars differ from canonical bytes'); END""",
    """CREATE TRIGGER event_hypothesis_version_coherence BEFORE INSERT ON event_hypothesis_versions_v2
      WHEN NOT json_valid(CAST(NEW.canonical_bytes AS TEXT))
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.schema_version') IS NOT 'newsroom.increment6.event-hypothesis-version.v1'
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.version_id') IS NOT NEW.version_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.hypothesis_id') IS NOT NEW.hypothesis_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.ordinal') IS NOT NEW.ordinal
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.previous_version_id') IS NOT NEW.previous_version_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.previous_version_digest') IS NOT NEW.previous_version_digest
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.proposal_id') IS NOT NEW.proposal_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.proposal_local_id') IS NOT NEW.proposal_local_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.proposal_content_identity') IS NOT NEW.proposal_content_identity
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.proposal_canonical_digest') IS NOT NEW.proposal_canonical_digest
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.proposed_relationship') IS NOT NEW.proposed_relationship
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.proposed_target_hypothesis_id') IS NOT NEW.proposed_target_hypothesis_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.target_version_id') IS NOT NEW.target_version_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.target_version_digest') IS NOT NEW.target_version_digest
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.work_item_id') IS NOT NEW.work_item_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.work_item_version_id') IS NOT NEW.work_item_version_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.work_item_version_digest') IS NOT NEW.work_item_version_digest
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.retrieval_context_id') IS NOT NEW.retrieval_context_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.retrieval_context_digest') IS NOT NEW.retrieval_context_digest
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.actor_identity_digest') IS NOT NEW.actor_identity_digest
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.authority_event_id') IS NOT NEW.authority_event_id
        OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.version.recorded_at') IS NOT NEW.recorded_at
        OR (NEW.ordinal>1 AND NOT EXISTS(SELECT 1 FROM event_hypothesis_versions_v2 p
            WHERE p.version_id=NEW.previous_version_id AND p.hypothesis_id=NEW.hypothesis_id
              AND p.ordinal=NEW.ordinal-1 AND p.canonical_digest=NEW.previous_version_digest))
      BEGIN SELECT RAISE(ABORT,'Hypothesis Version scalars or predecessor differ'); END""",
    """CREATE TRIGGER event_hypothesis_head_insert_guard BEFORE INSERT ON event_hypothesis_heads_v2
      WHEN NOT EXISTS(SELECT 1 FROM event_hypothesis_versions_v2 v WHERE v.version_id=NEW.version_id
        AND v.hypothesis_id=NEW.hypothesis_id AND v.ordinal=NEW.ordinal
        AND v.canonical_digest=NEW.version_digest AND v.recorded_at=NEW.updated_at)
      BEGIN SELECT RAISE(ABORT,'Hypothesis head differs from Version'); END""",
    """CREATE TRIGGER event_hypothesis_head_update_guard BEFORE UPDATE ON event_hypothesis_heads_v2
      WHEN NEW.hypothesis_id IS NOT OLD.hypothesis_id OR NEW.ordinal!=OLD.ordinal+1
        OR NOT EXISTS(SELECT 1 FROM event_hypothesis_versions_v2 v WHERE v.version_id=NEW.version_id
          AND v.hypothesis_id=NEW.hypothesis_id AND v.ordinal=NEW.ordinal
          AND v.previous_version_id=OLD.version_id AND v.previous_version_digest=OLD.version_digest
          AND v.canonical_digest=NEW.version_digest AND v.recorded_at=NEW.updated_at)
      BEGIN SELECT RAISE(ABORT,'illegal Hypothesis head CAS update'); END""",
    """CREATE TRIGGER immutable_event_hypothesis_update BEFORE UPDATE ON event_hypotheses_v2 BEGIN SELECT RAISE(ABORT,'immutable Hypothesis'); END""",
    """CREATE TRIGGER retained_event_hypothesis_delete BEFORE DELETE ON event_hypotheses_v2 BEGIN SELECT RAISE(ABORT,'retained Hypothesis'); END""",
    """CREATE TRIGGER immutable_event_hypothesis_version_update BEFORE UPDATE ON event_hypothesis_versions_v2 BEGIN SELECT RAISE(ABORT,'immutable Hypothesis Version'); END""",
    """CREATE TRIGGER retained_event_hypothesis_version_delete BEFORE DELETE ON event_hypothesis_versions_v2 BEGIN SELECT RAISE(ABORT,'retained Hypothesis Version'); END""",
    """CREATE TRIGGER retained_event_hypothesis_head_delete BEFORE DELETE ON event_hypothesis_heads_v2 BEGIN SELECT RAISE(ABORT,'retained Hypothesis head'); END""",
)
EVENT_HYPOTHESIS_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": EVENT_HYPOTHESIS_SCHEMA_VERSION,
        "name": EVENT_HYPOTHESIS_MIGRATION_NAME,
        "statements": list(EVENT_HYPOTHESIS_MIGRATION_STATEMENTS),
    }
)
EVENT_HYPOTHESIS_MIGRATION = EventHypothesisMigrationRecord(
    EVENT_HYPOTHESIS_SCHEMA_VERSION,
    EVENT_HYPOTHESIS_MIGRATION_NAME,
    EVENT_HYPOTHESIS_MIGRATION_CHECKSUM,
)
__all__ = [
    "EVENT_HYPOTHESIS_MIGRATION",
    "EVENT_HYPOTHESIS_MIGRATION_CHECKSUM",
    "EVENT_HYPOTHESIS_MIGRATION_NAME",
    "EVENT_HYPOTHESIS_MIGRATION_STATEMENTS",
    "EVENT_HYPOTHESIS_PREDECESSOR_FINGERPRINT",
    "EVENT_HYPOTHESIS_PREDECESSOR_MIGRATION_CHECKSUM",
    "EVENT_HYPOTHESIS_SCHEMA_VERSION",
    "EventHypothesisBackupError",
    "EventHypothesisBackupReceipt",
    "event_hypothesis_backup_paths",
    "prepare_event_hypothesis_backup",
    "require_event_hypothesis_backup",
]
