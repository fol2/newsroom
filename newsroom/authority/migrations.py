from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Iterable

from .canonical import digest_canonical
from .object_migrations import (
    OBJECT_MIGRATION,
    OBJECT_MIGRATION_CHECKSUM,
    OBJECT_MIGRATION_NAME,
    OBJECT_MIGRATION_STATEMENTS,
    OBJECT_SCHEMA_VERSION,
)
from .projection_migrations import (
    PROJECTION_MIGRATION,
    PROJECTION_MIGRATION_CHECKSUM,
    PROJECTION_MIGRATION_NAME,
    PROJECTION_MIGRATION_STATEMENTS,
    PROJECTION_SCHEMA_VERSION,
)
from .projection_promotion_migrations import (
    PROJECTION_PROMOTION_MIGRATION,
    PROJECTION_PROMOTION_MIGRATION_CHECKSUM,
    PROJECTION_PROMOTION_MIGRATION_NAME,
    PROJECTION_PROMOTION_MIGRATION_STATEMENTS,
    PROJECTION_PROMOTION_SCHEMA_VERSION,
)

BASE_SCHEMA_VERSION = 1
SCHEMA_VERSION = PROJECTION_PROMOTION_SCHEMA_VERSION
MIGRATION_NAME = "authority_event_foundation_v1"


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    version: int
    name: str
    checksum: str


MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE authority_migrations(
        version INTEGER PRIMARY KEY CHECK(version > 0),
        name TEXT NOT NULL UNIQUE,
        checksum TEXT NOT NULL,
        applied_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE payload_schema_contracts(
        contract_digest TEXT PRIMARY KEY,
        schema_version TEXT NOT NULL,
        payload_mode TEXT NOT NULL
            CHECK(payload_mode IN ('INLINE','OBJECT_ADMISSION','NO_PAYLOAD')),
        contract_version TEXT NOT NULL,
        canonicalizer_implementation_version TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(
            schema_version,
            payload_mode,
            contract_version,
            canonicalizer_implementation_version
        ),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE command_definitions(
        definition_digest TEXT PRIMARY KEY,
        command_type TEXT NOT NULL,
        definition_version TEXT NOT NULL,
        payload_schema_contract_digest TEXT NOT NULL
            REFERENCES payload_schema_contracts(contract_digest),
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(command_type, definition_version),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE authentication_contexts(
        authentication_context_id TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        authority_domain TEXT NOT NULL,
        authentication_method TEXT NOT NULL,
        assurance_class TEXT NOT NULL,
        credential_binding_digest TEXT NOT NULL,
        authenticated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE authorization_requests(
        request_digest TEXT PRIMARY KEY,
        authentication_context_id TEXT NOT NULL
            REFERENCES authentication_contexts(authentication_context_id),
        principal_id TEXT NOT NULL,
        authority_domain TEXT NOT NULL,
        operation_type TEXT NOT NULL,
        required_scope TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_record_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(request_digest, authentication_context_id),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE authorization_decisions(
        authorization_decision_id TEXT PRIMARY KEY,
        authentication_context_id TEXT NOT NULL,
        authorization_request_digest TEXT NOT NULL,
        authorization_policy_version TEXT NOT NULL,
        effective_scopes BLOB NOT NULL,
        effective_scope_digest TEXT NOT NULL,
        allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),
        reason_code TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        UNIQUE(
            authorization_decision_id,
            authentication_context_id,
            authorization_request_digest
        ),
        FOREIGN KEY(authentication_context_id)
            REFERENCES authentication_contexts(authentication_context_id),
        FOREIGN KEY(authorization_request_digest, authentication_context_id)
            REFERENCES authorization_requests(
                request_digest, authentication_context_id
            ),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE authority_payloads(
        payload_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL
            CHECK(mode IN ('INLINE','OBJECT_ADMISSION','NO_PAYLOAD')),
        schema_version TEXT NOT NULL,
        schema_contract_version TEXT NOT NULL,
        schema_contract_digest TEXT NOT NULL
            REFERENCES payload_schema_contracts(contract_digest),
        canonicalizer_implementation_version TEXT NOT NULL,
        payload_digest TEXT NOT NULL,
        payload_bytes BLOB,
        object_admission_id TEXT,
        created_at TEXT NOT NULL,
        CHECK((mode='INLINE' AND payload_bytes IS NOT NULL
               AND length(payload_bytes) > 0 AND object_admission_id IS NULL)
           OR (mode='OBJECT_ADMISSION' AND payload_bytes IS NULL
               AND object_admission_id IS NOT NULL)
           OR (mode='NO_PAYLOAD' AND payload_bytes IS NOT NULL
               AND length(payload_bytes) = 0 AND object_admission_id IS NULL))
    ) STRICT""",
    """CREATE TABLE authority_aggregates(
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        current_version INTEGER NOT NULL CHECK(current_version > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(aggregate_type, aggregate_id),
        FOREIGN KEY(aggregate_type, aggregate_id, current_version)
            REFERENCES authority_aggregate_versions(
                aggregate_type, aggregate_id, aggregate_version
            ) DEFERRABLE INITIALLY DEFERRED
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE authority_commands(
        command_id TEXT PRIMARY KEY,
        command_type TEXT NOT NULL,
        producer_version TEXT NOT NULL,
        command_definition_version TEXT NOT NULL,
        command_definition_digest TEXT NOT NULL
            REFERENCES command_definitions(definition_digest),
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        expected_aggregate_version INTEGER NOT NULL
            CHECK(expected_aggregate_version >= 0),
        payload_id TEXT NOT NULL REFERENCES authority_payloads(payload_id),
        idempotency_namespace TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        stable_semantic_request_digest TEXT NOT NULL,
        authentication_context_id TEXT NOT NULL,
        authorization_request_digest TEXT NOT NULL,
        authorization_decision_id TEXT NOT NULL,
        result_digest TEXT NOT NULL,
        result_bytes BLOB NOT NULL,
        committed_at TEXT NOT NULL,
        UNIQUE(idempotency_namespace, idempotency_key),
        FOREIGN KEY(authentication_context_id)
            REFERENCES authentication_contexts(authentication_context_id),
        FOREIGN KEY(authorization_request_digest, authentication_context_id)
            REFERENCES authorization_requests(
                request_digest, authentication_context_id
            ),
        FOREIGN KEY(
            authorization_decision_id,
            authentication_context_id,
            authorization_request_digest
        ) REFERENCES authorization_decisions(
            authorization_decision_id,
            authentication_context_id,
            authorization_request_digest
        ),
        CHECK(length(result_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE authority_aggregate_versions(
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        aggregate_version INTEGER NOT NULL CHECK(aggregate_version > 0),
        command_id TEXT NOT NULL UNIQUE
            REFERENCES authority_commands(command_id),
        payload_id TEXT NOT NULL REFERENCES authority_payloads(payload_id),
        trust_scope TEXT NOT NULL
            CHECK(trust_scope IN ('OBSERVED','PROPOSED','ADMITTED')),
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(aggregate_type, aggregate_id, aggregate_version),
        FOREIGN KEY(aggregate_type, aggregate_id)
            REFERENCES authority_aggregates(aggregate_type, aggregate_id)
            DEFERRABLE INITIALLY DEFERRED
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE authority_audit_events(
        audit_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL UNIQUE
            REFERENCES authority_commands(command_id),
        authentication_context_id TEXT NOT NULL,
        authorization_request_digest TEXT NOT NULL,
        authorization_decision_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        detail_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(authorization_request_digest, authentication_context_id)
            REFERENCES authorization_requests(
                request_digest, authentication_context_id
            ),
        FOREIGN KEY(
            authorization_decision_id,
            authentication_context_id,
            authorization_request_digest
        ) REFERENCES authorization_decisions(
            authorization_decision_id,
            authentication_context_id,
            authorization_request_digest
        )
    ) STRICT""",
    """CREATE TABLE ledger_events(
        ledger_seq INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        event_schema_version INTEGER NOT NULL CHECK(event_schema_version > 0),
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        aggregate_version INTEGER NOT NULL CHECK(aggregate_version > 0),
        recorded_at TEXT NOT NULL,
        command_id TEXT NOT NULL UNIQUE
            REFERENCES authority_commands(command_id),
        producer_version TEXT NOT NULL,
        command_definition_version TEXT NOT NULL,
        command_definition_digest TEXT NOT NULL
            REFERENCES command_definitions(definition_digest),
        payload_id TEXT NOT NULL REFERENCES authority_payloads(payload_id),
        payload_mode TEXT NOT NULL,
        payload_schema_version TEXT NOT NULL,
        payload_schema_contract_version TEXT NOT NULL,
        payload_schema_contract_digest TEXT NOT NULL
            REFERENCES payload_schema_contracts(contract_digest),
        payload_canonicalizer_version TEXT NOT NULL,
        payload_digest TEXT NOT NULL,
        object_admission_id TEXT,
        principal_id TEXT NOT NULL,
        authentication_context_id TEXT NOT NULL,
        authorization_request_digest TEXT NOT NULL,
        authorization_decision_id TEXT NOT NULL,
        correlation_id TEXT,
        causation_kind TEXT
            CHECK(causation_kind IN ('COMMAND','EVENT','EXTERNAL')),
        causation_identifier TEXT,
        causation_external_system TEXT,
        security_scope TEXT NOT NULL,
        retention_scope TEXT NOT NULL,
        trust_scope TEXT NOT NULL
            CHECK(trust_scope IN ('OBSERVED','PROPOSED','ADMITTED')),
        FOREIGN KEY(aggregate_type, aggregate_id, aggregate_version)
            REFERENCES authority_aggregate_versions(
                aggregate_type, aggregate_id, aggregate_version
            ),
        FOREIGN KEY(authorization_request_digest, authentication_context_id)
            REFERENCES authorization_requests(
                request_digest, authentication_context_id
            ),
        FOREIGN KEY(
            authorization_decision_id,
            authentication_context_id,
            authorization_request_digest
        ) REFERENCES authorization_decisions(
            authorization_decision_id,
            authentication_context_id,
            authorization_request_digest
        ),
        CHECK((causation_kind IS NULL AND causation_identifier IS NULL
               AND causation_external_system IS NULL)
           OR (causation_kind IN ('COMMAND','EVENT')
               AND causation_identifier IS NOT NULL
               AND causation_external_system IS NULL)
           OR (causation_kind='EXTERNAL'
               AND causation_identifier IS NOT NULL
               AND causation_external_system IS NOT NULL))
    ) STRICT""",
    "CREATE INDEX idx_ledger_events_aggregate ON ledger_events(aggregate_type, aggregate_id, aggregate_version)",
    "CREATE INDEX idx_ledger_events_recorded ON ledger_events(recorded_at, ledger_seq)",
    "CREATE INDEX idx_ledger_events_visibility ON ledger_events(security_scope, trust_scope, ledger_seq)",
    "CREATE INDEX idx_authorization_decisions_context ON authorization_decisions(authentication_context_id, decided_at)",
    """CREATE TRIGGER immutable_authority_migrations_update
        BEFORE UPDATE ON authority_migrations BEGIN
        SELECT RAISE(ABORT,'immutable migration history'); END""",
    """CREATE TRIGGER immutable_authority_migrations_delete
        BEFORE DELETE ON authority_migrations BEGIN
        SELECT RAISE(ABORT,'immutable migration history'); END""",
    """CREATE TRIGGER immutable_payload_schema_contracts_update
        BEFORE UPDATE ON payload_schema_contracts BEGIN
        SELECT RAISE(ABORT,'immutable payload schema contract'); END""",
    """CREATE TRIGGER immutable_payload_schema_contracts_delete
        BEFORE DELETE ON payload_schema_contracts BEGIN
        SELECT RAISE(ABORT,'immutable payload schema contract'); END""",
    """CREATE TRIGGER immutable_command_definitions_update
        BEFORE UPDATE ON command_definitions BEGIN
        SELECT RAISE(ABORT,'immutable command definition'); END""",
    """CREATE TRIGGER immutable_command_definitions_delete
        BEFORE DELETE ON command_definitions BEGIN
        SELECT RAISE(ABORT,'immutable command definition'); END""",
    """CREATE TRIGGER immutable_authentication_contexts_update
        BEFORE UPDATE ON authentication_contexts BEGIN
        SELECT RAISE(ABORT,'immutable authentication context'); END""",
    """CREATE TRIGGER immutable_authentication_contexts_delete
        BEFORE DELETE ON authentication_contexts BEGIN
        SELECT RAISE(ABORT,'immutable authentication context'); END""",
    """CREATE TRIGGER immutable_authorization_requests_update
        BEFORE UPDATE ON authorization_requests BEGIN
        SELECT RAISE(ABORT,'immutable authorization request'); END""",
    """CREATE TRIGGER immutable_authorization_requests_delete
        BEFORE DELETE ON authorization_requests BEGIN
        SELECT RAISE(ABORT,'immutable authorization request'); END""",
    """CREATE TRIGGER immutable_authorization_decisions_update
        BEFORE UPDATE ON authorization_decisions BEGIN
        SELECT RAISE(ABORT,'immutable authorization decision'); END""",
    """CREATE TRIGGER immutable_authorization_decisions_delete
        BEFORE DELETE ON authorization_decisions BEGIN
        SELECT RAISE(ABORT,'immutable authorization decision'); END""",
    """CREATE TRIGGER immutable_authority_payloads_update
        BEFORE UPDATE ON authority_payloads BEGIN
        SELECT RAISE(ABORT,'immutable authority payload'); END""",
    """CREATE TRIGGER immutable_authority_payloads_delete
        BEFORE DELETE ON authority_payloads BEGIN
        SELECT RAISE(ABORT,'immutable authority payload'); END""",
    """CREATE TRIGGER immutable_authority_commands_update
        BEFORE UPDATE ON authority_commands BEGIN
        SELECT RAISE(ABORT,'immutable authority command'); END""",
    """CREATE TRIGGER immutable_authority_commands_delete
        BEFORE DELETE ON authority_commands BEGIN
        SELECT RAISE(ABORT,'immutable authority command'); END""",
    """CREATE TRIGGER authority_aggregates_insert_guard
        BEFORE INSERT ON authority_aggregates
        WHEN NEW.current_version != 1 BEGIN
        SELECT RAISE(ABORT,'aggregate heads begin at version one'); END""",
    """CREATE TRIGGER authority_aggregates_update_guard
        BEFORE UPDATE ON authority_aggregates
        WHEN NEW.aggregate_type != OLD.aggregate_type
          OR NEW.aggregate_id != OLD.aggregate_id
          OR NEW.current_version != OLD.current_version + 1
          OR NEW.created_at != OLD.created_at
        BEGIN SELECT RAISE(ABORT,'invalid aggregate-head update'); END""",
    """CREATE TRIGGER authority_aggregates_delete_guard
        BEFORE DELETE ON authority_aggregates BEGIN
        SELECT RAISE(ABORT,'aggregate heads are retained'); END""",
    """CREATE TRIGGER immutable_aggregate_versions_update
        BEFORE UPDATE ON authority_aggregate_versions BEGIN
        SELECT RAISE(ABORT,'immutable aggregate version'); END""",
    """CREATE TRIGGER immutable_aggregate_versions_delete
        BEFORE DELETE ON authority_aggregate_versions BEGIN
        SELECT RAISE(ABORT,'immutable aggregate version'); END""",
    """CREATE TRIGGER immutable_authority_audit_events_update
        BEFORE UPDATE ON authority_audit_events BEGIN
        SELECT RAISE(ABORT,'immutable audit event'); END""",
    """CREATE TRIGGER immutable_authority_audit_events_delete
        BEFORE DELETE ON authority_audit_events BEGIN
        SELECT RAISE(ABORT,'immutable audit event'); END""",
    """CREATE TRIGGER immutable_ledger_events_update
        BEFORE UPDATE ON ledger_events BEGIN
        SELECT RAISE(ABORT,'immutable ledger event'); END""",
    """CREATE TRIGGER immutable_ledger_events_delete
        BEFORE DELETE ON ledger_events BEGIN
        SELECT RAISE(ABORT,'immutable ledger event'); END""",
    """CREATE TRIGGER ledger_event_payload_guard
        BEFORE INSERT ON ledger_events
        WHEN NOT EXISTS(
            SELECT 1 FROM authority_payloads p
            WHERE p.payload_id = NEW.payload_id
              AND p.mode = NEW.payload_mode
              AND p.schema_version = NEW.payload_schema_version
              AND p.schema_contract_version =
                    NEW.payload_schema_contract_version
              AND p.schema_contract_digest =
                    NEW.payload_schema_contract_digest
              AND p.canonicalizer_implementation_version =
                    NEW.payload_canonicalizer_version
              AND p.payload_digest = NEW.payload_digest
              AND p.object_admission_id IS NEW.object_admission_id
        )
        BEGIN SELECT RAISE(ABORT,'event payload envelope mismatch'); END""",
    """CREATE TRIGGER ledger_event_command_guard
        BEFORE INSERT ON ledger_events
        WHEN NOT EXISTS(
            SELECT 1 FROM authority_commands c
            WHERE c.command_id = NEW.command_id
              AND c.producer_version = NEW.producer_version
              AND c.command_definition_version =
                    NEW.command_definition_version
              AND c.command_definition_digest =
                    NEW.command_definition_digest
              AND c.payload_id = NEW.payload_id
              AND c.authentication_context_id =
                    NEW.authentication_context_id
              AND c.authorization_request_digest =
                    NEW.authorization_request_digest
              AND c.authorization_decision_id =
                    NEW.authorization_decision_id
        )
        BEGIN SELECT RAISE(ABORT,'event command envelope mismatch'); END""",
    """CREATE TRIGGER ledger_event_command_causation_guard
        BEFORE INSERT ON ledger_events
        WHEN NEW.causation_kind='COMMAND'
         AND NOT EXISTS(
            SELECT 1 FROM authority_commands
            WHERE command_id=NEW.causation_identifier
         )
        BEGIN SELECT RAISE(ABORT,'unknown command causation'); END""",
    """CREATE TRIGGER ledger_event_event_causation_guard
        BEFORE INSERT ON ledger_events
        WHEN NEW.causation_kind='EVENT'
         AND NOT EXISTS(
            SELECT 1 FROM ledger_events
            WHERE event_id=NEW.causation_identifier
         )
        BEGIN SELECT RAISE(ABORT,'unknown event causation'); END""",
)

MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": BASE_SCHEMA_VERSION,
        "name": MIGRATION_NAME,
        "statements": list(MIGRATION_STATEMENTS),
    }
)
MIGRATION = MigrationRecord(
    version=BASE_SCHEMA_VERSION,
    name=MIGRATION_NAME,
    checksum=MIGRATION_CHECKSUM,
)


def _normalize(sql: str | None) -> str:
    return " ".join((sql or "").split())


def schema_fingerprint(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    return digest_canonical(
        [
            [str(row[0]), str(row[1]), str(row[2]), _normalize(row[3])]
            for row in rows
        ]
    )


def apply_migration(
    conn: sqlite3.Connection,
    *,
    applied_at: str,
    statements: Iterable[str] = MIGRATION_STATEMENTS,
) -> None:
    try:
        conn.execute("BEGIN EXCLUSIVE")
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO authority_migrations(version,name,checksum,applied_at) "
            "VALUES(?,?,?,?)",
            (BASE_SCHEMA_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, applied_at),
        )
        conn.execute(f"PRAGMA user_version={BASE_SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def apply_pending_migrations(
    conn: sqlite3.Connection, *, applied_at: str
) -> None:
    """Apply every pending checked migration in one exclusive transaction.

    Fresh schema creation is all-or-nothing across the A2a and A2b migration
    records.  Upgrading an A2a schema applies only v2.
    """

    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"database schema {current} is newer than supported {SCHEMA_VERSION}"
        )
    if current == SCHEMA_VERSION:
        return
    try:
        conn.execute("BEGIN EXCLUSIVE")
        if current == 0:
            for statement in MIGRATION_STATEMENTS:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO authority_migrations(version,name,checksum,applied_at) "
                "VALUES(?,?,?,?)",
                (BASE_SCHEMA_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, applied_at),
            )
            current = BASE_SCHEMA_VERSION
        if current == BASE_SCHEMA_VERSION:
            for statement in OBJECT_MIGRATION_STATEMENTS:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO authority_migrations(version,name,checksum,applied_at) "
                "VALUES(?,?,?,?)",
                (
                    OBJECT_SCHEMA_VERSION,
                    OBJECT_MIGRATION_NAME,
                    OBJECT_MIGRATION_CHECKSUM,
                    applied_at,
                ),
            )
            current = OBJECT_SCHEMA_VERSION
        if current == OBJECT_SCHEMA_VERSION:
            for statement in PROJECTION_MIGRATION_STATEMENTS:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO authority_migrations(version,name,checksum,applied_at) "
                "VALUES(?,?,?,?)",
                (
                    PROJECTION_SCHEMA_VERSION,
                    PROJECTION_MIGRATION_NAME,
                    PROJECTION_MIGRATION_CHECKSUM,
                    applied_at,
                ),
            )
            current = PROJECTION_SCHEMA_VERSION
        if current == PROJECTION_SCHEMA_VERSION:
            for statement in PROJECTION_PROMOTION_MIGRATION_STATEMENTS:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO authority_migrations(version,name,checksum,applied_at) "
                "VALUES(?,?,?,?)",
                (
                    PROJECTION_PROMOTION_SCHEMA_VERSION,
                    PROJECTION_PROMOTION_MIGRATION_NAME,
                    PROJECTION_PROMOTION_MIGRATION_CHECKSUM,
                    applied_at,
                ),
            )
            current = PROJECTION_PROMOTION_SCHEMA_VERSION
        conn.execute(f"PRAGMA user_version={current}")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


MIGRATIONS: tuple[MigrationRecord | object, ...] = (
    MIGRATION,
    OBJECT_MIGRATION,
    PROJECTION_MIGRATION,
    PROJECTION_PROMOTION_MIGRATION,
)

def _expected_fingerprint() -> str:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        apply_pending_migrations(
            conn, applied_at="1970-01-01T00:00:00.000000Z"
        )
        return schema_fingerprint(conn)
    finally:
        conn.close()


EXPECTED_SCHEMA_FINGERPRINT = _expected_fingerprint()
EXPECTED_MIGRATION_HISTORY: tuple[tuple[int, str, str], ...] = (
    (BASE_SCHEMA_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    (OBJECT_SCHEMA_VERSION, OBJECT_MIGRATION_NAME, OBJECT_MIGRATION_CHECKSUM),
    (
        PROJECTION_SCHEMA_VERSION,
        PROJECTION_MIGRATION_NAME,
        PROJECTION_MIGRATION_CHECKSUM,
    ),
    (
        PROJECTION_PROMOTION_SCHEMA_VERSION,
        PROJECTION_PROMOTION_MIGRATION_NAME,
        PROJECTION_PROMOTION_MIGRATION_CHECKSUM,
    ),
)
