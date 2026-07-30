from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority.types import UtcTimestamp
from newsroom.entities import EntityAliasKind, EntityResolutionDecisionAction

from newsroom.relations import (
    EDITORIAL_PREDICATE_REGISTRY_V1,
    EditorialPredicateCode,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionConflict,
    EditorialRelationProjectionAction,
    EditorialRelationTemporalScope,
    SourceRevisionRelationEndpoint,
)
from newsroom.relations.editorial_policy import (
    merge_editorial_relation_authority_registries,
)
from newsroom.sources import open_governed_source_registry_authority_system

from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    RELATION_HOLD_DECISION_ID,
    RELATION_PROPOSAL_ID,
    RELATION_SECOND_DECISION_ID,
    ZH_ENTITY_ID,
    ZH_ENTITY_VERSION_ID,
    ZH_PRIMARY_ALIAS_ID,
    ZH_RELATION_DEPENDENCY_ID,
    competing_unresolved_dependency,
    open_entity_system_after_relation,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .entity_4b_helpers import decision_request as entity_decision_request
from .extraction_4a_helpers import extraction_proof
from .source_3a_helpers import (
    ITEM_ID,
    REVISION_1_ID,
    REVISION_2_ID,
    SOURCE_NOW,
    authenticator as source_authenticator,
    authorizer as source_authorizer,
    proof as source_proof,
    read_policy as source_read_policy,
    revision_request,
)


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


def test_held_relation_can_be_admitted_after_material_identity_is_resolved(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path, resolve_secondary=False)
    commands, schemas = merge_editorial_relation_authority_registries(
        command_registry=state.entity.extraction.commands,
        payload_schemas=state.entity.extraction.schemas,
    )
    with open_governed_source_registry_authority_system(
        path=state.entity.extraction.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=source_authenticator(),
        authorizer=source_authorizer(),
        read_policy=source_read_policy(),
        clock=lambda: SOURCE_NOW,
    ) as sources:
        sources.sources.record_revision(
            revision_request(
                revision_id=REVISION_2_ID,
                prior_revision_id=REVISION_1_ID,
                state_character="e",
                key="relation-held-second-revision-v1",
            ),
            proof=source_proof(),
        )

    predicate = EditorialPredicateCode.DEVELOPMENT_OF
    contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(predicate)
    request = replace(
        relation_proposal_request(
            state,
            dependency_ids=(ZH_RELATION_DEPENDENCY_ID,),
        ),
        predicate=predicate,
        predicate_contract_digest=contract.digest,
        subject=SourceRevisionRelationEndpoint(
            source_item_id=ITEM_ID,
            source_revision_id=REVISION_1_ID,
        ),
        object=SourceRevisionRelationEndpoint(
            source_item_id=ITEM_ID,
            source_revision_id=REVISION_2_ID,
        ),
        temporal_scope=EditorialRelationTemporalScope(
            valid_from=SOURCE_NOW,
            valid_until=UtcTimestamp.parse("2042-03-13T10:00:00.000000Z"),
            observed_at=SOURCE_NOW,
        ),
        statement=(
            "The later retained source revision develops the earlier retained "
            "revision."
        ),
        idempotency_key="relation-held-later-resolved-proposal-v1",
    )

    with open_relation_system(state) as relations:
        proposal = relations.relations.propose(
            request, proof=extraction_proof()
        )
        with pytest.raises(
            EditorialRelationDecisionConflict,
            match="material entity identity",
        ):
            relations.relations.decide(
                relation_decision_request(
                    proposal,
                    action=EditorialRelationDecisionAction.ACCEPT,
                    decision_id=RELATION_ACCEPT_DECISION_ID,
                    assertion_id=RELATION_ASSERTION_ID,
                    key="relation-held-premature-accept-v1",
                ),
                proof=extraction_proof(),
            )
        held = relations.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.HOLD,
                decision_id=RELATION_HOLD_DECISION_ID,
                key="relation-held-unresolved-v1",
            ),
            proof=extraction_proof(),
        )
        assert held.current_state.value == "HELD"
        assert held.decision_version == 1

    with open_entity_system_after_relation(state) as entities:
        resolved = entities.entities.decide_resolution(
            entity_decision_request(
                state.zh_resolution_proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ZH_ENTITY_ID,
                version_id=ZH_ENTITY_VERSION_ID,
                alias_id=ZH_PRIMARY_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="relation-held-later-identity-accept-v1",
            ),
            proof=extraction_proof(),
        )
        assert resolved.action is EntityResolutionDecisionAction.ACCEPT

    with open_relation_system(state) as relations:
        admitted = relations.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_SECOND_DECISION_ID,
                expected_previous_version=1,
                previous_decision_id=RELATION_HOLD_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="relation-held-later-admit-v1",
            ),
            proof=extraction_proof(),
        )
        assert admitted.current_state.value == "ADMITTED"
        assert admitted.decision_version == 2
        assert relations.relations.current(
            RELATION_ASSERTION_ID, proof=extraction_proof()
        ).assertion.admission_decision_id == RELATION_SECOND_DECISION_ID

    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        assert conn.execute(
            "SELECT action,decision_version FROM editorial_relation_decisions "
            "WHERE proposal_id=? ORDER BY decision_version",
            (str(proposal.proposal_id),),
        ).fetchall() == [("HOLD", 1), ("ACCEPT", 2)]
