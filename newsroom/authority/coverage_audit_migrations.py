"""Checked v28 Coverage Audit authority migration and exact v27 backup gate."""

# fmt: off
# ruff: noqa: I001
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import bounded_search_migrations as predecessor
from .canonical import digest_canonical

COVERAGE_AUDIT_SCHEMA_VERSION = 28
COVERAGE_AUDIT_MIGRATION_NAME = "coverage_audit_authority_v28"
COVERAGE_AUDIT_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:ee5679aba6ceb3e95ba925febbbb7853369f93d055563ac85402d380377672b0"
)
COVERAGE_AUDIT_PREDECESSOR_FINGERPRINT = (
    "sha256:d7fc1557bd02588969efdd53c749a2f125ab5bab146395c4cf8f7d51b1e32719"
)
CoverageAuditBackupError = predecessor.BoundedSearchBackupError
CoverageAuditBackupReceipt = predecessor.BoundedSearchBackupReceipt
CoverageAuditMigrationRecord = predecessor.BoundedSearchMigrationRecord
_helpers = predecessor._helpers


def coverage_audit_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v28.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> CoverageAuditBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = _helpers._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise CoverageAuditBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 27
            or _helpers._schema_fingerprint(target) != COVERAGE_AUDIT_PREDECESSOR_FINGERPRINT
            or _helpers._logical_database_digest(target) != logical
        ):
            raise CoverageAuditBackupError("backup differs from source")
    finally:
        target.close()
    return CoverageAuditBackupReceipt(path, digest_path, digest, logical)


def prepare_coverage_audit_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> CoverageAuditBackupReceipt:
    fingerprint = _helpers._schema_fingerprint
    logical_digest = _helpers._logical_database_digest
    file_digest = _helpers._file_digest
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 27
        or fingerprint(connection) != COVERAGE_AUDIT_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise CoverageAuditBackupError("backup requires checked schema v27")
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
        raise CoverageAuditBackupError("backup boundary differs")
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
        "CREATE TEMP TABLE IF NOT EXISTS coverage_audit_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,"
        "logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM coverage_audit_backup_gate")
    connection.execute(
        "INSERT INTO coverage_audit_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_coverage_audit_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> CoverageAuditBackupReceipt:
    logical_digest = _helpers._logical_database_digest
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.coverage_audit_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise CoverageAuditBackupError("v27 to v28 requires prepared backup") from exc
    if row is None or logical_digest(connection) != row[2]:
        raise CoverageAuditBackupError("v27 to v28 requires prepared backup")
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
        raise CoverageAuditBackupError("prepared backup is not exact v27")
    return receipt


_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
COVERAGE_AUDIT_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE coverage_audits(
        audit_id TEXT PRIMARY KEY,
        comparator_bytes BLOB NOT NULL,
        comparator_digest TEXT NOT NULL UNIQUE CHECK({_D.format('comparator_digest')}),
        assessment_bytes BLOB NOT NULL,
        assessment_digest TEXT NOT NULL UNIQUE CHECK({_D.format('assessment_digest')}),
        audit_bytes BLOB NOT NULL,
        audit_digest TEXT NOT NULL UNIQUE CHECK({_D.format('audit_digest')}),
        assessment_state TEXT NOT NULL CHECK(assessment_state IN ('COMPLETE_BEST_EFFORT','PARTIAL_LIMITED','DEFERRED')),
        completed_at TEXT NOT NULL,
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        UNIQUE(audit_id,audit_digest),
        CHECK(length(comparator_bytes)>0 AND length(assessment_bytes)>0 AND length(audit_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE coverage_audit_observations(
        audit_id TEXT NOT NULL REFERENCES coverage_audits(audit_id),
        observation_ordinal INTEGER NOT NULL CHECK(observation_ordinal BETWEEN 1 AND 256),
        kind TEXT NOT NULL CHECK(kind IN ('SEARCH_RESULT_REFERENCE','EDITORIAL_RECORD','SOURCE_CHECK','EXPECTATION_NOT_OBSERVED')),
        reference_digest TEXT NOT NULL CHECK({_D.format('reference_digest')}),
        observed_at TEXT NOT NULL,
        PRIMARY KEY(audit_id,observation_ordinal),
        UNIQUE(audit_id,kind,reference_digest)
    ) STRICT""",
    f"""CREATE TABLE coverage_gaps(
        gap_id TEXT PRIMARY KEY,
        gap_bytes BLOB NOT NULL,
        gap_digest TEXT NOT NULL UNIQUE CHECK({_D.format('gap_digest')}),
        audit_id TEXT NOT NULL UNIQUE REFERENCES coverage_audits(audit_id),
        gap_state TEXT NOT NULL CHECK(gap_state IN ('PROPOSED','DEFERRED_ASSESSMENT')),
        proposed_at TEXT NOT NULL,
        UNIQUE(gap_id,gap_digest),
        CHECK(length(gap_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE coverage_gap_decisions(
        decision_id TEXT PRIMARY KEY,
        decision_bytes BLOB NOT NULL,
        decision_digest TEXT NOT NULL UNIQUE CHECK({_D.format('decision_digest')}),
        gap_id TEXT NOT NULL REFERENCES coverage_gaps(gap_id),
        decision_ordinal INTEGER NOT NULL CHECK(decision_ordinal BETWEEN 1 AND 1000000),
        previous_decision_digest TEXT CHECK(previous_decision_digest IS NULL OR {_D.format('previous_decision_digest')}),
        command_bytes BLOB NOT NULL,
        command_digest TEXT NOT NULL UNIQUE CHECK({_D.format('command_digest')}),
        command_id TEXT NOT NULL UNIQUE,
        request_id TEXT NOT NULL UNIQUE,
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL UNIQUE,
        disposition TEXT NOT NULL CHECK(disposition IN ('CONFIRMED_BEST_EFFORT_GAP','NOT_CONFIRMED','DEFERRED_INSUFFICIENT_BASIS')),
        decided_at TEXT NOT NULL,
        locality_decision_digest TEXT NOT NULL CHECK({_D.format('locality_decision_digest')}),
        UNIQUE(gap_id,decision_ordinal),
        UNIQUE(gap_id,decision_digest),
        FOREIGN KEY(gap_id,previous_decision_digest) REFERENCES coverage_gap_decisions(gap_id,decision_digest),
        CHECK((decision_ordinal=1 AND previous_decision_digest IS NULL) OR (decision_ordinal>1 AND previous_decision_digest IS NOT NULL)),
        CHECK(length(decision_bytes)>0 AND length(command_bytes)>0)
    ) STRICT""",
    """CREATE TRIGGER insert_once_coverage_audits BEFORE INSERT ON coverage_audits
       WHEN EXISTS(SELECT 1 FROM coverage_audits WHERE audit_id=NEW.audit_id OR comparator_digest=NEW.comparator_digest OR assessment_digest=NEW.assessment_digest OR audit_digest=NEW.audit_digest)
       BEGIN SELECT RAISE(ABORT,'Coverage Audit identity already retained'); END""",
    """CREATE TRIGGER insert_once_coverage_gaps BEFORE INSERT ON coverage_gaps
       WHEN EXISTS(SELECT 1 FROM coverage_gaps WHERE gap_id=NEW.gap_id OR gap_digest=NEW.gap_digest OR audit_id=NEW.audit_id)
       BEGIN SELECT RAISE(ABORT,'Coverage Gap identity already retained'); END""",
    """CREATE TRIGGER insert_once_coverage_gap_decisions BEFORE INSERT ON coverage_gap_decisions
       WHEN EXISTS(SELECT 1 FROM coverage_gap_decisions WHERE decision_id=NEW.decision_id OR decision_digest=NEW.decision_digest OR command_id=NEW.command_id OR command_digest=NEW.command_digest OR request_id=NEW.request_id OR idempotency_key=NEW.idempotency_key OR (gap_id=NEW.gap_id AND decision_ordinal=NEW.decision_ordinal))
       BEGIN SELECT RAISE(ABORT,'Coverage Gap Decision identity already retained'); END""",
    *tuple(
        f"CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable Coverage record'); END"
        for table in (
            "coverage_audits", "coverage_audit_observations", "coverage_gaps", "coverage_gap_decisions",
        )
    ),
    *tuple(
        f"CREATE TRIGGER retained_{table} BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'retained Coverage record'); END"
        for table in (
            "coverage_audits", "coverage_audit_observations", "coverage_gaps", "coverage_gap_decisions",
        )
    ),
)
COVERAGE_AUDIT_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": COVERAGE_AUDIT_SCHEMA_VERSION,
        "name": COVERAGE_AUDIT_MIGRATION_NAME,
        "statements": list(COVERAGE_AUDIT_MIGRATION_STATEMENTS),
    }
)
COVERAGE_AUDIT_MIGRATION = CoverageAuditMigrationRecord(
    COVERAGE_AUDIT_SCHEMA_VERSION,
    COVERAGE_AUDIT_MIGRATION_NAME,
    COVERAGE_AUDIT_MIGRATION_CHECKSUM,
)
__all__ = [
    name for name in globals()
    if name.startswith(("COVERAGE_", "Coverage", "coverage_", "prepare_", "require_"))
]
# fmt: on
