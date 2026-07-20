from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Any

from ._capability import _AuthorizedCommandGrant
from ._object_capability import _MaintenanceGrant
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical
from .objects import (
    AdmissionRevocationView,
    AdmissionState,
    BlobIdentity,
    BlobIntegrityState,
    BlobLifecycleState,
    DeletionState,
    GovernedDeletionId,
    GovernedDeletionView,
    ObjectAdmissionId,
    ObjectLifecycleError,
    RecoveryPinId,
    RecoveryPinState,
    RecoveryPinView,
)
from .persistence import AuthorityPersistenceError, IdempotencyConflict
from .types import EventId, UtcTimestamp, UUIDv4Id


_LifecycleGrantFactory = Callable[
    [str, UUIDv4Id, dict[str, object]], _AuthorizedCommandGrant
]


class _ObjectLifecycleStoreMixin:
    """Atomic revocation, deletion/tombstone, recovery pin, and orphan state."""

    @staticmethod
    def _verify_lifecycle_command(
        object_grant: _MaintenanceGrant,
        command_grant: _AuthorizedCommandGrant,
        *,
        expected_command_type: str,
        expected_payload: dict[str, object],
    ) -> None:
        if command_grant.definition.command_type != expected_command_type:
            raise AuthorityPersistenceError(
                "lifecycle command type differs from maintenance operation"
            )
        if (
            command_grant.authentication.principal_id
            != object_grant.authentication.principal_id
            or command_grant.authentication.authority_domain
            != object_grant.authentication.authority_domain
        ):
            raise AuthorityPersistenceError(
                "lifecycle command security provenance differs from maintenance"
            )
        if command_grant.payload.inline_bytes != canonical_json_bytes(
            expected_payload
        ):
            raise AuthorityPersistenceError(
                "lifecycle command payload differs from exact mutation"
            )

    def _existing_operation(
        self, grant: _MaintenanceGrant
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT operation_type,stable_semantic_request_digest,result_bytes,"
            "result_digest FROM object_lifecycle_operations "
            "WHERE idempotency_namespace=? AND idempotency_key=?",
            (grant.idempotency_namespace, grant.idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_type"]) != grant.operation_type:
            raise IdempotencyConflict(
                "object idempotency identity belongs to another operation"
            )
        if (
            str(row["stable_semantic_request_digest"])
            != grant.stable_semantic_request_digest
        ):
            raise IdempotencyConflict(
                "object idempotency identity belongs to another semantic request"
            )
        data = bytes(row["result_bytes"])
        if digest_bytes(data) != str(row["result_digest"]):
            raise AuthorityPersistenceError(
                "object lifecycle result digest mismatch"
            )
        value = self._decode_canonical_object(data)
        if not isinstance(value, dict):
            raise AuthorityPersistenceError(
                "object lifecycle result must be a canonical object"
            )
        return value

    def _record_operation(
        self,
        conn: sqlite3.Connection,
        *,
        grant: _MaintenanceGrant,
        committed: Any,
        result: dict[str, object],
        recorded_at: str,
    ) -> None:
        result_bytes = canonical_json_bytes(result)
        conn.execute(
            "INSERT INTO object_lifecycle_operations("
            "operation_id,operation_type,idempotency_namespace,idempotency_key,"
            "stable_semantic_request_digest,authentication_context_id,"
            "authorization_request_digest,authorization_decision_id,"
            "command_id,event_id,result_bytes,result_digest,committed_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(grant.operation_id),
                grant.operation_type,
                grant.idempotency_namespace,
                grant.idempotency_key,
                grant.stable_semantic_request_digest,
                str(grant.authentication.authentication_context_id),
                grant.authorization_request.request_digest,
                str(grant.authorization.authorization_decision_id),
                committed.command_id,
                committed.event_id,
                result_bytes,
                digest_bytes(result_bytes),
                recorded_at,
            ),
        )

    @staticmethod
    def _next_version(
        conn: sqlite3.Connection,
        *,
        head_table: str,
        id_column: str,
        identity: str,
    ) -> int:
        allowed = {
            ("object_admission_heads", "admission_id"),
            ("blob_lifecycle_heads", "blob_digest"),
            ("object_deletion_heads", "deletion_id"),
            ("object_recovery_pin_heads", "pin_id"),
        }
        if (head_table, id_column) not in allowed:
            raise AuthorityPersistenceError("unsupported lifecycle head")
        row = conn.execute(
            f"SELECT current_version FROM {head_table} WHERE {id_column}=?",
            (identity,),
        ).fetchone()
        if row is None:
            raise KeyError(identity)
        return int(row["current_version"]) + 1

    def revoke_admission(
        self,
        grant: _MaintenanceGrant,
        *,
        lifecycle_grant_factory: _LifecycleGrantFactory,
    ) -> AdmissionRevocationView:
        now = self._clock()
        self._object_issuer.verify_maintenance(grant, now=now)
        if grant.operation_type != "ADMISSION_REVOKE":
            raise AuthorityPersistenceError("wrong maintenance operation")
        admission_id = ObjectAdmissionId.parse(grant.target_identity)
        with self._lock:
            existing = self._existing_operation(grant)
            if existing is not None:
                return self._revocation_view(admission_id)
            row = self._current_admission_row(
                self._connection,
                str(admission_id),
                now=now,
                require_active=True,
                require_bytes=False,
            )
            next_version = int(row["admission_lifecycle_version"]) + 1
            payload = {
                "operation_id": str(grant.operation_id),
                "admission_id": str(admission_id),
                "reason_code": grant.reason_code,
            }
            lifecycle_grant = lifecycle_grant_factory(
                "object.admission.revoke", admission_id, payload
            )
            self._issuer.verify(lifecycle_grant)
            self._verify_lifecycle_command(
                grant,
                lifecycle_grant,
                expected_command_type="object.admission.revoke",
                expected_payload=payload,
            )
            with self._transaction() as conn:
                recorded = self._clock()
                self._object_issuer.verify_maintenance(grant, now=recorded)
                self._current_admission_row(
                    conn,
                    str(admission_id),
                    now=recorded,
                    require_active=True,
                    require_bytes=False,
                )
                self._persist_security_records(
                    conn,
                    authentication=grant.authentication,
                    request=grant.authorization_request,
                    decision=grant.authorization,
                    recorded_at=recorded.to_text(),
                )
                committed = self._commit_grant_in_transaction(
                    conn, lifecycle_grant, recorded_at=recorded.to_text()
                )
                conn.execute(
                    "INSERT INTO object_admission_versions("
                    "admission_id,lifecycle_version,state,operation_id,event_id,"
                    "reason_code,recorded_at,detail_digest) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        str(admission_id),
                        next_version,
                        AdmissionState.REVOKED.value,
                        str(grant.operation_id),
                        committed.event_id,
                        grant.reason_code,
                        recorded.to_text(),
                        digest_canonical(payload),
                    ),
                )
                conn.execute(
                    "UPDATE object_admission_heads SET current_version=?,updated_at=? "
                    "WHERE admission_id=?",
                    (next_version, recorded.to_text(), str(admission_id)),
                )
                self._record_operation(
                    conn,
                    grant=grant,
                    committed=committed,
                    result={
                        "admission_id": str(admission_id),
                        "lifecycle_version": next_version,
                    },
                    recorded_at=recorded.to_text(),
                )
            return self._revocation_view(admission_id)

    def _revocation_view(
        self, admission_id: ObjectAdmissionId
    ) -> AdmissionRevocationView:
        row = self._connection.execute(
            "SELECT h.current_version,v.reason_code,v.recorded_at,v.event_id "
            "FROM object_admission_heads h "
            "JOIN object_admission_versions v "
            "ON v.admission_id=h.admission_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE h.admission_id=? AND v.state='REVOKED'",
            (str(admission_id),),
        ).fetchone()
        if row is None:
            raise ObjectLifecycleError("admission is not revoked")
        return AdmissionRevocationView(
            admission_id=admission_id,
            lifecycle_version=int(row["current_version"]),
            reason_code=str(row["reason_code"]),
            revoked_at=UtcTimestamp.parse(str(row["recorded_at"])),
            event_id=EventId.parse(str(row["event_id"])),
        )

    def request_deletion(
        self,
        grant: _MaintenanceGrant,
        *,
        lifecycle_grant_factory: _LifecycleGrantFactory,
    ) -> GovernedDeletionView:
        now = self._clock()
        self._object_issuer.verify_maintenance(grant, now=now)
        if grant.operation_type != "DELETION_REQUEST":
            raise AuthorityPersistenceError("wrong maintenance operation")
        identity = BlobIdentity(
            grant.target_identity,
            self._blob_size(grant.target_identity),
        )
        with self._lock:
            existing = self._existing_operation(grant)
            if existing is not None:
                return self.deletion_view(
                    GovernedDeletionId.parse(str(existing["deletion_id"]))
                )
            current_deletion = self._latest_deletion_row(
                self._connection, identity.blob_digest
            )
            if current_deletion is not None and str(current_deletion["state"]) != DeletionState.PHYSICALLY_REMOVED.value:
                raise ObjectLifecycleError(
                    "blob already has an unfinished governed deletion"
                )
            deletion_id = GovernedDeletionId.new()
            payload = {
                "operation_id": str(grant.operation_id),
                "deletion_id": str(deletion_id),
                "blob_digest": identity.blob_digest,
                "reason_code": grant.reason_code,
            }
            lifecycle_grant = lifecycle_grant_factory(
                "object.deletion.request", deletion_id, payload
            )
            self._issuer.verify(lifecycle_grant)
            self._verify_lifecycle_command(
                grant,
                lifecycle_grant,
                expected_command_type="object.deletion.request",
                expected_payload=payload,
            )
            with self._transaction() as conn:
                recorded = self._clock()
                self._object_issuer.verify_maintenance(grant, now=recorded)
                self._persist_security_records(
                    conn,
                    authentication=grant.authentication,
                    request=grant.authorization_request,
                    decision=grant.authorization,
                    recorded_at=recorded.to_text(),
                )
                committed = self._commit_grant_in_transaction(
                    conn, lifecycle_grant, recorded_at=recorded.to_text()
                )
                conn.execute(
                    "INSERT INTO object_deletions("
                    "deletion_id,blob_digest,reason_code,created_at) VALUES(?,?,?,?)",
                    (
                        str(deletion_id),
                        identity.blob_digest,
                        grant.reason_code,
                        recorded.to_text(),
                    ),
                )
                conn.execute(
                    "INSERT INTO object_deletion_versions("
                    "deletion_id,lifecycle_version,state,operation_id,event_id,"
                    "error_code,recorded_at,detail_digest) VALUES(?,?,?,?,?,NULL,?,?)",
                    (
                        str(deletion_id),
                        1,
                        DeletionState.REQUESTED.value,
                        str(grant.operation_id),
                        committed.event_id,
                        recorded.to_text(),
                        digest_canonical(payload),
                    ),
                )
                conn.execute(
                    "INSERT INTO object_deletion_heads("
                    "deletion_id,current_version,updated_at) VALUES(?,?,?)",
                    (str(deletion_id), 1, recorded.to_text()),
                )
                self._record_operation(
                    conn,
                    grant=grant,
                    committed=committed,
                    result={"deletion_id": str(deletion_id)},
                    recorded_at=recorded.to_text(),
                )
            return self.deletion_view(deletion_id)

    def tombstone_deletion(
        self,
        grant: _MaintenanceGrant,
        *,
        lifecycle_grant_factory: _LifecycleGrantFactory,
    ) -> GovernedDeletionView:
        return self._transition_deletion(
            grant,
            expected_operation="DELETION_TOMBSTONE",
            expected_current=DeletionState.REQUESTED,
            new_state=DeletionState.TOMBSTONED,
            command_type="object.deletion.tombstone",
            lifecycle_grant_factory=lifecycle_grant_factory,
            update_blob_state=BlobLifecycleState.DELETION_PENDING,
        )

    def _transition_deletion(
        self,
        grant: _MaintenanceGrant,
        *,
        expected_operation: str,
        expected_current: DeletionState,
        new_state: DeletionState,
        command_type: str,
        lifecycle_grant_factory: _LifecycleGrantFactory,
        update_blob_state: BlobLifecycleState | None,
        error_code: str | None = None,
    ) -> GovernedDeletionView:
        now = self._clock()
        self._object_issuer.verify_maintenance(grant, now=now)
        if grant.operation_type != expected_operation:
            raise AuthorityPersistenceError("wrong deletion operation")
        deletion_id = GovernedDeletionId.parse(grant.target_identity)
        with self._lock:
            existing = self._existing_operation(grant)
            if existing is not None:
                return self.deletion_view(deletion_id)
            row = self._deletion_row(deletion_id)
            if DeletionState(str(row["state"])) is not expected_current:
                raise ObjectLifecycleError(
                    f"deletion must be {expected_current.value}"
                )
            blob_digest = str(row["blob_digest"])
            payload: dict[str, object] = {
                "operation_id": str(grant.operation_id),
                "deletion_id": str(deletion_id),
                "blob_digest": blob_digest,
            }
            if command_type in {
                "object.deletion.tombstone",
                "object.deletion.request",
            }:
                payload["reason_code"] = str(row["reason_code"])
            if command_type == "object.deletion.fail":
                payload["error_code"] = error_code or grant.reason_code
            lifecycle_grant = lifecycle_grant_factory(
                command_type, deletion_id, payload
            )
            self._issuer.verify(lifecycle_grant)
            self._verify_lifecycle_command(
                grant,
                lifecycle_grant,
                expected_command_type=command_type,
                expected_payload=payload,
            )
            with self._transaction() as conn:
                recorded = self._clock()
                self._object_issuer.verify_maintenance(grant, now=recorded)
                current = self._deletion_row(deletion_id, conn=conn)
                if DeletionState(str(current["state"])) is not expected_current:
                    raise ObjectLifecycleError(
                        "deletion state changed before commit"
                    )
                self._persist_security_records(
                    conn,
                    authentication=grant.authentication,
                    request=grant.authorization_request,
                    decision=grant.authorization,
                    recorded_at=recorded.to_text(),
                )
                committed = self._commit_grant_in_transaction(
                    conn, lifecycle_grant, recorded_at=recorded.to_text()
                )
                next_version = int(current["current_version"]) + 1
                conn.execute(
                    "INSERT INTO object_deletion_versions("
                    "deletion_id,lifecycle_version,state,operation_id,event_id,"
                    "error_code,recorded_at,detail_digest) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        str(deletion_id),
                        next_version,
                        new_state.value,
                        str(grant.operation_id),
                        committed.event_id,
                        error_code,
                        recorded.to_text(),
                        digest_canonical(payload),
                    ),
                )
                conn.execute(
                    "UPDATE object_deletion_heads SET current_version=?,updated_at=? "
                    "WHERE deletion_id=?",
                    (next_version, recorded.to_text(), str(deletion_id)),
                )
                if update_blob_state is not None:
                    self._append_blob_lifecycle(
                        conn,
                        blob_digest=blob_digest,
                        state=update_blob_state,
                        integrity=(
                            BlobIntegrityState.VERIFIED
                            if update_blob_state
                            is BlobLifecycleState.DELETION_PENDING
                            else BlobIntegrityState.MISSING
                        ),
                        operation_id=str(grant.operation_id),
                        event_id=committed.event_id,
                        recorded_at=recorded,
                    )
                self._record_operation(
                    conn,
                    grant=grant,
                    committed=committed,
                    result={
                        "deletion_id": str(deletion_id),
                        "lifecycle_version": next_version,
                        "state": new_state.value,
                    },
                    recorded_at=recorded.to_text(),
                )
            return self.deletion_view(deletion_id)

    def complete_deletion(
        self,
        grant: _MaintenanceGrant,
        *,
        lifecycle_grant_factory: _LifecycleGrantFactory,
        failure_grant_factory: _LifecycleGrantFactory,
    ) -> GovernedDeletionView:
        now = self._clock()
        self._object_issuer.verify_maintenance(grant, now=now)
        if grant.operation_type != "DELETION_COMPLETE":
            raise AuthorityPersistenceError("wrong deletion operation")
        deletion_id = GovernedDeletionId.parse(grant.target_identity)
        with self._lock:
            existing = self._existing_operation(grant)
            if existing is not None:
                return self.deletion_view(deletion_id)
            row = self._deletion_row(deletion_id)
            current_state = DeletionState(str(row["state"]))
            if current_state is DeletionState.PHYSICALLY_REMOVED:
                return self.deletion_view(deletion_id)
            if current_state is not DeletionState.TOMBSTONED:
                raise ObjectLifecycleError(
                    "physical removal requires TOMBSTONED deletion"
                )
            blob = BlobIdentity(
                str(row["blob_digest"]), self._blob_size(str(row["blob_digest"]))
            )
            liveness = self.object_liveness(self._connection, blob.blob_digest)
            if not liveness.may_physically_remove:
                raise ObjectLifecycleError(
                    "recovery pin or deletion state blocks physical removal"
                )
            payload = {
                "operation_id": str(grant.operation_id),
                "deletion_id": str(deletion_id),
                "blob_digest": blob.blob_digest,
            }
            lifecycle_grant = lifecycle_grant_factory(
                "object.deletion.complete", deletion_id, payload
            )
            self._issuer.verify(lifecycle_grant)
            self._verify_lifecycle_command(
                grant,
                lifecycle_grant,
                expected_command_type="object.deletion.complete",
                expected_payload=payload,
            )
            try:
                # Hold the SQLite write transaction and the lifetime writer lock
                # across the final liveness check, durable unlink and ordered
                # lifecycle mutation.  Filesystem and SQLite cannot share one
                # atomic primitive, so a post-unlink SQLite failure deliberately
                # leaves TOMBSTONED authority for deterministic reconciliation.
                with self._transaction() as conn:
                    recorded = self._clock()
                    self._object_issuer.verify_maintenance(grant, now=recorded)
                    current = self._deletion_row(deletion_id, conn=conn)
                    if (
                        DeletionState(str(current["state"]))
                        is not DeletionState.TOMBSTONED
                    ):
                        raise ObjectLifecycleError(
                            "deletion state changed before completion"
                        )
                    if self.object_liveness(
                        conn, blob.blob_digest
                    ).active_recovery_pins:
                        raise ObjectLifecycleError(
                            "recovery pin appeared before completion commit"
                        )
                    self._cas.unlink(blob)
                    # Unlink and parent-directory fsync can take long enough for
                    # a short-lived maintenance authority to expire.  Recheck on
                    # the post-filesystem server clock before recording the
                    # terminal lifecycle event.  If this fails, TOMBSTONED
                    # authority remains and deterministic reconciliation can
                    # complete later without resurrecting hydration.
                    recorded = self._clock()
                    self._object_issuer.verify_maintenance(grant, now=recorded)
                    self._persist_security_records(
                        conn,
                        authentication=grant.authentication,
                        request=grant.authorization_request,
                        decision=grant.authorization,
                        recorded_at=recorded.to_text(),
                    )
                    committed = self._commit_grant_in_transaction(
                        conn, lifecycle_grant, recorded_at=recorded.to_text()
                    )
                    next_version = int(current["current_version"]) + 1
                    conn.execute(
                        "INSERT INTO object_deletion_versions("
                        "deletion_id,lifecycle_version,state,operation_id,event_id,"
                        "error_code,recorded_at,detail_digest) "
                        "VALUES(?,?,?,?,?,NULL,?,?)",
                        (
                            str(deletion_id),
                            next_version,
                            DeletionState.PHYSICALLY_REMOVED.value,
                            str(grant.operation_id),
                            committed.event_id,
                            recorded.to_text(),
                            digest_canonical(payload),
                        ),
                    )
                    conn.execute(
                        "UPDATE object_deletion_heads "
                        "SET current_version=?,updated_at=? WHERE deletion_id=?",
                        (next_version, recorded.to_text(), str(deletion_id)),
                    )
                    self._append_blob_lifecycle(
                        conn,
                        blob_digest=blob.blob_digest,
                        state=BlobLifecycleState.DELETED,
                        integrity=BlobIntegrityState.MISSING,
                        operation_id=str(grant.operation_id),
                        event_id=committed.event_id,
                        recorded_at=recorded,
                    )
                    self._record_operation(
                        conn,
                        grant=grant,
                        committed=committed,
                        result={
                            "deletion_id": str(deletion_id),
                            "lifecycle_version": next_version,
                            "state": DeletionState.PHYSICALLY_REMOVED.value,
                        },
                        recorded_at=recorded.to_text(),
                    )
            except Exception as exc:
                # A pre-unlink failure leaves bytes present and is recorded as
                # FAILED.  A post-unlink durability failure is indeterminate:
                # preserve TOMBSTONED authority so a later authenticated retry
                # can durably reconcile and commit PHYSICALLY_REMOVED.
                if self._cas.object_path(blob).exists():
                    self._record_deletion_failure(
                        grant,
                        deletion_id=deletion_id,
                        blob=blob,
                        error_code="UNLINK_FAILED",
                        lifecycle_grant_factory=failure_grant_factory,
                    )
                raise ObjectLifecycleError("governed unlink failed") from exc
            return self.deletion_view(deletion_id)

    def _record_deletion_failure(
        self,
        grant: _MaintenanceGrant,
        *,
        deletion_id: GovernedDeletionId,
        blob: BlobIdentity,
        error_code: str,
        lifecycle_grant_factory: _LifecycleGrantFactory,
    ) -> None:
        payload = {
            "operation_id": str(grant.operation_id),
            "deletion_id": str(deletion_id),
            "blob_digest": blob.blob_digest,
            "error_code": error_code,
        }
        lifecycle = lifecycle_grant_factory(
            "object.deletion.fail", deletion_id, payload
        )
        self._issuer.verify(lifecycle)
        self._verify_lifecycle_command(
            grant,
            lifecycle,
            expected_command_type="object.deletion.fail",
            expected_payload=payload,
        )
        with self._transaction() as conn:
            recorded = self._clock()
            self._object_issuer.verify_maintenance(grant, now=recorded)
            current = self._deletion_row(deletion_id, conn=conn)
            if DeletionState(str(current["state"])) is not DeletionState.TOMBSTONED:
                return
            self._persist_security_records(
                conn,
                authentication=grant.authentication,
                request=grant.authorization_request,
                decision=grant.authorization,
                recorded_at=recorded.to_text(),
            )
            committed = self._commit_grant_in_transaction(
                conn, lifecycle, recorded_at=recorded.to_text()
            )
            next_version = int(current["current_version"]) + 1
            conn.execute(
                "INSERT INTO object_deletion_versions("
                "deletion_id,lifecycle_version,state,operation_id,event_id,"
                "error_code,recorded_at,detail_digest) VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(deletion_id),
                    next_version,
                    DeletionState.FAILED.value,
                    str(grant.operation_id),
                    committed.event_id,
                    error_code,
                    recorded.to_text(),
                    digest_canonical(payload),
                ),
            )
            conn.execute(
                "UPDATE object_deletion_heads SET current_version=?,updated_at=? "
                "WHERE deletion_id=?",
                (next_version, recorded.to_text(), str(deletion_id)),
            )

    def create_recovery_pin(
        self,
        grant: _MaintenanceGrant,
        *,
        lifecycle_grant_factory: _LifecycleGrantFactory,
    ) -> RecoveryPinView:
        now = self._clock()
        self._object_issuer.verify_maintenance(grant, now=now)
        if grant.operation_type != "RECOVERY_PIN_CREATE":
            raise AuthorityPersistenceError("wrong recovery pin operation")
        blob = BlobIdentity(grant.target_identity, self._blob_size(grant.target_identity))
        with self._lock:
            existing = self._existing_operation(grant)
            if existing is not None:
                return self.recovery_pin_view(
                    RecoveryPinId.parse(str(existing["pin_id"]))
                )
            pin_id = RecoveryPinId.new()
            payload = {
                "operation_id": str(grant.operation_id),
                "pin_id": str(pin_id),
                "blob_digest": blob.blob_digest,
                "reason_code": grant.reason_code,
            }
            lifecycle = lifecycle_grant_factory(
                "object.recovery_pin.create", pin_id, payload
            )
            self._issuer.verify(lifecycle)
            self._verify_lifecycle_command(
                grant,
                lifecycle,
                expected_command_type="object.recovery_pin.create",
                expected_payload=payload,
            )
            with self._transaction() as conn:
                recorded = self._clock()
                self._object_issuer.verify_maintenance(grant, now=recorded)
                self._persist_security_records(
                    conn,
                    authentication=grant.authentication,
                    request=grant.authorization_request,
                    decision=grant.authorization,
                    recorded_at=recorded.to_text(),
                )
                committed = self._commit_grant_in_transaction(
                    conn, lifecycle, recorded_at=recorded.to_text()
                )
                conn.execute(
                    "INSERT INTO object_recovery_pins("
                    "pin_id,blob_digest,reason_code,created_at) VALUES(?,?,?,?)",
                    (
                        str(pin_id),
                        blob.blob_digest,
                        grant.reason_code,
                        recorded.to_text(),
                    ),
                )
                conn.execute(
                    "INSERT INTO object_recovery_pin_versions("
                    "pin_id,lifecycle_version,state,operation_id,event_id,"
                    "recorded_at,detail_digest) VALUES(?,?,?,?,?,?,?)",
                    (
                        str(pin_id),
                        1,
                        RecoveryPinState.ACTIVE.value,
                        str(grant.operation_id),
                        committed.event_id,
                        recorded.to_text(),
                        digest_canonical(payload),
                    ),
                )
                conn.execute(
                    "INSERT INTO object_recovery_pin_heads("
                    "pin_id,current_version,updated_at) VALUES(?,?,?)",
                    (str(pin_id), 1, recorded.to_text()),
                )
                self._record_operation(
                    conn,
                    grant=grant,
                    committed=committed,
                    result={"pin_id": str(pin_id)},
                    recorded_at=recorded.to_text(),
                )
            return self.recovery_pin_view(pin_id)

    def release_recovery_pin(
        self,
        grant: _MaintenanceGrant,
        *,
        lifecycle_grant_factory: _LifecycleGrantFactory,
    ) -> RecoveryPinView:
        now = self._clock()
        self._object_issuer.verify_maintenance(grant, now=now)
        if grant.operation_type != "RECOVERY_PIN_RELEASE":
            raise AuthorityPersistenceError("wrong recovery pin operation")
        pin_id = RecoveryPinId.parse(grant.target_identity)
        with self._lock:
            existing = self._existing_operation(grant)
            if existing is not None:
                return self.recovery_pin_view(pin_id)
            row = self._pin_row(pin_id)
            if RecoveryPinState(str(row["state"])) is not RecoveryPinState.ACTIVE:
                return self.recovery_pin_view(pin_id)
            payload = {
                "operation_id": str(grant.operation_id),
                "pin_id": str(pin_id),
                "blob_digest": str(row["blob_digest"]),
                "reason_code": grant.reason_code,
            }
            lifecycle = lifecycle_grant_factory(
                "object.recovery_pin.release", pin_id, payload
            )
            self._issuer.verify(lifecycle)
            self._verify_lifecycle_command(
                grant,
                lifecycle,
                expected_command_type="object.recovery_pin.release",
                expected_payload=payload,
            )
            with self._transaction() as conn:
                recorded = self._clock()
                self._object_issuer.verify_maintenance(grant, now=recorded)
                current = self._pin_row(pin_id, conn=conn)
                if RecoveryPinState(str(current["state"])) is not RecoveryPinState.ACTIVE:
                    raise ObjectLifecycleError("recovery pin state changed")
                self._persist_security_records(
                    conn,
                    authentication=grant.authentication,
                    request=grant.authorization_request,
                    decision=grant.authorization,
                    recorded_at=recorded.to_text(),
                )
                committed = self._commit_grant_in_transaction(
                    conn, lifecycle, recorded_at=recorded.to_text()
                )
                next_version = int(current["current_version"]) + 1
                conn.execute(
                    "INSERT INTO object_recovery_pin_versions("
                    "pin_id,lifecycle_version,state,operation_id,event_id,"
                    "recorded_at,detail_digest) VALUES(?,?,?,?,?,?,?)",
                    (
                        str(pin_id),
                        next_version,
                        RecoveryPinState.RELEASED.value,
                        str(grant.operation_id),
                        committed.event_id,
                        recorded.to_text(),
                        digest_canonical(payload),
                    ),
                )
                conn.execute(
                    "UPDATE object_recovery_pin_heads "
                    "SET current_version=?,updated_at=? WHERE pin_id=?",
                    (next_version, recorded.to_text(), str(pin_id)),
                )
                self._record_operation(
                    conn,
                    grant=grant,
                    committed=committed,
                    result={
                        "pin_id": str(pin_id),
                        "lifecycle_version": next_version,
                    },
                    recorded_at=recorded.to_text(),
                )
            return self.recovery_pin_view(pin_id)

    def remove_orphan(
        self,
        grant: _MaintenanceGrant,
        *,
        lifecycle_grant_factory: _LifecycleGrantFactory,
    ) -> BlobIdentity:
        now = self._clock()
        self._object_issuer.verify_maintenance(grant, now=now)
        if grant.operation_type != "ORPHAN_REMOVE":
            raise AuthorityPersistenceError("wrong orphan operation")
        blob = BlobIdentity(
            grant.target_identity, self._blob_size(grant.target_identity)
        )
        with self._lock:
            existing = self._existing_operation(grant)
            if existing is not None:
                # A committed orphan-removal decision is authoritative even if a
                # previous physical unlink was interrupted.  Reconcile the
                # idempotent byte removal before returning the old result.
                if self._cas.object_path(blob).exists():
                    try:
                        self._cas.unlink(blob)
                    except Exception as exc:
                        raise ObjectLifecycleError(
                            "orphan unlink remains pending reconciliation"
                        ) from exc
                return blob
            liveness = self.object_liveness(self._connection, blob.blob_digest)
            if (
                liveness.deletion_state is not None
                or not liveness.may_physically_remove
            ):
                raise ObjectLifecycleError(
                    "blob is not an ordinary removable orphan"
                )
            payload = {
                "operation_id": str(grant.operation_id),
                "blob_digest": blob.blob_digest,
                "size_bytes": blob.size_bytes,
            }
            lifecycle = lifecycle_grant_factory(
                "object.orphan.remove", grant.operation_id, payload
            )
            self._issuer.verify(lifecycle)
            self._verify_lifecycle_command(
                grant,
                lifecycle,
                expected_command_type="object.orphan.remove",
                expected_payload=payload,
            )
            # Commit the authoritative zero-liveness removal decision first.
            # If physical unlink then fails, current DELETED state blocks all
            # hydration and startup/idempotent replay safely completes cleanup.
            with self._transaction() as conn:
                recorded = self._clock()
                self._object_issuer.verify_maintenance(grant, now=recorded)
                current_liveness = self.object_liveness(
                    conn, blob.blob_digest
                )
                if (
                    current_liveness.deletion_state is not None
                    or not current_liveness.may_physically_remove
                ):
                    raise ObjectLifecycleError(
                        "orphan liveness changed before commit"
                    )
                self._persist_security_records(
                    conn,
                    authentication=grant.authentication,
                    request=grant.authorization_request,
                    decision=grant.authorization,
                    recorded_at=recorded.to_text(),
                )
                committed = self._commit_grant_in_transaction(
                    conn, lifecycle, recorded_at=recorded.to_text()
                )
                self._append_blob_lifecycle(
                    conn,
                    blob_digest=blob.blob_digest,
                    state=BlobLifecycleState.DELETED,
                    integrity=BlobIntegrityState.MISSING,
                    operation_id=str(grant.operation_id),
                    event_id=committed.event_id,
                    recorded_at=recorded,
                )
                self._record_operation(
                    conn,
                    grant=grant,
                    committed=committed,
                    result={"blob_digest": blob.blob_digest},
                    recorded_at=recorded.to_text(),
                )
            try:
                self._cas.unlink(blob)
            except Exception as exc:
                raise ObjectLifecycleError(
                    "orphan unlink pending reconciliation"
                ) from exc
            return blob

    def orphan_candidates(self) -> tuple[BlobIdentity, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT blob_digest,size_bytes FROM blob_identities"
            ).fetchall()
            candidates: list[BlobIdentity] = []
            for row in rows:
                digest = str(row["blob_digest"])
                liveness = self.object_liveness(self._connection, digest)
                if liveness.deletion_state is None and liveness.may_physically_remove:
                    candidates.append(BlobIdentity(digest, int(row["size_bytes"])))
            return tuple(candidates)

    def _append_blob_lifecycle(
        self,
        conn: sqlite3.Connection,
        *,
        blob_digest: str,
        state: BlobLifecycleState,
        integrity: BlobIntegrityState,
        operation_id: str,
        event_id: str,
        recorded_at: UtcTimestamp,
    ) -> int:
        next_version = self._next_version(
            conn,
            head_table="blob_lifecycle_heads",
            id_column="blob_digest",
            identity=blob_digest,
        )
        detail = {
            "blob_digest": blob_digest,
            "state": state.value,
            "integrity_state": integrity.value,
            "operation_id": operation_id,
            "event_id": event_id,
        }
        conn.execute(
            "INSERT INTO blob_lifecycle_versions("
            "blob_digest,lifecycle_version,state,integrity_state,operation_id,"
            "event_id,recorded_at,detail_digest) VALUES(?,?,?,?,?,?,?,?)",
            (
                blob_digest,
                next_version,
                state.value,
                integrity.value,
                operation_id,
                event_id,
                recorded_at.to_text(),
                digest_canonical(detail),
            ),
        )
        conn.execute(
            "UPDATE blob_lifecycle_heads SET current_version=?,updated_at=? "
            "WHERE blob_digest=?",
            (next_version, recorded_at.to_text(), blob_digest),
        )
        return next_version

    def _blob_size(self, blob_digest: str) -> int:
        row = self._connection.execute(
            "SELECT size_bytes FROM blob_identities WHERE blob_digest=?",
            (blob_digest,),
        ).fetchone()
        if row is None:
            raise KeyError(blob_digest)
        return int(row["size_bytes"])

    def _latest_deletion_row(
        self,
        conn: sqlite3.Connection,
        blob_digest: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT d.*,h.current_version,v.state,v.event_id,v.recorded_at,"
            "v.error_code FROM object_deletions d "
            "JOIN object_deletion_heads h ON h.deletion_id=d.deletion_id "
            "JOIN object_deletion_versions v "
            "ON v.deletion_id=h.deletion_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE d.blob_digest=? ORDER BY d.created_at DESC LIMIT 1",
            (blob_digest,),
        ).fetchone()

    def _deletion_row(
        self,
        deletion_id: GovernedDeletionId,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        selected = conn or self._connection
        row = selected.execute(
            "SELECT d.*,h.current_version,v.state,v.event_id,v.recorded_at,"
            "v.error_code FROM object_deletions d "
            "JOIN object_deletion_heads h ON h.deletion_id=d.deletion_id "
            "JOIN object_deletion_versions v "
            "ON v.deletion_id=h.deletion_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE d.deletion_id=?",
            (str(deletion_id),),
        ).fetchone()
        if row is None:
            raise KeyError(str(deletion_id))
        return row

    def deletion_view(
        self, deletion_id: GovernedDeletionId
    ) -> GovernedDeletionView:
        with self._lock:
            row = self._deletion_row(deletion_id)
            return GovernedDeletionView(
                deletion_id=deletion_id,
                blob=BlobIdentity(
                    str(row["blob_digest"]),
                    self._blob_size(str(row["blob_digest"])),
                ),
                reason_code=str(row["reason_code"]),
                lifecycle_version=int(row["current_version"]),
                state=DeletionState(str(row["state"])),
                requested_at=UtcTimestamp.parse(str(row["created_at"])),
                updated_at=UtcTimestamp.parse(str(row["recorded_at"])),
                event_id=EventId.parse(str(row["event_id"])),
            )

    def _pin_row(
        self,
        pin_id: RecoveryPinId,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        selected = conn or self._connection
        row = selected.execute(
            "SELECT p.*,h.current_version,v.state,v.event_id,v.recorded_at "
            "FROM object_recovery_pins p "
            "JOIN object_recovery_pin_heads h ON h.pin_id=p.pin_id "
            "JOIN object_recovery_pin_versions v "
            "ON v.pin_id=h.pin_id AND v.lifecycle_version=h.current_version "
            "WHERE p.pin_id=?",
            (str(pin_id),),
        ).fetchone()
        if row is None:
            raise KeyError(str(pin_id))
        return row

    def recovery_pin_view(self, pin_id: RecoveryPinId) -> RecoveryPinView:
        with self._lock:
            row = self._pin_row(pin_id)
            return RecoveryPinView(
                pin_id=pin_id,
                blob=BlobIdentity(
                    str(row["blob_digest"]),
                    self._blob_size(str(row["blob_digest"])),
                ),
                reason_code=str(row["reason_code"]),
                lifecycle_version=int(row["current_version"]),
                state=RecoveryPinState(str(row["state"])),
                created_at=UtcTimestamp.parse(str(row["created_at"])),
                updated_at=UtcTimestamp.parse(str(row["recorded_at"])),
                event_id=EventId.parse(str(row["event_id"])),
            )


__all__ = ["_ObjectLifecycleStoreMixin"]
