"""Standalone schema for the isolated Increment 9 shadow Epoch authority.

It is intentionally absent from the production authority migration registry.
Installation rejects a non-empty or production-versioned database.
"""

from __future__ import annotations

import sqlite3

from .canonical import digest_canonical

INCREMENT9_SHADOW_APPLICATION_ID = 0x4E523931  # NR91
INCREMENT9_SHADOW_SCHEMA_VERSION = 1
INCREMENT9_SHADOW_MIGRATION_NAME = "increment9_isolated_shadow_epoch_v1"
INCREMENT9_SHADOW_PLAN_DIGEST = (
    "sha256:92510c8b3989bb25cfce187b3477a71d8909a691ad8f3b88ae4917e456e9216d"
)
_D = "substr({0},1,7)='sha256:' AND length({0})=71 AND substr({0},8) NOT GLOB '*[^0-9a-f]*'"

INCREMENT9_SHADOW_MIGRATION_STATEMENTS = (
    f"""CREATE TABLE increment9_shadow_meta(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        schema_version INTEGER NOT NULL CHECK(schema_version=1),
        migration_name TEXT NOT NULL,
        migration_checksum TEXT NOT NULL CHECK({_D.format('migration_checksum')}),
        plan_digest TEXT NOT NULL CHECK({_D.format('plan_digest')})
    ) STRICT""",
    f"""CREATE TABLE shadow_epoch_records(
        record_schema TEXT NOT NULL,
        record_id TEXT NOT NULL,
        record_bytes BLOB NOT NULL CHECK(length(record_bytes)>0 AND length(record_bytes)<=1048576),
        record_digest TEXT PRIMARY KEY CHECK({_D.format('record_digest')}),
        epoch_id TEXT NOT NULL,
        cohort_digest TEXT CHECK(cohort_digest IS NULL OR ({_D.format('cohort_digest')})),
        run_id TEXT,
        attempt_id TEXT,
        sequence INTEGER CHECK(sequence IS NULL OR sequence>=0),
        UNIQUE(record_schema,record_id),
        UNIQUE(record_schema,attempt_id,sequence)
    ) STRICT""",
    "CREATE INDEX shadow_epoch_records_epoch ON shadow_epoch_records(epoch_id,record_schema,record_id)",
    "CREATE INDEX shadow_epoch_records_run ON shadow_epoch_records(run_id,attempt_id,sequence)",
    "CREATE TRIGGER immutable_shadow_epoch_records BEFORE UPDATE ON shadow_epoch_records BEGIN SELECT RAISE(ABORT,'immutable Increment 9 shadow record'); END",
    "CREATE TRIGGER retained_shadow_epoch_records BEFORE DELETE ON shadow_epoch_records BEGIN SELECT RAISE(ABORT,'retained Increment 9 shadow record'); END",
    "CREATE TRIGGER immutable_increment9_shadow_meta BEFORE UPDATE ON increment9_shadow_meta BEGIN SELECT RAISE(ABORT,'immutable Increment 9 shadow metadata'); END",
    "CREATE TRIGGER retained_increment9_shadow_meta BEFORE DELETE ON increment9_shadow_meta BEGIN SELECT RAISE(ABORT,'retained Increment 9 shadow metadata'); END",
)
INCREMENT9_SHADOW_MIGRATION_CHECKSUM = digest_canonical(
    {
        "application_id": INCREMENT9_SHADOW_APPLICATION_ID,
        "name": INCREMENT9_SHADOW_MIGRATION_NAME,
        "schema_version": INCREMENT9_SHADOW_SCHEMA_VERSION,
        "statements": list(INCREMENT9_SHADOW_MIGRATION_STATEMENTS),
    }
)


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    return digest_canonical(
        [
            {
                "name": row[1],
                "sql": row[3],
                "table": row[2],
                "type": row[0],
            }
            for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            )
        ]
    )


def _expected_schema_fingerprint() -> str:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    try:
        for statement in INCREMENT9_SHADOW_MIGRATION_STATEMENTS:
            connection.execute(statement)
        return _schema_fingerprint(connection)
    finally:
        connection.close()


INCREMENT9_SHADOW_SCHEMA_FINGERPRINT = _expected_schema_fingerprint()


class Increment9ShadowMigrationError(ValueError):
    """The isolated shadow schema is absent, contaminated or changed."""


def _tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )


def install_increment9_shadow_schema(connection: sqlite3.Connection) -> None:
    if not isinstance(connection, sqlite3.Connection) or connection.in_transaction:
        raise Increment9ShadowMigrationError("isolated schema requires an idle SQLite connection")
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    tables = _tables(connection)
    if tables:
        verify_increment9_shadow_schema(connection)
        return
    if application_id != 0 or user_version != 0:
        raise Increment9ShadowMigrationError("refusing a non-empty or production authority identity")
    try:
        connection.execute("BEGIN EXCLUSIVE")
        for statement in INCREMENT9_SHADOW_MIGRATION_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO increment9_shadow_meta VALUES(1,?,?,?,?)",
            (
                INCREMENT9_SHADOW_SCHEMA_VERSION,
                INCREMENT9_SHADOW_MIGRATION_NAME,
                INCREMENT9_SHADOW_MIGRATION_CHECKSUM,
                INCREMENT9_SHADOW_PLAN_DIGEST,
            ),
        )
        connection.execute(f"PRAGMA application_id={INCREMENT9_SHADOW_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version={INCREMENT9_SHADOW_SCHEMA_VERSION}")
        connection.commit()
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise Increment9ShadowMigrationError("isolated shadow schema installation failed") from exc
    verify_increment9_shadow_schema(connection)


def verify_increment9_shadow_schema(connection: sqlite3.Connection) -> None:
    if not isinstance(connection, sqlite3.Connection):
        raise Increment9ShadowMigrationError("SQLite connection is required")
    if (
        connection.execute("PRAGMA application_id").fetchone()[0]
        != INCREMENT9_SHADOW_APPLICATION_ID
        or connection.execute("PRAGMA user_version").fetchone()[0]
        != INCREMENT9_SHADOW_SCHEMA_VERSION
        or _tables(connection) != ("increment9_shadow_meta", "shadow_epoch_records")
    ):
        raise Increment9ShadowMigrationError("isolated shadow schema identity differs")
    row = connection.execute(
        "SELECT schema_version,migration_name,migration_checksum,plan_digest FROM increment9_shadow_meta WHERE singleton=1"
    ).fetchone()
    if row != (
        INCREMENT9_SHADOW_SCHEMA_VERSION,
        INCREMENT9_SHADOW_MIGRATION_NAME,
        INCREMENT9_SHADOW_MIGRATION_CHECKSUM,
        INCREMENT9_SHADOW_PLAN_DIGEST,
    ):
        raise Increment9ShadowMigrationError("isolated shadow migration receipt differs")
    if _schema_fingerprint(connection) != INCREMENT9_SHADOW_SCHEMA_FINGERPRINT:
        raise Increment9ShadowMigrationError("isolated shadow schema fingerprint differs")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise Increment9ShadowMigrationError("isolated shadow integrity differs")
