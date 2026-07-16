from __future__ import annotations

import dataclasses

import pytest

import newsroom.authority as authority
from newsroom.authority import (
    AggregateId,
    AuthorizationDenied,
    CommandValidationError,
    InlinePayload,
    SemanticCommand,
)
from newsroom.authority._capability import (
    InvalidCommitCapability,
    _AuthorizedCommandGrant,
    _CapabilityIssuer,
)

from .authority_helpers import command, make_service, proof


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
    service = make_service(scopes=frozenset({"authority.observed.write"}))
    with pytest.raises(AuthorizationDenied):
        service.authorize(command(command_type="record.admitted"), proof=proof())


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
    issuer = service._issuer
    issuer.verify(grant)
    fabricated = _AuthorizedCommandGrant(
        command_type=grant.command_type,
        aggregate_id=grant.aggregate_id,
        expected_aggregate_version=grant.expected_aggregate_version,
        definition=grant.definition,
        payload=grant.payload,
        authentication=grant.authentication,
        authorization_request=grant.authorization_request,
        authorization=grant.authorization,
        idempotency_namespace=grant.idempotency_namespace,
        idempotency_key=grant.idempotency_key,
        stable_semantic_request_digest=grant.stable_semantic_request_digest,
        correlation_id=grant.correlation_id,
        causation_kind=grant.causation_kind,
        causation_identifier=grant.causation_identifier,
        causation_external_system=grant.causation_external_system,
        signature="hmac-sha256:" + "0" * 64,
    )
    with pytest.raises(InvalidCommitCapability):
        issuer.verify(fabricated)


def test_separate_issuer_cannot_validate_another_boundary_grant() -> None:
    grant = make_service()._authorize_for_commit(command(), proof=proof())
    with pytest.raises(InvalidCommitCapability):
        _CapabilityIssuer().verify(grant)
