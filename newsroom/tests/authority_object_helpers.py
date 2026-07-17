from __future__ import annotations

from pathlib import Path
from typing import Callable

from newsroom.authority import (
    CommandDefinition, CommandRegistry, ObjectAdmissionDefinition,
    ObjectAdmissionDescriptor, ObjectAdmissionRegistry, ObjectLimits, PayloadMode,
    PayloadSchemaContract, PayloadSchemaRegistry, PayloadSchemaValidationError,
    StaticAuthenticator, StaticAuthorizer, StaticPrincipal, StaticRightsResolver,
    StaticRightsRule, TrustScope, UtcTimestamp, canonical_json_bytes,
    open_authority_object_system,
)
from .authority_helpers import FIXED_NOW, admitted_definition, fixture_payload_bytes, observed_definition

ALL_SCOPES = frozenset({
    "authority.observed.write", "authority.events.read", "authority.audit.read",
    "authority.objects.admit", "authority.objects.read", "authority.objects.manage",
    "authority.objects.delete", "authority.objects.recovery", "authority.objects.gc",
})


def admission_definition() -> ObjectAdmissionDefinition:
    return ObjectAdmissionDefinition(
        admission_type="source.capture", definition_version="admission-v1",
        object_class="source_capture", allowed_use="project.discovery",
        security_scope="authority.protected", retention_scope="source.short",
        required_write_scope="authority.objects.admit",
        required_read_scope="authority.objects.read",
        required_manage_scope="authority.objects.manage",
        rights_policy_key="source-permitted",
    )


def object_command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="record.object", definition_version="cmd-v1",
        aggregate_type="fixture_record", event_type="fixture.object.recorded",
        event_schema_version=1, payload_mode=PayloadMode.OBJECT_ADMISSION,
        payload_schema_version="object_reference_v1", trust_scope=TrustScope.OBSERVED,
        security_scope="authority.protected", retention_scope="source.short",
        required_scope="authority.observed.write", required_object_class="source_capture",
        required_allowed_use="project.discovery",
    )


def object_reference_bytes(value: object) -> bytes:
    if not isinstance(value, ObjectAdmissionDescriptor):
        raise PayloadSchemaValidationError("object schema requires admission descriptor")
    return canonical_json_bytes({
        "admission_id": str(value.admission_id), "blob_digest": value.blob_digest,
        "object_class": value.object_class, "allowed_use": value.allowed_use,
    })


def payload_schemas() -> PayloadSchemaRegistry:
    return PayloadSchemaRegistry([
        PayloadSchemaContract(
            schema_version="fixture_payload_v1", payload_mode=PayloadMode.INLINE,
            canonicalizer=fixture_payload_bytes,
        ),
        PayloadSchemaContract(
            schema_version="object_reference_v1", payload_mode=PayloadMode.OBJECT_ADMISSION,
            canonicalizer=object_reference_bytes,
        ),
    ])


def open_object_system(
    root: Path, *, rights_allowed: bool = True,
    rights_validity_seconds: int | None = 3600,
    scopes: frozenset[str] = ALL_SCOPES, limits: ObjectLimits | None = None,
    blob_store_factory: object | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
):
    kwargs = {}
    if blob_store_factory is not None:
        kwargs["blob_store_factory"] = blob_store_factory
    return open_authority_object_system(
        database_path=root / "authority.sqlite3", object_root=root / "objects",
        command_registry=CommandRegistry([
            observed_definition(), admitted_definition(), object_command_definition(),
        ]),
        payload_schemas=payload_schemas(),
        admission_registry=ObjectAdmissionRegistry([admission_definition()]),
        rights_resolver=StaticRightsResolver({
            "source-permitted": StaticRightsRule(
                policy_version="rights-v1", allowed=rights_allowed,
                reason_code="RIGHTS_ALLOWED" if rights_allowed else "RIGHTS_PROHIBITED",
                validity_seconds=rights_validity_seconds,
            )
        }),
        limits=limits or ObjectLimits(
            global_max_bytes=1024, class_max_bytes={"source_capture": 512},
            max_read_bytes=512, min_free_bytes=0, io_chunk_bytes=32,
        ),
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1", grants_by_principal={"principal.alpha": scopes},
        ),
        clock=clock or (lambda: FIXED_NOW), **kwargs,
    )
