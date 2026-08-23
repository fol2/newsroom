"""Shared SQLite operating profile for Control Plane stores (ADR 0002)."""

from __future__ import annotations

import sqlite3

BUSY_TIMEOUT_MS = 5_000


def apply_control_plane_sqlite_profile(
    connection: sqlite3.Connection,
    *,
    query_only: bool = False,
    wal: bool | None = True,
    busy_timeout_ms: int = BUSY_TIMEOUT_MS,
    schema: str = "main",
) -> None:
    """Enable foreign keys, FULL sync, busy timeout, and the WAL writer profile.

    Pass wal=None to leave journal_mode unchanged. That is required for
    proving connections that must not take a journal-mode lock while a
    writer fence is held.
    """

    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={max(1, int(busy_timeout_ms))}")
    if query_only:
        if schema == "main":
            connection.execute("PRAGMA query_only=ON")
        return
    connection.execute(f"PRAGMA {schema}.synchronous=FULL")
    if connection.execute(f"PRAGMA {schema}.synchronous").fetchone()[0] != 2:
        raise RuntimeError(f"{schema} SQLite synchronous mode is not FULL")
    if wal is None:
        return
    journal = "WAL" if wal else "DELETE"
    if schema == "main":
        connection.execute(f"PRAGMA journal_mode={journal}")
        return
    connection.execute(f"PRAGMA {schema}.journal_mode={journal}")
