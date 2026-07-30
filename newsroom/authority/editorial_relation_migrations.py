from __future__ import annotations

from dataclasses import dataclass

from .canonical import canonical_json_bytes, digest_bytes, digest_canonical


EDITORIAL_RELATION_SCHEMA_VERSION = 15
EDITORIAL_RELATION_MIGRATION_NAME = "editorial_relation_authority_v15"
EDITORIAL_PREDICATE_REGISTRY_VERSION = "editorial-predicate-registry-v1"
EDITORIAL_PREDICATE_CONTRACT_VERSION = "editorial-predicate-contract-v1"
EDITORIAL_RELATION_ADMISSION_POLICY_VERSION = "editorial-relation-admission-policy-v1"


@dataclass(frozen=True, slots=True)
class EditorialRelationMigrationRecord:
    version: int
    name: str
    checksum: str


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _blob(value: bytes) -> str:
    return "X'" + value.hex() + "'"


_ENDPOINT_KIND_VALUES = (
    "CANONICAL_ENTITY_VERSION",
    "SOURCE_REVISION",
    "EVENT_HYPOTHESIS_VERSION",
    "STORY_CANDIDATE_VERSION",
    "RELATION_ASSERTION",
)
_PREDICATE_VALUES = (
    "SAME_EVENT_AS",
    "DEVELOPMENT_OF",
    "SAME_PROCESS_AS",
    "CORRECTS",
    "SUPERSEDES",
    "SUPPORTS",
    "DISPUTES",
    "CONTRADICTS",
    "ABOUT_EVENT",
)
_DIRECTION_VALUES = ("DIRECTED", "SYMMETRIC")
_TEMPORAL_VALUES = (
    "VALID_INTERVAL_REQUIRED",
    "VALID_INTERVAL_OPTIONAL",
    "TIMELESS",
)
_EVIDENCE_KIND_VALUES = ("EXTRACTION_PROPOSAL", "WORKFLOW_EVENT")
_PRODUCER_KIND_VALUES = (
    "DETERMINISTIC_FIXTURE",
    "EXTRACTION_RUN",
    "AUTHORISED_OPERATOR",
    "GOVERNED_WORKFLOW",
)
_DECISION_ACTION_VALUES = (
    "ACCEPT",
    "REJECT",
    "HOLD",
    "UNRESOLVED",
    "INVALIDATE",
    "REVOKE",
    "SUPERSEDE",
)
_CURRENT_STATE_VALUES = (
    "PROPOSED",
    "HELD",
    "UNRESOLVED",
    "REJECTED",
    "ADMITTED",
    "INVALIDATED",
    "REVOKED",
    "SUPERSEDED",
)
_ASSERTION_LIFECYCLE_VALUES = ("ACTIVE", "INVALIDATED", "REVOKED", "SUPERSEDED")
_PROJECTION_ACTION_VALUES = ("UPSERT", "REMOVE")


def _sql_values(values: tuple[str, ...]) -> str:
    return ",".join(_quoted(item) for item in values)


_ENDPOINT_KINDS = _sql_values(_ENDPOINT_KIND_VALUES)
_PREDICATES = _sql_values(_PREDICATE_VALUES)
_DIRECTIONS = _sql_values(_DIRECTION_VALUES)
_TEMPORAL = _sql_values(_TEMPORAL_VALUES)
_EVIDENCE_KINDS = _sql_values(_EVIDENCE_KIND_VALUES)
_PRODUCER_KINDS = _sql_values(_PRODUCER_KIND_VALUES)
_DECISION_ACTIONS = _sql_values(_DECISION_ACTION_VALUES)
_CURRENT_STATES = _sql_values(_CURRENT_STATE_VALUES)
_ASSERTION_LIFECYCLES = _sql_values(_ASSERTION_LIFECYCLE_VALUES)
_PROJECTION_ACTIONS = _sql_values(_PROJECTION_ACTION_VALUES)


def _pairs(*values: tuple[str, str]) -> tuple[dict[str, str], ...]:
    return tuple(
        {"subject_kind": subject, "object_kind": object_}
        for subject, object_ in sorted(set(values))
    )


_PREDICATE_SPECS: tuple[dict[str, object], ...] = tuple(
    sorted(
        (
            {
                "predicate": "ABOUT_EVENT",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "DIRECTED",
                "temporal_semantics": "VALID_INTERVAL_OPTIONAL",
                "allowed_endpoint_pairs": _pairs(
                    ("CANONICAL_ENTITY_VERSION", "EVENT_HYPOTHESIS_VERSION"),
                    ("SOURCE_REVISION", "EVENT_HYPOTHESIS_VERSION"),
                    ("STORY_CANDIDATE_VERSION", "EVENT_HYPOTHESIS_VERSION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
            {
                "predicate": "CONTRADICTS",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "SYMMETRIC",
                "temporal_semantics": "VALID_INTERVAL_OPTIONAL",
                "allowed_endpoint_pairs": _pairs(
                    ("EVENT_HYPOTHESIS_VERSION", "EVENT_HYPOTHESIS_VERSION"),
                    ("RELATION_ASSERTION", "RELATION_ASSERTION"),
                    ("SOURCE_REVISION", "EVENT_HYPOTHESIS_VERSION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
            {
                "predicate": "CORRECTS",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "DIRECTED",
                "temporal_semantics": "VALID_INTERVAL_OPTIONAL",
                "allowed_endpoint_pairs": _pairs(
                    ("RELATION_ASSERTION", "RELATION_ASSERTION"),
                    ("SOURCE_REVISION", "SOURCE_REVISION"),
                    ("STORY_CANDIDATE_VERSION", "STORY_CANDIDATE_VERSION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
            {
                "predicate": "DEVELOPMENT_OF",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "DIRECTED",
                "temporal_semantics": "VALID_INTERVAL_REQUIRED",
                "allowed_endpoint_pairs": _pairs(
                    ("EVENT_HYPOTHESIS_VERSION", "EVENT_HYPOTHESIS_VERSION"),
                    ("SOURCE_REVISION", "SOURCE_REVISION"),
                    ("STORY_CANDIDATE_VERSION", "STORY_CANDIDATE_VERSION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
            {
                "predicate": "DISPUTES",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "DIRECTED",
                "temporal_semantics": "VALID_INTERVAL_OPTIONAL",
                "allowed_endpoint_pairs": _pairs(
                    ("CANONICAL_ENTITY_VERSION", "EVENT_HYPOTHESIS_VERSION"),
                    ("CANONICAL_ENTITY_VERSION", "RELATION_ASSERTION"),
                    ("SOURCE_REVISION", "EVENT_HYPOTHESIS_VERSION"),
                    ("SOURCE_REVISION", "RELATION_ASSERTION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
            {
                "predicate": "SAME_EVENT_AS",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "SYMMETRIC",
                "temporal_semantics": "VALID_INTERVAL_OPTIONAL",
                "allowed_endpoint_pairs": _pairs(
                    ("EVENT_HYPOTHESIS_VERSION", "EVENT_HYPOTHESIS_VERSION"),
                    ("SOURCE_REVISION", "SOURCE_REVISION"),
                    ("STORY_CANDIDATE_VERSION", "STORY_CANDIDATE_VERSION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
            {
                "predicate": "SAME_PROCESS_AS",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "SYMMETRIC",
                "temporal_semantics": "VALID_INTERVAL_OPTIONAL",
                "allowed_endpoint_pairs": _pairs(
                    ("CANONICAL_ENTITY_VERSION", "CANONICAL_ENTITY_VERSION"),
                    ("EVENT_HYPOTHESIS_VERSION", "EVENT_HYPOTHESIS_VERSION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
            {
                "predicate": "SUPERSEDES",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "DIRECTED",
                "temporal_semantics": "VALID_INTERVAL_OPTIONAL",
                "allowed_endpoint_pairs": _pairs(
                    ("RELATION_ASSERTION", "RELATION_ASSERTION"),
                    ("SOURCE_REVISION", "SOURCE_REVISION"),
                    ("STORY_CANDIDATE_VERSION", "STORY_CANDIDATE_VERSION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
            {
                "predicate": "SUPPORTS",
                "contract_version": EDITORIAL_PREDICATE_CONTRACT_VERSION,
                "directionality": "DIRECTED",
                "temporal_semantics": "VALID_INTERVAL_OPTIONAL",
                "allowed_endpoint_pairs": _pairs(
                    ("CANONICAL_ENTITY_VERSION", "EVENT_HYPOTHESIS_VERSION"),
                    ("CANONICAL_ENTITY_VERSION", "RELATION_ASSERTION"),
                    ("SOURCE_REVISION", "EVENT_HYPOTHESIS_VERSION"),
                    ("SOURCE_REVISION", "RELATION_ASSERTION"),
                ),
                "admission_policy_version": EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
            },
        ),
        key=lambda item: str(item["predicate"]),
    )
)

_EDITORIAL_REGISTRY_CANONICAL_VALUE = {
    "registry_version": EDITORIAL_PREDICATE_REGISTRY_VERSION,
    "contracts": [
        {
            **spec,
            "allowed_endpoint_pairs": list(spec["allowed_endpoint_pairs"]),
        }
        for spec in _PREDICATE_SPECS
    ],
}
EDITORIAL_PREDICATE_REGISTRY_CANONICAL_BYTES = canonical_json_bytes(
    _EDITORIAL_REGISTRY_CANONICAL_VALUE
)
EDITORIAL_PREDICATE_REGISTRY_DIGEST = digest_bytes(
    EDITORIAL_PREDICATE_REGISTRY_CANONICAL_BYTES
)

_REGISTRY_INSERTS: list[str] = [
    "INSERT INTO editorial_predicate_registries("
    "registry_version,canonical_bytes,canonical_digest) VALUES("
    f"{_quoted(EDITORIAL_PREDICATE_REGISTRY_VERSION)},"
    f"{_blob(EDITORIAL_PREDICATE_REGISTRY_CANONICAL_BYTES)},"
    f"{_quoted(EDITORIAL_PREDICATE_REGISTRY_DIGEST)})"
]
for spec in _PREDICATE_SPECS:
    canonical_value = {
        **spec,
        "allowed_endpoint_pairs": list(spec["allowed_endpoint_pairs"]),
    }
    canonical_bytes = canonical_json_bytes(canonical_value)
    canonical_digest_value = digest_bytes(canonical_bytes)
    _REGISTRY_INSERTS.append(
        "INSERT INTO editorial_predicate_contracts("
        "predicate,contract_version,registry_version,directionality,"
        "temporal_semantics,admission_policy_version,canonical_bytes,"
        "canonical_digest) VALUES("
        f"{_quoted(str(spec['predicate']))},"
        f"{_quoted(str(spec['contract_version']))},"
        f"{_quoted(EDITORIAL_PREDICATE_REGISTRY_VERSION)},"
        f"{_quoted(str(spec['directionality']))},"
        f"{_quoted(str(spec['temporal_semantics']))},"
        f"{_quoted(str(spec['admission_policy_version']))},"
        f"{_blob(canonical_bytes)},"
        f"{_quoted(canonical_digest_value)})"
    )
    for pair in spec["allowed_endpoint_pairs"]:
        _REGISTRY_INSERTS.append(
            "INSERT INTO editorial_predicate_endpoint_pairs("
            "predicate,contract_version,subject_kind,object_kind) VALUES("
            f"{_quoted(str(spec['predicate']))},"
            f"{_quoted(str(spec['contract_version']))},"
            f"{_quoted(pair['subject_kind'])},"
            f"{_quoted(pair['object_kind'])})"
        )


EDITORIAL_RELATION_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE editorial_predicate_registries(
        registry_version TEXT PRIMARY KEY,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE editorial_predicate_contracts(
        predicate TEXT NOT NULL CHECK(predicate IN({_PREDICATES})),
        contract_version TEXT NOT NULL,
        registry_version TEXT NOT NULL
            REFERENCES editorial_predicate_registries(registry_version),
        directionality TEXT NOT NULL CHECK(directionality IN({_DIRECTIONS})),
        temporal_semantics TEXT NOT NULL CHECK(temporal_semantics IN({_TEMPORAL})),
        admission_policy_version TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        PRIMARY KEY(predicate,contract_version),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE editorial_predicate_endpoint_pairs(
        predicate TEXT NOT NULL,
        contract_version TEXT NOT NULL,
        subject_kind TEXT NOT NULL CHECK(subject_kind IN({_ENDPOINT_KINDS})),
        object_kind TEXT NOT NULL CHECK(object_kind IN({_ENDPOINT_KINDS})),
        PRIMARY KEY(predicate,contract_version,subject_kind,object_kind),
        FOREIGN KEY(predicate,contract_version)
            REFERENCES editorial_predicate_contracts(predicate,contract_version)
    ) WITHOUT ROWID, STRICT""",
    *_REGISTRY_INSERTS,
    f"""CREATE TABLE editorial_relation_endpoints(
        endpoint_digest TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK(kind IN({_ENDPOINT_KINDS})),
        entity_id TEXT,
        entity_version_id TEXT,
        source_item_id TEXT,
        source_revision_id TEXT,
        hypothesis_version_id TEXT,
        candidate_id TEXT,
        candidate_version_id TEXT,
        assertion_id TEXT,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL UNIQUE,
        FOREIGN KEY(entity_version_id,entity_id)
            REFERENCES canonical_entity_versions(entity_version_id,entity_id),
        FOREIGN KEY(source_revision_id,source_item_id)
            REFERENCES source_revisions(revision_id,item_id),
        FOREIGN KEY(candidate_id) REFERENCES story_candidates(candidate_id),
        FOREIGN KEY(candidate_version_id)
            REFERENCES story_candidate_versions(candidate_version_id),
        FOREIGN KEY(assertion_id)
            REFERENCES editorial_relation_assertions(assertion_id)
            DEFERRABLE INITIALLY DEFERRED,
        CHECK((kind='CANONICAL_ENTITY_VERSION'
               AND entity_id IS NOT NULL AND entity_version_id IS NOT NULL
               AND source_item_id IS NULL AND source_revision_id IS NULL
               AND hypothesis_version_id IS NULL
               AND candidate_id IS NULL AND candidate_version_id IS NULL
               AND assertion_id IS NULL)
           OR (kind='SOURCE_REVISION'
               AND entity_id IS NULL AND entity_version_id IS NULL
               AND source_item_id IS NOT NULL AND source_revision_id IS NOT NULL
               AND hypothesis_version_id IS NULL
               AND candidate_id IS NULL AND candidate_version_id IS NULL
               AND assertion_id IS NULL)
           OR (kind='EVENT_HYPOTHESIS_VERSION'
               AND entity_id IS NULL AND entity_version_id IS NULL
               AND source_item_id IS NULL AND source_revision_id IS NULL
               AND hypothesis_version_id IS NOT NULL
               AND candidate_id IS NULL AND candidate_version_id IS NULL
               AND assertion_id IS NULL)
           OR (kind='STORY_CANDIDATE_VERSION'
               AND entity_id IS NULL AND entity_version_id IS NULL
               AND source_item_id IS NULL AND source_revision_id IS NULL
               AND hypothesis_version_id IS NULL
               AND candidate_id IS NOT NULL AND candidate_version_id IS NOT NULL
               AND assertion_id IS NULL)
           OR (kind='RELATION_ASSERTION'
               AND entity_id IS NULL AND entity_version_id IS NULL
               AND source_item_id IS NULL AND source_revision_id IS NULL
               AND hypothesis_version_id IS NULL
               AND candidate_id IS NULL AND candidate_version_id IS NULL
               AND assertion_id IS NOT NULL)),
        CHECK(endpoint_digest=canonical_digest),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE editorial_relation_proposals(
        proposal_id TEXT PRIMARY KEY,
        registry_version TEXT NOT NULL,
        predicate_registry_digest TEXT NOT NULL,
        predicate TEXT NOT NULL CHECK(predicate IN({_PREDICATES})),
        predicate_contract_version TEXT NOT NULL,
        predicate_contract_digest TEXT NOT NULL,
        subject_endpoint_digest TEXT NOT NULL
            REFERENCES editorial_relation_endpoints(endpoint_digest),
        object_endpoint_digest TEXT NOT NULL
            REFERENCES editorial_relation_endpoints(endpoint_digest),
        producer_kind TEXT NOT NULL CHECK(producer_kind IN({_PRODUCER_KINDS})),
        producer_id TEXT NOT NULL,
        producer_version TEXT NOT NULL,
        producer_contract_digest TEXT NOT NULL,
        semantic_slot_digest TEXT NOT NULL,
        stable_semantic_digest TEXT NOT NULL UNIQUE,
        created_by_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(registry_version)
            REFERENCES editorial_predicate_registries(registry_version),
        FOREIGN KEY(predicate,predicate_contract_version)
            REFERENCES editorial_predicate_contracts(predicate,contract_version),
        CHECK(subject_endpoint_digest!=object_endpoint_digest),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE editorial_relation_proposal_versions(
        proposal_version_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL
            REFERENCES editorial_relation_proposals(proposal_id),
        version_number INTEGER NOT NULL CHECK(version_number>0),
        previous_proposal_version_id TEXT
            REFERENCES editorial_relation_proposal_versions(proposal_version_id),
        valid_from TEXT,
        valid_until TEXT,
        observed_at TEXT NOT NULL,
        statement TEXT NOT NULL,
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
        authority_ledger_seq INTEGER NOT NULL UNIQUE CHECK(authority_ledger_seq>0),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        recorded_at TEXT NOT NULL,
        UNIQUE(proposal_id,version_number),
        UNIQUE(proposal_version_id,proposal_id),
        UNIQUE(proposal_id,version_number,proposal_version_id),
        CHECK((version_number=1 AND previous_proposal_version_id IS NULL)
           OR (version_number>1 AND previous_proposal_version_id IS NOT NULL)),
        CHECK(valid_until IS NULL OR
              (valid_from IS NOT NULL AND valid_until>valid_from)),
        CHECK(length(statement)>0),
        CHECK(length(uncertainty_codes_bytes)>0),
        CHECK(length(basis_codes_bytes)>0),
        CHECK(length(request_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE TABLE editorial_relation_proposal_heads(
        proposal_id TEXT PRIMARY KEY
            REFERENCES editorial_relation_proposals(proposal_id),
        current_version_number INTEGER NOT NULL CHECK(current_version_number>0),
        current_proposal_version_id TEXT NOT NULL UNIQUE,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(proposal_id,current_version_number,current_proposal_version_id)
            REFERENCES editorial_relation_proposal_versions(
                proposal_id,version_number,proposal_version_id
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE editorial_relation_evidence_items(
        proposal_version_id TEXT NOT NULL
            REFERENCES editorial_relation_proposal_versions(proposal_version_id),
        evidence_ordinal INTEGER NOT NULL CHECK(evidence_ordinal>=0),
        evidence_kind TEXT NOT NULL CHECK(evidence_kind IN({_EVIDENCE_KINDS})),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        PRIMARY KEY(proposal_version_id,evidence_ordinal),
        UNIQUE(proposal_version_id,canonical_digest),
        CHECK(length(canonical_bytes)>0)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE editorial_relation_extraction_evidence(
        proposal_version_id TEXT NOT NULL,
        evidence_ordinal INTEGER NOT NULL,
        source_proposal_id TEXT NOT NULL
            REFERENCES extraction_proposals(proposal_id),
        source_evidence_ordinal INTEGER NOT NULL CHECK(source_evidence_ordinal>=0),
        source_proposal_digest TEXT NOT NULL,
        run_id TEXT NOT NULL REFERENCES extraction_runs(run_id),
        run_version_id TEXT NOT NULL,
        output_id TEXT NOT NULL,
        passage_id TEXT NOT NULL,
        start_byte INTEGER NOT NULL CHECK(start_byte>=0),
        end_byte INTEGER NOT NULL CHECK(end_byte>start_byte),
        evidence_text_digest TEXT NOT NULL,
        PRIMARY KEY(proposal_version_id,evidence_ordinal),
        FOREIGN KEY(proposal_version_id,evidence_ordinal)
            REFERENCES editorial_relation_evidence_items(
                proposal_version_id,evidence_ordinal
            ),
        FOREIGN KEY(source_proposal_id,source_evidence_ordinal)
            REFERENCES extraction_proposal_evidence(proposal_id,evidence_ordinal),
        FOREIGN KEY(run_version_id,run_id)
            REFERENCES extraction_run_versions(run_version_id,run_id),
        FOREIGN KEY(output_id)
            REFERENCES extraction_outputs(output_id),
        FOREIGN KEY(run_id,passage_id)
            REFERENCES extraction_run_passages(run_id,passage_id)
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE editorial_relation_workflow_evidence(
        proposal_version_id TEXT NOT NULL,
        evidence_ordinal INTEGER NOT NULL,
        authority_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        aggregate_version INTEGER NOT NULL CHECK(aggregate_version>0),
        event_digest TEXT NOT NULL,
        PRIMARY KEY(proposal_version_id,evidence_ordinal),
        FOREIGN KEY(proposal_version_id,evidence_ordinal)
            REFERENCES editorial_relation_evidence_items(
                proposal_version_id,evidence_ordinal
            )
    ) WITHOUT ROWID, STRICT""",
    """CREATE TABLE editorial_relation_resolution_dependencies(
        proposal_version_id TEXT NOT NULL
            REFERENCES editorial_relation_proposal_versions(proposal_version_id),
        dependency_ordinal INTEGER NOT NULL CHECK(dependency_ordinal>=0),
        dependency_id TEXT NOT NULL
            REFERENCES entity_resolution_dependencies(dependency_id),
        PRIMARY KEY(proposal_version_id,dependency_ordinal),
        UNIQUE(proposal_version_id,dependency_id)
    ) WITHOUT ROWID, STRICT""",
    f"""CREATE TABLE editorial_relation_decisions(
        decision_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL REFERENCES editorial_relation_proposals(proposal_id),
        proposal_version_id TEXT NOT NULL,
        proposal_version_digest TEXT NOT NULL,
        decision_version INTEGER NOT NULL CHECK(decision_version>0),
        previous_decision_id TEXT REFERENCES editorial_relation_decisions(decision_id),
        action TEXT NOT NULL CHECK(action IN({_DECISION_ACTIONS})),
        assertion_id TEXT REFERENCES editorial_relation_assertions(assertion_id)
            DEFERRABLE INITIALLY DEFERRED,
        target_assertion_id TEXT REFERENCES editorial_relation_assertions(assertion_id),
        successor_assertion_id TEXT REFERENCES editorial_relation_assertions(assertion_id),
        supersession_id TEXT REFERENCES editorial_relation_supersessions(supersession_id)
            DEFERRABLE INITIALLY DEFERRED,
        reason_code TEXT NOT NULL,
        decision_policy_version TEXT NOT NULL,
        authority_event_id TEXT NOT NULL UNIQUE REFERENCES ledger_events(event_id),
        authority_ledger_seq INTEGER NOT NULL UNIQUE CHECK(authority_ledger_seq>0),
        authority_aggregate_version INTEGER NOT NULL CHECK(authority_aggregate_version=1),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(proposal_id,decision_version),
        UNIQUE(decision_id,proposal_id),
        UNIQUE(proposal_id,decision_version,decision_id),
        FOREIGN KEY(proposal_version_id,proposal_id)
            REFERENCES editorial_relation_proposal_versions(
                proposal_version_id,proposal_id
            ),
        CHECK((decision_version=1 AND previous_decision_id IS NULL)
           OR (decision_version>1 AND previous_decision_id IS NOT NULL)),
        CHECK((action='ACCEPT' AND assertion_id IS NOT NULL
               AND target_assertion_id IS NULL AND successor_assertion_id IS NULL
               AND supersession_id IS NULL)
           OR (action IN('REJECT','HOLD','UNRESOLVED')
               AND assertion_id IS NULL AND target_assertion_id IS NULL
               AND successor_assertion_id IS NULL AND supersession_id IS NULL)
           OR (action IN('INVALIDATE','REVOKE')
               AND assertion_id IS NULL AND target_assertion_id IS NOT NULL
               AND successor_assertion_id IS NULL AND supersession_id IS NULL)
           OR (action='SUPERSEDE'
               AND assertion_id IS NULL AND target_assertion_id IS NOT NULL
               AND successor_assertion_id IS NOT NULL
               AND successor_assertion_id!=target_assertion_id
               AND supersession_id IS NOT NULL)),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE editorial_relation_decision_heads(
        proposal_id TEXT PRIMARY KEY REFERENCES editorial_relation_proposals(proposal_id),
        current_decision_version INTEGER NOT NULL CHECK(current_decision_version>0),
        current_decision_id TEXT NOT NULL UNIQUE,
        current_state TEXT NOT NULL CHECK(current_state IN({_CURRENT_STATES})),
        updated_at TEXT NOT NULL,
        FOREIGN KEY(proposal_id,current_decision_version,current_decision_id)
            REFERENCES editorial_relation_decisions(
                proposal_id,decision_version,decision_id
            ) DEFERRABLE INITIALLY DEFERRED
    ) STRICT""",
    f"""CREATE TABLE editorial_relation_assertions(
        assertion_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL UNIQUE
            REFERENCES editorial_relation_proposals(proposal_id),
        proposal_version_id TEXT NOT NULL UNIQUE,
        admission_decision_id TEXT NOT NULL UNIQUE
            REFERENCES editorial_relation_decisions(decision_id)
            DEFERRABLE INITIALLY DEFERRED,
        registry_version TEXT NOT NULL,
        predicate_registry_digest TEXT NOT NULL,
        predicate TEXT NOT NULL CHECK(predicate IN({_PREDICATES})),
        predicate_contract_version TEXT NOT NULL,
        predicate_contract_digest TEXT NOT NULL,
        subject_endpoint_digest TEXT NOT NULL
            REFERENCES editorial_relation_endpoints(endpoint_digest),
        object_endpoint_digest TEXT NOT NULL
            REFERENCES editorial_relation_endpoints(endpoint_digest),
        valid_from TEXT,
        valid_until TEXT,
        observed_at TEXT NOT NULL,
        producer_kind TEXT NOT NULL CHECK(producer_kind IN({_PRODUCER_KINDS})),
        producer_id TEXT NOT NULL,
        producer_version TEXT NOT NULL,
        producer_contract_digest TEXT NOT NULL,
        statement TEXT NOT NULL,
        uncertainty_codes_bytes BLOB NOT NULL,
        relation_key TEXT NOT NULL UNIQUE,
        trust_scope TEXT NOT NULL CHECK(trust_scope='ADMITTED'),
        proposal_version_digest TEXT NOT NULL,
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        admitted_at TEXT NOT NULL,
        FOREIGN KEY(proposal_version_id,proposal_id)
            REFERENCES editorial_relation_proposal_versions(
                proposal_version_id,proposal_id
            ),
        FOREIGN KEY(registry_version)
            REFERENCES editorial_predicate_registries(registry_version),
        FOREIGN KEY(predicate,predicate_contract_version)
            REFERENCES editorial_predicate_contracts(predicate,contract_version),
        CHECK(subject_endpoint_digest!=object_endpoint_digest),
        CHECK(valid_until IS NULL OR
              (valid_from IS NOT NULL AND valid_until>valid_from)),
        CHECK(length(statement)>0),
        CHECK(length(uncertainty_codes_bytes)>0),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE editorial_relation_assertion_heads(
        assertion_id TEXT PRIMARY KEY REFERENCES editorial_relation_assertions(assertion_id),
        lifecycle TEXT NOT NULL CHECK(lifecycle IN({_ASSERTION_LIFECYCLES})),
        current_decision_id TEXT NOT NULL UNIQUE
            REFERENCES editorial_relation_decisions(decision_id),
        current_decision_version INTEGER NOT NULL CHECK(current_decision_version>0),
        updated_at TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE editorial_relation_supersessions(
        supersession_id TEXT PRIMARY KEY,
        decision_id TEXT NOT NULL UNIQUE REFERENCES editorial_relation_decisions(decision_id),
        predecessor_assertion_id TEXT NOT NULL
            REFERENCES editorial_relation_assertions(assertion_id),
        successor_assertion_id TEXT NOT NULL
            REFERENCES editorial_relation_assertions(assertion_id),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(predecessor_assertion_id!=successor_assertion_id),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    f"""CREATE TABLE editorial_relation_projection_events(
        projection_event_id TEXT PRIMARY KEY,
        source_event_id TEXT NOT NULL REFERENCES ledger_events(event_id),
        source_ledger_seq INTEGER NOT NULL UNIQUE CHECK(source_ledger_seq>0),
        action TEXT NOT NULL CHECK(action IN({_PROJECTION_ACTIONS})),
        assertion_id TEXT NOT NULL REFERENCES editorial_relation_assertions(assertion_id),
        lifecycle TEXT NOT NULL CHECK(lifecycle IN({_ASSERTION_LIFECYCLES})),
        canonical_bytes BLOB NOT NULL,
        canonical_digest TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(source_event_id,assertion_id),
        CHECK((action='UPSERT' AND lifecycle='ACTIVE')
           OR (action='REMOVE' AND lifecycle!='ACTIVE')),
        CHECK(length(canonical_bytes)>0)
    ) STRICT""",
    """CREATE VIEW editorial_current_admitted_relations AS
        SELECT a.*,h.lifecycle,h.current_decision_id,
               h.current_decision_version,h.updated_at
        FROM editorial_relation_assertions AS a
        JOIN editorial_relation_assertion_heads AS h
          ON h.assertion_id=a.assertion_id
        WHERE h.lifecycle='ACTIVE'""",
    """CREATE INDEX idx_editorial_relation_proposal_slot
        ON editorial_relation_proposals(semantic_slot_digest,created_at)""",
    """CREATE INDEX idx_editorial_relation_version_proposal
        ON editorial_relation_proposal_versions(proposal_id,version_number)""",
    """CREATE INDEX idx_editorial_relation_decision_proposal
        ON editorial_relation_decisions(proposal_id,decision_version)""",
    """CREATE INDEX idx_editorial_relation_assertion_endpoints
        ON editorial_relation_assertions(
            predicate,subject_endpoint_digest,object_endpoint_digest
        )""",
    """CREATE INDEX idx_editorial_relation_projection_sequence
        ON editorial_relation_projection_events(source_ledger_seq,assertion_id)""",
    """CREATE TRIGGER editorial_story_candidate_endpoint_guard
        BEFORE INSERT ON editorial_relation_endpoints
        WHEN NEW.kind='STORY_CANDIDATE_VERSION' AND NOT EXISTS(
            SELECT 1 FROM story_candidate_versions
            WHERE candidate_version_id=NEW.candidate_version_id
              AND candidate_id=NEW.candidate_id
        )
        BEGIN SELECT RAISE(ABORT,'story candidate endpoint version mismatch'); END""",
    """CREATE TRIGGER editorial_relation_proposal_contract_guard
        BEFORE INSERT ON editorial_relation_proposals
        WHEN NOT EXISTS(
            SELECT 1
            FROM editorial_predicate_contracts AS c
            JOIN editorial_predicate_registries AS r
              ON r.registry_version=c.registry_version
            JOIN editorial_relation_endpoints AS s
              ON s.endpoint_digest=NEW.subject_endpoint_digest
            JOIN editorial_relation_endpoints AS o
              ON o.endpoint_digest=NEW.object_endpoint_digest
            JOIN editorial_predicate_endpoint_pairs AS p
              ON p.predicate=c.predicate
             AND p.contract_version=c.contract_version
             AND p.subject_kind=s.kind
             AND p.object_kind=o.kind
            WHERE c.predicate=NEW.predicate
              AND c.contract_version=NEW.predicate_contract_version
              AND c.canonical_digest=NEW.predicate_contract_digest
              AND r.registry_version=NEW.registry_version
              AND r.canonical_digest=NEW.predicate_registry_digest
        )
        BEGIN SELECT RAISE(ABORT,'editorial relation predicate contract mismatch'); END""",
    """CREATE TRIGGER editorial_relation_proposal_version_chain_guard
        BEFORE INSERT ON editorial_relation_proposal_versions
        WHEN (NEW.version_number=1 AND NEW.previous_proposal_version_id IS NOT NULL)
          OR (NEW.version_number>1 AND NOT EXISTS(
              SELECT 1 FROM editorial_relation_proposal_versions
              WHERE proposal_version_id=NEW.previous_proposal_version_id
                AND proposal_id=NEW.proposal_id
                AND version_number=NEW.version_number-1
          ))
        BEGIN SELECT RAISE(ABORT,'invalid editorial relation proposal version chain'); END""",
    """CREATE TRIGGER editorial_relation_proposal_head_insert_guard
        BEFORE INSERT ON editorial_relation_proposal_heads
        WHEN NEW.current_version_number!=1
        BEGIN SELECT RAISE(ABORT,'editorial relation proposal heads begin at one'); END""",
    """CREATE TRIGGER editorial_relation_proposal_head_update_guard
        BEFORE UPDATE ON editorial_relation_proposal_heads
        WHEN NEW.proposal_id!=OLD.proposal_id
          OR NEW.current_version_number!=OLD.current_version_number+1
        BEGIN SELECT RAISE(ABORT,'invalid editorial relation proposal head advance'); END""",
    """CREATE TRIGGER editorial_relation_decision_chain_guard
        BEFORE INSERT ON editorial_relation_decisions
        WHEN (NEW.decision_version=1 AND NEW.previous_decision_id IS NOT NULL)
          OR (NEW.decision_version>1 AND NOT EXISTS(
              SELECT 1 FROM editorial_relation_decisions
              WHERE decision_id=NEW.previous_decision_id
                AND proposal_id=NEW.proposal_id
                AND decision_version=NEW.decision_version-1
          ))
        BEGIN SELECT RAISE(ABORT,'invalid editorial relation decision chain'); END""",
    """CREATE TRIGGER editorial_relation_decision_head_insert_guard
        BEFORE INSERT ON editorial_relation_decision_heads
        WHEN NEW.current_decision_version!=1
        BEGIN SELECT RAISE(ABORT,'editorial relation decision heads begin at one'); END""",
    """CREATE TRIGGER editorial_relation_decision_head_update_guard
        BEFORE UPDATE ON editorial_relation_decision_heads
        WHEN NEW.proposal_id!=OLD.proposal_id
          OR NEW.current_decision_version!=OLD.current_decision_version+1
        BEGIN SELECT RAISE(ABORT,'invalid editorial relation decision head advance'); END""",
    """CREATE TRIGGER editorial_relation_assertion_admission_guard
        BEFORE INSERT ON editorial_relation_assertions
        WHEN NOT EXISTS(
            SELECT 1 FROM editorial_relation_decisions AS d
            WHERE d.decision_id=NEW.admission_decision_id
              AND d.proposal_id=NEW.proposal_id
              AND d.proposal_version_id=NEW.proposal_version_id
              AND d.assertion_id=NEW.assertion_id
              AND d.action='ACCEPT'
        )
        BEGIN SELECT RAISE(ABORT,'relation assertion lacks exact accept decision'); END""",
    """CREATE TRIGGER editorial_relation_assertion_head_update_guard
        BEFORE UPDATE ON editorial_relation_assertion_heads
        WHEN NEW.assertion_id!=OLD.assertion_id
          OR NEW.current_decision_version!=OLD.current_decision_version+1
          OR OLD.lifecycle!='ACTIVE'
          OR NEW.lifecycle='ACTIVE'
        BEGIN SELECT RAISE(ABORT,'invalid editorial relation lifecycle advance'); END""",
    """CREATE TRIGGER editorial_relation_supersession_guard
        BEFORE INSERT ON editorial_relation_supersessions
        WHEN NOT EXISTS(
            SELECT 1 FROM editorial_relation_decisions
            WHERE decision_id=NEW.decision_id
              AND action='SUPERSEDE'
              AND target_assertion_id=NEW.predecessor_assertion_id
              AND successor_assertion_id=NEW.successor_assertion_id
              AND supersession_id=NEW.supersession_id
        )
        BEGIN SELECT RAISE(ABORT,'relation supersession lacks exact decision'); END""",
    """CREATE TRIGGER editorial_relation_projection_event_guard
        BEFORE INSERT ON editorial_relation_projection_events
        WHEN NOT EXISTS(
            SELECT 1 FROM editorial_relation_assertion_heads AS h
            JOIN editorial_relation_decisions AS d
              ON d.decision_id=h.current_decision_id
            WHERE h.assertion_id=NEW.assertion_id
              AND h.lifecycle=NEW.lifecycle
              AND d.authority_event_id=NEW.source_event_id
              AND d.authority_ledger_seq=NEW.source_ledger_seq
        )
        BEGIN SELECT RAISE(ABORT,'relation projection event differs from authority head'); END""",
    """CREATE TRIGGER editorial_extraction_evidence_kind_guard
        BEFORE INSERT ON editorial_relation_extraction_evidence
        WHEN NOT EXISTS(
            SELECT 1 FROM editorial_relation_evidence_items
            WHERE proposal_version_id=NEW.proposal_version_id
              AND evidence_ordinal=NEW.evidence_ordinal
              AND evidence_kind='EXTRACTION_PROPOSAL'
        )
        BEGIN SELECT RAISE(ABORT,'relation extraction evidence kind mismatch'); END""",
    """CREATE TRIGGER editorial_workflow_evidence_kind_guard
        BEFORE INSERT ON editorial_relation_workflow_evidence
        WHEN NOT EXISTS(
            SELECT 1 FROM editorial_relation_evidence_items
            WHERE proposal_version_id=NEW.proposal_version_id
              AND evidence_ordinal=NEW.evidence_ordinal
              AND evidence_kind='WORKFLOW_EVENT'
        )
        BEGIN SELECT RAISE(ABORT,'relation workflow evidence kind mismatch'); END""",
    *tuple(
        statement
        for table in (
            "editorial_predicate_registries",
            "editorial_predicate_contracts",
            "editorial_predicate_endpoint_pairs",
            "editorial_relation_endpoints",
            "editorial_relation_proposals",
            "editorial_relation_proposal_versions",
            "editorial_relation_evidence_items",
            "editorial_relation_extraction_evidence",
            "editorial_relation_workflow_evidence",
            "editorial_relation_resolution_dependencies",
            "editorial_relation_decisions",
            "editorial_relation_assertions",
            "editorial_relation_supersessions",
            "editorial_relation_projection_events",
        )
        for statement in (
            f"CREATE TRIGGER immutable_{table}_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT,'immutable {table}'); END",
            f"CREATE TRIGGER immutable_{table}_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT,'retained {table}'); END",
        )
    ),
    """CREATE TRIGGER editorial_relation_proposal_head_delete_guard
        BEFORE DELETE ON editorial_relation_proposal_heads
        BEGIN SELECT RAISE(ABORT,'relation proposal heads are retained'); END""",
    """CREATE TRIGGER editorial_relation_decision_head_delete_guard
        BEFORE DELETE ON editorial_relation_decision_heads
        BEGIN SELECT RAISE(ABORT,'relation decision heads are retained'); END""",
    """CREATE TRIGGER editorial_relation_assertion_head_delete_guard
        BEFORE DELETE ON editorial_relation_assertion_heads
        BEGIN SELECT RAISE(ABORT,'relation assertion heads are retained'); END""",
)


EDITORIAL_RELATION_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": EDITORIAL_RELATION_SCHEMA_VERSION,
        "name": EDITORIAL_RELATION_MIGRATION_NAME,
        "statements": list(EDITORIAL_RELATION_MIGRATION_STATEMENTS),
    }
)
EDITORIAL_RELATION_MIGRATION = EditorialRelationMigrationRecord(
    version=EDITORIAL_RELATION_SCHEMA_VERSION,
    name=EDITORIAL_RELATION_MIGRATION_NAME,
    checksum=EDITORIAL_RELATION_MIGRATION_CHECKSUM,
)


__all__ = [
    "EDITORIAL_PREDICATE_CONTRACT_VERSION",
    "EDITORIAL_PREDICATE_REGISTRY_CANONICAL_BYTES",
    "EDITORIAL_PREDICATE_REGISTRY_DIGEST",
    "EDITORIAL_PREDICATE_REGISTRY_VERSION",
    "EDITORIAL_RELATION_ADMISSION_POLICY_VERSION",
    "EDITORIAL_RELATION_MIGRATION",
    "EDITORIAL_RELATION_MIGRATION_CHECKSUM",
    "EDITORIAL_RELATION_MIGRATION_NAME",
    "EDITORIAL_RELATION_MIGRATION_STATEMENTS",
    "EDITORIAL_RELATION_SCHEMA_VERSION",
]
