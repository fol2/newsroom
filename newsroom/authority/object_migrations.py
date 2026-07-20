from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


OBJECT_SCHEMA_VERSION = 2
OBJECT_MIGRATION_NAME = "governed_object_authority_v2"


@dataclass(frozen=True, slots=True)
class ObjectMigrationRecord:
    version: int
    name: str
    checksum: str


OBJECT_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE rights_policy_contracts(
        contract_digest TEXT PRIMARY KEY,
        policy_key TEXT NOT NULL,
        contract_version TEXT NOT NULL,
        implementation_version TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(policy_key, contract_version),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE hydration_policy_contracts(
        contract_digest TEXT PRIMARY KEY,
        policy_id TEXT NOT NULL,
        contract_version TEXT NOT NULL,
        implementation_version TEXT NOT NULL,
        purpose TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(policy_id, contract_version),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE object_admission_definitions(
        definition_digest TEXT PRIMARY KEY,
        admission_type TEXT NOT NULL,
        definition_version TEXT NOT NULL,
        object_class TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        security_scope TEXT NOT NULL,
        retention_scope TEXT NOT NULL,
        required_write_scope TEXT NOT NULL,
        required_read_scope TEXT NOT NULL,
        required_manage_scope TEXT NOT NULL,
        rights_policy_contract_digest TEXT NOT NULL
            REFERENCES rights_policy_contracts(contract_digest),
        hydration_policy_contract_digests BLOB NOT NULL,
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(admission_type, definition_version),
        CHECK(length(canonical_bytes) > 0),
        CHECK(length(hydration_policy_contract_digests) > 0)
    ) STRICT""",
    """CREATE TABLE object_admission_idempotency(
        idempotency_namespace TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        stable_semantic_request_digest TEXT NOT NULL,
        admission_type TEXT NOT NULL,
        admission_definition_digest TEXT NOT NULL
            REFERENCES object_admission_definitions(definition_digest),
        rights_policy_contract_digest TEXT NOT NULL
            REFERENCES rights_policy_contracts(contract_digest),
        created_at TEXT NOT NULL,
        PRIMARY KEY(idempotency_namespace, idempotency_key)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE object_admission_preflights(
        preflight_id TEXT PRIMARY KEY,
        idempotency_namespace TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        stable_semantic_request_digest TEXT NOT NULL,
        admission_type TEXT NOT NULL,
        admission_definition_digest TEXT NOT NULL
            REFERENCES object_admission_definitions(definition_digest),
        rights_policy_contract_digest TEXT NOT NULL
            REFERENCES rights_policy_contracts(contract_digest),
        authentication_context_id TEXT NOT NULL,
        authorization_request_digest TEXT NOT NULL,
        authorization_decision_id TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        FOREIGN KEY(idempotency_namespace, idempotency_key)
            REFERENCES object_admission_idempotency(
                idempotency_namespace, idempotency_key
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
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE object_staging_records(
        stage_id TEXT PRIMARY KEY,
        preflight_id TEXT NOT NULL
            REFERENCES object_admission_preflights(preflight_id),
        staged_name TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL
            CHECK(state IN ('STAGED','INSTALLED','COMMITTED','FAILED','CLEANED')),
        blob_digest TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        failure_code TEXT
    ) STRICT""",
    """CREATE TABLE blob_identities(
        blob_digest TEXT PRIMARY KEY,
        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
        created_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE blob_lifecycle_versions(
        blob_digest TEXT NOT NULL
            REFERENCES blob_identities(blob_digest),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        state TEXT NOT NULL CHECK(state IN(
            'STAGING','INSTALLED','ACTIVE','DELETION_PENDING','DELETED','FAILED'
        )),
        integrity_state TEXT NOT NULL CHECK(integrity_state IN(
            'UNVERIFIED','VERIFIED','MISSING','CORRUPT'
        )),
        operation_id TEXT NOT NULL,
        event_id TEXT REFERENCES ledger_events(event_id),
        recorded_at TEXT NOT NULL,
        detail_digest TEXT NOT NULL,
        PRIMARY KEY(blob_digest, lifecycle_version),
        CHECK(
            state IN ('STAGING','INSTALLED','FAILED')
            OR event_id IS NOT NULL
        )
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE blob_lifecycle_heads(
        blob_digest TEXT PRIMARY KEY
            REFERENCES blob_identities(blob_digest),
        current_version INTEGER NOT NULL CHECK(current_version > 0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(blob_digest, current_version)
            REFERENCES blob_lifecycle_versions(
                blob_digest, lifecycle_version
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    """CREATE TABLE object_rights_decisions(
        rights_decision_id TEXT PRIMARY KEY,
        authentication_context_id TEXT NOT NULL,
        authorization_request_digest TEXT NOT NULL,
        authorization_decision_id TEXT NOT NULL,
        rights_request_digest TEXT NOT NULL,
        policy_contract_digest TEXT NOT NULL
            REFERENCES rights_policy_contracts(contract_digest),
        admission_definition_digest TEXT NOT NULL
            REFERENCES object_admission_definitions(definition_digest),
        blob_digest TEXT NOT NULL
            REFERENCES blob_identities(blob_digest),
        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
        object_class TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        security_scope TEXT NOT NULL,
        retention_scope TEXT NOT NULL,
        allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),
        reason_code TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_until TEXT,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
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
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE object_admissions(
        admission_id TEXT PRIMARY KEY,
        admission_type TEXT NOT NULL,
        definition_version TEXT NOT NULL,
        definition_digest TEXT NOT NULL
            REFERENCES object_admission_definitions(definition_digest),
        rights_decision_id TEXT NOT NULL
            REFERENCES object_rights_decisions(rights_decision_id),
        blob_digest TEXT NOT NULL
            REFERENCES blob_identities(blob_digest),
        object_class TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        security_scope TEXT NOT NULL,
        retention_scope TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_until TEXT,
        created_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE object_admission_versions(
        admission_id TEXT NOT NULL
            REFERENCES object_admissions(admission_id),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        state TEXT NOT NULL CHECK(state IN('PENDING','ACTIVE','REVOKED','FAILED')),
        operation_id TEXT NOT NULL,
        event_id TEXT REFERENCES ledger_events(event_id),
        reason_code TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        detail_digest TEXT NOT NULL,
        PRIMARY KEY(admission_id, lifecycle_version),
        CHECK(state IN ('PENDING','FAILED') OR event_id IS NOT NULL)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE object_admission_heads(
        admission_id TEXT PRIMARY KEY
            REFERENCES object_admissions(admission_id),
        current_version INTEGER NOT NULL CHECK(current_version > 0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(admission_id, current_version)
            REFERENCES object_admission_versions(
                admission_id, lifecycle_version
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    """CREATE TABLE object_access_decisions(
        access_decision_id TEXT PRIMARY KEY,
        hydration_policy_contract_digest TEXT NOT NULL
            REFERENCES hydration_policy_contracts(contract_digest),
        authentication_context_id TEXT NOT NULL,
        authorization_request_digest TEXT NOT NULL,
        authorization_decision_id TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        authority_domain TEXT NOT NULL,
        purpose TEXT NOT NULL,
        admission_id TEXT NOT NULL
            REFERENCES object_admissions(admission_id),
        object_class TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        security_scope TEXT NOT NULL,
        retention_scope TEXT NOT NULL,
        byte_offset INTEGER NOT NULL CHECK(byte_offset >= 0),
        allowed_bytes INTEGER NOT NULL CHECK(allowed_bytes >= 0),
        state_cutoff_digest TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
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
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE object_deletions(
        deletion_id TEXT PRIMARY KEY,
        blob_digest TEXT NOT NULL
            REFERENCES blob_identities(blob_digest),
        reason_code TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE object_deletion_versions(
        deletion_id TEXT NOT NULL
            REFERENCES object_deletions(deletion_id),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        state TEXT NOT NULL CHECK(state IN(
            'REQUESTED','TOMBSTONED','PHYSICALLY_REMOVED','FAILED'
        )),
        operation_id TEXT NOT NULL,
        event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        error_code TEXT,
        recorded_at TEXT NOT NULL,
        detail_digest TEXT NOT NULL,
        PRIMARY KEY(deletion_id, lifecycle_version)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE object_deletion_heads(
        deletion_id TEXT PRIMARY KEY
            REFERENCES object_deletions(deletion_id),
        current_version INTEGER NOT NULL CHECK(current_version > 0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(deletion_id, current_version)
            REFERENCES object_deletion_versions(
                deletion_id, lifecycle_version
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    """CREATE TABLE object_recovery_pins(
        pin_id TEXT PRIMARY KEY,
        blob_digest TEXT NOT NULL
            REFERENCES blob_identities(blob_digest),
        reason_code TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE object_recovery_pin_versions(
        pin_id TEXT NOT NULL
            REFERENCES object_recovery_pins(pin_id),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        state TEXT NOT NULL CHECK(state IN('ACTIVE','RELEASED')),
        operation_id TEXT NOT NULL,
        event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        recorded_at TEXT NOT NULL,
        detail_digest TEXT NOT NULL,
        PRIMARY KEY(pin_id, lifecycle_version)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE object_recovery_pin_heads(
        pin_id TEXT PRIMARY KEY
            REFERENCES object_recovery_pins(pin_id),
        current_version INTEGER NOT NULL CHECK(current_version > 0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(pin_id, current_version)
            REFERENCES object_recovery_pin_versions(
                pin_id, lifecycle_version
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    """CREATE TABLE object_lifecycle_operations(
        operation_id TEXT PRIMARY KEY,
        operation_type TEXT NOT NULL,
        idempotency_namespace TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        stable_semantic_request_digest TEXT NOT NULL,
        authentication_context_id TEXT NOT NULL,
        authorization_request_digest TEXT NOT NULL,
        authorization_decision_id TEXT NOT NULL,
        command_id TEXT NOT NULL UNIQUE
            REFERENCES authority_commands(command_id),
        event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        result_bytes BLOB NOT NULL,
        result_digest TEXT NOT NULL,
        committed_at TEXT NOT NULL,
        UNIQUE(idempotency_namespace, idempotency_key),
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
    "CREATE INDEX idx_object_admissions_blob ON object_admissions(blob_digest)",
    "CREATE INDEX idx_object_access_admission ON object_access_decisions(admission_id, decided_at)",
    "CREATE INDEX idx_object_deletions_blob ON object_deletions(blob_digest)",
    "CREATE INDEX idx_object_staging_state ON object_staging_records(state, updated_at)",
    "CREATE INDEX idx_object_preflights_idempotency ON object_admission_preflights(idempotency_namespace, idempotency_key, checked_at)",
    "CREATE INDEX idx_object_operations_type ON object_lifecycle_operations(operation_type, committed_at)",
    """CREATE TRIGGER immutable_rights_policy_contracts_update
        BEFORE UPDATE ON rights_policy_contracts BEGIN
        SELECT RAISE(ABORT,'immutable rights policy contract'); END""",
    """CREATE TRIGGER immutable_rights_policy_contracts_delete
        BEFORE DELETE ON rights_policy_contracts BEGIN
        SELECT RAISE(ABORT,'immutable rights policy contract'); END""",
    """CREATE TRIGGER immutable_hydration_policy_contracts_update
        BEFORE UPDATE ON hydration_policy_contracts BEGIN
        SELECT RAISE(ABORT,'immutable hydration policy contract'); END""",
    """CREATE TRIGGER immutable_hydration_policy_contracts_delete
        BEFORE DELETE ON hydration_policy_contracts BEGIN
        SELECT RAISE(ABORT,'immutable hydration policy contract'); END""",
    """CREATE TRIGGER immutable_object_admission_definitions_update
        BEFORE UPDATE ON object_admission_definitions BEGIN
        SELECT RAISE(ABORT,'immutable object admission definition'); END""",
    """CREATE TRIGGER immutable_object_admission_definitions_delete
        BEFORE DELETE ON object_admission_definitions BEGIN
        SELECT RAISE(ABORT,'immutable object admission definition'); END""",
    """CREATE TRIGGER immutable_object_admission_idempotency_update
        BEFORE UPDATE ON object_admission_idempotency BEGIN
        SELECT RAISE(ABORT,'immutable object admission idempotency'); END""",
    """CREATE TRIGGER immutable_object_admission_idempotency_delete
        BEFORE DELETE ON object_admission_idempotency BEGIN
        SELECT RAISE(ABORT,'object admission idempotency is retained'); END""",
    """CREATE TRIGGER immutable_object_preflights_update
        BEFORE UPDATE ON object_admission_preflights BEGIN
        SELECT RAISE(ABORT,'immutable object admission preflight'); END""",
    """CREATE TRIGGER immutable_object_preflights_delete
        BEFORE DELETE ON object_admission_preflights BEGIN
        SELECT RAISE(ABORT,'immutable object admission preflight'); END""",
    """CREATE TRIGGER object_staging_transition_guard
        BEFORE UPDATE ON object_staging_records
        WHEN NEW.stage_id != OLD.stage_id
          OR NEW.preflight_id != OLD.preflight_id
          OR NEW.staged_name != OLD.staged_name
          OR NEW.blob_digest != OLD.blob_digest
          OR NEW.size_bytes != OLD.size_bytes
          OR NEW.created_at != OLD.created_at
          OR NOT (
              (OLD.state='STAGED' AND NEW.state IN('INSTALLED','FAILED','CLEANED'))
              OR (OLD.state='INSTALLED' AND NEW.state IN('COMMITTED','FAILED','CLEANED'))
              OR (OLD.state='FAILED' AND NEW.state='CLEANED')
              OR (OLD.state=NEW.state)
          )
        BEGIN SELECT RAISE(ABORT,'invalid object staging transition'); END""",
    """CREATE TRIGGER object_staging_delete_guard
        BEFORE DELETE ON object_staging_records BEGIN
        SELECT RAISE(ABORT,'object staging history is retained'); END""",
    """CREATE TRIGGER immutable_blob_identities_update
        BEFORE UPDATE ON blob_identities BEGIN
        SELECT RAISE(ABORT,'immutable blob identity'); END""",
    """CREATE TRIGGER immutable_blob_identities_delete
        BEFORE DELETE ON blob_identities BEGIN
        SELECT RAISE(ABORT,'immutable blob identity'); END""",
    """CREATE TRIGGER immutable_blob_lifecycle_versions_update
        BEFORE UPDATE ON blob_lifecycle_versions BEGIN
        SELECT RAISE(ABORT,'immutable blob lifecycle version'); END""",
    """CREATE TRIGGER immutable_blob_lifecycle_versions_delete
        BEFORE DELETE ON blob_lifecycle_versions BEGIN
        SELECT RAISE(ABORT,'immutable blob lifecycle version'); END""",
    """CREATE TRIGGER blob_lifecycle_head_update_guard
        BEFORE UPDATE ON blob_lifecycle_heads
        WHEN NEW.blob_digest != OLD.blob_digest
          OR NEW.current_version != OLD.current_version + 1
        BEGIN SELECT RAISE(ABORT,'invalid blob lifecycle head update'); END""",
    """CREATE TRIGGER blob_lifecycle_head_delete_guard
        BEFORE DELETE ON blob_lifecycle_heads BEGIN
        SELECT RAISE(ABORT,'blob lifecycle heads are retained'); END""",
    """CREATE TRIGGER immutable_object_rights_decisions_update
        BEFORE UPDATE ON object_rights_decisions BEGIN
        SELECT RAISE(ABORT,'immutable object rights decision'); END""",
    """CREATE TRIGGER immutable_object_rights_decisions_delete
        BEFORE DELETE ON object_rights_decisions BEGIN
        SELECT RAISE(ABORT,'immutable object rights decision'); END""",
    """CREATE TRIGGER immutable_object_admissions_update
        BEFORE UPDATE ON object_admissions BEGIN
        SELECT RAISE(ABORT,'immutable object admission'); END""",
    """CREATE TRIGGER immutable_object_admissions_delete
        BEFORE DELETE ON object_admissions BEGIN
        SELECT RAISE(ABORT,'immutable object admission'); END""",
    """CREATE TRIGGER immutable_object_admission_versions_update
        BEFORE UPDATE ON object_admission_versions BEGIN
        SELECT RAISE(ABORT,'immutable object admission version'); END""",
    """CREATE TRIGGER immutable_object_admission_versions_delete
        BEFORE DELETE ON object_admission_versions BEGIN
        SELECT RAISE(ABORT,'immutable object admission version'); END""",
    """CREATE TRIGGER object_admission_head_update_guard
        BEFORE UPDATE ON object_admission_heads
        WHEN NEW.admission_id != OLD.admission_id
          OR NEW.current_version != OLD.current_version + 1
        BEGIN SELECT RAISE(ABORT,'invalid object admission head update'); END""",
    """CREATE TRIGGER object_admission_head_delete_guard
        BEFORE DELETE ON object_admission_heads BEGIN
        SELECT RAISE(ABORT,'object admission heads are retained'); END""",
    """CREATE TRIGGER immutable_object_access_decisions_update
        BEFORE UPDATE ON object_access_decisions BEGIN
        SELECT RAISE(ABORT,'immutable object access decision'); END""",
    """CREATE TRIGGER immutable_object_access_decisions_delete
        BEFORE DELETE ON object_access_decisions BEGIN
        SELECT RAISE(ABORT,'immutable object access decision'); END""",
    """CREATE TRIGGER immutable_object_deletions_update
        BEFORE UPDATE ON object_deletions BEGIN
        SELECT RAISE(ABORT,'immutable governed deletion identity'); END""",
    """CREATE TRIGGER immutable_object_deletions_delete
        BEFORE DELETE ON object_deletions BEGIN
        SELECT RAISE(ABORT,'governed deletion identity is retained'); END""",
    """CREATE TRIGGER immutable_object_deletion_versions_update
        BEFORE UPDATE ON object_deletion_versions BEGIN
        SELECT RAISE(ABORT,'immutable governed deletion version'); END""",
    """CREATE TRIGGER immutable_object_deletion_versions_delete
        BEFORE DELETE ON object_deletion_versions BEGIN
        SELECT RAISE(ABORT,'immutable governed deletion version'); END""",
    """CREATE TRIGGER object_deletion_head_update_guard
        BEFORE UPDATE ON object_deletion_heads
        WHEN NEW.deletion_id != OLD.deletion_id
          OR NEW.current_version != OLD.current_version + 1
        BEGIN SELECT RAISE(ABORT,'invalid governed deletion head update'); END""",
    """CREATE TRIGGER object_deletion_head_delete_guard
        BEFORE DELETE ON object_deletion_heads BEGIN
        SELECT RAISE(ABORT,'governed deletion heads are retained'); END""",
    """CREATE TRIGGER immutable_object_recovery_pins_update
        BEFORE UPDATE ON object_recovery_pins BEGIN
        SELECT RAISE(ABORT,'immutable recovery pin identity'); END""",
    """CREATE TRIGGER immutable_object_recovery_pins_delete
        BEFORE DELETE ON object_recovery_pins BEGIN
        SELECT RAISE(ABORT,'recovery pin identity is retained'); END""",
    """CREATE TRIGGER immutable_object_recovery_pin_versions_update
        BEFORE UPDATE ON object_recovery_pin_versions BEGIN
        SELECT RAISE(ABORT,'immutable recovery pin version'); END""",
    """CREATE TRIGGER immutable_object_recovery_pin_versions_delete
        BEFORE DELETE ON object_recovery_pin_versions BEGIN
        SELECT RAISE(ABORT,'immutable recovery pin version'); END""",
    """CREATE TRIGGER object_recovery_pin_head_update_guard
        BEFORE UPDATE ON object_recovery_pin_heads
        WHEN NEW.pin_id != OLD.pin_id
          OR NEW.current_version != OLD.current_version + 1
        BEGIN SELECT RAISE(ABORT,'invalid recovery pin head update'); END""",
    """CREATE TRIGGER object_recovery_pin_head_delete_guard
        BEFORE DELETE ON object_recovery_pin_heads BEGIN
        SELECT RAISE(ABORT,'recovery pin heads are retained'); END""",
    """CREATE TRIGGER immutable_object_lifecycle_operations_update
        BEFORE UPDATE ON object_lifecycle_operations BEGIN
        SELECT RAISE(ABORT,'immutable object lifecycle operation'); END""",
    """CREATE TRIGGER immutable_object_lifecycle_operations_delete
        BEFORE DELETE ON object_lifecycle_operations BEGIN
        SELECT RAISE(ABORT,'object lifecycle operations are retained'); END""",
    """CREATE TRIGGER authority_payload_object_admission_guard
        BEFORE INSERT ON authority_payloads
        WHEN NEW.mode='OBJECT_ADMISSION'
         AND NOT EXISTS(
            SELECT 1 FROM object_admissions a
            JOIN object_admission_heads h ON h.admission_id=a.admission_id
            JOIN object_admission_versions v
              ON v.admission_id=h.admission_id
             AND v.lifecycle_version=h.current_version
            WHERE a.admission_id=NEW.object_admission_id
              AND v.state='ACTIVE'
              AND a.blob_digest=NEW.payload_digest
         )
        BEGIN SELECT RAISE(ABORT,'object payload admission is not active'); END""",
)


OBJECT_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": OBJECT_SCHEMA_VERSION,
        "name": OBJECT_MIGRATION_NAME,
        "statements": list(OBJECT_MIGRATION_STATEMENTS),
    }
)
OBJECT_MIGRATION = ObjectMigrationRecord(
    version=OBJECT_SCHEMA_VERSION,
    name=OBJECT_MIGRATION_NAME,
    checksum=OBJECT_MIGRATION_CHECKSUM,
)


__all__ = [
    "OBJECT_MIGRATION",
    "OBJECT_MIGRATION_CHECKSUM",
    "OBJECT_MIGRATION_NAME",
    "OBJECT_MIGRATION_STATEMENTS",
    "OBJECT_SCHEMA_VERSION",
]
