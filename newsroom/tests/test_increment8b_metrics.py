from __future__ import annotations

import json
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment8.evaluation import (
    EvaluationCase,
    ReviewLabel,
    RightsStatus,
    ReviewRole,
    RunKind,
    build_case,
    build_evaluation_plan,
    build_review_label,
    freeze_epoch,
    open_run,
)
from newsroom.increment8.metrics import (
    AblationResult,
    MeasurementStatus,
    MetricReport,
    MetricReportError,
    PerformanceMeasurement,
    ReviewedCaseOutcome,
    RoleRecommendation,
    SourceContribution,
    SourceRole,
    build_metric_report,
    reviewed_case_assessment_label,
)
from newsroom.increment8.readiness import INCREMENT_8_READINESS

_D = "sha256:" + "1" * 64
_AT = "2042-01-05T00:00:00.000000Z"
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
_TRIAGE_NAMES = ("false_correction", "false_development", "missed_development")


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
        metric_success = {name: True for name in _RATE_NAMES}
        if metric_fail is not None:
            failures_needed = (
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
            if index < failures_needed:
                metric_success[metric_fail] = False
        triage = {name: False for name in _TRIAGE_NAMES}
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
                metric_success=metric_success,
                triage_error=triage,
                slice_success=slice_success,
                zero_tolerance_findings=findings,
            ),
            blinded=True,
            recorded_at=_AT,
        )
        outcome = ReviewedCaseOutcome.build(
            case=case,
            review_label=label,
            metric_success=metric_success,
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


def test_complete_report_is_reconstructed_from_frozen_context_and_reviewed_cases() -> (
    None
):
    report = _report()
    assert report.overall_status is MeasurementStatus.PASS
    assert report.case_count == 120
    assert set(report.payload["case_stratum_counts"]) == {
        "NEGATIVE",
        "UNCHANGED",
        "FAILURE_HEAVY",
    }
    assert len(report.payload["reviewed_case_outcome_evidence"]) == 120
    assert (
        report.payload["coverage_scope"]
        == "REVIEWED_PROSPECTIVE_UNIVERSE_ONLY_NOT_ABSOLUTE_RECALL"
    )
    assert report.payload["production_activation_authorised"] is False
    assert report.payload["live_shadow_execution_authorised"] is False
    assert MetricReport.from_canonical_bytes(report.canonical_bytes) == report


def test_rate_slice_and_zero_results_are_derived_not_caller_supplied() -> None:
    context = _context()
    metric_failure = _report(
        context=context,
        case_outcomes=_case_outcomes(
            context=context, metric_fail="candidate_precision"
        ),
    )
    assert metric_failure.metric_status is MeasurementStatus.FAIL
    assert metric_failure.overall_status is MeasurementStatus.FAIL
    slice_failure = _report(
        context=context,
        case_outcomes=_case_outcomes(
            context=context, slice_fail="SOURCE_MULTI_DOMAIN_CORROBORATED"
        ),
    )
    assert slice_failure.slice_status is MeasurementStatus.FAIL
    blocker = _report(
        context=context,
        case_outcomes=_case_outcomes(
            context=context, count=1, zero_finding="temporal_rewrite"
        ),
    )
    assert blocker.overall_status is MeasurementStatus.FAIL


def test_every_frozen_exposure_minimum_is_enforced() -> None:
    context = _context()
    assert (
        _report(
            context=context,
            case_outcomes=_case_outcomes(context=context, count=119),
        ).overall_status
        is MeasurementStatus.NOT_EVALUATED
    )
    assert (
        _report(
            context=context,
            case_outcomes=_case_outcomes(
                context=context, insufficient_slice="SOURCE_MULTI_DOMAIN_CORROBORATED"
            ),
        ).overall_status
        is MeasurementStatus.NOT_EVALUATED
    )
    assert (
        _report(
            context=context,
            case_outcomes=_case_outcomes(
                context=context, insufficient_stratum="NEGATIVE"
            ),
        ).overall_status
        is MeasurementStatus.NOT_EVALUATED
    )


def test_required_development_and_correction_errors_are_retained_separately() -> None:
    context = _context()
    report = _report(
        context=context,
        case_outcomes=_case_outcomes(context=context, triage_error="false_correction"),
    )
    evidence = {
        item["payload"]["metric_name"]: item["payload"]
        for item in report.payload["triage_error_evidence"]
    }
    assert tuple(sorted(evidence)) == _TRIAGE_NAMES
    assert evidence["false_correction"]["error_count"] == 1
    assert all(
        item["decision_treatment"] == "MANDATORY_SEPARATE_REPORT_NO_POST_HOC_THRESHOLD"
        for item in evidence.values()
    )


def test_forged_run_case_or_report_bytes_fail_canonical_reconstruction() -> None:
    context = _context()
    forged_run = replace(
        context[2], payload={**context[2].payload, "production_effect_allowed": True}
    )
    with pytest.raises(MetricReportError, match="linkage"):
        _report(context=(context[0], context[1], forged_run))
    outcome = _case_outcomes(context=context)[0]
    forged = replace(outcome, slice_success=False)
    with pytest.raises(MetricReportError, match="forged"):
        _report(
            context=context,
            case_outcomes=(forged, *_case_outcomes(context=context)[1:]),
        )
    raw = _report().canonical_bytes.replace(
        b'"slice_success":true', b'"slice_success":false', 1
    )
    with pytest.raises(MetricReportError):
        MetricReport.from_canonical_bytes(raw)


def test_outcomes_require_exact_human_attestation_and_frozen_membership() -> None:
    context = _context()
    outcome = _case_outcomes(context=context)[0]
    document = json.loads(outcome.canonical_bytes)["payload"]

    case = EvaluationCase.from_canonical_bytes(canonical_json_bytes(document["case"]))
    label = ReviewLabel.from_canonical_bytes(
        canonical_json_bytes(document["review_label"])
    )
    arbitrary = build_review_label(
        case=case,
        reviewer_identity_digest=label.payload["reviewer_identity_digest"],
        role=ReviewRole.PRIMARY,
        label="PASS",
        blinded=True,
        recorded_at=_AT,
    )
    with pytest.raises(MetricReportError, match="does not attest"):
        ReviewedCaseOutcome.build(
            case=case,
            review_label=arbitrary,
            metric_success=outcome.metric_success,
            triage_error=outcome.triage_error,
            slice_success=outcome.slice_success,
        )
    forged_case = EvaluationCase.build(
        {**case.payload, "required_slices": ["URGENCY_URGENT"]}
    )
    forged_label = build_review_label(
        case=forged_case,
        reviewer_identity_digest=label.payload["reviewer_identity_digest"],
        role=ReviewRole.PRIMARY,
        label=reviewed_case_assessment_label(
            case=forged_case,
            metric_success=outcome.metric_success,
            triage_error=outcome.triage_error,
            slice_success=outcome.slice_success,
        ),
        blinded=True,
        recorded_at=_AT,
    )
    with pytest.raises(MetricReportError, match="membership"):
        ReviewedCaseOutcome.build(
            case=forged_case,
            review_label=forged_label,
            metric_success=outcome.metric_success,
            triage_error=outcome.triage_error,
            slice_success=outcome.slice_success,
        )


def test_source_dependency_evidence_is_explicit_and_reconstructed() -> None:
    report = _report()
    inventory = report.payload["source_dependency_inventory"]
    assert inventory == {"sha256:" + "d" * 64: ["anchor-fixture"]}
    with pytest.raises(MetricReportError, match="dependency roots"):
        SourceContribution.build(
            source_id="source",
            role=SourceRole.COMPLEMENT,
            provider_version_digest=_D,
            dependency_root_digests=(),
            unique_detection_count=0,
            earlier_detection_count=0,
            resilience_case_count=0,
            overlap_count=1,
            noise_count=0,
            gross_cost_microunits=0,
            rights_permitted=True,
            recommendation=RoleRecommendation.NO_CHANGE,
            rationale_digest=_D,
        )


def test_performance_failure_and_ablation_cannot_rescue_target() -> None:
    report = _report(performance=_performance(fail="case_latency_p95_ms"))
    assert report.performance_status is MeasurementStatus.FAIL
    assert report.overall_status is MeasurementStatus.FAIL
    assert report.payload["ablation_is_decision_bearing"] is False
