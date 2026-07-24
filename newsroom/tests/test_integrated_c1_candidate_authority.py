from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import digest_canonical
from newsroom.authority._integrated_system import _open_candidate_with_adapter
from newsroom.integrated import (
    CandidateAdmissionOutcome,
    CandidateAdmissionRequest,
    IntegratedStateError,
)
from newsroom.projection.neo4j import Neo4jIdentityConflict

from .authority_helpers import FIXED_NOW
from .integrated_c1_helpers import (
    PROPOSAL_ID,
    SECOND_PROPOSAL_ID,
    IntegratedFixtureState,
    IntegratedGraphState,
    authenticator,
    authorizer,
    build_active_graph_context,
    candidate_request,
    event_policy,
    proof,
    seed_fixture_authority,
)
from .projection_b1_helpers import projection_contracts, projection_read_policy


def _open_candidate_system(
    database: Path,
    state: IntegratedFixtureState,
    graph: IntegratedGraphState,
):
    return _open_candidate_with_adapter(
        path=database,
        registry=state.commands,
        payload_schemas=state.schemas,
        contracts=projection_contracts(),
        authenticator=authenticator(),
        authorizer=authorizer(),
        event_read_policy=event_policy(),
        projection_read_policy=projection_read_policy(),
        adapter=graph.adapter,
        clock=lambda: FIXED_NOW,
    )


def _seed(tmp_path: Path) -> tuple[Path, IntegratedFixtureState, IntegratedGraphState]:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    state = seed_fixture_authority(database, object_root=object_root)
    graph = build_active_graph_context(
        database,
        state,
        object_root=object_root,
    )
    return database, state, graph


def test_fixture_traverses_authority_graph_hydration_and_candidate_admission(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    system = _open_candidate_system(database, state, graph)
    try:
        request = candidate_request(graph.context)
        admitted = system.candidates.admit(
            request,
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
        assert admitted.outcome is CandidateAdmissionOutcome.ADMITTED
        assert admitted.fixture_event_id == state.fixture_event_id
        assert admitted.admission_id == state.admission_id
        assert admitted.retrieval_context_digest == graph.context.context_digest
        assert admitted.manifest_digest == state.manifest.manifest_digest

        before_replay = system.events.after(0, limit=1000, proof=proof())
        replay = system.candidates.admit(
            request,
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
        assert replay == admitted
        assert system.events.after(
            0,
            limit=1000,
            proof=proof(),
        ) == before_replay

        duplicate = system.candidates.admit(
            candidate_request(
                graph.context,
                proposal_id=SECOND_PROPOSAL_ID,
                key="integrated-candidate-deduplicate",
            ),
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
        assert duplicate.outcome is CandidateAdmissionOutcome.DEDUPLICATED
        assert duplicate.candidate_id == admitted.candidate_id
        assert duplicate.candidate_version_id == admitted.candidate_version_id
        assert duplicate.decision_id != admitted.decision_id

        candidate_events = tuple(
            event
            for event in system.events.after(0, limit=1000, proof=proof())
            if event.event_type == "candidate.admission.decided"
        )
        assert len(candidate_events) == 2
        assert all(
            event.aggregate_type == "candidate_admission_proposal"
            and event.trust_scope == "ADMITTED"
            for event in candidate_events
        )
    finally:
        system.close()

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM integrated_retrieval_contexts"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM story_candidates"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM story_candidate_versions"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM candidate_admission_decisions"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM integrated_exact_index_entries"
        ).fetchone()[0] == len(graph.context.exact_index)
    finally:
        connection.close()

    # Reopening runs the complete retained-context/Candidate integrity audit.
    reopened = _open_candidate_system(database, state, graph)
    reopened.close()


def test_stale_context_digest_cannot_commit_candidate_authority(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        stale = CandidateAdmissionRequest(
            proposal_id=PROPOSAL_ID,
            route=candidate_request(graph.context).route,
            fixture_id=state.manifest.fixture_id,
            expected_context_digest=digest_canonical(
                {"stale": graph.context.context_digest}
            ),
            idempotency_key="integrated-stale-context",
        )
        with pytest.raises(
            IntegratedStateError,
            match="exact retrieval context digest",
        ):
            system.candidates.admit(
                stale,
                context=graph.context,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()


def test_current_graph_loss_cannot_be_treated_as_no_prior_match(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    graph.adapter.deliveries.clear()
    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(
            Neo4jIdentityConflict,
            match="current Neo4j read differs",
        ):
            system.candidates.admit(
                candidate_request(graph.context),
                context=graph.context,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()


def test_graph_reconciliation_mismatch_blocks_before_candidate_commit(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    graph.adapter.reconciliation_mismatch = True
    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(Neo4jIdentityConflict, match="differs"):
            system.candidates.admit(
                candidate_request(graph.context),
                context=graph.context,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()
