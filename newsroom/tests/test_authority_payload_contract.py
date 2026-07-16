from __future__ import annotations

import pytest

from newsroom.authority import (
    AggregateId,
    CommandDefinition,
    CommandRegistry,
    CommandService,
    InlinePayload,
    NO_PAYLOAD,
    ObjectAdmissionDescriptor,
    ObjectAdmissionId,
    ObjectAdmissionPayload,
    PayloadMode,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    canonical_json_bytes,
)

from .authority_helpers import FIXED_NOW, proof


class Lookup:
    def __init__(self, descriptor: ObjectAdmissionDescriptor) -> None:
        self.descriptor = descriptor

    def resolve(self, admission_id: object) -> ObjectAdmissionDescriptor:
        assert admission_id == self.descriptor.admission_id
        return self.descriptor


def _inline_schema(value: object) -> bytes:
    if not isinstance(value, dict) or set(value) != {"a"}:
        raise PayloadSchemaValidationError("inline schema requires exactly field a")
    if isinstance(value["a"], bool) or not isinstance(value["a"], int):
        raise PayloadSchemaValidationError("field a must be an integer")
    return canonical_json_bytes(value)


def _no_payload_schema(value: object) -> bytes:
    if value is not None:
        raise PayloadSchemaValidationError("no-payload schema accepts no value")
    return b""


def _object_schema(value: object) -> bytes:
    if not isinstance(value, ObjectAdmissionDescriptor):
        raise PayloadSchemaValidationError("object schema requires admission descriptor")
    return canonical_json_bytes(
        {
            "admission_id": str(value.admission_id),
            "object_class": value.object_class,
            "allowed_use": value.allowed_use,
        }
    )


def schemas_for(definition: CommandDefinition) -> PayloadSchemaRegistry:
    if definition.payload_mode is PayloadMode.INLINE:
        canonicalizer = _inline_schema
    elif definition.payload_mode is PayloadMode.NO_PAYLOAD:
        canonicalizer = _no_payload_schema
    else:
        canonicalizer = _object_schema
    return PayloadSchemaRegistry(
        [
            PayloadSchemaContract(
                schema_version=definition.payload_schema_version,
                payload_mode=definition.payload_mode,
                canonicalizer=canonicalizer,
            )
        ]
    )


def service_for(
    definition: CommandDefinition, *, lookup: Lookup | None = None
) -> CommandService:
    return CommandService(
        registry=CommandRegistry([definition]),
        payload_schemas=schemas_for(definition),
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={
                "principal.alpha": frozenset({definition.required_scope})
            },
        ),
        admission_lookup=lookup,
        clock=lambda: FIXED_NOW,
    )


def test_arbitrary_digest_only_payload_is_not_a_supported_request_form() -> None:
    fields = SemanticCommand.__dataclass_fields__
    assert "payload_digest" not in fields
    assert "payload_object_ref" not in fields


def test_inline_payload_is_schema_validated_and_bounded() -> None:
    definition = CommandDefinition(
        command_type="inline.write",
        definition_version="v1",
        aggregate_type="fixture",
        event_type="fixture.written",
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
        payload_schema_version="fixture_v1",
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="authority.default",
        required_scope="authority.write",
        max_inline_bytes=16,
    )
    service = service_for(definition)
    receipt = service.authorize(
        SemanticCommand(
            command_type="inline.write",
            aggregate_id=AggregateId.new(),
            expected_aggregate_version=0,
            payload=InlinePayload({"a": 1}),
            idempotency_key="k",
        ),
        proof=proof(),
    )
    assert receipt.payload_mode == "INLINE"
    with pytest.raises(PayloadSchemaValidationError):
        service.authorize(
            SemanticCommand(
                command_type="inline.write",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=InlinePayload({"unvalidated": True}),
                idempotency_key="k-invalid",
            ),
            proof=proof(),
        )
    with pytest.raises(ValueError, match="exceeds"):
        service.authorize(
            SemanticCommand(
                command_type="inline.write",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=InlinePayload({"a": 10**12}),
                idempotency_key="k2",
            ),
            proof=proof(),
        )


def test_explicit_no_payload_is_required_and_schema_enforced() -> None:
    definition = CommandDefinition(
        command_type="no.payload",
        definition_version="v1",
        aggregate_type="fixture",
        event_type="fixture.pinged",
        event_schema_version=1,
        payload_mode=PayloadMode.NO_PAYLOAD,
        payload_schema_version="no_payload_v1",
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="authority.default",
        required_scope="authority.write",
    )
    service = service_for(definition)
    receipt = service.authorize(
        SemanticCommand(
            command_type="no.payload",
            aggregate_id=AggregateId.new(),
            expected_aggregate_version=0,
            payload=NO_PAYLOAD,
            idempotency_key="k",
        ),
        proof=proof(),
    )
    assert receipt.payload_mode == "NO_PAYLOAD"
    with pytest.raises(ValueError):
        service.authorize(
            SemanticCommand(
                command_type="no.payload",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=InlinePayload({}),
                idempotency_key="k2",
            ),
            proof=proof(),
        )


def test_object_payload_must_match_server_definition_and_schema() -> None:
    admission_id = ObjectAdmissionId.new()
    descriptor = ObjectAdmissionDescriptor(
        admission_id=admission_id,
        blob_digest="sha256:" + "a" * 64,
        object_class="source_capture",
        allowed_use="project.discovery",
        security_scope="authority.protected",
        retention_scope="source.short",
        active=True,
    )
    definition = CommandDefinition(
        command_type="object.write",
        definition_version="v1",
        aggregate_type="fixture",
        event_type="fixture.object.recorded",
        event_schema_version=1,
        payload_mode=PayloadMode.OBJECT_ADMISSION,
        payload_schema_version="object_reference_v1",
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.protected",
        retention_scope="source.short",
        required_scope="authority.write",
        required_object_class="source_capture",
        required_allowed_use="project.discovery",
    )
    service = service_for(definition, lookup=Lookup(descriptor))
    receipt = service.authorize(
        SemanticCommand(
            command_type="object.write",
            aggregate_id=AggregateId.new(),
            expected_aggregate_version=0,
            payload=ObjectAdmissionPayload(admission_id),
            idempotency_key="k",
        ),
        proof=proof(),
    )
    assert receipt.payload_digest == descriptor.blob_digest
    assert receipt.security_scope == descriptor.security_scope
