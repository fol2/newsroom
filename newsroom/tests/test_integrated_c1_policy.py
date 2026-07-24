from __future__ import annotations

import pytest

from newsroom.authority import (
    AggregateId,
    InlinePayload,
    ObjectAdmissionId,
    ObjectAdmissionPayload,
    PayloadMode,
    SemanticCommand,
)
from newsroom.authority.models import ObjectAdmissionDescriptor
from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.integrated import (
    CANDIDATE_ADMISSION_COMMAND,
    INTEGRATED_FIXTURE_COMMAND,
    integrated_command_definitions,
    integrated_payload_contracts,
    merge_integrated_authority_registries,
)

from .authority_event_helpers import payload_schemas
from .projection_b1_helpers import source_command_registry


def test_integrated_command_contracts_preserve_object_and_candidate_authority() -> None:
    definitions = {
        item.command_type: item for item in integrated_command_definitions()
    }
    fixture = definitions[INTEGRATED_FIXTURE_COMMAND]
    assert fixture.aggregate_type == "integrated_fixture"
    assert fixture.event_type == "authority.aggregate.versioned"
    assert fixture.payload_mode is PayloadMode.OBJECT_ADMISSION
    assert fixture.required_object_class == "source_capture"
    assert fixture.required_allowed_use == "project.discovery"
    assert fixture.trust_scope.value == "OBSERVED"

    candidate = definitions[CANDIDATE_ADMISSION_COMMAND]
    assert candidate.aggregate_type == "candidate_admission_proposal"
    assert candidate.event_type == "candidate.admission.decided"
    assert candidate.payload_mode is PayloadMode.INLINE
    assert candidate.required_scope == "authority.candidate.admit"
    assert candidate.trust_scope.value == "ADMITTED"


def test_integrated_payload_contracts_are_exact_and_replay_stable() -> None:
    contracts = {
        item.schema_version: item for item in integrated_payload_contracts()
    }
    fixture = contracts["integrated_fixture_object_v1"]
    descriptor = ObjectAdmissionDescriptor(
        admission_id=ObjectAdmissionId.parse(
            "00000000-0000-4000-8000-000000000301"
        ),
        blob_digest="sha256:" + "b" * 64,
        object_class="source_capture",
        allowed_use="project.discovery",
        security_scope="authority.protected",
        retention_scope="source.short",
        active=True,
    )
    assert fixture.canonicalize(descriptor)
    with pytest.raises(PayloadSchemaValidationError):
        fixture.canonicalize({"admission_id": str(descriptor.admission_id)})

    candidate = contracts["integrated_candidate_admission_v1"]
    value = {
        "proposal_id": "proposal",
        "route": "NEW_EVENT",
        "fixture_id": "fixture",
        "retrieval_context_digest": "sha256:" + "1" * 64,
        "manifest_digest": "sha256:" + "2" * 64,
        "semantic_collision_digest": "sha256:" + "3" * 64,
    }
    assert candidate.canonicalize(value)
    with pytest.raises(PayloadSchemaValidationError):
        candidate.canonicalize({**value, "unexpected": "field"})


def test_integrated_registry_merge_is_idempotent_and_retains_payload_modes() -> None:
    commands, schemas = merge_integrated_authority_registries(
        command_registry=source_command_registry(),
        payload_schemas=payload_schemas(),
    )
    repeated_commands, repeated_schemas = merge_integrated_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )

    for command_type in (
        INTEGRATED_FIXTURE_COMMAND,
        CANDIDATE_ADMISSION_COMMAND,
    ):
        assert commands.resolve(command_type).digest == (
            repeated_commands.resolve(command_type).digest
        )

    fixture = commands.resolve(INTEGRATED_FIXTURE_COMMAND)
    candidate = commands.resolve(CANDIDATE_ADMISSION_COMMAND)
    assert isinstance(
        SemanticCommand(
            command_type=fixture.command_type,
            aggregate_id=AggregateId.new(),
            expected_aggregate_version=0,
            payload=ObjectAdmissionPayload(
                ObjectAdmissionId.parse(
                    "00000000-0000-4000-8000-000000000302"
                )
            ),
            idempotency_key="integrated-fixture-policy-test",
        ).payload,
        ObjectAdmissionPayload,
    )
    assert isinstance(
        SemanticCommand(
            command_type=candidate.command_type,
            aggregate_id=AggregateId.new(),
            expected_aggregate_version=0,
            payload=InlinePayload(
                {
                    "proposal_id": "proposal",
                    "route": "NEW_EVENT",
                    "fixture_id": "fixture",
                    "retrieval_context_digest": "sha256:" + "1" * 64,
                    "manifest_digest": "sha256:" + "2" * 64,
                    "semantic_collision_digest": "sha256:" + "3" * 64,
                }
            ),
            idempotency_key="integrated-candidate-policy-test",
        ).payload,
        InlinePayload,
    )

    assert schemas.resolve(
        fixture.payload_schema_version,
        PayloadMode.OBJECT_ADMISSION,
    ).contract_digest == repeated_schemas.resolve(
        fixture.payload_schema_version,
        PayloadMode.OBJECT_ADMISSION,
    ).contract_digest
    assert schemas.resolve(
        candidate.payload_schema_version,
        PayloadMode.INLINE,
    ).contract_digest == repeated_schemas.resolve(
        candidate.payload_schema_version,
        PayloadMode.INLINE,
    ).contract_digest
