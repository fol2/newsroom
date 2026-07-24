from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    UtcTimestamp,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.integrated import IntegratedRetrievalContextId

from .authority_helpers import FIXED_NOW
from .integrated_c1_helpers import (
    build_active_graph_context,
    candidate_request,
    proof,
    seed_fixture_authority,
)
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)
from .test_integrated_c1_context_integrity_faults import _insert_context


LATER = UtcTimestamp(FIXED_NOW.value + timedelta(minutes=1))


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    sql = str(row[0])
    conn.execute(f'DROP TRIGGER "{name}"')
    return sql


def _admit_primary(database, state, graph) -> None:
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


def test_reopen_rejects_context_served_before_generation_activation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    state = seed_fixture_authority(
        database,
        object_root=object_root,
        clock=lambda: FIXED_NOW,
    )
    graph = build_active_graph_context(
        database,
        state,
        object_root=object_root,
        clock=lambda: LATER,
    )
    premature = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
        metadata=replace(
            graph.context.metadata,
            serving_time=FIXED_NOW,
        ),
    )
    _insert_context(
        database,
        replace(graph, context=premature),
        premature.canonical_value(),
    )

    with pytest.raises(
        AuthorityPersistenceError,
        match="ACTIVE projection evidence",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_context_time_rebound_from_hydration_decision(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    _admit_primary(database, state, graph)
    conn = sqlite3.connect(database)
    try:
        trigger = _disable_trigger(conn, "immutable_integrated_context_update")
        conn.execute(
            "UPDATE integrated_retrieval_contexts SET recorded_at=?",
            (LATER.to_text(),),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="hydration decision",
    ):
        _open_candidate_system(database, state, graph)


@pytest.mark.parametrize(
    ("table", "trigger"),
    (
        (
            "projection_generation_validations",
            "immutable_projection_generation_validation_update",
        ),
        (
            "projection_generation_promotions",
            "immutable_projection_generation_promotion_update",
        ),
    ),
)
def test_reopen_rejects_projection_evidence_recorded_after_serving(
    tmp_path: Path,
    table: str,
    trigger: str,
) -> None:
    database, state, graph = _seed(tmp_path)
    _admit_primary(database, state, graph)
    conn = sqlite3.connect(database)
    try:
        trigger_sql = _disable_trigger(conn, trigger)
        conn.execute(f'UPDATE "{table}" SET recorded_at=?', (LATER.to_text(),))
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="ACTIVE projection evidence|postdates serving",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_partial_hydration_rebinding(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    _admit_primary(database, state, graph)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        trigger = _disable_trigger(
            conn,
            "immutable_object_access_decisions_update",
        )
        row = conn.execute("SELECT * FROM object_access_decisions").fetchone()
        assert row is not None and int(row["allowed_bytes"]) > 1
        allowed = int(row["allowed_bytes"]) - 1
        cutoff = json.loads(bytes(row["state_cutoff_bytes"]).decode("utf-8"))
        canonical = json.loads(bytes(row["canonical_bytes"]).decode("utf-8"))
        cutoff["length"] = allowed
        cutoff_bytes = canonical_json_bytes(cutoff)
        cutoff_digest = digest_bytes(cutoff_bytes)
        canonical["allowed_bytes"] = allowed
        canonical["state_cutoff"] = cutoff
        canonical["state_cutoff_digest"] = cutoff_digest
        canonical_bytes = canonical_json_bytes(canonical)
        conn.execute(
            "UPDATE object_access_decisions SET allowed_bytes=?,"
            "state_cutoff_bytes=?,state_cutoff_digest=?,canonical_bytes=?,"
            "canonical_digest=?",
            (
                allowed,
                cutoff_bytes,
                cutoff_digest,
                canonical_bytes,
                digest_bytes(canonical_bytes),
            ),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="hydration decision",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_relation_rebound_from_ledger_authority(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    relations = list(graph.context.relations)
    relations[0] = replace(relations[0], principal_id="principal.tampered")
    tampered = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
        relations=tuple(relations),
    )
    _insert_context(
        database,
        replace(graph, context=tampered),
        tampered.canonical_value(),
    )

    with pytest.raises(
        AuthorityPersistenceError,
        match="graph relation.*ledger authority",
    ):
        _open_candidate_system(database, state, graph)
