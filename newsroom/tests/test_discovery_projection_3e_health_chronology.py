from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    DiscoveryHealthContractError,
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


def test_active_projection_health_advances_after_all_live_observations(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    system = open_lineage_projection_system(database, MemoryNeo4jAdapter())
    try:
        generation = _activate(system)
        requested_at = UtcTimestamp.now()
        status = system.projections.status(
            DISCOVERY_LINEAGE_FAMILY_ID,
            proof=proof(),
        )
        assert status.generation_id is not None
        reconciliation_time = UtcTimestamp(
            status.serving_time.value + timedelta(seconds=1)
        )
        read_time = UtcTimestamp(
            status.serving_time.value + timedelta(seconds=2)
        )
        observed: dict[str, UtcTimestamp] = {}

        def reconcile_active(request, auth):
            result = system.structural.reconcile_active(
                request,
                proof=auth,
            )
            observed["reconciliation"] = reconciliation_time
            return replace(result, serving_time=reconciliation_time)

        def active_read(request, auth):
            result = system.structural.read_active(
                request,
                proof=auth,
            )
            observed["read"] = read_time
            return replace(
                result,
                metadata=replace(
                    result.metadata,
                    serving_time=read_time,
                ),
            )

        facade = DiscoveryLineageProjectionFacade(
            active_read=active_read,
            reconcile_active=reconcile_active,
            status=lambda _family_id, _auth: status,
            validation=lambda generation_id, auth: system.projections.validation(
                generation_id,
                proof=auth,
            ),
            gaps=lambda generation_id, limit, auth: system.projections.gaps(
                generation_id,
                limit=limit,
                proof=auth,
            ),
            dead_letters=lambda generation_id, limit, auth: (
                system.projections.dead_letters(
                    generation_id,
                    limit=limit,
                    proof=auth,
                )
            ),
            eligibility=lambda identifiers, auth: (
                system.health.require_lineage_eligible(
                    identifiers,
                    proof=auth,
                )
            ),
        )

        assessment = facade.assess_projection(
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
        assert observed == {
            "reconciliation": reconciliation_time,
            "read": read_time,
        }
        assert assessment.scope_id == DISCOVERY_LINEAGE_FAMILY_ID
        assert assessment.state is DiscoveryHealthState.HEALTHY
        assert assessment.reason_code == "PROJECTION_ACTIVE_AND_RECONCILED"
        assert {item.evidence_type for item in assessment.evidence} >= {
            "PROJECTION_STATUS",
            "PROJECTION_VALIDATION",
        }
        assert assessment.assessed_at == read_time
        assert assessment.assessed_at == max(
            (
                requested_at,
                status_evidence.observed_at,
                reconciliation_time,
                read_time,
            ),
            key=lambda item: item.value,
        )
        assert all(
            item.observed_at.value <= assessment.assessed_at.value
            for item in assessment.evidence
        )
    finally:
        system.close()


def test_persisted_future_validation_evidence_still_fails_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    system = open_lineage_projection_system(database, MemoryNeo4jAdapter())
    try:
        _activate(system)
        status = system.projections.status(
            DISCOVERY_LINEAGE_FAMILY_ID,
            proof=proof(),
        )
        assert status.generation_id is not None
        validation = system.projections.validation(
            status.generation_id,
            proof=proof(),
        )
        future = UtcTimestamp(
            status.serving_time.value + timedelta(seconds=1)
        )
        facade = DiscoveryLineageProjectionFacade(
            active_read=lambda request, auth: system.structural.read_active(
                request,
                proof=auth,
            ),
            reconcile_active=lambda request, auth: system.structural.reconcile_active(
                request,
                proof=auth,
            ),
            status=lambda _family_id, _auth: status,
            validation=lambda _generation_id, _auth: replace(
                validation,
                recorded_at=future,
            ),
            gaps=lambda generation_id, limit, auth: system.projections.gaps(
                generation_id,
                limit=limit,
                proof=auth,
            ),
            dead_letters=lambda generation_id, limit, auth: (
                system.projections.dead_letters(
                    generation_id,
                    limit=limit,
                    proof=auth,
                )
            ),
            eligibility=lambda identifiers, auth: system.health.require_lineage_eligible(
                identifiers,
                proof=auth,
            ),
        )

        with pytest.raises(
            DiscoveryHealthContractError,
            match="evidence cannot follow",
        ):
            facade.assess_projection(
                _request(),
                policy=_POLICY,
                assessed_at=status.serving_time,
                proof=proof(),
            )
    finally:
        system.close()
