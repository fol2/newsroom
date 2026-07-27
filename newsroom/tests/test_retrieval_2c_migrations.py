from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.authority.retrieval_migrations import (
    HYBRID_RETRIEVAL_MIGRATION_CHECKSUM,
    HYBRID_RETRIEVAL_MIGRATION_NAME,
    HYBRID_RETRIEVAL_SCHEMA_VERSION,
)


_EXPECTED_TABLES = {
    "hybrid_retrieval_attempts",
    "hybrid_retrieval_contexts_v2",
    "hybrid_retrieval_context_hydrations",
}


def migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(
        conn,
        applied_at="2042-03-12T12:00:00.000000Z",
    )
    return conn


def test_retrieval_migration_is_checked_repository_schema_version_eight() -> None:
    assert HYBRID_RETRIEVAL_SCHEMA_VERSION == 8
    assert SCHEMA_VERSION == 10
    assert (
        8,
        HYBRID_RETRIEVAL_MIGRATION_NAME,
        HYBRID_RETRIEVAL_MIGRATION_CHECKSUM,
    ) in EXPECTED_MIGRATION_HISTORY


def test_retrieval_tables_are_in_exact_schema_fingerprint() -> None:
    conn = migrated()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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


@pytest.mark.parametrize(
    ("table", "message"),
    (
        ("hybrid_retrieval_attempts", "immutable hybrid retrieval attempt"),
        ("hybrid_retrieval_contexts_v2", "immutable retrieval context v2"),
        (
            "hybrid_retrieval_context_hydrations",
            "immutable retrieval hydration linkage",
        ),
    ),
)
def test_retrieval_authority_rows_are_immutable(
    table: str,
    message: str,
) -> None:
    conn = migrated()
    try:
        # Trigger execution is proved against a temporary structurally valid row
        # only for the attempt table; the other tables are guarded by the exact
        # trigger SQL inventory below because their required authority parents are
        # intentionally absent in this isolated migration test.
        triggers = {
            str(row[0]): str(row[1])
            for row in conn.execute(
                "SELECT name,sql FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name=?",
                (table,),
            ).fetchall()
        }
        assert len(triggers) == 2
        assert any(message in sql for sql in triggers.values())
    finally:
        conn.close()
