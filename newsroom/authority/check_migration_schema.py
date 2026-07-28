from __future__ import annotations


CHECK_AUTHORITY_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE check_requests(
        request_id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        trigger_kind TEXT NOT NULL CHECK(trigger_kind IN('FIXTURE_MANUAL','APPROVED_REPLAY','PLANNED_WINDOW','DELIVERED_INPUT','LINKED_FOLLOWUP','RESET_REBUILD')),
        trigger_id TEXT NOT NULL,
        trigger_version TEXT NOT NULL,
        expected_window_digest TEXT,
        coverage_obligation_id TEXT NOT NULL,
        coverage_responsibility TEXT NOT NULL
            CHECK(coverage_responsibility IN('ACTIVE','BEST_EFFORT','EXPLICIT_DEFERRED_GAP','OPERATIONAL_RESILIENCE','EVALUATION')),
        coverage_contribution TEXT NOT NULL
            CHECK(coverage_contribution IN('DETECTION_PATH','OCCURRENCE_CONFIRMATION','REVISION_VISIBILITY','URGENT_FAST_PATH','REDUNDANCY','COMPARATOR')),
        coverage_policy_id TEXT NOT NULL,
        coverage_policy_version TEXT NOT NULL,
        rights_decision_id TEXT NOT NULL,
        rights_policy_version TEXT NOT NULL,
        adapter_request_digest TEXT NOT NULL,
        producer_slot_digest TEXT NOT NULL,
        baseline_policy_id TEXT NOT NULL,
        baseline_policy_version TEXT NOT NULL,
        revision_policy_id TEXT NOT NULL,
        revision_policy_version TEXT NOT NULL,
        transition_policy_id TEXT NOT NULL,
        transition_policy_version TEXT NOT NULL,
        validator_policy_id TEXT NOT NULL,
        validator_policy_version TEXT NOT NULL,
        purpose TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(request_id,definition_id,definition_version_id),
        UNIQUE(request_id,adapter_request_digest),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        CHECK((trigger_kind='PLANNED_WINDOW' AND expected_window_digest IS NOT NULL)
           OR (trigger_kind!='PLANNED_WINDOW' AND expected_window_digest IS NULL)),
        CHECK(length(trigger_id)>0),
        CHECK(length(trigger_version)>0),
        CHECK(length(purpose)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE check_attempts(
        attempt_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES check_requests(request_id),
        attempt_number INTEGER NOT NULL CHECK(attempt_number>0),
        kind TEXT NOT NULL CHECK(kind IN('PRIMARY','RETRY','REPLAY','CONFIRMATION')),
        prior_attempt_id TEXT REFERENCES check_attempts(attempt_id),
        adapter_request_id TEXT NOT NULL,
        adapter_request_digest TEXT NOT NULL,
        started_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(request_id,attempt_number),
        UNIQUE(attempt_id,request_id),
        FOREIGN KEY(request_id,adapter_request_digest)
            REFERENCES check_requests(request_id,adapter_request_digest),
        CHECK((attempt_number=1 AND kind='PRIMARY' AND prior_attempt_id IS NULL)
           OR (attempt_number>1 AND prior_attempt_id IS NOT NULL)),
        CHECK(prior_attempt_id IS NULL OR prior_attempt_id!=attempt_id),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE check_outcomes(
        outcome_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL UNIQUE,
        proposal_id TEXT NOT NULL UNIQUE,
        definition_id TEXT NOT NULL,
        definition_version_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN('BLOCKED','SUCCESS_EMPTY','SUCCESS_UNCHANGED','SUCCESS_CHANGED','SUCCESS_PARTIAL','SUCCESS_TRUNCATED','REDIRECTED','RATE_LIMITED','UNAUTHORISED','NOT_FOUND','GONE','MALFORMED','SHAPE_DRIFT','TRANSPORT_FAILED','QUARANTINED_DISABLED')),
        reason_codes_bytes BLOB NOT NULL,
        quarantine TEXT NOT NULL CHECK(quarantine IN('NONE','REVIEW','QUARANTINE')),
        incomplete INTEGER NOT NULL CHECK(incomplete IN(0,1)),
        receipt_digest TEXT,
        capture_digest TEXT,
        parser_result_digest TEXT,
        source_body_digest TEXT,
        producer_slot_digest TEXT,
        representation_digest TEXT,
        validator_digest TEXT,
        candidate_observations_bytes BLOB NOT NULL,
        candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
        observed_items_bytes BLOB NOT NULL,
        observed_item_count INTEGER NOT NULL CHECK(observed_item_count>=0),
        completed_at TEXT NOT NULL,
        admission_semantic_digest TEXT,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(outcome_id,request_id),
        UNIQUE(outcome_id,attempt_id),
        UNIQUE(outcome_id,definition_id,definition_version_id),
        FOREIGN KEY(attempt_id,request_id)
            REFERENCES check_attempts(attempt_id,request_id),
        FOREIGN KEY(request_id,definition_id,definition_version_id)
            REFERENCES check_requests(
                request_id,definition_id,definition_version_id
            ),
        CHECK((kind IN('SUCCESS_CHANGED','SUCCESS_PARTIAL','SUCCESS_TRUNCATED') AND candidate_count>0)
           OR (kind NOT IN('SUCCESS_CHANGED','SUCCESS_PARTIAL','SUCCESS_TRUNCATED') AND candidate_count=0)),
        CHECK((kind IN('SUCCESS_CHANGED','SUCCESS_PARTIAL','SUCCESS_TRUNCATED')
               AND observed_item_count=candidate_count)
           OR kind='SUCCESS_UNCHANGED'
           OR (kind NOT IN('SUCCESS_CHANGED','SUCCESS_PARTIAL','SUCCESS_TRUNCATED','SUCCESS_UNCHANGED')
               AND observed_item_count=0)),
        CHECK((kind IN('BLOCKED','SUCCESS_PARTIAL','SUCCESS_TRUNCATED','REDIRECTED','RATE_LIMITED','UNAUTHORISED','NOT_FOUND','GONE','MALFORMED','SHAPE_DRIFT','TRANSPORT_FAILED','QUARANTINED_DISABLED') AND incomplete=1)
           OR (kind NOT IN('BLOCKED','SUCCESS_PARTIAL','SUCCESS_TRUNCATED','REDIRECTED','RATE_LIMITED','UNAUTHORISED','NOT_FOUND','GONE','MALFORMED','SHAPE_DRIFT','TRANSPORT_FAILED','QUARANTINED_DISABLED') AND incomplete=0)),
        CHECK(capture_digest IS NULL OR receipt_digest IS NOT NULL),
        CHECK(parser_result_digest IS NULL OR capture_digest IS NOT NULL),
        CHECK((source_body_digest IS NULL AND producer_slot_digest IS NULL
               AND representation_digest IS NULL)
           OR (source_body_digest IS NOT NULL AND producer_slot_digest IS NOT NULL
               AND representation_digest IS NOT NULL
               AND parser_result_digest IS NOT NULL)),
        CHECK(kind NOT IN('SUCCESS_CHANGED','SUCCESS_PARTIAL','SUCCESS_TRUNCATED')
              OR parser_result_digest IS NOT NULL),
        CHECK(kind NOT IN('MALFORMED','SHAPE_DRIFT')
              OR parser_result_digest IS NOT NULL),
        CHECK(kind NOT IN('BLOCKED','QUARANTINED_DISABLED')
              OR (receipt_digest IS NULL AND capture_digest IS NULL
                  AND parser_result_digest IS NULL)),
        CHECK(kind IN('BLOCKED','QUARANTINED_DISABLED')
              OR receipt_digest IS NOT NULL),
        CHECK(kind NOT IN('REDIRECTED','RATE_LIMITED','UNAUTHORISED',
                          'NOT_FOUND','GONE','TRANSPORT_FAILED')
              OR (capture_digest IS NULL AND parser_result_digest IS NULL)),
        CHECK(observed_item_count=0 OR parser_result_digest IS NOT NULL),
        CHECK(kind NOT IN('SHAPE_DRIFT','QUARANTINED_DISABLED')
              OR quarantine!='NONE'),
        CHECK(length(reason_codes_bytes)>0),
        CHECK(length(candidate_observations_bytes)>0),
        CHECK(length(observed_items_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE check_outcome_observed_items(
        outcome_id TEXT NOT NULL REFERENCES check_outcomes(outcome_id),
        item_key TEXT NOT NULL,
        item_digest TEXT NOT NULL,
        item_id TEXT NOT NULL,
        PRIMARY KEY(outcome_id,item_key),
        UNIQUE(outcome_id,item_id),
        CHECK(length(item_key)>0),
        CHECK(length(item_digest)>0),
        CHECK(length(item_id)>0)
    ) STRICT""",
    """CREATE INDEX idx_check_outcome_observed_item_id
        ON check_outcome_observed_items(item_id,outcome_id)""",
    """CREATE TABLE baseline_decisions(
        decision_id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        check_request_id TEXT NOT NULL REFERENCES check_requests(request_id),
        check_outcome_id TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL CHECK(kind IN('ESTABLISH','RESET','REBUILD')),
        disposition TEXT NOT NULL CHECK(disposition IN('MAINTAINED_BASELINE_ONLY','BOUNDED_BACKFILL','FIRST_OBSERVED_ACTIVE','FUTURE_EXPECTATIONS_ONLY','EXPLICIT_DELTA_SEQUENCE','MANUAL_HOLD')),
        observation_model TEXT NOT NULL CHECK(observation_model IN('APPEND_ONLY','MUTABLE_ITEM','COMPLETE_CURRENT_STATE','ROLLING_LIST','EXPLICIT_DELTA','PLANNED_AGENDA')),
        baseline_policy_id TEXT NOT NULL,
        baseline_policy_version TEXT NOT NULL,
        previous_decision_id TEXT REFERENCES baseline_decisions(decision_id),
        source_body_digest TEXT,
        producer_slot_digest TEXT,
        representation_digest TEXT,
        validator_digest TEXT,
        reason_codes_bytes BLOB NOT NULL,
        item_keys_digest TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(decision_id,definition_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        FOREIGN KEY(check_outcome_id,check_request_id)
            REFERENCES check_outcomes(outcome_id,request_id),
        CHECK((kind='ESTABLISH' AND previous_decision_id IS NULL)
           OR (kind IN('RESET','REBUILD') AND previous_decision_id IS NOT NULL)),
        CHECK(previous_decision_id IS NULL OR previous_decision_id!=decision_id),
        CHECK((source_body_digest IS NULL AND producer_slot_digest IS NULL
               AND representation_digest IS NULL)
           OR (source_body_digest IS NOT NULL AND producer_slot_digest IS NOT NULL
               AND representation_digest IS NOT NULL)),
        CHECK((observation_model='MUTABLE_ITEM'
               AND disposition IN('MAINTAINED_BASELINE_ONLY','MANUAL_HOLD'))
           OR (observation_model IN('APPEND_ONLY','ROLLING_LIST')
               AND disposition IN('BOUNDED_BACKFILL','MANUAL_HOLD'))
           OR (observation_model='COMPLETE_CURRENT_STATE'
               AND disposition IN('FIRST_OBSERVED_ACTIVE','MANUAL_HOLD'))
           OR (observation_model='PLANNED_AGENDA'
               AND disposition IN('FUTURE_EXPECTATIONS_ONLY','MANUAL_HOLD'))
           OR (observation_model='EXPLICIT_DELTA'
               AND disposition IN('EXPLICIT_DELTA_SEQUENCE','MANUAL_HOLD'))),
        CHECK(length(reason_codes_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE baseline_manifest_entries(
        decision_id TEXT NOT NULL REFERENCES baseline_decisions(decision_id),
        item_key TEXT NOT NULL,
        disposition TEXT NOT NULL CHECK(disposition IN('INCLUDED','EXCLUDED')),
        reason_code TEXT NOT NULL,
        item_id TEXT,
        revision_id TEXT,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(decision_id,item_key),
        FOREIGN KEY(revision_id,item_id)
            REFERENCES source_revisions(revision_id,item_id),
        CHECK((item_id IS NULL AND revision_id IS NULL)
           OR (item_id IS NOT NULL AND revision_id IS NOT NULL)),
        CHECK(disposition!='INCLUDED' OR item_id IS NOT NULL),
        CHECK(length(reason_code)>0),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE baseline_decision_heads(
        definition_id TEXT PRIMARY KEY REFERENCES source_definitions(definition_id),
        current_decision_id TEXT NOT NULL UNIQUE,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_decision_id,definition_id)
            REFERENCES baseline_decisions(decision_id,definition_id)
            DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    """CREATE TABLE observable_transitions(
        transition_id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        check_outcome_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN('FIRST_OBSERVED','REVISED','REOBSERVED','ACTIVATED','ESCALATED','DEESCALATED','RESOLVED_OR_CLEARED','EXPIRED','CANCELLED','WITHDRAWN','REPLACED','REACTIVATED','AGENDA_CREATED','AGENDA_RESCHEDULED','AGENDA_CANCELLED','AGENDA_MISSED_EXPECTATION','AGENDA_LATE_OCCURRENCE','AMBIGUOUS_ABSENCE')),
        basis TEXT NOT NULL CHECK(basis IN('REVISION','EXPLICIT_DELTA','COMPLETE_SNAPSHOT_ABSENCE','AGENDA_EXPECTATION')),
        observation_model TEXT NOT NULL CHECK(observation_model IN('APPEND_ONLY','MUTABLE_ITEM','COMPLETE_CURRENT_STATE','ROLLING_LIST','EXPLICIT_DELTA','PLANNED_AGENDA')),
        prior_revision_id TEXT,
        current_revision_id TEXT,
        representation_id TEXT,
        related_item_id TEXT,
        change_facets_bytes BLOB NOT NULL,
        transition_policy_id TEXT NOT NULL,
        transition_policy_version TEXT NOT NULL,
        absence_guard_bytes BLOB,
        agenda_guard_bytes BLOB,
        source_asserted_time_bytes BLOB NOT NULL,
        observed_at TEXT NOT NULL,
        transition_discriminator TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(transition_id,definition_id),
        UNIQUE(check_outcome_id,item_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        FOREIGN KEY(check_outcome_id,definition_id,definition_version_id)
            REFERENCES check_outcomes(
                outcome_id,definition_id,definition_version_id
            ),
        FOREIGN KEY(item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        FOREIGN KEY(prior_revision_id,item_id)
            REFERENCES source_revisions(revision_id,item_id),
        FOREIGN KEY(current_revision_id,item_id)
            REFERENCES source_revisions(revision_id,item_id),
        FOREIGN KEY(representation_id,current_revision_id)
            REFERENCES discovery_representations(representation_id,revision_id),
        FOREIGN KEY(related_item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        CHECK((current_revision_id IS NULL AND representation_id IS NULL)
           OR (current_revision_id IS NOT NULL AND representation_id IS NOT NULL)),
        CHECK((basis='COMPLETE_SNAPSHOT_ABSENCE' AND absence_guard_bytes IS NOT NULL)
           OR (basis!='COMPLETE_SNAPSHOT_ABSENCE' AND absence_guard_bytes IS NULL)),
        CHECK((kind='AGENDA_MISSED_EXPECTATION' AND agenda_guard_bytes IS NOT NULL)
           OR (kind!='AGENDA_MISSED_EXPECTATION' AND agenda_guard_bytes IS NULL)),
        CHECK(kind NOT LIKE 'AGENDA_%'
              OR (observation_model='PLANNED_AGENDA'
                  AND basis='AGENDA_EXPECTATION')),
        CHECK(kind NOT IN('FIRST_OBSERVED','ACTIVATED','AGENDA_CREATED')
              OR (prior_revision_id IS NULL AND current_revision_id IS NOT NULL)),
        CHECK(kind!='REOBSERVED'
              OR (prior_revision_id IS NOT NULL
                  AND prior_revision_id=current_revision_id)),
        CHECK(kind!='AMBIGUOUS_ABSENCE'
              OR (prior_revision_id IS NOT NULL
                  AND current_revision_id IS NULL
                  AND basis='COMPLETE_SNAPSHOT_ABSENCE')),
        CHECK(kind='REPLACED' OR related_item_id IS NULL),
        CHECK(kind!='REPLACED' OR
              (related_item_id IS NOT NULL AND related_item_id!=item_id)),
        CHECK(length(change_facets_bytes)>0),
        CHECK(length(source_asserted_time_bytes)>0),
        CHECK(length(transition_discriminator)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE operational_findings(
        finding_id TEXT PRIMARY KEY,
        scope_kind TEXT NOT NULL CHECK(scope_kind IN('SOURCE_DEFINITION','SOURCE_VERSION','CHECK_REQUEST','CHECK_ATTEMPT','CHECK_OUTCOME','SOURCE_ITEM','ADAPTER')),
        scope_id TEXT NOT NULL,
        category TEXT NOT NULL CHECK(category IN('IDENTITY_INTEGRITY','BASELINE_INTEGRITY','PARSER','RIGHTS','POLICY','TRANSPORT','SOURCE_CONTRACT','QUARANTINE','CONFIRMATION','STORE')),
        severity TEXT NOT NULL CHECK(severity IN('INFO','DEGRADED','BLOCKING','INTEGRITY')),
        finding_policy_id TEXT NOT NULL,
        finding_policy_version TEXT NOT NULL,
        summary TEXT NOT NULL,
        opened_by_request_id TEXT REFERENCES check_requests(request_id),
        opened_by_attempt_id TEXT REFERENCES check_attempts(attempt_id),
        opened_by_outcome_id TEXT REFERENCES check_outcomes(outcome_id),
        opened_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(opened_by_request_id IS NOT NULL
           OR opened_by_attempt_id IS NOT NULL
           OR opened_by_outcome_id IS NOT NULL),
        CHECK(length(summary)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE operational_finding_occurrences(
        occurrence_id TEXT PRIMARY KEY,
        finding_id TEXT NOT NULL REFERENCES operational_findings(finding_id),
        request_id TEXT REFERENCES check_requests(request_id),
        attempt_id TEXT REFERENCES check_attempts(attempt_id),
        outcome_id TEXT REFERENCES check_outcomes(outcome_id),
        code TEXT NOT NULL,
        detail_digest TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(request_id IS NOT NULL OR attempt_id IS NOT NULL
              OR outcome_id IS NOT NULL),
        CHECK(length(code)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE discovery_occurrence_check_links(
        occurrence_id TEXT PRIMARY KEY,
        check_outcome_id TEXT NOT NULL REFERENCES check_outcomes(outcome_id),
        FOREIGN KEY(occurrence_id,check_outcome_id)
            REFERENCES discovery_occurrences(occurrence_id,check_outcome_id)
    ) WITHOUT ROWID, STRICT""",
    """CREATE UNIQUE INDEX idx_discovery_occurrence_identity_outcome ON discovery_occurrences(occurrence_id,check_outcome_id)""",
    """CREATE INDEX idx_check_requests_source ON check_requests(definition_id,definition_version_id,recorded_at)""",
    """CREATE INDEX idx_check_attempts_request ON check_attempts(request_id,attempt_number)""",
    """CREATE INDEX idx_check_outcomes_request ON check_outcomes(request_id,completed_at)""",
    """CREATE INDEX idx_baseline_decisions_source ON baseline_decisions(definition_id,decided_at)""",
    """CREATE INDEX idx_observable_transitions_item ON observable_transitions(item_id,observed_at,recorded_at)""",
    """CREATE INDEX idx_operational_findings_scope ON operational_findings(scope_kind,scope_id,recorded_at)""",
    """CREATE INDEX idx_operational_finding_occurrences_case ON operational_finding_occurrences(finding_id,observed_at)""",
)


__all__ = ["CHECK_AUTHORITY_SCHEMA_STATEMENTS"]
