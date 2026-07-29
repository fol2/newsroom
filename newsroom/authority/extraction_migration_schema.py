from __future__ import annotations

_PRODUCERS = "'DETERMINISTIC_FAKE','APPROVED_REPLAY'"
_PROFILES = "'FIXTURE','REPLAY'"
_OUTCOMES = (
    "'SUCCESS','PARTIAL','RETRYABLE_FAILURE','BLOCKING_FAILURE','INVALID_OUTPUT'"
)
_OUTPUT_KINDS = "'INLINE_STRUCTURED','GOVERNED_OBJECT_REFERENCE'"
_COMPLETENESS = "'COMPLETE','PARTIAL'"
_PROPOSAL_KINDS = (
    "'ENTITY_MENTION','ENTITY_ALIAS','ENTITY_EQUIVALENCE','RELATION',"
    "'TEMPORAL_CLAIM','OTHER_STRUCTURED'"
)
_ENDPOINT_KINDS = "'MENTION','LITERAL','UNKNOWN'"
_UNCERTAINTY = "'LOW','MEDIUM','HIGH','UNKNOWN'"
_RUNTIME_AUTHORITY_DISABLED = "FIXTURE_REPLAY_ONLY_DISABLED"


EXTRACTION_AUTHORITY_SCHEMA_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE extractor_contracts(
        contract_id TEXT PRIMARY KEY,
        contract_family TEXT NOT NULL,
        version_number INTEGER NOT NULL CHECK(version_number>0),
        previous_contract_id TEXT REFERENCES extractor_contracts(contract_id),
        framework_bytes BLOB NOT NULL,
        model_placeholder_bytes BLOB NOT NULL,
        prompt_contract_bytes BLOB NOT NULL,
        output_schema_contract_bytes BLOB NOT NULL,
        code_contract_bytes BLOB NOT NULL,
        normalization_contract_bytes BLOB NOT NULL,
        extraction_policy_bytes BLOB NOT NULL,
        producer_kind TEXT NOT NULL CHECK(producer_kind IN({_PRODUCERS})),
        execution_profile TEXT NOT NULL CHECK(execution_profile IN({_PROFILES})),
        resource_bounds_bytes BLOB NOT NULL,
        max_input_bytes INTEGER NOT NULL CHECK(max_input_bytes>0),
        max_output_bytes INTEGER NOT NULL CHECK(max_output_bytes>0),
        max_proposals INTEGER NOT NULL CHECK(max_proposals>0),
        max_attempts INTEGER NOT NULL CHECK(max_attempts>0),
        max_duration_ms INTEGER NOT NULL CHECK(max_duration_ms>0),
        max_input_tokens INTEGER NOT NULL CHECK(max_input_tokens>=0),
        max_output_tokens INTEGER NOT NULL CHECK(max_output_tokens>=0),
        max_cost_microunits INTEGER NOT NULL CHECK(max_cost_microunits>=0),
        runtime_authority TEXT NOT NULL
            CHECK(runtime_authority='{_RUNTIME_AUTHORITY_DISABLED}'),
        registered_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(contract_family,version_number),
        UNIQUE(contract_family,semantic_digest),
        UNIQUE(contract_family,version_number,contract_id),
        CHECK((version_number=1 AND previous_contract_id IS NULL)
           OR (version_number>1 AND previous_contract_id IS NOT NULL)),
        CHECK(length(canonical_bytes)>0),
        CHECK(length(resource_bounds_bytes)>0)
    ) STRICT""",
    """CREATE TABLE extractor_contract_heads(
        contract_family TEXT PRIMARY KEY,
        current_version_number INTEGER NOT NULL CHECK(current_version_number>0),
        current_contract_id TEXT NOT NULL UNIQUE,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(contract_family,current_version_number,current_contract_id)
            REFERENCES extractor_contracts(
                contract_family,version_number,contract_id
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    """CREATE TABLE extraction_runs(
        run_id TEXT PRIMARY KEY,
        contract_id TEXT NOT NULL REFERENCES extractor_contracts(contract_id),
        contract_digest TEXT NOT NULL,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        representation_id TEXT NOT NULL,
        rights_decision_id TEXT NOT NULL,
        rights_policy_version TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        source_retention_scope TEXT NOT NULL,
        input_manifest_bytes BLOB NOT NULL,
        input_manifest_digest TEXT NOT NULL,
        producer_id TEXT NOT NULL,
        producer_version TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        FOREIGN KEY(item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        FOREIGN KEY(revision_id,item_id)
            REFERENCES source_revisions(revision_id,item_id),
        FOREIGN KEY(revision_id,definition_id)
            REFERENCES source_revisions(revision_id,definition_id),
        FOREIGN KEY(representation_id,revision_id)
            REFERENCES discovery_representations(representation_id,revision_id),
        UNIQUE(run_id,contract_id),
        CHECK(length(input_manifest_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE extraction_passages(
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        passage_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK(ordinal>=0),
        source_field TEXT NOT NULL,
        start_offset INTEGER NOT NULL CHECK(start_offset>=0),
        end_offset INTEGER NOT NULL CHECK(end_offset>start_offset),
        text_digest TEXT NOT NULL,
        language TEXT NOT NULL,
        object_admission_id TEXT REFERENCES object_admissions(admission_id),
        hydration_digest TEXT,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(run_id,passage_id),
        UNIQUE(run_id,ordinal),
        CHECK((object_admission_id IS NULL AND hydration_digest IS NULL)
           OR (object_admission_id IS NOT NULL AND hydration_digest IS NOT NULL)),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE extraction_attempts(
        attempt_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        attempt_number INTEGER NOT NULL CHECK(attempt_number>0),
        previous_attempt_id TEXT REFERENCES extraction_attempts(attempt_id),
        outcome TEXT NOT NULL CHECK(outcome IN({_OUTCOMES})),
        producer_execution_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        input_bytes INTEGER NOT NULL CHECK(input_bytes>=0),
        output_bytes INTEGER NOT NULL CHECK(output_bytes>=0),
        input_tokens INTEGER NOT NULL CHECK(input_tokens>=0),
        output_tokens INTEGER NOT NULL CHECK(output_tokens>=0),
        cost_microunits INTEGER NOT NULL CHECK(cost_microunits>=0),
        error_code TEXT,
        error_summary TEXT,
        semantic_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(run_id,attempt_number),
        UNIQUE(run_id,producer_execution_id),
        UNIQUE(attempt_id,run_id),
        UNIQUE(run_id,attempt_number,attempt_id),
        CHECK((attempt_number=1 AND previous_attempt_id IS NULL)
           OR (attempt_number>1 AND previous_attempt_id IS NOT NULL)),
        CHECK(ended_at>=started_at),
        CHECK((outcome IN('RETRYABLE_FAILURE','BLOCKING_FAILURE')
               AND error_code IS NOT NULL AND error_summary IS NOT NULL)
           OR (outcome NOT IN('RETRYABLE_FAILURE','BLOCKING_FAILURE')
               AND error_code IS NULL AND error_summary IS NULL)),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE extraction_attempt_heads(
        run_id TEXT PRIMARY KEY REFERENCES extraction_runs(run_id),
        current_attempt_number INTEGER NOT NULL CHECK(current_attempt_number>0),
        current_attempt_id TEXT NOT NULL UNIQUE,
        current_outcome TEXT NOT NULL CHECK(current_outcome IN({_OUTCOMES})),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(run_id,current_attempt_number,current_attempt_id)
            REFERENCES extraction_attempts(run_id,attempt_number,attempt_id)
            DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE extraction_outputs(
        output_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        attempt_id TEXT NOT NULL UNIQUE,
        output_kind TEXT NOT NULL CHECK(output_kind IN({_OUTPUT_KINDS})),
        output_schema_digest TEXT NOT NULL,
        structured_output_bytes BLOB,
        object_admission_id TEXT REFERENCES object_admissions(admission_id),
        hydration_digest TEXT,
        output_digest TEXT NOT NULL,
        valid INTEGER NOT NULL CHECK(valid IN(0,1)),
        validation_errors_bytes BLOB NOT NULL,
        retained_at TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(attempt_id,run_id)
            REFERENCES extraction_attempts(attempt_id,run_id),
        UNIQUE(output_id,run_id),
        UNIQUE(output_id,attempt_id),
        CHECK((output_kind='INLINE_STRUCTURED'
               AND structured_output_bytes IS NOT NULL
               AND object_admission_id IS NULL AND hydration_digest IS NULL)
           OR (output_kind='GOVERNED_OBJECT_REFERENCE'
               AND structured_output_bytes IS NULL
               AND object_admission_id IS NOT NULL AND hydration_digest IS NOT NULL)),
        CHECK((valid=1 AND length(validation_errors_bytes)=2)
           OR (valid=0 AND length(validation_errors_bytes)>2)),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE extraction_proposal_sets(
        proposal_set_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        attempt_id TEXT NOT NULL,
        output_id TEXT NOT NULL UNIQUE,
        completeness TEXT NOT NULL CHECK(completeness IN({_COMPLETENESS})),
        proposal_count INTEGER NOT NULL CHECK(proposal_count>=0),
        semantic_digest TEXT NOT NULL UNIQUE,
        retained_at TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(attempt_id,run_id)
            REFERENCES extraction_attempts(attempt_id,run_id),
        FOREIGN KEY(output_id,run_id)
            REFERENCES extraction_outputs(output_id,run_id),
        FOREIGN KEY(output_id,attempt_id)
            REFERENCES extraction_outputs(output_id,attempt_id),
        UNIQUE(proposal_set_id,run_id),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE extraction_proposals(
        proposal_id TEXT PRIMARY KEY,
        proposal_set_id TEXT NOT NULL REFERENCES extraction_proposal_sets(proposal_set_id),
        run_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        output_id TEXT NOT NULL,
        producer_local_id TEXT NOT NULL,
        proposal_kind TEXT NOT NULL CHECK(proposal_kind IN({_PROPOSAL_KINDS})),
        subject_kind TEXT NOT NULL CHECK(subject_kind IN({_ENDPOINT_KINDS})),
        subject_bytes BLOB NOT NULL,
        object_kind TEXT CHECK(object_kind IS NULL OR object_kind IN({_ENDPOINT_KINDS})),
        object_bytes BLOB,
        predicate_hint TEXT,
        passage_ids_bytes BLOB NOT NULL,
        confidence_basis_points INTEGER NOT NULL
            CHECK(confidence_basis_points BETWEEN 0 AND 10000),
        uncertainty TEXT NOT NULL CHECK(uncertainty IN({_UNCERTAINTY})),
        uncertainty_reasons_bytes BLOB NOT NULL,
        attributes_bytes BLOB NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        UNIQUE(proposal_set_id,producer_local_id),
        FOREIGN KEY(proposal_set_id,run_id)
            REFERENCES extraction_proposal_sets(proposal_set_id,run_id),
        FOREIGN KEY(output_id,run_id)
            REFERENCES extraction_outputs(output_id,run_id),
        FOREIGN KEY(attempt_id,run_id)
            REFERENCES extraction_attempts(attempt_id,run_id),
        CHECK((proposal_kind='RELATION'
               AND object_kind IS NOT NULL AND object_bytes IS NOT NULL
               AND predicate_hint IS NOT NULL)
           OR (proposal_kind!='RELATION' AND predicate_hint IS NULL)),
        CHECK((object_kind IS NULL AND object_bytes IS NULL)
           OR (object_kind IS NOT NULL AND object_bytes IS NOT NULL)),
        CHECK(length(subject_bytes)>0),
        CHECK(length(passage_ids_bytes)>0),
        CHECK(length(uncertainty_reasons_bytes)>0),
        CHECK(length(attributes_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE extraction_proposal_passages(
        proposal_id TEXT NOT NULL REFERENCES extraction_proposals(proposal_id),
        run_id TEXT NOT NULL,
        passage_id TEXT NOT NULL,
        PRIMARY KEY(proposal_id,passage_id),
        FOREIGN KEY(run_id,passage_id)
            REFERENCES extraction_passages(run_id,passage_id)
    ) WITHOUT ROWID, STRICT""",
    "CREATE INDEX idx_extractor_contract_family ON extractor_contracts(contract_family,version_number)",
    "CREATE INDEX idx_extraction_runs_revision ON extraction_runs(revision_id,recorded_at)",
    "CREATE INDEX idx_extraction_runs_representation ON extraction_runs(representation_id,recorded_at)",
    "CREATE INDEX idx_extraction_attempts_run ON extraction_attempts(run_id,attempt_number)",
    "CREATE INDEX idx_extraction_proposals_set ON extraction_proposals(proposal_set_id,proposal_kind)",
    "CREATE INDEX idx_extraction_proposals_run ON extraction_proposals(run_id,proposal_kind)",
)


__all__ = ["EXTRACTION_AUTHORITY_SCHEMA_STATEMENTS"]
