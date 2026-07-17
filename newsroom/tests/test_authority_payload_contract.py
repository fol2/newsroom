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
    PayloadGoldenVector,
    PayloadMode,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    UnknownPayloadSchema,
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
        raise PayloadSchemaValidationError(
            "inline schema requires exactly field a"
        )
    if isinstance(value["a"], bool) or not isinstance(value["a"], int):
        raise PayloadSchemaValidationError("field a must be an integer")
    return canonical_json_bytes(value)


def _no_payload_schema(value: object) -> bytes:
    if value is not None:
        raise PayloadSchemaValidationError(
            "no-payload schema accepts no value"
        )
    return b""


def _object_schema(value: object) -> bytes:
    if not isinstance(value, ObjectAdmissionDescriptor):
        raise PayloadSchemaValidationError(
            "object schema requires admission descriptor"
        )
    return canonical_json_bytes(
        {
            "admission_id": str(value.admission_id),
            "object_class": value.object_class,
            "allowed_use": value.allowed_use,
        }
    )


def _contract(
    *,
    schema_version: str,
    mode: PayloadMode,
    contract_version: str,
    canonicalizer_version: str,
    canonicalizer,
    vector_value: object,
    vector_bytes: bytes,
) -> PayloadSchemaContract:
    return PayloadSchemaContract(
        schema_version=schema_version,
        payload_mode=mode,
        contract_version=contract_version,
        canonicalizer_implementation_version=canonicalizer_version,
        canonicalizer=canonicalizer,
        golden_vectors=(
            PayloadGoldenVector(
                name="golden",
                input_identity=f"{schema_version}-golden-v1",
                value=vector_value,
                expected_bytes=vector_bytes,
            ),
        ),
    )


def _definition(
    *,
    command_type: str,
    mode: PayloadMode,
    contract: PayloadSchemaContract,
    max_inline_bytes: int = 0,
    object_class: str | None = None,
    allowed_use: str | None = None,
) -> CommandDefinition:
    return CommandDefinition(
        command_type=command_type,
        definition_version="v1",
        aggregate_type="fixture",
        event_type=f"{command_type}.recorded",
        event_schema_version=1,
        payload_mode=mode,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=(
            contract.canonicalizer_implementation_version
        ),
        trust_scope=TrustScope.OBSERVED,
        security_scope=(
            "authority.protected"
            if mode is PayloadMode.OBJECT_ADMISSION
            else "authority.internal"
        ),
        retention_scope=(
            "source.short"
            if mode is PayloadMode.OBJECT_ADMISSION
            else "authority.default"
        ),
        required_scope="authority.write",
        max_inline_bytes=max_inline_bytes,
        required_object_class=object_class,
        required_allowed_use=allowed_use,
    )


def service_for(
    definition: CommandDefinition,
    contract: PayloadSchemaContract,
    *,
    lookup: Lookup | None = None,
) -> CommandService:
    return CommandService(
        registry=CommandRegistry([definition]),
        payload_schemas=PayloadSchemaRegistry([contract]),
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


def test_arbitrary_digest_only_payload_is_not_supported() -> None:
    fields = SemanticCommand.__dataclass_fields__
    assert "payload_digest" not in fields
    assert "payload_object_ref" not in fields


def test_inline_payload_is_schema_validated_bounded_and_identified() -> None:
    vector = {"a": 1}
    contract = _contract(
        schema_version="fixture_v1",
        mode=PayloadMode.INLINE,
        contract_version="fixture-contract-v1",
        canonicalizer_version="fixture-canon-v1",
        canonicalizer=_inline_schema,
        vector_value=vector,
        vector_bytes=_inline_schema(vector),
    )
    definition = _definition(
        command_type="inline.write",
        mode=PayloadMode.INLINE,
        contract=contract,
        max_inline_bytes=16,
    )
    service = service_for(definition, contract)
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
    assert (
        receipt.payload_schema_contract_digest
        == contract.contract_digest
    )
    assert (
        receipt.payload_canonicalizer_version
        == contract.canonicalizer_implementation_version
    )
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
    contract = _contract(
        schema_version="no_payload_v1",
        mode=PayloadMode.NO_PAYLOAD,
        contract_version="no-payload-contract-v1",
        canonicalizer_version="no-payload-canon-v1",
        canonicalizer=_no_payload_schema,
        vector_value=None,
        vector_bytes=b"",
    )
    definition = _definition(
        command_type="no.payload",
        mode=PayloadMode.NO_PAYLOAD,
        contract=contract,
    )
    service = service_for(definition, contract)
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


def test_object_payload_must_match_definition_and_schema_contract() -> None:
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
    contract = _contract(
        schema_version="object_reference_v1",
        mode=PayloadMode.OBJECT_ADMISSION,
        contract_version="object-contract-v1",
        canonicalizer_version="object-canon-v1",
        canonicalizer=_object_schema,
        vector_value=descriptor,
        vector_bytes=_object_schema(descriptor),
    )
    definition = _definition(
        command_type="object.write",
        mode=PayloadMode.OBJECT_ADMISSION,
        contract=contract,
        object_class="source_capture",
        allowed_use="project.discovery",
    )
    receipt = service_for(
        definition, contract, lookup=Lookup(descriptor)
    ).authorize(
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


def test_golden_vectors_reject_silent_canonicalizer_change() -> None:
    vector = {"a": 1}

    def changed(value: object) -> bytes:
        _inline_schema(value)
        return b'{"a":2}'

    with pytest.raises(
        PayloadSchemaValidationError, match="golden vector"
    ):
        _contract(
            schema_version="fixture_v1",
            mode=PayloadMode.INLINE,
            contract_version="fixture-contract-v1",
            canonicalizer_version="fixture-canon-v1",
            canonicalizer=changed,
            vector_value=vector,
            vector_bytes=_inline_schema(vector),
        )


def test_schema_contract_identity_changes_definition_and_semantic_identity() -> None:
    vector = {"a": 1}
    first_contract = _contract(
        schema_version="fixture_v1",
        mode=PayloadMode.INLINE,
        contract_version="fixture-contract-v1",
        canonicalizer_version="fixture-canon-v1",
        canonicalizer=_inline_schema,
        vector_value=vector,
        vector_bytes=_inline_schema(vector),
    )
    second_contract = _contract(
        schema_version="fixture_v1",
        mode=PayloadMode.INLINE,
        contract_version="fixture-contract-v2",
        canonicalizer_version="fixture-canon-v2",
        canonicalizer=_inline_schema,
        vector_value=vector,
        vector_bytes=_inline_schema(vector),
    )
    first_definition = _definition(
        command_type="inline.write",
        mode=PayloadMode.INLINE,
        contract=first_contract,
        max_inline_bytes=16,
    )
    second_definition = _definition(
        command_type="inline.write",
        mode=PayloadMode.INLINE,
        contract=second_contract,
        max_inline_bytes=16,
    )
    assert first_definition.digest != second_definition.digest
    aggregate_id = AggregateId.new()
    request = SemanticCommand(
        command_type="inline.write",
        aggregate_id=aggregate_id,
        expected_aggregate_version=0,
        payload=InlinePayload({"a": 1}),
        idempotency_key="k",
    )
    first = service_for(
        first_definition, first_contract
    ).authorize(request, proof=proof())
    second = service_for(
        second_definition, second_contract
    ).authorize(request, proof=proof())
    assert (
        first.stable_semantic_request_digest
        != second.stable_semantic_request_digest
    )


def test_composition_rejects_definition_without_retained_schema_contract() -> None:
    vector = {"a": 1}
    required = _contract(
        schema_version="fixture_v1",
        mode=PayloadMode.INLINE,
        contract_version="fixture-contract-v1",
        canonicalizer_version="fixture-canon-v1",
        canonicalizer=_inline_schema,
        vector_value=vector,
        vector_bytes=_inline_schema(vector),
    )
    unrelated = _contract(
        schema_version="other_v1",
        mode=PayloadMode.INLINE,
        contract_version="other-contract-v1",
        canonicalizer_version="other-canon-v1",
        canonicalizer=_inline_schema,
        vector_value=vector,
        vector_bytes=_inline_schema(vector),
    )
    definition = _definition(
        command_type="inline.write",
        mode=PayloadMode.INLINE,
        contract=required,
        max_inline_bytes=16,
    )
    with pytest.raises(UnknownPayloadSchema):
        CommandService(
            registry=CommandRegistry([definition]),
            payload_schemas=PayloadSchemaRegistry([unrelated]),
            authenticator=StaticAuthenticator(
                credentials={
                    "token-1": StaticPrincipal("principal.alpha")
                },
                authority_domain="newsroom.authority",
            ),
            authorizer=StaticAuthorizer(
                policy_version="authz-v1",
                grants_by_principal={
                    "principal.alpha": frozenset({"authority.write"})
                },
            ),
            clock=lambda: FIXED_NOW,
        )
