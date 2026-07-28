from __future__ import annotations


DISCOVERY_AUTHORITY_GUARD_STATEMENTS: tuple[str, ...] = (
    """CREATE INDEX discovery_signals_source_idx
        ON discovery_signals(definition_id,item_id,admitted_at)""",
    """CREATE INDEX discovery_signals_revision_idx
        ON discovery_signals(revision_id,representation_id,transition_id)""",
    """CREATE INDEX gate_decisions_signal_idx
        ON discovery_gate_decisions(signal_id,decision_ordinal)""",
    """CREATE INDEX news_leads_source_idx
        ON news_leads(definition_id,item_id,created_at)""",
    """CREATE INDEX news_leads_urgency_idx
        ON news_leads(urgency_route,created_at)""",
    """CREATE INDEX watch_conditions_lead_idx
        ON discovery_watch_conditions(lead_id,condition_recorded_at)""",
    """CREATE INDEX lead_dispositions_lead_idx
        ON lead_disposition_decisions(lead_id,decision_ordinal)""",
    """CREATE TRIGGER discovery_signal_lineage_guard
        BEFORE INSERT ON discovery_signals
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
             AND p.definition_version_id=NEW.definition_version_id
            JOIN check_outcomes o
              ON o.outcome_id=NEW.check_outcome_id
             AND o.definition_id=NEW.definition_id
             AND o.definition_version_id=NEW.definition_version_id
             AND o.kind IN(
                 'SUCCESS_UNCHANGED','SUCCESS_CHANGED',
                 'SUCCESS_PARTIAL','SUCCESS_TRUNCATED'
             )
             AND o.incomplete=NEW.incomplete
            JOIN discovery_occurrences c
              ON c.occurrence_id=NEW.occurrence_id
             AND c.check_outcome_id=NEW.check_outcome_id
             AND c.revision_id=NEW.revision_id
             AND c.representation_id=NEW.representation_id
             AND c.definition_id=NEW.definition_id
             AND c.definition_version_id=NEW.definition_version_id
            JOIN observable_transitions t
              ON t.transition_id=NEW.transition_id
             AND t.check_outcome_id=NEW.check_outcome_id
             AND t.item_id=NEW.item_id
             AND t.current_revision_id=NEW.revision_id
             AND t.representation_id=NEW.representation_id
             AND t.definition_id=NEW.definition_id
             AND t.definition_version_id=NEW.definition_version_id
            WHERE i.item_id=NEW.item_id
              AND i.definition_id=NEW.definition_id
              AND NEW.admitted_at>=o.completed_at
              AND NEW.admitted_at>=t.observed_at
        )
        BEGIN SELECT RAISE(ABORT,'Discovery Signal lineage mismatch'); END""",
    """CREATE TRIGGER discovery_signal_finding_count_guard
        BEFORE INSERT ON discovery_signal_findings
        WHEN NOT EXISTS(
            SELECT 1
            FROM discovery_signals s
            JOIN operational_findings f ON f.finding_id=NEW.finding_id
            LEFT JOIN operational_finding_occurrences o
              ON o.finding_id=f.finding_id
             AND o.outcome_id=s.check_outcome_id
            WHERE s.signal_id=NEW.signal_id
              AND (
                  f.opened_by_outcome_id=s.check_outcome_id
                  OR o.finding_id IS NOT NULL
              )
        )
        BEGIN SELECT RAISE(ABORT,'Signal Finding lineage mismatch'); END""",
    """CREATE TRIGGER gate_decision_source_contract_guard
        BEFORE INSERT ON discovery_gate_decisions
        WHEN NOT EXISTS(
            SELECT 1
            FROM discovery_signals s
            JOIN source_definition_versions v
              ON v.version_id=NEW.evaluated_definition_version_id
             AND v.definition_id=s.definition_id
            JOIN source_version_coverage_mappings c
              ON c.version_id=v.version_id
             AND c.obligation_id=NEW.coverage_obligation_id
             AND c.responsibility=NEW.coverage_responsibility
             AND c.contribution=NEW.coverage_contribution
            WHERE s.signal_id=NEW.signal_id
              AND NEW.signal_admission_policy_id=s.admission_policy_id
              AND NEW.signal_admission_policy_version=
                  s.admission_policy_version
              AND NEW.decided_at>=s.admitted_at
              AND (
                  NEW.rights_current=0
                  OR (
                      v.rights_decision_id=NEW.rights_decision_id
                      AND v.rights_policy_version=NEW.rights_policy_version
                  )
              )
              AND v.recorded_at<=NEW.decided_at
              AND (
                  NEW.policy_current=0
                  OR EXISTS(
                      SELECT 1
                      FROM source_definition_version_heads h
                      WHERE h.definition_id=v.definition_id
                        AND h.current_version_id=v.version_id
                        AND h.updated_at<=NEW.decided_at
                  )
              )
        )
        BEGIN SELECT RAISE(ABORT,'Gate Decision source contract mismatch'); END""",
    """CREATE TRIGGER gate_decision_outcome_guard
        BEFORE INSERT ON discovery_gate_decisions
        WHEN (NEW.outcome='SIGNAL_SUPPRESSED_DUPLICATE' AND NOT(
                NEW.duplicate_signal_id IS NOT NULL
                AND NEW.duplicate_signal_id!=NEW.signal_id
                AND EXISTS(
                    SELECT 1 FROM discovery_signals d
                    WHERE d.signal_id=NEW.duplicate_signal_id
                      AND d.admitted_at<=NEW.decided_at
                )
                AND NEW.terminality='TERMINAL_EXACT_VERSION'
             ))
          OR (NEW.outcome='SIGNAL_SUPPRESSED_NON_CHANGE' AND NOT(
                NEW.duplicate_signal_id IS NULL
                AND NEW.observable_newness IN(
                    'EXACT_REPEAT','PARSER_ONLY','EXPECTATION_ONLY'
                )
                AND NEW.terminality='TERMINAL_EXACT_VERSION'
             ))
          OR (NEW.outcome='SIGNAL_REJECTED_CLEAR_EXCLUSION' AND NOT(
                NEW.scope_disposition='CLEAR_EXCLUSION'
                AND NEW.terminality='TERMINAL_EXACT_VERSION'
             ))
          OR (NEW.outcome='SIGNAL_PROMOTED_TO_LEAD' AND NOT(
                NEW.identity_integrity=1
                AND NEW.rights_current=1
                AND NEW.policy_current=1
                AND NEW.operationally_executable=1
                AND NEW.duplicate_signal_id IS NULL
                AND NEW.observable_newness='GENUINE_TRANSITION'
                AND NEW.scope_disposition!='CLEAR_EXCLUSION'
                AND NEW.terminality='TERMINAL_EXACT_VERSION'
             ))
          OR (NEW.outcome='SIGNAL_OPERATIONAL_HOLD' AND NOT(
                NEW.next_action_kind IN(
                    'RETRY','REVIEW','WAIT_DEPENDENCY'
                )
                AND NEW.terminality IN(
                    'PENDING_CONDITION','RETRYABLE_SAME_REQUEST'
                )
             ))
          OR (NEW.outcome!='SIGNAL_OPERATIONAL_HOLD' AND NOT(
                NEW.next_action_kind IS NULL
                OR NEW.next_action_kind IN('CLOSE','QUEUE_TRIAGE')
             ))
          OR ((NEW.identity_integrity=0
               OR NEW.rights_current=0
               OR NEW.policy_current=0
               OR NEW.operationally_executable=0)
              AND NEW.outcome!='SIGNAL_OPERATIONAL_HOLD')
        BEGIN SELECT RAISE(ABORT,'Gate Decision outcome contract mismatch'); END""",
    """CREATE TRIGGER gate_decision_chain_guard
        BEFORE INSERT ON discovery_gate_decisions
        WHEN (NEW.decision_ordinal=1 AND EXISTS(
                SELECT 1 FROM discovery_gate_decision_heads h
                WHERE h.signal_id=NEW.signal_id
             ))
          OR (NEW.decision_ordinal>1 AND NOT EXISTS(
                SELECT 1 FROM discovery_gate_decision_heads h
                WHERE h.signal_id=NEW.signal_id
                  AND h.current_decision_id=NEW.previous_decision_id
                  AND h.current_decision_ordinal=NEW.decision_ordinal-1
             ))
        BEGIN SELECT RAISE(ABORT,'Gate Decision does not extend current head'); END""",
    """CREATE TRIGGER gate_decision_predecessor_guard
        BEFORE INSERT ON discovery_gate_decisions
        WHEN NEW.previous_decision_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM discovery_gate_decisions p
            WHERE p.decision_id=NEW.previous_decision_id
              AND p.signal_id=NEW.signal_id
              AND p.decision_ordinal=NEW.decision_ordinal-1
              AND p.decided_at<=NEW.decided_at
        )
        BEGIN SELECT RAISE(ABORT,'Gate Decision predecessor mismatch'); END""",
    """CREATE TRIGGER gate_head_insert_guard
        BEFORE INSERT ON discovery_gate_decision_heads
        WHEN NOT EXISTS(
            SELECT 1 FROM discovery_gate_decisions d
            WHERE d.decision_id=NEW.current_decision_id
              AND d.signal_id=NEW.signal_id
              AND d.decision_ordinal=1
              AND d.previous_decision_id IS NULL
              AND d.decided_at=NEW.updated_at
        )
        BEGIN SELECT RAISE(ABORT,'Gate head requires first decision'); END""",
    """CREATE TRIGGER gate_head_update_guard
        BEFORE UPDATE ON discovery_gate_decision_heads
        WHEN NEW.signal_id!=OLD.signal_id
          OR NOT EXISTS(
            SELECT 1
            FROM discovery_gate_decisions n
            JOIN discovery_gate_decisions p
              ON p.decision_id=OLD.current_decision_id
            JOIN ledger_events ne ON ne.event_id=n.authority_event_id
            JOIN ledger_events pe ON pe.event_id=p.authority_event_id
            WHERE n.decision_id=NEW.current_decision_id
              AND n.signal_id=NEW.signal_id
              AND n.previous_decision_id=OLD.current_decision_id
              AND n.decision_ordinal=OLD.current_decision_ordinal+1
              AND NEW.current_decision_ordinal=n.decision_ordinal
              AND NEW.updated_at=n.decided_at
              AND ne.ledger_seq>pe.ledger_seq
          )
        BEGIN SELECT RAISE(ABORT,'invalid Gate head update'); END""",
    """CREATE TRIGGER gate_head_delete_guard
        BEFORE DELETE ON discovery_gate_decision_heads BEGIN
        SELECT RAISE(ABORT,'Gate Decision heads are retained'); END""",
    """CREATE TRIGGER gate_decision_create_head
        AFTER INSERT ON discovery_gate_decisions
        WHEN NEW.decision_ordinal=1
        BEGIN
            INSERT INTO discovery_gate_decision_heads(
                signal_id,current_decision_id,current_decision_ordinal,updated_at
            ) VALUES(
                NEW.signal_id,NEW.decision_id,NEW.decision_ordinal,NEW.decided_at
            );
        END""",
    """CREATE TRIGGER gate_decision_advance_head
        AFTER INSERT ON discovery_gate_decisions
        WHEN NEW.decision_ordinal>1
        BEGIN
            UPDATE discovery_gate_decision_heads
            SET current_decision_id=NEW.decision_id,
                current_decision_ordinal=NEW.decision_ordinal,
                updated_at=NEW.decided_at
            WHERE signal_id=NEW.signal_id
              AND current_decision_id=NEW.previous_decision_id;
        END""",
    """CREATE TRIGGER news_lead_promotion_guard
        BEFORE INSERT ON news_leads
        WHEN NOT EXISTS(
            SELECT 1
            FROM discovery_signals s
            JOIN discovery_gate_decisions g
              ON g.decision_id=NEW.promoting_gate_decision_id
             AND g.signal_id=NEW.signal_id
             AND g.outcome='SIGNAL_PROMOTED_TO_LEAD'
            JOIN discovery_gate_decision_heads h
              ON h.signal_id=NEW.signal_id
             AND h.current_decision_id=NEW.promoting_gate_decision_id
            JOIN observable_transitions t
              ON t.transition_id=NEW.transition_id
             AND t.kind=NEW.transition_kind
            WHERE s.signal_id=NEW.signal_id
              AND s.definition_id=NEW.definition_id
              AND g.evaluated_definition_version_id=NEW.definition_version_id
              AND s.item_id=NEW.item_id
              AND s.revision_id=NEW.revision_id
              AND s.representation_id=NEW.representation_id
              AND s.occurrence_id=NEW.occurrence_id
              AND s.transition_id=NEW.transition_id
              AND g.coverage_obligation_id=NEW.coverage_obligation_id
              AND g.coverage_responsibility=NEW.coverage_responsibility
              AND g.coverage_contribution=NEW.coverage_contribution
              AND g.coverage_policy_id=NEW.coverage_policy_id
              AND g.coverage_policy_version=NEW.coverage_policy_version
              AND NEW.created_at>=g.decided_at
              AND NEW.created_at>=s.admitted_at
              AND NEW.source_role_count=(
                  SELECT count(*) FROM source_version_roles r
                  WHERE r.version_id=NEW.definition_version_id
              )
              AND NEW.portfolio_function_count=(
                  SELECT count(*) FROM source_version_portfolio_functions f
                  WHERE f.version_id=NEW.definition_version_id
              )
              AND NEW.source_dependency_count=(
                  SELECT count(*) FROM source_version_dependencies d
                  WHERE d.version_id=NEW.definition_version_id
              )
              AND (s.incomplete=0 OR NEW.incompleteness_warning_count>0)
        )
        BEGIN SELECT RAISE(ABORT,'News Lead lineage mismatch'); END""",
    """CREATE TRIGGER watch_condition_chronology_guard
        BEFORE INSERT ON discovery_watch_conditions
        WHEN NOT EXISTS(
            SELECT 1
            FROM news_leads l
            JOIN discovery_gate_decision_heads h
              ON h.signal_id=l.signal_id
             AND h.current_decision_id=NEW.gate_decision_id
            JOIN discovery_gate_decisions g
              ON g.decision_id=NEW.gate_decision_id
             AND g.signal_id=l.signal_id
             AND g.outcome='SIGNAL_PROMOTED_TO_LEAD'
            WHERE l.lead_id=NEW.lead_id
              AND NEW.condition_recorded_at>=l.created_at
              AND NEW.condition_recorded_at>=g.decided_at
              AND (
                  NEW.corroborating_lead_id IS NULL
                  OR EXISTS(
                      SELECT 1 FROM news_leads c
                      WHERE c.lead_id=NEW.corroborating_lead_id
                        AND c.created_at<=NEW.condition_recorded_at
                  )
              )
        )
        BEGIN SELECT RAISE(ABORT,'Watch Condition Lead/Gate mismatch'); END""",
    """CREATE TRIGGER lead_disposition_chronology_guard
        BEFORE INSERT ON lead_disposition_decisions
        WHEN NOT EXISTS(
            SELECT 1
            FROM news_leads l
            JOIN discovery_gate_decision_heads h
              ON h.signal_id=l.signal_id
             AND h.current_decision_id=NEW.gate_decision_id
            JOIN discovery_gate_decisions g
              ON g.decision_id=NEW.gate_decision_id
             AND g.signal_id=l.signal_id
             AND g.outcome='SIGNAL_PROMOTED_TO_LEAD'
            WHERE l.lead_id=NEW.lead_id
              AND NEW.decided_at>=l.created_at
              AND NEW.decided_at>=g.decided_at
              AND NEW.urgency_route=l.urgency_route
              AND NEW.urgency_bytes=l.urgency_bytes
              AND (
                  (NEW.decision_ordinal=1
                   AND NEW.gate_decision_id=l.promoting_gate_decision_id)
                  OR NEW.decision_ordinal>1
              )
              AND (
                  NEW.watch_condition_id IS NULL
                  OR EXISTS(
                      SELECT 1 FROM discovery_watch_conditions w
                      WHERE w.watch_condition_id=NEW.watch_condition_id
                        AND w.lead_id=NEW.lead_id
                        AND w.gate_decision_id=NEW.gate_decision_id
                        AND w.condition_recorded_at<=NEW.decided_at
                  )
              )
        )
        BEGIN SELECT RAISE(ABORT,'Lead disposition Lead/Gate mismatch'); END""",
    """CREATE TRIGGER lead_disposition_outcome_guard
        BEFORE INSERT ON lead_disposition_decisions
        WHEN (NEW.outcome='LEAD_QUEUED_FOR_TRIAGE' AND NOT(
                NEW.next_action_kind='QUEUE_TRIAGE'
                AND NEW.terminality='PENDING_CONDITION'
             ))
          OR (NEW.outcome='LEAD_WATCH_DEFER' AND NOT(
                NEW.next_action_kind='RESUME_ON_WATCH'
                AND NEW.watch_condition_id IS NOT NULL
                AND NEW.terminality='PENDING_CONDITION'
             ))
          OR (NEW.outcome='LEAD_OPERATIONAL_HOLD' AND NOT(
                NEW.next_action_kind IN(
                    'RETRY','REVIEW','WAIT_DEPENDENCY'
                )
                AND NEW.watch_condition_id IS NULL
                AND NEW.terminality IN(
                    'PENDING_CONDITION','RETRYABLE_SAME_REQUEST'
                )
             ))
        BEGIN SELECT RAISE(ABORT,'Lead disposition outcome mismatch'); END""",
    """CREATE TRIGGER lead_disposition_chain_guard
        BEFORE INSERT ON lead_disposition_decisions
        WHEN (NEW.decision_ordinal=1 AND EXISTS(
                SELECT 1 FROM lead_disposition_heads h
                WHERE h.lead_id=NEW.lead_id
             ))
          OR (NEW.decision_ordinal>1 AND NOT EXISTS(
                SELECT 1 FROM lead_disposition_heads h
                WHERE h.lead_id=NEW.lead_id
                  AND h.current_decision_id=NEW.previous_decision_id
                  AND h.current_decision_ordinal=NEW.decision_ordinal-1
             ))
        BEGIN SELECT RAISE(ABORT,'Lead disposition does not extend current head'); END""",
    """CREATE TRIGGER lead_disposition_predecessor_guard
        BEFORE INSERT ON lead_disposition_decisions
        WHEN NEW.previous_decision_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM lead_disposition_decisions p
            WHERE p.decision_id=NEW.previous_decision_id
              AND p.lead_id=NEW.lead_id
              AND p.decision_ordinal=NEW.decision_ordinal-1
              AND p.decided_at<=NEW.decided_at
        )
        BEGIN SELECT RAISE(ABORT,'Lead disposition predecessor mismatch'); END""",
    """CREATE TRIGGER lead_disposition_head_insert_guard
        BEFORE INSERT ON lead_disposition_heads
        WHEN NOT EXISTS(
            SELECT 1 FROM lead_disposition_decisions d
            WHERE d.decision_id=NEW.current_decision_id
              AND d.lead_id=NEW.lead_id
              AND d.decision_ordinal=1
              AND d.previous_decision_id IS NULL
              AND d.decided_at=NEW.updated_at
        )
        BEGIN SELECT RAISE(ABORT,'Lead disposition head requires first decision'); END""",
    """CREATE TRIGGER lead_disposition_head_update_guard
        BEFORE UPDATE ON lead_disposition_heads
        WHEN NEW.lead_id!=OLD.lead_id
          OR NOT EXISTS(
            SELECT 1
            FROM lead_disposition_decisions n
            JOIN lead_disposition_decisions p
              ON p.decision_id=OLD.current_decision_id
            JOIN ledger_events ne ON ne.event_id=n.authority_event_id
            JOIN ledger_events pe ON pe.event_id=p.authority_event_id
            WHERE n.decision_id=NEW.current_decision_id
              AND n.lead_id=NEW.lead_id
              AND n.previous_decision_id=OLD.current_decision_id
              AND n.decision_ordinal=OLD.current_decision_ordinal+1
              AND NEW.current_decision_ordinal=n.decision_ordinal
              AND NEW.updated_at=n.decided_at
              AND ne.ledger_seq>pe.ledger_seq
          )
        BEGIN SELECT RAISE(ABORT,'invalid Lead disposition head update'); END""",
    """CREATE TRIGGER lead_disposition_head_delete_guard
        BEFORE DELETE ON lead_disposition_heads BEGIN
        SELECT RAISE(ABORT,'Lead disposition heads are retained'); END""",
    """CREATE TRIGGER lead_disposition_create_head
        AFTER INSERT ON lead_disposition_decisions
        WHEN NEW.decision_ordinal=1
        BEGIN
            INSERT INTO lead_disposition_heads(
                lead_id,current_decision_id,current_decision_ordinal,updated_at
            ) VALUES(
                NEW.lead_id,NEW.decision_id,NEW.decision_ordinal,NEW.decided_at
            );
        END""",
    """CREATE TRIGGER lead_disposition_advance_head
        AFTER INSERT ON lead_disposition_decisions
        WHEN NEW.decision_ordinal>1
        BEGIN
            UPDATE lead_disposition_heads
            SET current_decision_id=NEW.decision_id,
                current_decision_ordinal=NEW.decision_ordinal,
                updated_at=NEW.decided_at
            WHERE lead_id=NEW.lead_id
              AND current_decision_id=NEW.previous_decision_id;
        END""",
    """CREATE TRIGGER immutable_discovery_signals_update
        BEFORE UPDATE ON discovery_signals BEGIN
        SELECT RAISE(ABORT,'immutable Discovery Signal'); END""",
    """CREATE TRIGGER immutable_discovery_signals_delete
        BEFORE DELETE ON discovery_signals BEGIN
        SELECT RAISE(ABORT,'Discovery Signals are retained'); END""",
    """CREATE TRIGGER immutable_discovery_signal_findings_update
        BEFORE UPDATE ON discovery_signal_findings BEGIN
        SELECT RAISE(ABORT,'immutable Signal Finding link'); END""",
    """CREATE TRIGGER immutable_discovery_signal_findings_delete
        BEFORE DELETE ON discovery_signal_findings BEGIN
        SELECT RAISE(ABORT,'Signal Finding links are retained'); END""",
    """CREATE TRIGGER immutable_discovery_gate_decisions_update
        BEFORE UPDATE ON discovery_gate_decisions BEGIN
        SELECT RAISE(ABORT,'immutable Gate Decision'); END""",
    """CREATE TRIGGER immutable_discovery_gate_decisions_delete
        BEFORE DELETE ON discovery_gate_decisions BEGIN
        SELECT RAISE(ABORT,'Gate Decisions are retained'); END""",
    """CREATE TRIGGER immutable_news_leads_update
        BEFORE UPDATE ON news_leads BEGIN
        SELECT RAISE(ABORT,'immutable News Lead'); END""",
    """CREATE TRIGGER immutable_news_leads_delete
        BEFORE DELETE ON news_leads BEGIN
        SELECT RAISE(ABORT,'News Leads are retained'); END""",
    """CREATE TRIGGER immutable_discovery_watch_conditions_update
        BEFORE UPDATE ON discovery_watch_conditions BEGIN
        SELECT RAISE(ABORT,'immutable Watch Condition'); END""",
    """CREATE TRIGGER immutable_discovery_watch_conditions_delete
        BEFORE DELETE ON discovery_watch_conditions BEGIN
        SELECT RAISE(ABORT,'Watch Conditions are retained'); END""",
    """CREATE TRIGGER immutable_lead_dispositions_update
        BEFORE UPDATE ON lead_disposition_decisions BEGIN
        SELECT RAISE(ABORT,'immutable Lead disposition'); END""",
    """CREATE TRIGGER immutable_lead_dispositions_delete
        BEFORE DELETE ON lead_disposition_decisions BEGIN
        SELECT RAISE(ABORT,'Lead dispositions are retained'); END""",
)


__all__ = ["DISCOVERY_AUTHORITY_GUARD_STATEMENTS"]
