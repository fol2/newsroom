from __future__ import annotations

import dataclasses
from datetime import timedelta
import inspect

import pytest

from newsroom.authority import (
    AuthenticationContextId,
    AuthorizationDecisionId,
    BlobState,
    ImmutableBlobIdentity,
    ObjectAdmissionDefinition,
    ObjectAdmissionDenied,
    ObjectAdmissionRegistry,
    ObjectAdmissionRequest,
    ObjectPolicyError,
    StaticRightsResolver,
    StaticRightsRule,
    UtcTimestamp,
    activate_admission_contract,
    digest_canonical,
    prepare_admission,
)

from .authority_helpers import FIXED_NOW


BLOB = ImmutableBlobIdentity(
    blob_digest="sha256:" + "b" * 64,
    size_bytes=128,
    state=BlobState.ACTIVE,
)
AUTHENTICATION_CONTEXT_ID = AuthenticationContextId.new()
AUTHORIZATION_DECISION_ID = AuthorizationDecisionId.new()
AUTHORIZATION_REQUEST_DIGEST = digest_canonical({"authorization": "object-admit"})


def definition(
    *,
    admission_type: str = "source.capture",
    allowed_use: str = "project.discovery",
    policy_key: str = "source-permitted",
    version: str = "admission-v1",
) -> ObjectAdmissionDefinition:
    return ObjectAdmissionDefinition(
        admission_type=admission_type,
        definition_version=version,
        object_class="source_capture",
        allowed_use=allowed_use,
        security_scope="authority.protected",
        retention_scope="source.short",
        required_write_scope="authority.objects.admit",
        required_read_scope="authority.objects.read",
        required_manage_scope="authority.objects.manage",
        rights_policy_key=policy_key,
    )


def resolver(*, allowed: bool = True) -> StaticRightsResolver:
    return StaticRightsResolver(
        {
            "source-permitted": StaticRightsRule(
                policy_version="rights-v1",
                allowed=allowed,
                reason_code=(
                    "RIGHTS_ALLOWED" if allowed else "RIGHTS_PROHIBITED"
                ),
                validity_seconds=300,
            ),
            "source-publish": StaticRightsRule(
                policy_version="rights-v2",
                allowed=True,
                reason_code="RIGHTS_ALLOWED_FOR_PUBLISH",
                validity_seconds=120,
            ),
        }
    )


def decide(
    selected: ObjectAdmissionDefinition,
    *,
    selected_resolver: StaticRightsResolver | None = None,
    blob: ImmutableBlobIdentity = BLOB,
    now: UtcTimestamp = FIXED_NOW,
):
    return (selected_resolver or resolver()).decide(
        selected,
        blob=blob,
        principal_id="principal.alpha",
        authority_domain="newsroom.authority",
        authentication_context_id=AUTHENTICATION_CONTEXT_ID,
        authorization_request_digest=AUTHORIZATION_REQUEST_DIGEST,
        authorization_decision_id=AUTHORIZATION_DECISION_ID,
        now=now,
    )


def test_registry_retains_historical_admission_definitions() -> None:
    v1 = definition(version="admission-v1")
    v2 = definition(version="admission-v2")
    registry = ObjectAdmissionRegistry(
        [v1, v2],
        current_versions={"source.capture": "admission-v2"},
    )
    assert registry.resolve("source.capture") == v2
    assert registry.resolve_exact(
        "source.capture", "admission-v1", v1.digest
    ) == v1
    with pytest.raises(LookupError, match="digest"):
        registry.resolve_exact(
            "source.capture",
            "admission-v1",
            digest_canonical({"different": True}),
        )


def test_known_denial_preflight_accepts_no_bytes_digest_or_source() -> None:
    parameters = set(inspect.signature(prepare_admission).parameters)
    assert {
        "data",
        "bytes",
        "source",
        "blob",
        "blob_digest",
        "size_bytes",
    }.isdisjoint(parameters)

    selected = definition()
    preflight = prepare_admission(
        registry=ObjectAdmissionRegistry([selected]),
        rights_resolver=resolver(allowed=False),
        request=ObjectAdmissionRequest(
            admission_type="source.capture",
            idempotency_key="deny-before-stage",
        ),
        principal_id="principal.alpha",
        authority_domain="newsroom.authority",
        now=FIXED_NOW,
    )
    assert preflight.required_write_scope == "authority.objects.admit"
    assert not preflight.rights.allowed
    with pytest.raises(ObjectAdmissionDenied, match="PROHIBITED"):
        preflight.require_allowed()


def test_exact_rights_decision_binds_blob_use_and_security_provenance() -> None:
    selected = definition()
    rights = decide(selected)
    assert rights.blob_digest == BLOB.blob_digest
    assert rights.size_bytes == BLOB.size_bytes
    assert rights.object_class == selected.object_class
    assert rights.allowed_use == selected.allowed_use
    assert rights.security_scope == selected.security_scope
    assert rights.retention_scope == selected.retention_scope
    assert rights.authentication_context_id == AUTHENTICATION_CONTEXT_ID
    assert rights.authorization_request_digest == AUTHORIZATION_REQUEST_DIGEST
    assert rights.authorization_decision_id == AUTHORIZATION_DECISION_ID
    assert rights.admission_definition_digest == selected.digest
    assert rights.rights_request_digest.startswith("sha256:")
    assert rights.digest.startswith("sha256:")
    rights.require_current(FIXED_NOW)

    changed = dataclasses.replace(rights, reason_code="RIGHTS_OTHER")
    assert changed.rights_decision_id == rights.rights_decision_id
    assert changed.digest != rights.digest


def test_denied_and_expired_rights_cannot_activate() -> None:
    selected = definition()
    denied = decide(selected, selected_resolver=resolver(allowed=False))
    with pytest.raises(ObjectAdmissionDenied, match="PROHIBITED"):
        activate_admission_contract(
            definition=selected,
            blob=BLOB,
            rights=denied,
            now=FIXED_NOW,
        )

    allowed = decide(selected)
    after_expiry = UtcTimestamp(
        FIXED_NOW.value + timedelta(seconds=300)
    )
    with pytest.raises(ObjectAdmissionDenied, match="EXPIRED"):
        activate_admission_contract(
            definition=selected,
            blob=BLOB,
            rights=allowed,
            now=after_expiry,
        )


def test_same_blob_supports_distinct_governed_use_admissions() -> None:
    discovery = definition(
        admission_type="source.discovery",
        allowed_use="project.discovery",
        policy_key="source-permitted",
    )
    publishing = definition(
        admission_type="source.publish",
        allowed_use="publish.article",
        policy_key="source-publish",
    )
    selected_resolver = resolver()
    discovery_rights = decide(
        discovery, selected_resolver=selected_resolver
    )
    publish_rights = decide(
        publishing, selected_resolver=selected_resolver
    )
    discovery_admission = activate_admission_contract(
        definition=discovery,
        blob=BLOB,
        rights=discovery_rights,
        now=FIXED_NOW,
    )
    publish_admission = activate_admission_contract(
        definition=publishing,
        blob=BLOB,
        rights=publish_rights,
        now=FIXED_NOW,
    )

    assert discovery_admission.blob == publish_admission.blob
    assert discovery_admission.admission_id != publish_admission.admission_id
    assert discovery_admission.allowed_use == "project.discovery"
    assert publish_admission.allowed_use == "publish.article"
    assert (
        discovery_admission.rights_decision_id
        != publish_admission.rights_decision_id
    )


def test_activation_rejects_rights_for_another_definition_or_blob() -> None:
    selected = definition()
    rights = decide(selected)
    other_definition = definition(allowed_use="publish.article")
    with pytest.raises(ObjectPolicyError, match="definition"):
        activate_admission_contract(
            definition=other_definition,
            blob=BLOB,
            rights=rights,
            now=FIXED_NOW,
        )

    other_blob = ImmutableBlobIdentity(
        blob_digest="sha256:" + "c" * 64,
        size_bytes=BLOB.size_bytes,
    )
    with pytest.raises(ObjectPolicyError, match="blob"):
        activate_admission_contract(
            definition=selected,
            blob=other_blob,
            rights=rights,
            now=FIXED_NOW,
        )
