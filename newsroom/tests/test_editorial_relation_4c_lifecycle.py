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


def test_revocation_removes_current_relation_and_retains_decision_history(
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
                key="relation-lifecycle-revoke-accept-v1",
            ),
            proof=extraction_proof(),
        )
        revoked = system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.REVOKE,
                decision_id=RELATION_SECOND_DECISION_ID,
                expected_previous_version=accepted.decision_version,
                previous_decision_id=accepted.decision_id,
                target_assertion_id=RELATION_ASSERTION_ID,
                key="relation-lifecycle-revoke-v2",
            ),
            proof=extraction_proof(),
        )
        assert revoked.current_state.value == "REVOKED"
        assert system.relations.current_relations(
            limit=10, proof=extraction_proof()
        ) == ()
        with pytest.raises(EditorialRelationRightsDenied):
            system.relations.current(
                RELATION_ASSERTION_ID, proof=extraction_proof()
            )
        assert system.relations.decision(
            proposal.proposal_id, proof=extraction_proof()
        ).decision_id == RELATION_SECOND_DECISION_ID
        events = system.relations.projection_events_after(
            after_ledger_seq=0,
            limit=10,
            proof=extraction_proof(),
        )
        assert [item.lifecycle.value for item in events] == ["ACTIVE", "REVOKED"]


def test_supersession_removes_predecessor_and_preserves_successor(
    tmp_path: Path,
) -> None:
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
                key="relation-supersede-first-accept-v1",
            ),
            proof=extraction_proof(),
        )
        second_request = replace(
            relation_proposal_request(state),
            proposal_id=RELATION_SECOND_PROPOSAL_ID,
            proposal_version_id=RELATION_SECOND_PROPOSAL_V1_ID,
            temporal_scope=EditorialRelationTemporalScope(
                valid_from=SOURCE_NOW,
                valid_until=None,
                observed_at=SOURCE_NOW,
            ),
            statement=(
                "A later governed interval supersedes the earlier relation assertion."
            ),
            idempotency_key="relation-supersede-second-proposal-v1",
        )
        second_proposal = system.relations.propose(
            second_request, proof=extraction_proof()
        )
        system.relations.decide(
            relation_decision_request(
                second_proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_SECOND_ACCEPT_DECISION_ID,
                assertion_id=RELATION_SECOND_ASSERTION_ID,
                key="relation-supersede-second-accept-v1",
            ),
            proof=extraction_proof(),
        )
        superseded = system.relations.decide(
            relation_decision_request(
                first_proposal,
                action=EditorialRelationDecisionAction.SUPERSEDE,
                decision_id=RELATION_SUPERSEDE_DECISION_ID,
                expected_previous_version=first_decision.decision_version,
                previous_decision_id=first_decision.decision_id,
                target_assertion_id=RELATION_ASSERTION_ID,
                successor_assertion_id=RELATION_SECOND_ASSERTION_ID,
                supersession_id=RELATION_SUPERSESSION_ID,
                key="relation-supersede-first-v2",
            ),
            proof=extraction_proof(),
        )
        assert superseded.current_state.value == "SUPERSEDED"
        with pytest.raises(EditorialRelationRightsDenied):
            system.relations.assertion(
                RELATION_ASSERTION_ID, proof=extraction_proof()
            )
        assert system.relations.current(
            RELATION_SECOND_ASSERTION_ID, proof=extraction_proof()
        ).assertion.assertion_id == RELATION_SECOND_ASSERTION_ID
        current = system.relations.current_relations(
            limit=10, proof=extraction_proof()
        )
        assert [item.assertion.assertion_id for item in current] == [
            RELATION_SECOND_ASSERTION_ID
        ]
        events = system.relations.projection_events_after(
            after_ledger_seq=0,
            limit=10,
            proof=extraction_proof(),
        )
        assert [item.action for item in events] == [
            EditorialRelationProjectionAction.UPSERT,
            EditorialRelationProjectionAction.UPSERT,
            EditorialRelationProjectionAction.REMOVE,
        ]
        assert events[-1].lifecycle.value == "SUPERSEDED"

    with open_relation_system(state) as reopened:
        assert reopened.relations.current(
            RELATION_SECOND_ASSERTION_ID, proof=extraction_proof()
        ).assertion.assertion_id == RELATION_SECOND_ASSERTION_ID
