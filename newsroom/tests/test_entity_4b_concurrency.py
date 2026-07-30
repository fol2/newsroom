from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

import pytest

from newsroom.entities import (
    EntityResolutionDecision,
    EntityResolutionDecisionAction,
    EntityStaleDecision,
)

from .entity_4b_helpers import (
    EN_MENTION_ID,
    decision_request,
    mention_request,
    new_entity_proposal_request,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof


def _seed_resolution_proposal(system, state):
    system.entities.admit_mention(
        mention_request(
            state.en_source,
            mention_id=EN_MENTION_ID,
            language="en-GB",
            key="concurrency-mention-en-v1",
        ),
        proof=extraction_proof(),
    )
    return system.entities.propose_resolution(
        new_entity_proposal_request(
            state, key="concurrency-resolution-proposal-v1"
        ),
        proof=extraction_proof(),
    )


def test_concurrent_incompatible_resolution_decisions_fail_closed(tmp_path) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal = _seed_resolution_proposal(system, state)
        barrier = Barrier(2)
        requests = (
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.HOLD,
                key="concurrency-hold-v1",
            ),
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.UNRESOLVED,
                key="concurrency-unresolved-v1",
            ),
        )

        def decide(request):
            barrier.wait(timeout=5)
            return system.entities.decide_resolution(
                request, proof=extraction_proof()
            )

        results: list[EntityResolutionDecision] = []
        failures: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(decide, request) for request in requests]
            for future in futures:
                try:
                    results.append(future.result(timeout=10))
                except BaseException as exc:  # asserted below
                    failures.append(exc)

        assert len(results) == len(failures) == 1
        assert isinstance(failures[0], EntityStaleDecision)
        current = system.entities.decision(
            proposal.proposal_id, proof=extraction_proof()
        )
        assert current is not None
        assert current.decision_id == results[0].decision_id
        assert current.action in {
            EntityResolutionDecisionAction.HOLD,
            EntityResolutionDecisionAction.UNRESOLVED,
        }

    conn = sqlite3.connect(state.extraction.database)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_resolution_decisions "
            "WHERE resolution_proposal_id=?",
            (str(proposal.proposal_id),),
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_concurrent_identical_decision_is_one_commit_plus_exact_replay(
    tmp_path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal = _seed_resolution_proposal(system, state)
        request = decision_request(
            proposal,
            action=EntityResolutionDecisionAction.HOLD,
            key="concurrency-identical-hold-v1",
        )
        barrier = Barrier(2)

        def decide():
            barrier.wait(timeout=5)
            return system.entities.decide_resolution(
                request, proof=extraction_proof()
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(decide) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]

        assert results[0].canonical_digest == results[1].canonical_digest
        assert sorted(item.replayed for item in results) == [False, True]

    conn = sqlite3.connect(state.extraction.database)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_resolution_decisions "
            "WHERE resolution_proposal_id=?",
            (str(proposal.proposal_id),),
        ).fetchone()[0] == 1
    finally:
        conn.close()
