from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import AggregateId
from newsroom.projection import ProjectionGenerationState, ProjectionStateError

from .authority_helpers import command as authority_command
from .extraction_4a_helpers import extraction_proof
from .increment4e_helpers import (
    admitted_increment4_fixture,
    open_increment4_neo4j_system,
)
from .test_increment4e_neo4j_controller import (
    GENERATION_1,
    _SourceRaceAdapter,
    _request,
)


def test_increment4_active_replay_rechecks_source_after_reconciliation(
    tmp_path: Path,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = _SourceRaceAdapter()
    request = _request(
        GENERATION_1,
        snapshot,
        key="increment4-active-source-race-v1",
    )

    with open_increment4_neo4j_system(state, adapter) as system:
        built = system.increment4.build_and_promote(
            request,
            proof=extraction_proof(),
        )
        apply_before_retry = adapter.apply_count
        cleanup_before_retry = adapter.cleanup_count
        reconcile_before_retry = adapter.reconcile_count
        adapter.before_first_reconcile = lambda: system.commands.execute(
            authority_command(
                key="increment4-active-source-race-authority-v1",
                aggregate_id=AggregateId.parse(
                    "00000000-0000-4000-8000-000000005099"
                ),
            ),
            proof=extraction_proof(),
        )

        with pytest.raises(
            ProjectionStateError,
            match="differs from exact retained admitted authority",
        ):
            system.increment4.build_and_promote(
                request,
                proof=extraction_proof(),
            )
        status = system.increment4.generation_status(
            GENERATION_1,
            proof=extraction_proof(),
        )

    assert built.generation.state is ProjectionGenerationState.ACTIVE
    assert status.generation.state is ProjectionGenerationState.ACTIVE
    assert status.source_watermark_ledger_seq > snapshot.through_ledger_seq
    assert adapter.apply_count == apply_before_retry
    assert adapter.cleanup_count == cleanup_before_retry
    assert adapter.reconcile_count == reconcile_before_retry + 1
