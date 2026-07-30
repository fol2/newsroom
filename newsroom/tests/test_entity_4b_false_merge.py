from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.entities import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityKind,
    EntityMentionId,
    EntityResolutionDecisionAction,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersionId,
    EntityStateError,
)

from .entity_4b_helpers import (
    decision_request,
    mention_request,
    open_entity_system,
    seed_homonym_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof


def _id(cls, suffix: int):
    return cls.parse(f"00000000-0000-4000-8000-{suffix:012d}")


EN_TRANSIT_MENTION_ID = _id(EntityMentionId, 4701)
EN_ASSOCIATION_MENTION_ID = _id(EntityMentionId, 4702)
ZH_TRANSIT_MENTION_ID = _id(EntityMentionId, 4703)
ZH_ASSOCIATION_MENTION_ID = _id(EntityMentionId, 4704)

EN_TRANSIT_PROPOSAL_ID = _id(EntityResolutionProposalId, 4711)
EN_TRANSIT_PROPOSAL_VERSION_ID = _id(EntityResolutionProposalVersionId, 4712)
EN_ASSOCIATION_PROPOSAL_ID = _id(EntityResolutionProposalId, 4713)
EN_ASSOCIATION_PROPOSAL_VERSION_ID = _id(
    EntityResolutionProposalVersionId, 4714
)
ZH_TRANSIT_EQ_PROPOSAL_ID = _id(EntityResolutionProposalId, 4721)
ZH_TRANSIT_EQ_PROPOSAL_VERSION_ID = _id(
    EntityResolutionProposalVersionId, 4722
)
ZH_ASSOCIATION_EQ_PROPOSAL_ID = _id(EntityResolutionProposalId, 4723)
ZH_ASSOCIATION_EQ_PROPOSAL_VERSION_ID = _id(
    EntityResolutionProposalVersionId, 4724
)
CROSS_CONTEXT_EQ_PROPOSAL_ID = _id(EntityResolutionProposalId, 4725)
CROSS_CONTEXT_EQ_PROPOSAL_VERSION_ID = _id(
    EntityResolutionProposalVersionId, 4726
)

TRANSIT_ENTITY_ID = _id(CanonicalEntityId, 4731)
TRANSIT_ENTITY_VERSION_ID = _id(CanonicalEntityVersionId, 4732)
TRANSIT_EN_ALIAS_ID = _id(EntityAliasId, 4733)
TRANSIT_ZH_ALIAS_ID = _id(EntityAliasId, 4734)
ASSOCIATION_ENTITY_ID = _id(CanonicalEntityId, 4741)
ASSOCIATION_ENTITY_VERSION_ID = _id(CanonicalEntityVersionId, 4742)
ASSOCIATION_EN_ALIAS_ID = _id(EntityAliasId, 4743)
ASSOCIATION_ZH_ALIAS_ID = _id(EntityAliasId, 4744)


def _new_entity_proposal(
    source,
    *,
    mention_id: EntityMentionId,
    proposal_id: EntityResolutionProposalId,
    proposal_version_id: EntityResolutionProposalVersionId,
    key: str,
) -> EntityResolutionProposalRequest:
    return EntityResolutionProposalRequest(
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        version_number=1,
        expected_previous_version_id=None,
        source_proposal_id=source.proposal_id,
        expected_source_proposal_digest=source.canonical_digest,
        kind=EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY,
        subject_mention_id=mention_id,
        object_mention_id=None,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=9_600,
        uncertainty_codes=("SAME_NAME_DISTINCT_CONTEXT",),
        basis_codes=("EXACT_SOURCE_MENTION",),
        idempotency_key=key,
    )


def _equivalence_proposal(
    source,
    *,
    subject_mention_id: EntityMentionId,
    object_mention_id: EntityMentionId,
    proposal_id: EntityResolutionProposalId,
    proposal_version_id: EntityResolutionProposalVersionId,
    key: str,
) -> EntityResolutionProposalRequest:
    return EntityResolutionProposalRequest(
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        version_number=1,
        expected_previous_version_id=None,
        source_proposal_id=source.proposal_id,
        expected_source_proposal_digest=source.canonical_digest,
        kind=EntityResolutionProposalKind.MENTION_EQUIVALENCE,
        subject_mention_id=subject_mention_id,
        object_mention_id=object_mention_id,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=8_000,
        uncertainty_codes=(
            "REQUIRES_EXPLICIT_RESOLUTION",
            "SAME_NAME_DISTINCT_CONTEXT",
        ),
        basis_codes=("CONTEXT_BOUND_BILINGUAL_ALIAS",),
        idempotency_key=key,
    )


def test_same_name_bilingual_mentions_remain_separate_and_context_bound(
    tmp_path: Path,
) -> None:
    state = seed_homonym_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        mention_specs = (
            (
                state.en_transit_source,
                EN_TRANSIT_MENTION_ID,
                "en-GB",
                "homonym-mention-en-transit",
            ),
            (
                state.en_association_source,
                EN_ASSOCIATION_MENTION_ID,
                "en-GB",
                "homonym-mention-en-association",
            ),
            (
                state.zh_transit_source,
                ZH_TRANSIT_MENTION_ID,
                "zh-HK",
                "homonym-mention-zh-transit",
            ),
            (
                state.zh_association_source,
                ZH_ASSOCIATION_MENTION_ID,
                "zh-HK",
                "homonym-mention-zh-association",
            ),
        )
        mentions = {
            mention_id: system.entities.admit_mention(
                mention_request(
                    source,
                    mention_id=mention_id,
                    language=language,
                    entity_kind=EntityKind.PERSON,
                    key=key,
                ),
                proof=extraction_proof(),
            )
            for source, mention_id, language, key in mention_specs
        }

        en_transit = mentions[EN_TRANSIT_MENTION_ID]
        en_association = mentions[EN_ASSOCIATION_MENTION_ID]
        zh_transit = mentions[ZH_TRANSIT_MENTION_ID]
        zh_association = mentions[ZH_ASSOCIATION_MENTION_ID]

        assert en_transit.mention_text == en_association.mention_text == (
            "Chan Chi Ming"
        )
        assert en_transit.normalized_text == en_association.normalized_text
        assert en_transit.source_proposal_id != en_association.source_proposal_id
        assert (en_transit.start_byte, en_transit.end_byte) != (
            en_association.start_byte,
            en_association.end_byte,
        )
        assert zh_transit.mention_text == zh_association.mention_text == "陳志明"
        assert zh_transit.normalized_text == zh_association.normalized_text
        assert (zh_transit.start_byte, zh_transit.end_byte) != (
            zh_association.start_byte,
            zh_association.end_byte,
        )

        # The placeholders are identical, so text equality alone cannot identify
        # the correct pair. Exact evidence ranges must reject this crossed pair.
        with pytest.raises(EntityStateError, match="exact mentions"):
            system.entities.propose_resolution(
                _equivalence_proposal(
                    state.equivalence_association_source,
                    subject_mention_id=ZH_TRANSIT_MENTION_ID,
                    object_mention_id=EN_ASSOCIATION_MENTION_ID,
                    proposal_id=CROSS_CONTEXT_EQ_PROPOSAL_ID,
                    proposal_version_id=CROSS_CONTEXT_EQ_PROPOSAL_VERSION_ID,
                    key="homonym-cross-context-equivalence",
                ),
                proof=extraction_proof(),
            )

        transit_proposal = system.entities.propose_resolution(
            _new_entity_proposal(
                state.en_transit_source,
                mention_id=EN_TRANSIT_MENTION_ID,
                proposal_id=EN_TRANSIT_PROPOSAL_ID,
                proposal_version_id=EN_TRANSIT_PROPOSAL_VERSION_ID,
                key="homonym-propose-en-transit",
            ),
            proof=extraction_proof(),
        )
        association_proposal = system.entities.propose_resolution(
            _new_entity_proposal(
                state.en_association_source,
                mention_id=EN_ASSOCIATION_MENTION_ID,
                proposal_id=EN_ASSOCIATION_PROPOSAL_ID,
                proposal_version_id=EN_ASSOCIATION_PROPOSAL_VERSION_ID,
                key="homonym-propose-en-association",
            ),
            proof=extraction_proof(),
        )
        system.entities.decide_resolution(
            decision_request(
                transit_proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=TRANSIT_ENTITY_ID,
                version_id=TRANSIT_ENTITY_VERSION_ID,
                alias_id=TRANSIT_EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="homonym-accept-en-transit",
            ),
            proof=extraction_proof(),
        )
        system.entities.decide_resolution(
            decision_request(
                association_proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ASSOCIATION_ENTITY_ID,
                version_id=ASSOCIATION_ENTITY_VERSION_ID,
                alias_id=ASSOCIATION_EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="homonym-accept-en-association",
            ),
            proof=extraction_proof(),
        )

        transit_equivalence = system.entities.propose_resolution(
            _equivalence_proposal(
                state.equivalence_transit_source,
                subject_mention_id=ZH_TRANSIT_MENTION_ID,
                object_mention_id=EN_TRANSIT_MENTION_ID,
                proposal_id=ZH_TRANSIT_EQ_PROPOSAL_ID,
                proposal_version_id=ZH_TRANSIT_EQ_PROPOSAL_VERSION_ID,
                key="homonym-propose-zh-transit",
            ),
            proof=extraction_proof(),
        )
        association_equivalence = system.entities.propose_resolution(
            _equivalence_proposal(
                state.equivalence_association_source,
                subject_mention_id=ZH_ASSOCIATION_MENTION_ID,
                object_mention_id=EN_ASSOCIATION_MENTION_ID,
                proposal_id=ZH_ASSOCIATION_EQ_PROPOSAL_ID,
                proposal_version_id=ZH_ASSOCIATION_EQ_PROPOSAL_VERSION_ID,
                key="homonym-propose-zh-association",
            ),
            proof=extraction_proof(),
        )
        system.entities.decide_resolution(
            decision_request(
                transit_equivalence,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=TRANSIT_ENTITY_ID,
                version_id=TRANSIT_ENTITY_VERSION_ID,
                alias_id=TRANSIT_ZH_ALIAS_ID,
                alias_kind=EntityAliasKind.TRANSLITERATION,
                key="homonym-accept-zh-transit",
            ),
            proof=extraction_proof(),
        )
        system.entities.decide_resolution(
            decision_request(
                association_equivalence,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ASSOCIATION_ENTITY_ID,
                version_id=ASSOCIATION_ENTITY_VERSION_ID,
                alias_id=ASSOCIATION_ZH_ALIAS_ID,
                alias_kind=EntityAliasKind.TRANSLITERATION,
                key="homonym-accept-zh-association",
            ),
            proof=extraction_proof(),
        )

        assert TRANSIT_ENTITY_ID != ASSOCIATION_ENTITY_ID
        assert system.entities.preferred(
            TRANSIT_ENTITY_ID, proof=extraction_proof()
        ).preferred_entity_id == TRANSIT_ENTITY_ID
        assert system.entities.preferred(
            ASSOCIATION_ENTITY_ID, proof=extraction_proof()
        ).preferred_entity_id == ASSOCIATION_ENTITY_ID
        assert [
            (alias.alias_text, alias.alias_kind)
            for alias in system.entities.aliases(
                TRANSIT_ENTITY_ID, limit=10, proof=extraction_proof()
            )
        ] == [
            ("Chan Chi Ming", EntityAliasKind.PRIMARY_NAME),
            ("陳志明", EntityAliasKind.TRANSLITERATION),
        ]
        assert [
            (alias.alias_text, alias.alias_kind)
            for alias in system.entities.aliases(
                ASSOCIATION_ENTITY_ID, limit=10, proof=extraction_proof()
            )
        ] == [
            ("Chan Chi Ming", EntityAliasKind.PRIMARY_NAME),
            ("陳志明", EntityAliasKind.TRANSLITERATION),
        ]
