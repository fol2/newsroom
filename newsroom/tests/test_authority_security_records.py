from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from newsroom.authority import (
    AuthenticationContextId,
    AuthenticationProof,
    AuthorizationDecisionId,
    UtcTimestamp,
    digest_canonical,
)
from newsroom.authority._security import (
    AuthenticationError,
    _AuthorizationDecision,
    _AuthorizationRequest,
    _VerifiedAuthenticationContext,
    _effective_scope_digest,
)

from .authority_helpers import FIXED_NOW


def authentication(
    *,
    authenticated_at: UtcTimestamp = FIXED_NOW,
) -> _VerifiedAuthenticationContext:
    return _VerifiedAuthenticationContext(
        authentication_context_id=AuthenticationContextId.new(),
        principal_id="principal.alpha",
        authority_domain="newsroom.authority",
        authentication_method="STATIC_TOKEN",
        assurance_class="TEST_STATIC_TOKEN",
        credential_binding_digest=digest_canonical(
            {"binding": "alpha"}
        ),
        authenticated_at=authenticated_at,
        expires_at=UtcTimestamp(
            authenticated_at.value + timedelta(minutes=5)
        ),
    )


def request(
    context: _VerifiedAuthenticationContext,
) -> _AuthorizationRequest:
    unsigned = {
        "authentication_context_id": str(
            context.authentication_context_id
        ),
        "principal_id": context.principal_id,
        "authority_domain": context.authority_domain,
        "operation_type": "command:record.observed",
        "required_scope": "authority.observed.write",
        "stable_semantic_request_digest": digest_canonical(
            {"semantic": 1}
        ),
        "command_definition_digest": digest_canonical(
            {"definition": 1}
        ),
        "aggregate_type": "fixture_record",
        "aggregate_id": "aggregate-id",
        "event_type": "fixture.observed.recorded",
        "event_schema_version": 1,
        "payload_mode": "INLINE",
        "payload_schema_version": "fixture_payload_v1",
        "payload_schema_contract_version": "fixture-contract-v1",
        "payload_schema_contract_digest": digest_canonical(
            {"payload_contract": 1}
        ),
        "payload_canonicalizer_version": "fixture-canon-v1",
        "trust_scope": "OBSERVED",
        "security_scope": "authority.internal",
        "retention_scope": "authority.default",
        "object_class": None,
        "allowed_use": None,
    }
    return _AuthorizationRequest(
        authentication_context_id=context.authentication_context_id,
        principal_id=context.principal_id,
        authority_domain=context.authority_domain,
        operation_type="command:record.observed",
        required_scope="authority.observed.write",
        stable_semantic_request_digest=unsigned[
            "stable_semantic_request_digest"
        ],
        command_definition_digest=unsigned[
            "command_definition_digest"
        ],
        aggregate_type="fixture_record",
        aggregate_id="aggregate-id",
        event_type="fixture.observed.recorded",
        event_schema_version=1,
        payload_mode="INLINE",
        payload_schema_version="fixture_payload_v1",
        payload_schema_contract_version="fixture-contract-v1",
        payload_schema_contract_digest=unsigned[
            "payload_schema_contract_digest"
        ],
        payload_canonicalizer_version="fixture-canon-v1",
        trust_scope="OBSERVED",
        security_scope="authority.internal",
        retention_scope="authority.default",
        object_class=None,
        allowed_use=None,
        request_digest=digest_canonical(unsigned),
    )


def test_authentication_context_rejects_malformed_provenance() -> None:
    context = authentication()
    with pytest.raises(Exception):
        replace(context, principal_id="")
    with pytest.raises(Exception):
        replace(
            context,
            credential_binding_digest="sha256:" + "A" * 64,
        )
    with pytest.raises(AuthenticationError):
        replace(context, expires_at=context.authenticated_at)


def test_authentication_context_enforces_not_before_and_expiry() -> None:
    future = UtcTimestamp(
        FIXED_NOW.value + timedelta(seconds=30)
    )
    context = authentication(authenticated_at=future)
    with pytest.raises(AuthenticationError, match="not yet valid"):
        context.require_current(FIXED_NOW)
    context.require_current(future)
    with pytest.raises(AuthenticationError, match="expired"):
        context.require_current(context.expires_at)


def test_authentication_proof_repr_redacts_raw_credential() -> None:
    proof = AuthenticationProof(
        method="STATIC_TOKEN",
        credential="super-secret-token",
    )
    rendered = repr(proof)
    assert "super-secret-token" not in rendered
    assert "credential=" not in rendered


def test_authorization_request_rejects_changed_fields_with_retained_digest() -> None:
    context = authentication()
    original = request(context)
    with pytest.raises(ValueError, match="digest"):
        replace(original, retention_scope="authority.other")


def test_authorization_decision_rejects_malformed_policy_and_scopes() -> None:
    context = authentication()
    original_request = request(context)
    decision = _AuthorizationDecision(
        authorization_decision_id=AuthorizationDecisionId.new(),
        authentication_context_id=context.authentication_context_id,
        authorization_request_digest=original_request.request_digest,
        authorization_policy_version="authz-v1",
        effective_scopes=("authority.observed.write",),
        effective_scope_digest=_effective_scope_digest(
            context, ("authority.observed.write",)
        ),
        allowed=True,
        reason_code="AUTHZ_ALLOWED",
        decided_at=FIXED_NOW,
    )
    with pytest.raises(Exception):
        replace(decision, authorization_policy_version="")
    with pytest.raises(ValueError, match="sorted"):
        replace(
            decision,
            effective_scopes=("z.scope", "a.scope"),
        )
    with pytest.raises(Exception):
        replace(
            decision,
            effective_scope_digest="not-a-digest",
        )
