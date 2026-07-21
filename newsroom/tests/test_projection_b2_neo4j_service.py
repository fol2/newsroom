from __future__ import annotations

import os
from pathlib import Path

import pytest

from newsroom.authority import AuthenticationProof, digest_canonical
from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    StructuralIdentityContext,
    canonical_node_id,
)
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
    Neo4jApplyOutcome,
    Neo4jConnectionError,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    StructuralDeliveryRequest,
    StructuralReadRequest,
)
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter

from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import FAMILY_ID, projection_contracts
from .projection_b2_helpers import (
    open_b2_service_system,
    proof,
    source_command,
    structural_batch,
)


_REQUIRED_FLAG = "NEWSROOM_NEO4J_SERVICE_REQUIRED"


def _service_config() -> Neo4jProjectorConfig:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("actual Neo4j service is required only by the permanent B2 gate")
    return Neo4jProjectorConfig.from_environment()


def _register_and_create(system, *, key_suffix: str):
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(
            FAMILY_ID,
            f"b2-service-family-{key_suffix}",
        ),
        proof=proof(),
    )
    generation = system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "B2_ACTUAL_SERVICE",
            f"b2-service-generation-{key_suffix}",
        ),
        proof=proof(),
    )
    return generation


def _source_event(system, *, key: str):
    command = system.commands.execute(source_command(key=key), proof=proof())
    return next(
        event
        for event in system.events.after(0, limit=1000, proof=proof())
        if event.command_id == str(command.command_id)
    )


def _canonical_ids_for_source_event(event) -> tuple[str, ...]:
    contracts = projection_contracts()
    family = contracts.family(FAMILY_ID)
    mapping_contract = contracts.mappings.resolve_digest(
        family.mapping_contract_digest
    )
    mapping = mapping_contract.resolve(event.event_type)
    assert mapping is not None
    context = StructuralIdentityContext(
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        aggregate_version=event.aggregate_version,
        event_id=event.event_id,
        payload_id=event.payload_id,
        payload={"headline": "B2 fixture", "count": 1},
    )
    return tuple(
        canonical_node_id(binding, context)
        for binding in mapping.nodes
    )


def _cleanup(config: Neo4jProjectorConfig, *generation_ids: ProjectionGenerationId) -> None:
    adapter = _open_neo4j_adapter(config)
    try:
        adapter.verify_compatibility()
        for generation_id in generation_ids:
            adapter.cleanup_generation(str(generation_id))
    finally:
        adapter.close()


def test_actual_service_public_round_trip_duplicate_and_generation_isolation(
    tmp_path: Path,
) -> None:
    config = _service_config()
    generations: list[ProjectionGenerationId] = []
    system = open_b2_service_system(tmp_path / "authority.sqlite3", config)
    try:
        assert system.compatibility.server_version == NEO4J_B2_SERVER_VERSION
        assert system.compatibility.edition == "community"
        assert system.compatibility.driver_version == NEO4J_B2_DRIVER_VERSION

        first_generation = _register_and_create(system, key_suffix="first")
        generations.append(first_generation.generation_id)
        source = _source_event(system, key="b2-service-source")
        request = StructuralDeliveryRequest(
            first_generation.generation_id,
            first_generation.authority_aggregate_version,
            source.ledger_seq,
            "b2-service-delivery",
        )
        first = system.structural.deliver(request, proof=proof())
        replay = system.structural.deliver(request, proof=proof())
        assert replay == first

        canonical_ids = _canonical_ids_for_source_event(source)
        response = system.structural.read(
            StructuralReadRequest(
                first_generation.generation_id,
                canonical_ids,
                FIXED_NOW,
                limit=100,
            ),
            proof=proof(),
        )
        assert response.nodes
        assert response.relations
        assert {node.canonical_id for node in response.nodes} <= set(canonical_ids)
        assert all(node.canonical_id.startswith("npid:v1:") for node in response.nodes)
        assert all(
            relation.source_event_id == source.event_id
            and relation.source_event_digest == first.source_event_digest
            for relation in response.relations
        )
        assert not any(hasattr(node, "element_id") for node in response.nodes)
        assert not any(hasattr(node, "neo4j_id") for node in response.nodes)

        second_generation = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                ProjectionGenerationId.new(),
                FAMILY_ID,
                "B2_ACTUAL_SERVICE_ISOLATION",
                "b2-service-generation-second",
            ),
            proof=proof(),
        )
        generations.append(second_generation.generation_id)
        isolated = system.structural.read(
            StructuralReadRequest(
                second_generation.generation_id,
                canonical_ids,
                FIXED_NOW,
                limit=100,
            ),
            proof=proof(),
        )
        assert isolated.nodes == ()
        assert isolated.relations == ()
    finally:
        system.close()
        _cleanup(config, *generations)


def test_actual_service_private_adapter_exact_duplicate_and_digest_conflict() -> None:
    config = _service_config()
    generation_id = ProjectionGenerationId.new()
    adapter = _open_neo4j_adapter(config)
    try:
        compatibility = adapter.verify_compatibility()
        assert compatibility.server_version == NEO4J_B2_SERVER_VERSION
        adapter.bootstrap_schema()
        batch = structural_batch(generation_id=generation_id, ledger_seq=900_001)
        assert adapter.apply(batch).outcome is Neo4jApplyOutcome.APPLIED
        assert adapter.apply(batch).outcome is Neo4jApplyOutcome.DUPLICATE
        object.__setattr__(
            batch,
            "source_event_digest",
            digest_canonical({"changed": "same delivery identity"}),
        )
        with pytest.raises(Neo4jIdentityConflict):
            adapter.apply(batch)
    finally:
        try:
            adapter.cleanup_generation(str(generation_id))
        finally:
            adapter.close()


def test_actual_service_wrong_projector_credential_fails_closed_without_secret(
    tmp_path: Path,
) -> None:
    config = _service_config()
    wrong_secret = "B2WrongCredentialMustNotLeak"
    wrong = Neo4jProjectorConfig(
        uri=config.uri,
        database=config.database,
        username=config.username,
        password=wrong_secret,
    )
    with pytest.raises(Neo4jConnectionError) as captured:
        open_b2_service_system(tmp_path / "wrong.sqlite3", wrong)
    assert wrong_secret not in str(captured.value)
    assert wrong_secret not in repr(captured.value)


def test_actual_service_requires_explicit_authentication_configuration() -> None:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("actual Neo4j service is required only by the permanent B2 gate")
    with pytest.raises(Exception, match="incomplete"):
        Neo4jProjectorConfig.from_environment({})
    with pytest.raises(Exception):
        AuthenticationProof(method="STATIC_TOKEN", credential="")
