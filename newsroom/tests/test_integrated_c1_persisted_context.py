from __future__ import annotations

from pathlib import Path

from newsroom.integrated import CandidateAdmissionOutcome

from .authority_helpers import FIXED_NOW
from .integrated_c1_helpers import (
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
from newsroom.authority._integrated_system import _open_candidate_with_adapter


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


def test_retained_context_replays_after_candidate_system_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    state = seed_fixture_authority(database, object_root=object_root)
    graph = build_active_graph_context(
        database,
        state,
        object_root=object_root,
    )
    request = candidate_request(graph.context)

    system = _open_candidate_system(database, state, graph)
    try:
        admitted = system.candidates.admit(
            request,
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
        assert admitted.outcome is CandidateAdmissionOutcome.ADMITTED
    finally:
        system.close()

    reopened = _open_candidate_system(database, state, graph)
    try:
        retained = reopened.candidates.context(
            graph.context.context_id,
            proof=proof(),
        )
        assert retained == graph.context

        before_replay = reopened.events.after(0, limit=1000, proof=proof())
        replay = reopened.candidates.admit(
            request,
            context=retained,
            manifest=state.manifest,
            proof=proof(),
        )
        assert replay == admitted
        assert reopened.events.after(
            0,
            limit=1000,
            proof=proof(),
        ) == before_replay
    finally:
        reopened.close()
