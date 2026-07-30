from __future__ import annotations

from typing import Callable

from newsroom.authority.auth import AuthenticationProof
from newsroom.entities.models import (
    CanonicalEntity,
    CanonicalEntityVersion,
    EntityAdmissionGuard,
    EntityAlias,
    EntityDependentAdmissionGuard,
    EntityMention,
    EntityMentionAdmissionRequest,
    EntityMergeDecision,
    EntityMergeDecisionRequest,
    EntityPreferredIdentity,
    EntityProjectionEvent,
    EntityResolutionDecision,
    EntityResolutionDecisionRequest,
    EntityResolutionDependency,
    EntityResolutionDependencyRequest,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersion,
    EntityReversalDecision,
    EntityReversalDecisionRequest,
    EntitySplitDecision,
    EntitySplitDecisionRequest,
)
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityMentionId,
    EntityMergeDecisionId,
    EntityResolutionDependencyId,
    EntityResolutionProposalId,
    EntityResolutionProposalVersionId,
    EntityReversalDecisionId,
    EntitySplitDecisionId,
)
from newsroom.extraction.types import ProposalEnvelopeId


class GovernedEntityRecords:
    """Authenticated typed facade; no SQLite connection or capability escapes."""

    __slots__ = (
        "__admit_mention",
        "__propose_resolution",
        "__decide_resolution",
        "__bind_resolution_dependency",
        "__merge_entities",
        "__split_entity",
        "__reverse_lineage",
        "__mention",
        "__proposal",
        "__proposal_version",
        "__decision",
        "__entity",
        "__entity_version",
        "__aliases",
        "__preferred",
        "__projection_events_after",
        "__admission_guard",
        "__dependency",
        "__dependent_admission_guard",
        "__merge_decision",
        "__split_decision",
        "__reversal_decision",
    )

    def __init__(
        self,
        *,
        admit_mention: Callable[
            [EntityMentionAdmissionRequest, AuthenticationProof], EntityMention
        ],
        propose_resolution: Callable[
            [EntityResolutionProposalRequest, AuthenticationProof],
            EntityResolutionProposalVersion,
        ],
        decide_resolution: Callable[
            [EntityResolutionDecisionRequest, AuthenticationProof],
            EntityResolutionDecision,
        ],
        bind_resolution_dependency: Callable[
            [EntityResolutionDependencyRequest, AuthenticationProof],
            EntityResolutionDependency,
        ],
        merge_entities: Callable[
            [EntityMergeDecisionRequest, AuthenticationProof], EntityMergeDecision
        ],
        split_entity: Callable[
            [EntitySplitDecisionRequest, AuthenticationProof], EntitySplitDecision
        ],
        reverse_lineage: Callable[
            [EntityReversalDecisionRequest, AuthenticationProof],
            EntityReversalDecision,
        ],
        mention: Callable[[EntityMentionId, AuthenticationProof], EntityMention],
        proposal: Callable[
            [EntityResolutionProposalId, AuthenticationProof],
            EntityResolutionProposalVersion,
        ],
        proposal_version: Callable[
            [EntityResolutionProposalVersionId, AuthenticationProof],
            EntityResolutionProposalVersion,
        ],
        decision: Callable[
            [EntityResolutionProposalId, AuthenticationProof],
            EntityResolutionDecision | None,
        ],
        entity: Callable[[CanonicalEntityId, AuthenticationProof], CanonicalEntity],
        entity_version: Callable[
            [CanonicalEntityVersionId, AuthenticationProof], CanonicalEntityVersion
        ],
        aliases: Callable[
            [CanonicalEntityId, int, AuthenticationProof], tuple[EntityAlias, ...]
        ],
        preferred: Callable[
            [CanonicalEntityId, AuthenticationProof], EntityPreferredIdentity
        ],
        projection_events_after: Callable[
            [int, int, AuthenticationProof], tuple[EntityProjectionEvent, ...]
        ],
        admission_guard: Callable[
            [EntityResolutionProposalId, AuthenticationProof], EntityAdmissionGuard
        ],
        dependency: Callable[
            [EntityResolutionDependencyId, AuthenticationProof],
            EntityResolutionDependency,
        ],
        dependent_admission_guard: Callable[
            [ProposalEnvelopeId, AuthenticationProof],
            EntityDependentAdmissionGuard,
        ],
        merge_decision: Callable[
            [EntityMergeDecisionId, AuthenticationProof], EntityMergeDecision
        ],
        split_decision: Callable[
            [EntitySplitDecisionId, AuthenticationProof], EntitySplitDecision
        ],
        reversal_decision: Callable[
            [EntityReversalDecisionId, AuthenticationProof], EntityReversalDecision
        ],
    ) -> None:
        self.__admit_mention = admit_mention
        self.__propose_resolution = propose_resolution
        self.__decide_resolution = decide_resolution
        self.__bind_resolution_dependency = bind_resolution_dependency
        self.__merge_entities = merge_entities
        self.__split_entity = split_entity
        self.__reverse_lineage = reverse_lineage
        self.__mention = mention
        self.__proposal = proposal
        self.__proposal_version = proposal_version
        self.__decision = decision
        self.__entity = entity
        self.__entity_version = entity_version
        self.__aliases = aliases
        self.__preferred = preferred
        self.__projection_events_after = projection_events_after
        self.__admission_guard = admission_guard
        self.__dependency = dependency
        self.__dependent_admission_guard = dependent_admission_guard
        self.__merge_decision = merge_decision
        self.__split_decision = split_decision
        self.__reversal_decision = reversal_decision

    def admit_mention(
        self,
        request: EntityMentionAdmissionRequest,
        *,
        proof: AuthenticationProof,
    ) -> EntityMention:
        return self.__admit_mention(request, proof)

    def propose_resolution(
        self,
        request: EntityResolutionProposalRequest,
        *,
        proof: AuthenticationProof,
    ) -> EntityResolutionProposalVersion:
        return self.__propose_resolution(request, proof)

    def decide_resolution(
        self,
        request: EntityResolutionDecisionRequest,
        *,
        proof: AuthenticationProof,
    ) -> EntityResolutionDecision:
        return self.__decide_resolution(request, proof)

    def bind_resolution_dependency(
        self,
        request: EntityResolutionDependencyRequest,
        *,
        proof: AuthenticationProof,
    ) -> EntityResolutionDependency:
        return self.__bind_resolution_dependency(request, proof)

    def merge_entities(
        self,
        request: EntityMergeDecisionRequest,
        *,
        proof: AuthenticationProof,
    ) -> EntityMergeDecision:
        return self.__merge_entities(request, proof)

    def split_entity(
        self,
        request: EntitySplitDecisionRequest,
        *,
        proof: AuthenticationProof,
    ) -> EntitySplitDecision:
        return self.__split_entity(request, proof)

    def reverse_lineage(
        self,
        request: EntityReversalDecisionRequest,
        *,
        proof: AuthenticationProof,
    ) -> EntityReversalDecision:
        return self.__reverse_lineage(request, proof)

    def mention(
        self, mention_id: EntityMentionId, *, proof: AuthenticationProof
    ) -> EntityMention:
        return self.__mention(mention_id, proof)

    def proposal(
        self,
        proposal_id: EntityResolutionProposalId,
        *,
        proof: AuthenticationProof,
    ) -> EntityResolutionProposalVersion:
        return self.__proposal(proposal_id, proof)

    def proposal_version(
        self,
        proposal_version_id: EntityResolutionProposalVersionId,
        *,
        proof: AuthenticationProof,
    ) -> EntityResolutionProposalVersion:
        return self.__proposal_version(proposal_version_id, proof)

    def decision(
        self,
        proposal_id: EntityResolutionProposalId,
        *,
        proof: AuthenticationProof,
    ) -> EntityResolutionDecision | None:
        return self.__decision(proposal_id, proof)

    def entity(
        self, entity_id: CanonicalEntityId, *, proof: AuthenticationProof
    ) -> CanonicalEntity:
        return self.__entity(entity_id, proof)

    def entity_version(
        self,
        entity_version_id: CanonicalEntityVersionId,
        *,
        proof: AuthenticationProof,
    ) -> CanonicalEntityVersion:
        return self.__entity_version(entity_version_id, proof)

    def aliases(
        self,
        entity_id: CanonicalEntityId,
        *,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[EntityAlias, ...]:
        return self.__aliases(entity_id, limit, proof)

    def preferred(
        self, entity_id: CanonicalEntityId, *, proof: AuthenticationProof
    ) -> EntityPreferredIdentity:
        return self.__preferred(entity_id, proof)

    def projection_events_after(
        self,
        after_ledger_seq: int,
        *,
        limit: int = 1000,
        proof: AuthenticationProof,
    ) -> tuple[EntityProjectionEvent, ...]:
        return self.__projection_events_after(after_ledger_seq, limit, proof)

    def admission_guard(
        self,
        proposal_id: EntityResolutionProposalId,
        *,
        proof: AuthenticationProof,
    ) -> EntityAdmissionGuard:
        return self.__admission_guard(proposal_id, proof)

    def dependency(
        self,
        dependency_id: EntityResolutionDependencyId,
        *,
        proof: AuthenticationProof,
    ) -> EntityResolutionDependency:
        return self.__dependency(dependency_id, proof)

    def dependent_admission_guard(
        self,
        dependent_proposal_id: ProposalEnvelopeId,
        *,
        proof: AuthenticationProof,
    ) -> EntityDependentAdmissionGuard:
        return self.__dependent_admission_guard(dependent_proposal_id, proof)

    def merge_decision(
        self,
        decision_id: EntityMergeDecisionId,
        *,
        proof: AuthenticationProof,
    ) -> EntityMergeDecision:
        return self.__merge_decision(decision_id, proof)

    def split_decision(
        self,
        decision_id: EntitySplitDecisionId,
        *,
        proof: AuthenticationProof,
    ) -> EntitySplitDecision:
        return self.__split_decision(decision_id, proof)

    def reversal_decision(
        self,
        decision_id: EntityReversalDecisionId,
        *,
        proof: AuthenticationProof,
    ) -> EntityReversalDecision:
        return self.__reversal_decision(decision_id, proof)


__all__ = ["GovernedEntityRecords"]
