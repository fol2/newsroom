from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical


SOURCE_REGISTRY_SCHEMA_VERSION = 10
SOURCE_REGISTRY_MIGRATION_NAME = "source_registry_authority_v10"


@dataclass(frozen=True, slots=True)
class SourceRegistryMigrationRecord:
    version: int
    name: str
    checksum: str


_ROLES = (
    "'ORIGINATING_AUTHORITY','RESPONSIBLE_OPERATOR','PLANNED_AGENDA',"
    "'ESTABLISHED_MEDIA_RADAR','SPECIALIST_OR_LOCAL_RADAR',"
    "'MANUAL_EDITOR_READER_LEAD'"
)
_FUNCTIONS = (
    "'ANCHOR','COMPLEMENT','COMPARATOR','EXPLICIT_CONTINGENCY','MANUAL_ONLY'"
)
_RESPONSIBILITIES = (
    "'ACTIVE','BEST_EFFORT','EXPLICIT_DEFERRED_GAP',"
    "'OPERATIONAL_RESILIENCE','EVALUATION'"
)
_CONTRIBUTIONS = (
    "'DETECTION_PATH','OCCURRENCE_CONFIRMATION','REVISION_VISIBILITY',"
    "'URGENT_FAST_PATH','REDUNDANCY','COMPARATOR'"
)
_DEPENDENCIES = (
    "'ORIGINATING_MATERIAL','SYNDICATION','WIRE','PRESS_RELEASE','SHARED_DATA',"
    "'EDITORIAL_SELECTION','TRANSPORT','AUTHENTICATION','CREDENTIAL','OTHER'"
)
_OBSERVATION_MODELS = (
    "'APPEND_ONLY','MUTABLE_ITEM','COMPLETE_CURRENT_STATE','ROLLING_LIST',"
    "'EXPLICIT_DELTA','PLANNED_AGENDA'"
)
_BASELINE_KINDS = (
    "'MAINTAINED_DOCUMENT','BOUNDED_BACKFILL',"
    "'COMPLETE_STATE_FIRST_OBSERVED_ACTIVE','PLANNED_AGENDA_FUTURE_ONLY',"
    "'EXPLICIT_DELTA_SEQUENCE','MANUAL_ONLY'"
)
_LIFECYCLE_STAGES = (
    "'RESEARCH_CANDIDATE','HELD_CANDIDATE','SHADOW_SHORTLISTED',"
    "'COMPARATOR_ONLY','PRODUCTION_ELIGIBLE','RETIRED','REJECTED'"
)
_IDENTITY_KINDS = "'SOURCE_NATIVE','COMPOSITE','ASSIGNED_WITH_UNCERTAINTY'"
_LOCATOR_OUTCOMES = (
    "'SAME_ITEM','DIFFERENT_ITEM','POSSIBLE_REPLACEMENT',"
    "'POSSIBLE_EQUIVALENCE','UNCERTAIN'"
)
_OCCURRENCE_KINDS = "'FIRST_OBSERVED','REOBSERVED','DELIVERED'"


SOURCE_REGISTRY_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE source_definitions(
        definition_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        editorial_purpose TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(length(name)>0),
        CHECK(length(editorial_purpose)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE source_definition_versions(
        version_id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        version_number INTEGER NOT NULL CHECK(version_number>0),
        previous_version_id TEXT REFERENCES source_definition_versions(version_id),
        locator TEXT NOT NULL,
        locator_digest TEXT NOT NULL,
        adapter_policy_id TEXT NOT NULL,
        adapter_policy_version TEXT NOT NULL,
        extraction_scope_bytes BLOB NOT NULL,
        rights_decision_id TEXT NOT NULL,
        rights_policy_version TEXT NOT NULL,
        allowed_use TEXT NOT NULL,
        source_retention_scope TEXT NOT NULL,
        observation_model TEXT NOT NULL CHECK(observation_model IN({_OBSERVATION_MODELS})),
        baseline_policy_id TEXT NOT NULL,
        baseline_policy_version TEXT NOT NULL,
        baseline_kind TEXT NOT NULL CHECK(baseline_kind IN({_BASELINE_KINDS})),
        baseline_freshness_seconds INTEGER CHECK(
            baseline_freshness_seconds IS NULL OR baseline_freshness_seconds>0
        ),
        baseline_reset_requires_decision INTEGER NOT NULL
            CHECK(baseline_reset_requires_decision IN(0,1)),
        baseline_notes TEXT NOT NULL,
        item_identity_policy_id TEXT NOT NULL,
        item_identity_policy_version TEXT NOT NULL,
        revision_policy_id TEXT NOT NULL,
        revision_policy_version TEXT NOT NULL,
        canonicalization_policy_id TEXT NOT NULL,
        canonicalization_policy_version TEXT NOT NULL,
        lifecycle_stage TEXT NOT NULL CHECK(lifecycle_stage IN({_LIFECYCLE_STAGES})),
        change_reason TEXT NOT NULL,
        execution_authority TEXT NOT NULL
            CHECK(execution_authority='FIXTURE_REPLAY_ONLY_DISABLED'),
        semantic_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(definition_id,version_number),
        UNIQUE(definition_id,semantic_digest),
        UNIQUE(version_id,definition_id),
        UNIQUE(definition_id,version_number,version_id),
        CHECK((version_number=1 AND previous_version_id IS NULL)
           OR (version_number>1 AND previous_version_id IS NOT NULL)),
        CHECK(length(locator)>0),
        CHECK(length(extraction_scope_bytes)>0),
        CHECK(length(change_reason)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE source_definition_version_heads(
        definition_id TEXT PRIMARY KEY REFERENCES source_definitions(definition_id),
        current_version_number INTEGER NOT NULL CHECK(current_version_number>0),
        current_version_id TEXT NOT NULL UNIQUE,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(definition_id,current_version_number,current_version_id)
            REFERENCES source_definition_versions(
                definition_id,version_number,version_id
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE source_version_roles(
        version_id TEXT NOT NULL REFERENCES source_definition_versions(version_id),
        role TEXT NOT NULL CHECK(role IN({_ROLES})),
        purpose TEXT NOT NULL,
        limitations_bytes BLOB NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(version_id,role),
        CHECK(length(purpose)>0),
        CHECK(length(limitations_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE source_version_portfolio_functions(
        version_id TEXT NOT NULL REFERENCES source_definition_versions(version_id),
        portfolio_function TEXT NOT NULL CHECK(portfolio_function IN({_FUNCTIONS})),
        PRIMARY KEY(version_id,portfolio_function)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE source_version_gaps(
        version_id TEXT NOT NULL REFERENCES source_definition_versions(version_id),
        gap_id TEXT NOT NULL,
        gap_class TEXT NOT NULL,
        description TEXT NOT NULL,
        launch_blocking INTEGER NOT NULL CHECK(launch_blocking IN(0,1)),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(version_id,gap_id),
        CHECK(length(description)>0),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE source_version_coverage_mappings(
        version_id TEXT NOT NULL REFERENCES source_definition_versions(version_id),
        obligation_id TEXT NOT NULL,
        responsibility TEXT NOT NULL CHECK(responsibility IN({_RESPONSIBILITIES})),
        contribution TEXT NOT NULL CHECK(contribution IN({_CONTRIBUTIONS})),
        geographies_bytes BLOB NOT NULL,
        languages_bytes BLOB NOT NULL,
        limitations_bytes BLOB NOT NULL,
        explicit_gap_id TEXT,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(version_id,obligation_id,responsibility,contribution),
        FOREIGN KEY(version_id,explicit_gap_id)
            REFERENCES source_version_gaps(version_id,gap_id)
            DEFERRABLE INITIALLY DEFERRED,
        CHECK((responsibility='EXPLICIT_DEFERRED_GAP' AND explicit_gap_id IS NOT NULL)
           OR (responsibility!='EXPLICIT_DEFERRED_GAP' AND explicit_gap_id IS NULL)),
        CHECK(length(geographies_bytes)>0),
        CHECK(length(languages_bytes)>0),
        CHECK(length(limitations_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE source_version_dependencies(
        version_id TEXT NOT NULL REFERENCES source_definition_versions(version_id),
        dependency_id TEXT NOT NULL,
        dependency_kind TEXT NOT NULL CHECK(dependency_kind IN({_DEPENDENCIES})),
        description TEXT NOT NULL,
        upstream_definition_id TEXT REFERENCES source_definitions(definition_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(version_id,dependency_id),
        CHECK(length(description)>0),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE source_items(
        item_id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        identity_kind TEXT NOT NULL CHECK(identity_kind IN({_IDENTITY_KINDS})),
        identity_policy_id TEXT NOT NULL,
        identity_policy_version TEXT NOT NULL,
        source_native_id TEXT,
        identity_components_bytes BLOB NOT NULL,
        uncertainties_bytes BLOB NOT NULL,
        identity_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(definition_id,identity_digest),
        UNIQUE(item_id,definition_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        CHECK(length(identity_components_bytes)>0),
        CHECK(length(uncertainties_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE source_locator_continuity_decisions(
        decision_id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        prior_item_id TEXT NOT NULL,
        prior_locator TEXT NOT NULL,
        prior_locator_digest TEXT NOT NULL,
        observed_locator TEXT NOT NULL,
        observed_locator_digest TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN({_LOCATOR_OUTCOMES})),
        related_item_id TEXT NOT NULL,
        rationale TEXT NOT NULL,
        decision_policy_id TEXT NOT NULL,
        decision_policy_version TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        semantic_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(definition_id,semantic_digest),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        FOREIGN KEY(prior_item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        FOREIGN KEY(related_item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        CHECK(prior_locator!=observed_locator),
        CHECK((outcome='SAME_ITEM' AND related_item_id=prior_item_id)
           OR (outcome!='SAME_ITEM' AND related_item_id!=prior_item_id)),
        CHECK(length(rationale)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE source_revisions(
        revision_id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES source_items(item_id),
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        prior_revision_id TEXT REFERENCES source_revisions(revision_id),
        source_native_revision_token TEXT,
        permitted_state_digest TEXT NOT NULL,
        revision_policy_id TEXT NOT NULL,
        revision_policy_version TEXT NOT NULL,
        canonicalizer_version TEXT NOT NULL,
        source_published_time_bytes BLOB NOT NULL,
        source_updated_time_bytes BLOB NOT NULL,
        observed_at TEXT NOT NULL,
        revision_identity_digest TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(item_id,revision_identity_digest),
        UNIQUE(revision_id,item_id),
        UNIQUE(revision_id,definition_id),
        FOREIGN KEY(item_id,definition_id)
            REFERENCES source_items(item_id,definition_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        CHECK(prior_revision_id IS NULL OR prior_revision_id!=revision_id),
        CHECK(length(source_published_time_bytes)>0),
        CHECK(length(source_updated_time_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE discovery_representations(
        representation_id TEXT PRIMARY KEY,
        revision_id TEXT NOT NULL REFERENCES source_revisions(revision_id),
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        adapter_version TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        normalizer_version TEXT NOT NULL,
        extraction_scope_version TEXT NOT NULL,
        permitted_fields_digest TEXT NOT NULL,
        representation_digest TEXT NOT NULL,
        producer_slot_digest TEXT NOT NULL,
        representation_identity_digest TEXT NOT NULL,
        produced_at TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(revision_id,producer_slot_digest),
        UNIQUE(revision_id,representation_identity_digest),
        UNIQUE(representation_id,revision_id),
        FOREIGN KEY(revision_id,definition_id)
            REFERENCES source_revisions(revision_id,definition_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE discovery_occurrences(
        occurrence_id TEXT PRIMARY KEY,
        check_outcome_id TEXT NOT NULL,
        revision_id TEXT NOT NULL REFERENCES source_revisions(revision_id),
        representation_id TEXT,
        definition_id TEXT NOT NULL REFERENCES source_definitions(definition_id),
        definition_version_id TEXT NOT NULL,
        occurrence_kind TEXT NOT NULL CHECK(occurrence_kind IN({_OCCURRENCE_KINDS})),
        observed_at TEXT NOT NULL,
        receipt_digest TEXT NOT NULL,
        source_asserted_time_bytes BLOB NOT NULL,
        semantic_digest TEXT NOT NULL UNIQUE,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(check_outcome_id,revision_id,occurrence_kind),
        FOREIGN KEY(revision_id,definition_id)
            REFERENCES source_revisions(revision_id,definition_id),
        FOREIGN KEY(representation_id,revision_id)
            REFERENCES discovery_representations(representation_id,revision_id),
        FOREIGN KEY(definition_version_id,definition_id)
            REFERENCES source_definition_versions(version_id,definition_id),
        CHECK(length(source_asserted_time_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    "CREATE INDEX idx_source_versions_definition ON source_definition_versions(definition_id,version_number)",
    "CREATE INDEX idx_source_coverage_obligation ON source_version_coverage_mappings(obligation_id,responsibility,contribution)",
    "CREATE INDEX idx_source_items_definition ON source_items(definition_id,recorded_at)",
    "CREATE INDEX idx_source_revisions_item ON source_revisions(item_id,recorded_at)",
    "CREATE INDEX idx_source_representations_revision ON discovery_representations(revision_id,recorded_at)",
    "CREATE INDEX idx_source_occurrences_revision ON discovery_occurrences(revision_id,observed_at,recorded_at)",
    """CREATE TRIGGER immutable_source_definition_update
        BEFORE UPDATE ON source_definitions BEGIN
        SELECT RAISE(ABORT,'immutable source definition'); END""",
    """CREATE TRIGGER immutable_source_definition_delete
        BEFORE DELETE ON source_definitions BEGIN
        SELECT RAISE(ABORT,'source definitions are retained'); END""",
    """CREATE TRIGGER immutable_source_version_update
        BEFORE UPDATE ON source_definition_versions BEGIN
        SELECT RAISE(ABORT,'immutable source definition version'); END""",
    """CREATE TRIGGER immutable_source_version_delete
        BEFORE DELETE ON source_definition_versions BEGIN
        SELECT RAISE(ABORT,'source definition versions are retained'); END""",
    """CREATE TRIGGER source_version_head_insert_guard
        BEFORE INSERT ON source_definition_version_heads
        WHEN NEW.current_version_number!=1 BEGIN
        SELECT RAISE(ABORT,'source version heads begin at version one'); END""",
    """CREATE TRIGGER source_version_head_update_guard
        BEFORE UPDATE ON source_definition_version_heads
        WHEN NEW.definition_id!=OLD.definition_id
          OR NEW.current_version_number!=OLD.current_version_number+1
          OR NOT EXISTS(
              SELECT 1 FROM source_definition_versions v
              WHERE v.version_id=NEW.current_version_id
                AND v.definition_id=NEW.definition_id
                AND v.version_number=NEW.current_version_number
                AND v.previous_version_id=OLD.current_version_id
          )
        BEGIN SELECT RAISE(ABORT,'invalid source version-head update'); END""",
    """CREATE TRIGGER source_version_head_delete_guard
        BEFORE DELETE ON source_definition_version_heads BEGIN
        SELECT RAISE(ABORT,'source version heads are retained'); END""",
    """CREATE TRIGGER immutable_source_role_update
        BEFORE UPDATE ON source_version_roles BEGIN
        SELECT RAISE(ABORT,'immutable source role'); END""",
    """CREATE TRIGGER immutable_source_role_delete
        BEFORE DELETE ON source_version_roles BEGIN
        SELECT RAISE(ABORT,'source roles are retained'); END""",
    """CREATE TRIGGER immutable_source_function_update
        BEFORE UPDATE ON source_version_portfolio_functions BEGIN
        SELECT RAISE(ABORT,'immutable source portfolio function'); END""",
    """CREATE TRIGGER immutable_source_function_delete
        BEFORE DELETE ON source_version_portfolio_functions BEGIN
        SELECT RAISE(ABORT,'source portfolio functions are retained'); END""",
    """CREATE TRIGGER immutable_source_gap_update
        BEFORE UPDATE ON source_version_gaps BEGIN
        SELECT RAISE(ABORT,'immutable source gap'); END""",
    """CREATE TRIGGER immutable_source_gap_delete
        BEFORE DELETE ON source_version_gaps BEGIN
        SELECT RAISE(ABORT,'source gaps are retained'); END""",
    """CREATE TRIGGER immutable_source_coverage_update
        BEFORE UPDATE ON source_version_coverage_mappings BEGIN
        SELECT RAISE(ABORT,'immutable source coverage mapping'); END""",
    """CREATE TRIGGER immutable_source_coverage_delete
        BEFORE DELETE ON source_version_coverage_mappings BEGIN
        SELECT RAISE(ABORT,'source coverage mappings are retained'); END""",
    """CREATE TRIGGER immutable_source_dependency_update
        BEFORE UPDATE ON source_version_dependencies BEGIN
        SELECT RAISE(ABORT,'immutable source dependency'); END""",
    """CREATE TRIGGER immutable_source_dependency_delete
        BEFORE DELETE ON source_version_dependencies BEGIN
        SELECT RAISE(ABORT,'source dependencies are retained'); END""",
    """CREATE TRIGGER immutable_source_item_update
        BEFORE UPDATE ON source_items BEGIN
        SELECT RAISE(ABORT,'immutable source item'); END""",
    """CREATE TRIGGER immutable_source_item_delete
        BEFORE DELETE ON source_items BEGIN
        SELECT RAISE(ABORT,'source items are retained'); END""",
    """CREATE TRIGGER immutable_source_locator_decision_update
        BEFORE UPDATE ON source_locator_continuity_decisions BEGIN
        SELECT RAISE(ABORT,'immutable source locator decision'); END""",
    """CREATE TRIGGER immutable_source_locator_decision_delete
        BEFORE DELETE ON source_locator_continuity_decisions BEGIN
        SELECT RAISE(ABORT,'source locator decisions are retained'); END""",
    """CREATE TRIGGER immutable_source_revision_update
        BEFORE UPDATE ON source_revisions BEGIN
        SELECT RAISE(ABORT,'immutable source revision'); END""",
    """CREATE TRIGGER immutable_source_revision_delete
        BEFORE DELETE ON source_revisions BEGIN
        SELECT RAISE(ABORT,'source revisions are retained'); END""",
    """CREATE TRIGGER immutable_discovery_representation_update
        BEFORE UPDATE ON discovery_representations BEGIN
        SELECT RAISE(ABORT,'immutable discovery representation'); END""",
    """CREATE TRIGGER immutable_discovery_representation_delete
        BEFORE DELETE ON discovery_representations BEGIN
        SELECT RAISE(ABORT,'discovery representations are retained'); END""",
    """CREATE TRIGGER immutable_discovery_occurrence_update
        BEFORE UPDATE ON discovery_occurrences BEGIN
        SELECT RAISE(ABORT,'immutable discovery occurrence'); END""",
    """CREATE TRIGGER immutable_discovery_occurrence_delete
        BEFORE DELETE ON discovery_occurrences BEGIN
        SELECT RAISE(ABORT,'discovery occurrences are retained'); END""",
)


SOURCE_REGISTRY_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": SOURCE_REGISTRY_SCHEMA_VERSION,
        "name": SOURCE_REGISTRY_MIGRATION_NAME,
        "statements": list(SOURCE_REGISTRY_MIGRATION_STATEMENTS),
    }
)
SOURCE_REGISTRY_MIGRATION = SourceRegistryMigrationRecord(
    version=SOURCE_REGISTRY_SCHEMA_VERSION,
    name=SOURCE_REGISTRY_MIGRATION_NAME,
    checksum=SOURCE_REGISTRY_MIGRATION_CHECKSUM,
)


__all__ = [
    "SOURCE_REGISTRY_MIGRATION",
    "SOURCE_REGISTRY_MIGRATION_CHECKSUM",
    "SOURCE_REGISTRY_MIGRATION_NAME",
    "SOURCE_REGISTRY_MIGRATION_STATEMENTS",
    "SOURCE_REGISTRY_SCHEMA_VERSION",
]
