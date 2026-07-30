from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.integrated.models import IntegratedHypothesisVersionId
from newsroom.relations import (
    EDITORIAL_PREDICATE_REGISTRY_V1,
    EventHypothesisRelationEndpoint,
    EditorialPredicateCode,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionId,
    EditorialRelationIdentifierReuse,
    EditorialRelationProposalId,
    EditorialRelationProposalVersionId,
    EditorialRelationSemanticCollision,
    EditorialRelationStaleDecision,
    EditorialRelationStateError,
)

from .editorial_relation_4c_helpers import (
    RELATION_HOLD_DECISION_ID,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_proof


def _id(identifier_type: type, suffix: int):
    return identifier_type.parse(
        f"00000000-0000-4000-8000-{suffix:012d}"
    )


PROPOSAL_2_ID = _id(EditorialRelationProposalId, 4811)
PROPOSAL_2_V1_ID = _id(EditorialRelationProposalVersionId, 4812)
PROPOSAL_V2_ID = _id(EditorialRelationProposalVersionId, 4813)
PROPOSAL_V3_ID = _id(EditorialRelationProposalVersionId, 4814)
UNRETAINED_HYPOTHESIS_ID = _id(IntegratedHypothesisVersionId, 4815)
ALT_HOLD_DECISION_ID = _id(EditorialRelationDecisionId, 4816)


def test_relation_proposal_version_advances_exactly_and_stale_extension_fails(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    first_request = relation_proposal_request(state)
    with open_relation_system(state) as system:
        first = system.relations.propose(
            first_request, proof=extraction_proof()
        )
        second_request = replace(
            first_request,
            proposal_version_id=PROPOSAL_V2_ID,
            version_number=2,
            expected_previous_version_id=first.proposal_version_id,
            statement=(
                "The two admitted entities remain in the same governed process "
                "after editorial review."
            ),
            confidence_basis_points=9_200,
            idempotency_key="relation-proposal-v2",
        )
        second = system.relations.propose(
            second_request, proof=extraction_proof()
        )
        assert second.version_number == 2
        assert second.previous_proposal_version_id == first.proposal_version_id
        assert system.relations.proposal(
            first.proposal_id, proof=extraction_proof()
        ).proposal_version_id == second.proposal_version_id
        assert system.relations.proposal_version(
            first.proposal_version_id, proof=extraction_proof()
        ).proposal_version_id == first.proposal_version_id

        stale = replace(
            second_request,
            proposal_version_id=PROPOSAL_V3_ID,
            version_number=3,
            expected_previous_version_id=first.proposal_version_id,
            idempotency_key="relation-proposal-stale-v3",
        )
        with pytest.raises(
            EditorialRelationStaleDecision, match="does not extend the current head"
        ):
            system.relations.propose(stale, proof=extraction_proof())


def test_decided_relation_proposal_cannot_receive_a_new_version(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    first_request = relation_proposal_request(state)
    with open_relation_system(state) as system:
        first = system.relations.propose(
            first_request, proof=extraction_proof()
        )
        system.relations.decide(
            relation_decision_request(
                first,
                action=EditorialRelationDecisionAction.HOLD,
                decision_id=RELATION_HOLD_DECISION_ID,
                key="relation-version-hold-v1",
            ),
            proof=extraction_proof(),
        )
        second_request = replace(
            first_request,
            proposal_version_id=PROPOSAL_V2_ID,
            version_number=2,
            expected_previous_version_id=first.proposal_version_id,
            statement="A decided proposal must not silently change.",
            idempotency_key="relation-version-after-decision-v2",
        )
        with pytest.raises(
            EditorialRelationStateError, match="decided relation proposal"
        ):
            system.relations.propose(second_request, proof=extraction_proof())


def test_equivalent_stable_relation_semantics_cannot_allocate_another_proposal(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    first_request = relation_proposal_request(state)
    with open_relation_system(state) as system:
        system.relations.propose(first_request, proof=extraction_proof())
        collision = replace(
            first_request,
            proposal_id=PROPOSAL_2_ID,
            proposal_version_id=PROPOSAL_2_V1_ID,
            idempotency_key="relation-proposal-semantic-collision",
        )
        with pytest.raises(
            EditorialRelationSemanticCollision, match="semantics"
        ):
            system.relations.propose(collision, proof=extraction_proof())


def test_relation_proposal_version_identity_cannot_be_reused(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    first_request = relation_proposal_request(state)
    with open_relation_system(state) as system:
        system.relations.propose(first_request, proof=extraction_proof())
        reused = replace(
            first_request,
            proposal_id=PROPOSAL_2_ID,
            statement="A different proposal cannot reuse a retained version ID.",
            producer=replace(
                first_request.producer,
                producer_version="fixture-increment-4c-v2",
            ),
            idempotency_key="relation-proposal-version-id-reuse",
        )
        with pytest.raises(EditorialRelationIdentifierReuse):
            system.relations.propose(reused, proof=extraction_proof())


def test_unretained_event_hypothesis_endpoint_fails_closed(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    base = relation_proposal_request(state)
    predicate = EditorialPredicateCode.ABOUT_EVENT
    contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(predicate)
    request = replace(
        base,
        proposal_id=PROPOSAL_2_ID,
        proposal_version_id=PROPOSAL_2_V1_ID,
        predicate=predicate,
        predicate_contract_digest=contract.digest,
        object=EventHypothesisRelationEndpoint(
            hypothesis_version_id=UNRETAINED_HYPOTHESIS_ID
        ),
        statement="An arbitrary hypothesis UUID cannot become relation authority.",
        idempotency_key="relation-unretained-hypothesis-v1",
    )
    with open_relation_system(state) as system:
        with pytest.raises(
            EditorialRelationStateError,
            match="no retained workflow authority",
        ):
            system.relations.propose(request, proof=extraction_proof())
