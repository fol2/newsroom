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
_T118 = "2042-01-05T00:01:58.000000Z"
_T120 = "2042-01-05T00:02:00.000000Z"
_T121 = "2042-01-05T00:02:01.000000Z"


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


def _commit_lease(
    authority: OperationalAuthority,
    work,
    *,
    acquired_at: str = _AT,
    authority_deadline_at: str | None = None,
):
    lease = acquire_lease(
        work=work,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=acquired_at,
        progress_digest="sha256:" + "3" * 64,
        authority_deadline_at=authority_deadline_at,
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
        first_attempt_at=_AT,
        failed_at=_AT,
    )
    authority.append_retry_finding(first_finding)
    with pytest.raises(OperationalAuthorityError, match="include its work transition"):
        authority.append_lease(
            close_lease(first_lease, LeaseState.RELEASED, closed_at=_AT)
        )
    _, retry_once = authority.close_lease_and_transition(
        lease=first_lease,
        lease_state=LeaseState.RELEASED,
        work_state=WorkState.RETRY_PENDING,
        transitioned_at=_AT,
    )

    assert authority.due_work(_T1) == ()
    assert authority.due_work(_T2) == (retry_once,)
    with pytest.raises(OperationalAuthorityError, match="exact authority deadline"):
        acquire_lease(
            work=retry_once,
            owner_digest="sha256:" + "2" * 64,
            acquired_at=_T2,
            progress_digest="sha256:" + "3" * 64,
        )
    early = acquire_lease(
        work=retry_once,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T1,
        progress_digest="sha256:" + "3" * 64,
        authority_deadline_at=_T120,
    )
    with pytest.raises(OperationalAuthorityError, match="backoff"):
        authority.append_lease(early)
    with pytest.raises(OperationalAuthorityError, match="authority deadline"):
        acquire_lease(
            work=retry_once,
            owner_digest="sha256:" + "2" * 64,
            acquired_at=_T121,
            progress_digest="sha256:" + "3" * 64,
            authority_deadline_at=_T120,
        )
    near_horizon = acquire_lease(
        work=retry_once,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T118,
        progress_digest="sha256:" + "3" * 64,
        authority_deadline_at=_T120,
    )
    assert near_horizon.payload["expires_at"] == _T120
    assert near_horizon.payload["maximum_expires_at"] == _T120

    second_lease = acquire_lease(
        work=retry_once,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T2,
        progress_digest="sha256:" + "3" * 64,
        authority_deadline_at=_T120,
    )
    authority.append_lease(second_lease)
    assert second_lease.payload["maximum_expires_at"] == _T120
    leased_twice = transition_work(retry_once, state=WorkState.LEASED, attempt_count=2)
    assert authority.due_work(_T2) == ()
    second_finding = build_retry_finding(
        work=leased_twice,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        first_attempt_at=_AT,
        failed_at=_T2,
    )
    authority.append_retry_finding(second_finding)
    _, retry_twice = authority.close_lease_and_transition(
        lease=second_lease,
        lease_state=LeaseState.RELEASED,
        work_state=WorkState.RETRY_PENDING,
        transitioned_at=_T2,
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
            transitioned_at=_AT,
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
        first_attempt_at=_AT,
        failed_at=_AT,
    )
    authority.append_retry_finding(terminal)
    with pytest.raises(OperationalAuthorityError, match="Finding differs"):
        authority.close_lease_and_transition(
            lease=lease,
            lease_state=LeaseState.RELEASED,
            work_state=WorkState.RETRY_PENDING,
            transitioned_at=_AT,
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
        first_attempt_at=_AT,
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
                transitioned_at=_AT,
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
        first_attempt_at=_T1,
        failed_at=_T1,
    )
    with pytest.raises(OperationalAuthorityError, match="outside"):
        authority.append_retry_finding(finding)
    after_expiry = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        first_attempt_at=_T2,
        failed_at=_T63,
    )
    with pytest.raises(OperationalAuthorityError, match="outside"):
        authority.append_retry_finding(after_expiry)
    elapsed = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        first_attempt_at=_AT,
        failed_at=_T121,
    )
    assert elapsed.payload["retry_exhausted"] is True
    assert elapsed.payload["next_due_at"] is None
    boundary = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        first_attempt_at=_AT,
        failed_at=_T118,
    )
    assert boundary.payload["retry_exhausted"] is True
    assert boundary.payload["next_due_at"] is None
    connection.close()


def test_retry_serialised_lease_check_uses_exact_parsed_instants(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "retry:timestamp-spelling")
    authority.append_work(queued)
    basic_acquired_at = "20420105T000001.000000Z"
    first_lease, leased = _commit_lease(
        authority, queued, acquired_at=basic_acquired_at
    )
    finding = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        first_attempt_at=basic_acquired_at,
        failed_at=_T2,
    )
    authority.append_retry_finding(finding)
    _, retry = authority.close_lease_and_transition(
        lease=first_lease,
        lease_state=LeaseState.RELEASED,
        work_state=WorkState.RETRY_PENDING,
        transitioned_at=_T2,
    )
    second_lease, leased_twice = _commit_lease(
        authority, retry, acquired_at=_T5, authority_deadline_at=_T121
    )
    second_finding = build_retry_finding(
        work=leased_twice,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        first_attempt_at=basic_acquired_at,
        failed_at=_T5,
    )
    authority.append_retry_finding(second_finding)
    assert second_lease.payload["acquired_at"] == _T5
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
    with pytest.raises(OperationalAuthorityError, match="exceeds expiry"):
        authority.close_lease_and_transition(
            lease=lease,
            lease_state=LeaseState.RELEASED,
            work_state=WorkState.COMPLETED,
            transitioned_at=_T63,
        )
    orphaned, quarantined = authority.close_lease_and_transition(
        lease=lease,
        lease_state=LeaseState.ORPHANED,
        work_state=WorkState.QUARANTINED,
        transitioned_at=_T63,
    )
    assert orphaned.payload["closed_at"] == _T63
    assert quarantined.payload["state"] == WorkState.QUARANTINED.value
    connection.close()


def test_renewal_cannot_extend_active_ownership_past_work_deadline(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = enqueue_due_work(
        profile=profile,
        logical_due_key="lease:renewal-deadline",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE,
        due_at=_AT,
        deadline_at=_T5,
        authority_version_digest=_D,
    )
    authority.append_work(queued)
    lease, _ = _commit_lease(authority, queued, acquired_at=_T1)
    renewed = operations.renew_lease(
        lease,
        progress_digest="sha256:" + "9" * 64,
        renewed_at=_T2,
    )
    authority.append_lease(renewed)
    assert renewed.payload["expires_at"] == _T5
    assert renewed.payload["maximum_expires_at"] == _T5
    connection.close()


def test_direct_renewal_cannot_resurrect_an_expired_predecessor(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "lease:renewal-resurrection")
    authority.append_work(queued)
    lease, _ = _commit_lease(authority, queued)
    forged = operations.WorkLease.build(
        {
            **lease.payload,
            "lease_version": 2,
            "progress_digest": "sha256:" + "9" * 64,
            "expires_at": "2042-01-05T00:02:00.000000Z",
            "renewed_at": _T63,
            "previous_digest": lease.digest,
        }
    )
    with pytest.raises(OperationalAuthorityError, match="renewal"):
        authority.append_lease(forged)
    connection.close()


def test_legacy_active_lease_is_upgraded_by_bounded_renewal(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = enqueue_due_work(
        profile=profile,
        logical_due_key="lease:legacy-renewal",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE,
        due_at=_AT,
        deadline_at=_T5,
        authority_version_digest=_D,
    )
    authority.append_work(queued)
    current = acquire_lease(
        work=queued,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_AT,
        progress_digest="sha256:" + "3" * 64,
    )
    legacy_payload = dict(current.payload)
    legacy_payload.pop("authority_deadline_at")
    legacy_payload.pop("renewed_at")
    legacy_payload.pop("closed_at")
    legacy_payload["expires_at"] = "2042-01-05T00:01:00.000000Z"
    legacy_payload["maximum_expires_at"] = "2042-01-05T00:05:00.000000Z"
    legacy = operations.WorkLease.build(legacy_payload)
    connection.execute(
        "INSERT INTO work_leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            legacy.lease_id,
            legacy.payload["lease_version"],
            legacy.canonical_bytes,
            legacy.digest,
            legacy.payload["work_id"],
            legacy.payload["owner_digest"],
            legacy.payload["progress_digest"],
            legacy.payload["acquired_at"],
            legacy.payload["expires_at"],
            legacy.payload["maximum_expires_at"],
            legacy.payload["status"],
            legacy.payload["previous_digest"],
        ),
    )
    leased = transition_work(queued, state=WorkState.LEASED, attempt_count=1)
    connection.execute(
        "INSERT INTO due_work VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            leased.work_id,
            leased.payload["state_version"],
            leased.canonical_bytes,
            leased.digest,
            leased.payload["profile_record_id"],
            leased.payload["logical_due_key"],
            leased.payload["scope_kind"],
            leased.payload["urgency"],
            leased.payload["state"],
            leased.payload["attempt_count"],
            leased.payload["due_at"],
            leased.payload["deadline_at"],
            leased.payload["previous_digest"],
            leased.payload["authority_version_digest"],
        ),
    )
    renewed = operations.renew_lease(
        legacy,
        progress_digest="sha256:" + "9" * 64,
        renewed_at=_T5,
        authority_deadline_at=str(queued.payload["deadline_at"]),
    )
    authority.append_lease(renewed)
    assert renewed.payload["authority_deadline_at"] == queued.payload["deadline_at"]
    assert renewed.payload["expires_at"] == _T5
    assert renewed.payload["maximum_expires_at"] == _T5
    assert renewed.payload["renewed_at"] == _T5
    connection.close()


def test_legacy_retry_lease_cannot_close_after_derived_horizon(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = _work(profile, "lease:legacy-retry-close")
    authority.append_work(queued)
    first_lease, leased_once = _commit_lease(authority, queued)
    finding = build_retry_finding(
        work=leased_once,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        first_attempt_at=_AT,
        failed_at=_AT,
    )
    legacy_finding_payload = dict(finding.payload)
    legacy_finding_payload.pop("first_attempt_at")
    legacy_finding_payload.pop("elapsed_microseconds")
    legacy_finding = operations.RetryFinding.build(legacy_finding_payload)
    connection.execute(
        "INSERT INTO retry_findings VALUES(?,?,?,?,?,?,?,?,?)",
        (
            legacy_finding.finding_id,
            legacy_finding.canonical_bytes,
            legacy_finding.digest,
            legacy_finding.payload["work_id"],
            legacy_finding.payload["attempt_number"],
            legacy_finding.payload["classification"],
            legacy_finding.payload["dependency_scope"],
            legacy_finding.payload["next_due_at"],
            0,
        ),
    )
    _, retry = authority.close_lease_and_transition(
        lease=first_lease,
        lease_state=LeaseState.RELEASED,
        work_state=WorkState.RETRY_PENDING,
        transitioned_at=_AT,
    )
    current = acquire_lease(
        work=retry,
        owner_digest="sha256:" + "2" * 64,
        acquired_at=_T118,
        progress_digest="sha256:" + "3" * 64,
        authority_deadline_at=_T120,
    )
    legacy_payload = dict(current.payload)
    legacy_payload.pop("authority_deadline_at")
    legacy_payload.pop("renewed_at")
    legacy_payload.pop("closed_at")
    legacy_payload["expires_at"] = "2042-01-05T00:02:59.000000Z"
    legacy_payload["maximum_expires_at"] = "2042-01-05T00:06:59.000000Z"
    legacy = operations.WorkLease.build(legacy_payload)
    connection.execute(
        "INSERT INTO work_leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            legacy.lease_id,
            legacy.payload["lease_version"],
            legacy.canonical_bytes,
            legacy.digest,
            legacy.payload["work_id"],
            legacy.payload["owner_digest"],
            legacy.payload["progress_digest"],
            legacy.payload["acquired_at"],
            legacy.payload["expires_at"],
            legacy.payload["maximum_expires_at"],
            legacy.payload["status"],
            legacy.payload["previous_digest"],
        ),
    )
    leased_twice = transition_work(retry, state=WorkState.LEASED, attempt_count=2)
    connection.execute(
        "INSERT INTO due_work VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            leased_twice.work_id,
            leased_twice.payload["state_version"],
            leased_twice.canonical_bytes,
            leased_twice.digest,
            leased_twice.payload["profile_record_id"],
            leased_twice.payload["logical_due_key"],
            leased_twice.payload["scope_kind"],
            leased_twice.payload["urgency"],
            leased_twice.payload["state"],
            leased_twice.payload["attempt_count"],
            leased_twice.payload["due_at"],
            leased_twice.payload["deadline_at"],
            leased_twice.payload["previous_digest"],
            leased_twice.payload["authority_version_digest"],
        ),
    )
    with pytest.raises(OperationalAuthorityError, match="authority deadline"):
        authority.close_lease_and_transition(
            lease=legacy,
            lease_state=LeaseState.RELEASED,
            work_state=WorkState.COMPLETED,
            transitioned_at=_T121,
        )
    connection.close()


def test_release_obeys_work_deadline_and_retry_failure_chronology(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    queued = enqueue_due_work(
        profile=profile,
        logical_due_key="lease:deadline-close",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE,
        due_at=_AT,
        deadline_at=_T2,
        authority_version_digest=_D,
    )
    authority.append_work(queued)
    lease, leased = _commit_lease(authority, queued, acquired_at=_T1)
    with pytest.raises(OperationalAuthorityError, match="deadline"):
        authority.close_lease_and_transition(
            lease=lease,
            lease_state=LeaseState.RELEASED,
            work_state=WorkState.COMPLETED,
            transitioned_at=_T5,
        )
    finding = build_retry_finding(
        work=leased,
        classification=RetryClassification.RETRYABLE,
        dependency_scope="FIXTURE_PROVIDER",
        first_attempt_at=_T1,
        failed_at=_T2,
    )
    authority.append_retry_finding(finding)
    with pytest.raises(OperationalAuthorityError, match="Finding differs"):
        authority.close_lease_and_transition(
            lease=lease,
            lease_state=LeaseState.RELEASED,
            work_state=WorkState.RETRY_PENDING,
            transitioned_at=_T1,
        )
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
    with pytest.raises(OperationalAuthorityError, match="deadline"):
        acquire_lease(
            work=expired,
            owner_digest="sha256:" + "4" * 64,
            acquired_at=_T5,
            progress_digest="sha256:" + "5" * 64,
        )
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
    routine = enqueue_due_work(
        profile=profile,
        logical_due_key="starvation:routine",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE,
        due_at="20420105T000000.000000Z",
        deadline_at="20420105T003000.000000Z",
        authority_version_digest=_D,
    )
    newer_routine = enqueue_due_work(
        profile=profile,
        logical_due_key="starvation:routine-newer",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE,
        due_at=_AT,
        deadline_at="2042-01-05T00:45:00.000000Z",
        authority_version_digest=_D,
    )
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
    authority.append_work(newer_routine)
    for item in urgent:
        authority.append_work(item)
    selected = authority.due_work("2042-01-05T00:00:20.000000Z")
    assert len(selected) == 2
    assert selected[0].payload["urgency"] == Urgency.URGENT.value
    assert routine in selected
    assert newer_routine not in selected
    connection.close()


def test_same_priority_work_uses_parsed_deadline_order(tmp_path, monkeypatch) -> None:
    profile_definition = dict(operations.INCREMENT_8_READINESS.operational_profile)
    schedule = dict(profile_definition["schedule"])
    schedule["maximum_catch_up_items"] = 1
    profile_definition["schedule"] = schedule
    monkeypatch.setattr(
        operations,
        "INCREMENT_8_READINESS",
        replace(
            operations.INCREMENT_8_READINESS, operational_profile=profile_definition
        ),
    )
    _, connection = _database(tmp_path)
    authority = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    authority.register_profile(profile)
    earlier = enqueue_due_work(
        profile=profile,
        logical_due_key="deadline:earlier",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.URGENT,
        due_at=_AT,
        deadline_at="20420105T003000.000000Z",
        authority_version_digest=_D,
    )
    later = enqueue_due_work(
        profile=profile,
        logical_due_key="deadline:later",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.URGENT,
        due_at=_AT,
        deadline_at="2042-01-05T00:45:00.000000Z",
        authority_version_digest=_D,
    )
    authority.append_work(earlier)
    authority.append_work(later)
    assert authority.due_work(_T2) == (earlier,)
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
