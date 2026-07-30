from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.relations import (
    EditorialRelationDecisionAction,
    EditorialRelationProjectionAction,
    EditorialRelationRightsDenied,
)

from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    RELATION_PROPOSAL_ID,
    RELATION_SECOND_DECISION_ID,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_proof


def test_invalidation_removes_current_relation_without_deleting_history(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        accepted = system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="relation-lifecycle-accept-v1",
            ),
            proof=extraction_proof(),
        )
        invalidated = system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.INVALIDATE,
                decision_id=RELATION_SECOND_DECISION_ID,
                expected_previous_version=accepted.decision_version,
                previous_decision_id=accepted.decision_id,
                target_assertion_id=RELATION_ASSERTION_ID,
                key="relation-lifecycle-invalidate-v2",
            ),
            proof=extraction_proof(),
        )
        assert invalidated.current_state.value == "INVALIDATED"
        assert system.relations.current_relations(
            limit=10, proof=extraction_proof()
        ) == ()
        with pytest.raises(EditorialRelationRightsDenied):
            system.relations.assertion(
                RELATION_ASSERTION_ID, proof=extraction_proof()
            )
        retained = system.relations.decision(
            RELATION_PROPOSAL_ID, proof=extraction_proof()
        )
        assert retained is not None
        assert retained.decision_id == RELATION_SECOND_DECISION_ID
        events = system.relations.projection_events_after(
            after_ledger_seq=0,
            limit=10,
            proof=extraction_proof(),
        )
        assert [item.action for item in events] == [
            EditorialRelationProjectionAction.UPSERT,
            EditorialRelationProjectionAction.REMOVE,
        ]
        assert events[-1].assertion is None
