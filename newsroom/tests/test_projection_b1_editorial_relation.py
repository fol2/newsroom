from __future__ import annotations

from pathlib import Path

from newsroom.relations import (
    EditorialRelationDecisionAction,
    EditorialRelationProjectionAction,
)

from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_proof


def test_editorial_relation_projects_only_after_explicit_admission(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        assert system.relations.projection_events_after(
            after_ledger_seq=0,
            limit=100,
            proof=extraction_proof(),
        ) == ()

        system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="projection-b1-editorial-relation-accept-v1",
            ),
            proof=extraction_proof(),
        )
        events = system.relations.projection_events_after(
            after_ledger_seq=0,
            limit=100,
            proof=extraction_proof(),
        )
        current = system.relations.current(
            RELATION_ASSERTION_ID, proof=extraction_proof()
        )

    assert len(events) == 1
    event = events[0]
    assert event.action is EditorialRelationProjectionAction.UPSERT
    assert event.assertion is not None
    assert event.assertion.assertion_id == RELATION_ASSERTION_ID
    assert event.assertion.trust_scope.value == "ADMITTED"
    assert current.assertion.assertion_id == RELATION_ASSERTION_ID
