from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.extraction_migrations import (
    EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM,
    EXTRACTION_AUTHORITY_MIGRATION_NAME,
    EXTRACTION_AUTHORITY_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.authority.persistence import AuthoritySchemaError

from .extraction_4a_helpers import open_extraction_system, seed_extraction_fixture


_EXTRACTION_TABLES_IN_DROP_ORDER = (
    "extraction_proposal_evidence",
    "extraction_proposals",
    "extraction_proposal_sets",
    "extraction_outputs",
    "extraction_run_heads",
    "extraction_run_versions",
    "extraction_run_passages",
    "extraction_runs",
    "extractor_contracts",
)


def _downgrade_empty_extraction_schema_to_v12(database: Path) -> None:
    conn = sqlite3.connect(database, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        delete_trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_authority_migrations_delete'"
        ).fetchone()
        assert delete_trigger is not None and delete_trigger[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_delete")
        entity_views = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view' "
                "AND name LIKE 'entity_%'"
            ).fetchall()
        ]
        for view in entity_views:
            conn.execute(f'DROP VIEW "{view}"')
        entity_triggers = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND (name LIKE '%entity%' OR tbl_name LIKE 'entity_%' "
                "OR tbl_name LIKE 'canonical_entit%')"
            ).fetchall()
        ]
        for trigger in entity_triggers:
            conn.execute(f'DROP TRIGGER "{trigger}"')
        entity_tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE 'entity_%' OR name LIKE 'canonical_entit%')"
            ).fetchall()
        ]
        for table in entity_tables:
            conn.execute(f'DROP TABLE "{table}"')
        for table in _EXTRACTION_TABLES_IN_DROP_ORDER:
            conn.execute(f'DROP TABLE "{table}"')
        conn.execute(
            "DELETE FROM authority_migrations WHERE version>=?",
            (EXTRACTION_AUTHORITY_SCHEMA_VERSION,),
        )
        conn.execute(str(delete_trigger[0]))
        conn.execute("PRAGMA user_version=12")
    finally:
        conn.close()


def test_current_schema_retains_exact_v13_history_and_extraction_tables(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert schema_fingerprint(conn) == EXPECTED_SCHEMA_FINGERPRINT
        assert conn.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=13"
        ).fetchone() == (
            EXTRACTION_AUTHORITY_MIGRATION_NAME,
            EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM,
        )
        assert conn.execute(
            "SELECT version,name,checksum FROM authority_migrations "
            "ORDER BY version"
        ).fetchall() == list(EXPECTED_MIGRATION_HISTORY)
        actual_tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name='extractor_contracts' OR name LIKE 'extraction_%')"
            ).fetchall()
        }
        assert actual_tables == set(_EXTRACTION_TABLES_IN_DROP_ORDER)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_checked_v12_to_v13_upgrade_preserves_prior_authority(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    _downgrade_empty_extraction_schema_to_v12(state.database)

    before = sqlite3.connect(state.database)
    try:
        source_count = before.execute(
            "SELECT COUNT(*) FROM source_revisions"
        ).fetchone()[0]
        object_count = before.execute(
            "SELECT COUNT(*) FROM object_admissions"
        ).fetchone()[0]
        assert before.execute("PRAGMA user_version").fetchone()[0] == 12
        assert before.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=13"
        ).fetchone()[0] == 0
    finally:
        before.close()

    with open_extraction_system(state):
        pass

    after = sqlite3.connect(state.database)
    try:
        assert after.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert schema_fingerprint(after) == EXPECTED_SCHEMA_FINGERPRINT
        assert after.execute(
            "SELECT COUNT(*) FROM source_revisions"
        ).fetchone()[0] == source_count
        assert after.execute(
            "SELECT COUNT(*) FROM object_admissions"
        ).fetchone()[0] == object_count
        assert after.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=13"
        ).fetchone() == (
            EXTRACTION_AUTHORITY_MIGRATION_NAME,
            EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM,
        )
    finally:
        after.close()


def test_failed_v13_upgrade_rolls_back_without_partial_schema(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    _downgrade_empty_extraction_schema_to_v12(state.database)

    conn = sqlite3.connect(state.database, isolation_level=None)
    try:
        conn.execute("CREATE TABLE extractor_contracts(conflict TEXT) STRICT")
        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            apply_pending_migrations(
                conn,
                applied_at="2042-03-12T10:00:00.000000Z",
            )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
        assert conn.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=13"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='extraction_runs'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='extractor_contracts'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_newer_or_tampered_migration_state_fails_closed(tmp_path: Path) -> None:
    state = seed_extraction_fixture(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="newer than supported"):
        open_extraction_system(state)

    second = seed_extraction_fixture(tmp_path / "tampered")
    conn = sqlite3.connect(second.database)
    try:
        trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_authority_migrations_update'"
        ).fetchone()
        assert trigger is not None and trigger[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_update")
        conn.execute(
            "UPDATE authority_migrations SET checksum=? WHERE version=13",
            ("sha256:" + "0" * 64,),
        )
        conn.execute(str(trigger[0]))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="migration history"):
        open_extraction_system(second)
