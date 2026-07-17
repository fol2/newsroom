from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

from ._security import (
    AuthenticationError,
    AuthorizationDenied,
    _AuthorizationDecision,
    _AuthorizationRequest,
    _VerifiedAuthenticationContext,
    _effective_scope_digest,
)
from .canonical import digest_canonical
from .types import (
    AuthenticationContextId,
    AuthorizationDecisionId,
    UtcTimestamp,
    require_scope,
    require_token,
)


@dataclass(frozen=True, slots=True)
class AuthenticationProof:
    """Untrusted transport proof supplied by a caller.

    The raw credential is deliberately excluded from repr to avoid accidental
    token disclosure through debug logging and exception rendering.
    """

    method: str
    credential: str = field(repr=False)
    untrusted_claims: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_token(self.method, field="authentication method")
        if not isinstance(self.credential, str) or not self.credential:
            raise AuthenticationError(
                "authentication credential must be non-empty"
            )
        if not isinstance(self.untrusted_claims, Mapping):
            raise AuthenticationError("untrusted claims must be a mapping")
        for key, value in self.untrusted_claims.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise AuthenticationError(
                    "untrusted claim names and values must be strings"
                )


@dataclass(frozen=True, slots=True)
class StaticPrincipal:
    principal_id: str
    assurance_class: str = "TEST_STATIC_TOKEN"
    credential_binding_id: str | None = None

    def __post_init__(self) -> None:
        require_token(self.principal_id, field="principal_id")
        require_token(self.assurance_class, field="assurance_class")
        if self.credential_binding_id is not None:
            require_token(
                self.credential_binding_id, field="credential_binding_id"
            )

    def binding_id(self) -> str:
        return self.credential_binding_id or f"static:{self.principal_id}"


class StaticAuthenticator:
    """Deterministic test/local adapter with server-owned credential bindings."""

    def __init__(
        self,
        *,
        credentials: Mapping[str, StaticPrincipal],
        authority_domain: str,
        method: str = "STATIC_TOKEN",
        ttl_seconds: int = 300,
    ) -> None:
        if not credentials:
            raise ValueError(
                "static authenticator requires at least one credential"
            )
        require_token(authority_domain, field="authority_domain")
        require_token(method, field="method")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._credentials = dict(credentials)
        self._authority_domain = authority_domain
        self._method = method
        self._ttl_seconds = ttl_seconds

    def authenticate(
        self, proof: object, *, now: UtcTimestamp
    ) -> _VerifiedAuthenticationContext:
        if not isinstance(proof, AuthenticationProof):
            raise AuthenticationError("unsupported authentication proof type")
        if proof.method != self._method:
            raise AuthenticationError("unsupported authentication method")
        principal = self._credentials.get(proof.credential)
        if principal is None:
            raise AuthenticationError("invalid authentication credential")
        expires_at = UtcTimestamp(
            now.value + timedelta(seconds=self._ttl_seconds)
        )
        return _VerifiedAuthenticationContext(
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


class StaticAuthorizer:
    """Server-side authorization policy for tests and local integration."""

    def __init__(
        self,
        *,
        policy_version: str,
        grants_by_principal: Mapping[str, frozenset[str]],
    ) -> None:
        require_token(policy_version, field="authorization policy version")
        self._policy_version = policy_version
        self._grants_by_principal = {
            principal: frozenset(scopes)
            for principal, scopes in grants_by_principal.items()
        }
        for principal, scopes in self._grants_by_principal.items():
            require_token(principal, field="principal_id")
            for scope in scopes:
                require_scope(scope, field="effective scope")

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def authorize(
        self,
        context: _VerifiedAuthenticationContext,
        request: _AuthorizationRequest,
        *,
        now: UtcTimestamp,
    ) -> _AuthorizationDecision:
        context.require_current(now)
        if request.authentication_context_id != context.authentication_context_id:
            decision = self._denial(
                context,
                request,
                now=now,
                reason="AUTHZ_CONTEXT_MISMATCH",
            )
            raise AuthorizationDenied(decision)
        if request.principal_id != context.principal_id:
            decision = self._denial(
                context,
                request,
                now=now,
                reason="AUTHZ_PRINCIPAL_MISMATCH",
            )
            raise AuthorizationDenied(decision)
        if request.authority_domain != context.authority_domain:
            decision = self._denial(
                context,
                request,
                now=now,
                reason="AUTHZ_DOMAIN_MISMATCH",
            )
            raise AuthorizationDenied(decision)
        scopes = tuple(
            sorted(
                self._grants_by_principal.get(
                    context.principal_id, frozenset()
                )
            )
        )
        allowed = request.required_scope in scopes
        reason = "AUTHZ_ALLOWED" if allowed else "AUTHZ_SCOPE_MISSING"
        return _AuthorizationDecision(
            authorization_decision_id=AuthorizationDecisionId.new(),
            authentication_context_id=context.authentication_context_id,
            authorization_request_digest=request.request_digest,
            authorization_policy_version=self._policy_version,
            effective_scopes=scopes,
            effective_scope_digest=_effective_scope_digest(context, scopes),
            allowed=allowed,
            reason_code=reason,
            decided_at=now,
        )

    def _denial(
        self,
        context: _VerifiedAuthenticationContext,
        request: _AuthorizationRequest,
        *,
        now: UtcTimestamp,
        reason: str,
    ) -> _AuthorizationDecision:
        return _AuthorizationDecision(
            authorization_decision_id=AuthorizationDecisionId.new(),
            authentication_context_id=context.authentication_context_id,
            authorization_request_digest=request.request_digest,
            authorization_policy_version=self._policy_version,
            effective_scopes=(),
            effective_scope_digest=_effective_scope_digest(context, ()),
            allowed=False,
            reason_code=reason,
            decided_at=now,
        )


__all__ = [
    "AuthenticationError",
    "AuthenticationProof",
    "AuthorizationDenied",
    "StaticAuthenticator",
    "StaticAuthorizer",
    "StaticPrincipal",
]
