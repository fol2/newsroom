from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from newsroom.authority.evaluation_handoff_migrations import (
    EVALUATION_HANDOFF_MIGRATION_CHECKSUM,
    EVALUATION_HANDOFF_MIGRATION_NAME,
    EVALUATION_HANDOFF_SCHEMA_VERSION,
    evaluation_handoff_backup_paths,
    prepare_evaluation_handoff_backup,
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
    HandoffContractError,
    HandoffState,
    create_handoff,
    mark_attempt_ambiguous,
    mark_attempt_sent,
    persist_attempt,
    request_retry,
)

from .authority_event_helpers import open_test_system
from .extraction_4a_helpers import open_extraction_system, seed_extraction_fixture
from .graphiti_adapter_4d_migration_helpers import (
    downgrade_empty_graphiti_adapter_schema_to_v15,
    drop_empty_v22_relationship_schema,
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
    drop_empty_v22_relationship_schema(connection)
    for table in (
        "event_hypothesis_heads_v2",
        "event_hypothesis_versions_v2",
        "event_hypotheses_v2",
        "triage_work_item_leases",
        "triage_worker_attempts",
        "triage_execution_batches",
        "triage_proposal_dispositions",
        "triage_proposal_validation_findings",
        "triage_work_item_heads",
        "triage_work_item_versions",
        "triage_work_items",
    ):
        connection.execute(f'DROP TABLE "{table}"')
    connection.execute("DELETE FROM authority_migrations WHERE version>=18")
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
        assert EVALUATION_HANDOFF_SCHEMA_VERSION == 17
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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


def test_exact_v16_upgrade_requires_and_retains_exact_backup_digest(
    tmp_path: Path,
) -> None:
    database = tmp_path / "upgrade.sqlite3"
    connection = _fresh(database)
    try:
        retained_v16_history = connection.execute(
            "SELECT version,name,checksum FROM authority_migrations "
            "WHERE version<=16 ORDER BY version"
        ).fetchall()
        _downgrade_empty_v17_to_v16(connection)
        prepare_evaluation_handoff_backup(
            connection, evaluation_handoff_backup_paths(database)[0]
        )
        connection.close()
        connection = _open(database)
        replayed_receipt = prepare_evaluation_handoff_backup(
            connection, evaluation_handoff_backup_paths(database)[0]
        )
        apply_pending_migrations(
            connection, applied_at="2042-03-12T10:00:01.000000Z"
        )
        backup, digest_file = evaluation_handoff_backup_paths(database)
        digest = "sha256:" + hashlib.sha256(backup.read_bytes()).hexdigest()
        assert backup.is_file()
        assert replayed_receipt.backup_path == backup
        assert digest_file.read_text(encoding="ascii") == digest + "\n"
        backup_connection = _open(backup)
        try:
            assert backup_connection.execute("PRAGMA user_version").fetchone()[0] == 16
            assert backup_connection.execute(
                "SELECT version,name,checksum FROM authority_migrations "
                "ORDER BY version"
            ).fetchall() == retained_v16_history
        finally:
            backup_connection.close()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute(
            "SELECT version,name,checksum FROM authority_migrations "
            "WHERE version<=16 ORDER BY version"
        ).fetchall() == retained_v16_history

    finally:
        connection.close()


def test_multihop_existing_upgrade_checkpoints_v16_backup_before_v17(
    tmp_path: Path,
) -> None:
    database = tmp_path / "multihop.sqlite3"
    _fresh(database).close()
    downgrade_empty_graphiti_adapter_schema_to_v15(database)

    connection = _open(database)
    try:
        apply_pending_migrations(
            connection, applied_at="2042-03-12T10:00:01.000000Z"
        )
        backup, digest_path = evaluation_handoff_backup_paths(database)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert backup.is_file()
        assert digest_path.is_file()
        backup_connection = _open(backup)
        try:
            assert backup_connection.execute("PRAGMA user_version").fetchone()[0] == 16
            assert backup_connection.execute(
                "SELECT MAX(version) FROM authority_migrations"
            ).fetchone()[0] == 16
        finally:
            backup_connection.close()
    finally:
        connection.close()


def test_exact_v16_upgrade_without_prepared_backup_fails_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing-backup.sqlite3"
    connection = _fresh(database)
    try:
        _downgrade_empty_v17_to_v16(connection)
        with pytest.raises(sqlite3.DatabaseError, match="requires a prepared backup"):
            apply_pending_migrations(
                connection, applied_at="2042-03-12T10:00:01.000000Z"
            )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
        assert connection.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=17"
        ).fetchone()[0] == 0
        assert not evaluation_handoff_backup_paths(database)[0].exists()
    finally:
        connection.close()


def test_exact_v16_upgrade_rejects_changed_backup_digest(tmp_path: Path) -> None:
    database = tmp_path / "changed-backup.sqlite3"
    connection = _fresh(database)
    try:
        _downgrade_empty_v17_to_v16(connection)
        backup, digest_path = evaluation_handoff_backup_paths(database)
        prepare_evaluation_handoff_backup(connection, backup)
        digest_path.write_text("sha256:" + "0" * 64 + "\n", encoding="ascii")

        with pytest.raises(sqlite3.DatabaseError, match="identity differs"):
            apply_pending_migrations(
                connection, applied_at="2042-03-12T10:00:01.000000Z"
            )

        assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
        assert connection.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=17"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_standard_sqlite_connection_backup_preflight_leaves_no_transaction(
    tmp_path: Path,
) -> None:
    database = tmp_path / "standard-connection.sqlite3"
    initial = _fresh(database)
    _downgrade_empty_v17_to_v16(initial)
    initial.close()
    connection = sqlite3.connect(database)
    try:
        prepare_evaluation_handoff_backup(
            connection, evaluation_handoff_backup_paths(database)[0]
        )
        assert connection.in_transaction is False
        apply_pending_migrations(
            connection, applied_at="2042-03-12T10:00:01.000000Z"
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        connection.close()


def test_actual_service_event_and_object_open_preflight_exact_v16_backup(
    tmp_path: Path,
) -> None:
    event_database = tmp_path / "event" / "authority.sqlite3"
    with open_test_system(event_database):
        pass
    event_connection = _open(event_database)
    _downgrade_empty_v17_to_v16(event_connection)
    event_connection.close()
    with open_test_system(event_database):
        pass
    assert evaluation_handoff_backup_paths(event_database)[0].is_file()

    extraction = seed_extraction_fixture(tmp_path / "object")
    object_connection = _open(extraction.database)
    _downgrade_empty_v17_to_v16(object_connection)
    object_connection.close()
    with open_extraction_system(extraction):
        pass
    assert evaluation_handoff_backup_paths(extraction.database)[0].is_file()


def test_failed_v17_upgrade_rolls_back_exclusively_after_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "failed-upgrade.sqlite3"
    connection = _fresh(database)
    try:
        _downgrade_empty_v17_to_v16(connection)
        prepare_evaluation_handoff_backup(
            connection, evaluation_handoff_backup_paths(database)[0]
        )
        from newsroom.authority import migrations

        monkeypatch.setattr(
            migrations,
            "EVALUATION_HANDOFF_MIGRATION_STATEMENTS",
            migrations.EVALUATION_HANDOFF_MIGRATION_STATEMENTS
            + ("CREATE TABLE injected_failure(",),
        )
        with pytest.raises(sqlite3.OperationalError):
            apply_pending_migrations(
                connection, applied_at="2042-03-12T10:00:02.000000Z"
            )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
        assert connection.execute(
            "SELECT COUNT(*) FROM authority_migrations WHERE version=17"
        ).fetchone()[0] == 0
        backup, digest_file = evaluation_handoff_backup_paths(database)
        assert backup.is_file()
        assert digest_file.is_file()
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


def test_store_bounds_retry_after_exact_timeout(tmp_path: Path) -> None:
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
    assert store.correlate_acknowledgement(handoff.handoff_id, mismatched) == handoff
    ambiguous = store.mark_attempt_ambiguous(handoff.handoff_id, attempt.attempt_id)
    assert ambiguous.state is HandoffState.AMBIGUOUS
    assert ambiguous.ambiguity_reason == "target_outcome_unknown"
    exhausted = store.request_retry(handoff.handoff_id)
    assert exhausted.retry_exhausted is True
    assert store.persist_attempt(handoff.handoff_id) == exhausted
    connection.close()


def test_store_can_persist_bounded_retry_after_wrong_response_and_timeout(
    tmp_path: Path,
) -> None:
    connection = _fresh(tmp_path / "ambiguous-retry.sqlite3")
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(
        store.register(_handoff(max_attempts=2)).handoff_id
    )
    attempt = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, attempt.attempt_id)
    mismatched = Acknowledgement.create(
        handoff_id="handoff:sha256:" + "0" * 64,
        attempt_id=attempt.attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "7" * 64,
    )
    handoff = store.correlate_acknowledgement(handoff.handoff_id, mismatched)
    handoff = store.mark_attempt_ambiguous(handoff.handoff_id, attempt.attempt_id)

    retry = store.request_retry(handoff.handoff_id)
    pending = store.persist_attempt(handoff.handoff_id)

    assert retry.state is HandoffState.RETRY
    assert pending.state is HandoffState.PENDING
    assert len(pending.attempts) == 2
    assert store.load(handoff.handoff_id) == pending
    connection.close()


def test_retry_timeout_after_wrong_ack_uses_one_deterministic_reason(
    tmp_path: Path,
) -> None:
    connection = _fresh(tmp_path / "retry-timeout.sqlite3")
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(
        store.register(_handoff(max_attempts=2)).handoff_id
    )
    first = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, first.attempt_id)
    wrong = Acknowledgement.create(
        handoff_id="handoff:sha256:" + "0" * 64,
        attempt_id=first.attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "6" * 64,
    )
    handoff = store.correlate_acknowledgement(handoff.handoff_id, wrong)
    handoff = store.mark_attempt_ambiguous(handoff.handoff_id, first.attempt_id)
    handoff = store.persist_attempt(store.request_retry(handoff.handoff_id).handoff_id)
    second = handoff.attempts[1]
    handoff = store.mark_attempt_sent(handoff.handoff_id, second.attempt_id)

    timed_out = store.mark_attempt_ambiguous(handoff.handoff_id, second.attempt_id)

    assert timed_out.state is HandoffState.AMBIGUOUS
    assert timed_out.ambiguity_reason == "target_outcome_unknown"
    assert timed_out.retry_exhausted is True
    assert store.load(handoff.handoff_id) == timed_out


def test_store_delayed_old_timeout_preserves_active_sent_retry(
    tmp_path: Path,
) -> None:
    database = tmp_path / "delayed-old-timeout.sqlite3"
    connection = _fresh(database)
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    first = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, first.attempt_id)
    wrong = Acknowledgement.create(
        handoff_id="handoff:sha256:" + "0" * 64,
        attempt_id=first.attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "5" * 64,
    )
    handoff = store.correlate_acknowledgement(handoff.handoff_id, wrong)
    handoff = store.mark_attempt_ambiguous(handoff.handoff_id, first.attempt_id)
    handoff = store.persist_attempt(store.request_retry(handoff.handoff_id).handoff_id)
    second = handoff.attempts[1]
    handoff = store.mark_attempt_sent(handoff.handoff_id, second.attempt_id)

    retained = store.mark_attempt_ambiguous(handoff.handoff_id, first.attempt_id)

    assert retained.state is HandoffState.PENDING
    assert retained.attempts[1].sent is True
    assert store.persist_attempt(handoff.handoff_id) == retained
    assert store.load(handoff.handoff_id) == retained
    connection.close()


def test_database_and_restart_reject_premature_second_attempt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "premature-attempt.sqlite3"
    connection = _fresh(database)
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    handoff = store.mark_attempt_sent(
        handoff.handoff_id, handoff.attempts[0].attempt_id
    )
    valid = persist_attempt(_handoff())
    valid = mark_attempt_sent(valid, valid.attempts[0].attempt_id)
    valid = mark_attempt_ambiguous(valid, valid.attempts[0].attempt_id)
    valid = persist_attempt(request_retry(valid))
    second = valid.attempts[1]
    with pytest.raises(sqlite3.IntegrityError, match="attempt sequence"):
        connection.execute(
            "INSERT INTO evaluation_handoff_attempts VALUES(?,?,?,?,?,?,?,?)",
            (
                second.attempt_id,
                second.schema_identity,
                handoff.handoff_id,
                2,
                handoff.handoff_id,
                1,
                0,
                0,
            ),
        )

    connection.execute("DROP TRIGGER evaluation_handoff_attempt_insert_guard")
    connection.execute(
        "INSERT INTO evaluation_handoff_attempts VALUES(?,?,?,?,?,?,?,?)",
        (
            second.attempt_id,
            second.schema_identity,
            handoff.handoff_id,
            2,
            handoff.handoff_id,
            1,
            0,
            0,
        ),
    )
    connection.close()
    connection = _open(database)
    with pytest.raises(HandoffContractError, match="attempt history"):
        EvaluationHandoffStore(connection).load(handoff.handoff_id)
    connection.close()


def test_store_pristine_wrong_ack_remains_inert_across_restart_and_send(
    tmp_path: Path,
) -> None:
    database = tmp_path / "pristine-wrong-ack.sqlite3"
    connection = _fresh(database)
    store = EvaluationHandoffStore(connection)
    handoff = store.register(_handoff())
    wrong = Acknowledgement.create(
        handoff_id="handoff:sha256:" + "0" * 64,
        attempt_id="attempt:sha256:" + "0" * 64,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "4" * 64,
    )
    retained = store.correlate_acknowledgement(handoff.handoff_id, wrong)
    assert retained == handoff
    assert retained.acknowledgements == ()
    assert store.correlate_acknowledgement(handoff.handoff_id, wrong) == retained
    connection.close()

    connection = _open(database)
    store = EvaluationHandoffStore(connection)
    retained = store.load(handoff.handoff_id)
    assert retained.state is HandoffState.PENDING
    retained = store.persist_attempt(handoff.handoff_id)
    retained = store.mark_attempt_sent(
        handoff.handoff_id, retained.attempts[0].attempt_id
    )
    assert store.correlate_acknowledgement(handoff.handoff_id, wrong) == retained
    connection.close()


def test_database_rejects_ack_without_exact_sent_attempt(tmp_path: Path) -> None:
    connection = _fresh(tmp_path / "pristine-ack-authority.sqlite3")
    handoff = EvaluationHandoffStore(connection).register(_handoff())
    wrong = Acknowledgement.create(
        handoff_id="handoff:sha256:" + "0" * 64,
        attempt_id="attempt:sha256:" + "0" * 64,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "2" * 64,
    )

    with pytest.raises(sqlite3.IntegrityError, match="correlation"):
        connection.execute(
            "INSERT INTO evaluation_handoff_acknowledgements VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                wrong.acknowledgement_id,
                wrong.schema_identity,
                handoff.handoff_id,
                wrong.handoff_id,
                wrong.attempt_id,
                wrong.candidate_version_id,
                wrong.governing_manifest_digest,
                wrong.sink_id,
                wrong.outcome.value,
                wrong.response_digest,
            ),
        )
    connection.close()


def test_sql_exact_sent_ack_has_no_suppression_seam(tmp_path: Path) -> None:
    connection = _fresh(tmp_path / "exact-sql-ack.sqlite3")
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    handoff = store.mark_attempt_sent(
        handoff.handoff_id, handoff.attempts[0].attempt_id
    )
    acknowledgement = Acknowledgement.create(
        handoff_id=handoff.handoff_id,
        attempt_id=handoff.attempts[0].attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "1" * 64,
    )
    assert "state_authority" not in {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(evaluation_handoff_acknowledgements)"
        )
    }
    connection.execute(
        "INSERT INTO evaluation_handoff_acknowledgements VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            acknowledgement.acknowledgement_id,
            acknowledgement.schema_identity,
            handoff.handoff_id,
            acknowledgement.handoff_id,
            acknowledgement.attempt_id,
            acknowledgement.candidate_version_id,
            acknowledgement.governing_manifest_digest,
            acknowledgement.sink_id,
            acknowledgement.outcome.value,
            acknowledgement.response_digest,
        ),
    )
    connection.execute(
        "UPDATE evaluation_handoffs SET transport_state='acknowledged' "
        "WHERE handoff_id=?",
        (handoff.handoff_id,),
    )
    assert EvaluationHandoffStore(connection).load(handoff.handoff_id).state is (
        HandoffState.ACKNOWLEDGED
    )
    connection.close()


def test_store_future_response_is_inert_until_exact_attempt_is_sent(
    tmp_path: Path,
) -> None:
    connection = _fresh(tmp_path / "future-response.sqlite3")
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    handoff = store.mark_attempt_sent(
        handoff.handoff_id, handoff.attempts[0].attempt_id
    )
    handoff = store.mark_attempt_ambiguous(
        handoff.handoff_id, handoff.attempts[0].attempt_id
    )
    future = persist_attempt(request_retry(handoff))
    response = Acknowledgement.create(
        handoff_id=future.handoff_id,
        attempt_id=future.attempts[1].attempt_id,
        candidate_version_id=future.candidate_version_id,
        governing_manifest_digest=future.governing_manifest_digest,
        sink_id=future.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "0" * 64,
    )

    assert store.correlate_acknowledgement(handoff.handoff_id, response) == handoff
    pending = store.persist_attempt(store.request_retry(handoff.handoff_id).handoff_id)
    assert store.correlate_acknowledgement(handoff.handoff_id, response) == pending
    store.mark_attempt_sent(handoff.handoff_id, pending.attempts[1].attempt_id)
    assert store.correlate_acknowledgement(
        handoff.handoff_id, response
    ).state is HandoffState.ACKNOWLEDGED
    connection.close()


def test_store_wrong_response_preserves_unsent_retry_for_rightful_ack(
    tmp_path: Path,
) -> None:
    connection = _fresh(tmp_path / "wrong-active-retry.sqlite3")
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    handoff = store.mark_attempt_sent(
        handoff.handoff_id, handoff.attempts[0].attempt_id
    )
    handoff = store.mark_attempt_ambiguous(
        handoff.handoff_id, handoff.attempts[0].attempt_id
    )
    pending = store.persist_attempt(store.request_retry(handoff.handoff_id).handoff_id)
    wrong = Acknowledgement.create(
        handoff_id="handoff:sha256:" + "0" * 64,
        attempt_id=pending.attempts[1].attempt_id,
        candidate_version_id=pending.candidate_version_id,
        governing_manifest_digest=pending.governing_manifest_digest,
        sink_id=pending.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "8" * 64,
    )

    assert store.correlate_acknowledgement(pending.handoff_id, wrong) == pending
    sent = store.mark_attempt_sent(pending.handoff_id, pending.attempts[1].attempt_id)
    rightful = Acknowledgement.create(
        handoff_id=sent.handoff_id,
        attempt_id=sent.attempts[1].attempt_id,
        candidate_version_id=sent.candidate_version_id,
        governing_manifest_digest=sent.governing_manifest_digest,
        sink_id=sent.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "7" * 64,
    )
    assert store.correlate_acknowledgement(
        sent.handoff_id, rightful
    ).state is HandoffState.ACKNOWLEDGED
    connection.close()


def test_store_conflicting_old_acks_preserve_active_retry_across_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "old-conflict-active-retry.sqlite3"
    connection = _fresh(database)
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    first = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, first.attempt_id)
    handoff = store.mark_attempt_ambiguous(handoff.handoff_id, first.attempt_id)
    pending = store.persist_attempt(store.request_retry(handoff.handoff_id).handoff_id)
    accepted = Acknowledgement.create(
        handoff_id=pending.handoff_id,
        attempt_id=first.attempt_id,
        candidate_version_id=pending.candidate_version_id,
        governing_manifest_digest=pending.governing_manifest_digest,
        sink_id=pending.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "a" * 64,
    )
    rejected = Acknowledgement.create(
        handoff_id=pending.handoff_id,
        attempt_id=first.attempt_id,
        candidate_version_id=pending.candidate_version_id,
        governing_manifest_digest=pending.governing_manifest_digest,
        sink_id=pending.sink_id,
        outcome=AcknowledgementOutcome.REJECTED,
        response_digest="sha256:" + "b" * 64,
    )
    pending = store.correlate_acknowledgement(pending.handoff_id, accepted)
    pending = store.correlate_acknowledgement(pending.handoff_id, rejected)
    assert pending.state is HandoffState.PENDING
    connection.close()

    connection = _open(database)
    store = EvaluationHandoffStore(connection)
    pending = store.load(pending.handoff_id)
    assert pending.state is HandoffState.PENDING
    sent = store.mark_attempt_sent(pending.handoff_id, pending.attempts[1].attempt_id)
    timed_out = store.mark_attempt_ambiguous(sent.handoff_id, sent.attempts[1].attempt_id)
    assert timed_out.state is HandoffState.AMBIGUOUS
    assert timed_out.ambiguity_reason == "conflicting_acknowledgements"
    connection.close()


def test_sql_and_restart_reject_current_attempt_conflict_as_non_ambiguous(
    tmp_path: Path,
) -> None:
    database = tmp_path / "current-conflict-tamper.sqlite3"
    connection = _fresh(database)
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    first = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, first.attempt_id)
    handoff = store.mark_attempt_ambiguous(handoff.handoff_id, first.attempt_id)
    handoff = store.persist_attempt(store.request_retry(handoff.handoff_id).handoff_id)
    handoff = store.mark_attempt_sent(handoff.handoff_id, handoff.attempts[1].attempt_id)
    accepted_current = Acknowledgement.create(
        handoff_id=handoff.handoff_id,
        attempt_id=handoff.attempts[1].attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "2" * 64,
    )
    rejected_old = Acknowledgement.create(
        handoff_id=handoff.handoff_id,
        attempt_id=first.attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.REJECTED,
        response_digest="sha256:" + "3" * 64,
    )
    handoff = store.correlate_acknowledgement(handoff.handoff_id, accepted_current)
    handoff = store.correlate_acknowledgement(handoff.handoff_id, rejected_old)
    assert handoff.state is HandoffState.AMBIGUOUS

    with pytest.raises(sqlite3.IntegrityError, match="state transition"):
        connection.execute(
            "UPDATE evaluation_handoffs SET transport_state='acknowledged',"
            "ambiguity_reason=NULL WHERE handoff_id=?",
            (handoff.handoff_id,),
        )

    connection.execute("DROP TRIGGER evaluation_handoff_state_guard")
    connection.execute(
        "UPDATE evaluation_handoffs SET transport_state='pending',"
        "ambiguity_reason=NULL WHERE handoff_id=?",
        (handoff.handoff_id,),
    )
    connection.close()
    connection = _open(database)
    with pytest.raises(HandoffContractError, match="Handoff state"):
        EvaluationHandoffStore(connection).load(handoff.handoff_id)
    connection.close()

def test_concurrent_pristine_ack_and_attempt_persistence_remain_retry_inert(
    tmp_path: Path,
) -> None:
    database = tmp_path / "concurrent-pristine-ack.sqlite3"
    connection = _fresh(database)
    handoff = EvaluationHandoffStore(connection).register(_handoff())
    connection.close()
    wrong = Acknowledgement.create(
        handoff_id="handoff:sha256:" + "0" * 64,
        attempt_id="attempt:sha256:" + "0" * 64,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "3" * 64,
    )

    def observe_or_persist(observe: bool) -> None:
        local = _open(database)
        try:
            store = EvaluationHandoffStore(local)
            if observe:
                store.correlate_acknowledgement(handoff.handoff_id, wrong)
            else:
                store.persist_attempt(handoff.handoff_id)
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(observe_or_persist, (True, False)))

    connection = _open(database)
    try:
        retained = EvaluationHandoffStore(connection).load(handoff.handoff_id)
        assert retained.state is HandoffState.PENDING
        assert len(retained.attempts) == 1
        assert retained.acknowledgements == ()
    finally:
        connection.close()


def test_restart_rejects_premature_retry_exhaustion_sql_tamper(
    tmp_path: Path,
) -> None:
    database = tmp_path / "exhaustion-tamper.sqlite3"
    connection = _fresh(database)
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(
        store.register(_handoff(max_attempts=3)).handoff_id
    )
    attempt = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, attempt.attempt_id)
    handoff = store.mark_attempt_ambiguous(handoff.handoff_id, attempt.attempt_id)
    connection.execute(
        "UPDATE evaluation_handoffs SET retry_exhausted=1 WHERE handoff_id=?",
        (handoff.handoff_id,),
    )
    connection.close()

    connection = _open(database)
    with pytest.raises(HandoffContractError, match="Handoff state"):
        EvaluationHandoffStore(connection).load(handoff.handoff_id)
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


def test_wrong_handoff_observation_cannot_poison_rightful_ack_correlation(
    tmp_path: Path,
) -> None:
    connection = _fresh(tmp_path / "ack-association.sqlite3")
    store = EvaluationHandoffStore(connection)
    first = store.persist_attempt(store.register(_handoff()).handoff_id)
    first = store.mark_attempt_sent(first.handoff_id, first.attempts[0].attempt_id)
    second_request = create_handoff(
        CANDIDATE_VERSION_ID + ":second",
        MANIFEST_DIGEST,
        SINK_ID,
    )
    second = store.persist_attempt(store.register(second_request).handoff_id)
    second = store.mark_attempt_sent(
        second.handoff_id, second.attempts[0].attempt_id
    )
    acknowledgement = Acknowledgement.create(
        handoff_id=second.handoff_id,
        attempt_id=second.attempts[0].attempt_id,
        candidate_version_id=second.candidate_version_id,
        governing_manifest_digest=second.governing_manifest_digest,
        sink_id=second.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "f" * 64,
    )

    poisoned = store.correlate_acknowledgement(first.handoff_id, acknowledgement)
    rightful = store.correlate_acknowledgement(second.handoff_id, acknowledgement)

    assert poisoned == first
    assert rightful.state is HandoffState.ACKNOWLEDGED
    assert store.correlate_acknowledgement(
        second.handoff_id, acknowledgement
    ) == rightful
    assert connection.execute(
        "SELECT recorded_handoff_id FROM evaluation_handoff_acknowledgements "
        "WHERE acknowledgement_id=? ORDER BY recorded_handoff_id",
        (acknowledgement.acknowledgement_id,),
    ).fetchall() == [(second.handoff_id,)]
    connection.close()


def test_restart_rederives_state_and_rejects_terminal_to_ambiguous_tamper(
    tmp_path: Path,
) -> None:
    connection = _fresh(tmp_path / "state-tamper.sqlite3")
    store = EvaluationHandoffStore(connection)
    handoff = store.persist_attempt(store.register(_handoff()).handoff_id)
    handoff = store.mark_attempt_sent(
        handoff.handoff_id, handoff.attempts[0].attempt_id
    )
    acknowledgement = Acknowledgement.create(
        handoff_id=handoff.handoff_id,
        attempt_id=handoff.attempts[0].attempt_id,
        candidate_version_id=handoff.candidate_version_id,
        governing_manifest_digest=handoff.governing_manifest_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + "9" * 64,
    )
    handoff = store.correlate_acknowledgement(handoff.handoff_id, acknowledgement)
    connection.execute(
        "UPDATE evaluation_handoffs SET transport_state='ambiguous',"
        "ambiguity_reason='target_outcome_unknown' WHERE handoff_id=?",
        (handoff.handoff_id,),
    )
    connection.close()

    connection = _open(tmp_path / "state-tamper.sqlite3")
    with pytest.raises(HandoffContractError, match="Handoff state"):
        EvaluationHandoffStore(connection).load(handoff.handoff_id)
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
