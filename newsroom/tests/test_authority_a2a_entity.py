from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path

from newsroom.entities import (
    EntityAliasKind,
    EntityResolutionDecisionAction,
)

from .entity_4b_helpers import (
    EN_ALIAS_ID,
    EN_MENTION_ID,
    ENTITY_ID,
    ENTITY_VERSION_ID,
    decision_request,
    mention_request,
    new_entity_proposal_request,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof


def test_entity_commands_retain_exact_authority_event_envelopes(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        mention = system.entities.admit_mention(
            mention_request(
                state.en_source,
                mention_id=EN_MENTION_ID,
                language="en-GB",
                key="a2a-entity-mention-v1",
            ),
            proof=extraction_proof(),
        )
        proposal = system.entities.propose_resolution(
            new_entity_proposal_request(
                state, key="a2a-entity-proposal-v1"
            ),
            proof=extraction_proof(),
        )
        decision = system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="a2a-entity-decision-v1",
            ),
            proof=extraction_proof(),
        )

    with closing(sqlite3.connect(state.extraction.database)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT c.command_type,c.aggregate_type,c.aggregate_id,"
            "c.authentication_context_id,c.authorization_request_digest,"
            "c.authorization_decision_id,c.result_digest,e.event_id,"
            "e.event_type,e.aggregate_version,e.payload_mode,e.payload_digest,"
            "e.security_scope,e.retention_scope,e.trust_scope "
            "FROM authority_commands c JOIN ledger_events e USING(command_id) "
            "WHERE c.command_type IN(?,?,?) ORDER BY e.ledger_seq",
            (
                "entity.mention.admit",
                "entity.resolution.propose",
                "entity.resolution.decide",
            ),
        ).fetchall()

    assert [row["event_id"] for row in rows] == [
        str(mention.authority_event_id),
        str(proposal.authority_event_id),
        str(decision.authority_event_id),
    ]
    assert [row["event_type"] for row in rows] == [
        "entity.mention.admitted",
        "entity.resolution.proposed",
        "entity.resolution.decided",
    ]
    assert [row["aggregate_type"] for row in rows] == [
        "entity_mention",
        "entity_resolution_proposal_version",
        "entity_resolution_decision",
    ]
    assert [row["trust_scope"] for row in rows] == [
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
        assert row["security_scope"] == "authority.entity"
        assert row["retention_scope"] == "authority.audit"
