from __future__ import annotations

from pathlib import Path

from newsroom.entities import (
    EntityAliasKind,
    EntityProjectionAction,
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


def test_entity_resolution_emits_one_admitted_projection_event(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        system.entities.admit_mention(
            mention_request(
                state.en_source,
                mention_id=EN_MENTION_ID,
                language="en-GB",
                key="b1-entity-mention-v1",
            ),
            proof=extraction_proof(),
        )
        proposal = system.entities.propose_resolution(
            new_entity_proposal_request(
                state, key="b1-entity-proposal-v1"
            ),
            proof=extraction_proof(),
        )
        assert system.entities.projection_events_after(
            0, limit=100, proof=extraction_proof()
        ) == ()

        system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="b1-entity-decision-v1",
            ),
            proof=extraction_proof(),
        )
        events = system.entities.projection_events_after(
            0, limit=100, proof=extraction_proof()
        )
        preferred = system.entities.preferred(
            ENTITY_ID, proof=extraction_proof()
        )

    assert len(events) == 1
    event = events[0]
    assert event.action is EntityProjectionAction.UPSERT
    assert event.entity_id == ENTITY_ID
    assert event.entity_version_id == ENTITY_VERSION_ID
    assert event.preferred_entity_id == ENTITY_ID
    assert event.trust_scope.value == "ADMITTED"
    assert preferred.entity_id == ENTITY_ID
    assert preferred.current_entity_version_id == ENTITY_VERSION_ID
    assert preferred.preferred_entity_id == ENTITY_ID
