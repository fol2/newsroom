from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .canonical import digest_canonical, validate_sha256_digest
from .types import (
    AuthenticationContextId,
    AuthorizationDecisionId,
    UtcTimestamp,
    require_scope,
    require_token,
)


class AuthenticationError(PermissionError):
    pass


class AuthorizationDenied(PermissionError):
    def __init__(self, decision: _AuthorizationDecision) -> None:
        super().__init__(f"authorization denied: {decision.reason_code}")
        self.reason_code = decision.reason_code
        self.authorization_decision_id = str(decision.authorization_decision_id)


@dataclass(frozen=True, slots=True)
class _VerifiedAuthenticationContext:
    authentication_context_id: AuthenticationContextId
    principal_id: str
    authority_domain: str
    authentication_method: str
    assurance_class: str
    credential_binding_digest: str
    authenticated_at: UtcTimestamp
    expires_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.authentication_context_id, AuthenticationContextId):
            raise AuthenticationError("authentication context identity must be typed")
        require_token(self.principal_id, field="principal_id")
        require_token(self.authority_domain, field="authority_domain")
        require_token(self.authentication_method, field="authentication_method")
        require_token(self.assurance_class, field="assurance_class")
        normalized = validate_sha256_digest(
            self.credential_binding_digest, field="credential_binding_digest"
        )
        if normalized != self.credential_binding_digest:
            raise AuthenticationError("credential binding digest must be canonical lowercase")
        if not isinstance(self.authenticated_at, UtcTimestamp) or not isinstance(
            self.expires_at, UtcTimestamp
        ):
            raise AuthenticationError("authentication validity times must be typed UTC values")
        if self.expires_at.value <= self.authenticated_at.value:
            raise AuthenticationError("authentication expiry must follow authentication time")

    def require_current(self, now: UtcTimestamp) -> None:
        if not isinstance(now, UtcTimestamp):
            raise AuthenticationError("current time must be a typed UTC value")
        if now.value >= self.expires_at.value:
            raise AuthenticationError("authentication context has expired")

    def canonical_value(self) -> dict[str, str]:
        return {
            "authentication_context_id": str(self.authentication_context_id),
            "principal_id": self.principal_id,
            "authority_domain": self.authority_domain,
            "authentication_method": self.authentication_method,
            "assurance_class": self.assurance_class,
            "credential_binding_digest": self.credential_binding_digest,
            "authenticated_at": self.authenticated_at.to_text(),
            "expires_at": self.expires_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class _AuthorizationRequest:
    authentication_context_id: AuthenticationContextId
    principal_id: str
    authority_domain: str
    operation_type: str
    required_scope: str
    stable_semantic_request_digest: str
    command_definition_digest: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    event_schema_version: int
    payload_mode: str
    payload_schema_version: str
    trust_scope: str
    security_scope: str
    retention_scope: str
    object_class: str | None
    allowed_use: str | None
    request_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.authentication_context_id, AuthenticationContextId):
            raise ValueError("authorization request context identity must be typed")
        require_token(self.principal_id, field="principal_id")
        require_token(self.authority_domain, field="authority_domain")
        require_token(self.operation_type, field="operation_type")
        require_scope(self.required_scope, field="required_scope")
        validate_sha256_digest(
            self.stable_semantic_request_digest,
            field="stable_semantic_request_digest",
        )
        validate_sha256_digest(
            self.command_definition_digest, field="command_definition_digest"
        )
        require_token(self.aggregate_type, field="aggregate_type")
        if not isinstance(self.aggregate_id, str) or not self.aggregate_id:
            raise ValueError("aggregate_id must be non-empty")
        require_token(self.event_type, field="event_type")
        if (
            isinstance(self.event_schema_version, bool)
            or not isinstance(self.event_schema_version, int)
            or self.event_schema_version <= 0
        ):
            raise ValueError("event_schema_version must be positive")
        require_token(self.payload_mode, field="payload_mode")
        require_token(self.payload_schema_version, field="payload_schema_version")
        require_token(self.trust_scope, field="trust_scope")
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        if self.object_class is not None:
            require_token(self.object_class, field="object_class")
        if self.allowed_use is not None:
            require_token(self.allowed_use, field="allowed_use")
        validate_sha256_digest(self.request_digest, field="authorization_request_digest")
        if self.request_digest != self.computed_digest:
            raise ValueError("authorization request digest does not match exact request")

    def unsigned_value(self) -> dict[str, Any]:
        return {
            "authentication_context_id": str(self.authentication_context_id),
            "principal_id": self.principal_id,
            "authority_domain": self.authority_domain,
            "operation_type": self.operation_type,
            "required_scope": self.required_scope,
            "stable_semantic_request_digest": self.stable_semantic_request_digest,
            "command_definition_digest": self.command_definition_digest,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "event_type": self.event_type,
            "event_schema_version": self.event_schema_version,
            "payload_mode": self.payload_mode,
            "payload_schema_version": self.payload_schema_version,
            "trust_scope": self.trust_scope,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
        }

    @property
    def computed_digest(self) -> str:
        return digest_canonical(self.unsigned_value())

    def canonical_value(self) -> dict[str, Any]:
        return {**self.unsigned_value(), "request_digest": self.request_digest}

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class _AuthorizationDecision:
    authorization_decision_id: AuthorizationDecisionId
    authentication_context_id: AuthenticationContextId
    authorization_request_digest: str
    authorization_policy_version: str
    effective_scopes: tuple[str, ...]
    effective_scope_digest: str
    allowed: bool
    reason_code: str
    decided_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.authorization_decision_id, AuthorizationDecisionId):
            raise ValueError("authorization decision identity must be typed")
        if not isinstance(self.authentication_context_id, AuthenticationContextId):
            raise ValueError("authorization context identity must be typed")
        validate_sha256_digest(
            self.authorization_request_digest,
            field="authorization_request_digest",
        )
        require_token(
            self.authorization_policy_version,
            field="authorization_policy_version",
        )
        if not isinstance(self.effective_scopes, tuple):
            raise ValueError("effective_scopes must be an immutable tuple")
        if tuple(sorted(set(self.effective_scopes))) != self.effective_scopes:
            raise ValueError("effective_scopes must be sorted and unique")
        for scope in self.effective_scopes:
            require_scope(scope, field="effective_scope")
        normalized = validate_sha256_digest(
            self.effective_scope_digest, field="effective_scope_digest"
        )
        if normalized != self.effective_scope_digest:
            raise ValueError("effective scope digest must be canonical lowercase")
        if not isinstance(self.allowed, bool):
            raise ValueError("authorization allowed value must be boolean")
        require_token(self.reason_code, field="authorization_reason_code")
        if not isinstance(self.decided_at, UtcTimestamp):
            raise ValueError("authorization decision time must be typed UTC")

    def require_allowed(self) -> None:
        if not self.allowed:
            raise AuthorizationDenied(self)

    def canonical_value(self) -> dict[str, object]:
        return {
            "authorization_decision_id": str(self.authorization_decision_id),
            "authentication_context_id": str(self.authentication_context_id),
            "authorization_request_digest": self.authorization_request_digest,
            "authorization_policy_version": self.authorization_policy_version,
            "effective_scopes": list(self.effective_scopes),
            "effective_scope_digest": self.effective_scope_digest,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "decided_at": self.decided_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


def _effective_scope_digest(
    context: _VerifiedAuthenticationContext, scopes: tuple[str, ...]
) -> str:
    return digest_canonical(
        {
            "authentication_context_digest": context.digest,
            "effective_scopes": list(scopes),
        }
    )


class _Authenticator(Protocol):
    def authenticate(
        self, proof: object, *, now: UtcTimestamp
    ) -> _VerifiedAuthenticationContext:
        ...


class _Authorizer(Protocol):
    def authorize(
        self,
        context: _VerifiedAuthenticationContext,
        request: _AuthorizationRequest,
        *,
        now: UtcTimestamp,
    ) -> _AuthorizationDecision:
        ...
