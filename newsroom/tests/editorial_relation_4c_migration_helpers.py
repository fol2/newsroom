from __future__ import annotations

import sqlite3
from pathlib import Path

from newsroom.authority.editorial_relation_migrations import (
    EDITORIAL_RELATION_SCHEMA_VERSION,
)


def downgrade_empty_editorial_relation_schema_to_v14(database: Path) -> None:
    """Remove only the v15 editorial-relation schema from a checked test DB.

    This helper is intentionally test-only.  It preserves every v1-v14 row and
    restores the authority-migration immutability trigger after deleting the
    v15 history record.
    """

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
            "AND name LIKE 'editorial_%' ORDER BY name DESC"
        ).fetchall():
            conn.execute(f'DROP VIEW "{row[0]}"')
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND (name LIKE '%editorial%' OR tbl_name LIKE 'editorial_%') "
            "ORDER BY name DESC"
        ).fetchall():
            conn.execute(f'DROP TRIGGER "{row[0]}"')
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'editorial_%' ORDER BY name DESC"
        ).fetchall():
            conn.execute(f'DROP TABLE "{row[0]}"')

        conn.execute(
            "DELETE FROM authority_migrations WHERE version>=?",
            (EDITORIAL_RELATION_SCHEMA_VERSION,),
        )
        conn.execute(str(delete_trigger[0]))
        conn.execute("PRAGMA user_version=14")
    finally:
        conn.close()
