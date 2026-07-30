from __future__ import annotations

from contextlib import closing
from pathlib import Path
import re
import sqlite3

import pytest

from newsroom.authority.persistence import (
    AuthorityPersistenceError,
    AuthoritySchemaError,
)
from newsroom.relations import (
    EditorialRelationContractError,
    EditorialRelationDecisionAction,
)

from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    RELATION_PROPOSAL_ID,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_proof


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    conn.execute(f'DROP TRIGGER "{name}"')
    return str(row[0])


def _expect_reopen_failure(state, *patterns: str) -> None:
    with pytest.raises(
        (
            AuthorityPersistenceError,
            AuthoritySchemaError,
            EditorialRelationContractError,
        )
    ) as caught:
        open_relation_system(state)
    messages: list[str] = []
    current: BaseException | None = caught.value
    while current is not None:
        messages.append(str(current))
        current = current.__cause__
    assert any(
        re.search(pattern, message)
        for pattern in patterns
        for message in messages
    ), messages


def _seed_admitted_relation(tmp_path: Path):
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
                key="relation-integrity-accept-v1",
            ),
            proof=extraction_proof(),
        )
    return state, proposal, decision


def test_relation_authority_history_and_evidence_rows_are_immutable(
    tmp_path: Path,
) -> None:
    state, _proposal, _decision = _seed_admitted_relation(tmp_path)
    cases = (
        (
            "editorial_relation_proposals",
            "UPDATE editorial_relation_proposals SET predicate=predicate",
        ),
        (
            "editorial_relation_proposal_versions",
            "UPDATE editorial_relation_proposal_versions SET statement=statement",
        ),
        (
            "editorial_relation_evidence_items",
            "UPDATE editorial_relation_evidence_items "
            "SET canonical_digest=canonical_digest",
        ),
        (
            "editorial_relation_extraction_evidence",
            "UPDATE editorial_relation_extraction_evidence "
            "SET start_byte=start_byte",
        ),
        (
            "editorial_relation_resolution_dependencies",
            "UPDATE editorial_relation_resolution_dependencies "
            "SET dependency_id=dependency_id",
        ),
        (
            "editorial_relation_decisions",
            "UPDATE editorial_relation_decisions SET reason_code=reason_code",
        ),
        (
            "editorial_relation_assertions",
            "UPDATE editorial_relation_assertions SET statement=statement",
        ),
        (
            "editorial_relation_projection_events",
            "UPDATE editorial_relation_projection_events SET action=action",
        ),
    )
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        for table, statement in cases:
            trigger = f"immutable_{table}_update"
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='trigger' AND name=?",
                (trigger,),
            ).fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError, match=f"immutable {table}"):
                conn.execute(statement)


def test_reopen_rejects_wrong_decision_policy_after_trigger_bypass(
    tmp_path: Path,
) -> None:
    state, _proposal, _decision = _seed_admitted_relation(tmp_path)
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        trigger = _disable_trigger(
            conn, "immutable_editorial_relation_decisions_update"
        )
        conn.execute(
            "UPDATE editorial_relation_decisions "
            "SET decision_policy_version=? WHERE decision_id=?",
            ("editorial-relation-admission-policy-v2", str(RELATION_ACCEPT_DECISION_ID)),
        )
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "unapproved policy version",
        "policy version",
        "decision columns differ from request",
    )


def test_reopen_rejects_missing_evidence_lineage(tmp_path: Path) -> None:
    state, proposal, _decision = _seed_admitted_relation(tmp_path)
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        extraction_trigger = _disable_trigger(
            conn, "immutable_editorial_relation_extraction_evidence_delete"
        )
        item_trigger = _disable_trigger(
            conn, "immutable_editorial_relation_evidence_items_delete"
        )
        conn.execute(
            "DELETE FROM editorial_relation_extraction_evidence "
            "WHERE proposal_version_id=?",
            (str(proposal.proposal_version_id),),
        )
        conn.execute(
            "DELETE FROM editorial_relation_evidence_items "
            "WHERE proposal_version_id=?",
            (str(proposal.proposal_version_id),),
        )
        conn.execute(extraction_trigger)
        conn.execute(item_trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "evidence",
        "relation proposal version",
        "relation evidence",
    )


def test_reopen_rejects_missing_resolution_dependency_lineage(
    tmp_path: Path,
) -> None:
    state, proposal, _decision = _seed_admitted_relation(tmp_path)
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        trigger = _disable_trigger(
            conn, "immutable_editorial_relation_resolution_dependencies_delete"
        )
        conn.execute(
            "DELETE FROM editorial_relation_resolution_dependencies "
            "WHERE proposal_version_id=?",
            (str(proposal.proposal_version_id),),
        )
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "dependency",
        "dependencies differ from request",
        "relation proposal version",
        "request differs",
    )


@pytest.mark.parametrize(
    ("trigger_name", "statement", "pattern"),
    (
        (
            "editorial_relation_proposal_head_update_guard",
            "UPDATE editorial_relation_proposal_heads "
            "SET current_version_number=current_version_number+1",
            "proposal head is inconsistent|foreign-key|foreign key",
        ),
        (
            "editorial_relation_decision_head_update_guard",
            "UPDATE editorial_relation_decision_heads SET current_state='REJECTED'",
            "decision head is inconsistent",
        ),
        (
            "editorial_relation_assertion_head_update_guard",
            "UPDATE editorial_relation_assertion_heads SET lifecycle='REVOKED'",
            "assertion head is inconsistent|projection coverage",
        ),
    ),
)
def test_reopen_rejects_divergent_current_heads(
    tmp_path: Path,
    trigger_name: str,
    statement: str,
    pattern: str,
) -> None:
    state, _proposal, _decision = _seed_admitted_relation(tmp_path)
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        trigger = _disable_trigger(conn, trigger_name)
        conn.execute(statement)
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(state, pattern)


def test_reopen_rejects_assertion_canonical_tamper(tmp_path: Path) -> None:
    state, _proposal, _decision = _seed_admitted_relation(tmp_path)
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        trigger = _disable_trigger(
            conn, "immutable_editorial_relation_assertions_update"
        )
        conn.execute(
            "UPDATE editorial_relation_assertions SET canonical_digest=? "
            "WHERE assertion_id=?",
            ("sha256:" + "0" * 64, str(RELATION_ASSERTION_ID)),
        )
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "assertion differs from canonical columns",
        "canonical",
    )


def test_reopen_rejects_missing_projection_event_coverage(tmp_path: Path) -> None:
    state, _proposal, _decision = _seed_admitted_relation(tmp_path)
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        trigger = _disable_trigger(
            conn, "immutable_editorial_relation_projection_events_delete"
        )
        conn.execute(
            "DELETE FROM editorial_relation_projection_events "
            "WHERE assertion_id=?",
            (str(RELATION_ASSERTION_ID),),
        )
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "projection event",
        "projection coverage",
        "assertion head",
    )


def test_reopen_rejects_supersession_canonical_tamper(tmp_path: Path) -> None:
    from dataclasses import replace

    from newsroom.relations import EditorialRelationTemporalScope

    from .editorial_relation_4c_helpers import (
        RELATION_SECOND_ACCEPT_DECISION_ID,
        RELATION_SECOND_ASSERTION_ID,
        RELATION_SECOND_PROPOSAL_ID,
        RELATION_SECOND_PROPOSAL_V1_ID,
        RELATION_SUPERSEDE_DECISION_ID,
        RELATION_SUPERSESSION_ID,
    )
    from .source_3a_helpers import SOURCE_NOW

    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        first_proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        first_decision = system.relations.decide(
            relation_decision_request(
                first_proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="relation-integrity-supersede-first-accept-v1",
            ),
            proof=extraction_proof(),
        )
        second_proposal = system.relations.propose(
            replace(
                relation_proposal_request(state),
                proposal_id=RELATION_SECOND_PROPOSAL_ID,
                proposal_version_id=RELATION_SECOND_PROPOSAL_V1_ID,
                temporal_scope=EditorialRelationTemporalScope(
                    valid_from=SOURCE_NOW,
                    valid_until=None,
                    observed_at=SOURCE_NOW,
                ),
                statement="A later retained assertion supersedes the first.",
                idempotency_key="relation-integrity-supersede-second-proposal-v1",
            ),
            proof=extraction_proof(),
        )
        system.relations.decide(
            relation_decision_request(
                second_proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_SECOND_ACCEPT_DECISION_ID,
                assertion_id=RELATION_SECOND_ASSERTION_ID,
                key="relation-integrity-supersede-second-accept-v1",
            ),
            proof=extraction_proof(),
        )
        system.relations.decide(
            relation_decision_request(
                first_proposal,
                action=EditorialRelationDecisionAction.SUPERSEDE,
                decision_id=RELATION_SUPERSEDE_DECISION_ID,
                expected_previous_version=first_decision.decision_version,
                previous_decision_id=first_decision.decision_id,
                target_assertion_id=RELATION_ASSERTION_ID,
                successor_assertion_id=RELATION_SECOND_ASSERTION_ID,
                supersession_id=RELATION_SUPERSESSION_ID,
                key="relation-integrity-supersede-first-v2",
            ),
            proof=extraction_proof(),
        )

    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        trigger = _disable_trigger(
            conn, "immutable_editorial_relation_supersessions_update"
        )
        conn.execute(
            "UPDATE editorial_relation_supersessions SET canonical_digest=? "
            "WHERE supersession_id=?",
            ("sha256:" + "0" * 64, str(RELATION_SUPERSESSION_ID)),
        )
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "supersession",
        "canonical",
    )
