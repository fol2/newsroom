from __future__ import annotations


CHECK_AUTHORITY_GUARD_STATEMENTS: tuple[str, ...] = (
    """CREATE TRIGGER check_request_source_contract_guard
        BEFORE INSERT ON check_requests
        WHEN NOT EXISTS(
            SELECT 1 FROM source_definition_versions v
            WHERE v.version_id=NEW.definition_version_id
              AND v.definition_id=NEW.definition_id
              AND v.rights_decision_id=NEW.rights_decision_id
              AND v.rights_policy_version=NEW.rights_policy_version
              AND v.baseline_policy_id=NEW.baseline_policy_id
              AND v.baseline_policy_version=NEW.baseline_policy_version
              AND v.revision_policy_id=NEW.revision_policy_id
              AND v.revision_policy_version=NEW.revision_policy_version
        )
        BEGIN SELECT RAISE(ABORT,'Check Request source contract mismatch'); END""",
    """CREATE TRIGGER check_request_coverage_guard
        BEFORE INSERT ON check_requests
        WHEN NOT EXISTS(
            SELECT 1 FROM source_version_coverage_mappings c
            WHERE c.version_id=NEW.definition_version_id
              AND c.obligation_id=NEW.coverage_obligation_id
              AND c.responsibility=NEW.coverage_responsibility
              AND c.contribution=NEW.coverage_contribution
        )
        BEGIN SELECT RAISE(ABORT,'Check Request coverage mismatch'); END""",
    """CREATE TRIGGER baseline_decision_source_contract_guard
        BEFORE INSERT ON baseline_decisions
        WHEN NOT EXISTS(
            SELECT 1
            FROM source_definition_versions v
            JOIN check_requests r
              ON r.request_id=NEW.check_request_id
            JOIN check_outcomes o
              ON o.outcome_id=NEW.check_outcome_id
            WHERE v.version_id=NEW.definition_version_id
              AND v.definition_id=NEW.definition_id
              AND v.observation_model=NEW.observation_model
              AND v.baseline_policy_id=NEW.baseline_policy_id
              AND v.baseline_policy_version=NEW.baseline_policy_version
              AND r.definition_id=NEW.definition_id
              AND r.definition_version_id=NEW.definition_version_id
              AND r.baseline_policy_id=NEW.baseline_policy_id
              AND r.baseline_policy_version=NEW.baseline_policy_version
              AND o.request_id=NEW.check_request_id
              AND o.definition_id=NEW.definition_id
              AND o.definition_version_id=NEW.definition_version_id
              AND (
                  NEW.disposition='MANUAL_HOLD'
                  OR (
                      o.incomplete=0
                      AND o.kind IN(
                          'SUCCESS_EMPTY','SUCCESS_UNCHANGED','SUCCESS_CHANGED'
                      )
                      AND o.source_body_digest IS NEW.source_body_digest
                      AND o.producer_slot_digest IS NEW.producer_slot_digest
                      AND o.representation_digest IS NEW.representation_digest
                      AND o.validator_digest IS NEW.validator_digest
                  )
              )
        )
        BEGIN SELECT RAISE(ABORT,'Baseline Decision source contract mismatch'); END""",
    """CREATE TRIGGER baseline_manifest_source_guard
        BEFORE INSERT ON baseline_manifest_entries
        WHEN NEW.item_id IS NOT NULL AND NOT EXISTS(
            SELECT 1
            FROM baseline_decisions d
            JOIN source_items i ON i.item_id=NEW.item_id
            JOIN source_revisions r
              ON r.revision_id=NEW.revision_id
             AND r.item_id=NEW.item_id
            WHERE d.decision_id=NEW.decision_id
              AND i.definition_id=d.definition_id
              AND r.definition_id=d.definition_id
        )
        BEGIN SELECT RAISE(ABORT,'baseline manifest source lineage mismatch'); END""",
    """CREATE TRIGGER observable_transition_source_contract_guard
        BEFORE INSERT ON observable_transitions
        WHEN NOT EXISTS(
            SELECT 1
            FROM source_definition_versions v
            JOIN check_outcomes o
              ON o.outcome_id=NEW.check_outcome_id
            WHERE v.version_id=NEW.definition_version_id
              AND v.definition_id=NEW.definition_id
              AND v.observation_model=NEW.observation_model
              AND o.definition_id=NEW.definition_id
              AND o.definition_version_id=NEW.definition_version_id
              AND (
                  o.incomplete=0
                  OR NEW.kind='AMBIGUOUS_ABSENCE'
                  OR NEW.current_revision_id IS NOT NULL
              )
        )
        BEGIN SELECT RAISE(ABORT,'observable transition source contract mismatch'); END""",
    """CREATE TRIGGER operational_finding_lineage_guard
        BEFORE INSERT ON operational_findings
        WHEN (NEW.opened_by_attempt_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM check_attempts a
                WHERE a.attempt_id=NEW.opened_by_attempt_id
                  AND (
                      NEW.opened_by_request_id IS NULL
                      OR a.request_id=NEW.opened_by_request_id
                  )
             ))
          OR (NEW.opened_by_outcome_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM check_outcomes o
                WHERE o.outcome_id=NEW.opened_by_outcome_id
                  AND (
                      NEW.opened_by_request_id IS NULL
                      OR o.request_id=NEW.opened_by_request_id
                  )
                  AND (
                      NEW.opened_by_attempt_id IS NULL
                      OR o.attempt_id=NEW.opened_by_attempt_id
                  )
             ))
        BEGIN SELECT RAISE(ABORT,'Operational Finding Check lineage mismatch'); END""",
    """CREATE TRIGGER finding_occurrence_lineage_guard
        BEFORE INSERT ON operational_finding_occurrences
        WHEN (NEW.attempt_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM check_attempts a
                WHERE a.attempt_id=NEW.attempt_id
                  AND (NEW.request_id IS NULL OR a.request_id=NEW.request_id)
             ))
          OR (NEW.outcome_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM check_outcomes o
                WHERE o.outcome_id=NEW.outcome_id
                  AND (NEW.request_id IS NULL OR o.request_id=NEW.request_id)
                  AND (NEW.attempt_id IS NULL OR o.attempt_id=NEW.attempt_id)
             ))
        BEGIN SELECT RAISE(ABORT,'Finding occurrence Check lineage mismatch'); END""",
    """CREATE TRIGGER check_attempt_exact_predecessor_guard
        BEFORE INSERT ON check_attempts
        WHEN NEW.attempt_number>1 AND NOT EXISTS(
            SELECT 1 FROM check_attempts p
            WHERE p.attempt_id=NEW.prior_attempt_id
              AND p.request_id=NEW.request_id
              AND p.attempt_number=NEW.attempt_number-1
        )
        BEGIN SELECT RAISE(ABORT,'check attempt predecessor mismatch'); END""",
    """CREATE TRIGGER check_outcome_chronology_guard
        BEFORE INSERT ON check_outcomes
        WHEN EXISTS(
            SELECT 1 FROM check_attempts a
            WHERE a.attempt_id=NEW.attempt_id
              AND NEW.completed_at<a.started_at
        )
        BEGIN SELECT RAISE(ABORT,'check outcome precedes attempt'); END""",
    """CREATE TRIGGER check_outcome_retroactive_occurrence_guard
        BEFORE INSERT ON check_outcomes
        WHEN EXISTS(
            SELECT 1 FROM discovery_occurrences o
            WHERE o.check_outcome_id=NEW.outcome_id
        )
        BEGIN SELECT RAISE(ABORT,'check outcome cannot adopt prior occurrence'); END""",
    """CREATE TRIGGER baseline_decision_chain_guard
        BEFORE INSERT ON baseline_decisions
        WHEN (NEW.kind='ESTABLISH' AND EXISTS(
                SELECT 1 FROM baseline_decision_heads h
                WHERE h.definition_id=NEW.definition_id
             ))
          OR (NEW.kind IN('RESET','REBUILD') AND NOT EXISTS(
                SELECT 1 FROM baseline_decision_heads h
                WHERE h.definition_id=NEW.definition_id
                  AND h.current_decision_id=NEW.previous_decision_id
             ))
        BEGIN SELECT RAISE(ABORT,'Baseline Decision does not extend current head'); END""",
    """CREATE TRIGGER baseline_decision_predecessor_guard
        BEFORE INSERT ON baseline_decisions
        WHEN NEW.previous_decision_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM baseline_decisions p
            WHERE p.decision_id=NEW.previous_decision_id
              AND p.definition_id=NEW.definition_id
        )
        BEGIN SELECT RAISE(ABORT,'baseline predecessor differs from source'); END""",
    """CREATE TRIGGER baseline_head_insert_guard
        BEFORE INSERT ON baseline_decision_heads
        WHEN NOT EXISTS(
            SELECT 1 FROM baseline_decisions d
            WHERE d.decision_id=NEW.current_decision_id
              AND d.definition_id=NEW.definition_id
              AND d.kind='ESTABLISH'
              AND d.previous_decision_id IS NULL
        )
        BEGIN SELECT RAISE(ABORT,'baseline head requires establishment'); END""",
    """CREATE TRIGGER baseline_head_update_guard
        BEFORE UPDATE ON baseline_decision_heads
        WHEN NEW.definition_id!=OLD.definition_id
          OR NOT EXISTS(
            SELECT 1
            FROM baseline_decisions n
            JOIN baseline_decisions p
              ON p.decision_id=OLD.current_decision_id
            JOIN ledger_events ne ON ne.event_id=n.authority_event_id
            JOIN ledger_events pe ON pe.event_id=p.authority_event_id
            WHERE n.decision_id=NEW.current_decision_id
              AND n.definition_id=NEW.definition_id
              AND n.previous_decision_id=OLD.current_decision_id
              AND ne.ledger_seq>pe.ledger_seq
          )
        BEGIN SELECT RAISE(ABORT,'invalid baseline-head update'); END""",
    """CREATE TRIGGER baseline_head_delete_guard
        BEFORE DELETE ON baseline_decision_heads BEGIN
        SELECT RAISE(ABORT,'baseline heads are retained'); END""",
    """CREATE TRIGGER baseline_decision_establish_head
        AFTER INSERT ON baseline_decisions
        WHEN NEW.kind='ESTABLISH'
        BEGIN
            INSERT INTO baseline_decision_heads(
                definition_id,current_decision_id,updated_at
            ) VALUES(NEW.definition_id,NEW.decision_id,NEW.decided_at);
        END""",
    """CREATE TRIGGER baseline_decision_advance_head
        AFTER INSERT ON baseline_decisions
        WHEN NEW.kind IN('RESET','REBUILD')
        BEGIN
            UPDATE baseline_decision_heads
            SET current_decision_id=NEW.decision_id,
                updated_at=NEW.decided_at
            WHERE definition_id=NEW.definition_id
              AND current_decision_id=NEW.previous_decision_id;
        END""",
    """CREATE TRIGGER discovery_occurrence_check_link
        AFTER INSERT ON discovery_occurrences
        WHEN EXISTS(
            SELECT 1 FROM check_outcomes c
            WHERE c.outcome_id=NEW.check_outcome_id
        )
        BEGIN
            INSERT INTO discovery_occurrence_check_links(
                occurrence_id,check_outcome_id
            ) VALUES(NEW.occurrence_id,NEW.check_outcome_id);
        END""",
    """CREATE TRIGGER immutable_check_requests_update
        BEFORE UPDATE ON check_requests BEGIN
        SELECT RAISE(ABORT,'immutable Check Request'); END""",
    """CREATE TRIGGER immutable_check_requests_delete
        BEFORE DELETE ON check_requests BEGIN
        SELECT RAISE(ABORT,'Check Requests are retained'); END""",
    """CREATE TRIGGER immutable_check_attempts_update
        BEFORE UPDATE ON check_attempts BEGIN
        SELECT RAISE(ABORT,'immutable Check Attempt'); END""",
    """CREATE TRIGGER immutable_check_attempts_delete
        BEFORE DELETE ON check_attempts BEGIN
        SELECT RAISE(ABORT,'Check Attempts are retained'); END""",
    """CREATE TRIGGER immutable_check_outcomes_update
        BEFORE UPDATE ON check_outcomes BEGIN
        SELECT RAISE(ABORT,'immutable Check Outcome'); END""",
    """CREATE TRIGGER immutable_check_outcomes_delete
        BEFORE DELETE ON check_outcomes BEGIN
        SELECT RAISE(ABORT,'Check Outcomes are retained'); END""",
    """CREATE TRIGGER immutable_baseline_decisions_update
        BEFORE UPDATE ON baseline_decisions BEGIN
        SELECT RAISE(ABORT,'immutable Baseline Decision'); END""",
    """CREATE TRIGGER immutable_baseline_decisions_delete
        BEFORE DELETE ON baseline_decisions BEGIN
        SELECT RAISE(ABORT,'Baseline Decisions are retained'); END""",
    """CREATE TRIGGER immutable_baseline_entries_update
        BEFORE UPDATE ON baseline_manifest_entries BEGIN
        SELECT RAISE(ABORT,'immutable baseline manifest entry'); END""",
    """CREATE TRIGGER immutable_baseline_entries_delete
        BEFORE DELETE ON baseline_manifest_entries BEGIN
        SELECT RAISE(ABORT,'baseline manifest entries are retained'); END""",
    """CREATE TRIGGER immutable_observable_transitions_update
        BEFORE UPDATE ON observable_transitions BEGIN
        SELECT RAISE(ABORT,'immutable observable transition'); END""",
    """CREATE TRIGGER immutable_observable_transitions_delete
        BEFORE DELETE ON observable_transitions BEGIN
        SELECT RAISE(ABORT,'observable transitions are retained'); END""",
    """CREATE TRIGGER immutable_operational_findings_update
        BEFORE UPDATE ON operational_findings BEGIN
        SELECT RAISE(ABORT,'immutable Operational Finding'); END""",
    """CREATE TRIGGER immutable_operational_findings_delete
        BEFORE DELETE ON operational_findings BEGIN
        SELECT RAISE(ABORT,'Operational Findings are retained'); END""",
    """CREATE TRIGGER immutable_finding_occurrences_update
        BEFORE UPDATE ON operational_finding_occurrences BEGIN
        SELECT RAISE(ABORT,'immutable Finding occurrence'); END""",
    """CREATE TRIGGER immutable_finding_occurrences_delete
        BEFORE DELETE ON operational_finding_occurrences BEGIN
        SELECT RAISE(ABORT,'Finding occurrences are retained'); END""",
    """CREATE TRIGGER immutable_occurrence_check_links_update
        BEFORE UPDATE ON discovery_occurrence_check_links BEGIN
        SELECT RAISE(ABORT,'immutable occurrence Check link'); END""",
    """CREATE TRIGGER immutable_occurrence_check_links_delete
        BEFORE DELETE ON discovery_occurrence_check_links BEGIN
        SELECT RAISE(ABORT,'occurrence Check links are retained'); END""",
)


__all__ = ["CHECK_AUTHORITY_GUARD_STATEMENTS"]
