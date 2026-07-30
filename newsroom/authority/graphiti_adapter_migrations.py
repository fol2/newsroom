from __future__ import annotations

from dataclasses import dataclass

from .canonical import canonical_json_bytes, digest_bytes, digest_canonical


GRAPHITI_ADAPTER_SCHEMA_VERSION = 16
GRAPHITI_ADAPTER_MIGRATION_NAME = "graphiti_proposal_adapter_v16"


@dataclass(frozen=True, slots=True)
class GraphitiAdapterMigrationRecord:
    version: int
    name: str
    checksum: str


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _blob(value: bytes) -> str:
    return "X'" + value.hex() + "'"


def _sql_values(values: tuple[str, ...]) -> str:
    return ",".join(_quoted(item) for item in values)


_RUNTIME_MODES = _sql_values(
    ("DETERMINISTIC_FAKE", "APPROVED_REPLAY", "REAL_GRAPHITI")
)
_EXECUTION_PROFILES = _sql_values(
    ("QUALIFICATION", "REPLAY", "EVALUATION", "PRODUCTION")
)
_FIXTURE_CASES = _sql_values(
    (
        "BILINGUAL_COMPLETE",
        "BILINGUAL_PARTIAL",
        "BILINGUAL_HOMONYM",
        "RETRYABLE_FAILURE",
        "BLOCKING_FAILURE",
        "INVALID_OUTPUT",
    )
)
_EGRESS_POLICIES = _sql_values(("DENY_ALL", "APPROVED_PROVIDER_ONLY"))
_CREDENTIAL_CLASSES = _sql_values(("NONE", "PROPOSAL_WORKSPACE_ONLY"))
_WORKSPACE_STATES = _sql_values(("CREATED", "ACTIVE", "CLEANED", "LOST"))
_CLEANUP_REASONS = _sql_values(
    (
        "NORMAL",
        "PARTIAL",
        "TIMEOUT",
        "MALFORMED_OUTPUT",
        "PROVIDER_REJECTED",
        "POLICY_BLOCKED",
        "FAILED",
        "AMBIGUOUS_EFFECT",
        "SIMULATED_LOSS",
    )
)
_ADAPTER_OUTCOMES = _sql_values(
    (
        "COMPLETE",
        "PARTIAL",
        "TIMEOUT",
        "MALFORMED_OUTPUT",
        "PROVIDER_REJECTED",
        "POLICY_BLOCKED",
        "FAILED",
        "AMBIGUOUS_EFFECT",
    )
)
_REPLAY_ELIGIBILITY = _sql_values(("COMPLETE", "PARTIAL", "MALFORMED_OUTPUT"))


_QUALIFICATION_WORKSPACE_POLICY_SEED: dict[str, object] = {
    "policy_id": "00000000-0000-4000-8000-000000004801",
    "policy_version": "graphiti-disposable-workspace-v1",
    "namespace_prefix": "graphiti-qualification",
    "max_workspace_bytes": 4 * 1024 * 1024,
    "max_private_nodes": 1_000,
    "max_private_relations": 2_000,
    "egress_policy": "DENY_ALL",
    "credential_class": "NONE",
    "cleanup_required": True,
    "persistent_state_allowed": False,
}
_REPLAY_WORKSPACE_POLICY_SEED: dict[str, object] = {
    "policy_id": "00000000-0000-4000-8000-000000004802",
    "policy_version": "graphiti-disposable-workspace-v1",
    "namespace_prefix": "graphiti-replay",
    "max_workspace_bytes": 1 * 1024 * 1024,
    "max_private_nodes": 1,
    "max_private_relations": 1,
    "egress_policy": "DENY_ALL",
    "credential_class": "NONE",
    "cleanup_required": True,
    "persistent_state_allowed": False,
}


def _workspace_policy_insert(policy: dict[str, object]) -> str:
    canonical_bytes = canonical_json_bytes(policy)
    canonical_digest = digest_bytes(canonical_bytes)
    return (
        "INSERT INTO graphiti_workspace_policies("
        "policy_id,policy_version,namespace_prefix,max_workspace_bytes,"
        "max_private_nodes,max_private_relations,egress_policy,credential_class,"
        "cleanup_required,persistent_state_allowed,canonical_bytes,canonical_digest) "
        "VALUES("
        f"{_quoted(str(policy['policy_id']))},"
        f"{_quoted(str(policy['policy_version']))},"
        f"{_quoted(str(policy['namespace_prefix']))},"
        f"{int(policy['max_workspace_bytes'])},"
        f"{int(policy['max_private_nodes'])},"
        f"{int(policy['max_private_relations'])},"
        f"{_quoted(str(policy['egress_policy']))},"
        f"{_quoted(str(policy['credential_class']))},"
        "1,0,"
        f"{_blob(canonical_bytes)},"
        f"{_quoted(canonical_digest)}"
        ")"
    )


GRAPHITI_ADAPTER_MIGRATION_STATEMENTS: tuple[str, ...] = (
    f"""CREATE TABLE graphiti_workspace_policies(
        policy_id TEXT PRIMARY KEY,
        policy_version TEXT NOT NULL,
        namespace_prefix TEXT NOT NULL UNIQUE,
        max_workspace_bytes INTEGER NOT NULL
            CHECK(max_workspace_bytes>0 AND max_workspace_bytes<=268435456),
        max_private_nodes INTEGER NOT NULL
            CHECK(max_private_nodes>0 AND max_private_nodes<=100000),
        max_private_relations INTEGER NOT NULL
            CHECK(max_private_relations>0 AND max_private_relations<=200000),
        egress_policy TEXT NOT NULL CHECK(egress_policy IN({_EGRESS_POLICIES})),
        credential_class TEXT NOT NULL
            CHECK(credential_class IN({_CREDENTIAL_CLASSES})),
        cleanup_required INTEGER NOT NULL CHECK(cleanup_required=1),
        persistent_state_allowed INTEGER NOT NULL
            CHECK(persistent_state_allowed=0),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        CHECK(length(canonical_bytes)>0),
        CHECK((egress_policy='DENY_ALL' AND credential_class='NONE')
           OR (egress_policy='APPROVED_PROVIDER_ONLY'
               AND credential_class='PROPOSAL_WORKSPACE_ONLY'))
    ) STRICT""",
    _workspace_policy_insert(_QUALIFICATION_WORKSPACE_POLICY_SEED),
    _workspace_policy_insert(_REPLAY_WORKSPACE_POLICY_SEED),
    f"""CREATE TABLE graphiti_adapter_configurations(
        configuration_id TEXT PRIMARY KEY,
        runtime_mode TEXT NOT NULL CHECK(runtime_mode IN({_RUNTIME_MODES})),
        execution_profile TEXT NOT NULL
            CHECK(execution_profile IN({_EXECUTION_PROFILES})),
        framework_id TEXT NOT NULL,
        framework_version TEXT NOT NULL,
        framework_digest TEXT NOT NULL,
        model_id TEXT NOT NULL,
        model_version TEXT NOT NULL,
        model_digest TEXT NOT NULL,
        embedding_id TEXT NOT NULL,
        embedding_version TEXT NOT NULL,
        embedding_digest TEXT NOT NULL,
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
        temporal_policy_id TEXT NOT NULL,
        temporal_policy_version TEXT NOT NULL,
        temporal_policy_digest TEXT NOT NULL,
        adapter_policy_id TEXT NOT NULL,
        adapter_policy_version TEXT NOT NULL,
        adapter_policy_digest TEXT NOT NULL,
        extractor_contract_id TEXT NOT NULL
            REFERENCES extractor_contracts(contract_id),
        extractor_contract_digest TEXT NOT NULL,
        workspace_policy_id TEXT NOT NULL
            REFERENCES graphiti_workspace_policies(policy_id),
        workspace_policy_digest TEXT NOT NULL,
        fixture_case TEXT CHECK(fixture_case IS NULL OR fixture_case IN({_FIXTURE_CASES})),
        real_runtime_authority_digest TEXT,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0),
        CHECK((runtime_mode='DETERMINISTIC_FAKE'
               AND execution_profile='QUALIFICATION'
               AND fixture_case IS NOT NULL
               AND real_runtime_authority_digest IS NULL)
           OR (runtime_mode='APPROVED_REPLAY'
               AND execution_profile='REPLAY'
               AND fixture_case IS NULL
               AND real_runtime_authority_digest IS NULL)
           OR (runtime_mode='REAL_GRAPHITI'
               AND execution_profile IN('EVALUATION','PRODUCTION')
               AND fixture_case IS NULL
               AND real_runtime_authority_digest IS NOT NULL))
    ) STRICT""",
    """CREATE TABLE graphiti_workspaces(
        workspace_id TEXT PRIMARY KEY,
        configuration_id TEXT NOT NULL
            REFERENCES graphiti_adapter_configurations(configuration_id),
        policy_id TEXT NOT NULL REFERENCES graphiti_workspace_policies(policy_id),
        policy_digest TEXT NOT NULL,
        namespace TEXT NOT NULL UNIQUE,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE graphiti_workspace_lifecycle_events(
        workspace_id TEXT NOT NULL REFERENCES graphiti_workspaces(workspace_id),
        lifecycle_ordinal INTEGER NOT NULL CHECK(lifecycle_ordinal>0),
        state TEXT NOT NULL CHECK(state IN({_WORKSPACE_STATES})),
        reason TEXT CHECK(reason IS NULL OR reason IN({_CLEANUP_REASONS})),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(workspace_id,lifecycle_ordinal),
        CHECK(length(canonical_bytes)>0),
        CHECK((state IN('CREATED','ACTIVE') AND reason IS NULL)
           OR (state='CLEANED' AND reason IS NOT NULL
               AND reason!='SIMULATED_LOSS')
           OR (state='LOST' AND reason='SIMULATED_LOSS'))
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE graphiti_input_manifests(
        manifest_id TEXT PRIMARY KEY,
        configuration_id TEXT NOT NULL
            REFERENCES graphiti_adapter_configurations(configuration_id),
        configuration_digest TEXT NOT NULL,
        extractor_contract_id TEXT NOT NULL
            REFERENCES extractor_contracts(contract_id),
        extractor_contract_digest TEXT NOT NULL,
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        requested_run_version_id TEXT NOT NULL UNIQUE,
        requested_version_number INTEGER NOT NULL CHECK(requested_version_number>0),
        definition_id TEXT NOT NULL,
        definition_version_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        representation_id TEXT NOT NULL,
        input_binding_digest TEXT NOT NULL,
        passage_count INTEGER NOT NULL CHECK(passage_count>0 AND passage_count<=128),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        retained_at TEXT NOT NULL,
        FOREIGN KEY(requested_run_version_id,run_id)
            REFERENCES extraction_run_versions(run_version_id,run_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        FOREIGN KEY(item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        FOREIGN KEY(revision_id,item_id)
            REFERENCES source_revisions(revision_id,item_id),
        FOREIGN KEY(representation_id,revision_id)
            REFERENCES discovery_representations(representation_id,revision_id),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE graphiti_input_manifest_passages(
        manifest_id TEXT NOT NULL REFERENCES graphiti_input_manifests(manifest_id),
        passage_ordinal INTEGER NOT NULL CHECK(passage_ordinal>0),
        run_id TEXT NOT NULL,
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
        canonical_digest TEXT NOT NULL UNIQUE,
        PRIMARY KEY(manifest_id,passage_ordinal),
        UNIQUE(manifest_id,passage_id),
        FOREIGN KEY(run_id,passage_id)
            REFERENCES extraction_run_passages(run_id,passage_id),
        CHECK(blob_digest=text_digest),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE graphiti_cleanup_receipts(
        receipt_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL UNIQUE REFERENCES graphiti_workspaces(workspace_id),
        final_state TEXT NOT NULL CHECK(final_state IN('CLEANED','LOST')),
        reason TEXT NOT NULL CHECK(reason IN({_CLEANUP_REASONS})),
        private_node_count INTEGER NOT NULL CHECK(private_node_count>=0),
        private_relation_count INTEGER NOT NULL CHECK(private_relation_count>=0),
        file_count INTEGER NOT NULL CHECK(file_count>=0),
        byte_count INTEGER NOT NULL CHECK(byte_count>=0),
        workspace_absent INTEGER NOT NULL CHECK(workspace_absent=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0),
        CHECK((final_state='LOST' AND reason='SIMULATED_LOSS')
           OR (final_state='CLEANED' AND reason!='SIMULATED_LOSS'))
    ) STRICT""",
    f"""CREATE TABLE graphiti_adapter_attempts(
        attempt_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        run_version_id TEXT NOT NULL UNIQUE,
        attempt_number INTEGER NOT NULL CHECK(attempt_number>0),
        previous_attempt_id TEXT REFERENCES graphiti_adapter_attempts(attempt_id),
        configuration_id TEXT NOT NULL
            REFERENCES graphiti_adapter_configurations(configuration_id),
        configuration_digest TEXT NOT NULL,
        workspace_id TEXT NOT NULL UNIQUE REFERENCES graphiti_workspaces(workspace_id),
        manifest_id TEXT NOT NULL UNIQUE REFERENCES graphiti_input_manifests(manifest_id),
        outcome TEXT NOT NULL CHECK(outcome IN({_ADAPTER_OUTCOMES})),
        failure_code TEXT NOT NULL,
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
        extraction_output_id TEXT REFERENCES extraction_outputs(output_id),
        proposal_set_id TEXT REFERENCES extraction_proposal_sets(proposal_set_id),
        cleanup_receipt_id TEXT NOT NULL UNIQUE
            REFERENCES graphiti_cleanup_receipts(receipt_id),
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        recorded_at TEXT NOT NULL,
        UNIQUE(run_id,attempt_number),
        UNIQUE(run_id,attempt_number,attempt_id),
        FOREIGN KEY(run_version_id,run_id)
            REFERENCES extraction_run_versions(run_version_id,run_id),
        CHECK((attempt_number=1 AND previous_attempt_id IS NULL)
           OR (attempt_number>1 AND previous_attempt_id IS NOT NULL)),
        CHECK(started_at<=ended_at AND ended_at<=recorded_at),
        CHECK(length(canonical_bytes)>0),
        CHECK((outcome IN('COMPLETE','PARTIAL')
               AND extraction_output_id IS NOT NULL
               AND proposal_set_id IS NOT NULL)
           OR (outcome='MALFORMED_OUTPUT'
               AND extraction_output_id IS NOT NULL
               AND proposal_set_id IS NULL)
           OR (outcome IN('TIMEOUT','PROVIDER_REJECTED','POLICY_BLOCKED',
                           'FAILED','AMBIGUOUS_EFFECT')
               AND extraction_output_id IS NULL
               AND proposal_set_id IS NULL))
    ) STRICT""",
    """CREATE TABLE graphiti_adapter_attempt_heads(
        run_id TEXT PRIMARY KEY REFERENCES extraction_runs(run_id),
        current_attempt_number INTEGER NOT NULL CHECK(current_attempt_number>0),
        current_attempt_id TEXT NOT NULL UNIQUE,
        terminal INTEGER NOT NULL CHECK(terminal IN(0,1)),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(run_id,current_attempt_number,current_attempt_id)
            REFERENCES graphiti_adapter_attempts(run_id,attempt_number,attempt_id)
            DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE graphiti_replay_sources(
        replay_source_id TEXT PRIMARY KEY,
        source_attempt_id TEXT NOT NULL UNIQUE
            REFERENCES graphiti_adapter_attempts(attempt_id),
        source_run_version_id TEXT NOT NULL
            REFERENCES extraction_run_versions(run_version_id),
        source_output_id TEXT NOT NULL REFERENCES extraction_outputs(output_id),
        source_proposal_set_id TEXT REFERENCES extraction_proposal_sets(proposal_set_id),
        eligibility TEXT NOT NULL CHECK(eligibility IN({_REPLAY_ELIGIBILITY})),
        output_canonical_digest TEXT NOT NULL,
        proposal_set_canonical_digest TEXT,
        replay_payload_digest TEXT NOT NULL,
        approval_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        approval_event_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        approved_at TEXT NOT NULL,
        CHECK(length(canonical_bytes)>0),
        CHECK((eligibility='MALFORMED_OUTPUT'
               AND source_proposal_set_id IS NULL
               AND proposal_set_canonical_digest IS NULL)
           OR (eligibility IN('COMPLETE','PARTIAL')
               AND source_proposal_set_id IS NOT NULL
               AND proposal_set_canonical_digest IS NOT NULL))
    ) STRICT""",
    """CREATE TABLE graphiti_adapter_attempt_replays(
        attempt_id TEXT PRIMARY KEY REFERENCES graphiti_adapter_attempts(attempt_id),
        replay_source_id TEXT NOT NULL UNIQUE
            REFERENCES graphiti_replay_sources(replay_source_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    "CREATE INDEX idx_graphiti_attempts_run ON graphiti_adapter_attempts(run_id,attempt_number)",
    "CREATE INDEX idx_graphiti_manifest_source ON graphiti_input_manifests(definition_id,item_id,revision_id,representation_id)",
    "CREATE INDEX idx_graphiti_workspace_config ON graphiti_workspaces(configuration_id,created_at)",
    """CREATE TRIGGER graphiti_configuration_contract_guard
        BEFORE INSERT ON graphiti_adapter_configurations
        WHEN NOT EXISTS(
            SELECT 1 FROM extractor_contracts
            WHERE contract_id=NEW.extractor_contract_id
              AND canonical_digest=NEW.extractor_contract_digest
        )
        BEGIN SELECT RAISE(ABORT,'graphiti configuration extractor contract mismatch'); END""",
    """CREATE TRIGGER graphiti_configuration_workspace_policy_guard
        BEFORE INSERT ON graphiti_adapter_configurations
        WHEN NOT EXISTS(
            SELECT 1 FROM graphiti_workspace_policies
            WHERE policy_id=NEW.workspace_policy_id
              AND canonical_digest=NEW.workspace_policy_digest
              AND ((NEW.runtime_mode IN('DETERMINISTIC_FAKE','APPROVED_REPLAY')
                    AND egress_policy='DENY_ALL' AND credential_class='NONE')
                OR (NEW.runtime_mode='REAL_GRAPHITI'
                    AND egress_policy='APPROVED_PROVIDER_ONLY'
                    AND credential_class='PROPOSAL_WORKSPACE_ONLY'))
        )
        BEGIN SELECT RAISE(ABORT,'graphiti configuration workspace policy mismatch'); END""",
    """CREATE TRIGGER graphiti_workspace_policy_guard
        BEFORE INSERT ON graphiti_workspaces
        WHEN NOT EXISTS(
            SELECT 1 FROM graphiti_adapter_configurations AS c
            JOIN graphiti_workspace_policies AS p
              ON p.policy_id=c.workspace_policy_id
            WHERE c.configuration_id=NEW.configuration_id
              AND p.policy_id=NEW.policy_id
              AND p.canonical_digest=NEW.policy_digest
        )
        BEGIN SELECT RAISE(ABORT,'graphiti workspace policy mismatch'); END""",
    """CREATE TRIGGER graphiti_workspace_lifecycle_chain_guard
        BEFORE INSERT ON graphiti_workspace_lifecycle_events
        WHEN (NEW.lifecycle_ordinal=1 AND NEW.state!='CREATED')
          OR (NEW.lifecycle_ordinal=2 AND (
              NEW.state!='ACTIVE' OR NOT EXISTS(
                  SELECT 1 FROM graphiti_workspace_lifecycle_events
                  WHERE workspace_id=NEW.workspace_id
                    AND lifecycle_ordinal=1 AND state='CREATED'
              )))
          OR (NEW.lifecycle_ordinal=3 AND (
              NEW.state NOT IN('CLEANED','LOST') OR NOT EXISTS(
                  SELECT 1 FROM graphiti_workspace_lifecycle_events
                  WHERE workspace_id=NEW.workspace_id
                    AND lifecycle_ordinal=2 AND state='ACTIVE'
              )))
          OR NEW.lifecycle_ordinal>3
        BEGIN SELECT RAISE(ABORT,'invalid graphiti workspace lifecycle'); END""",
    """CREATE TRIGGER graphiti_manifest_guard
        BEFORE INSERT ON graphiti_input_manifests
        WHEN NOT EXISTS(
            SELECT 1
            FROM graphiti_adapter_configurations AS c
            JOIN extraction_runs AS r ON r.run_id=NEW.run_id
            JOIN extraction_run_versions AS v
              ON v.run_version_id=NEW.requested_run_version_id
             AND v.run_id=NEW.run_id
            WHERE c.configuration_id=NEW.configuration_id
              AND c.canonical_digest=NEW.configuration_digest
              AND c.extractor_contract_id=NEW.extractor_contract_id
              AND c.extractor_contract_digest=NEW.extractor_contract_digest
              AND r.contract_id=NEW.extractor_contract_id
              AND r.input_binding_digest=NEW.input_binding_digest
              AND r.definition_id=NEW.definition_id
              AND r.definition_version_id=NEW.definition_version_id
              AND r.item_id=NEW.item_id
              AND r.revision_id=NEW.revision_id
              AND r.representation_id=NEW.representation_id
              AND v.version_number=NEW.requested_version_number
        )
        BEGIN SELECT RAISE(ABORT,'graphiti input manifest lineage mismatch'); END""",
    """CREATE TRIGGER graphiti_manifest_passage_guard
        BEFORE INSERT ON graphiti_input_manifest_passages
        WHEN NOT EXISTS(
            SELECT 1 FROM graphiti_input_manifests AS m
            JOIN extraction_run_passages AS p
              ON p.run_id=m.run_id AND p.passage_id=NEW.passage_id
            WHERE m.manifest_id=NEW.manifest_id
              AND m.run_id=NEW.run_id
              AND p.admission_id=NEW.admission_id
              AND p.access_decision_id=NEW.access_decision_id
              AND p.hydration_policy_contract_digest=NEW.hydration_policy_contract_digest
              AND p.principal_id=NEW.principal_id
              AND p.authority_domain=NEW.authority_domain
              AND p.purpose=NEW.purpose
              AND p.object_class=NEW.object_class
              AND p.allowed_use=NEW.allowed_use
              AND p.security_scope=NEW.security_scope
              AND p.retention_scope=NEW.retention_scope
              AND p.byte_offset=NEW.byte_offset
              AND p.byte_length=NEW.byte_length
              AND p.blob_digest=NEW.blob_digest
              AND p.text_digest=NEW.text_digest
              AND p.language=NEW.language
        )
        BEGIN SELECT RAISE(ABORT,'graphiti manifest passage differs from extraction authority'); END""",
    """CREATE TRIGGER graphiti_cleanup_receipt_guard
        BEFORE INSERT ON graphiti_cleanup_receipts
        WHEN NOT EXISTS(
            SELECT 1 FROM graphiti_workspace_lifecycle_events
            WHERE workspace_id=NEW.workspace_id
              AND lifecycle_ordinal=3
              AND state=NEW.final_state
              AND reason=NEW.reason
              AND recorded_at=NEW.recorded_at
        )
        BEGIN SELECT RAISE(ABORT,'graphiti cleanup receipt lacks lifecycle event'); END""",
    """CREATE TRIGGER graphiti_attempt_chain_guard
        BEFORE INSERT ON graphiti_adapter_attempts
        WHEN (NEW.attempt_number=1 AND NEW.previous_attempt_id IS NOT NULL)
          OR (NEW.attempt_number>1 AND NOT EXISTS(
              SELECT 1 FROM graphiti_adapter_attempts
              WHERE attempt_id=NEW.previous_attempt_id
                AND run_id=NEW.run_id
                AND attempt_number=NEW.attempt_number-1
          ))
        BEGIN SELECT RAISE(ABORT,'invalid graphiti attempt chain'); END""",
    """CREATE TRIGGER graphiti_attempt_lineage_guard
        BEFORE INSERT ON graphiti_adapter_attempts
        WHEN NOT EXISTS(
            SELECT 1
            FROM graphiti_adapter_configurations AS c
            JOIN graphiti_input_manifests AS m
              ON m.manifest_id=NEW.manifest_id
            JOIN graphiti_workspaces AS w
              ON w.workspace_id=NEW.workspace_id
            JOIN graphiti_cleanup_receipts AS q
              ON q.receipt_id=NEW.cleanup_receipt_id
            JOIN extraction_run_versions AS v
              ON v.run_version_id=NEW.run_version_id
             AND v.run_id=NEW.run_id
            WHERE c.configuration_id=NEW.configuration_id
              AND c.canonical_digest=NEW.configuration_digest
              AND m.configuration_id=NEW.configuration_id
              AND m.configuration_digest=NEW.configuration_digest
              AND m.run_id=NEW.run_id
              AND m.requested_run_version_id=NEW.run_version_id
              AND w.configuration_id=NEW.configuration_id
              AND q.workspace_id=NEW.workspace_id
        )
        BEGIN SELECT RAISE(ABORT,'graphiti attempt lineage mismatch'); END""",
    """CREATE TRIGGER graphiti_attempt_output_guard
        BEFORE INSERT ON graphiti_adapter_attempts
        WHEN (NEW.extraction_output_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM extraction_outputs
                WHERE output_id=NEW.extraction_output_id
                  AND run_id=NEW.run_id
                  AND run_version_id=NEW.run_version_id
              ))
          OR (NEW.proposal_set_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM extraction_proposal_sets
                WHERE proposal_set_id=NEW.proposal_set_id
                  AND run_id=NEW.run_id
                  AND run_version_id=NEW.run_version_id
              ))
        BEGIN SELECT RAISE(ABORT,'graphiti attempt output lineage mismatch'); END""",
    """CREATE TRIGGER graphiti_attempt_head_insert_guard
        BEFORE INSERT ON graphiti_adapter_attempt_heads
        WHEN NEW.current_attempt_number!=1
        BEGIN SELECT RAISE(ABORT,'graphiti attempt heads begin at one'); END""",
    """CREATE TRIGGER graphiti_attempt_head_update_guard
        BEFORE UPDATE ON graphiti_adapter_attempt_heads
        WHEN NEW.run_id!=OLD.run_id
          OR NEW.current_attempt_number!=OLD.current_attempt_number+1
          OR OLD.terminal!=0
        BEGIN SELECT RAISE(ABORT,'invalid graphiti attempt head advance'); END""",
    """CREATE TRIGGER graphiti_replay_source_guard
        BEFORE INSERT ON graphiti_replay_sources
        WHEN NOT EXISTS(
            SELECT 1 FROM graphiti_adapter_attempts AS a
            JOIN extraction_outputs AS o
              ON o.output_id=NEW.source_output_id
            WHERE a.attempt_id=NEW.source_attempt_id
              AND a.run_version_id=NEW.source_run_version_id
              AND a.extraction_output_id=NEW.source_output_id
              AND o.canonical_digest=NEW.output_canonical_digest
              AND ((NEW.eligibility='MALFORMED_OUTPUT'
                    AND a.outcome='MALFORMED_OUTPUT'
                    AND NEW.source_proposal_set_id IS NULL)
                OR (NEW.eligibility IN('COMPLETE','PARTIAL')
                    AND a.outcome=NEW.eligibility
                    AND a.proposal_set_id=NEW.source_proposal_set_id
                    AND EXISTS(
                        SELECT 1 FROM extraction_proposal_sets AS ps
                        WHERE ps.proposal_set_id=NEW.source_proposal_set_id
                          AND ps.canonical_digest=NEW.proposal_set_canonical_digest
                    )))
        )
        BEGIN SELECT RAISE(ABORT,'graphiti replay source differs from retained authority'); END""",
    """CREATE TRIGGER graphiti_attempt_replay_guard
        BEFORE INSERT ON graphiti_adapter_attempt_replays
        WHEN NOT EXISTS(
            SELECT 1 FROM graphiti_adapter_attempts AS a
            JOIN graphiti_adapter_configurations AS c
              ON c.configuration_id=a.configuration_id
            WHERE a.attempt_id=NEW.attempt_id
              AND c.runtime_mode='APPROVED_REPLAY'
        )
        BEGIN SELECT RAISE(ABORT,'graphiti replay binding requires replay configuration'); END""",
    *tuple(
        statement
        for table in (
            "graphiti_workspace_policies",
            "graphiti_adapter_configurations",
            "graphiti_workspaces",
            "graphiti_workspace_lifecycle_events",
            "graphiti_input_manifests",
            "graphiti_input_manifest_passages",
            "graphiti_cleanup_receipts",
            "graphiti_adapter_attempts",
            "graphiti_replay_sources",
            "graphiti_adapter_attempt_replays",
        )
        for statement in (
            f"CREATE TRIGGER immutable_{table}_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT,'immutable {table}'); END",
            f"CREATE TRIGGER immutable_{table}_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT,'retained {table}'); END",
        )
    ),
    """CREATE TRIGGER graphiti_attempt_head_delete_guard
        BEFORE DELETE ON graphiti_adapter_attempt_heads
        BEGIN SELECT RAISE(ABORT,'graphiti attempt heads are retained'); END""",
)


GRAPHITI_ADAPTER_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": GRAPHITI_ADAPTER_SCHEMA_VERSION,
        "name": GRAPHITI_ADAPTER_MIGRATION_NAME,
        "statements": list(GRAPHITI_ADAPTER_MIGRATION_STATEMENTS),
    }
)
GRAPHITI_ADAPTER_MIGRATION = GraphitiAdapterMigrationRecord(
    version=GRAPHITI_ADAPTER_SCHEMA_VERSION,
    name=GRAPHITI_ADAPTER_MIGRATION_NAME,
    checksum=GRAPHITI_ADAPTER_MIGRATION_CHECKSUM,
)


__all__ = [
    "GRAPHITI_ADAPTER_MIGRATION",
    "GRAPHITI_ADAPTER_MIGRATION_CHECKSUM",
    "GRAPHITI_ADAPTER_MIGRATION_NAME",
    "GRAPHITI_ADAPTER_MIGRATION_STATEMENTS",
    "GRAPHITI_ADAPTER_SCHEMA_VERSION",
]
