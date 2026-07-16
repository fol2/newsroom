from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Iterable

from .canonical import digest_canonical
from .migrations import (
    EXPECTED_MIGRATION_HISTORY as V1_HISTORY,
    MIGRATION_STATEMENTS as V1_STATEMENTS,
    apply_migration as apply_v1_migration,
    schema_fingerprint,
)

OBJECT_SCHEMA_VERSION = 2
OBJECT_MIGRATION_NAME = "governed_object_lifecycle_v2"

OBJECT_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE rights_decisions(
        rights_decision_id TEXT PRIMARY KEY,
        authentication_context_id TEXT NOT NULL
            REFERENCES authentication_contexts(authentication_context_id),
        authorization_decision_id TEXT NOT NULL
            REFERENCES authorization_decisions(authorization_decision_id),
        request_digest TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),
        reason_code TEXT NOT NULL,
        blob_digest TEXT NOT NULL,
        object_class TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        security_scope TEXT NOT NULL,
        retention_scope TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_until TEXT,
        decided_at TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE blob_records(
        blob_digest TEXT PRIMARY KEY,
        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
        state TEXT NOT NULL
            CHECK(state IN ('ACTIVE','DELETION_PENDING','DELETED','FAILED')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    ) STRICT""",
    """CREATE TABLE object_admission_operations(
        operation_id TEXT PRIMARY KEY,
        idempotency_namespace TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        stable_semantic_request_digest TEXT NOT NULL,
        admission_id TEXT NOT NULL UNIQUE,
        blob_digest TEXT NOT NULL REFERENCES blob_records(blob_digest),
        result_digest TEXT NOT NULL,
        result_bytes BLOB NOT NULL,
        command_id TEXT NOT NULL UNIQUE REFERENCES authority_commands(command_id),
        created_at TEXT NOT NULL,
        UNIQUE(idempotency_namespace, idempotency_key),
        CHECK(length(result_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE object_admissions(
        admission_id TEXT PRIMARY KEY,
        blob_digest TEXT NOT NULL REFERENCES blob_records(blob_digest),
        admission_type TEXT NOT NULL,
        definition_version TEXT NOT NULL,
        definition_digest TEXT NOT NULL,
        object_class TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        security_scope TEXT NOT NULL,
        retention_scope TEXT NOT NULL,
        required_read_scope TEXT NOT NULL,
        required_manage_scope TEXT NOT NULL,
        rights_decision_id TEXT NOT NULL
            REFERENCES rights_decisions(rights_decision_id),
        rights_policy_version TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_until TEXT,
        state TEXT NOT NULL CHECK(state IN ('ACTIVE','REVOKED','DELETED')),
        aggregate_version INTEGER NOT NULL CHECK(aggregate_version > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE object_admission_revocations(
        revocation_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES object_admissions(admission_id),
        authentication_context_id TEXT NOT NULL
            REFERENCES authentication_contexts(authentication_context_id),
        authorization_decision_id TEXT NOT NULL
            REFERENCES authorization_decisions(authorization_decision_id),
        command_id TEXT NOT NULL UNIQUE REFERENCES authority_commands(command_id),
        reason_code TEXT NOT NULL,
        revoked_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE blob_deletion_tombstones(
        deletion_id TEXT PRIMARY KEY,
        blob_digest TEXT NOT NULL REFERENCES blob_records(blob_digest),
        authentication_context_id TEXT NOT NULL
            REFERENCES authentication_contexts(authentication_context_id),
        authorization_decision_id TEXT NOT NULL
            REFERENCES authorization_decisions(authorization_decision_id),
        request_command_id TEXT NOT NULL UNIQUE REFERENCES authority_commands(command_id),
        completion_command_id TEXT UNIQUE REFERENCES authority_commands(command_id),
        reason_code TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        completed_at TEXT,
        CHECK((completion_command_id IS NULL AND completed_at IS NULL)
           OR (completion_command_id IS NOT NULL AND completed_at IS NOT NULL))
    ) STRICT""",
    """CREATE TABLE object_references(
        admission_id TEXT NOT NULL REFERENCES object_admissions(admission_id),
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        aggregate_version INTEGER NOT NULL,
        command_id TEXT NOT NULL REFERENCES authority_commands(command_id),
        created_at TEXT NOT NULL,
        PRIMARY KEY(admission_id, aggregate_type, aggregate_id, aggregate_version),
        FOREIGN KEY(aggregate_type, aggregate_id, aggregate_version)
            REFERENCES authority_aggregate_versions(
                aggregate_type, aggregate_id, aggregate_version
            )
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE recovery_pins(
        pin_id TEXT PRIMARY KEY,
        blob_digest TEXT NOT NULL REFERENCES blob_records(blob_digest),
        authentication_context_id TEXT NOT NULL
            REFERENCES authentication_contexts(authentication_context_id),
        authorization_decision_id TEXT NOT NULL
            REFERENCES authorization_decisions(authorization_decision_id),
        reason_code TEXT NOT NULL,
        created_at TEXT NOT NULL,
        released_at TEXT
    ) STRICT""",
    """CREATE TABLE object_access_decisions(
        access_decision_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES object_admissions(admission_id),
        authentication_context_id TEXT NOT NULL
            REFERENCES authentication_contexts(authentication_context_id),
        authorization_decision_id TEXT NOT NULL
            REFERENCES authorization_decisions(authorization_decision_id),
        purpose TEXT NOT NULL,
        allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),
        reason_code TEXT NOT NULL,
        decided_at TEXT NOT NULL
    ) STRICT""",
    "CREATE INDEX idx_object_admissions_blob_state ON object_admissions(blob_digest, state)",
    "CREATE INDEX idx_recovery_pins_blob ON recovery_pins(blob_digest, released_at)",
    "CREATE INDEX idx_tombstones_blob ON blob_deletion_tombstones(blob_digest, completed_at)",
    "CREATE INDEX idx_object_references_admission ON object_references(admission_id)",
    """CREATE TRIGGER authority_payload_object_admission_guard
        BEFORE INSERT ON authority_payloads
        WHEN NEW.mode='OBJECT_ADMISSION' AND NOT EXISTS(
            SELECT 1 FROM object_admissions a
            WHERE a.admission_id=NEW.object_admission_id AND a.state='ACTIVE'
        )
        BEGIN SELECT RAISE(ABORT,'object admission is not active'); END""",
    """CREATE TRIGGER immutable_rights_decisions_update BEFORE UPDATE ON rights_decisions BEGIN SELECT RAISE(ABORT,'immutable rights decision'); END""",
    """CREATE TRIGGER immutable_rights_decisions_delete BEFORE DELETE ON rights_decisions BEGIN SELECT RAISE(ABORT,'immutable rights decision'); END""",
    """CREATE TRIGGER immutable_object_admission_operations_update BEFORE UPDATE ON object_admission_operations BEGIN SELECT RAISE(ABORT,'immutable admission operation'); END""",
    """CREATE TRIGGER immutable_object_admission_operations_delete BEFORE DELETE ON object_admission_operations BEGIN SELECT RAISE(ABORT,'immutable admission operation'); END""",
    """CREATE TRIGGER object_admissions_update_guard
        BEFORE UPDATE ON object_admissions
        WHEN NEW.admission_id != OLD.admission_id
          OR NEW.blob_digest != OLD.blob_digest
          OR NEW.admission_type != OLD.admission_type
          OR NEW.definition_version != OLD.definition_version
          OR NEW.definition_digest != OLD.definition_digest
          OR NEW.object_class != OLD.object_class
          OR NEW.allowed_use != OLD.allowed_use
          OR NEW.security_scope != OLD.security_scope
          OR NEW.retention_scope != OLD.retention_scope
          OR NEW.required_read_scope != OLD.required_read_scope
          OR NEW.required_manage_scope != OLD.required_manage_scope
          OR NEW.rights_decision_id != OLD.rights_decision_id
          OR NEW.rights_policy_version != OLD.rights_policy_version
          OR NEW.valid_from != OLD.valid_from
          OR COALESCE(NEW.valid_until,'') != COALESCE(OLD.valid_until,'')
          OR NEW.created_at != OLD.created_at
          OR NEW.aggregate_version != OLD.aggregate_version + 1
          OR NOT((OLD.state='ACTIVE' AND NEW.state IN ('REVOKED','DELETED'))
              OR (OLD.state='REVOKED' AND NEW.state='DELETED'))
        BEGIN SELECT RAISE(ABORT,'invalid object admission update'); END""",
    """CREATE TRIGGER object_admissions_delete_guard BEFORE DELETE ON object_admissions BEGIN SELECT RAISE(ABORT,'object admissions are retained'); END""",
    """CREATE TRIGGER blob_records_update_guard
        BEFORE UPDATE ON blob_records
        WHEN NEW.blob_digest != OLD.blob_digest
          OR NEW.size_bytes != OLD.size_bytes
          OR NEW.created_at != OLD.created_at
          OR NOT((OLD.state='ACTIVE' AND NEW.state IN ('DELETION_PENDING','FAILED'))
              OR (OLD.state='DELETION_PENDING' AND NEW.state IN ('DELETED','FAILED')))
        BEGIN SELECT RAISE(ABORT,'invalid blob state update'); END""",
    """CREATE TRIGGER blob_records_delete_guard BEFORE DELETE ON blob_records BEGIN SELECT RAISE(ABORT,'blob identities are retained'); END""",
    """CREATE TRIGGER immutable_object_admission_revocations_update BEFORE UPDATE ON object_admission_revocations BEGIN SELECT RAISE(ABORT,'immutable admission revocation'); END""",
    """CREATE TRIGGER immutable_object_admission_revocations_delete BEFORE DELETE ON object_admission_revocations BEGIN SELECT RAISE(ABORT,'immutable admission revocation'); END""",
    """CREATE TRIGGER deletion_tombstones_update_guard
        BEFORE UPDATE ON blob_deletion_tombstones
        WHEN NEW.deletion_id != OLD.deletion_id
          OR NEW.blob_digest != OLD.blob_digest
          OR NEW.authentication_context_id != OLD.authentication_context_id
          OR NEW.authorization_decision_id != OLD.authorization_decision_id
          OR NEW.request_command_id != OLD.request_command_id
          OR NEW.reason_code != OLD.reason_code
          OR NEW.requested_at != OLD.requested_at
          OR OLD.completion_command_id IS NOT NULL
          OR NEW.completion_command_id IS NULL
          OR NEW.completed_at IS NULL
        BEGIN SELECT RAISE(ABORT,'invalid deletion tombstone update'); END""",
    """CREATE TRIGGER deletion_tombstones_delete_guard BEFORE DELETE ON blob_deletion_tombstones BEGIN SELECT RAISE(ABORT,'deletion tombstones are retained'); END""",
    """CREATE TRIGGER immutable_object_references_update BEFORE UPDATE ON object_references BEGIN SELECT RAISE(ABORT,'immutable object reference'); END""",
    """CREATE TRIGGER immutable_object_references_delete BEFORE DELETE ON object_references BEGIN SELECT RAISE(ABORT,'object references are retained'); END""",
    """CREATE TRIGGER recovery_pins_update_guard
        BEFORE UPDATE ON recovery_pins
        WHEN NEW.pin_id != OLD.pin_id
          OR NEW.blob_digest != OLD.blob_digest
          OR NEW.authentication_context_id != OLD.authentication_context_id
          OR NEW.authorization_decision_id != OLD.authorization_decision_id
          OR NEW.reason_code != OLD.reason_code
          OR NEW.created_at != OLD.created_at
          OR OLD.released_at IS NOT NULL
          OR NEW.released_at IS NULL
        BEGIN SELECT RAISE(ABORT,'invalid recovery pin update'); END""",
    """CREATE TRIGGER recovery_pins_delete_guard BEFORE DELETE ON recovery_pins BEGIN SELECT RAISE(ABORT,'recovery pins are retained'); END""",
    """CREATE TRIGGER immutable_object_access_decisions_update BEFORE UPDATE ON object_access_decisions BEGIN SELECT RAISE(ABORT,'immutable object access decision'); END""",
    """CREATE TRIGGER immutable_object_access_decisions_delete BEFORE DELETE ON object_access_decisions BEGIN SELECT RAISE(ABORT,'immutable object access decision'); END""",
    """CREATE TRIGGER immutable_authority_migrations_update BEFORE UPDATE ON authority_migrations BEGIN SELECT RAISE(ABORT,'immutable migration history'); END""",
    """CREATE TRIGGER immutable_authority_migrations_delete BEFORE DELETE ON authority_migrations BEGIN SELECT RAISE(ABORT,'immutable migration history'); END""",
)

OBJECT_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": OBJECT_SCHEMA_VERSION,
        "name": OBJECT_MIGRATION_NAME,
        "statements": list(OBJECT_MIGRATION_STATEMENTS),
    }
)


def apply_object_migration(
    conn: sqlite3.Connection,
    *,
    applied_at: str,
    statements: Iterable[str] = OBJECT_MIGRATION_STATEMENTS,
) -> None:
    try:
        conn.execute("BEGIN EXCLUSIVE")
        for statement in statements:
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
        conn.execute(f"PRAGMA user_version={OBJECT_SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _expected_object_fingerprint() -> str:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        apply_v1_migration(conn, applied_at="1970-01-01T00:00:00.000000Z")
        apply_object_migration(conn, applied_at="1970-01-01T00:00:01.000000Z")
        return schema_fingerprint(conn)
    finally:
        conn.close()


EXPECTED_OBJECT_SCHEMA_FINGERPRINT = _expected_object_fingerprint()
EXPECTED_OBJECT_MIGRATION_HISTORY: tuple[tuple[int, str, str], ...] = (
    *V1_HISTORY,
    (OBJECT_SCHEMA_VERSION, OBJECT_MIGRATION_NAME, OBJECT_MIGRATION_CHECKSUM),
)
