from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


HYBRID_RETRIEVAL_SCHEMA_VERSION = 8
HYBRID_RETRIEVAL_MIGRATION_NAME = "hybrid_retrieval_authority_v8"


@dataclass(frozen=True, slots=True)
class HybridRetrievalMigrationRecord:
    version: int
    name: str
    checksum: str


HYBRID_RETRIEVAL_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE hybrid_retrieval_attempts(
        request_id TEXT PRIMARY KEY,
        context_id TEXT NOT NULL UNIQUE,
        idempotency_key TEXT NOT NULL UNIQUE,
        request_digest TEXT NOT NULL UNIQUE,
        request_bytes BLOB NOT NULL,
        fixture_id TEXT NOT NULL,
        query_revision_id TEXT NOT NULL,
        query_hypothesis_version_id TEXT NOT NULL,
        query_valid_time TEXT NOT NULL,
        tool_name TEXT NOT NULL
            CHECK(tool_name='find_related_event_candidates'),
        tool_version TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        retrieval_contract_digest TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN(
            'COMPLETE','DEGRADED','STALE','UNAVAILABLE','INCOMPLETE','POLICY_BLOCKED'
        )),
        failure_code TEXT,
        generation_id TEXT REFERENCES projection_generations(generation_id),
        projection_identity_digest TEXT,
        authority_watermark INTEGER CHECK(
            authority_watermark IS NULL OR authority_watermark > 0
        ),
        context_digest TEXT UNIQUE,
        authentication_context_id TEXT NOT NULL
            REFERENCES authentication_contexts(authentication_context_id),
        authorization_request_digest TEXT NOT NULL,
        authorization_decision_id TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(authorization_request_digest,authentication_context_id)
            REFERENCES authorization_requests(
                request_digest,authentication_context_id
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
        CHECK(length(request_bytes)>0),
        CHECK(length(canonical_bytes)>0),
        CHECK(
            (generation_id IS NULL
             AND projection_identity_digest IS NULL
             AND authority_watermark IS NULL)
            OR
            (generation_id IS NOT NULL
             AND projection_identity_digest IS NOT NULL
             AND authority_watermark IS NOT NULL)
        ),
        CHECK(
            (outcome='COMPLETE'
             AND failure_code IS NULL
             AND generation_id IS NOT NULL
             AND projection_identity_digest IS NOT NULL
             AND authority_watermark IS NOT NULL
             AND context_digest IS NOT NULL)
            OR
            (outcome!='COMPLETE'
             AND failure_code IS NOT NULL
             AND context_digest IS NULL)
        )
    ) STRICT""",
    """CREATE TABLE hybrid_retrieval_contexts_v2(
        context_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL UNIQUE
            REFERENCES hybrid_retrieval_attempts(request_id),
        context_digest TEXT NOT NULL UNIQUE,
        generation_id TEXT NOT NULL
            REFERENCES projection_generations(generation_id),
        family_id TEXT NOT NULL,
        projection_identity_digest TEXT NOT NULL,
        contiguous_ledger_seq INTEGER NOT NULL CHECK(contiguous_ledger_seq>0),
        open_gap_count INTEGER NOT NULL CHECK(open_gap_count=0),
        dead_letter_count INTEGER NOT NULL CHECK(dead_letter_count=0),
        policy_digest TEXT NOT NULL,
        query_digest TEXT NOT NULL,
        total_context_bytes INTEGER NOT NULL
            CHECK(total_context_bytes>=0 AND total_context_bytes<=262144),
        truncated INTEGER NOT NULL CHECK(truncated=0),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE hybrid_retrieval_context_hydrations(
        context_id TEXT NOT NULL
            REFERENCES hybrid_retrieval_contexts_v2(context_id),
        passage_id TEXT NOT NULL,
        admission_id TEXT NOT NULL
            REFERENCES object_admissions(admission_id),
        access_decision_id TEXT NOT NULL UNIQUE
            REFERENCES object_access_decisions(access_decision_id),
        blob_digest TEXT NOT NULL,
        text_digest TEXT NOT NULL,
        hydration_policy_contract_digest TEXT NOT NULL
            REFERENCES hydration_policy_contracts(contract_digest),
        byte_start INTEGER NOT NULL CHECK(byte_start=0),
        byte_end INTEGER NOT NULL CHECK(byte_end>0),
        rights_state TEXT NOT NULL,
        lifecycle_state TEXT NOT NULL,
        trust_scope TEXT NOT NULL CHECK(trust_scope='OBSERVED'),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(context_id,passage_id),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE INDEX idx_hybrid_retrieval_attempt_outcome
        ON hybrid_retrieval_attempts(outcome,recorded_at)""",
    """CREATE INDEX idx_hybrid_retrieval_attempt_generation
        ON hybrid_retrieval_attempts(generation_id,authority_watermark)""",
    """CREATE INDEX idx_hybrid_retrieval_hydration_admission
        ON hybrid_retrieval_context_hydrations(admission_id,passage_id)""",
    """CREATE TRIGGER immutable_hybrid_retrieval_attempt_update
        BEFORE UPDATE ON hybrid_retrieval_attempts BEGIN
        SELECT RAISE(ABORT,'immutable hybrid retrieval attempt'); END""",
    """CREATE TRIGGER immutable_hybrid_retrieval_attempt_delete
        BEFORE DELETE ON hybrid_retrieval_attempts BEGIN
        SELECT RAISE(ABORT,'hybrid retrieval attempts are retained'); END""",
    """CREATE TRIGGER immutable_hybrid_retrieval_context_update
        BEFORE UPDATE ON hybrid_retrieval_contexts_v2 BEGIN
        SELECT RAISE(ABORT,'immutable retrieval context v2'); END""",
    """CREATE TRIGGER immutable_hybrid_retrieval_context_delete
        BEFORE DELETE ON hybrid_retrieval_contexts_v2 BEGIN
        SELECT RAISE(ABORT,'retrieval contexts v2 are retained'); END""",
    """CREATE TRIGGER immutable_hybrid_retrieval_hydration_update
        BEFORE UPDATE ON hybrid_retrieval_context_hydrations BEGIN
        SELECT RAISE(ABORT,'immutable retrieval hydration linkage'); END""",
    """CREATE TRIGGER immutable_hybrid_retrieval_hydration_delete
        BEFORE DELETE ON hybrid_retrieval_context_hydrations BEGIN
        SELECT RAISE(ABORT,'retrieval hydration linkages are retained'); END""",
)


HYBRID_RETRIEVAL_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": HYBRID_RETRIEVAL_SCHEMA_VERSION,
        "name": HYBRID_RETRIEVAL_MIGRATION_NAME,
        "statements": list(HYBRID_RETRIEVAL_MIGRATION_STATEMENTS),
    }
)
HYBRID_RETRIEVAL_MIGRATION = HybridRetrievalMigrationRecord(
    version=HYBRID_RETRIEVAL_SCHEMA_VERSION,
    name=HYBRID_RETRIEVAL_MIGRATION_NAME,
    checksum=HYBRID_RETRIEVAL_MIGRATION_CHECKSUM,
)


__all__ = [
    "HYBRID_RETRIEVAL_MIGRATION",
    "HYBRID_RETRIEVAL_MIGRATION_CHECKSUM",
    "HYBRID_RETRIEVAL_MIGRATION_NAME",
    "HYBRID_RETRIEVAL_MIGRATION_STATEMENTS",
    "HYBRID_RETRIEVAL_SCHEMA_VERSION",
]
