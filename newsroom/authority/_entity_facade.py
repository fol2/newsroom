from __future__ import annotations

from typing import Callable

from newsroom.authority.auth import AuthenticationProof
from newsroom.entities.models import (
    CanonicalEntity,
    CanonicalEntityVersion,
    EntityAdmissionGuard,
    EntityAlias,
    EntityMention,
    EntityMentionAdmissionRequest,
    EntityPreferredIdentity,
    EntityResolutionDecision,
    EntityResolutionDecisionRequest,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersion,
)
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityMentionId,
    EntityResolutionProposalId,
    EntityResolutionProposalVersionId,
)


class GovernedEntityRecords:
    """Authenticated typed facade; no SQLite connection or capability escapes."""

    __slots__ = (
        "__admit_mention",
        "__propose_resolution",
        "__decide_resolution",
        "__mention",
        "__proposal",
        "__proposal_version",
        "__decision",
        "__entity",
        "__entity_version",
        "__aliases",
        "__preferred",
        "__admission_guard",
    )

    def __init__(
        self,
        *,
        admit_mention: Callable[[EntityMentionAdmissionRequest, AuthenticationProof], EntityMention],
        propose_resolution: Callable[[EntityResolutionProposalRequest, AuthenticationProof], EntityResolutionProposalVersion],
        decide_resolution: Callable[[EntityResolutionDecisionRequest, AuthenticationProof], EntityResolutionDecision],
        mention: Callable[[EntityMentionId, AuthenticationProof], EntityMention],
        proposal: Callable[[EntityResolutionProposalId, AuthenticationProof], EntityResolutionProposalVersion],
        proposal_version: Callable[[EntityResolutionProposalVersionId, AuthenticationProof], EntityResolutionProposalVersion],
        decision: Callable[[EntityResolutionProposalId, AuthenticationProof], EntityResolutionDecision | None],
        entity: Callable[[CanonicalEntityId, AuthenticationProof], CanonicalEntity],
        entity_version: Callable[[CanonicalEntityVersionId, AuthenticationProof], CanonicalEntityVersion],
        aliases: Callable[[CanonicalEntityId, int, AuthenticationProof], tuple[EntityAlias, ...]],
        preferred: Callable[[CanonicalEntityId, AuthenticationProof], EntityPreferredIdentity],
        admission_guard: Callable[[EntityResolutionProposalId, AuthenticationProof], EntityAdmissionGuard],
    ) -> None:
        self.__admit_mention = admit_mention
        self.__propose_resolution = propose_resolution
        self.__decide_resolution = decide_resolution
        self.__mention = mention
        self.__proposal = proposal
        self.__proposal_version = proposal_version
        self.__decision = decision
        self.__entity = entity
        self.__entity_version = entity_version
        self.__aliases = aliases
        self.__preferred = preferred
        self.__admission_guard = admission_guard

    def admit_mention(self, request: EntityMentionAdmissionRequest, *, proof: AuthenticationProof) -> EntityMention:
        return self.__admit_mention(request, proof)

    def propose_resolution(self, request: EntityResolutionProposalRequest, *, proof: AuthenticationProof) -> EntityResolutionProposalVersion:
        return self.__propose_resolution(request, proof)

    def decide_resolution(self, request: EntityResolutionDecisionRequest, *, proof: AuthenticationProof) -> EntityResolutionDecision:
        return self.__decide_resolution(request, proof)

    def mention(self, mention_id: EntityMentionId, *, proof: AuthenticationProof) -> EntityMention:
        return self.__mention(mention_id, proof)

    def proposal(self, proposal_id: EntityResolutionProposalId, *, proof: AuthenticationProof) -> EntityResolutionProposalVersion:
        return self.__proposal(proposal_id, proof)

    def proposal_version(self, proposal_version_id: EntityResolutionProposalVersionId, *, proof: AuthenticationProof) -> EntityResolutionProposalVersion:
        return self.__proposal_version(proposal_version_id, proof)

    def decision(self, proposal_id: EntityResolutionProposalId, *, proof: AuthenticationProof) -> EntityResolutionDecision | None:
        return self.__decision(proposal_id, proof)

    def entity(self, entity_id: CanonicalEntityId, *, proof: AuthenticationProof) -> CanonicalEntity:
        return self.__entity(entity_id, proof)

    def entity_version(self, entity_version_id: CanonicalEntityVersionId, *, proof: AuthenticationProof) -> CanonicalEntityVersion:
        return self.__entity_version(entity_version_id, proof)

    def aliases(self, entity_id: CanonicalEntityId, *, limit: int, proof: AuthenticationProof) -> tuple[EntityAlias, ...]:
        return self.__aliases(entity_id, limit, proof)

    def preferred(self, entity_id: CanonicalEntityId, *, proof: AuthenticationProof) -> EntityPreferredIdentity:
        return self.__preferred(entity_id, proof)

    def admission_guard(self, proposal_id: EntityResolutionProposalId, *, proof: AuthenticationProof) -> EntityAdmissionGuard:
        return self.__admission_guard(proposal_id, proof)


__all__ = ["GovernedEntityRecords"]
