from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace

import pytest

from newsroom.increment8 import operations
from newsroom.increment8.operations import (
    OperationalAuthority,
    OperationalAuthorityError,
    QuarantineRecord,
    QuarantineState,
    RetryClassification,
    Urgency,
    WorkState,
    acquire_lease,
    build_operational_profile,
    build_retry_finding,
    enqueue_due_work,
    quarantine_scope,
    transition_work,
)
from newsroom.tests.test_increment8c_operations import _AT, _D, _database

_T1 = "2042-01-05T00:00:01.000000Z"
_T2 = "2042-01-05T00:00:02.000000Z"
_T5 = "2042-01-05T00:00:05.000000Z"
_T6 = "2042-01-05T00:00:06.000000Z"


def _work(profile, key: str):
    return enqueue_due_work(
        profile=profile,
        logical_due_key=key,
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE,
        due_at=_AT,
        deadline_at="2042-01-05T01:00:00.000000Z",
        authority_version_digest=_D,
    )


def test_retry_uses_latest_work_version_and_exact_next_due_at(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "retry:latest")
    authority.append_work(queued)

    leased_once = transition_work(queued, state=WorkState.LEASED, attempt_count=1)
    authority.append_work(leased_once)
    first_finding = build_retry_finding(
        work=leased_once,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_AT,
    )
    authority.append_retry_finding(first_finding)
    retry_once = transition_work(leased_once, state=WorkState.RETRY_PENDING)
    authority.append_work(retry_once)

    assert authority.due_work(_T1) == ()
    assert authority.due_work(_T2) == (retry_once,)
    early = acquire_lease(
        work=retry_once,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T1,
        progress_digest="sha256:" + "3" * 64,
    )
    with pytest.raises(OperationalAuthorityError, match="backoff"):
        authority.append_lease(early)

    second_lease = acquire_lease(
        work=retry_once,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T2,
        progress_digest="sha256:" + "3" * 64,
    )
    authority.append_lease(second_lease)
    leased_twice = transition_work(retry_once, state=WorkState.LEASED, attempt_count=2)
    assert authority.due_work(_T2) == ()
    second_finding = build_retry_finding(
        work=leased_twice,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_T2,
    )
    authority.append_retry_finding(second_finding)
    retry_twice = transition_work(leased_twice, state=WorkState.RETRY_PENDING)
    authority.append_work(retry_twice)

    assert second_finding.payload["next_due_at"] == _T6
    assert authority.due_work(_T5) == ()
    assert authority.due_work(_T6) == (retry_twice,)
    connection.close()


def test_retry_attempts_cannot_jump_or_enter_pending_without_finding(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "retry:lineage")
    authority.append_work(queued)
    with pytest.raises(OperationalAuthorityError, match="exactly one"):
        transition_work(queued, state=WorkState.LEASED, attempt_count=2)
    leased = transition_work(queued, state=WorkState.LEASED, attempt_count=1)
    authority.append_work(leased)
    retry_pending = transition_work(leased, state=WorkState.RETRY_PENDING)
    with pytest.raises(OperationalAuthorityError, match="lacks its Finding"):
        authority.append_work(retry_pending)
    connection.close()


def test_terminal_retry_finding_cannot_leave_active_retry_pending_work(
    tmp_path,
) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "retry:terminal")
    authority.append_work(queued)
    leased = transition_work(queued, state=WorkState.LEASED, attempt_count=1)
    authority.append_work(leased)
    terminal = build_retry_finding(
        work=leased,
        classification=RetryClassification.NON_RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_AT,
    )
    authority.append_retry_finding(terminal)
    retry_pending = transition_work(leased, state=WorkState.RETRY_PENDING)
    with pytest.raises(OperationalAuthorityError, match="Finding differs"):
        authority.append_work(retry_pending)
    connection.close()


def test_retry_finding_rechecks_latest_work_inside_serialised_insert(
    tmp_path, monkeypatch
) -> None:
    path, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "retry:atomic")
    authority.append_work(queued)
    leased = transition_work(queued, state=WorkState.LEASED, attempt_count=1)
    authority.append_work(leased)
    finding = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_AT,
    )
    competing_connection = sqlite3.connect(path, isolation_level=None)
    competing = OperationalAuthority(competing_connection)
    completed = transition_work(leased, state=WorkState.COMPLETED)
    original_insert = OperationalAuthority._insert
    advanced = False

    def insert_after_competing_write(self, sql, values):
        nonlocal advanced
        if not advanced and sql.startswith("INSERT INTO retry_findings"):
            advanced = True
            competing.append_work(completed)
        return original_insert(self, sql, values)

    monkeypatch.setattr(OperationalAuthority, "_insert", insert_after_competing_write)
    with pytest.raises(OperationalAuthorityError, match="latest-work authority"):
        authority.append_retry_finding(finding)
    assert connection.execute("SELECT COUNT(*) FROM retry_findings").fetchone() == (0,)
    competing_connection.close()
    connection.close()


def test_initial_quarantine_must_be_active_canonical_origin(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    active = quarantine_scope(
        scope_id="fixture-source:one",
        reason_class="IDENTITY_FAILURE",
        evidence_digest=_D,
        recorded_at=_AT,
    )
    forged = QuarantineRecord.build(
        {
            **active.payload,
            "status": QuarantineState.RELEASED.value,
            "authorised_by_digest": "sha256:" + "2" * 64,
        }
    )
    with pytest.raises(OperationalAuthorityError, match="initial quarantine"):
        authority.append_quarantine(forged)
    authority.append_quarantine(active)
    connection.close()


def test_lease_acquisition_is_due_and_atomically_advances_work(tmp_path) -> None:
    path, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    future = enqueue_due_work(
        profile=profile,
        logical_due_key="lease:future",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE,
        due_at=_T2,
        deadline_at="2042-01-05T01:00:00.000000Z",
        authority_version_digest=_D,
    )
    authority.append_work(future)
    early = acquire_lease(
        work=future,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T1,
        progress_digest="sha256:" + "3" * 64,
    )
    with pytest.raises(OperationalAuthorityError, match="not due"):
        authority.append_lease(early)
    due = acquire_lease(
        work=future,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T2,
        progress_digest="sha256:" + "3" * 64,
    )
    authority.append_lease(due)
    connection.close()

    restarted_connection = sqlite3.connect(path, isolation_level=None)
    restarted = OperationalAuthority(restarted_connection)
    assert restarted.due_work(_T2) == ()
    assert restarted_connection.execute(
        "SELECT state,attempt_count FROM due_work WHERE work_id=? "
        "ORDER BY state_version DESC LIMIT 1",
        (future.work_id,),
    ).fetchone() == (WorkState.LEASED.value, 1)
    assert restarted.active_lease_count() == 1
    restarted_connection.close()


def _contract_with_execution(**changes: int):
    profile = dict(operations.INCREMENT_8_READINESS.operational_profile)
    execution = dict(profile["execution"])
    execution.update(changes)
    profile["execution"] = execution
    return replace(operations.INCREMENT_8_READINESS, operational_profile=profile)


def test_starved_routine_work_is_promoted_before_catch_up_limit(
    tmp_path, monkeypatch
) -> None:
    profile_definition = dict(operations.INCREMENT_8_READINESS.operational_profile)
    schedule = dict(profile_definition["schedule"])
    schedule["maximum_catch_up_items"] = 1
    profile_definition["schedule"] = schedule
    execution = dict(profile_definition["execution"])
    execution["routine_starvation_limit_seconds"] = 10
    profile_definition["execution"] = execution
    monkeypatch.setattr(
        operations,
        "INCREMENT_8_READINESS",
        replace(
            operations.INCREMENT_8_READINESS,
            operational_profile=profile_definition,
        ),
    )
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    routine = _work(profile, "starvation:routine")
    urgent = enqueue_due_work(
        profile=profile,
        logical_due_key="starvation:urgent",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.URGENT,
        due_at="2042-01-05T00:00:20.000000Z",
        deadline_at="2042-01-05T01:00:00.000000Z",
        authority_version_digest=_D,
    )
    authority.append_work(routine)
    authority.append_work(urgent)
    assert authority.due_work("2042-01-05T00:00:20.000000Z") == (routine,)
    connection.close()


def test_queue_capacity_check_and_insert_are_one_serialised_write(
    tmp_path, monkeypatch
) -> None:
    path, setup = _database(tmp_path)
    monkeypatch.setattr(
        operations,
        "INCREMENT_8_READINESS",
        _contract_with_execution(queue_capacity_items=1, urgent_reserve_items=0),
    )
    authority = OperationalAuthority(setup)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    work = (_work(profile, "capacity:a"), _work(profile, "capacity:b"))
    setup.close()

    barrier = threading.Barrier(2)
    results: list[str] = []

    def append(item) -> None:
        connection = sqlite3.connect(path, isolation_level=None, timeout=10)
        local = OperationalAuthority(connection)
        barrier.wait()
        try:
            local.append_work(item)
        except OperationalAuthorityError:
            results.append("rejected")
        else:
            results.append("inserted")
        finally:
            connection.close()

    threads = [threading.Thread(target=append, args=(item,)) for item in work]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert sorted(results) == ["inserted", "rejected"]
    check = sqlite3.connect(path, isolation_level=None)
    assert check.execute("SELECT COUNT(*) FROM due_work").fetchone() == (1,)
    check.close()


def test_lease_capacity_check_and_insert_are_one_serialised_write(
    tmp_path, monkeypatch
) -> None:
    path, setup = _database(tmp_path)
    monkeypatch.setattr(
        operations,
        "INCREMENT_8_READINESS",
        _contract_with_execution(host_concurrency=1),
    )
    authority = OperationalAuthority(setup)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    work = (_work(profile, "lease:a"), _work(profile, "lease:b"))
    for item in work:
        authority.append_work(item)
    leases = tuple(
        acquire_lease(
            work=item,
            owner_digest="sha256:" + str(index + 2) * 64,
            acquired_at=_AT,
            progress_digest="sha256:" + str(index + 4) * 64,
        )
        for index, item in enumerate(work)
    )
    setup.close()

    barrier = threading.Barrier(2)
    results: list[str] = []

    def append(item) -> None:
        connection = sqlite3.connect(path, isolation_level=None, timeout=10)
        local = OperationalAuthority(connection)
        barrier.wait()
        try:
            local.append_lease(item)
        except OperationalAuthorityError:
            results.append("rejected")
        else:
            results.append("inserted")
        finally:
            connection.close()

    threads = [threading.Thread(target=append, args=(item,)) for item in leases]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert sorted(results) == ["inserted", "rejected"]
    check = sqlite3.connect(path, isolation_level=None)
    assert check.execute("SELECT COUNT(*) FROM work_leases").fetchone() == (1,)
    check.close()
