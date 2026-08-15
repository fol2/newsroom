from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace

import pytest

from newsroom.increment8 import operations
from newsroom.increment8.operations import (
    LeaseState,
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
    close_lease,
    enqueue_due_work,
    quarantine_scope,
    transition_work,
)
from newsroom.tests.test_increment8c_operations import _AT, _D, _database

_T1 = "2042-01-05T00:00:01.000000Z"
_T2 = "2042-01-05T00:00:02.000000Z"
_T5 = "2042-01-05T00:00:05.000000Z"
_T6 = "2042-01-05T00:00:06.000000Z"
_T63 = "2042-01-05T00:01:03.000000Z"


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


def _commit_lease(authority: OperationalAuthority, work, *, acquired_at: str = _AT):
    lease = acquire_lease(
        work=work,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=acquired_at,
        progress_digest="sha256:" + "3" * 64,
    )
    authority.append_lease(lease)
    return (
        lease,
        transition_work(
            work,
            state=WorkState.LEASED,
            attempt_count=int(work.payload["attempt_count"]) + 1,
        ),
    )


def test_retry_uses_latest_work_version_and_exact_next_due_at(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "retry:latest")
    authority.append_work(queued)

    first_lease, leased_once = _commit_lease(authority, queued)
    first_finding = build_retry_finding(
        work=leased_once,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_AT,
    )
    authority.append_retry_finding(first_finding)
    with pytest.raises(OperationalAuthorityError, match="include its work transition"):
        authority.append_lease(close_lease(first_lease, LeaseState.RELEASED))
    _, retry_once = authority.close_lease_and_transition(
        lease=first_lease,
        lease_state=LeaseState.RELEASED,
        work_state=WorkState.RETRY_PENDING,
    )

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
    _, retry_twice = authority.close_lease_and_transition(
        lease=second_lease,
        lease_state=LeaseState.RELEASED,
        work_state=WorkState.RETRY_PENDING,
    )

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
    direct_lease_state = transition_work(
        queued, state=WorkState.LEASED, attempt_count=1
    )
    with pytest.raises(OperationalAuthorityError, match="lease acquisition"):
        authority.append_work(direct_lease_state)
    lease, _ = _commit_lease(authority, queued)
    with pytest.raises(OperationalAuthorityError, match="lacks its Finding"):
        authority.close_lease_and_transition(
            lease=lease,
            lease_state=LeaseState.RELEASED,
            work_state=WorkState.RETRY_PENDING,
        )
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
    lease, leased = _commit_lease(authority, queued)
    terminal = build_retry_finding(
        work=leased,
        classification=RetryClassification.NON_RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_AT,
    )
    authority.append_retry_finding(terminal)
    with pytest.raises(OperationalAuthorityError, match="Finding differs"):
        authority.close_lease_and_transition(
            lease=lease,
            lease_state=LeaseState.RELEASED,
            work_state=WorkState.RETRY_PENDING,
        )
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
    lease, leased = _commit_lease(authority, queued)
    finding = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_AT,
    )
    competing_connection = sqlite3.connect(path, isolation_level=None)
    competing = OperationalAuthority(competing_connection)
    original_insert = OperationalAuthority._insert
    advanced = False

    def insert_after_competing_write(self, sql, values):
        nonlocal advanced
        if not advanced and sql.startswith("INSERT INTO retry_findings"):
            advanced = True
            competing.close_lease_and_transition(
                lease=lease,
                lease_state=LeaseState.RELEASED,
                work_state=WorkState.COMPLETED,
            )
        return original_insert(self, sql, values)

    monkeypatch.setattr(OperationalAuthority, "_insert", insert_after_competing_write)
    with pytest.raises(OperationalAuthorityError, match="latest-work authority"):
        authority.append_retry_finding(finding)
    assert connection.execute("SELECT COUNT(*) FROM retry_findings").fetchone() == (0,)
    competing_connection.close()
    connection.close()


def test_retry_failure_cannot_predate_exact_active_lease(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "retry:failure-time")
    authority.append_work(queued)
    _, leased = _commit_lease(authority, queued, acquired_at=_T2)
    finding = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_T1,
    )
    with pytest.raises(OperationalAuthorityError, match="outside"):
        authority.append_retry_finding(finding)
    after_expiry = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        failed_at=_T63,
    )
    with pytest.raises(OperationalAuthorityError, match="outside"):
        authority.append_retry_finding(after_expiry)
    connection.close()


def test_direct_renewal_cannot_jump_to_maximum_expiry(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "lease:renewal-bound")
    authority.append_work(queued)
    lease, _ = _commit_lease(authority, queued)
    forged = operations.WorkLease.build(
        {
            **lease.payload,
            "lease_version": 2,
            "progress_digest": "sha256:" + "9" * 64,
            "expires_at": lease.payload["maximum_expires_at"],
            "previous_digest": lease.digest,
        }
    )
    with pytest.raises(OperationalAuthorityError, match="renewal"):
        authority.append_lease(forged)
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
    forged_origin = operations.DueWork.build(
        {
            **future.payload,
            "state": WorkState.LEASED.value,
            "attempt_count": 1,
        }
    )
    with pytest.raises(OperationalAuthorityError, match="lease acquisition"):
        authority.append_work(forged_origin)
    authority.append_work(future)
    early = acquire_lease(
        work=future,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T1,
        progress_digest="sha256:" + "3" * 64,
    )
    with pytest.raises(OperationalAuthorityError, match="not due"):
        authority.append_lease(early)
    expired = enqueue_due_work(
        profile=profile,
        logical_due_key="lease:expired",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE,
        due_at=_AT,
        deadline_at=_T2,
        authority_version_digest=_D,
    )
    authority.append_work(expired)
    late = acquire_lease(
        work=expired,
        owner_digest="sha256:" + "4" * 64,
        acquired_at=_T5,
        progress_digest="sha256:" + "5" * 64,
    )
    with pytest.raises(OperationalAuthorityError, match="deadline"):
        authority.append_lease(late)
    authority.append_work(transition_work(expired, state=WorkState.EXPLICITLY_CLOSED))
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
    schedule["maximum_catch_up_items"] = 2
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
    urgent = tuple(
        enqueue_due_work(
            profile=profile,
            logical_due_key=f"starvation:urgent-{index}",
            scope_kind="FIXTURE_SOURCE",
            urgency=Urgency.URGENT,
            due_at="2042-01-05T00:00:20.000000Z",
            deadline_at="2042-01-05T01:00:00.000000Z",
            authority_version_digest=_D,
        )
        for index in range(2)
    )
    authority.append_work(routine)
    for item in urgent:
        authority.append_work(item)
    selected = authority.due_work("2042-01-05T00:00:20.000000Z")
    assert len(selected) == 2
    assert selected[0].payload["urgency"] == Urgency.URGENT.value
    assert routine in selected
    connection.close()


def test_routine_promotion_preserves_each_present_higher_priority_class(
    tmp_path, monkeypatch
) -> None:
    profile_definition = dict(operations.INCREMENT_8_READINESS.operational_profile)
    schedule = dict(profile_definition["schedule"])
    schedule["maximum_catch_up_items"] = 2
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
    routine = _work(profile, "fairness:routine")
    higher = tuple(
        enqueue_due_work(
            profile=profile,
            logical_due_key=f"fairness:{urgency.value.lower()}",
            scope_kind="FIXTURE_SOURCE",
            urgency=urgency,
            due_at="2042-01-05T00:00:20.000000Z",
            deadline_at="2042-01-05T01:00:00.000000Z",
            authority_version_digest=_D,
        )
        for urgency in (Urgency.TIME_SENSITIVE, Urgency.PLANNED)
    )
    authority.append_work(routine)
    for item in higher:
        authority.append_work(item)
    selected = authority.due_work("2042-01-05T00:00:20.000000Z")
    assert {item.payload["urgency"] for item in selected} == {
        Urgency.TIME_SENSITIVE.value,
        Urgency.PLANNED.value,
    }
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
