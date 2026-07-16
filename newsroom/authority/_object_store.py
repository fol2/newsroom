from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

from ._blob_store import PinnedBlob, StagedBlob, _BlobStore
from ._capability import (
    _AuthorizedAdmissionGrant,
    _AuthorizedCommandGrant,
    _AuthorizedMaintenanceGrant,
    _CapabilityIssuer,
)
from ._event_store import _EventAuthorityStore
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical
from .migrations import apply_migration, schema_fingerprint
from .models import CommandDefinition, ObjectAdmissionDescriptor
from .object_migrations import (
    EXPECTED_OBJECT_MIGRATION_HISTORY,
    EXPECTED_OBJECT_SCHEMA_FINGERPRINT,
    OBJECT_SCHEMA_VERSION,
    apply_object_migration,
)
from .objects import (
    HydratedObject,
    ObjectAdmissionReceipt,
    ObjectDeletionReceipt,
    ObjectHydrationDenied,
    ObjectIntegrityError,
    ObjectLifecycleError,
)
from .persistence import (
    AuthorityPersistenceError,
    AuthoritySchemaError,
    CommittedCommand,
    IdempotencyConflict,
    UnsupportedPayloadMode,
)
from .service import IdempotencyIdentityConflict
from .types import (
    AuditId,
    EventId,
    ObjectAdmissionId,
    PayloadId,
    RightsDecisionId,
    UtcTimestamp,
)


class _ObjectAuthorityStore(_EventAuthorityStore):
    """A2b authority writer coordinating SQLite state with durable blob bytes."""

    def __init__(
        self,
        path: Path,
        *,
        issuer: _CapabilityIssuer,
        blob_store: _BlobStore,
        command_service_version: str,
        busy_timeout_ms: int = 5_000,
        clock: Any = UtcTimestamp.now,
        staging_grace_seconds: int = 0,
    ) -> None:
        self._blob_store = blob_store
        self._staging_grace_seconds = staging_grace_seconds
        try:
            super().__init__(
                path,
                issuer=issuer,
                command_service_version=command_service_version,
                busy_timeout_ms=busy_timeout_ms,
                clock=clock,
            )
            self._reconcile_startup()
        except Exception:
            try:
                self.close()
            finally:
                raise

    def _migrate_or_validate(self) -> None:
        conn = self._connection
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = self._table_names()
        if version > OBJECT_SCHEMA_VERSION:
            raise AuthoritySchemaError(
                f"database schema {version} is newer than supported {OBJECT_SCHEMA_VERSION}"
            )
        if version == 0:
            if tables:
                raise AuthoritySchemaError(
                    "refusing to adopt a non-empty unversioned authority database"
                )
            apply_migration(conn, applied_at=self._clock().to_text())
            version = 1
        if version == 1:
            apply_object_migration(conn, applied_at=self._clock().to_text())
        self._validate_schema()

    def _validate_schema(self) -> None:
        conn = self._connection
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != OBJECT_SCHEMA_VERSION:
            raise AuthoritySchemaError(
                f"database schema {version} does not match {OBJECT_SCHEMA_VERSION}"
            )
        rows = conn.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
        history = tuple(
            (int(row["version"]), str(row["name"]), str(row["checksum"]))
            for row in rows
        )
        if history != EXPECTED_OBJECT_MIGRATION_HISTORY:
            raise AuthoritySchemaError(
                f"authority migration history mismatch: {history!r}"
            )
        if schema_fingerprint(conn) != EXPECTED_OBJECT_SCHEMA_FINGERPRINT:
            raise AuthoritySchemaError("governed object schema fingerprint mismatch")
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

    def _reconcile_startup(self) -> None:
        with self._lock:
            cutoff = time.time() - max(0, self._staging_grace_seconds)
            self._blob_store.cleanup_staging(older_than_epoch=cutoff)
            rows = self._connection.execute(
                "SELECT blob_digest,size_bytes,state FROM blob_records "
                "WHERE state IN ('ACTIVE','DELETION_PENDING')"
            ).fetchall()
            for row in rows:
                digest = str(row["blob_digest"])
                size = int(row["size_bytes"])
                state = str(row["state"])
                try:
                    self._blob_store.verify(digest, expected_size=size)
                except Exception as exc:
                    if state == "DELETION_PENDING" and not self._blob_store.path_for(digest).exists():
                        continue
                    raise ObjectLifecycleError(
                        f"authoritative blob {digest} is missing or corrupt during reconciliation"
                    ) from exc

    def find_admission_operation(
        self, *, idempotency_namespace: str, idempotency_key: str
    ) -> ObjectAdmissionReceipt | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT result_digest,result_bytes FROM object_admission_operations "
                "WHERE idempotency_namespace=? AND idempotency_key=?",
                (idempotency_namespace, idempotency_key),
            ).fetchone()
            if row is None:
                return None
            receipt = self._decode_admission_receipt(
                bytes(row["result_bytes"]), str(row["result_digest"]), replayed=True
            )
            self._blob_store.verify(
                receipt.blob_digest, expected_size=receipt.size_bytes
            )
            return receipt

    def resolve(self, admission_id: object) -> ObjectAdmissionDescriptor:
        if not isinstance(admission_id, ObjectAdmissionId):
            raise TypeError("admission lookup requires ObjectAdmissionId")
        now = self._clock()
        with self._lock:
            row = self._admission_row(str(admission_id))
            active = self._admission_is_current(row, now=now)
            return ObjectAdmissionDescriptor(
                admission_id=admission_id,
                blob_digest=str(row["blob_digest"]),
                object_class=str(row["object_class"]),
                allowed_use=str(row["allowed_use"]),
                security_scope=str(row["security_scope"]),
                retention_scope=str(row["retention_scope"]),
                active=active,
            )

    def admission_security(self, admission_id: ObjectAdmissionId) -> sqlite3.Row:
        with self._lock:
            return self._admission_row(str(admission_id))

    def activate_admission(
        self,
        admission_grant: _AuthorizedAdmissionGrant,
        event_grant: _AuthorizedCommandGrant,
        staged: StagedBlob,
    ) -> ObjectAdmissionReceipt:
        self._issuer.verify_admission(admission_grant)
        self._issuer.verify(event_grant)
        if event_grant.aggregate_id != str(admission_grant.admission_id):
            raise ObjectLifecycleError("admission event aggregate identity mismatch")
        if staged.blob_digest != admission_grant.blob_digest:
            raise ObjectIntegrityError("staged bytes do not match the admission grant")
        if staged.size_bytes != admission_grant.size_bytes:
            raise ObjectIntegrityError("staged size does not match the admission grant")
        with self._lock:
            existing = self.find_admission_operation(
                idempotency_namespace=admission_grant.idempotency_namespace,
                idempotency_key=admission_grant.idempotency_key,
            )
            if existing is not None:
                self._blob_store.discard_stage(staged)
                return existing
            self._blob_store.install(staged)
            with self._blob_store.pin(
                admission_grant.blob_digest,
                expected_size=admission_grant.size_bytes,
            ) as pinned:
                with self._transaction() as conn:
                    existing_row = conn.execute(
                        "SELECT result_digest,result_bytes FROM object_admission_operations "
                        "WHERE idempotency_namespace=? AND idempotency_key=?",
                        (
                            admission_grant.idempotency_namespace,
                            admission_grant.idempotency_key,
                        ),
                    ).fetchone()
                    if existing_row is not None:
                        return self._decode_admission_receipt(
                            bytes(existing_row["result_bytes"]),
                            str(existing_row["result_digest"]),
                            replayed=True,
                        )
                    now = self._clock()
                    admission_grant.rights.require_current(now)
                    self._persist_security(
                        conn, event_grant, recorded_at=now.to_text()
                    )
                    self._persist_rights(conn, admission_grant)
                    self._insert_or_validate_blob(conn, admission_grant, now=now)
                    definition_digest = digest_canonical(
                        admission_grant.definition.canonical_value()
                    )
                    conn.execute(
                        "INSERT INTO object_admissions(" 
                        "admission_id,blob_digest,admission_type,definition_version,"
                        "definition_digest,object_class,allowed_use,security_scope,"
                        "retention_scope,required_read_scope,required_manage_scope,"
                        "rights_decision_id,rights_policy_version,valid_from,valid_until,"
                        "state,aggregate_version,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(admission_grant.admission_id),
                            admission_grant.blob_digest,
                            admission_grant.definition.admission_type,
                            admission_grant.definition.definition_version,
                            definition_digest,
                            admission_grant.definition.object_class,
                            admission_grant.definition.allowed_use,
                            admission_grant.definition.security_scope,
                            admission_grant.definition.retention_scope,
                            admission_grant.definition.required_read_scope,
                            admission_grant.definition.required_manage_scope,
                            str(admission_grant.rights.rights_decision_id),
                            admission_grant.rights.policy_version,
                            admission_grant.rights.valid_from.to_text(),
                            None
                            if admission_grant.rights.valid_until is None
                            else admission_grant.rights.valid_until.to_text(),
                            "ACTIVE",
                            1,
                            now.to_text(),
                            now.to_text(),
                        ),
                    )
                    event_result = self._commit_grant_on_connection(
                        conn, event_grant, recorded_at=now.to_text()
                    )
                    receipt = ObjectAdmissionReceipt(
                        admission_id=admission_grant.admission_id,
                        blob_digest=admission_grant.blob_digest,
                        size_bytes=admission_grant.size_bytes,
                        object_class=admission_grant.definition.object_class,
                        allowed_use=admission_grant.definition.allowed_use,
                        security_scope=admission_grant.definition.security_scope,
                        retention_scope=admission_grant.definition.retention_scope,
                        rights_decision_id=admission_grant.rights.rights_decision_id,
                        rights_policy_version=admission_grant.rights.policy_version,
                        valid_from=admission_grant.rights.valid_from.to_text(),
                        valid_until=(
                            None
                            if admission_grant.rights.valid_until is None
                            else admission_grant.rights.valid_until.to_text()
                        ),
                        ledger_seq=event_result.ledger_seq,
                        event_id=event_result.event_id,
                        replayed=False,
                    )
                    result_bytes = self._admission_receipt_bytes(receipt)
                    result_digest = digest_bytes(result_bytes)
                    conn.execute(
                        "INSERT INTO object_admission_operations(" 
                        "operation_id,idempotency_namespace,idempotency_key,"
                        "stable_semantic_request_digest,admission_id,blob_digest,"
                        "result_digest,result_bytes,command_id,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(AuditId.new()),
                            admission_grant.idempotency_namespace,
                            admission_grant.idempotency_key,
                            admission_grant.stable_semantic_request_digest,
                            str(admission_grant.admission_id),
                            admission_grant.blob_digest,
                            result_digest,
                            result_bytes,
                            event_result.command_id,
                            now.to_text(),
                        ),
                    )
                    pinned.verify_current()
                    return receipt

    def commit(self, grant: _AuthorizedCommandGrant) -> CommittedCommand:
        if grant.payload.kind != "OBJECT_ADMISSION":
            return super().commit(grant)
        self._issuer.verify(grant)
        if grant.payload.object_admission_id is None:
            raise UnsupportedPayloadMode("object payload lacks admission identity")
        with self._lock:
            row = self._admission_row(str(grant.payload.object_admission_id))
            with self._blob_store.pin(
                str(row["blob_digest"]), expected_size=int(row["size_bytes"])
            ) as pinned:
                with self._transaction() as conn:
                    current = self._admission_row(
                        str(grant.payload.object_admission_id), conn=conn
                    )
                    if not self._admission_is_current(current, now=self._clock()):
                        raise ObjectHydrationDenied(
                            "object admission expired, revoked, deleted or blocked"
                        )
                    result = self._commit_grant_on_connection(
                        conn, grant, recorded_at=self._clock().to_text()
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO object_references(" 
                        "admission_id,aggregate_type,aggregate_id,aggregate_version,"
                        "command_id,created_at) VALUES(?,?,?,?,?,?)",
                        (
                            str(grant.payload.object_admission_id),
                            result.aggregate_type,
                            result.aggregate_id,
                            result.aggregate_version,
                            result.command_id,
                            self._clock().to_text(),
                        ),
                    )
                    pinned.verify_current()
                    return result

    def revoke_admission(
        self,
        maintenance_grant: _AuthorizedMaintenanceGrant,
        event_grant: _AuthorizedCommandGrant,
    ) -> int:
        self._issuer.verify_maintenance(maintenance_grant)
        self._issuer.verify(event_grant)
        with self._lock, self._transaction() as conn:
            row = self._admission_row(maintenance_grant.target_id, conn=conn)
            if str(row["state"]) == "REVOKED":
                return int(row["aggregate_version"])
            if str(row["state"]) != "ACTIVE":
                raise ObjectLifecycleError("only an active admission may be revoked")
            now = self._clock().to_text()
            self._persist_security(conn, event_grant, recorded_at=now)
            next_version = int(row["aggregate_version"]) + 1
            conn.execute(
                "UPDATE object_admissions SET state='REVOKED',aggregate_version=?,"
                "updated_at=? WHERE admission_id=?",
                (next_version, now, maintenance_grant.target_id),
            )
            event_result = self._commit_grant_on_connection(
                conn, event_grant, recorded_at=now
            )
            conn.execute(
                "INSERT INTO object_admission_revocations(" 
                "revocation_id,admission_id,authentication_context_id,"
                "authorization_decision_id,command_id,reason_code,revoked_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    str(AuditId.new()),
                    maintenance_grant.target_id,
                    str(maintenance_grant.authentication.authentication_context_id),
                    str(maintenance_grant.authorization.authorization_decision_id),
                    event_result.command_id,
                    maintenance_grant.reason_code,
                    now,
                ),
            )
            return next_version

    def request_deletion(
        self,
        maintenance_grant: _AuthorizedMaintenanceGrant,
        event_grant: _AuthorizedCommandGrant,
        *,
        deletion_id: str,
        blob_digest: str,
    ) -> ObjectDeletionReceipt:
        self._issuer.verify_maintenance(maintenance_grant)
        self._issuer.verify(event_grant)
        with self._lock, self._transaction() as conn:
            existing = conn.execute(
                "SELECT t.*,e.ledger_seq FROM blob_deletion_tombstones t "
                "JOIN ledger_events e ON e.command_id=t.request_command_id "
                "WHERE t.blob_digest=?",
                (blob_digest,),
            ).fetchone()
            if existing is not None:
                return ObjectDeletionReceipt(
                    deletion_id=str(existing["deletion_id"]),
                    blob_digest=blob_digest,
                    requested_ledger_seq=int(existing["ledger_seq"]),
                    completed_ledger_seq=self._completion_sequence(
                        conn, existing["completion_command_id"]
                    ),
                    completed=existing["completion_command_id"] is not None,
                )
            blob = conn.execute(
                "SELECT state FROM blob_records WHERE blob_digest=?", (blob_digest,)
            ).fetchone()
            if blob is None:
                raise KeyError(blob_digest)
            if str(blob["state"]) == "DELETED":
                raise ObjectLifecycleError("deleted blob lacks its required tombstone")
            now = self._clock().to_text()
            conn.execute(
                "UPDATE blob_records SET state='DELETION_PENDING',updated_at=? "
                "WHERE blob_digest=? AND state='ACTIVE'",
                (now, blob_digest),
            )
            rows = conn.execute(
                "SELECT admission_id,state,aggregate_version FROM object_admissions "
                "WHERE blob_digest=? AND state IN ('ACTIVE','REVOKED')",
                (blob_digest,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE object_admissions SET state='DELETED',aggregate_version=?,"
                    "updated_at=? WHERE admission_id=?",
                    (
                        int(row["aggregate_version"]) + 1,
                        now,
                        str(row["admission_id"]),
                    ),
                )
            self._persist_security(conn, event_grant, recorded_at=now)
            event_result = self._commit_grant_on_connection(
                conn, event_grant, recorded_at=now
            )
            conn.execute(
                "INSERT INTO blob_deletion_tombstones(" 
                "deletion_id,blob_digest,authentication_context_id,"
                "authorization_decision_id,request_command_id,completion_command_id,"
                "reason_code,requested_at,completed_at) VALUES(?,?,?,?,?,NULL,?,?,NULL)",
                (
                    deletion_id,
                    blob_digest,
                    str(maintenance_grant.authentication.authentication_context_id),
                    str(maintenance_grant.authorization.authorization_decision_id),
                    event_result.command_id,
                    maintenance_grant.reason_code,
                    now,
                ),
            )
            return ObjectDeletionReceipt(
                deletion_id=deletion_id,
                blob_digest=blob_digest,
                requested_ledger_seq=event_result.ledger_seq,
                completed_ledger_seq=None,
                completed=False,
            )

    def complete_deletion(
        self,
        maintenance_grant: _AuthorizedMaintenanceGrant,
        event_grant: _AuthorizedCommandGrant,
        *,
        deletion_id: str,
        blob_digest: str,
    ) -> ObjectDeletionReceipt:
        self._issuer.verify_maintenance(maintenance_grant)
        self._issuer.verify(event_grant)
        with self._lock:
            pin = self._connection.execute(
                "SELECT 1 FROM recovery_pins WHERE blob_digest=? AND released_at IS NULL",
                (blob_digest,),
            ).fetchone()
            if pin is not None:
                requested = self._deletion_receipt(blob_digest)
                return requested
            self._blob_store.unlink_blob(blob_digest)
            with self._transaction() as conn:
                tombstone = conn.execute(
                    "SELECT * FROM blob_deletion_tombstones WHERE deletion_id=? "
                    "AND blob_digest=?",
                    (deletion_id, blob_digest),
                ).fetchone()
                if tombstone is None:
                    raise ObjectLifecycleError("deletion tombstone is missing")
                if tombstone["completion_command_id"] is not None:
                    return self._deletion_receipt(blob_digest, conn=conn)
                if self._blob_store.path_for(blob_digest).exists():
                    raise ObjectIntegrityError("deleted blob path still exists")
                now = self._clock().to_text()
                self._persist_security(conn, event_grant, recorded_at=now)
                event_result = self._commit_grant_on_connection(
                    conn, event_grant, recorded_at=now
                )
                conn.execute(
                    "UPDATE blob_records SET state='DELETED',updated_at=?,deleted_at=? "
                    "WHERE blob_digest=? AND state='DELETION_PENDING'",
                    (now, now, blob_digest),
                )
                conn.execute(
                    "UPDATE blob_deletion_tombstones SET completion_command_id=?,"
                    "completed_at=? WHERE deletion_id=?",
                    (event_result.command_id, now, deletion_id),
                )
                requested_seq = int(
                    conn.execute(
                        "SELECT e.ledger_seq FROM blob_deletion_tombstones t "
                        "JOIN ledger_events e ON e.command_id=t.request_command_id "
                        "WHERE t.deletion_id=?",
                        (deletion_id,),
                    ).fetchone()[0]
                )
                return ObjectDeletionReceipt(
                    deletion_id=deletion_id,
                    blob_digest=blob_digest,
                    requested_ledger_seq=requested_seq,
                    completed_ledger_seq=event_result.ledger_seq,
                    completed=True,
                )

    def hydrate(
        self,
        grant: _AuthorizedMaintenanceGrant,
        *,
        admission_id: ObjectAdmissionId,
        purpose: str,
        max_bytes: int,
    ) -> HydratedObject:
        self._issuer.verify_maintenance(grant)
        with self._lock:
            row = self._admission_row(str(admission_id))
            if purpose != str(row["allowed_use"]):
                raise ObjectHydrationDenied("requested purpose is not admitted")
            if not self._admission_is_current(row, now=self._clock()):
                raise ObjectHydrationDenied("object admission is not currently usable")
            if max_bytes > self._blob_store.limits.max_read_bytes:
                raise ObjectHydrationDenied("requested read exceeds the configured hard limit")
            with self._blob_store.pin(
                str(row["blob_digest"]), expected_size=int(row["size_bytes"])
            ) as pinned:
                with self._transaction() as conn:
                    current = self._admission_row(str(admission_id), conn=conn)
                    if not self._admission_is_current(current, now=self._clock()):
                        raise ObjectHydrationDenied(
                            "object admission changed before hydration"
                        )
                    now = self._clock().to_text()
                    self._persist_security_records(
                        conn,
                        grant.authentication,
                        grant.authorization_request,
                        grant.authorization,
                        recorded_at=now,
                    )
                    access_decision_id = str(AuditId.new())
                    conn.execute(
                        "INSERT INTO object_access_decisions(" 
                        "access_decision_id,admission_id,authentication_context_id,"
                        "authorization_decision_id,purpose,allowed,reason_code,decided_at) "
                        "VALUES(?,?,?,?,?,1,?,?)",
                        (
                            access_decision_id,
                            str(admission_id),
                            str(grant.authentication.authentication_context_id),
                            str(grant.authorization.authorization_decision_id),
                            purpose,
                            "ACCESS_ALLOWED",
                            now,
                        ),
                    )
                    bytes_value = pinned.read_bounded(max_bytes=max_bytes)
                    pinned.verify_current()
                    return HydratedObject(
                        admission_id=admission_id,
                        blob_digest=str(row["blob_digest"]),
                        purpose=purpose,
                        bytes_value=bytes_value,
                        access_decision_id=access_decision_id,
                    )

    def create_recovery_pin(
        self, grant: _AuthorizedMaintenanceGrant, *, blob_digest: str
    ) -> str:
        self._issuer.verify_maintenance(grant)
        with self._lock, self._transaction() as conn:
            blob = conn.execute(
                "SELECT state FROM blob_records WHERE blob_digest=?", (blob_digest,)
            ).fetchone()
            if blob is None or str(blob["state"]) == "DELETED":
                raise KeyError(blob_digest)
            now = self._clock().to_text()
            self._persist_security_records(
                conn,
                grant.authentication,
                grant.authorization_request,
                grant.authorization,
                recorded_at=now,
            )
            pin_id = str(AuditId.new())
            conn.execute(
                "INSERT INTO recovery_pins(" 
                "pin_id,blob_digest,authentication_context_id,"
                "authorization_decision_id,reason_code,created_at,released_at) "
                "VALUES(?,?,?,?,?,?,NULL)",
                (
                    pin_id,
                    blob_digest,
                    str(grant.authentication.authentication_context_id),
                    str(grant.authorization.authorization_decision_id),
                    grant.reason_code,
                    now,
                ),
            )
            return pin_id

    def release_recovery_pin(self, grant: _AuthorizedMaintenanceGrant) -> None:
        self._issuer.verify_maintenance(grant)
        with self._lock, self._transaction() as conn:
            now = self._clock().to_text()
            self._persist_security_records(
                conn,
                grant.authentication,
                grant.authorization_request,
                grant.authorization,
                recorded_at=now,
            )
            cursor = conn.execute(
                "UPDATE recovery_pins SET released_at=? WHERE pin_id=? "
                "AND released_at IS NULL",
                (now, grant.target_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(grant.target_id)

    def collect_garbage(
        self, grant: _AuthorizedMaintenanceGrant, *, grace_seconds: int
    ) -> tuple[str, ...]:
        self._issuer.verify_maintenance(grant)
        if grace_seconds < 0:
            raise ValueError("grace_seconds must be non-negative")
        cutoff = time.time() - grace_seconds
        removed: list[str] = []
        with self._lock:
            rows = {
                str(row["blob_digest"]): str(row["state"])
                for row in self._connection.execute(
                    "SELECT blob_digest,state FROM blob_records"
                ).fetchall()
            }
            pins = {
                str(row[0])
                for row in self._connection.execute(
                    "SELECT DISTINCT blob_digest FROM recovery_pins "
                    "WHERE released_at IS NULL"
                ).fetchall()
            }
            for digest, modified_at in self._blob_store.installed_digests():
                if digest in pins:
                    continue
                state = rows.get(digest)
                if state in {"ACTIVE", "DELETION_PENDING"}:
                    continue
                if state == "DELETED" or (state is None and modified_at < cutoff):
                    if self._blob_store.unlink_blob(digest):
                        removed.append(digest)
            return tuple(sorted(removed))

    def _commit_grant_on_connection(
        self,
        conn: sqlite3.Connection,
        grant: _AuthorizedCommandGrant,
        *,
        recorded_at: str,
    ) -> CommittedCommand:
        self._issuer.verify(grant)
        existing = conn.execute(
            "SELECT command_id,command_definition_version,command_definition_digest,"
            "stable_semantic_request_digest,result_digest,result_bytes "
            "FROM authority_commands WHERE idempotency_namespace=? AND idempotency_key=?",
            (grant.idempotency_namespace, grant.idempotency_key),
        ).fetchone()
        if existing is not None:
            return self._replay_existing(grant, existing)
        if grant.replay_of_command_id is not None:
            raise IdempotencyConflict(
                "command boundary expected a replay but no command exists"
            )
        self._persist_definition(conn, grant, recorded_at=recorded_at)
        self._persist_security(conn, grant, recorded_at=recorded_at)
        self._validate_causation(conn, grant)
        current_version, new_version = self._resolve_version(conn, grant)
        payload_id = str(PayloadId.new())
        if grant.payload.kind in {"INLINE", "NO_PAYLOAD"}:
            payload_bytes = grant.payload.inline_bytes
            if payload_bytes is None or digest_bytes(payload_bytes) != grant.payload.digest:
                raise AuthorityPersistenceError("retained lifecycle payload mismatch")
            conn.execute(
                "INSERT INTO authority_payloads(" 
                "payload_id,mode,schema_version,payload_digest,payload_bytes,"
                "object_admission_id,created_at) VALUES(?,?,?,?,?,NULL,?)",
                (
                    payload_id,
                    grant.payload.kind,
                    grant.payload.schema_version,
                    grant.payload.digest,
                    payload_bytes,
                    recorded_at,
                ),
            )
        elif grant.payload.kind == "OBJECT_ADMISSION":
            if grant.payload.object_admission_id is None:
                raise UnsupportedPayloadMode("object payload lacks admission identity")
            conn.execute(
                "INSERT INTO authority_payloads(" 
                "payload_id,mode,schema_version,payload_digest,payload_bytes,"
                "object_admission_id,created_at) VALUES(?,?,?,?,NULL,?,?)",
                (
                    payload_id,
                    grant.payload.kind,
                    grant.payload.schema_version,
                    grant.payload.digest,
                    str(grant.payload.object_admission_id),
                    recorded_at,
                ),
            )
        else:
            raise UnsupportedPayloadMode(grant.payload.kind)

        command_id = str(AuditId.new())
        event_id = str(EventId.new())
        audit_id = str(AuditId.new())
        ledger_seq = int(
            conn.execute("SELECT COALESCE(MAX(ledger_seq),0)+1 FROM ledger_events").fetchone()[0]
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
            "INSERT INTO authority_commands(" 
            "command_id,command_type,command_definition_version,command_definition_digest,"
            "aggregate_type,aggregate_id,expected_aggregate_version,"
            "idempotency_namespace,idempotency_key,stable_semantic_request_digest,"
            "authentication_context_id,authorization_request_digest,"
            "authorization_decision_id,result_digest,result_bytes,committed_at) "
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
            "aggregate_type,aggregate_id,aggregate_version,command_id,payload_id,"
            "trust_scope,recorded_at) VALUES(?,?,?,?,?,?,?)",
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
            "authorization_request_digest,authorization_decision_id,event_type,"
            "detail_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
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
            "retention_scope,trust_scope,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
        if grant.payload.kind == "OBJECT_ADMISSION":
            conn.execute(
                "INSERT INTO object_references(" 
                "admission_id,aggregate_type,aggregate_id,aggregate_version,command_id,"
                "created_at) VALUES(?,?,?,?,?,?)",
                (
                    str(grant.payload.object_admission_id),
                    grant.definition.aggregate_type,
                    grant.aggregate_id,
                    new_version,
                    command_id,
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

    def _persist_security_records(
        self,
        conn: sqlite3.Connection,
        authentication: Any,
        request: Any,
        authorization: Any,
        *,
        recorded_at: str,
    ) -> None:
        class Grant:
            pass
        grant = Grant()
        grant.authentication = authentication
        grant.authorization_request = request
        grant.authorization = authorization
        self._persist_security(conn, grant, recorded_at=recorded_at)

    def _persist_rights(
        self, conn: sqlite3.Connection, grant: _AuthorizedAdmissionGrant
    ) -> None:
        rights_bytes = canonical_json_bytes(grant.rights.canonical_value())
        conn.execute(
            "INSERT OR IGNORE INTO rights_decisions(" 
            "rights_decision_id,authentication_context_id,authorization_decision_id,"
            "request_digest,policy_version,allowed,reason_code,blob_digest,"
            "object_class,allowed_use,security_scope,retention_scope,valid_from,"
            "valid_until,decided_at,canonical_bytes,canonical_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(grant.rights.rights_decision_id),
                grant.rights.authentication_context_id,
                grant.rights.authorization_decision_id,
                grant.rights.request_digest,
                grant.rights.policy_version,
                int(grant.rights.allowed),
                grant.rights.reason_code,
                grant.rights.blob_digest,
                grant.rights.object_class,
                grant.rights.allowed_use,
                grant.rights.security_scope,
                grant.rights.retention_scope,
                grant.rights.valid_from.to_text(),
                None if grant.rights.valid_until is None else grant.rights.valid_until.to_text(),
                grant.rights.decided_at.to_text(),
                rights_bytes,
                grant.rights.digest,
            ),
        )
        row = conn.execute(
            "SELECT canonical_bytes FROM rights_decisions WHERE rights_decision_id=?",
            (str(grant.rights.rights_decision_id),),
        ).fetchone()
        if row is None or bytes(row[0]) != rights_bytes:
            raise AuthorityPersistenceError("rights decision identity conflict")

    @staticmethod
    def _insert_or_validate_blob(
        conn: sqlite3.Connection,
        grant: _AuthorizedAdmissionGrant,
        *,
        now: UtcTimestamp,
    ) -> None:
        row = conn.execute(
            "SELECT size_bytes,state FROM blob_records WHERE blob_digest=?",
            (grant.blob_digest,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO blob_records(" 
                "blob_digest,size_bytes,state,created_at,updated_at,deleted_at) "
                "VALUES(?,?,'ACTIVE',?,?,NULL)",
                (
                    grant.blob_digest,
                    grant.size_bytes,
                    now.to_text(),
                    now.to_text(),
                ),
            )
            return
        if int(row["size_bytes"]) != grant.size_bytes:
            raise ObjectIntegrityError("blob identity has conflicting size metadata")
        if str(row["state"]) != "ACTIVE":
            raise ObjectLifecycleError("blob is not available for a new admission")

    def _admission_row(
        self, admission_id: str, *, conn: sqlite3.Connection | None = None
    ) -> sqlite3.Row:
        connection = self._connection if conn is None else conn
        row = connection.execute(
            "SELECT a.*,b.size_bytes,b.state AS blob_state,r.allowed AS rights_allowed,"
            "r.valid_from AS rights_valid_from,r.valid_until AS rights_valid_until "
            "FROM object_admissions a JOIN blob_records b ON b.blob_digest=a.blob_digest "
            "JOIN rights_decisions r ON r.rights_decision_id=a.rights_decision_id "
            "WHERE a.admission_id=?",
            (admission_id,),
        ).fetchone()
        if row is None:
            raise KeyError(admission_id)
        return row

    @staticmethod
    def _admission_is_current(row: sqlite3.Row, *, now: UtcTimestamp) -> bool:
        if str(row["state"]) != "ACTIVE" or str(row["blob_state"]) != "ACTIVE":
            return False
        if not bool(row["rights_allowed"]):
            return False
        valid_from = UtcTimestamp.parse(str(row["rights_valid_from"]))
        valid_until = (
            None if row["rights_valid_until"] is None else UtcTimestamp.parse(str(row["rights_valid_until"]))
        )
        return now.value >= valid_from.value and (
            valid_until is None or now.value < valid_until.value
        )

    @staticmethod
    def _admission_receipt_bytes(receipt: ObjectAdmissionReceipt) -> bytes:
        return canonical_json_bytes(
            {
                "admission_id": str(receipt.admission_id),
                "blob_digest": receipt.blob_digest,
                "size_bytes": receipt.size_bytes,
                "object_class": receipt.object_class,
                "allowed_use": receipt.allowed_use,
                "security_scope": receipt.security_scope,
                "retention_scope": receipt.retention_scope,
                "rights_decision_id": str(receipt.rights_decision_id),
                "rights_policy_version": receipt.rights_policy_version,
                "valid_from": receipt.valid_from,
                "valid_until": receipt.valid_until,
                "ledger_seq": receipt.ledger_seq,
                "event_id": receipt.event_id,
            }
        )

    @staticmethod
    def _decode_admission_receipt(
        data: bytes, expected_digest: str, *, replayed: bool
    ) -> ObjectAdmissionReceipt:
        if digest_bytes(data) != expected_digest:
            raise AuthorityPersistenceError("stored admission result digest mismatch")
        try:
            value = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError("stored admission result is invalid") from exc
        if canonical_json_bytes(value) != data or not isinstance(value, dict):
            raise AuthorityPersistenceError("stored admission result is not canonical")
        return ObjectAdmissionReceipt(
            admission_id=ObjectAdmissionId.parse(str(value["admission_id"])),
            blob_digest=str(value["blob_digest"]),
            size_bytes=int(value["size_bytes"]),
            object_class=str(value["object_class"]),
            allowed_use=str(value["allowed_use"]),
            security_scope=str(value["security_scope"]),
            retention_scope=str(value["retention_scope"]),
            rights_decision_id=RightsDecisionId.parse(str(value["rights_decision_id"])),
            rights_policy_version=str(value["rights_policy_version"]),
            valid_from=str(value["valid_from"]),
            valid_until=None if value["valid_until"] is None else str(value["valid_until"]),
            ledger_seq=int(value["ledger_seq"]),
            event_id=str(value["event_id"]),
            replayed=replayed,
        )

    def _deletion_receipt(
        self, blob_digest: str, *, conn: sqlite3.Connection | None = None
    ) -> ObjectDeletionReceipt:
        connection = self._connection if conn is None else conn
        row = connection.execute(
            "SELECT t.*,r.ledger_seq AS requested_seq,c.ledger_seq AS completed_seq "
            "FROM blob_deletion_tombstones t "
            "JOIN ledger_events r ON r.command_id=t.request_command_id "
            "LEFT JOIN ledger_events c ON c.command_id=t.completion_command_id "
            "WHERE t.blob_digest=?",
            (blob_digest,),
        ).fetchone()
        if row is None:
            raise KeyError(blob_digest)
        return ObjectDeletionReceipt(
            deletion_id=str(row["deletion_id"]),
            blob_digest=blob_digest,
            requested_ledger_seq=int(row["requested_seq"]),
            completed_ledger_seq=(None if row["completed_seq"] is None else int(row["completed_seq"])),
            completed=row["completion_command_id"] is not None,
        )

    @staticmethod
    def _completion_sequence(
        conn: sqlite3.Connection, command_id: object
    ) -> int | None:
        if command_id is None:
            return None
        row = conn.execute(
            "SELECT ledger_seq FROM ledger_events WHERE command_id=?", (command_id,)
        ).fetchone()
        return None if row is None else int(row[0])
