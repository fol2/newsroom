from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    DiscoveryHealthState,
    HealthPolicy,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
)
from newsroom.projection.neo4j import (
    DiscoveryLineageProjectionFacade,
    DiscoveryLineageReadError,
    DiscoveryLineageReadRequest,
    DiscoveryLineageSubject,
    Neo4jConnectionError,
)

from .check_3c_helpers import DEFINITION_ID
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
            assessed_at=UtcTimestamp.now(),
            proof=proof(),
        )
        assert assessment.state is DiscoveryHealthState.QUARANTINED
        assert assessment.reason_code == "PROJECTION_VALIDATION_FAILED"
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
            assessed_at=UtcTimestamp.now(),
            proof=proof(),
        )
        assert assessment.state is DiscoveryHealthState.UNAVAILABLE
        assert assessment.reason_code == "PROJECTION_SERVICE_UNAVAILABLE"
    finally:
        system.close()
