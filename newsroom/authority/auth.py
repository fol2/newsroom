from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from .canonical import digest_canonical
from .types import (
    AuthenticationContextId,
    AuthorizationDecisionId,
    UtcTimestamp,
)


class AuthenticationError(PermissionError):
    """Raised when a caller cannot establish a verified authentication context."""


class AuthorizationDenied(PermissionError):
    """Raised when a server-side policy denies a semantic command."""

    def __init__(self, decision: AuthorizationDecision) -> None:
        super().__init__(f"authorization denied: {decision.reason_code}")
        self.decision = decision


@dataclass(frozen=True, slots=True)
class AuthenticationProof:
    """Untrusted transport proof supplied by a caller.

    `untrusted_claims` is retained only to make the trust boundary explicit in
    tests and adapters. An authenticator must not copy caller-supplied principal,
    role or scope values into verified authority without independently proving
    them from its server-side credential configuration.
    """

    method: str
    credential: str
    untrusted_claims: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.method or not self.credential:
            raise AuthenticationError("authentication proof requires method and credential")


@dataclass(frozen=True, slots=True)
class VerifiedAuthenticationContext:
    authentication_context_id: AuthenticationContextId
    principal_id: str
    authority_domain: str
    authentication_method: str
    assurance_class: str
    credential_binding_digest: str
    authenticated_at: UtcTimestamp
    expires_at: UtcTimestamp

    def __post_init__(self) -> None:
        for field_name in (
            "principal_id",
            "authority_domain",
            "authentication_method",
            "assurance_class",
            "credential_binding_digest",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise AuthenticationError(f"{field_name} must be non-empty")
        if self.expires_at.value <= self.authenticated_at.value:
            raise AuthenticationError("authentication context expiry must follow issue time")

    def require_current(self, now: UtcTimestamp) -> None:
        if now.value >= self.expires_at.value:
            raise AuthenticationError("authentication context has expired")


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    command_type: str
    aggregate_type: str
    aggregate_id: str


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    authorization_decision_id: AuthorizationDecisionId
    authorization_policy_version: str
    effective_scope_digest: str
    allowed: bool
    reason_code: str

    def require_allowed(self) -> None:
        if not self.allowed:
            raise AuthorizationDenied(self)


class Authenticator(Protocol):
    def authenticate(
        self, proof: AuthenticationProof, *, now: UtcTimestamp
    ) -> VerifiedAuthenticationContext:
        ...


class Authorizer(Protocol):
    def authorize(
        self,
        context: VerifiedAuthenticationContext,
        request: AuthorizationRequest,
    ) -> AuthorizationDecision:
        ...


@dataclass(frozen=True, slots=True)
class StaticPrincipal:
    principal_id: str
    assurance_class: str = "TEST_STATIC_TOKEN"
    credential_binding_id: str | None = None

    def binding_id(self) -> str:
        return self.credential_binding_id or f"static:{self.principal_id}"


class StaticAuthenticator:
    """Deterministic authenticated adapter for tests and local integration.

    Credentials and their principal bindings are server-side constructor input.
    Caller claims are ignored. There is intentionally no anonymous fallback.
    """

    def __init__(
        self,
        *,
        credentials: Mapping[str, StaticPrincipal],
        authority_domain: str,
        method: str = "STATIC_TOKEN",
        ttl_seconds: int = 300,
    ) -> None:
        if not credentials:
            raise ValueError("static authenticator requires at least one credential")
        if not authority_domain.strip():
            raise ValueError("authority_domain must be non-empty")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._credentials = dict(credentials)
        self._authority_domain = authority_domain
        self._method = method
        self._ttl_seconds = ttl_seconds

    def authenticate(
        self, proof: AuthenticationProof, *, now: UtcTimestamp
    ) -> VerifiedAuthenticationContext:
        if proof.method != self._method:
            raise AuthenticationError("unsupported authentication method")
        principal = self._credentials.get(proof.credential)
        if principal is None:
            raise AuthenticationError("invalid authentication credential")
        expires_at = UtcTimestamp(now.value + timedelta(seconds=self._ttl_seconds))
        return VerifiedAuthenticationContext(
            authentication_context_id=AuthenticationContextId.new(),
            principal_id=principal.principal_id,
            authority_domain=self._authority_domain,
            authentication_method=self._method,
            assurance_class=principal.assurance_class,
            credential_binding_digest=digest_canonical(
                {
                    "authority_domain": self._authority_domain,
                    "method": self._method,
                    "credential_binding_id": principal.binding_id(),
                    "principal_id": principal.principal_id,
                }
            ),
            authenticated_at=now,
            expires_at=expires_at,
        )


@dataclass(frozen=True, slots=True)
class AuthorizationRule:
    required_scope: str
    aggregate_types: frozenset[str]

    def __post_init__(self) -> None:
        if not self.required_scope.strip():
            raise ValueError("required_scope must be non-empty")
        if not self.aggregate_types:
            raise ValueError("authorization rule requires aggregate types")


class StaticAuthorizer:
    """Server-side policy used by tests and the first integration boundary."""

    def __init__(
        self,
        *,
        policy_version: str,
        grants_by_principal: Mapping[str, frozenset[str]],
        rules_by_command: Mapping[str, AuthorizationRule],
    ) -> None:
        if not policy_version.strip():
            raise ValueError("policy_version must be non-empty")
        self._policy_version = policy_version
        self._grants_by_principal = {
            principal: frozenset(scopes)
            for principal, scopes in grants_by_principal.items()
        }
        self._rules_by_command = dict(rules_by_command)

    def authorize(
        self,
        context: VerifiedAuthenticationContext,
        request: AuthorizationRequest,
    ) -> AuthorizationDecision:
        scopes = self._grants_by_principal.get(context.principal_id, frozenset())
        rule = self._rules_by_command.get(request.command_type)
        allowed = False
        reason = "AUTHZ_UNKNOWN_COMMAND"
        if rule is not None:
            if request.aggregate_type not in rule.aggregate_types:
                reason = "AUTHZ_AGGREGATE_TYPE_DENIED"
            elif rule.required_scope not in scopes:
                reason = "AUTHZ_SCOPE_MISSING"
            else:
                allowed = True
                reason = "AUTHZ_ALLOWED"
        effective_scope_digest = digest_canonical(
            {
                "authority_domain": context.authority_domain,
                "principal_id": context.principal_id,
                "policy_version": self._policy_version,
                "effective_scopes": sorted(scopes),
            }
        )
        return AuthorizationDecision(
            authorization_decision_id=AuthorizationDecisionId.new(),
            authorization_policy_version=self._policy_version,
            effective_scope_digest=effective_scope_digest,
            allowed=allowed,
            reason_code=reason,
        )
