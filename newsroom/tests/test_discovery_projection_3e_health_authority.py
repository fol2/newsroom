from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import AuthenticationProof
from newsroom.authority._security import AuthenticationError
from newsroom.projection import (
    DiscoveryHealthDimension,
    DiscoveryHealthState,
    HealthPolicy,
)
from newsroom.projection.neo4j import (
    DiscoveryCoverageHealthReadRequest,
    DiscoverySourceHealthReadRequest,
)
from newsroom.sources.types import SourceDefinitionId

from .check_3c_helpers import DEFINITION_ID, LATER
from .discovery_projection_3e_helpers import (
    MemoryNeo4jAdapter,
    open_lineage_projection_system,
    proof,
)
from .test_discovery_projection_3e_authority import (
    register_generation,
    seed_complete_lineage,
)


POLICY = HealthPolicy(
    policy_id="increment-3e-authority-health",
    policy_version="v1",
    freshness_window_seconds=3_600,
)


def _source_request(
    definition_id: SourceDefinitionId = DEFINITION_ID,
) -> DiscoverySourceHealthReadRequest:
    return DiscoverySourceHealthReadRequest(
        definition_id=definition_id,
        policy=POLICY,
        assessed_at=LATER,
    )


def _open(database: Path):
    system = open_lineage_projection_system(
        database,
        MemoryNeo4jAdapter(),
        clock=lambda: LATER,
    )
    register_generation(system)
    return system


def test_authenticated_source_health_is_rederived_from_current_authority(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    system = _open(database)
    try:
        assessments = system.health.source(
            _source_request(),
            proof=proof(),
        )
        by_dimension = {item.dimension: item for item in assessments}

        assert set(by_dimension) == {
            DiscoveryHealthDimension.SOURCE_ACCESS,
            DiscoveryHealthDimension.SOURCE_CONTRACT,
            DiscoveryHealthDimension.PARSER,
            DiscoveryHealthDimension.CHECK_EXECUTION,
            DiscoveryHealthDimension.OBSERVATION_FRESHNESS,
            DiscoveryHealthDimension.SEMANTIC_LINEAGE,
        }
        assert all(
            item.state is DiscoveryHealthState.HEALTHY
            for item in by_dimension.values()
        )
        assert by_dimension[
            DiscoveryHealthDimension.OBSERVATION_FRESHNESS
        ].last_complete_observation_at == LATER
        assert by_dimension[
            DiscoveryHealthDimension.OBSERVATION_FRESHNESS
        ].last_successful_observation_at == LATER
        assert by_dimension[
            DiscoveryHealthDimension.OBSERVATION_FRESHNESS
        ].last_source_change_at == LATER
        evidence_types = {
            evidence.evidence_type
            for item in assessments
            for evidence in item.evidence
        }
        assert "SOURCE_DEFINITION_VERSION" in evidence_types
        assert "CHECK_OUTCOME" in evidence_types
        assert any(
            value.startswith("OBSERVABLE_TRANSITION:")
            for value in evidence_types
        )
    finally:
        system.close()


def test_coverage_health_uses_retained_anchor_contract_not_source_count(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    system = _open(database)
    try:
        available = system.health.coverage(
            DiscoveryCoverageHealthReadRequest(
                obligation_id="COV-021",
                policy=POLICY,
                assessed_at=LATER,
            ),
            proof=proof(),
        )
        missing = system.health.coverage(
            DiscoveryCoverageHealthReadRequest(
                obligation_id="COV-999",
                policy=POLICY,
                assessed_at=LATER,
            ),
            proof=proof(),
        )

        assert available.dimension is DiscoveryHealthDimension.COVERAGE_AVAILABILITY
        assert available.state is DiscoveryHealthState.HEALTHY
        assert available.reason_code == "COVERAGE_ACTIVE_ANCHOR_AVAILABLE"
        assert missing.state is DiscoveryHealthState.UNKNOWN
        assert missing.reason_code == "COVERAGE_ANCHOR_NOT_DEFINED"
    finally:
        system.close()


def test_health_authentication_precedes_definition_lookup(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    system = _open(database)
    try:
        missing = SourceDefinitionId.parse(
            "00000000-0000-4000-8000-000000009999"
        )
        with pytest.raises(AuthenticationError):
            system.health.source(
                _source_request(missing),
                proof=AuthenticationProof(
                    method="STATIC_TOKEN",
                    credential="invalid",
                ),
            )
    finally:
        system.close()
