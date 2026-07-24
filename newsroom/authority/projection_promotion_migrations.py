from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical

PROJECTION_PROMOTION_SCHEMA_VERSION = 4
PROJECTION_PROMOTION_MIGRATION_NAME = "projection_generation_promotion_v4"


@dataclass(frozen=True, slots=True)
class ProjectionPromotionMigrationRecord:
    version: int
    name: str
    checksum: str


PROJECTION_PROMOTION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE projection_generation_validations(
        validation_digest TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        validation_version INTEGER NOT NULL CHECK(validation_version > 0),
        lifecycle_version INTEGER NOT NULL CHECK(lifecycle_version > 0),
        checkpoint_ledger_seq INTEGER NOT NULL CHECK(checkpoint_ledger_seq >= 0),
        definition_digest TEXT NOT NULL
            REFERENCES projection_family_definitions(definition_digest),
        ontology_contract_digest TEXT NOT NULL
            REFERENCES projection_ontology_contracts(contract_digest),
        mapping_contract_digest TEXT NOT NULL
            REFERENCES projection_mapping_contracts(contract_digest),
        projector_version TEXT NOT NULL,
        service_compatibility_digest TEXT NOT NULL,
        projection_state_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version > 0),
        authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        recorded_at TEXT NOT NULL,
        UNIQUE(generation_id, validation_version),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE projection_generation_promotions(
        promotion_digest TEXT PRIMARY KEY,
        family_id TEXT NOT NULL REFERENCES projection_families(family_id),
        generation_id TEXT NOT NULL UNIQUE
            REFERENCES projection_generations(generation_id),
        prior_generation_id TEXT
            REFERENCES projection_generations(generation_id),
        checkpoint_ledger_seq INTEGER NOT NULL CHECK(checkpoint_ledger_seq >= 0),
        validation_digest TEXT NOT NULL
            REFERENCES projection_generation_validations(validation_digest),
        target_authority_aggregate_version INTEGER NOT NULL
            CHECK(target_authority_aggregate_version > 0),
        target_authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        prior_authority_aggregate_version INTEGER
            CHECK(prior_authority_aggregate_version IS NULL
                  OR prior_authority_aggregate_version > 0),
        prior_authority_event_id TEXT UNIQUE REFERENCES ledger_events(event_id),
        canonical_bytes BLOB NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK((prior_generation_id IS NULL
               AND prior_authority_aggregate_version IS NULL
               AND prior_authority_event_id IS NULL)
           OR (prior_generation_id IS NOT NULL
               AND prior_authority_aggregate_version IS NOT NULL
               AND prior_authority_event_id IS NOT NULL)),
        CHECK(prior_generation_id IS NULL OR prior_generation_id != generation_id),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE INDEX idx_projection_validations_generation
        ON projection_generation_validations(generation_id, validation_version)""",
    """CREATE INDEX idx_projection_promotions_family
        ON projection_generation_promotions(family_id, recorded_at)""",
    """CREATE TRIGGER immutable_projection_generation_validation_update
        BEFORE UPDATE ON projection_generation_validations BEGIN
        SELECT RAISE(ABORT,'immutable projection generation validation'); END""",
    """CREATE TRIGGER immutable_projection_generation_validation_delete
        BEFORE DELETE ON projection_generation_validations BEGIN
        SELECT RAISE(ABORT,'projection generation validations are retained'); END""",
    """CREATE TRIGGER immutable_projection_generation_promotion_update
        BEFORE UPDATE ON projection_generation_promotions BEGIN
        SELECT RAISE(ABORT,'immutable projection generation promotion'); END""",
    """CREATE TRIGGER immutable_projection_generation_promotion_delete
        BEFORE DELETE ON projection_generation_promotions BEGIN
        SELECT RAISE(ABORT,'projection generation promotions are retained'); END""",
)

PROJECTION_PROMOTION_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": PROJECTION_PROMOTION_SCHEMA_VERSION,
        "name": PROJECTION_PROMOTION_MIGRATION_NAME,
        "statements": list(PROJECTION_PROMOTION_MIGRATION_STATEMENTS),
    }
)
PROJECTION_PROMOTION_MIGRATION = ProjectionPromotionMigrationRecord(
    version=PROJECTION_PROMOTION_SCHEMA_VERSION,
    name=PROJECTION_PROMOTION_MIGRATION_NAME,
    checksum=PROJECTION_PROMOTION_MIGRATION_CHECKSUM,
)

__all__ = [
    "PROJECTION_PROMOTION_MIGRATION",
    "PROJECTION_PROMOTION_MIGRATION_CHECKSUM",
    "PROJECTION_PROMOTION_MIGRATION_NAME",
    "PROJECTION_PROMOTION_MIGRATION_STATEMENTS",
    "PROJECTION_PROMOTION_SCHEMA_VERSION",
]
