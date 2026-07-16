from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Callable, Iterator

from .auth import AuthorizationDecision, VerifiedAuthenticationContext
from .canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from .migrations import MIGRATIONS, SCHEMA_VERSION, Migration
from .models import (
    AuditRecord,
    CommittedCommand,
    LedgerEvent,
    RuntimeConfiguration,
    SemanticCommand,
)
from .objects import GovernedObject, GovernedObjectStore
from .types import AggregateVersion, AuditId, CommandId, EventId, TrustScope, UtcTimestamp


class AuthorityStoreError(RuntimeError):
    """Base class for authority persistence failures."""


class UnversionedDatabaseError(AuthorityStoreError):
    pass


class UnsupportedSchemaVersionError(AuthorityStoreError):
    pass


class MigrationChecksumError(AuthorityStoreError):
    pass


class AuthorityBusyError(AuthorityStoreError):
    pass


class IdempotencyConflict(AuthorityStoreError):
    pass


class ExpectedVersionConflict(AuthorityStoreError):
    pass


class UnknownObjectReference(AuthorityStoreError):
    pass


class ObjectMetadataConflict(AuthorityStoreError):
    pass


_EXPECTED_TABLES = frozenset(
    {
        "authority_migrations",
        "governed_objects",
        "authority_aggregates",
        "authority_commands",
        "authority_aggregate_versions",
        "authority_audit_events",
        "ledger_events",
    }
)


class AuthorityStoreBase:
    """Single-writer SQLite authority boundary for Increment 1A."""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = 5_000,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = busy_timeout_ms
        self._clock = clock
        try:
            self._conn = sqlite3.connect(
                self.path,
                isolation_level=None,
                timeout=busy_timeout_ms / 1000,
            )
            self._conn.row_factory = sqlite3.Row
            self._configure_connection()
            self._migrate()
            self._validate_schema()
            self._runtime_configuration = self._read_runtime_configuration()
        except Exception:
            connection = getattr(self, "_conn", None)
            if connection is not None:
                connection.close()
            raise

    def __enter__(self) -> AuthorityStoreBase:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    @property
    def runtime_configuration(self) -> RuntimeConfiguration:
        return self._runtime_configuration

    def _configure_connection(self) -> None:
        self._conn.execute("PRAGMA foreign_keys=ON")
        mode = str(self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise AuthorityStoreError(f"journal_mode WAL unavailable: {mode}")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")

    def _read_runtime_configuration(self) -> RuntimeConfiguration:
        return RuntimeConfiguration(
            schema_version=int(self._conn.execute("PRAGMA user_version").fetchone()[0]),
            journal_mode=str(self._conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            synchronous=int(self._conn.execute("PRAGMA synchronous").fetchone()[0]),
            foreign_keys=bool(self._conn.execute("PRAGMA foreign_keys").fetchone()[0]),
            busy_timeout_ms=int(self._conn.execute("PRAGMA busy_timeout").fetchone()[0]),
        )

    def _table_names(self) -> set[str]:
        return {
            str(row[0])
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    def _migrate(self) -> None:
        tables = self._table_names()
        user_version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if user_version > SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"database schema {user_version} is newer than supported {SCHEMA_VERSION}"
            )
        if "authority_migrations" not in tables:
            if tables:
                raise UnversionedDatabaseError(
                    "refusing to adopt a non-empty unversioned authority database"
                )
            self._conn.execute(
                """CREATE TABLE authority_migrations (
                    version INTEGER PRIMARY KEY CHECK (version > 0),
                    name TEXT NOT NULL UNIQUE,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                ) STRICT"""
            )

        applied = {
            int(row["version"]): row
            for row in self._conn.execute(
                "SELECT version, name, checksum, applied_at "
                "FROM authority_migrations ORDER BY version"
            )
        }
        for migration in MIGRATIONS:
            existing = applied.get(migration.version)
            if existing is not None:
                if (
                    str(existing["name"]) != migration.name
                    or str(existing["checksum"]) != migration.checksum
                ):
                    raise MigrationChecksumError(
                        f"migration {migration.version} checksum/name mismatch"
                    )
                continue
            self._apply_migration(migration)
        final_version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if final_version != SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"database schema {final_version} does not match {SCHEMA_VERSION}"
            )

    def _apply_migration(self, migration: Migration) -> None:
        try:
            self._conn.execute("BEGIN EXCLUSIVE")
            current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if current != migration.version - 1:
                raise UnsupportedSchemaVersionError(
                    f"migration {migration.version} expected schema {migration.version - 1}, "
                    f"found {current}"
                )
            for statement in migration.statements():
                self._conn.execute(statement)
            applied_at = self._clock().to_text()
            self._conn.execute(
                "INSERT INTO authority_migrations(version, name, checksum, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, migration.checksum, applied_at),
            )
            self._conn.execute(f"PRAGMA user_version={migration.version}")
            self._conn.execute("COMMIT")
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def _validate_schema(self) -> None:
        tables = self._table_names()
        if tables != _EXPECTED_TABLES:
            raise AuthorityStoreError(
                "authority schema table mismatch: "
                f"missing={sorted(_EXPECTED_TABLES - tables)} "
                f"unexpected={sorted(tables - _EXPECTED_TABLES)}"
            )
        violations = self._conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise AuthorityStoreError("authority database foreign-key check failed")

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            yield
            self._conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            lowered = str(exc).lower()
            if "busy" in lowered or "locked" in lowered:
                raise AuthorityBusyError("authority writer remained busy") from exc
            raise AuthorityStoreError(str(exc)) from exc
        except sqlite3.DatabaseError as exc:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise AuthorityStoreError(str(exc)) from exc
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def register_governed_object(
        self,
        governed_object: GovernedObject,
        *,
        object_store: GovernedObjectStore,
    ) -> None:
        actual_size = object_store.verify(governed_object.digest)
        if actual_size != governed_object.size_bytes:
            raise ObjectMetadataConflict("governed object size metadata mismatch")
        with self._write_transaction():
            existing = self._conn.execute(
                "SELECT * FROM governed_objects WHERE digest = ?",
                (governed_object.digest,),
            ).fetchone()
            values = (
                governed_object.digest,
                governed_object.size_bytes,
                governed_object.object_class,
                governed_object.rights_status.value,
                governed_object.security_scope,
                governed_object.retention_scope,
                governed_object.installed_at.to_text(),
            )
            if existing is not None:
                existing_values = (
                    str(existing["digest"]),
                    int(existing["size_bytes"]),
                    str(existing["object_class"]),
                    str(existing["rights_status"]),
                    str(existing["security_scope"]),
                    str(existing["retention_scope"]),
                )
                if existing_values != values[:6]:
                    raise ObjectMetadataConflict(
                        "governed object identity reused with different metadata"
                    )
                return
            self._conn.execute(
                "INSERT INTO governed_objects(" 
                "digest, size_bytes, object_class, rights_status, security_scope, "
                "retention_scope, installed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    def has_governed_object(self, digest: str) -> bool:
        normalized = validate_sha256_digest(digest)
        row = self._conn.execute(
            "SELECT 1 FROM governed_objects WHERE digest = ?", (normalized,)
        ).fetchone()
        return row is not None

    def referenced_object_digests(self) -> frozenset[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT payload_object_ref FROM authority_aggregate_versions "
            "WHERE payload_object_ref IS NOT NULL"
        ).fetchall()
        return frozenset(str(row[0]) for row in rows)

