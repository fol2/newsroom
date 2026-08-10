from __future__ import annotations

import sqlite3
from pathlib import Path

from newsroom.authority.evaluation_handoff_migrations import (
    EVALUATION_HANDOFF_SCHEMA_VERSION,
)
from newsroom.authority.event_hypothesis_migrations import (
    EVENT_HYPOTHESIS_SCHEMA_VERSION,
)
from newsroom.authority.event_hypothesis_relationship_migrations import (
    EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_CHECKSUM,
    EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_NAME,
    EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION,
)
from newsroom.authority.graphiti_adapter_migrations import (
    GRAPHITI_ADAPTER_SCHEMA_VERSION,
)
from newsroom.authority.triage_disposition_migrations import (
    TRIAGE_DISPOSITION_SCHEMA_VERSION,
)
from newsroom.authority.triage_execution_migrations import (
    TRIAGE_EXECUTION_SCHEMA_VERSION,
)
from newsroom.authority.triage_work_item_migrations import (
    TRIAGE_WORK_ITEM_SCHEMA_VERSION,
)


def drop_empty_v22_relationship_schema(connection: sqlite3.Connection) -> None:
    """Remove an exact, empty v22 relationship schema atomically."""

    savepoint = "checked_empty_v22_relationship_downgrade"
    relationship_table = "event_hypothesis_relationship_decisions"
    relationship_triggers = (
        "retained_event_hypothesis_relationship_delete",
        "immutable_event_hypothesis_relationship_update",
        "event_hypothesis_relationship_coherence",
    )
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        maximum_history_version = connection.execute(
            "SELECT MAX(version) FROM authority_migrations"
        ).fetchone()[0]
        if maximum_history_version != user_version:
            raise sqlite3.DatabaseError("v22 schema version/history mismatch")
        if user_version < EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION:
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            return
        if user_version != EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION:
            raise sqlite3.DatabaseError("downgrade requires exact schema v22")

        v22_history = connection.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=?",
            (EVENT_HYPOTHESIS_RELATIONSHIP_SCHEMA_VERSION,),
        ).fetchone()
        if v22_history != (
            EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_NAME,
            EVENT_HYPOTHESIS_RELATIONSHIP_MIGRATION_CHECKSUM,
        ):
            raise sqlite3.DatabaseError(
                "downgrade requires exact v22 migration history"
            )

        required_objects = {
            ("table", relationship_table, relationship_table),
            *(
                ("trigger", trigger, relationship_table)
                for trigger in relationship_triggers
            ),
        }
        present_objects = set(
            connection.execute(
                "SELECT type,name,tbl_name FROM sqlite_master "
                f"WHERE name IN ({','.join('?' for _ in required_objects)})",
                tuple(name for _, name, _ in required_objects),
            ).fetchall()
        )
        if present_objects != required_objects:
            raise sqlite3.DatabaseError(
                "downgrade requires exact v22 relationship schema"
            )
        if connection.execute(
            f'SELECT COUNT(*) FROM "{relationship_table}"'
        ).fetchone() != (0,):
            raise sqlite3.DatabaseError("v22 relationship table must be empty")

        for trigger in relationship_triggers:
            connection.execute(f'DROP TRIGGER "{trigger}"')
        connection.execute(f'DROP TABLE "{relationship_table}"')
    except Exception:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    else:
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def downgrade_empty_graphiti_adapter_schema_to_v15(database: Path) -> None:
    """Remove only the empty v16 Graphiti-adapter schema from a checked test DB.

    This helper is test-only. It first removes the empty additive v17 successor,
    preserves all v1-v15 authority rows, and restores the migration-history
    delete guard after removing the v16+ history records.
    """

    conn = sqlite3.connect(database, isolation_level=None)
    try:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current < GRAPHITI_ADAPTER_SCHEMA_VERSION:
            return
        drop_empty_v22_relationship_schema(conn)
        conn.execute("PRAGMA foreign_keys=OFF")
        delete_trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_authority_migrations_delete'"
        ).fetchone()
        assert delete_trigger is not None and delete_trigger[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_delete")

        if current >= EVENT_HYPOTHESIS_SCHEMA_VERSION:
            for table in (
                "event_hypothesis_heads_v2",
                "event_hypothesis_versions_v2",
                "event_hypotheses_v2",
            ):
                conn.execute(f'DROP TABLE "{table}"')

        if current >= TRIAGE_EXECUTION_SCHEMA_VERSION:
            for table in (
                "triage_work_item_leases",
                "triage_worker_attempts",
                "triage_execution_batches",
            ):
                conn.execute(f'DROP TABLE "{table}"')

        if current >= TRIAGE_DISPOSITION_SCHEMA_VERSION:
            for table in (
                "triage_proposal_dispositions",
                "triage_proposal_validation_findings",
            ):
                conn.execute(f'DROP TABLE "{table}"')

        if current >= TRIAGE_WORK_ITEM_SCHEMA_VERSION:
            for table in (
                "triage_work_item_heads",
                "triage_work_item_versions",
                "triage_work_items",
            ):
                conn.execute(f'DROP TABLE "{table}"')

        if current >= EVALUATION_HANDOFF_SCHEMA_VERSION:
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND (name LIKE '%evaluation_handoff%' "
                "OR tbl_name LIKE 'evaluation_handoff%') ORDER BY name DESC"
            ).fetchall():
                conn.execute(f'DROP TRIGGER "{row[0]}"')
            for table in (
                "evaluation_handoff_acknowledgements",
                "evaluation_handoff_attempts",
                "evaluation_handoffs",
            ):
                conn.execute(f'DROP TABLE "{table}"')

        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' "
            "AND name LIKE 'graphiti_%' ORDER BY name DESC"
        ).fetchall():
            conn.execute(f'DROP VIEW "{row[0]}"')
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND (name LIKE 'graphiti_%' OR name LIKE 'immutable_graphiti_%' OR tbl_name LIKE 'graphiti_%') "
            "ORDER BY name DESC"
        ).fetchall():
            conn.execute(f'DROP TRIGGER "{row[0]}"')
        for table in (
            "graphiti_adapter_attempt_replays",
            "graphiti_replay_sources",
            "graphiti_adapter_attempt_heads",
            "graphiti_adapter_attempts",
            "graphiti_cleanup_receipts",
            "graphiti_input_manifest_passages",
            "graphiti_input_manifests",
            "graphiti_workspace_lifecycle_events",
            "graphiti_workspaces",
            "graphiti_adapter_configurations",
            "graphiti_workspace_policies",
        ):
            conn.execute(f'DROP TABLE "{table}"')

        conn.execute(
            "DELETE FROM authority_migrations WHERE version>=?",
            (GRAPHITI_ADAPTER_SCHEMA_VERSION,),
        )
        conn.execute(str(delete_trigger[0]))
        conn.execute("PRAGMA user_version=15")
    finally:
        conn.close()
