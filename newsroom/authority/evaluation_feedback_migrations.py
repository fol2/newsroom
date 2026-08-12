"""Checked v25 Evaluation Feedback authority migration and v24 backup gate."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from . import story_candidate_migrations as predecessor
from .canonical import digest_canonical


EVALUATION_FEEDBACK_SCHEMA_VERSION = 25
EVALUATION_FEEDBACK_MIGRATION_NAME = "evaluation_feedback_authority_v25"
EVALUATION_FEEDBACK_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:1eea25005483de124e0add0100f4805ed5a537852fc70916f17a209c633e0ca0"
)
EVALUATION_FEEDBACK_PREDECESSOR_FINGERPRINT = (
    "sha256:abf8430bfd676a9b0e574847cde9375d90aa1e32680725a08b30c0657d567a7c"
)

EvaluationFeedbackBackupError = predecessor.StoryCandidateBackupError
EvaluationFeedbackBackupReceipt = predecessor.StoryCandidateBackupReceipt
EvaluationFeedbackMigrationRecord = predecessor.StoryCandidateMigrationRecord


def evaluation_feedback_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v25.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> EvaluationFeedbackBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = predecessor.predecessor._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise EvaluationFeedbackBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 24
            or predecessor.predecessor._schema_fingerprint(target)
            != EVALUATION_FEEDBACK_PREDECESSOR_FINGERPRINT
            or predecessor.predecessor._logical_database_digest(target) != logical
        ):
            raise EvaluationFeedbackBackupError("backup differs from source")
    finally:
        target.close()
    return EvaluationFeedbackBackupReceipt(path, digest_path, digest, logical)


def prepare_evaluation_feedback_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> EvaluationFeedbackBackupReceipt:
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 24
        or predecessor.predecessor._schema_fingerprint(connection)
        != EVALUATION_FEEDBACK_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise EvaluationFeedbackBackupError("backup requires checked schema v24")
    source = Path(
        next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main")
    )
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical = predecessor.predecessor._logical_database_digest(connection)
    if (
        not source
        or source.resolve() == backup_path.resolve()
        or backup_path.exists() != digest_path.exists()
    ):
        raise EvaluationFeedbackBackupError("backup boundary differs")
    if not backup_path.exists():
        backup_path.open("xb").close()
        target = sqlite3.connect(backup_path, isolation_level=None)
        try:
            connection.backup(target)
        finally:
            target.close()
        digest_path.write_text(
            predecessor.predecessor._file_digest(backup_path) + "\n", encoding="ascii"
        )
    receipt = _checked_backup(backup_path, logical)
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS evaluation_feedback_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,"
        "logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM evaluation_feedback_backup_gate")
    connection.execute(
        "INSERT INTO evaluation_feedback_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_evaluation_feedback_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> EvaluationFeedbackBackupReceipt:
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.evaluation_feedback_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise EvaluationFeedbackBackupError(
            "v24 to v25 requires prepared backup"
        ) from exc
    if row is None or predecessor.predecessor._logical_database_digest(connection) != row[2]:
        raise EvaluationFeedbackBackupError("v24 to v25 requires prepared backup")
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
        raise EvaluationFeedbackBackupError("prepared backup is not exact v24")
    return receipt


_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"

EVALUATION_FEEDBACK_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE evaluation_feedback(
        feedback_id TEXT PRIMARY KEY,
        feedback_bytes BLOB NOT NULL,
        feedback_digest TEXT NOT NULL UNIQUE CHECK({_D.format('feedback_digest')}),
        source_feedback_id TEXT NOT NULL,
        handoff_id TEXT NOT NULL,
        acknowledgement_id TEXT NOT NULL UNIQUE,
        candidate_id TEXT NOT NULL,
        candidate_version_id TEXT NOT NULL,
        candidate_version_digest TEXT NOT NULL CHECK({_D.format('candidate_version_digest')}),
        request_id TEXT NOT NULL UNIQUE,
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL,
        authority_aggregate_id TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        acceptance_snapshot_bytes BLOB NOT NULL,
        acceptance_snapshot_digest TEXT NOT NULL UNIQUE CHECK({_D.format('acceptance_snapshot_digest')}),
        recorded_at TEXT NOT NULL,
        UNIQUE(actor_identity_digest,idempotency_key),
        UNIQUE(handoff_id),
        UNIQUE(source_feedback_id),
        CHECK(length(feedback_bytes)>0 AND length(acceptance_snapshot_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE evaluation_reconciliation_obligations(
        obligation_id TEXT PRIMARY KEY,
        obligation_bytes BLOB NOT NULL,
        obligation_digest TEXT NOT NULL UNIQUE CHECK({_D.format('obligation_digest')}),
        feedback_id TEXT NOT NULL UNIQUE REFERENCES evaluation_feedback(feedback_id),
        feedback_digest TEXT NOT NULL CHECK({_D.format('feedback_digest')}),
        candidate_id TEXT NOT NULL,
        candidate_version_id TEXT NOT NULL,
        request_id TEXT NOT NULL UNIQUE,
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL,
        authority_aggregate_id TEXT NOT NULL,
        authority_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        recorded_at TEXT NOT NULL,
        UNIQUE(actor_identity_digest,idempotency_key),
        UNIQUE(authority_event_id),
        CHECK(length(obligation_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE evaluation_reconciliation_dispositions(
        disposition_id TEXT PRIMARY KEY,
        disposition_bytes BLOB NOT NULL,
        disposition_digest TEXT NOT NULL UNIQUE CHECK({_D.format('disposition_digest')}),
        obligation_id TEXT NOT NULL REFERENCES evaluation_reconciliation_obligations(obligation_id),
        ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
        previous_disposition_id TEXT,
        previous_disposition_digest TEXT CHECK(previous_disposition_digest IS NULL OR {_D.format('previous_disposition_digest')}),
        outcome TEXT NOT NULL CHECK(outcome IN('fulfilled','blocked','unresolved')),
        request_id TEXT NOT NULL UNIQUE,
        actor_identity_digest TEXT NOT NULL CHECK({_D.format('actor_identity_digest')}),
        idempotency_key TEXT NOT NULL,
        authority_aggregate_id TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(obligation_id,ordinal), UNIQUE(actor_identity_digest,idempotency_key),
        CHECK((ordinal=1 AND previous_disposition_id IS NULL AND previous_disposition_digest IS NULL)
           OR (ordinal>1 AND previous_disposition_id IS NOT NULL AND previous_disposition_digest IS NOT NULL)),
        CHECK(authority_aggregate_version=ordinal+1),
        CHECK(length(disposition_bytes)>0)
    ) STRICT""",
    "CREATE TRIGGER immutable_evaluation_feedback BEFORE UPDATE ON evaluation_feedback BEGIN SELECT RAISE(ABORT,'immutable Evaluation Feedback'); END",
    "CREATE TRIGGER retained_evaluation_feedback BEFORE DELETE ON evaluation_feedback BEGIN SELECT RAISE(ABORT,'retained Evaluation Feedback'); END",
    "CREATE TRIGGER immutable_evaluation_obligation BEFORE UPDATE ON evaluation_reconciliation_obligations BEGIN SELECT RAISE(ABORT,'immutable reconciliation obligation'); END",
    "CREATE TRIGGER retained_evaluation_obligation BEFORE DELETE ON evaluation_reconciliation_obligations BEGIN SELECT RAISE(ABORT,'retained reconciliation obligation'); END",
    "CREATE TRIGGER immutable_evaluation_disposition BEFORE UPDATE ON evaluation_reconciliation_dispositions BEGIN SELECT RAISE(ABORT,'immutable reconciliation disposition'); END",
    "CREATE TRIGGER retained_evaluation_disposition BEFORE DELETE ON evaluation_reconciliation_dispositions BEGIN SELECT RAISE(ABORT,'retained reconciliation disposition'); END",
    """CREATE TRIGGER evaluation_disposition_predecessor_guard
       BEFORE INSERT ON evaluation_reconciliation_dispositions
       WHEN (NEW.ordinal>1 AND NOT EXISTS(
          SELECT 1 FROM evaluation_reconciliation_dispositions p
          WHERE p.obligation_id=NEW.obligation_id AND p.ordinal=NEW.ordinal-1
            AND p.disposition_id=NEW.previous_disposition_id
            AND p.disposition_digest=NEW.previous_disposition_digest))
         OR EXISTS(SELECT 1 FROM evaluation_reconciliation_dispositions p
          WHERE p.obligation_id=NEW.obligation_id AND p.outcome='fulfilled')
       BEGIN SELECT RAISE(ABORT,'reconciliation disposition predecessor differs'); END""",
)

EVALUATION_FEEDBACK_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": EVALUATION_FEEDBACK_SCHEMA_VERSION,
        "name": EVALUATION_FEEDBACK_MIGRATION_NAME,
        "statements": list(EVALUATION_FEEDBACK_MIGRATION_STATEMENTS),
    }
)
EVALUATION_FEEDBACK_MIGRATION = EvaluationFeedbackMigrationRecord(
    EVALUATION_FEEDBACK_SCHEMA_VERSION,
    EVALUATION_FEEDBACK_MIGRATION_NAME,
    EVALUATION_FEEDBACK_MIGRATION_CHECKSUM,
)

__all__ = [
    name
    for name in globals()
    if name.startswith(("EVALUATION_", "Evaluation", "evaluation_", "prepare_", "require_"))
]
