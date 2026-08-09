from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3

from .canonical import digest_canonical


EVALUATION_HANDOFF_SCHEMA_VERSION = 17
EVALUATION_HANDOFF_MIGRATION_NAME = "evaluation_handoff_authority_v17"
EVALUATION_HANDOFF_PREDECESSOR_FINGERPRINT = (
    "sha256:b5a6d2afc78838cdeb648e7cd34b66452f2e0a0f7dab4773dd17a4cc28e3b5d8"
)


class EvaluationHandoffBackupError(sqlite3.DatabaseError):
    """The exact retained v16 backup boundary is absent or differs."""


@dataclass(frozen=True, slots=True)
class EvaluationHandoffBackupReceipt:
    backup_path: Path
    digest_path: Path
    backup_digest: str
    logical_digest: str


@dataclass(frozen=True, slots=True)
class EvaluationHandoffMigrationRecord:
    version: int
    name: str
    checksum: str


def evaluation_handoff_backup_paths(database: str | Path) -> tuple[Path, Path]:
    source = Path(database)
    backup = source.with_name(source.name + ".pre-v17.sqlite3")
    return backup, backup.with_name(backup.name + ".sha256")


def _logical_database_digest(connection: sqlite3.Connection) -> str:
    return digest_canonical(list(connection.iterdump()))


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    return digest_canonical(
        [
            [str(row[0]), str(row[1]), str(row[2]), " ".join(str(row[3] or "").split())]
            for row in rows
        ]
    )


def prepare_evaluation_handoff_backup(
    connection: sqlite3.Connection,
    backup_path: Path,
) -> EvaluationHandoffBackupReceipt:
    """Retain an exact v16 SQLite backup and digest before the v17 upgrade."""
    if connection.in_transaction:
        raise EvaluationHandoffBackupError("backup requires no active transaction")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 16:
        raise EvaluationHandoffBackupError("backup requires exact schema v16")
    if (
        _schema_fingerprint(connection)
        != EVALUATION_HANDOFF_PREDECESSOR_FINGERPRINT
    ):
        raise EvaluationHandoffBackupError("backup requires checked v16 schema")
    if not isinstance(backup_path, Path) or not backup_path.is_absolute():
        raise EvaluationHandoffBackupError("backup path must be absolute")
    source_path = Path(
        next(
            row[2]
            for row in connection.execute("PRAGMA database_list").fetchall()
            if row[1] == "main"
        )
    )
    if not source_path or source_path.resolve() == backup_path.resolve():
        raise EvaluationHandoffBackupError("backup path must differ from source")
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    source_logical_digest = _logical_database_digest(connection)
    if backup_path.exists() != digest_path.exists():
        raise EvaluationHandoffBackupError("backup receipt is incomplete")
    if backup_path.exists():
        backup_digest = _file_digest(backup_path)
        if digest_path.read_text(encoding="ascii") != backup_digest + "\n":
            raise EvaluationHandoffBackupError("retained backup digest differs")
        backup_connection = sqlite3.connect(
            f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
        )
        try:
            backup_logical_digest = _logical_database_digest(backup_connection)
            backup_version = backup_connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            backup_fingerprint = _schema_fingerprint(backup_connection)
        finally:
            backup_connection.close()
        if (
            backup_version != 16
            or backup_fingerprint != EVALUATION_HANDOFF_PREDECESSOR_FINGERPRINT
            or backup_logical_digest != source_logical_digest
        ):
            raise EvaluationHandoffBackupError("retained backup differs from source")
    else:
        backup_path.open("xb").close()
        backup_connection = sqlite3.connect(backup_path, isolation_level=None)
        try:
            connection.backup(backup_connection)
            backup_logical_digest = _logical_database_digest(backup_connection)
        finally:
            backup_connection.close()
        if backup_logical_digest != source_logical_digest:
            raise EvaluationHandoffBackupError("backup differs from source snapshot")
        backup_digest = _file_digest(backup_path)
        with digest_path.open("x", encoding="ascii") as receipt_file:
            receipt_file.write(backup_digest + "\n")
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS evaluation_handoff_backup_gate("
        "backup_path TEXT PRIMARY KEY,backup_digest TEXT NOT NULL,"
        "logical_digest TEXT NOT NULL) STRICT"
    )
    connection.execute("DELETE FROM evaluation_handoff_backup_gate")
    connection.execute(
        "INSERT INTO evaluation_handoff_backup_gate VALUES(?,?,?)",
        (str(backup_path), backup_digest, source_logical_digest),
    )
    if connection.in_transaction:
        connection.commit()
    return EvaluationHandoffBackupReceipt(
        backup_path=backup_path,
        digest_path=digest_path,
        backup_digest=backup_digest,
        logical_digest=source_logical_digest,
    )


def require_evaluation_handoff_backup(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> EvaluationHandoffBackupReceipt:
    """Validate the prepared backup while the upgrade holds its exclusive lock."""
    try:
        row = connection.execute(
            "SELECT backup_path,backup_digest,logical_digest "
            "FROM temp.evaluation_handoff_backup_gate"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise EvaluationHandoffBackupError(
            "v16 to v17 upgrade requires a prepared backup"
        ) from exc
    if row is None:
        raise EvaluationHandoffBackupError(
            "v16 to v17 upgrade requires a prepared backup"
        )
    backup_path = Path(str(row[0]))
    digest_path = backup_path.with_name(backup_path.name + ".sha256")
    backup_digest = str(row[1])
    logical_digest = str(row[2])
    if (
        not backup_path.is_file()
        or not digest_path.is_file()
        or _file_digest(backup_path) != backup_digest
        or digest_path.read_text(encoding="ascii") != backup_digest + "\n"
        or _logical_database_digest(connection) != logical_digest
    ):
        raise EvaluationHandoffBackupError("prepared backup identity differs")
    backup_connection = sqlite3.connect(
        f"file:{backup_path}?mode=ro", uri=True, isolation_level=None
    )
    try:
        if (
            backup_connection.execute("PRAGMA user_version").fetchone()[0] != 16
            or _schema_fingerprint(backup_connection)
            != EVALUATION_HANDOFF_PREDECESSOR_FINGERPRINT
            or _logical_database_digest(backup_connection) != logical_digest
            or backup_connection.execute(
                "SELECT version,name,checksum FROM authority_migrations "
                "ORDER BY version"
            ).fetchall()
            != list(expected_history)
        ):
            raise EvaluationHandoffBackupError("prepared backup is not exact v16")
    finally:
        backup_connection.close()
    return EvaluationHandoffBackupReceipt(
        backup_path=backup_path,
        digest_path=digest_path,
        backup_digest=backup_digest,
        logical_digest=logical_digest,
    )


EVALUATION_HANDOFF_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE evaluation_handoffs(
        handoff_id TEXT PRIMARY KEY,
        schema_identity TEXT NOT NULL
            CHECK(schema_identity='newsroom.increment6.evaluation-handoff.v1'),
        candidate_version_id TEXT NOT NULL,
        governing_manifest_digest TEXT NOT NULL,
        sink_id TEXT NOT NULL CHECK(sink_id LIKE 'evaluation-sink:%'),
        max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 100),
        transport_state TEXT NOT NULL
            CHECK(transport_state IN('pending','acknowledged','rejected','ambiguous','retry')),
        retry_exhausted INTEGER NOT NULL CHECK(retry_exhausted IN(0,1)),
        ambiguity_reason TEXT,
        evaluation_only INTEGER NOT NULL CHECK(evaluation_only=1),
        publication_authority INTEGER NOT NULL CHECK(publication_authority=0),
        evidence_authority INTEGER NOT NULL CHECK(evidence_authority=0),
        UNIQUE(candidate_version_id,governing_manifest_digest,sink_id),
        CHECK(substr(governing_manifest_digest,1,7)='sha256:'
              AND length(governing_manifest_digest)=71
              AND substr(governing_manifest_digest,8)
                  NOT GLOB '*[^0-9a-f]*'),
        CHECK((retry_exhausted=0) OR transport_state='ambiguous')
    ) STRICT""",
    """CREATE TABLE evaluation_handoff_attempts(
        attempt_id TEXT PRIMARY KEY,
        schema_identity TEXT NOT NULL
            CHECK(schema_identity='newsroom.increment6.evaluation-handoff-attempt.v1'),
        handoff_id TEXT NOT NULL REFERENCES evaluation_handoffs(handoff_id),
        attempt_number INTEGER NOT NULL CHECK(attempt_number>0),
        semantic_idempotency_key TEXT NOT NULL,
        persisted_before_send INTEGER NOT NULL CHECK(persisted_before_send=1),
        sent INTEGER NOT NULL CHECK(sent IN(0,1)),
        ambiguous INTEGER NOT NULL CHECK(ambiguous IN(0,1)),
        UNIQUE(handoff_id,attempt_number),
        UNIQUE(attempt_id,handoff_id),
        CHECK(semantic_idempotency_key=handoff_id),
        CHECK(ambiguous=0 OR sent=1)
    ) STRICT""",
    """CREATE TABLE evaluation_handoff_acknowledgements(
        acknowledgement_id TEXT NOT NULL,
        schema_identity TEXT NOT NULL
            CHECK(schema_identity='newsroom.increment6.evaluation-handoff-acknowledgement.v1'),
        recorded_handoff_id TEXT NOT NULL
            REFERENCES evaluation_handoffs(handoff_id),
        handoff_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        candidate_version_id TEXT NOT NULL,
        governing_manifest_digest TEXT NOT NULL,
        sink_id TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN('acknowledged','rejected')),
        response_digest TEXT NOT NULL,
        PRIMARY KEY(recorded_handoff_id,acknowledgement_id),
        CHECK(substr(governing_manifest_digest,1,7)='sha256:'
              AND length(governing_manifest_digest)=71
              AND substr(governing_manifest_digest,8)
                  NOT GLOB '*[^0-9a-f]*'),
        CHECK(substr(response_digest,1,7)='sha256:'
              AND length(response_digest)=71
              AND substr(response_digest,8) NOT GLOB '*[^0-9a-f]*')
    ) WITHOUT ROWID, STRICT""",
    """CREATE TRIGGER evaluation_handoff_identity_guard
        BEFORE UPDATE ON evaluation_handoffs
        WHEN NEW.handoff_id!=OLD.handoff_id
          OR NEW.schema_identity!=OLD.schema_identity
          OR NEW.candidate_version_id!=OLD.candidate_version_id
          OR NEW.governing_manifest_digest!=OLD.governing_manifest_digest
          OR NEW.sink_id!=OLD.sink_id
          OR NEW.max_attempts!=OLD.max_attempts
          OR NEW.evaluation_only!=OLD.evaluation_only
          OR NEW.publication_authority!=OLD.publication_authority
          OR NEW.evidence_authority!=OLD.evidence_authority
        BEGIN SELECT RAISE(ABORT,'immutable evaluation Handoff identity'); END""",
    """CREATE TRIGGER evaluation_handoff_state_guard
        BEFORE UPDATE ON evaluation_handoffs
        WHEN NOT (
            NEW.transport_state=OLD.transport_state
            OR (OLD.transport_state='pending'
                AND NEW.transport_state IN('ambiguous','acknowledged','rejected'))
            OR (OLD.transport_state='ambiguous'
                AND NEW.transport_state IN('retry','acknowledged','rejected'))
            OR (OLD.transport_state='retry'
                AND NEW.transport_state IN('pending','acknowledged','rejected'))
            OR (OLD.transport_state IN('acknowledged','rejected')
                AND NEW.transport_state='ambiguous')
            OR (OLD.transport_state IN('acknowledged','rejected')
                AND NEW.transport_state='pending'
                AND EXISTS(
                    SELECT 1 FROM evaluation_handoff_attempts AS active
                    WHERE active.handoff_id=NEW.handoff_id
                      AND active.attempt_number=(
                          SELECT MAX(attempt_number)
                          FROM evaluation_handoff_attempts
                          WHERE handoff_id=NEW.handoff_id
                      )
                      AND active.attempt_number>1
                      AND active.ambiguous=0
                      AND NOT EXISTS(
                          SELECT 1
                          FROM evaluation_handoff_acknowledgements AS current_ack
                          WHERE current_ack.recorded_handoff_id=NEW.handoff_id
                            AND current_ack.attempt_id=active.attempt_id
                      )
                      AND EXISTS(
                          SELECT 1
                          FROM evaluation_handoff_acknowledgements
                          WHERE recorded_handoff_id=NEW.handoff_id
                            AND outcome='acknowledged'
                      )
                      AND EXISTS(
                          SELECT 1
                          FROM evaluation_handoff_acknowledgements
                          WHERE recorded_handoff_id=NEW.handoff_id
                            AND outcome='rejected'
                      )
                ))
        )
        OR (
            NEW.transport_state IN('acknowledged','rejected')
            AND NOT EXISTS(
                SELECT 1
                FROM evaluation_handoff_acknowledgements AS k
                JOIN evaluation_handoff_attempts AS a
                  ON a.attempt_id=k.attempt_id
                 AND a.handoff_id=NEW.handoff_id
                WHERE k.recorded_handoff_id=NEW.handoff_id
                  AND k.handoff_id=NEW.handoff_id
                  AND k.candidate_version_id=NEW.candidate_version_id
                  AND k.governing_manifest_digest=NEW.governing_manifest_digest
                  AND k.sink_id=NEW.sink_id
                  AND k.outcome=NEW.transport_state
                AND a.sent=1
            )
        )
        OR (
            NEW.transport_state IN('acknowledged','rejected')
            AND EXISTS(
                SELECT 1
                FROM evaluation_handoff_acknowledgements AS conflict
                WHERE conflict.recorded_handoff_id=NEW.handoff_id
                  AND conflict.outcome!=NEW.transport_state
            )
        )
        BEGIN SELECT RAISE(ABORT,'invalid evaluation Handoff state transition'); END""",
    """CREATE TRIGGER evaluation_handoff_attempt_insert_guard
        BEFORE INSERT ON evaluation_handoff_attempts
        WHEN NOT EXISTS(
            SELECT 1 FROM evaluation_handoffs AS h
            WHERE h.handoff_id=NEW.handoff_id
              AND NEW.attempt_number=(
                  SELECT COUNT(*)+1 FROM evaluation_handoff_attempts
                  WHERE handoff_id=NEW.handoff_id
              )
              AND NEW.attempt_number<=h.max_attempts
              AND (
                  (NEW.attempt_number=1 AND h.transport_state='pending')
                  OR (
                      NEW.attempt_number>1
                      AND h.transport_state='retry'
                      AND EXISTS(
                          SELECT 1 FROM evaluation_handoff_attempts AS previous
                          WHERE previous.handoff_id=NEW.handoff_id
                            AND previous.attempt_number=NEW.attempt_number-1
                            AND previous.sent=1
                            AND previous.ambiguous=1
                      )
                  )
              )
        )
        BEGIN SELECT RAISE(ABORT,'invalid evaluation Handoff attempt sequence'); END""",
    """CREATE TRIGGER evaluation_handoff_attempt_update_guard
        BEFORE UPDATE ON evaluation_handoff_attempts
        WHEN NEW.attempt_id!=OLD.attempt_id
          OR NEW.schema_identity!=OLD.schema_identity
          OR NEW.handoff_id!=OLD.handoff_id
          OR NEW.attempt_number!=OLD.attempt_number
          OR NEW.semantic_idempotency_key!=OLD.semantic_idempotency_key
          OR NEW.persisted_before_send!=OLD.persisted_before_send
          OR NEW.sent<OLD.sent OR NEW.ambiguous<OLD.ambiguous
        BEGIN SELECT RAISE(ABORT,'immutable evaluation Handoff attempt identity'); END""",
    *tuple(
        statement
        for table in (
            "evaluation_handoffs",
            "evaluation_handoff_attempts",
            "evaluation_handoff_acknowledgements",
        )
        for statement in (
            f"CREATE TRIGGER retained_{table}_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT,'retained {table}'); END",
        )
    ),
    """CREATE TRIGGER immutable_evaluation_handoff_acknowledgements_update
        BEFORE UPDATE ON evaluation_handoff_acknowledgements
        BEGIN SELECT RAISE(ABORT,'immutable evaluation Handoff acknowledgement'); END""",
    """CREATE TRIGGER evaluation_handoff_ack_correlation_guard
        BEFORE INSERT ON evaluation_handoff_acknowledgements
        WHEN NOT EXISTS(
            SELECT 1
            FROM evaluation_handoffs AS h
            JOIN evaluation_handoff_attempts AS a
              ON a.handoff_id=h.handoff_id
             AND a.attempt_id=NEW.attempt_id
            WHERE h.handoff_id=NEW.recorded_handoff_id
              AND NEW.handoff_id=h.handoff_id
              AND NEW.candidate_version_id=h.candidate_version_id
              AND NEW.governing_manifest_digest=h.governing_manifest_digest
              AND NEW.sink_id=h.sink_id
              AND a.sent=1
        )
        BEGIN SELECT RAISE(ABORT,'invalid acknowledgement correlation'); END""",
)


EVALUATION_HANDOFF_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": EVALUATION_HANDOFF_SCHEMA_VERSION,
        "name": EVALUATION_HANDOFF_MIGRATION_NAME,
        "statements": list(EVALUATION_HANDOFF_MIGRATION_STATEMENTS),
    }
)
EVALUATION_HANDOFF_MIGRATION = EvaluationHandoffMigrationRecord(
    version=EVALUATION_HANDOFF_SCHEMA_VERSION,
    name=EVALUATION_HANDOFF_MIGRATION_NAME,
    checksum=EVALUATION_HANDOFF_MIGRATION_CHECKSUM,
)


__all__ = [
    "EvaluationHandoffBackupError",
    "EvaluationHandoffBackupReceipt",
    "EVALUATION_HANDOFF_MIGRATION",
    "EVALUATION_HANDOFF_MIGRATION_CHECKSUM",
    "EVALUATION_HANDOFF_MIGRATION_NAME",
    "EVALUATION_HANDOFF_MIGRATION_STATEMENTS",
    "EVALUATION_HANDOFF_SCHEMA_VERSION",
    "evaluation_handoff_backup_paths",
    "prepare_evaluation_handoff_backup",
    "require_evaluation_handoff_backup",
]
