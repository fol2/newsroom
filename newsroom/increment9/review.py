"""Blinded review, adjudication, slice, ablation and metric authority for 9D1.

All operations are pure construction or validation over already sealed bytes.
This module neither reads shadow evidence nor invokes a reviewer/provider.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Mapping, Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST

MAX_RECORD_BYTES = 4_194_304
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class ReviewContractError(ValueError):
    """Review evidence or an ingest request differs from the sealed authority."""


class ReviewRole(StrEnum):
    PRIMARY_A = "PRIMARY_A"
    PRIMARY_B = "PRIMARY_B"
    ADJUDICATOR = "ADJUDICATOR"


class ReviewVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class SliceDimension(StrEnum):
    JURISDICTION = "JURISDICTION"
    LANGUAGE = "LANGUAGE"
    SOURCE_ROLE = "SOURCE_ROLE"
    BEAT = "BEAT"
    CASE_KIND = "CASE_KIND"


class MetricDirection(StrEnum):
    MINIMUM = "MINIMUM"
    MAXIMUM = "MAXIMUM"
    ZERO = "ZERO"


class IngestDisposition(StrEnum):
    ADMITTED_FOR_LATER_REVIEW = "ADMITTED_FOR_LATER_REVIEW"
    REJECTED = "REJECTED"


EXPECTED_REVIEWERS = MappingProxyType(
    {
        ReviewRole.PRIMARY_A: (
            "Anthropic",
            "Claude Agent SDK",
            "claude-sonnet-5",
            "increment9/primary-a",
        ),
        ReviewRole.PRIMARY_B: (
            "xAI",
            "Grok Build CLI",
            "grok-4.6",
            "increment9/primary-b",
        ),
        ReviewRole.ADJUDICATOR: (
            "Google",
            "Gemini API",
            "gemini-3.7-flash",
            "increment9/adjudicator",
        ),
    }
)
EXPECTED_SLICE_VALUES = MappingProxyType(
    {
        SliceDimension.JURISDICTION: ("HONG_KONG", "UK"),
        SliceDimension.LANGUAGE: ("EN_GB", "MIXED", "ZH_HANT_HK"),
        SliceDimension.SOURCE_ROLE: ("COMPARATOR", "OFFICIAL"),
        SliceDimension.BEAT: (
            "EDUCATION_AND_FAMILIES",
            "IMMIGRATION_AND_BNO",
            "OFFICIAL_WARNINGS",
            "POLICY_AND_SERVICES",
        ),
        SliceDimension.CASE_KIND: (
            "CORRECTION_OR_SUPERSESSION",
            "RELATED_DISTINCT_OR_FALSE_MERGE",
            "WARNING_TRANSITION",
        ),
    }
)
EXPECTED_SOURCE_IDS = (
    "HK-01",
    "HK-02",
    "HK-04",
    "RAD-01",
    "RAD-02",
    "UK-01",
    "UK-02",
    "UK-03",
    "UK-05",
    "UK-10",
)
EXPECTED_ABLATIONS = MappingProxyType(
    {
        "EXTRACTION": ("DETERMINISTIC_SOURCE_TEXT", "GRAPHITI_EXTRACTION"),
        "GRAPHRAG": ("GRAPHITI_PLUS_ADMITTED_GRAPH", "WITHOUT_ADMITTED_GRAPH"),
        "OPERATIONAL": ("HERMES_FULL_WORKFLOW", "WARNING_DETERMINISTIC_DEFAULT"),
        "RETRIEVAL": ("ADMITTED_GRAPH", "EXACT", "FULL_TEXT", "HYBRID_RRF", "VECTOR"),
        "SOURCE": ("ALL_APPROVED_SOURCES", "MEDIA_COMPARATOR_ONLY", "OFFICIAL_ONLY"),
        "TRIAGE": ("DETERMINISTIC_VETO", "PROPOSAL_FIRST"),
    }
)
EXPECTED_METRICS = MappingProxyType(
    {
        "ai_consensus_editorial_pass_ppm": (MetricDirection.MINIMUM, 900_000, "ALL_REVIEWABLE_CASES"),
        "completed_scheduled_checks_ppm": (MetricDirection.MINIMUM, 995_000, "ALL_DUE_POLLS"),
        "event_precision_ppm": (MetricDirection.MINIMUM, 900_000, "ALL_POSITIVE_EVENT_DECISIONS"),
        "event_recall_ppm": (MetricDirection.MINIMUM, 800_000, "ALL_ELIGIBLE_EVENTS"),
        "exact_id_precision_at_1_ppm": (MetricDirection.MINIMUM, 1_000_000, "ALL_EXACT_ID_CASES"),
        "hybrid_recall_at_12_ppm": (MetricDirection.MINIMUM, 900_000, "ALL_RETRIEVAL_CASES"),
        "mrr_at_12_ppm": (MetricDirection.MINIMUM, 750_000, "ALL_RETRIEVAL_CASES"),
        "nonurgent_batch_p95_minutes": (MetricDirection.MAXIMUM, 120, "ALL_NONURGENT_BATCHES"),
        "per_slice_pass_ppm": (MetricDirection.MINIMUM, 800_000, "EACH_REQUIRED_SLICE"),
        "projection_age_minutes": (MetricDirection.MAXIMUM, 60, "ALL_ADMITTED_PROJECTIONS"),
        "retrieval_p95_milliseconds": (MetricDirection.MAXIMUM, 5_000, "ALL_RETRIEVAL_ATTEMPTS"),
        "warning_p95_minutes": (MetricDirection.MAXIMUM, 15, "ALL_WARNING_TRANSITIONS"),
    }
)
EXPECTED_ZERO_TOLERANCE = (
    "BUDGET_OVERRUN",
    "DEAD_LETTER",
    "DISTRACTOR_FALSE_MERGE",
    "GAP",
    "PROHIBITED_EFFECT",
    "PROVENANCE_FAILURE",
    "RIGHTS_FAILURE",
    "SCOPE_FAILURE",
    "SILENT_LOSS",
    "TEMPORAL_FAILURE",
    "TRUST_LABEL_FAILURE",
    "UNSUPPORTED_MATERIAL_CLAIM",
)
EXPECTED_REVIEW_REASONS = tuple(
    sorted(
        set(EXPECTED_ZERO_TOLERANCE)
        | {
            "IDENTITY_UNRESOLVED",
            "MISSING_EVIDENCE",
            "OTHER_MATERIAL_ERROR",
            "UNREVIEWABLE",
        }
    )
)


class _NoEffect:
    authorises_live_call = False
    authorises_reviewer_access = False
    authorises_credentials = False
    authorises_external_egress = False
    authorises_spend = False
    authorises_publication = False
    authorises_evidence_intake = False
    authorises_canary = False
    authorises_production_mutation = False
    authorises_production_activation = False


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewContractError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _text(value: object, field: str, maximum: int = 2048) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value.encode("utf-8", errors="strict")) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ReviewContractError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise ReviewContractError(f"{field} must be a canonical token")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise ReviewContractError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise ReviewContractError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ReviewContractError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _integer(value: object, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ReviewContractError(f"{field} must be a bounded integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ReviewContractError(f"{field} must be a boolean")
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    try:
        if type(value) is not str and type(value) is not kind:
            raise ValueError
        return kind(value)
    except ValueError as exc:
        raise ReviewContractError(f"{field} differs") from exc


def _mapping(value: object, fields: frozenset[str], field: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ReviewContractError(f"{field} fields differ")
    return value


def _tokens(value: object, field: str, *, allow_empty: bool = False, sorted_only: bool = True) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or (not value and not allow_empty) or len(value) > 4096:
        raise ReviewContractError(f"{field} must be a bounded array")
    result = tuple(_token(item, field) for item in value)
    expected = tuple(sorted(set(result))) if sorted_only else result
    if len(set(result)) != len(result) or (sorted_only and result != expected):
        raise ReviewContractError(f"{field} must be unique" + (" and sorted" if sorted_only else ""))
    return result


def _document(raw: bytes, schema: str, fields: frozenset[str]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
        raise ReviewContractError("review record bytes are not bounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except ReviewContractError:
        raise
    except (UnicodeError, json.JSONDecodeError, CanonicalizationError, RecursionError) as exc:
        raise ReviewContractError("review record bytes are invalid") from exc
    if canonical != raw:
        raise ReviewContractError("review record bytes must be exact canonical JSON")
    value = _mapping(value, fields | {"schema_version"}, "review record")
    if value.pop("schema_version") != schema:
        raise ReviewContractError("review record schema differs")
    return value


@dataclass(frozen=True, slots=True)
class _Record(_NoEffect):
    schema_version: ClassVar[str]

    def primitive(self) -> dict[str, object]:
        raise NotImplementedError

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.primitive())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ReviewerProfile(_NoEffect):
    role: ReviewRole
    provider: str
    route: str
    model_selector: str
    memory_namespace: str

    def __post_init__(self) -> None:
        role = _enum(ReviewRole, self.role, "role")
        object.__setattr__(self, "role", role)
        expected = EXPECTED_REVIEWERS[role]
        actual = (self.provider, self.route, self.model_selector, self.memory_namespace)
        if actual != expected:
            raise ReviewContractError(f"{role} reviewer identity differs from OD-009")

    def primitive(self) -> dict[str, object]:
        return {
            "memory_namespace": self.memory_namespace,
            "model_selector": self.model_selector,
            "provider": self.provider,
            "role": str(self.role),
            "route": self.route,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        value = _mapping(value, frozenset(cls.__dataclass_fields__), "reviewer")
        value["role"] = _enum(ReviewRole, value["role"], "role")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class AblationPlan(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.ablation-plan.v1"
    ablation_plan_id: str
    owner_plan_digest: str
    axes: Mapping[str, tuple[str, ...]]
    same_case_universe: bool = True
    substitution_allowed: bool = False

    def __post_init__(self) -> None:
        _token(self.ablation_plan_id, "ablation_plan_id")
        _digest(self.owner_plan_digest, "owner_plan_digest")
        if self.owner_plan_digest != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise ReviewContractError("ablation owner plan differs")
        if not isinstance(self.axes, Mapping):
            raise ReviewContractError("ablation axes must be an object")
        normalised = {
            _token(axis, "ablation axis"): _tokens(modes, f"ablation.{axis}")
            for axis, modes in self.axes.items()
        }
        if normalised != dict(EXPECTED_ABLATIONS):
            raise ReviewContractError("ablation definitions differ")
        object.__setattr__(self, "axes", MappingProxyType(dict(sorted(normalised.items()))))
        if (self.same_case_universe, self.substitution_allowed) != (True, False):
            raise ReviewContractError("ablation anti-hindsight rules differ")

    def primitive(self) -> dict[str, object]:
        return {
            "ablation_plan_id": self.ablation_plan_id,
            "axes": {key: list(value) for key, value in self.axes.items()},
            "owner_plan_digest": self.owner_plan_digest,
            "same_case_universe": self.same_case_universe,
            "schema_version": self.schema_version,
            "substitution_allowed": self.substitution_allowed,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        if type(value["axes"]) is not dict:
            raise ReviewContractError("ablation axes must be an object")
        value["axes"] = {key: tuple(item) for key, item in value["axes"].items()}  # type: ignore[union-attr]
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class MetricPlan(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.metric-plan.v1"
    metric_plan_id: str
    owner_plan_digest: str
    metrics: Mapping[str, tuple[MetricDirection, int, str]]
    zero_tolerance: tuple[str, ...]
    uncertainty_method: str = "WILSON_SCORE_95_FIXED_INTEGER"
    missing_evidence_policy: str = "INCONCLUSIVE_OR_BLOCKED_NEVER_PASS"
    threshold_change_after_results_allowed: bool = False

    def __post_init__(self) -> None:
        _token(self.metric_plan_id, "metric_plan_id")
        _digest(self.owner_plan_digest, "owner_plan_digest")
        if self.owner_plan_digest != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise ReviewContractError("metric owner plan differs")
        if not isinstance(self.metrics, Mapping):
            raise ReviewContractError("metrics must be an object")
        normalised: dict[str, tuple[MetricDirection, int, str]] = {}
        for name, spec in self.metrics.items():
            if type(spec) not in (tuple, list) or len(spec) != 3:
                raise ReviewContractError("metric definition differs")
            direction = _enum(MetricDirection, spec[0], f"metric.{name}.direction")
            threshold = _integer(spec[1], f"metric.{name}.threshold")
            denominator = _token(spec[2], f"metric.{name}.denominator")
            normalised[_token(name, "metric name")] = (direction, threshold, denominator)
        if normalised != dict(EXPECTED_METRICS):
            raise ReviewContractError("metric definitions differ from OD-008")
        object.__setattr__(self, "metrics", MappingProxyType(dict(sorted(normalised.items()))))
        if tuple(self.zero_tolerance) != EXPECTED_ZERO_TOLERANCE:
            raise ReviewContractError("zero-tolerance inventory differs")
        object.__setattr__(self, "zero_tolerance", tuple(self.zero_tolerance))
        if self.uncertainty_method != "WILSON_SCORE_95_FIXED_INTEGER":
            raise ReviewContractError("uncertainty method differs")
        if self.missing_evidence_policy != "INCONCLUSIVE_OR_BLOCKED_NEVER_PASS":
            raise ReviewContractError("missing evidence policy differs")
        if self.threshold_change_after_results_allowed is not False:
            raise ReviewContractError("thresholds cannot change after results")

    def primitive(self) -> dict[str, object]:
        return {
            "metric_plan_id": self.metric_plan_id,
            "metrics": {
                key: [str(value[0]), value[1], value[2]]
                for key, value in self.metrics.items()
            },
            "missing_evidence_policy": self.missing_evidence_policy,
            "owner_plan_digest": self.owner_plan_digest,
            "schema_version": self.schema_version,
            "threshold_change_after_results_allowed": self.threshold_change_after_results_allowed,
            "uncertainty_method": self.uncertainty_method,
            "zero_tolerance": list(self.zero_tolerance),
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        raw_metrics = value["metrics"]
        if type(raw_metrics) is not dict:
            raise ReviewContractError("metrics must be an object")
        value["metrics"] = {
            key: (
                _enum(MetricDirection, item[0], f"metric.{key}.direction"),
                item[1],
                item[2],
            )
            for key, item in raw_metrics.items()
            if type(item) is list and len(item) == 3
        }
        if len(value["metrics"]) != len(raw_metrics):
            raise ReviewContractError("metric definitions differ")
        value["zero_tolerance"] = tuple(value["zero_tolerance"])  # type: ignore[arg-type]
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ReviewPlan(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.review-plan.v1"
    review_plan_id: str
    review_version: str
    owner_plan_digest: str
    eligible_universe_digest: str
    reviewer_profiles: tuple[ReviewerProfile, ...]
    ablation_plan_digest: str
    metric_plan_digest: str
    sealed_at: str
    reviewer_ai_minutes_cap: int = 2400
    reviewer_human_minutes: int = 0
    sut_provider: str = "OpenAI"
    agreement_rule: str = "PRIMARY_CONSENSUS"
    disagreement_rule: str = "GEMINI_ADJUDICATION"
    missing_primary: str = "NOT_EVALUATED"
    invalid_adjudication: str = "NOT_EVALUATED"
    primaries_parallel: bool = True
    peer_results_after_both_sealed: bool = True
    operational_metadata_blinded: bool = True
    same_family_replacement_allowed: bool = False
    adjudicator_replacement_allowed: bool = False
    human_labelled_anchor: bool = False
    case_substitution_allowed: bool = False

    def __post_init__(self) -> None:
        _token(self.review_plan_id, "review_plan_id")
        _token(self.review_version, "review_version")
        for field in (
            "owner_plan_digest",
            "eligible_universe_digest",
            "ablation_plan_digest",
            "metric_plan_digest",
        ):
            _digest(getattr(self, field), field)
        if self.owner_plan_digest != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise ReviewContractError("review owner plan differs")
        expected_profiles = tuple(
            ReviewerProfile(role, *EXPECTED_REVIEWERS[role]) for role in ReviewRole
        )
        if self.reviewer_profiles != expected_profiles:
            raise ReviewContractError("reviewer manifest differs from OD-009")
        _timestamp(self.sealed_at, "sealed_at")
        if (self.reviewer_ai_minutes_cap, self.reviewer_human_minutes) != (2400, 0):
            raise ReviewContractError("reviewer budget differs from OD-009/OD-011")
        if self.sut_provider != "OpenAI":
            raise ReviewContractError("SUT provider independence differs")
        if (self.agreement_rule, self.disagreement_rule) != (
            "PRIMARY_CONSENSUS",
            "GEMINI_ADJUDICATION",
        ):
            raise ReviewContractError("agreement authority differs")
        if (self.missing_primary, self.invalid_adjudication) != (
            "NOT_EVALUATED",
            "NOT_EVALUATED",
        ):
            raise ReviewContractError("missing review semantics differ")
        if (
            self.primaries_parallel,
            self.peer_results_after_both_sealed,
            self.operational_metadata_blinded,
        ) != (True, True, True):
            raise ReviewContractError("blinding rules differ")
        if any(
            (
                self.same_family_replacement_allowed,
                self.adjudicator_replacement_allowed,
                self.human_labelled_anchor,
                self.case_substitution_allowed,
            )
        ):
            raise ReviewContractError("replacement or hindsight rules differ")

    def primitive(self) -> dict[str, object]:
        return {
            "ablation_plan_digest": self.ablation_plan_digest,
            "adjudicator_replacement_allowed": self.adjudicator_replacement_allowed,
            "agreement_rule": self.agreement_rule,
            "case_substitution_allowed": self.case_substitution_allowed,
            "disagreement_rule": self.disagreement_rule,
            "eligible_universe_digest": self.eligible_universe_digest,
            "human_labelled_anchor": self.human_labelled_anchor,
            "invalid_adjudication": self.invalid_adjudication,
            "metric_plan_digest": self.metric_plan_digest,
            "missing_primary": self.missing_primary,
            "operational_metadata_blinded": self.operational_metadata_blinded,
            "owner_plan_digest": self.owner_plan_digest,
            "peer_results_after_both_sealed": self.peer_results_after_both_sealed,
            "primaries_parallel": self.primaries_parallel,
            "review_plan_id": self.review_plan_id,
            "review_version": self.review_version,
            "reviewer_ai_minutes_cap": self.reviewer_ai_minutes_cap,
            "reviewer_human_minutes": self.reviewer_human_minutes,
            "reviewer_profiles": [item.primitive() for item in self.reviewer_profiles],
            "same_family_replacement_allowed": self.same_family_replacement_allowed,
            "schema_version": self.schema_version,
            "sealed_at": self.sealed_at,
            "sut_provider": self.sut_provider,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        profiles = value["reviewer_profiles"]
        if type(profiles) is not list:
            raise ReviewContractError("reviewer profiles must be an array")
        value["reviewer_profiles"] = tuple(ReviewerProfile.from_primitive(item) for item in profiles)
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ReviewCase(_NoEffect):
    case_id: str
    evidence_digest: str
    epoch_digest: str
    final_cohort_digest: str
    effective_manifest_digest: str
    source_id: str
    jurisdiction: str
    language: str
    source_role: str
    beat: str
    case_kind: str
    changed_revision: bool
    ablation_evidence_digests: Mapping[str, str]

    def __post_init__(self) -> None:
        _token(self.case_id, "case_id")
        for field in (
            "evidence_digest",
            "epoch_digest",
            "final_cohort_digest",
            "effective_manifest_digest",
        ):
            _digest(getattr(self, field), field)
        if self.source_id not in EXPECTED_SOURCE_IDS:
            raise ReviewContractError("case source differs")
        memberships = {
            SliceDimension.JURISDICTION: self.jurisdiction,
            SliceDimension.LANGUAGE: self.language,
            SliceDimension.SOURCE_ROLE: self.source_role,
            SliceDimension.BEAT: self.beat,
            SliceDimension.CASE_KIND: self.case_kind,
        }
        for dimension, value in memberships.items():
            if value not in EXPECTED_SLICE_VALUES[dimension]:
                raise ReviewContractError(f"case {dimension} differs")
        _boolean(self.changed_revision, "changed_revision")
        expected_keys = tuple(
            f"{axis}:{mode}"
            for axis, modes in EXPECTED_ABLATIONS.items()
            for mode in modes
        )
        if not isinstance(self.ablation_evidence_digests, Mapping):
            raise ReviewContractError("case ablation inventory must be an object")
        if tuple(sorted(self.ablation_evidence_digests)) != tuple(sorted(expected_keys)):
            raise ReviewContractError("case ablation inventory differs")
        frozen = {
            key: _digest(value, f"ablation_evidence_digests.{key}")
            for key, value in self.ablation_evidence_digests.items()
        }
        object.__setattr__(self, "ablation_evidence_digests", MappingProxyType(dict(sorted(frozen.items()))))

    def primitive(self) -> dict[str, object]:
        return {
            "ablation_evidence_digests": dict(self.ablation_evidence_digests),
            "beat": self.beat,
            "case_id": self.case_id,
            "case_kind": self.case_kind,
            "changed_revision": self.changed_revision,
            "effective_manifest_digest": self.effective_manifest_digest,
            "epoch_digest": self.epoch_digest,
            "evidence_digest": self.evidence_digest,
            "final_cohort_digest": self.final_cohort_digest,
            "jurisdiction": self.jurisdiction,
            "language": self.language,
            "source_id": self.source_id,
            "source_role": self.source_role,
        }

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.primitive()))

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        value = _mapping(value, frozenset(cls.__dataclass_fields__), "review_case")
        return cls(**value)  # type: ignore[arg-type]


def _exposure_failures(cases: tuple[ReviewCase, ...]) -> tuple[str, ...]:
    failures: list[str] = []
    if len(cases) != 120:
        failures.append("SEMANTIC_CASES_120")
    requirements = (
        ("JURISDICTION_HONG_KONG_30", sum(case.jurisdiction == "HONG_KONG" for case in cases), 30),
        ("JURISDICTION_UK_30", sum(case.jurisdiction == "UK" for case in cases), 30),
        ("LANGUAGE_EN_GB_30", sum(case.language == "EN_GB" for case in cases), 30),
        ("LANGUAGE_ZH_HANT_HK_30", sum(case.language == "ZH_HANT_HK" for case in cases), 30),
        ("LANGUAGE_MIXED_20", sum(case.language == "MIXED" for case in cases), 20),
        ("OFFICIAL_60", sum(case.source_role == "OFFICIAL" for case in cases), 60),
        ("CORRECTION_10", sum(case.case_kind == "CORRECTION_OR_SUPERSESSION" for case in cases), 10),
        ("RELATED_DISTINCT_20", sum(case.case_kind == "RELATED_DISTINCT_OR_FALSE_MERGE" for case in cases), 20),
        ("WARNING_TRANSITION_12", sum(case.case_kind == "WARNING_TRANSITION" for case in cases), 12),
    )
    failures.extend(name for name, observed, minimum in requirements if observed < minimum)
    if sum(case.source_role == "COMPARATOR" for case in cases) * 3 > len(cases):
        failures.append("COMPARATOR_FRACTION_MAX_ONE_THIRD")
    for beat in EXPECTED_SLICE_VALUES[SliceDimension.BEAT]:
        if sum(case.beat == beat for case in cases) < 20:
            failures.append(f"BEAT_{beat}_20")
    for source_id in EXPECTED_SOURCE_IDS:
        if sum(case.source_id == source_id and case.changed_revision for case in cases) < 10:
            failures.append(f"SOURCE_{source_id}_CHANGED_10")
    return tuple(sorted(failures))


@dataclass(frozen=True, slots=True)
class ReviewUniverseSeal(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.review-universe-seal.v1"
    universe_id: str
    review_plan_digest: str
    epoch_digest: str
    final_cohort_digest: str
    effective_manifest_digest: str
    sealed_evidence_inventory_digest: str
    cases: tuple[ReviewCase, ...]
    sealed_at: str
    prospective_evidence_sealed: bool = True
    natural_warning_transitions_complete: bool = True
    result_knowledge_available_at_seal: bool = False
    case_substitution_allowed: bool = False

    def __post_init__(self) -> None:
        _token(self.universe_id, "universe_id")
        for field in (
            "review_plan_digest",
            "epoch_digest",
            "final_cohort_digest",
            "effective_manifest_digest",
            "sealed_evidence_inventory_digest",
        ):
            _digest(getattr(self, field), field)
        if type(self.cases) is not tuple or not self.cases:
            raise ReviewContractError("review cases must be a non-empty tuple")
        if any(type(case) is not ReviewCase for case in self.cases):
            raise ReviewContractError("review case type differs")
        if tuple(sorted(case.case_id for case in self.cases)) != tuple(case.case_id for case in self.cases):
            raise ReviewContractError("review cases must be sorted by case ID")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ReviewContractError("review case IDs must be unique")
        if len({case.evidence_digest for case in self.cases}) != len(self.cases):
            raise ReviewContractError("review evidence digests must be unique")
        for case in self.cases:
            if (
                case.epoch_digest,
                case.final_cohort_digest,
                case.effective_manifest_digest,
            ) != (
                self.epoch_digest,
                self.final_cohort_digest,
                self.effective_manifest_digest,
            ):
                raise ReviewContractError("review case authority binding differs")
        failures = _exposure_failures(self.cases)
        if failures:
            raise ReviewContractError("review exposure differs: " + ",".join(failures))
        _timestamp(self.sealed_at, "sealed_at")
        if (
            self.prospective_evidence_sealed,
            self.natural_warning_transitions_complete,
            self.result_knowledge_available_at_seal,
            self.case_substitution_allowed,
        ) != (True, True, False, False):
            raise ReviewContractError("review sealing or anti-hindsight rules differ")

    def primitive(self) -> dict[str, object]:
        return {
            "case_substitution_allowed": self.case_substitution_allowed,
            "cases": [case.primitive() for case in self.cases],
            "effective_manifest_digest": self.effective_manifest_digest,
            "epoch_digest": self.epoch_digest,
            "final_cohort_digest": self.final_cohort_digest,
            "natural_warning_transitions_complete": self.natural_warning_transitions_complete,
            "prospective_evidence_sealed": self.prospective_evidence_sealed,
            "result_knowledge_available_at_seal": self.result_knowledge_available_at_seal,
            "review_plan_digest": self.review_plan_digest,
            "schema_version": self.schema_version,
            "sealed_at": self.sealed_at,
            "sealed_evidence_inventory_digest": self.sealed_evidence_inventory_digest,
            "universe_id": self.universe_id,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        raw_cases = value["cases"]
        if type(raw_cases) is not list:
            raise ReviewContractError("review cases must be an array")
        value["cases"] = tuple(ReviewCase.from_primitive(item) for item in raw_cases)
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ReviewAssignment(_NoEffect):
    assignment_id: str
    review_plan_digest: str
    universe_digest: str
    case_id: str
    case_digest: str
    role: ReviewRole
    reviewer_profile_digest: str
    ordinal: int
    assigned_at: str

    def __post_init__(self) -> None:
        _token(self.assignment_id, "assignment_id")
        for field in ("review_plan_digest", "universe_digest", "case_digest", "reviewer_profile_digest"):
            _digest(getattr(self, field), field)
        _token(self.case_id, "case_id")
        object.__setattr__(self, "role", _enum(ReviewRole, self.role, "role"))
        _integer(self.ordinal, "ordinal", minimum=1)
        _timestamp(self.assigned_at, "assigned_at")

    def primitive(self) -> dict[str, object]:
        return {
            "assigned_at": self.assigned_at,
            "assignment_id": self.assignment_id,
            "case_digest": self.case_digest,
            "case_id": self.case_id,
            "ordinal": self.ordinal,
            "review_plan_digest": self.review_plan_digest,
            "reviewer_profile_digest": self.reviewer_profile_digest,
            "role": str(self.role),
            "universe_digest": self.universe_digest,
        }

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.primitive()))

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        value = _mapping(value, frozenset(cls.__dataclass_fields__), "assignment")
        value["role"] = _enum(ReviewRole, value["role"], "role")
        return cls(**value)  # type: ignore[arg-type]


def _profile_digest(profile: ReviewerProfile) -> str:
    return digest_bytes(canonical_json_bytes(profile.primitive()))


@dataclass(frozen=True, slots=True)
class AssignmentManifest(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.assignment-manifest.v1"
    manifest_id: str
    review_plan_digest: str
    universe_digest: str
    assignments: tuple[ReviewAssignment, ...]
    sealed_at: str
    replacement_allowed: bool = False

    def __post_init__(self) -> None:
        _token(self.manifest_id, "manifest_id")
        _digest(self.review_plan_digest, "review_plan_digest")
        _digest(self.universe_digest, "universe_digest")
        if type(self.assignments) is not tuple or not self.assignments:
            raise ReviewContractError("assignment manifest is empty")
        if any(type(item) is not ReviewAssignment for item in self.assignments):
            raise ReviewContractError("assignment type differs")
        if len({item.assignment_id for item in self.assignments}) != len(self.assignments):
            raise ReviewContractError("assignment IDs must be unique")
        if any(
            item.review_plan_digest != self.review_plan_digest
            or item.universe_digest != self.universe_digest
            or item.role not in {ReviewRole.PRIMARY_A, ReviewRole.PRIMARY_B}
            for item in self.assignments
        ):
            raise ReviewContractError("assignment authority differs")
        _timestamp(self.sealed_at, "sealed_at")
        if self.replacement_allowed is not False:
            raise ReviewContractError("reviewer replacement is prohibited")

    def primitive(self) -> dict[str, object]:
        return {
            "assignments": [item.primitive() for item in self.assignments],
            "manifest_id": self.manifest_id,
            "replacement_allowed": self.replacement_allowed,
            "review_plan_digest": self.review_plan_digest,
            "schema_version": self.schema_version,
            "sealed_at": self.sealed_at,
            "universe_digest": self.universe_digest,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        raw_assignments = value["assignments"]
        if type(raw_assignments) is not list:
            raise ReviewContractError("assignments must be an array")
        value["assignments"] = tuple(ReviewAssignment.from_primitive(item) for item in raw_assignments)
        return cls(**value)  # type: ignore[arg-type]


def build_assignment_manifest(
    plan: ReviewPlan,
    universe: ReviewUniverseSeal,
    *,
    manifest_id: str,
    sealed_at: str,
) -> AssignmentManifest:
    """Assign every sealed Case to both primaries in deterministic order."""

    if type(plan) is not ReviewPlan or type(universe) is not ReviewUniverseSeal:
        raise ReviewContractError("assignment authority types differ")
    if universe.review_plan_digest != plan.canonical_digest:
        raise ReviewContractError("review universe plan binding differs")
    if _instant(sealed_at) < _instant(universe.sealed_at):
        raise ReviewContractError("assignment predates the sealed universe")
    profiles = {profile.role: profile for profile in plan.reviewer_profiles}
    assignments = tuple(
        ReviewAssignment(
            assignment_id=f"assignment-{ordinal:03d}-{role.value.lower().replace('_', '-')}",
            review_plan_digest=plan.canonical_digest,
            universe_digest=universe.canonical_digest,
            case_id=case.case_id,
            case_digest=case.canonical_digest,
            role=role,
            reviewer_profile_digest=_profile_digest(profiles[role]),
            ordinal=ordinal,
            assigned_at=sealed_at,
        )
        for ordinal, case in enumerate(universe.cases, start=1)
        for role in (ReviewRole.PRIMARY_A, ReviewRole.PRIMARY_B)
    )
    return AssignmentManifest(
        manifest_id=manifest_id,
        review_plan_digest=plan.canonical_digest,
        universe_digest=universe.canonical_digest,
        assignments=assignments,
        sealed_at=sealed_at,
    )


@dataclass(frozen=True, slots=True)
class ReviewLabel(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.review-label.v1"
    label_id: str
    assignment_digest: str
    case_id: str
    case_digest: str
    role: ReviewRole
    reviewer_profile_digest: str
    resolved_model_identity_digest: str
    memory_snapshot_digest: str
    verdict: ReviewVerdict
    reasons: tuple[str, ...]
    confidence_ppm: int
    research_appendix_digest: str
    sealed_at: str
    peer_result_visible: bool = False
    operational_metadata_visible: bool = False

    def __post_init__(self) -> None:
        _token(self.label_id, "label_id")
        for field in (
            "assignment_digest",
            "case_digest",
            "reviewer_profile_digest",
            "resolved_model_identity_digest",
            "memory_snapshot_digest",
            "research_appendix_digest",
        ):
            _digest(getattr(self, field), field)
        _token(self.case_id, "case_id")
        role = _enum(ReviewRole, self.role, "role")
        if role is ReviewRole.ADJUDICATOR:
            raise ReviewContractError("adjudicator cannot create a primary label")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "verdict", _enum(ReviewVerdict, self.verdict, "verdict"))
        reasons = _tokens(self.reasons, "reasons", allow_empty=True)
        object.__setattr__(self, "reasons", reasons)
        if any(reason not in EXPECTED_REVIEW_REASONS for reason in reasons):
            raise ReviewContractError("review reason differs")
        if self.verdict is ReviewVerdict.PASS and reasons:
            raise ReviewContractError("PASS label cannot contain failure reasons")
        if self.verdict is not ReviewVerdict.PASS and not reasons:
            raise ReviewContractError("non-PASS label requires a structured reason")
        _integer(self.confidence_ppm, "confidence_ppm", maximum=1_000_000)
        _timestamp(self.sealed_at, "sealed_at")
        if (self.peer_result_visible, self.operational_metadata_visible) != (False, False):
            raise ReviewContractError("review blinding boundary was crossed")

    def primitive(self) -> dict[str, object]:
        return {
            "assignment_digest": self.assignment_digest,
            "case_digest": self.case_digest,
            "case_id": self.case_id,
            "confidence_ppm": self.confidence_ppm,
            "label_id": self.label_id,
            "memory_snapshot_digest": self.memory_snapshot_digest,
            "operational_metadata_visible": self.operational_metadata_visible,
            "peer_result_visible": self.peer_result_visible,
            "reasons": list(self.reasons),
            "research_appendix_digest": self.research_appendix_digest,
            "resolved_model_identity_digest": self.resolved_model_identity_digest,
            "reviewer_profile_digest": self.reviewer_profile_digest,
            "role": str(self.role),
            "schema_version": self.schema_version,
            "sealed_at": self.sealed_at,
            "verdict": str(self.verdict),
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        value["role"] = _enum(ReviewRole, value["role"], "role")
        value["verdict"] = _enum(ReviewVerdict, value["verdict"], "verdict")
        value["reasons"] = tuple(value["reasons"])  # type: ignore[arg-type]
        return cls(**value)  # type: ignore[arg-type]


def validate_label_for_assignment(label: ReviewLabel, assignment: ReviewAssignment) -> ReviewLabel:
    if type(label) is not ReviewLabel or type(assignment) is not ReviewAssignment:
        raise ReviewContractError("review label assignment types differ")
    if (
        label.assignment_digest != assignment.canonical_digest
        or label.case_id != assignment.case_id
        or label.case_digest != assignment.case_digest
        or label.role != assignment.role
        or label.reviewer_profile_digest != assignment.reviewer_profile_digest
        or _instant(label.sealed_at) < _instant(assignment.assigned_at)
    ):
        raise ReviewContractError("review label assignment binding differs")
    return label


@dataclass(frozen=True, slots=True)
class AdjudicationDecision(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.adjudication.v1"
    adjudication_id: str
    case_id: str
    case_digest: str
    primary_a_label_digest: str
    primary_b_label_digest: str
    adjudicator_profile_digest: str
    resolved_model_identity_digest: str
    memory_snapshot_digest: str
    final_verdict: ReviewVerdict
    final_reasons: tuple[str, ...]
    research_appendix_digest: str
    decided_at: str
    peer_results_materialised_after_both_sealed: bool = True

    def __post_init__(self) -> None:
        _token(self.adjudication_id, "adjudication_id")
        _token(self.case_id, "case_id")
        for field in (
            "case_digest",
            "primary_a_label_digest",
            "primary_b_label_digest",
            "adjudicator_profile_digest",
            "resolved_model_identity_digest",
            "memory_snapshot_digest",
            "research_appendix_digest",
        ):
            _digest(getattr(self, field), field)
        object.__setattr__(self, "final_verdict", _enum(ReviewVerdict, self.final_verdict, "final_verdict"))
        reasons = _tokens(self.final_reasons, "final_reasons", allow_empty=True)
        object.__setattr__(self, "final_reasons", reasons)
        if any(reason not in EXPECTED_REVIEW_REASONS for reason in reasons):
            raise ReviewContractError("adjudication reason differs")
        if self.final_verdict is ReviewVerdict.PASS and reasons:
            raise ReviewContractError("PASS adjudication cannot contain failure reasons")
        if self.final_verdict is not ReviewVerdict.PASS and not reasons:
            raise ReviewContractError("non-PASS adjudication requires reasons")
        _timestamp(self.decided_at, "decided_at")
        if self.peer_results_materialised_after_both_sealed is not True:
            raise ReviewContractError("adjudication unblinding boundary differs")

    def primitive(self) -> dict[str, object]:
        return {
            "adjudication_id": self.adjudication_id,
            "adjudicator_profile_digest": self.adjudicator_profile_digest,
            "case_digest": self.case_digest,
            "case_id": self.case_id,
            "decided_at": self.decided_at,
            "final_reasons": list(self.final_reasons),
            "final_verdict": str(self.final_verdict),
            "memory_snapshot_digest": self.memory_snapshot_digest,
            "peer_results_materialised_after_both_sealed": self.peer_results_materialised_after_both_sealed,
            "primary_a_label_digest": self.primary_a_label_digest,
            "primary_b_label_digest": self.primary_b_label_digest,
            "research_appendix_digest": self.research_appendix_digest,
            "resolved_model_identity_digest": self.resolved_model_identity_digest,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        value["final_verdict"] = _enum(ReviewVerdict, value["final_verdict"], "final_verdict")
        value["final_reasons"] = tuple(value["final_reasons"])  # type: ignore[arg-type]
        return cls(**value)  # type: ignore[arg-type]


def build_adjudication(
    plan: ReviewPlan,
    primary_a: ReviewLabel,
    primary_b: ReviewLabel,
    *,
    adjudication_id: str,
    resolved_model_identity_digest: str,
    memory_snapshot_digest: str,
    final_verdict: ReviewVerdict,
    final_reasons: tuple[str, ...],
    research_appendix_digest: str,
    decided_at: str,
) -> AdjudicationDecision:
    if (
        type(plan) is not ReviewPlan
        or type(primary_a) is not ReviewLabel
        or type(primary_b) is not ReviewLabel
    ):
        raise ReviewContractError("adjudication authority types differ")
    if {primary_a.role, primary_b.role} != {ReviewRole.PRIMARY_A, ReviewRole.PRIMARY_B}:
        raise ReviewContractError("adjudication requires both primary roles")
    if (primary_a.case_id, primary_a.case_digest) != (primary_b.case_id, primary_b.case_digest):
        raise ReviewContractError("adjudication Case differs")
    zero_tolerance = bool(
        set(primary_a.reasons + primary_b.reasons) & set(EXPECTED_ZERO_TOLERANCE)
    )
    if primary_a.verdict == primary_b.verdict and primary_a.reasons == primary_b.reasons and not zero_tolerance:
        raise ReviewContractError("agreement does not require adjudication")
    if ReviewVerdict.NOT_EVALUATED in {primary_a.verdict, primary_b.verdict}:
        raise ReviewContractError("missing or invalid primary cannot be adjudicated")
    profiles = {item.role: item for item in plan.reviewer_profiles}
    if (
        primary_a.reviewer_profile_digest != _profile_digest(profiles[primary_a.role])
        or primary_b.reviewer_profile_digest != _profile_digest(profiles[primary_b.role])
    ):
        raise ReviewContractError("primary reviewer authority differs")
    if _instant(decided_at) < max(_instant(primary_a.sealed_at), _instant(primary_b.sealed_at)):
        raise ReviewContractError("adjudication predates sealed primary labels")
    profile = profiles[ReviewRole.ADJUDICATOR]
    return AdjudicationDecision(
        adjudication_id=adjudication_id,
        case_id=primary_a.case_id,
        case_digest=primary_a.case_digest,
        primary_a_label_digest=primary_a.canonical_digest if primary_a.role is ReviewRole.PRIMARY_A else primary_b.canonical_digest,
        primary_b_label_digest=primary_b.canonical_digest if primary_b.role is ReviewRole.PRIMARY_B else primary_a.canonical_digest,
        adjudicator_profile_digest=_profile_digest(profile),
        resolved_model_identity_digest=resolved_model_identity_digest,
        memory_snapshot_digest=memory_snapshot_digest,
        final_verdict=final_verdict,
        final_reasons=final_reasons,
        research_appendix_digest=research_appendix_digest,
        decided_at=decided_at,
    )


@dataclass(frozen=True, slots=True)
class ReviewIngestRequest(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.review-ingest-request.v1"
    request_id: str
    review_plan_digest: str
    universe_digest: str
    assignment_manifest_digest: str
    epoch_digest: str
    final_cohort_digest: str
    effective_manifest_digest: str
    sealed_evidence_inventory_digest: str
    requested_at: str
    final_cohort_qualifies: bool
    evidence_inventory_sealed: bool
    prospective_only: bool
    material_change: bool
    result_knowledge_changed_universe: bool

    def __post_init__(self) -> None:
        _token(self.request_id, "request_id")
        for field in (
            "review_plan_digest",
            "universe_digest",
            "assignment_manifest_digest",
            "epoch_digest",
            "final_cohort_digest",
            "effective_manifest_digest",
            "sealed_evidence_inventory_digest",
        ):
            _digest(getattr(self, field), field)
        _timestamp(self.requested_at, "requested_at")
        for field in (
            "final_cohort_qualifies",
            "evidence_inventory_sealed",
            "prospective_only",
            "material_change",
            "result_knowledge_changed_universe",
        ):
            _boolean(getattr(self, field), field)

    def primitive(self) -> dict[str, object]:
        return {
            "assignment_manifest_digest": self.assignment_manifest_digest,
            "effective_manifest_digest": self.effective_manifest_digest,
            "epoch_digest": self.epoch_digest,
            "evidence_inventory_sealed": self.evidence_inventory_sealed,
            "final_cohort_digest": self.final_cohort_digest,
            "final_cohort_qualifies": self.final_cohort_qualifies,
            "material_change": self.material_change,
            "prospective_only": self.prospective_only,
            "request_id": self.request_id,
            "requested_at": self.requested_at,
            "result_knowledge_changed_universe": self.result_knowledge_changed_universe,
            "review_plan_digest": self.review_plan_digest,
            "schema_version": self.schema_version,
            "sealed_evidence_inventory_digest": self.sealed_evidence_inventory_digest,
            "universe_digest": self.universe_digest,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        return cls(**_document(raw, cls.schema_version, fields))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ReviewIngestReceipt(_NoEffect):
    request_digest: str
    disposition: IngestDisposition
    reason: str
    runtime_reviewer_authority_still_required: bool = True

    def __post_init__(self) -> None:
        _digest(self.request_digest, "request_digest")
        object.__setattr__(self, "disposition", _enum(IngestDisposition, self.disposition, "disposition"))
        _token(self.reason, "reason")
        if self.runtime_reviewer_authority_still_required is not True:
            raise ReviewContractError("9D1 cannot grant runtime reviewer authority")


class SealedEvidenceIngestController(_NoEffect):
    """Pure boundary that 9D2 must pass before reviewer access is possible."""

    def __init__(self, plan: ReviewPlan, universe: ReviewUniverseSeal, assignments: AssignmentManifest):
        if (
            type(plan) is not ReviewPlan
            or type(universe) is not ReviewUniverseSeal
            or type(assignments) is not AssignmentManifest
        ):
            raise ReviewContractError("review ingest authority types differ")
        if universe.review_plan_digest != plan.canonical_digest:
            raise ReviewContractError("universe Review Plan binding differs")
        if (
            assignments.review_plan_digest != plan.canonical_digest
            or assignments.universe_digest != universe.canonical_digest
        ):
            raise ReviewContractError("assignment authority binding differs")
        expected_count = len(universe.cases) * 2
        if len(assignments.assignments) != expected_count:
            raise ReviewContractError("every Case requires both primary assignments")
        expected = build_assignment_manifest(
            plan,
            universe,
            manifest_id=assignments.manifest_id,
            sealed_at=assignments.sealed_at,
        )
        if assignments.assignments != expected.assignments:
            raise ReviewContractError("deterministic assignment replay differs")
        grouped: dict[str, set[ReviewRole]] = {}
        for assignment in assignments.assignments:
            grouped.setdefault(assignment.case_id, set()).add(assignment.role)
        if set(grouped) != {case.case_id for case in universe.cases} or any(
            roles != {ReviewRole.PRIMARY_A, ReviewRole.PRIMARY_B}
            for roles in grouped.values()
        ):
            raise ReviewContractError("primary assignment coverage differs")
        self._plan = plan
        self._universe = universe
        self._assignments = assignments

    def admit(self, request: ReviewIngestRequest) -> ReviewIngestReceipt:
        if type(request) is not ReviewIngestRequest:
            raise ReviewContractError("review ingest request type differs")
        exact = (
            request.review_plan_digest == self._plan.canonical_digest,
            request.universe_digest == self._universe.canonical_digest,
            request.assignment_manifest_digest == self._assignments.canonical_digest,
            request.epoch_digest == self._universe.epoch_digest,
            request.final_cohort_digest == self._universe.final_cohort_digest,
            request.effective_manifest_digest == self._universe.effective_manifest_digest,
            request.sealed_evidence_inventory_digest
            == self._universe.sealed_evidence_inventory_digest,
            _instant(request.requested_at) >= _instant(self._assignments.sealed_at),
        )
        if not all(exact):
            return ReviewIngestReceipt(request.canonical_digest, IngestDisposition.REJECTED, "AUTHORITY_BINDING_DIFFERS")
        if not request.final_cohort_qualifies:
            return ReviewIngestReceipt(request.canonical_digest, IngestDisposition.REJECTED, "FINAL_COHORT_NOT_QUALIFIED")
        if not request.evidence_inventory_sealed or not request.prospective_only:
            return ReviewIngestReceipt(request.canonical_digest, IngestDisposition.REJECTED, "EVIDENCE_NOT_SEALED_PROSPECTIVE")
        if request.material_change:
            return ReviewIngestReceipt(request.canonical_digest, IngestDisposition.REJECTED, "MATERIAL_CHANGE_CLOSES_EPOCH")
        if request.result_knowledge_changed_universe:
            return ReviewIngestReceipt(request.canonical_digest, IngestDisposition.REJECTED, "HINDSIGHT_UNIVERSE_CHANGE")
        return ReviewIngestReceipt(
            request.canonical_digest,
            IngestDisposition.ADMITTED_FOR_LATER_REVIEW,
            "EXACT_SEALED_UNIVERSE",
        )
