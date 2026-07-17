from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

import newsroom.authority as authority
from newsroom.authority import (
    AggregateId,
    AuthorizationDenied,
    CommandValidationError,
    InlinePayload,
    SemanticCommand,
    UtcTimestamp,
    digest_canonical,
)
from newsroom.authority._capability import (
    InvalidCommitCapability,
    _AuthorizedCommandGrant,
    _CapabilityIssuer,
)
from newsroom.authority._security import (
    _AuthorizationDecision,
    _AuthorizationRequest,
    _effective_scope_digest,
)

from .authority_helpers import command, make_service, proof


def _resign(service, grant, **changes):
    values = {
        field.name: getattr(grant, field.name)
        for field in dataclasses.fields(grant)
        if field.name != "signature"
    }
    values.update(changes)
    return service._issuer.issue(**values)


def _changed_request(
    grant, **changes: object
) -> _AuthorizationRequest:
    unsigned = grant.authorization_request.unsigned_value()
    unsigned.update(changes)
    return dataclasses.replace(
        grant.authorization_request,
        **changes,
        request_digest=digest_canonical(unsigned),
    )


def _decision_for(
    grant,
    request: _AuthorizationRequest,
    *,
    scopes: tuple[str, ...],
) -> _AuthorizationDecision:
    return dataclasses.replace(
        grant.authorization,
        authorization_request_digest=request.request_digest,
        effective_scopes=scopes,
        effective_scope_digest=_effective_scope_digest(
            grant.authentication, scopes
        ),
        allowed=True,
        reason_code="AUTHZ_ALLOWED",
    )


def test_public_api_does_not_export_mutation_store_or_internal_authority_types() -> None:
    prohibited = {
        "AuthorityStore",
        "GovernedObjectStore",
        "VerifiedAuthenticationContext",
        "AuthorizationDecision",
        "CommitCapability",
    }
    assert prohibited.isdisjoint(set(authority.__all__))
    for name in prohibited:
        assert not hasattr(authority, name)


def test_caller_cannot_supply_authority_bearing_fields() -> None:
    fields = {field.name for field in dataclasses.fields(SemanticCommand)}
    assert "event_type" not in fields
    assert "event_schema_version" not in fields
    assert "aggregate_type" not in fields
    assert "trust_scope" not in fields
    assert "security_scope" not in fields
    assert "retention_scope" not in fields
    assert "payload_schema_version" not in fields
    assert "payload_digest" not in fields
    assert "principal_id" not in fields
    assert "principal_scopes" not in fields


def test_untrusted_principal_and_scope_claims_have_no_authority() -> None:
    receipt = make_service().authorize(command(), proof=proof())
    assert receipt.trust_scope == "OBSERVED"
    assert receipt.event_type == "fixture.observed.recorded"
    assert receipt.security_scope == "authority.internal"


def test_observed_writer_cannot_self_promote_to_admitted() -> None:
    service = make_service(
        scopes=frozenset({"authority.observed.write"})
    )
    with pytest.raises(AuthorizationDenied):
        service.authorize(
            command(command_type="record.admitted"), proof=proof()
        )


def test_command_requires_typed_values_at_construction() -> None:
    with pytest.raises(CommandValidationError):
        SemanticCommand(
            command_type="record.observed",
            aggregate_id="not-an-id",  # type: ignore[arg-type]
            expected_aggregate_version=0,
            payload=InlinePayload({"x": 1}),
            idempotency_key="x",
        )
    with pytest.raises(CommandValidationError):
        SemanticCommand(
            command_type="record.observed",
            aggregate_id=AggregateId.new(),
            expected_aggregate_version=-1,
            payload=InlinePayload({"x": 1}),
            idempotency_key="x",
        )


def test_fabricated_capability_is_rejected() -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    service._issuer.verify(grant)
    fabricated = _AuthorizedCommandGrant(
        **{
            field.name: getattr(grant, field.name)
            for field in dataclasses.fields(grant)
            if field.name != "signature"
        },
        signature="hmac-sha256:" + "0" * 64,
    )
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(fabricated)


def test_separate_issuer_cannot_validate_another_boundary_grant() -> None:
    grant = make_service()._authorize_for_commit(
        command(), proof=proof()
    )
    with pytest.raises(InvalidCommitCapability):
        _CapabilityIssuer().verify(grant)


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal_id", "principal.other"),
        ("authority_domain", "other.authority"),
        ("authentication_method", "OTHER_TOKEN"),
        ("assurance_class", "OTHER_ASSURANCE"),
        (
            "credential_binding_digest",
            digest_canonical({"binding": "other"}),
        ),
    ],
)
def test_changing_authentication_provenance_with_same_id_invalidates_grant(
    field: str, value: object
) -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    tampered = dataclasses.replace(
        grant,
        authentication=dataclasses.replace(
            grant.authentication, **{field: value}
        ),
    )
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(tampered)


def test_changing_authentication_validity_with_same_id_invalidates_grant() -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    tampered = dataclasses.replace(
        grant,
        authentication=dataclasses.replace(
            grant.authentication,
            expires_at=UtcTimestamp(
                grant.authentication.expires_at.value
                + timedelta(seconds=60)
            ),
        ),
    )
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(tampered)


@pytest.mark.parametrize(
    "field,value",
    [
        ("authorization_policy_version", "authz-v999"),
        (
            "effective_scopes",
            ("authority.observed.write", "extra.scope"),
        ),
        ("reason_code", "AUTHZ_OTHER_REASON"),
    ],
)
def test_changing_authorization_provenance_with_same_id_invalidates_grant(
    field: str, value: object
) -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    tampered = dataclasses.replace(
        grant,
        authorization=dataclasses.replace(
            grant.authorization, **{field: value}
        ),
    )
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(tampered)


def test_changing_authorization_time_with_same_id_invalidates_grant() -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    tampered = dataclasses.replace(
        grant,
        authorization=dataclasses.replace(
            grant.authorization,
            decided_at=UtcTimestamp(
                grant.authorization.decided_at.value
                + timedelta(seconds=1)
            ),
        ),
    )
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(tampered)


def test_changing_authorization_request_fields_with_retained_digest_fails() -> None:
    grant = make_service()._authorize_for_commit(
        command(), proof=proof()
    )
    with pytest.raises(ValueError, match="digest"):
        dataclasses.replace(
            grant.authorization_request,
            security_scope="authority.other",
        )


@pytest.mark.parametrize(
    "changes,scopes",
    [
        (
            {"required_scope": "authority.weaker.write"},
            ("authority.weaker.write",),
        ),
        (
            {"operation_type": "command:record.other"},
            ("authority.observed.write",),
        ),
    ],
)
def test_same_issuer_cannot_sign_weaker_or_changed_authority_derivation(
    changes: dict[str, object], scopes: tuple[str, ...]
) -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    request = _changed_request(grant, **changes)
    decision = _decision_for(grant, request, scopes=scopes)
    resigned = _resign(
        service,
        grant,
        authorization_request=request,
        authorization=decision,
    )
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(resigned)


def test_same_issuer_cannot_sign_arbitrary_idempotency_namespace() -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    resigned = _resign(
        service,
        grant,
        idempotency_namespace=digest_canonical(
            {"caller_chosen_namespace": True}
        ),
    )
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(resigned)


def test_same_issuer_cannot_sign_arbitrary_semantic_digest() -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    arbitrary = digest_canonical({"arbitrary": "semantic"})
    request = _changed_request(
        grant, stable_semantic_request_digest=arbitrary
    )
    decision = _decision_for(
        grant,
        request,
        scopes=("authority.observed.write",),
    )
    resigned = _resign(
        service,
        grant,
        stable_semantic_request_digest=arbitrary,
        authorization_request=request,
        authorization=decision,
    )
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(resigned)


def test_same_issuer_cannot_sign_payload_digest_not_matching_bytes() -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    tampered_payload = dataclasses.replace(
        grant.payload,
        digest=digest_canonical({"not": "the retained bytes"}),
    )
    resigned = _resign(service, grant, payload=tampered_payload)
    with pytest.raises(InvalidCommitCapability):
        service._issuer.verify(resigned)
