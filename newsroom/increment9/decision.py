"""Sealed Increment 9D2 metric and shadow-decision authority.

The module consumes already verified evidence identities.  It performs no file,
network, reviewer, provider or production I/O.  Missing prospective evidence is
represented explicitly and can only yield a non-activating blocked decision.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Mapping, Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.plan import (
    INCREMENT_9_SHADOW_PLAN,
    INCREMENT_9_SHADOW_PLAN_DIGEST,
)
from newsroom.increment9.review import (
    EXPECTED_ABLATIONS,
    EXPECTED_METRICS,
    EXPECTED_REVIEWERS,
    EXPECTED_SLICE_VALUES,
    EXPECTED_ZERO_TOLERANCE,
    MetricDirection,
)

MAX_RECORD_BYTES = 4_194_304
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class DecisionError(ValueError):
    """Sealed evidence or a derived decision differs from 9D1 authority."""


class EvidenceVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class ShadowDisposition(StrEnum):
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CONTINUE_SHADOW = "CONTINUE_SHADOW"
    COMPARATOR_ONLY = "COMPARATOR_ONLY"
    BLOCKED_ACTIVE_COVERAGE = "BLOCKED_ACTIVE_COVERAGE"
    SCOPED_OPERATIONAL_ELIGIBILITY = "SCOPED_OPERATIONAL_ELIGIBILITY"


BLOCKED_REASON_IDS = (
    "ACTIVE_COVERAGE_ZERO",
    "BASELINE_BLOCKED_BEFORE_FIRST_IO",
    "COMPARATOR_FAULT_NOT_RUN",
    "REQUIRED_EXPOSURE_UNMET",
    "REVIEWER_IDENTITIES_NOT_RESOLVED",
    "REVIEW_UNIVERSE_EMPTY",
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
    authorises_increment10 = False


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if type(name) is not str or name in value:
            raise DecisionError("decision JSON names are invalid or duplicated")
        value[name] = item
    return value


def _document(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
        raise DecisionError("decision bytes are absent or unbounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except DecisionError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
    ) as exc:
        raise DecisionError("decision bytes are not canonical JSON") from exc
    if canonical != raw or type(value) is not dict:
        raise DecisionError("decision bytes differ")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise DecisionError(f"{field} digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise DecisionError(f"{field} digest differs") from exc


def _nonnegative(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise DecisionError(f"{field} count differs")
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class MetricOutcome(_NoEffect):
    metric_id: str
    direction: MetricDirection
    threshold: int
    denominator_id: str
    numerator: int
    denominator: int
    observed_value: int | None
    verdict: EvidenceVerdict
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        expected = EXPECTED_METRICS.get(self.metric_id)
        if expected is None or (
            self.direction,
            self.threshold,
            self.denominator_id,
        ) != expected:
            raise DecisionError("metric authority differs")
        _nonnegative(self.numerator, "metric numerator")
        _nonnegative(self.denominator, "metric denominator")
        if (
            self.numerator != 0
            or self.denominator != 0
            or self.observed_value is not None
            or self.verdict is not EvidenceVerdict.NOT_EVALUATED
            or self.reasons != ("MISSING_EVIDENCE",)
        ):
            raise DecisionError("zero-universe metric must remain NOT_EVALUATED")

    def primitive(self) -> dict[str, object]:
        return {
            "denominator": self.denominator,
            "denominator_id": self.denominator_id,
            "direction": self.direction.value,
            "metric_id": self.metric_id,
            "numerator": self.numerator,
            "observed_value": self.observed_value,
            "reasons": list(self.reasons),
            "threshold": self.threshold,
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True, slots=True)
class DimensionOutcome(_NoEffect):
    dimension: str
    value: str
    case_count: int
    verdict: EvidenceVerdict
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        expected = {
            dimension.value: values
            for dimension, values in EXPECTED_SLICE_VALUES.items()
        }
        if self.dimension not in expected or self.value not in expected[self.dimension]:
            raise DecisionError("slice authority differs")
        if (
            self.case_count != 0
            or self.verdict is not EvidenceVerdict.NOT_EVALUATED
            or self.reasons != ("MISSING_EVIDENCE",)
        ):
            raise DecisionError("zero-universe slice must remain NOT_EVALUATED")

    def primitive(self) -> dict[str, object]:
        return {
            "case_count": self.case_count,
            "dimension": self.dimension,
            "reasons": list(self.reasons),
            "value": self.value,
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True, slots=True)
class AblationOutcome(_NoEffect):
    axis: str
    mode: str
    case_count: int
    verdict: EvidenceVerdict
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.axis not in EXPECTED_ABLATIONS or self.mode not in EXPECTED_ABLATIONS[self.axis]:
            raise DecisionError("ablation authority differs")
        if (
            self.case_count != 0
            or self.verdict is not EvidenceVerdict.NOT_EVALUATED
            or self.reasons != ("MISSING_EVIDENCE",)
        ):
            raise DecisionError("zero-universe ablation must remain NOT_EVALUATED")

    def primitive(self) -> dict[str, object]:
        return {
            "axis": self.axis,
            "case_count": self.case_count,
            "mode": self.mode,
            "reasons": list(self.reasons),
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True, slots=True)
class ReviewerOutcome(_NoEffect):
    role: str
    provider: str
    route: str
    model_selector: str
    memory_namespace: str
    resolved_identity: str | None
    invocation_count: int
    label_count: int
    verdict: EvidenceVerdict
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        expected_by_role = {
            role.value: profile for role, profile in EXPECTED_REVIEWERS.items()
        }
        expected = expected_by_role.get(self.role)
        actual = (
            self.provider,
            self.route,
            self.model_selector,
            self.memory_namespace,
        )
        if expected is None or actual != expected:
            raise DecisionError("reviewer authority differs")
        if (
            self.resolved_identity is not None
            or self.invocation_count != 0
            or self.label_count != 0
            or self.verdict is not EvidenceVerdict.NOT_EVALUATED
            or self.reasons != ("IDENTITY_UNRESOLVED", "MISSING_EVIDENCE")
        ):
            raise DecisionError("uninvoked reviewer result differs")

    def primitive(self) -> dict[str, object]:
        return {
            "invocation_count": self.invocation_count,
            "label_count": self.label_count,
            "memory_namespace": self.memory_namespace,
            "model_selector": self.model_selector,
            "provider": self.provider,
            "reasons": list(self.reasons),
            "resolved_identity": self.resolved_identity,
            "role": self.role,
            "route": self.route,
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True, slots=True)
class BlockedShadowDecision(_NoEffect):
    schema_version: ClassVar[str] = "newsroom.increment9.blocked-shadow-decision.v1"
    decision_id: str
    decided_at: str
    exact_main_sha: str
    exact_main_tree: str
    campaign_bundle_digest: str
    fault_bundle_digest: str
    dependency_evidence_digest: str
    review_contract_git_blob: str
    metrics: tuple[MetricOutcome, ...]
    slices: tuple[DimensionOutcome, ...]
    ablations: tuple[AblationOutcome, ...]
    reviewers: tuple[ReviewerOutcome, ...]
    zero_tolerance: tuple[Mapping[str, object], ...]
    cost_and_capacity: Mapping[str, object]
    operational_domains: tuple[Mapping[str, object], ...]
    production_equivalence: Mapping[str, object]
    disposition: ShadowDisposition
    reason_ids: tuple[str, ...]
    residual_blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _TOKEN.fullmatch(self.decision_id):
            raise DecisionError("decision identity differs")
        if not _UTC.fullmatch(self.decided_at):
            raise DecisionError("decision timestamp differs")
        for value in (
            self.exact_main_sha,
            self.exact_main_tree,
            self.review_contract_git_blob,
        ):
            if not re.fullmatch(r"[0-9a-f]{40}", value):
                raise DecisionError("decision checkout identity differs")
        for field in (
            "campaign_bundle_digest",
            "fault_bundle_digest",
            "dependency_evidence_digest",
        ):
            _digest(getattr(self, field), field)
        if self.disposition is not ShadowDisposition.BLOCKED_ACTIVE_COVERAGE:
            raise DecisionError("zero-universe decision must block active coverage")
        if (
            self.reason_ids != BLOCKED_REASON_IDS
            or not self.residual_blockers
            or self.residual_blockers
            != tuple(sorted(set(self.residual_blockers)))
        ):
            raise DecisionError("blocked decision reasons differ")
        if tuple(item.metric_id for item in self.metrics) != tuple(sorted(EXPECTED_METRICS)):
            raise DecisionError("metric inventory differs")
        expected_slices = tuple(
            (dimension.value, value)
            for dimension, values in EXPECTED_SLICE_VALUES.items()
            for value in values
        )
        if tuple((item.dimension, item.value) for item in self.slices) != expected_slices:
            raise DecisionError("slice inventory differs")
        expected_ablations = tuple(
            (axis, mode)
            for axis, modes in EXPECTED_ABLATIONS.items()
            for mode in modes
        )
        if tuple((item.axis, item.mode) for item in self.ablations) != expected_ablations:
            raise DecisionError("ablation inventory differs")
        if tuple(item.role for item in self.reviewers) != tuple(
            role.value for role in EXPECTED_REVIEWERS
        ):
            raise DecisionError("reviewer inventory differs")
        if tuple(item["finding_id"] for item in self.zero_tolerance) != EXPECTED_ZERO_TOLERANCE:
            raise DecisionError("zero-tolerance inventory differs")
        if any(
            item != {
                "evidence_absent": True,
                "finding_id": item["finding_id"],
                "observed_count": 0,
                "verdict": "NOT_EVALUATED",
            }
            for item in self.zero_tolerance
        ):
            raise DecisionError("zero-tolerance result differs")
        if set(self.cost_and_capacity) != {
            "embedding_calls",
            "gross_gbp_minor_units",
            "model_calls",
            "provider_requests",
            "reviewer_invocations",
            "reviewer_minutes",
            "source_http_attempts",
            "storage_bytes",
        } or any(value != 0 for value in self.cost_and_capacity.values()):
            raise DecisionError("cost result differs")
        expected_domains = (
            "CAPACITY",
            "COST",
            "COVERAGE",
            "DEGRADATION",
            "QUALITY",
            "RECOVERY",
            "RIGHTS",
            "SECURITY",
            "TIMELINESS",
        )
        if tuple(item["domain"] for item in self.operational_domains) != expected_domains:
            raise DecisionError("operational domain inventory differs")
        if any(item["verdict"] != "NOT_EVALUATED" for item in self.operational_domains):
            raise DecisionError("operational domain verdict differs")
        expected_differences = next(
            item.selection
            for item in INCREMENT_9_SHADOW_PLAN.owner_decisions
            if item.decision_id == "OD-013"
        )
        if self.production_equivalence != {
            "claim_permitted": False,
            "owner_statement": _plain(expected_differences),
            "reason": "NO_DECISION_BEARING_PROSPECTIVE_EVIDENCE",
        }:
            raise DecisionError("production-equivalence result differs")

    def primitive(self) -> dict[str, object]:
        return {
            "ablations": [item.primitive() for item in self.ablations],
            "authorities": {
                "canary": False,
                "evidence_intake": False,
                "increment10": False,
                "production_activation": False,
                "production_mutation": False,
                "publication": False,
            },
            "campaign_bundle_digest": self.campaign_bundle_digest,
            "cost_and_capacity": dict(self.cost_and_capacity),
            "decided_at": self.decided_at,
            "decision_id": self.decision_id,
            "dependency_evidence_digest": self.dependency_evidence_digest,
            "disposition": self.disposition.value,
            "exact_main_sha": self.exact_main_sha,
            "exact_main_tree": self.exact_main_tree,
            "fault_bundle_digest": self.fault_bundle_digest,
            "metrics": [item.primitive() for item in self.metrics],
            "operational_domains": [dict(item) for item in self.operational_domains],
            "owner_plan_digest": INCREMENT_9_SHADOW_PLAN_DIGEST,
            "production_equivalence": dict(self.production_equivalence),
            "reason_ids": list(self.reason_ids),
            "residual_blockers": list(self.residual_blockers),
            "review_contract_git_blob": self.review_contract_git_blob,
            "reviewers": [item.primitive() for item in self.reviewers],
            "schema_version": self.schema_version,
            "slices": [item.primitive() for item in self.slices],
            "zero_tolerance": [dict(item) for item in self.zero_tolerance],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.primitive())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = _document(raw)
        expected_fields = {
            "ablations",
            "authorities",
            "campaign_bundle_digest",
            "cost_and_capacity",
            "decided_at",
            "decision_id",
            "dependency_evidence_digest",
            "disposition",
            "exact_main_sha",
            "exact_main_tree",
            "fault_bundle_digest",
            "metrics",
            "operational_domains",
            "owner_plan_digest",
            "production_equivalence",
            "reason_ids",
            "residual_blockers",
            "review_contract_git_blob",
            "reviewers",
            "schema_version",
            "slices",
            "zero_tolerance",
        }
        if set(value) != expected_fields or value["schema_version"] != cls.schema_version:
            raise DecisionError("decision fields differ")
        if value["owner_plan_digest"] != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise DecisionError("decision owner plan differs")
        if value["authorities"] != {
            "canary": False,
            "evidence_intake": False,
            "increment10": False,
            "production_activation": False,
            "production_mutation": False,
            "publication": False,
        }:
            raise DecisionError("decision authority differs")
        metrics = tuple(
            MetricOutcome(
                metric_id=item["metric_id"],
                direction=MetricDirection(item["direction"]),
                threshold=item["threshold"],
                denominator_id=item["denominator_id"],
                numerator=item["numerator"],
                denominator=item["denominator"],
                observed_value=item["observed_value"],
                verdict=EvidenceVerdict(item["verdict"]),
                reasons=tuple(item["reasons"]),
            )
            for item in value["metrics"]
        )
        slices = tuple(
            DimensionOutcome(
                dimension=item["dimension"],
                value=item["value"],
                case_count=item["case_count"],
                verdict=EvidenceVerdict(item["verdict"]),
                reasons=tuple(item["reasons"]),
            )
            for item in value["slices"]
        )
        ablations = tuple(
            AblationOutcome(
                axis=item["axis"],
                mode=item["mode"],
                case_count=item["case_count"],
                verdict=EvidenceVerdict(item["verdict"]),
                reasons=tuple(item["reasons"]),
            )
            for item in value["ablations"]
        )
        reviewers = tuple(
            ReviewerOutcome(
                role=item["role"],
                provider=item["provider"],
                route=item["route"],
                model_selector=item["model_selector"],
                memory_namespace=item["memory_namespace"],
                resolved_identity=item["resolved_identity"],
                invocation_count=item["invocation_count"],
                label_count=item["label_count"],
                verdict=EvidenceVerdict(item["verdict"]),
                reasons=tuple(item["reasons"]),
            )
            for item in value["reviewers"]
        )
        result = cls(
            decision_id=value["decision_id"],
            decided_at=value["decided_at"],
            exact_main_sha=value["exact_main_sha"],
            exact_main_tree=value["exact_main_tree"],
            campaign_bundle_digest=value["campaign_bundle_digest"],
            fault_bundle_digest=value["fault_bundle_digest"],
            dependency_evidence_digest=value["dependency_evidence_digest"],
            review_contract_git_blob=value["review_contract_git_blob"],
            metrics=metrics,
            slices=slices,
            ablations=ablations,
            reviewers=reviewers,
            zero_tolerance=tuple(value["zero_tolerance"]),
            cost_and_capacity=value["cost_and_capacity"],
            operational_domains=tuple(value["operational_domains"]),
            production_equivalence=value["production_equivalence"],
            disposition=ShadowDisposition(value["disposition"]),
            reason_ids=tuple(value["reason_ids"]),
            residual_blockers=tuple(value["residual_blockers"]),
        )
        if result.canonical_bytes != raw:
            raise DecisionError("decision reconstruction differs")
        return result


def build_blocked_active_coverage_decision(
    *,
    decision_id: str,
    decided_at: str,
    exact_main_sha: str,
    exact_main_tree: str,
    campaign_bundle_digest: str,
    fault_bundle_digest: str,
    dependency_evidence_digest: str,
    review_contract_git_blob: str,
    residual_blockers: tuple[str, ...],
) -> BlockedShadowDecision:
    metrics = tuple(
        MetricOutcome(
            metric_id=metric_id,
            direction=authority[0],
            threshold=authority[1],
            denominator_id=authority[2],
            numerator=0,
            denominator=0,
            observed_value=None,
            verdict=EvidenceVerdict.NOT_EVALUATED,
            reasons=("MISSING_EVIDENCE",),
        )
        for metric_id, authority in sorted(EXPECTED_METRICS.items())
    )
    slices = tuple(
        DimensionOutcome(
            dimension=dimension.value,
            value=value,
            case_count=0,
            verdict=EvidenceVerdict.NOT_EVALUATED,
            reasons=("MISSING_EVIDENCE",),
        )
        for dimension, values in EXPECTED_SLICE_VALUES.items()
        for value in values
    )
    ablations = tuple(
        AblationOutcome(
            axis=axis,
            mode=mode,
            case_count=0,
            verdict=EvidenceVerdict.NOT_EVALUATED,
            reasons=("MISSING_EVIDENCE",),
        )
        for axis, modes in EXPECTED_ABLATIONS.items()
        for mode in modes
    )
    reviewers = tuple(
        ReviewerOutcome(
            role=role.value,
            provider=profile[0],
            route=profile[1],
            model_selector=profile[2],
            memory_namespace=profile[3],
            resolved_identity=None,
            invocation_count=0,
            label_count=0,
            verdict=EvidenceVerdict.NOT_EVALUATED,
            reasons=("IDENTITY_UNRESOLVED", "MISSING_EVIDENCE"),
        )
        for role, profile in EXPECTED_REVIEWERS.items()
    )
    zero_tolerance = tuple(
        {
            "evidence_absent": True,
            "finding_id": finding_id,
            "observed_count": 0,
            "verdict": "NOT_EVALUATED",
        }
        for finding_id in EXPECTED_ZERO_TOLERANCE
    )
    cost = {
        "embedding_calls": 0,
        "gross_gbp_minor_units": 0,
        "model_calls": 0,
        "provider_requests": 0,
        "reviewer_invocations": 0,
        "reviewer_minutes": 0,
        "source_http_attempts": 0,
        "storage_bytes": 0,
    }
    operational = tuple(
        {
            "domain": domain,
            "reason": "NO_DECISION_BEARING_PROSPECTIVE_EVIDENCE",
            "verdict": "NOT_EVALUATED",
        }
        for domain in (
            "CAPACITY",
            "COST",
            "COVERAGE",
            "DEGRADATION",
            "QUALITY",
            "RECOVERY",
            "RIGHTS",
            "SECURITY",
            "TIMELINESS",
        )
    )
    differences = next(
        item.selection
        for item in INCREMENT_9_SHADOW_PLAN.owner_decisions
        if item.decision_id == "OD-013"
    )
    return BlockedShadowDecision(
        decision_id=decision_id,
        decided_at=decided_at,
        exact_main_sha=exact_main_sha,
        exact_main_tree=exact_main_tree,
        campaign_bundle_digest=campaign_bundle_digest,
        fault_bundle_digest=fault_bundle_digest,
        dependency_evidence_digest=dependency_evidence_digest,
        review_contract_git_blob=review_contract_git_blob,
        metrics=metrics,
        slices=slices,
        ablations=ablations,
        reviewers=reviewers,
        zero_tolerance=zero_tolerance,
        cost_and_capacity=cost,
        operational_domains=operational,
        production_equivalence={
            "claim_permitted": False,
            "owner_statement": _plain(differences),
            "reason": "NO_DECISION_BEARING_PROSPECTIVE_EVIDENCE",
        },
        disposition=ShadowDisposition.BLOCKED_ACTIVE_COVERAGE,
        reason_ids=BLOCKED_REASON_IDS,
        residual_blockers=residual_blockers,
    )
