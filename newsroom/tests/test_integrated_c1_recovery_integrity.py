from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    UtcTimestamp,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.integrated import (
    CandidateAdmissionOutcome,
    IntegratedRetrievalContextId,
    StoryCandidateVersionId,
)

from .integrated_c1_helpers import (
    SECOND_PROPOSAL_ID,
    candidate_request,
    proof,
)
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    sql = str(row[0])
    conn.execute(f'DROP TRIGGER "{name}"')
    return sql


def test_recovery_equivalent_context_dedup_reopens_exactly(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    recovered_context = replace(
        graph.context,
        context_id=IntegratedRetrievalContextId.new(),
    )
    system = _open_candidate_system(database, state, graph)
    try:
        admitted = system.candidates.admit(
            candidate_request(graph.context),
            context=graph.context,
            manifest=state.manifest,
            proof=proof(),
        )
        deduplicated = system.candidates.admit(
            candidate_request(
                recovered_context,
                proposal_id=SECOND_PROPOSAL_ID,
                key="integrated-recovery-context-deduplicate",
            ),
            context=recovered_context,
            manifest=state.manifest,
            proof=proof(),
        )
        assert admitted.outcome is CandidateAdmissionOutcome.ADMITTED
        assert deduplicated.outcome is CandidateAdmissionOutcome.DEDUPLICATED
        assert deduplicated.candidate_id == admitted.candidate_id
        assert deduplicated.candidate_version_id == admitted.candidate_version_id
        assert deduplicated.retrieval_context_id == recovered_context.context_id
    finally:
        system.close()

    reopened = _open_candidate_system(database, state, graph)
    try:
        assert reopened.candidates.context(
            recovered_context.context_id,
            proof=proof(),
        ) == recovered_context
    finally:
        reopened.close()


def test_schema_v5_rejects_candidate_version_without_creation_authority(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
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

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM story_candidate_versions"
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row["canonical_bytes"]).decode("utf-8"))
        new_version_id = StoryCandidateVersionId.new()
        value["candidate_version_id"] = str(new_version_id)
        value["version_number"] = 2
        canonical = canonical_json_bytes(value)
        conn.execute(
            "INSERT INTO story_candidate_versions("
            "candidate_version_id,candidate_id,version_number,fixture_id,"
            "signal_id,lead_id,hypothesis_version_id,route,"
            "hypothesis_trust_scope,retrieval_context_id,manifest_digest,"
            "canonical_bytes,canonical_digest,recorded_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(new_version_id),
                str(row["candidate_id"]),
                2,
                str(row["fixture_id"]),
                str(row["signal_id"]),
                str(row["lead_id"]),
                str(row["hypothesis_version_id"]),
                str(row["route"]),
                str(row["hypothesis_trust_scope"]),
                str(row["retrieval_context_id"]),
                str(row["manifest_digest"]),
                canonical,
                digest_bytes(canonical),
                str(row["recorded_at"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="one exact ADMITTED immutable version",
    ):
        _open_candidate_system(database, state, graph)


def test_decision_time_must_equal_authority_event_time(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
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

    rewritten_time = UtcTimestamp.parse(
        "2030-01-01T00:00:00.000000Z"
    ).to_text()
    conn = sqlite3.connect(database)
    try:
        triggers = tuple(
            _disable_trigger(conn, name)
            for name in (
                "immutable_story_candidate_update",
                "immutable_story_candidate_version_update",
                "immutable_candidate_admission_decision_update",
            )
        )
        conn.execute(
            "UPDATE story_candidates SET created_at=?",
            (rewritten_time,),
        )
        conn.execute(
            "UPDATE story_candidate_versions SET recorded_at=?",
            (rewritten_time,),
        )
        conn.execute(
            "UPDATE candidate_admission_decisions SET recorded_at=?",
            (rewritten_time,),
        )
        for trigger in triggers:
            conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="exact authority event|recorded_at",
    ):
        _open_candidate_system(database, state, graph)
