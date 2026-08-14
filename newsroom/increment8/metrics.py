"""Deterministic prospective measurement, slice and ablation evidence.

This module measures only an already frozen fixture qualification Run.  It does
not fetch sources, call providers, execute shadow work, or grant release or
production authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment8.evaluation import EvaluationRun, RunKind
from newsroom.increment8.readiness import (
    INCREMENT_8_READINESS,
    INCREMENT_8_READINESS_DIGEST,
)


class MetricReportError(ValueError):
    """Measurement evidence differs from the frozen Increment 8 plan."""


class SamplingMethod(StrEnum):
    POPULATION = "POPULATION"
    STRATIFIED_SAMPLE = "STRATIFIED_SAMPLE"


class MeasurementStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class SourceRole(StrEnum):
    ANCHOR = "ANCHOR"
    COMPLEMENT = "COMPLEMENT"
    COMPARATOR = "COMPARATOR"
    SEARCH_PURPOSE = "SEARCH_PURPOSE"


class RoleRecommendation(StrEnum):
    RETAIN = "RETAIN"
    PROMOTE = "PROMOTE"
    REMOVE = "REMOVE"
    NO_CHANGE = "NO_CHANGE"


REQUIRED_SLICES = tuple(
    str(item["slice_id"])
    for item in INCREMENT_8_READINESS.evaluation_plan["required_slice_manifest"]  # type: ignore[union-attr]
)

_MINIMUM_METRICS = frozenset(
    {
        "bounded_event_coverage",
        "candidate_precision",
        "candidate_recall",
        "grouping_precision",
        "grouping_recall",
        "reviewer_agreement",
        "route_decision_agreement",
    }
)
_MAXIMUM_METRICS = frozenset(
    {
        "duplicate_candidate",
        "false_merge",
        "fragmentation",
        "snowball_absorption",
        "unnecessary_candidate",
    }
)
_EXPECTED_METRICS = tuple(sorted(_MINIMUM_METRICS | _MAXIMUM_METRICS))
_EXPECTED_PERFORMANCE = tuple(
    sorted(
        str(name)
        for name in INCREMENT_8_READINESS.evaluation_plan["performance_limits"]
    )
)
_EXPECTED_ZERO_TOLERANCE = tuple(
    sorted(
        str(name)
        for name in INCREMENT_8_READINESS.evaluation_plan["zero_tolerance_counts"]
    )
)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MetricReportError(f"{field} must be an integer >= {minimum}")
    return value


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise MetricReportError(f"{field} must be bounded text")
    allowed = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
    )
    if any(character not in allowed for character in value):
        raise MetricReportError(f"{field} contains unsupported characters")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise MetricReportError(f"{field} must be a canonical digest") from exc


def _sorted_tokens(
    value: Sequence[str], field: str, *, empty: bool = False
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise MetricReportError(f"{field} must be a sequence")
    result = tuple(_token(item, field) for item in value)
    if (not empty and not result) or result != tuple(sorted(set(result))):
        raise MetricReportError(f"{field} must be sorted and unique")
    return result


def _record(schema_version: str, payload: Mapping[str, object]) -> tuple[bytes, str]:
    raw = canonical_json_bytes(
        {"schema_version": schema_version, "payload": dict(payload)}
    )
    return raw, digest_bytes(raw)


def _document(raw: bytes, schema_version: str) -> Mapping[str, object]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MetricReportError("metric evidence is not canonical JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "payload"}
        or value["schema_version"] != schema_version
        or not isinstance(value["payload"], dict)
        or canonical_json_bytes(value) != raw
    ):
        raise MetricReportError("metric evidence envelope differs")
    return MappingProxyType(value)


def _embedded(raw: bytes) -> dict[str, object]:
    value = json.loads(raw.decode("utf-8", errors="strict"))
    assert isinstance(value, dict)
    return value


@dataclass(frozen=True, slots=True)
class RateMeasurement:
    metric_name: str
    count: int
    denominator: int
    rate_ppm: int
    threshold_ppm: int
    sampling_method: SamplingMethod
    uncertainty_ppm: int
    status: MeasurementStatus
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        metric_name: str,
        count: int,
        denominator: int,
        sampling_method: SamplingMethod,
        uncertainty_ppm: int,
    ) -> RateMeasurement:
        name = _token(metric_name, "metric_name")
        if name not in _EXPECTED_METRICS or not isinstance(
            sampling_method, SamplingMethod
        ):
            raise MetricReportError("metric is not pre-registered")
        numerator = _integer(count, "count")
        total = _integer(denominator, "denominator", minimum=1)
        uncertainty = _integer(uncertainty_ppm, "uncertainty_ppm")
        if numerator > total or uncertainty > 1_000_000:
            raise MetricReportError("rate evidence exceeds its denominator")
        rate = numerator * 1_000_000 // total
        threshold_name = f"{name}_{'min' if name in _MINIMUM_METRICS else 'max'}"
        threshold = int(
            INCREMENT_8_READINESS.evaluation_plan["thresholds_ppm"][threshold_name]
        )  # type: ignore[index]
        passed = rate >= threshold if name in _MINIMUM_METRICS else rate <= threshold
        payload = {
            "metric_name": name,
            "count": numerator,
            "denominator": total,
            "rate_ppm": rate,
            "threshold_ppm": threshold,
            "direction": "MINIMUM" if name in _MINIMUM_METRICS else "MAXIMUM",
            "sampling_method": sampling_method.value,
            "uncertainty_ppm": uncertainty,
            "status": MeasurementStatus.PASS.value
            if passed
            else MeasurementStatus.FAIL.value,
        }
        raw, record_digest = _record("newsroom.increment8.rate-measurement.v1", payload)
        return cls(
            name,
            numerator,
            total,
            rate,
            threshold,
            sampling_method,
            uncertainty,
            MeasurementStatus.PASS if passed else MeasurementStatus.FAIL,
            raw,
            record_digest,
        )


@dataclass(frozen=True, slots=True)
class PerformanceMeasurement:
    metric_name: str
    observed_value: int
    maximum_value: int
    status: MeasurementStatus
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(cls, *, metric_name: str, observed_value: int) -> PerformanceMeasurement:
        name = _token(metric_name, "metric_name")
        if name not in _EXPECTED_PERFORMANCE:
            raise MetricReportError("performance metric is not pre-registered")
        observed = _integer(observed_value, "observed_value")
        maximum = int(INCREMENT_8_READINESS.evaluation_plan["performance_limits"][name])  # type: ignore[index]
        status = (
            MeasurementStatus.PASS if observed <= maximum else MeasurementStatus.FAIL
        )
        payload = {
            "metric_name": name,
            "observed_value": observed,
            "maximum_value": maximum,
            "status": status.value,
        }
        raw, record_digest = _record(
            "newsroom.increment8.performance-measurement.v1", payload
        )
        return cls(name, observed, maximum, status, raw, record_digest)


@dataclass(frozen=True, slots=True)
class RequiredSliceResult:
    slice_id: str
    completed_cases: int
    success_count: int
    score_ppm: int | None
    minimum_cases: int
    threshold_ppm: int
    status: MeasurementStatus
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls, *, slice_id: str, completed_cases: int, success_count: int
    ) -> RequiredSliceResult:
        identity = _token(slice_id, "slice_id")
        if identity not in REQUIRED_SLICES:
            raise MetricReportError("slice is not pre-registered")
        completed = _integer(completed_cases, "completed_cases")
        successes = _integer(success_count, "success_count")
        if successes > completed:
            raise MetricReportError("slice successes exceed completed Cases")
        minimum = int(
            INCREMENT_8_READINESS.evaluation_plan["required_slice_minimum_cases"]
        )
        threshold = int(
            INCREMENT_8_READINESS.evaluation_plan["thresholds_ppm"][
                "required_slice_min"
            ]
        )  # type: ignore[index]
        if completed < minimum:
            score: int | None = None
            status = MeasurementStatus.NOT_EVALUATED
        else:
            score = successes * 1_000_000 // completed
            status = (
                MeasurementStatus.PASS if score >= threshold else MeasurementStatus.FAIL
            )
        payload = {
            "slice_id": identity,
            "completed_cases": completed,
            "success_count": successes,
            "score_ppm": score,
            "minimum_cases": minimum,
            "threshold_ppm": threshold,
            "status": status.value,
        }
        raw, record_digest = _record(
            "newsroom.increment8.required-slice-result.v1", payload
        )
        return cls(
            identity,
            completed,
            successes,
            score,
            minimum,
            threshold,
            status,
            raw,
            record_digest,
        )


@dataclass(frozen=True, slots=True)
class ZeroToleranceEvidence:
    counts: Mapping[str, int]
    status: MeasurementStatus
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(cls, counts: Mapping[str, int]) -> ZeroToleranceEvidence:
        if (
            not isinstance(counts, Mapping)
            or tuple(sorted(counts)) != _EXPECTED_ZERO_TOLERANCE
        ):
            raise MetricReportError("zero-tolerance inventory differs")
        checked = {
            name: _integer(counts[name], name) for name in _EXPECTED_ZERO_TOLERANCE
        }
        status = (
            MeasurementStatus.PASS
            if not any(checked.values())
            else MeasurementStatus.FAIL
        )
        payload = {"counts": checked, "status": status.value}
        raw, record_digest = _record(
            "newsroom.increment8.zero-tolerance-evidence.v1", payload
        )
        return cls(MappingProxyType(checked), status, raw, record_digest)


@dataclass(frozen=True, slots=True)
class SourceContribution:
    source_id: str
    role: SourceRole
    provider_version_digest: str
    search_purpose: str | None
    unique_detection_count: int
    earlier_detection_count: int
    resilience_case_count: int
    overlap_count: int
    noise_count: int
    gross_cost_microunits: int
    rights_permitted: bool
    recommendation: RoleRecommendation
    rationale_digest: str
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        source_id: str,
        role: SourceRole,
        provider_version_digest: str,
        unique_detection_count: int,
        earlier_detection_count: int,
        resilience_case_count: int,
        overlap_count: int,
        noise_count: int,
        gross_cost_microunits: int,
        rights_permitted: bool,
        recommendation: RoleRecommendation,
        rationale_digest: str,
        search_purpose: str | None = None,
    ) -> SourceContribution:
        if not isinstance(role, SourceRole) or not isinstance(
            recommendation, RoleRecommendation
        ):
            raise MetricReportError("source role evidence must be typed")
        if not isinstance(rights_permitted, bool):
            raise MetricReportError("rights_permitted must be boolean")
        purpose = (
            None if search_purpose is None else _token(search_purpose, "search_purpose")
        )
        if (role is SourceRole.SEARCH_PURPOSE) != (purpose is not None):
            raise MetricReportError(
                "Search contribution requires exact Purpose attribution"
            )
        counts = tuple(
            _integer(value, name)
            for name, value in (
                ("unique_detection_count", unique_detection_count),
                ("earlier_detection_count", earlier_detection_count),
                ("resilience_case_count", resilience_case_count),
                ("overlap_count", overlap_count),
                ("noise_count", noise_count),
                ("gross_cost_microunits", gross_cost_microunits),
            )
        )
        unique, earlier, resilience, overlap, noise, cost = counts
        if not rights_permitted and recommendation in {
            RoleRecommendation.PROMOTE,
            RoleRecommendation.RETAIN,
        }:
            raise MetricReportError(
                "rights-limited source cannot be retained or promoted"
            )
        if (
            role is SourceRole.ANCHOR
            and recommendation is RoleRecommendation.REMOVE
            and not any((unique, earlier, resilience, noise))
        ):
            raise MetricReportError(
                "a quiet Anchor cannot be removed without event-level evidence"
            )
        if (
            role is SourceRole.COMPARATOR
            and recommendation is RoleRecommendation.PROMOTE
            and not any((unique, earlier, resilience))
        ):
            raise MetricReportError("Comparator volume alone cannot justify promotion")
        payload = {
            "source_id": _token(source_id, "source_id"),
            "role": role.value,
            "provider_version_digest": _digest(
                provider_version_digest, "provider_version_digest"
            ),
            "search_purpose": purpose,
            "unique_detection_count": unique,
            "earlier_detection_count": earlier,
            "resilience_case_count": resilience,
            "overlap_count": overlap,
            "noise_count": noise,
            "gross_cost_microunits": cost,
            "rights_permitted": rights_permitted,
            "recommendation": recommendation.value,
            "rationale_digest": _digest(rationale_digest, "rationale_digest"),
        }
        raw, record_digest = _record(
            "newsroom.increment8.source-contribution.v1", payload
        )
        return cls(
            str(payload["source_id"]),
            role,
            str(payload["provider_version_digest"]),
            purpose,
            unique,
            earlier,
            resilience,
            overlap,
            noise,
            cost,
            rights_permitted,
            recommendation,
            str(payload["rationale_digest"]),
            raw,
            record_digest,
        )


@dataclass(frozen=True, slots=True)
class AblationResult:
    component_id: str
    component_version_digest: str
    evaluated_case_count: int
    lost_detection_count: int
    earlier_detection_lost_count: int
    resilience_loss_count: int
    noise_removed_count: int
    cost_removed_microunits: int
    affected_slices: tuple[str, ...]
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        component_id: str,
        component_version_digest: str,
        evaluated_case_count: int,
        lost_detection_count: int,
        earlier_detection_lost_count: int,
        resilience_loss_count: int,
        noise_removed_count: int,
        cost_removed_microunits: int,
        affected_slices: Sequence[str],
    ) -> AblationResult:
        total = _integer(evaluated_case_count, "evaluated_case_count", minimum=1)
        values = tuple(
            _integer(value, name)
            for name, value in (
                ("lost_detection_count", lost_detection_count),
                ("earlier_detection_lost_count", earlier_detection_lost_count),
                ("resilience_loss_count", resilience_loss_count),
                ("noise_removed_count", noise_removed_count),
                ("cost_removed_microunits", cost_removed_microunits),
            )
        )
        if any(value > total for value in values[:4]):
            raise MetricReportError("ablation counts exceed evaluated Cases")
        slices = _sorted_tokens(affected_slices, "affected_slices", empty=True)
        if any(item not in REQUIRED_SLICES for item in slices):
            raise MetricReportError("ablation references an unknown required slice")
        payload = {
            "component_id": _token(component_id, "component_id"),
            "component_version_digest": _digest(
                component_version_digest, "component_version_digest"
            ),
            "evaluated_case_count": total,
            "lost_detection_count": values[0],
            "earlier_detection_lost_count": values[1],
            "resilience_loss_count": values[2],
            "noise_removed_count": values[3],
            "cost_removed_microunits": values[4],
            "affected_slices": list(slices),
            "decision_bearing": False,
            "may_rescue_target_failure": False,
        }
        raw, record_digest = _record("newsroom.increment8.ablation-result.v1", payload)
        return cls(
            str(payload["component_id"]),
            str(payload["component_version_digest"]),
            total,
            values[0],
            values[1],
            values[2],
            values[3],
            values[4],
            slices,
            raw,
            record_digest,
        )


@dataclass(frozen=True, slots=True)
class MetricReport:
    run_id: str
    case_count: int
    metric_status: MeasurementStatus
    slice_status: MeasurementStatus
    zero_tolerance_status: MeasurementStatus
    performance_status: MeasurementStatus
    overall_status: MeasurementStatus
    canonical_bytes: bytes
    digest: str
    payload: Mapping[str, object]

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> MetricReport:
        return verify_metric_report_canonical_bytes(raw)


def _exact_named(
    records: Sequence[object], expected: tuple[str, ...], field: str
) -> tuple[object, ...]:
    names = tuple(getattr(item, field, None) for item in records)
    if names != expected:
        raise MetricReportError(f"{field} inventory must be sorted, exact and complete")
    return tuple(records)


def _verify_records(
    rates: Sequence[RateMeasurement],
    performance: Sequence[PerformanceMeasurement],
    slices: Sequence[RequiredSliceResult],
    zero_tolerance: ZeroToleranceEvidence,
    contributions: Sequence[SourceContribution],
    ablations: Sequence[AblationResult],
) -> None:
    rebuilt: list[tuple[object, object]] = []
    for item in rates:
        if not isinstance(item, RateMeasurement):
            raise MetricReportError("rate evidence must be typed")
        rebuilt.append(
            (
                item,
                RateMeasurement.build(
                    metric_name=item.metric_name,
                    count=item.count,
                    denominator=item.denominator,
                    sampling_method=item.sampling_method,
                    uncertainty_ppm=item.uncertainty_ppm,
                ),
            )
        )
    for item in performance:
        if not isinstance(item, PerformanceMeasurement):
            raise MetricReportError("performance evidence must be typed")
        rebuilt.append(
            (
                item,
                PerformanceMeasurement.build(
                    metric_name=item.metric_name,
                    observed_value=item.observed_value,
                ),
            )
        )
    for item in slices:
        if not isinstance(item, RequiredSliceResult):
            raise MetricReportError("slice evidence must be typed")
        rebuilt.append(
            (
                item,
                RequiredSliceResult.build(
                    slice_id=item.slice_id,
                    completed_cases=item.completed_cases,
                    success_count=item.success_count,
                ),
            )
        )
    if not isinstance(zero_tolerance, ZeroToleranceEvidence):
        raise MetricReportError("zero_tolerance evidence must be typed")
    rebuilt.append((zero_tolerance, ZeroToleranceEvidence.build(zero_tolerance.counts)))
    for item in contributions:
        if not isinstance(item, SourceContribution):
            raise MetricReportError("source contribution evidence must be typed")
        rebuilt.append(
            (
                item,
                SourceContribution.build(
                    source_id=item.source_id,
                    role=item.role,
                    provider_version_digest=item.provider_version_digest,
                    search_purpose=item.search_purpose,
                    unique_detection_count=item.unique_detection_count,
                    earlier_detection_count=item.earlier_detection_count,
                    resilience_case_count=item.resilience_case_count,
                    overlap_count=item.overlap_count,
                    noise_count=item.noise_count,
                    gross_cost_microunits=item.gross_cost_microunits,
                    rights_permitted=item.rights_permitted,
                    recommendation=item.recommendation,
                    rationale_digest=item.rationale_digest,
                ),
            )
        )
    for item in ablations:
        if not isinstance(item, AblationResult):
            raise MetricReportError("ablation evidence must be typed")
        rebuilt.append(
            (
                item,
                AblationResult.build(
                    component_id=item.component_id,
                    component_version_digest=item.component_version_digest,
                    evaluated_case_count=item.evaluated_case_count,
                    lost_detection_count=item.lost_detection_count,
                    earlier_detection_lost_count=item.earlier_detection_lost_count,
                    resilience_loss_count=item.resilience_loss_count,
                    noise_removed_count=item.noise_removed_count,
                    cost_removed_microunits=item.cost_removed_microunits,
                    affected_slices=item.affected_slices,
                ),
            )
        )
    if any(actual != expected for actual, expected in rebuilt):
        raise MetricReportError("measurement evidence is forged or non-canonical")


def build_metric_report(
    *,
    run: EvaluationRun,
    case_count: int,
    rates: Sequence[RateMeasurement],
    performance: Sequence[PerformanceMeasurement],
    slices: Sequence[RequiredSliceResult],
    zero_tolerance: ZeroToleranceEvidence,
    contributions: Sequence[SourceContribution],
    ablations: Sequence[AblationResult],
    metric_code_digest: str,
    environment_digest: str,
    sampling_manifest_digest: str,
    label_manifest_digest: str,
    deviation_digests: Sequence[str] = (),
) -> MetricReport:
    if (
        not isinstance(run, EvaluationRun)
        or run.payload["run_kind"] != RunKind.QUALIFICATION.value
    ):
        raise MetricReportError("metric report requires a frozen qualification Run")
    total_cases = _integer(case_count, "case_count")
    checked_rates = _exact_named(tuple(rates), _EXPECTED_METRICS, "metric_name")
    checked_performance = _exact_named(
        tuple(performance), _EXPECTED_PERFORMANCE, "metric_name"
    )
    checked_slices = _exact_named(tuple(slices), REQUIRED_SLICES, "slice_id")
    if not contributions or any(
        not isinstance(item, SourceContribution) for item in contributions
    ):
        raise MetricReportError("source contribution evidence is required")
    if not ablations or any(not isinstance(item, AblationResult) for item in ablations):
        raise MetricReportError("separately reported ablation evidence is required")
    contribution_ids = tuple(item.source_id for item in contributions)
    ablation_ids = tuple(item.component_id for item in ablations)
    if contribution_ids != tuple(
        sorted(set(contribution_ids))
    ) or ablation_ids != tuple(sorted(set(ablation_ids))):
        raise MetricReportError(
            "contribution and ablation inventories must be sorted and unique"
        )
    _verify_records(
        checked_rates,  # type: ignore[arg-type]
        checked_performance,  # type: ignore[arg-type]
        checked_slices,  # type: ignore[arg-type]
        zero_tolerance,
        contributions,
        ablations,
    )
    minimum_cases = int(
        INCREMENT_8_READINESS.evaluation_plan["qualification_exposure"][
            "minimum_completed_cases"
        ]
    )  # type: ignore[index]
    metric_status = (
        MeasurementStatus.PASS
        if all(item.status is MeasurementStatus.PASS for item in checked_rates)
        else MeasurementStatus.FAIL
    )
    performance_status = (
        MeasurementStatus.PASS
        if all(item.status is MeasurementStatus.PASS for item in checked_performance)
        else MeasurementStatus.FAIL
    )
    if any(item.status is MeasurementStatus.FAIL for item in checked_slices):
        slice_status = MeasurementStatus.FAIL
    elif any(item.status is MeasurementStatus.NOT_EVALUATED for item in checked_slices):
        slice_status = MeasurementStatus.NOT_EVALUATED
    else:
        slice_status = MeasurementStatus.PASS
    if zero_tolerance.status is MeasurementStatus.FAIL:
        overall = MeasurementStatus.FAIL
    elif total_cases < minimum_cases or slice_status is MeasurementStatus.NOT_EVALUATED:
        overall = MeasurementStatus.NOT_EVALUATED
    elif all(
        status is MeasurementStatus.PASS
        for status in (
            metric_status,
            performance_status,
            slice_status,
            zero_tolerance.status,
        )
    ):
        overall = MeasurementStatus.PASS
    else:
        overall = MeasurementStatus.FAIL
    deviations = tuple(
        sorted(_digest(item, "deviation_digest") for item in deviation_digests)
    )
    if len(deviations) != len(set(deviations)):
        raise MetricReportError("deviation digests must be unique")
    payload: dict[str, object] = {
        "run_id": run.run_id,
        "run_digest": run.digest,
        "run": _embedded(run.canonical_bytes),
        "readiness_digest": INCREMENT_8_READINESS_DIGEST,
        "case_count": total_cases,
        "minimum_case_count": minimum_cases,
        "coverage_scope": "REVIEWED_PROSPECTIVE_UNIVERSE_ONLY_NOT_ABSOLUTE_RECALL",
        "rates": [item.digest for item in checked_rates],
        "rate_evidence": [_embedded(item.canonical_bytes) for item in checked_rates],
        "performance": [item.digest for item in checked_performance],
        "performance_evidence": [
            _embedded(item.canonical_bytes) for item in checked_performance
        ],
        "required_slices": [item.digest for item in checked_slices],
        "required_slice_evidence": [
            _embedded(item.canonical_bytes) for item in checked_slices
        ],
        "zero_tolerance_digest": zero_tolerance.digest,
        "zero_tolerance_evidence": _embedded(zero_tolerance.canonical_bytes),
        "source_contribution_digests": [item.digest for item in contributions],
        "source_contribution_evidence": [
            _embedded(item.canonical_bytes) for item in contributions
        ],
        "ablation_digests": [item.digest for item in ablations],
        "ablation_evidence": [_embedded(item.canonical_bytes) for item in ablations],
        "metric_code_digest": _digest(metric_code_digest, "metric_code_digest"),
        "environment_digest": _digest(environment_digest, "environment_digest"),
        "sampling_manifest_digest": _digest(
            sampling_manifest_digest, "sampling_manifest_digest"
        ),
        "label_manifest_digest": _digest(
            label_manifest_digest, "label_manifest_digest"
        ),
        "deviation_digests": list(deviations),
        "metric_status": metric_status.value,
        "performance_status": performance_status.value,
        "slice_status": slice_status.value,
        "zero_tolerance_status": zero_tolerance.status.value,
        "overall_status": overall.value,
        "ablation_is_decision_bearing": False,
        "production_activation_authorised": False,
        "live_shadow_execution_authorised": False,
    }
    raw, record_digest = _record("newsroom.increment8.metric-report.v1", payload)
    return MetricReport(
        run.run_id,
        total_cases,
        metric_status,
        slice_status,
        zero_tolerance.status,
        performance_status,
        overall,
        raw,
        record_digest,
        MappingProxyType(payload),
    )


def _evidence_payload(
    value: object, schema_version: str
) -> tuple[bytes, Mapping[str, object]]:
    if not isinstance(value, dict):
        raise MetricReportError("embedded metric evidence must be an object")
    raw = canonical_json_bytes(value)
    document = _document(raw, schema_version)
    payload = document["payload"]
    assert isinstance(payload, Mapping)
    return raw, payload


def verify_metric_report_canonical_bytes(raw: bytes) -> MetricReport:
    """Reconstruct a Metric Report and every retained measurement from bytes."""

    document = _document(raw, "newsroom.increment8.metric-report.v1")
    payload = document["payload"]
    assert isinstance(payload, Mapping)
    try:
        run_raw = canonical_json_bytes(payload["run"])
        run = EvaluationRun.from_canonical_bytes(run_raw)

        rates: list[RateMeasurement] = []
        for value in payload["rate_evidence"]:  # type: ignore[union-attr]
            item_raw, item = _evidence_payload(
                value, "newsroom.increment8.rate-measurement.v1"
            )
            rebuilt = RateMeasurement.build(
                metric_name=item["metric_name"],  # type: ignore[arg-type]
                count=item["count"],  # type: ignore[arg-type]
                denominator=item["denominator"],  # type: ignore[arg-type]
                sampling_method=SamplingMethod(item["sampling_method"]),
                uncertainty_ppm=item["uncertainty_ppm"],  # type: ignore[arg-type]
            )
            if rebuilt.canonical_bytes != item_raw:
                raise MetricReportError("rate evidence differs after reconstruction")
            rates.append(rebuilt)

        performance: list[PerformanceMeasurement] = []
        for value in payload["performance_evidence"]:  # type: ignore[union-attr]
            item_raw, item = _evidence_payload(
                value, "newsroom.increment8.performance-measurement.v1"
            )
            rebuilt = PerformanceMeasurement.build(
                metric_name=item["metric_name"],  # type: ignore[arg-type]
                observed_value=item["observed_value"],  # type: ignore[arg-type]
            )
            if rebuilt.canonical_bytes != item_raw:
                raise MetricReportError(
                    "performance evidence differs after reconstruction"
                )
            performance.append(rebuilt)

        slices: list[RequiredSliceResult] = []
        for value in payload["required_slice_evidence"]:  # type: ignore[union-attr]
            item_raw, item = _evidence_payload(
                value, "newsroom.increment8.required-slice-result.v1"
            )
            rebuilt = RequiredSliceResult.build(
                slice_id=item["slice_id"],  # type: ignore[arg-type]
                completed_cases=item["completed_cases"],  # type: ignore[arg-type]
                success_count=item["success_count"],  # type: ignore[arg-type]
            )
            if rebuilt.canonical_bytes != item_raw:
                raise MetricReportError("slice evidence differs after reconstruction")
            slices.append(rebuilt)

        zero_raw, zero_payload = _evidence_payload(
            payload["zero_tolerance_evidence"],
            "newsroom.increment8.zero-tolerance-evidence.v1",
        )
        zero = ZeroToleranceEvidence.build(zero_payload["counts"])  # type: ignore[arg-type]
        if zero.canonical_bytes != zero_raw:
            raise MetricReportError(
                "zero-tolerance evidence differs after reconstruction"
            )

        contributions: list[SourceContribution] = []
        for value in payload["source_contribution_evidence"]:  # type: ignore[union-attr]
            item_raw, item = _evidence_payload(
                value, "newsroom.increment8.source-contribution.v1"
            )
            rebuilt = SourceContribution.build(
                source_id=item["source_id"],  # type: ignore[arg-type]
                role=SourceRole(item["role"]),
                provider_version_digest=item["provider_version_digest"],  # type: ignore[arg-type]
                search_purpose=item["search_purpose"],  # type: ignore[arg-type]
                unique_detection_count=item["unique_detection_count"],  # type: ignore[arg-type]
                earlier_detection_count=item["earlier_detection_count"],  # type: ignore[arg-type]
                resilience_case_count=item["resilience_case_count"],  # type: ignore[arg-type]
                overlap_count=item["overlap_count"],  # type: ignore[arg-type]
                noise_count=item["noise_count"],  # type: ignore[arg-type]
                gross_cost_microunits=item["gross_cost_microunits"],  # type: ignore[arg-type]
                rights_permitted=item["rights_permitted"],  # type: ignore[arg-type]
                recommendation=RoleRecommendation(item["recommendation"]),
                rationale_digest=item["rationale_digest"],  # type: ignore[arg-type]
            )
            if rebuilt.canonical_bytes != item_raw:
                raise MetricReportError(
                    "source contribution differs after reconstruction"
                )
            contributions.append(rebuilt)

        ablations: list[AblationResult] = []
        for value in payload["ablation_evidence"]:  # type: ignore[union-attr]
            item_raw, item = _evidence_payload(
                value, "newsroom.increment8.ablation-result.v1"
            )
            rebuilt = AblationResult.build(
                component_id=item["component_id"],  # type: ignore[arg-type]
                component_version_digest=item["component_version_digest"],  # type: ignore[arg-type]
                evaluated_case_count=item["evaluated_case_count"],  # type: ignore[arg-type]
                lost_detection_count=item["lost_detection_count"],  # type: ignore[arg-type]
                earlier_detection_lost_count=item["earlier_detection_lost_count"],  # type: ignore[arg-type]
                resilience_loss_count=item["resilience_loss_count"],  # type: ignore[arg-type]
                noise_removed_count=item["noise_removed_count"],  # type: ignore[arg-type]
                cost_removed_microunits=item["cost_removed_microunits"],  # type: ignore[arg-type]
                affected_slices=item["affected_slices"],  # type: ignore[arg-type]
            )
            if rebuilt.canonical_bytes != item_raw:
                raise MetricReportError(
                    "ablation evidence differs after reconstruction"
                )
            ablations.append(rebuilt)

        rebuilt_report = build_metric_report(
            run=run,
            case_count=payload["case_count"],  # type: ignore[arg-type]
            rates=rates,
            performance=performance,
            slices=slices,
            zero_tolerance=zero,
            contributions=contributions,
            ablations=ablations,
            metric_code_digest=payload["metric_code_digest"],  # type: ignore[arg-type]
            environment_digest=payload["environment_digest"],  # type: ignore[arg-type]
            sampling_manifest_digest=payload["sampling_manifest_digest"],  # type: ignore[arg-type]
            label_manifest_digest=payload["label_manifest_digest"],  # type: ignore[arg-type]
            deviation_digests=payload["deviation_digests"],  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, MetricReportError):
            raise
        raise MetricReportError("Metric Report reconstruction failed") from exc
    if rebuilt_report.canonical_bytes != raw:
        raise MetricReportError("Metric Report differs after reconstruction")
    return rebuilt_report


__all__ = [
    "REQUIRED_SLICES",
    "AblationResult",
    "MeasurementStatus",
    "MetricReport",
    "MetricReportError",
    "PerformanceMeasurement",
    "RateMeasurement",
    "RequiredSliceResult",
    "RoleRecommendation",
    "SamplingMethod",
    "SourceContribution",
    "SourceRole",
    "ZeroToleranceEvidence",
    "build_metric_report",
    "verify_metric_report_canonical_bytes",
]
