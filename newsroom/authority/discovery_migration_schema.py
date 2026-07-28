from __future__ import annotations


_GATE_OUTCOMES = (
    "'SIGNAL_SUPPRESSED_DUPLICATE','SIGNAL_SUPPRESSED_NON_CHANGE',"
    "'SIGNAL_REJECTED_CLEAR_EXCLUSION','SIGNAL_PROMOTED_TO_LEAD',"
    "'SIGNAL_OPERATIONAL_HOLD'"
)
_TERMINALITIES = (
    "'TERMINAL_EXACT_VERSION','PENDING_CONDITION',"
    "'RETRYABLE_SAME_REQUEST','OCCURRENCE_ONLY'"
)
_NEWNESS = (
    "'GENUINE_TRANSITION','EXACT_REPEAT','PARSER_ONLY',"
    "'EXPECTATION_ONLY','UNKNOWN'"
)
_TIME_VALIDITY = "'CURRENT','STALE','UNKNOWN','CONFLICTING'"
_SCOPE_DISPOSITIONS = "'ACCEPTED','CLEAR_EXCLUSION','AMBIGUOUS','UNKNOWN'"
_NEXT_ACTIONS = (
    "'CLOSE','QUEUE_TRIAGE','RETRY','REVIEW','WAIT_DEPENDENCY',"
    "'RESUME_ON_WATCH'"
)
_URGENCY_ROUTES = "'URGENT','TIME_SENSITIVE','PLANNED','ROUTINE'"
_ACTIVE_DISPOSITIONS = (
    "'LEAD_QUEUED_FOR_TRIAGE','LEAD_OPERATIONAL_HOLD','LEAD_WATCH_DEFER'"
)
_REASON_BASES = (
    "'DETERMINISTIC_OBSERVATION','DETERMINISTIC_POLICY',"
    "'SOURCE_ASSERTION','OPERATIONAL_ASSESSMENT'"
)
_TRANSITION_KINDS = (
    "'FIRST_OBSERVED','REVISED','REOBSERVED','ACTIVATED','ESCALATED',"
    "'DEESCALATED','RESOLVED_OR_CLEARED','EXPIRED','CANCELLED',"
    "'WITHDRAWN','REPLACED','REACTIVATED','AGENDA_CREATED',"
    "'AGENDA_RESCHEDULED','AGENDA_CANCELLED','AGENDA_MISSED_EXPECTATION',"
    "'AGENDA_LATE_OCCURRENCE','AMBIGUOUS_ABSENCE'"
)
_ROLES = (
    "'ORIGINATING_AUTHORITY','DIRECT_PRIMARY','OFFICIAL_SUMMARY',"
    "'CORROBORATING','DEPENDENT_REPUBLISHER','RADAR_ONLY','OTHER'"
)
_FUNCTIONS = "'ANCHOR','CORROBORATION','RADAR','AGENDA','OTHER'"
_DEPENDENCIES = (
    "'ORIGINATING_MATERIAL','REPUBLISHER','UPSTREAM_DATA',"
    "'SAME_INSTITUTION','OTHER'"
)
_RESPONSIBILITIES = "'ACTIVE','BEST_EFFORT','EXPLICIT_DEFERRED_GAP'"
_CONTRIBUTIONS = (
    "'DETECTION_PATH','CORROBORATION_PATH','AGENDA_PATH',"
    "'RADAR_PATH','OTHER'"
)


DISCOVERY_AUTHORITY_SCHEMA_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE discovery_signals(
        signal_id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        representation_id TEXT NOT NULL,
        check_outcome_id TEXT NOT NULL,
        occurrence_id TEXT NOT NULL UNIQUE,
        transition_id TEXT NOT NULL,
        purpose TEXT NOT NULL,
        discriminator TEXT NOT NULL,
        admission_policy_id TEXT NOT NULL,
        admission_policy_version TEXT NOT NULL,
        incomplete INTEGER NOT NULL CHECK(incomplete IN(0,1)),
        operational_finding_ids_bytes BLOB NOT NULL,
        operational_finding_count INTEGER NOT NULL
            CHECK(operational_finding_count>=0),
        admitted_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(signal_id,definition_id),
        UNIQUE(transition_id,purpose,discriminator),
        UNIQUE(
            signal_id,definition_id,definition_version_id,item_id,revision_id,
            representation_id,occurrence_id,transition_id
        ),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        FOREIGN KEY(item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        FOREIGN KEY(revision_id,item_id)
            REFERENCES source_revisions(revision_id,item_id),
        FOREIGN KEY(representation_id,revision_id)
            REFERENCES discovery_representations(representation_id,revision_id),
        FOREIGN KEY(check_outcome_id,definition_id,definition_version_id)
            REFERENCES check_outcomes(
                outcome_id,definition_id,definition_version_id
            ),
        FOREIGN KEY(occurrence_id)
            REFERENCES discovery_occurrence_check_links(occurrence_id),
        FOREIGN KEY(transition_id,definition_id)
            REFERENCES observable_transitions(transition_id,definition_id),
        CHECK((incomplete=0 AND operational_finding_count=0)
           OR (incomplete=1 AND operational_finding_count>0)),
        CHECK(length(purpose)>0),
        CHECK(length(discriminator)>0),
        CHECK(length(operational_finding_ids_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE discovery_signal_findings(
        signal_id TEXT NOT NULL REFERENCES discovery_signals(signal_id),
        finding_id TEXT NOT NULL REFERENCES operational_findings(finding_id),
        PRIMARY KEY(signal_id,finding_id)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE discovery_gate_decisions(
        decision_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL REFERENCES discovery_signals(signal_id),
        decision_ordinal INTEGER NOT NULL CHECK(decision_ordinal>0),
        previous_decision_id TEXT REFERENCES discovery_gate_decisions(decision_id),
        evaluated_definition_version_id TEXT NOT NULL
            REFERENCES source_definition_versions(version_id),
        coverage_obligation_id TEXT NOT NULL,
        coverage_responsibility TEXT NOT NULL
            CHECK(coverage_responsibility IN({_RESPONSIBILITIES})),
        coverage_contribution TEXT NOT NULL
            CHECK(coverage_contribution IN({_CONTRIBUTIONS})),
        coverage_policy_id TEXT NOT NULL,
        coverage_policy_version TEXT NOT NULL,
        coverage_bytes BLOB NOT NULL,
        rights_decision_id TEXT NOT NULL,
        rights_policy_version TEXT NOT NULL,
        signal_admission_policy_id TEXT NOT NULL,
        signal_admission_policy_version TEXT NOT NULL,
        gate_policy_id TEXT NOT NULL,
        gate_policy_version TEXT NOT NULL,
        duplicate_policy_id TEXT NOT NULL,
        duplicate_policy_version TEXT NOT NULL,
        newness_policy_id TEXT NOT NULL,
        newness_policy_version TEXT NOT NULL,
        time_validity_policy_id TEXT NOT NULL,
        time_validity_policy_version TEXT NOT NULL,
        exclusion_policy_id TEXT NOT NULL,
        exclusion_policy_version TEXT NOT NULL,
        basis_bytes BLOB NOT NULL,
        identity_integrity INTEGER NOT NULL CHECK(identity_integrity IN(0,1)),
        duplicate_signal_id TEXT REFERENCES discovery_signals(signal_id),
        duplicate_rule TEXT,
        observable_newness TEXT NOT NULL CHECK(observable_newness IN({_NEWNESS})),
        time_validity TEXT NOT NULL CHECK(time_validity IN({_TIME_VALIDITY})),
        scope_disposition TEXT NOT NULL
            CHECK(scope_disposition IN({_SCOPE_DISPOSITIONS})),
        clear_exclusion_rule TEXT,
        rights_current INTEGER NOT NULL CHECK(rights_current IN(0,1)),
        policy_current INTEGER NOT NULL CHECK(policy_current IN(0,1)),
        operationally_executable INTEGER NOT NULL
            CHECK(operationally_executable IN(0,1)),
        outcome TEXT NOT NULL CHECK(outcome IN({_GATE_OUTCOMES})),
        terminality TEXT NOT NULL CHECK(terminality IN({_TERMINALITIES})),
        primary_reason_code TEXT NOT NULL,
        primary_reason_basis TEXT NOT NULL
            CHECK(primary_reason_basis IN({_REASON_BASES})),
        primary_reason_bytes BLOB NOT NULL,
        supporting_reasons_bytes BLOB NOT NULL,
        reason_taxonomy_version TEXT NOT NULL,
        outcome_taxonomy_version TEXT NOT NULL,
        next_action_kind TEXT CHECK(next_action_kind IN({_NEXT_ACTIONS})),
        next_action_bytes BLOB,
        decided_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(signal_id,decision_ordinal),
        UNIQUE(decision_id,signal_id),
        CHECK((decision_ordinal=1 AND previous_decision_id IS NULL)
           OR (decision_ordinal>1 AND previous_decision_id IS NOT NULL)),
        CHECK(previous_decision_id IS NULL OR previous_decision_id!=decision_id),
        CHECK((duplicate_signal_id IS NULL AND duplicate_rule IS NULL)
           OR (duplicate_signal_id IS NOT NULL AND duplicate_rule IS NOT NULL)),
        CHECK(duplicate_signal_id IS NULL OR duplicate_signal_id!=signal_id),
        CHECK((scope_disposition='CLEAR_EXCLUSION'
               AND clear_exclusion_rule IS NOT NULL)
           OR (scope_disposition!='CLEAR_EXCLUSION'
               AND clear_exclusion_rule IS NULL)),
        CHECK((next_action_kind IS NULL AND next_action_bytes IS NULL)
           OR (next_action_kind IS NOT NULL AND next_action_bytes IS NOT NULL)),
        CHECK(outcome='SIGNAL_OPERATIONAL_HOLD'
           OR (identity_integrity=1 AND rights_current=1
               AND policy_current=1 AND operationally_executable=1)),
        CHECK(outcome!='SIGNAL_SUPPRESSED_DUPLICATE'
           OR (duplicate_signal_id IS NOT NULL
               AND observable_newness='EXACT_REPEAT')),
        CHECK(outcome!='SIGNAL_SUPPRESSED_NON_CHANGE'
           OR (duplicate_signal_id IS NULL
               AND observable_newness IN('EXACT_REPEAT','PARSER_ONLY','EXPECTATION_ONLY'))),
        CHECK(outcome!='SIGNAL_REJECTED_CLEAR_EXCLUSION'
           OR (scope_disposition='CLEAR_EXCLUSION'
               AND clear_exclusion_rule IS NOT NULL)),
        CHECK(outcome!='SIGNAL_PROMOTED_TO_LEAD'
           OR (identity_integrity=1 AND duplicate_signal_id IS NULL
               AND observable_newness='GENUINE_TRANSITION'
               AND time_validity='CURRENT'
               AND scope_disposition IN('ACCEPTED','AMBIGUOUS')
               AND rights_current=1 AND policy_current=1
               AND operationally_executable=1
               AND next_action_kind='QUEUE_TRIAGE')),
        CHECK(outcome NOT IN(
                'SIGNAL_SUPPRESSED_DUPLICATE',
                'SIGNAL_SUPPRESSED_NON_CHANGE',
                'SIGNAL_REJECTED_CLEAR_EXCLUSION'
              )
              OR next_action_kind IS NULL OR next_action_kind='CLOSE'),
        CHECK(outcome!='SIGNAL_OPERATIONAL_HOLD'
           OR (next_action_kind IN('RETRY','REVIEW','WAIT_DEPENDENCY')
               AND terminality IN('PENDING_CONDITION','RETRYABLE_SAME_REQUEST'))),
        CHECK(length(coverage_bytes)>0),
        CHECK(length(basis_bytes)>0),
        CHECK(length(primary_reason_bytes)>0),
        CHECK(length(supporting_reasons_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE discovery_gate_decision_heads(
        signal_id TEXT PRIMARY KEY REFERENCES discovery_signals(signal_id),
        current_decision_id TEXT NOT NULL UNIQUE,
        current_ordinal INTEGER NOT NULL CHECK(current_ordinal>0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_decision_id,signal_id)
            REFERENCES discovery_gate_decisions(decision_id,signal_id)
            DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE news_leads(
        lead_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL UNIQUE REFERENCES discovery_signals(signal_id),
        promoting_gate_decision_id TEXT NOT NULL UNIQUE,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        representation_id TEXT NOT NULL,
        occurrence_id TEXT NOT NULL,
        transition_id TEXT NOT NULL,
        transition_kind TEXT NOT NULL CHECK(transition_kind IN({_TRANSITION_KINDS})),
        coverage_obligation_id TEXT NOT NULL,
        coverage_responsibility TEXT NOT NULL
            CHECK(coverage_responsibility IN({_RESPONSIBILITIES})),
        coverage_contribution TEXT NOT NULL
            CHECK(coverage_contribution IN({_CONTRIBUTIONS})),
        coverage_policy_id TEXT NOT NULL,
        coverage_policy_version TEXT NOT NULL,
        coverage_bytes BLOB NOT NULL,
        source_roles_bytes BLOB NOT NULL,
        portfolio_functions_bytes BLOB NOT NULL,
        source_dependencies_bytes BLOB NOT NULL,
        incompleteness_warnings_bytes BLOB NOT NULL,
        urgency_route TEXT NOT NULL CHECK(urgency_route IN({_URGENCY_ROUTES})),
        urgency_bytes BLOB NOT NULL,
        lead_policy_id TEXT NOT NULL,
        lead_policy_version TEXT NOT NULL,
        reason_taxonomy_version TEXT NOT NULL,
        outcome_taxonomy_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(lead_id,definition_id),
        FOREIGN KEY(promoting_gate_decision_id,signal_id)
            REFERENCES discovery_gate_decisions(decision_id,signal_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        FOREIGN KEY(item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        FOREIGN KEY(revision_id,item_id)
            REFERENCES source_revisions(revision_id,item_id),
        FOREIGN KEY(representation_id,revision_id)
            REFERENCES discovery_representations(representation_id,revision_id),
        FOREIGN KEY(
            signal_id,definition_id,definition_version_id,item_id,revision_id,
            representation_id,occurrence_id,transition_id
        ) REFERENCES discovery_signals(
            signal_id,definition_id,definition_version_id,item_id,revision_id,
            representation_id,occurrence_id,transition_id
        ),
        CHECK(length(coverage_bytes)>0),
        CHECK(length(source_roles_bytes)>0),
        CHECK(length(portfolio_functions_bytes)>0),
        CHECK(length(source_dependencies_bytes)>0),
        CHECK(length(incompleteness_warnings_bytes)>0),
        CHECK(length(urgency_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE news_lead_source_roles(
        lead_id TEXT NOT NULL REFERENCES news_leads(lead_id),
        source_role TEXT NOT NULL CHECK(source_role IN({_ROLES})),
        purpose TEXT NOT NULL,
        limitations_bytes BLOB NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(lead_id,source_role),
        CHECK(length(purpose)>0),
        CHECK(length(limitations_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE news_lead_portfolio_functions(
        lead_id TEXT NOT NULL REFERENCES news_leads(lead_id),
        portfolio_function TEXT NOT NULL CHECK(portfolio_function IN({_FUNCTIONS})),
        PRIMARY KEY(lead_id,portfolio_function)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE news_lead_source_dependencies(
        lead_id TEXT NOT NULL REFERENCES news_leads(lead_id),
        dependency_id TEXT NOT NULL,
        dependency_kind TEXT NOT NULL CHECK(dependency_kind IN({_DEPENDENCIES})),
        description TEXT NOT NULL,
        upstream_definition_id TEXT REFERENCES source_definitions(definition_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(lead_id,dependency_id),
        CHECK(length(description)>0),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE discovery_watch_conditions(
        watch_condition_id TEXT PRIMARY KEY,
        lead_id TEXT NOT NULL REFERENCES news_leads(lead_id),
        resume_transition_kinds_bytes BLOB NOT NULL,
        resume_transition_kind_count INTEGER NOT NULL
            CHECK(resume_transition_kind_count>=0),
        expected_occurrence TEXT,
        corroborating_lead_id TEXT REFERENCES news_leads(lead_id),
        review_at TEXT,
        expires_at TEXT,
        operator_review_condition TEXT,
        closure_rule TEXT NOT NULL,
        watch_policy_id TEXT NOT NULL,
        watch_policy_version TEXT NOT NULL,
        condition_recorded_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(watch_condition_id,lead_id),
        CHECK(corroborating_lead_id IS NULL OR corroborating_lead_id!=lead_id),
        CHECK(resume_transition_kind_count>0
           OR expected_occurrence IS NOT NULL
           OR corroborating_lead_id IS NOT NULL
           OR review_at IS NOT NULL
           OR expires_at IS NOT NULL
           OR operator_review_condition IS NOT NULL),
        CHECK(review_at IS NULL OR review_at>condition_recorded_at),
        CHECK(expires_at IS NULL OR expires_at>condition_recorded_at),
        CHECK(review_at IS NULL OR expires_at IS NULL OR review_at<=expires_at),
        CHECK(length(resume_transition_kinds_bytes)>0),
        CHECK(length(closure_rule)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE lead_disposition_decisions(
        decision_id TEXT PRIMARY KEY,
        lead_id TEXT NOT NULL REFERENCES news_leads(lead_id),
        decision_ordinal INTEGER NOT NULL CHECK(decision_ordinal>0),
        previous_decision_id TEXT REFERENCES lead_disposition_decisions(decision_id),
        outcome TEXT NOT NULL CHECK(outcome IN({_ACTIVE_DISPOSITIONS})),
        terminality TEXT NOT NULL CHECK(terminality IN({_TERMINALITIES})),
        primary_reason_code TEXT NOT NULL,
        primary_reason_basis TEXT NOT NULL
            CHECK(primary_reason_basis IN({_REASON_BASES})),
        primary_reason_bytes BLOB NOT NULL,
        supporting_reasons_bytes BLOB NOT NULL,
        watch_condition_id TEXT,
        next_action_kind TEXT NOT NULL CHECK(next_action_kind IN({_NEXT_ACTIONS})),
        next_action_bytes BLOB NOT NULL,
        urgency_route TEXT NOT NULL CHECK(urgency_route IN({_URGENCY_ROUTES})),
        urgency_bytes BLOB NOT NULL,
        disposition_policy_id TEXT NOT NULL,
        disposition_policy_version TEXT NOT NULL,
        reason_taxonomy_version TEXT NOT NULL,
        outcome_taxonomy_version TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL
            CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(lead_id,decision_ordinal),
        UNIQUE(decision_id,lead_id),
        FOREIGN KEY(watch_condition_id,lead_id)
            REFERENCES discovery_watch_conditions(watch_condition_id,lead_id),
        CHECK((decision_ordinal=1 AND previous_decision_id IS NULL)
           OR (decision_ordinal>1 AND previous_decision_id IS NOT NULL)),
        CHECK(previous_decision_id IS NULL OR previous_decision_id!=decision_id),
        CHECK(decision_ordinal!=1 OR outcome='LEAD_QUEUED_FOR_TRIAGE'),
        CHECK(outcome!='LEAD_QUEUED_FOR_TRIAGE'
           OR (watch_condition_id IS NULL
               AND next_action_kind='QUEUE_TRIAGE'
               AND terminality='PENDING_CONDITION')),
        CHECK(outcome!='LEAD_WATCH_DEFER'
           OR (watch_condition_id IS NOT NULL
               AND next_action_kind='RESUME_ON_WATCH'
               AND terminality='PENDING_CONDITION')),
        CHECK(outcome!='LEAD_OPERATIONAL_HOLD'
           OR (watch_condition_id IS NULL
               AND next_action_kind IN('RETRY','REVIEW','WAIT_DEPENDENCY')
               AND terminality IN('PENDING_CONDITION','RETRYABLE_SAME_REQUEST'))),
        CHECK(length(primary_reason_bytes)>0),
        CHECK(length(supporting_reasons_bytes)>0),
        CHECK(length(next_action_bytes)>0),
        CHECK(length(urgency_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE lead_disposition_heads(
        lead_id TEXT PRIMARY KEY REFERENCES news_leads(lead_id),
        current_decision_id TEXT NOT NULL UNIQUE,
        current_ordinal INTEGER NOT NULL CHECK(current_ordinal>0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_decision_id,lead_id)
            REFERENCES lead_disposition_decisions(decision_id,lead_id)
            DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    "CREATE INDEX idx_discovery_signals_revision ON discovery_signals(revision_id,admitted_at)",
    "CREATE INDEX idx_discovery_signals_transition ON discovery_signals(transition_id,purpose,discriminator)",
    "CREATE INDEX idx_discovery_gate_signal ON discovery_gate_decisions(signal_id,decision_ordinal)",
    "CREATE INDEX idx_news_leads_source ON news_leads(definition_id,definition_version_id,created_at)",
    "CREATE INDEX idx_news_leads_urgency ON news_leads(urgency_route,created_at)",
    "CREATE INDEX idx_watch_conditions_lead ON discovery_watch_conditions(lead_id,condition_recorded_at)",
    "CREATE INDEX idx_lead_dispositions_lead ON lead_disposition_decisions(lead_id,decision_ordinal)",
)


__all__ = ["DISCOVERY_AUTHORITY_SCHEMA_STATEMENTS"]
