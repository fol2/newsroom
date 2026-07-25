from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


RELATION_SCHEMA_VERSION = 6
RELATION_MIGRATION_NAME = "governed_relation_authority_v6"


@dataclass(frozen=True, slots=True)
class RelationMigrationRecord:
    version: int
    name: str
    checksum: str


_PREDICATES = (
    "'SAME_EVENT_AS','DEVELOPMENT_OF','SAME_PROCESS_AS','CORRECTS',"
    "'SUPERSEDES','SUPPORTS','DISPUTES','CONTRADICTS','ABOUT_EVENT'"
)


RELATION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE integrated_fixture_v2_bindings(
        binding_id TEXT PRIMARY KEY,
        fixture_id TEXT NOT NULL,
        schema_version TEXT NOT NULL CHECK(schema_version='integrated_fixture_v2'),
        fixture_digest TEXT NOT NULL,
        manifest_admission_id TEXT NOT NULL
            REFERENCES object_admissions(admission_id),
        manifest_blob_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE
            REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(fixture_id, fixture_digest),
        CHECK(fixture_digest=manifest_blob_digest),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE integrated_fixture_v2_passage_objects(
        binding_id TEXT NOT NULL
            REFERENCES integrated_fixture_v2_bindings(binding_id),
        passage_id TEXT NOT NULL,
        revision_id TEXT,
        language TEXT NOT NULL CHECK(language IN('en-GB','zh-HK')),
        expected_lifecycle TEXT NOT NULL
            CHECK(expected_lifecycle IN('ACTIVE','TOMBSTONED')),
        eligible_for_relation_evidence INTEGER NOT NULL
            CHECK(eligible_for_relation_evidence IN(0,1)),
        admission_id TEXT NOT NULL REFERENCES object_admissions(admission_id),
        blob_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(binding_id, passage_id),
        UNIQUE(binding_id, admission_id),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE relation_proposals(
        proposal_id TEXT PRIMARY KEY,
        fixture_binding_id TEXT NOT NULL
            REFERENCES integrated_fixture_v2_bindings(binding_id),
        subject_type TEXT NOT NULL CHECK(subject_type IN(
            'SOURCE_REVISION','EVENT_HYPOTHESIS_VERSION','STORY_CANDIDATE_VERSION'
        )),
        subject_id TEXT NOT NULL,
        predicate TEXT NOT NULL CHECK(predicate IN({_PREDICATES})),
        object_type TEXT NOT NULL CHECK(object_type IN(
            'SOURCE_REVISION','EVENT_HYPOTHESIS_VERSION','STORY_CANDIDATE_VERSION'
        )),
        object_id TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_until TEXT,
        temporal_precision TEXT NOT NULL CHECK(temporal_precision='EXACT'),
        producer_kind TEXT NOT NULL CHECK(producer_kind IN(
            'DETERMINISTIC_RULE','EXTRACTOR','AUTHORISED_OPERATOR'
        )),
        producer_id TEXT NOT NULL,
        producer_version TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        statement TEXT NOT NULL,
        uncertainties_bytes BLOB NOT NULL,
        trust_scope TEXT NOT NULL CHECK(trust_scope='PROPOSED'),
        proposal_digest TEXT NOT NULL UNIQUE,
        semantic_slot_digest TEXT NOT NULL,
        semantic_identity_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_ledger_seq INTEGER NOT NULL UNIQUE CHECK(authority_ledger_seq>0),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(subject_type!=object_type OR subject_id!=object_id),
        CHECK(valid_until IS NULL OR valid_until>valid_from),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE relation_proposal_evidence(
        proposal_id TEXT NOT NULL REFERENCES relation_proposals(proposal_id),
        fixture_binding_id TEXT NOT NULL,
        passage_id TEXT NOT NULL,
        admission_id TEXT NOT NULL REFERENCES object_admissions(admission_id),
        blob_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(proposal_id, passage_id),
        FOREIGN KEY(fixture_binding_id, passage_id)
            REFERENCES integrated_fixture_v2_passage_objects(
                binding_id, passage_id
            ),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE relation_admission_decisions(
        decision_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL REFERENCES relation_proposals(proposal_id),
        decision_version INTEGER NOT NULL CHECK(decision_version>0),
        previous_decision_id TEXT REFERENCES relation_admission_decisions(decision_id),
        action TEXT NOT NULL CHECK(action IN(
            'ADMIT','REJECT','HOLD','INVALIDATE','REVOKE','SUPERSEDE'
        )),
        proposal_digest TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        decision_policy_version TEXT NOT NULL,
        successor_proposal_id TEXT REFERENCES relation_proposals(proposal_id),
        assertion_id TEXT UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_ledger_seq INTEGER NOT NULL UNIQUE CHECK(authority_ledger_seq>0),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version>0),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(proposal_id, decision_version),
        CHECK((decision_version=1 AND previous_decision_id IS NULL)
           OR (decision_version>1 AND previous_decision_id IS NOT NULL)),
        CHECK((action='ADMIT' AND assertion_id IS NOT NULL)
           OR (action!='ADMIT' AND assertion_id IS NULL)),
        CHECK((action='SUPERSEDE' AND successor_proposal_id IS NOT NULL)
           OR (action!='SUPERSEDE' AND successor_proposal_id IS NULL)),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE relation_decision_heads(
        proposal_id TEXT PRIMARY KEY REFERENCES relation_proposals(proposal_id),
        current_version INTEGER NOT NULL CHECK(current_version>0),
        decision_id TEXT NOT NULL UNIQUE REFERENCES relation_admission_decisions(decision_id),
        current_state TEXT NOT NULL CHECK(current_state IN(
            'HELD','REJECTED','ADMITTED','INVALIDATED','REVOKED','SUPERSEDED'
        )),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(proposal_id, current_version)
            REFERENCES relation_admission_decisions(proposal_id, decision_version)
            DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE relation_assertions(
        assertion_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL UNIQUE REFERENCES relation_proposals(proposal_id),
        admission_decision_id TEXT NOT NULL UNIQUE
            REFERENCES relation_admission_decisions(decision_id)
            DEFERRABLE INITIALLY DEFERRED,
        relation_key TEXT NOT NULL UNIQUE,
        subject_type TEXT NOT NULL CHECK(subject_type IN(
            'SOURCE_REVISION','EVENT_HYPOTHESIS_VERSION','STORY_CANDIDATE_VERSION'
        )),
        subject_id TEXT NOT NULL,
        predicate TEXT NOT NULL CHECK(predicate IN({_PREDICATES})),
        object_type TEXT NOT NULL CHECK(object_type IN(
            'SOURCE_REVISION','EVENT_HYPOTHESIS_VERSION','STORY_CANDIDATE_VERSION'
        )),
        object_id TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_until TEXT,
        temporal_precision TEXT NOT NULL CHECK(temporal_precision='EXACT'),
        producer_kind TEXT NOT NULL,
        producer_id TEXT NOT NULL,
        producer_version TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        statement TEXT NOT NULL,
        uncertainties_bytes BLOB NOT NULL,
        trust_scope TEXT NOT NULL CHECK(trust_scope='ADMITTED'),
        proposal_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        admitted_at TEXT NOT NULL,
        CHECK(subject_type!=object_type OR subject_id!=object_id),
        CHECK(valid_until IS NULL OR valid_until>valid_from),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE relation_assertion_evidence(
        assertion_id TEXT NOT NULL REFERENCES relation_assertions(assertion_id),
        proposal_id TEXT NOT NULL REFERENCES relation_proposals(proposal_id),
        fixture_binding_id TEXT NOT NULL,
        passage_id TEXT NOT NULL,
        admission_id TEXT NOT NULL REFERENCES object_admissions(admission_id),
        blob_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(assertion_id, passage_id),
        FOREIGN KEY(proposal_id, passage_id)
            REFERENCES relation_proposal_evidence(proposal_id, passage_id),
        FOREIGN KEY(fixture_binding_id, passage_id)
            REFERENCES integrated_fixture_v2_passage_objects(
                binding_id, passage_id
            ),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    "CREATE INDEX idx_relation_proposal_slot ON relation_proposals(semantic_slot_digest,recorded_at)",
    "CREATE INDEX idx_relation_decision_proposal ON relation_admission_decisions(proposal_id,decision_version)",
    "CREATE INDEX idx_relation_assertion_endpoints ON relation_assertions(subject_type,subject_id,predicate,object_type,object_id)",
    "CREATE INDEX idx_relation_evidence_admission ON relation_assertion_evidence(admission_id,assertion_id)",
    """CREATE TRIGGER immutable_fixture_v2_binding_update
        BEFORE UPDATE ON integrated_fixture_v2_bindings BEGIN
        SELECT RAISE(ABORT,'immutable integrated fixture v2 binding'); END""",
    """CREATE TRIGGER immutable_fixture_v2_binding_delete
        BEFORE DELETE ON integrated_fixture_v2_bindings BEGIN
        SELECT RAISE(ABORT,'integrated fixture v2 bindings are retained'); END""",
    """CREATE TRIGGER immutable_fixture_v2_passage_update
        BEFORE UPDATE ON integrated_fixture_v2_passage_objects BEGIN
        SELECT RAISE(ABORT,'immutable integrated fixture v2 passage'); END""",
    """CREATE TRIGGER immutable_fixture_v2_passage_delete
        BEFORE DELETE ON integrated_fixture_v2_passage_objects BEGIN
        SELECT RAISE(ABORT,'integrated fixture v2 passages are retained'); END""",
    """CREATE TRIGGER immutable_relation_proposal_update
        BEFORE UPDATE ON relation_proposals BEGIN
        SELECT RAISE(ABORT,'immutable relation proposal'); END""",
    """CREATE TRIGGER immutable_relation_proposal_delete
        BEFORE DELETE ON relation_proposals BEGIN
        SELECT RAISE(ABORT,'relation proposals are retained'); END""",
    """CREATE TRIGGER immutable_relation_proposal_evidence_update
        BEFORE UPDATE ON relation_proposal_evidence BEGIN
        SELECT RAISE(ABORT,'immutable relation proposal evidence'); END""",
    """CREATE TRIGGER immutable_relation_proposal_evidence_delete
        BEFORE DELETE ON relation_proposal_evidence BEGIN
        SELECT RAISE(ABORT,'relation proposal evidence is retained'); END""",
    """CREATE TRIGGER immutable_relation_decision_update
        BEFORE UPDATE ON relation_admission_decisions BEGIN
        SELECT RAISE(ABORT,'immutable relation admission decision'); END""",
    """CREATE TRIGGER immutable_relation_decision_delete
        BEFORE DELETE ON relation_admission_decisions BEGIN
        SELECT RAISE(ABORT,'relation admission decisions are retained'); END""",
    """CREATE TRIGGER relation_decision_head_insert_guard
        BEFORE INSERT ON relation_decision_heads
        WHEN NEW.current_version!=1 BEGIN
        SELECT RAISE(ABORT,'relation decision heads begin at version one'); END""",
    """CREATE TRIGGER relation_decision_head_update_guard
        BEFORE UPDATE ON relation_decision_heads
        WHEN NEW.proposal_id!=OLD.proposal_id
          OR NEW.current_version!=OLD.current_version+1
        BEGIN SELECT RAISE(ABORT,'invalid relation decision-head update'); END""",
    """CREATE TRIGGER relation_decision_head_delete_guard
        BEFORE DELETE ON relation_decision_heads BEGIN
        SELECT RAISE(ABORT,'relation decision heads are retained'); END""",
    """CREATE TRIGGER immutable_relation_assertion_update
        BEFORE UPDATE ON relation_assertions BEGIN
        SELECT RAISE(ABORT,'immutable relation assertion'); END""",
    """CREATE TRIGGER immutable_relation_assertion_delete
        BEFORE DELETE ON relation_assertions BEGIN
        SELECT RAISE(ABORT,'relation assertions are retained'); END""",
    """CREATE TRIGGER immutable_relation_assertion_evidence_update
        BEFORE UPDATE ON relation_assertion_evidence BEGIN
        SELECT RAISE(ABORT,'immutable relation assertion evidence'); END""",
    """CREATE TRIGGER immutable_relation_assertion_evidence_delete
        BEFORE DELETE ON relation_assertion_evidence BEGIN
        SELECT RAISE(ABORT,'relation assertion evidence is retained'); END""",
)


RELATION_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": RELATION_SCHEMA_VERSION,
        "name": RELATION_MIGRATION_NAME,
        "statements": list(RELATION_MIGRATION_STATEMENTS),
    }
)
RELATION_MIGRATION = RelationMigrationRecord(
    version=RELATION_SCHEMA_VERSION,
    name=RELATION_MIGRATION_NAME,
    checksum=RELATION_MIGRATION_CHECKSUM,
)


__all__ = [
    "RELATION_MIGRATION",
    "RELATION_MIGRATION_CHECKSUM",
    "RELATION_MIGRATION_NAME",
    "RELATION_MIGRATION_STATEMENTS",
    "RELATION_SCHEMA_VERSION",
]
