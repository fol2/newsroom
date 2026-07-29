from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    DiscoveryHealthDimension,
    DiscoveryHealthState,
    HealthPolicy,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionRelationType,
)
from newsroom.projection.neo4j import (
    DiscoveryLineageProjectionFacade,
    DiscoverySourceHealthReadRequest,
    DiscoveryLineageReadError,
    DiscoveryLineageReadRequest,
    DiscoveryLineageSubject,
    Neo4jConnectionError,
)
from newsroom.sources import SourceDefinitionVersionId, SourceLifecycleStage

from .check_3c_authority_helpers import version_request
from .check_3c_helpers import DEFINITION_ID, LATER, VERSION_ID
from .discovery_3d_authority_helpers import open_discovery_system
from .discovery_3d_helpers import LEAD_ID, SIGNAL_ID
from .discovery_projection_3e_helpers import (
    MemoryNeo4jAdapter,
    open_lineage_projection_system,
    proof,
)
from .test_discovery_projection_3e_authority import (
    register_generation,
    seed_complete_lineage,
)
from .test_discovery_projection_3e_lifecycle import (
    _promote,
    _rebuild,
    _validate,
)


_POLICY = HealthPolicy(
    policy_id="discovery-lineage-health-v1",
    policy_version="discovery-lineage-health-policy-v1",
    freshness_window_seconds=3_600,
)


def _activate(system):
    generation = register_generation(system)
    rebuilt = _rebuild(system, generation, key="3e-read-rebuild")
    validation = _validate(
        system,
        generation.generation_id,
        rebuilt.checkpoint_ledger_seq,
        key="3e-read-validate",
    )
    _promote(
        system,
        generation.generation_id,
        validation,
        key="3e-read-promote",
    )
    return generation


def _request() -> DiscoveryLineageReadRequest:
    return DiscoveryLineageReadRequest(
        subjects=(
            DiscoveryLineageSubject(DEFINITION_ID),
            DiscoveryLineageSubject(SIGNAL_ID),
            DiscoveryLineageSubject(LEAD_ID),
        ),
        query_valid_time=UtcTimestamp.now(),
        limit=100,
    )


def test_discovery_lineage_read_requires_typed_unique_bounded_subjects() -> None:
    with pytest.raises(TypeError, match="governed lifecycle identity"):
        DiscoveryLineageSubject("raw-id")  # type: ignore[arg-type]

    subject = DiscoveryLineageSubject(SIGNAL_ID)
    with pytest.raises(ValueError, match="unique"):
        DiscoveryLineageReadRequest(
            subjects=(subject, subject),
            query_valid_time=UtcTimestamp.now(),
        )
    with pytest.raises(ValueError, match="outside policy bounds"):
        DiscoveryLineageReadRequest(
            subjects=(
                DiscoveryLineageSubject(SIGNAL_ID),
                DiscoveryLineageSubject(LEAD_ID),
            ),
            query_valid_time=UtcTimestamp.now(),
            limit=1,
        )


def test_fixed_family_read_requires_active_fresh_governed_roots(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        generation = _activate(system)
        facade = DiscoveryLineageProjectionFacade.from_system(system)
        request = _request()

        response = facade.read(request, proof=proof())
        assert response.metadata.family_id == DISCOVERY_LINEAGE_FAMILY_ID
        assert response.metadata.generation_id == generation.generation_id
        returned = {node.canonical_id: node for node in response.nodes}
        for subject in request.subjects:
            assert returned[subject.canonical_id].node_type is subject.node_type
            assert returned[subject.canonical_id].identity_source == "GOVERNED_ID"

        status = facade.status(proof=proof())
        assert status.authority_watermark_ledger_seq == status.contiguous_ledger_seq
        assert facade.gaps(proof=proof()) == ()
        assert facade.dead_letters(proof=proof()) == ()

        # Projection-management events occur after the projected source
        # watermark and must not make the fixed lineage family appear stale.
        system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                ProjectionGenerationId.new(),
                DISCOVERY_LINEAGE_FAMILY_ID,
                "INCREMENT_3E_PARALLEL_REBUILD",
                "3e-read-new-building-generation",
            ),
            proof=proof(),
        )
        later = facade.status(proof=proof())
        assert later.generation_id == generation.generation_id
        assert later.authority_watermark_ledger_seq == status.contiguous_ledger_seq
    finally:
        system.close()


def test_graph_loss_fails_closed_and_health_is_quarantined(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = MemoryNeo4jAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        generation = _activate(system)
        facade = DiscoveryLineageProjectionFacade.from_system(system)
        adapter.cleanup_generation(str(generation.generation_id))

        with pytest.raises(
            DiscoveryLineageReadError,
            match="missing a governed subject",
        ):
            facade.read(_request(), proof=proof())

        assessment = facade.assess_projection(
            _request(),
            policy=_POLICY,
            assessed_at=LATER,
            proof=proof(),
        )
        assert assessment.state is DiscoveryHealthState.QUARANTINED
        assert assessment.reason_code == "PROJECTION_VALIDATION_FAILED"
    finally:
        system.close()


class _UnexpectedRelationAdapter(MemoryNeo4jAdapter):
    def read(self, **kwargs):
        response = super().read(**kwargs)
        assert response.relations
        return replace(
            response,
            relations=(
                replace(
                    response.relations[0],
                    relation_type=ProjectionRelationType.DERIVED_FROM,
                ),
                *response.relations[1:],
            ),
        )


def test_bounded_read_rejects_relation_outside_discovery_ontology(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = _UnexpectedRelationAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        _activate(system)
        with pytest.raises(
            DiscoveryLineageReadError,
            match="unexpected relation type",
        ):
            DiscoveryLineageProjectionFacade.from_system(system).read(
                _request(), proof=proof()
            )
    finally:
        system.close()


class _InvalidEndpointTypeAdapter(MemoryNeo4jAdapter):
    def read(self, **kwargs):
        response = super().read(**kwargs)
        assert response.relations
        lead = DiscoveryLineageSubject(LEAD_ID).canonical_id
        return replace(
            response,
            relations=(
                replace(response.relations[0], target_canonical_id=lead),
                *response.relations[1:],
            ),
        )


def test_bounded_read_rejects_relation_endpoint_type_tamper(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = _InvalidEndpointTypeAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        _activate(system)
        with pytest.raises(
            DiscoveryLineageReadError,
            match="endpoints violate the ontology",
        ):
            DiscoveryLineageProjectionFacade.from_system(system).read(
                _request(), proof=proof()
            )
    finally:
        system.close()


class _UnavailableReadAdapter(MemoryNeo4jAdapter):
    def read(self, **_kwargs):
        raise Neo4jConnectionError("fixed unavailable projection service")


def test_projection_health_distinguishes_service_unavailability(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    adapter = _UnavailableReadAdapter()
    system = open_lineage_projection_system(database, adapter)
    try:
        _activate(system)
        assessment = DiscoveryLineageProjectionFacade.from_system(
            system
        ).assess_projection(
            _request(),
            policy=_POLICY,
            assessed_at=LATER,
            proof=proof(),
        )
        assert assessment.state is DiscoveryHealthState.UNAVAILABLE
        assert assessment.reason_code == "PROJECTION_SERVICE_UNAVAILABLE"
    finally:
        system.close()


def test_retired_source_fails_serving_and_rebuild_does_not_resurrect_lineage(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)

    retired_version_id = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000009801"
    )
    authority = open_discovery_system(database)
    try:
        authority.sources.record_definition_version(
            replace(
                version_request(),
                version_id=retired_version_id,
                version_number=2,
                expected_previous_version_id=VERSION_ID,
                locator="fixture://increment-3e/retired-guidance",
                lifecycle_stage=SourceLifecycleStage.RETIRED,
                change_reason="Retire the fixture source from current projection serving.",
                idempotency_key="increment-3e-retire-source",
            ),
            proof=proof(),
        )
    finally:
        authority.close()

    replacement_adapter = MemoryNeo4jAdapter()
    replacement_system = open_lineage_projection_system(
        database, replacement_adapter
    )
    try:
        facade = DiscoveryLineageProjectionFacade.from_system(
            replacement_system
        )
        replacement = register_generation(replacement_system)
        source_health = replacement_system.health.source(
            DiscoverySourceHealthReadRequest(
                definition_id=DEFINITION_ID,
                policy=_POLICY,
                assessed_at=LATER,
            ),
            proof=proof(),
        )
        source_contract = next(
            item
            for item in source_health
            if item.dimension is DiscoveryHealthDimension.SOURCE_CONTRACT
        )
        assert source_contract.state is DiscoveryHealthState.BLOCKED
        assert source_contract.reason_code == "SOURCE_RIGHTS_NOT_CURRENT"

        with pytest.raises(
            DiscoveryLineageReadError,
            match="not currently eligible",
        ):
            facade.read(_request(), proof=proof())
        with pytest.raises(
            DiscoveryLineageReadError,
            match="health subject is not currently eligible",
        ):
            facade.assess_projection(
                _request(),
                policy=_POLICY,
                assessed_at=LATER,
                proof=proof(),
            )

        rebuilt = _rebuild(
            replacement_system,
            replacement,
            key="3e-retired-source-rebuild",
        )
        assert rebuilt.recorded_delivery_count == 0
        assert rebuilt.ignored_optional_count > 0
        assert rebuilt.checkpoint_ledger_seq >= rebuilt.through_ledger_seq
        assert not {
            node.canonical_id
            for (generation_id, _sequence), batch
            in replacement_adapter.deliveries.items()
            if generation_id == str(replacement.generation_id)
            for node in batch.nodes
        }

        validation = _validate(
            replacement_system,
            replacement.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="3e-retired-source-validate",
        )
        _promote(
            replacement_system,
            replacement.generation_id,
            validation,
            key="3e-retired-source-promote",
        )
        with pytest.raises(
            DiscoveryLineageReadError,
            match="not currently eligible",
        ):
            facade.read(_request(), proof=proof())
    finally:
        replacement_system.close()
