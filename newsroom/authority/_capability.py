from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
from typing import Any

from ._security import (
    _AuthorizationDecision,
    _AuthorizationRequest,
    _VerifiedAuthenticationContext,
    _effective_scope_digest,
)
from .canonical import canonical_json_bytes, digest_bytes
from .models import CommandDefinition
from .types import ObjectAdmissionId


class InvalidCommitCapability(PermissionError):
    """Raised when persistence receives a fabricated or mismatched commit grant."""


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


class _CapabilityIssuer:
    """Issues request-bound opaque grants for the internal persistence boundary."""

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("capability secret must be at least 256 bits")

    def _signature(self, value: dict[str, Any]) -> str:
        mac = hmac.new(self._secret, canonical_json_bytes(value), hashlib.sha256)
        return f"hmac-sha256:{mac.hexdigest()}"

    def issue(self, **kwargs: Any) -> _AuthorizedCommandGrant:
        provisional = _AuthorizedCommandGrant(signature="", **kwargs)
        return _AuthorizedCommandGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def verify(self, grant: _AuthorizedCommandGrant) -> None:
        if not isinstance(grant, _AuthorizedCommandGrant):
            raise InvalidCommitCapability("commit requires an authorised command grant")
        expected = self._signature(grant.unsigned_value())
        if not hmac.compare_digest(expected, grant.signature):
            raise InvalidCommitCapability("commit capability signature mismatch")
        if grant.authorization_request.request_digest != grant.authorization_request.computed_digest:
            raise InvalidCommitCapability("authorization request digest changed")
        if (
            grant.authorization_request.authentication_context_id
            != grant.authentication.authentication_context_id
            or grant.authorization_request.principal_id != grant.authentication.principal_id
            or grant.authorization_request.authority_domain
            != grant.authentication.authority_domain
        ):
            raise InvalidCommitCapability(
                "authorization request is not bound to the authentication context"
            )
        if (
            grant.authorization.authentication_context_id
            != grant.authentication.authentication_context_id
        ):
            raise InvalidCommitCapability(
                "authorization decision is not bound to the authentication context"
            )
        if (
            grant.authorization.authorization_request_digest
            != grant.authorization_request.request_digest
        ):
            raise InvalidCommitCapability(
                "authorization decision is not bound to the exact request"
            )
        if grant.authorization.effective_scope_digest != _effective_scope_digest(
            grant.authentication, grant.authorization.effective_scopes
        ):
            raise InvalidCommitCapability(
                "authorization scope digest is not bound to authentication provenance"
            )
        if grant.authorization.decided_at.value < grant.authentication.authenticated_at.value:
            raise InvalidCommitCapability("authorization predates authentication")
        if grant.authorization.decided_at.value >= grant.authentication.expires_at.value:
            raise InvalidCommitCapability("authorization occurred after authentication expiry")
        if not grant.authorization.allowed:
            raise InvalidCommitCapability("denied authorization cannot create a grant")
