from __future__ import annotations

import sqlite3

from ._object_capability import _HydrationGrant
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical
from .objects import (
    BlobIdentity,
    ObjectAccessDecisionId,
    ObjectAdmissionId,
    ObjectAccessDecisionView,
    ObjectAdmissionDenied,
    ObjectHydrationDenied,
)
from .persistence import AuthorityPersistenceError
from .types import (
    AuthenticationContextId,
    AuthorizationDecisionId,
    UtcTimestamp,
)


class _ObjectHydrationStoreMixin:
    """Authenticated, purpose-bound hydration with exact current-state cutoff."""

    def hydrate(
        self, grant: _HydrationGrant
    ) -> tuple[bytes, ObjectAccessDecisionView]:
        now = self._clock()
        self._object_issuer.verify_hydration(grant, now=now)
        policy = self._hydration_policies.resolve_exact(
            grant.policy.policy_id,
            grant.policy.contract_version,
            grant.policy.contract_digest,
        )
        with self._lock:
            with self._transaction() as conn:
                decided_at = self._clock()
                self._object_issuer.verify_hydration(
                    grant, now=decided_at
                )
                row = self._current_admission_row(
                    conn,
                    str(grant.request.admission_id),
                    now=decided_at,
                    require_active=True,
                    require_bytes=True,
                )
                definition = self._admission_registry.resolve_exact(
                    str(row["admission_type"]),
                    str(row["definition_version"]),
                    str(row["definition_digest"]),
                )
                if policy.contract_digest not in (
                    definition.hydration_policy_contract_digests
                ):
                    raise ObjectHydrationDenied(
                        "hydration policy is not admitted for this object use"
                    )
                authentication = grant.authentication
                if (
                    authentication.principal_id
                    not in policy.allowed_principal_ids
                    or authentication.authority_domain
                    not in policy.allowed_authority_domains
                ):
                    raise ObjectHydrationDenied(
                        "principal or authority domain is outside hydration policy"
                    )
                if str(row["object_class"]) not in policy.allowed_object_classes:
                    raise ObjectHydrationDenied(
                        "object class is outside hydration policy"
                    )
                if str(row["allowed_use"]) not in policy.allowed_uses:
                    raise ObjectHydrationDenied(
                        "object use is outside hydration policy"
                    )
                if (
                    str(row["security_scope"])
                    not in policy.allowed_security_scopes
                ):
                    raise ObjectHydrationDenied(
                        "security scope is outside hydration policy"
                    )
                if (
                    str(row["retention_scope"])
                    not in policy.allowed_retention_scopes
                ):
                    raise ObjectHydrationDenied(
                        "retention scope is outside hydration policy"
                    )
                blob = BlobIdentity(
                    str(row["blob_digest"]), int(row["size_bytes"])
                )
                offset = grant.request.offset
                length = (
                    blob.size_bytes - offset
                    if grant.request.length is None
                    else grant.request.length
                )
                if not policy.allow_ranges and (
                    offset != 0 or length != blob.size_bytes
                ):
                    raise ObjectHydrationDenied(
                        "hydration policy permits only a complete object read"
                    )
                if length > policy.max_bytes:
                    raise ObjectHydrationDenied(
                        "requested bytes exceed hydration policy"
                    )
                self._cas.limits.require_range(
                    total_size=blob.size_bytes,
                    offset=offset,
                    length=length,
                )
                pinned = self._cas.pin(blob)
                try:
                    self._cas.verify_pinned(pinned)
                    blob_lifecycle = self._blob_lifecycle_row(
                        blob.blob_digest, conn=conn
                    )
                    deletion = self._active_deletion_for_blob(
                        conn, blob.blob_digest
                    )
                    state_cutoff_value = {
                        "admission_id": str(grant.request.admission_id),
                        "admission_lifecycle_version": int(
                            row["admission_lifecycle_version"]
                        ),
                        "admission_state": str(row["state"]),
                        "rights_decision_id": str(row["rights_decision_id"]),
                        "rights_decision_digest": str(
                            row["rights_decision_digest"]
                        ),
                        "rights_valid_from": str(row["rights_valid_from"]),
                        "rights_valid_until": (
                            None
                            if row["rights_valid_until"] is None
                            else str(row["rights_valid_until"])
                        ),
                        "blob_digest": blob.blob_digest,
                        "blob_lifecycle_version": int(
                            blob_lifecycle["current_version"]
                        ),
                        "blob_state": str(blob_lifecycle["state"]),
                        "blob_integrity_state": str(
                            blob_lifecycle["integrity_state"]
                        ),
                        "deletion_id": (
                            None
                            if deletion is None
                            else str(deletion["deletion_id"])
                        ),
                        "deletion_lifecycle_version": (
                            None
                            if deletion is None
                            else int(deletion["current_version"])
                        ),
                        "deletion_state": (
                            None if deletion is None else str(deletion["state"])
                        ),
                        "offset": offset,
                        "length": length,
                    }
                    state_cutoff_bytes = canonical_json_bytes(
                        state_cutoff_value
                    )
                    state_cutoff = digest_bytes(state_cutoff_bytes)
                    access_decision_id = ObjectAccessDecisionId.new()
                    canonical_value = {
                        "access_decision_id": str(access_decision_id),
                        "policy_contract_digest": policy.contract_digest,
                        "authentication_context_id": str(
                            authentication.authentication_context_id
                        ),
                        "authorization_request_digest": (
                            grant.authorization_request.request_digest
                        ),
                        "authorization_decision_id": str(
                            grant.authorization.authorization_decision_id
                        ),
                        "principal_id": authentication.principal_id,
                        "authority_domain": authentication.authority_domain,
                        "purpose": policy.purpose,
                        "admission_id": str(grant.request.admission_id),
                        "object_class": str(row["object_class"]),
                        "allowed_use": str(row["allowed_use"]),
                        "security_scope": str(row["security_scope"]),
                        "retention_scope": str(row["retention_scope"]),
                        "offset": offset,
                        "allowed_bytes": length,
                        "state_cutoff": state_cutoff_value,
                        "state_cutoff_digest": state_cutoff,
                        "decided_at": decided_at.to_text(),
                    }
                    canonical = canonical_json_bytes(canonical_value)
                    canonical_digest = digest_bytes(canonical)
                    self._persist_security_records(
                        conn,
                        authentication=grant.authentication,
                        request=grant.authorization_request,
                        decision=grant.authorization,
                        recorded_at=decided_at.to_text(),
                    )
                    conn.execute(
                        "INSERT INTO object_access_decisions("
                        "access_decision_id,hydration_policy_contract_digest,"
                        "authentication_context_id,authorization_request_digest,"
                        "authorization_decision_id,principal_id,authority_domain,"
                        "purpose,admission_id,object_class,allowed_use,"
                        "security_scope,retention_scope,byte_offset,allowed_bytes,"
                        "state_cutoff_bytes,state_cutoff_digest,decided_at,"
                        "canonical_bytes,canonical_digest) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(access_decision_id),
                            policy.contract_digest,
                            str(authentication.authentication_context_id),
                            grant.authorization_request.request_digest,
                            str(grant.authorization.authorization_decision_id),
                            authentication.principal_id,
                            authentication.authority_domain,
                            policy.purpose,
                            str(grant.request.admission_id),
                            str(row["object_class"]),
                            str(row["allowed_use"]),
                            str(row["security_scope"]),
                            str(row["retention_scope"]),
                            offset,
                            length,
                            state_cutoff_bytes,
                            state_cutoff,
                            decided_at.to_text(),
                            canonical,
                            canonical_digest,
                        ),
                    )
                    # The state and pinned bytes are rechecked immediately before
                    # leaving the authority transaction.
                    self._current_admission_row(
                        conn,
                        str(grant.request.admission_id),
                        now=self._clock(),
                        require_active=True,
                        require_bytes=True,
                    )
                    self._cas.verify_pinned(pinned)
                    data = self._cas.read_range(
                        pinned, offset=offset, length=length
                    )
                finally:
                    pinned.close()
            return data, self.access_decision_view(access_decision_id)

    def access_decision_view(
        self, access_decision_id: ObjectAccessDecisionId
    ) -> ObjectAccessDecisionView:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM object_access_decisions WHERE access_decision_id=?",
                (str(access_decision_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(access_decision_id))
            value = self._require_canonical_record(row)
            if value.get("access_decision_id") != str(access_decision_id):
                raise AuthorityPersistenceError(
                    "access decision canonical identity mismatch"
                )
            cutoff_bytes = bytes(row["state_cutoff_bytes"])
            cutoff_digest = str(row["state_cutoff_digest"])
            cutoff_value = self._decode_canonical_object(cutoff_bytes)
            if digest_bytes(cutoff_bytes) != cutoff_digest:
                raise AuthorityPersistenceError(
                    "access decision state cutoff digest mismatch"
                )
            if (
                value.get("state_cutoff") != cutoff_value
                or value.get("state_cutoff_digest") != cutoff_digest
            ):
                raise AuthorityPersistenceError(
                    "access decision canonical cutoff differs from indexed record"
                )
            return ObjectAccessDecisionView(
                access_decision_id=access_decision_id,
                policy_contract_digest=str(
                    row["hydration_policy_contract_digest"]
                ),
                authentication_context_id=AuthenticationContextId.parse(
                    str(row["authentication_context_id"])
                ),
                authorization_request_digest=str(
                    row["authorization_request_digest"]
                ),
                authorization_decision_id=AuthorizationDecisionId.parse(
                    str(row["authorization_decision_id"])
                ),
                principal_id=str(row["principal_id"]),
                authority_domain=str(row["authority_domain"]),
                purpose=str(row["purpose"]),
                admission_id=ObjectAdmissionId.parse(str(row["admission_id"])),
                object_class=str(row["object_class"]),
                allowed_use=str(row["allowed_use"]),
                security_scope=str(row["security_scope"]),
                retention_scope=str(row["retention_scope"]),
                offset=int(row["byte_offset"]),
                allowed_bytes=int(row["allowed_bytes"]),
                state_cutoff_bytes=cutoff_bytes,
                state_cutoff_digest=cutoff_digest,
                decided_at=UtcTimestamp.parse(str(row["decided_at"])),
                canonical_digest=str(row["canonical_digest"]),
            )


__all__ = ["_ObjectHydrationStoreMixin"]
