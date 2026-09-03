"""Checked v34 migration for coupled Graphiti evaluation extraction authority."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import increment8_recovery_migrations as predecessor
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical

GRAPHITI_EVALUATION_SCHEMA_VERSION = 34
GRAPHITI_EVALUATION_MIGRATION_NAME = "graphiti_evaluation_extraction_authority_v34"
GRAPHITI_EVALUATION_PREDECESSOR_FINGERPRINT = (
    "sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676"
)
GraphitiEvaluationBackupError = predecessor.Increment8RecoveryBackupError
GraphitiEvaluationBackupReceipt = predecessor.Increment8RecoveryBackupReceipt
GraphitiEvaluationMigrationRecord = predecessor.Increment8RecoveryMigrationRecord
_helpers = predecessor._helpers


def graphiti_evaluation_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v34.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> GraphitiEvaluationBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = _helpers._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise GraphitiEvaluationBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 32
            or _helpers._schema_fingerprint(target)
            != GRAPHITI_EVALUATION_PREDECESSOR_FINGERPRINT
            or _helpers._logical_database_digest(target) != logical
        ):
            raise GraphitiEvaluationBackupError("backup differs from source")
    finally:
        target.close()
    return GraphitiEvaluationBackupReceipt(path, digest_path, digest, logical)


def prepare_graphiti_evaluation_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> GraphitiEvaluationBackupReceipt:
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 32
        or _helpers._schema_fingerprint(connection)
        != GRAPHITI_EVALUATION_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise GraphitiEvaluationBackupError("backup requires checked schema v32")
    source = Path(
        next(
            row[2]
            for row in connection.execute("PRAGMA database_list")
            if row[1] == "main"
        )
    )
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    logical = _helpers._logical_database_digest(connection)
    if (
        not source
        or source.resolve() == backup_path.resolve()
        or backup_path.exists() != digest_path.exists()
    ):
        raise GraphitiEvaluationBackupError("backup boundary differs")
    if not backup_path.exists():
        backup_path.open("xb").close()
        target = sqlite3.connect(backup_path, isolation_level=None)
        try:
            connection.backup(target)
        finally:
            target.close()
        digest_path.write_text(_helpers._file_digest(backup_path) + "\n", encoding="ascii")
    receipt = _checked_backup(backup_path, logical)
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS graphiti_evaluation_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,"
        "logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM graphiti_evaluation_backup_gate")
    connection.execute(
        "INSERT INTO graphiti_evaluation_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_graphiti_evaluation_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> GraphitiEvaluationBackupReceipt:
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.graphiti_evaluation_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise GraphitiEvaluationBackupError(
            "v32 to v34 requires prepared backup"
        ) from exc
    if row is None or _helpers._logical_database_digest(connection) != row[2]:
        raise GraphitiEvaluationBackupError("v32 to v34 requires prepared backup")
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
        raise GraphitiEvaluationBackupError("prepared backup is not exact v32")
    return receipt


_OUTCOMES = "'SUCCESS','PARTIAL','RETRYABLE_FAILURE','BLOCKING_FAILURE','INVALID_OUTPUT'"
_FAILURES = (
    "'NONE','FIXTURE_PARTIAL','FIXTURE_RETRYABLE','FIXTURE_BLOCKED',"
    "'OUTPUT_SCHEMA_INVALID','POLICY_BLOCKED','PRODUCER_INTERNAL_ERROR',"
    "'EXECUTION_TIMEOUT','AMBIGUOUS_EFFECT'"
)


def _evaluation_workspace_policy_insert() -> str:
    policy = {
        "policy_id": "00000000-0000-4000-8000-000000004803",
        "policy_version": "graphiti-disposable-workspace-v1",
        "namespace_prefix": "newsroom-eval-proposal-6820802464f7",
        "max_workspace_bytes": 33_554_432,
        "max_private_nodes": 20_000,
        "max_private_relations": 40_000,
        "egress_policy": "APPROVED_PROVIDER_ONLY",
        "credential_class": "PROPOSAL_WORKSPACE_ONLY",
        "cleanup_required": True,
        "persistent_state_allowed": False,
    }
    data = canonical_json_bytes(policy)
    quoted = lambda value: "'" + str(value).replace("'", "''") + "'"
    return (
        "INSERT INTO graphiti_workspace_policies("
        "policy_id,policy_version,namespace_prefix,max_workspace_bytes,"
        "max_private_nodes,max_private_relations,egress_policy,credential_class,"
        "cleanup_required,persistent_state_allowed,canonical_bytes,canonical_digest) VALUES("
        f"{quoted(policy['policy_id'])},{quoted(policy['policy_version'])},"
        f"{quoted(policy['namespace_prefix'])},{policy['max_workspace_bytes']},"
        f"{policy['max_private_nodes']},{policy['max_private_relations']},"
        f"{quoted(policy['egress_policy'])},{quoted(policy['credential_class'])},"
        f"1,0,X'{data.hex()}',{quoted(digest_bytes(data))})"
    )

GRAPHITI_EVALUATION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    "PRAGMA defer_foreign_keys=ON",
    _evaluation_workspace_policy_insert(),
    "DROP TRIGGER immutable_extractor_contract_update",
    "DROP TRIGGER immutable_extractor_contract_delete",
    "DROP INDEX idx_extraction_versions_run",
    "CREATE TABLE extractor_contracts_v34 AS SELECT * FROM extractor_contracts WHERE 0",
    "INSERT INTO extractor_contracts_v34 SELECT * FROM extractor_contracts",
    "DROP TABLE extractor_contracts",
    """CREATE TABLE extractor_contracts(
        contract_id TEXT PRIMARY KEY, framework_id TEXT NOT NULL,
        framework_version TEXT NOT NULL, framework_digest TEXT NOT NULL,
        model_id TEXT NOT NULL, model_version TEXT NOT NULL, model_digest TEXT NOT NULL,
        prompt_id TEXT NOT NULL, prompt_version TEXT NOT NULL, prompt_digest TEXT NOT NULL,
        output_schema_id TEXT NOT NULL, output_schema_version TEXT NOT NULL,
        output_schema_digest TEXT NOT NULL, code_id TEXT NOT NULL,
        code_version TEXT NOT NULL, code_digest TEXT NOT NULL,
        normalisation_id TEXT NOT NULL, normalisation_version TEXT NOT NULL,
        normalisation_digest TEXT NOT NULL, policy_id TEXT NOT NULL,
        policy_version TEXT NOT NULL, policy_digest TEXT NOT NULL,
        execution_profile TEXT NOT NULL CHECK(execution_profile='FIXTURE_REPLAY_ONLY'),
        producer_kind TEXT NOT NULL CHECK(producer_kind IN('DETERMINISTIC_FIXTURE','GRAPHITI_EVALUATION')),
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL, canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL, CHECK(length(canonical_bytes)>0)) STRICT""",
    "INSERT INTO extractor_contracts SELECT * FROM extractor_contracts_v34",
    "DROP TABLE extractor_contracts_v34",
    """CREATE TRIGGER immutable_extractor_contract_update BEFORE UPDATE ON
        extractor_contracts BEGIN SELECT RAISE(ABORT,'immutable extractor contract'); END""",
    """CREATE TRIGGER immutable_extractor_contract_delete BEFORE DELETE ON
        extractor_contracts BEGIN SELECT RAISE(ABORT,'extractor contracts are retained'); END""",
    "CREATE TABLE extraction_run_versions_v34 AS SELECT * FROM extraction_run_versions WHERE 0",
    "INSERT INTO extraction_run_versions_v34 SELECT * FROM extraction_run_versions",
    "DROP TABLE extraction_run_versions",
    f"""CREATE TABLE extraction_run_versions(
        run_version_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        version_number INTEGER NOT NULL CHECK(version_number>0),
        previous_run_version_id TEXT REFERENCES extraction_run_versions(run_version_id),
        contract_canonical_digest TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN({_OUTCOMES})),
        failure_code TEXT NOT NULL CHECK(failure_code IN({_FAILURES})),
        started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
        elapsed_ms INTEGER NOT NULL CHECK(elapsed_ms>=0), input_bytes INTEGER NOT NULL CHECK(input_bytes>=0),
        output_bytes INTEGER NOT NULL CHECK(output_bytes>=0), proposal_count INTEGER NOT NULL CHECK(proposal_count>=0),
        evidence_range_count INTEGER NOT NULL CHECK(evidence_range_count>=0), request_tokens INTEGER NOT NULL CHECK(request_tokens>=0),
        response_tokens INTEGER NOT NULL CHECK(response_tokens>=0), cost_microunits INTEGER NOT NULL CHECK(cost_microunits>=0),
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        request_bytes BLOB NOT NULL, request_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL, canonical_digest TEXT NOT NULL, recorded_at TEXT NOT NULL,
        UNIQUE(run_id,version_number), UNIQUE(run_version_id,run_id), UNIQUE(run_id,version_number,run_version_id),
        CHECK((version_number=1 AND previous_run_version_id IS NULL) OR (version_number>1 AND previous_run_version_id IS NOT NULL)),
        CHECK(started_at<=ended_at AND ended_at<=recorded_at),
        CHECK((outcome='SUCCESS' AND failure_code='NONE')
           OR (outcome='PARTIAL' AND failure_code='FIXTURE_PARTIAL')
           OR (outcome='RETRYABLE_FAILURE' AND failure_code IN('FIXTURE_RETRYABLE','PRODUCER_INTERNAL_ERROR','EXECUTION_TIMEOUT','AMBIGUOUS_EFFECT'))
           OR (outcome='BLOCKING_FAILURE' AND failure_code IN('FIXTURE_BLOCKED','POLICY_BLOCKED'))
           OR (outcome='INVALID_OUTPUT' AND failure_code='OUTPUT_SCHEMA_INVALID')),
        CHECK(length(request_bytes)>0), CHECK(length(canonical_bytes)>0)) STRICT""",
    "INSERT INTO extraction_run_versions SELECT * FROM extraction_run_versions_v34",
    "DROP TABLE extraction_run_versions_v34",
    "CREATE INDEX idx_extraction_versions_run ON extraction_run_versions(run_id,version_number)",
    """CREATE TRIGGER extraction_run_version_chain_guard BEFORE INSERT ON extraction_run_versions
        WHEN (NEW.version_number=1 AND EXISTS(SELECT 1 FROM extraction_run_heads h WHERE h.run_id=NEW.run_id))
          OR (NEW.version_number>1 AND NOT EXISTS(SELECT 1 FROM extraction_run_heads h WHERE h.run_id=NEW.run_id AND h.current_run_version_id=NEW.previous_run_version_id AND h.current_version_number=NEW.version_number-1 AND h.terminal=0))
        BEGIN SELECT RAISE(ABORT,'extraction run version does not extend current head'); END""",
    """CREATE TRIGGER extraction_run_version_predecessor_guard BEFORE INSERT ON extraction_run_versions
        WHEN NEW.previous_run_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM extraction_run_versions p WHERE p.run_version_id=NEW.previous_run_version_id AND p.run_id=NEW.run_id AND p.version_number=NEW.version_number-1 AND p.ended_at<=NEW.started_at)
        BEGIN SELECT RAISE(ABORT,'extraction run predecessor mismatch'); END""",
    """CREATE TRIGGER immutable_extraction_run_version_update BEFORE UPDATE ON extraction_run_versions
        BEGIN SELECT RAISE(ABORT,'immutable extraction run version'); END""",
    """CREATE TRIGGER immutable_extraction_run_version_delete BEFORE DELETE ON extraction_run_versions
        BEGIN SELECT RAISE(ABORT,'extraction run versions are retained'); END""",
    """CREATE TRIGGER extraction_run_version_create_head AFTER INSERT ON extraction_run_versions
        WHEN NEW.version_number=1 BEGIN INSERT INTO extraction_run_heads(run_id,current_version_number,current_run_version_id,terminal,updated_at)
        VALUES(NEW.run_id,NEW.version_number,NEW.run_version_id,NEW.outcome IN('SUCCESS','BLOCKING_FAILURE','INVALID_OUTPUT'),NEW.recorded_at); END""",
    """CREATE TRIGGER extraction_run_version_advance_head AFTER INSERT ON extraction_run_versions
        WHEN NEW.version_number>1 BEGIN UPDATE extraction_run_heads SET current_version_number=NEW.version_number,current_run_version_id=NEW.run_version_id,
        terminal=NEW.outcome IN('SUCCESS','BLOCKING_FAILURE','INVALID_OUTPUT'),updated_at=NEW.recorded_at
        WHERE run_id=NEW.run_id AND current_run_version_id=NEW.previous_run_version_id AND terminal=0; END""",
    """CREATE TABLE graphiti_attempt_receipts(
        attempt_id TEXT PRIMARY KEY REFERENCES graphiti_adapter_attempts(attempt_id),
        run_version_id TEXT NOT NULL UNIQUE REFERENCES extraction_run_versions(run_version_id),
        canonical_bytes BLOB NOT NULL, canonical_digest TEXT NOT NULL UNIQUE,
        retained_at TEXT NOT NULL, CHECK(length(canonical_bytes)>0)) WITHOUT ROWID, STRICT""",
    """CREATE TRIGGER immutable_graphiti_attempt_receipt BEFORE UPDATE ON
        graphiti_attempt_receipts BEGIN SELECT RAISE(ABORT,'immutable Graphiti attempt receipt'); END""",
    """CREATE TRIGGER retained_graphiti_attempt_receipt BEFORE DELETE ON
        graphiti_attempt_receipts BEGIN SELECT RAISE(ABORT,'Graphiti attempt receipts are retained'); END""",
)
GRAPHITI_EVALUATION_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": GRAPHITI_EVALUATION_SCHEMA_VERSION,
        "name": GRAPHITI_EVALUATION_MIGRATION_NAME,
        "statements": list(GRAPHITI_EVALUATION_MIGRATION_STATEMENTS),
    }
)
GRAPHITI_EVALUATION_MIGRATION = GraphitiEvaluationMigrationRecord(
    GRAPHITI_EVALUATION_SCHEMA_VERSION,
    GRAPHITI_EVALUATION_MIGRATION_NAME,
    GRAPHITI_EVALUATION_MIGRATION_CHECKSUM,
)

__all__ = [
    name
    for name in globals()
    if name.startswith(
        ("GRAPHITI_EVALUATION_", "GraphitiEvaluation", "graphiti_evaluation_", "prepare_", "require_")
    )
]
