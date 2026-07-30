from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.entities import (
    EntityAliasKind,
    EntityDecisionConflict,
    EntityMentionId,
    EntityResolutionDecisionAction,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersionId,
    EntityResolutionState,
    EntityStaleDecision,
)

from .entity_4b_helpers import (
    EN_ALIAS_ID,
    EN_MENTION_ID,
    ENTITY_ID,
    ENTITY_VERSION_ID,
    ZH_ALIAS_ID,
    ZH_EQ_PROPOSAL_ID,
    ZH_EQ_PROPOSAL_V1_ID,
    ZH_MENTION_ID,
    decision_request,
    mention_request,
    new_entity_proposal_request,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof


def test_mentions_are_exact_bilingual_proposals_and_replay_is_idempotent(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        en_request = mention_request(
            state.en_source,
            mention_id=EN_MENTION_ID,
            language="en-GB",
            key="mention-en-v1",
        )
        en = system.entities.admit_mention(en_request, proof=extraction_proof())
        replay = system.entities.admit_mention(en_request, proof=extraction_proof())
        zh = system.entities.admit_mention(
            mention_request(
                state.zh_source,
                mention_id=ZH_MENTION_ID,
                language="zh-HK",
                key="mention-zh-v1",
            ),
            proof=extraction_proof(),
        )

        assert en.mention_text == "Hong Kong Transport Department"
        assert zh.mention_text == "香港運輸署"
        assert replay.replayed is True
        assert replay.canonical_digest == en.canonical_digest
        assert system.entities.mention(
            EN_MENTION_ID, proof=extraction_proof()
        ).canonical_digest == en.canonical_digest
    finally:
        system.close()


def test_mention_rejects_stale_source_and_wrong_normalisation_without_rows(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        request = mention_request(
            state.en_source,
            mention_id=EN_MENTION_ID,
            language="en-GB",
            key="mention-en-stale",
        )
        with pytest.raises(EntityStaleDecision):
            system.entities.admit_mention(
                replace(request, expected_source_proposal_digest="sha256:" + "0" * 64),
                proof=extraction_proof(),
            )
        with pytest.raises(Exception, match="normalized"):
            system.entities.admit_mention(
                replace(
                    request,
                    normalized_text="different",
                    idempotency_key="mention-en-wrong-normalized",
                ),
                proof=extraction_proof(),
            )
        with pytest.raises(KeyError):
            system.entities.mention(EN_MENTION_ID, proof=extraction_proof())
    finally:
        system.close()


def test_hold_then_accept_new_entity_preserves_history_and_admits_alias(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        system.entities.admit_mention(
            mention_request(
                state.en_source,
                mention_id=EN_MENTION_ID,
                language="en-GB",
                key="mention-en-v1",
            ),
            proof=extraction_proof(),
        )
        proposal = system.entities.propose_resolution(
            new_entity_proposal_request(state), proof=extraction_proof()
        )
        hold = system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.HOLD,
                key="decision-en-hold-v1",
            ),
            proof=extraction_proof(),
        )
        guard = system.entities.admission_guard(
            proposal.proposal_id, proof=extraction_proof()
        )
        assert hold.current_state is EntityResolutionState.HELD
        assert guard.materially_unresolved is True

        accepted = system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                expected_decision_version=1,
                previous=hold.decision_id,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="decision-en-accept-v2",
            ),
            proof=extraction_proof(),
        )
        entity = system.entities.entity(ENTITY_ID, proof=extraction_proof())
        version = system.entities.entity_version(
            ENTITY_VERSION_ID, proof=extraction_proof()
        )
        aliases = system.entities.aliases(
            ENTITY_ID, limit=10, proof=extraction_proof()
        )
        preferred = system.entities.preferred(
            ENTITY_ID, proof=extraction_proof()
        )
        final_guard = system.entities.admission_guard(
            proposal.proposal_id, proof=extraction_proof()
        )

        assert accepted.current_state is EntityResolutionState.ACCEPTED
        assert entity.initial_version_id == ENTITY_VERSION_ID
        assert version.entity_id == ENTITY_ID
        assert [item.alias_text for item in aliases] == [
            "Hong Kong Transport Department"
        ]
        assert preferred.preferred_entity_id == ENTITY_ID
        assert final_guard.materially_unresolved is False
        assert system.entities.decision(
            proposal.proposal_id, proof=extraction_proof()
        ).decision_id == accepted.decision_id
    finally:
        system.close()


def test_bilingual_equivalence_requires_object_identity_before_acceptance(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        for source, mention_id, language, key in (
            (state.en_source, EN_MENTION_ID, "en-GB", "mention-en-v1"),
            (state.zh_source, ZH_MENTION_ID, "zh-HK", "mention-zh-v1"),
        ):
            system.entities.admit_mention(
                mention_request(
                    source,
                    mention_id=mention_id,
                    language=language,
                    key=key,
                ),
                proof=extraction_proof(),
            )

        eq = system.entities.propose_resolution(
            EntityResolutionProposalRequest(
                proposal_id=ZH_EQ_PROPOSAL_ID,
                proposal_version_id=ZH_EQ_PROPOSAL_V1_ID,
                version_number=1,
                expected_previous_version_id=None,
                source_proposal_id=state.equivalence_source.proposal_id,
                expected_source_proposal_digest=state.equivalence_source.canonical_digest,
                kind=EntityResolutionProposalKind.MENTION_EQUIVALENCE,
                subject_mention_id=ZH_MENTION_ID,
                object_mention_id=EN_MENTION_ID,
                candidate_entity_id=None,
                candidate_entity_version_id=None,
                confidence_basis_points=8_500,
                uncertainty_codes=("REQUIRES_EXPLICIT_RESOLUTION",),
                basis_codes=("BILINGUAL_FIXTURE_ALIAS",),
                idempotency_key="equivalence-zh-en-v1",
            ),
            proof=extraction_proof(),
        )
        with pytest.raises(EntityDecisionConflict, match="object mention"):
            system.entities.decide_resolution(
                decision_request(
                    eq,
                    action=EntityResolutionDecisionAction.ACCEPT,
                    entity_id=ENTITY_ID,
                    version_id=ENTITY_VERSION_ID,
                    alias_id=ZH_ALIAS_ID,
                    alias_kind=EntityAliasKind.TRANSLATION,
                    key="equivalence-premature-accept",
                ),
                proof=extraction_proof(),
            )

        en_proposal = system.entities.propose_resolution(
            new_entity_proposal_request(state), proof=extraction_proof()
        )
        system.entities.decide_resolution(
            decision_request(
                en_proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="decision-en-accept-v1",
            ),
            proof=extraction_proof(),
        )
        accepted = system.entities.decide_resolution(
            decision_request(
                eq,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=ZH_ALIAS_ID,
                alias_kind=EntityAliasKind.TRANSLATION,
                key="equivalence-accept-v1",
            ),
            proof=extraction_proof(),
        )
        aliases = system.entities.aliases(
            ENTITY_ID, limit=10, proof=extraction_proof()
        )
        assert accepted.accepted_entity_id == ENTITY_ID
        assert {item.language for item in aliases} == {"en-GB", "zh-HK"}
        assert {item.alias_text for item in aliases} == {
            "Hong Kong Transport Department",
            "香港運輸署",
        }
    finally:
        system.close()


def test_reject_is_terminal_and_creates_no_admitted_entity(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        system.entities.admit_mention(
            mention_request(
                state.en_source,
                mention_id=EN_MENTION_ID,
                language="en-GB",
                key="mention-en-v1",
            ),
            proof=extraction_proof(),
        )
        proposal = system.entities.propose_resolution(
            new_entity_proposal_request(state), proof=extraction_proof()
        )
        rejected = system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.REJECT,
                key="decision-en-reject-v1",
            ),
            proof=extraction_proof(),
        )
        assert rejected.current_state is EntityResolutionState.REJECTED
        with pytest.raises(Exception):
            system.entities.decide_resolution(
                decision_request(
                    proposal,
                    action=EntityResolutionDecisionAction.HOLD,
                    expected_decision_version=1,
                    previous=rejected.decision_id,
                    key="decision-after-reject",
                ),
                proof=extraction_proof(),
            )
        with pytest.raises(KeyError):
            system.entities.entity(ENTITY_ID, proof=extraction_proof())
    finally:
        system.close()
