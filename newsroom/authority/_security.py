from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .types import (
    AuthenticationContextId,
    AuthorizationDecisionId,
    UtcTimestamp,
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

    def require_current(self, now: UtcTimestamp) -> None:
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


class _Authenticator(Protocol):
    def authenticate(self, proof: object, *, now: UtcTimestamp) -> _VerifiedAuthenticationContext:
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
