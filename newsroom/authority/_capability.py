from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
from typing import Any

from ._rights import _RightsDecision
from ._security import (
    _AuthorizationDecision,
    _AuthorizationRequest,
    _VerifiedAuthenticationContext,
    _effective_scope_digest,
)
from .canonical import canonical_json_bytes, digest_bytes
from .models import CommandDefinition
from .objects import ObjectAdmissionDefinition
from .types import ObjectAdmissionId


class InvalidCommitCapability(PermissionError):
    """Raised when persistence receives a fabricated or mismatched grant."""


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
            "inline_digest": (
                None if self.inline_bytes is None else digest_bytes(self.inline_bytes)
            ),
            "object_admission_id": (
                None if self.object_admission_id is None else str(self.object_admission_id)
            ),
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
    """Issues request-bound opaque HMAC grants to private persistence."""

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("capability secret must be at least 256 bits")

    def _signature(self, value: dict[str, Any]) -> str:
        mac = hmac.new(self._secret, canonical_json_bytes(value), hashlib.sha256)
        return f"hmac-sha256:{mac.hexdigest()}"

    @staticmethod
    def _verify_security(
        authentication: _VerifiedAuthenticationContext,
        request: _AuthorizationRequest,
        authorization: _AuthorizationDecision,
    ) -> None:
        if request.request_digest != request.computed_digest:
            raise InvalidCommitCapability("authorization request digest changed")
        if (
            request.authentication_context_id
            != authentication.authentication_context_id
            or request.principal_id != authentication.principal_id
            or request.authority_domain != authentication.authority_domain
        ):
            raise InvalidCommitCapability(
                "authorization request is not bound to authentication provenance"
            )
        if authorization.authentication_context_id != authentication.authentication_context_id:
            raise InvalidCommitCapability("authorization context mismatch")
        if authorization.authorization_request_digest != request.request_digest:
            raise InvalidCommitCapability("authorization request mismatch")
        if authorization.effective_scope_digest != _effective_scope_digest(
            authentication, authorization.effective_scopes
        ):
            raise InvalidCommitCapability("authorization scope digest mismatch")
        if authorization.decided_at.value < authentication.authenticated_at.value:
            raise InvalidCommitCapability("authorization predates authentication")
        if authorization.decided_at.value >= authentication.expires_at.value:
            raise InvalidCommitCapability("authorization followed authentication expiry")
        if not authorization.allowed:
            raise InvalidCommitCapability("denied authorization cannot create a grant")

    def issue(self, **kwargs: Any) -> _AuthorizedCommandGrant:
        provisional = _AuthorizedCommandGrant(signature="", **kwargs)
        return _AuthorizedCommandGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def verify(self, grant: _AuthorizedCommandGrant) -> None:
        if not isinstance(grant, _AuthorizedCommandGrant):
            raise InvalidCommitCapability("command commit requires an authorised grant")
        if not hmac.compare_digest(
            self._signature(grant.unsigned_value()), grant.signature
        ):
            raise InvalidCommitCapability("command capability signature mismatch")
        self._verify_security(
            grant.authentication, grant.authorization_request, grant.authorization
        )

    def issue_admission(self, **kwargs: Any) -> _AuthorizedAdmissionGrant:
        provisional = _AuthorizedAdmissionGrant(signature="", **kwargs)
        return _AuthorizedAdmissionGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def verify_admission(self, grant: _AuthorizedAdmissionGrant) -> None:
        if not isinstance(grant, _AuthorizedAdmissionGrant):
            raise InvalidCommitCapability("object admission requires an authorised grant")
        if not hmac.compare_digest(
            self._signature(grant.unsigned_value()), grant.signature
        ):
            raise InvalidCommitCapability("object admission capability signature mismatch")
        self._verify_security(
            grant.authentication, grant.authorization_request, grant.authorization
        )
        if not grant.rights.allowed:
            raise InvalidCommitCapability("denied rights cannot create an admission")
        if (
            grant.rights.authentication_context_id
            != str(grant.authentication.authentication_context_id)
            or grant.rights.authorization_decision_id
            != str(grant.authorization.authorization_decision_id)
        ):
            raise InvalidCommitCapability("rights provenance is not security-bound")
        if grant.rights.blob_digest != grant.blob_digest:
            raise InvalidCommitCapability("rights decision is not blob-bound")
        if (
            grant.rights.object_class != grant.definition.object_class
            or grant.rights.allowed_use != grant.definition.allowed_use
            or grant.rights.security_scope != grant.definition.security_scope
            or grant.rights.retention_scope != grant.definition.retention_scope
        ):
            raise InvalidCommitCapability("rights decision is not use-bound")

    def issue_maintenance(self, **kwargs: Any) -> _AuthorizedMaintenanceGrant:
        provisional = _AuthorizedMaintenanceGrant(signature="", **kwargs)
        return _AuthorizedMaintenanceGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def verify_maintenance(self, grant: _AuthorizedMaintenanceGrant) -> None:
        if not isinstance(grant, _AuthorizedMaintenanceGrant):
            raise InvalidCommitCapability("maintenance requires an authorised grant")
        if not hmac.compare_digest(
            self._signature(grant.unsigned_value()), grant.signature
        ):
            raise InvalidCommitCapability("maintenance capability signature mismatch")
        self._verify_security(
            grant.authentication, grant.authorization_request, grant.authorization
        )
