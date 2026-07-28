from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority.discovery_migrations import (
    DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM,
    DISCOVERY_AUTHORITY_MIGRATION_NAME,
    DISCOVERY_AUTHORITY_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    SCHEMA_VERSION,
)
from newsroom.authority.persistence import AuthoritySchemaError

from .source_3a_helpers import open_source_system


DISCOVERY_TABLES = frozenset(
    {
        "discovery_signals",
        "discovery_signal_findings",
        "discovery_gate_decisions",
        "discovery_gate_decision_heads",
        "news_leads",
        "news_lead_source_roles",
        "news_lead_portfolio_functions",
        "news_lead_source_dependencies",
        "discovery_watch_conditions",
        "lead_disposition_decisions",
        "lead_disposition_heads",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "discovery_signal_lineage_guard",
        "discovery_signal_finding_insert_guard",
        "discovery_gate_source_revalidation_guard",
        "discovery_gate_predecessor_guard",
        "discovery_gate_head_update_guard",
        "news_lead_gate_lineage_guard",
        "news_lead_source_role_guard",
        "news_lead_dependency_guard",
        "discovery_watch_condition_chronology_guard",
        "lead_disposition_lineage_guard",
        "lead_disposition_predecessor_guard",
        "lead_disposition_head_update_guard",
        "immutable_discovery_signals_update",
        "immutable_discovery_gate_decisions_delete",
        "immutable_news_leads_update",
        "immutable_watch_conditions_delete",
        "immutable_lead_dispositions_update",
    }
)


def _reduce_empty_v12_database_to_retained_v11(database) -> None:
    """Remove only additive v12 objects to reproduce an exact empty v11 DB."""

    conn = sqlite3.connect(database)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        for table in (
            "lead_disposition_heads",
            "lead_disposition_decisions",
            "discovery_watch_conditions",
            "news_lead_source_dependencies",
            "news_lead_portfolio_functions",
            "news_lead_source_roles",
            "news_leads",
            "discovery_gate_decision_heads",
            "discovery_gate_decisions",
            "discovery_signal_findings",
            "discovery_signals",
        ):
            conn.execute(f"DROP TABLE {table}")
        delete_trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
            ("immutable_authority_migrations_delete",),
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_delete")
        conn.execute(
            "DELETE FROM authority_migrations WHERE version=?",
            (DISCOVERY_AUTHORITY_SCHEMA_VERSION,),
        )
        conn.execute(delete_trigger_sql)
        conn.execute("PRAGMA user_version=11")
        conn.commit()
    finally:
        conn.close()


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


def test_retained_v11_database_upgrades_atomically_to_v12(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    open_source_system(database).close()
    _reduce_empty_v12_database_to_retained_v11(database)

    conn = sqlite3.connect(database)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='discovery_signals'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=12"
        ).fetchone()[0] == 0
    finally:
        conn.close()

    open_source_system(database).close()
    conn = sqlite3.connect(database)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
        assert conn.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=12"
        ).fetchone() == (
            DISCOVERY_AUTHORITY_MIGRATION_NAME,
            DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM,
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='discovery_signals'"
        ).fetchone()[0] == 1
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
