from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


DEVELOPMENT_CANDIDATE_SCHEMA_VERSION = 9
DEVELOPMENT_CANDIDATE_MIGRATION_NAME = (
    "complete_fixture_candidate_authority_v9"
)


@dataclass(frozen=True, slots=True)
class DevelopmentCandidateMigrationRecord:
    version: int
    name: str
    checksum: str


DEVELOPMENT_CANDIDATE_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE development_candidates_v2(
        candidate_id TEXT PRIMARY KEY,
        semantic_collision_digest TEXT NOT NULL UNIQUE,
        manifest_digest TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE development_candidate_versions_v2(
        candidate_version_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL
            REFERENCES development_candidates_v2(candidate_id),
        version_number INTEGER NOT NULL CHECK(version_number=1),
        fixture_id TEXT NOT NULL,
        signal_id TEXT NOT NULL,
        lead_id TEXT NOT NULL,
        hypothesis_version_id TEXT NOT NULL,
        prior_hypothesis_version_id TEXT NOT NULL,
        prior_candidate_version_id TEXT NOT NULL,
        current_revision_id TEXT NOT NULL,
        prior_revision_id TEXT NOT NULL,
        canonical_process_id TEXT NOT NULL,
        relation_key TEXT NOT NULL,
        route TEXT NOT NULL CHECK(route='DEVELOPMENT'),
        hypothesis_trust_scope TEXT NOT NULL CHECK(hypothesis_trust_scope='PROPOSED'),
        initial_retrieval_context_id TEXT NOT NULL
            REFERENCES hybrid_retrieval_contexts_v2(context_id),
        initial_retrieval_context_digest TEXT NOT NULL,
        manifest_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(candidate_id,version_number),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE development_candidate_admission_decisions_v2(
        decision_id TEXT PRIMARY KEY,
        proposal_aggregate_type TEXT NOT NULL
            CHECK(proposal_aggregate_type='development_candidate_admission_proposal'),
        proposal_id TEXT NOT NULL UNIQUE,
        outcome TEXT NOT NULL CHECK(outcome IN('ADMITTED','DEDUPLICATED')),
        candidate_id TEXT NOT NULL
            REFERENCES development_candidates_v2(candidate_id),
        candidate_version_id TEXT NOT NULL
            REFERENCES development_candidate_versions_v2(candidate_version_id),
        route TEXT NOT NULL CHECK(route='DEVELOPMENT'),
        fixture_id TEXT NOT NULL,
        retrieval_context_id TEXT NOT NULL
            REFERENCES hybrid_retrieval_contexts_v2(context_id),
        retrieval_context_digest TEXT NOT NULL,
        manifest_digest TEXT NOT NULL,
        semantic_collision_digest TEXT NOT NULL,
        relation_key TEXT NOT NULL,
        prior_candidate_version_id TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(proposal_aggregate_type,proposal_id)
            REFERENCES authority_aggregates(aggregate_type,aggregate_id),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE INDEX idx_development_candidate_fixture
        ON development_candidate_versions_v2(
            fixture_id,canonical_process_id,candidate_id
        )""",
    """CREATE INDEX idx_development_candidate_context
        ON development_candidate_admission_decisions_v2(
            retrieval_context_id,recorded_at
        )""",
    """CREATE TRIGGER immutable_development_candidate_update
        BEFORE UPDATE ON development_candidates_v2 BEGIN
        SELECT RAISE(ABORT,'immutable development Candidate identity'); END""",
    """CREATE TRIGGER immutable_development_candidate_delete
        BEFORE DELETE ON development_candidates_v2 BEGIN
        SELECT RAISE(ABORT,'development Candidate identities are retained'); END""",
    """CREATE TRIGGER immutable_development_candidate_version_update
        BEFORE UPDATE ON development_candidate_versions_v2 BEGIN
        SELECT RAISE(ABORT,'immutable development Candidate version'); END""",
    """CREATE TRIGGER immutable_development_candidate_version_delete
        BEFORE DELETE ON development_candidate_versions_v2 BEGIN
        SELECT RAISE(ABORT,'development Candidate versions are retained'); END""",
    """CREATE TRIGGER immutable_development_candidate_decision_update
        BEFORE UPDATE ON development_candidate_admission_decisions_v2 BEGIN
        SELECT RAISE(ABORT,'immutable development Candidate decision'); END""",
    """CREATE TRIGGER immutable_development_candidate_decision_delete
        BEFORE DELETE ON development_candidate_admission_decisions_v2 BEGIN
        SELECT RAISE(ABORT,'development Candidate decisions are retained'); END""",
)


DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": DEVELOPMENT_CANDIDATE_SCHEMA_VERSION,
        "name": DEVELOPMENT_CANDIDATE_MIGRATION_NAME,
        "statements": list(DEVELOPMENT_CANDIDATE_MIGRATION_STATEMENTS),
    }
)
DEVELOPMENT_CANDIDATE_MIGRATION = DevelopmentCandidateMigrationRecord(
    version=DEVELOPMENT_CANDIDATE_SCHEMA_VERSION,
    name=DEVELOPMENT_CANDIDATE_MIGRATION_NAME,
    checksum=DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM,
)


__all__ = [
    "DEVELOPMENT_CANDIDATE_MIGRATION",
    "DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM",
    "DEVELOPMENT_CANDIDATE_MIGRATION_NAME",
    "DEVELOPMENT_CANDIDATE_MIGRATION_STATEMENTS",
    "DEVELOPMENT_CANDIDATE_SCHEMA_VERSION",
]
