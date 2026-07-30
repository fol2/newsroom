from __future__ import annotations

import sqlite3
from pathlib import Path

from newsroom.authority.graphiti_adapter_migrations import (
    GRAPHITI_ADAPTER_SCHEMA_VERSION,
)


def downgrade_empty_graphiti_adapter_schema_to_v15(database: Path) -> None:
    """Remove only the empty v16 Graphiti-adapter schema from a checked test DB.

    This helper is test-only. It preserves all v1-v15 authority rows and restores
    the migration-history delete guard after removing the v16 history record.
    """

    conn = sqlite3.connect(database, isolation_level=None)
    try:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current < GRAPHITI_ADAPTER_SCHEMA_VERSION:
            return
        conn.execute("PRAGMA foreign_keys=OFF")
        delete_trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_authority_migrations_delete'"
        ).fetchone()
        assert delete_trigger is not None and delete_trigger[0]
        conn.execute("DROP TRIGGER immutable_authority_migrations_delete")

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
