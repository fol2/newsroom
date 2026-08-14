from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from newsroom.authority import migrations
from newsroom.increment6.handoffs import EvaluationHandoffStore, create_handoff
from newsroom.increment8.operations import (
    HandoffOperationalStatus,
    HandoffRegistrationAnchor,
    LeaseState,
    OperationalAuthority,
    OperationalAuthorityError,
    QuarantineState,
    RetryClassification,
    Urgency,
    WorkState,
    acquire_lease,
    approve_quarantine_release,
    build_capacity_evidence,
    build_operational_profile,
    build_retry_finding,
    close_lease,
    enqueue_due_work,
    handoff_operational_status,
    quarantine_scope,
    record_observed_handoff_at_hardening,
    register_anchored_handoff,
    renew_lease,
    transition_work,
)
from newsroom.tests.authority_migration_compatibility import build_exact_prefix

_AT = "2042-01-05T00:00:00.000000Z"
_LATER = "2042-01-05T00:00:10.000000Z"
_D = "sha256:" + "1" * 64


def _database(tmp_path):
    path = tmp_path / "authority.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    migrations.apply_pending_migrations(connection, applied_at=_AT)
    return path, connection


def _profile(authority: OperationalAuthority):
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    return profile


def _work(profile, *, key="due:one", urgency=Urgency.ROUTINE, due_at=_AT):
    return enqueue_due_work(
        profile=profile,
        logical_due_key=key,
        scope_kind="FIXTURE_SOURCE",
        urgency=urgency,
        due_at=due_at,
        deadline_at="2042-01-05T01:00:00.000000Z",
        authority_version_digest=_D,
    )


def test_v30_to_v31_requires_exact_backup_and_preserves_prefix(tmp_path) -> None:
    path = tmp_path / "v30.sqlite3"
    build_exact_prefix(path, 30)
    connection = sqlite3.connect(path, isolation_level=None)
    with pytest.raises(sqlite3.DatabaseError, match="prepared backup"):
        migrations.apply_pending_migrations(connection, applied_at=_AT)
    receipt = migrations.prepare_pending_migration_backup(connection)
    assert receipt is not None
    migrations.apply_pending_migrations(connection, applied_at=_AT)
    assert connection.execute("PRAGMA user_version").fetchone() == (
        migrations.SCHEMA_VERSION,
    )
    assert connection.execute(
        "SELECT version,name FROM authority_migrations WHERE version=31"
    ).fetchone() == (31, "increment8_operational_authority_v31")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_profile_and_due_work_are_exact_append_only_and_deduplicated(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = _profile(authority)
    work = _work(profile)
    authority.append_work(work)
    assert authority.due_work(_AT) == (work,)
    with pytest.raises(sqlite3.IntegrityError):
        authority.append_work(work)
    leased = transition_work(work, state=WorkState.LEASED, attempt_count=1)
    authority.append_work(leased)
    assert authority.due_work(_AT) == ()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE due_work SET state='COMPLETED'")
    with pytest.raises(sqlite3.IntegrityError, match="retained"):
        connection.execute("DELETE FROM due_work")
    connection.close()


def test_due_selection_is_deterministic_urgent_first_and_catch_up_bounded(
    tmp_path,
) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = _profile(authority)
    routine = _work(profile, key="due:routine")
    urgent = _work(profile, key="due:urgent", urgency=Urgency.URGENT)
    authority.append_work(routine)
    authority.append_work(urgent)
    assert authority.due_work(_AT) == (urgent, routine)
    connection.close()


def test_lease_is_bounded_renewable_only_with_progress_and_append_only(
    tmp_path,
) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = _profile(authority)
    work = _work(profile)
    authority.append_work(work)
    lease = acquire_lease(
        work=work,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_AT,
        progress_digest="sha256:" + "3" * 64,
    )
    authority.append_lease(lease)
    assert authority.active_lease_count() == 1
    with pytest.raises(OperationalAuthorityError, match="valid progress"):
        renew_lease(
            lease,
            progress_digest=str(lease.payload["progress_digest"]),
            renewed_at=_LATER,
        )
    renewed = renew_lease(
        lease, progress_digest="sha256:" + "4" * 64, renewed_at=_LATER
    )
    authority.append_lease(renewed)
    released = close_lease(renewed, LeaseState.RELEASED)
    authority.append_lease(released)
    assert authority.active_lease_count() == 0
    connection.close()


def test_host_concurrency_is_enforced_before_a_fifth_active_lease(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = _profile(authority)
    for index in range(4):
        work = _work(profile, key=f"due:{index}")
        authority.append_work(work)
        authority.append_lease(
            acquire_lease(
                work=work,
                owner_digest="sha256:" + str(index + 2) * 64,
                acquired_at=_AT,
                progress_digest="sha256:" + str(index + 6) * 64,
            )
        )
    fifth = _work(profile, key="due:fifth")
    authority.append_work(fifth)
    with pytest.raises(OperationalAuthorityError, match="host concurrency"):
        authority.append_lease(
            acquire_lease(
                work=fifth,
                owner_digest="sha256:" + "a" * 64,
                acquired_at=_AT,
                progress_digest="sha256:" + "b" * 64,
            )
        )
    connection.close()


def test_retry_is_classified_bounded_and_never_refreshes_health(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = _profile(authority)
    work = _work(profile)
    authority.append_work(work)
    leased = transition_work(work, state=WorkState.LEASED, attempt_count=1)
    authority.append_work(leased)
    finding = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_AT,
    )
    assert finding.payload["next_due_at"] == "2042-01-05T00:00:02.000000Z"
    assert finding.payload["health_clock_refreshed"] is False
    assert finding.payload["editorial_no_news"] is False
    authority.append_retry_finding(finding)
    attempt_one = transition_work(
        _work(profile), state=WorkState.LEASED, attempt_count=1
    )
    retry_one = transition_work(attempt_one, state=WorkState.RETRY_PENDING)
    attempt_two = transition_work(retry_one, state=WorkState.LEASED, attempt_count=2)
    retry_two = transition_work(attempt_two, state=WorkState.RETRY_PENDING)
    exhausted = transition_work(retry_two, state=WorkState.LEASED, attempt_count=3)
    terminal = build_retry_finding(
        work=exhausted,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_AT,
    )
    assert terminal.payload["retry_exhausted"] is True
    assert terminal.payload["next_due_at"] is None
    connection.close()


def test_quarantine_cannot_release_automatically(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    record = quarantine_scope(
        scope_id="fixture-source:one",
        reason_class="IDENTITY_FAILURE",
        evidence_digest=_D,
        recorded_at=_AT,
    )
    authority.append_quarantine(record)
    assert record.payload["automatic_release"] is False
    approved = approve_quarantine_release(
        record,
        authorised_by_digest="sha256:" + "2" * 64,
        repair_evidence_digest="sha256:" + "3" * 64,
        decided_at=_LATER,
    )
    assert approved.payload["status"] == QuarantineState.RELEASE_APPROVED.value
    authority.append_quarantine(approved)
    connection.close()


def test_capacity_evidence_covers_all_scenarios_and_frozen_limits() -> None:
    passed = build_capacity_evidence(
        scenario_counts={
            "AVERAGE": 10,
            "FAILURE_HEAVY": 10,
            "NO_CHANGE_HEAVY": 10,
            "PEAK": 10,
        },
        cpu_cores=4,
        memory_mib=8192,
        free_disk_mib=10240,
        peak_queue_items=500,
        urgent_capacity_items=200,
        worker_throughput_per_minute=20,
        operator_minutes=5,
    )
    assert passed.payload["status"] == "PASS"
    failed = build_capacity_evidence(
        scenario_counts={
            "AVERAGE": 10,
            "FAILURE_HEAVY": 10,
            "NO_CHANGE_HEAVY": 10,
            "PEAK": 10,
        },
        cpu_cores=3,
        memory_mib=8192,
        free_disk_mib=10240,
        peak_queue_items=501,
        urgent_capacity_items=199,
        worker_throughput_per_minute=20,
        operator_minutes=5,
    )
    assert failed.payload["status"] == "FAIL"


def test_handoff_anchor_is_atomic_for_profiled_registration_and_honest_for_history(
    tmp_path,
) -> None:
    path, connection = _database(tmp_path)
    store = EvaluationHandoffStore(connection)
    legacy = create_handoff(
        "candidate-version:legacy", _D, "evaluation-sink:fixture", max_attempts=3
    )
    assert store.register(legacy) == legacy
    assert handoff_operational_status(connection, legacy.handoff_id) is (
        HandoffOperationalStatus.GRANDFATHERED_UNANCHORED
    )
    observed = record_observed_handoff_at_hardening(
        connection, handoff_id=legacy.handoff_id, observed_at=_AT
    )
    assert observed.payload["original_value_claimed"] is False
    assert handoff_operational_status(connection, legacy.handoff_id) is (
        HandoffOperationalStatus.OBSERVED_ONLY
    )

    authority = OperationalAuthority(connection)
    _profile(authority)
    current = create_handoff(
        "candidate-version:current", _D, "evaluation-sink:fixture", max_attempts=4
    )
    assert register_anchored_handoff(connection, current, registered_at=_AT) == current
    assert handoff_operational_status(connection, current.handoff_id) is (
        HandoffOperationalStatus.ANCHORED_ORIGINAL
    )
    anchor = connection.execute(
        "SELECT anchor_bytes,max_attempts,anchor_kind FROM handoff_registration_anchors WHERE handoff_id=?",
        (current.handoff_id,),
    ).fetchone()
    assert anchor[1:] == (4, "ORIGINAL_REGISTRATION")
    assert b'"max_attempts":4' in bytes(anchor[0])

    restored_path = tmp_path / "restored.sqlite3"
    restored = sqlite3.connect(restored_path, isolation_level=None)
    connection.backup(restored)
    assert handoff_operational_status(restored, current.handoff_id) is (
        HandoffOperationalStatus.ANCHORED_ORIGINAL
    )
    restored.close()
    connection.close()
    assert path.exists()


def test_handoff_coherent_scalar_tamper_is_detected_even_if_v17_trigger_is_restored(
    tmp_path,
) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    _profile(authority)
    handoff = create_handoff(
        "candidate-version:tamper", _D, "evaluation-sink:fixture", max_attempts=3
    )
    register_anchored_handoff(connection, handoff, registered_at=_AT)
    trigger = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='evaluation_handoff_identity_guard'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER evaluation_handoff_identity_guard")
    connection.execute(
        "UPDATE evaluation_handoffs SET max_attempts=4 WHERE handoff_id=?",
        (handoff.handoff_id,),
    )
    connection.execute(trigger)
    assert handoff_operational_status(connection, handoff.handoff_id) is (
        HandoffOperationalStatus.ANCHOR_MISMATCH
    )
    connection.close()


def test_self_consistent_anchor_rewrite_fails_against_pinned_registration_digest(
    tmp_path,
) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    _profile(authority)
    handoff = create_handoff(
        "candidate-version:pinned", _D, "evaluation-sink:fixture", max_attempts=3
    )
    register_anchored_handoff(connection, handoff, registered_at=_AT)
    original = connection.execute(
        "SELECT anchor_bytes,anchor_digest FROM handoff_registration_anchors WHERE handoff_id=?",
        (handoff.handoff_id,),
    ).fetchone()
    original_anchor = HandoffRegistrationAnchor.from_canonical_bytes(bytes(original[0]))
    rewritten_payload = dict(original_anchor.payload)
    rewritten_payload["recorded_at"] = _LATER
    rewritten = HandoffRegistrationAnchor.build(rewritten_payload)
    connection.execute("DROP TRIGGER immutable_handoff_registration_anchors")
    connection.execute(
        "UPDATE handoff_registration_anchors SET anchor_id=?,anchor_bytes=?,anchor_digest=?,"
        "handoff_identity_digest=?,max_attempts=?,anchor_kind=?,recorded_at=?,operational_eligible=? "
        "WHERE handoff_id=?",
        (
            rewritten.anchor_id,
            rewritten.canonical_bytes,
            rewritten.digest,
            rewritten.payload["handoff_identity_digest"],
            rewritten.payload["max_attempts"],
            rewritten.payload["anchor_kind"],
            rewritten.payload["recorded_at"],
            int(bool(rewritten.payload["operational_eligible"])),
            handoff.handoff_id,
        ),
    )
    assert handoff_operational_status(connection, handoff.handoff_id) is (
        HandoffOperationalStatus.ANCHORED_ORIGINAL
    )
    assert (
        handoff_operational_status(
            connection, handoff.handoff_id, expected_anchor_digest=str(original[1])
        )
        is HandoffOperationalStatus.ANCHOR_MISMATCH
    )
    connection.close()


def test_forged_work_record_is_rejected(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = _profile(authority)
    work = _work(profile)
    forged = replace(work, digest="sha256:" + "f" * 64)
    with pytest.raises(OperationalAuthorityError, match="forged"):
        authority.append_work(forged)
    connection.close()
