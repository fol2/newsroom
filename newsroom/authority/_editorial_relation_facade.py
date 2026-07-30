from __future__ import annotations

from typing import Callable

from newsroom.authority.auth import AuthenticationProof
from newsroom.relations.editorial_models import (
    EditorialRelationAssertion,
    EditorialRelationCurrentView,
    EditorialRelationDecision,
    EditorialRelationDecisionRequest,
    EditorialRelationProjectionEvent,
    EditorialRelationProposalRequest,
    EditorialRelationProposalVersion,
)
from newsroom.relations.editorial_types import (
    EditorialRelationAssertionId,
    EditorialRelationProposalId,
    EditorialRelationProposalVersionId,
)


class GovernedEditorialRelations:
    """Authenticated typed facade; no SQLite or capability authority escapes."""

    __slots__ = (
        "__propose",
        "__decide",
        "__proposal",
        "__proposal_version",
        "__decision",
        "__assertion",
        "__current",
        "__current_relations",
        "__projection_events_after",
    )

    def __init__(
        self,
        *,
        propose: Callable[
            [EditorialRelationProposalRequest, AuthenticationProof],
            EditorialRelationProposalVersion,
        ],
        decide: Callable[
            [EditorialRelationDecisionRequest, AuthenticationProof],
            EditorialRelationDecision,
        ],
        proposal: Callable[
            [EditorialRelationProposalId, AuthenticationProof],
            EditorialRelationProposalVersion,
        ],
        proposal_version: Callable[
            [EditorialRelationProposalVersionId, AuthenticationProof],
            EditorialRelationProposalVersion,
        ],
        decision: Callable[
            [EditorialRelationProposalId, AuthenticationProof],
            EditorialRelationDecision | None,
        ],
        assertion: Callable[
            [EditorialRelationAssertionId, AuthenticationProof],
            EditorialRelationAssertion,
        ],
        current: Callable[
            [EditorialRelationAssertionId, AuthenticationProof],
            EditorialRelationCurrentView,
        ],
        current_relations: Callable[
            [int, AuthenticationProof], tuple[EditorialRelationCurrentView, ...]
        ],
        projection_events_after: Callable[
            [int, int, AuthenticationProof],
            tuple[EditorialRelationProjectionEvent, ...],
        ],
    ) -> None:
        self.__propose = propose
        self.__decide = decide
        self.__proposal = proposal
        self.__proposal_version = proposal_version
        self.__decision = decision
        self.__assertion = assertion
        self.__current = current
        self.__current_relations = current_relations
        self.__projection_events_after = projection_events_after

    def propose(
        self,
        request: EditorialRelationProposalRequest,
        *,
        proof: AuthenticationProof,
    ) -> EditorialRelationProposalVersion:
        return self.__propose(request, proof)

    def decide(
        self,
        request: EditorialRelationDecisionRequest,
        *,
        proof: AuthenticationProof,
    ) -> EditorialRelationDecision:
        return self.__decide(request, proof)

    def proposal(
        self,
        proposal_id: EditorialRelationProposalId,
        *,
        proof: AuthenticationProof,
    ) -> EditorialRelationProposalVersion:
        return self.__proposal(proposal_id, proof)

    def proposal_version(
        self,
        proposal_version_id: EditorialRelationProposalVersionId,
        *,
        proof: AuthenticationProof,
    ) -> EditorialRelationProposalVersion:
        return self.__proposal_version(proposal_version_id, proof)

    def decision(
        self,
        proposal_id: EditorialRelationProposalId,
        *,
        proof: AuthenticationProof,
    ) -> EditorialRelationDecision | None:
        return self.__decision(proposal_id, proof)

    def assertion(
        self,
        assertion_id: EditorialRelationAssertionId,
        *,
        proof: AuthenticationProof,
    ) -> EditorialRelationAssertion:
        return self.__assertion(assertion_id, proof)

    def current(
        self,
        assertion_id: EditorialRelationAssertionId,
        *,
        proof: AuthenticationProof,
    ) -> EditorialRelationCurrentView:
        return self.__current(assertion_id, proof)

    def current_relations(
        self,
        *,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[EditorialRelationCurrentView, ...]:
        return self.__current_relations(limit, proof)

    def projection_events_after(
        self,
        *,
        after_ledger_seq: int,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[EditorialRelationProjectionEvent, ...]:
        return self.__projection_events_after(after_ledger_seq, limit, proof)


__all__ = ["GovernedEditorialRelations"]
