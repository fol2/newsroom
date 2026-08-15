from __future__ import annotations

import sqlite3
from dataclasses import replace
from types import MappingProxyType

import pytest

from newsroom.authority import migrations
from newsroom.authority.increment8_recovery_migrations import _helpers
from newsroom.increment8.operations import (
    OperationalAuthority,
    Urgency,
    build_operational_profile,
    enqueue_due_work,
)
from newsroom.increment8.recovery import (
    FaultInjectionRun,
    FaultScenario,
    RecoveryAuthority,
    RecoveryError,
    bounded_catch_up,
    build_fault_injection_run,
    create_checked_backup,
    restore_checked_backup,
)

_AT = "2042-01-05T00:00:00.000000Z"
_LATER = "2042-01-05T00:10:00.000000Z"
_RETAIN = "2042-02-05T00:00:00.000000Z"
_D = "sha256:" + "1" * 64


def _database(tmp_path):
    path = tmp_path / "authority.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    migrations.apply_pending_migrations(connection, applied_at=_AT)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _manifest(tmp_path):
    connection = _database(tmp_path)
    source = (tmp_path / "backup.sqlite3").absolute()
    manifest = create_checked_backup(
        connection,
        source,
        profile_digest=_D,
        authority_version_digest=_D,
        audit_state_digest=_D,
        created_at=_AT,
        retain_until=_RETAIN,
    )
    return connection, source, manifest


def test_recovery_authority_requires_idle_foreign_key_enabled_connection(
    tmp_path,
) -> None:
    connection = _database(tmp_path)
    connection.execute("PRAGMA foreign_keys=OFF")
    with pytest.raises(RecoveryError, match="foreign-key-enabled"):
        RecoveryAuthority(connection)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN")
    with pytest.raises(RecoveryError, match="idle"):
        RecoveryAuthority(connection)
    connection.execute("ROLLBACK")
    RecoveryAuthority(connection)
    connection.close()


def test_fault_run_reconstruction_rejects_self_consistent_semantic_forgery(
    tmp_path,
) -> None:
    connection = _database(tmp_path)
    authority = RecoveryAuthority(connection)
    forged = FaultInjectionRun.build(
        {
            "profile_digest": _D,
            "scenario": FaultScenario.STORE_FAILURE.value,
            "expected_outcome": "FAIL_CLOSED",
            "observed_outcome": "NOT_CLOSED",
            "completed_at": _AT,
            "status": "PASS",
            "live_effect_authorised": False,
        }
    )
    with pytest.raises(RecoveryError, match="semantics differ"):
        authority.append_fault(forged)

    valid = build_fault_injection_run(
        profile_digest=_D,
        scenario=FaultScenario.STORE_FAILURE,
        observed_outcome="FAIL_CLOSED",
        completed_at=_AT,
    )
    detached = replace(
        valid,
        payload=MappingProxyType({**valid.payload, "live_effect_authorised": True}),
    )
    with pytest.raises(RecoveryError, match="forged"):
        authority.append_fault(detached)
    assert connection.execute(
        "SELECT COUNT(*) FROM fault_injection_runs"
    ).fetchone() == (0,)
    connection.close()


def test_catch_up_reconstructs_every_due_work_before_sorting(tmp_path) -> None:
    connection = _database(tmp_path)
    operational = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    operational.register_profile(profile)
    due = enqueue_due_work(
        profile=profile,
        logical_due_key="urgent",
        scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.URGENT,
        due_at=_AT,
        deadline_at=_LATER,
        authority_version_digest=_D,
    )
    forged_bytes = replace(due, canonical_bytes=b"{}")
    with pytest.raises(RecoveryError, match="forged"):
        bounded_catch_up([forged_bytes])
    detached = replace(
        due,
        payload=MappingProxyType({**due.payload, "urgency": Urgency.ROUTINE.value}),
    )
    with pytest.raises(RecoveryError, match="forged"):
        bounded_catch_up([detached])
    connection.close()


def test_failed_backup_removes_partial_destination_and_same_path_can_retry(
    tmp_path, monkeypatch
) -> None:
    connection = _database(tmp_path)
    destination = (tmp_path / "backup.sqlite3").absolute()
    original_digest = _helpers._file_digest
    first = True

    def fail_once(path):
        nonlocal first
        if path == destination and first:
            first = False
            raise RuntimeError("injected digest failure")
        return original_digest(path)

    monkeypatch.setattr(_helpers, "_file_digest", fail_once)
    with pytest.raises(RuntimeError, match="injected digest failure"):
        create_checked_backup(
            connection,
            destination,
            profile_digest=_D,
            authority_version_digest=_D,
            audit_state_digest=_D,
            created_at=_AT,
            retain_until=_RETAIN,
        )
    assert not destination.exists()

    manifest = create_checked_backup(
        connection,
        destination,
        profile_digest=_D,
        authority_version_digest=_D,
        audit_state_digest=_D,
        created_at=_AT,
        retain_until=_RETAIN,
    )
    assert destination.is_file()
    assert manifest.payload["backup_file_digest"] == original_digest(destination)
    connection.close()


def test_restore_rejects_missing_parent_without_creating_partial_destination(
    tmp_path,
) -> None:
    connection, source, manifest = _manifest(tmp_path)
    destination = (tmp_path / "absent" / "restored.sqlite3").absolute()
    with pytest.raises(RecoveryError, match="parent is absent"):
        restore_checked_backup(manifest, source, destination, completed_at=_LATER)
    assert not destination.exists()
    connection.close()


def test_restore_failure_removes_partial_destination(tmp_path, monkeypatch) -> None:
    connection, source, manifest = _manifest(tmp_path)
    destination = (tmp_path / "restored.sqlite3").absolute()
    original_logical = _helpers._logical_database_digest
    calls = 0

    def diverge_after_copy(database):
        nonlocal calls
        calls += 1
        value = original_logical(database)
        if calls == 2:
            return "sha256:" + "f" * 64
        return value

    monkeypatch.setattr(_helpers, "_logical_database_digest", diverge_after_copy)
    with pytest.raises(RecoveryError, match="restored authority differs"):
        restore_checked_backup(manifest, source, destination, completed_at=_LATER)
    assert not destination.exists()
    connection.close()
