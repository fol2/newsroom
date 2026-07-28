from __future__ import annotations


DISCOVERY_AUTHORITY_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE discovery_signals(
        signal_id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        item_id TEXT NOT NULL REFERENCES source_items(item_id),
        revision_id TEXT NOT NULL REFERENCES source_revisions(revision_id),
        representation_id TEXT NOT NULL
            REFERENCES discovery_representations(representation_id),
        check_outcome_id TEXT NOT NULL REFERENCES check_outcomes(outcome_id),
        occurrence_id TEXT NOT NULL
            REFERENCES discovery_occurrences(occurrence_id),
        transition_id TEXT NOT NULL REFERENCES observable_transitions(transition_id),
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
        UNIQUE(signal_id,definition_id,definition_version_id),
        UNIQUE(signal_id,item_id,revision_id,representation_id),
        UNIQUE(signal_id,check_outcome_id,occurrence_id,transition_id),
        UNIQUE(
            revision_id,
            representation_id,
            transition_id,
            purpose,
            discriminator,
            admission_policy_id,
            admission_policy_version
        ),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        CHECK(length(purpose)>0),
        CHECK(length(discriminator)>0),
        CHECK(length(admission_policy_id)>0),
        CHECK(length(admission_policy_version)>0),
        CHECK(length(operational_finding_ids_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE discovery_signal_findings(
        signal_id TEXT NOT NULL REFERENCES discovery_signals(signal_id),
        finding_id TEXT NOT NULL REFERENCES operational_findings(finding_id),
        finding_ordinal INTEGER NOT NULL CHECK(finding_ordinal>=0),
        PRIMARY KEY(signal_id,finding_id),
        UNIQUE(signal_id,finding_ordinal)
    ) STRICT""",
    """CREATE TABLE discovery_gate_decisions(
        decision_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL REFERENCES discovery_signals(signal_id),
        decision_ordinal INTEGER NOT NULL CHECK(decision_ordinal>0),
        previous_decision_id TEXT REFERENCES discovery_gate_decisions(decision_id),
        evaluated_definition_version_id TEXT NOT NULL
            REFERENCES source_definition_versions(version_id),
        coverage_obligation_id TEXT NOT NULL,
        coverage_responsibility TEXT NOT NULL
            CHECK(coverage_responsibility IN(
                'ACTIVE','BEST_EFFORT','EXPLICIT_DEFERRED_GAP',
                'OPERATIONAL_RESILIENCE','EVALUATION'
            )),
        coverage_contribution TEXT NOT NULL
            CHECK(coverage_contribution IN(
                'DETECTION_PATH','OCCURRENCE_CONFIRMATION',
                'REVISION_VISIBILITY','URGENT_FAST_PATH',
                'REDUNDANCY','COMPARATOR'
            )),
        coverage_policy_id TEXT NOT NULL,
        coverage_policy_version TEXT NOT NULL,
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
        identity_integrity INTEGER NOT NULL CHECK(identity_integrity IN(0,1)),
        duplicate_signal_id TEXT REFERENCES discovery_signals(signal_id),
        duplicate_rule_id TEXT,
        duplicate_rule_version TEXT,
        observable_newness TEXT NOT NULL
            CHECK(observable_newness IN(
                'GENUINE_TRANSITION','EXACT_REPEAT','PARSER_ONLY',
                'EXPECTATION_ONLY','UNKNOWN'
            )),
        time_validity TEXT NOT NULL
            CHECK(time_validity IN('CURRENT','STALE','UNKNOWN','CONFLICTING')),
        scope_disposition TEXT NOT NULL
            CHECK(scope_disposition IN(
                'ACCEPTED','CLEAR_EXCLUSION','AMBIGUOUS','UNKNOWN'
            )),
        clear_exclusion_rule_id TEXT,
        clear_exclusion_rule_version TEXT,
        rights_current INTEGER NOT NULL CHECK(rights_current IN(0,1)),
        policy_current INTEGER NOT NULL CHECK(policy_current IN(0,1)),
        operationally_executable INTEGER NOT NULL
            CHECK(operationally_executable IN(0,1)),
        ambiguities_bytes BLOB NOT NULL,
        ambiguity_count INTEGER NOT NULL CHECK(ambiguity_count>=0),
        outcome TEXT NOT NULL
            CHECK(outcome IN(
                'SIGNAL_SUPPRESSED_DUPLICATE',
                'SIGNAL_SUPPRESSED_NON_CHANGE',
                'SIGNAL_REJECTED_CLEAR_EXCLUSION',
                'SIGNAL_PROMOTED_TO_LEAD',
                'SIGNAL_OPERATIONAL_HOLD'
            )),
        terminality TEXT NOT NULL
            CHECK(terminality IN(
                'TERMINAL_EXACT_VERSION','PENDING_CONDITION',
                'RETRYABLE_SAME_REQUEST','OCCURRENCE_ONLY'
            )),
        primary_reason_bytes BLOB NOT NULL,
        supporting_reasons_bytes BLOB NOT NULL,
        supporting_reason_count INTEGER NOT NULL
            CHECK(supporting_reason_count>=0),
        reason_taxonomy_version TEXT NOT NULL,
        outcome_taxonomy_version TEXT NOT NULL,
        next_action_kind TEXT CHECK(next_action_kind IS NULL OR next_action_kind IN(
            'CLOSE','QUEUE_TRIAGE','RETRY','REVIEW',
            'WAIT_DEPENDENCY','RESUME_ON_WATCH'
        )),
        next_action_code TEXT,
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
        CHECK(
            (decision_ordinal=1 AND previous_decision_id IS NULL)
            OR (decision_ordinal>1 AND previous_decision_id IS NOT NULL)
        ),
        CHECK(duplicate_signal_id IS NULL OR duplicate_signal_id!=signal_id),
        CHECK(
            (duplicate_signal_id IS NULL
             AND duplicate_rule_id IS NULL
             AND duplicate_rule_version IS NULL)
            OR (duplicate_signal_id IS NOT NULL
                AND duplicate_rule_id IS NOT NULL
                AND duplicate_rule_version IS NOT NULL)
        ),
        CHECK(
            (scope_disposition='CLEAR_EXCLUSION'
             AND clear_exclusion_rule_id IS NOT NULL
             AND clear_exclusion_rule_version IS NOT NULL
             AND ambiguity_count=0)
            OR (scope_disposition!='CLEAR_EXCLUSION'
                AND clear_exclusion_rule_id IS NULL
                AND clear_exclusion_rule_version IS NULL)
        ),
        CHECK(
            (next_action_kind IS NULL
             AND next_action_code IS NULL
             AND next_action_bytes IS NULL)
            OR (next_action_kind IS NOT NULL
                AND next_action_code IS NOT NULL
                AND next_action_bytes IS NOT NULL)
        ),
        CHECK(length(ambiguities_bytes)>0),
        CHECK(length(primary_reason_bytes)>0),
        CHECK(length(supporting_reasons_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE discovery_gate_decision_heads(
        signal_id TEXT PRIMARY KEY REFERENCES discovery_signals(signal_id),
        current_decision_id TEXT NOT NULL UNIQUE,
        current_decision_ordinal INTEGER NOT NULL
            CHECK(current_decision_ordinal>0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_decision_id,signal_id)
            REFERENCES discovery_gate_decisions(decision_id,signal_id)
    ) STRICT""",
    """CREATE TABLE news_leads(
        lead_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL UNIQUE REFERENCES discovery_signals(signal_id),
        promoting_gate_decision_id TEXT NOT NULL UNIQUE
            REFERENCES discovery_gate_decisions(decision_id),
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        item_id TEXT NOT NULL REFERENCES source_items(item_id),
        revision_id TEXT NOT NULL REFERENCES source_revisions(revision_id),
        representation_id TEXT NOT NULL
            REFERENCES discovery_representations(representation_id),
        occurrence_id TEXT NOT NULL REFERENCES discovery_occurrences(occurrence_id),
        transition_id TEXT NOT NULL REFERENCES observable_transitions(transition_id),
        transition_kind TEXT NOT NULL CHECK(transition_kind IN(
            'FIRST_OBSERVED','REVISED','REOBSERVED','ACTIVATED',
            'ESCALATED','DEESCALATED','RESOLVED_OR_CLEARED','EXPIRED',
            'CANCELLED','WITHDRAWN','REPLACED','REACTIVATED',
            'AGENDA_CREATED','AGENDA_RESCHEDULED','AGENDA_CANCELLED',
            'AGENDA_MISSED_EXPECTATION','AGENDA_LATE_OCCURRENCE',
            'AMBIGUOUS_ABSENCE'
        )),
        coverage_obligation_id TEXT NOT NULL,
        coverage_responsibility TEXT NOT NULL
            CHECK(coverage_responsibility IN(
                'ACTIVE','BEST_EFFORT','EXPLICIT_DEFERRED_GAP',
                'OPERATIONAL_RESILIENCE','EVALUATION'
            )),
        coverage_contribution TEXT NOT NULL
            CHECK(coverage_contribution IN(
                'DETECTION_PATH','OCCURRENCE_CONFIRMATION',
                'REVISION_VISIBILITY','URGENT_FAST_PATH',
                'REDUNDANCY','COMPARATOR'
            )),
        coverage_policy_id TEXT NOT NULL,
        coverage_policy_version TEXT NOT NULL,
        source_roles_bytes BLOB NOT NULL,
        source_role_count INTEGER NOT NULL CHECK(source_role_count>0),
        portfolio_functions_bytes BLOB NOT NULL,
        portfolio_function_count INTEGER NOT NULL
            CHECK(portfolio_function_count>0),
        source_dependencies_bytes BLOB NOT NULL,
        source_dependency_count INTEGER NOT NULL
            CHECK(source_dependency_count>=0),
        incompleteness_warnings_bytes BLOB NOT NULL,
        incompleteness_warning_count INTEGER NOT NULL
            CHECK(incompleteness_warning_count>=0),
        urgency_bytes BLOB NOT NULL,
        urgency_route TEXT NOT NULL
            CHECK(urgency_route IN(
                'URGENT','TIME_SENSITIVE','PLANNED','ROUTINE'
            )),
        urgency_hard_deadline TEXT,
        urgency_planned_window TEXT,
        urgency_isolation_required INTEGER NOT NULL
            CHECK(urgency_isolation_required IN(0,1)),
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
        UNIQUE(lead_id,signal_id),
        UNIQUE(lead_id,definition_id,definition_version_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        CHECK(
            (urgency_route='URGENT' AND urgency_isolation_required=1)
            OR urgency_route!='URGENT'
        ),
        CHECK(
            (urgency_route='PLANNED' AND urgency_planned_window IS NOT NULL)
            OR (urgency_route!='PLANNED' AND urgency_planned_window IS NULL)
        ),
        CHECK(length(source_roles_bytes)>0),
        CHECK(length(portfolio_functions_bytes)>0),
        CHECK(length(source_dependencies_bytes)>0),
        CHECK(length(incompleteness_warnings_bytes)>0),
        CHECK(length(urgency_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE discovery_watch_conditions(
        watch_condition_id TEXT PRIMARY KEY,
        lead_id TEXT NOT NULL REFERENCES news_leads(lead_id),
        gate_decision_id TEXT NOT NULL
            REFERENCES discovery_gate_decisions(decision_id),
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
        CHECK(
            corroborating_lead_id IS NULL
            OR corroborating_lead_id!=lead_id
        ),
        CHECK(
            resume_transition_kind_count>0
            OR expected_occurrence IS NOT NULL
            OR corroborating_lead_id IS NOT NULL
            OR review_at IS NOT NULL
            OR expires_at IS NOT NULL
            OR operator_review_condition IS NOT NULL
        ),
        CHECK(review_at IS NULL OR review_at>=condition_recorded_at),
        CHECK(expires_at IS NULL OR expires_at>condition_recorded_at),
        CHECK(review_at IS NULL OR expires_at IS NULL OR expires_at>=review_at),
        CHECK(length(resume_transition_kinds_bytes)>0),
        CHECK(length(closure_rule)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE lead_disposition_decisions(
        decision_id TEXT PRIMARY KEY,
        lead_id TEXT NOT NULL REFERENCES news_leads(lead_id),
        gate_decision_id TEXT NOT NULL
            REFERENCES discovery_gate_decisions(decision_id),
        decision_ordinal INTEGER NOT NULL CHECK(decision_ordinal>0),
        previous_decision_id TEXT
            REFERENCES lead_disposition_decisions(decision_id),
        outcome TEXT NOT NULL
            CHECK(outcome IN(
                'LEAD_QUEUED_FOR_TRIAGE',
                'LEAD_OPERATIONAL_HOLD',
                'LEAD_WATCH_DEFER'
            )),
        terminality TEXT NOT NULL
            CHECK(terminality IN(
                'TERMINAL_EXACT_VERSION','PENDING_CONDITION',
                'RETRYABLE_SAME_REQUEST','OCCURRENCE_ONLY'
            )),
        primary_reason_bytes BLOB NOT NULL,
        supporting_reasons_bytes BLOB NOT NULL,
        supporting_reason_count INTEGER NOT NULL
            CHECK(supporting_reason_count>=0),
        watch_condition_id TEXT REFERENCES discovery_watch_conditions(watch_condition_id),
        next_action_kind TEXT NOT NULL CHECK(next_action_kind IN(
            'CLOSE','QUEUE_TRIAGE','RETRY','REVIEW',
            'WAIT_DEPENDENCY','RESUME_ON_WATCH'
        )),
        next_action_code TEXT NOT NULL,
        next_action_bytes BLOB NOT NULL,
        urgency_bytes BLOB NOT NULL,
        urgency_route TEXT NOT NULL
            CHECK(urgency_route IN(
                'URGENT','TIME_SENSITIVE','PLANNED','ROUTINE'
            )),
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
        CHECK(
            (decision_ordinal=1 AND previous_decision_id IS NULL
             AND outcome='LEAD_QUEUED_FOR_TRIAGE')
            OR (decision_ordinal>1 AND previous_decision_id IS NOT NULL)
        ),
        CHECK(
            (outcome='LEAD_WATCH_DEFER' AND watch_condition_id IS NOT NULL)
            OR (outcome!='LEAD_WATCH_DEFER' AND watch_condition_id IS NULL)
        ),
        CHECK(length(primary_reason_bytes)>0),
        CHECK(length(supporting_reasons_bytes)>0),
        CHECK(length(next_action_bytes)>0),
        CHECK(length(urgency_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE lead_disposition_heads(
        lead_id TEXT PRIMARY KEY REFERENCES news_leads(lead_id),
        current_decision_id TEXT NOT NULL UNIQUE,
        current_decision_ordinal INTEGER NOT NULL
            CHECK(current_decision_ordinal>0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_decision_id,lead_id)
            REFERENCES lead_disposition_decisions(decision_id,lead_id)
    ) STRICT""",
)


__all__ = ["DISCOVERY_AUTHORITY_SCHEMA_STATEMENTS"]
