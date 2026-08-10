"""Checked v19 persistence for proposal findings and dispositions."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_json_bytes, digest_canonical

TRIAGE_DISPOSITION_SCHEMA_VERSION = 19
TRIAGE_DISPOSITION_MIGRATION_NAME = "triage_proposal_disposition_authority_v19"
TRIAGE_DISPOSITION_PREDECESSOR_FINGERPRINT = (
    "sha256:7a33005d06998ffd7c438e352ffce2c2c4da008deaa2b0d1171fe3f7599798ea"
)
TRIAGE_DISPOSITION_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:f815499c103fed95fbff0c25528331b2483b7c01687f8742394faa92a538bb88"
)


class TriageDispositionBackupError(sqlite3.DatabaseError):
    """The exact retained v18 backup boundary is absent or differs."""


@dataclass(frozen=True, slots=True)
class TriageDispositionBackupReceipt:
    backup_path: Path
    digest_path: Path
    backup_digest: str
    logical_digest: str


@dataclass(frozen=True, slots=True)
class TriageDispositionMigrationRecord:
    version: int
    name: str
    checksum: str


def triage_disposition_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v19.sqlite3")
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


def prepare_triage_disposition_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> TriageDispositionBackupReceipt:
    if connection.in_transaction:
        raise TriageDispositionBackupError("backup requires no active transaction")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 18:
        raise TriageDispositionBackupError("backup requires exact schema v18")
    if _schema_fingerprint(connection) != TRIAGE_DISPOSITION_PREDECESSOR_FINGERPRINT:
        raise TriageDispositionBackupError("backup requires checked v18 schema")
    if not isinstance(backup_path, Path) or not backup_path.is_absolute():
        raise TriageDispositionBackupError("backup path must be absolute")
    source_path = Path(next(r[2] for r in connection.execute("PRAGMA database_list") if r[1] == "main"))
    if not source_path or source_path.resolve() == backup_path.resolve():
        raise TriageDispositionBackupError("backup path must differ from source")
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical_digest = _logical_database_digest(connection)
    if backup_path.exists() != digest_path.exists():
        raise TriageDispositionBackupError("backup receipt is incomplete")
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
        raise TriageDispositionBackupError("retained backup digest differs")
    target = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (target.execute("PRAGMA user_version").fetchone()[0] != 18
            or _schema_fingerprint(target) != TRIAGE_DISPOSITION_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest):
            raise TriageDispositionBackupError("retained backup differs from source")
    finally:
        target.close()
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS triage_disposition_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM triage_disposition_backup_gate")
    connection.execute("INSERT INTO triage_disposition_backup_gate VALUES(?,?,?)", (str(backup_path), backup_digest, logical_digest))
    if connection.in_transaction:
        connection.commit()
    return TriageDispositionBackupReceipt(backup_path, digest_path, backup_digest, logical_digest)


def require_triage_disposition_backup(
    connection: sqlite3.Connection, *, expected_history: tuple[tuple[int, str, str], ...]
) -> TriageDispositionBackupReceipt:
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest FROM temp.triage_disposition_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise TriageDispositionBackupError("v18 to v19 upgrade requires a prepared backup") from exc
    if row is None:
        raise TriageDispositionBackupError("v18 to v19 upgrade requires a prepared backup")
    backup_path, backup_digest, logical_digest = Path(str(row[0])), str(row[1]), str(row[2])
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    if (not backup_path.is_file() or not digest_path.is_file()
        or _file_digest(backup_path) != backup_digest
        or digest_path.read_text(encoding="ascii") != backup_digest + "\n"
        or _logical_database_digest(connection) != logical_digest):
        raise TriageDispositionBackupError("prepared backup identity differs")
    target = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True, isolation_level=None)
    try:
        history = target.execute("SELECT version,name,checksum FROM authority_migrations ORDER BY version").fetchall()
        if (target.execute("PRAGMA user_version").fetchone()[0] != 18
            or _schema_fingerprint(target) != TRIAGE_DISPOSITION_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(target) != logical_digest
            or history != list(expected_history)):
            raise TriageDispositionBackupError("prepared backup is not exact v18")
    finally:
        target.close()
    return TriageDispositionBackupReceipt(backup_path, digest_path, backup_digest, logical_digest)


_DIGEST_CHECK = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"

TRIAGE_DISPOSITION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE triage_proposal_validation_findings(
        finding_id TEXT PRIMARY KEY CHECK({_DIGEST_CHECK.format('finding_id')}),
        work_item_id TEXT NOT NULL,
        work_item_version_id TEXT NOT NULL REFERENCES triage_work_item_versions(version_id),
        work_item_version_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('work_item_version_digest')}),
        proposal_id TEXT NOT NULL,
        proposal_content_identity TEXT NOT NULL CHECK({_DIGEST_CHECK.format('proposal_content_identity')}),
        proposal_canonical_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('proposal_canonical_digest')}),
        decision_lead_id TEXT NOT NULL,
        validator_input_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('validator_input_digest')}),
        finding_set_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('finding_set_digest')}),
        severity TEXT NOT NULL CHECK(severity IN ('INFO','ERROR')),
        canonical_bytes BLOB NOT NULL CHECK(length(canonical_bytes) BETWEEN 1 AND 67108864),
        canonical_digest TEXT NOT NULL UNIQUE CHECK({_DIGEST_CHECK.format('canonical_digest')}),
        recorded_at TEXT NOT NULL,
        UNIQUE(work_item_version_id,decision_lead_id),
        UNIQUE(finding_id,work_item_version_id,proposal_id,decision_lead_id),
        FOREIGN KEY(work_item_version_id,work_item_id) REFERENCES triage_work_item_versions(version_id,work_item_id)
    ) STRICT""",
    f"""CREATE TABLE triage_proposal_dispositions(
        disposition_id TEXT PRIMARY KEY CHECK({_DIGEST_CHECK.format('disposition_id')}),
        work_item_id TEXT NOT NULL,
        work_item_version_id TEXT NOT NULL REFERENCES triage_work_item_versions(version_id),
        work_item_version_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('work_item_version_digest')}),
        proposal_id TEXT NOT NULL,
        proposal_content_identity TEXT NOT NULL CHECK({_DIGEST_CHECK.format('proposal_content_identity')}),
        proposal_canonical_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('proposal_canonical_digest')}),
        decision_lead_id TEXT NOT NULL,
        lead_head_id TEXT NOT NULL,
        lead_head_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('lead_head_digest')}),
        validator_input_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('validator_input_digest')}),
        finding_set_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('finding_set_digest')}),
        finding_id TEXT NOT NULL,
        selection_digest TEXT NOT NULL CHECK({_DIGEST_CHECK.format('selection_digest')}),
        canonical_bytes BLOB NOT NULL CHECK(length(canonical_bytes) BETWEEN 1 AND 67108864),
        canonical_digest TEXT NOT NULL UNIQUE CHECK({_DIGEST_CHECK.format('canonical_digest')}),
        recorded_at TEXT NOT NULL,
        UNIQUE(work_item_version_id,decision_lead_id),
        FOREIGN KEY(finding_id,work_item_version_id,proposal_id,decision_lead_id)
            REFERENCES triage_proposal_validation_findings(finding_id,work_item_version_id,proposal_id,decision_lead_id),
        FOREIGN KEY(work_item_version_id,work_item_id) REFERENCES triage_work_item_versions(version_id,work_item_id)
    ) STRICT""",
    """CREATE TRIGGER triage_proposal_finding_coherence_guard BEFORE INSERT ON triage_proposal_validation_findings
        WHEN NOT json_valid(CAST(NEW.canonical_bytes AS TEXT))
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.schema_version') IS NOT 'newsroom.increment6.triage-proposal-finding.v1'
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.finding.finding_id') IS NOT NEW.finding_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.finding.proposal_id') IS NOT NEW.proposal_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.finding.proposal_content_identity') IS NOT NEW.proposal_content_identity
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.finding.proposal_canonical_digest') IS NOT NEW.proposal_canonical_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.finding.evidence_reference_id') IS NOT NEW.decision_lead_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.finding.validator_input_binding.input_digest') IS NOT NEW.validator_input_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.finding.severity') IS NOT NEW.severity
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.finding.authority') IS NOT 'NONE'
        BEGIN SELECT RAISE(ABORT,'Proposal finding scalars differ from canonical bytes'); END""",
    """CREATE TRIGGER triage_proposal_disposition_coherence_guard BEFORE INSERT ON triage_proposal_dispositions
        WHEN NOT json_valid(CAST(NEW.canonical_bytes AS TEXT))
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.schema_version') IS NOT 'newsroom.increment6.triage-proposal-disposition.v1'
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.disposition_id') IS NOT NEW.disposition_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.work_item_id') IS NOT NEW.work_item_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.work_item_version_id') IS NOT NEW.work_item_version_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.work_item_version_digest') IS NOT NEW.work_item_version_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.proposal_id') IS NOT NEW.proposal_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.proposal_content_identity') IS NOT NEW.proposal_content_identity
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.proposal_canonical_digest') IS NOT NEW.proposal_canonical_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.lead_head_binding.decision_lead_id') IS NOT NEW.decision_lead_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.lead_head_binding.current_disposition_head_id') IS NOT NEW.lead_head_id
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.lead_head_binding.current_disposition_head_digest') IS NOT NEW.lead_head_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.validator_input_binding.input_digest') IS NOT NEW.validator_input_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.finding_set_digest') IS NOT NEW.finding_set_digest
          OR json_extract(CAST(NEW.canonical_bytes AS TEXT),'$.disposition.authority') IS NOT 'NONE'
        BEGIN SELECT RAISE(ABORT,'Proposal disposition scalars differ from canonical bytes'); END""",
    """CREATE TRIGGER immutable_triage_proposal_findings_update BEFORE UPDATE ON triage_proposal_validation_findings BEGIN SELECT RAISE(ABORT,'immutable Proposal finding'); END""",
    """CREATE TRIGGER retained_triage_proposal_findings_delete BEFORE DELETE ON triage_proposal_validation_findings BEGIN SELECT RAISE(ABORT,'retained Proposal finding'); END""",
    """CREATE TRIGGER immutable_triage_proposal_dispositions_update BEFORE UPDATE ON triage_proposal_dispositions BEGIN SELECT RAISE(ABORT,'immutable Proposal disposition'); END""",
    """CREATE TRIGGER retained_triage_proposal_dispositions_delete BEFORE DELETE ON triage_proposal_dispositions BEGIN SELECT RAISE(ABORT,'retained Proposal disposition'); END""",
)

TRIAGE_DISPOSITION_MIGRATION_CHECKSUM = digest_canonical({
    "version": TRIAGE_DISPOSITION_SCHEMA_VERSION,
    "name": TRIAGE_DISPOSITION_MIGRATION_NAME,
    "statements": list(TRIAGE_DISPOSITION_MIGRATION_STATEMENTS),
})
TRIAGE_DISPOSITION_MIGRATION = TriageDispositionMigrationRecord(
    TRIAGE_DISPOSITION_SCHEMA_VERSION,
    TRIAGE_DISPOSITION_MIGRATION_NAME,
    TRIAGE_DISPOSITION_MIGRATION_CHECKSUM,
)

__all__ = [
    "TRIAGE_DISPOSITION_MIGRATION", "TRIAGE_DISPOSITION_MIGRATION_CHECKSUM",
    "TRIAGE_DISPOSITION_MIGRATION_NAME", "TRIAGE_DISPOSITION_MIGRATION_STATEMENTS",
    "TRIAGE_DISPOSITION_PREDECESSOR_FINGERPRINT",
    "TRIAGE_DISPOSITION_PREDECESSOR_MIGRATION_CHECKSUM",
    "TRIAGE_DISPOSITION_SCHEMA_VERSION", "TriageDispositionBackupError",
    "TriageDispositionBackupReceipt", "prepare_triage_disposition_backup",
    "require_triage_disposition_backup", "triage_disposition_backup_paths",
]
