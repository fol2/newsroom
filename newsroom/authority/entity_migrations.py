from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


ENTITY_AUTHORITY_SCHEMA_VERSION = 14
ENTITY_AUTHORITY_MIGRATION_NAME = "entity_resolution_authority_v14"


@dataclass(frozen=True, slots=True)
class EntityAuthorityMigrationRecord:
    version: int
    name: str
    checksum: str


_ENTITY_KINDS = (
    "'PERSON','ORGANISATION','GOVERNMENT_BODY','LOCATION','FACILITY',"
    "'PRODUCT','WORK','EVENT','OTHER','UNKNOWN'"
)
_ENTITY_SCRIPTS = "'LATIN','TRADITIONAL_HAN','MIXED','UNKNOWN'"
_ALIAS_KINDS = (
    "'PRIMARY_NAME','ALIAS','LEGAL_NAME','ABBREVIATION','TRANSLATION',"
    "'TRANSLITERATION'"
)
_RESOLUTION_PROPOSAL_KINDS = (
    "'MENTION_TO_NEW_ENTITY','MENTION_TO_ENTITY','MENTION_EQUIVALENCE',"
    "'ALIAS_TO_ENTITY'"
)
_RESOLUTION_ACTIONS = "'ACCEPT','REJECT','HOLD','UNRESOLVED'"
_RESOLUTION_STATES = "'PROPOSED','HELD','UNRESOLVED','ACCEPTED','REJECTED','REVERSED'"
_ENTITY_LIFECYCLES = "'ACTIVE','MERGED','SPLIT','REVERSED','RETIRED'"
_LINEAGE_KINDS = "'MERGE','SPLIT','REVERSAL'"
_REVERSAL_TARGETS = "'RESOLUTION','MERGE','SPLIT'"
_PROJECTION_ACTIONS = "'UPSERT','REMOVE'"


ENTITY_AUTHORITY_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE entity_mentions(
        mention_id TEXT PRIMARY KEY,
        source_proposal_id TEXT NOT NULL UNIQUE
            REFERENCES extraction_proposals(proposal_id),
        proposal_set_id TEXT NOT NULL
            REFERENCES extraction_proposal_sets(proposal_set_id),
        output_id TEXT NOT NULL REFERENCES extraction_outputs(output_id),
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        run_version_id TEXT NOT NULL
            REFERENCES extraction_run_versions(run_version_id),
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        representation_id TEXT NOT NULL,
        passage_id TEXT NOT NULL,
        start_byte INTEGER NOT NULL CHECK(start_byte>=0),
        end_byte INTEGER NOT NULL CHECK(end_byte>start_byte),
        evidence_text_digest TEXT NOT NULL,
        mention_text TEXT NOT NULL,
        normalized_text TEXT NOT NULL,
        normalization_contract_digest TEXT NOT NULL,
        language TEXT NOT NULL,
        script TEXT NOT NULL CHECK(script IN({_ENTITY_SCRIPTS})),
        entity_kind TEXT NOT NULL CHECK(entity_kind IN({_ENTITY_KINDS})),
        confidence_basis_points INTEGER
            CHECK(confidence_basis_points IS NULL OR
                  (confidence_basis_points>=0 AND confidence_basis_points<=10000)),
        uncertainty_codes_bytes BLOB NOT NULL,
        rationale_codes_bytes BLOB NOT NULL,
        source_proposal_digest TEXT NOT NULL,
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
        FOREIGN KEY(representation_id,revision_id)
            REFERENCES discovery_representations(representation_id,revision_id),
        FOREIGN KEY(run_id,passage_id)
            REFERENCES extraction_run_passages(run_id,passage_id),
        FOREIGN KEY(run_version_id,run_id)
            REFERENCES extraction_run_versions(run_version_id,run_id),
        CHECK(length(mention_text)>0),
        CHECK(length(CAST(mention_text AS BLOB))=end_byte-start_byte),
        CHECK(length(normalized_text)>0),
        CHECK(length(uncertainty_codes_bytes)>0),
        CHECK(length(rationale_codes_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE entity_resolution_proposals(
        resolution_proposal_id TEXT PRIMARY KEY,
        source_proposal_id TEXT NOT NULL
            REFERENCES extraction_proposals(proposal_id),
        proposal_kind TEXT NOT NULL CHECK(proposal_kind IN({_RESOLUTION_PROPOSAL_KINDS})),
        subject_mention_id TEXT NOT NULL REFERENCES entity_mentions(mention_id),
        object_mention_id TEXT REFERENCES entity_mentions(mention_id),
        candidate_entity_id TEXT REFERENCES canonical_entities(entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        candidate_entity_version_id TEXT
            REFERENCES canonical_entity_versions(entity_version_id)
            DEFERRABLE INITIALLY DEFERRED,
        stable_semantic_digest TEXT NOT NULL UNIQUE,
        created_by_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        created_at TEXT NOT NULL,
        CHECK((proposal_kind='MENTION_TO_NEW_ENTITY'
               AND object_mention_id IS NULL
               AND candidate_entity_id IS NULL
               AND candidate_entity_version_id IS NULL)
           OR (proposal_kind IN('MENTION_TO_ENTITY','ALIAS_TO_ENTITY')
               AND object_mention_id IS NULL
               AND candidate_entity_id IS NOT NULL
               AND candidate_entity_version_id IS NOT NULL)
           OR (proposal_kind='MENTION_EQUIVALENCE'
               AND object_mention_id IS NOT NULL
               AND object_mention_id!=subject_mention_id
               AND candidate_entity_id IS NULL
               AND candidate_entity_version_id IS NULL)),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE entity_resolution_proposal_versions(
        proposal_version_id TEXT PRIMARY KEY,
        resolution_proposal_id TEXT NOT NULL
            REFERENCES entity_resolution_proposals(resolution_proposal_id),
        version_number INTEGER NOT NULL CHECK(version_number>0),
        previous_proposal_version_id TEXT
            REFERENCES entity_resolution_proposal_versions(proposal_version_id),
        source_proposal_digest TEXT NOT NULL,
        confidence_basis_points INTEGER
            CHECK(confidence_basis_points IS NULL OR
                  (confidence_basis_points>=0 AND confidence_basis_points<=10000)),
        uncertainty_codes_bytes BLOB NOT NULL,
        basis_codes_bytes BLOB NOT NULL,
        request_bytes BLOB NOT NULL,
        request_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        recorded_at TEXT NOT NULL,
        UNIQUE(resolution_proposal_id,version_number),
        UNIQUE(proposal_version_id,resolution_proposal_id),
        UNIQUE(resolution_proposal_id,version_number,proposal_version_id),
        CHECK((version_number=1 AND previous_proposal_version_id IS NULL)
           OR (version_number>1 AND previous_proposal_version_id IS NOT NULL)),
        CHECK(length(uncertainty_codes_bytes)>0),
        CHECK(length(basis_codes_bytes)>0),
        CHECK(length(request_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE entity_resolution_proposal_heads(
        resolution_proposal_id TEXT PRIMARY KEY
            REFERENCES entity_resolution_proposals(resolution_proposal_id),
        current_version_number INTEGER NOT NULL CHECK(current_version_number>0),
        current_proposal_version_id TEXT NOT NULL UNIQUE,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(
            resolution_proposal_id,current_version_number,current_proposal_version_id
        ) REFERENCES entity_resolution_proposal_versions(
            resolution_proposal_id,version_number,proposal_version_id
        ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE entity_resolution_decisions(
        decision_id TEXT PRIMARY KEY,
        resolution_proposal_id TEXT NOT NULL
            REFERENCES entity_resolution_proposals(resolution_proposal_id),
        proposal_version_id TEXT NOT NULL,
        proposal_digest TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN({_RESOLUTION_ACTIONS})),
        decision_version INTEGER NOT NULL CHECK(decision_version>0),
        previous_decision_id TEXT
            REFERENCES entity_resolution_decisions(decision_id),
        accepted_entity_id TEXT REFERENCES canonical_entities(entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        accepted_entity_version_id TEXT
            REFERENCES canonical_entity_versions(entity_version_id)
            DEFERRABLE INITIALLY DEFERRED,
        alias_id TEXT REFERENCES entity_aliases(alias_id)
            DEFERRABLE INITIALLY DEFERRED,
        reason_code TEXT NOT NULL,
        decision_policy_version TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(resolution_proposal_id,decision_version),
        UNIQUE(decision_id,resolution_proposal_id),
        FOREIGN KEY(proposal_version_id,resolution_proposal_id)
            REFERENCES entity_resolution_proposal_versions(
                proposal_version_id,resolution_proposal_id
            ),
        CHECK((decision_version=1 AND previous_decision_id IS NULL)
           OR (decision_version>1 AND previous_decision_id IS NOT NULL)),
        CHECK((action='ACCEPT'
               AND accepted_entity_id IS NOT NULL
               AND accepted_entity_version_id IS NOT NULL
               AND alias_id IS NOT NULL)
           OR (action!='ACCEPT'
               AND accepted_entity_id IS NULL
               AND accepted_entity_version_id IS NULL
               AND alias_id IS NULL)),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE entity_resolution_decision_heads(
        resolution_proposal_id TEXT PRIMARY KEY
            REFERENCES entity_resolution_proposals(resolution_proposal_id),
        current_decision_version INTEGER NOT NULL CHECK(current_decision_version>0),
        current_decision_id TEXT NOT NULL UNIQUE,
        current_state TEXT NOT NULL CHECK(current_state IN({_RESOLUTION_STATES})),
        terminal INTEGER NOT NULL CHECK(terminal IN(0,1)),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_decision_id,resolution_proposal_id)
            REFERENCES entity_resolution_decisions(
                decision_id,resolution_proposal_id
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE canonical_entities(
        entity_id TEXT PRIMARY KEY,
        entity_kind TEXT NOT NULL CHECK(entity_kind IN({_ENTITY_KINDS})),
        created_by_decision_id TEXT NOT NULL UNIQUE
            REFERENCES entity_resolution_decisions(decision_id)
            DEFERRABLE INITIALLY DEFERRED,
        initial_version_id TEXT NOT NULL UNIQUE
            REFERENCES canonical_entity_versions(entity_version_id)
            DEFERRABLE INITIALLY DEFERRED,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        created_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE canonical_entity_versions(
        entity_version_id TEXT PRIMARY KEY,
        entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        version_number INTEGER NOT NULL CHECK(version_number>0),
        previous_entity_version_id TEXT
            REFERENCES canonical_entity_versions(entity_version_id),
        entity_kind TEXT NOT NULL CHECK(entity_kind IN({_ENTITY_KINDS})),
        lifecycle TEXT NOT NULL CHECK(lifecycle IN({_ENTITY_LIFECYCLES})),
        lineage_decision_kind TEXT
            CHECK(lineage_decision_kind IS NULL OR lineage_decision_kind IN({_LINEAGE_KINDS})),
        lineage_decision_id TEXT,
        preferred_continuation_entity_id TEXT
            REFERENCES canonical_entities(entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(entity_id,version_number),
        UNIQUE(entity_version_id,entity_id),
        UNIQUE(entity_id,version_number,entity_version_id),
        CHECK((version_number=1 AND previous_entity_version_id IS NULL)
           OR (version_number>1 AND previous_entity_version_id IS NOT NULL)),
        CHECK((lineage_decision_kind IS NULL AND lineage_decision_id IS NULL)
           OR (lineage_decision_kind IS NOT NULL AND lineage_decision_id IS NOT NULL)),
        CHECK((lifecycle='ACTIVE'
               AND (preferred_continuation_entity_id IS NULL
                    OR preferred_continuation_entity_id=entity_id))
           OR lifecycle!='ACTIVE'),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE canonical_entity_heads(
        entity_id TEXT PRIMARY KEY REFERENCES canonical_entities(entity_id),
        current_version_number INTEGER NOT NULL CHECK(current_version_number>0),
        current_entity_version_id TEXT NOT NULL UNIQUE,
        lifecycle TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(entity_id,current_version_number,current_entity_version_id)
            REFERENCES canonical_entity_versions(
                entity_id,version_number,entity_version_id
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE entity_aliases(
        alias_id TEXT PRIMARY KEY,
        entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id),
        entity_version_id TEXT NOT NULL,
        alias_text TEXT NOT NULL,
        normalized_text TEXT NOT NULL,
        normalization_contract_digest TEXT NOT NULL,
        language TEXT NOT NULL,
        script TEXT NOT NULL CHECK(script IN({_ENTITY_SCRIPTS})),
        alias_kind TEXT NOT NULL CHECK(alias_kind IN({_ALIAS_KINDS})),
        valid_from TEXT,
        valid_until TEXT,
        provenance_mention_id TEXT NOT NULL REFERENCES entity_mentions(mention_id),
        resolution_decision_id TEXT NOT NULL
            REFERENCES entity_resolution_decisions(decision_id)
            DEFERRABLE INITIALLY DEFERRED,
        uncertainty_codes_bytes BLOB NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(entity_version_id,entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id),
        CHECK(valid_until IS NULL OR valid_from IS NULL OR valid_until>valid_from),
        CHECK(length(alias_text)>0),
        CHECK(length(normalized_text)>0),
        CHECK(length(uncertainty_codes_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE entity_mention_resolutions(
        mention_id TEXT NOT NULL REFERENCES entity_mentions(mention_id),
        decision_id TEXT NOT NULL UNIQUE
            REFERENCES entity_resolution_decisions(decision_id),
        resolution_proposal_id TEXT NOT NULL
            REFERENCES entity_resolution_proposals(resolution_proposal_id),
        entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id),
        entity_version_id TEXT NOT NULL,
        alias_id TEXT NOT NULL UNIQUE REFERENCES entity_aliases(alias_id),
        admitted_at TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(mention_id,decision_id),
        FOREIGN KEY(entity_version_id,entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE entity_merge_decisions(
        merge_decision_id TEXT PRIMARY KEY,
        successor_entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        successor_entity_version_id TEXT NOT NULL,
        preferred_continuation_entity_id TEXT NOT NULL
            REFERENCES canonical_entities(entity_id),
        predecessor_count INTEGER NOT NULL CHECK(predecessor_count>=2),
        basis_resolution_proposal_ids_bytes BLOB NOT NULL,
        reason_code TEXT NOT NULL,
        decision_policy_version TEXT NOT NULL,
        request_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(successor_entity_version_id,successor_entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        CHECK(length(basis_resolution_proposal_ids_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE entity_merge_predecessors(
        merge_decision_id TEXT NOT NULL
            REFERENCES entity_merge_decisions(merge_decision_id),
        predecessor_ordinal INTEGER NOT NULL CHECK(predecessor_ordinal>0),
        entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id),
        expected_entity_version_id TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(merge_decision_id,predecessor_ordinal),
        UNIQUE(merge_decision_id,entity_id),
        FOREIGN KEY(expected_entity_version_id,entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE entity_split_decisions(
        split_decision_id TEXT PRIMARY KEY,
        source_entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id),
        expected_source_version_id TEXT NOT NULL,
        successor_count INTEGER NOT NULL CHECK(successor_count>=2),
        reason_code TEXT NOT NULL,
        decision_policy_version TEXT NOT NULL,
        request_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(expected_source_version_id,source_entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE entity_split_successors(
        split_decision_id TEXT NOT NULL
            REFERENCES entity_split_decisions(split_decision_id),
        successor_ordinal INTEGER NOT NULL CHECK(successor_ordinal>0),
        entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        entity_version_id TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(split_decision_id,successor_ordinal),
        UNIQUE(split_decision_id,entity_id),
        FOREIGN KEY(entity_version_id,entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE entity_split_allocations(
        split_decision_id TEXT NOT NULL
            REFERENCES entity_split_decisions(split_decision_id),
        mention_id TEXT NOT NULL REFERENCES entity_mentions(mention_id),
        successor_entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id)
            DEFERRABLE INITIALLY DEFERRED,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(split_decision_id,mention_id),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE entity_reversal_decisions(
        reversal_decision_id TEXT PRIMARY KEY,
        target_kind TEXT NOT NULL CHECK(target_kind IN({_REVERSAL_TARGETS})),
        target_decision_id TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        decision_policy_version TEXT NOT NULL,
        request_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE entity_reversal_expected_versions(
        reversal_decision_id TEXT NOT NULL
            REFERENCES entity_reversal_decisions(reversal_decision_id),
        version_ordinal INTEGER NOT NULL CHECK(version_ordinal>0),
        entity_version_id TEXT NOT NULL UNIQUE
            REFERENCES canonical_entity_versions(entity_version_id),
        PRIMARY KEY(reversal_decision_id,version_ordinal)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE entity_reversal_restorations(
        reversal_decision_id TEXT NOT NULL
            REFERENCES entity_reversal_decisions(reversal_decision_id),
        restoration_ordinal INTEGER NOT NULL CHECK(restoration_ordinal>0),
        entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id),
        entity_version_id TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(reversal_decision_id,restoration_ordinal),
        UNIQUE(reversal_decision_id,entity_id),
        FOREIGN KEY(entity_version_id,entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE entity_resolution_dependencies(
        dependent_proposal_id TEXT NOT NULL
            REFERENCES extraction_proposals(proposal_id),
        resolution_proposal_id TEXT NOT NULL
            REFERENCES entity_resolution_proposals(resolution_proposal_id),
        proposal_version_id TEXT NOT NULL,
        material INTEGER NOT NULL CHECK(material IN(0,1)),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(dependent_proposal_id,resolution_proposal_id),
        FOREIGN KEY(proposal_version_id,resolution_proposal_id)
            REFERENCES entity_resolution_proposal_versions(
                proposal_version_id,resolution_proposal_id
            ),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE entity_preferred_identities(
        entity_id TEXT PRIMARY KEY REFERENCES canonical_entities(entity_id),
        current_entity_version_id TEXT NOT NULL,
        preferred_entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id),
        lifecycle TEXT NOT NULL CHECK(lifecycle IN({_ENTITY_LIFECYCLES})),
        decided_by_kind TEXT
            CHECK(decided_by_kind IS NULL OR decided_by_kind IN({_LINEAGE_KINDS})),
        decided_by_id TEXT,
        projected_through_ledger_seq INTEGER NOT NULL
            CHECK(projected_through_ledger_seq>0),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(current_entity_version_id,entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id),
        CHECK((decided_by_kind IS NULL AND decided_by_id IS NULL)
           OR (decided_by_kind IS NOT NULL AND decided_by_id IS NOT NULL))
    ) STRICT""",
    f"""CREATE TABLE entity_projection_events(
        projection_event_id TEXT PRIMARY KEY,
        source_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        source_ledger_seq INTEGER NOT NULL CHECK(source_ledger_seq>0),
        action TEXT NOT NULL CHECK(action IN({_PROJECTION_ACTIONS})),
        entity_id TEXT NOT NULL REFERENCES canonical_entities(entity_id),
        entity_version_id TEXT NOT NULL,
        preferred_entity_id TEXT REFERENCES canonical_entities(entity_id),
        lifecycle TEXT NOT NULL CHECK(lifecycle IN({_ENTITY_LIFECYCLES})),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(entity_version_id,entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id),
        CHECK((action='UPSERT' AND preferred_entity_id IS NOT NULL)
           OR (action='REMOVE' AND preferred_entity_id IS NULL)),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE VIEW entity_dependent_admission_guard AS
        SELECT d.dependent_proposal_id,
               d.resolution_proposal_id,
               d.proposal_version_id,
               d.material,
               COALESCE(h.current_state,'PROPOSED') AS current_state,
               CASE WHEN d.material=1 AND COALESCE(h.current_state,'PROPOSED')
                    IN('PROPOSED','HELD','UNRESOLVED') THEN 1 ELSE 0 END
                    AS materially_unresolved
        FROM entity_resolution_dependencies d
        LEFT JOIN entity_resolution_decision_heads h
          ON h.resolution_proposal_id=d.resolution_proposal_id""",
    "CREATE INDEX idx_entity_mentions_source ON entity_mentions(definition_id,item_id,revision_id,representation_id)",
    "CREATE INDEX idx_entity_mentions_normalized ON entity_mentions(normalized_text,language,script,entity_kind)",
    "CREATE INDEX idx_entity_resolution_source ON entity_resolution_proposals(source_proposal_id,proposal_kind)",
    "CREATE INDEX idx_entity_resolution_versions ON entity_resolution_proposal_versions(resolution_proposal_id,version_number)",
    "CREATE INDEX idx_entity_resolution_decisions ON entity_resolution_decisions(resolution_proposal_id,decision_version)",
    "CREATE INDEX idx_entity_alias_lookup ON entity_aliases(normalized_text,language,script,entity_id)",
    "CREATE INDEX idx_entity_projection_order ON entity_projection_events(source_ledger_seq,projection_event_id)",
    """CREATE TRIGGER entity_mention_lineage_guard
        BEFORE INSERT ON entity_mentions
        WHEN NOT EXISTS(
            SELECT 1
            FROM extraction_proposals p
            JOIN extraction_proposal_sets s
              ON s.proposal_set_id=p.proposal_set_id
            JOIN extraction_outputs o ON o.output_id=p.output_id
            JOIN extraction_runs r ON r.run_id=p.run_id
            JOIN extraction_proposal_evidence e ON e.proposal_id=p.proposal_id
            WHERE p.proposal_id=NEW.source_proposal_id
              AND p.proposal_kind='ENTITY_MENTION'
              AND p.proposal_set_id=NEW.proposal_set_id
              AND p.output_id=NEW.output_id
              AND p.run_id=NEW.run_id
              AND p.run_version_id=NEW.run_version_id
              AND p.canonical_digest=NEW.source_proposal_digest
              AND r.definition_id=NEW.definition_id
              AND r.definition_version_id=NEW.definition_version_id
              AND r.item_id=NEW.item_id
              AND r.revision_id=NEW.revision_id
              AND r.representation_id=NEW.representation_id
              AND e.passage_id=NEW.passage_id
              AND e.start_byte=NEW.start_byte
              AND e.end_byte=NEW.end_byte
              AND e.evidence_text_digest=NEW.evidence_text_digest
              AND p.subject_placeholder=NEW.mention_text
              AND (p.confidence_basis_points IS NEW.confidence_basis_points)
              AND NOT EXISTS(
                  SELECT 1 FROM extraction_proposal_evidence other
                  WHERE other.proposal_id=p.proposal_id
                    AND other.evidence_ordinal!=e.evidence_ordinal
              )
        )
        BEGIN SELECT RAISE(ABORT,'entity mention extraction lineage mismatch'); END""",
    """CREATE TRIGGER immutable_entity_mention_update
        BEFORE UPDATE ON entity_mentions BEGIN
        SELECT RAISE(ABORT,'immutable entity mention'); END""",
    """CREATE TRIGGER immutable_entity_mention_delete
        BEFORE DELETE ON entity_mentions BEGIN
        SELECT RAISE(ABORT,'entity mentions are retained'); END""",
    """CREATE TRIGGER entity_resolution_proposal_lineage_guard
        BEFORE INSERT ON entity_resolution_proposals
        WHEN NOT EXISTS(
            SELECT 1
            FROM extraction_proposals p
            JOIN entity_mentions m ON m.mention_id=NEW.subject_mention_id
            WHERE p.proposal_id=NEW.source_proposal_id
              AND ((NEW.proposal_kind IN(
                        'MENTION_TO_NEW_ENTITY','MENTION_TO_ENTITY','ALIAS_TO_ENTITY'
                    )
                    AND p.proposal_kind='ENTITY_MENTION'
                    AND m.source_proposal_id=p.proposal_id)
                OR (NEW.proposal_kind='MENTION_EQUIVALENCE'
                    AND p.proposal_kind='ENTITY_EQUIVALENCE'
                    AND EXISTS(
                        SELECT 1 FROM entity_mentions o
                        WHERE o.mention_id=NEW.object_mention_id
                          AND ((m.mention_text=p.subject_placeholder
                                AND o.mention_text=p.object_placeholder)
                            OR (m.mention_text=p.object_placeholder
                                AND o.mention_text=p.subject_placeholder))
                    )))
              AND (NEW.candidate_entity_id IS NULL OR EXISTS(
                    SELECT 1 FROM canonical_entity_versions v
                    WHERE v.entity_id=NEW.candidate_entity_id
                      AND v.entity_version_id=NEW.candidate_entity_version_id
              ))
        )
        BEGIN SELECT RAISE(ABORT,'entity resolution proposal lineage mismatch'); END""",
    """CREATE TRIGGER immutable_entity_resolution_proposal_update
        BEFORE UPDATE ON entity_resolution_proposals BEGIN
        SELECT RAISE(ABORT,'immutable entity resolution proposal'); END""",
    """CREATE TRIGGER immutable_entity_resolution_proposal_delete
        BEFORE DELETE ON entity_resolution_proposals BEGIN
        SELECT RAISE(ABORT,'entity resolution proposals are retained'); END""",
    """CREATE TRIGGER entity_resolution_proposal_version_chain_guard
        BEFORE INSERT ON entity_resolution_proposal_versions
        WHEN (NEW.version_number=1 AND EXISTS(
                SELECT 1 FROM entity_resolution_proposal_heads h
                WHERE h.resolution_proposal_id=NEW.resolution_proposal_id
             ))
          OR (NEW.version_number>1 AND NOT EXISTS(
                SELECT 1 FROM entity_resolution_proposal_heads h
                WHERE h.resolution_proposal_id=NEW.resolution_proposal_id
                  AND h.current_proposal_version_id=NEW.previous_proposal_version_id
                  AND h.current_version_number=NEW.version_number-1
             ))
        BEGIN SELECT RAISE(ABORT,'entity resolution proposal does not extend current head'); END""",
    """CREATE TRIGGER entity_resolution_proposal_version_predecessor_guard
        BEFORE INSERT ON entity_resolution_proposal_versions
        WHEN NEW.previous_proposal_version_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM entity_resolution_proposal_versions p
            WHERE p.proposal_version_id=NEW.previous_proposal_version_id
              AND p.resolution_proposal_id=NEW.resolution_proposal_id
              AND p.version_number=NEW.version_number-1
              AND p.recorded_at<=NEW.recorded_at
        )
        BEGIN SELECT RAISE(ABORT,'entity resolution proposal predecessor mismatch'); END""",
    """CREATE TRIGGER immutable_entity_resolution_proposal_version_update
        BEFORE UPDATE ON entity_resolution_proposal_versions BEGIN
        SELECT RAISE(ABORT,'immutable entity resolution proposal version'); END""",
    """CREATE TRIGGER immutable_entity_resolution_proposal_version_delete
        BEFORE DELETE ON entity_resolution_proposal_versions BEGIN
        SELECT RAISE(ABORT,'entity resolution proposal versions are retained'); END""",
    """CREATE TRIGGER entity_resolution_proposal_version_create_head
        AFTER INSERT ON entity_resolution_proposal_versions
        WHEN NEW.version_number=1
        BEGIN
            INSERT INTO entity_resolution_proposal_heads(
                resolution_proposal_id,current_version_number,
                current_proposal_version_id,updated_at
            ) VALUES(
                NEW.resolution_proposal_id,NEW.version_number,
                NEW.proposal_version_id,NEW.recorded_at
            );
        END""",
    """CREATE TRIGGER entity_resolution_proposal_version_advance_head
        AFTER INSERT ON entity_resolution_proposal_versions
        WHEN NEW.version_number>1
        BEGIN
            UPDATE entity_resolution_proposal_heads
            SET current_version_number=NEW.version_number,
                current_proposal_version_id=NEW.proposal_version_id,
                updated_at=NEW.recorded_at
            WHERE resolution_proposal_id=NEW.resolution_proposal_id
              AND current_proposal_version_id=NEW.previous_proposal_version_id;
        END""",
    """CREATE TRIGGER entity_resolution_proposal_head_insert_guard
        BEFORE INSERT ON entity_resolution_proposal_heads
        WHEN NEW.current_version_number!=1 OR NOT EXISTS(
            SELECT 1 FROM entity_resolution_proposal_versions v
            WHERE v.resolution_proposal_id=NEW.resolution_proposal_id
              AND v.proposal_version_id=NEW.current_proposal_version_id
              AND v.version_number=1
              AND v.recorded_at=NEW.updated_at
        )
        BEGIN SELECT RAISE(ABORT,'invalid initial entity resolution proposal head'); END""",
    """CREATE TRIGGER entity_resolution_proposal_head_update_guard
        BEFORE UPDATE ON entity_resolution_proposal_heads
        WHEN NEW.resolution_proposal_id!=OLD.resolution_proposal_id
          OR NEW.current_version_number!=OLD.current_version_number+1
          OR NOT EXISTS(
              SELECT 1 FROM entity_resolution_proposal_versions v
              WHERE v.resolution_proposal_id=NEW.resolution_proposal_id
                AND v.proposal_version_id=NEW.current_proposal_version_id
                AND v.previous_proposal_version_id=OLD.current_proposal_version_id
                AND v.version_number=NEW.current_version_number
                AND v.recorded_at=NEW.updated_at
          )
        BEGIN SELECT RAISE(ABORT,'invalid entity resolution proposal head update'); END""",
    """CREATE TRIGGER entity_resolution_proposal_head_delete_guard
        BEFORE DELETE ON entity_resolution_proposal_heads BEGIN
        SELECT RAISE(ABORT,'entity resolution proposal heads are retained'); END""",
    """CREATE TRIGGER entity_resolution_decision_chain_guard
        BEFORE INSERT ON entity_resolution_decisions
        WHEN (NEW.decision_version=1 AND EXISTS(
                SELECT 1 FROM entity_resolution_decision_heads h
                WHERE h.resolution_proposal_id=NEW.resolution_proposal_id
             ))
          OR (NEW.decision_version>1 AND NOT EXISTS(
                SELECT 1 FROM entity_resolution_decision_heads h
                WHERE h.resolution_proposal_id=NEW.resolution_proposal_id
                  AND h.current_decision_id=NEW.previous_decision_id
                  AND h.current_decision_version=NEW.decision_version-1
                  AND h.terminal=0
             ))
          OR NOT EXISTS(
                SELECT 1 FROM entity_resolution_proposal_heads p
                WHERE p.resolution_proposal_id=NEW.resolution_proposal_id
                  AND p.current_proposal_version_id=NEW.proposal_version_id
             )
        BEGIN SELECT RAISE(ABORT,'entity resolution decision is stale or non-contiguous'); END""",
    """CREATE TRIGGER entity_resolution_decision_target_guard
        BEFORE INSERT ON entity_resolution_decisions
        WHEN NEW.action='ACCEPT' AND NOT EXISTS(
            SELECT 1 FROM entity_resolution_proposals p
            WHERE p.resolution_proposal_id=NEW.resolution_proposal_id
              AND ((p.proposal_kind='MENTION_TO_NEW_ENTITY')
                OR (p.proposal_kind IN('MENTION_TO_ENTITY','ALIAS_TO_ENTITY')
                    AND p.candidate_entity_id=NEW.accepted_entity_id
                    AND p.candidate_entity_version_id=NEW.accepted_entity_version_id)
                OR p.proposal_kind='MENTION_EQUIVALENCE')
        )
        BEGIN SELECT RAISE(ABORT,'accepted entity differs from resolution proposal'); END""",
    """CREATE TRIGGER immutable_entity_resolution_decision_update
        BEFORE UPDATE ON entity_resolution_decisions BEGIN
        SELECT RAISE(ABORT,'immutable entity resolution decision'); END""",
    """CREATE TRIGGER immutable_entity_resolution_decision_delete
        BEFORE DELETE ON entity_resolution_decisions BEGIN
        SELECT RAISE(ABORT,'entity resolution decisions are retained'); END""",
    """CREATE TRIGGER entity_resolution_decision_create_head
        AFTER INSERT ON entity_resolution_decisions
        WHEN NEW.decision_version=1
        BEGIN
            INSERT INTO entity_resolution_decision_heads(
                resolution_proposal_id,current_decision_version,
                current_decision_id,current_state,terminal,updated_at
            ) VALUES(
                NEW.resolution_proposal_id,NEW.decision_version,NEW.decision_id,
                CASE NEW.action
                    WHEN 'ACCEPT' THEN 'ACCEPTED'
                    WHEN 'REJECT' THEN 'REJECTED'
                    WHEN 'HOLD' THEN 'HELD'
                    ELSE 'UNRESOLVED'
                END,
                NEW.action IN('ACCEPT','REJECT'),NEW.recorded_at
            );
        END""",
    """CREATE TRIGGER entity_resolution_decision_advance_head
        AFTER INSERT ON entity_resolution_decisions
        WHEN NEW.decision_version>1
        BEGIN
            UPDATE entity_resolution_decision_heads
            SET current_decision_version=NEW.decision_version,
                current_decision_id=NEW.decision_id,
                current_state=CASE NEW.action
                    WHEN 'ACCEPT' THEN 'ACCEPTED'
                    WHEN 'REJECT' THEN 'REJECTED'
                    WHEN 'HOLD' THEN 'HELD'
                    ELSE 'UNRESOLVED'
                END,
                terminal=NEW.action IN('ACCEPT','REJECT'),
                updated_at=NEW.recorded_at
            WHERE resolution_proposal_id=NEW.resolution_proposal_id
              AND current_decision_id=NEW.previous_decision_id
              AND terminal=0;
        END""",
    """CREATE TRIGGER entity_resolution_decision_head_insert_guard
        BEFORE INSERT ON entity_resolution_decision_heads
        WHEN NEW.current_decision_version!=1 OR NOT EXISTS(
            SELECT 1 FROM entity_resolution_decisions d
            WHERE d.resolution_proposal_id=NEW.resolution_proposal_id
              AND d.decision_id=NEW.current_decision_id
              AND d.decision_version=1
              AND d.recorded_at=NEW.updated_at
              AND NEW.terminal=(d.action IN('ACCEPT','REJECT'))
        )
        BEGIN SELECT RAISE(ABORT,'invalid initial entity resolution decision head'); END""",
    """CREATE TRIGGER entity_resolution_decision_head_update_guard
        BEFORE UPDATE ON entity_resolution_decision_heads
        WHEN NEW.resolution_proposal_id!=OLD.resolution_proposal_id
          OR OLD.terminal!=0
          OR NEW.current_decision_version!=OLD.current_decision_version+1
          OR NOT EXISTS(
              SELECT 1 FROM entity_resolution_decisions d
              WHERE d.resolution_proposal_id=NEW.resolution_proposal_id
                AND d.decision_id=NEW.current_decision_id
                AND d.previous_decision_id=OLD.current_decision_id
                AND d.decision_version=NEW.current_decision_version
                AND d.recorded_at=NEW.updated_at
                AND NEW.terminal=(d.action IN('ACCEPT','REJECT'))
          )
        BEGIN SELECT RAISE(ABORT,'invalid entity resolution decision head update'); END""",
    """CREATE TRIGGER entity_resolution_decision_head_delete_guard
        BEFORE DELETE ON entity_resolution_decision_heads BEGIN
        SELECT RAISE(ABORT,'entity resolution decision heads are retained'); END""",
    """CREATE TRIGGER canonical_entity_creation_guard
        BEFORE INSERT ON canonical_entities
        WHEN NOT EXISTS(
            SELECT 1
            FROM entity_resolution_decisions d
            JOIN entity_resolution_proposals p
              ON p.resolution_proposal_id=d.resolution_proposal_id
            JOIN entity_mentions m ON m.mention_id=p.subject_mention_id
            WHERE d.decision_id=NEW.created_by_decision_id
              AND d.action='ACCEPT'
              AND d.accepted_entity_id=NEW.entity_id
              AND d.accepted_entity_version_id=NEW.initial_version_id
              AND p.proposal_kind='MENTION_TO_NEW_ENTITY'
              AND m.entity_kind=NEW.entity_kind
        )
        BEGIN SELECT RAISE(ABORT,'canonical entity requires accepted new-entity decision'); END""",
    """CREATE TRIGGER immutable_canonical_entity_update
        BEFORE UPDATE ON canonical_entities BEGIN
        SELECT RAISE(ABORT,'canonical entity identity is immutable'); END""",
    """CREATE TRIGGER immutable_canonical_entity_delete
        BEFORE DELETE ON canonical_entities BEGIN
        SELECT RAISE(ABORT,'canonical entities are retained'); END""",
    """CREATE TRIGGER canonical_entity_version_chain_guard
        BEFORE INSERT ON canonical_entity_versions
        WHEN (NEW.version_number=1 AND EXISTS(
                SELECT 1 FROM canonical_entity_heads h
                WHERE h.entity_id=NEW.entity_id
             ))
          OR (NEW.version_number>1 AND NOT EXISTS(
                SELECT 1 FROM canonical_entity_heads h
                WHERE h.entity_id=NEW.entity_id
                  AND h.current_entity_version_id=NEW.previous_entity_version_id
                  AND h.current_version_number=NEW.version_number-1
             ))
        BEGIN SELECT RAISE(ABORT,'canonical entity version does not extend current head'); END""",
    """CREATE TRIGGER immutable_canonical_entity_version_update
        BEFORE UPDATE ON canonical_entity_versions BEGIN
        SELECT RAISE(ABORT,'canonical entity versions are immutable'); END""",
    """CREATE TRIGGER immutable_canonical_entity_version_delete
        BEFORE DELETE ON canonical_entity_versions BEGIN
        SELECT RAISE(ABORT,'canonical entity versions are retained'); END""",
    """CREATE TRIGGER canonical_entity_version_create_head
        AFTER INSERT ON canonical_entity_versions
        WHEN NEW.version_number=1
        BEGIN
            INSERT INTO canonical_entity_heads(
                entity_id,current_version_number,current_entity_version_id,
                lifecycle,updated_at
            ) VALUES(
                NEW.entity_id,NEW.version_number,NEW.entity_version_id,
                NEW.lifecycle,NEW.recorded_at
            );
        END""",
    """CREATE TRIGGER canonical_entity_version_advance_head
        AFTER INSERT ON canonical_entity_versions
        WHEN NEW.version_number>1
        BEGIN
            UPDATE canonical_entity_heads
            SET current_version_number=NEW.version_number,
                current_entity_version_id=NEW.entity_version_id,
                lifecycle=NEW.lifecycle,
                updated_at=NEW.recorded_at
            WHERE entity_id=NEW.entity_id
              AND current_entity_version_id=NEW.previous_entity_version_id;
        END""",
    """CREATE TRIGGER canonical_entity_head_insert_guard
        BEFORE INSERT ON canonical_entity_heads
        WHEN NEW.current_version_number!=1 OR NOT EXISTS(
            SELECT 1 FROM canonical_entity_versions v
            WHERE v.entity_id=NEW.entity_id
              AND v.entity_version_id=NEW.current_entity_version_id
              AND v.version_number=1
              AND v.lifecycle=NEW.lifecycle
              AND v.recorded_at=NEW.updated_at
        )
        BEGIN SELECT RAISE(ABORT,'invalid initial canonical entity head'); END""",
    """CREATE TRIGGER canonical_entity_head_update_guard
        BEFORE UPDATE ON canonical_entity_heads
        WHEN NEW.entity_id!=OLD.entity_id
          OR NEW.current_version_number!=OLD.current_version_number+1
          OR NOT EXISTS(
              SELECT 1 FROM canonical_entity_versions v
              WHERE v.entity_id=NEW.entity_id
                AND v.entity_version_id=NEW.current_entity_version_id
                AND v.previous_entity_version_id=OLD.current_entity_version_id
                AND v.version_number=NEW.current_version_number
                AND v.lifecycle=NEW.lifecycle
                AND v.recorded_at=NEW.updated_at
          )
        BEGIN SELECT RAISE(ABORT,'invalid canonical entity head update'); END""",
    """CREATE TRIGGER canonical_entity_head_delete_guard
        BEFORE DELETE ON canonical_entity_heads BEGIN
        SELECT RAISE(ABORT,'canonical entity heads are retained'); END""",
    """CREATE TRIGGER entity_alias_lineage_guard
        BEFORE INSERT ON entity_aliases
        WHEN NOT EXISTS(
            SELECT 1
            FROM entity_resolution_decisions d
            JOIN entity_resolution_proposals p
              ON p.resolution_proposal_id=d.resolution_proposal_id
            JOIN entity_mentions m ON m.mention_id=p.subject_mention_id
            WHERE d.decision_id=NEW.resolution_decision_id
              AND d.action='ACCEPT'
              AND d.accepted_entity_id=NEW.entity_id
              AND d.accepted_entity_version_id=NEW.entity_version_id
              AND d.alias_id=NEW.alias_id
              AND m.mention_id=NEW.provenance_mention_id
              AND m.mention_text=NEW.alias_text
              AND m.normalized_text=NEW.normalized_text
              AND m.normalization_contract_digest=NEW.normalization_contract_digest
              AND m.language=NEW.language
              AND m.script=NEW.script
        )
        BEGIN SELECT RAISE(ABORT,'entity alias resolution lineage mismatch'); END""",
    """CREATE TRIGGER immutable_entity_alias_update
        BEFORE UPDATE ON entity_aliases BEGIN
        SELECT RAISE(ABORT,'entity aliases are immutable'); END""",
    """CREATE TRIGGER immutable_entity_alias_delete
        BEFORE DELETE ON entity_aliases BEGIN
        SELECT RAISE(ABORT,'entity aliases are retained'); END""",
    """CREATE TRIGGER entity_mention_resolution_guard
        BEFORE INSERT ON entity_mention_resolutions
        WHEN NOT EXISTS(
            SELECT 1
            FROM entity_resolution_decisions d
            JOIN entity_resolution_proposals p
              ON p.resolution_proposal_id=d.resolution_proposal_id
            WHERE d.decision_id=NEW.decision_id
              AND d.resolution_proposal_id=NEW.resolution_proposal_id
              AND d.action='ACCEPT'
              AND d.accepted_entity_id=NEW.entity_id
              AND d.accepted_entity_version_id=NEW.entity_version_id
              AND d.alias_id=NEW.alias_id
              AND p.subject_mention_id=NEW.mention_id
              AND d.recorded_at=NEW.admitted_at
        )
        BEGIN SELECT RAISE(ABORT,'entity mention resolution lineage mismatch'); END""",
    """CREATE TRIGGER immutable_entity_mention_resolution_update
        BEFORE UPDATE ON entity_mention_resolutions BEGIN
        SELECT RAISE(ABORT,'entity mention resolutions are immutable'); END""",
    """CREATE TRIGGER immutable_entity_mention_resolution_delete
        BEFORE DELETE ON entity_mention_resolutions BEGIN
        SELECT RAISE(ABORT,'entity mention resolutions are retained'); END""",
    """CREATE TRIGGER entity_merge_predecessor_count_guard
        BEFORE INSERT ON entity_merge_predecessors
        WHEN NEW.predecessor_ordinal>(
            SELECT predecessor_count FROM entity_merge_decisions
            WHERE merge_decision_id=NEW.merge_decision_id
        ) OR NEW.entity_id=(
            SELECT successor_entity_id FROM entity_merge_decisions
            WHERE merge_decision_id=NEW.merge_decision_id
        )
        BEGIN SELECT RAISE(ABORT,'invalid entity merge predecessor'); END""",
    """CREATE TRIGGER entity_split_successor_count_guard
        BEFORE INSERT ON entity_split_successors
        WHEN NEW.successor_ordinal>(
            SELECT successor_count FROM entity_split_decisions
            WHERE split_decision_id=NEW.split_decision_id
        ) OR NEW.entity_id=(
            SELECT source_entity_id FROM entity_split_decisions
            WHERE split_decision_id=NEW.split_decision_id
        )
        BEGIN SELECT RAISE(ABORT,'invalid entity split successor'); END""",
    """CREATE TRIGGER entity_split_allocation_guard
        BEFORE INSERT ON entity_split_allocations
        WHEN NOT EXISTS(
            SELECT 1 FROM entity_split_successors s
            WHERE s.split_decision_id=NEW.split_decision_id
              AND s.entity_id=NEW.successor_entity_id
        ) OR NOT EXISTS(
            SELECT 1 FROM entity_mention_resolutions r
            JOIN entity_split_decisions d
              ON d.split_decision_id=NEW.split_decision_id
            WHERE r.mention_id=NEW.mention_id
              AND r.entity_id=d.source_entity_id
        )
        BEGIN SELECT RAISE(ABORT,'entity split allocation lineage mismatch'); END""",
    """CREATE TRIGGER entity_reversal_target_guard
        BEFORE INSERT ON entity_reversal_decisions
        WHEN (NEW.target_kind='RESOLUTION' AND NOT EXISTS(
                SELECT 1 FROM entity_resolution_decisions d
                WHERE d.decision_id=NEW.target_decision_id
             ))
          OR (NEW.target_kind='MERGE' AND NOT EXISTS(
                SELECT 1 FROM entity_merge_decisions d
                WHERE d.merge_decision_id=NEW.target_decision_id
             ))
          OR (NEW.target_kind='SPLIT' AND NOT EXISTS(
                SELECT 1 FROM entity_split_decisions d
                WHERE d.split_decision_id=NEW.target_decision_id
             ))
        BEGIN SELECT RAISE(ABORT,'entity reversal target is missing'); END""",
    """CREATE TRIGGER entity_resolution_dependency_guard
        BEFORE INSERT ON entity_resolution_dependencies
        WHEN NOT EXISTS(
            SELECT 1 FROM extraction_proposals p
            WHERE p.proposal_id=NEW.dependent_proposal_id
              AND p.proposal_kind IN('RELATION','CLAIM')
        ) OR NOT EXISTS(
            SELECT 1 FROM entity_resolution_proposal_heads h
            WHERE h.resolution_proposal_id=NEW.resolution_proposal_id
              AND h.current_proposal_version_id=NEW.proposal_version_id
        )
        BEGIN SELECT RAISE(ABORT,'entity resolution dependency lineage mismatch'); END""",
    """CREATE TRIGGER entity_preferred_identity_insert_guard
        BEFORE INSERT ON entity_preferred_identities
        WHEN NOT EXISTS(
            SELECT 1 FROM canonical_entity_heads h
            WHERE h.entity_id=NEW.entity_id
              AND h.current_entity_version_id=NEW.current_entity_version_id
              AND h.lifecycle=NEW.lifecycle
        ) OR NOT EXISTS(
            SELECT 1 FROM canonical_entities e
            WHERE e.entity_id=NEW.preferred_entity_id
        )
        BEGIN SELECT RAISE(ABORT,'preferred entity projection differs from authority'); END""",
    """CREATE TRIGGER entity_preferred_identity_update_guard
        BEFORE UPDATE ON entity_preferred_identities
        WHEN NEW.entity_id!=OLD.entity_id
          OR NEW.projected_through_ledger_seq<=OLD.projected_through_ledger_seq
          OR NOT EXISTS(
              SELECT 1 FROM canonical_entity_heads h
              WHERE h.entity_id=NEW.entity_id
                AND h.current_entity_version_id=NEW.current_entity_version_id
                AND h.lifecycle=NEW.lifecycle
          )
          OR NOT EXISTS(
              SELECT 1 FROM canonical_entities e
              WHERE e.entity_id=NEW.preferred_entity_id
          )
        BEGIN SELECT RAISE(ABORT,'invalid preferred entity projection update'); END""",
    """CREATE TRIGGER entity_preferred_identity_delete_guard
        BEFORE DELETE ON entity_preferred_identities BEGIN
        SELECT RAISE(ABORT,'preferred entity projection requires explicit rebuild'); END""",
    """CREATE TRIGGER immutable_entity_projection_event_update
        BEFORE UPDATE ON entity_projection_events BEGIN
        SELECT RAISE(ABORT,'entity projection events are immutable'); END""",
    """CREATE TRIGGER immutable_entity_projection_event_delete
        BEFORE DELETE ON entity_projection_events BEGIN
        SELECT RAISE(ABORT,'entity projection events are retained'); END""",
)

ENTITY_AUTHORITY_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": ENTITY_AUTHORITY_SCHEMA_VERSION,
        "name": ENTITY_AUTHORITY_MIGRATION_NAME,
        "statements": ENTITY_AUTHORITY_MIGRATION_STATEMENTS,
    }
)

ENTITY_AUTHORITY_MIGRATION = EntityAuthorityMigrationRecord(
    version=ENTITY_AUTHORITY_SCHEMA_VERSION,
    name=ENTITY_AUTHORITY_MIGRATION_NAME,
    checksum=ENTITY_AUTHORITY_MIGRATION_CHECKSUM,
)


__all__ = [
    "ENTITY_AUTHORITY_MIGRATION",
    "ENTITY_AUTHORITY_MIGRATION_CHECKSUM",
    "ENTITY_AUTHORITY_MIGRATION_NAME",
    "ENTITY_AUTHORITY_MIGRATION_STATEMENTS",
    "ENTITY_AUTHORITY_SCHEMA_VERSION",
]
