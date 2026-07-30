from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.relations import (
    EditorialRelationDecisionAction,
    EditorialRelationDecisionConflict,
    EditorialRelationProjectionAction,
)

from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    RELATION_HOLD_DECISION_ID,
    RELATION_PROPOSAL_ID,
    competing_unresolved_dependency,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_proof


def test_relation_proposal_persists_replays_and_remains_proposal_scoped(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    request = relation_proposal_request(state)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(request, proof=extraction_proof())
        replay = system.relations.propose(request, proof=extraction_proof())
        assert replay.replayed is True
        assert replay.canonical_digest == proposal.canonical_digest
        assert system.relations.proposal(
            RELATION_PROPOSAL_ID, proof=extraction_proof()
        ).canonical_digest == proposal.canonical_digest
        assert system.relations.decision(
            RELATION_PROPOSAL_ID, proof=extraction_proof()
        ) is None
        assert system.relations.current_relations(
            limit=10, proof=extraction_proof()
        ) == ()
        assert system.relations.projection_events_after(
            after_ledger_seq=0,
            limit=10,
            proof=extraction_proof(),
        ) == ()


def test_explicit_accept_creates_one_admitted_assertion_and_projection_event(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        decision_request_value = relation_decision_request(
            proposal,
            action=EditorialRelationDecisionAction.ACCEPT,
            decision_id=RELATION_ACCEPT_DECISION_ID,
            assertion_id=RELATION_ASSERTION_ID,
            key="relation-accept-v1",
        )
        decision = system.relations.decide(
            decision_request_value, proof=extraction_proof()
        )
        replay = system.relations.decide(
            decision_request_value, proof=extraction_proof()
        )
        assert replay.replayed is True
        assert decision.current_state.value == "ADMITTED"
        assertion = system.relations.assertion(
            RELATION_ASSERTION_ID, proof=extraction_proof()
        )
        current = system.relations.current(
            RELATION_ASSERTION_ID, proof=extraction_proof()
        )
        assert assertion.admission_decision_id == RELATION_ACCEPT_DECISION_ID
        assert current.assertion.canonical_digest == assertion.canonical_digest
        assert [item.assertion.assertion_id for item in system.relations.current_relations(
            limit=10, proof=extraction_proof()
        )] == [RELATION_ASSERTION_ID]
        events = system.relations.projection_events_after(
            after_ledger_seq=0,
            limit=10,
            proof=extraction_proof(),
        )
        assert len(events) == 1
        assert events[0].action is EditorialRelationProjectionAction.UPSERT
        assert events[0].assertion is not None
        assert events[0].assertion.canonical_digest == assertion.canonical_digest

    with open_relation_system(state) as reopened:
        assert reopened.relations.current(
            RELATION_ASSERTION_ID, proof=extraction_proof()
        ).assertion.canonical_digest == assertion.canonical_digest


def test_material_unresolved_identity_blocks_accept_and_preserves_hold(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    unresolved_dependency_id = competing_unresolved_dependency(state)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(
                state, dependency_ids=(unresolved_dependency_id,)
            ),
            proof=extraction_proof(),
        )
        with pytest.raises(
            EditorialRelationDecisionConflict, match="material entity identity"
        ):
            system.relations.decide(
                relation_decision_request(
                    proposal,
                    action=EditorialRelationDecisionAction.ACCEPT,
                    decision_id=RELATION_ACCEPT_DECISION_ID,
                    assertion_id=RELATION_ASSERTION_ID,
                    key="relation-premature-accept-v1",
                ),
                proof=extraction_proof(),
            )
        hold = system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.HOLD,
                decision_id=RELATION_HOLD_DECISION_ID,
                key="relation-hold-v1",
            ),
            proof=extraction_proof(),
        )
        assert hold.current_state.value == "HELD"
        assert system.relations.current_relations(
            limit=10, proof=extraction_proof()
        ) == ()
