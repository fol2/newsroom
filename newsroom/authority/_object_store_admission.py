from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import sqlite3
from typing import Any

from ._capability import _AuthorizedCommandGrant
from ._object_capability import (
    _AdmissionCommitGrant,
    _AdmissionPreflightGrant,
)
from ._object_cas import _StagedBlob
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical
from .objects import (
    AdmissionState,
    BlobIdentity,
    BlobIntegrityState,
    BlobLifecycleState,
    ObjectAdmissionId,
    ObjectAdmissionView,
    RightsDecisionId,
)
from .persistence import AuthorityPersistenceError, IdempotencyConflict
from .types import EventId, UtcTimestamp


@dataclass(frozen=True, slots=True)
class _AdmissionCommitResult:
    admission: ObjectAdmissionView
    replayed: bool


@dataclass(frozen=True, slots=True)
class _AdmissionReplayContract:
    stable_semantic_request_digest: str
    admission_type: str
    admission_definition_digest: str
    rights_policy_contract_digest: str


class _ObjectAdmissionStoreMixin:
    """Two-phase admission persistence and atomic activation event commit."""

    def _persist_preflight(
        self,
        conn: sqlite3.Connection,
        grant: _AdmissionPreflightGrant,
        *,
        recorded_at: str,
    ) -> None:
        self._object_issuer.verify_preflight(grant, now=self._clock())
        self._persist_security_records(
            conn,
            authentication=grant.authentication,
            request=grant.authorization_request,
            decision=grant.authorization,
            recorded_at=recorded_at,
        )
        reservation = (
            grant.idempotency_namespace,
            grant.request.idempotency_key,
            grant.stable_semantic_request_digest,
            grant.request.admission_type,
            grant.definition.digest,
            grant.rights_policy.contract_digest,
        )
        conn.execute(
            "INSERT OR IGNORE INTO object_admission_idempotency("
            "idempotency_namespace,idempotency_key,"
            "stable_semantic_request_digest,admission_type,"
            "admission_definition_digest,rights_policy_contract_digest,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (*reservation, recorded_at),
        )
        reserved = conn.execute(
            "SELECT stable_semantic_request_digest,admission_type,"
            "admission_definition_digest,rights_policy_contract_digest "
            "FROM object_admission_idempotency "
            "WHERE idempotency_namespace=? AND idempotency_key=?",
            reservation[:2],
        ).fetchone()
        if reserved is None or (
            str(reserved["stable_semantic_request_digest"]) != reservation[2]
            or str(reserved["admission_type"]) != reservation[3]
            or str(reserved["admission_definition_digest"]) != reservation[4]
            or str(reserved["rights_policy_contract_digest"]) != reservation[5]
        ):
            raise IdempotencyConflict(
                "admission idempotency identity belongs to another semantic request"
            )

        canonical = canonical_json_bytes(grant.unsigned_value())
        canonical_digest = digest_bytes(canonical)
        conn.execute(
            "INSERT OR IGNORE INTO object_admission_preflights("
            "preflight_id,idempotency_namespace,idempotency_key,"
            "stable_semantic_request_digest,admission_type,"
            "admission_definition_digest,rights_policy_contract_digest,"
            "authentication_context_id,authorization_request_digest,"
            "authorization_decision_id,checked_at,expires_at,"
            "canonical_bytes,canonical_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(grant.preflight_id),
                grant.idempotency_namespace,
                grant.request.idempotency_key,
                grant.stable_semantic_request_digest,
                grant.request.admission_type,
                grant.definition.digest,
                grant.rights_policy.contract_digest,
                str(grant.authentication.authentication_context_id),
                grant.authorization_request.request_digest,
                str(grant.authorization.authorization_decision_id),
                grant.checked_at.to_text(),
                grant.expires_at.to_text(),
                canonical,
                canonical_digest,
            ),
        )
        row = conn.execute(
            "SELECT * FROM object_admission_preflights WHERE preflight_id=?",
            (str(grant.preflight_id),),
        ).fetchone()
        if (
            row is None
            or bytes(row["canonical_bytes"]) != canonical
            or str(row["canonical_digest"]) != canonical_digest
        ):
            raise AuthorityPersistenceError(
                "preflight identity already belongs to another exact request"
            )

    def record_stage(
        self, preflight: _AdmissionPreflightGrant, staged: _StagedBlob
    ) -> None:
        self._object_issuer.verify_preflight(preflight, now=self._clock())
        if staged.identity.size_bytes < 0:
            raise AuthorityPersistenceError("staged size is invalid")
        with self._lock, self._transaction() as conn:
            recorded_at = self._clock().to_text()
            self._persist_object_contracts(conn, recorded_at=recorded_at)
            self._persist_preflight(conn, preflight, recorded_at=recorded_at)
            conn.execute(
                "INSERT INTO object_staging_records("
                "stage_id,preflight_id,staged_name,state,blob_digest,size_bytes,"
                "created_at,updated_at,failure_code) VALUES(?,?,?,?,?,?,?,?,NULL)",
                (
                    staged.stage_id,
                    str(preflight.preflight_id),
                    staged.staged_name,
                    "STAGED",
                    staged.identity.blob_digest,
                    staged.identity.size_bytes,
                    staged.created_at.to_text(),
                    recorded_at,
                ),
            )

    def fail_stage(self, stage_id: str, *, failure_code: str) -> None:
        with self._lock, self._transaction() as conn:
            row = conn.execute(
                "SELECT staged_name,state FROM object_staging_records WHERE stage_id=?",
                (stage_id,),
            ).fetchone()
            if row is None:
                return
            state = str(row["state"])
            if state in {"COMMITTED", "CLEANED"}:
                return
            conn.execute(
                "UPDATE object_staging_records SET state='FAILED',failure_code=?,updated_at=? "
                "WHERE stage_id=?",
                (failure_code, self._clock().to_text(), stage_id),
            )
            path = self._cas.staging_root / str(row["staged_name"])
            if path.exists():
                path.unlink()
                self._cas._fsync_directory(self._cas.staging_root)
            conn.execute(
                "UPDATE object_staging_records SET state='CLEANED',updated_at=? "
                "WHERE stage_id=?",
                (self._clock().to_text(), stage_id),
            )

    def find_admission_replay(
        self, preflight: _AdmissionPreflightGrant
    ) -> ObjectAdmissionView | None:
        self._object_issuer.verify_preflight(preflight, now=self._clock())
        with self._lock:
            reservation = self._connection.execute(
                "SELECT stable_semantic_request_digest,admission_type,"
                "admission_definition_digest,rights_policy_contract_digest "
                "FROM object_admission_idempotency "
                "WHERE idempotency_namespace=? AND idempotency_key=?",
                (
                    preflight.idempotency_namespace,
                    preflight.request.idempotency_key,
                ),
            ).fetchone()
            if reservation is not None and (
                str(reservation["stable_semantic_request_digest"])
                != preflight.stable_semantic_request_digest
                or str(reservation["admission_type"])
                != preflight.request.admission_type
                or str(reservation["admission_definition_digest"])
                != preflight.definition.digest
                or str(reservation["rights_policy_contract_digest"])
                != preflight.rights_policy.contract_digest
            ):
                raise IdempotencyConflict(
                    "admission idempotency identity belongs to another semantic request"
                )

            row = self._connection.execute(
                "SELECT o.result_bytes,o.result_digest "
                "FROM object_lifecycle_operations o "
                "WHERE o.operation_type='ADMISSION_ACTIVATE' "
                "AND o.idempotency_namespace=? AND o.idempotency_key=?",
                (
                    preflight.idempotency_namespace,
                    preflight.request.idempotency_key,
                ),
            ).fetchone()
            if row is None:
                return None
            if reservation is None:
                raise AuthorityPersistenceError(
                    "committed admission lacks its idempotency reservation"
                )
            data = bytes(row["result_bytes"])
            if digest_bytes(data) != str(row["result_digest"]):
                raise AuthorityPersistenceError(
                    "stored admission replay result digest mismatch"
                )
            value = self._decode_canonical_object(data)
            if not isinstance(value, dict) or set(value) != {
                "admission_id",
                "blob_digest",
                "rights_decision_id",
            }:
                raise AuthorityPersistenceError(
                    "stored admission replay result shape is invalid"
                )
            admission_id = ObjectAdmissionId.parse(str(value["admission_id"]))
            activation = self._admission_activation_row(
                str(admission_id), conn=self._connection
            )
            if (
                str(activation["blob_digest"])
                != str(value["blob_digest"])
                or str(activation["rights_decision_id"])
                != str(value["rights_decision_id"])
            ):
                raise AuthorityPersistenceError(
                    "stored admission replay result differs from activation records"
                )
            return self._admission_view_from_row(activation)

    def committed_admission_replay_contract(
        self,
        *,
        idempotency_namespace: str,
        idempotency_key: str,
    ) -> _AdmissionReplayContract | None:
        """Resolve retained semantics only for an already committed admission.

        An unfinished preflight or staging reservation must not pin an obsolete
        policy after a rollout.  Historical contracts are selected only when a
        committed result exists and the retry is therefore result recovery.
        """

        with self._lock:
            row = self._connection.execute(
                "SELECT i.stable_semantic_request_digest,i.admission_type,"
                "i.admission_definition_digest,i.rights_policy_contract_digest "
                "FROM object_admission_idempotency i "
                "JOIN object_lifecycle_operations o "
                "ON o.operation_type='ADMISSION_ACTIVATE' "
                "AND o.idempotency_namespace=i.idempotency_namespace "
                "AND o.idempotency_key=i.idempotency_key "
                "WHERE i.idempotency_namespace=? AND i.idempotency_key=?",
                (idempotency_namespace, idempotency_key),
            ).fetchone()
            if row is None:
                return None
            return _AdmissionReplayContract(
                stable_semantic_request_digest=str(
                    row["stable_semantic_request_digest"]
                ),
                admission_type=str(row["admission_type"]),
                admission_definition_digest=str(
                    row["admission_definition_digest"]
                ),
                rights_policy_contract_digest=str(
                    row["rights_policy_contract_digest"]
                ),
            )

    @staticmethod
    def _verify_lifecycle_grant(
        grant: _AuthorizedCommandGrant,
        *,
        expected_command_type: str,
        expected_payload: dict[str, object],
        principal_id: str,
        authority_domain: str,
    ) -> None:
        if grant.definition.command_type != expected_command_type:
            raise AuthorityPersistenceError(
                "lifecycle command type differs from object operation"
            )
        if grant.authentication.principal_id != principal_id:
            raise AuthorityPersistenceError(
                "lifecycle command principal differs from object operation"
            )
        if grant.authentication.authority_domain != authority_domain:
            raise AuthorityPersistenceError(
                "lifecycle command domain differs from object operation"
            )
        if grant.payload.inline_bytes != canonical_json_bytes(expected_payload):
            raise AuthorityPersistenceError(
                "lifecycle payload differs from exact object mutation"
            )

    def commit_admission(
        self,
        grant: _AdmissionCommitGrant,
        *,
        lifecycle_grant_factory: Callable[
            [ObjectAdmissionId, RightsDecisionId, dict[str, object]],
            _AuthorizedCommandGrant,
        ],
    ) -> _AdmissionCommitResult:
        now = self._clock()
        self._object_issuer.verify_admission(grant, now=now)
        with self._lock:
            existing = self.find_admission_replay(grant.preflight)
            if existing is not None:
                stage_path = self._cas.staging_root / grant.staged_name
                if stage_path.exists():
                    self._cas.discard_stage(
                        _StagedBlob(
                            stage_id=grant.stage_id,
                            staged_name=grant.staged_name,
                            path=stage_path,
                            identity=grant.blob,
                            created_at=grant.preflight.checked_at,
                        )
                    )
                return _AdmissionCommitResult(existing, replayed=True)

            stage_row = self._connection.execute(
                "SELECT * FROM object_staging_records WHERE stage_id=?",
                (grant.stage_id,),
            ).fetchone()
            if stage_row is None:
                raise AuthorityPersistenceError(
                    "admission staging record does not exist"
                )
            if (
                str(stage_row["state"]) != "STAGED"
                or str(stage_row["preflight_id"])
                != str(grant.preflight.preflight_id)
                or str(stage_row["staged_name"]) != grant.staged_name
                or str(stage_row["blob_digest"]) != grant.blob.blob_digest
                or int(stage_row["size_bytes"]) != grant.blob.size_bytes
            ):
                raise AuthorityPersistenceError(
                    "staging record differs from final admission capability"
                )
            staged = _StagedBlob(
                stage_id=grant.stage_id,
                staged_name=grant.staged_name,
                path=self._cas.staging_root / grant.staged_name,
                identity=grant.blob,
                created_at=grant.preflight.checked_at,
            )
            pinned = self._cas.install(staged)
            admission_id = ObjectAdmissionId.new()
            rights_decision_id = RightsDecisionId.new()
            operation_id = str(grant.operation_id)
            payload = {
                "operation_id": operation_id,
                "admission_id": str(admission_id),
                "blob_digest": grant.blob.blob_digest,
                "size_bytes": grant.blob.size_bytes,
                "definition_digest": grant.preflight.definition.digest,
                "rights_decision_id": str(rights_decision_id),
                "object_class": grant.preflight.definition.object_class,
                "allowed_use": grant.preflight.definition.allowed_use,
                "security_scope": grant.preflight.definition.security_scope,
                "retention_scope": grant.preflight.definition.retention_scope,
                "valid_from": grant.rights.valid_from.to_text(),
                "valid_until": (
                    None
                    if grant.rights.valid_until is None
                    else grant.rights.valid_until.to_text()
                ),
            }
            lifecycle_grant = lifecycle_grant_factory(
                admission_id, rights_decision_id, payload
            )
            self._issuer.verify(lifecycle_grant)
            self._verify_lifecycle_grant(
                lifecycle_grant,
                expected_command_type="object.admission.activate",
                expected_payload=payload,
                principal_id=grant.authentication.principal_id,
                authority_domain=grant.authentication.authority_domain,
            )
            sqlite_committed = False
            try:
                with self._transaction() as conn:
                    recorded_at = self._clock()
                    self._object_issuer.verify_admission(
                        grant, now=recorded_at
                    )
                    self._cas.verify_pinned(pinned)
                    recorded_text = recorded_at.to_text()
                    self._persist_object_contracts(
                        conn, recorded_at=recorded_text
                    )
                    self._persist_preflight(
                        conn, grant.preflight, recorded_at=recorded_text
                    )
                    self._persist_security_records(
                        conn,
                        authentication=grant.authentication,
                        request=grant.authorization_request,
                        decision=grant.authorization,
                        recorded_at=recorded_text,
                    )
                    committed_event = self._commit_grant_in_transaction(
                        conn,
                        lifecycle_grant,
                        recorded_at=recorded_text,
                    )
                    self._persist_admission_rows(
                        conn,
                        grant=grant,
                        admission_id=admission_id,
                        rights_decision_id=rights_decision_id,
                        activation_event_id=EventId.parse(
                            committed_event.event_id
                        ),
                        recorded_at=recorded_at,
                    )
                    result_bytes = canonical_json_bytes(
                        {
                            "admission_id": str(admission_id),
                            "blob_digest": grant.blob.blob_digest,
                            "rights_decision_id": str(rights_decision_id),
                        }
                    )
                    result_digest = digest_bytes(result_bytes)
                    conn.execute(
                        "INSERT INTO object_lifecycle_operations("
                        "operation_id,operation_type,idempotency_namespace,"
                        "idempotency_key,stable_semantic_request_digest,"
                        "authentication_context_id,authorization_request_digest,"
                        "authorization_decision_id,command_id,event_id,"
                        "result_bytes,result_digest,committed_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            operation_id,
                            "ADMISSION_ACTIVATE",
                            grant.preflight.idempotency_namespace,
                            grant.preflight.request.idempotency_key,
                            grant.stable_semantic_request_digest,
                            str(grant.authentication.authentication_context_id),
                            grant.authorization_request.request_digest,
                            str(grant.authorization.authorization_decision_id),
                            committed_event.command_id,
                            committed_event.event_id,
                            result_bytes,
                            result_digest,
                            recorded_text,
                        ),
                    )
                    conn.execute(
                        "UPDATE object_staging_records "
                        "SET state='INSTALLED',updated_at=? WHERE stage_id=?",
                        (recorded_text, grant.stage_id),
                    )
                    conn.execute(
                        "UPDATE object_staging_records "
                        "SET state='COMMITTED',updated_at=? WHERE stage_id=?",
                        (recorded_text, grant.stage_id),
                    )
                    # Last check before SQLite commit: exact pinned bytes, path,
                    # link count and read-only mode must still match authority.
                    self._cas.verify_pinned(pinned)
                sqlite_committed = True
                # Staging cleanup occurs only after authority commit.  If it fails,
                # preserve the committed installed blob and surface an operational
                # error; replay/startup reconciliation will finish cleanup.
                self._cas.finish_stage(staged)
            except Exception:
                if not sqlite_committed:
                    try:
                        self._cas.discard_stage(staged)
                    finally:
                        if pinned.installed_new:
                            try:
                                self._cas.unlink(grant.blob)
                            except Exception:
                                pass
                raise
            finally:
                pinned.close()
            view = self.admission_view(admission_id)
            return _AdmissionCommitResult(view, replayed=False)

    def _persist_admission_rows(
        self,
        conn: sqlite3.Connection,
        *,
        grant: _AdmissionCommitGrant,
        admission_id: ObjectAdmissionId,
        rights_decision_id: RightsDecisionId,
        activation_event_id: EventId,
        recorded_at: UtcTimestamp,
    ) -> None:
        definition = grant.preflight.definition
        rights = grant.rights
        recorded_text = recorded_at.to_text()
        existing_blob = conn.execute(
            "SELECT size_bytes FROM blob_identities WHERE blob_digest=?",
            (grant.blob.blob_digest,),
        ).fetchone()
        if existing_blob is None:
            conn.execute(
                "INSERT INTO blob_identities(blob_digest,size_bytes,created_at) "
                "VALUES(?,?,?)",
                (
                    grant.blob.blob_digest,
                    grant.blob.size_bytes,
                    recorded_text,
                ),
            )
            lifecycle_rows = (
                (1, BlobLifecycleState.STAGING, BlobIntegrityState.UNVERIFIED, None),
                (2, BlobLifecycleState.INSTALLED, BlobIntegrityState.VERIFIED, None),
                (
                    3,
                    BlobLifecycleState.ACTIVE,
                    BlobIntegrityState.VERIFIED,
                    str(activation_event_id),
                ),
            )
            for version, state, integrity, event_id in lifecycle_rows:
                conn.execute(
                    "INSERT INTO blob_lifecycle_versions("
                    "blob_digest,lifecycle_version,state,integrity_state,"
                    "operation_id,event_id,recorded_at,detail_digest) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        grant.blob.blob_digest,
                        version,
                        state.value,
                        integrity.value,
                        str(grant.operation_id),
                        event_id,
                        recorded_text,
                        digest_canonical(
                            {
                                "blob": grant.blob.canonical_value(),
                                "state": state.value,
                                "integrity_state": integrity.value,
                                "operation_id": str(grant.operation_id),
                                "event_id": event_id,
                            }
                        ),
                    ),
                )
            conn.execute(
                "INSERT INTO blob_lifecycle_heads("
                "blob_digest,current_version,updated_at) VALUES(?,?,?)",
                (grant.blob.blob_digest, 3, recorded_text),
            )
        elif int(existing_blob["size_bytes"]) != grant.blob.size_bytes:
            raise AuthorityPersistenceError(
                "content digest already belongs to another exact size"
            )
        else:
            current = conn.execute(
                "SELECT v.state,v.integrity_state FROM blob_lifecycle_heads h "
                "JOIN blob_lifecycle_versions v "
                "ON v.blob_digest=h.blob_digest "
                "AND v.lifecycle_version=h.current_version "
                "WHERE h.blob_digest=?",
                (grant.blob.blob_digest,),
            ).fetchone()
            if (
                current is None
                or str(current["state"]) != BlobLifecycleState.ACTIVE.value
                or str(current["integrity_state"])
                != BlobIntegrityState.VERIFIED.value
            ):
                raise AuthorityPersistenceError(
                    "existing blob identity is not current ACTIVE/VERIFIED"
                )

        rights_value = {
            "rights_decision_id": str(rights_decision_id),
            "authentication_context_id": str(
                grant.authentication.authentication_context_id
            ),
            "authorization_request_digest": (
                grant.authorization_request.request_digest
            ),
            "authorization_decision_id": str(
                grant.authorization.authorization_decision_id
            ),
            **rights.canonical_value(),
        }
        rights_bytes = canonical_json_bytes(rights_value)
        rights_digest = digest_bytes(rights_bytes)
        conn.execute(
            "INSERT INTO object_rights_decisions("
            "rights_decision_id,authentication_context_id,"
            "authorization_request_digest,authorization_decision_id,"
            "rights_request_digest,policy_contract_digest,"
            "admission_definition_digest,blob_digest,size_bytes,"
            "object_class,allowed_use,security_scope,retention_scope,"
            "allowed,reason_code,decided_at,valid_from,valid_until,"
            "canonical_bytes,canonical_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(rights_decision_id),
                str(grant.authentication.authentication_context_id),
                grant.authorization_request.request_digest,
                str(grant.authorization.authorization_decision_id),
                rights.rights_request_digest,
                rights.policy_contract_digest,
                rights.admission_definition_digest,
                rights.blob.blob_digest,
                rights.blob.size_bytes,
                rights.object_class,
                rights.allowed_use,
                rights.security_scope,
                rights.retention_scope,
                int(rights.allowed),
                rights.reason_code,
                rights.decided_at.to_text(),
                rights.valid_from.to_text(),
                None
                if rights.valid_until is None
                else rights.valid_until.to_text(),
                rights_bytes,
                rights_digest,
            ),
        )
        conn.execute(
            "INSERT INTO object_admissions("
            "admission_id,admission_type,definition_version,definition_digest,"
            "rights_decision_id,blob_digest,object_class,allowed_use,"
            "security_scope,retention_scope,valid_from,valid_until,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(admission_id),
                definition.admission_type,
                definition.definition_version,
                definition.digest,
                str(rights_decision_id),
                grant.blob.blob_digest,
                definition.object_class,
                definition.allowed_use,
                definition.security_scope,
                definition.retention_scope,
                rights.valid_from.to_text(),
                None
                if rights.valid_until is None
                else rights.valid_until.to_text(),
                recorded_text,
            ),
        )
        conn.execute(
            "INSERT INTO object_admission_versions("
            "admission_id,lifecycle_version,state,operation_id,event_id,"
            "reason_code,recorded_at,detail_digest) VALUES(?,?,?,?,?,?,?,?)",
            (
                str(admission_id),
                1,
                AdmissionState.ACTIVE.value,
                str(grant.operation_id),
                str(activation_event_id),
                rights.reason_code,
                recorded_text,
                digest_canonical(
                    {
                        "admission_id": str(admission_id),
                        "state": AdmissionState.ACTIVE.value,
                        "event_id": str(activation_event_id),
                        "rights_decision_id": str(rights_decision_id),
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO object_admission_heads("
            "admission_id,current_version,updated_at) VALUES(?,?,?)",
            (str(admission_id), 1, recorded_text),
        )


__all__ = [
    "_AdmissionCommitResult",
    "_AdmissionReplayContract",
    "_ObjectAdmissionStoreMixin",
]
