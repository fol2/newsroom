from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority.check_migrations import (
    CHECK_AUTHORITY_MIGRATION_CHECKSUM,
    CHECK_AUTHORITY_MIGRATION_NAME,
    CHECK_AUTHORITY_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    SCHEMA_VERSION,
)
from newsroom.authority.persistence import AuthoritySchemaError

from .source_3a_helpers import open_source_system


CHECK_TABLES = frozenset(
    {
        "check_requests",
        "check_attempts",
        "check_outcomes",
        "baseline_decisions",
        "baseline_manifest_entries",
        "baseline_decision_heads",
        "observable_transitions",
        "operational_findings",
        "operational_finding_occurrences",
        "discovery_occurrence_check_links",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "check_request_source_contract_guard",
        "check_request_coverage_guard",
        "check_attempt_exact_predecessor_guard",
        "check_attempt_request_chronology_guard",
        "check_attempt_terminal_predecessor_guard",
        "check_outcome_request_contract_guard",
        "baseline_decision_chain_guard",
        "baseline_head_update_guard",
        "observable_transition_source_contract_guard",
        "observable_transition_occurrence_guard",
        "discovery_occurrence_check_link",
        "immutable_check_outcomes_update",
        "immutable_observable_transitions_delete",
    }
)


def test_checked_v11_migration_creates_and_reopens_exact_schema(
    tmp_path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    open_source_system(database).close()

    conn = sqlite3.connect(database)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == (
            CHECK_AUTHORITY_SCHEMA_VERSION
        )
        assert SCHEMA_VERSION == CHECK_AUTHORITY_SCHEMA_VERSION
        row = conn.execute(
            "SELECT name,checksum FROM authority_migrations "
            "WHERE version=?",
            (CHECK_AUTHORITY_SCHEMA_VERSION,),
        ).fetchone()
        assert row == (
            CHECK_AUTHORITY_MIGRATION_NAME,
            CHECK_AUTHORITY_MIGRATION_CHECKSUM,
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
        assert CHECK_TABLES <= tables
        assert REQUIRED_TRIGGERS <= triggers
    finally:
        conn.close()

    assert EXPECTED_MIGRATION_HISTORY[-1] == (
        CHECK_AUTHORITY_SCHEMA_VERSION,
        CHECK_AUTHORITY_MIGRATION_NAME,
        CHECK_AUTHORITY_MIGRATION_CHECKSUM,
    )
    open_source_system(database).close()


def test_startup_rejects_v11_migration_history_tampering(
    tmp_path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    open_source_system(database).close()

    conn = sqlite3.connect(database)
    try:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name=?",
            ("immutable_authority_migrations_update",),
        ).fetchone()[0]
        conn.execute(
            "DROP TRIGGER immutable_authority_migrations_update"
        )
        conn.execute(
            "UPDATE authority_migrations SET checksum=? "
            "WHERE version=?",
            (
                "sha256:" + "0" * 64,
                CHECK_AUTHORITY_SCHEMA_VERSION,
            ),
        )
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthoritySchemaError,
        match="migration history",
    ):
        open_source_system(database)
