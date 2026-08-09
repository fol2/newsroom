from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


EVALUATION_HANDOFF_SCHEMA_VERSION = 17
EVALUATION_HANDOFF_MIGRATION_NAME = "evaluation_handoff_authority_v17"


@dataclass(frozen=True, slots=True)
class EvaluationHandoffMigrationRecord:
    version: int
    name: str
    checksum: str


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
        acknowledgement_id TEXT PRIMARY KEY,
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
        UNIQUE(recorded_handoff_id,acknowledgement_id),
        CHECK(substr(governing_manifest_digest,1,7)='sha256:'
              AND length(governing_manifest_digest)=71
              AND substr(governing_manifest_digest,8)
                  NOT GLOB '*[^0-9a-f]*'),
        CHECK(substr(response_digest,1,7)='sha256:'
              AND length(response_digest)=71
              AND substr(response_digest,8) NOT GLOB '*[^0-9a-f]*')
    ) STRICT""",
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
    "EVALUATION_HANDOFF_MIGRATION",
    "EVALUATION_HANDOFF_MIGRATION_CHECKSUM",
    "EVALUATION_HANDOFF_MIGRATION_NAME",
    "EVALUATION_HANDOFF_MIGRATION_STATEMENTS",
    "EVALUATION_HANDOFF_SCHEMA_VERSION",
]
