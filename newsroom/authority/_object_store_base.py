from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from typing import Any, Iterator

from ._capability import _AuthorizedCommandGrant
from ._object_capability import _ObjectCapabilityIssuer
from ._object_cas import _GovernedCAS, _PinnedBlob
from .canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from .models import ObjectAdmissionDescriptor
from .object_policy import (
    HydrationPolicyRegistry,
    ObjectAdmissionRegistry,
    RightsPolicyRegistry,
)
from .objects import (
    AdmissionState,
    BlobIdentity,
    BlobIntegrityState,
    BlobLifecycleState,
    BlobLifecycleView,
    DeletionState,
    ObjectAdmissionDenied,
    ObjectAdmissionId,
    ObjectAdmissionView,
    ObjectIntegrityError,
    ObjectLifecycleError,
    ObjectLivenessSnapshot,
    RightsDecisionId,
    RightsDecisionView,
)
from .persistence import AuthorityPersistenceError, UnsupportedPayloadMode
from .types import EventId, PayloadMode, UtcTimestamp


class _ObjectStoreBase:
    """Policy persistence, current-state resolution, CAS hooks, and reconciliation."""

    def _migrate_or_validate(self) -> None:
        """Apply A2a/A2b migrations, retain exact object contracts, then validate."""

        from .migrations import SCHEMA_VERSION, apply_pending_migrations
        from .persistence import AuthoritySchemaError

        conn = self._connection
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = self._table_names()
        if version > SCHEMA_VERSION:
            raise AuthoritySchemaError(
                f"database schema {version} is newer than supported {SCHEMA_VERSION}"
            )
        if version == 0 and tables:
            raise AuthoritySchemaError(
                "refusing to adopt a non-empty unversioned authority database"
            )
        if version < SCHEMA_VERSION:
            apply_pending_migrations(conn, applied_at=self._clock().to_text())
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._persist_object_contracts(
                conn, recorded_at=self._clock().to_text()
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        self._validate_schema_and_integrity()


    def _configure_object_store(
        self,
        *,
        object_issuer: _ObjectCapabilityIssuer,
        admission_registry: ObjectAdmissionRegistry,
        rights_policies: RightsPolicyRegistry,
        hydration_policies: HydrationPolicyRegistry,
        cas: _GovernedCAS,
    ) -> None:
        self._object_issuer = object_issuer
        self._admission_registry = admission_registry
        self._rights_policies = rights_policies
        self._hydration_policies = hydration_policies
        self._cas = cas
        self._reconcile_objects()

    def _persist_object_contracts(
        self, conn: sqlite3.Connection, *, recorded_at: str
    ) -> None:
        # Foreign-key order is rights/hydration contracts before definitions.
        for contract in self._rights_policies.contracts():
            canonical = canonical_json_bytes(contract.canonical_value())
            if digest_bytes(canonical) != contract.contract_digest:
                raise AuthorityPersistenceError(
                    "rights policy contract digest mismatch"
                )
            conn.execute(
                "INSERT OR IGNORE INTO rights_policy_contracts("
                "contract_digest,policy_key,contract_version,implementation_version,"
                "canonical_bytes,registered_at) VALUES(?,?,?,?,?,?)",
                (
                    contract.contract_digest,
                    contract.policy_key,
                    contract.contract_version,
                    contract.implementation_version,
                    canonical,
                    recorded_at,
                ),
            )
            row = conn.execute(
                "SELECT canonical_bytes FROM rights_policy_contracts "
                "WHERE contract_digest=?",
                (contract.contract_digest,),
            ).fetchone()
            if row is None or bytes(row["canonical_bytes"]) != canonical:
                raise AuthorityPersistenceError(
                    "rights policy contract identity conflict"
                )

        for contract in self._hydration_policies.contracts():
            canonical = canonical_json_bytes(contract.canonical_value())
            if digest_bytes(canonical) != contract.contract_digest:
                raise AuthorityPersistenceError(
                    "hydration policy contract digest mismatch"
                )
            conn.execute(
                "INSERT OR IGNORE INTO hydration_policy_contracts("
                "contract_digest,policy_id,contract_version,implementation_version,"
                "purpose,canonical_bytes,registered_at) VALUES(?,?,?,?,?,?,?)",
                (
                    contract.contract_digest,
                    contract.policy_id,
                    contract.contract_version,
                    contract.implementation_version,
                    contract.purpose,
                    canonical,
                    recorded_at,
                ),
            )
            row = conn.execute(
                "SELECT canonical_bytes FROM hydration_policy_contracts "
                "WHERE contract_digest=?",
                (contract.contract_digest,),
            ).fetchone()
            if row is None or bytes(row["canonical_bytes"]) != canonical:
                raise AuthorityPersistenceError(
                    "hydration policy contract identity conflict"
                )

        for definition in self._admission_registry.definitions():
            canonical = canonical_json_bytes(definition.canonical_value())
            if digest_bytes(canonical) != definition.digest:
                raise AuthorityPersistenceError(
                    "object admission definition digest mismatch"
                )
            conn.execute(
                "INSERT OR IGNORE INTO object_admission_definitions("
                "definition_digest,admission_type,definition_version,"
                "object_class,allowed_use,security_scope,retention_scope,"
                "required_write_scope,required_read_scope,required_manage_scope,"
                "rights_policy_contract_digest,hydration_policy_contract_digests,"
                "canonical_bytes,registered_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    definition.digest,
                    definition.admission_type,
                    definition.definition_version,
                    definition.object_class,
                    definition.allowed_use,
                    definition.security_scope,
                    definition.retention_scope,
                    definition.required_write_scope,
                    definition.required_read_scope,
                    definition.required_manage_scope,
                    definition.rights_policy_contract_digest,
                    canonical_json_bytes(
                        sorted(definition.hydration_policy_contract_digests)
                    ),
                    canonical,
                    recorded_at,
                ),
            )
            row = conn.execute(
                "SELECT canonical_bytes FROM object_admission_definitions "
                "WHERE definition_digest=?",
                (definition.digest,),
            ).fetchone()
            if row is None or bytes(row["canonical_bytes"]) != canonical:
                raise AuthorityPersistenceError(
                    "object admission definition identity conflict"
                )

    def persist_object_contracts(self) -> None:
        with self._lock, self._transaction() as conn:
            self._persist_object_contracts(
                conn, recorded_at=self._clock().to_text()
            )

    @staticmethod
    def _decode_canonical_object(data: bytes) -> Any:
        try:
            value = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError("stored object JSON is invalid") from exc
        if canonical_json_bytes(value) != data:
            raise AuthorityPersistenceError("stored object JSON is not canonical")
        return value

    def _require_canonical_record(self, row: sqlite3.Row) -> dict[str, Any]:
        """Decode an immutable canonical record and verify its stored digest."""

        data = bytes(row["canonical_bytes"])
        digest = str(row["canonical_digest"])
        if digest_bytes(data) != digest:
            raise AuthorityPersistenceError(
                "stored object record digest mismatch"
            )
        value = self._decode_canonical_object(data)
        if not isinstance(value, dict):
            raise AuthorityPersistenceError(
                "stored object record is not a canonical object"
            )
        return value

    def _admission_row(
        self, admission_id: str, *, conn: sqlite3.Connection | None = None
    ) -> sqlite3.Row:
        selected = conn or self._connection
        row = selected.execute(
            "SELECT a.*,h.current_version,"
            "h.current_version AS admission_lifecycle_version,"
            "v.state,v.event_id,v.recorded_at,b.size_bytes,"
            "bh.current_version AS blob_lifecycle_version,"
            "r.allowed AS rights_allowed,r.reason_code,r.decided_at,"
            "r.valid_from AS rights_valid_from,"
            "r.valid_until AS rights_valid_until,"
            "r.canonical_digest AS rights_digest,"
            "r.canonical_digest AS rights_decision_digest "
            "FROM object_admissions a "
            "JOIN object_admission_heads h ON h.admission_id=a.admission_id "
            "JOIN object_admission_versions v "
            "ON v.admission_id=h.admission_id "
            "AND v.lifecycle_version=h.current_version "
            "JOIN blob_identities b ON b.blob_digest=a.blob_digest "
            "JOIN blob_lifecycle_heads bh ON bh.blob_digest=a.blob_digest "
            "JOIN object_rights_decisions r "
            "ON r.rights_decision_id=a.rights_decision_id "
            "WHERE a.admission_id=?",
            (admission_id,),
        ).fetchone()
        if row is None:
            raise KeyError(admission_id)
        return row

    def _admission_activation_row(
        self, admission_id: str, *, conn: sqlite3.Connection | None = None
    ) -> sqlite3.Row:
        """Return the immutable admission result committed at activation.

        Idempotent command replay returns the original committed result, not a
        projection of later revocation, expiry, deletion, or blob lifecycle
        state.  This row is metadata only and therefore deliberately does not
        require current rights or bytes.
        """

        selected = conn or self._connection
        row = selected.execute(
            "SELECT a.*,1 AS current_version,"
            "1 AS admission_lifecycle_version,v.state,v.event_id,v.recorded_at,"
            "b.size_bytes,1 AS blob_lifecycle_version,"
            "r.allowed AS rights_allowed,r.reason_code,r.decided_at,"
            "r.valid_from AS rights_valid_from,"
            "r.valid_until AS rights_valid_until,"
            "r.canonical_digest AS rights_digest,"
            "r.canonical_digest AS rights_decision_digest "
            "FROM object_admissions a "
            "JOIN object_admission_versions v "
            "ON v.admission_id=a.admission_id "
            "AND v.lifecycle_version=1 AND v.state='ACTIVE' "
            "JOIN blob_identities b ON b.blob_digest=a.blob_digest "
            "JOIN object_rights_decisions r "
            "ON r.rights_decision_id=a.rights_decision_id "
            "WHERE a.admission_id=?",
            (admission_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "committed admission lacks its immutable activation result"
            )
        return row

    def _blob_lifecycle_row(
        self, blob_digest: str, *, conn: sqlite3.Connection | None = None
    ) -> sqlite3.Row:
        selected = conn or self._connection
        row = selected.execute(
            "SELECT b.size_bytes,h.current_version,v.state,v.integrity_state,"
            "v.event_id,v.recorded_at FROM blob_identities b "
            "JOIN blob_lifecycle_heads h ON h.blob_digest=b.blob_digest "
            "JOIN blob_lifecycle_versions v "
            "ON v.blob_digest=h.blob_digest "
            "AND v.lifecycle_version=h.current_version "
            "WHERE b.blob_digest=?",
            (blob_digest,),
        ).fetchone()
        if row is None:
            raise KeyError(blob_digest)
        return row

    @staticmethod
    def _require_rights_current(row: sqlite3.Row, now: UtcTimestamp) -> None:
        if not bool(row["rights_allowed"]):
            raise ObjectAdmissionDenied(str(row["reason_code"]))
        decided_at = UtcTimestamp.parse(str(row["decided_at"]))
        valid_from = UtcTimestamp.parse(str(row["rights_valid_from"]))
        valid_until = (
            None
            if row["rights_valid_until"] is None
            else UtcTimestamp.parse(str(row["rights_valid_until"]))
        )
        if now.value < decided_at.value or now.value < valid_from.value:
            raise ObjectAdmissionDenied("RIGHTS_NOT_YET_VALID")
        if valid_until is not None and now.value >= valid_until.value:
            raise ObjectAdmissionDenied("RIGHTS_EXPIRED")

    def _current_admission_row(
        self,
        conn: sqlite3.Connection,
        admission_id: str,
        *,
        now: UtcTimestamp,
        require_active: bool = True,
        require_bytes: bool = True,
    ) -> sqlite3.Row:
        row = self._admission_row(admission_id, conn=conn)
        if require_active and str(row["state"]) != AdmissionState.ACTIVE.value:
            raise ObjectAdmissionDenied("object admission is not ACTIVE")
        valid_from = UtcTimestamp.parse(str(row["valid_from"]))
        valid_until = (
            None
            if row["valid_until"] is None
            else UtcTimestamp.parse(str(row["valid_until"]))
        )
        if now.value < valid_from.value:
            raise ObjectAdmissionDenied("object admission is not yet valid")
        if valid_until is not None and now.value >= valid_until.value:
            raise ObjectAdmissionDenied("object admission has expired")
        self._require_rights_current(row, now)
        deletion = self._active_deletion_for_blob(
            conn, str(row["blob_digest"])
        )
        if deletion is not None:
            state = DeletionState(str(deletion["state"]))
            if state in {
                DeletionState.TOMBSTONED,
                DeletionState.PHYSICALLY_REMOVED,
            }:
                raise ObjectAdmissionDenied(
                    "governed tombstone blocks object authority"
                )
        lifecycle = self._blob_lifecycle_row(
            str(row["blob_digest"]), conn=conn
        )
        if require_bytes and (
            str(lifecycle["state"]) != BlobLifecycleState.ACTIVE.value
            or str(lifecycle["integrity_state"])
            != BlobIntegrityState.VERIFIED.value
        ):
            raise ObjectAdmissionDenied("blob bytes are not ACTIVE and verified")
        return row

    def resolve_admission(
        self, admission_id: ObjectAdmissionId
    ) -> ObjectAdmissionDescriptor:
        if not isinstance(admission_id, ObjectAdmissionId):
            raise TypeError("admission lookup requires ObjectAdmissionId")
        now = self._clock()
        with self._lock:
            row = self._current_admission_row(
                self._connection,
                str(admission_id),
                now=now,
                require_active=True,
                require_bytes=True,
            )
            identity = BlobIdentity(
                str(row["blob_digest"]), int(row["size_bytes"])
            )
            with self._cas.pin(identity):
                pass
            return ObjectAdmissionDescriptor(
                admission_id=admission_id,
                blob_digest=identity.blob_digest,
                object_class=str(row["object_class"]),
                allowed_use=str(row["allowed_use"]),
                security_scope=str(row["security_scope"]),
                retention_scope=str(row["retention_scope"]),
                active=True,
            )

    def _object_payload_commit_guard(
        self, conn: sqlite3.Connection, grant: _AuthorizedCommandGrant
    ) -> Iterator[_PinnedBlob]:
        if grant.payload.kind != PayloadMode.OBJECT_ADMISSION.value:
            return super()._object_payload_commit_guard(conn, grant)
        if grant.payload.object_admission_id is None:
            raise UnsupportedPayloadMode(
                "object payload requires admission identity"
            )
        now = self._clock()
        row = self._current_admission_row(
            conn,
            str(grant.payload.object_admission_id),
            now=now,
            require_active=True,
            require_bytes=True,
        )
        expected = (
            str(row["object_class"]) == grant.definition.required_object_class
            and str(row["allowed_use"])
            == grant.definition.required_allowed_use
            and str(row["security_scope"]) == grant.definition.security_scope
            and str(row["retention_scope"])
            == grant.definition.retention_scope
            and str(row["blob_digest"]) == grant.payload.blob_digest
            and str(row["blob_digest"]) == grant.payload.digest
        )
        if not expected:
            raise ObjectAdmissionDenied(
                "object admission semantics do not match command definition"
            )
        identity = BlobIdentity(
            str(row["blob_digest"]), int(row["size_bytes"])
        )
        pinned = self._cas.pin(identity)

        @contextmanager
        def guard() -> Iterator[_PinnedBlob]:
            try:
                yield pinned
            finally:
                pinned.close()

        return guard()

    def _final_object_payload_commit_check(
        self,
        conn: sqlite3.Connection,
        grant: _AuthorizedCommandGrant,
        pinned: _PinnedBlob,
    ) -> None:
        # Re-resolve every mutable authority record inside the command write
        # transaction.  The earlier descriptor is deliberately ignored.
        now = self._clock()
        row = self._current_admission_row(
            conn,
            str(grant.payload.object_admission_id),
            now=now,
            require_active=True,
            require_bytes=True,
        )
        if (
            str(row["blob_digest"]) != pinned.identity.blob_digest
            or int(row["size_bytes"]) != pinned.identity.size_bytes
        ):
            raise ObjectAdmissionDenied(
                "object authority changed while command was committing"
            )
        self._cas.verify_pinned(pinned)

    @staticmethod
    def _validate_object_admission_payload_record(
        conn: sqlite3.Connection, row: sqlite3.Row
    ) -> None:
        if row["payload_bytes"] is not None:
            raise AuthorityPersistenceError(
                "object admission payload cannot embed bytes"
            )
        if row["object_admission_id"] is None:
            raise AuthorityPersistenceError(
                "object admission payload lacks admission identity"
            )
        admission = conn.execute(
            "SELECT blob_digest FROM object_admissions WHERE admission_id=?",
            (str(row["object_admission_id"]),),
        ).fetchone()
        if admission is None:
            raise AuthorityPersistenceError(
                "object admission payload identity does not resolve"
            )
        if str(admission["blob_digest"]) != str(row["payload_digest"]):
            raise AuthorityPersistenceError(
                "object payload digest differs from admitted blob"
            )

    def _active_deletion_for_blob(
        self, conn: sqlite3.Connection, blob_digest: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT d.deletion_id,h.current_version,v.state,v.recorded_at "
            "FROM object_deletions d "
            "JOIN object_deletion_heads h ON h.deletion_id=d.deletion_id "
            "JOIN object_deletion_versions v "
            "ON v.deletion_id=h.deletion_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE d.blob_digest=? "
            "AND v.state!='PHYSICALLY_REMOVED' "
            "ORDER BY d.created_at DESC LIMIT 1",
            (blob_digest,),
        ).fetchone()

    def _admission_view_from_row(self, row: sqlite3.Row) -> ObjectAdmissionView:
        activation_event = (
            None
            if row["event_id"] is None
            else EventId.parse(str(row["event_id"]))
        )
        state = AdmissionState(str(row["state"]))
        return ObjectAdmissionView(
            admission_id=ObjectAdmissionId.parse(str(row["admission_id"])),
            admission_type=str(row["admission_type"]),
            definition_version=str(row["definition_version"]),
            definition_digest=str(row["definition_digest"]),
            blob=BlobIdentity(
                str(row["blob_digest"]), int(row["size_bytes"])
            ),
            object_class=str(row["object_class"]),
            allowed_use=str(row["allowed_use"]),
            security_scope=str(row["security_scope"]),
            retention_scope=str(row["retention_scope"]),
            rights_decision_id=RightsDecisionId.parse(
                str(row["rights_decision_id"])
            ),
            rights_decision_digest=str(row["rights_digest"]),
            valid_from=UtcTimestamp.parse(str(row["valid_from"])),
            valid_until=(
                None
                if row["valid_until"] is None
                else UtcTimestamp.parse(str(row["valid_until"]))
            ),
            lifecycle_version=int(row["current_version"]),
            state=state,
            activation_event_id=activation_event
        )

    def admission_view(self, admission_id: ObjectAdmissionId) -> ObjectAdmissionView:
        if not isinstance(admission_id, ObjectAdmissionId):
            raise TypeError("admission view requires ObjectAdmissionId")
        with self._lock:
            return self._admission_view_from_row(
                self._admission_row(str(admission_id))
            )

    def rights_view(
        self, rights_decision_id: RightsDecisionId
    ) -> RightsDecisionView:
        if not isinstance(rights_decision_id, RightsDecisionId):
            raise TypeError("rights view requires RightsDecisionId")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM object_rights_decisions WHERE rights_decision_id=?",
                (str(rights_decision_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(rights_decision_id))
            canonical = bytes(row["canonical_bytes"])
            digest = str(row["canonical_digest"])
            if digest_bytes(canonical) != digest:
                raise AuthorityPersistenceError(
                    "stored rights decision digest mismatch"
                )
            value = self._decode_canonical_object(canonical)
            if not isinstance(value, dict):
                raise AuthorityPersistenceError(
                    "stored rights decision is not an object"
                )
            return RightsDecisionView(
                rights_decision_id=rights_decision_id,
                authentication_context_id=str(row["authentication_context_id"]),
                authorization_request_digest=str(
                    row["authorization_request_digest"]
                ),
                authorization_decision_id=str(row["authorization_decision_id"]),
                policy_contract_digest=str(row["policy_contract_digest"]),
                admission_definition_digest=str(
                    row["admission_definition_digest"]
                ),
                blob=BlobIdentity(
                    str(row["blob_digest"]), int(row["size_bytes"])
                ),
                object_class=str(row["object_class"]),
                allowed_use=str(row["allowed_use"]),
                security_scope=str(row["security_scope"]),
                retention_scope=str(row["retention_scope"]),
                allowed=bool(row["allowed"]),
                reason_code=str(row["reason_code"]),
                decided_at=UtcTimestamp.parse(str(row["decided_at"])),
                valid_from=UtcTimestamp.parse(str(row["valid_from"])),
                valid_until=(
                    None
                    if row["valid_until"] is None
                    else UtcTimestamp.parse(str(row["valid_until"]))
                ),
                canonical_digest=digest,
            )

    def blob_view(self, blob_digest: str) -> BlobLifecycleView:
        validate_sha256_digest(blob_digest, field="blob_digest")
        with self._lock:
            row = self._blob_lifecycle_row(blob_digest)
            return BlobLifecycleView(
                blob=BlobIdentity(blob_digest, int(row["size_bytes"])),
                lifecycle_version=int(row["current_version"]),
                state=BlobLifecycleState(str(row["state"])),
                integrity_state=BlobIntegrityState(
                    str(row["integrity_state"])
                ),
                recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
                event_id=(
                    None
                    if row["event_id"] is None
                    else EventId.parse(str(row["event_id"]))
                ),
            )

    def object_liveness(
        self, conn: sqlite3.Connection, blob_digest: str
    ) -> ObjectLivenessSnapshot:
        row = conn.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM object_admissions a "
            "JOIN object_admission_heads h ON h.admission_id=a.admission_id "
            "JOIN object_admission_versions v "
            "ON v.admission_id=h.admission_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE a.blob_digest=? AND v.state='ACTIVE'),"
            "(SELECT COUNT(*) FROM object_admissions a "
            "JOIN object_admission_heads h ON h.admission_id=a.admission_id "
            "JOIN object_admission_versions v "
            "ON v.admission_id=h.admission_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE a.blob_digest=? AND v.state='PENDING'),"
            "(SELECT COUNT(*) FROM authority_payloads "
            "WHERE payload_digest=? AND object_admission_id IS NOT NULL),"
            "(SELECT COUNT(*) FROM object_recovery_pins p "
            "JOIN object_recovery_pin_heads h ON h.pin_id=p.pin_id "
            "JOIN object_recovery_pin_versions v "
            "ON v.pin_id=h.pin_id AND v.lifecycle_version=h.current_version "
            "WHERE p.blob_digest=? AND v.state='ACTIVE')",
            (blob_digest, blob_digest, blob_digest, blob_digest),
        ).fetchone()
        deletion = self._active_deletion_for_blob(conn, blob_digest)
        return ObjectLivenessSnapshot(
            active_admissions=int(row[0]),
            pending_admissions=int(row[1]),
            authority_references=int(row[2]),
            active_recovery_pins=int(row[3]),
            deletion_state=(
                None
                if deletion is None
                else DeletionState(str(deletion["state"]))
            ),
        )

    def _append_blob_lifecycle(
        self,
        conn: sqlite3.Connection,
        *,
        blob_digest: str,
        state: BlobLifecycleState,
        integrity: BlobIntegrityState,
        operation_id: str,
        event_id: str | None,
        recorded_at: UtcTimestamp,
    ) -> int:
        head = conn.execute(
            "SELECT current_version FROM blob_lifecycle_heads WHERE blob_digest=?",
            (blob_digest,),
        ).fetchone()
        if head is None:
            raise KeyError(blob_digest)
        next_version = int(head["current_version"]) + 1
        detail = {
            "blob_digest": blob_digest,
            "lifecycle_version": next_version,
            "state": state.value,
            "integrity_state": integrity.value,
            "operation_id": operation_id,
            "event_id": event_id,
        }
        conn.execute(
            "INSERT INTO blob_lifecycle_versions("
            "blob_digest,lifecycle_version,state,integrity_state,"
            "operation_id,event_id,recorded_at,detail_digest) "
            "VALUES(?,?,?,?,?,?,?,?)",
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

    def _validate_relational_invariants(self, conn: sqlite3.Connection) -> None:
        super()._validate_relational_invariants(conn)
        missing = conn.execute(
            "SELECT a.admission_id FROM object_admission_heads h "
            "JOIN object_admissions a ON a.admission_id=h.admission_id "
            "LEFT JOIN object_admission_versions v "
            "ON v.admission_id=h.admission_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE v.admission_id IS NULL LIMIT 1"
        ).fetchone()
        if missing is not None:
            raise AuthorityPersistenceError(
                "object admission head does not resolve exact version"
            )
        active_without_event = conn.execute(
            "SELECT v.admission_id FROM object_admission_versions v "
            "WHERE v.state='ACTIVE' AND v.event_id IS NULL LIMIT 1"
        ).fetchone()
        if active_without_event is not None:
            raise AuthorityPersistenceError(
                "ACTIVE object admission lacks committed activation event"
            )
        blob_missing = conn.execute(
            "SELECT h.blob_digest FROM blob_lifecycle_heads h "
            "LEFT JOIN blob_lifecycle_versions v "
            "ON v.blob_digest=h.blob_digest "
            "AND v.lifecycle_version=h.current_version "
            "WHERE v.blob_digest IS NULL LIMIT 1"
        ).fetchone()
        if blob_missing is not None:
            raise AuthorityPersistenceError(
                "blob lifecycle head does not resolve exact version"
            )

    def _validate_immutable_records(self, conn: sqlite3.Connection) -> None:
        super()._validate_immutable_records(conn)
        for table, bytes_column, digest_column in (
            (
                "rights_policy_contracts",
                "canonical_bytes",
                "contract_digest",
            ),
            (
                "hydration_policy_contracts",
                "canonical_bytes",
                "contract_digest",
            ),
            (
                "object_admission_definitions",
                "canonical_bytes",
                "definition_digest",
            ),
            (
                "object_admission_preflights",
                "canonical_bytes",
                "canonical_digest",
            ),
            (
                "object_rights_decisions",
                "canonical_bytes",
                "canonical_digest",
            ),
            (
                "object_access_decisions",
                "canonical_bytes",
                "canonical_digest",
            ),
        ):
            for row in conn.execute(
                f"SELECT {bytes_column},{digest_column} FROM {table}"
            ).fetchall():
                data = bytes(row[bytes_column])
                value = self._decode_canonical_object(data)
                expected = str(row[digest_column])
                # Contract/definition primary identities are digests over the
                # canonical contract bytes. Other records retain an independent
                # canonical_digest column.
                if digest_bytes(canonical_json_bytes(value)) != expected:
                    raise AuthorityPersistenceError(
                        f"immutable {table} canonical digest mismatch"
                    )

    def _validate_registry_coverage(self, conn: sqlite3.Connection) -> None:
        super()._validate_registry_coverage(conn)
        for definition in self._admission_registry.definitions():
            row = conn.execute(
                "SELECT canonical_bytes FROM object_admission_definitions "
                "WHERE definition_digest=?",
                (definition.digest,),
            ).fetchone()
            if row is None or bytes(row["canonical_bytes"]) != canonical_json_bytes(
                definition.canonical_value()
            ):
                raise AuthorityPersistenceError(
                    "retained admission definition is missing from authority"
                )
        for contract in self._rights_policies.contracts():
            row = conn.execute(
                "SELECT canonical_bytes FROM rights_policy_contracts "
                "WHERE contract_digest=?",
                (contract.contract_digest,),
            ).fetchone()
            if row is None or bytes(row["canonical_bytes"]) != canonical_json_bytes(
                contract.canonical_value()
            ):
                raise AuthorityPersistenceError(
                    "retained rights policy is missing from authority"
                )
        for contract in self._hydration_policies.contracts():
            row = conn.execute(
                "SELECT canonical_bytes FROM hydration_policy_contracts "
                "WHERE contract_digest=?",
                (contract.contract_digest,),
            ).fetchone()
            if row is None or bytes(row["canonical_bytes"]) != canonical_json_bytes(
                contract.canonical_value()
            ):
                raise AuthorityPersistenceError(
                    "retained hydration policy is missing from authority"
                )

    def _known_installed_digests(self) -> frozenset[str]:
        return frozenset(
            str(row["blob_digest"])
            for row in self._connection.execute(
                "SELECT b.blob_digest FROM blob_identities b "
                "JOIN blob_lifecycle_heads h ON h.blob_digest=b.blob_digest "
                "JOIN blob_lifecycle_versions v "
                "ON v.blob_digest=h.blob_digest "
                "AND v.lifecycle_version=h.current_version "
                "WHERE v.state IN ('INSTALLED','ACTIVE','DELETION_PENDING')"
            ).fetchall()
        )

    def _reconcile_objects(self) -> None:
        with self._lock:
            self._persist_object_contracts(
                self._connection, recorded_at=self._clock().to_text()
            )
            self._reconcile_staging_records()
            # An install can complete durably before SQLite commit.  Such a file
            # has no authoritative blob identity and is safe to remove.
            self._cas.cleanup_unreferenced_installed(
                known_digests=frozenset(
                    str(row["blob_digest"])
                    for row in self._connection.execute(
                        "SELECT blob_digest FROM blob_identities"
                    ).fetchall()
                )
            )
            self._reconcile_blob_integrity()
            self._reconcile_expired_rights()
            self._reconcile_deletions()

    def _reconcile_staging_records(self) -> None:
        records = self._connection.execute(
            "SELECT stage_id,staged_name,state FROM object_staging_records"
        ).fetchall()
        for row in records:
            state = str(row["state"])
            path = self._cas.staging_root / str(row["staged_name"])
            if state in {"COMMITTED", "FAILED", "CLEANED"} and path.exists():
                path.unlink()
                self._cas._fsync_directory(self._cas.staging_root)
                if state != "COMMITTED":
                    self._connection.execute(
                        "UPDATE object_staging_records "
                        "SET state='CLEANED',updated_at=? WHERE stage_id=?",
                        (self._clock().to_text(), str(row["stage_id"])),
                    )
            elif state == "STAGED" and not path.exists():
                self._connection.execute(
                    "UPDATE object_staging_records "
                    "SET state='FAILED',failure_code='MISSING_STAGED_BYTES',updated_at=? "
                    "WHERE stage_id=?",
                    (self._clock().to_text(), str(row["stage_id"])),
                )
        keep = frozenset(
            str(row["staged_name"])
            for row in self._connection.execute(
                "SELECT staged_name FROM object_staging_records WHERE state='STAGED'"
            ).fetchall()
        )
        self._cas.cleanup_staging(keep_names=keep)

    def _reconcile_blob_integrity(self) -> None:
        rows = self._connection.execute(
            "SELECT b.blob_digest,b.size_bytes,v.state,v.integrity_state "
            "FROM blob_identities b "
            "JOIN blob_lifecycle_heads h ON h.blob_digest=b.blob_digest "
            "JOIN blob_lifecycle_versions v "
            "ON v.blob_digest=h.blob_digest "
            "AND v.lifecycle_version=h.current_version"
        ).fetchall()
        for row in rows:
            state = BlobLifecycleState(str(row["state"]))
            identity = BlobIdentity(
                str(row["blob_digest"]), int(row["size_bytes"])
            )
            if state in {
                BlobLifecycleState.INSTALLED,
                BlobLifecycleState.ACTIVE,
                BlobLifecycleState.DELETION_PENDING,
            }:
                try:
                    with self._cas.pin(identity):
                        pass
                except ObjectIntegrityError as exc:
                    raise AuthorityPersistenceError(
                        "active authoritative blob bytes are missing or corrupt"
                    ) from exc
            if state is BlobLifecycleState.DELETED and self._cas.object_path(
                identity
            ).exists():
                # SQLite tombstone authority wins.  Bytes can reappear after a
                # crash, restore, or manual filesystem mutation; remove them
                # deterministically instead of allowing content resurrection.
                try:
                    self._cas.unlink(identity)
                except Exception as exc:
                    raise AuthorityPersistenceError(
                        "deleted blob bytes could not be reconciled"
                    ) from exc

    def _reconcile_expired_rights(self) -> None:
        now = self._clock().to_text()
        rows = self._connection.execute(
            "SELECT a.admission_id,h.current_version,v.state "
            "FROM object_admissions a "
            "JOIN object_admission_heads h ON h.admission_id=a.admission_id "
            "JOIN object_admission_versions v "
            "ON v.admission_id=h.admission_id "
            "AND v.lifecycle_version=h.current_version "
            "JOIN object_rights_decisions r "
            "ON r.rights_decision_id=a.rights_decision_id "
            "WHERE v.state IN ('PENDING','ACTIVE') "
            "AND (r.allowed=0 OR r.valid_until IS NOT NULL AND r.valid_until<=?)",
            (now,),
        ).fetchall()
        if rows:
            raise AuthorityPersistenceError(
                "expired or denied rights require an authenticated lifecycle event"
            )

    def _reconcile_deletions(self) -> None:
        rows = self._connection.execute(
            "SELECT d.deletion_id,d.blob_digest,h.current_version,v.state "
            "FROM object_deletions d "
            "JOIN object_deletion_heads h ON h.deletion_id=d.deletion_id "
            "JOIN object_deletion_versions v "
            "ON v.deletion_id=h.deletion_id "
            "AND v.lifecycle_version=h.current_version"
        ).fetchall()
        for row in rows:
            state = DeletionState(str(row["state"]))
            digest = str(row["blob_digest"])
            try:
                lifecycle = self._blob_lifecycle_row(digest)
            except KeyError as exc:
                raise AuthorityPersistenceError(
                    "governed deletion references an unknown blob"
                ) from exc
            identity = BlobIdentity(digest, int(lifecycle["size_bytes"]))
            path = self._cas.object_path(identity)
            pin_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM object_recovery_pins p "
                    "JOIN object_recovery_pin_heads h ON h.pin_id=p.pin_id "
                    "JOIN object_recovery_pin_versions v "
                    "ON v.pin_id=h.pin_id AND v.lifecycle_version=h.current_version "
                    "WHERE p.blob_digest=? AND v.state='ACTIVE'",
                    (digest,),
                ).fetchone()[0]
            )

            if state is DeletionState.PHYSICALLY_REMOVED:
                # SQLite tombstone authority wins over stray filesystem bytes.
                # Removing a reappeared file is deterministic reconciliation,
                # not a new editorial or lifecycle decision.
                if path.exists():
                    self._cas.unlink(identity)
                continue

            if state in {DeletionState.REQUESTED, DeletionState.FAILED}:
                try:
                    with self._cas.pin(identity):
                        pass
                except ObjectIntegrityError as exc:
                    raise AuthorityPersistenceError(
                        "pre-tombstone governed deletion has missing or corrupt bytes"
                    ) from exc
                continue

            if state is DeletionState.TOMBSTONED and pin_count:
                try:
                    with self._cas.pin(identity):
                        pass
                except ObjectIntegrityError as exc:
                    raise AuthorityPersistenceError(
                        "recovery-pinned tombstone has missing or corrupt bytes"
                    ) from exc
                continue

            if state is DeletionState.TOMBSTONED:
                # Hydration is already blocked.  Bytes may still await an
                # authenticated completion operation, or an interrupted unlink
                # may already have removed them.  Startup never invents the
                # terminal lifecycle event; it only preserves non-resurrection.
                continue

            raise AuthorityPersistenceError(
                f"unsupported governed deletion state during reconciliation: {state.value}"
            )
