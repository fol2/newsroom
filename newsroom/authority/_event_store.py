from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
import threading
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported CI/runtime profile is POSIX
    fcntl = None  # type: ignore[assignment]

from ._capability import _AuthorizedCommandGrant, _CapabilityIssuer
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical
from .migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    MIGRATION,
    SCHEMA_VERSION,
    apply_migration,
    schema_fingerprint,
)
from .models import CommittedCommandIdentity
from .persistence import (
    AuthenticationContextRecord,
    AuthorityPersistenceError,
    AuthoritySchemaError,
    AuthorityWriterBusy,
    AuthorizationDecisionRecord,
    CommandResultRecord,
    CommittedCommand,
    EventProvenanceRecord,
    ExpectedVersionConflict,
    IdempotencyConflict,
    LedgerEventRecord,
    UnknownCausation,
    UnsupportedPayloadMode,
)
from .service import IdempotencyIdentityConflict
from .types import AuditId, CommandId, EventId, PayloadId, UtcTimestamp, require_token


class _EventAuthorityStore:
    """Private SQLite authority writer and authenticated metadata source."""

    def __init__(
        self,
        path: Path,
        *,
        issuer: _CapabilityIssuer,
        command_service_version: str,
        busy_timeout_ms: int = 5_000,
        clock: Any = UtcTimestamp.now,
    ) -> None:
        if fcntl is None:
            raise AuthoritySchemaError("POSIX advisory locking is required")
        if not isinstance(path, Path):
            path = Path(path)
        if path.is_symlink():
            raise AuthoritySchemaError("authority database path cannot be a symlink")
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        require_token(command_service_version, field="command_service_version")
        self.path = path
        self._issuer = issuer
        self._command_service_version = command_service_version
        self._busy_timeout_ms = busy_timeout_ms
        self._clock = clock
        self._lock = threading.RLock()
        self._closed = False
        self._lock_fd: int | None = None
        self._conn: sqlite3.Connection | None = None

        self._secure_directory(path.parent)
        existed = path.exists()
        if existed:
            self._validate_owned_file(path)
        try:
            self._acquire_writer_lock()
            self._conn = sqlite3.connect(
                path,
                isolation_level=None,
                timeout=busy_timeout_ms / 1000,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._configure_connection()
            if not existed:
                os.chmod(path, 0o600)
            self._validate_owned_file(path)
            self._migrate_or_validate()
        except Exception:
            self.close()
            raise

    @staticmethod
    def _secure_directory(path: Path) -> None:
        if path.exists():
            if path.is_symlink() or not path.is_dir():
                raise AuthoritySchemaError(
                    "authority database parent must be a real directory"
                )
        else:
            path.mkdir(parents=True, mode=0o700)
            os.chmod(path, 0o700)
        info = path.stat()
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise AuthoritySchemaError("authority directory must be owned by the writer")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise AuthoritySchemaError(
                "authority directory cannot grant group or other permissions"
            )

    @staticmethod
    def _validate_owned_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise AuthoritySchemaError("authority database must be a regular file")
        info = path.stat()
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise AuthoritySchemaError("authority database must be owned by the writer")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise AuthoritySchemaError(
                "authority database cannot grant group or other permissions"
            )

    def _acquire_writer_lock(self) -> None:
        lock_path = self.path.with_name(self.path.name + ".writer.lock")
        if lock_path.is_symlink():
            raise AuthoritySchemaError("writer lock path cannot be a symlink")
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(descriptor)
            raise AuthorityWriterBusy("another authority writer is active") from exc
        self._lock_fd = descriptor

    @property
    def _connection(self) -> sqlite3.Connection:
        if self._closed or self._conn is None:
            raise AuthorityPersistenceError("authority store is closed")
        return self._conn

    def _configure_connection(self) -> None:
        conn = self._connection
        conn.execute("PRAGMA foreign_keys=ON")
        mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise AuthoritySchemaError(f"journal_mode WAL unavailable: {mode}")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_ms)}")

    def _table_names(self) -> set[str]:
        return {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    def _migrate_or_validate(self) -> None:
        conn = self._connection
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = self._table_names()
        if version > SCHEMA_VERSION:
            raise AuthoritySchemaError(
                f"database schema {version} is newer than supported {SCHEMA_VERSION}"
            )
        if version == 0:
            if tables:
                raise AuthoritySchemaError(
                    "refusing to adopt a non-empty unversioned authority database"
                )
            apply_migration(conn, applied_at=self._clock().to_text())
        self._validate_schema()

    def _validate_schema(self) -> None:
        conn = self._connection
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise AuthoritySchemaError(
                f"database schema {version} does not match {SCHEMA_VERSION}"
            )
        history_rows = conn.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
        history = tuple(
            (int(row["version"]), str(row["name"]), str(row["checksum"]))
            for row in history_rows
        )
        if history != EXPECTED_MIGRATION_HISTORY:
            raise AuthoritySchemaError(
                f"authority migration history mismatch: {history!r}"
            )
        actual_fingerprint = schema_fingerprint(conn)
        if actual_fingerprint != EXPECTED_SCHEMA_FINGERPRINT:
            raise AuthoritySchemaError("authority schema fingerprint mismatch")
        quick = [str(row[0]) for row in conn.execute("PRAGMA quick_check").fetchall()]
        if quick != ["ok"]:
            raise AuthoritySchemaError(f"authority quick_check failed: {quick!r}")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise AuthoritySchemaError("authority foreign-key check failed")
        if not bool(conn.execute("PRAGMA foreign_keys").fetchone()[0]):
            raise AuthoritySchemaError("SQLite foreign keys are not enabled")
        if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
            raise AuthoritySchemaError("SQLite WAL mode is not active")
        if int(conn.execute("PRAGMA synchronous").fetchone()[0]) != 2:
            raise AuthoritySchemaError("SQLite synchronous=FULL is not active")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connection
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            lowered = str(exc).lower()
            if "locked" in lowered or "busy" in lowered:
                raise AuthorityWriterBusy("authority writer remained busy") from exc
            raise AuthorityPersistenceError(str(exc)) from exc
        except sqlite3.DatabaseError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise AuthorityPersistenceError(str(exc)) from exc
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            if self._lock_fd is not None:
                try:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(self._lock_fd)
                    self._lock_fd = None

    def __enter__(self) -> _EventAuthorityStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def find(
        self, *, idempotency_namespace: str, idempotency_key: str
    ) -> CommittedCommandIdentity | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT c.command_id,c.command_type,c.command_definition_version,"
                "c.command_definition_digest,c.idempotency_namespace,c.idempotency_key,"
                "c.stable_semantic_request_digest,a.principal_id,a.authority_domain "
                "FROM authority_commands c JOIN authentication_contexts a "
                "ON a.authentication_context_id=c.authentication_context_id "
                "WHERE c.idempotency_namespace=? AND c.idempotency_key=?",
                (idempotency_namespace, idempotency_key),
            ).fetchone()
            if row is None:
                return None
            return CommittedCommandIdentity(
                command_id=str(row["command_id"]),
                authority_domain=str(row["authority_domain"]),
                principal_id=str(row["principal_id"]),
                command_type=str(row["command_type"]),
                idempotency_namespace=str(row["idempotency_namespace"]),
                idempotency_key=str(row["idempotency_key"]),
                command_definition_version=str(row["command_definition_version"]),
                command_definition_digest=str(row["command_definition_digest"]),
                stable_semantic_request_digest=str(
                    row["stable_semantic_request_digest"]
                ),
            )

    def commit(self, grant: _AuthorizedCommandGrant) -> CommittedCommand:
        self._issuer.verify(grant)
        with self._lock, self._transaction() as conn:
            existing = conn.execute(
                "SELECT command_id,command_definition_version,"
                "command_definition_digest,stable_semantic_request_digest,"
                "result_digest,result_bytes FROM authority_commands "
                "WHERE idempotency_namespace=? AND idempotency_key=?",
                (grant.idempotency_namespace, grant.idempotency_key),
            ).fetchone()
            if existing is not None:
                return self._replay_existing(grant, existing)
            if grant.replay_of_command_id is not None:
                raise IdempotencyConflict(
                    "command boundary expected a replay but no committed row exists"
                )
            if grant.payload.kind not in {"INLINE", "NO_PAYLOAD"}:
                raise UnsupportedPayloadMode(
                    "object-admission payload persistence belongs to Increment 1A2b"
                )

            recorded_at = self._clock().to_text()
            self._persist_definition(conn, grant, recorded_at=recorded_at)
            self._persist_security(conn, grant, recorded_at=recorded_at)
            self._validate_causation(conn, grant)
            current_version, new_version = self._resolve_version(conn, grant)

            payload_bytes = grant.payload.inline_bytes
            if payload_bytes is None:
                raise AuthorityPersistenceError("retained payload bytes are required")
            if digest_bytes(payload_bytes) != grant.payload.digest:
                raise AuthorityPersistenceError("retained payload digest mismatch")

            command_id = str(CommandId.new())
            event_id = str(EventId.new())
            audit_id = str(AuditId.new())
            payload_id = str(PayloadId.new())
            ledger_seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(ledger_seq),0)+1 FROM ledger_events"
                ).fetchone()[0]
            )
            result_bytes = canonical_json_bytes(
                {
                    "command_id": command_id,
                    "aggregate_type": grant.definition.aggregate_type,
                    "aggregate_id": grant.aggregate_id,
                    "aggregate_version": new_version,
                    "ledger_seq": ledger_seq,
                    "event_id": event_id,
                }
            )
            result_digest = digest_bytes(result_bytes)

            conn.execute(
                "INSERT INTO authority_payloads(" 
                "payload_id,mode,schema_version,payload_digest,payload_bytes,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    payload_id,
                    grant.payload.kind,
                    grant.payload.schema_version,
                    grant.payload.digest,
                    payload_bytes,
                    recorded_at,
                ),
            )
            conn.execute(
                "INSERT INTO authority_commands(" 
                "command_id,command_type,command_definition_version,"
                "command_definition_digest,aggregate_type,aggregate_id,"
                "expected_aggregate_version,idempotency_namespace,idempotency_key,"
                "stable_semantic_request_digest,authentication_context_id,"
                "authorization_request_digest,authorization_decision_id,"
                "result_digest,result_bytes,committed_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    command_id,
                    grant.command_type,
                    grant.definition.definition_version,
                    grant.definition.digest,
                    grant.definition.aggregate_type,
                    grant.aggregate_id,
                    grant.expected_aggregate_version,
                    grant.idempotency_namespace,
                    grant.idempotency_key,
                    grant.stable_semantic_request_digest,
                    str(grant.authentication.authentication_context_id),
                    grant.authorization_request.request_digest,
                    str(grant.authorization.authorization_decision_id),
                    result_digest,
                    result_bytes,
                    recorded_at,
                ),
            )
            if current_version is None:
                conn.execute(
                    "INSERT INTO authority_aggregates(" 
                    "aggregate_type,aggregate_id,current_version,created_at,updated_at) "
                    "VALUES(?,?,?,?,?)",
                    (
                        grant.definition.aggregate_type,
                        grant.aggregate_id,
                        new_version,
                        recorded_at,
                        recorded_at,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE authority_aggregates SET current_version=?,updated_at=? "
                    "WHERE aggregate_type=? AND aggregate_id=?",
                    (
                        new_version,
                        recorded_at,
                        grant.definition.aggregate_type,
                        grant.aggregate_id,
                    ),
                )
            conn.execute(
                "INSERT INTO authority_aggregate_versions(" 
                "aggregate_type,aggregate_id,aggregate_version,command_id,"
                "payload_id,trust_scope,recorded_at) VALUES(?,?,?,?,?,?,?)",
                (
                    grant.definition.aggregate_type,
                    grant.aggregate_id,
                    new_version,
                    command_id,
                    payload_id,
                    grant.definition.trust_scope.value,
                    recorded_at,
                ),
            )
            conn.execute(
                "INSERT INTO authority_audit_events(" 
                "audit_id,command_id,authentication_context_id,"
                "authorization_request_digest,authorization_decision_id,"
                "event_type,detail_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    audit_id,
                    command_id,
                    str(grant.authentication.authentication_context_id),
                    grant.authorization_request.request_digest,
                    str(grant.authorization.authorization_decision_id),
                    grant.definition.event_type,
                    digest_canonical(grant.unsigned_value()),
                    recorded_at,
                ),
            )
            conn.execute(
                "INSERT INTO ledger_events(" 
                "ledger_seq,event_id,event_type,event_schema_version,aggregate_type,"
                "aggregate_id,aggregate_version,command_id,payload_id,principal_id,"
                "authentication_context_id,authorization_request_digest,"
                "authorization_decision_id,command_definition_version,"
                "command_definition_digest,correlation_id,causation_kind,"
                "causation_identifier,causation_external_system,security_scope,"
                "retention_scope,trust_scope,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ledger_seq,
                    event_id,
                    grant.definition.event_type,
                    grant.definition.event_schema_version,
                    grant.definition.aggregate_type,
                    grant.aggregate_id,
                    new_version,
                    command_id,
                    payload_id,
                    grant.authentication.principal_id,
                    str(grant.authentication.authentication_context_id),
                    grant.authorization_request.request_digest,
                    str(grant.authorization.authorization_decision_id),
                    grant.definition.definition_version,
                    grant.definition.digest,
                    grant.correlation_id,
                    grant.causation_kind,
                    grant.causation_identifier,
                    grant.causation_external_system,
                    grant.definition.security_scope,
                    grant.definition.retention_scope,
                    grant.definition.trust_scope.value,
                    recorded_at,
                ),
            )
            return CommittedCommand(
                command_id=command_id,
                aggregate_type=grant.definition.aggregate_type,
                aggregate_id=grant.aggregate_id,
                aggregate_version=new_version,
                ledger_seq=ledger_seq,
                event_id=event_id,
                result_digest=result_digest,
                replayed=False,
            )

    def _replay_existing(
        self, grant: _AuthorizedCommandGrant, row: sqlite3.Row
    ) -> CommittedCommand:
        if str(row["stable_semantic_request_digest"]) != grant.stable_semantic_request_digest:
            raise IdempotencyIdentityConflict(
                "idempotency identity belongs to a different semantic command"
            )
        if (
            str(row["command_definition_version"])
            != grant.definition.definition_version
            or str(row["command_definition_digest"]) != grant.definition.digest
        ):
            raise IdempotencyConflict(
                "replay grant does not use the committed command definition"
            )
        if (
            grant.replay_of_command_id is not None
            and str(row["command_id"]) != grant.replay_of_command_id
        ):
            raise IdempotencyConflict("replay command identity mismatch")
        return self._decode_result(
            bytes(row["result_bytes"]), str(row["result_digest"]), replayed=True
        )

    def _persist_definition(
        self, conn: sqlite3.Connection, grant: _AuthorizedCommandGrant, *, recorded_at: str
    ) -> None:
        definition_bytes = canonical_json_bytes(grant.definition.canonical_value())
        if digest_bytes(definition_bytes) != grant.definition.digest:
            raise AuthorityPersistenceError("command definition digest mismatch")
        conn.execute(
            "INSERT OR IGNORE INTO command_definitions(" 
            "definition_digest,command_type,definition_version,canonical_bytes,"
            "registered_at) VALUES(?,?,?,?,?)",
            (
                grant.definition.digest,
                grant.definition.command_type,
                grant.definition.definition_version,
                definition_bytes,
                recorded_at,
            ),
        )
        row = conn.execute(
            "SELECT command_type,definition_version,canonical_bytes "
            "FROM command_definitions WHERE definition_digest=?",
            (grant.definition.digest,),
        ).fetchone()
        if row is None or (
            str(row["command_type"]) != grant.definition.command_type
            or str(row["definition_version"]) != grant.definition.definition_version
            or bytes(row["canonical_bytes"]) != definition_bytes
        ):
            raise AuthorityPersistenceError("command definition identity conflict")

    def _persist_security(
        self, conn: sqlite3.Connection, grant: _AuthorizedCommandGrant, *, recorded_at: str
    ) -> None:
        auth_bytes = canonical_json_bytes(grant.authentication.canonical_value())
        conn.execute(
            "INSERT OR IGNORE INTO authentication_contexts(" 
            "authentication_context_id,principal_id,authority_domain,"
            "authentication_method,assurance_class,credential_binding_digest,"
            "authenticated_at,expires_at,canonical_bytes,canonical_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                str(grant.authentication.authentication_context_id),
                grant.authentication.principal_id,
                grant.authentication.authority_domain,
                grant.authentication.authentication_method,
                grant.authentication.assurance_class,
                grant.authentication.credential_binding_digest,
                grant.authentication.authenticated_at.to_text(),
                grant.authentication.expires_at.to_text(),
                auth_bytes,
                grant.authentication.digest,
            ),
        )
        self._require_exact_bytes(
            conn,
            table="authentication_contexts",
            key_column="authentication_context_id",
            key=str(grant.authentication.authentication_context_id),
            bytes_column="canonical_bytes",
            expected=auth_bytes,
        )

        request_bytes = canonical_json_bytes(
            grant.authorization_request.canonical_value()
        )
        conn.execute(
            "INSERT OR IGNORE INTO authorization_requests(" 
            "request_digest,authentication_context_id,canonical_bytes,recorded_at) "
            "VALUES(?,?,?,?)",
            (
                grant.authorization_request.request_digest,
                str(grant.authentication.authentication_context_id),
                request_bytes,
                recorded_at,
            ),
        )
        self._require_exact_bytes(
            conn,
            table="authorization_requests",
            key_column="request_digest",
            key=grant.authorization_request.request_digest,
            bytes_column="canonical_bytes",
            expected=request_bytes,
        )

        decision_bytes = canonical_json_bytes(grant.authorization.canonical_value())
        scopes_bytes = canonical_json_bytes(list(grant.authorization.effective_scopes))
        conn.execute(
            "INSERT OR IGNORE INTO authorization_decisions(" 
            "authorization_decision_id,authentication_context_id,"
            "authorization_request_digest,authorization_policy_version,"
            "effective_scopes,effective_scope_digest,allowed,reason_code,"
            "decided_at,canonical_bytes,canonical_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(grant.authorization.authorization_decision_id),
                str(grant.authentication.authentication_context_id),
                grant.authorization_request.request_digest,
                grant.authorization.authorization_policy_version,
                scopes_bytes,
                grant.authorization.effective_scope_digest,
                int(grant.authorization.allowed),
                grant.authorization.reason_code,
                grant.authorization.decided_at.to_text(),
                decision_bytes,
                grant.authorization.digest,
            ),
        )
        self._require_exact_bytes(
            conn,
            table="authorization_decisions",
            key_column="authorization_decision_id",
            key=str(grant.authorization.authorization_decision_id),
            bytes_column="canonical_bytes",
            expected=decision_bytes,
        )

    @staticmethod
    def _require_exact_bytes(
        conn: sqlite3.Connection,
        *,
        table: str,
        key_column: str,
        key: str,
        bytes_column: str,
        expected: bytes,
    ) -> None:
        allowed = {
            ("authentication_contexts", "authentication_context_id", "canonical_bytes"),
            ("authorization_requests", "request_digest", "canonical_bytes"),
            ("authorization_decisions", "authorization_decision_id", "canonical_bytes"),
        }
        if (table, key_column, bytes_column) not in allowed:
            raise AuthorityPersistenceError("unsupported immutable record check")
        row = conn.execute(
            f"SELECT {bytes_column} FROM {table} WHERE {key_column}=?", (key,)
        ).fetchone()
        if row is None or bytes(row[0]) != expected:
            raise AuthorityPersistenceError(f"immutable {table} identity conflict")

    @staticmethod
    def _validate_causation(
        conn: sqlite3.Connection, grant: _AuthorizedCommandGrant
    ) -> None:
        if grant.causation_kind == "COMMAND":
            row = conn.execute(
                "SELECT 1 FROM authority_commands WHERE command_id=?",
                (grant.causation_identifier,),
            ).fetchone()
            if row is None:
                raise UnknownCausation("causation command does not resolve")
        elif grant.causation_kind == "EVENT":
            row = conn.execute(
                "SELECT 1 FROM ledger_events WHERE event_id=?",
                (grant.causation_identifier,),
            ).fetchone()
            if row is None:
                raise UnknownCausation("causation event does not resolve")

    @staticmethod
    def _resolve_version(
        conn: sqlite3.Connection, grant: _AuthorizedCommandGrant
    ) -> tuple[int | None, int]:
        row = conn.execute(
            "SELECT current_version FROM authority_aggregates "
            "WHERE aggregate_type=? AND aggregate_id=?",
            (grant.definition.aggregate_type, grant.aggregate_id),
        ).fetchone()
        current = None if row is None else int(row["current_version"])
        if current is None:
            if grant.expected_aggregate_version != 0:
                raise ExpectedVersionConflict(
                    "create command requires expected aggregate version 0"
                )
            return None, 1
        if grant.expected_aggregate_version != current:
            raise ExpectedVersionConflict(
                f"expected aggregate version {grant.expected_aggregate_version}, "
                f"current is {current}"
            )
        return current, current + 1

    @staticmethod
    def _decode_canonical(data: bytes) -> Any:
        try:
            value = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError("stored canonical JSON is invalid") from exc
        if canonical_json_bytes(value) != data:
            raise AuthorityPersistenceError("stored JSON is not canonical")
        return value

    def _decode_result(
        self, data: bytes, expected_digest: str, *, replayed: bool
    ) -> CommittedCommand:
        if digest_bytes(data) != expected_digest:
            raise AuthorityPersistenceError("stored command result digest mismatch")
        value = self._decode_canonical(data)
        if not isinstance(value, dict):
            raise AuthorityPersistenceError("stored command result is not an object")
        return CommittedCommand(
            command_id=str(value["command_id"]),
            aggregate_type=str(value["aggregate_type"]),
            aggregate_id=str(value["aggregate_id"]),
            aggregate_version=int(value["aggregate_version"]),
            ledger_seq=int(value["ledger_seq"]),
            event_id=str(value["event_id"]),
            result_digest=expected_digest,
            replayed=replayed,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> LedgerEventRecord:
        return LedgerEventRecord(
            ledger_seq=int(row["ledger_seq"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            event_schema_version=int(row["event_schema_version"]),
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=str(row["aggregate_id"]),
            aggregate_version=int(row["aggregate_version"]),
            command_id=str(row["command_id"]),
            payload_id=str(row["payload_id"]),
            principal_id=str(row["principal_id"]),
            authentication_context_id=str(row["authentication_context_id"]),
            authorization_request_digest=str(row["authorization_request_digest"]),
            authorization_decision_id=str(row["authorization_decision_id"]),
            command_definition_version=str(row["command_definition_version"]),
            command_definition_digest=str(row["command_definition_digest"]),
            correlation_id=(None if row["correlation_id"] is None else str(row["correlation_id"])),
            causation_kind=(None if row["causation_kind"] is None else str(row["causation_kind"])),
            causation_identifier=(None if row["causation_identifier"] is None else str(row["causation_identifier"])),
            causation_external_system=(None if row["causation_external_system"] is None else str(row["causation_external_system"])),
            security_scope=str(row["security_scope"]),
            retention_scope=str(row["retention_scope"]),
            trust_scope=str(row["trust_scope"]),
            recorded_at=str(row["recorded_at"]),
        )

    def events_after(self, ledger_seq: int, *, limit: int) -> tuple[LedgerEventRecord, ...]:
        if isinstance(ledger_seq, bool) or not isinstance(ledger_seq, int) or ledger_seq < 0:
            raise ValueError("ledger_seq must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("event limit must be between 1 and 1000")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM ledger_events WHERE ledger_seq>? "
                "ORDER BY ledger_seq LIMIT ?",
                (ledger_seq, limit),
            ).fetchall()
            return tuple(self._event_from_row(row) for row in rows)

    def event_provenance(self, event_id: str) -> EventProvenanceRecord:
        with self._lock:
            event_row = self._connection.execute(
                "SELECT * FROM ledger_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if event_row is None:
                raise KeyError(event_id)
            auth_row = self._connection.execute(
                "SELECT * FROM authentication_contexts "
                "WHERE authentication_context_id=?",
                (event_row["authentication_context_id"],),
            ).fetchone()
            decision_row = self._connection.execute(
                "SELECT * FROM authorization_decisions "
                "WHERE authorization_decision_id=?",
                (event_row["authorization_decision_id"],),
            ).fetchone()
            if auth_row is None or decision_row is None:
                raise AuthorityPersistenceError("event security provenance is incomplete")
            scopes_value = self._decode_canonical(bytes(decision_row["effective_scopes"]))
            if not isinstance(scopes_value, list) or not all(
                isinstance(item, str) for item in scopes_value
            ):
                raise AuthorityPersistenceError("stored effective scopes are invalid")
            return EventProvenanceRecord(
                event=self._event_from_row(event_row),
                authentication=AuthenticationContextRecord(
                    authentication_context_id=str(auth_row["authentication_context_id"]),
                    principal_id=str(auth_row["principal_id"]),
                    authority_domain=str(auth_row["authority_domain"]),
                    authentication_method=str(auth_row["authentication_method"]),
                    assurance_class=str(auth_row["assurance_class"]),
                    credential_binding_digest=str(auth_row["credential_binding_digest"]),
                    authenticated_at=str(auth_row["authenticated_at"]),
                    expires_at=str(auth_row["expires_at"]),
                    canonical_digest=str(auth_row["canonical_digest"]),
                ),
                authorization=AuthorizationDecisionRecord(
                    authorization_decision_id=str(decision_row["authorization_decision_id"]),
                    authentication_context_id=str(decision_row["authentication_context_id"]),
                    authorization_request_digest=str(decision_row["authorization_request_digest"]),
                    authorization_policy_version=str(decision_row["authorization_policy_version"]),
                    effective_scopes=tuple(scopes_value),
                    effective_scope_digest=str(decision_row["effective_scope_digest"]),
                    allowed=bool(decision_row["allowed"]),
                    reason_code=str(decision_row["reason_code"]),
                    decided_at=str(decision_row["decided_at"]),
                    canonical_digest=str(decision_row["canonical_digest"]),
                ),
            )

    def command_result(self, command_id: str) -> CommandResultRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT command_id,result_digest,result_bytes FROM authority_commands "
                "WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if row is None:
                raise KeyError(command_id)
            data = bytes(row["result_bytes"])
            digest = str(row["result_digest"])
            self._decode_result(data, digest, replayed=False)
            return CommandResultRecord(
                command_id=str(row["command_id"]),
                result_digest=digest,
                result_bytes=data,
            )

    # Test-only inspection is intentionally private and never exported.
    def _execute_test_sql(self, sql: str) -> None:
        with self._lock:
            self._connection.execute(sql)
