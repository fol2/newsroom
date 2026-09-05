"""Checked v35 migration: persist accounted-zero Graphiti COMPLETE attempts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import graphiti_evaluation_migrations as predecessor
from .canonical import digest_canonical

GRAPHITI_ACCOUNTED_ZERO_SCHEMA_VERSION = 35
GRAPHITI_ACCOUNTED_ZERO_MIGRATION_NAME = (
    "graphiti_accounted_zero_proposal_authority_v35"
)
GRAPHITI_ACCOUNTED_ZERO_PREDECESSOR_FINGERPRINT = (
    "sha256:8b38a4c2279363ed4105c272370bfdc733591c30032aed4cbab5e83ef92b7065"
)
GraphitiAccountedZeroBackupError = predecessor.GraphitiEvaluationBackupError
GraphitiAccountedZeroBackupReceipt = predecessor.GraphitiEvaluationBackupReceipt
GraphitiAccountedZeroMigrationRecord = predecessor.GraphitiEvaluationMigrationRecord
_helpers = predecessor._helpers

_ADAPTER_OUTCOMES = (
    "'COMPLETE','PARTIAL','TIMEOUT','MALFORMED_OUTPUT',"
    "'PROVIDER_REJECTED','POLICY_BLOCKED','FAILED','AMBIGUOUS_EFFECT'"
)


def graphiti_accounted_zero_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v35.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> GraphitiAccountedZeroBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = _helpers._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise GraphitiAccountedZeroBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 34
            or _helpers._schema_fingerprint(target)
            != GRAPHITI_ACCOUNTED_ZERO_PREDECESSOR_FINGERPRINT
            or _helpers._logical_database_digest(target) != logical
        ):
            raise GraphitiAccountedZeroBackupError("backup differs from source")
    finally:
        target.close()
    return GraphitiAccountedZeroBackupReceipt(path, digest_path, digest, logical)


def prepare_graphiti_accounted_zero_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> GraphitiAccountedZeroBackupReceipt:
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 34
        or _helpers._schema_fingerprint(connection)
        != GRAPHITI_ACCOUNTED_ZERO_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise GraphitiAccountedZeroBackupError("backup requires checked schema v34")
    source = Path(
        next(
            row[2]
            for row in connection.execute("PRAGMA database_list")
            if row[1] == "main"
        )
    )
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    if (
        not source
        or source.resolve() == backup_path.resolve()
        or backup_path.exists() != digest_path.exists()
    ):
        raise GraphitiAccountedZeroBackupError("backup boundary differs")
    source_conn = sqlite3.connect(
        f"file:{source}?mode=ro", uri=True, isolation_level=None
    )
    try:
        logical = _helpers._logical_database_digest(source_conn)
        if not backup_path.exists():
            backup_path.open("xb").close()
            target = sqlite3.connect(backup_path, isolation_level=None)
            try:
                source_conn.backup(target)
            finally:
                target.close()
            digest_path.write_text(
                _helpers._file_digest(backup_path) + "\n", encoding="ascii"
            )
    finally:
        source_conn.close()
    receipt = _checked_backup(backup_path, logical)
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS graphiti_accounted_zero_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,"
        "logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM graphiti_accounted_zero_backup_gate")
    connection.execute(
        "INSERT INTO graphiti_accounted_zero_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_graphiti_accounted_zero_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> GraphitiAccountedZeroBackupReceipt:
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.graphiti_accounted_zero_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise GraphitiAccountedZeroBackupError(
            "v34 to v35 requires prepared backup"
        ) from exc
    if row is None or _helpers._logical_database_digest(connection) != row[2]:
        raise GraphitiAccountedZeroBackupError(
            "v34 to v35 requires prepared backup"
        )
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
        raise GraphitiAccountedZeroBackupError("prepared backup is not exact v34")
    return receipt


GRAPHITI_ACCOUNTED_ZERO_MIGRATION_STATEMENTS: tuple[str, ...] = (
    "PRAGMA defer_foreign_keys=ON",
    "CREATE TABLE graphiti_adapter_attempts_v35 AS SELECT * FROM graphiti_adapter_attempts WHERE 0",
    "INSERT INTO graphiti_adapter_attempts_v35 SELECT * FROM graphiti_adapter_attempts",
    "DROP TABLE graphiti_adapter_attempts",
    f"""CREATE TABLE graphiti_adapter_attempts(
        attempt_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        run_version_id TEXT NOT NULL UNIQUE,
        attempt_number INTEGER NOT NULL CHECK(attempt_number>0),
        previous_attempt_id TEXT REFERENCES graphiti_adapter_attempts(attempt_id),
        configuration_id TEXT NOT NULL
            REFERENCES graphiti_adapter_configurations(configuration_id),
        configuration_digest TEXT NOT NULL,
        workspace_id TEXT NOT NULL UNIQUE REFERENCES graphiti_workspaces(workspace_id),
        manifest_id TEXT NOT NULL UNIQUE REFERENCES graphiti_input_manifests(manifest_id),
        outcome TEXT NOT NULL CHECK(outcome IN({_ADAPTER_OUTCOMES})),
        failure_code TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        elapsed_ms INTEGER NOT NULL CHECK(elapsed_ms>=0),
        input_bytes INTEGER NOT NULL CHECK(input_bytes>=0),
        output_bytes INTEGER NOT NULL CHECK(output_bytes>=0),
        proposal_count INTEGER NOT NULL CHECK(proposal_count>=0),
        evidence_range_count INTEGER NOT NULL CHECK(evidence_range_count>=0),
        request_tokens INTEGER NOT NULL CHECK(request_tokens>=0),
        response_tokens INTEGER NOT NULL CHECK(response_tokens>=0),
        cost_microunits INTEGER NOT NULL CHECK(cost_microunits>=0),
        extraction_output_id TEXT REFERENCES extraction_outputs(output_id),
        proposal_set_id TEXT REFERENCES extraction_proposal_sets(proposal_set_id),
        cleanup_receipt_id TEXT NOT NULL UNIQUE
            REFERENCES graphiti_cleanup_receipts(receipt_id),
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL,
        UNIQUE(run_id,attempt_number),
        UNIQUE(run_id,attempt_number,attempt_id),
        FOREIGN KEY(run_version_id,run_id)
            REFERENCES extraction_run_versions(run_version_id,run_id),
        CHECK((attempt_number=1 AND previous_attempt_id IS NULL)
           OR (attempt_number>1 AND previous_attempt_id IS NOT NULL)),
        CHECK(started_at<=ended_at AND ended_at<=recorded_at),
        CHECK(length(canonical_bytes)>0),
        CHECK((outcome IN('COMPLETE','PARTIAL')
               AND extraction_output_id IS NOT NULL
               AND proposal_set_id IS NOT NULL)
           OR (outcome IN('COMPLETE','PARTIAL')
               AND extraction_output_id IS NOT NULL
               AND proposal_set_id IS NULL
               AND proposal_count=0)
           OR (outcome='MALFORMED_OUTPUT'
               AND extraction_output_id IS NOT NULL
               AND proposal_set_id IS NULL)
           OR (outcome IN('TIMEOUT','PROVIDER_REJECTED','POLICY_BLOCKED',
                           'FAILED','AMBIGUOUS_EFFECT')
               AND extraction_output_id IS NULL
               AND proposal_set_id IS NULL))
    ) STRICT""",
    "INSERT INTO graphiti_adapter_attempts SELECT * FROM graphiti_adapter_attempts_v35",
    "DROP TABLE graphiti_adapter_attempts_v35",
    "CREATE INDEX idx_graphiti_attempts_run ON graphiti_adapter_attempts(run_id,attempt_number)",
    """CREATE TRIGGER graphiti_attempt_chain_guard
        BEFORE INSERT ON graphiti_adapter_attempts
        WHEN (NEW.attempt_number=1 AND NEW.previous_attempt_id IS NOT NULL)
          OR (NEW.attempt_number>1 AND NOT EXISTS(
              SELECT 1 FROM graphiti_adapter_attempts
              WHERE attempt_id=NEW.previous_attempt_id
                AND run_id=NEW.run_id
                AND attempt_number=NEW.attempt_number-1
          ))
        BEGIN SELECT RAISE(ABORT,'invalid graphiti attempt chain'); END""",
    """CREATE TRIGGER graphiti_attempt_lineage_guard
        BEFORE INSERT ON graphiti_adapter_attempts
        WHEN NOT EXISTS(
            SELECT 1
            FROM graphiti_adapter_configurations AS c
            JOIN graphiti_input_manifests AS m
              ON m.manifest_id=NEW.manifest_id
            JOIN graphiti_workspaces AS w
              ON w.workspace_id=NEW.workspace_id
            JOIN graphiti_cleanup_receipts AS q
              ON q.receipt_id=NEW.cleanup_receipt_id
            JOIN extraction_run_versions AS v
              ON v.run_version_id=NEW.run_version_id
             AND v.run_id=NEW.run_id
            WHERE c.configuration_id=NEW.configuration_id
              AND c.canonical_digest=NEW.configuration_digest
              AND m.configuration_id=NEW.configuration_id
              AND m.configuration_digest=NEW.configuration_digest
              AND m.run_id=NEW.run_id
              AND m.requested_run_version_id=NEW.run_version_id
              AND w.configuration_id=NEW.configuration_id
              AND q.workspace_id=NEW.workspace_id
        )
        BEGIN SELECT RAISE(ABORT,'graphiti attempt lineage mismatch'); END""",
    """CREATE TRIGGER graphiti_attempt_output_guard
        BEFORE INSERT ON graphiti_adapter_attempts
        WHEN (NEW.extraction_output_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM extraction_outputs
                WHERE output_id=NEW.extraction_output_id
                  AND run_id=NEW.run_id
                  AND run_version_id=NEW.run_version_id
              ))
          OR (NEW.proposal_set_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM extraction_proposal_sets
                WHERE proposal_set_id=NEW.proposal_set_id
                  AND run_id=NEW.run_id
                  AND run_version_id=NEW.run_version_id
              ))
        BEGIN SELECT RAISE(ABORT,'graphiti attempt output lineage mismatch'); END""",
    "CREATE TRIGGER immutable_graphiti_adapter_attempts_update BEFORE UPDATE ON graphiti_adapter_attempts BEGIN SELECT RAISE(ABORT,'immutable graphiti_adapter_attempts'); END",
    "CREATE TRIGGER immutable_graphiti_adapter_attempts_delete BEFORE DELETE ON graphiti_adapter_attempts BEGIN SELECT RAISE(ABORT,'retained graphiti_adapter_attempts'); END",
)
GRAPHITI_ACCOUNTED_ZERO_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": GRAPHITI_ACCOUNTED_ZERO_SCHEMA_VERSION,
        "name": GRAPHITI_ACCOUNTED_ZERO_MIGRATION_NAME,
        "statements": list(GRAPHITI_ACCOUNTED_ZERO_MIGRATION_STATEMENTS),
    }
)
GRAPHITI_ACCOUNTED_ZERO_MIGRATION = GraphitiAccountedZeroMigrationRecord(
    GRAPHITI_ACCOUNTED_ZERO_SCHEMA_VERSION,
    GRAPHITI_ACCOUNTED_ZERO_MIGRATION_NAME,
    GRAPHITI_ACCOUNTED_ZERO_MIGRATION_CHECKSUM,
)


__all__ = [
    name
    for name in globals()
    if name.startswith(
        (
            "GRAPHITI_ACCOUNTED_ZERO_",
            "GraphitiAccountedZero",
            "graphiti_accounted_zero_",
            "prepare_",
            "require_",
        )
    )
]
