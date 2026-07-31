from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority._graphiti_adapter_store import _GraphitiAdapterAuthorityStore

from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    fake_attempt,
    open_graphiti_system,
    seed_graphiti_authority_fixture,
)


def _row_count(path, table: str, *, where: str = "", params=()) -> int:
    conn = sqlite3.connect(path)
    try:
        suffix = f" WHERE {where}" if where else ""
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}{suffix}", params).fetchone()[0])
    finally:
        conn.close()


def test_extraction_output_and_proposals_precede_adapter_attempt_event(tmp_path) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()

    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )
        retained = system.graphiti.execute_attempt(
            request, proof=extraction_proof()
        )

    conn = sqlite3.connect(state.database)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT ledger_seq,event_id,event_type,aggregate_id "
            "FROM ledger_events WHERE event_type IN(?,?) ORDER BY ledger_seq",
            ("extraction.run.executed", "graphiti.adapter.attempt.executed"),
        ).fetchall()
        assert [str(row["event_type"]) for row in rows] == [
            "extraction.run.executed",
            "graphiti.adapter.attempt.executed",
        ]
        assert int(rows[0]["ledger_seq"]) < int(rows[1]["ledger_seq"])
        assert str(rows[0]["aggregate_id"]) == str(request.extraction_request.run_version_id)
        assert str(rows[1]["aggregate_id"]) == str(request.attempt_id)

        run = conn.execute(
            "SELECT authority_event_id FROM extraction_run_versions "
            "WHERE run_version_id=?",
            (str(request.extraction_request.run_version_id),),
        ).fetchone()
        assert run is not None
        assert str(run["authority_event_id"]) == str(rows[0]["event_id"])
        assert retained.output_id is not None
        assert retained.proposal_set_id is not None
        assert conn.execute(
            "SELECT 1 FROM extraction_outputs WHERE output_id=?",
            (str(retained.output_id),),
        ).fetchone() is not None
        assert conn.execute(
            "SELECT 1 FROM extraction_proposal_sets WHERE proposal_set_id=?",
            (str(retained.proposal_set_id),),
        ).fetchone() is not None
        assert conn.execute(
            "SELECT authority_event_id FROM graphiti_adapter_attempts "
            "WHERE attempt_id=?",
            (str(request.attempt_id),),
        ).fetchone()[0] == str(rows[1]["event_id"])
    finally:
        conn.close()


def test_adapter_metadata_failure_rolls_back_extraction_and_attempt_atomically(
    tmp_path, monkeypatch
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()

    def fail_after_extraction(*_args, **_kwargs):
        raise RuntimeError("injected adapter metadata failure")

    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )
        monkeypatch.setattr(
            _GraphitiAdapterAuthorityStore,
            "_persist_graphiti_attempt_after_extraction",
            fail_after_extraction,
        )
        with pytest.raises(RuntimeError, match="injected adapter metadata failure"):
            system.graphiti.execute_attempt(request, proof=extraction_proof())

    assert _row_count(
        state.database,
        "extraction_runs",
        where="run_id=?",
        params=(str(request.extraction_request.run_id),),
    ) == 0
    assert _row_count(
        state.database,
        "extraction_run_versions",
        where="run_version_id=?",
        params=(str(request.extraction_request.run_version_id),),
    ) == 0
    assert _row_count(state.database, "extraction_outputs") == 0
    assert _row_count(state.database, "extraction_proposal_sets") == 0
    assert _row_count(state.database, "graphiti_adapter_attempts") == 0
    assert _row_count(state.database, "graphiti_workspaces") == 0
    assert not any(workspace_root.glob("*"))
