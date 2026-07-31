from __future__ import annotations

from contextlib import closing
import sqlite3

from .increment4e_governed_path_helpers import (
    admit_increment4_graphiti_path,
    seed_increment4_graphiti_path,
)


def test_increment4e_retains_exact_persist_before_admission_command_order(tmp_path) -> None:
    state = seed_increment4_graphiti_path(tmp_path)
    admitted = admit_increment4_graphiti_path(state)

    with closing(sqlite3.connect(state.extraction.database)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT e.ledger_seq,c.command_type,c.command_id,c.aggregate_type,"
            "c.authentication_context_id,c.authorization_request_digest,"
            "c.authorization_decision_id,c.result_digest,e.event_type,"
            "e.aggregate_version,e.payload_digest,e.trust_scope "
            "FROM authority_commands c JOIN ledger_events e USING(command_id) "
            "WHERE c.command_type IN(?,?,?,?,?,?,?,?,?) ORDER BY e.ledger_seq",
            (
                "graphiti.adapter.configuration.register",
                "extraction.run.execute",
                "graphiti.adapter.attempt.execute",
                "graphiti.adapter.replay.approve",
                "entity.mention.admit",
                "entity.resolution.propose",
                "entity.resolution.decide",
                "editorial.relation.proposal.record",
                "editorial.relation.decision.record",
            ),
        ).fetchall()

    command_types = [str(row["command_type"]) for row in rows]
    assert command_types == [
        "graphiti.adapter.configuration.register",
        "extraction.run.execute",
        "graphiti.adapter.attempt.execute",
        "graphiti.adapter.replay.approve",
        "graphiti.adapter.configuration.register",
        "extraction.run.execute",
        "graphiti.adapter.attempt.execute",
        "entity.mention.admit",
        "entity.mention.admit",
        "entity.resolution.propose",
        "entity.resolution.decide",
        "entity.resolution.propose",
        "entity.resolution.decide",
        "editorial.relation.proposal.record",
        "editorial.relation.decision.record",
    ]
    assert [str(row["trust_scope"]) for row in rows] == [
        "ADMITTED",
        "PROPOSED",
        "PROPOSED",
        "ADMITTED",
        "ADMITTED",
        "PROPOSED",
        "PROPOSED",
        "PROPOSED",
        "PROPOSED",
        "PROPOSED",
        "ADMITTED",
        "PROPOSED",
        "ADMITTED",
        "PROPOSED",
        "ADMITTED",
    ]
    assert rows[-1]["aggregate_type"] == "editorial_relation_decision"
    assert rows[-1]["event_type"] == "editorial.relation.decided"
    assert rows[-1]["result_digest"].startswith("sha256:")
    assert admitted.decision.authority_ledger_seq == rows[-1]["ledger_seq"]
    assert len({str(row["command_id"]) for row in rows}) == len(rows)
    for row in rows:
        assert int(row["aggregate_version"]) == 1
        assert str(row["payload_digest"]).startswith("sha256:")
        assert str(row["result_digest"]).startswith("sha256:")
        assert row["authentication_context_id"]
        assert str(row["authorization_request_digest"]).startswith("sha256:")
        assert row["authorization_decision_id"]
