from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.entities import (
    CanonicalEntityId,
    CanonicalEntityLifecycle,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityContractError,
    EntityDecisionConflict,
    EntityLineageDecisionKind,
    EntityLineageVersion,
    EntityMergeDecisionId,
    EntityMergeDecisionRequest,
    EntityMentionId,
    EntityResolutionDecisionAction,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersionId,
    EntityReversalDecisionId,
    EntityReversalDecisionRequest,
    EntityReversalTargetKind,
    EntitySplitAllocation,
    EntitySplitDecisionId,
    EntitySplitDecisionRequest,
    EntityStaleDecision,
)

from .entity_4b_helpers import (
    EN_MENTION_ID,
    ZH_MENTION_ID,
    decision_request,
    mention_request,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof


def _id(cls, suffix: int):
    return cls.parse(f"00000000-0000-4000-8000-{suffix:012d}")


ENTITY_A_ID = _id(CanonicalEntityId, 5001)
ENTITY_A_V1_ID = _id(CanonicalEntityVersionId, 5002)
ENTITY_A_ALIAS_ID = _id(EntityAliasId, 5003)
ENTITY_A_PROPOSAL_ID = _id(EntityResolutionProposalId, 5011)
ENTITY_A_PROPOSAL_V1_ID = _id(EntityResolutionProposalVersionId, 5012)

ENTITY_B_ID = _id(CanonicalEntityId, 5101)
ENTITY_B_V1_ID = _id(CanonicalEntityVersionId, 5102)
ENTITY_B_ALIAS_ID = _id(EntityAliasId, 5103)
ENTITY_B_PROPOSAL_ID = _id(EntityResolutionProposalId, 5111)
ENTITY_B_PROPOSAL_V1_ID = _id(EntityResolutionProposalVersionId, 5112)

EQUIVALENCE_PROPOSAL_ID = _id(EntityResolutionProposalId, 5151)
EQUIVALENCE_PROPOSAL_V1_ID = _id(EntityResolutionProposalVersionId, 5152)
EQUIVALENCE_ALIAS_ID = _id(EntityAliasId, 5153)

MERGE_DECISION_ID = _id(EntityMergeDecisionId, 5201)
MERGE_SUCCESSOR_ID = _id(CanonicalEntityId, 5202)
MERGE_SUCCESSOR_V1_ID = _id(CanonicalEntityVersionId, 5203)

SPLIT_DECISION_ID = _id(EntitySplitDecisionId, 5301)
SPLIT_SUCCESSOR_A_ID = _id(CanonicalEntityId, 5302)
SPLIT_SUCCESSOR_B_ID = _id(CanonicalEntityId, 5303)
SPLIT_SUCCESSOR_A_V1_ID = _id(CanonicalEntityVersionId, 5304)
SPLIT_SUCCESSOR_B_V1_ID = _id(CanonicalEntityVersionId, 5305)

MERGE_REVERSAL_ID = _id(EntityReversalDecisionId, 5401)
MERGE_RESTORED_A_ID = _id(CanonicalEntityVersionId, 5402)
MERGE_RESTORED_B_ID = _id(CanonicalEntityVersionId, 5403)
SPLIT_REVERSAL_ID = _id(EntityReversalDecisionId, 5411)
SPLIT_RESTORED_SOURCE_ID = _id(CanonicalEntityVersionId, 5412)
UNRELATED_MENTION_ID = _id(EntityMentionId, 5499)


def _admit_mentions(system, state) -> None:
    for source, mention_id, language, key in (
        (state.en_source, EN_MENTION_ID, "en-GB", "lineage-mention-en-v1"),
        (state.zh_source, ZH_MENTION_ID, "zh-HK", "lineage-mention-zh-v1"),
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


def _new_entity_request(
    *,
    source,
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
        confidence_basis_points=9_000,
        uncertainty_codes=(),
        basis_codes=("EXPLICIT_EDITORIAL_IDENTITY",),
        idempotency_key=key,
    )


def _accept_new_entity(
    system,
    *,
    source,
    mention_id: EntityMentionId,
    proposal_id: EntityResolutionProposalId,
    proposal_version_id: EntityResolutionProposalVersionId,
    entity_id: CanonicalEntityId,
    entity_version_id: CanonicalEntityVersionId,
    alias_id: EntityAliasId,
    key_prefix: str,
):
    proposal = system.entities.propose_resolution(
        _new_entity_request(
            source=source,
            mention_id=mention_id,
            proposal_id=proposal_id,
            proposal_version_id=proposal_version_id,
            key=f"{key_prefix}-proposal",
        ),
        proof=extraction_proof(),
    )
    decision = system.entities.decide_resolution(
        decision_request(
            proposal,
            action=EntityResolutionDecisionAction.ACCEPT,
            entity_id=entity_id,
            version_id=entity_version_id,
            alias_id=alias_id,
            alias_kind=EntityAliasKind.PRIMARY_NAME,
            key=f"{key_prefix}-accept",
        ),
        proof=extraction_proof(),
    )
    return proposal, decision


def _accept_bilingual_equivalence(system, state) -> None:
    proposal = system.entities.propose_resolution(
        EntityResolutionProposalRequest(
            proposal_id=EQUIVALENCE_PROPOSAL_ID,
            proposal_version_id=EQUIVALENCE_PROPOSAL_V1_ID,
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
            idempotency_key="lineage-equivalence-proposal-v1",
        ),
        proof=extraction_proof(),
    )
    system.entities.decide_resolution(
        decision_request(
            proposal,
            action=EntityResolutionDecisionAction.ACCEPT,
            entity_id=ENTITY_A_ID,
            version_id=ENTITY_A_V1_ID,
            alias_id=EQUIVALENCE_ALIAS_ID,
            alias_kind=EntityAliasKind.TRANSLATION,
            key="lineage-equivalence-accept-v1",
        ),
        proof=extraction_proof(),
    )


def _seed_two_entities(system, state):
    _admit_mentions(system, state)
    proposal_a, _ = _accept_new_entity(
        system,
        source=state.en_source,
        mention_id=EN_MENTION_ID,
        proposal_id=ENTITY_A_PROPOSAL_ID,
        proposal_version_id=ENTITY_A_PROPOSAL_V1_ID,
        entity_id=ENTITY_A_ID,
        entity_version_id=ENTITY_A_V1_ID,
        alias_id=ENTITY_A_ALIAS_ID,
        key_prefix="lineage-a",
    )
    proposal_b, _ = _accept_new_entity(
        system,
        source=state.zh_source,
        mention_id=ZH_MENTION_ID,
        proposal_id=ENTITY_B_PROPOSAL_ID,
        proposal_version_id=ENTITY_B_PROPOSAL_V1_ID,
        entity_id=ENTITY_B_ID,
        entity_version_id=ENTITY_B_V1_ID,
        alias_id=ENTITY_B_ALIAS_ID,
        key_prefix="lineage-b",
    )
    return proposal_a, proposal_b


def _merge_request(proposal_ids) -> EntityMergeDecisionRequest:
    predecessors = tuple(
        sorted(
            (
                EntityLineageVersion(ENTITY_A_ID, ENTITY_A_V1_ID),
                EntityLineageVersion(ENTITY_B_ID, ENTITY_B_V1_ID),
            ),
            key=lambda item: str(item.entity_id),
        )
    )
    return EntityMergeDecisionRequest(
        merge_decision_id=MERGE_DECISION_ID,
        predecessors=predecessors,
        successor_entity_id=MERGE_SUCCESSOR_ID,
        successor_entity_version_id=MERGE_SUCCESSOR_V1_ID,
        preferred_continuation_entity_id=ENTITY_A_ID,
        basis_resolution_proposal_ids=tuple(sorted(proposal_ids, key=str)),
        reason_code="EDITORIAL_MERGE",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="lineage-merge-v1",
    )


def _split_request() -> EntitySplitDecisionRequest:
    successors = tuple(
        sorted(
            (
                EntityLineageVersion(
                    SPLIT_SUCCESSOR_A_ID, SPLIT_SUCCESSOR_A_V1_ID
                ),
                EntityLineageVersion(
                    SPLIT_SUCCESSOR_B_ID, SPLIT_SUCCESSOR_B_V1_ID
                ),
            ),
            key=lambda item: str(item.entity_id),
        )
    )
    allocations = tuple(
        sorted(
            (
                EntitySplitAllocation(EN_MENTION_ID, SPLIT_SUCCESSOR_A_ID),
                EntitySplitAllocation(ZH_MENTION_ID, SPLIT_SUCCESSOR_B_ID),
            ),
            key=lambda item: (str(item.mention_id), str(item.successor_entity_id)),
        )
    )
    return EntitySplitDecisionRequest(
        split_decision_id=SPLIT_DECISION_ID,
        source_entity_id=ENTITY_A_ID,
        expected_source_version_id=ENTITY_A_V1_ID,
        successors=successors,
        allocations=allocations,
        reason_code="EDITORIAL_SPLIT",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="lineage-split-v1",
    )


def test_merge_is_append_only_replayable_and_projects_one_successor(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        proposal_a, proposal_b = _seed_two_entities(system, state)
        request = _merge_request((proposal_a.proposal_id, proposal_b.proposal_id))
        merged = system.entities.merge_entities(request, proof=extraction_proof())
        replay = system.entities.merge_entities(request, proof=extraction_proof())

        assert replay.replayed is True
        assert replay.canonical_digest == merged.canonical_digest
        assert len(merged.predecessors) == 2
        assert system.entities.merge_decision(
            MERGE_DECISION_ID, proof=extraction_proof()
        ).canonical_digest == merged.canonical_digest
        assert system.entities.entity(
            MERGE_SUCCESSOR_ID, proof=extraction_proof()
        ).created_by_decision_id == str(MERGE_DECISION_ID)
        for predecessor in merged.predecessors:
            version = system.entities.entity_version(
                predecessor.merged_entity_version_id, proof=extraction_proof()
            )
            preferred = system.entities.preferred(
                predecessor.entity_id, proof=extraction_proof()
            )
            assert version.lifecycle is CanonicalEntityLifecycle.MERGED
            assert version.previous_entity_version_id == (
                predecessor.expected_entity_version_id
            )
            assert preferred.preferred_entity_id == MERGE_SUCCESSOR_ID
            assert preferred.lifecycle is CanonicalEntityLifecycle.MERGED
        successor = system.entities.preferred(
            MERGE_SUCCESSOR_ID, proof=extraction_proof()
        )
        assert successor.lifecycle is CanonicalEntityLifecycle.ACTIVE
        assert successor.preferred_entity_id == MERGE_SUCCESSOR_ID
    finally:
        system.close()


def test_merge_rejects_stale_or_incomplete_basis_without_partial_lineage(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        proposal_a, proposal_b = _seed_two_entities(system, state)
        request = _merge_request((proposal_a.proposal_id, proposal_b.proposal_id))
        with pytest.raises(EntityDecisionConflict, match="exactly cover"):
            system.entities.merge_entities(
                replace(
                    request,
                    basis_resolution_proposal_ids=(proposal_a.proposal_id,),
                    idempotency_key="lineage-merge-incomplete",
                ),
                proof=extraction_proof(),
            )
        with pytest.raises(KeyError):
            system.entities.entity(MERGE_SUCCESSOR_ID, proof=extraction_proof())
    finally:
        system.close()


def test_split_partitions_every_admitted_mention_and_is_replayable(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        _admit_mentions(system, state)
        _accept_new_entity(
            system,
            source=state.en_source,
            mention_id=EN_MENTION_ID,
            proposal_id=ENTITY_A_PROPOSAL_ID,
            proposal_version_id=ENTITY_A_PROPOSAL_V1_ID,
            entity_id=ENTITY_A_ID,
            entity_version_id=ENTITY_A_V1_ID,
            alias_id=ENTITY_A_ALIAS_ID,
            key_prefix="lineage-a",
        )
        _accept_bilingual_equivalence(system, state)
        request = _split_request()
        split = system.entities.split_entity(request, proof=extraction_proof())
        replay = system.entities.split_entity(request, proof=extraction_proof())

        assert replay.replayed is True
        assert replay.canonical_digest == split.canonical_digest
        assert system.entities.split_decision(
            SPLIT_DECISION_ID, proof=extraction_proof()
        ).allocations == request.allocations
        source = system.entities.preferred(
            ENTITY_A_ID, proof=extraction_proof()
        )
        assert source.lifecycle is CanonicalEntityLifecycle.SPLIT
        for successor in split.successors:
            preferred = system.entities.preferred(
                successor.entity_id, proof=extraction_proof()
            )
            assert preferred.lifecycle is CanonicalEntityLifecycle.ACTIVE
            assert preferred.preferred_entity_id == successor.entity_id
    finally:
        system.close()


def test_split_rejects_incomplete_partition_and_stale_source(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        _admit_mentions(system, state)
        _accept_new_entity(
            system,
            source=state.en_source,
            mention_id=EN_MENTION_ID,
            proposal_id=ENTITY_A_PROPOSAL_ID,
            proposal_version_id=ENTITY_A_PROPOSAL_V1_ID,
            entity_id=ENTITY_A_ID,
            entity_version_id=ENTITY_A_V1_ID,
            alias_id=ENTITY_A_ALIAS_ID,
            key_prefix="lineage-a",
        )
        _accept_bilingual_equivalence(system, state)
        request = _split_request()
        with pytest.raises(EntityDecisionConflict, match="partition"):
            system.entities.split_entity(
                replace(
                    request,
                    allocations=tuple(
                        sorted(
                            (
                                request.allocations[0],
                                EntitySplitAllocation(
                                    UNRELATED_MENTION_ID, SPLIT_SUCCESSOR_B_ID
                                ),
                            ),
                            key=lambda item: (
                                str(item.mention_id), str(item.successor_entity_id)
                            ),
                        )
                    ),
                    idempotency_key="lineage-split-incomplete",
                ),
                proof=extraction_proof(),
            )
        assert system.entities.preferred(
            ENTITY_A_ID, proof=extraction_proof()
        ).lifecycle is CanonicalEntityLifecycle.ACTIVE
        system.entities.split_entity(request, proof=extraction_proof())
        with pytest.raises(EntityStaleDecision):
            system.entities.split_entity(
                replace(
                    request,
                    split_decision_id=_id(EntitySplitDecisionId, 5399),
                    idempotency_key="lineage-split-stale",
                ),
                proof=extraction_proof(),
            )
    finally:
        system.close()


def test_merge_reversal_restores_predecessors_and_supersedes_successor(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        proposal_a, proposal_b = _seed_two_entities(system, state)
        merged = system.entities.merge_entities(
            _merge_request((proposal_a.proposal_id, proposal_b.proposal_id)),
            proof=extraction_proof(),
        )
        restorations = tuple(
            sorted(
                (
                    EntityLineageVersion(ENTITY_A_ID, MERGE_RESTORED_A_ID),
                    EntityLineageVersion(ENTITY_B_ID, MERGE_RESTORED_B_ID),
                ),
                key=lambda item: str(item.entity_id),
            )
        )
        expected_versions = tuple(
            sorted(
                (
                    *(item.merged_entity_version_id for item in merged.predecessors),
                    merged.successor_entity_version_id,
                ),
                key=str,
            )
        )
        request = EntityReversalDecisionRequest(
            reversal_decision_id=MERGE_REVERSAL_ID,
            target_kind=EntityReversalTargetKind.MERGE,
            target_decision_id=str(MERGE_DECISION_ID),
            expected_current_entity_version_ids=expected_versions,
            restorations=restorations,
            reason_code="EDITORIAL_MERGE_REVERSAL",
            decision_policy_version="entity-resolution-policy-v1",
            idempotency_key="lineage-merge-reversal-v1",
        )
        reversal = system.entities.reverse_lineage(
            request, proof=extraction_proof()
        )
        replay = system.entities.reverse_lineage(
            request, proof=extraction_proof()
        )

        assert replay.replayed is True
        assert replay.canonical_digest == reversal.canonical_digest
        assert len(reversal.supersessions) == 1
        for restored in reversal.restorations:
            preferred = system.entities.preferred(
                restored.entity_id, proof=extraction_proof()
            )
            assert preferred.lifecycle is CanonicalEntityLifecycle.ACTIVE
            assert preferred.current_entity_version_id == restored.entity_version_id
        superseded = reversal.supersessions[0]
        preferred = system.entities.preferred(
            superseded.entity_id, proof=extraction_proof()
        )
        assert preferred.lifecycle is CanonicalEntityLifecycle.REVERSED
        assert preferred.preferred_entity_id == ENTITY_A_ID
        assert system.entities.reversal_decision(
            MERGE_REVERSAL_ID, proof=extraction_proof()
        ).canonical_digest == reversal.canonical_digest
    finally:
        system.close()


def test_split_reversal_restores_source_and_supersedes_successors(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    system = open_entity_system(state)
    try:
        _admit_mentions(system, state)
        _accept_new_entity(
            system,
            source=state.en_source,
            mention_id=EN_MENTION_ID,
            proposal_id=ENTITY_A_PROPOSAL_ID,
            proposal_version_id=ENTITY_A_PROPOSAL_V1_ID,
            entity_id=ENTITY_A_ID,
            entity_version_id=ENTITY_A_V1_ID,
            alias_id=ENTITY_A_ALIAS_ID,
            key_prefix="lineage-a",
        )
        _accept_bilingual_equivalence(system, state)
        split = system.entities.split_entity(
            _split_request(), proof=extraction_proof()
        )
        expected_versions = tuple(
            sorted(
                (
                    split.source_split_version_id,
                    *(item.entity_version_id for item in split.successors),
                ),
                key=str,
            )
        )
        request = EntityReversalDecisionRequest(
            reversal_decision_id=SPLIT_REVERSAL_ID,
            target_kind=EntityReversalTargetKind.SPLIT,
            target_decision_id=str(SPLIT_DECISION_ID),
            expected_current_entity_version_ids=expected_versions,
            restorations=(
                EntityLineageVersion(
                    ENTITY_A_ID, SPLIT_RESTORED_SOURCE_ID
                ),
            ),
            reason_code="EDITORIAL_SPLIT_REVERSAL",
            decision_policy_version="entity-resolution-policy-v1",
            idempotency_key="lineage-split-reversal-v1",
        )
        reversal = system.entities.reverse_lineage(
            request, proof=extraction_proof()
        )

        source = system.entities.preferred(
            ENTITY_A_ID, proof=extraction_proof()
        )
        assert source.lifecycle is CanonicalEntityLifecycle.ACTIVE
        assert source.current_entity_version_id == SPLIT_RESTORED_SOURCE_ID
        assert len(reversal.supersessions) == 2
        for superseded in reversal.supersessions:
            preferred = system.entities.preferred(
                superseded.entity_id, proof=extraction_proof()
            )
            assert preferred.lifecycle is CanonicalEntityLifecycle.REVERSED
            assert preferred.preferred_entity_id == ENTITY_A_ID
    finally:
        system.close()
