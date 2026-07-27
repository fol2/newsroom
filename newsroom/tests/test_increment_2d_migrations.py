from __future__ import annotations

import sqlite3

from newsroom.authority.development_candidate_migrations import (
    DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM,
    DEVELOPMENT_CANDIDATE_MIGRATION_NAME,
    DEVELOPMENT_CANDIDATE_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)


_EXPECTED_TABLES = {
    "development_candidates_v2",
    "development_candidate_versions_v2",
    "development_candidate_admission_decisions_v2",
}


def _migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(
        conn,
        applied_at="2042-03-12T12:00:00.000000Z",
    )
    return conn


def test_increment_2d_migration_is_checked_schema_version_nine() -> None:
    assert DEVELOPMENT_CANDIDATE_SCHEMA_VERSION == SCHEMA_VERSION == 9
    assert EXPECTED_MIGRATION_HISTORY[-1] == (
        9,
        DEVELOPMENT_CANDIDATE_MIGRATION_NAME,
        DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM,
    )


def test_increment_2d_tables_are_in_exact_schema_fingerprint() -> None:
    conn = _migrated()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert _EXPECTED_TABLES <= tables
        assert schema_fingerprint(conn) == EXPECTED_SCHEMA_FINGERPRINT
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_increment_2d_rows_have_exact_immutable_triggers() -> None:
    conn = _migrated()
    try:
        for table in sorted(_EXPECTED_TABLES):
            triggers = {
                str(row[0]): str(row[1])
                for row in conn.execute(
                    "SELECT name,sql FROM sqlite_master "
                    "WHERE type='trigger' AND tbl_name=?",
                    (table,),
                ).fetchall()
            }
            assert len(triggers) == 2
            assert any("immutable" in sql for sql in triggers.values())
            assert any("retained" in sql for sql in triggers.values())
    finally:
        conn.close()
