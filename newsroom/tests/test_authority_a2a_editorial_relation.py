from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from newsroom.relations import EditorialRelationDecisionAction

from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_proof


def test_editorial_relation_commands_retain_exact_authority_event_envelopes(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        decision = system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="a2a-editorial-relation-accept-v1",
            ),
            proof=extraction_proof(),
        )

    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT c.command_type,c.aggregate_type,c.aggregate_id,"
            "c.authentication_context_id,c.authorization_request_digest,"
            "c.authorization_decision_id,c.result_digest,e.event_id,"
            "e.event_type,e.aggregate_version,e.payload_mode,e.payload_digest,"
            "e.security_scope,e.retention_scope,e.trust_scope "
            "FROM authority_commands c JOIN ledger_events e USING(command_id) "
            "WHERE c.command_type IN(?,?) ORDER BY e.ledger_seq",
            (
                "editorial.relation.proposal.record",
                "editorial.relation.decision.record",
            ),
        ).fetchall()

    assert [row["event_id"] for row in rows] == [
        str(proposal.authority_event_id),
        str(decision.authority_event_id),
    ]
    assert [row["event_type"] for row in rows] == [
        "editorial.relation.proposed",
        "editorial.relation.decided",
    ]
    assert [row["aggregate_type"] for row in rows] == [
        "editorial_relation_proposal_version",
        "editorial_relation_decision",
    ]
    assert [row["trust_scope"] for row in rows] == ["PROPOSED", "ADMITTED"]
    for row in rows:
        assert row["aggregate_version"] == 1
        assert row["payload_mode"] == "INLINE"
        assert row["payload_digest"].startswith("sha256:")
        assert row["result_digest"].startswith("sha256:")
        assert row["authentication_context_id"]
        assert row["authorization_request_digest"].startswith("sha256:")
        assert row["authorization_decision_id"]
        assert row["security_scope"] == "authority.relation"
        assert row["retention_scope"] == "authority.audit"
