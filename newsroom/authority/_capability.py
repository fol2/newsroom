from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
from typing import Any

from ._rights import _RightsDecision
from ._security import _AuthorizationDecision, _AuthorizationRequest, _VerifiedAuthenticationContext, _effective_scope_digest
from .canonical import canonical_json_bytes, digest_bytes
from .models import CommandDefinition
from .objects import ObjectAdmissionDefinition
from .types import ObjectAdmissionId


class InvalidCommitCapability(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class _ResolvedPayload:
    kind: str
    schema_version: str
    digest: str
    inline_bytes: bytes | None
    object_admission_id: ObjectAdmissionId | None
    blob_digest: str | None
    object_class: str | None
    allowed_use: str | None

    def canonical_value(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "schema_version": self.schema_version,
            "digest": self.digest,
            "inline_digest": None if self.inline_bytes is None else digest_bytes(self.inline_bytes),
            "object_admission_id": None if self.object_admission_id is None else str(self.object_admission_id),
            "blob_digest": self.blob_digest,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
        }


@dataclass(frozen=True, slots=True)
class _AuthorizedCommandGrant:
    command_type: str
    aggregate_id: str
    expected_aggregate_version: int
    definition: CommandDefinition
    payload: _ResolvedPayload
    authentication: _VerifiedAuthenticationContext
    authorization_request: _AuthorizationRequest
    authorization: _AuthorizationDecision
    idempotency_namespace: str
    idempotency_key: str
    stable_semantic_request_digest: str
    correlation_id: str | None
    causation_kind: str | None
    causation_identifier: str | None
    causation_external_system: str | None
    signature: str
    replay_of_command_id: str | None = None

    def unsigned_value(self) -> dict[str, Any]:
        return {
            "operation": "COMMAND_COMMIT",
            "command_type": self.command_type,
            "aggregate_id": self.aggregate_id,
            "expected_aggregate_version": self.expected_aggregate_version,
            "definition_digest": self.definition.digest,
            "definition_version": self.definition.definition_version,
            "payload": self.payload.canonical_value(),
            "authentication_context_digest": self.authentication.digest,
            "authorization_request_record_digest": self.authorization_request.digest,
            "authorization_request_digest": self.authorization_request.request_digest,
            "authorization_decision_digest": self.authorization.digest,
            "idempotency_namespace": self.idempotency_namespace,
            "idempotency_key": self.idempotency_key,
            "stable_semantic_request_digest": self.stable_semantic_request_digest,
            "correlation_id": self.correlation_id,
            "causation_kind": self.causation_kind,
            "causation_identifier": self.causation_identifier,
            "causation_external_system": self.causation_external_system,
            "replay_of_command_id": self.replay_of_command_id,
        }


@dataclass(frozen=True, slots=True)
class _AuthorizedAdmissionGrant:
    definition: ObjectAdmissionDefinition
    admission_id: ObjectAdmissionId
    blob_digest: str
    size_bytes: int
    authentication: _VerifiedAuthenticationContext
    authorization_request: _AuthorizationRequest
    authorization: _AuthorizationDecision
    rights: _RightsDecision
    idempotency_namespace: str
    idempotency_key: str
    stable_semantic_request_digest: str
    signature: str

    def unsigned_value(self) -> dict[str, Any]:
        return {
            "operation": "OBJECT_ADMISSION",
            "definition": self.definition.canonical_value(),
            "admission_id": str(self.admission_id),
            "blob_digest": self.blob_digest,
            "size_bytes": self.size_bytes,
            "authentication_context_digest": self.authentication.digest,
            "authorization_request_record_digest": self.authorization_request.digest,
            "authorization_request_digest": self.authorization_request.request_digest,
            "authorization_decision_digest": self.authorization.digest,
            "rights_decision_digest": self.rights.digest,
            "idempotency_namespace": self.idempotency_namespace,
            "idempotency_key": self.idempotency_key,
            "stable_semantic_request_digest": self.stable_semantic_request_digest,
        }


@dataclass(frozen=True, slots=True)
class _AuthorizedMaintenanceGrant:
    operation_type: str
    target_id: str
    reason_code: str
    authentication: _VerifiedAuthenticationContext
    authorization_request: _AuthorizationRequest
    authorization: _AuthorizationDecision
    signature: str

    def unsigned_value(self) -> dict[str, Any]:
        return {
            "operation": self.operation_type,
            "target_id": self.target_id,
            "reason_code": self.reason_code,
            "authentication_context_digest": self.authentication.digest,
            "authorization_request_record_digest": self.authorization_request.digest,
            "authorization_request_digest": self.authorization_request.request_digest,
            "authorization_decision_digest": self.authorization.digest,
        }


class _CapabilityIssuer:
    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("capability secret must be at least 256 bits")

    def _signature(self, value: dict[str, Any]) -> str:
        return "hmac-sha256:" + hmac.new(self._secret, canonical_json_bytes(value), hashlib.sha256).hexdigest()

    @staticmethod
    def _verify_security(authentication: _VerifiedAuthenticationContext, request: _AuthorizationRequest, authorization: _AuthorizationDecision) -> None:
        if request.request_digest != request.computed_digest:
            raise InvalidCommitCapability("authorization request digest changed")
        if request.authentication_context_id != authentication.authentication_context_id or request.principal_id != authentication.principal_id or request.authority_domain != authentication.authority_domain:
            raise InvalidCommitCapability("authorization request is not authentication-bound")
        if authorization.authentication_context_id != authentication.authentication_context_id or authorization.authorization_request_digest != request.request_digest:
            raise InvalidCommitCapability("authorization decision binding mismatch")
        if authorization.effective_scope_digest != _effective_scope_digest(authentication, authorization.effective_scopes):
            raise InvalidCommitCapability("authorization scope digest mismatch")
        if authorization.decided_at.value < authentication.authenticated_at.value or authorization.decided_at.value >= authentication.expires_at.value:
            raise InvalidCommitCapability("authorization time is outside authentication validity")
        if not authorization.allowed:
            raise InvalidCommitCapability("denied authorization cannot create a grant")

    def issue(self, **kwargs: Any) -> _AuthorizedCommandGrant:
        provisional = _AuthorizedCommandGrant(signature="", **kwargs)
        return _AuthorizedCommandGrant(signature=self._signature(provisional.unsigned_value()), **kwargs)

    def verify(self, grant: _AuthorizedCommandGrant) -> None:
        if not isinstance(grant, _AuthorizedCommandGrant) or not hmac.compare_digest(self._signature(grant.unsigned_value()), grant.signature):
            raise InvalidCommitCapability("invalid command capability")
        self._verify_security(grant.authentication, grant.authorization_request, grant.authorization)
        request, definition, payload = grant.authorization_request, grant.definition, grant.payload
        lifecycle_extra_use = grant.command_type in {"object.admission.activate", "object.admission.revoke"} and request.object_class is not None and request.allowed_use is not None
        object_context_matches = (request.object_class == definition.required_object_class and request.allowed_use == definition.required_allowed_use) or lifecycle_extra_use
        if not (
            request.command_definition_digest == definition.digest
            and request.stable_semantic_request_digest == grant.stable_semantic_request_digest
            and request.aggregate_type == definition.aggregate_type
            and request.aggregate_id == grant.aggregate_id
            and request.event_type == definition.event_type
            and request.event_schema_version == definition.event_schema_version
            and request.payload_mode == definition.payload_mode.value
            and request.payload_schema_version == definition.payload_schema_version
            and request.trust_scope == definition.trust_scope.value
            and request.security_scope == definition.security_scope
            and request.retention_scope == definition.retention_scope
            and object_context_matches
            and grant.command_type == definition.command_type
            and payload.kind == definition.payload_mode.value
            and payload.schema_version == definition.payload_schema_version
        ):
            raise InvalidCommitCapability("command grant semantics mismatch")

    def issue_admission(self, **kwargs: Any) -> _AuthorizedAdmissionGrant:
        provisional = _AuthorizedAdmissionGrant(signature="", **kwargs)
        return _AuthorizedAdmissionGrant(signature=self._signature(provisional.unsigned_value()), **kwargs)

    def verify_admission(self, grant: _AuthorizedAdmissionGrant) -> None:
        if not isinstance(grant, _AuthorizedAdmissionGrant) or not hmac.compare_digest(self._signature(grant.unsigned_value()), grant.signature):
            raise InvalidCommitCapability("invalid object admission capability")
        self._verify_security(grant.authentication, grant.authorization_request, grant.authorization)
        request = grant.authorization_request
        if request.stable_semantic_request_digest != grant.stable_semantic_request_digest or request.aggregate_id != str(grant.admission_id) or request.object_class != grant.definition.object_class or request.allowed_use != grant.definition.allowed_use or request.security_scope != grant.definition.security_scope or request.retention_scope != grant.definition.retention_scope:
            raise InvalidCommitCapability("admission grant semantics mismatch")
        if not grant.rights.allowed or grant.rights.authentication_context_id != str(grant.authentication.authentication_context_id) or grant.rights.authorization_decision_id != str(grant.authorization.authorization_decision_id) or grant.rights.blob_digest != grant.blob_digest:
            raise InvalidCommitCapability("rights decision binding mismatch")
        if grant.rights.object_class != grant.definition.object_class or grant.rights.allowed_use != grant.definition.allowed_use or grant.rights.security_scope != grant.definition.security_scope or grant.rights.retention_scope != grant.definition.retention_scope:
            raise InvalidCommitCapability("rights use binding mismatch")

    def issue_maintenance(self, **kwargs: Any) -> _AuthorizedMaintenanceGrant:
        provisional = _AuthorizedMaintenanceGrant(signature="", **kwargs)
        return _AuthorizedMaintenanceGrant(signature=self._signature(provisional.unsigned_value()), **kwargs)

    def verify_maintenance(self, grant: _AuthorizedMaintenanceGrant) -> None:
        if not isinstance(grant, _AuthorizedMaintenanceGrant) or not hmac.compare_digest(self._signature(grant.unsigned_value()), grant.signature):
            raise InvalidCommitCapability("invalid maintenance capability")
        self._verify_security(grant.authentication, grant.authorization_request, grant.authorization)
