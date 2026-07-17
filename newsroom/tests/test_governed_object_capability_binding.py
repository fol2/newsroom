from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from newsroom.authority import ObjectAdmissionId, StaticAuthenticator, StaticAuthorizer, StaticPrincipal, UtcTimestamp, digest_canonical
from newsroom.authority._capability import InvalidCommitCapability, _CapabilityIssuer
from newsroom.authority._object_service import _ObjectLifecycleService
from newsroom.authority._rights import resolve_rights
from newsroom.authority._security import _AuthorizationRequest

from .authority_helpers import FIXED_NOW, proof
from .authority_object_helpers import admission_definition
from newsroom.authority import StaticRightsResolver, StaticRightsRule


def valid_grant():
    definition = admission_definition()
    event_definition = _ObjectLifecycleService._admission_event_definition(definition)
    authenticator = StaticAuthenticator(
        credentials={"token-1": StaticPrincipal("principal.alpha")},
        authority_domain="newsroom.authority",
    )
    authorizer = StaticAuthorizer(
        policy_version="authz-v1",
        grants_by_principal={
            "principal.alpha": frozenset({"authority.objects.admit"})
        },
    )
    authentication = authenticator.authenticate(proof(), now=FIXED_NOW)
    admission_id = ObjectAdmissionId.new()
    stable = digest_canonical(
        {
            "operation": "OBJECT_ADMISSION",
            "definition": definition.canonical_value(),
            "blob_digest": "sha256:" + "a" * 64,
            "size_bytes": 7,
        }
    )
    unsigned = {
        "authentication_context_id": str(authentication.authentication_context_id),
        "principal_id": authentication.principal_id,
        "authority_domain": authentication.authority_domain,
        "operation_type": "object.admit:source.capture",
        "required_scope": definition.required_write_scope,
        "stable_semantic_request_digest": stable,
        "command_definition_digest": event_definition.digest,
        "aggregate_type": event_definition.aggregate_type,
        "aggregate_id": str(admission_id),
        "event_type": event_definition.event_type,
        "event_schema_version": 1,
        "payload_mode": "INLINE",
        "payload_schema_version": event_definition.payload_schema_version,
        "trust_scope": "OBSERVED",
        "security_scope": definition.security_scope,
        "retention_scope": definition.retention_scope,
        "object_class": definition.object_class,
        "allowed_use": definition.allowed_use,
    }
    request = _AuthorizationRequest(
        authentication_context_id=authentication.authentication_context_id,
        principal_id=authentication.principal_id,
        authority_domain=authentication.authority_domain,
        operation_type="object.admit:source.capture",
        required_scope=definition.required_write_scope,
        stable_semantic_request_digest=stable,
        command_definition_digest=event_definition.digest,
        aggregate_type=event_definition.aggregate_type,
        aggregate_id=str(admission_id),
        event_type=event_definition.event_type,
        event_schema_version=1,
        payload_mode="INLINE",
        payload_schema_version=event_definition.payload_schema_version,
        trust_scope="OBSERVED",
        security_scope=definition.security_scope,
        retention_scope=definition.retention_scope,
        object_class=definition.object_class,
        allowed_use=definition.allowed_use,
        request_digest=digest_canonical(unsigned),
    )
    authorization = authorizer.authorize(authentication, request, now=FIXED_NOW)
    rights = resolve_rights(
        StaticRightsResolver(
            {
                "source-permitted": StaticRightsRule(
                    policy_version="rights-v1",
                    allowed=True,
                    reason_code="RIGHTS_ALLOWED",
                    validity_seconds=300,
                )
            }
        ),
        definition,
        blob_digest="sha256:" + "a" * 64,
        authentication_context_id=str(authentication.authentication_context_id),
        authorization_decision_id=str(authorization.authorization_decision_id),
        principal_id=authentication.principal_id,
        authority_domain=authentication.authority_domain,
        now=FIXED_NOW,
    )
    issuer = _CapabilityIssuer(secret=b"x" * 32)
    grant = issuer.issue_admission(
        definition=definition,
        admission_id=admission_id,
        blob_digest="sha256:" + "a" * 64,
        size_bytes=7,
        authentication=authentication,
        authorization_request=request,
        authorization=authorization,
        rights=rights,
        idempotency_namespace=digest_canonical({"namespace": 1}),
        idempotency_key="admit-1",
        stable_semantic_request_digest=stable,
    )
    issuer.verify_admission(grant)
    return issuer, grant


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_version", "rights-v2"),
        ("reason_code", "RIGHTS_OTHER"),
        ("allowed_use", "publish.article"),
    ],
)
def test_changing_rights_provenance_with_same_id_invalidates_admission_grant(
    field: str, value: object
) -> None:
    issuer, grant = valid_grant()
    tampered = dataclasses.replace(
        grant,
        rights=dataclasses.replace(grant.rights, **{field: value}),
    )
    with pytest.raises(InvalidCommitCapability):
        issuer.verify_admission(tampered)


def test_changing_rights_validity_with_same_id_invalidates_admission_grant() -> None:
    issuer, grant = valid_grant()
    tampered = dataclasses.replace(
        grant,
        rights=dataclasses.replace(
            grant.rights,
            valid_until=UtcTimestamp(
                grant.rights.valid_until.value + timedelta(seconds=60)  # type: ignore[union-attr]
            ),
        ),
    )
    with pytest.raises(InvalidCommitCapability):
        issuer.verify_admission(tampered)
