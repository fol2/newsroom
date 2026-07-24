from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


INTEGRATED_FOUNDATION_SCHEMA_VERSION = 5
INTEGRATED_FOUNDATION_MIGRATION_NAME = "integrated_foundation_proof_v5"


@dataclass(frozen=True, slots=True)
class IntegratedFoundationMigrationRecord:
    version: int
    name: str
    checksum: str


INTEGRATED_FOUNDATION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE integrated_retrieval_contexts(
        context_id TEXT PRIMARY KEY,
        context_digest TEXT NOT NULL,
        fixture_id TEXT NOT NULL,
        fixture_aggregate_type TEXT NOT NULL
            CHECK(fixture_aggregate_type='integrated_fixture'),
        fixture_aggregate_id TEXT NOT NULL,
        fixture_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        admission_id TEXT NOT NULL REFERENCES object_admissions(admission_id),
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        projected_through_ledger_seq INTEGER NOT NULL
            CHECK(projected_through_ledger_seq >= 0),
        hydration_access_decision_id TEXT NOT NULL
            REFERENCES object_access_decisions(access_decision_id),
        manifest_digest TEXT NOT NULL,
        retrieval_version TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(fixture_aggregate_type,fixture_aggregate_id)
            REFERENCES authority_aggregates(aggregate_type,aggregate_id),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE integrated_exact_index_entries(
        context_id TEXT NOT NULL
            REFERENCES integrated_retrieval_contexts(context_id),
        canonical_id TEXT NOT NULL,
        node_type TEXT NOT NULL,
        first_ledger_seq INTEGER NOT NULL CHECK(first_ledger_seq > 0),
        first_source_event_id TEXT NOT NULL,
        first_source_event_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(context_id, canonical_id),
        CHECK(length(canonical_bytes) > 0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE story_candidates(
        candidate_id TEXT PRIMARY KEY,
        semantic_collision_digest TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE story_candidate_versions(
        candidate_version_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL REFERENCES story_candidates(candidate_id),
        version_number INTEGER NOT NULL CHECK(version_number > 0),
        fixture_id TEXT NOT NULL,
        signal_id TEXT NOT NULL,
        lead_id TEXT NOT NULL,
        hypothesis_version_id TEXT NOT NULL,
        route TEXT NOT NULL
            CHECK(route IN('NEW_EVENT','DEVELOPMENT','CORRECTION')),
        hypothesis_trust_scope TEXT NOT NULL
            CHECK(hypothesis_trust_scope='PROPOSED'),
        retrieval_context_id TEXT NOT NULL
            REFERENCES integrated_retrieval_contexts(context_id),
        manifest_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(candidate_id, version_number),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE TABLE candidate_admission_decisions(
        decision_id TEXT PRIMARY KEY,
        proposal_aggregate_type TEXT NOT NULL
            CHECK(proposal_aggregate_type='candidate_admission_proposal'),
        proposal_id TEXT NOT NULL UNIQUE,
        outcome TEXT NOT NULL CHECK(outcome IN('ADMITTED','DEDUPLICATED')),
        candidate_id TEXT NOT NULL REFERENCES story_candidates(candidate_id),
        candidate_version_id TEXT NOT NULL
            REFERENCES story_candidate_versions(candidate_version_id),
        route TEXT NOT NULL
            CHECK(route IN('NEW_EVENT','DEVELOPMENT','CORRECTION')),
        fixture_id TEXT NOT NULL,
        retrieval_context_id TEXT NOT NULL
            REFERENCES integrated_retrieval_contexts(context_id),
        retrieval_context_digest TEXT NOT NULL,
        manifest_digest TEXT NOT NULL,
        semantic_collision_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version > 0),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(proposal_aggregate_type,proposal_id)
            REFERENCES authority_aggregates(aggregate_type,aggregate_id),
        CHECK(length(canonical_bytes) > 0)
    ) STRICT""",
    """CREATE INDEX idx_integrated_context_fixture
        ON integrated_retrieval_contexts(fixture_id, recorded_at)""",
    """CREATE INDEX idx_integrated_index_event
        ON integrated_exact_index_entries(first_source_event_id, first_ledger_seq)""",
    """CREATE INDEX idx_story_candidate_fixture
        ON story_candidate_versions(fixture_id, candidate_id, version_number)""",
    """CREATE INDEX idx_candidate_decision_candidate
        ON candidate_admission_decisions(candidate_id, recorded_at)""",
    """CREATE TRIGGER immutable_integrated_context_update
        BEFORE UPDATE ON integrated_retrieval_contexts BEGIN
        SELECT RAISE(ABORT,'immutable integrated retrieval context'); END""",
    """CREATE TRIGGER immutable_integrated_context_delete
        BEFORE DELETE ON integrated_retrieval_contexts BEGIN
        SELECT RAISE(ABORT,'integrated retrieval contexts are retained'); END""",
    """CREATE TRIGGER immutable_integrated_exact_index_update
        BEFORE UPDATE ON integrated_exact_index_entries BEGIN
        SELECT RAISE(ABORT,'immutable integrated exact index'); END""",
    """CREATE TRIGGER immutable_integrated_exact_index_delete
        BEFORE DELETE ON integrated_exact_index_entries BEGIN
        SELECT RAISE(ABORT,'integrated exact index entries are retained'); END""",
    """CREATE TRIGGER immutable_story_candidate_update
        BEFORE UPDATE ON story_candidates BEGIN
        SELECT RAISE(ABORT,'immutable story candidate identity'); END""",
    """CREATE TRIGGER immutable_story_candidate_delete
        BEFORE DELETE ON story_candidates BEGIN
        SELECT RAISE(ABORT,'story candidate identities are retained'); END""",
    """CREATE TRIGGER immutable_story_candidate_version_update
        BEFORE UPDATE ON story_candidate_versions BEGIN
        SELECT RAISE(ABORT,'immutable story candidate version'); END""",
    """CREATE TRIGGER immutable_story_candidate_version_delete
        BEFORE DELETE ON story_candidate_versions BEGIN
        SELECT RAISE(ABORT,'story candidate versions are retained'); END""",
    """CREATE TRIGGER immutable_candidate_admission_decision_update
        BEFORE UPDATE ON candidate_admission_decisions BEGIN
        SELECT RAISE(ABORT,'immutable candidate admission decision'); END""",
    """CREATE TRIGGER immutable_candidate_admission_decision_delete
        BEFORE DELETE ON candidate_admission_decisions BEGIN
        SELECT RAISE(ABORT,'candidate admission decisions are retained'); END""",
)

INTEGRATED_FOUNDATION_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": INTEGRATED_FOUNDATION_SCHEMA_VERSION,
        "name": INTEGRATED_FOUNDATION_MIGRATION_NAME,
        "statements": list(INTEGRATED_FOUNDATION_MIGRATION_STATEMENTS),
    }
)
INTEGRATED_FOUNDATION_MIGRATION = IntegratedFoundationMigrationRecord(
    version=INTEGRATED_FOUNDATION_SCHEMA_VERSION,
    name=INTEGRATED_FOUNDATION_MIGRATION_NAME,
    checksum=INTEGRATED_FOUNDATION_MIGRATION_CHECKSUM,
)


__all__ = [
    "INTEGRATED_FOUNDATION_MIGRATION",
    "INTEGRATED_FOUNDATION_MIGRATION_CHECKSUM",
    "INTEGRATED_FOUNDATION_MIGRATION_NAME",
    "INTEGRATED_FOUNDATION_MIGRATION_STATEMENTS",
    "INTEGRATED_FOUNDATION_SCHEMA_VERSION",
]
