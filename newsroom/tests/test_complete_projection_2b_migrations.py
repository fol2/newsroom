from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority.complete_projection_migrations import (
    COMPLETE_PROJECTION_MIGRATION_CHECKSUM,
    COMPLETE_PROJECTION_MIGRATION_NAME,
    COMPLETE_PROJECTION_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)


_EXPECTED_TABLES = {
    "projection_fulltext_contracts",
    "projection_vector_contracts",
    "projection_fixture_vector_manifests",
    "projection_fixture_vectors",
    "projection_complete_contracts",
    "projection_family_complete_contracts",
    "projection_generation_complete_bindings",
    "projection_generation_complete_validations",
}


def _migrated_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(conn, applied_at="2042-03-12T12:00:00.000000Z")
    return conn


def test_complete_projection_migration_is_checked_version_seven() -> None:
    assert COMPLETE_PROJECTION_SCHEMA_VERSION == SCHEMA_VERSION == 7
    assert EXPECTED_MIGRATION_HISTORY[-1] == (
        7,
        COMPLETE_PROJECTION_MIGRATION_NAME,
        COMPLETE_PROJECTION_MIGRATION_CHECKSUM,
    )


def test_complete_projection_tables_are_in_exact_schema_fingerprint() -> None:
    conn = _migrated_connection()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
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


def test_complete_contract_rows_are_immutable() -> None:
    conn = _migrated_connection()
    try:
        conn.execute(
            "INSERT INTO projection_fulltext_contracts("
            "contract_digest,contract_id,contract_version,implementation_version,"
            "index_name,node_label,source_field,retrieval_property,analyzer,provider,"
            "unicode_normalization,casefold,collapse_whitespace,eventually_consistent,"
            "canonical_bytes,registered_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "sha256:" + "1" * 64,
                "test_fulltext",
                "v1",
                "impl-v1",
                "test_fulltext_index",
                "Document",
                "text",
                "retrieval_text",
                "standard-no-stop-words",
                "fulltext-2.0",
                "NFKC",
                1,
                1,
                0,
                b"{}",
                "2042-03-12T12:00:00.000000Z",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE projection_fulltext_contracts SET analyzer='standard'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            conn.execute("DELETE FROM projection_fulltext_contracts")
    finally:
        conn.close()
