"""Checked v22 persistence for Event Hypothesis relationship authority."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_json_bytes, digest_canonical

EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION = 22
EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_NAME = (
    "event_hypothesis_relationship_authority_v22"
)
EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:42009475669a475af8e3e24bbcd02e6fcd9fbb71a800e18d83624e34e79e5e21"
)
EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_FINGERPRINT = (
    "sha256:d314d06118a25f8a32a0f9d8acb1af5383abd6b30be682cb5f65943ae15c213f"
)


class EventHypothesisRelationshipBackupError(sqlite3.DatabaseError):
    """The exact retained v21 backup boundary is absent or differs."""


@dataclass(frozen=True, slots=True)
class EventHypothesisRelationshipBackupReceipt:
    backup_path: Path
    digest_path: Path
    backup_digest: str
    logical_digest: str


@dataclass(frozen=True, slots=True)
class EventHypothesisRelationshipMigrationRecord:
    version: int
    name: str
    checksum: str


def event_hypothesis_relationship_backup_paths(
    database: str | Path,
) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v22.sqlite3")
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


def prepare_event_hypothesis_relationship_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> EventHypothesisRelationshipBackupReceipt:
    if connection.in_transaction:
        raise EventHypothesisRelationshipBackupError(
            "backup requires no active transaction"
        )
    if connection.execute("PRAGMA user_version").fetchone()[0] != 21:
        raise EventHypothesisRelationshipBackupError("backup requires exact schema v21")
    if (
        _schema_fingerprint(connection)
        != EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_FINGERPRINT
    ):
        raise EventHypothesisRelationshipBackupError(
            "backup requires checked v21 schema"
        )
    if not isinstance(backup_path, Path) or not backup_path.is_absolute():
        raise EventHypothesisRelationshipBackupError("backup path must be absolute")
    source_path = Path(
        next(r[2] for r in connection.execute("PRAGMA database_list") if r[1] == "main")
    )
    if not source_path or source_path.resolve() == backup_path.resolve():
        raise EventHypothesisRelationshipBackupError(
            "backup path must differ from source"
        )
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical_digest = _logical_database_digest(connection)
    if backup_path.exists() != digest_path.exists():
        raise EventHypothesisRelationshipBackupError("backup receipt is incomplete")
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
        raise EventHypothesisRelationshipBackupError("retained backup digest differs")
    target = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 21
            or _schema_fingerprint(target)
            != EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
        ):
            raise EventHypothesisRelationshipBackupError(
                "retained backup differs from source"
            )
    finally:
        target.close()
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS event_hypothesis_relationship_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM event_hypothesis_relationship_backup_gate")
    connection.execute(
        "INSERT INTO event_hypothesis_relationship_backup_gate VALUES(?,?,?)",
        (str(backup_path), backup_digest, logical_digest),
    )
    if connection.in_transaction:
        connection.commit()
    return EventHypothesisRelationshipBackupReceipt(
        backup_path, digest_path, backup_digest, logical_digest
    )


def require_event_hypothesis_relationship_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> EventHypothesisRelationshipBackupReceipt:
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.event_hypothesis_relationship_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise EventHypothesisRelationshipBackupError(
            "v21 to v22 upgrade requires a prepared backup"
        ) from exc
    if row is None:
        raise EventHypothesisRelationshipBackupError(
            "v21 to v22 upgrade requires a prepared backup"
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
        raise EventHypothesisRelationshipBackupError("prepared backup identity differs")
    target = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        history = target.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 21
            or _schema_fingerprint(target)
            != EVENT_HYPOTHESIS_RELATIONSHIP_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
            or history != list(expected_history)
        ):
            raise EventHypothesisRelationshipBackupError(
                "prepared backup is not exact v21"
            )
    finally:
        target.close()
    return EventHypothesisRelationshipBackupReceipt(
        backup_path, digest_path, backup_digest, logical_digest
    )


_DIGEST = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"

EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE event_hypothesis_relationship_decisions(
        decision_id TEXT PRIMARY KEY CHECK({_DIGEST.format("decision_id")}),
        authority_aggregate_id TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        subject_hypothesis_id TEXT NOT NULL,
        subject_version_id TEXT NOT NULL UNIQUE REFERENCES event_hypothesis_versions_v2(version_id),
        subject_version_digest TEXT NOT NULL CHECK({_DIGEST.format("subject_version_digest")}),
        comparator_manifest_bytes BLOB NOT NULL CHECK(length(comparator_manifest_bytes) BETWEEN 1 AND 16777216),
        comparator_manifest_digest TEXT NOT NULL CHECK({_DIGEST.format("comparator_manifest_digest")}),
        selected_comparator_hypothesis_id TEXT,
        selected_comparator_version_id TEXT REFERENCES event_hypothesis_versions_v2(version_id),
        selected_comparator_version_digest TEXT CHECK(selected_comparator_version_digest IS NULL OR {_DIGEST.format("selected_comparator_version_digest")}),
        decision TEXT NOT NULL CHECK(decision IN ('REL_SAME_STATE','REL_DEVELOPMENT_OF','REL_CORRECTION_REVERSAL_OF','REL_RELATED_DISTINCT','REL_NO_ADEQUATE_PRIOR_MATCH','REL_UNCERTAIN')),
        assessment_bytes BLOB NOT NULL CHECK(length(assessment_bytes) BETWEEN 1 AND 16777216),
        assessment_digest TEXT NOT NULL UNIQUE CHECK({_DIGEST.format("assessment_digest")}),
        evidence_bytes BLOB NOT NULL CHECK(length(evidence_bytes) BETWEEN 2 AND 16777216),
        evidence_digest TEXT NOT NULL CHECK({_DIGEST.format("evidence_digest")}),
        actor_identity_digest TEXT NOT NULL CHECK({_DIGEST.format("actor_identity_digest")}),
        recorded_at TEXT NOT NULL,
        CHECK(decision_id=assessment_digest),
        CHECK((decision='REL_NO_ADEQUATE_PRIOR_MATCH' AND selected_comparator_hypothesis_id IS NULL AND selected_comparator_version_id IS NULL AND selected_comparator_version_digest IS NULL)
          OR (decision!='REL_NO_ADEQUATE_PRIOR_MATCH' AND selected_comparator_hypothesis_id IS NOT NULL AND selected_comparator_version_id IS NOT NULL AND selected_comparator_version_digest IS NOT NULL))
    ) STRICT""",
    """CREATE TRIGGER event_hypothesis_relationship_coherence BEFORE INSERT ON event_hypothesis_relationship_decisions
      WHEN NOT json_valid(CAST(NEW.assessment_bytes AS TEXT))
        OR json_extract(CAST(NEW.assessment_bytes AS TEXT),'$.schema_version') IS NOT 'newsroom.increment6.hypothesis-relationship-decision.v1'
        OR json_extract(CAST(NEW.assessment_bytes AS TEXT),'$.subject.hypothesis_id') IS NOT NEW.subject_hypothesis_id
        OR json_extract(CAST(NEW.assessment_bytes AS TEXT),'$.subject.version_id') IS NOT NEW.subject_version_id
        OR json_extract(CAST(NEW.assessment_bytes AS TEXT),'$.subject.version_digest') IS NOT NEW.subject_version_digest
        OR json_extract(CAST(NEW.assessment_bytes AS TEXT),'$.decision') IS NOT NEW.decision
        OR json_extract(CAST(NEW.assessment_bytes AS TEXT),'$.comparator.version_id') IS NOT NEW.selected_comparator_version_id
      BEGIN SELECT RAISE(ABORT,'relationship decision scalars differ'); END""",
    """CREATE TRIGGER immutable_event_hypothesis_relationship_update BEFORE UPDATE ON event_hypothesis_relationship_decisions BEGIN SELECT RAISE(ABORT,'immutable relationship decision'); END""",
    """CREATE TRIGGER retained_event_hypothesis_relationship_delete BEFORE DELETE ON event_hypothesis_relationship_decisions BEGIN SELECT RAISE(ABORT,'retained relationship decision'); END""",
)
EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION,
        "name": EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_NAME,
        "statements": list(EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_STATEMENTS),
    }
)
EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION = EventHypothesisRelationshipMigrationRecord(
    EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION,
    EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_NAME,
    EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_CHECKSUM,
)


__all__ = [
    name
    for name in globals()
    if name.startswith(("EVENT_", "Event", "event_", "prepare_", "require_"))
]
