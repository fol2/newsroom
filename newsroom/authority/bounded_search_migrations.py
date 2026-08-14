"""Checked v27 bounded Search authority migration and exact v26 backup gate."""

# fmt: off
# ruff: noqa: I001
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import planned_agenda_migrations as predecessor
from .canonical import digest_canonical

BOUNDED_SEARCH_SCHEMA_VERSION = 27
BOUNDED_SEARCH_MIGRATION_NAME = "bounded_search_authority_v27"
BOUNDED_SEARCH_PREDECESSOR_MIGRATION_CHECKSUM = (
    "sha256:55e6e8878140714dc6fc6c8149357e1f15e4683fcb7ee0b31b168a737bfd3d4c"
)
BOUNDED_SEARCH_PREDECESSOR_FINGERPRINT = (
    "sha256:9c4d5b94b10b34d3b9ef2f140dbfbcc85b2c01fb6d8660879403a21fef701374"
)
BoundedSearchBackupError = predecessor.PlannedAgendaBackupError
BoundedSearchBackupReceipt = predecessor.PlannedAgendaBackupReceipt
BoundedSearchMigrationRecord = predecessor.PlannedAgendaMigrationRecord
_helpers = predecessor.predecessor.predecessor.predecessor


def bounded_search_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v27.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _checked_backup(path: Path, logical: str) -> BoundedSearchBackupReceipt:
    digest_path = path.with_name(path.name + ".sha256")
    digest = _helpers._file_digest(path)
    if digest_path.read_text(encoding="ascii") != digest + "\n":
        raise BoundedSearchBackupError("backup digest differs")
    target = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    try:
        if (
            target.execute("PRAGMA user_version").fetchone()[0] != 26
            or _helpers._schema_fingerprint(target) != BOUNDED_SEARCH_PREDECESSOR_FINGERPRINT
            or _helpers._logical_database_digest(target) != logical
        ):
            raise BoundedSearchBackupError("backup differs from source")
    finally:
        target.close()
    return BoundedSearchBackupReceipt(path, digest_path, digest, logical)


def prepare_bounded_search_backup(
    connection: sqlite3.Connection, backup_path: Path
) -> BoundedSearchBackupReceipt:
    fingerprint = _helpers._schema_fingerprint
    logical_digest = _helpers._logical_database_digest
    file_digest = _helpers._file_digest
    if (
        connection.in_transaction
        or connection.execute("PRAGMA user_version").fetchone()[0] != 26
        or fingerprint(connection) != BOUNDED_SEARCH_PREDECESSOR_FINGERPRINT
        or not isinstance(backup_path, Path)
        or not backup_path.is_absolute()
    ):
        raise BoundedSearchBackupError("backup requires checked schema v26")
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
        raise BoundedSearchBackupError("backup boundary differs")
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
        "CREATE TEMP TABLE IF NOT EXISTS bounded_search_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,"
        "logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM bounded_search_backup_gate")
    connection.execute(
        "INSERT INTO bounded_search_backup_gate VALUES(?,?,?)",
        (str(backup_path), receipt.backup_digest, logical),
    )
    if connection.in_transaction:
        connection.commit()
    return receipt


def require_bounded_search_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> BoundedSearchBackupReceipt:
    logical_digest = _helpers._logical_database_digest
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.bounded_search_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise BoundedSearchBackupError("v26 to v27 requires prepared backup") from exc
    if row is None or logical_digest(connection) != row[2]:
        raise BoundedSearchBackupError("v26 to v27 requires prepared backup")
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
        raise BoundedSearchBackupError("prepared backup is not exact v26")
    return receipt


_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"
BOUNDED_SEARCH_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE search_purposes(
        purpose_id TEXT PRIMARY KEY,
        purpose_bytes BLOB NOT NULL,
        purpose_digest TEXT NOT NULL UNIQUE CHECK({_D.format('purpose_digest')}),
        purpose_kind TEXT NOT NULL,
        query_privacy TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(purpose_id,purpose_digest),
        CHECK(length(purpose_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE search_requests(
        request_id TEXT PRIMARY KEY,
        request_bytes BLOB NOT NULL,
        request_digest TEXT NOT NULL UNIQUE CHECK({_D.format('request_digest')}),
        purpose_id TEXT NOT NULL,
        purpose_digest TEXT NOT NULL CHECK({_D.format('purpose_digest')}),
        provider_id TEXT NOT NULL,
        provider_configuration_digest TEXT NOT NULL CHECK({_D.format('provider_configuration_digest')}),
        budget_reservation_digest TEXT NOT NULL UNIQUE CHECK({_D.format('budget_reservation_digest')}),
        query_privacy TEXT NOT NULL,
        max_provider_calls INTEGER NOT NULL CHECK(max_provider_calls BETWEEN 1 AND 1000000),
        max_results INTEGER NOT NULL CHECK(max_results BETWEEN 1 AND 1000000),
        max_gross_cost_microunits INTEGER NOT NULL CHECK(max_gross_cost_microunits>=0),
        max_elapsed_seconds INTEGER NOT NULL CHECK(max_elapsed_seconds BETWEEN 1 AND 1000000),
        requested_at TEXT NOT NULL,
        FOREIGN KEY(purpose_id,purpose_digest) REFERENCES search_purposes(purpose_id,purpose_digest),
        UNIQUE(request_id,request_digest),
        CHECK(length(request_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE search_attempts(
        attempt_id TEXT PRIMARY KEY,
        attempt_bytes BLOB NOT NULL,
        attempt_digest TEXT NOT NULL UNIQUE CHECK({_D.format('attempt_digest')}),
        request_id TEXT NOT NULL REFERENCES search_requests(request_id),
        request_digest TEXT NOT NULL CHECK({_D.format('request_digest')}),
        attempt_ordinal INTEGER NOT NULL CHECK(attempt_ordinal BETWEEN 1 AND 1000000),
        variant_ordinal INTEGER NOT NULL CHECK(variant_ordinal BETWEEN 1 AND 1000000),
        language_ordinal INTEGER NOT NULL CHECK(language_ordinal BETWEEN 1 AND 1000000),
        page_number INTEGER NOT NULL CHECK(page_number BETWEEN 1 AND 1000000),
        retry_ordinal INTEGER NOT NULL CHECK(retry_ordinal BETWEEN 0 AND 1000000),
        branch_ordinal INTEGER NOT NULL CHECK(branch_ordinal BETWEEN 0 AND 1000000),
        started_at TEXT NOT NULL,
        FOREIGN KEY(request_id,request_digest) REFERENCES search_requests(request_id,request_digest),
        UNIQUE(attempt_id,attempt_digest),
        UNIQUE(request_id,attempt_ordinal),
        CHECK(length(attempt_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE search_outcomes(
        outcome_id TEXT PRIMARY KEY,
        outcome_bytes BLOB NOT NULL,
        outcome_digest TEXT NOT NULL UNIQUE CHECK({_D.format('outcome_digest')}),
        attempt_id TEXT NOT NULL UNIQUE,
        attempt_digest TEXT NOT NULL CHECK({_D.format('attempt_digest')}),
        outcome_kind TEXT NOT NULL,
        result_count INTEGER NOT NULL CHECK(result_count>=0),
        returned_pages INTEGER NOT NULL CHECK(returned_pages>=0),
        gross_cost_microunits INTEGER NOT NULL CHECK(gross_cost_microunits>=0),
        completed_at TEXT NOT NULL,
        FOREIGN KEY(attempt_id,attempt_digest) REFERENCES search_attempts(attempt_id,attempt_digest),
        UNIQUE(outcome_id,outcome_digest),
        CHECK(length(outcome_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE search_result_references(
        result_reference_id TEXT PRIMARY KEY,
        result_bytes BLOB NOT NULL,
        result_digest TEXT NOT NULL UNIQUE CHECK({_D.format('result_digest')}),
        outcome_id TEXT NOT NULL REFERENCES search_outcomes(outcome_id),
        outcome_digest TEXT NOT NULL CHECK({_D.format('outcome_digest')}),
        request_id TEXT NOT NULL REFERENCES search_requests(request_id),
        request_digest TEXT NOT NULL CHECK({_D.format('request_digest')}),
        rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 1000000),
        page_number INTEGER NOT NULL CHECK(page_number BETWEEN 1 AND 1000000),
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(outcome_id,outcome_digest) REFERENCES search_outcomes(outcome_id,outcome_digest),
        FOREIGN KEY(request_id,request_digest) REFERENCES search_requests(request_id,request_digest),
        UNIQUE(outcome_id,rank),
        CHECK(length(result_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE search_review_decisions(
        review_decision_id TEXT PRIMARY KEY,
        decision_bytes BLOB NOT NULL,
        decision_digest TEXT NOT NULL UNIQUE CHECK({_D.format('decision_digest')}),
        request_id TEXT NOT NULL REFERENCES search_requests(request_id),
        request_digest TEXT NOT NULL CHECK({_D.format('request_digest')}),
        action TEXT NOT NULL,
        work_reference_digest TEXT CHECK(work_reference_digest IS NULL OR {_D.format('work_reference_digest')}),
        decided_at TEXT NOT NULL,
        FOREIGN KEY(request_id,request_digest) REFERENCES search_requests(request_id,request_digest),
        CHECK(length(decision_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE search_budget_ledger(
        outcome_id TEXT PRIMARY KEY REFERENCES search_outcomes(outcome_id),
        request_id TEXT NOT NULL REFERENCES search_requests(request_id),
        attempt_id TEXT NOT NULL UNIQUE REFERENCES search_attempts(attempt_id),
        gross_cost_microunits INTEGER NOT NULL CHECK(gross_cost_microunits>=0),
        cumulative_provider_calls INTEGER NOT NULL CHECK(cumulative_provider_calls BETWEEN 1 AND 1000000),
        cumulative_results INTEGER NOT NULL CHECK(cumulative_results>=0),
        cumulative_gross_cost_microunits INTEGER NOT NULL CHECK(cumulative_gross_cost_microunits>=0),
        ledger_digest TEXT NOT NULL UNIQUE CHECK({_D.format('ledger_digest')}),
        recorded_at TEXT NOT NULL,
        UNIQUE(request_id,cumulative_provider_calls)
    ) STRICT""",
    *tuple(
        f"CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable bounded Search record'); END"
        for table in (
            "search_purposes", "search_requests", "search_attempts", "search_outcomes",
            "search_result_references", "search_review_decisions", "search_budget_ledger",
        )
    ),
    *tuple(
        f"CREATE TRIGGER retained_{table} BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'retained bounded Search record'); END"
        for table in (
            "search_purposes", "search_requests", "search_attempts", "search_outcomes",
            "search_result_references", "search_review_decisions", "search_budget_ledger",
        )
    ),
)
BOUNDED_SEARCH_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": BOUNDED_SEARCH_SCHEMA_VERSION,
        "name": BOUNDED_SEARCH_MIGRATION_NAME,
        "statements": list(BOUNDED_SEARCH_MIGRATION_STATEMENTS),
    }
)
BOUNDED_SEARCH_MIGRATION = BoundedSearchMigrationRecord(
    BOUNDED_SEARCH_SCHEMA_VERSION,
    BOUNDED_SEARCH_MIGRATION_NAME,
    BOUNDED_SEARCH_MIGRATION_CHECKSUM,
)
__all__ = [
    name for name in globals()
    if name.startswith(("BOUNDED_", "Bounded", "bounded_", "prepare_", "require_"))
]
# fmt: on
