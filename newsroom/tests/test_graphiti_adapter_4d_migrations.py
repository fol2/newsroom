from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.graphiti_adapter_migrations import (
    GRAPHITI_ADAPTER_MIGRATION_CHECKSUM,
    GRAPHITI_ADAPTER_MIGRATION_NAME,
    GRAPHITI_ADAPTER_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.graphiti_adapter import (
    QUALIFICATION_WORKSPACE_POLICY,
    REPLAY_WORKSPACE_POLICY,
)

from .extraction_4a_helpers import (
    contract_request,
    extraction_proof,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
)
from .graphiti_adapter_4d_migration_helpers import (
    downgrade_empty_graphiti_adapter_schema_to_v15,
)


GRAPHITI_ADAPTER_TABLES = {
    "graphiti_adapter_attempt_heads",
    "graphiti_adapter_attempt_replays",
    "graphiti_adapter_attempts",
    "graphiti_adapter_configurations",
    "graphiti_cleanup_receipts",
    "graphiti_input_manifest_passages",
    "graphiti_input_manifests",
    "graphiti_replay_sources",
    "graphiti_workspace_lifecycle_events",
    "graphiti_workspace_policies",
    "graphiti_workspaces",
}
REQUIRED_GRAPHITI_ADAPTER_TRIGGERS = {
    "graphiti_configuration_contract_guard",
    "graphiti_configuration_workspace_policy_guard",
    "graphiti_workspace_policy_guard",
    "graphiti_workspace_lifecycle_chain_guard",
    "graphiti_manifest_guard",
    "graphiti_manifest_passage_guard",
    "graphiti_cleanup_receipt_guard",
    "graphiti_attempt_chain_guard",
    "graphiti_attempt_lineage_guard",
    "graphiti_attempt_output_guard",
    "graphiti_attempt_head_insert_guard",
    "graphiti_attempt_head_update_guard",
    "graphiti_replay_source_guard",
    "graphiti_attempt_replay_guard",
    "immutable_graphiti_adapter_attempts_update",
    "immutable_graphiti_adapter_attempts_delete",
    "graphiti_attempt_head_delete_guard",
}


def test_fresh_schema_v16_history_policies_tables_and_triggers_are_exact(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        assert GRAPHITI_ADAPTER_SCHEMA_VERSION == 16
        assert SCHEMA_VERSION == 20
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert schema_fingerprint(conn) == EXPECTED_SCHEMA_FINGERPRINT
        assert conn.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=?",
            (GRAPHITI_ADAPTER_SCHEMA_VERSION,),
        ).fetchone() == (
            GRAPHITI_ADAPTER_MIGRATION_NAME,
            GRAPHITI_ADAPTER_MIGRATION_CHECKSUM,
        )
        assert conn.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall() == list(EXPECTED_MIGRATION_HISTORY)

        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'graphiti_%'"
            ).fetchall()
        }
        assert tables == GRAPHITI_ADAPTER_TABLES
        triggers = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert REQUIRED_GRAPHITI_ADAPTER_TRIGGERS <= triggers

        policies = conn.execute(
            "SELECT policy_id,canonical_bytes,canonical_digest "
            "FROM graphiti_workspace_policies ORDER BY policy_id"
        ).fetchall()
        assert policies == [
            (
                str(QUALIFICATION_WORKSPACE_POLICY.policy_id),
                QUALIFICATION_WORKSPACE_POLICY.canonical_bytes,
                QUALIFICATION_WORKSPACE_POLICY.canonical_digest,
            ),
            (
                str(REPLAY_WORKSPACE_POLICY.policy_id),
                REPLAY_WORKSPACE_POLICY.canonical_bytes,
                REPLAY_WORKSPACE_POLICY.canonical_digest,
            ),
        ]
        columns = {
            str(row[1]).lower()
            for table in GRAPHITI_ADAPTER_TABLES
            for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        assert not {
            "api_key",
            "access_token",
            "credential",
            "credentials",
            "cypher",
            "private_node_id",
            "private_relation_id",
            "neo4j_id",
            "secret",
        } & columns
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_checked_v15_to_v16_upgrade_preserves_retained_extraction_authority(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with open_extraction_system(state) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        system.extraction.execute(run_request(state), proof=extraction_proof())

    before = sqlite3.connect(state.database)
    try:
        retained = {
            table: before.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "extractor_contracts",
                "extraction_runs",
                "extraction_run_versions",
                "extraction_outputs",
                "extraction_proposal_sets",
                "extraction_proposals",
                "ledger_events",
            )
        }
    finally:
        before.close()

    downgrade_empty_graphiti_adapter_schema_to_v15(state.database)
    downgraded = sqlite3.connect(state.database)
    try:
        assert downgraded.execute("PRAGMA user_version").fetchone()[0] == 15
        assert downgraded.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=16"
        ).fetchone()[0] == 0
        assert downgraded.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='graphiti_adapter_attempts'"
        ).fetchone()[0] == 0
        assert downgraded.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='evaluation_handoffs'"
        ).fetchone()[0] == 0
    finally:
        downgraded.close()

    with open_extraction_system(state):
        pass

    after = sqlite3.connect(state.database)
    try:
        assert after.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert schema_fingerprint(after) == EXPECTED_SCHEMA_FINGERPRINT
        assert {
            table: after.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in retained
        } == retained
        assert after.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=16"
        ).fetchone() == (
            GRAPHITI_ADAPTER_MIGRATION_NAME,
            GRAPHITI_ADAPTER_MIGRATION_CHECKSUM,
        )
        assert after.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        after.close()


def test_failed_v16_upgrade_rolls_back_without_partial_adapter_schema(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    downgrade_empty_graphiti_adapter_schema_to_v15(state.database)
    conn = sqlite3.connect(state.database, isolation_level=None)
    try:
        conn.execute("CREATE TABLE graphiti_workspace_policies(conflict TEXT) STRICT")
        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            apply_pending_migrations(
                conn,
                applied_at="2042-03-12T10:00:00.000000Z",
            )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 15
        assert conn.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=16"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='graphiti_adapter_attempts'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='graphiti_workspace_policies'"
        ).fetchone()[0] == (
            "CREATE TABLE graphiti_workspace_policies(conflict TEXT) STRICT"
        )
    finally:
        conn.close()


def test_v16_rows_are_immutable_and_tampering_fails_checked_open(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    conn = sqlite3.connect(state.database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE graphiti_workspace_policies SET max_workspace_bytes=1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            conn.execute("DELETE FROM graphiti_workspace_policies")
    finally:
        conn.close()

    history = seed_extraction_fixture(tmp_path / "history")
    conn = sqlite3.connect(history.database)
    try:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
            ("immutable_authority_migrations_update",),
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_update")
        conn.execute(
            "UPDATE authority_migrations SET checksum=? WHERE version=16",
            ("sha256:" + "0" * 64,),
        )
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="migration history"):
        open_extraction_system(history)

    schema = seed_extraction_fixture(tmp_path / "schema")
    conn = sqlite3.connect(schema.database)
    try:
        conn.execute("DROP TRIGGER graphiti_manifest_guard")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuthoritySchemaError, match="schema fingerprint"):
        open_extraction_system(schema)
