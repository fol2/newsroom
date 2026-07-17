from __future__ import annotations

from collections.abc import BinaryIO, Callable
from typing import Any

from ._capability import (
    _AuthorizedCommandGrant,
    _CapabilityIssuer,
    _ResolvedPayload,
)
from ._object_store import _ObjectAuthorityStore
from ._rights import resolve_rights
from ._security import _AuthorizationRequest
from .auth import AuthenticationProof
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical
from .models import CommandDefinition
from .objects import (
    HydratedObject,
    ObjectAdmissionDefinition,
    ObjectAdmissionReceipt,
    ObjectAdmissionRegistry,
    ObjectAdmissionRequest,
    ObjectDeletionReceipt,
    ObjectLimits,
    StaticRightsResolver,
)
from .types import (
    AuditId,
    ObjectAdmissionId,
    PayloadMode,
    TrustScope,
    UtcTimestamp,
    require_token,
)


class _ObjectLifecycleService:
    def __init__(
        self,
        *,
        store: _ObjectAuthorityStore,
        admission_registry: ObjectAdmissionRegistry,
        rights_resolver: StaticRightsResolver,
        limits: ObjectLimits,
        authenticator: Any,
        authorizer: Any,
        issuer: _CapabilityIssuer,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        self._store = store
        self._admission_registry = admission_registry
        self._rights_resolver = rights_resolver
        self._limits = limits
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._issuer = issuer
        self._clock = clock

    def admit(
        self,
        request: ObjectAdmissionRequest,
        source: BinaryIO,
        proof: object,
    ) -> ObjectAdmissionReceipt:
        if not isinstance(request, ObjectAdmissionRequest):
            raise TypeError("object admission request must be typed")
        if not isinstance(proof, AuthenticationProof):
            raise TypeError("object admission requires AuthenticationProof")
        definition = self._admission_registry.resolve(request.admission_type)
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        preflight_digest = digest_canonical(
            {
                "operation": "OBJECT_ADMISSION_PREFLIGHT",
                "definition": definition.canonical_value(),
                "principal_id": authentication.principal_id,
                "authority_domain": authentication.authority_domain,
            }
        )
        self._authorize(
            authentication,
            operation_type=f"object.preflight:{definition.admission_type}",
            required_scope=definition.required_write_scope,
            stable_digest=preflight_digest,
            definition_digest=digest_canonical(definition.canonical_value()),
            aggregate_type="governed_object_admission",
            aggregate_id="preflight",
            event_type="governed.object.admission.preflight",
            payload_mode="NO_PAYLOAD",
            payload_schema_version="object_preflight_v1",
            trust_scope="OBSERVED",
            security_scope=definition.security_scope,
            retention_scope=definition.retention_scope,
            object_class=definition.object_class,
            allowed_use=definition.allowed_use,
            now=now,
        )
        self._rights_resolver.preflight(definition)
        namespace = digest_canonical(
            {
                "authority_domain": authentication.authority_domain,
                "principal_id": authentication.principal_id,
                "admission_type": definition.admission_type,
            }
        )
        existing = self._store.find_admission_operation(
            idempotency_namespace=namespace,
            idempotency_key=request.idempotency_key,
        )
        if existing is not None:
            return existing

        staged = self._store._blob_store.stage(
            source, object_class=definition.object_class
        )
        try:
            admission_id = ObjectAdmissionId.new()
            stable_digest = digest_canonical(
                {
                    "operation": "OBJECT_ADMISSION",
                    "definition": definition.canonical_value(),
                    "blob_digest": staged.blob_digest,
                    "size_bytes": staged.size_bytes,
                }
            )
            event_definition = self._admission_event_definition(definition)
            auth_request, authorization = self._authorize(
                authentication,
                operation_type=f"object.admit:{definition.admission_type}",
                required_scope=definition.required_write_scope,
                stable_digest=stable_digest,
                definition_digest=event_definition.digest,
                aggregate_type=event_definition.aggregate_type,
                aggregate_id=str(admission_id),
                event_type=event_definition.event_type,
                payload_mode=event_definition.payload_mode.value,
                payload_schema_version=event_definition.payload_schema_version,
                trust_scope=event_definition.trust_scope.value,
                security_scope=event_definition.security_scope,
                retention_scope=event_definition.retention_scope,
                object_class=definition.object_class,
                allowed_use=definition.allowed_use,
                now=now,
            )
            rights = resolve_rights(
                self._rights_resolver,
                definition,
                blob_digest=staged.blob_digest,
                authentication_context_id=str(
                    authentication.authentication_context_id
                ),
                authorization_decision_id=str(
                    authorization.authorization_decision_id
                ),
                principal_id=authentication.principal_id,
                authority_domain=authentication.authority_domain,
                now=now,
            )
            rights.require_current(now)
            admission_grant = self._issuer.issue_admission(
                definition=definition,
                admission_id=admission_id,
                blob_digest=staged.blob_digest,
                size_bytes=staged.size_bytes,
                authentication=authentication,
                authorization_request=auth_request,
                authorization=authorization,
                rights=rights,
                idempotency_namespace=namespace,
                idempotency_key=request.idempotency_key,
                stable_semantic_request_digest=stable_digest,
            )
            event_payload_bytes = canonical_json_bytes(
                {
                    "admission_id": str(admission_id),
                    "blob_digest": staged.blob_digest,
                    "size_bytes": staged.size_bytes,
                    "object_class": definition.object_class,
                    "allowed_use": definition.allowed_use,
                    "security_scope": definition.security_scope,
                    "retention_scope": definition.retention_scope,
                    "rights_decision_id": str(rights.rights_decision_id),
                    "rights_policy_version": rights.policy_version,
                    "valid_from": rights.valid_from.to_text(),
                    "valid_until": None
                    if rights.valid_until is None
                    else rights.valid_until.to_text(),
                }
            )
            event_grant = self._issuer.issue(
                command_type=event_definition.command_type,
                aggregate_id=str(admission_id),
                expected_aggregate_version=0,
                definition=event_definition,
                payload=_ResolvedPayload(
                    kind="INLINE",
                    schema_version=event_definition.payload_schema_version,
                    digest=digest_bytes(event_payload_bytes),
                    inline_bytes=event_payload_bytes,
                    object_admission_id=None,
                    blob_digest=None,
                    object_class=None,
                    allowed_use=None,
                ),
                authentication=authentication,
                authorization_request=auth_request,
                authorization=authorization,
                idempotency_namespace=digest_canonical(
                    {
                        "authority_domain": authentication.authority_domain,
                        "principal_id": authentication.principal_id,
                        "command_type": event_definition.command_type,
                    }
                ),
                idempotency_key=f"admit:{request.idempotency_key}",
                stable_semantic_request_digest=stable_digest,
                correlation_id=None,
                causation_kind=None,
                causation_identifier=None,
                causation_external_system=None,
                replay_of_command_id=None,
            )
            return self._store.activate_admission(
                admission_grant, event_grant, staged
            )
        except Exception:
            self._store._blob_store.discard_stage(staged)
            raise

    def hydrate(
        self,
        admission_id: ObjectAdmissionId,
        purpose: str,
        max_bytes: int,
        proof: object,
    ) -> HydratedObject:
        if not isinstance(proof, AuthenticationProof):
            raise TypeError("hydration requires AuthenticationProof")
        require_token(purpose, field="hydration purpose")
        row = self._store.admission_security(admission_id)
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        stable_digest = digest_canonical(
            {
                "operation": "OBJECT_HYDRATE",
                "admission_id": str(admission_id),
                "purpose": purpose,
                "max_bytes": max_bytes,
            }
        )
        request, authorization = self._authorize(
            authentication,
            operation_type="object.hydrate",
            required_scope=str(row["required_read_scope"]),
            stable_digest=stable_digest,
            definition_digest=str(row["definition_digest"]),
            aggregate_type="governed_object_admission",
            aggregate_id=str(admission_id),
            event_type="governed.object.hydrated",
            payload_mode="NO_PAYLOAD",
            payload_schema_version="object_hydration_v1",
            trust_scope="OBSERVED",
            security_scope=str(row["security_scope"]),
            retention_scope=str(row["retention_scope"]),
            object_class=str(row["object_class"]),
            allowed_use=str(row["allowed_use"]),
            now=now,
        )
        grant = self._issuer.issue_maintenance(
            operation_type="OBJECT_HYDRATE",
            target_id=str(admission_id),
            reason_code="ACCESS_ALLOWED",
            authentication=authentication,
            authorization_request=request,
            authorization=authorization,
        )
        return self._store.hydrate(
            grant,
            admission_id=admission_id,
            purpose=purpose,
            max_bytes=max_bytes,
        )

    def revoke(self, admission_id: ObjectAdmissionId, proof: object) -> int:
        if not isinstance(proof, AuthenticationProof):
            raise TypeError("revocation requires AuthenticationProof")
        row = self._store.admission_security(admission_id)
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        event_definition = self._revocation_event_definition(row)
        stable_digest = digest_canonical(
            {
                "operation": "OBJECT_ADMISSION_REVOKE",
                "admission_id": str(admission_id),
                "current_version": int(row["aggregate_version"]),
            }
        )
        request, authorization = self._authorize(
            authentication,
            operation_type="object.admission.revoke",
            required_scope=str(row["required_manage_scope"]),
            stable_digest=stable_digest,
            definition_digest=event_definition.digest,
            aggregate_type=event_definition.aggregate_type,
            aggregate_id=str(admission_id),
            event_type=event_definition.event_type,
            payload_mode="INLINE",
            payload_schema_version=event_definition.payload_schema_version,
            trust_scope="OBSERVED",
            security_scope=str(row["security_scope"]),
            retention_scope=str(row["retention_scope"]),
            object_class=str(row["object_class"]),
            allowed_use=str(row["allowed_use"]),
            now=now,
        )
        maintenance = self._issuer.issue_maintenance(
            operation_type="OBJECT_ADMISSION_REVOKE",
            target_id=str(admission_id),
            reason_code="AUTHORISED_REVOCATION",
            authentication=authentication,
            authorization_request=request,
            authorization=authorization,
        )
        payload_bytes = canonical_json_bytes(
            {
                "admission_id": str(admission_id),
                "reason_code": "AUTHORISED_REVOCATION",
            }
        )
        event_grant = self._issuer.issue(
            command_type=event_definition.command_type,
            aggregate_id=str(admission_id),
            expected_aggregate_version=int(row["aggregate_version"]),
            definition=event_definition,
            payload=_ResolvedPayload(
                kind="INLINE",
                schema_version=event_definition.payload_schema_version,
                digest=digest_bytes(payload_bytes),
                inline_bytes=payload_bytes,
                object_admission_id=None,
                blob_digest=None,
                object_class=None,
                allowed_use=None,
            ),
            authentication=authentication,
            authorization_request=request,
            authorization=authorization,
            idempotency_namespace=digest_canonical(
                {
                    "authority_domain": authentication.authority_domain,
                    "principal_id": authentication.principal_id,
                    "command_type": event_definition.command_type,
                }
            ),
            idempotency_key=f"revoke:{admission_id}:{row['aggregate_version']}",
            stable_semantic_request_digest=stable_digest,
            correlation_id=None,
            causation_kind=None,
            causation_identifier=None,
            causation_external_system=None,
            replay_of_command_id=None,
        )
        return self._store.revoke_admission(maintenance, event_grant)

    def delete_blob(
        self, blob_digest: str, reason_code: str, proof: object
    ) -> ObjectDeletionReceipt:
        if not isinstance(proof, AuthenticationProof):
            raise TypeError("deletion requires AuthenticationProof")
        require_token(reason_code, field="deletion reason")
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        deletion_id = str(AuditId.new())
        request_definition = self._deletion_event_definition(completed=False)
        request_stable = digest_canonical(
            {
                "operation": "BLOB_DELETE_REQUEST",
                "blob_digest": blob_digest,
                "reason_code": reason_code,
            }
        )
        request, authorization = self._authorize(
            authentication,
            operation_type="object.blob.delete",
            required_scope="authority.objects.delete",
            stable_digest=request_stable,
            definition_digest=request_definition.digest,
            aggregate_type=request_definition.aggregate_type,
            aggregate_id=deletion_id,
            event_type=request_definition.event_type,
            payload_mode="INLINE",
            payload_schema_version=request_definition.payload_schema_version,
            trust_scope="OBSERVED",
            security_scope="authority.protected",
            retention_scope="authority.tombstone",
            object_class=None,
            allowed_use=None,
            now=now,
        )
        maintenance = self._issuer.issue_maintenance(
            operation_type="BLOB_DELETE_REQUEST",
            target_id=blob_digest,
            reason_code=reason_code,
            authentication=authentication,
            authorization_request=request,
            authorization=authorization,
        )
        request_event = self._lifecycle_event_grant(
            definition=request_definition,
            aggregate_id=deletion_id,
            expected_version=0,
            payload_value={
                "deletion_id": deletion_id,
                "blob_digest": blob_digest,
                "reason_code": reason_code,
                "state": "DELETION_PENDING",
            },
            authentication=authentication,
            request=request,
            authorization=authorization,
            stable_digest=request_stable,
            key=f"delete-request:{blob_digest}",
        )
        requested = self._store.request_deletion(
            maintenance,
            request_event,
            deletion_id=deletion_id,
            blob_digest=blob_digest,
        )
        if requested.completed:
            return requested

        completion_definition = self._deletion_event_definition(completed=True)
        completion_stable = digest_canonical(
            {
                "operation": "BLOB_DELETE_COMPLETE",
                "deletion_id": requested.deletion_id,
                "blob_digest": blob_digest,
            }
        )
        completion_request, completion_auth = self._authorize(
            authentication,
            operation_type="object.blob.delete.complete",
            required_scope="authority.objects.delete",
            stable_digest=completion_stable,
            definition_digest=completion_definition.digest,
            aggregate_type=completion_definition.aggregate_type,
            aggregate_id=requested.deletion_id,
            event_type=completion_definition.event_type,
            payload_mode="INLINE",
            payload_schema_version=completion_definition.payload_schema_version,
            trust_scope="OBSERVED",
            security_scope="authority.protected",
            retention_scope="authority.tombstone",
            object_class=None,
            allowed_use=None,
            now=now,
        )
        completion_maintenance = self._issuer.issue_maintenance(
            operation_type="BLOB_DELETE_COMPLETE",
            target_id=blob_digest,
            reason_code=reason_code,
            authentication=authentication,
            authorization_request=completion_request,
            authorization=completion_auth,
        )
        completion_event = self._lifecycle_event_grant(
            definition=completion_definition,
            aggregate_id=requested.deletion_id,
            expected_version=1,
            payload_value={
                "deletion_id": requested.deletion_id,
                "blob_digest": blob_digest,
                "state": "DELETED",
            },
            authentication=authentication,
            request=completion_request,
            authorization=completion_auth,
            stable_digest=completion_stable,
            key=f"delete-complete:{requested.deletion_id}",
        )
        return self._store.complete_deletion(
            completion_maintenance,
            completion_event,
            deletion_id=requested.deletion_id,
            blob_digest=blob_digest,
        )

    def pin_recovery(self, blob_digest: str, reason_code: str, proof: object) -> str:
        grant = self._maintenance_grant(
            operation_type="RECOVERY_PIN_CREATE",
            target_id=blob_digest,
            reason_code=reason_code,
            required_scope="authority.objects.recovery",
            proof=proof,
        )
        return self._store.create_recovery_pin(grant, blob_digest=blob_digest)

    def release_recovery_pin(self, pin_id: str, proof: object) -> None:
        grant = self._maintenance_grant(
            operation_type="RECOVERY_PIN_RELEASE",
            target_id=pin_id,
            reason_code="RECOVERY_PIN_RELEASED",
            required_scope="authority.objects.recovery",
            proof=proof,
        )
        self._store.release_recovery_pin(grant)

    def collect_garbage(self, grace_seconds: int, proof: object) -> tuple[str, ...]:
        grant = self._maintenance_grant(
            operation_type="OBJECT_GC",
            target_id="authority-object-store",
            reason_code="AUTHORISED_GC",
            required_scope="authority.objects.gc",
            proof=proof,
        )
        return self._store.collect_garbage(grant, grace_seconds=grace_seconds)

    def _maintenance_grant(
        self,
        *,
        operation_type: str,
        target_id: str,
        reason_code: str,
        required_scope: str,
        proof: object,
    ) -> Any:
        if not isinstance(proof, AuthenticationProof):
            raise TypeError("maintenance requires AuthenticationProof")
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        stable = digest_canonical(
            {
                "operation_type": operation_type,
                "target_id": target_id,
                "reason_code": reason_code,
            }
        )
        request, authorization = self._authorize(
            authentication,
            operation_type=operation_type.lower(),
            required_scope=required_scope,
            stable_digest=stable,
            definition_digest=digest_canonical(
                {"operation_type": operation_type, "version": "v1"}
            ),
            aggregate_type="authority_maintenance",
            aggregate_id=target_id,
            event_type="authority.maintenance.authorised",
            payload_mode="NO_PAYLOAD",
            payload_schema_version="authority_maintenance_v1",
            trust_scope="OBSERVED",
            security_scope="authority.internal",
            retention_scope="authority.audit",
            object_class=None,
            allowed_use=None,
            now=now,
        )
        return self._issuer.issue_maintenance(
            operation_type=operation_type,
            target_id=target_id,
            reason_code=reason_code,
            authentication=authentication,
            authorization_request=request,
            authorization=authorization,
        )

    def _authorize(
        self,
        authentication: Any,
        *,
        operation_type: str,
        required_scope: str,
        stable_digest: str,
        definition_digest: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload_mode: str,
        payload_schema_version: str,
        trust_scope: str,
        security_scope: str,
        retention_scope: str,
        object_class: str | None,
        allowed_use: str | None,
        now: UtcTimestamp,
    ) -> tuple[Any, Any]:
        unsigned = {
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": operation_type,
            "required_scope": required_scope,
            "stable_semantic_request_digest": stable_digest,
            "command_definition_digest": definition_digest,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": event_type,
            "event_schema_version": 1,
            "payload_mode": payload_mode,
            "payload_schema_version": payload_schema_version,
            "trust_scope": trust_scope,
            "security_scope": security_scope,
            "retention_scope": retention_scope,
            "object_class": object_class,
            "allowed_use": allowed_use,
        }
        request = _AuthorizationRequest(
            authentication_context_id=authentication.authentication_context_id,
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type=operation_type,
            required_scope=required_scope,
            stable_semantic_request_digest=stable_digest,
            command_definition_digest=definition_digest,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            event_schema_version=1,
            payload_mode=payload_mode,
            payload_schema_version=payload_schema_version,
            trust_scope=trust_scope,
            security_scope=security_scope,
            retention_scope=retention_scope,
            object_class=object_class,
            allowed_use=allowed_use,
            request_digest=digest_canonical(unsigned),
        )
        decision = self._authorizer.authorize(authentication, request, now=now)
        decision.require_allowed()
        return request, decision

    @staticmethod
    def _admission_event_definition(
        definition: ObjectAdmissionDefinition,
    ) -> CommandDefinition:
        return CommandDefinition(
            command_type="object.admission.activate",
            definition_version="object-lifecycle-v1",
            aggregate_type="governed_object_admission",
            event_type="governed.object.admission.activated",
            event_schema_version=1,
            payload_mode=PayloadMode.INLINE,
            payload_schema_version="object_admission_event_v1",
            trust_scope=TrustScope.OBSERVED,
            security_scope=definition.security_scope,
            retention_scope=definition.retention_scope,
            required_scope=definition.required_write_scope,
            max_inline_bytes=64 * 1024,
        )

    @staticmethod
    def _revocation_event_definition(row: Any) -> CommandDefinition:
        return CommandDefinition(
            command_type="object.admission.revoke",
            definition_version="object-lifecycle-v1",
            aggregate_type="governed_object_admission",
            event_type="governed.object.admission.revoked",
            event_schema_version=1,
            payload_mode=PayloadMode.INLINE,
            payload_schema_version="object_revocation_event_v1",
            trust_scope=TrustScope.OBSERVED,
            security_scope=str(row["security_scope"]),
            retention_scope=str(row["retention_scope"]),
            required_scope=str(row["required_manage_scope"]),
            max_inline_bytes=16 * 1024,
        )

    @staticmethod
    def _deletion_event_definition(*, completed: bool) -> CommandDefinition:
        return CommandDefinition(
            command_type=(
                "blob.deletion.complete" if completed else "blob.deletion.request"
            ),
            definition_version="object-lifecycle-v1",
            aggregate_type="governed_blob_deletion",
            event_type=(
                "governed.blob.deleted"
                if completed
                else "governed.blob.deletion_requested"
            ),
            event_schema_version=1,
            payload_mode=PayloadMode.INLINE,
            payload_schema_version="blob_deletion_event_v1",
            trust_scope=TrustScope.OBSERVED,
            security_scope="authority.protected",
            retention_scope="authority.tombstone",
            required_scope="authority.objects.delete",
            max_inline_bytes=16 * 1024,
        )

    def _lifecycle_event_grant(
        self,
        *,
        definition: CommandDefinition,
        aggregate_id: str,
        expected_version: int,
        payload_value: dict[str, object],
        authentication: Any,
        request: Any,
        authorization: Any,
        stable_digest: str,
        key: str,
    ) -> _AuthorizedCommandGrant:
        payload_bytes = canonical_json_bytes(payload_value)
        return self._issuer.issue(
            command_type=definition.command_type,
            aggregate_id=aggregate_id,
            expected_aggregate_version=expected_version,
            definition=definition,
            payload=_ResolvedPayload(
                kind="INLINE",
                schema_version=definition.payload_schema_version,
                digest=digest_bytes(payload_bytes),
                inline_bytes=payload_bytes,
                object_admission_id=None,
                blob_digest=None,
                object_class=None,
                allowed_use=None,
            ),
            authentication=authentication,
            authorization_request=request,
            authorization=authorization,
            idempotency_namespace=digest_canonical(
                {
                    "authority_domain": authentication.authority_domain,
                    "principal_id": authentication.principal_id,
                    "command_type": definition.command_type,
                }
            ),
            idempotency_key=key,
            stable_semantic_request_digest=stable_digest,
            correlation_id=None,
            causation_kind=None,
            causation_identifier=None,
            causation_external_system=None,
            replay_of_command_id=None,
        )
