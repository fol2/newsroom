from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.increment8.evaluation import (
    RunKind,
    build_evaluation_plan,
    freeze_epoch,
    open_run,
)
from newsroom.increment8.metrics import (
    REQUIRED_SLICES,
    AblationResult,
    MeasurementStatus,
    MetricReportError,
    PerformanceMeasurement,
    RateMeasurement,
    RequiredSliceResult,
    RoleRecommendation,
    SamplingMethod,
    SourceContribution,
    SourceRole,
    ZeroToleranceEvidence,
    build_metric_report,
)
from newsroom.increment8.readiness import INCREMENT_8_READINESS

_D = "sha256:" + "1" * 64
_AT = "2042-01-05T00:00:00.000000Z"


def _run(kind: RunKind = RunKind.QUALIFICATION):
    plan = build_evaluation_plan(
        component_manifest_digest=_D,
        approved_by_digest="sha256:" + "2" * 64,
        approved_at=_AT,
    )
    epoch = freeze_epoch(
        plan=plan,
        target_manifest_digest="sha256:" + "3" * 64,
        universe_manifest_digest="sha256:" + "4" * 64,
        sampling_method_digest="sha256:" + "5" * 64,
        cutoff_at=_AT,
        opened_at=_AT,
    )
    return open_run(epoch=epoch, kind=kind, started_at=_AT)


def _rates(*, fail: str | None = None):
    thresholds = INCREMENT_8_READINESS.evaluation_plan["thresholds_ppm"]
    minimum = {
        "bounded_event_coverage",
        "candidate_precision",
        "candidate_recall",
        "grouping_precision",
        "grouping_recall",
        "reviewer_agreement",
        "route_decision_agreement",
    }
    output = []
    for name in sorted(
        minimum
        | {
            "duplicate_candidate",
            "false_merge",
            "fragmentation",
            "snowball_absorption",
            "unnecessary_candidate",
        }
    ):
        threshold = int(thresholds[f"{name}_{'min' if name in minimum else 'max'}"])
        if name in minimum:
            count = threshold // 10_000
            count = count - 1 if fail == name else count
        else:
            count = threshold // 10_000
            count = count + 1 if fail == name else count
        output.append(
            RateMeasurement.build(
                metric_name=name,
                count=count,
                denominator=100,
                sampling_method=SamplingMethod.POPULATION,
                uncertainty_ppm=0,
            )
        )
    return tuple(output)


def _performance(*, fail: str | None = None):
    limits = INCREMENT_8_READINESS.evaluation_plan["performance_limits"]
    return tuple(
        PerformanceMeasurement.build(
            metric_name=name,
            observed_value=int(limits[name]) + (1 if name == fail else 0),
        )
        for name in sorted(limits)
    )


def _slices(*, low: str | None = None, insufficient: str | None = None):
    output = []
    for name in REQUIRED_SLICES:
        completed = 11 if name == insufficient else 20
        success = completed if name != low else 16
        output.append(
            RequiredSliceResult.build(
                slice_id=name,
                completed_cases=completed,
                success_count=success,
            )
        )
    return tuple(output)


def _zero(**changed: int):
    names = INCREMENT_8_READINESS.evaluation_plan["zero_tolerance_counts"]
    return ZeroToleranceEvidence.build(
        {name: changed.get(str(name), 0) for name in sorted(names)}
    )


def _contributions():
    return (
        SourceContribution.build(
            source_id="anchor-fixture",
            role=SourceRole.ANCHOR,
            provider_version_digest="sha256:" + "6" * 64,
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
    values = {
        "run": _run(),
        "case_count": 120,
        "rates": _rates(),
        "performance": _performance(),
        "slices": _slices(),
        "zero_tolerance": _zero(),
        "contributions": _contributions(),
        "ablations": _ablations(),
        "metric_code_digest": "sha256:" + "9" * 64,
        "environment_digest": "sha256:" + "a" * 64,
        "sampling_manifest_digest": "sha256:" + "b" * 64,
        "label_manifest_digest": "sha256:" + "c" * 64,
    }
    values.update(changes)
    return build_metric_report(**values)


def test_complete_report_is_canonical_bounded_and_non_activating() -> None:
    report = _report()
    assert report.overall_status is MeasurementStatus.PASS
    assert report.payload["coverage_scope"] == (
        "REVIEWED_PROSPECTIVE_UNIVERSE_ONLY_NOT_ABSOLUTE_RECALL"
    )
    assert report.payload["ablation_is_decision_bearing"] is False
    assert report.payload["production_activation_authorised"] is False
    assert report.payload["live_shadow_execution_authorised"] is False
    assert report.digest.startswith("sha256:")
    assert b'"schema_version":"newsroom.increment8.metric-report.v1"' in (
        report.canonical_bytes
    )


def test_every_rate_retains_count_denominator_sampling_and_uncertainty() -> None:
    measurement = RateMeasurement.build(
        metric_name="candidate_precision",
        count=95,
        denominator=100,
        sampling_method=SamplingMethod.STRATIFIED_SAMPLE,
        uncertainty_ppm=20_000,
    )
    assert measurement.rate_ppm == 950_000
    assert measurement.status is MeasurementStatus.PASS
    with pytest.raises(MetricReportError, match="denominator"):
        RateMeasurement.build(
            metric_name="candidate_precision",
            count=1,
            denominator=0,
            sampling_method=SamplingMethod.POPULATION,
            uncertainty_ppm=0,
        )


def test_metric_or_performance_failure_cannot_be_rescued_by_ablation() -> None:
    report = _report(rates=_rates(fail="candidate_precision"))
    assert report.metric_status is MeasurementStatus.FAIL
    assert report.overall_status is MeasurementStatus.FAIL
    assert report.payload["ablation_is_decision_bearing"] is False
    slow = _report(performance=_performance(fail="case_latency_p95_ms"))
    assert slow.performance_status is MeasurementStatus.FAIL
    assert slow.overall_status is MeasurementStatus.FAIL


def test_required_slice_failure_and_insufficient_exposure_override_aggregate() -> None:
    failed = _report(slices=_slices(low="GEOGRAPHY_HONG_KONG"))
    assert failed.metric_status is MeasurementStatus.PASS
    assert failed.slice_status is MeasurementStatus.FAIL
    assert failed.overall_status is MeasurementStatus.FAIL
    insufficient = _report(slices=_slices(insufficient="LANGUAGE_ZH_HANT_HK"))
    assert insufficient.slice_status is MeasurementStatus.NOT_EVALUATED
    assert insufficient.overall_status is MeasurementStatus.NOT_EVALUATED
    too_short = _report(case_count=119)
    assert too_short.overall_status is MeasurementStatus.NOT_EVALUATED


def test_zero_tolerance_failure_blocks_report() -> None:
    report = _report(zero_tolerance=_zero(temporal_rewrite=1))
    assert report.zero_tolerance_status is MeasurementStatus.FAIL
    assert report.overall_status is MeasurementStatus.FAIL


def test_report_requires_exact_sorted_measurement_and_slice_inventories() -> None:
    with pytest.raises(MetricReportError, match="metric_name inventory"):
        _report(rates=_rates()[:-1])
    with pytest.raises(MetricReportError, match="slice_id inventory"):
        _report(slices=tuple(reversed(_slices())))
    with pytest.raises(MetricReportError, match="qualification Run"):
        _report(run=_run(RunKind.CALIBRATION))


def test_source_role_decisions_require_rights_and_event_level_value() -> None:
    common = {
        "source_id": "source",
        "provider_version_digest": _D,
        "unique_detection_count": 0,
        "earlier_detection_count": 0,
        "resilience_case_count": 0,
        "overlap_count": 12,
        "noise_count": 0,
        "gross_cost_microunits": 0,
        "rights_permitted": True,
        "rationale_digest": _D,
    }
    with pytest.raises(MetricReportError, match="quiet Anchor"):
        SourceContribution.build(
            **common, role=SourceRole.ANCHOR, recommendation=RoleRecommendation.REMOVE
        )
    with pytest.raises(MetricReportError, match="volume alone"):
        SourceContribution.build(
            **common,
            role=SourceRole.COMPARATOR,
            recommendation=RoleRecommendation.PROMOTE,
        )
    with pytest.raises(MetricReportError, match="rights-limited"):
        SourceContribution.build(
            **{**common, "rights_permitted": False},
            role=SourceRole.COMPLEMENT,
            recommendation=RoleRecommendation.RETAIN,
        )


def test_search_contribution_is_bound_to_exact_purpose_and_provider_version() -> None:
    with pytest.raises(MetricReportError, match="exact Purpose"):
        SourceContribution.build(
            source_id="search",
            role=SourceRole.SEARCH_PURPOSE,
            provider_version_digest=_D,
            unique_detection_count=1,
            earlier_detection_count=0,
            resilience_case_count=0,
            overlap_count=0,
            noise_count=0,
            gross_cost_microunits=0,
            rights_permitted=True,
            recommendation=RoleRecommendation.RETAIN,
            rationale_digest=_D,
        )


def test_typed_records_reject_forged_status_and_unknown_ablation_slice() -> None:
    rate = _rates()[0]
    with pytest.raises(AttributeError):
        rate.status = MeasurementStatus.FAIL  # type: ignore[misc]
    with pytest.raises(MetricReportError, match="unknown required slice"):
        AblationResult.build(
            component_id="bad",
            component_version_digest=_D,
            evaluated_case_count=1,
            lost_detection_count=0,
            earlier_detection_lost_count=0,
            resilience_loss_count=0,
            noise_removed_count=0,
            cost_removed_microunits=0,
            affected_slices=("UNKNOWN",),
        )
    forged = replace(rate, status=MeasurementStatus.FAIL)
    assert forged.canonical_bytes == rate.canonical_bytes
    with pytest.raises(MetricReportError, match="forged"):
        _report(rates=(forged, *_rates()[1:]))
