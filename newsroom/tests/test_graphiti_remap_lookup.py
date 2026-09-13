"""Legacy remap lookups remain exact and bounded for native no-change ticks."""
from __future__ import annotations

import sqlite3

import pytest

from newsroom.control_plane.store import (
    _remapped_ingest_aliases,
    connect,
    ensure_reconciliation_schema,
    graphiti_failure_state,
    has_graphiti_ingest,
    insert_graphiti_ingest,
)


_INDEX = "idx_effective_revision_remap_ingest"
_TABLE = "unpublished_effective_revision_remap"
_AT = "2026-01-01T00:00:00.000000Z"


def _add_remaps(connection, count):
    connection.executemany(
        f"INSERT INTO {_TABLE}(mapping_id,source_id,item_key,revision_digest,"
        "new_first_observed_at,kind,old_ingest_id,new_ingest_id,at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ((f"mapping-{i}", "UK-01", "item", "sha256:" + "a" * 64,
          _AT, "RETAINED_LINEAGE_REMAP", f"old-{i}", f"new-{i}", _AT)
         for i in range(count)),
    )


@pytest.mark.parametrize("unrelated", (200, 5000))
def test_remap_helpers_do_not_walk_unrelated_history(tmp_path, unrelated):
    connection = connect(str(tmp_path / "remaps.sqlite3"))
    try:
        _add_remaps(connection, unrelated)
        for i, alias in enumerate(("old-z", "old-a", "old-z", None, "")):
            connection.execute(
                f"INSERT INTO {_TABLE}(mapping_id,source_id,item_key,revision_digest,"
                "new_first_observed_at,kind,old_ingest_id,new_ingest_id,at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (f"selected-{i}", "UK-01", "item", "sha256:" + "b" * 64,
                 _AT, "RETAINED_LINEAGE_REMAP", alias, "selected", _AT),
            )
        insert_graphiti_ingest(
            connection, ingest_id="old-z", source_id="UK-01", item_key="item",
            outcome="COMPLETE", proposal_count=0, entity_count=0,
            relation_count=0, failure_code="NONE", temporal_basis="SOURCE_UPDATED",
            reference_time=_AT, generation_id="generation", receipt_digest="sha256:receipt",
        )
        connection.execute(
            "INSERT INTO unpublished_graphiti_failures VALUES (?,?,?,?,?,?,?,?)",
            ("old-a", "UK-01", "item", 3, "FAILED", "PROVIDER_ERROR", 1, _AT),
        )
        connection.commit()
        before = connection.total_changes
        for _ in range(2):
            progress = []
            statements = []
            connection.set_progress_handler(lambda: progress.append(1) or 0, 100)
            connection.set_trace_callback(statements.append)
            try:
                # Preserve prior rowid order, duplicates and null/empty exclusion.
                assert _remapped_ingest_aliases(connection, "selected") == (
                    "old-z", "old-a", "old-z",
                )
                assert has_graphiti_ingest(connection, "absent") is False
                assert graphiti_failure_state(connection, "absent") == (0, False)
                assert has_graphiti_ingest(connection, "selected") is True
                assert graphiti_failure_state(connection, "selected") == (3, True)
            finally:
                connection.set_progress_handler(None, 0)
                connection.set_trace_callback(None)
            assert len(progress) * 100 < 3000
            lookups = [sql for sql in statements if sql.startswith("SELECT old_ingest_id")]
            assert len(lookups) == 5
            for sql in lookups:
                plan = [str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + sql)]
                assert any(f"SEARCH {_TABLE} USING COVERING INDEX {_INDEX}" in row for row in plan)
        assert connection.total_changes == before
    finally:
        connection.close()


def test_existing_store_installs_index_without_changing_remaps_on_reopen(tmp_path):
    path = str(tmp_path / "existing.sqlite3")
    connection = connect(path)
    _add_remaps(connection, 3)
    connection.execute(f"DROP INDEX {_INDEX}")
    connection.commit()
    before = connection.execute(f"SELECT rowid,* FROM {_TABLE} ORDER BY rowid").fetchall()
    connection.close()
    for _ in range(2):
        connection = connect(path)
        try:
            assert connection.execute(f"SELECT rowid,* FROM {_TABLE} ORDER BY rowid").fetchall() == before
            assert [row[2] for row in connection.execute(f"PRAGMA index_info({_INDEX})")] == [
                "new_ingest_id", "old_ingest_id",
            ]
            assert _remapped_ingest_aliases(connection, "new-1") == ("old-1",)
        finally:
            connection.close()


_LEGACY_SCHEMA = """CREATE TABLE {prefix}unpublished_effective_revision_remap(
    mapping_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,item_key TEXT NOT NULL,
    revision_digest TEXT NOT NULL,old_observed_fallback_at TEXT,
    new_first_observed_at TEXT NOT NULL,kind TEXT NOT NULL,
    retention_window_bounded_inaccuracy INTEGER NOT NULL DEFAULT 0
        CHECK(retention_window_bounded_inaccuracy IN (0,1)),
    old_ingest_id TEXT,at TEXT NOT NULL)"""


@pytest.mark.parametrize("schema", ("main", "unpublished"))
def test_legacy_remap_column_upgrade_creates_index_in_its_own_schema(tmp_path, schema):
    connection = sqlite3.connect(tmp_path / "main.sqlite3")
    try:
        if schema != "main":
            # The same index name in main must not hide the attached store index.
            ensure_reconciliation_schema(connection)
            connection.execute("ATTACH DATABASE ? AS unpublished", (str(tmp_path / "attached.sqlite3"),))
        prefix = f"{schema}."
        connection.execute(_LEGACY_SCHEMA.format(prefix=prefix))
        connection.execute(
            f"INSERT INTO {prefix}{_TABLE} VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("mapping", "UK-01", "item", "sha256:" + "a" * 64,
             None, _AT, "RETAINED_LINEAGE_REMAP", 0, "old", _AT),
        )
        connection.commit()
        before = connection.execute(f"SELECT rowid,* FROM {prefix}{_TABLE}").fetchone()
        for _ in range(2):
            ensure_reconciliation_schema(connection, schema=schema)
            after = connection.execute(f"SELECT rowid,* FROM {prefix}{_TABLE}").fetchone()
            assert after == (*before, None, "", "")
            assert [row[2] for row in connection.execute(f"PRAGMA {schema}.index_info({_INDEX})")] == [
                "new_ingest_id", "old_ingest_id",
            ]
    finally:
        connection.close()


@pytest.mark.parametrize("caller_transaction", (False, True))
def test_remap_index_creation_failure_preserves_transaction_and_legacy_schema(caller_transaction):
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(_LEGACY_SCHEMA.format(prefix=""))
        before = connection.execute("SELECT name,sql FROM sqlite_schema ORDER BY name").fetchall()
        if caller_transaction:
            connection.execute("BEGIN IMMEDIATE")
        connection.set_authorizer(
            lambda action, name, *_: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_CREATE_INDEX and name == _INDEX
            else sqlite3.SQLITE_OK
        )
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ensure_reconciliation_schema(connection)
        connection.set_authorizer(None)
        assert connection.in_transaction is caller_transaction
        if caller_transaction:
            connection.rollback()
        assert connection.execute("SELECT name,sql FROM sqlite_schema ORDER BY name").fetchall() == before
    finally:
        connection.close()
