from __future__ import annotations


_IMMUTABLE_TABLES = (
    ("extractor_contracts", "extractor contract"),
    ("extraction_runs", "extraction run"),
    ("extraction_passages", "extraction passage"),
    ("extraction_attempts", "extraction attempt"),
    ("extraction_outputs", "extraction output"),
    ("extraction_proposal_sets", "extraction proposal set"),
    ("extraction_proposals", "extraction proposal"),
    ("extraction_proposal_passages", "extraction proposal passage"),
)


EXTRACTION_AUTHORITY_GUARD_STATEMENTS: tuple[str, ...] = (
    """CREATE TRIGGER extractor_contract_predecessor_guard
        BEFORE INSERT ON extractor_contracts
        WHEN NEW.version_number>1 AND NOT EXISTS(
            SELECT 1 FROM extractor_contracts p
            WHERE p.contract_id=NEW.previous_contract_id
              AND p.contract_family=NEW.contract_family
              AND p.version_number=NEW.version_number-1
        ) BEGIN
        SELECT RAISE(ABORT,'extractor contract predecessor mismatch'); END""",
    """CREATE TRIGGER extractor_contract_create_head
        AFTER INSERT ON extractor_contracts
        WHEN NEW.version_number=1 BEGIN
        INSERT INTO extractor_contract_heads(
            contract_family,current_version_number,current_contract_id,updated_at
        ) VALUES(NEW.contract_family,1,NEW.contract_id,NEW.recorded_at); END""",
    """CREATE TRIGGER extractor_contract_advance_head
        AFTER INSERT ON extractor_contracts
        WHEN NEW.version_number>1 BEGIN
        UPDATE extractor_contract_heads
        SET current_version_number=NEW.version_number,
            current_contract_id=NEW.contract_id,
            updated_at=NEW.recorded_at
        WHERE contract_family=NEW.contract_family
          AND current_version_number=NEW.version_number-1
          AND current_contract_id=NEW.previous_contract_id;
        SELECT CASE WHEN changes()!=1 THEN
            RAISE(ABORT,'extractor contract head mismatch') END; END""",
    """CREATE TRIGGER extractor_contract_heads_insert_guard
        BEFORE INSERT ON extractor_contract_heads
        WHEN NEW.current_version_number!=1 BEGIN
        SELECT RAISE(ABORT,'extractor contract head must begin at one'); END""",
    """CREATE TRIGGER extractor_contract_heads_update_guard
        BEFORE UPDATE ON extractor_contract_heads
        WHEN NEW.contract_family!=OLD.contract_family
          OR NEW.current_version_number!=OLD.current_version_number+1
          OR NEW.current_contract_id=OLD.current_contract_id
        BEGIN SELECT RAISE(ABORT,'invalid extractor contract head update'); END""",
    """CREATE TRIGGER extractor_contract_heads_delete_guard
        BEFORE DELETE ON extractor_contract_heads BEGIN
        SELECT RAISE(ABORT,'extractor contract heads are retained'); END""",
    """CREATE TRIGGER extraction_run_lineage_guard
        BEFORE INSERT ON extraction_runs
        WHEN NOT EXISTS(
            SELECT 1
            FROM extractor_contracts c
            JOIN extractor_contract_heads ch
              ON ch.contract_family=c.contract_family
             AND ch.current_contract_id=c.contract_id
            JOIN source_definition_versions v
              ON v.version_id=NEW.definition_version_id
             AND v.definition_id=NEW.definition_id
            JOIN source_definition_version_heads vh
              ON vh.definition_id=NEW.definition_id
             AND vh.current_version_id=NEW.definition_version_id
            JOIN source_items i
              ON i.item_id=NEW.item_id
             AND i.definition_id=NEW.definition_id
            JOIN source_revisions r
              ON r.revision_id=NEW.revision_id
             AND r.item_id=NEW.item_id
             AND r.definition_id=NEW.definition_id
             AND r.definition_version_id=NEW.definition_version_id
            JOIN discovery_representations p
              ON p.representation_id=NEW.representation_id
             AND p.revision_id=NEW.revision_id
             AND p.definition_id=NEW.definition_id
             AND p.definition_version_id=NEW.definition_version_id
            WHERE c.contract_id=NEW.contract_id
              AND c.canonical_digest=NEW.contract_digest
              AND v.rights_decision_id=NEW.rights_decision_id
              AND v.rights_policy_version=NEW.rights_policy_version
              AND v.allowed_use=NEW.allowed_use
              AND v.source_retention_scope=NEW.source_retention_scope
              AND v.lifecycle_stage NOT IN('RETIRED','REJECTED')
        ) BEGIN
        SELECT RAISE(ABORT,'extraction run lineage or current rights mismatch'); END""",
    """CREATE TRIGGER extraction_passage_ordinal_guard
        BEFORE INSERT ON extraction_passages
        WHEN NEW.ordinal!=(
            SELECT COUNT(*) FROM extraction_passages WHERE run_id=NEW.run_id
        ) BEGIN
        SELECT RAISE(ABORT,'extraction passage ordinals must be contiguous'); END""",
    """CREATE TRIGGER extraction_attempt_predecessor_guard
        BEFORE INSERT ON extraction_attempts
        WHEN (NEW.attempt_number=1 AND EXISTS(
                SELECT 1 FROM extraction_attempts WHERE run_id=NEW.run_id
             ))
          OR (NEW.attempt_number>1 AND NOT EXISTS(
                SELECT 1 FROM extraction_attempts p
                WHERE p.attempt_id=NEW.previous_attempt_id
                  AND p.run_id=NEW.run_id
                  AND p.attempt_number=NEW.attempt_number-1
                  AND p.outcome='RETRYABLE_FAILURE'
             ))
        BEGIN SELECT RAISE(ABORT,'extraction attempt predecessor mismatch'); END""",
    """CREATE TRIGGER extraction_attempt_resource_guard
        BEFORE INSERT ON extraction_attempts
        WHEN NOT EXISTS(
            SELECT 1 FROM extraction_runs r
            JOIN extractor_contracts c ON c.contract_id=r.contract_id
            WHERE r.run_id=NEW.run_id
              AND NEW.attempt_number<=c.max_attempts
              AND NEW.input_bytes<=c.max_input_bytes
              AND NEW.output_bytes<=c.max_output_bytes
              AND NEW.input_tokens<=c.max_input_tokens
              AND NEW.output_tokens<=c.max_output_tokens
              AND NEW.cost_microunits<=c.max_cost_microunits
        ) BEGIN
        SELECT RAISE(ABORT,'extraction attempt exceeds contract bounds'); END""",
    """CREATE TRIGGER extraction_attempt_create_head
        AFTER INSERT ON extraction_attempts
        WHEN NEW.attempt_number=1 BEGIN
        INSERT INTO extraction_attempt_heads(
            run_id,current_attempt_number,current_attempt_id,current_outcome,updated_at
        ) VALUES(NEW.run_id,1,NEW.attempt_id,NEW.outcome,NEW.recorded_at); END""",
    """CREATE TRIGGER extraction_attempt_advance_head
        AFTER INSERT ON extraction_attempts
        WHEN NEW.attempt_number>1 BEGIN
        UPDATE extraction_attempt_heads
        SET current_attempt_number=NEW.attempt_number,
            current_attempt_id=NEW.attempt_id,
            current_outcome=NEW.outcome,
            updated_at=NEW.recorded_at
        WHERE run_id=NEW.run_id
          AND current_attempt_number=NEW.attempt_number-1
          AND current_attempt_id=NEW.previous_attempt_id
          AND current_outcome='RETRYABLE_FAILURE';
        SELECT CASE WHEN changes()!=1 THEN
            RAISE(ABORT,'extraction attempt head mismatch') END; END""",
    """CREATE TRIGGER extraction_attempt_heads_insert_guard
        BEFORE INSERT ON extraction_attempt_heads
        WHEN NEW.current_attempt_number!=1 BEGIN
        SELECT RAISE(ABORT,'extraction attempt head must begin at one'); END""",
    """CREATE TRIGGER extraction_attempt_heads_update_guard
        BEFORE UPDATE ON extraction_attempt_heads
        WHEN NEW.run_id!=OLD.run_id
          OR NEW.current_attempt_number!=OLD.current_attempt_number+1
          OR NEW.current_attempt_id=OLD.current_attempt_id
          OR OLD.current_outcome!='RETRYABLE_FAILURE'
        BEGIN SELECT RAISE(ABORT,'invalid extraction attempt head update'); END""",
    """CREATE TRIGGER extraction_attempt_heads_delete_guard
        BEFORE DELETE ON extraction_attempt_heads BEGIN
        SELECT RAISE(ABORT,'extraction attempt heads are retained'); END""",
    """CREATE TRIGGER extraction_output_attempt_guard
        BEFORE INSERT ON extraction_outputs
        WHEN NOT EXISTS(
            SELECT 1 FROM extraction_attempts a
            WHERE a.attempt_id=NEW.attempt_id
              AND a.run_id=NEW.run_id
              AND a.outcome IN('SUCCESS','PARTIAL','INVALID_OUTPUT')
              AND ((a.outcome='INVALID_OUTPUT' AND NEW.valid=0)
                OR (a.outcome IN('SUCCESS','PARTIAL') AND NEW.valid=1))
              AND a.output_bytes=CASE
                    WHEN NEW.structured_output_bytes IS NULL THEN a.output_bytes
                    ELSE length(NEW.structured_output_bytes)
                  END
        ) BEGIN
        SELECT RAISE(ABORT,'extraction output differs from attempt outcome'); END""",
    """CREATE TRIGGER extraction_proposal_set_persisted_output_guard
        BEFORE INSERT ON extraction_proposal_sets
        WHEN NOT EXISTS(
            SELECT 1
            FROM extraction_outputs o
            JOIN extraction_attempts a
              ON a.attempt_id=o.attempt_id AND a.run_id=o.run_id
            JOIN ledger_events oe ON oe.event_id=o.authority_event_id
            JOIN ledger_events pe ON pe.event_id=NEW.authority_event_id
            JOIN extraction_runs r ON r.run_id=o.run_id
            JOIN extractor_contracts c ON c.contract_id=r.contract_id
            WHERE o.output_id=NEW.output_id
              AND o.attempt_id=NEW.attempt_id
              AND o.run_id=NEW.run_id
              AND o.valid=1
              AND a.outcome IN('SUCCESS','PARTIAL')
              AND ((a.outcome='SUCCESS' AND NEW.completeness='COMPLETE')
                OR (a.outcome='PARTIAL' AND NEW.completeness='PARTIAL'))
              AND NEW.proposal_count<=c.max_proposals
              AND oe.ledger_seq<pe.ledger_seq
        ) BEGIN
        SELECT RAISE(ABORT,'proposal set requires earlier retained valid output'); END""",
    """CREATE TRIGGER extraction_proposal_lineage_guard
        BEFORE INSERT ON extraction_proposals
        WHEN NOT EXISTS(
            SELECT 1 FROM extraction_proposal_sets s
            WHERE s.proposal_set_id=NEW.proposal_set_id
              AND s.run_id=NEW.run_id
              AND s.attempt_id=NEW.attempt_id
              AND s.output_id=NEW.output_id
        ) BEGIN
        SELECT RAISE(ABORT,'proposal lineage differs from proposal set'); END""",
    """CREATE TRIGGER extraction_proposal_passage_guard
        BEFORE INSERT ON extraction_proposal_passages
        WHEN NOT EXISTS(
            SELECT 1 FROM extraction_proposals p
            JOIN extraction_proposal_sets s
              ON s.proposal_set_id=p.proposal_set_id
            WHERE p.proposal_id=NEW.proposal_id
              AND p.run_id=NEW.run_id
              AND EXISTS(
                SELECT 1 FROM extraction_passages x
                WHERE x.run_id=NEW.run_id
                  AND x.passage_id=NEW.passage_id
              )
        ) BEGIN
        SELECT RAISE(ABORT,'proposal passage is outside retained run input'); END""",
) + tuple(
    statement
    for table, identity in _IMMUTABLE_TABLES
    for statement in (
        f"""CREATE TRIGGER immutable_{table}_update
            BEFORE UPDATE ON {table} BEGIN
            SELECT RAISE(ABORT,'immutable {identity}'); END""",
        f"""CREATE TRIGGER immutable_{table}_delete
            BEFORE DELETE ON {table} BEGIN
            SELECT RAISE(ABORT,'immutable {identity}'); END""",
    )
)


__all__ = ["EXTRACTION_AUTHORITY_GUARD_STATEMENTS"]
