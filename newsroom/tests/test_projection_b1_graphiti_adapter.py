from __future__ import annotations

from contextlib import closing
import sqlite3

from newsroom.graphiti_adapter import GraphitiAdapterOutcome

from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    fake_attempt,
    open_graphiti_system,
    seed_graphiti_authority_fixture,
)


def test_graphiti_workspace_and_proposals_never_enter_admitted_projection(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration,
            proof=extraction_proof(),
        )
        attempt = system.graphiti.execute_attempt(
            request,
            proof=extraction_proof(),
        )

    assert attempt.outcome is GraphitiAdapterOutcome.COMPLETE
    assert attempt.proposal_set_id is not None
    private_namespace = (
        workspace_root
        / f"{request.configuration.workspace_policy.namespace_prefix}-"
        f"{request.workspace_id}"
    )
    assert not private_namespace.exists()
    with closing(sqlite3.connect(state.database)) as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "entity_resolution_decisions",
                "canonical_entities",
                "entity_projection_events",
                "editorial_relation_decisions",
                "editorial_relation_assertions",
                "editorial_relation_projection_events",
            )
        }
        assert counts == {table: 0 for table in counts}
        proposal_count = conn.execute(
            "SELECT COUNT(*) FROM extraction_proposals "
            "WHERE proposal_set_id=?",
            (str(attempt.proposal_set_id),),
        ).fetchone()[0]
        workspace_rows = conn.execute(
            "SELECT COUNT(*) FROM graphiti_workspaces WHERE workspace_id=?",
            (str(attempt.workspace_id),),
        ).fetchone()[0]
        cleanup_rows = conn.execute(
            "SELECT COUNT(*) FROM graphiti_cleanup_receipts WHERE workspace_id=?",
            (str(attempt.workspace_id),),
        ).fetchone()[0]

    assert proposal_count == 4
    assert workspace_rows == 1
    assert cleanup_rows == 1
