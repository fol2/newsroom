from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


EXTRACTION_AUTHORITY_SCHEMA_VERSION = 13
EXTRACTION_AUTHORITY_MIGRATION_NAME = "extraction_run_authority_v13"


@dataclass(frozen=True, slots=True)
class ExtractionAuthorityMigrationRecord:
    version: int
    name: str
    checksum: str


_OUTCOMES = (
    "'SUCCESS','PARTIAL','RETRYABLE_FAILURE','BLOCKING_FAILURE','INVALID_OUTPUT'"
)
_FAILURE_CODES = (
    "'NONE','FIXTURE_PARTIAL','FIXTURE_RETRYABLE','FIXTURE_BLOCKED',"
    "'OUTPUT_SCHEMA_INVALID','POLICY_BLOCKED','PRODUCER_INTERNAL_ERROR'"
)
_PROPOSAL_KINDS = (
    "'ENTITY_MENTION','ENTITY_EQUIVALENCE','RELATION','CLAIM'"
)
_PREDICATES = (
    "'SAME_EVENT_AS','DEVELOPMENT_OF','SAME_PROCESS_AS','CORRECTS',"
    "'SUPERSEDES','SUPPORTS','DISPUTES','ABOUT_EVENT'"
)


EXTRACTION_AUTHORITY_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE extractor_contracts(
        contract_id TEXT PRIMARY KEY,
        framework_id TEXT NOT NULL,
        framework_version TEXT NOT NULL,
        framework_digest TEXT NOT NULL,
        model_id TEXT NOT NULL,
        model_version TEXT NOT NULL,
        model_digest TEXT NOT NULL,
        prompt_id TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        prompt_digest TEXT NOT NULL,
        output_schema_id TEXT NOT NULL,
        output_schema_version TEXT NOT NULL,
        output_schema_digest TEXT NOT NULL,
        code_id TEXT NOT NULL,
        code_version TEXT NOT NULL,
        code_digest TEXT NOT NULL,
        normalisation_id TEXT NOT NULL,
        normalisation_version TEXT NOT NULL,
        normalisation_digest TEXT NOT NULL,
        policy_id TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        execution_profile TEXT NOT NULL
            CHECK(execution_profile='FIXTURE_REPLAY_ONLY'),
        producer_kind TEXT NOT NULL
            CHECK(producer_kind='DETERMINISTIC_FIXTURE'),
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE extraction_runs(
        run_id TEXT PRIMARY KEY,
        contract_id TEXT NOT NULL REFERENCES extractor_contracts(contract_id),
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        representation_id TEXT NOT NULL,
        input_binding_digest TEXT NOT NULL,
        budget_bytes BLOB NOT NULL,
        budget_digest TEXT NOT NULL,
        stable_semantic_digest TEXT NOT NULL UNIQUE,
        created_by_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        FOREIGN KEY(item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        FOREIGN KEY(revision_id,item_id)
            REFERENCES source_revisions(revision_id,item_id),
        FOREIGN KEY(representation_id,revision_id)
            REFERENCES discovery_representations(representation_id,revision_id),
        CHECK(length(budget_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE extraction_run_passages(
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        passage_id TEXT NOT NULL,
        admission_id TEXT NOT NULL REFERENCES object_admissions(admission_id),
        access_decision_id TEXT NOT NULL
            REFERENCES object_access_decisions(access_decision_id),
        hydration_policy_contract_digest TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        authority_domain TEXT NOT NULL,
        purpose TEXT NOT NULL,
        object_class TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        security_scope TEXT NOT NULL,
        retention_scope TEXT NOT NULL,
        byte_offset INTEGER NOT NULL CHECK(byte_offset=0),
        byte_length INTEGER NOT NULL CHECK(byte_length>0),
        blob_digest TEXT NOT NULL REFERENCES blob_identities(blob_digest),
        text_digest TEXT NOT NULL,
        language TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(run_id,passage_id),
        UNIQUE(run_id,access_decision_id),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE extraction_run_versions(
        run_version_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        version_number INTEGER NOT NULL CHECK(version_number>0),
        previous_run_version_id TEXT
            REFERENCES extraction_run_versions(run_version_id),
        contract_canonical_digest TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN({_OUTCOMES})),
        failure_code TEXT NOT NULL CHECK(failure_code IN({_FAILURE_CODES})),
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        elapsed_ms INTEGER NOT NULL CHECK(elapsed_ms>=0),
        input_bytes INTEGER NOT NULL CHECK(input_bytes>=0),
        output_bytes INTEGER NOT NULL CHECK(output_bytes>=0),
        proposal_count INTEGER NOT NULL CHECK(proposal_count>=0),
        evidence_range_count INTEGER NOT NULL CHECK(evidence_range_count>=0),
        request_tokens INTEGER NOT NULL CHECK(request_tokens>=0),
        response_tokens INTEGER NOT NULL CHECK(response_tokens>=0),
        cost_microunits INTEGER NOT NULL CHECK(cost_microunits>=0),
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        request_bytes BLOB NOT NULL,
        request_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(run_id,version_number),
        UNIQUE(run_version_id,run_id),
        UNIQUE(run_id,version_number,run_version_id),
        CHECK((version_number=1 AND previous_run_version_id IS NULL)
           OR (version_number>1 AND previous_run_version_id IS NOT NULL)),
        CHECK(started_at<=ended_at AND ended_at<=recorded_at),
        CHECK((outcome='SUCCESS' AND failure_code='NONE')
           OR (outcome='PARTIAL' AND failure_code='FIXTURE_PARTIAL')
           OR (outcome='RETRYABLE_FAILURE' AND failure_code IN(
                'FIXTURE_RETRYABLE','PRODUCER_INTERNAL_ERROR'))
           OR (outcome='BLOCKING_FAILURE' AND failure_code IN(
                'FIXTURE_BLOCKED','POLICY_BLOCKED'))
           OR (outcome='INVALID_OUTPUT'
               AND failure_code='OUTPUT_SCHEMA_INVALID')),
        CHECK(length(request_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE extraction_run_heads(
        run_id TEXT PRIMARY KEY REFERENCES extraction_runs(run_id),
        current_version_number INTEGER NOT NULL CHECK(current_version_number>0),
        current_run_version_id TEXT NOT NULL UNIQUE,
        terminal INTEGER NOT NULL CHECK(terminal IN(0,1)),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(run_id,current_version_number,current_run_version_id)
            REFERENCES extraction_run_versions(
                run_id,version_number,run_version_id
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    """CREATE TABLE extraction_outputs(
        output_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        run_version_id TEXT NOT NULL UNIQUE,
        validation_state TEXT NOT NULL CHECK(validation_state IN('VALID','INVALID')),
        schema_contract_digest TEXT NOT NULL,
        byte_length INTEGER NOT NULL CHECK(byte_length>0),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        retained_at TEXT NOT NULL,
        FOREIGN KEY(run_version_id,run_id)
            REFERENCES extraction_run_versions(run_version_id,run_id),
        CHECK(byte_length=length(canonical_bytes))
    ) STRICT""",
    """CREATE TABLE extraction_proposal_sets(
        proposal_set_id TEXT PRIMARY KEY,
        output_id TEXT NOT NULL UNIQUE REFERENCES extraction_outputs(output_id),
        run_id TEXT NOT NULL,
        run_version_id TEXT NOT NULL UNIQUE,
        proposal_count INTEGER NOT NULL CHECK(proposal_count>0),
        producer_contract_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        retained_at TEXT NOT NULL,
        FOREIGN KEY(run_version_id,run_id)
            REFERENCES extraction_run_versions(run_version_id,run_id),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE extraction_proposals(
        proposal_id TEXT PRIMARY KEY,
        proposal_set_id TEXT NOT NULL
            REFERENCES extraction_proposal_sets(proposal_set_id),
        output_id TEXT NOT NULL REFERENCES extraction_outputs(output_id),
        run_id TEXT NOT NULL,
        run_version_id TEXT NOT NULL,
        local_id TEXT NOT NULL,
        proposal_kind TEXT NOT NULL CHECK(proposal_kind IN({_PROPOSAL_KINDS})),
        subject_placeholder TEXT NOT NULL,
        object_placeholder TEXT,
        predicate_hint TEXT CHECK(predicate_hint IS NULL OR predicate_hint IN({_PREDICATES})),
        confidence_basis_points INTEGER
            CHECK(confidence_basis_points IS NULL OR
                  (confidence_basis_points>=0 AND confidence_basis_points<=10000)),
        uncertainty_codes_bytes BLOB NOT NULL,
        rationale_codes_bytes BLOB NOT NULL,
        producer_contract_digest TEXT NOT NULL,
        semantic_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        retained_at TEXT NOT NULL,
        UNIQUE(proposal_set_id,local_id),
        UNIQUE(proposal_set_id,semantic_digest),
        FOREIGN KEY(run_version_id,run_id)
            REFERENCES extraction_run_versions(run_version_id,run_id),
        CHECK((proposal_kind='RELATION' AND object_placeholder IS NOT NULL
               AND predicate_hint IS NOT NULL)
           OR (proposal_kind!='RELATION' AND predicate_hint IS NULL)),
        CHECK(length(subject_placeholder)>0),
        CHECK(length(uncertainty_codes_bytes)>0),
        CHECK(length(rationale_codes_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE extraction_proposal_evidence(
        proposal_id TEXT NOT NULL REFERENCES extraction_proposals(proposal_id),
        evidence_ordinal INTEGER NOT NULL CHECK(evidence_ordinal>0),
        run_id TEXT NOT NULL,
        passage_id TEXT NOT NULL,
        start_byte INTEGER NOT NULL CHECK(start_byte>=0),
        end_byte INTEGER NOT NULL CHECK(end_byte>start_byte),
        evidence_text_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(proposal_id,evidence_ordinal),
        UNIQUE(proposal_id,passage_id,start_byte,end_byte),
        FOREIGN KEY(run_id,passage_id)
            REFERENCES extraction_run_passages(run_id,passage_id),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    "CREATE INDEX idx_extraction_runs_source ON extraction_runs(definition_id,item_id,revision_id,representation_id)",
    "CREATE INDEX idx_extraction_versions_run ON extraction_run_versions(run_id,version_number)",
    "CREATE INDEX idx_extraction_proposals_run ON extraction_proposals(run_id,run_version_id,proposal_kind)",
    "CREATE INDEX idx_extraction_evidence_passage ON extraction_proposal_evidence(run_id,passage_id)",
    """CREATE TRIGGER immutable_extractor_contract_update
        BEFORE UPDATE ON extractor_contracts BEGIN
        SELECT RAISE(ABORT,'immutable extractor contract'); END""",
    """CREATE TRIGGER immutable_extractor_contract_delete
        BEFORE DELETE ON extractor_contracts BEGIN
        SELECT RAISE(ABORT,'extractor contracts are retained'); END""",
    """CREATE TRIGGER extraction_run_lineage_guard
        BEFORE INSERT ON extraction_runs
        WHEN NOT EXISTS(
            SELECT 1
            FROM source_items i
            JOIN source_revisions r
              ON r.revision_id=NEW.revision_id
             AND r.item_id=NEW.item_id
             AND r.definition_id=NEW.definition_id
            JOIN discovery_representations p
              ON p.representation_id=NEW.representation_id
             AND p.revision_id=NEW.revision_id
             AND p.definition_id=NEW.definition_id
            WHERE i.item_id=NEW.item_id
              AND i.definition_id=NEW.definition_id
              AND NEW.definition_version_id=p.definition_version_id
        )
        BEGIN SELECT RAISE(ABORT,'extraction run source lineage mismatch'); END""",
    """CREATE TRIGGER immutable_extraction_run_update
        BEFORE UPDATE ON extraction_runs BEGIN
        SELECT RAISE(ABORT,'immutable extraction run'); END""",
    """CREATE TRIGGER immutable_extraction_run_delete
        BEFORE DELETE ON extraction_runs BEGIN
        SELECT RAISE(ABORT,'extraction runs are retained'); END""",
    """CREATE TRIGGER extraction_passage_access_guard
        BEFORE INSERT ON extraction_run_passages
        WHEN NOT EXISTS(
            SELECT 1
            FROM object_access_decisions d
            JOIN object_admissions a ON a.admission_id=d.admission_id
            WHERE d.access_decision_id=NEW.access_decision_id
              AND d.admission_id=NEW.admission_id
              AND d.hydration_policy_contract_digest=
                    NEW.hydration_policy_contract_digest
              AND d.principal_id=NEW.principal_id
              AND d.authority_domain=NEW.authority_domain
              AND d.purpose=NEW.purpose
              AND d.object_class=NEW.object_class
              AND d.allowed_use=NEW.allowed_use
              AND d.security_scope=NEW.security_scope
              AND d.retention_scope=NEW.retention_scope
              AND d.byte_offset=NEW.byte_offset
              AND d.allowed_bytes=NEW.byte_length
              AND a.blob_digest=NEW.blob_digest
              AND NEW.text_digest=NEW.blob_digest
        )
        BEGIN SELECT RAISE(ABORT,'extraction passage access lineage mismatch'); END""",
    """CREATE TRIGGER immutable_extraction_passage_update
        BEFORE UPDATE ON extraction_run_passages BEGIN
        SELECT RAISE(ABORT,'immutable extraction passage'); END""",
    """CREATE TRIGGER immutable_extraction_passage_delete
        BEFORE DELETE ON extraction_run_passages BEGIN
        SELECT RAISE(ABORT,'extraction passages are retained'); END""",
    """CREATE TRIGGER extraction_run_version_chain_guard
        BEFORE INSERT ON extraction_run_versions
        WHEN (NEW.version_number=1 AND EXISTS(
                SELECT 1 FROM extraction_run_heads h
                WHERE h.run_id=NEW.run_id
             ))
          OR (NEW.version_number>1 AND NOT EXISTS(
                SELECT 1 FROM extraction_run_heads h
                WHERE h.run_id=NEW.run_id
                  AND h.current_run_version_id=NEW.previous_run_version_id
                  AND h.current_version_number=NEW.version_number-1
                  AND h.terminal=0
             ))
        BEGIN SELECT RAISE(ABORT,'extraction run version does not extend current head'); END""",
    """CREATE TRIGGER extraction_run_version_predecessor_guard
        BEFORE INSERT ON extraction_run_versions
        WHEN NEW.previous_run_version_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM extraction_run_versions p
            WHERE p.run_version_id=NEW.previous_run_version_id
              AND p.run_id=NEW.run_id
              AND p.version_number=NEW.version_number-1
              AND p.ended_at<=NEW.started_at
        )
        BEGIN SELECT RAISE(ABORT,'extraction run predecessor mismatch'); END""",
    """CREATE TRIGGER immutable_extraction_run_version_update
        BEFORE UPDATE ON extraction_run_versions BEGIN
        SELECT RAISE(ABORT,'immutable extraction run version'); END""",
    """CREATE TRIGGER immutable_extraction_run_version_delete
        BEFORE DELETE ON extraction_run_versions BEGIN
        SELECT RAISE(ABORT,'extraction run versions are retained'); END""",
    """CREATE TRIGGER extraction_run_head_insert_guard
        BEFORE INSERT ON extraction_run_heads
        WHEN NEW.current_version_number!=1
          OR NOT EXISTS(
              SELECT 1 FROM extraction_run_versions v
              WHERE v.run_id=NEW.run_id
                AND v.run_version_id=NEW.current_run_version_id
                AND v.version_number=1
                AND NEW.updated_at=v.recorded_at
                AND NEW.terminal=(v.outcome IN(
                    'SUCCESS','BLOCKING_FAILURE','INVALID_OUTPUT'
                ))
          )
        BEGIN SELECT RAISE(ABORT,'invalid initial extraction run head'); END""",
    """CREATE TRIGGER extraction_run_head_update_guard
        BEFORE UPDATE ON extraction_run_heads
        WHEN NEW.run_id!=OLD.run_id
          OR OLD.terminal!=0
          OR NEW.current_version_number!=OLD.current_version_number+1
          OR NOT EXISTS(
              SELECT 1 FROM extraction_run_versions v
              WHERE v.run_id=NEW.run_id
                AND v.run_version_id=NEW.current_run_version_id
                AND v.previous_run_version_id=OLD.current_run_version_id
                AND v.version_number=NEW.current_version_number
                AND NEW.updated_at=v.recorded_at
                AND NEW.terminal=(v.outcome IN(
                    'SUCCESS','BLOCKING_FAILURE','INVALID_OUTPUT'
                ))
          )
        BEGIN SELECT RAISE(ABORT,'invalid extraction run head update'); END""",
    """CREATE TRIGGER extraction_run_head_delete_guard
        BEFORE DELETE ON extraction_run_heads BEGIN
        SELECT RAISE(ABORT,'extraction run heads are retained'); END""",
    """CREATE TRIGGER extraction_run_version_create_head
        AFTER INSERT ON extraction_run_versions
        WHEN NEW.version_number=1
        BEGIN
            INSERT INTO extraction_run_heads(
                run_id,current_version_number,current_run_version_id,
                terminal,updated_at
            ) VALUES(
                NEW.run_id,NEW.version_number,NEW.run_version_id,
                NEW.outcome IN('SUCCESS','BLOCKING_FAILURE','INVALID_OUTPUT'),
                NEW.recorded_at
            );
        END""",
    """CREATE TRIGGER extraction_run_version_advance_head
        AFTER INSERT ON extraction_run_versions
        WHEN NEW.version_number>1
        BEGIN
            UPDATE extraction_run_heads
            SET current_version_number=NEW.version_number,
                current_run_version_id=NEW.run_version_id,
                terminal=NEW.outcome IN(
                    'SUCCESS','BLOCKING_FAILURE','INVALID_OUTPUT'
                ),
                updated_at=NEW.recorded_at
            WHERE run_id=NEW.run_id
              AND current_run_version_id=NEW.previous_run_version_id
              AND terminal=0;
        END""",
    """CREATE TRIGGER extraction_output_outcome_guard
        BEFORE INSERT ON extraction_outputs
        WHEN NOT EXISTS(
            SELECT 1 FROM extraction_run_versions v
            WHERE v.run_version_id=NEW.run_version_id
              AND v.run_id=NEW.run_id
              AND ((NEW.validation_state='VALID'
                    AND v.outcome IN('SUCCESS','PARTIAL'))
                OR (NEW.validation_state='INVALID'
                    AND v.outcome='INVALID_OUTPUT'))
              AND v.output_bytes=NEW.byte_length
        )
        BEGIN SELECT RAISE(ABORT,'extraction output/outcome mismatch'); END""",
    """CREATE TRIGGER immutable_extraction_output_update
        BEFORE UPDATE ON extraction_outputs BEGIN
        SELECT RAISE(ABORT,'immutable extraction output'); END""",
    """CREATE TRIGGER immutable_extraction_output_delete
        BEFORE DELETE ON extraction_outputs BEGIN
        SELECT RAISE(ABORT,'extraction outputs are retained'); END""",
    """CREATE TRIGGER extraction_proposal_set_guard
        BEFORE INSERT ON extraction_proposal_sets
        WHEN NOT EXISTS(
            SELECT 1
            FROM extraction_outputs o
            JOIN extraction_run_versions v
              ON v.run_version_id=NEW.run_version_id
             AND v.run_id=NEW.run_id
            WHERE o.output_id=NEW.output_id
              AND o.run_version_id=NEW.run_version_id
              AND o.run_id=NEW.run_id
              AND o.validation_state='VALID'
              AND v.outcome IN('SUCCESS','PARTIAL')
              AND v.proposal_count=NEW.proposal_count
        )
        BEGIN SELECT RAISE(ABORT,'proposal set requires valid retained output'); END""",
    """CREATE TRIGGER immutable_extraction_proposal_set_update
        BEFORE UPDATE ON extraction_proposal_sets BEGIN
        SELECT RAISE(ABORT,'immutable extraction proposal set'); END""",
    """CREATE TRIGGER immutable_extraction_proposal_set_delete
        BEFORE DELETE ON extraction_proposal_sets BEGIN
        SELECT RAISE(ABORT,'extraction proposal sets are retained'); END""",
    """CREATE TRIGGER extraction_proposal_lineage_guard
        BEFORE INSERT ON extraction_proposals
        WHEN NOT EXISTS(
            SELECT 1 FROM extraction_proposal_sets s
            WHERE s.proposal_set_id=NEW.proposal_set_id
              AND s.output_id=NEW.output_id
              AND s.run_id=NEW.run_id
              AND s.run_version_id=NEW.run_version_id
              AND s.producer_contract_digest=NEW.producer_contract_digest
        )
        BEGIN SELECT RAISE(ABORT,'proposal lineage mismatch'); END""",
    """CREATE TRIGGER immutable_extraction_proposal_update
        BEFORE UPDATE ON extraction_proposals BEGIN
        SELECT RAISE(ABORT,'immutable extraction proposal'); END""",
    """CREATE TRIGGER immutable_extraction_proposal_delete
        BEFORE DELETE ON extraction_proposals BEGIN
        SELECT RAISE(ABORT,'extraction proposals are retained'); END""",
    """CREATE TRIGGER extraction_evidence_range_guard
        BEFORE INSERT ON extraction_proposal_evidence
        WHEN NOT EXISTS(
            SELECT 1
            FROM extraction_proposals p
            JOIN extraction_run_passages r
              ON r.run_id=NEW.run_id
             AND r.passage_id=NEW.passage_id
            WHERE p.proposal_id=NEW.proposal_id
              AND p.run_id=NEW.run_id
              AND NEW.end_byte<=r.byte_length
        )
        BEGIN SELECT RAISE(ABORT,'proposal evidence passage/range mismatch'); END""",
    """CREATE TRIGGER immutable_extraction_evidence_update
        BEFORE UPDATE ON extraction_proposal_evidence BEGIN
        SELECT RAISE(ABORT,'immutable extraction proposal evidence'); END""",
    """CREATE TRIGGER immutable_extraction_evidence_delete
        BEFORE DELETE ON extraction_proposal_evidence BEGIN
        SELECT RAISE(ABORT,'extraction proposal evidence is retained'); END""",
)

EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": EXTRACTION_AUTHORITY_SCHEMA_VERSION,
        "name": EXTRACTION_AUTHORITY_MIGRATION_NAME,
        "statements": EXTRACTION_AUTHORITY_MIGRATION_STATEMENTS,
    }
)

EXTRACTION_AUTHORITY_MIGRATION = ExtractionAuthorityMigrationRecord(
    version=EXTRACTION_AUTHORITY_SCHEMA_VERSION,
    name=EXTRACTION_AUTHORITY_MIGRATION_NAME,
    checksum=EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM,
)


__all__ = [
    "EXTRACTION_AUTHORITY_MIGRATION",
    "EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM",
    "EXTRACTION_AUTHORITY_MIGRATION_NAME",
    "EXTRACTION_AUTHORITY_MIGRATION_STATEMENTS",
    "EXTRACTION_AUTHORITY_SCHEMA_VERSION",
]
