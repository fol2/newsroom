from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.entity_migrations import (
    ENTITY_AUTHORITY_MIGRATION_CHECKSUM,
    ENTITY_AUTHORITY_MIGRATION_NAME,
    ENTITY_AUTHORITY_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.authority.extraction_system import (
    open_governed_extraction_authority_system,
)

from .extraction_4a_helpers import open_extraction_system, seed_extraction_fixture


ENTITY_TABLES = {
    "canonical_entities",
    "canonical_entity_heads",
    "canonical_entity_versions",
    "entity_aliases",
    "entity_mention_resolutions",
    "entity_mentions",
    "entity_merge_decisions",
    "entity_merge_predecessors",
    "entity_preferred_identities",
    "entity_projection_events",
    "entity_resolution_decision_heads",
    "entity_resolution_decisions",
    "entity_resolution_dependencies",
    "entity_resolution_proposal_heads",
    "entity_resolution_proposal_versions",
    "entity_resolution_proposals",
    "entity_reversal_decisions",
    "entity_reversal_expected_versions",
    "entity_reversal_restorations",
    "entity_reversal_supersessions",
    "entity_split_allocations",
    "entity_split_decisions",
    "entity_split_successors",
}

REQUIRED_ENTITY_TRIGGERS = {
    "entity_mention_lineage_guard",
    "immutable_entity_mention_update",
    "immutable_entity_mention_delete",
    "entity_resolution_proposal_lineage_guard",
    "entity_resolution_proposal_version_chain_guard",
    "entity_resolution_decision_chain_guard",
    "entity_resolution_decision_target_guard",
    "canonical_entity_creation_guard",
    "canonical_entity_version_chain_guard",
    "entity_alias_lineage_guard",
    "entity_mention_resolution_guard",
    "entity_split_allocation_guard",
    "entity_reversal_target_guard",
    "entity_resolution_dependency_guard",
    "entity_preferred_identity_update_guard",
    "immutable_entity_projection_event_update",
}


def _drop_empty_entity_schema_to_v13(database: Path) -> None:
    conn = sqlite3.connect(database, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        delete_trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_authority_migrations_delete'"
        ).fetchone()
        assert delete_trigger is not None and delete_trigger[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_delete")
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' "
            "AND name LIKE 'entity_%'"
        ).fetchall():
            conn.execute(f'DROP VIEW "{row[0]}"')
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND (name LIKE '%entity%' OR tbl_name LIKE 'entity_%' "
            "OR tbl_name LIKE 'canonical_entit%')"
        ).fetchall():
            conn.execute(f'DROP TRIGGER "{row[0]}"')
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND (name LIKE 'entity_%' OR name LIKE 'canonical_entit%')"
        ).fetchall():
            conn.execute(f'DROP TABLE "{row[0]}"')
        conn.execute(
            "DELETE FROM authority_migrations WHERE version=?",
            (ENTITY_AUTHORITY_SCHEMA_VERSION,),
        )
        conn.execute(str(delete_trigger[0]))
        conn.execute("PRAGMA user_version=13")
    finally:
        conn.close()


def test_fresh_schema_v14_history_fingerprint_tables_and_view_are_exact(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        assert SCHEMA_VERSION == ENTITY_AUTHORITY_SCHEMA_VERSION == 14
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 14
        assert schema_fingerprint(conn) == EXPECTED_SCHEMA_FINGERPRINT
        assert conn.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=?",
            (ENTITY_AUTHORITY_SCHEMA_VERSION,),
        ).fetchone() == (
            ENTITY_AUTHORITY_MIGRATION_NAME,
            ENTITY_AUTHORITY_MIGRATION_CHECKSUM,
        )
        assert conn.execute(
            "SELECT version,name,checksum FROM authority_migrations "
            "ORDER BY version"
        ).fetchall() == list(EXPECTED_MIGRATION_HISTORY)
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE 'entity_%' OR name LIKE 'canonical_entit%')"
            ).fetchall()
        }
        assert tables == ENTITY_TABLES
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' "
            "AND name='entity_dependent_admission_guard'"
        ).fetchone() == ("entity_dependent_admission_guard",)
        triggers = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert REQUIRED_ENTITY_TRIGGERS <= triggers
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_checked_v13_to_v14_upgrade_preserves_extraction_authority(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    before = sqlite3.connect(state.database)
    try:
        extraction_counts = {
            table: before.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "extractor_contracts",
                "extraction_runs",
                "extraction_run_versions",
                "extraction_outputs",
                "extraction_proposal_sets",
                "extraction_proposals",
                "extraction_proposal_evidence",
            )
        }
    finally:
        before.close()

    _drop_empty_entity_schema_to_v13(state.database)
    downgraded = sqlite3.connect(state.database)
    try:
        assert downgraded.execute("PRAGMA user_version").fetchone()[0] == 13
        assert downgraded.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=14"
        ).fetchone()[0] == 0
        assert downgraded.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='entity_mentions'"
        ).fetchone()[0] == 0
    finally:
        downgraded.close()

    with open_extraction_system(state):
        pass

    after = sqlite3.connect(state.database)
    try:
        assert after.execute("PRAGMA user_version").fetchone()[0] == 14
        assert schema_fingerprint(after) == EXPECTED_SCHEMA_FINGERPRINT
        assert {
            table: after.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in extraction_counts
        } == extraction_counts
        assert after.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=14"
        ).fetchone() == (
            ENTITY_AUTHORITY_MIGRATION_NAME,
            ENTITY_AUTHORITY_MIGRATION_CHECKSUM,
        )
        assert after.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        after.close()


def test_failed_v14_upgrade_rolls_back_without_partial_entity_schema(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    _drop_empty_entity_schema_to_v13(state.database)
    conn = sqlite3.connect(state.database, isolation_level=None)
    try:
        conn.execute("CREATE TABLE entity_mentions(conflict TEXT) STRICT")
        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            apply_pending_migrations(
                conn,
                applied_at="2042-03-12T10:00:00.000000Z",
            )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 13
        assert conn.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=14"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='entity_resolution_proposals'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='entity_mentions'"
        ).fetchone()[0] == "CREATE TABLE entity_mentions(conflict TEXT) STRICT"
    finally:
        conn.close()


def test_v14_migration_and_schema_tampering_fail_closed(tmp_path: Path) -> None:
    state = seed_extraction_fixture(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
            ("immutable_authority_migrations_update",),
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_update")
        conn.execute(
            "UPDATE authority_migrations SET checksum=? WHERE version=14",
            ("sha256:" + "0" * 64,),
        )
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="migration history"):
        open_extraction_system(state)

    second = seed_extraction_fixture(tmp_path / "schema")
    conn = sqlite3.connect(second.database)
    try:
        conn.execute("DROP TRIGGER immutable_entity_mention_update")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="schema fingerprint"):
        open_extraction_system(second)
