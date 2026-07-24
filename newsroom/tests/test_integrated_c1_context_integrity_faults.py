from __future__ import annotations

from copy import deepcopy
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

from .authority_helpers import FIXED_NOW
from .integrated_c1_helpers import (
    IntegratedFixtureState,
    IntegratedGraphState,
    authenticator,
    authorizer,
    build_active_graph_context,
    event_policy,
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


def _insert_context(
    database: Path,
    graph: IntegratedGraphState,
    canonical_value: dict[str, object],
) -> None:
    context = graph.context
    canonical = canonical_json_bytes(canonical_value)
    digest = digest_bytes(canonical)
    conn = sqlite3.connect(database)
    try:
        conn.execute(
            "INSERT INTO integrated_retrieval_contexts("
            "context_id,context_digest,fixture_id,fixture_aggregate_type,"
            "fixture_aggregate_id,fixture_event_id,admission_id,generation_id,"
            "projected_through_ledger_seq,hydration_access_decision_id,"
            "manifest_digest,retrieval_version,canonical_bytes,canonical_digest,"
            "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(context.context_id),
                digest,
                str(context.fixture_id),
                "integrated_fixture",
                str(context.fixture_aggregate_id),
                str(context.fixture_event_id),
                str(context.admission_id),
                str(context.metadata.generation_id),
                context.metadata.contiguous_ledger_seq,
                str(context.hydration_access_decision_id),
                context.manifest_digest,
                context.retrieval_version,
                canonical,
                digest,
                context.recorded_at.to_text(),
            ),
        )
        for entry in context.exact_index:
            value = entry.canonical_value()
            entry_canonical = canonical_json_bytes(value)
            conn.execute(
                "INSERT INTO integrated_exact_index_entries("
                "context_id,canonical_id,node_type,first_ledger_seq,"
                "first_source_event_id,first_source_event_digest,"
                "canonical_bytes,canonical_digest) VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(context.context_id),
                    entry.canonical_id,
                    entry.node_type.value,
                    entry.first_ledger_seq,
                    entry.first_source_event_id,
                    entry.first_source_event_digest,
                    entry_canonical,
                    digest_bytes(entry_canonical),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_reopen_rehydrates_and_rejects_non_active_context_contract(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    value = deepcopy(graph.context.canonical_value())
    metadata = value["metadata"]
    assert isinstance(metadata, dict)
    metadata["authority_selection"] = "exact-generation"
    _insert_context(database, graph, value)

    with pytest.raises(
        AuthorityPersistenceError,
        match="rehydrated|authority-selected ACTIVE",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_context_hydration_policy_and_blob_rebinding(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    value = deepcopy(graph.context.canonical_value())
    value["hydration_policy_contract_digest"] = digest_canonical(
        {"tampered": "hydration-policy"}
    )
    value["hydrated_blob_digest"] = digest_canonical(
        {"tampered": "hydrated-blob"}
    )
    _insert_context(database, graph, value)

    with pytest.raises(
        AuthorityPersistenceError,
        match="rehydrated|hydration|blob|fixture authority",
    ):
        _open_candidate_system(database, state, graph)
