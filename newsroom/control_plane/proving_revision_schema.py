"""DDL for durable first-seen revision facts.

Shared so live identity, cycle backfill, and backlog migration cannot drift.
Contains no identity hashing: backlog reconciliation may import this module
without coupling G1 to the live resolver.
"""

from __future__ import annotations

import sqlite3

_FIRST_SEEN_COLUMNS = """
    source_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    revision_digest TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY(source_id, item_key, revision_digest)
"""

_WATERMARK_COLUMNS = """
    processed_until TEXT PRIMARY KEY
"""


def _qualify(table: str, *, schema: str) -> str:
    if schema == "main":
        return table
    return f"{schema}.{table}"


def ensure_proving_revision_schema(
    connection: sqlite3.Connection, *, schema: str = "main"
) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualify("proving_revision_first_seen", schema=schema)}(
            {_FIRST_SEEN_COLUMNS}
        ) WITHOUT ROWID
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_qualify("proving_backfill_watermark", schema=schema)}(
            {_WATERMARK_COLUMNS}
        )
        """
    )
