from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from newsroom.relations import (
    EditorialRelationDecision,
    EditorialRelationDecisionAction,
    EditorialRelationProposalVersion,
    EditorialRelationStaleDecision,
)

from .editorial_relation_4c_helpers import (
    RELATION_ASSERTION_ID,
    RELATION_HOLD_DECISION_ID,
    RELATION_SECOND_DECISION_ID,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
from .extraction_4a_helpers import extraction_proof


def test_concurrent_identical_relation_proposals_commit_once_and_replay(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    request = relation_proposal_request(state)
    barrier = Barrier(2)
    with open_relation_system(state) as system:
        def propose() -> EditorialRelationProposalVersion:
            barrier.wait(timeout=5)
            return system.relations.propose(request, proof=extraction_proof())

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=15)
                for future in (executor.submit(propose), executor.submit(propose))
            ]

        assert {item.canonical_digest for item in results} == {
            results[0].canonical_digest
        }
        assert sorted(item.replayed for item in results) == [False, True]


def test_concurrent_identical_relation_decisions_commit_once_and_replay(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    barrier = Barrier(2)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        request = relation_decision_request(
            proposal,
            action=EditorialRelationDecisionAction.HOLD,
            decision_id=RELATION_HOLD_DECISION_ID,
            key="relation-concurrent-identical-hold-v1",
        )

        def decide() -> EditorialRelationDecision:
            barrier.wait(timeout=5)
            return system.relations.decide(request, proof=extraction_proof())

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=15)
                for future in (executor.submit(decide), executor.submit(decide))
            ]

        assert {item.canonical_digest for item in results} == {
            results[0].canonical_digest
        }
        assert sorted(item.replayed for item in results) == [False, True]


def test_concurrent_incompatible_relation_decisions_fail_closed(
    tmp_path: Path,
) -> None:
    state = seed_relation_fixture(tmp_path)
    barrier = Barrier(2)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        requests = (
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.HOLD,
                decision_id=RELATION_HOLD_DECISION_ID,
                key="relation-concurrent-hold-v1",
            ),
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.UNRESOLVED,
                decision_id=RELATION_SECOND_DECISION_ID,
                key="relation-concurrent-unresolved-v1",
            ),
        )

        def decide(request):
            barrier.wait(timeout=5)
            return system.relations.decide(request, proof=extraction_proof())

        results: list[EditorialRelationDecision] = []
        failures: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(decide, request) for request in requests]
            for future in futures:
                try:
                    results.append(future.result(timeout=15))
                except BaseException as exc:  # asserted below
                    failures.append(exc)

        assert len(results) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], EditorialRelationStaleDecision)
        current = system.relations.decision(
            proposal.proposal_id, proof=extraction_proof()
        )
        assert current is not None
        assert current.decision_id == results[0].decision_id
