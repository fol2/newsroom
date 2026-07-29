from __future__ import annotations

from pathlib import Path

from newsroom.authority import UtcTimestamp
from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    DiscoveryHealthState,
)
from newsroom.projection.neo4j import DiscoveryLineageProjectionFacade

from .discovery_projection_3e_helpers import (
    MemoryNeo4jAdapter,
    open_lineage_projection_system,
    proof,
)
from .test_discovery_projection_3e_authority import seed_complete_lineage
from .test_discovery_projection_3e_reads import _POLICY, _activate, _request


def test_active_projection_health_advances_current_assessment_after_evidence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    system = open_lineage_projection_system(database, MemoryNeo4jAdapter())
    try:
        generation = _activate(system)
        requested_at = UtcTimestamp.now()

        assessment = DiscoveryLineageProjectionFacade.from_system(
            system
        ).assess_projection(
            _request(),
            policy=_POLICY,
            assessed_at=requested_at,
            proof=proof(),
        )

        status_evidence = next(
            item
            for item in assessment.evidence
            if item.evidence_type == "PROJECTION_STATUS"
        )
        assert status_evidence.identifier == str(generation.generation_id)
        assert status_evidence.observed_at.value > requested_at.value
        assert assessment.scope_id == DISCOVERY_LINEAGE_FAMILY_ID
        assert assessment.state is DiscoveryHealthState.HEALTHY
        assert assessment.reason_code == "PROJECTION_ACTIVE_AND_RECONCILED"
        assert {item.evidence_type for item in assessment.evidence} >= {
            "PROJECTION_STATUS",
            "PROJECTION_VALIDATION",
        }
        expected_assessed_at = max(
            [requested_at, *(item.observed_at for item in assessment.evidence)],
            key=lambda value: value.value,
        )
        assert assessment.assessed_at == expected_assessed_at
        assert all(
            item.observed_at.value <= assessment.assessed_at.value
            for item in assessment.evidence
        )
    finally:
        system.close()
