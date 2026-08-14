"""Checked v31 Increment 8 operational-authority migration and v30 backup gate."""

# fmt: off
# ruff: noqa: I001
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import increment8_evaluation_migrations as predecessor
from .canonical import digest_canonical

INCREMENT8_OPERATIONAL_SCHEMA_VERSION = 31
INCREMENT8_OPERATIONAL_MIGRATION_NAME = "increment8_operational_authority_v31"
INCREMENT8_OPERATIONAL_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:764306cbc8fced0b50657c87c2c8735aa07b6ed6b02b1d7ceec84afd9db7dc15"
)
INCREMENT8_OPERATIONAL_PREDECESSOR_FINGERPRINT = (
    "sha256:cf9a5ee83f6d3396d8d9fff4aa234ba252037dd4056e88f85afcb27c6c45bfd9"
)
Increment8OperationalBackupError = predecessor.Increment8EvaluationBackupError
Increment8OperationalBackupReceipt = predecessor.Increment8EvaluationBackupReceipt
Increment8OperationalMigrationRecord = predecessor.Increment8EvaluationMigrationRecord
_helpers = predecessor._helpers


def increment8_operational_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v31.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> Increment8OperationalBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = _helpers._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise Increment8OperationalBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 30
            or _helpers._schema_fingerprint(target) != INCREMENT8_OPERATIONAL_PREDECESSOR_FINGERPRINT
            or _helpers._logical_database_digest(target) != logical
        ):
            raise Increment8OperationalBackupError("backup differs from source")
    finally:
        target.close()
    return Increment8OperationalBackupReceipt(path, digest_path, digest, logical)


def prepare_increment8_operational_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> Increment8OperationalBackupReceipt:
    fingerprint = _helpers._schema_fingerprint
    logical_digest = _helpers._logical_database_digest
    file_digest = _helpers._file_digest
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 30
        or fingerprint(connection) != INCREMENT8_OPERATIONAL_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise Increment8OperationalBackupError("backup requires checked schema v30")
    source = Path(next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"))
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical = logical_digest(connection)
    if not source or source.resolve() == backup_path.resolve() or backup_path.exists() != digest_path.exists():
        raise Increment8OperationalBackupError("backup boundary differs")
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
        "CREATE TEMP TABLE IF NOT EXISTS increment8_operational_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM increment8_operational_backup_gate")
    connection.execute(
        "INSERT INTO increment8_operational_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_increment8_operational_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> Increment8OperationalBackupReceipt:
    logical_digest = _helpers._logical_database_digest
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest FROM temp.increment8_operational_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise Increment8OperationalBackupError("v30 to v31 requires prepared backup") from exc
    if row is None or logical_digest(connection) != row[2]:
        raise Increment8OperationalBackupError("v30 to v31 requires prepared backup")
    receipt = _checked_backup(Path(row[0]), str(row[2]))
    target = sqlite3.connect(f"file:{receipt.backup_path}?mode=ro", uri=True, isolation_level=None)
    try:
        history = target.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
    finally:
        target.close()
    if receipt.backup_digest != row[1] or history != list(expected_history):
        raise Increment8OperationalBackupError("prepared backup is not exact v30")
    return receipt


_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
INCREMENT8_OPERATIONAL_TABLES = (
    "operational_profiles",
    "due_work",
    "work_leases",
    "retry_findings",
    "quarantine_records",
    "handoff_registration_anchors",
)
INCREMENT8_OPERATIONAL_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE operational_profiles(
        profile_id TEXT PRIMARY KEY,
        profile_bytes BLOB NOT NULL,
        profile_digest TEXT NOT NULL UNIQUE CHECK({_D.format('profile_digest')}),
        readiness_digest TEXT NOT NULL CHECK({_D.format('readiness_digest')}),
        approved_by_digest TEXT NOT NULL CHECK({_D.format('approved_by_digest')}),
        approved_at TEXT NOT NULL,
        live_execution_authorised INTEGER NOT NULL CHECK(live_execution_authorised=0),
        CHECK(length(profile_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE due_work(
        work_id TEXT NOT NULL,
        state_version INTEGER NOT NULL CHECK(state_version>0),
        work_bytes BLOB NOT NULL,
        work_digest TEXT NOT NULL UNIQUE CHECK({_D.format('work_digest')}),
        profile_id TEXT NOT NULL REFERENCES operational_profiles(profile_id),
        logical_due_key TEXT NOT NULL,
        scope_kind TEXT NOT NULL,
        urgency TEXT NOT NULL CHECK(urgency IN('URGENT','TIME_SENSITIVE','PLANNED','ROUTINE')),
        state TEXT NOT NULL CHECK(state IN('QUEUED','LEASED','RETRY_PENDING','COMPLETED','EXPLICITLY_CLOSED','QUARANTINED')),
        attempt_count INTEGER NOT NULL CHECK(attempt_count>=0),
        due_at TEXT NOT NULL,
        deadline_at TEXT NOT NULL,
        previous_digest TEXT CHECK(previous_digest IS NULL OR ({_D.format('previous_digest')})),
        authority_version_digest TEXT NOT NULL CHECK({_D.format('authority_version_digest')}),
        PRIMARY KEY(work_id,state_version),
        UNIQUE(logical_due_key,state_version),
        CHECK(length(work_bytes)>0),
        CHECK((state_version=1 AND previous_digest IS NULL) OR (state_version>1 AND previous_digest IS NOT NULL))
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE work_leases(
        lease_id TEXT NOT NULL,
        lease_version INTEGER NOT NULL CHECK(lease_version>0),
        lease_bytes BLOB NOT NULL,
        lease_digest TEXT NOT NULL UNIQUE CHECK({_D.format('lease_digest')}),
        work_id TEXT NOT NULL,
        owner_digest TEXT NOT NULL CHECK({_D.format('owner_digest')}),
        progress_digest TEXT NOT NULL CHECK({_D.format('progress_digest')}),
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        maximum_expires_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN('ACTIVE','RELEASED','ORPHANED')),
        previous_digest TEXT CHECK(previous_digest IS NULL OR ({_D.format('previous_digest')})),
        PRIMARY KEY(lease_id,lease_version),
        CHECK(length(lease_bytes)>0),
        CHECK((lease_version=1 AND previous_digest IS NULL) OR (lease_version>1 AND previous_digest IS NOT NULL))
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE retry_findings(
        finding_id TEXT PRIMARY KEY,
        finding_bytes BLOB NOT NULL,
        finding_digest TEXT NOT NULL UNIQUE CHECK({_D.format('finding_digest')}),
        work_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL CHECK(attempt_number>0),
        classification TEXT NOT NULL CHECK(classification IN('RETRYABLE','NON_RETRYABLE','OPERATOR_REQUIRED','AMBIGUOUS_EFFECT')),
        dependency_scope TEXT NOT NULL,
        next_due_at TEXT,
        health_clock_refreshed INTEGER NOT NULL CHECK(health_clock_refreshed=0),
        CHECK(length(finding_bytes)>0),
        UNIQUE(work_id,attempt_number)
    ) STRICT""",
    f"""CREATE TABLE quarantine_records(
        quarantine_id TEXT NOT NULL,
        quarantine_version INTEGER NOT NULL CHECK(quarantine_version>0),
        quarantine_bytes BLOB NOT NULL,
        quarantine_digest TEXT NOT NULL UNIQUE CHECK({_D.format('quarantine_digest')}),
        scope_id TEXT NOT NULL,
        reason_class TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN('ACTIVE','RELEASE_APPROVED','RELEASED')),
        authorised_by_digest TEXT CHECK(authorised_by_digest IS NULL OR ({_D.format('authorised_by_digest')})),
        evidence_digest TEXT NOT NULL CHECK({_D.format('evidence_digest')}),
        previous_digest TEXT CHECK(previous_digest IS NULL OR ({_D.format('previous_digest')})),
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(quarantine_id,quarantine_version),
        CHECK(length(quarantine_bytes)>0),
        CHECK((quarantine_version=1 AND previous_digest IS NULL) OR (quarantine_version>1 AND previous_digest IS NOT NULL)),
        CHECK(status='ACTIVE' OR authorised_by_digest IS NOT NULL)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE handoff_registration_anchors(
        handoff_id TEXT PRIMARY KEY REFERENCES evaluation_handoffs(handoff_id),
        anchor_id TEXT NOT NULL UNIQUE,
        anchor_bytes BLOB NOT NULL,
        anchor_digest TEXT NOT NULL UNIQUE CHECK({_D.format('anchor_digest')}),
        handoff_identity_digest TEXT NOT NULL CHECK({_D.format('handoff_identity_digest')}),
        max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 100),
        anchor_kind TEXT NOT NULL CHECK(anchor_kind IN('ORIGINAL_REGISTRATION','OBSERVED_AT_HARDENING')),
        recorded_at TEXT NOT NULL,
        operational_eligible INTEGER NOT NULL CHECK(operational_eligible IN(0,1)),
        CHECK((anchor_kind='ORIGINAL_REGISTRATION' AND operational_eligible=1) OR
              (anchor_kind='OBSERVED_AT_HARDENING' AND operational_eligible=0)),
        CHECK(length(anchor_bytes)>0)
    ) STRICT""",
    *tuple(
        f"CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable Increment 8 operational record'); END"
        for table in INCREMENT8_OPERATIONAL_TABLES
    ),
    *tuple(
        f"CREATE TRIGGER retained_{table} BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'retained Increment 8 operational record'); END"
        for table in INCREMENT8_OPERATIONAL_TABLES
    ),
)
INCREMENT8_OPERATIONAL_MIGRATION_CHECKSUM = digest_canonical({
    "version": INCREMENT8_OPERATIONAL_SCHEMA_VERSION,
    "name": INCREMENT8_OPERATIONAL_MIGRATION_NAME,
    "statements": list(INCREMENT8_OPERATIONAL_MIGRATION_STATEMENTS),
})
INCREMENT8_OPERATIONAL_MIGRATION = Increment8OperationalMigrationRecord(
    INCREMENT8_OPERATIONAL_SCHEMA_VERSION,
    INCREMENT8_OPERATIONAL_MIGRATION_NAME,
    INCREMENT8_OPERATIONAL_MIGRATION_CHECKSUM,
)
__all__ = [name for name in globals() if name.startswith(("INCREMENT8_OPERATIONAL_", "Increment8Operational", "increment8_operational_", "prepare_", "require_"))]
# fmt: on
