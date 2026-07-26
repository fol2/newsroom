from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthenticationProof,
    AuthorityPersistenceError,
    ObjectAdmissionId,
    UtcTimestamp,
)
from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.persistence import IdempotencyConflict
from newsroom.projection.neo4j import Neo4jReadError
from newsroom.retrieval import (
    FindRelatedEventCandidatesRequest,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalBranch,
    RetrievalContextV2Id,
    RetrievalOutcome,
    RetrievalRequestId,
)

from .complete_projection_2b_helpers import COMPLETE_NOW, complete_scopes, proof
from .relation_2a_helpers import open_fixture_object_system, proof as relation_proof
from .retrieval_2c_helpers import (
    MemoryHybridRetrievalAdapter,
    append_retrieval_source_event,
    block_active_retrieval_generation,
    open_retrieval_test_system,
    retire_active_retrieval_generation,
    seed_active_retrieval_authority,
)


_REQUEST_ID = RetrievalRequestId.parse(
    "00000000-0000-4000-8000-000000002401"
)
_CONTEXT_ID = RetrievalContextV2Id.parse(
    "00000000-0000-4000-8000-000000002402"
)


def request(
    *,
    key: str = "retrieval-2c-request",
    request_id: RetrievalRequestId = _REQUEST_ID,
    context_id: RetrievalContextV2Id = _CONTEXT_ID,
    fixture_id: str | None = None,
    query_valid_time: UtcTimestamp = COMPLETE_NOW,
) -> FindRelatedEventCandidatesRequest:
    fixture = INTEGRATED_FIXTURE_V2_RETRIEVAL
    return FindRelatedEventCandidatesRequest(
        request_id=request_id,
        context_id=context_id,
        fixture_id=fixture.fixture_id if fixture_id is None else fixture_id,
        query_revision_id=fixture.query_revision_id,
        query_hypothesis_version_id=fixture.query_hypothesis_version_id,
        query_valid_time=query_valid_time,
        idempotency_key=key,
    )


def setup(tmp_path: Path, *, adapter=None, scopes=None):
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    selected = adapter or MemoryHybridRetrievalAdapter()
    system = open_retrieval_test_system(
        database,
        object_root=object_root,
        adapter=selected,
        scopes=scopes,
    )
    return database, object_root, selected, system


def test_find_related_event_candidates_persists_authoritative_context_and_replays(
    tmp_path: Path,
) -> None:
    database, _objects, adapter, system = setup(tmp_path)
    try:
        first = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert first.outcome is RetrievalOutcome.COMPLETE
        assert first.replayed is False
        assert first.context is not None
        assert first.context.projection.generation_state.value == "ACTIVE"
        assert tuple(item.branch for item in first.context.branches) == tuple(
            RetrievalBranch
        )
        assert first.context.retained_candidates[0].candidate_version_id == (
            INTEGRATED_FIXTURE_V2_RETRIEVAL.prior_candidate_version_id
        )
        assert tuple(
            item.passage_id for item in first.context.hydrated_passages
        ) == ("ifv2-prior-en", "ifv2-prior-zh-hk")
        assert all(
            item.rights_state == "PERMITTED"
            and item.lifecycle_state == "ACTIVE"
            for item in first.context.hydrated_passages
        )
        assert adapter.call_count == 1

        replay = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert replay.replayed is True
        assert replay.result_digest == first.result_digest
        assert adapter.call_count == 1

        with sqlite3.connect(database) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM hybrid_retrieval_attempts"
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM hybrid_retrieval_contexts_v2"
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM hybrid_retrieval_context_hydrations"
            ).fetchone()[0] == 2
            assert conn.execute(
                "SELECT COUNT(*) FROM object_access_decisions"
            ).fetchone()[0] >= 2
    finally:
        system.close()
    assert adapter.closed is True


def test_authentication_and_scope_are_checked_before_graph_lookup(
    tmp_path: Path,
) -> None:
    restricted = frozenset(
        scope
        for scope in complete_scopes()
        if scope != "authority.retrieval.read"
    )
    _database, _objects, adapter, system = setup(
        tmp_path,
        scopes=restricted,
    )
    try:
        with pytest.raises(PermissionError):
            system.retrieval.find_related_event_candidates(
                request(), proof=proof()
            )
        assert adapter.call_count == 0
        with pytest.raises(PermissionError):
            system.retrieval.find_related_event_candidates(
                request(),
                proof=AuthenticationProof(
                    method="STATIC_TOKEN", credential="wrong"
                ),
            )
        assert adapter.call_count == 0
    finally:
        system.close()


def test_caller_scope_mismatch_is_retained_policy_blocked_without_graph_lookup(
    tmp_path: Path,
) -> None:
    database, _objects, adapter, system = setup(tmp_path)
    try:
        result = system.retrieval.find_related_event_candidates(
            request(fixture_id="00000000-0000-4000-8000-000000009999"),
            proof=proof(),
        )
        assert result.outcome is RetrievalOutcome.POLICY_BLOCKED
        assert result.failure is not None
        assert result.failure.reason_code == "FIXTURE_ID_NOT_ALLOWED"
        assert adapter.call_count == 0
        with sqlite3.connect(database) as conn:
            row = conn.execute(
                "SELECT outcome,failure_code,generation_id "
                "FROM hybrid_retrieval_attempts"
            ).fetchone()
            assert row == ("POLICY_BLOCKED", "FIXTURE_ID_NOT_ALLOWED", None)
    finally:
        system.close()


def test_future_query_valid_time_is_policy_blocked_before_graph_lookup(
    tmp_path: Path,
) -> None:
    _database, _objects, adapter, system = setup(tmp_path)
    try:
        result = system.retrieval.find_related_event_candidates(
            request(
                query_valid_time=UtcTimestamp.parse(
                    "2042-03-12T12:00:00.000001Z"
                )
            ),
            proof=proof(),
        )
        assert result.outcome is RetrievalOutcome.POLICY_BLOCKED
        assert result.failure is not None
        assert result.failure.reason_code == "QUERY_VALID_TIME_IN_FUTURE"
        assert adapter.call_count == 0
    finally:
        system.close()


def test_missing_active_generation_is_unavailable_not_no_match(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    retire_active_retrieval_generation(database, object_root=object_root)
    adapter = MemoryHybridRetrievalAdapter()
    system = open_retrieval_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        result = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert result.outcome is RetrievalOutcome.UNAVAILABLE
        assert result.failure is not None
        assert result.failure.reason_code == "ACTIVE_PROJECTION_UNAVAILABLE"
        assert adapter.call_count == 0
    finally:
        system.close()


def test_source_advance_is_stale_not_no_match(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    append_retrieval_source_event(database, object_root=object_root)
    adapter = MemoryHybridRetrievalAdapter()
    system = open_retrieval_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        result = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert result.outcome is RetrievalOutcome.STALE
        assert result.failure is not None
        assert result.failure.reason_code == "RETRIEVAL_SOURCE_STALE"
        assert adapter.call_count == 0
    finally:
        system.close()


def test_complete_replay_rechecks_current_rights_and_never_returns_revoked_bytes(
    tmp_path: Path,
) -> None:
    database, object_root, _adapter, system = setup(tmp_path)
    try:
        first = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert first.outcome is RetrievalOutcome.COMPLETE
        assert first.context is not None
    finally:
        system.close()

    with sqlite3.connect(database) as conn:
        admission_id = conn.execute(
            "SELECT admission_id FROM integrated_fixture_v2_passage_objects "
            "WHERE passage_id='ifv2-prior-en'"
        ).fetchone()[0]
    objects = open_fixture_object_system(
        database,
        object_root=object_root,
    )
    try:
        objects.objects.revoke(
            ObjectAdmissionId.parse(str(admission_id)),
            reason_code="INCREMENT_2C_REPLAY_RIGHTS_REVOKED",
            idempotency_key="retrieval-2c-replay-revoke",
            proof=relation_proof(),
        )
    finally:
        objects.close()

    adapter = MemoryHybridRetrievalAdapter()
    reopened = open_retrieval_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        replay = reopened.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert replay.replayed is True
        assert replay.context is None
        assert replay.outcome is RetrievalOutcome.STALE
        assert replay.failure is not None
        assert replay.failure.reason_code == "RETRIEVAL_SOURCE_STALE"
        assert adapter.call_count == 0
    finally:
        reopened.close()


def test_replay_is_bound_to_the_original_principal(tmp_path: Path) -> None:
    database, object_root, _adapter, system = setup(tmp_path)
    try:
        first = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert first.outcome is RetrievalOutcome.COMPLETE
    finally:
        system.close()

    adapter = MemoryHybridRetrievalAdapter()
    other = open_retrieval_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
        principal_id="principal.beta",
    )
    try:
        with pytest.raises(
            PermissionError,
            match="original principal",
        ):
            other.retrieval.find_related_event_candidates(
                request(), proof=proof()
            )
        assert adapter.call_count == 0
    finally:
        other.close()


def test_graph_unavailability_is_explicit_and_idempotently_retained(
    tmp_path: Path,
) -> None:
    database, _objects, adapter, system = setup(
        tmp_path,
        adapter=MemoryHybridRetrievalAdapter(
            failure=Neo4jReadError("synthetic graph unavailable")
        ),
    )
    try:
        first = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert first.outcome is RetrievalOutcome.UNAVAILABLE
        assert first.failure is not None
        assert first.failure.reason_code == "NEO4J_RETRIEVAL_UNAVAILABLE"
        replay = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert replay.replayed is True
        assert replay.result_digest == first.result_digest
        assert adapter.call_count == 1
        with sqlite3.connect(database) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM hybrid_retrieval_contexts_v2"
            ).fetchone()[0] == 0
            row = conn.execute(
                "SELECT generation_id,projection_identity_digest,"
                "authority_watermark FROM hybrid_retrieval_attempts"
            ).fetchone()
            assert row[0] is not None
            assert row[1] is not None
            assert int(row[2]) > 0
    finally:
        system.close()

    reopened_adapter = MemoryHybridRetrievalAdapter()
    reopened = open_retrieval_test_system(
        database,
        object_root=_objects,
        adapter=reopened_adapter,
    )
    try:
        replay = reopened.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert replay.replayed is True
        assert replay.outcome is RetrievalOutcome.UNAVAILABLE
        assert reopened_adapter.call_count == 0
    finally:
        reopened.close()


def test_substituted_typed_adapter_query_identity_fails_closed(
    tmp_path: Path,
) -> None:
    class SubstitutedAdapter(MemoryHybridRetrievalAdapter):
        def run_bounded_hybrid_branches(self, **kwargs):
            executions = super().run_bounded_hybrid_branches(**kwargs)
            first = executions[0]
            altered_hits = tuple(
                replace(hit, query_id="caller-selected-query")
                for hit in first.hits
            )
            return (
                replace(
                    first,
                    query_id="caller-selected-query",
                    hits=altered_hits,
                ),
                *executions[1:],
            )

    _database, _objects, adapter, system = setup(
        tmp_path,
        adapter=SubstitutedAdapter(),
    )
    try:
        result = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert result.outcome is RetrievalOutcome.INCOMPLETE
        assert result.failure is not None
        assert result.failure.reason_code == "RETRIEVAL_CONTRACT_MISMATCH"
        assert adapter.call_count == 1
    finally:
        system.close()


def test_idempotency_key_cannot_be_rebound_to_new_request_identity(
    tmp_path: Path,
) -> None:
    _database, _objects, _adapter, system = setup(tmp_path)
    try:
        system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        with pytest.raises(IdempotencyConflict):
            system.retrieval.find_related_event_candidates(
                request(
                    request_id=RetrievalRequestId.new(),
                    context_id=RetrievalContextV2Id.new(),
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_normalized_context_tamper_fails_store_reopen(tmp_path: Path) -> None:
    database, object_root, _adapter, system = setup(tmp_path)
    try:
        system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
    finally:
        system.close()

    with sqlite3.connect(database) as conn:
        trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_hybrid_retrieval_context_update'"
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_hybrid_retrieval_context_update")
        conn.execute(
            "UPDATE hybrid_retrieval_contexts_v2 "
            "SET total_context_bytes=total_context_bytes+1"
        )
        conn.execute(trigger)

    with pytest.raises(
        AuthorityPersistenceError,
        match="retrieval context normalized total_context_bytes differs",
    ):
        reopened = open_retrieval_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )
        reopened.close()


def test_normalized_attempt_tamper_fails_store_reopen(tmp_path: Path) -> None:
    database, object_root, _adapter, system = setup(tmp_path)
    try:
        result = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert result.outcome is RetrievalOutcome.COMPLETE
    finally:
        system.close()

    with sqlite3.connect(database) as conn:
        trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_hybrid_retrieval_attempt_update'"
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_hybrid_retrieval_attempt_update")
        conn.execute(
            "UPDATE hybrid_retrieval_attempts "
            "SET tool_version='tampered-tool-version'"
        )
        conn.execute(trigger)

    with pytest.raises(
        AuthorityPersistenceError,
        match="retrieval attempt normalized tool_version differs",
    ):
        reopened = open_retrieval_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )
        reopened.close()


def test_normalized_hydration_tamper_fails_store_reopen(tmp_path: Path) -> None:
    database, object_root, _adapter, system = setup(tmp_path)
    try:
        result = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert result.outcome is RetrievalOutcome.COMPLETE
    finally:
        system.close()

    with sqlite3.connect(database) as conn:
        trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_hybrid_retrieval_hydration_update'"
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_hybrid_retrieval_hydration_update")
        conn.execute(
            "UPDATE hybrid_retrieval_context_hydrations "
            "SET rights_state='REVOKED' WHERE passage_id='ifv2-prior-en'"
        )
        conn.execute(trigger)

    with pytest.raises(
        AuthorityPersistenceError,
        match="retrieval hydration normalized rights_state differs",
    ):
        reopened = open_retrieval_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )
        reopened.close()


def test_access_decision_tamper_fails_store_reopen(tmp_path: Path) -> None:
    database, object_root, _adapter, system = setup(tmp_path)
    try:
        result = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert result.outcome is RetrievalOutcome.COMPLETE
    finally:
        system.close()

    with sqlite3.connect(database) as conn:
        trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_object_access_decisions_update'"
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_object_access_decisions_update")
        conn.execute(
            "UPDATE object_access_decisions SET allowed_bytes=allowed_bytes-1 "
            "WHERE access_decision_id=("
            "SELECT access_decision_id FROM hybrid_retrieval_context_hydrations "
            "ORDER BY passage_id LIMIT 1)"
        )
        conn.execute(trigger)

    with pytest.raises(AuthorityPersistenceError):
        reopened = open_retrieval_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )
        reopened.close()


def test_request_and_context_identities_cannot_rebind_or_repeat_graph_lookup(
    tmp_path: Path,
) -> None:
    _database, _objects, adapter, system = setup(tmp_path)
    try:
        first = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert first.outcome is RetrievalOutcome.COMPLETE
        assert adapter.call_count == 1

        with pytest.raises(IdempotencyConflict, match="identity conflicts"):
            system.retrieval.find_related_event_candidates(
                request(
                    key="retrieval-2c-new-key-same-request",
                    context_id=RetrievalContextV2Id.new(),
                ),
                proof=proof(),
            )
        with pytest.raises(IdempotencyConflict, match="identity conflicts"):
            system.retrieval.find_related_event_candidates(
                request(
                    key="retrieval-2c-new-key-same-context",
                    request_id=RetrievalRequestId.new(),
                ),
                proof=proof(),
            )
        assert adapter.call_count == 1
    finally:
        system.close()


def test_redigested_security_rebinding_fails_store_reopen(tmp_path: Path) -> None:
    database, object_root, _adapter, system = setup(tmp_path)
    try:
        result = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert result.outcome is RetrievalOutcome.COMPLETE
    finally:
        system.close()

    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        attempt = conn.execute(
            "SELECT * FROM hybrid_retrieval_attempts"
        ).fetchone()
        assert attempt is not None
        original_request = conn.execute(
            "SELECT * FROM authorization_requests WHERE request_digest=?",
            (attempt["authorization_request_digest"],),
        ).fetchone()
        original_decision = conn.execute(
            "SELECT * FROM authorization_decisions "
            "WHERE authorization_decision_id=?",
            (attempt["authorization_decision_id"],),
        ).fetchone()
        assert original_request is not None
        assert original_decision is not None

        request_value = json.loads(
            bytes(original_request["canonical_bytes"]).decode("utf-8")
        )
        request_value["operation_type"] = (
            "read:project.discovery:caller-selected-tool"
        )
        unsigned = dict(request_value)
        unsigned.pop("request_digest")
        rebound_request_digest = digest_canonical(unsigned)
        request_value["request_digest"] = rebound_request_digest
        request_bytes = canonical_json_bytes(request_value)
        conn.execute(
            "INSERT INTO authorization_requests("
            "request_digest,authentication_context_id,principal_id,"
            "authority_domain,operation_type,required_scope,canonical_bytes,"
            "canonical_record_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                rebound_request_digest,
                original_request["authentication_context_id"],
                original_request["principal_id"],
                original_request["authority_domain"],
                request_value["operation_type"],
                original_request["required_scope"],
                request_bytes,
                digest_bytes(request_bytes),
                original_request["recorded_at"],
            ),
        )

        rebound_decision_id = (
            "00000000-0000-4000-8000-000000002501"
        )
        decision_value = json.loads(
            bytes(original_decision["canonical_bytes"]).decode("utf-8")
        )
        decision_value["authorization_decision_id"] = rebound_decision_id
        decision_value["authorization_request_digest"] = (
            rebound_request_digest
        )
        decision_bytes = canonical_json_bytes(decision_value)
        conn.execute(
            "INSERT INTO authorization_decisions("
            "authorization_decision_id,authentication_context_id,"
            "authorization_request_digest,authorization_policy_version,"
            "effective_scopes,effective_scope_digest,allowed,reason_code,"
            "decided_at,canonical_bytes,canonical_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                rebound_decision_id,
                original_decision["authentication_context_id"],
                rebound_request_digest,
                original_decision["authorization_policy_version"],
                original_decision["effective_scopes"],
                original_decision["effective_scope_digest"],
                original_decision["allowed"],
                original_decision["reason_code"],
                original_decision["decided_at"],
                decision_bytes,
                digest_bytes(decision_bytes),
            ),
        )

        trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='immutable_hybrid_retrieval_attempt_update'"
        ).fetchone()[0]
        conn.execute("DROP TRIGGER immutable_hybrid_retrieval_attempt_update")
        attempt_value = json.loads(
            bytes(attempt["canonical_bytes"]).decode("utf-8")
        )
        attempt_value["authorization_request_digest"] = (
            rebound_request_digest
        )
        attempt_value["authorization_decision_id"] = rebound_decision_id
        attempt_bytes = canonical_json_bytes(attempt_value)
        conn.execute(
            "UPDATE hybrid_retrieval_attempts SET "
            "authorization_request_digest=?,authorization_decision_id=?,"
            "canonical_bytes=?,canonical_digest=?",
            (
                rebound_request_digest,
                rebound_decision_id,
                attempt_bytes,
                digest_bytes(attempt_bytes),
            ),
        )
        conn.execute(trigger)

    with pytest.raises(
        AuthorityPersistenceError,
        match="retrieval authorization request differs from authority",
    ):
        reopened = open_retrieval_test_system(
            database,
            object_root=object_root,
            adapter=MemoryHybridRetrievalAdapter(),
        )
        reopened.close()


def test_generation_change_during_branch_reads_reclassifies_failure_without_stale_projection(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    mutation: dict[str, object] = {}

    def retire_during_read() -> None:
        with sqlite3.connect(database) as conn:
            row = conn.execute(
                "SELECT generation_id,state,lifecycle_version,"
                "authority_aggregate_version FROM projection_generations "
                "WHERE state='ACTIVE'"
            ).fetchone()
            assert row is not None
            trigger = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' "
                "AND name='projection_generation_update_guard'"
            ).fetchone()[0]
            mutation.update(
                {
                    "generation_id": row[0],
                    "state": row[1],
                    "lifecycle_version": row[2],
                    "authority_aggregate_version": row[3],
                    "trigger": trigger,
                }
            )
            conn.execute("DROP TRIGGER projection_generation_update_guard")
            conn.execute(
                "UPDATE projection_generations SET state='RETIRED' "
                "WHERE generation_id=?",
                (row[0],),
            )

    adapter = MemoryHybridRetrievalAdapter(on_execute=retire_during_read)
    system = open_retrieval_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        result = system.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert result.outcome is RetrievalOutcome.UNAVAILABLE
        assert result.failure is not None
        assert result.failure.reason_code == "ACTIVE_PROJECTION_UNAVAILABLE"
        assert adapter.call_count == 1
        with sqlite3.connect(database) as conn:
            row = conn.execute(
                "SELECT generation_id,projection_identity_digest,"
                "authority_watermark FROM hybrid_retrieval_attempts"
            ).fetchone()
            assert row == (None, None, None)
    finally:
        with sqlite3.connect(database) as conn:
            conn.execute(
                "UPDATE projection_generations SET state=?,"
                "lifecycle_version=?,authority_aggregate_version=? "
                "WHERE generation_id=?",
                (
                    mutation["state"],
                    mutation["lifecycle_version"],
                    mutation["authority_aggregate_version"],
                    mutation["generation_id"],
                ),
            )
            conn.execute(str(mutation["trigger"]))
        system.close()

    reopened_adapter = MemoryHybridRetrievalAdapter()
    reopened = open_retrieval_test_system(
        database,
        object_root=object_root,
        adapter=reopened_adapter,
    )
    try:
        replay = reopened.retrieval.find_related_event_candidates(
            request(), proof=proof()
        )
        assert replay.replayed is True
        assert replay.outcome is RetrievalOutcome.UNAVAILABLE
        assert reopened_adapter.call_count == 0
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("dead_letter", "reason_code"),
    (
        (False, "RETRIEVAL_GAP_BLOCKED"),
        (True, "RETRIEVAL_DEAD_LETTER_BLOCKED"),
    ),
)
def test_required_gap_and_dead_letter_are_explicit_blocked_outcomes(
    tmp_path: Path,
    dead_letter: bool,
    reason_code: str,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_active_retrieval_authority(database, object_root=object_root)
    block_active_retrieval_generation(
        database,
        object_root=object_root,
        dead_letter=dead_letter,
    )
    adapter = MemoryHybridRetrievalAdapter()
    system = open_retrieval_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        result = system.retrieval.find_related_event_candidates(
            request(
                key=(
                    "retrieval-2c-dead-letter-request"
                    if dead_letter
                    else "retrieval-2c-gap-request"
                ),
                request_id=RetrievalRequestId.new(),
                context_id=RetrievalContextV2Id.new(),
            ),
            proof=proof(),
        )
        assert result.outcome is RetrievalOutcome.INCOMPLETE
        assert result.failure is not None
        assert result.failure.reason_code == reason_code
        assert adapter.call_count == 0
    finally:
        system.close()
