from __future__ import annotations

from contextlib import closing
import sqlite3

from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    approval_from_authority,
    fake_attempt,
    open_graphiti_system,
    seed_graphiti_authority_fixture,
)


def test_graphiti_adapter_commands_retain_exact_ordered_authority_envelopes(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        configuration = system.graphiti.register_configuration(
            request.configuration,
            proof=extraction_proof(),
        )
        attempt = system.graphiti.execute_attempt(
            request,
            proof=extraction_proof(),
        )
    approval_request = approval_from_authority(state, attempt)
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        approval = system.graphiti.approve_replay(
            approval_request,
            proof=extraction_proof(),
        )

    with closing(sqlite3.connect(state.database)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT e.ledger_seq,c.command_type,c.aggregate_type,c.aggregate_id,"
            "c.authentication_context_id,c.authorization_request_digest,"
            "c.authorization_decision_id,c.result_digest,e.event_id,e.event_type,"
            "e.aggregate_version,e.payload_mode,e.payload_digest,e.security_scope,"
            "e.retention_scope,e.trust_scope "
            "FROM authority_commands c JOIN ledger_events e USING(command_id) "
            "WHERE c.command_type IN(?,?,?,?) ORDER BY e.ledger_seq",
            (
                "graphiti.adapter.configuration.register",
                "extraction.run.execute",
                "graphiti.adapter.attempt.execute",
                "graphiti.adapter.replay.approve",
            ),
        ).fetchall()

    assert [row["command_type"] for row in rows] == [
        "graphiti.adapter.configuration.register",
        "extraction.run.execute",
        "graphiti.adapter.attempt.execute",
        "graphiti.adapter.replay.approve",
    ]
    assert [row["event_type"] for row in rows] == [
        "graphiti.adapter.configuration.registered",
        "extraction.run.executed",
        "graphiti.adapter.attempt.executed",
        "graphiti.adapter.replay.approved",
    ]
    assert [row["aggregate_type"] for row in rows] == [
        "graphiti_adapter_configuration",
        "extraction_run_version",
        "graphiti_adapter_attempt",
        "graphiti_replay_source",
    ]
    assert rows[0]["event_id"] == str(configuration.authority_event_id)
    assert rows[1]["event_id"]
    assert rows[2]["event_id"] == str(attempt.authority_event_id)
    assert rows[3]["event_id"] == str(approval.authority_event_id)
    assert rows[1]["ledger_seq"] < rows[2]["ledger_seq"]
    assert [row["trust_scope"] for row in rows] == [
        "ADMITTED",
        "PROPOSED",
        "PROPOSED",
        "ADMITTED",
    ]
    for row in rows:
        assert row["aggregate_version"] == 1
        assert row["payload_mode"] == "INLINE"
        assert row["payload_digest"].startswith("sha256:")
        assert row["result_digest"].startswith("sha256:")
        assert row["authentication_context_id"]
        assert row["authorization_request_digest"].startswith("sha256:")
        assert row["authorization_decision_id"]
        assert row["retention_scope"] == "authority.audit"
    assert rows[0]["security_scope"] == "authority.graphiti_adapter"
    assert rows[1]["security_scope"] == "authority.extraction"
    assert rows[2]["security_scope"] == "authority.graphiti_adapter"
    assert rows[3]["security_scope"] == "authority.graphiti_adapter"
