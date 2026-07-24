from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority._integrated_system import _open_candidate_with_adapter
from newsroom.integrated import (
    CandidateAdmissionRequest,
    CandidateRoute,
    IntegratedTriageProposalId,
)

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


def _seed(
    tmp_path: Path,
) -> tuple[Path, IntegratedFixtureState, IntegratedGraphState]:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    state = seed_fixture_authority(database, object_root=object_root)
    graph = build_active_graph_context(
        database,
        state,
        object_root=object_root,
    )
    return database, state, graph


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    sql = str(row[0])
    conn.execute(f'DROP TRIGGER "{name}"')
    return sql


def _admit_primary(
    database: Path,
    state: IntegratedFixtureState,
    graph: IntegratedGraphState,
) -> None:
    system = _open_candidate_system(database, state, graph)
    try:
        system.candidates.admit(
            candidate_request(graph.context),
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
    finally:
        system.close()


def test_reopen_rejects_candidate_collision_identity_tampering(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    _admit_primary(database, state, graph)

    conn = sqlite3.connect(database)
    try:
        trigger = _disable_trigger(conn, "immutable_story_candidate_update")
        conn.execute(
            "UPDATE story_candidates SET semantic_collision_digest=?",
            (digest_canonical({"tampered": "collision"}),),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="semantic collision|candidate identity",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_candidate_version_manifest_tampering(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    _admit_primary(database, state, graph)

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        trigger = _disable_trigger(
            conn,
            "immutable_story_candidate_version_update",
        )
        row = conn.execute(
            "SELECT candidate_version_id,canonical_bytes "
            "FROM story_candidate_versions"
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row["canonical_bytes"]).decode("utf-8"))
        assert isinstance(value["manifest"], dict)
        value["manifest"]["geography"] = "tampered_geography"
        canonical = canonical_json_bytes(value)
        conn.execute(
            "UPDATE story_candidate_versions "
            "SET canonical_bytes=?,canonical_digest=? "
            "WHERE candidate_version_id=?",
            (
                canonical,
                digest_bytes(canonical),
                str(row["candidate_version_id"]),
            ),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="manifest|candidate version",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_decision_cross_wired_to_another_candidate_version(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    system = _open_candidate_system(database, state, graph)
    try:
        first = system.candidates.admit(
            candidate_request(graph.context),
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
        second_request = CandidateAdmissionRequest(
            proposal_id=IntegratedTriageProposalId.new(),
            route=CandidateRoute.DEVELOPMENT,
            fixture_id=state.manifest.fixture_id,
            expected_context_digest=graph.context.context_digest,
            idempotency_key="integrated-second-candidate",
        )
        second = system.candidates.admit(
            second_request,
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
        assert second.candidate_id != first.candidate_id
    finally:
        system.close()

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        trigger = _disable_trigger(
            conn,
            "immutable_candidate_admission_decision_update",
        )
        row = conn.execute(
            "SELECT decision_id,canonical_bytes "
            "FROM candidate_admission_decisions WHERE decision_id=?",
            (str(first.decision_id),),
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row["canonical_bytes"]).decode("utf-8"))
        value["candidate_version_id"] = str(second.candidate_version_id)
        canonical = canonical_json_bytes(value)
        conn.execute(
            "UPDATE candidate_admission_decisions "
            "SET candidate_version_id=?,canonical_bytes=?,canonical_digest=? "
            "WHERE decision_id=?",
            (
                str(second.candidate_version_id),
                canonical,
                digest_bytes(canonical),
                str(first.decision_id),
            ),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="candidate version|candidate identity|cross-record",
    ):
        _open_candidate_system(database, state, graph)
