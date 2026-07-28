from __future__ import annotations


DISCOVERY_AUTHORITY_GUARD_STATEMENTS: tuple[str, ...] = (
    """CREATE TRIGGER discovery_signal_lineage_guard
        BEFORE INSERT ON discovery_signals
        WHEN NOT EXISTS(
            SELECT 1
            FROM discovery_occurrences o
            JOIN discovery_occurrence_check_links l
              ON l.occurrence_id=o.occurrence_id
             AND l.check_outcome_id=o.check_outcome_id
            JOIN check_outcomes c
              ON c.outcome_id=o.check_outcome_id
            JOIN source_revisions r
              ON r.revision_id=o.revision_id
            JOIN discovery_representations p
              ON p.representation_id=o.representation_id
             AND p.revision_id=o.revision_id
            JOIN observable_transitions t
              ON t.transition_id=NEW.transition_id
             AND t.definition_id=o.definition_id
             AND t.definition_version_id=o.definition_version_id
             AND t.check_outcome_id=o.check_outcome_id
             AND t.item_id=r.item_id
             AND t.current_revision_id=o.revision_id
             AND t.representation_id=o.representation_id
            WHERE o.occurrence_id=NEW.occurrence_id
              AND o.definition_id=NEW.definition_id
              AND o.definition_version_id=NEW.definition_version_id
              AND o.revision_id=NEW.revision_id
              AND o.representation_id=NEW.representation_id
              AND o.check_outcome_id=NEW.check_outcome_id
              AND c.definition_id=NEW.definition_id
              AND c.definition_version_id=NEW.definition_version_id
              AND r.item_id=NEW.item_id
              AND r.definition_id=NEW.definition_id
              AND p.definition_id=NEW.definition_id
              AND p.definition_version_id=NEW.definition_version_id
        )
        BEGIN SELECT RAISE(ABORT,'Signal lineage differs from retained observation'); END""",
    """CREATE TRIGGER discovery_signal_finding_insert_guard
        BEFORE INSERT ON discovery_signal_findings
        WHEN NOT EXISTS(
            SELECT 1 FROM discovery_signals s
            WHERE s.signal_id=NEW.signal_id
              AND s.incomplete=1
              AND (
                  SELECT COUNT(*) FROM discovery_signal_findings f
                  WHERE f.signal_id=NEW.signal_id
              ) < s.operational_finding_count
        )
        BEGIN SELECT RAISE(ABORT,'Signal Finding lineage exceeds declared authority'); END""",
    """CREATE TRIGGER discovery_gate_source_revalidation_guard
        BEFORE INSERT ON discovery_gate_decisions
        WHEN NOT EXISTS(
            SELECT 1
            FROM discovery_signals s
            JOIN source_definition_version_heads h
              ON h.definition_id=s.definition_id
             AND h.current_version_id=NEW.evaluated_definition_version_id
            JOIN source_version_coverage_mappings c
              ON c.version_id=NEW.evaluated_definition_version_id
             AND c.obligation_id=NEW.coverage_obligation_id
             AND c.responsibility=NEW.coverage_responsibility
             AND c.contribution=NEW.coverage_contribution
            WHERE s.signal_id=NEW.signal_id
              AND NEW.decided_at>=s.admitted_at
        )
        BEGIN SELECT RAISE(ABORT,'Gate Decision lacks current source and coverage authority'); END""",
    """CREATE TRIGGER discovery_gate_predecessor_guard
        BEFORE INSERT ON discovery_gate_decisions
        WHEN NEW.decision_ordinal>1
         AND NOT EXISTS(
            SELECT 1
            FROM discovery_gate_decisions p
            JOIN discovery_gate_decision_heads h
              ON h.signal_id=p.signal_id
             AND h.current_decision_id=p.decision_id
             AND h.current_ordinal=p.decision_ordinal
            WHERE p.decision_id=NEW.previous_decision_id
              AND p.signal_id=NEW.signal_id
              AND p.decision_ordinal=NEW.decision_ordinal-1
              AND p.decided_at<=NEW.decided_at
         )
        BEGIN SELECT RAISE(ABORT,'Gate Decision predecessor is not the exact current head'); END""",
    """CREATE TRIGGER discovery_gate_head_insert_guard
        BEFORE INSERT ON discovery_gate_decision_heads
        WHEN NEW.current_ordinal!=1
          OR NOT EXISTS(
              SELECT 1 FROM discovery_gate_decisions d
              WHERE d.decision_id=NEW.current_decision_id
                AND d.signal_id=NEW.signal_id
                AND d.decision_ordinal=1
                AND d.decided_at=NEW.updated_at
          )
        BEGIN SELECT RAISE(ABORT,'Gate Decision heads begin at exact ordinal one'); END""",
    """CREATE TRIGGER discovery_gate_head_update_guard
        BEFORE UPDATE ON discovery_gate_decision_heads
        WHEN NEW.signal_id!=OLD.signal_id
          OR NEW.current_ordinal!=OLD.current_ordinal+1
          OR NOT EXISTS(
              SELECT 1 FROM discovery_gate_decisions d
              WHERE d.decision_id=NEW.current_decision_id
                AND d.signal_id=NEW.signal_id
                AND d.decision_ordinal=NEW.current_ordinal
                AND d.previous_decision_id=OLD.current_decision_id
                AND d.decided_at=NEW.updated_at
          )
        BEGIN SELECT RAISE(ABORT,'invalid Gate Decision head advance'); END""",
    """CREATE TRIGGER discovery_gate_head_delete_guard
        BEFORE DELETE ON discovery_gate_decision_heads
        BEGIN SELECT RAISE(ABORT,'Gate Decision heads are retained'); END""",
    """CREATE TRIGGER discovery_gate_establish_head
        AFTER INSERT ON discovery_gate_decisions
        WHEN NEW.decision_ordinal=1
        BEGIN
          INSERT INTO discovery_gate_decision_heads(
              signal_id,current_decision_id,current_ordinal,updated_at
          ) VALUES(NEW.signal_id,NEW.decision_id,1,NEW.decided_at);
        END""",
    """CREATE TRIGGER discovery_gate_advance_head
        AFTER INSERT ON discovery_gate_decisions
        WHEN NEW.decision_ordinal>1
        BEGIN
          UPDATE discovery_gate_decision_heads
          SET current_decision_id=NEW.decision_id,
              current_ordinal=NEW.decision_ordinal,
              updated_at=NEW.decided_at
          WHERE signal_id=NEW.signal_id;
        END""",
    """CREATE TRIGGER news_lead_gate_lineage_guard
        BEFORE INSERT ON news_leads
        WHEN NOT EXISTS(
            SELECT 1
            FROM discovery_gate_decisions g
            JOIN discovery_gate_decision_heads h
              ON h.signal_id=g.signal_id
             AND h.current_decision_id=g.decision_id
            JOIN discovery_signals s
              ON s.signal_id=g.signal_id
            WHERE g.decision_id=NEW.promoting_gate_decision_id
              AND g.signal_id=NEW.signal_id
              AND g.outcome='SIGNAL_PROMOTED_TO_LEAD'
              AND g.evaluated_definition_version_id=NEW.definition_version_id
              AND g.coverage_obligation_id=NEW.coverage_obligation_id
              AND g.coverage_responsibility=NEW.coverage_responsibility
              AND g.coverage_contribution=NEW.coverage_contribution
              AND g.coverage_policy_id=NEW.coverage_policy_id
              AND g.coverage_policy_version=NEW.coverage_policy_version
              AND g.coverage_bytes=NEW.coverage_bytes
              AND s.definition_id=NEW.definition_id
              AND s.definition_version_id=NEW.definition_version_id
              AND s.item_id=NEW.item_id
              AND s.revision_id=NEW.revision_id
              AND s.representation_id=NEW.representation_id
              AND s.occurrence_id=NEW.occurrence_id
              AND s.transition_id=NEW.transition_id
              AND g.decided_at<=NEW.created_at
        )
        BEGIN SELECT RAISE(ABORT,'News Lead differs from current promoting Gate authority'); END""",
    """CREATE TRIGGER news_lead_transition_kind_guard
        BEFORE INSERT ON news_leads
        WHEN NOT EXISTS(
            SELECT 1 FROM observable_transitions t
            WHERE t.transition_id=NEW.transition_id
              AND t.kind=NEW.transition_kind
        )
        BEGIN SELECT RAISE(ABORT,'News Lead transition kind differs'); END""",
    """CREATE TRIGGER news_lead_source_role_guard
        BEFORE INSERT ON news_lead_source_roles
        WHEN NOT EXISTS(
            SELECT 1
            FROM news_leads l
            JOIN source_version_roles r
              ON r.version_id=l.definition_version_id
             AND r.role=NEW.source_role
             AND r.purpose=NEW.purpose
             AND r.limitations_bytes=NEW.limitations_bytes
             AND r.canonical_bytes=NEW.canonical_bytes
             AND r.canonical_digest=NEW.canonical_digest
            WHERE l.lead_id=NEW.lead_id
        )
        BEGIN SELECT RAISE(ABORT,'News Lead role differs from source version'); END""",
    """CREATE TRIGGER news_lead_portfolio_function_guard
        BEFORE INSERT ON news_lead_portfolio_functions
        WHEN NOT EXISTS(
            SELECT 1
            FROM news_leads l
            JOIN source_version_portfolio_functions f
              ON f.version_id=l.definition_version_id
             AND f.portfolio_function=NEW.portfolio_function
            WHERE l.lead_id=NEW.lead_id
        )
        BEGIN SELECT RAISE(ABORT,'News Lead portfolio function differs from source version'); END""",
    """CREATE TRIGGER news_lead_dependency_guard
        BEFORE INSERT ON news_lead_source_dependencies
        WHEN NOT EXISTS(
            SELECT 1
            FROM news_leads l
            JOIN source_version_dependencies d
              ON d.version_id=l.definition_version_id
             AND d.dependency_id=NEW.dependency_id
             AND d.dependency_kind=NEW.dependency_kind
             AND d.description=NEW.description
             AND d.upstream_definition_id IS NEW.upstream_definition_id
             AND d.canonical_bytes=NEW.canonical_bytes
             AND d.canonical_digest=NEW.canonical_digest
            WHERE l.lead_id=NEW.lead_id
        )
        BEGIN SELECT RAISE(ABORT,'News Lead dependency differs from source version'); END""",
    """CREATE TRIGGER discovery_watch_condition_chronology_guard
        BEFORE INSERT ON discovery_watch_conditions
        WHEN NOT EXISTS(
            SELECT 1 FROM news_leads l
            WHERE l.lead_id=NEW.lead_id
              AND l.created_at<=NEW.condition_recorded_at
        )
        BEGIN SELECT RAISE(ABORT,'Watch Condition precedes its Lead'); END""",
    """CREATE TRIGGER lead_disposition_lineage_guard
        BEFORE INSERT ON lead_disposition_decisions
        WHEN NOT EXISTS(
            SELECT 1 FROM news_leads l
            WHERE l.lead_id=NEW.lead_id
              AND l.created_at<=NEW.decided_at
              AND l.urgency_route=NEW.urgency_route
        )
        BEGIN SELECT RAISE(ABORT,'Lead disposition differs from Lead chronology or urgency'); END""",
    """CREATE TRIGGER lead_disposition_watch_guard
        BEFORE INSERT ON lead_disposition_decisions
        WHEN NEW.watch_condition_id IS NOT NULL
         AND NOT EXISTS(
            SELECT 1 FROM discovery_watch_conditions w
            WHERE w.watch_condition_id=NEW.watch_condition_id
              AND w.lead_id=NEW.lead_id
              AND w.condition_recorded_at<=NEW.decided_at
         )
        BEGIN SELECT RAISE(ABORT,'Lead disposition Watch Condition is not retained'); END""",
    """CREATE TRIGGER lead_disposition_predecessor_guard
        BEFORE INSERT ON lead_disposition_decisions
        WHEN NEW.decision_ordinal>1
         AND NOT EXISTS(
            SELECT 1
            FROM lead_disposition_decisions p
            JOIN lead_disposition_heads h
              ON h.lead_id=p.lead_id
             AND h.current_decision_id=p.decision_id
             AND h.current_ordinal=p.decision_ordinal
            WHERE p.decision_id=NEW.previous_decision_id
              AND p.lead_id=NEW.lead_id
              AND p.decision_ordinal=NEW.decision_ordinal-1
              AND p.decided_at<=NEW.decided_at
         )
        BEGIN SELECT RAISE(ABORT,'Lead disposition predecessor is not the exact current head'); END""",
    """CREATE TRIGGER lead_disposition_head_insert_guard
        BEFORE INSERT ON lead_disposition_heads
        WHEN NEW.current_ordinal!=1
          OR NOT EXISTS(
              SELECT 1 FROM lead_disposition_decisions d
              WHERE d.decision_id=NEW.current_decision_id
                AND d.lead_id=NEW.lead_id
                AND d.decision_ordinal=1
                AND d.decided_at=NEW.updated_at
          )
        BEGIN SELECT RAISE(ABORT,'Lead disposition heads begin at exact ordinal one'); END""",
    """CREATE TRIGGER lead_disposition_head_update_guard
        BEFORE UPDATE ON lead_disposition_heads
        WHEN NEW.lead_id!=OLD.lead_id
          OR NEW.current_ordinal!=OLD.current_ordinal+1
          OR NOT EXISTS(
              SELECT 1 FROM lead_disposition_decisions d
              WHERE d.decision_id=NEW.current_decision_id
                AND d.lead_id=NEW.lead_id
                AND d.decision_ordinal=NEW.current_ordinal
                AND d.previous_decision_id=OLD.current_decision_id
                AND d.decided_at=NEW.updated_at
          )
        BEGIN SELECT RAISE(ABORT,'invalid Lead disposition head advance'); END""",
    """CREATE TRIGGER lead_disposition_head_delete_guard
        BEFORE DELETE ON lead_disposition_heads
        BEGIN SELECT RAISE(ABORT,'Lead disposition heads are retained'); END""",
    """CREATE TRIGGER lead_disposition_establish_head
        AFTER INSERT ON lead_disposition_decisions
        WHEN NEW.decision_ordinal=1
        BEGIN
          INSERT INTO lead_disposition_heads(
              lead_id,current_decision_id,current_ordinal,updated_at
          ) VALUES(NEW.lead_id,NEW.decision_id,1,NEW.decided_at);
        END""",
    """CREATE TRIGGER lead_disposition_advance_head
        AFTER INSERT ON lead_disposition_decisions
        WHEN NEW.decision_ordinal>1
        BEGIN
          UPDATE lead_disposition_heads
          SET current_decision_id=NEW.decision_id,
              current_ordinal=NEW.decision_ordinal,
              updated_at=NEW.decided_at
          WHERE lead_id=NEW.lead_id;
        END""",
    """CREATE TRIGGER immutable_discovery_signals_update
        BEFORE UPDATE ON discovery_signals BEGIN
        SELECT RAISE(ABORT,'immutable Discovery Signal'); END""",
    """CREATE TRIGGER immutable_discovery_signals_delete
        BEFORE DELETE ON discovery_signals BEGIN
        SELECT RAISE(ABORT,'Discovery Signals are retained'); END""",
    """CREATE TRIGGER immutable_discovery_signal_findings_update
        BEFORE UPDATE ON discovery_signal_findings BEGIN
        SELECT RAISE(ABORT,'immutable Signal Finding lineage'); END""",
    """CREATE TRIGGER immutable_discovery_signal_findings_delete
        BEFORE DELETE ON discovery_signal_findings BEGIN
        SELECT RAISE(ABORT,'Signal Finding lineage is retained'); END""",
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
    """CREATE TRIGGER immutable_news_lead_roles_update
        BEFORE UPDATE ON news_lead_source_roles BEGIN
        SELECT RAISE(ABORT,'immutable News Lead role'); END""",
    """CREATE TRIGGER immutable_news_lead_roles_delete
        BEFORE DELETE ON news_lead_source_roles BEGIN
        SELECT RAISE(ABORT,'News Lead roles are retained'); END""",
    """CREATE TRIGGER immutable_news_lead_functions_update
        BEFORE UPDATE ON news_lead_portfolio_functions BEGIN
        SELECT RAISE(ABORT,'immutable News Lead portfolio function'); END""",
    """CREATE TRIGGER immutable_news_lead_functions_delete
        BEFORE DELETE ON news_lead_portfolio_functions BEGIN
        SELECT RAISE(ABORT,'News Lead portfolio functions are retained'); END""",
    """CREATE TRIGGER immutable_news_lead_dependencies_update
        BEFORE UPDATE ON news_lead_source_dependencies BEGIN
        SELECT RAISE(ABORT,'immutable News Lead dependency'); END""",
    """CREATE TRIGGER immutable_news_lead_dependencies_delete
        BEFORE DELETE ON news_lead_source_dependencies BEGIN
        SELECT RAISE(ABORT,'News Lead dependencies are retained'); END""",
    """CREATE TRIGGER immutable_watch_conditions_update
        BEFORE UPDATE ON discovery_watch_conditions BEGIN
        SELECT RAISE(ABORT,'immutable Watch Condition'); END""",
    """CREATE TRIGGER immutable_watch_conditions_delete
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
