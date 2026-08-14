"""Checked v30 Increment 8 evaluation-authority migration and v29 backup gate."""

# fmt: off
# ruff: noqa: I001
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import local_watch_migrations as predecessor
from .canonical import digest_canonical

INCREMENT8_EVALUATION_SCHEMA_VERSION = 30
INCREMENT8_EVALUATION_MIGRATION_NAME = "increment8_evaluation_authority_v30"
INCREMENT8_EVALUATION_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:ca57c62c9bfadc2ea0a09a3bf762f95854e413aa71d324a296b4c867c90dec7b"
)
INCREMENT8_EVALUATION_PREDECESSOR_FINGERPRINT = (
    "sha256:68194825ecc7c429b283204dbc1332a43481e04ca2681fcbf75886a984ea6f55"
)
Increment8EvaluationBackupError = predecessor.LocalWatchBackupError
Increment8EvaluationBackupReceipt = predecessor.LocalWatchBackupReceipt
Increment8EvaluationMigrationRecord = predecessor.LocalWatchMigrationRecord
_helpers = predecessor._helpers


def increment8_evaluation_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v30.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> Increment8EvaluationBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = _helpers._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise Increment8EvaluationBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 29
            or _helpers._schema_fingerprint(target) != INCREMENT8_EVALUATION_PREDECESSOR_FINGERPRINT
            or _helpers._logical_database_digest(target) != logical
        ):
            raise Increment8EvaluationBackupError("backup differs from source")
    finally:
        target.close()
    return Increment8EvaluationBackupReceipt(path, digest_path, digest, logical)


def prepare_increment8_evaluation_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> Increment8EvaluationBackupReceipt:
    fingerprint = _helpers._schema_fingerprint
    logical_digest = _helpers._logical_database_digest
    file_digest = _helpers._file_digest
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 29
        or fingerprint(connection) != INCREMENT8_EVALUATION_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise Increment8EvaluationBackupError("backup requires checked schema v29")
    source = Path(next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"))
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical = logical_digest(connection)
    if not source or source.resolve() == backup_path.resolve() or backup_path.exists() != digest_path.exists():
        raise Increment8EvaluationBackupError("backup boundary differs")
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
        "CREATE TEMP TABLE IF NOT EXISTS increment8_evaluation_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM increment8_evaluation_backup_gate")
    connection.execute(
        "INSERT INTO increment8_evaluation_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_increment8_evaluation_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> Increment8EvaluationBackupReceipt:
    logical_digest = _helpers._logical_database_digest
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest FROM temp.increment8_evaluation_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise Increment8EvaluationBackupError("v29 to v30 requires prepared backup") from exc
    if row is None or logical_digest(connection) != row[2]:
        raise Increment8EvaluationBackupError("v29 to v30 requires prepared backup")
    receipt = _checked_backup(Path(row[0]), str(row[2]))
    target = sqlite3.connect(f"file:{receipt.backup_path}?mode=ro", uri=True, isolation_level=None)
    try:
        history = target.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
    finally:
        target.close()
    if receipt.backup_digest != row[1] or history != list(expected_history):
        raise Increment8EvaluationBackupError("prepared backup is not exact v29")
    return receipt


_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
INCREMENT8_EVALUATION_TABLES = (
        "evaluation_plans",
        "evaluation_epochs",
        "evaluation_runs",
        "evaluation_cases",
        "evaluation_labels",
        "evaluation_adjudications",
        "evaluation_release_decisions",
)
INCREMENT8_EVALUATION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE evaluation_plans(
        plan_id TEXT PRIMARY KEY,
        plan_bytes BLOB NOT NULL,
        plan_digest TEXT NOT NULL UNIQUE CHECK({_D.format('plan_digest')}),
        readiness_digest TEXT NOT NULL CHECK({_D.format('readiness_digest')}),
        component_manifest_digest TEXT NOT NULL CHECK({_D.format('component_manifest_digest')}),
        approved_by_digest TEXT NOT NULL CHECK({_D.format('approved_by_digest')}),
        approved_at TEXT NOT NULL,
        qualification_allowed INTEGER NOT NULL CHECK(qualification_allowed IN (0,1)),
        CHECK(length(plan_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE evaluation_epochs(
        epoch_id TEXT PRIMARY KEY,
        epoch_bytes BLOB NOT NULL,
        epoch_digest TEXT NOT NULL UNIQUE CHECK({_D.format('epoch_digest')}),
        plan_id TEXT NOT NULL REFERENCES evaluation_plans(plan_id),
        plan_digest TEXT NOT NULL CHECK({_D.format('plan_digest')}),
        target_manifest_digest TEXT NOT NULL CHECK({_D.format('target_manifest_digest')}),
        universe_manifest_digest TEXT NOT NULL CHECK({_D.format('universe_manifest_digest')}),
        opened_at TEXT NOT NULL,
        CHECK(length(epoch_bytes)>0),
        UNIQUE(epoch_id,plan_id,epoch_digest)
    ) STRICT""",
    f"""CREATE TABLE evaluation_runs(
        run_id TEXT PRIMARY KEY,
        run_bytes BLOB NOT NULL,
        run_digest TEXT NOT NULL UNIQUE CHECK({_D.format('run_digest')}),
        epoch_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        epoch_digest TEXT NOT NULL CHECK({_D.format('epoch_digest')}),
        run_kind TEXT NOT NULL CHECK(run_kind IN ('CALIBRATION','QUALIFICATION')),
        started_at TEXT NOT NULL,
        CHECK(length(run_bytes)>0),
        FOREIGN KEY(epoch_id,plan_id,epoch_digest) REFERENCES evaluation_epochs(epoch_id,plan_id,epoch_digest)
    ) STRICT""",
    f"""CREATE TABLE evaluation_cases(
        case_id TEXT PRIMARY KEY,
        case_bytes BLOB NOT NULL,
        case_digest TEXT NOT NULL UNIQUE CHECK({_D.format('case_digest')}),
        run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id),
        prospective INTEGER NOT NULL CHECK(prospective IN (0,1)),
        cutoff_at TEXT NOT NULL,
        input_manifest_digest TEXT NOT NULL CHECK({_D.format('input_manifest_digest')}),
        rights_status TEXT NOT NULL CHECK(rights_status IN ('REVIEWABLE','UNREVIEWABLE')),
        CHECK(length(case_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE evaluation_labels(
        label_id TEXT PRIMARY KEY,
        label_bytes BLOB NOT NULL,
        label_digest TEXT NOT NULL UNIQUE CHECK({_D.format('label_digest')}),
        case_id TEXT NOT NULL REFERENCES evaluation_cases(case_id),
        reviewer_identity_digest TEXT NOT NULL CHECK({_D.format('reviewer_identity_digest')}),
        review_role TEXT NOT NULL CHECK(review_role IN ('PRIMARY','SECONDARY')),
        blinded INTEGER NOT NULL CHECK(blinded IN (0,1)),
        recorded_at TEXT NOT NULL,
        CHECK(length(label_bytes)>0),
        UNIQUE(case_id,reviewer_identity_digest,review_role)
    ) STRICT""",
    f"""CREATE TABLE evaluation_adjudications(
        adjudication_id TEXT PRIMARY KEY,
        adjudication_bytes BLOB NOT NULL,
        adjudication_digest TEXT NOT NULL UNIQUE CHECK({_D.format('adjudication_digest')}),
        case_id TEXT NOT NULL UNIQUE REFERENCES evaluation_cases(case_id),
        primary_label_digest TEXT NOT NULL CHECK({_D.format('primary_label_digest')}),
        secondary_label_digest TEXT NOT NULL CHECK({_D.format('secondary_label_digest')}),
        adjudicator_identity_digest TEXT NOT NULL CHECK({_D.format('adjudicator_identity_digest')}),
        decided_at TEXT NOT NULL,
        CHECK(primary_label_digest!=secondary_label_digest),
        CHECK(length(adjudication_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE evaluation_release_decisions(
        decision_id TEXT PRIMARY KEY,
        decision_bytes BLOB NOT NULL,
        decision_digest TEXT NOT NULL UNIQUE CHECK({_D.format('decision_digest')}),
        run_id TEXT NOT NULL UNIQUE REFERENCES evaluation_runs(run_id),
        report_digest TEXT NOT NULL CHECK({_D.format('report_digest')}),
        verdict TEXT NOT NULL CHECK(verdict IN ('PASS','FAIL','INCONCLUSIVE')),
        owner_identity_digest TEXT NOT NULL CHECK({_D.format('owner_identity_digest')}),
        decided_at TEXT NOT NULL,
        early_stopped INTEGER NOT NULL CHECK(early_stopped IN (0,1)),
        production_activation_authorised INTEGER NOT NULL CHECK(production_activation_authorised=0),
        CHECK(length(decision_bytes)>0)
    ) STRICT""",
    *tuple(
        f"CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable Increment 8 evaluation record'); END"
        for table in INCREMENT8_EVALUATION_TABLES
    ),
    *tuple(
        f"CREATE TRIGGER retained_{table} BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'retained Increment 8 evaluation record'); END"
        for table in INCREMENT8_EVALUATION_TABLES
    ),
)
INCREMENT8_EVALUATION_MIGRATION_CHECKSUM = digest_canonical({
    "version": INCREMENT8_EVALUATION_SCHEMA_VERSION,
    "name": INCREMENT8_EVALUATION_MIGRATION_NAME,
    "statements": list(INCREMENT8_EVALUATION_MIGRATION_STATEMENTS),
})
INCREMENT8_EVALUATION_MIGRATION = Increment8EvaluationMigrationRecord(
    INCREMENT8_EVALUATION_SCHEMA_VERSION,
    INCREMENT8_EVALUATION_MIGRATION_NAME,
    INCREMENT8_EVALUATION_MIGRATION_CHECKSUM,
)
__all__ = [name for name in globals() if name.startswith(("INCREMENT8_EVALUATION_", "Increment8Evaluation", "increment8_evaluation_", "prepare_", "require_"))]
# fmt: on
