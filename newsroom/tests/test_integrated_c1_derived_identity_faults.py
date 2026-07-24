from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    EventId,
    UtcTimestamp,
    digest_canonical,
)
from newsroom.integrated import StoryCandidateId

from .test_integrated_c1_context_integrity_faults import (
    _insert_context,
    _open_candidate_system,
    _seed,
)


def test_reopen_rejects_exact_index_source_event_rebinding(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    value = deepcopy(graph.context.canonical_value())
    nodes = value["nodes"]
    index = value["exact_index"]
    assert isinstance(nodes, list) and nodes
    assert isinstance(index, list) and index

    selected = nodes[0]
    assert isinstance(selected, dict)
    canonical_id = selected["canonical_id"]
    fake_event_id = str(EventId.new())
    fake_event_digest = digest_canonical({"tampered": "first-source"})
    selected["first_source_event_id"] = fake_event_id
    selected["first_source_event_digest"] = fake_event_digest

    matching = [
        item
        for item in index
        if isinstance(item, dict) and item.get("canonical_id") == canonical_id
    ]
    assert len(matching) == 1
    matching[0]["first_source_event_id"] = fake_event_id
    matching[0]["first_source_event_digest"] = fake_event_digest
    _insert_context(database, graph, value)

    with pytest.raises(
        AuthorityPersistenceError,
        match="exact index|source event|ledger",
    ):
        _open_candidate_system(database, state, graph)


def test_reopen_rejects_orphan_candidate_identity_injection(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    conn = sqlite3.connect(database)
    try:
        conn.execute(
            "INSERT INTO story_candidates("
            "candidate_id,semantic_collision_digest,created_at) VALUES(?,?,?)",
            (
                str(StoryCandidateId.new()),
                digest_canonical({"injected": "candidate"}),
                UtcTimestamp.now().to_text(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="candidate identity|ADMITTED|immutable version",
    ):
        _open_candidate_system(database, state, graph)
