"""Repository-owned deterministic Increment 8 qualification fixture executor."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from newsroom.authority import migrations
from newsroom.increment6.handoffs import create_handoff
from newsroom.increment8.admission import (
    CostLicenceEvidence,
    IndependentVerificationEvidence,
    IntendedHardwareEvidence,
    RollbackEvidence,
    SubstantiveReviewEvidence,
    build_qualification_packet,
)
from newsroom.increment8.evaluation import (
    ReleaseVerdict,
    ReviewRole,
    RightsStatus,
    RunKind,
    build_adjudication,
    build_case,
    build_evaluation_plan,
    build_release_decision,
    build_review_label,
    freeze_epoch,
    open_run,
)
from newsroom.increment8.metrics import (
    AblationResult,
    PerformanceMeasurement,
    ReviewedCaseOutcome,
    RoleRecommendation,
    SourceContribution,
    SourceRole,
    build_metric_report,
    reviewed_case_assessment_label,
)
from newsroom.increment8.observability import (
    AccessContract,
    DimensionState,
    HealthDimension,
    HealthPosture,
    ObservabilityRecord,
    ObservationOutcome,
    SecurityAdmission,
)
from newsroom.increment8.operations import (
    HandoffRegistrationAnchor,
    OperationalAuthority,
    build_capacity_evidence,
    build_operational_profile,
    register_anchored_handoff,
)
from newsroom.increment8.readiness import INCREMENT_8_READINESS
from newsroom.increment8.recovery import (
    FaultScenario,
    build_fault_injection_run,
    build_reconciliation_run,
    build_restore_reconciliation_run,
    create_checked_backup,
    restore_checked_backup,
)

_D = "sha256:" + "1" * 64
_D2 = "sha256:" + "2" * 64
_D3 = "sha256:" + "3" * 64
_AT = "2042-01-05T00:00:00.000000Z"
_RECENT = "2042-01-04T23:59:00.000000Z"
_LATER = "2042-01-05T00:10:00.000000Z"
_AFTER_RESTORE = "2042-01-05T00:20:00.000000Z"
_AFTER_RECONCILIATION = "2042-01-05T00:30:00.000000Z"
_RETAIN = "2042-02-05T00:00:00.000000Z"
_RATE_NAMES = (
    "bounded_event_coverage",
    "candidate_precision",
    "candidate_recall",
    "duplicate_candidate",
    "false_merge",
    "fragmentation",
    "grouping_precision",
    "grouping_recall",
    "reviewer_agreement",
    "route_decision_agreement",
    "snowball_absorption",
    "unnecessary_candidate",
)
_CASE_RATE_NAMES = tuple(name for name in _RATE_NAMES if name != "reviewer_agreement")
_TRIAGE_NAMES = ("false_correction", "false_development", "missed_development")

FIXTURE_ADMISSION_OWNER_DIGEST = _D3
FIXTURE_DECISION_RECORDED_AT_DIGEST = _D


def _context(kind: RunKind = RunKind.QUALIFICATION):
    plan = build_evaluation_plan(
        component_manifest_digest=_D,
        approved_by_digest="sha256:" + "2" * 64,
        approved_at=_AT,
        authorised_primary_reviewer_digests=(
            "sha256:" + "2" * 64,
            "sha256:" + "6" * 64,
        ),
        authorised_secondary_reviewer_digests=("sha256:" + "7" * 64,),
        authorised_adjudicator_digests=("sha256:" + "8" * 64,),
        authorised_release_owner_digests=("sha256:" + "9" * 64,),
    )
    epoch = freeze_epoch(
        plan=plan,
        target_manifest_digest="sha256:" + "3" * 64,
        universe_manifest_digest="sha256:" + "4" * 64,
        sampling_method_digest="sha256:" + "5" * 64,
        cutoff_at=_AT,
        opened_at=_AT,
    )
    return plan, epoch, open_run(epoch=epoch, kind=kind, started_at=_AT)


def _run(kind: RunKind = RunKind.QUALIFICATION):
    return _context(kind)[2]


def _case_outcomes(
    *,
    context=None,
    count: int = 120,
    metric_fail: str | None = None,
    metric_failure_count: int | None = None,
    triage_eligible_count: int = 120,
    metric_eligible_counts: Mapping[str, int] | None = None,
    slice_fail: str | None = None,
    insufficient_slice: str | None = None,
    insufficient_stratum: str | None = None,
    zero_finding: str | None = None,
    triage_error: str | None = None,
):
    plan, epoch, run = context or _context()
    del epoch
    primary_reviewers = tuple(
        str(item["identity_digest"])
        for item in plan.payload["authorised_human_manifest"]
        if "PRIMARY" in item["roles"]
    )
    secondary_reviewers = tuple(
        str(item["identity_digest"])
        for item in plan.payload["authorised_human_manifest"]
        if "SECONDARY" in item["roles"]
    )
    adjudicator = next(
        str(item["identity_digest"])
        for item in plan.payload["authorised_human_manifest"]
        if "ADJUDICATOR" in item["roles"]
    )
    output = []
    for index in range(count):
        geography = ("GLOBAL", "HONG_KONG", "UNITED_KINGDOM")[index % 3]
        language = ("EN_GB", "MIXED_EN_GB_ZH_HANT_HK", "ZH_HANT_HK")[index % 3]
        source_member = index < (
            11 if insufficient_slice == "SOURCE_MULTI_DOMAIN_CORROBORATED" else 20
        )
        failure_member = index < 20
        urgent_member = index < 20
        negative_member = index < (11 if insufficient_stratum == "NEGATIVE" else 20)
        unchanged_member = 20 <= index < 40
        case = build_case(
            run=run,
            input_manifest_digest="sha256:" + f"{index + 1000:064x}",
            cutoff_at=_AT,
            membership_facts={
                "case_metadata": {
                    "geography": geography,
                    "language": language,
                    "urgency": "URGENT" if urgent_member else "ROUTINE",
                },
                "source_evidence": {"distinct_domain_count": 2 if source_member else 1},
                "fixture": {"injected_failure_count": 2 if failure_member else 0},
                "expected": {
                    "candidate_outcome": "NO_CANDIDATE"
                    if negative_member
                    else "CANDIDATE",
                    "transition_outcome": "UNCHANGED"
                    if unchanged_member
                    else "CHANGED",
                },
            },
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
            urgent=urgent_member,
            zero_tolerance=zero_finding is not None and index == 0,
        )
        metric_eligible = {
            name: index < (metric_eligible_counts or {}).get(name, count)
            for name in _CASE_RATE_NAMES
        }
        metric_success = {name: True for name in _CASE_RATE_NAMES}
        if metric_fail is not None:
            failures_needed = metric_failure_count or (
                7
                if metric_fail
                in {
                    "bounded_event_coverage",
                    "candidate_precision",
                    "candidate_recall",
                    "grouping_precision",
                    "grouping_recall",
                    "reviewer_agreement",
                    "route_decision_agreement",
                }
                else 3
            )
            if metric_fail != "reviewer_agreement" and index < failures_needed:
                metric_success[metric_fail] = False
        triage = {name: False for name in _TRIAGE_NAMES}
        triage_eligible = {
            name: index < triage_eligible_count for name in _TRIAGE_NAMES
        }
        if triage_error is not None and index == 0:
            triage[triage_error] = True
        slice_success = not (
            slice_fail in case.payload["required_slices"] and index < 8
        )
        findings = (zero_finding,) if index == 0 and zero_finding else ()
        label = build_review_label(
            case=case,
            reviewer_identity_digest=primary_reviewers[index % len(primary_reviewers)],
            role=ReviewRole.PRIMARY,
            label=reviewed_case_assessment_label(
                case=case,
                metric_eligible=metric_eligible,
                metric_success=metric_success,
                triage_eligible=triage_eligible,
                triage_error=triage,
                slice_success=slice_success,
                zero_tolerance_findings=findings,
            ),
            blinded=True,
            recorded_at=_AT,
        )
        secondary_label = None
        adjudication = None
        if index < 24:
            secondary_identity = next(
                identity
                for identity in secondary_reviewers
                if identity != label.payload["reviewer_identity_digest"]
            )
            secondary_label = build_review_label(
                case=case,
                reviewer_identity_digest=secondary_identity,
                role=ReviewRole.SECONDARY,
                label=(
                    "disagreement"
                    if metric_fail == "reviewer_agreement" and index < 4
                    else label.payload["label"]
                ),
                blinded=True,
                recorded_at=_AT,
            )
            if secondary_label.payload["label"] != label.payload["label"]:
                adjudication = build_adjudication(
                    case=case,
                    primary=label,
                    secondary=secondary_label,
                    adjudicator_identity_digest=adjudicator,
                    final_label=label.payload["label"],
                    decided_at=_AT,
                )
        outcome = ReviewedCaseOutcome.build(
            case=case,
            review_label=label,
            secondary_review_label=secondary_label,
            adjudication=adjudication,
            metric_eligible=metric_eligible,
            metric_success=metric_success,
            triage_eligible=triage_eligible,
            triage_error=triage,
            slice_success=slice_success,
            zero_tolerance_findings=findings,
        )
        output.append(outcome)
    return tuple(sorted(output, key=lambda item: item.case_id))


def _performance(*, fail: str | None = None):
    limits = INCREMENT_8_READINESS.evaluation_plan["performance_limits"]
    return tuple(
        PerformanceMeasurement.build(
            metric_name=name,
            observed_value=int(limits[name]) + (1 if name == fail else 0),
        )
        for name in sorted(limits)
    )


def _contributions():
    return (
        SourceContribution.build(
            source_id="anchor-fixture",
            role=SourceRole.ANCHOR,
            provider_version_digest="sha256:" + "6" * 64,
            dependency_root_digests=("sha256:" + "d" * 64,),
            unique_detection_count=1,
            earlier_detection_count=2,
            resilience_case_count=3,
            overlap_count=10,
            noise_count=1,
            gross_cost_microunits=0,
            rights_permitted=True,
            recommendation=RoleRecommendation.RETAIN,
            rationale_digest="sha256:" + "7" * 64,
        ),
    )


def _ablations():
    return (
        AblationResult.build(
            component_id="exact-only",
            component_version_digest="sha256:" + "8" * 64,
            evaluated_case_count=120,
            lost_detection_count=3,
            earlier_detection_lost_count=2,
            resilience_loss_count=1,
            noise_removed_count=4,
            cost_removed_microunits=0,
            affected_slices=("LANGUAGE_ZH_HANT_HK",),
        ),
    )


def _report(**changes):
    context = changes.pop("context", _context())
    case_outcomes = changes.pop("case_outcomes", _case_outcomes(context=context))
    values = {
        "plan": context[0],
        "epoch": context[1],
        "run": context[2],
        "case_outcomes": case_outcomes,
        "performance": _performance(),
        "contributions": _contributions(),
        "ablations": _ablations(),
        "metric_code_digest": "sha256:" + "9" * 64,
        "environment_digest": "sha256:" + "a" * 64,
        "sampling_manifest_digest": "sha256:" + "b" * 64,
        "label_manifest_digest": "sha256:" + "b" * 64,
    }
    values.update(changes)
    return build_metric_report(**values)


def _dimensions(state=DimensionState.HEALTHY):
    return {dimension.value: state for dimension in HealthDimension}


def _health(
    *, outcome=ObservationOutcome.COMPLETE_UNCHANGED, success=_RECENT, states=None
):
    return HealthPosture.build(
        scope_id="fixture-source:one",
        dimension_states=_dimensions() if states is None else states,
        observation_outcome=outcome,
        last_complete_success_at=success,
        last_source_change_at="2042-01-01T00:00:00.000000Z",
        observed_at=_AT,
    )


def _access():
    return AccessContract.build(
        contract_id="fixture-access:v1",
        approved_hosts=["fixture.invalid"],
        maximum_redirects=0,
        request_timeout_seconds=30,
        maximum_body_bytes=1_000_000,
        content_types=["application/json", "application/xml"],
    )


def _capacity():
    return build_capacity_evidence(
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


def _reconciliation(profile_digest=_D):
    return build_reconciliation_run(
        profile_digest=profile_digest,
        authority_version_digest=_D,
        finding_counts={
            "AMBIGUOUS_EFFECT": 0,
            "DUPLICATE_DELIVERY": 0,
            "MISSING_OUTCOME": 0,
            "ORPHANED_OWNERSHIP": 0,
            "PENDING_HANDOFF": 0,
            "PROJECTION_MISMATCH": 0,
            "STALE_WORK": 0,
        },
        replay_item_count=10,
        started_at=_AT,
        completed_at=_LATER,
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
            profile_digest=profile_digest,
            scenario=scenario,
            observed_outcome=outcomes[scenario],
            completed_at=_AT,
        )
        for scenario in FaultScenario
    )


def _observability(profile_digest=_D):
    names = (
        "budget",
        "complete_success_age",
        "coverage",
        "outcome",
        "parser",
        "queue",
        "reconciliation",
        "retry",
        "schedule",
        "storage",
    )
    stages = (
        "candidate",
        "check",
        "due_trigger",
        "handoff",
        "lead",
        "transition",
        "work_item",
    )
    return ObservabilityRecord.build(
        source_version_digest=_D,
        component_version_digest=_D,
        profile_digest=profile_digest,
        provider_version_digest=_D,
        policy_version_digest=_D,
        metrics={name: 0 for name in names},
        path_correlation={name: _D for name in stages},
        coverage_blocked=False,
        integrity_uncertain=False,
        urgent=False,
        owner_digest=_D,
        escalation_digest=_D,
        runbook_version_digest=_D,
    )


def _security():
    return SecurityAdmission.build(
        access_contract=_access(),
        exact_version_approved=True,
        rights_current=True,
        terms_current=True,
        pricing_current=True,
        credential_scope_current=True,
        rollback_tested=True,
        scoped_disable_tested=True,
        graph_capability_admitted=True,
        runbook_version_digest=_D,
    )


def _cost():
    return CostLicenceEvidence.build(
        external_spend_pence=0,
        internal_fixture_cost_pence=0,
        licence_review_digests={
            "neo4j-community": _D,
            "python-runtime": _D,
            "repository-components": _D,
        },
        terms_review_digest=_D,
        pricing_review_digest=_D,
        replacement_path_digest=_D,
    )


def _rollback(restore):
    return RollbackEvidence.build(
        restore=restore,
        runbook_version_digest=_D,
        rollback_plan_digest=_D,
        tested_at=_AFTER_RECONCILIATION,
    )


def _independent(reviewed_evidence_manifest_digest=_D):
    return IndependentVerificationEvidence.build(
        verifier_identity_digest=_D2,
        verification_method_digest=_D,
        reviewed_evidence_manifest_digest=reviewed_evidence_manifest_digest,
        verified_at_digest=_D,
    )


def _packet(tmp_path, *, substantive_review: SubstantiveReviewEvidence, **changes):
    tmp_path.mkdir(parents=True, exist_ok=True)
    database = tmp_path / "authority.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    migrations.apply_pending_migrations(connection, applied_at=_AT)
    operational_profile = build_operational_profile(
        approved_by_digest=_D, approved_at=_AT
    )
    authority = OperationalAuthority(connection)
    authority.register_profile(operational_profile)
    handoff = create_handoff(
        "candidate-version:qualification",
        _D,
        "evaluation-sink:fixture",
        max_attempts=3,
    )
    register_anchored_handoff(connection, handoff, registered_at=_AT)
    anchor_row = connection.execute(
        "SELECT anchor_bytes FROM handoff_registration_anchors WHERE handoff_id=?",
        (handoff.handoff_id,),
    ).fetchone()
    if anchor_row is None:
        raise RuntimeError("qualification Handoff anchor was not retained")
    anchor = HandoffRegistrationAnchor.from_canonical_bytes(bytes(anchor_row[0]))
    backup_path = (tmp_path / "backup.sqlite3").absolute()
    backup = create_checked_backup(
        connection,
        backup_path,
        profile_digest=operational_profile.digest,
        authority_version_digest=_D,
        audit_state_digest=_D,
        created_at=_AT,
        retain_until=_RETAIN,
    )
    restore = restore_checked_backup(
        backup,
        backup_path,
        (tmp_path / "restored.sqlite3").absolute(),
        completed_at=_LATER,
    )
    connection.close()
    report = _report()
    release = build_release_decision(
        run=_run(),
        report_canonical_bytes=report.canonical_bytes,
        evidence_manifest_digest=report.payload["sampling_manifest_digest"],
        verdict=ReleaseVerdict.PASS,
        owner_identity_digest=_D,
        decided_at=_AT,
    )
    capacity = _capacity()
    values = {
        "release_decision": release,
        "metric_report": report,
        "operational_profile": operational_profile,
        "capacity": capacity,
        "health_postures": [_health()],
        "observability": _observability(operational_profile.digest),
        "security": _security(),
        "reconciliation": _reconciliation(operational_profile.digest),
        "backup": backup,
        "restore": restore,
        "restore_reconciliation": build_restore_reconciliation_run(
            restore=restore,
            profile_digest=operational_profile.digest,
            authority_version_digest=_D,
            finding_counts={
                "AMBIGUOUS_EFFECT": 0,
                "DUPLICATE_DELIVERY": 0,
                "MISSING_OUTCOME": 0,
                "ORPHANED_OWNERSHIP": 0,
                "PENDING_HANDOFF": 0,
                "PROJECTION_MISMATCH": 0,
                "STALE_WORK": 0,
            },
            replay_item_count=10,
            started_at=_AFTER_RESTORE,
            completed_at=_AFTER_RECONCILIATION,
        ),
        "fault_runs": _faults(operational_profile.digest),
        "handoff_anchor": anchor,
        "expected_handoff_anchor_digest": anchor.digest,
        "hardware": IntendedHardwareEvidence.build(
            target_id="fixture-host:v1",
            cpu_cores=4,
            memory_mib=8192,
            free_disk_mib=10240,
            capacity=capacity,
            inventory_digest=_D,
            measured_at_digest=_D,
        ),
        "cost_licence": _cost(),
        "runbook_version_digest": _D,
        "rollback_evidence": _rollback(restore),
        "independent_verification": _independent(
            str(release.payload["evidence_manifest_digest"])
        ),
        "substantive_review": substantive_review,
    }
    values.update(changes)
    return build_qualification_packet(**values)


def execute_qualification_fixture(
    workspace, *, substantive_review: SubstantiveReviewEvidence
):
    """Execute the frozen 120-Case fixture and return its exact packet."""
    return _packet(workspace, substantive_review=substantive_review)


__all__ = [
    "FIXTURE_ADMISSION_OWNER_DIGEST",
    "FIXTURE_DECISION_RECORDED_AT_DIGEST",
    "execute_qualification_fixture",
]
