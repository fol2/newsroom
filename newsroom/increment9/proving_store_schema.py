"""Exact physical proving layouts and one atomic, explicit v1 to v2 migration.

The report SCHEMA_VERSION is independent. SQLite user_version is zero for the
original inline-body layout and two for the content-addressed layout.
"""

from __future__ import annotations

import re
import sqlite3

STORE_VERSION = 2

_V1_SCHEMA = """
        CREATE TABLE IF NOT EXISTS proving_runs(
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            publication INTEGER NOT NULL DEFAULT 0 CHECK(publication=0),
            public_dispatch INTEGER NOT NULL DEFAULT 0 CHECK(public_dispatch=0),
            openrouter_invoked INTEGER NOT NULL DEFAULT 0 CHECK(openrouter_invoked=0),
            spend_gbp_minor INTEGER NOT NULL DEFAULT 0 CHECK(spend_gbp_minor=0)
        );
        CREATE TABLE IF NOT EXISTS proving_observations(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            url TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            body_digest TEXT NOT NULL,
            body BLOB NOT NULL,
            item_count INTEGER NOT NULL,
            error TEXT,
            PRIMARY KEY(run_id, source_id, body_digest),
            FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS proving_gates(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id),
            FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS proving_rights_packets(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            packet_digest TEXT NOT NULL,
            packet_json TEXT NOT NULL,
            assessed_at TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id),
            FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS proving_source_health(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('ACTIVE','DEGRADED','HELD','BLOCKED')),
            endpoint TEXT NOT NULL,
            attempts INTEGER NOT NULL CHECK(attempts >= 0),
            reason TEXT,
            next_retry_at TEXT,
            recovered_at TEXT,
            PRIMARY KEY(run_id, source_id),
            FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)
        );
        """

_OBSERVATION_COLUMNS = (
    "source_id,run_id,fetched_at,url,status_code,body_digest,item_count,error"
)
_BODIES_DDL = """CREATE TABLE proving_bodies(
    body_digest TEXT PRIMARY KEY,
    body BLOB NOT NULL
) WITHOUT ROWID"""
_V2_SCHEMA = _V1_SCHEMA.replace("            body BLOB NOT NULL,\n", "").replace(
    "FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)\n        );\n        CREATE TABLE IF NOT EXISTS proving_gates",
    "FOREIGN KEY(run_id) REFERENCES proving_runs(run_id),\n"
    "            FOREIGN KEY(body_digest) REFERENCES proving_bodies(body_digest) "
    "ON DELETE RESTRICT ON UPDATE RESTRICT\n        );\n"
    "        CREATE TABLE IF NOT EXISTS proving_gates",
)
_CORE_TABLES = frozenset((
    "proving_runs", "proving_observations", "proving_gates",
    "proving_rights_packets", "proving_source_health",
))


def _statements(schema: str):
    return (statement.strip() for statement in schema.split(";") if statement.strip())


def _normalise(sql: str) -> str:
    # Compare the owned DDL, not merely column names: retain checks, keys and FKs.
    return "".join(
        part if index % 2 else re.sub(r'\s+|"|`|\[|\]', "", re.sub(
            r"\bif\s+not\s+exists\b", "", part.lower()
        ))
        for index, part in enumerate(re.split(r"('(?:''|[^'])*')", sql))
    )


def _revision_statements() -> tuple[str, ...]:
    from newsroom.control_plane.proving_revision_schema import (
        _FIRST_SEEN_COLUMNS, _PULL_FIRST_SEEN_COLUMNS, _WATERMARK_COLUMNS,
    )

    return (
        f"CREATE TABLE proving_revision_first_seen({_FIRST_SEEN_COLUMNS}) WITHOUT ROWID",
        f"CREATE TABLE proving_effective_pull_first_seen({_PULL_FIRST_SEEN_COLUMNS}) WITHOUT ROWID",
        f"CREATE TABLE proving_backfill_watermark({_WATERMARK_COLUMNS})",
    )


def _expected(version: int) -> dict[str, str]:
    statements = list(_statements(_V1_SCHEMA if version == 1 else _V2_SCHEMA))
    if version == 2:
        statements.append(_BODIES_DDL)
    statements.extend(_revision_statements())
    return {
        re.search(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", statement).group(1): _normalise(statement)
        for statement in statements
    }


def physical_store_version(connection: sqlite3.Connection) -> int:
    """Inspect only schema; never rewrite or scan retained bodies on connect."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, STORE_VERSION):
        raise ValueError("unsupported proving physical store version")
    owned = _CORE_TABLES | {"proving_bodies", "proving_revision_first_seen",
                           "proving_effective_pull_first_seen", "proving_backfill_watermark"}
    objects = {
        str(name): (kind, sql)
        for name, kind, sql in connection.execute(
            "SELECT name,type,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
        )
    }
    present = owned & objects.keys()
    if not present and version == 0:
        return 0
    layout = 2 if version == STORE_VERSION else 1
    expected = _expected(layout)
    if present != expected.keys() or any(
        objects[name][0] != "table" or _normalise(objects[name][1]) != sql
        for name, sql in expected.items()
    ):
        raise ValueError("malformed or hybrid proving physical store layout")
    # Related extensions require their own contract. In particular DROP TABLE
    # must never cascade-delete another table's rows, or strand a body-reading
    # view. Truly unrelated tables, views and indexes remain untouched.
    if layout == 1 and any(
        name != "proving_observations" and sql and re.search(
            r"\bproving_observations\b", re.sub(r"'(?:''|[^'])*'", "", sql), re.I
        )
        for name, (_kind, sql) in objects.items()
    ):
        raise ValueError("proving observations have unsupported related objects")
    return layout


def create_proving_schema(connection: sqlite3.Connection) -> None:
    """Initialise a fresh store only; old stores require explicit migration."""
    version = physical_store_version(connection)
    if version == 1:
        raise ValueError("proving physical store requires explicit v1 to v2 migration")
    if version == STORE_VERSION:
        return
    if connection.in_transaction:
        raise ValueError("proving schema creation requires an idle connection")
    connection.execute("BEGIN IMMEDIATE")
    try:
        # A second writer may have initialised the store while we waited.
        if physical_store_version(connection) == 0:
            connection.execute(_BODIES_DDL)
            for statement in _statements(_V2_SCHEMA):
                connection.execute(statement)
            for statement in _revision_statements():
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version={STORE_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def migrate_proving_bodies(connection: sqlite3.Connection) -> dict[str, int]:
    """Losslessly migrate one exact v1 store in place; never VACUUM or back up.

    Requires an idle writable connection. Any error rolls the entire migration
    back, including DDL; no intermediate schema is published to readers.
    """
    from newsroom.increment9.proving import _store_body, resolve_observation_body

    if connection.in_transaction:
        raise ValueError("proving migration requires an idle connection")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    try:
        if physical_store_version(connection) != 1:
            raise ValueError("proving migration requires the exact v1 layout")
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='_proving_observations_v2'").fetchone():
            raise ValueError("proving migration temporary table name is occupied")
        # Reject dangling old references before a swap can obscure them.
        for table in _CORE_TABLES:
            if connection.execute(f'PRAGMA foreign_key_check("{table}")').fetchone():
                raise ValueError("proving migration has invalid foreign keys")
        connection.execute(_BODIES_DDL)
        observation_ddl = next(
            statement for statement in _statements(_V2_SCHEMA)
            if "CREATE TABLE IF NOT EXISTS proving_observations(" in statement
        )
        connection.execute(observation_ddl.replace("proving_observations(", "_proving_observations_v2("))
        count = 0
        for row in connection.execute(
            f"SELECT rowid,{_OBSERVATION_COLUMNS},body FROM proving_observations ORDER BY rowid"
        ):
            _store_body(connection, row[6], row[9])
            connection.execute(
                f"INSERT INTO _proving_observations_v2(rowid,{_OBSERVATION_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?)",
                row[:9],
            )
            count += 1
        # Exact bidirectional metadata and rowid equivalence, not just a count.
        for left, right in (("proving_observations", "_proving_observations_v2"),
                            ("_proving_observations_v2", "proving_observations")):
            if connection.execute(
                f"SELECT rowid,{_OBSERVATION_COLUMNS} FROM {left} EXCEPT "
                f"SELECT rowid,{_OBSERVATION_COLUMNS} FROM {right} LIMIT 1"
            ).fetchone():
                raise ValueError("proving migration metadata differs")
        # Each unique body is resolved once here; every old row was validated above.
        for (digest,) in connection.execute("SELECT body_digest FROM proving_bodies"):
            resolve_observation_body(connection, digest)
        if connection.execute('PRAGMA foreign_key_check("_proving_observations_v2")').fetchone():
            raise ValueError("proving migration body resolution differs")
        connection.execute("DROP TABLE proving_observations")
        connection.execute("ALTER TABLE _proving_observations_v2 RENAME TO proving_observations")
        for table in ("proving_observations", "proving_bodies"):
            results = connection.execute(f'PRAGMA integrity_check("{table}")').fetchall()
            if results != [("ok",)]:
                raise ValueError("proving migration integrity check failed")
        body_count = connection.execute("SELECT COUNT(*) FROM proving_bodies").fetchone()[0]
        connection.execute(f"PRAGMA user_version={STORE_VERSION}")
        physical_store_version(connection)
        connection.commit()
        return {"observations": count, "bodies": body_count, "physical_store_version": STORE_VERSION}
    except BaseException:
        connection.rollback()
        raise
