from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical

PROJECTION_SCHEMA_VERSION = 3
PROJECTION_MIGRATION_NAME = "projection_authority_v3"


@dataclass(frozen=True, slots=True)
class ProjectionMigrationRecord:
    version: int
    name: str
    checksum: str


PROJECTION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE projection_ontology_contracts(
        contract_digest TEXT PRIMARY KEY,
        ontology_id TEXT NOT NULL,
        ontology_version TEXT NOT NULL,
        implementation_version TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(ontology_id, ontology_version),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE projection_mapping_contracts(
        contract_digest TEXT PRIMARY KEY,
        mapping_id TEXT NOT NULL,
        mapping_version TEXT NOT NULL,
        implementation_version TEXT NOT NULL,
        ontology_contract_digest TEXT NOT NULL
            REFERENCES projection_ontology_contracts(contract_digest),
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(mapping_id, mapping_version),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE projection_family_definitions(
        definition_digest TEXT PRIMARY KEY,
        family_id TEXT NOT NULL,
        definition_version TEXT NOT NULL,
        authority_aggregate_id TEXT NOT NULL,
        family_kind TEXT NOT NULL
            CHECK(family_kind IN ('GRAPH','VECTOR','FULL_TEXT')),
        projector_version TEXT NOT NULL,
        ontology_contract_digest TEXT NOT NULL
            REFERENCES projection_ontology_contracts(contract_digest),
        mapping_contract_digest TEXT NOT NULL
            REFERENCES projection_mapping_contracts(contract_digest),
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(family_id, definition_version),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE projection_families(
        family_id TEXT PRIMARY KEY,
        definition_digest TEXT NOT NULL
            REFERENCES projection_family_definitions(definition_digest),
        authority_aggregate_id TEXT NOT NULL UNIQUE,
        family_kind TEXT NOT NULL
            CHECK(family_kind IN ('GRAPH','VECTOR','FULL_TEXT')),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version > 0),
        registered_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        created_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE projection_generations(
        generation_id TEXT PRIMARY KEY,
        family_id TEXT NOT NULL REFERENCES projection_families(family_id),
        state TEXT NOT NULL
            CHECK(state IN ('BUILDING','VALIDATING','ACTIVE','RETIRED','FAILED')),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version > 0),
        validated_through_ledger_seq INTEGER
            CHECK(validated_through_ledger_seq IS NULL
                  OR validated_through_ledger_seq >= 0),
        created_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        updated_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) STRICT""",
    """CREATE UNIQUE INDEX idx_projection_one_active_generation
        ON projection_generations(family_id) WHERE state='ACTIVE'""",
    """CREATE TABLE projection_generation_versions(
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        state TEXT NOT NULL
            CHECK(state IN ('BUILDING','VALIDATING','ACTIVE','RETIRED','FAILED')),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version > 0),
        validated_through_ledger_seq INTEGER
            CHECK(validated_through_ledger_seq IS NULL
                  OR validated_through_ledger_seq >= 0),
        reason_code TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(generation_id, lifecycle_version)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE projection_checkpoint_versions(
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        checkpoint_version INTEGER NOT NULL CHECK(checkpoint_version > 0),
        contiguous_ledger_seq INTEGER NOT NULL CHECK(contiguous_ledger_seq >= 0),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version > 0),
        authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(generation_id, checkpoint_version)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE projection_gaps(
        gap_id TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        ledger_seq_start INTEGER NOT NULL CHECK(ledger_seq_start > 0),
        ledger_seq_end INTEGER NOT NULL CHECK(ledger_seq_end >= ledger_seq_start),
        state TEXT NOT NULL CHECK(state IN ('OPEN','RESOLVED')),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        required INTEGER NOT NULL CHECK(required IN (0,1)),
        reason_code TEXT NOT NULL,
        opened_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        resolved_event_id TEXT REFERENCES ledger_events(event_id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(generation_id, ledger_seq_start, ledger_seq_end)
    ) STRICT""",
    """CREATE UNIQUE INDEX idx_projection_open_gap_sequence
        ON projection_gaps(generation_id, ledger_seq_start)
        WHERE state='OPEN'""",
    """CREATE TABLE projection_gap_versions(
        gap_id TEXT NOT NULL REFERENCES projection_gaps(gap_id),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        state TEXT NOT NULL CHECK(state IN ('OPEN','RESOLVED')),
        required INTEGER NOT NULL CHECK(required IN (0,1)),
        reason_code TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(gap_id, lifecycle_version)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE projection_delivery_states(
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        ledger_seq INTEGER NOT NULL CHECK(ledger_seq > 0),
        source_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        source_event_digest TEXT NOT NULL,
        source_event_type TEXT NOT NULL,
        required INTEGER NOT NULL CHECK(required IN (0,1)),
        attempt_count INTEGER NOT NULL CHECK(attempt_count > 0),
        current_outcome TEXT NOT NULL
            CHECK(current_outcome IN (
                'APPLIED','IGNORED_OPTIONAL','RETRYABLE_FAILURE',
                'REQUIRED_UNSUPPORTED'
            )),
        finalized INTEGER NOT NULL CHECK(finalized IN (0,1)),
        last_error_code TEXT,
        last_authority_event_id TEXT NOT NULL
            REFERENCES ledger_events(event_id),
        updated_at TEXT NOT NULL,
        PRIMARY KEY(generation_id, ledger_seq),
        UNIQUE(generation_id, source_event_id)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE projection_delivery_attempts(
        delivery_attempt_id TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        ledger_seq INTEGER NOT NULL CHECK(ledger_seq > 0),
        source_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        source_event_digest TEXT NOT NULL,
        source_event_type TEXT NOT NULL,
        attempt_number INTEGER NOT NULL CHECK(attempt_number > 0),
        outcome TEXT NOT NULL
            CHECK(outcome IN (
                'APPLIED','IGNORED_OPTIONAL','RETRYABLE_FAILURE',
                'REQUIRED_UNSUPPORTED'
            )),
        required INTEGER NOT NULL CHECK(required IN (0,1)),
        error_code TEXT,
        authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        recorded_at TEXT NOT NULL,
        UNIQUE(generation_id, ledger_seq, attempt_number)
    ) STRICT""",
    """CREATE TABLE projection_dead_letters(
        dead_letter_id TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        ledger_seq INTEGER NOT NULL CHECK(ledger_seq > 0),
        source_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        attempts INTEGER NOT NULL CHECK(attempts > 0),
        reason_code TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        recorded_at TEXT NOT NULL,
        UNIQUE(generation_id, ledger_seq)
    ) STRICT""",
    """CREATE TABLE projection_graphiti_workspace_contracts(
        contract_digest TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        contract_version TEXT NOT NULL,
        endpoint_reference TEXT NOT NULL,
        secret_reference TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode='PROPOSAL_ONLY'),
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(workspace_id, contract_version),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    "CREATE INDEX idx_projection_generations_family ON projection_generations(family_id, state)",
    "CREATE INDEX idx_projection_delivery_source ON projection_delivery_attempts(source_event_id, generation_id)",
    "CREATE INDEX idx_projection_gaps_generation ON projection_gaps(generation_id, state, ledger_seq_start)",
    "CREATE INDEX idx_projection_dead_letters_generation ON projection_dead_letters(generation_id, ledger_seq)",
    """CREATE TRIGGER immutable_projection_ontology_update
        BEFORE UPDATE ON projection_ontology_contracts BEGIN
        SELECT RAISE(ABORT,'immutable projection ontology'); END""",
    """CREATE TRIGGER immutable_projection_ontology_delete
        BEFORE DELETE ON projection_ontology_contracts BEGIN
        SELECT RAISE(ABORT,'immutable projection ontology'); END""",
    """CREATE TRIGGER immutable_projection_mapping_update
        BEFORE UPDATE ON projection_mapping_contracts BEGIN
        SELECT RAISE(ABORT,'immutable projection mapping'); END""",
    """CREATE TRIGGER immutable_projection_mapping_delete
        BEFORE DELETE ON projection_mapping_contracts BEGIN
        SELECT RAISE(ABORT,'immutable projection mapping'); END""",
    """CREATE TRIGGER immutable_projection_family_definition_update
        BEFORE UPDATE ON projection_family_definitions BEGIN
        SELECT RAISE(ABORT,'immutable projection family definition'); END""",
    """CREATE TRIGGER immutable_projection_family_definition_delete
        BEFORE DELETE ON projection_family_definitions BEGIN
        SELECT RAISE(ABORT,'immutable projection family definition'); END""",
    """CREATE TRIGGER immutable_projection_family_update
        BEFORE UPDATE ON projection_families BEGIN
        SELECT RAISE(ABORT,'immutable projection family'); END""",
    """CREATE TRIGGER immutable_projection_family_delete
        BEFORE DELETE ON projection_families BEGIN
        SELECT RAISE(ABORT,'projection families are retained'); END""",
    """CREATE TRIGGER projection_generation_update_guard
        BEFORE UPDATE ON projection_generations
        WHEN NEW.generation_id != OLD.generation_id
          OR NEW.family_id != OLD.family_id
          OR NEW.lifecycle_version != OLD.lifecycle_version + 1
          OR NEW.authority_aggregate_version <= OLD.authority_aggregate_version
          OR NEW.created_event_id != OLD.created_event_id
          OR NEW.created_at != OLD.created_at
        BEGIN SELECT RAISE(ABORT,'invalid projection generation update'); END""",
    """CREATE TRIGGER projection_generation_delete_guard
        BEFORE DELETE ON projection_generations BEGIN
        SELECT RAISE(ABORT,'projection generations are retained'); END""",
    """CREATE TRIGGER immutable_projection_generation_version_update
        BEFORE UPDATE ON projection_generation_versions BEGIN
        SELECT RAISE(ABORT,'immutable projection generation version'); END""",
    """CREATE TRIGGER immutable_projection_generation_version_delete
        BEFORE DELETE ON projection_generation_versions BEGIN
        SELECT RAISE(ABORT,'immutable projection generation version'); END""",
    """CREATE TRIGGER immutable_projection_checkpoint_update
        BEFORE UPDATE ON projection_checkpoint_versions BEGIN
        SELECT RAISE(ABORT,'immutable projection checkpoint'); END""",
    """CREATE TRIGGER immutable_projection_checkpoint_delete
        BEFORE DELETE ON projection_checkpoint_versions BEGIN
        SELECT RAISE(ABORT,'immutable projection checkpoint'); END""",
    """CREATE TRIGGER projection_gap_update_guard
        BEFORE UPDATE ON projection_gaps
        WHEN NEW.gap_id != OLD.gap_id
          OR NEW.generation_id != OLD.generation_id
          OR NEW.ledger_seq_start != OLD.ledger_seq_start
          OR NEW.ledger_seq_end != OLD.ledger_seq_end
          OR NEW.lifecycle_version != OLD.lifecycle_version + 1
          OR NEW.required != OLD.required
          OR OLD.state != 'OPEN'
          OR NEW.state != 'RESOLVED'
          OR NEW.resolved_event_id IS NULL
          OR NEW.created_at != OLD.created_at
        BEGIN SELECT RAISE(ABORT,'invalid projection gap update'); END""",
    """CREATE TRIGGER projection_gap_delete_guard
        BEFORE DELETE ON projection_gaps BEGIN
        SELECT RAISE(ABORT,'projection gaps are retained'); END""",
    """CREATE TRIGGER immutable_projection_gap_version_update
        BEFORE UPDATE ON projection_gap_versions BEGIN
        SELECT RAISE(ABORT,'immutable projection gap version'); END""",
    """CREATE TRIGGER immutable_projection_gap_version_delete
        BEFORE DELETE ON projection_gap_versions BEGIN
        SELECT RAISE(ABORT,'immutable projection gap version'); END""",
    """CREATE TRIGGER projection_delivery_state_update_guard
        BEFORE UPDATE ON projection_delivery_states
        WHEN NEW.generation_id != OLD.generation_id
          OR NEW.ledger_seq != OLD.ledger_seq
          OR NEW.source_event_id != OLD.source_event_id
          OR NEW.source_event_digest != OLD.source_event_digest
          OR NEW.source_event_type != OLD.source_event_type
          OR NEW.required != OLD.required
          OR NEW.attempt_count != OLD.attempt_count + 1
          OR OLD.finalized = 1
        BEGIN SELECT RAISE(ABORT,'invalid projection delivery update'); END""",
    """CREATE TRIGGER projection_delivery_state_delete_guard
        BEFORE DELETE ON projection_delivery_states BEGIN
        SELECT RAISE(ABORT,'projection delivery state is retained'); END""",
    """CREATE TRIGGER immutable_projection_delivery_attempt_update
        BEFORE UPDATE ON projection_delivery_attempts BEGIN
        SELECT RAISE(ABORT,'immutable projection delivery attempt'); END""",
    """CREATE TRIGGER immutable_projection_delivery_attempt_delete
        BEFORE DELETE ON projection_delivery_attempts BEGIN
        SELECT RAISE(ABORT,'immutable projection delivery attempt'); END""",
    """CREATE TRIGGER immutable_projection_dead_letter_update
        BEFORE UPDATE ON projection_dead_letters BEGIN
        SELECT RAISE(ABORT,'immutable projection dead letter'); END""",
    """CREATE TRIGGER immutable_projection_dead_letter_delete
        BEFORE DELETE ON projection_dead_letters BEGIN
        SELECT RAISE(ABORT,'immutable projection dead letter'); END""",
    """CREATE TRIGGER immutable_projection_graphiti_contract_update
        BEFORE UPDATE ON projection_graphiti_workspace_contracts BEGIN
        SELECT RAISE(ABORT,'immutable Graphiti workspace contract'); END""",
    """CREATE TRIGGER immutable_projection_graphiti_contract_delete
        BEFORE DELETE ON projection_graphiti_workspace_contracts BEGIN
        SELECT RAISE(ABORT,'immutable Graphiti workspace contract'); END""",
)

PROJECTION_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": PROJECTION_SCHEMA_VERSION,
        "name": PROJECTION_MIGRATION_NAME,
        "statements": list(PROJECTION_MIGRATION_STATEMENTS),
    }
)
PROJECTION_MIGRATION = ProjectionMigrationRecord(
    version=PROJECTION_SCHEMA_VERSION,
    name=PROJECTION_MIGRATION_NAME,
    checksum=PROJECTION_MIGRATION_CHECKSUM,
)

__all__ = [
    "PROJECTION_MIGRATION",
    "PROJECTION_MIGRATION_CHECKSUM",
    "PROJECTION_MIGRATION_NAME",
    "PROJECTION_MIGRATION_STATEMENTS",
    "PROJECTION_SCHEMA_VERSION",
]
