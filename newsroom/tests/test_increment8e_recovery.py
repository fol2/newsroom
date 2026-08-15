from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest

from newsroom.authority import migrations
from newsroom.increment8.operations import (
    OperationalAuthority,
    Urgency,
    build_operational_profile,
    enqueue_due_work,
)
from newsroom.increment8.recovery import (
    FaultScenario,
    RecoveryAuthority,
    RecoveryError,
    bounded_catch_up,
    build_fault_injection_run,
    build_purge_receipt,
    build_reconciliation_run,
    build_replay_receipt,
    create_checked_backup,
    restore_checked_backup,
)
from newsroom.tests.authority_migration_compatibility import build_exact_prefix

_AT = "2042-01-05T00:00:00.000000Z"
_LATER = "2042-01-05T00:10:00.000000Z"
_RETAIN = "2042-02-05T00:00:00.000000Z"
_D = "sha256:" + "1" * 64
_D2 = "sha256:" + "2" * 64


def _database(tmp_path):
    path = tmp_path / "authority.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    migrations.apply_pending_migrations(connection, applied_at=_AT)
    connection.execute("PRAGMA foreign_keys=ON")
    return path, connection


def _findings(value=0):
    return {
        "AMBIGUOUS_EFFECT": value,
        "DUPLICATE_DELIVERY": 0,
        "MISSING_OUTCOME": 0,
        "ORPHANED_OWNERSHIP": 0,
        "PENDING_HANDOFF": 0,
        "PROJECTION_MISMATCH": 0,
        "STALE_WORK": 0,
    }


def test_v31_to_v32_requires_exact_backup_and_preserves_prefix(tmp_path) -> None:
    path = tmp_path / "v31.sqlite3"
    build_exact_prefix(path, 31)
    connection = sqlite3.connect(path, isolation_level=None)
    with pytest.raises(sqlite3.DatabaseError, match="prepared backup"):
        migrations.apply_pending_migrations(connection, applied_at=_AT)
    receipt = migrations.prepare_pending_migration_backup(connection)
    assert receipt is not None
    migrations.apply_pending_migrations(connection, applied_at=_AT)
    assert connection.execute("PRAGMA user_version").fetchone() == (32,)
    assert connection.execute(
        "SELECT version,name FROM authority_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone() == (32, "increment8_recovery_authority_v32")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_reconciliation_detects_every_required_class_and_blocks_automatic_operation(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = RecoveryAuthority(connection)
    passed = build_reconciliation_run(
        profile_digest=_D, authority_version_digest=_D, finding_counts=_findings(),
        replay_item_count=10, started_at=_AT, completed_at=_LATER,
    )
    authority.append_reconciliation(passed)
    assert passed.payload["status"] == "PASS"
    failed = build_reconciliation_run(
        profile_digest=_D, authority_version_digest=_D, finding_counts=_findings(1),
        replay_item_count=10, started_at=_AT, completed_at=_LATER,
    )
    authority.append_reconciliation(failed)
    assert failed.payload["status"] == "FAIL"
    assert failed.payload["automatic_operation_blocked"] is True
    with pytest.raises(RecoveryError, match="reconciliation exceeds"):
        build_reconciliation_run(
            profile_digest=_D,
            authority_version_digest=_D,
            finding_counts=_findings(),
            replay_item_count=10,
            started_at=_AT,
            completed_at="2042-01-05T01:00:00.000000Z",
        )
    connection.close()


def test_checked_backup_restore_preserves_authority_and_requires_reconciliation(tmp_path) -> None:
    _, connection = _database(tmp_path)
    operational = OperationalAuthority(connection)
    operational.register_profile(build_operational_profile(approved_by_digest=_D, approved_at=_AT))
    backup = (tmp_path / "backup.sqlite3").absolute()
    manifest = create_checked_backup(
        connection, backup, profile_digest=_D, authority_version_digest=_D,
        audit_state_digest=_D, created_at=_AT, retain_until=_RETAIN,
    )
    recovery = RecoveryAuthority(connection)
    recovery.append_backup(manifest)
    restored = (tmp_path / "restored.sqlite3").absolute()
    restore = restore_checked_backup(manifest, backup, restored, completed_at=_LATER)
    recovery.append_restore(restore)
    payload = json.loads(restore.canonical_bytes)["payload"]
    assert payload["status"] == "RECONCILIATION_REQUIRED"
    assert payload["automatic_operation_resumed"] is False
    assert all(payload[name] is False for name in (
        "baselines_reconciled", "leases_reconciled", "queues_reconciled",
        "handoffs_reconciled", "coverage_reconciled",
    ))
    check = sqlite3.connect(restored, isolation_level=None)
    assert check.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert check.execute("SELECT COUNT(*) FROM operational_profiles").fetchone() == (1,)
    check.close()
    connection.close()


def test_backup_tamper_fails_closed(tmp_path) -> None:
    _, connection = _database(tmp_path)
    backup = (tmp_path / "backup.sqlite3").absolute()
    manifest = create_checked_backup(
        connection, backup, profile_digest=_D, authority_version_digest=_D,
        audit_state_digest=_D, created_at=_AT, retain_until=_RETAIN,
    )
    with backup.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(RecoveryError, match="file digest"):
        restore_checked_backup(manifest, backup, (tmp_path / "restored.sqlite3").absolute(), completed_at=_LATER)
    connection.close()


def test_versioned_replay_creates_later_output_without_rewriting_history() -> None:
    receipt = build_replay_receipt(
        input_digest=_D, later_output_digest=_D2, version_digests=[_D, _D2],
        replay_item_count=1000, completed_at=_LATER,
    )
    assert receipt.payload["history_rewritten"] is False
    with pytest.raises(RecoveryError, match="frozen bound"):
        build_replay_receipt(
            input_digest=_D, later_output_digest=_D2, version_digests=[_D],
            replay_item_count=1001, completed_at=_LATER,
        )


def test_purge_is_authorised_rebuild_required_and_append_only(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = RecoveryAuthority(connection)
    receipt = build_purge_receipt(
        scope_digest=_D, before_digest=_D, after_digest=_D2,
        authorised_by_digest=_D, reason_class="RIGHTS_CHANGE", purged_at=_AT,
    )
    authority.append_purge(receipt)
    assert receipt.payload["rebuild_required"] is True
    assert receipt.payload["automatic_operation_resumed"] is False
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE purge_receipts SET purged_at='changed'")
    connection.close()


def test_fault_injection_is_fixture_only_and_verifies_fail_closed_outcomes(tmp_path) -> None:
    _, connection = _database(tmp_path)
    authority = RecoveryAuthority(connection)
    for scenario, outcome in (
        (FaultScenario.STORE_FAILURE, "FAIL_CLOSED"),
        (FaultScenario.ORPHANED_OWNERSHIP, "LEASE_ORPHANED"),
        (FaultScenario.AMBIGUOUS_EFFECT, "BLOCK_AND_RECONCILE"),
        (FaultScenario.DUPLICATE_DELIVERY, "DEDUPLICATE"),
        (FaultScenario.PROJECTION_MISMATCH, "BLOCK_PROJECTION"),
    ):
        run = build_fault_injection_run(
            profile_digest=_D, scenario=scenario, observed_outcome=outcome, completed_at=_AT,
        )
        authority.append_fault(run)
        assert run.payload["status"] == "PASS"
        assert run.payload["live_effect_authorised"] is False
    connection.close()


def test_catch_up_is_bounded_and_prioritises_urgent_then_planned(tmp_path) -> None:
    _, connection = _database(tmp_path)
    operational = OperationalAuthority(connection)
    profile = build_operational_profile(approved_by_digest=_D, approved_at=_AT)
    operational.register_profile(profile)
    routine = enqueue_due_work(
        profile=profile, logical_due_key="routine", scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.ROUTINE, due_at=_AT, deadline_at=_LATER, authority_version_digest=_D,
    )
    urgent = enqueue_due_work(
        profile=profile, logical_due_key="urgent", scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.URGENT, due_at=_AT, deadline_at=_LATER, authority_version_digest=_D,
    )
    planned = enqueue_due_work(
        profile=profile, logical_due_key="planned", scope_kind="FIXTURE_SOURCE",
        urgency=Urgency.PLANNED, due_at=_AT, deadline_at=_LATER, authority_version_digest=_D,
    )
    assert bounded_catch_up([routine, planned, urgent]) == (urgent, planned, routine)
    with pytest.raises(RecoveryError, match="typed due work"):
        bounded_catch_up([replace(urgent, canonical_bytes=b"forged"), object()])  # type: ignore[list-item]
    connection.close()
