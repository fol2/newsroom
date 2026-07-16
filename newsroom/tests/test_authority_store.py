from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityStore,
    GovernedObjectStore,
    MigrationChecksumError,
    ObjectIntegrityError,
    ObjectMetadataConflict,
    RightsStatus,
    UnversionedDatabaseError,
    UnsupportedSchemaVersionError,
    UtcTimestamp,
)
from newsroom.authority.migrations import SCHEMA_VERSION

_FIXED_TIME = UtcTimestamp(datetime(2026, 7, 16, 18, 30, tzinfo=UTC))


def _clock() -> UtcTimestamp:
    return _FIXED_TIME


def test_fresh_store_applies_checked_schema_and_sqlite_profile(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    with AuthorityStore(path, busy_timeout_ms=4321, clock=_clock) as store:
        runtime = store.runtime_configuration
        assert runtime.schema_version == SCHEMA_VERSION
        assert runtime.journal_mode == "wal"
        assert runtime.synchronous == 2
        assert runtime.foreign_keys is True
        assert runtime.busy_timeout_ms == 4321
        assert store.table_count("authority_migrations") == 1

    conn = sqlite3.connect(path)
    try:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
        row = conn.execute(
            "SELECT version, name, checksum FROM authority_migrations"
        ).fetchone()
        assert row is not None
        assert int(row[0]) == 1
        assert str(row[1]) == "initial_authority_foundation"
        assert str(row[2]).startswith("sha256:")
    finally:
        conn.close()


def test_non_empty_unversioned_database_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE accidental_state(id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(UnversionedDatabaseError):
        AuthorityStore(path, clock=_clock)


def test_newer_database_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    with AuthorityStore(path, clock=_clock):
        pass

    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA user_version=99")
    finally:
        conn.close()

    with pytest.raises(UnsupportedSchemaVersionError):
        AuthorityStore(path, clock=_clock)


def test_changed_migration_checksum_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    with AuthorityStore(path, clock=_clock):
        pass

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE authority_migrations SET checksum = ? WHERE version = 1",
            ("sha256:" + "0" * 64,),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MigrationChecksumError):
        AuthorityStore(path, clock=_clock)


def test_governed_object_registration_rejects_corrupt_or_changed_metadata(
    tmp_path: Path,
) -> None:
    authority_path = tmp_path / "authority.sqlite3"
    object_store = GovernedObjectStore(tmp_path / "objects")
    governed = object_store.install(
        b"retained bytes",
        object_class="fixture.capture",
        rights_status=RightsStatus.PERMITTED,
        security_scope="authority.internal",
        retention_scope="test.short",
        installed_at=_FIXED_TIME,
    )

    with AuthorityStore(authority_path, clock=_clock) as store:
        store.register_governed_object(governed, object_store=object_store)
        store.register_governed_object(governed, object_store=object_store)

        changed = type(governed)(
            digest=governed.digest,
            size_bytes=governed.size_bytes,
            object_class="different.class",
            rights_status=governed.rights_status,
            security_scope=governed.security_scope,
            retention_scope=governed.retention_scope,
            installed_at=governed.installed_at,
        )
        with pytest.raises(ObjectMetadataConflict):
            store.register_governed_object(changed, object_store=object_store)

    object_store.path_for(governed.digest).write_bytes(b"corrupted")
    with AuthorityStore(authority_path, clock=_clock) as store:
        with pytest.raises(ObjectIntegrityError):
            store.register_governed_object(governed, object_store=object_store)
