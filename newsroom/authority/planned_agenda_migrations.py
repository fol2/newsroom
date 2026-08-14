"""Checked v26 Planned Agenda authority migration and exact v25 backup gate."""

# fmt: off
# ruff: noqa: I001
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import evaluation_feedback_migrations as predecessor
from .canonical import digest_canonical

PLANNED_AGENDA_SCHEMA_VERSION = 26
PLANNED_AGENDA_MIGRATION_NAME = "planned_agenda_authority_v26"
PLANNED_AGENDA_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:59fe3bd40a2e22e874b4e5b02448501deffc23597e11b442e35b18e39ead0496"
)
PLANNED_AGENDA_PREDECESSOR_FINGERPRINT = (
    "sha256:353900bf5804f0b770489982541f3cff4fd30ea36fc75d19b9c63315d1b6ec06"
)
PlannedAgendaBackupError = predecessor.EvaluationFeedbackBackupError
PlannedAgendaBackupReceipt = predecessor.EvaluationFeedbackBackupReceipt
PlannedAgendaMigrationRecord = predecessor.EvaluationFeedbackMigrationRecord


def planned_agenda_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v26.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> PlannedAgendaBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = predecessor.predecessor.predecessor._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise PlannedAgendaBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 25
            or predecessor.predecessor.predecessor._schema_fingerprint(target)
            != PLANNED_AGENDA_PREDECESSOR_FINGERPRINT
            or predecessor.predecessor.predecessor._logical_database_digest(target)
            != logical
        ):
            raise PlannedAgendaBackupError("backup differs from source")
    finally:
        target.close()
    return PlannedAgendaBackupReceipt(path, digest_path, digest, logical)


def prepare_planned_agenda_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> PlannedAgendaBackupReceipt:
    fingerprint = predecessor.predecessor.predecessor._schema_fingerprint
    logical_digest = predecessor.predecessor.predecessor._logical_database_digest
    file_digest = predecessor.predecessor.predecessor._file_digest
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 25
        or fingerprint(connection) != PLANNED_AGENDA_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise PlannedAgendaBackupError("backup requires checked schema v25")
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
        raise PlannedAgendaBackupError("backup boundary differs")
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
        "CREATE TEMP TABLE IF NOT EXISTS planned_agenda_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,"
        "logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM planned_agenda_backup_gate")
    connection.execute(
        "INSERT INTO planned_agenda_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_planned_agenda_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> PlannedAgendaBackupReceipt:
    logical_digest = predecessor.predecessor.predecessor._logical_database_digest
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.planned_agenda_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise PlannedAgendaBackupError("v25 to v26 requires prepared backup") from exc
    if row is None or logical_digest(connection) != row[2]:
        raise PlannedAgendaBackupError("v25 to v26 requires prepared backup")
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
        raise PlannedAgendaBackupError("prepared backup is not exact v25")
    return receipt


_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
PLANNED_AGENDA_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE planned_agenda_items(
        agenda_item_id TEXT PRIMARY KEY,
        item_bytes BLOB NOT NULL,
        item_digest TEXT NOT NULL UNIQUE CHECK({_D.format('item_digest')}),
        agenda_kind TEXT NOT NULL,
        stable_subject_key TEXT NOT NULL UNIQUE,
        initial_version_id TEXT NOT NULL UNIQUE,
        request_id TEXT NOT NULL UNIQUE,
        command_digest TEXT NOT NULL CHECK({_D.format('command_digest')}),
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(actor_identity_digest,idempotency_key),
        CHECK(length(item_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE planned_agenda_versions(
        agenda_version_id TEXT PRIMARY KEY,
        agenda_item_id TEXT NOT NULL REFERENCES planned_agenda_items(agenda_item_id),
        version_ordinal INTEGER NOT NULL CHECK(version_ordinal BETWEEN 1 AND 1000000),
        predecessor_version_digest TEXT CHECK(predecessor_version_digest IS NULL OR {_D.format('predecessor_version_digest')}),
        version_bytes BLOB NOT NULL,
        version_digest TEXT NOT NULL UNIQUE CHECK({_D.format('version_digest')}),
        source_revision_id TEXT NOT NULL,
        schedule_status TEXT NOT NULL,
        request_id TEXT NOT NULL UNIQUE,
        command_digest TEXT NOT NULL CHECK({_D.format('command_digest')}),
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(agenda_item_id,version_ordinal),
        UNIQUE(agenda_version_id,agenda_item_id,version_digest),
        UNIQUE(actor_identity_digest,idempotency_key),
        CHECK(length(version_bytes)>0),
        CHECK((version_ordinal=1 AND predecessor_version_digest IS NULL)
           OR (version_ordinal>1 AND predecessor_version_digest IS NOT NULL))
    ) STRICT""",
    f"""CREATE TABLE planned_agenda_heads(
        agenda_item_id TEXT PRIMARY KEY REFERENCES planned_agenda_items(agenda_item_id),
        current_version_id TEXT NOT NULL,
        current_version_digest TEXT NOT NULL CHECK({_D.format('current_version_digest')}),
        current_version_ordinal INTEGER NOT NULL CHECK(current_version_ordinal BETWEEN 1 AND 1000000),
        current_resolution_digest TEXT CHECK(current_resolution_digest IS NULL OR {_D.format('current_resolution_digest')}),
        current_resolution_ordinal INTEGER NOT NULL CHECK(current_resolution_ordinal BETWEEN 0 AND 1000000),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_version_id,agenda_item_id,current_version_digest)
            REFERENCES planned_agenda_versions(agenda_version_id,agenda_item_id,version_digest),
        CHECK((current_resolution_ordinal=0 AND current_resolution_digest IS NULL)
           OR (current_resolution_ordinal>0 AND current_resolution_digest IS NOT NULL))
    ) STRICT""",
    f"""CREATE TABLE planned_agenda_resolutions(
        resolution_id TEXT PRIMARY KEY,
        agenda_item_id TEXT NOT NULL REFERENCES planned_agenda_items(agenda_item_id),
        agenda_version_id TEXT NOT NULL,
        agenda_version_digest TEXT NOT NULL CHECK({_D.format('agenda_version_digest')}),
        resolution_ordinal INTEGER NOT NULL CHECK(resolution_ordinal BETWEEN 1 AND 1000000),
        previous_resolution_digest TEXT CHECK(previous_resolution_digest IS NULL OR {_D.format('previous_resolution_digest')}),
        resolution_kind TEXT NOT NULL,
        resolution_bytes BLOB NOT NULL,
        resolution_digest TEXT NOT NULL UNIQUE CHECK({_D.format('resolution_digest')}),
        evidence_digest TEXT CHECK(evidence_digest IS NULL OR {_D.format('evidence_digest')}),
        confirmation_path_digest TEXT CHECK(confirmation_path_digest IS NULL OR {_D.format('confirmation_path_digest')}),
        baseline_evidence_digest TEXT CHECK(baseline_evidence_digest IS NULL OR {_D.format('baseline_evidence_digest')}),
        successor_version_digest TEXT CHECK(successor_version_digest IS NULL OR {_D.format('successor_version_digest')}),
        request_id TEXT NOT NULL UNIQUE,
        command_digest TEXT NOT NULL CHECK({_D.format('command_digest')}),
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        UNIQUE(agenda_item_id,resolution_ordinal),
        UNIQUE(actor_identity_digest,idempotency_key),
        FOREIGN KEY(agenda_version_id,agenda_item_id,agenda_version_digest)
            REFERENCES planned_agenda_versions(agenda_version_id,agenda_item_id,version_digest),
        CHECK(length(resolution_bytes)>0),
        CHECK((resolution_ordinal=1 AND previous_resolution_digest IS NULL)
           OR (resolution_ordinal>1 AND previous_resolution_digest IS NOT NULL))
    ) STRICT""",
    "CREATE TRIGGER immutable_planned_agenda_items BEFORE UPDATE ON planned_agenda_items BEGIN SELECT RAISE(ABORT,'immutable Planned Agenda Item'); END",
    "CREATE TRIGGER retained_planned_agenda_items BEFORE DELETE ON planned_agenda_items BEGIN SELECT RAISE(ABORT,'retained Planned Agenda Item'); END",
    "CREATE TRIGGER immutable_planned_agenda_versions BEFORE UPDATE ON planned_agenda_versions BEGIN SELECT RAISE(ABORT,'immutable Planned Agenda Version'); END",
    "CREATE TRIGGER retained_planned_agenda_versions BEFORE DELETE ON planned_agenda_versions BEGIN SELECT RAISE(ABORT,'retained Planned Agenda Version'); END",
    "CREATE TRIGGER immutable_planned_agenda_resolutions BEFORE UPDATE ON planned_agenda_resolutions BEGIN SELECT RAISE(ABORT,'immutable Agenda Resolution'); END",
    "CREATE TRIGGER retained_planned_agenda_resolutions BEFORE DELETE ON planned_agenda_resolutions BEGIN SELECT RAISE(ABORT,'retained Agenda Resolution'); END",
    "CREATE TRIGGER retained_planned_agenda_heads BEFORE DELETE ON planned_agenda_heads BEGIN SELECT RAISE(ABORT,'retained Planned Agenda head'); END",
    """CREATE TRIGGER planned_agenda_version_predecessor_guard
       BEFORE INSERT ON planned_agenda_versions WHEN NEW.version_ordinal>1 AND NOT EXISTS(
          SELECT 1 FROM planned_agenda_heads h
          WHERE h.agenda_item_id=NEW.agenda_item_id
            AND h.current_version_ordinal=NEW.version_ordinal-1
            AND h.current_version_digest=NEW.predecessor_version_digest)
       BEGIN SELECT RAISE(ABORT,'Planned Agenda Version predecessor differs'); END""",
    """CREATE TRIGGER planned_agenda_resolution_predecessor_guard
       BEFORE INSERT ON planned_agenda_resolutions WHEN NOT EXISTS(
          SELECT 1 FROM planned_agenda_heads h
          WHERE h.agenda_item_id=NEW.agenda_item_id
            AND h.current_resolution_ordinal=NEW.resolution_ordinal-1
            AND ((NEW.resolution_ordinal=1 AND h.current_resolution_digest IS NULL)
              OR h.current_resolution_digest=NEW.previous_resolution_digest))
       BEGIN SELECT RAISE(ABORT,'Agenda Resolution predecessor differs'); END""",
    """CREATE TRIGGER planned_agenda_head_progress_guard
       BEFORE UPDATE ON planned_agenda_heads WHEN
          NEW.current_version_ordinal NOT BETWEEN OLD.current_version_ordinal AND OLD.current_version_ordinal+1
          OR NEW.current_resolution_ordinal NOT BETWEEN OLD.current_resolution_ordinal AND OLD.current_resolution_ordinal+1
          OR (NEW.current_version_ordinal=OLD.current_version_ordinal
              AND (NEW.current_version_id!=OLD.current_version_id OR NEW.current_version_digest!=OLD.current_version_digest))
          OR (NEW.current_resolution_ordinal=OLD.current_resolution_ordinal
              AND NEW.current_resolution_digest IS NOT OLD.current_resolution_digest)
       BEGIN SELECT RAISE(ABORT,'Planned Agenda head progression differs'); END""",
)
PLANNED_AGENDA_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": PLANNED_AGENDA_SCHEMA_VERSION,
        "name": PLANNED_AGENDA_MIGRATION_NAME,
        "statements": list(PLANNED_AGENDA_MIGRATION_STATEMENTS),
    }
)
PLANNED_AGENDA_MIGRATION = PlannedAgendaMigrationRecord(
    PLANNED_AGENDA_SCHEMA_VERSION,
    PLANNED_AGENDA_MIGRATION_NAME,
    PLANNED_AGENDA_MIGRATION_CHECKSUM,
)
__all__ = [
    name for name in globals()
    if name.startswith(("PLANNED_", "Planned", "planned_", "prepare_", "require_"))
]
# fmt: on
