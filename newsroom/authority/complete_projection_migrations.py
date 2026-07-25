from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


COMPLETE_PROJECTION_SCHEMA_VERSION = 7
COMPLETE_PROJECTION_MIGRATION_NAME = "complete_projection_authority_v7"


@dataclass(frozen=True, slots=True)
class CompleteProjectionMigrationRecord:
    version: int
    name: str
    checksum: str


COMPLETE_PROJECTION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE projection_fulltext_contracts(
        contract_digest TEXT PRIMARY KEY,
        contract_id TEXT NOT NULL,
        contract_version TEXT NOT NULL,
        implementation_version TEXT NOT NULL,
        index_name TEXT NOT NULL,
        node_label TEXT NOT NULL,
        source_field TEXT NOT NULL,
        retrieval_property TEXT NOT NULL,
        analyzer TEXT NOT NULL,
        provider TEXT NOT NULL,
        unicode_normalization TEXT NOT NULL CHECK(unicode_normalization='NFKC'),
        casefold INTEGER NOT NULL CHECK(casefold IN(0,1)),
        collapse_whitespace INTEGER NOT NULL CHECK(collapse_whitespace IN(0,1)),
        eventually_consistent INTEGER NOT NULL
            CHECK(eventually_consistent=0),
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(contract_id, contract_version),
        UNIQUE(index_name),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE projection_vector_contracts(
        contract_digest TEXT PRIMARY KEY,
        contract_id TEXT NOT NULL,
        contract_version TEXT NOT NULL,
        implementation_version TEXT NOT NULL,
        index_name TEXT NOT NULL,
        node_label TEXT NOT NULL,
        vector_property TEXT NOT NULL,
        dimensions INTEGER NOT NULL CHECK(dimensions>0 AND dimensions<=4096),
        component_scale INTEGER NOT NULL
            CHECK(component_scale>0 AND component_scale<=1000000000),
        provider TEXT NOT NULL,
        similarity_function TEXT NOT NULL CHECK(similarity_function='COSINE'),
        quantization TEXT NOT NULL CHECK(quantization='NONE'),
        provider_kind TEXT NOT NULL CHECK(provider_kind='REPOSITORY_FIXTURE'),
        fixture_only INTEGER NOT NULL CHECK(fixture_only=1),
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(contract_id, contract_version),
        UNIQUE(index_name),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE projection_fixture_vector_manifests(
        manifest_digest TEXT PRIMARY KEY,
        schema_version TEXT NOT NULL
            CHECK(schema_version='integrated_fixture_v2_projection_v1'),
        fixture_id TEXT NOT NULL,
        source_fixture_digest TEXT NOT NULL,
        dimensions INTEGER NOT NULL CHECK(dimensions=16),
        component_scale INTEGER NOT NULL CHECK(component_scale=1000000),
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(fixture_id, source_fixture_digest),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE projection_fixture_vectors(
        manifest_digest TEXT NOT NULL
            REFERENCES projection_fixture_vector_manifests(manifest_digest),
        passage_id TEXT NOT NULL,
        blob_digest TEXT NOT NULL,
        language TEXT NOT NULL CHECK(language IN('en-GB','zh-HK')),
        revision_id TEXT,
        expected_lifecycle TEXT NOT NULL
            CHECK(expected_lifecycle IN('ACTIVE','TOMBSTONED')),
        normalized_text_digest TEXT NOT NULL,
        components_bytes BLOB NOT NULL,
        vector_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(manifest_digest, passage_id),
        UNIQUE(manifest_digest, vector_digest),
        CHECK(length(components_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE projection_complete_contracts(
        contract_digest TEXT PRIMARY KEY,
        contract_id TEXT NOT NULL,
        contract_version TEXT NOT NULL,
        implementation_version TEXT NOT NULL,
        admitted_relation_projector_version TEXT NOT NULL,
        source_fixture_digest TEXT NOT NULL,
        fixture_vector_manifest_digest TEXT NOT NULL
            REFERENCES projection_fixture_vector_manifests(manifest_digest),
        fulltext_contract_digest TEXT NOT NULL
            REFERENCES projection_fulltext_contracts(contract_digest),
        vector_contract_digest TEXT NOT NULL
            REFERENCES projection_vector_contracts(contract_digest),
        required_derivatives_bytes BLOB NOT NULL,
        canonical_bytes BLOB NOT NULL,
        registered_at TEXT NOT NULL,
        UNIQUE(contract_id, contract_version),
        CHECK(length(required_derivatives_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE projection_family_complete_contracts(
        definition_digest TEXT PRIMARY KEY
            REFERENCES projection_family_definitions(definition_digest),
        complete_contract_digest TEXT NOT NULL
            REFERENCES projection_complete_contracts(contract_digest),
        registered_at TEXT NOT NULL,
        UNIQUE(complete_contract_digest, definition_digest)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE projection_generation_complete_bindings(
        generation_id TEXT PRIMARY KEY
            REFERENCES projection_generations(generation_id),
        definition_digest TEXT NOT NULL
            REFERENCES projection_family_definitions(definition_digest),
        complete_contract_digest TEXT NOT NULL
            REFERENCES projection_complete_contracts(contract_digest),
        fulltext_contract_digest TEXT NOT NULL
            REFERENCES projection_fulltext_contracts(contract_digest),
        vector_contract_digest TEXT NOT NULL
            REFERENCES projection_vector_contracts(contract_digest),
        fixture_vector_manifest_digest TEXT NOT NULL
            REFERENCES projection_fixture_vector_manifests(manifest_digest),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        bound_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE projection_generation_complete_validations(
        validation_digest TEXT PRIMARY KEY
            REFERENCES projection_generation_validations(validation_digest),
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        complete_contract_digest TEXT NOT NULL
            REFERENCES projection_complete_contracts(contract_digest),
        fulltext_contract_digest TEXT NOT NULL
            REFERENCES projection_fulltext_contracts(contract_digest),
        vector_contract_digest TEXT NOT NULL
            REFERENCES projection_vector_contracts(contract_digest),
        fixture_vector_manifest_digest TEXT NOT NULL
            REFERENCES projection_fixture_vector_manifests(manifest_digest),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(generation_id, validation_digest),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE INDEX idx_projection_fixture_vector_blob
        ON projection_fixture_vectors(blob_digest, passage_id)""",
    """CREATE INDEX idx_projection_complete_contract_derivatives
        ON projection_complete_contracts(
            fulltext_contract_digest,
            vector_contract_digest,
            fixture_vector_manifest_digest
        )""",
    """CREATE TRIGGER immutable_projection_fulltext_contract_update
        BEFORE UPDATE ON projection_fulltext_contracts BEGIN
        SELECT RAISE(ABORT,'immutable projection full-text contract'); END""",
    """CREATE TRIGGER immutable_projection_fulltext_contract_delete
        BEFORE DELETE ON projection_fulltext_contracts BEGIN
        SELECT RAISE(ABORT,'projection full-text contracts are retained'); END""",
    """CREATE TRIGGER immutable_projection_vector_contract_update
        BEFORE UPDATE ON projection_vector_contracts BEGIN
        SELECT RAISE(ABORT,'immutable projection vector contract'); END""",
    """CREATE TRIGGER immutable_projection_vector_contract_delete
        BEFORE DELETE ON projection_vector_contracts BEGIN
        SELECT RAISE(ABORT,'projection vector contracts are retained'); END""",
    """CREATE TRIGGER immutable_projection_fixture_manifest_update
        BEFORE UPDATE ON projection_fixture_vector_manifests BEGIN
        SELECT RAISE(ABORT,'immutable projection fixture vector manifest'); END""",
    """CREATE TRIGGER immutable_projection_fixture_manifest_delete
        BEFORE DELETE ON projection_fixture_vector_manifests BEGIN
        SELECT RAISE(ABORT,'projection fixture vector manifests are retained'); END""",
    """CREATE TRIGGER immutable_projection_fixture_vector_update
        BEFORE UPDATE ON projection_fixture_vectors BEGIN
        SELECT RAISE(ABORT,'immutable projection fixture vector'); END""",
    """CREATE TRIGGER immutable_projection_fixture_vector_delete
        BEFORE DELETE ON projection_fixture_vectors BEGIN
        SELECT RAISE(ABORT,'projection fixture vectors are retained'); END""",
    """CREATE TRIGGER immutable_projection_complete_contract_update
        BEFORE UPDATE ON projection_complete_contracts BEGIN
        SELECT RAISE(ABORT,'immutable complete projection contract'); END""",
    """CREATE TRIGGER immutable_projection_complete_contract_delete
        BEFORE DELETE ON projection_complete_contracts BEGIN
        SELECT RAISE(ABORT,'complete projection contracts are retained'); END""",
    """CREATE TRIGGER immutable_projection_family_complete_update
        BEFORE UPDATE ON projection_family_complete_contracts BEGIN
        SELECT RAISE(ABORT,'immutable family complete projection binding'); END""",
    """CREATE TRIGGER immutable_projection_family_complete_delete
        BEFORE DELETE ON projection_family_complete_contracts BEGIN
        SELECT RAISE(ABORT,'family complete projection bindings are retained'); END""",
    """CREATE TRIGGER immutable_projection_generation_complete_update
        BEFORE UPDATE ON projection_generation_complete_bindings BEGIN
        SELECT RAISE(ABORT,'immutable generation complete projection binding'); END""",
    """CREATE TRIGGER immutable_projection_generation_complete_delete
        BEFORE DELETE ON projection_generation_complete_bindings BEGIN
        SELECT RAISE(ABORT,'generation complete projection bindings are retained'); END""",
    """CREATE TRIGGER immutable_projection_complete_validation_update
        BEFORE UPDATE ON projection_generation_complete_validations BEGIN
        SELECT RAISE(ABORT,'immutable complete projection validation binding'); END""",
    """CREATE TRIGGER immutable_projection_complete_validation_delete
        BEFORE DELETE ON projection_generation_complete_validations BEGIN
        SELECT RAISE(ABORT,'complete projection validation bindings are retained'); END""",
)


COMPLETE_PROJECTION_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": COMPLETE_PROJECTION_SCHEMA_VERSION,
        "name": COMPLETE_PROJECTION_MIGRATION_NAME,
        "statements": list(COMPLETE_PROJECTION_MIGRATION_STATEMENTS),
    }
)
COMPLETE_PROJECTION_MIGRATION = CompleteProjectionMigrationRecord(
    version=COMPLETE_PROJECTION_SCHEMA_VERSION,
    name=COMPLETE_PROJECTION_MIGRATION_NAME,
    checksum=COMPLETE_PROJECTION_MIGRATION_CHECKSUM,
)


__all__ = [
    "COMPLETE_PROJECTION_MIGRATION",
    "COMPLETE_PROJECTION_MIGRATION_CHECKSUM",
    "COMPLETE_PROJECTION_MIGRATION_NAME",
    "COMPLETE_PROJECTION_MIGRATION_STATEMENTS",
    "COMPLETE_PROJECTION_SCHEMA_VERSION",
]
