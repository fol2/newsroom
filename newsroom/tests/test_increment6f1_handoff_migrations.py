from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.evaluation_handoff_migrations import (
    EVALUATION_HANDOFF_MIGRATION_CHECKSUM,
    EVALUATION_HANDOFF_MIGRATION_NAME,
    EVALUATION_HANDOFF_SCHEMA_VERSION,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.increment6.handoffs import (
    Acknowledgement,
    AcknowledgementOutcome,
    EvaluationHandoffStore,
    HandoffState,
    create_handoff,
)


CANDIDATE_VERSION_ID = "candidate-version:01JZX7V7G8Q6XKNR4M8J5TH9WD"
MANIFEST_DIGEST = "sha256:" + "a" * 64
SINK_ID = "evaluation-sink:fixture-v1"


def _handoff(*, max_attempts: int = 3):
    return create_handoff(
        CANDIDATE_VERSION_ID,
        MANIFEST_DIGEST,
        SINK_ID,
        max_attempts=max_attempts,
    )


def _open(database: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, isolation_level=None, timeout=10)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _fresh(database: str | Path = ":memory:") -> sqlite3.Connection:
    connection = _open(database)
    apply_pending_migrations(
        connection, applied_at="2042-03-12T10:00:00.000000Z"
    )
    return connection


def _downgrade_empty_v17_to_v16(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=OFF")
    delete_guard = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' "
        "AND (name LIKE '%evaluation_handoff%') ORDER BY name DESC"
    ).fetchall():
        connection.execute(f'DROP TRIGGER "{row[0]}"')
    for table in (
        "evaluation_handoff_acknowledgements",
        "evaluation_handoff_attempts",
        "evaluation_handoffs",
    ):
        connection.execute(f'DROP TABLE "{table}"')
    connection.execute("DELETE FROM authority_migrations WHERE version=17")
    connection.execute(delete_guard)
    connection.execute("PRAGMA user_version=16")
    connection.execute("PRAGMA foreign_keys=ON")


def test_fresh_v17_schema_history_fingerprint_and_integrity_are_exact() -> None:
    connection = _fresh()
    try:
        assert SCHEMA_VERSION == EVALUATION_HANDOFF_SCHEMA_VERSION == 17
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert connection.execute(
            "SELECT version,name,checksum FROM authority_migrations "
            "ORDER BY version"
        ).fetchall() == list(EXPECTED_MIGRATION_HISTORY)
        assert connection.execute(
            "SELECT name,checksum FROM authority_migrations WHERE version=17"
        ).fetchone() == (
            EVALUATION_HANDOFF_MIGRATION_NAME,
            EVALUATION_HANDOFF_MIGRATION_CHECKSUM,
        )
        assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
        assert {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'evaluation_handoff%'"
            )
        } == {
            "evaluation_handoffs",
            "evaluation_handoff_attempts",
            "evaluation_handoff_acknowledgements",
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_exact_v16_upgrade_is_additive_and_failure_rolls_back_exclusively() -> None:
    connection = _fresh()
    try:
        retained_v16_history = connection.execute(
            "SELECT version,name,checksum FROM authority_migrations "
            "WHERE version<=16 ORDER BY version"
        ).fetchall()
        _downgrade_empty_v17_to_v16(connection)
        apply_pending_migrations(
            connection, applied_at="2042-03-12T10:00:01.000000Z"
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert connection.execute(
            "SELECT version,name,checksum FROM authority_migrations "
            "WHERE version<=16 ORDER BY version"
        ).fetchall() == retained_v16_history

        _downgrade_empty_v17_to_v16(connection)
        connection.execute("CREATE TABLE evaluation_handoffs(conflict TEXT) STRICT")
        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            apply_pending_migrations(
                connection, applied_at="2042-03-12T10:00:02.000000Z"
            )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
        assert connection.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=17"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='evaluation_handoff_attempts'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_store_persists_before_send_and_survives_restart_replay(tmp_path: Path) -> None:
    database = tmp_path / "handoffs.sqlite3"
    connection = _fresh(database)
    store = EvaluationHandoffStore(connection)
    initial = store.register(_handoff())
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE evaluation_handoffs SET publication_authority=1 "
            "WHERE handoff_id=?",
            (initial.handoff_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="state transition"):
        connection.execute(
            "UPDATE evaluation_handoffs SET transport_state='acknowledged' "
            "WHERE handoff_id=?",
            (initial.handoff_id,),
        )
    persisted = store.persist_attempt(initial.handoff_id)
    attempt = persisted.attempts[0]
    assert attempt.persisted_before_send is True
    assert attempt.sent is False
    connection.close()

    connection = _open(database)
    store = EvaluationHandoffStore(connection)
    assert store.register(_handoff()) == persisted
    sent = store.mark_attempt_sent(initial.handoff_id, attempt.attempt_id)
    acknowledgement = Acknowledgement.create(
        handoff_id=sent.handoff_id,
        attempt_id=attempt.attempt_id,
        candidate_version_id=sent.candidate_version_id,
        governing_manifest_digest=sent.governing_manifest_digest,
        sink_id=sent.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "b" * 64,
    )
    acknowledged = store.correlate_acknowledgement(
        sent.handoff_id, acknowledgement
    )
    assert acknowledged.state is HandoffState.ACKNOWLEDGED
    assert store.correlate_acknowledgement(
        sent.handoff_id, acknowledgement
    ) == acknowledged
    connection.close()

    connection = _open(database)
    try:
        assert EvaluationHandoffStore(connection).load(initial.handoff_id) == acknowledged
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_store_retains_ambiguous_ack_and_bounds_retry(tmp_path: Path) -> None:
    connection = _fresh(tmp_path / "ambiguous.sqlite3")
    store = EvaluationHandoffStore(connection)
    handoff = store.register(_handoff(max_attempts=1))
    handoff = store.persist_attempt(handoff.handoff_id)
    attempt = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, attempt.attempt_id)
    mismatched = Acknowledgement.create(
        handoff_id="handoff:sha256:" + "0" * 64,
        attempt_id=attempt.attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "c" * 64,
    )
    ambiguous = store.correlate_acknowledgement(handoff.handoff_id, mismatched)
    assert ambiguous.state is HandoffState.AMBIGUOUS
    assert ambiguous.ambiguity_reason == "acknowledgement_handoff_id_mismatch"
    exhausted = store.request_retry(handoff.handoff_id)
    assert exhausted.retry_exhausted is True
    assert store.persist_attempt(handoff.handoff_id) == exhausted
    connection.close()


def test_store_correlates_delayed_ack_after_lost_response_and_retry(
    tmp_path: Path,
) -> None:
    connection = _fresh(tmp_path / "delayed.sqlite3")
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    first = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, first.attempt_id)
    handoff = store.mark_attempt_ambiguous(handoff.handoff_id, first.attempt_id)
    handoff = store.request_retry(handoff.handoff_id)
    handoff = store.persist_attempt(handoff.handoff_id)
    handoff = store.mark_attempt_sent(
        handoff.handoff_id, handoff.attempts[1].attempt_id
    )
    delayed = Acknowledgement.create(
        handoff_id=handoff.handoff_id,
        attempt_id=first.attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "d" * 64,
    )

    result = store.correlate_acknowledgement(handoff.handoff_id, delayed)

    assert result.state is HandoffState.ACKNOWLEDGED
    assert result.handoff_id == handoff.handoff_id
    assert len(result.attempts) == 2
    connection.close()


def test_concurrent_replay_allocates_one_logical_handoff_and_attempt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "concurrent.sqlite3"
    _fresh(database).close()

    def persist() -> tuple[str, str]:
        connection = _open(database)
        try:
            store = EvaluationHandoffStore(connection)
            registered = store.register(_handoff())
            result = store.persist_attempt(registered.handoff_id)
            return result.handoff_id, result.attempts[0].attempt_id
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: persist(), range(8)))

    assert len(set(results)) == 1
    connection = _open(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM evaluation_handoffs"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM evaluation_handoff_attempts"
        ).fetchone()[0] == 1
    finally:
        connection.close()
