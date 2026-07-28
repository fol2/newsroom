from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority.check_migrations import (
    CHECK_AUTHORITY_MIGRATION_CHECKSUM,
    CHECK_AUTHORITY_MIGRATION_NAME,
    CHECK_AUTHORITY_MIGRATION_STATEMENTS,
    CHECK_AUTHORITY_SCHEMA_VERSION,
)
from newsroom.authority.complete_projection_migrations import (
    COMPLETE_PROJECTION_MIGRATION_CHECKSUM,
    COMPLETE_PROJECTION_MIGRATION_NAME,
    COMPLETE_PROJECTION_MIGRATION_STATEMENTS,
    COMPLETE_PROJECTION_SCHEMA_VERSION,
)
from newsroom.authority.development_candidate_migrations import (
    DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM,
    DEVELOPMENT_CANDIDATE_MIGRATION_NAME,
    DEVELOPMENT_CANDIDATE_MIGRATION_STATEMENTS,
    DEVELOPMENT_CANDIDATE_SCHEMA_VERSION,
)
from newsroom.authority.discovery_migrations import (
    DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM,
    DISCOVERY_AUTHORITY_MIGRATION_NAME,
    DISCOVERY_AUTHORITY_SCHEMA_VERSION,
)
from newsroom.authority.integrated_migrations import (
    INTEGRATED_FOUNDATION_MIGRATION_CHECKSUM,
    INTEGRATED_FOUNDATION_MIGRATION_NAME,
    INTEGRATED_FOUNDATION_MIGRATION_STATEMENTS,
    INTEGRATED_FOUNDATION_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    BASE_SCHEMA_VERSION,
    EXPECTED_MIGRATION_HISTORY,
    MIGRATION_CHECKSUM,
    MIGRATION_NAME,
    MIGRATION_STATEMENTS,
    SCHEMA_VERSION,
)
from newsroom.authority.object_migrations import (
    OBJECT_MIGRATION_CHECKSUM,
    OBJECT_MIGRATION_NAME,
    OBJECT_MIGRATION_STATEMENTS,
    OBJECT_SCHEMA_VERSION,
)
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.authority.projection_migrations import (
    PROJECTION_MIGRATION_CHECKSUM,
    PROJECTION_MIGRATION_NAME,
    PROJECTION_MIGRATION_STATEMENTS,
    PROJECTION_SCHEMA_VERSION,
)
from newsroom.authority.projection_promotion_migrations import (
    PROJECTION_PROMOTION_MIGRATION_CHECKSUM,
    PROJECTION_PROMOTION_MIGRATION_NAME,
    PROJECTION_PROMOTION_MIGRATION_STATEMENTS,
    PROJECTION_PROMOTION_SCHEMA_VERSION,
)
from newsroom.authority.relation_migrations import (
    RELATION_MIGRATION_CHECKSUM,
    RELATION_MIGRATION_NAME,
    RELATION_MIGRATION_STATEMENTS,
    RELATION_SCHEMA_VERSION,
)
from newsroom.authority.retrieval_migrations import (
    HYBRID_RETRIEVAL_MIGRATION_CHECKSUM,
    HYBRID_RETRIEVAL_MIGRATION_NAME,
    HYBRID_RETRIEVAL_MIGRATION_STATEMENTS,
    HYBRID_RETRIEVAL_SCHEMA_VERSION,
)
from newsroom.authority.source_registry_migrations import (
    SOURCE_REGISTRY_MIGRATION_CHECKSUM,
    SOURCE_REGISTRY_MIGRATION_NAME,
    SOURCE_REGISTRY_MIGRATION_STATEMENTS,
    SOURCE_REGISTRY_SCHEMA_VERSION,
)

from .source_3a_helpers import open_source_system

from .check_3c_authority_helpers import (
    OCCURRENCE_ID,
    definition_request,
    item_request,
    occurrence_request,
    open_check_system,
    proof,
    representation_request,
    revision_request,
    version_request,
)
from .check_3c_helpers import (
    DEFINITION_ID,
    ITEM_ID,
    OUTCOME_ID,
    REPRESENTATION_ID,
    REVISION_ID,
    TRANSITION_ID,
    VERSION_ID,
    check_attempt,
    check_request,
    changed_outcome,
    first_transition,
)


DISCOVERY_TABLES = frozenset(
    {
        "discovery_signals",
        "discovery_signal_findings",
        "discovery_gate_decisions",
        "discovery_gate_decision_heads",
        "news_leads",
        "discovery_watch_conditions",
        "lead_disposition_decisions",
        "lead_disposition_heads",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "discovery_signal_lineage_guard",
        "gate_decision_source_contract_guard",
        "gate_decision_predecessor_guard",
        "gate_decision_create_head",
        "gate_decision_advance_head",
        "news_lead_promotion_guard",
        "watch_condition_chronology_guard",
        "lead_disposition_predecessor_guard",
        "lead_disposition_chronology_guard",
        "lead_disposition_create_head",
        "lead_disposition_advance_head",
        "immutable_discovery_signals_update",
        "immutable_discovery_gate_decisions_delete",
        "immutable_news_leads_update",
        "immutable_discovery_watch_conditions_delete",
        "immutable_lead_dispositions_update",
    }
)


def _create_v11_database(path) -> None:
    migrations = (
        (
            BASE_SCHEMA_VERSION,
            MIGRATION_NAME,
            MIGRATION_CHECKSUM,
            MIGRATION_STATEMENTS,
        ),
        (
            OBJECT_SCHEMA_VERSION,
            OBJECT_MIGRATION_NAME,
            OBJECT_MIGRATION_CHECKSUM,
            OBJECT_MIGRATION_STATEMENTS,
        ),
        (
            PROJECTION_SCHEMA_VERSION,
            PROJECTION_MIGRATION_NAME,
            PROJECTION_MIGRATION_CHECKSUM,
            PROJECTION_MIGRATION_STATEMENTS,
        ),
        (
            PROJECTION_PROMOTION_SCHEMA_VERSION,
            PROJECTION_PROMOTION_MIGRATION_NAME,
            PROJECTION_PROMOTION_MIGRATION_CHECKSUM,
            PROJECTION_PROMOTION_MIGRATION_STATEMENTS,
        ),
        (
            INTEGRATED_FOUNDATION_SCHEMA_VERSION,
            INTEGRATED_FOUNDATION_MIGRATION_NAME,
            INTEGRATED_FOUNDATION_MIGRATION_CHECKSUM,
            INTEGRATED_FOUNDATION_MIGRATION_STATEMENTS,
        ),
        (
            RELATION_SCHEMA_VERSION,
            RELATION_MIGRATION_NAME,
            RELATION_MIGRATION_CHECKSUM,
            RELATION_MIGRATION_STATEMENTS,
        ),
        (
            COMPLETE_PROJECTION_SCHEMA_VERSION,
            COMPLETE_PROJECTION_MIGRATION_NAME,
            COMPLETE_PROJECTION_MIGRATION_CHECKSUM,
            COMPLETE_PROJECTION_MIGRATION_STATEMENTS,
        ),
        (
            HYBRID_RETRIEVAL_SCHEMA_VERSION,
            HYBRID_RETRIEVAL_MIGRATION_NAME,
            HYBRID_RETRIEVAL_MIGRATION_CHECKSUM,
            HYBRID_RETRIEVAL_MIGRATION_STATEMENTS,
        ),
        (
            DEVELOPMENT_CANDIDATE_SCHEMA_VERSION,
            DEVELOPMENT_CANDIDATE_MIGRATION_NAME,
            DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM,
            DEVELOPMENT_CANDIDATE_MIGRATION_STATEMENTS,
        ),
        (
            SOURCE_REGISTRY_SCHEMA_VERSION,
            SOURCE_REGISTRY_MIGRATION_NAME,
            SOURCE_REGISTRY_MIGRATION_CHECKSUM,
            SOURCE_REGISTRY_MIGRATION_STATEMENTS,
        ),
        (
            CHECK_AUTHORITY_SCHEMA_VERSION,
            CHECK_AUTHORITY_MIGRATION_NAME,
            CHECK_AUTHORITY_MIGRATION_CHECKSUM,
            CHECK_AUTHORITY_MIGRATION_STATEMENTS,
        ),
    )
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN EXCLUSIVE")
        for version, name, checksum, statements in migrations:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO authority_migrations("
                "version,name,checksum,applied_at) VALUES(?,?,?,?)",
                (version, name, checksum, "2042-03-12T10:00:00.000000Z"),
            )
        conn.execute(f"PRAGMA user_version={CHECK_AUTHORITY_SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    path.chmod(0o600)


def test_checked_v12_migration_creates_and_reopens_exact_schema(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    open_source_system(database).close()

    conn = sqlite3.connect(database)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == (
            DISCOVERY_AUTHORITY_SCHEMA_VERSION
        )
        assert SCHEMA_VERSION == DISCOVERY_AUTHORITY_SCHEMA_VERSION
        row = conn.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=?",
            (DISCOVERY_AUTHORITY_SCHEMA_VERSION,),
        ).fetchone()
        assert row == (
            DISCOVERY_AUTHORITY_MIGRATION_NAME,
            DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM,
        )
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        triggers = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert DISCOVERY_TABLES <= tables
        assert REQUIRED_TRIGGERS <= triggers
    finally:
        conn.close()

    assert EXPECTED_MIGRATION_HISTORY[-1] == (
        DISCOVERY_AUTHORITY_SCHEMA_VERSION,
        DISCOVERY_AUTHORITY_MIGRATION_NAME,
        DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM,
    )
    open_source_system(database).close()


def test_checked_v11_database_upgrades_to_v12_without_rewriting_history(
    tmp_path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    _create_v11_database(database)

    conn = sqlite3.connect(database)
    try:
        before = conn.execute(
            "SELECT version,name,checksum,applied_at FROM authority_migrations "
            "ORDER BY version"
        ).fetchall()
        assert before[-1][:3] == (
            CHECK_AUTHORITY_SCHEMA_VERSION,
            CHECK_AUTHORITY_MIGRATION_NAME,
            CHECK_AUTHORITY_MIGRATION_CHECKSUM,
        )
    finally:
        conn.close()

    open_source_system(database).close()

    conn = sqlite3.connect(database)
    try:
        after = conn.execute(
            "SELECT version,name,checksum,applied_at FROM authority_migrations "
            "ORDER BY version"
        ).fetchall()
        assert after[:-1] == before
        assert after[-1][:3] == (
            DISCOVERY_AUTHORITY_SCHEMA_VERSION,
            DISCOVERY_AUTHORITY_MIGRATION_NAME,
            DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM,
        )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == (
            DISCOVERY_AUTHORITY_SCHEMA_VERSION
        )
    finally:
        conn.close()


def test_startup_rejects_v12_migration_history_tampering(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    open_source_system(database).close()

    conn = sqlite3.connect(database)
    try:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
            ("immutable_authority_migrations_update",),
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_update")
        conn.execute(
            "UPDATE authority_migrations SET checksum=? WHERE version=?",
            ("sha256:" + "0" * 64, DISCOVERY_AUTHORITY_SCHEMA_VERSION),
        )
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthoritySchemaError, match="migration history"):
        open_source_system(database)



def _seed_signal_lineage(database) -> None:
    with open_check_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(changed_outcome(), proof=proof())
        system.sources.register_item(item_request(), proof=proof())
        system.sources.record_revision(revision_request(), proof=proof())
        system.sources.record_representation(
            representation_request(), proof=proof()
        )
        system.sources.record_occurrence(occurrence_request(), proof=proof())
        system.checks.record_transition(first_transition(), proof=proof())


def _event_id(conn: sqlite3.Connection, table: str) -> str:
    value = conn.execute(
        f"SELECT authority_event_id FROM {table} LIMIT 1"
    ).fetchone()
    assert value is not None
    return str(value[0])


def _insert_signal(
    conn: sqlite3.Connection,
    *,
    signal_id: str,
    purpose: str,
    discriminator: str,
    authority_event_id: str,
) -> None:
    conn.execute(
        """INSERT INTO discovery_signals(
            signal_id,definition_id,definition_version_id,item_id,revision_id,
            representation_id,check_outcome_id,occurrence_id,transition_id,
            purpose,discriminator,admission_policy_id,admission_policy_version,
            incomplete,operational_finding_ids_bytes,operational_finding_count,
            admitted_at,semantic_digest,authority_event_id,
            authority_aggregate_version,canonical_bytes,canonical_digest,recorded_at
        ) VALUES(
            :signal_id,:definition_id,:definition_version_id,:item_id,:revision_id,
            :representation_id,:check_outcome_id,:occurrence_id,:transition_id,
            :purpose,:discriminator,'fixture-signal','v1',0,x'5b5d',0,
            '2042-03-12T10:00:02.000000Z',:semantic_digest,:authority_event_id,
            1,x'7b7d',:canonical_digest,'2042-03-12T10:00:02.000000Z'
        )""",
        {
            "signal_id": signal_id,
            "definition_id": str(DEFINITION_ID),
            "definition_version_id": str(VERSION_ID),
            "item_id": str(ITEM_ID),
            "revision_id": str(REVISION_ID),
            "representation_id": str(REPRESENTATION_ID),
            "check_outcome_id": str(OUTCOME_ID),
            "occurrence_id": str(OCCURRENCE_ID),
            "transition_id": str(TRANSITION_ID),
            "purpose": purpose,
            "discriminator": discriminator,
            "semantic_digest": f"semantic-{signal_id}",
            "authority_event_id": authority_event_id,
            "canonical_digest": f"canonical-{signal_id}",
        },
    )


def _insert_gate(
    conn: sqlite3.Connection,
    *,
    decision_id: str,
    signal_id: str,
    authority_event_id: str,
    outcome: str = "SIGNAL_PROMOTED_TO_LEAD",
    policy_current: int = 1,
) -> None:
    conn.execute(
        """INSERT INTO discovery_gate_decisions(
            decision_id,signal_id,decision_ordinal,previous_decision_id,
            evaluated_definition_version_id,coverage_obligation_id,
            coverage_responsibility,coverage_contribution,coverage_policy_id,
            coverage_policy_version,rights_decision_id,rights_policy_version,
            signal_admission_policy_id,signal_admission_policy_version,
            gate_policy_id,gate_policy_version,duplicate_policy_id,
            duplicate_policy_version,newness_policy_id,newness_policy_version,
            time_validity_policy_id,time_validity_policy_version,
            exclusion_policy_id,exclusion_policy_version,identity_integrity,
            duplicate_signal_id,duplicate_rule_id,duplicate_rule_version,
            observable_newness,time_validity,scope_disposition,
            clear_exclusion_rule_id,clear_exclusion_rule_version,rights_current,
            policy_current,operationally_executable,ambiguities_bytes,
            ambiguity_count,outcome,terminality,primary_reason_bytes,
            supporting_reasons_bytes,supporting_reason_count,
            reason_taxonomy_version,outcome_taxonomy_version,next_action_kind,
            next_action_code,next_action_bytes,decided_at,semantic_digest,
            authority_event_id,authority_aggregate_version,canonical_bytes,
            canonical_digest,recorded_at
        ) VALUES(
            :decision_id,:signal_id,1,NULL,:version_id,'COV-021','ACTIVE',
            'REVISION_VISIBILITY','fixture-coverage','v1',
            '00000000-0000-4000-8000-000000006099','fixture-rights-v1',
            'fixture-signal','v1','fixture-gate','v1','fixture-duplicate','v1',
            'fixture-newness','v1','fixture-time','v1','fixture-exclusion','v1',
            1,NULL,NULL,NULL,'GENUINE_TRANSITION','CURRENT','ACCEPTED',NULL,NULL,
            1,:policy_current,1,x'5b5d',0,:outcome,'TERMINAL_EXACT_VERSION',
            x'7b7d',x'5b5d',0,'fixture-reasons-v1','fixture-outcomes-v1',
            'QUEUE_TRIAGE','QUEUE_FOR_TRIAGE',x'7b7d',
            '2042-03-12T10:00:03.000000Z',:semantic_digest,:authority_event_id,
            1,x'7b7d',:canonical_digest,'2042-03-12T10:00:03.000000Z'
        )""",
        {
            "decision_id": decision_id,
            "signal_id": signal_id,
            "version_id": str(VERSION_ID),
            "policy_current": policy_current,
            "outcome": outcome,
            "semantic_digest": f"semantic-{decision_id}",
            "authority_event_id": authority_event_id,
            "canonical_digest": f"canonical-{decision_id}",
        },
    )


def _insert_lead(
    conn: sqlite3.Connection,
    *,
    lead_id: str,
    signal_id: str,
    decision_id: str,
    authority_event_id: str,
) -> None:
    conn.execute(
        """INSERT INTO news_leads(
            lead_id,signal_id,promoting_gate_decision_id,definition_id,
            definition_version_id,item_id,revision_id,representation_id,
            occurrence_id,transition_id,transition_kind,coverage_obligation_id,
            coverage_responsibility,coverage_contribution,coverage_policy_id,
            coverage_policy_version,source_roles_bytes,source_role_count,
            portfolio_functions_bytes,portfolio_function_count,
            source_dependencies_bytes,source_dependency_count,
            incompleteness_warnings_bytes,incompleteness_warning_count,
            urgency_bytes,urgency_route,urgency_hard_deadline,
            urgency_planned_window,urgency_isolation_required,lead_policy_id,
            lead_policy_version,reason_taxonomy_version,outcome_taxonomy_version,
            created_at,semantic_digest,authority_event_id,
            authority_aggregate_version,canonical_bytes,canonical_digest,recorded_at
        ) VALUES(
            :lead_id,:signal_id,:decision_id,:definition_id,:version_id,:item_id,
            :revision_id,:representation_id,:occurrence_id,:transition_id,
            'FIRST_OBSERVED','COV-021','ACTIVE','REVISION_VISIBILITY',
            'fixture-coverage','v1',x'5b5d',1,x'5b5d',1,x'5b5d',0,x'5b5d',0,
            x'7b7d','ROUTINE',NULL,NULL,0,'fixture-lead','v1',
            'fixture-reasons-v1','fixture-outcomes-v1',
            '2042-03-12T10:00:04.000000Z',:semantic_digest,:authority_event_id,
            1,x'7b7d',:canonical_digest,'2042-03-12T10:00:04.000000Z'
        )""",
        {
            "lead_id": lead_id,
            "signal_id": signal_id,
            "decision_id": decision_id,
            "definition_id": str(DEFINITION_ID),
            "version_id": str(VERSION_ID),
            "item_id": str(ITEM_ID),
            "revision_id": str(REVISION_ID),
            "representation_id": str(REPRESENTATION_ID),
            "occurrence_id": str(OCCURRENCE_ID),
            "transition_id": str(TRANSITION_ID),
            "semantic_digest": f"semantic-{lead_id}",
            "authority_event_id": authority_event_id,
            "canonical_digest": f"canonical-{lead_id}",
        },
    )


def test_v12_allows_several_deterministic_signals_from_one_occurrence(
    tmp_path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    _seed_signal_lineage(database)

    conn = sqlite3.connect(database)
    try:
        _insert_signal(
            conn,
            signal_id="00000000-0000-4000-8000-000000007001",
            purpose="source-change",
            discriminator="primary",
            authority_event_id=_event_id(conn, "observable_transitions"),
        )
        _insert_signal(
            conn,
            signal_id="00000000-0000-4000-8000-000000007002",
            purpose="source-change-followup",
            discriminator="secondary",
            authority_event_id=_event_id(conn, "discovery_occurrences"),
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_signals WHERE occurrence_id=?",
            (str(OCCURRENCE_ID),),
        ).fetchone() == (2,)
    finally:
        conn.close()


def test_v12_gate_lead_watch_and_disposition_guards_fail_closed(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    _seed_signal_lineage(database)

    signal_id = "00000000-0000-4000-8000-000000007011"
    decision_id = "00000000-0000-4000-8000-000000007012"
    lead_id = "00000000-0000-4000-8000-000000007013"
    conn = sqlite3.connect(database)
    try:
        _insert_signal(
            conn,
            signal_id=signal_id,
            purpose="source-change",
            discriminator="primary",
            authority_event_id=_event_id(conn, "observable_transitions"),
        )
        with pytest.raises(sqlite3.IntegrityError, match="outcome contract"):
            _insert_gate(
                conn,
                decision_id=decision_id,
                signal_id=signal_id,
                authority_event_id=_event_id(conn, "check_outcomes"),
                policy_current=0,
            )
        _insert_gate(
            conn,
            decision_id=decision_id,
            signal_id=signal_id,
            authority_event_id=_event_id(conn, "observable_transitions"),
        )
        _insert_lead(
            conn,
            lead_id=lead_id,
            signal_id=signal_id,
            decision_id=decision_id,
            authority_event_id=_event_id(conn, "source_revisions"),
        )

        with pytest.raises(sqlite3.IntegrityError, match="Watch Condition"):
            conn.execute(
                """INSERT INTO discovery_watch_conditions(
                    watch_condition_id,lead_id,gate_decision_id,resume_transition_kinds_bytes,
                    resume_transition_kind_count,expected_occurrence,
                    corroborating_lead_id,review_at,expires_at,
                    operator_review_condition,closure_rule,watch_policy_id,
                    watch_policy_version,condition_recorded_at,semantic_digest,
                    authority_event_id,authority_aggregate_version,canonical_bytes,
                    canonical_digest,recorded_at
                ) VALUES(
                    '00000000-0000-4000-8000-000000007014',:lead_id,:gate_id,x'5b5d',0,
                    'Later fixture transition',NULL,
                    '2042-03-12T10:00:06.000000Z',NULL,NULL,'CLOSE_ON_REVIEW',
                    'fixture-watch','v1','2042-03-12T10:00:00.000000Z',
                    'semantic-watch',:event_id,1,x'7b7d','canonical-watch',
                    '2042-03-12T10:00:05.000000Z'
                )""",
                {
                    "lead_id": lead_id,
                    "gate_id": decision_id,
                    "event_id": _event_id(conn, "check_attempts"),
                },
            )

        with pytest.raises(sqlite3.IntegrityError, match="Lead/Gate mismatch"):
            conn.execute(
                """INSERT INTO lead_disposition_decisions(
                    decision_id,lead_id,gate_decision_id,decision_ordinal,previous_decision_id,
                    outcome,terminality,primary_reason_bytes,
                    supporting_reasons_bytes,supporting_reason_count,
                    watch_condition_id,next_action_kind,next_action_code,
                    next_action_bytes,urgency_bytes,urgency_route,
                    disposition_policy_id,disposition_policy_version,
                    reason_taxonomy_version,outcome_taxonomy_version,decided_at,
                    semantic_digest,authority_event_id,authority_aggregate_version,
                    canonical_bytes,canonical_digest,recorded_at
                ) VALUES(
                    '00000000-0000-4000-8000-000000007015',:lead_id,:gate_id,1,NULL,
                    'LEAD_QUEUED_FOR_TRIAGE','PENDING_CONDITION',x'7b7d',x'5b5d',0,
                    NULL,'QUEUE_TRIAGE','QUEUE_FOR_TRIAGE',x'7b7d',x'7b7d','URGENT',
                    'fixture-disposition','v1','fixture-reasons-v1',
                    'fixture-outcomes-v1','2042-03-12T10:00:05.000000Z',
                    'semantic-disposition',:event_id,1,x'7b7d',
                    'canonical-disposition','2042-03-12T10:00:05.000000Z'
                )""",
                {
                    "lead_id": lead_id,
                    "gate_id": decision_id,
                    "event_id": _event_id(conn, "check_outcomes"),
                },
            )
    finally:
        conn.close()
