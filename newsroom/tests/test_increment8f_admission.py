from __future__ import annotations

import sqlite3
from inspect import signature

import pytest

from newsroom.authority import migrations
from newsroom.increment8.admission import (
    AdmissionError,
    CostLicenceEvidence,
    IndependentVerificationEvidence,
    IntendedHardwareEvidence,
    RollbackEvidence,
    build_operational_admission_decision,
    build_qualification_packet,
)
from newsroom.increment8.evaluation import (
    ReleaseVerdict,
    build_release_decision,
)
from newsroom.increment8.observability import ObservabilityRecord, SecurityAdmission
from newsroom.increment8.operations import (
    HandoffAnchorKind,
    _handoff_anchor,
    build_capacity_evidence,
    build_operational_profile,
)
from newsroom.increment8.recovery import (
    FaultScenario,
    build_fault_injection_run,
    build_reconciliation_run,
    build_restore_reconciliation_run,
    create_checked_backup,
    restore_checked_backup,
)
from newsroom.tests.test_increment8b_metrics import _report, _run
from newsroom.tests.test_increment8d_observability import _access, _health

_D = "sha256:" + "1" * 64
_D2 = "sha256:" + "2" * 64
_D3 = "sha256:" + "3" * 64
_AT = "2042-01-05T00:00:00.000000Z"
_LATER = "2042-01-05T00:10:00.000000Z"
_AFTER_RESTORE = "2042-01-05T00:20:00.000000Z"
_AFTER_RECONCILIATION = "2042-01-05T00:30:00.000000Z"
_RETAIN = "2042-02-05T00:00:00.000000Z"


def _capacity():
    return build_capacity_evidence(
        scenario_counts={"AVERAGE": 10, "FAILURE_HEAVY": 10, "NO_CHANGE_HEAVY": 10, "PEAK": 10},
        cpu_cores=4, memory_mib=8192, free_disk_mib=10240, peak_queue_items=500,
        urgent_capacity_items=200, worker_throughput_per_minute=20, operator_minutes=5,
    )


def _reconciliation(profile_digest=_D):
    return build_reconciliation_run(
        profile_digest=profile_digest, authority_version_digest=_D,
        finding_counts={
            "AMBIGUOUS_EFFECT": 0, "DUPLICATE_DELIVERY": 0, "MISSING_OUTCOME": 0,
            "ORPHANED_OWNERSHIP": 0, "PENDING_HANDOFF": 0, "PROJECTION_MISMATCH": 0,
            "STALE_WORK": 0,
        },
        replay_item_count=10, started_at=_AT, completed_at=_LATER,
    )


def _faults(profile_digest=_D):
    outcomes = {
        FaultScenario.STORE_FAILURE: "FAIL_CLOSED",
        FaultScenario.ORPHANED_OWNERSHIP: "LEASE_ORPHANED",
        FaultScenario.MISSING_OUTCOME: "RETAIN_PENDING",
        FaultScenario.AMBIGUOUS_EFFECT: "BLOCK_AND_RECONCILE",
        FaultScenario.DUPLICATE_DELIVERY: "DEDUPLICATE",
        FaultScenario.STALE_WORK: "REVALIDATE",
        FaultScenario.PENDING_HANDOFF: "RETAIN_PENDING",
        FaultScenario.PROJECTION_MISMATCH: "BLOCK_PROJECTION",
    }
    return tuple(
        build_fault_injection_run(
            profile_digest=profile_digest, scenario=scenario, observed_outcome=outcomes[scenario], completed_at=_AT,
        )
        for scenario in FaultScenario
    )


def _observability(profile_digest=_D):
    names = ("budget", "complete_success_age", "coverage", "outcome", "parser", "queue", "reconciliation", "retry", "schedule", "storage")
    stages = ("candidate", "check", "due_trigger", "handoff", "lead", "transition", "work_item")
    return ObservabilityRecord.build(
        source_version_digest=_D, component_version_digest=_D, profile_digest=profile_digest,
        provider_version_digest=_D, policy_version_digest=_D, metrics={name: 0 for name in names},
        path_correlation={name: _D for name in stages}, coverage_blocked=False,
        integrity_uncertain=False, urgent=False, owner_digest=_D, escalation_digest=_D,
        runbook_version_digest=_D,
    )


def _security():
    return SecurityAdmission.build(
        access_contract=_access(), exact_version_approved=True, rights_current=True,
        terms_current=True, pricing_current=True, credential_scope_current=True,
        rollback_tested=True, scoped_disable_tested=True, graph_capability_admitted=True,
        runbook_version_digest=_D,
    )


def _cost():
    return CostLicenceEvidence.build(
        external_spend_pence=0, internal_fixture_cost_pence=0,
        licence_review_digests={
            "neo4j-community": _D, "python-runtime": _D, "repository-components": _D,
        },
        terms_review_digest=_D, pricing_review_digest=_D, replacement_path_digest=_D,
    )


def _rollback(restored_state_digest=_D):
    return RollbackEvidence.build(
        runbook_version_digest=_D,
        rollback_plan_digest=_D,
        restored_state_digest=restored_state_digest,
        tested_at_digest=_D,
    )


def _independent(reviewed_evidence_manifest_digest=_D):
    return IndependentVerificationEvidence.build(
        verifier_identity_digest=_D2,
        verification_method_digest=_D,
        reviewed_evidence_manifest_digest=reviewed_evidence_manifest_digest,
        verified_at_digest=_D,
    )


def _packet(tmp_path, **changes):
    tmp_path.mkdir(parents=True, exist_ok=True)
    database = tmp_path / "authority.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    migrations.apply_pending_migrations(connection, applied_at=_AT)
    operational_profile = build_operational_profile(
        approved_by_digest=_D, approved_at=_AT
    )
    backup_path = (tmp_path / "backup.sqlite3").absolute()
    backup = create_checked_backup(
        connection, backup_path, profile_digest=operational_profile.digest,
        authority_version_digest=_D,
        audit_state_digest=_D, created_at=_AT, retain_until=_RETAIN,
    )
    restore = restore_checked_backup(
        backup, backup_path, (tmp_path / "restored.sqlite3").absolute(), completed_at=_LATER,
    )
    connection.close()
    report = _report()
    release = build_release_decision(
        run=_run(), report_canonical_bytes=report.canonical_bytes,
        evidence_manifest_digest=report.payload["sampling_manifest_digest"], verdict=ReleaseVerdict.PASS,
        owner_identity_digest=_D, decided_at=_AT,
    )
    capacity = _capacity()
    anchor = _handoff_anchor(
        handoff_id="handoff:fixture", candidate_version_id="candidate:fixture",
        governing_manifest_digest=_D, sink_id="sink:fixture", max_attempts=3,
        kind=HandoffAnchorKind.ORIGINAL_REGISTRATION, recorded_at=_AT,
    )
    values = {
        "release_decision": release, "metric_report": report,
        "operational_profile": operational_profile, "capacity": capacity,
        "health_postures": [_health()],
        "observability": _observability(operational_profile.digest),
        "security": _security(),
        "reconciliation": _reconciliation(operational_profile.digest),
        "backup": backup, "restore": restore,
        "restore_reconciliation": build_restore_reconciliation_run(
            restore=restore,
            profile_digest=operational_profile.digest,
            authority_version_digest=_D,
            finding_counts={
                "AMBIGUOUS_EFFECT": 0, "DUPLICATE_DELIVERY": 0,
                "MISSING_OUTCOME": 0, "ORPHANED_OWNERSHIP": 0,
                "PENDING_HANDOFF": 0, "PROJECTION_MISMATCH": 0,
                "STALE_WORK": 0,
            },
            replay_item_count=10, started_at=_AFTER_RESTORE,
            completed_at=_AFTER_RECONCILIATION,
        ),
        "fault_runs": _faults(operational_profile.digest),
        "handoff_anchor": anchor, "expected_handoff_anchor_digest": anchor.digest,
        "hardware": IntendedHardwareEvidence.build(
            target_id="fixture-host:v1", cpu_cores=4, memory_mib=8192, free_disk_mib=10240,
            capacity=capacity, inventory_digest=_D, measured_at_digest=_D,
        ),
        "cost_licence": _cost(), "runbook_version_digest": _D,
        "rollback_evidence": _rollback(str(restore.payload["restored_logical_digest"])),
        "independent_verification": _independent(
            str(release.payload["evidence_manifest_digest"])
        ),
        "p1_finding_count": 0, "material_p2_finding_count": 0,
    }
    values.update(changes)
    return build_qualification_packet(**values)


def test_complete_packet_binds_every_gate_and_admits_only_fixture_operation(tmp_path) -> None:
    with pytest.raises(AdmissionError, match="corrective readiness"):
        _packet(tmp_path)


def test_hardware_cost_and_licence_values_are_exact_and_non_activating() -> None:
    capacity = _capacity()
    hardware = IntendedHardwareEvidence.build(
        target_id="fixture-host:v1", cpu_cores=4, memory_mib=8192, free_disk_mib=10240,
        capacity=capacity, inventory_digest=_D, measured_at_digest=_D,
    )
    assert hardware.capacity_digest == capacity.digest
    assert _cost().external_spend_pence == 0
    with pytest.raises(AdmissionError, match="cost or licence"):
        CostLicenceEvidence.build(
            external_spend_pence=1, internal_fixture_cost_pence=0,
            licence_review_digests={"neo4j-community": _D}, terms_review_digest=_D,
            pricing_review_digest=_D, replacement_path_digest=_D,
        )


def test_missing_fault_scenario_or_blocking_security_fails_closed(tmp_path) -> None:
    arguments = {
        name: None for name in signature(build_qualification_packet).parameters
    }
    with pytest.raises(AdmissionError, match="packet construction.*corrective"):
        build_qualification_packet(**arguments)


def test_handoff_anchor_digest_and_substantive_review_are_hard_gates(tmp_path) -> None:
    with pytest.raises(AdmissionError, match="Operational Admission.*corrective"):
        build_operational_admission_decision(
            packet=object(),  # type: ignore[arg-type]
            owner_identity_digest=_D,
            decision_recorded_at_digest=_D,
        )
