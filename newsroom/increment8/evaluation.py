"""Immutable Increment 8 evaluation and release-evidence authority.

The API retains pre-registered fixture qualification records.  It cannot start
shadow or production work and every decision explicitly records no activation.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.increment8.readiness import (
    INCREMENT_8_READINESS,
    INCREMENT_8_READINESS_DIGEST,
    CorrectiveGate,
    corrective_gate_authorised,
)


class EvaluationAuthorityError(ValueError):
    """The evaluation command or retained authority state is invalid."""


class RunKind(StrEnum):
    CALIBRATION = "CALIBRATION"
    QUALIFICATION = "QUALIFICATION"


class RightsStatus(StrEnum):
    REVIEWABLE = "REVIEWABLE"
    UNREVIEWABLE = "UNREVIEWABLE"


class ReviewRole(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class HumanAuthorityRole(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    ADJUDICATOR = "ADJUDICATOR"
    RELEASE_OWNER = "RELEASE_OWNER"


class ReleaseVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvaluationAuthorityError(f"{field} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise EvaluationAuthorityError(f"{field} must be canonical UTC text") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise EvaluationAuthorityError(f"{field} must be UTC")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise EvaluationAuthorityError(f"{field} must be a canonical digest") from exc


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 160:
        raise EvaluationAuthorityError(f"{field} must be bounded text")
    allowed = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
    )
    if any(character not in allowed for character in value):
        raise EvaluationAuthorityError(f"{field} contains unsupported characters")
    return value


def _strings(value: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not value:
        raise EvaluationAuthorityError(f"{field} must be a non-empty sequence")
    result = tuple(_token(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise EvaluationAuthorityError(f"{field} must be sorted and unique")
    return result


def _parse_timestamp(value: object, field: str) -> datetime:
    return datetime.fromisoformat(_timestamp(value, field).removesuffix("Z") + "+00:00")


def _not_after(earlier: object, later: object, *, boundary: str) -> None:
    if _parse_timestamp(earlier, boundary) > _parse_timestamp(later, boundary):
        raise EvaluationAuthorityError(f"{boundary} chronology differs")


def _human_authority_manifest(
    *,
    primary_reviewers: Sequence[str],
    secondary_reviewers: Sequence[str],
    adjudicators: Sequence[str],
    release_owners: Sequence[str],
) -> list[dict[str, object]]:
    by_identity: dict[str, set[str]] = {}
    inventories = (
        (HumanAuthorityRole.PRIMARY, primary_reviewers),
        (HumanAuthorityRole.SECONDARY, secondary_reviewers),
        (HumanAuthorityRole.ADJUDICATOR, adjudicators),
        (HumanAuthorityRole.RELEASE_OWNER, release_owners),
    )
    for role, identities in inventories:
        checked = _strings(identities, f"authorised_{role.value.lower()}_digests")
        for identity in checked:
            by_identity.setdefault(_digest(identity, "human identity"), set()).add(
                role.value
            )
    minimum_primary = int(
        INCREMENT_8_READINESS.evaluation_plan["minimum_authorised_primary_reviewers"]
    )
    minimum_adjudicators = int(
        INCREMENT_8_READINESS.evaluation_plan["minimum_authorised_adjudicators"]
    )
    if len(set(primary_reviewers)) < minimum_primary:
        raise EvaluationAuthorityError("authorised primary reviewer minimum differs")
    if len(set(adjudicators)) < minimum_adjudicators:
        raise EvaluationAuthorityError("authorised adjudicator minimum differs")
    return [
        {
            "identity_digest": identity,
            "human": True,
            "roles": sorted(roles),
        }
        for identity, roles in sorted(by_identity.items())
    ]


def _authorised_identities(
    plan: EvaluationPlan, role: HumanAuthorityRole
) -> frozenset[str]:
    manifest = plan.payload.get("authorised_human_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise EvaluationAuthorityError("authorised human manifest differs")
    result: set[str] = set()
    previous = ""
    for entry in manifest:
        if not isinstance(entry, dict) or set(entry) != {
            "identity_digest",
            "human",
            "roles",
        }:
            raise EvaluationAuthorityError("authorised human manifest differs")
        identity = _digest(entry["identity_digest"], "human identity")
        if identity <= previous or entry["human"] is not True:
            raise EvaluationAuthorityError("authorised human manifest differs")
        previous = identity
        roles = _strings(entry["roles"], "human roles")  # type: ignore[arg-type]
        if any(
            item not in {candidate.value for candidate in HumanAuthorityRole}
            for item in roles
        ):
            raise EvaluationAuthorityError("authorised human role differs")
        if role.value in roles:
            result.add(identity)
    return frozenset(result)


def _membership_facts(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "case_metadata",
        "source_evidence",
        "fixture",
        "expected",
    }:
        raise EvaluationAuthorityError("membership_facts fields differ")
    case_metadata = value["case_metadata"]
    source_evidence = value["source_evidence"]
    fixture = value["fixture"]
    expected = value["expected"]
    if not all(
        isinstance(item, Mapping)
        for item in (case_metadata, source_evidence, fixture, expected)
    ):
        raise EvaluationAuthorityError("membership_facts values must be objects")
    if set(case_metadata) != {"geography", "language", "urgency"}:
        raise EvaluationAuthorityError("case_metadata fields differ")
    if set(source_evidence) != {"distinct_domain_count"}:
        raise EvaluationAuthorityError("source_evidence fields differ")
    if set(fixture) != {"injected_failure_count"}:
        raise EvaluationAuthorityError("fixture fields differ")
    if set(expected) != {"candidate_outcome", "transition_outcome"}:
        raise EvaluationAuthorityError("expected fields differ")
    domains = source_evidence["distinct_domain_count"]
    failures = fixture["injected_failure_count"]
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in (domains, failures)
    ):
        raise EvaluationAuthorityError(
            "membership counts must be non-negative integers"
        )
    return {
        "case_metadata": {
            "geography": _token(case_metadata["geography"], "geography"),
            "language": _token(case_metadata["language"], "language"),
            "urgency": _token(case_metadata["urgency"], "urgency"),
        },
        "source_evidence": {"distinct_domain_count": domains},
        "fixture": {"injected_failure_count": failures},
        "expected": {
            "candidate_outcome": _token(
                expected["candidate_outcome"], "candidate_outcome"
            ),
            "transition_outcome": _token(
                expected["transition_outcome"], "transition_outcome"
            ),
        },
    }


def _fact(facts: Mapping[str, object], dotted: str) -> object:
    current: object = facts
    for component in dotted.split("."):
        if not isinstance(current, Mapping) or component not in current:
            raise EvaluationAuthorityError("membership rule field is absent")
        current = current[component]
    return current


def _matches(rule: Mapping[str, object], facts: Mapping[str, object]) -> bool:
    actual = _fact(facts, str(rule["field"]))
    if rule["operator"] == "EQ":
        return actual == rule["value"]
    if rule["operator"] == "GTE":
        return (
            isinstance(actual, int)
            and not isinstance(actual, bool)
            and actual >= rule["value"]
        )  # type: ignore[operator]
    raise EvaluationAuthorityError("membership rule operator differs")


def _memberships(
    facts: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    plan = INCREMENT_8_READINESS.evaluation_plan
    slices = tuple(
        sorted(
            str(item["slice_id"])
            for item in plan["required_slice_manifest"]  # type: ignore[union-attr]
            if _matches(item["membership_rule"], facts)  # type: ignore[index]
        )
    )
    strata = tuple(
        sorted(
            str(item["stratum_id"])
            for item in plan["case_strata_manifest"]  # type: ignore[union-attr]
            if _matches(item["membership_rule"], facts)  # type: ignore[index]
        )
    )
    return slices, strata


def _verified_metric_report(
    raw: bytes, run: EvaluationRun
) -> tuple[Mapping[str, object], str, Mapping[str, object]]:
    if not isinstance(raw, bytes):
        raise EvaluationAuthorityError("Metric Report must be canonical bytes")
    from newsroom.increment8.metrics import (
        MetricReportError,
        verify_metric_report_canonical_bytes,
    )

    try:
        report = verify_metric_report_canonical_bytes(raw)
    except MetricReportError as exc:
        raise EvaluationAuthorityError(
            "Metric Report failed canonical reconstruction"
        ) from exc
    if report.run_id != run.run_id or report.payload["run_digest"] != run.digest:
        raise EvaluationAuthorityError("Metric Report Run binding differs")
    document = json.loads(raw.decode("utf-8", errors="strict"))
    zero_document = report.payload["zero_tolerance_evidence"]
    if not isinstance(zero_document, Mapping):
        raise EvaluationAuthorityError("Metric Report zero-tolerance evidence differs")
    zero_payload = zero_document.get("payload")
    if not isinstance(zero_payload, Mapping) or not isinstance(
        zero_payload.get("counts"), Mapping
    ):
        raise EvaluationAuthorityError("Metric Report zero-tolerance evidence differs")
    zero_failure_count = sum(zero_payload["counts"].values())  # type: ignore[arg-type]
    summary_values: dict[str, object] = {
        name: str(report.payload[name])
        for name in (
            "metric_status",
            "performance_status",
            "slice_status",
            "zero_tolerance_status",
            "overall_status",
        )
    }
    summary_values["zero_tolerance_failure_count"] = zero_failure_count
    summary = MappingProxyType(summary_values)
    return MappingProxyType(document), report.digest, summary


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {name: _thaw(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _record(
    schema_version: str, id_field: str, prefix: str, payload: Mapping[str, object]
) -> tuple[str, bytes, str]:
    identity_digest = digest_canonical(
        {"schema_version": schema_version, "payload": payload}
    )
    identifier = f"{prefix}:{identity_digest.removeprefix('sha256:')}"
    document = {
        "schema_version": schema_version,
        id_field: identifier,
        "payload": dict(payload),
    }
    raw = canonical_json_bytes(document)
    return identifier, raw, digest_bytes(raw)


def _decode(
    raw: bytes, schema_version: str, id_field: str
) -> tuple[str, Mapping[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationAuthorityError("record bytes are not canonical JSON") from exc
    if canonical_json_bytes(value) != raw or not isinstance(value, dict):
        raise EvaluationAuthorityError("record bytes are not canonical JSON")
    if (
        set(value) != {"schema_version", id_field, "payload"}
        or value["schema_version"] != schema_version
    ):
        raise EvaluationAuthorityError("record envelope differs")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise EvaluationAuthorityError("record payload must be an object")
    expected_id, expected_raw, _ = _record(
        schema_version, id_field, id_field.removesuffix("_id"), payload
    )
    if value[id_field] != expected_id or raw != expected_raw:
        raise EvaluationAuthorityError("record identity differs")
    return expected_id, MappingProxyType(payload)


@dataclass(frozen=True, slots=True)
class _Record:
    identifier: str
    canonical_bytes: bytes
    digest: str
    payload: Mapping[str, object]

    SCHEMA_VERSION: ClassVar[str]
    ID_FIELD: ClassVar[str]
    PREFIX: ClassVar[str]

    @classmethod
    def build(cls, payload: Mapping[str, object]) -> Self:
        identifier, raw, record_digest = _record(
            cls.SCHEMA_VERSION, cls.ID_FIELD, cls.PREFIX, payload
        )
        return cls(identifier, raw, record_digest, MappingProxyType(dict(payload)))

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        identifier, payload = _decode(raw, cls.SCHEMA_VERSION, cls.ID_FIELD)
        return cls(identifier, raw, digest_bytes(raw), payload)


@dataclass(frozen=True, slots=True)
class EvaluationPlan(_Record):
    SCHEMA_VERSION = "newsroom.increment8.evaluation-plan.v1"
    ID_FIELD = "plan_id"
    PREFIX = "plan"

    @property
    def plan_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class EvaluationEpoch(_Record):
    SCHEMA_VERSION = "newsroom.increment8.evaluation-epoch.v1"
    ID_FIELD = "epoch_id"
    PREFIX = "epoch"

    @property
    def epoch_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class EvaluationRun(_Record):
    SCHEMA_VERSION = "newsroom.increment8.evaluation-run.v1"
    ID_FIELD = "run_id"
    PREFIX = "run"

    @property
    def run_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class EvaluationCase(_Record):
    SCHEMA_VERSION = "newsroom.increment8.evaluation-case.v1"
    ID_FIELD = "case_id"
    PREFIX = "case"

    @property
    def case_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class ReviewLabel(_Record):
    SCHEMA_VERSION = "newsroom.increment8.review-label.v1"
    ID_FIELD = "label_id"
    PREFIX = "label"

    @property
    def label_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class AdjudicationDecision(_Record):
    SCHEMA_VERSION = "newsroom.increment8.adjudication-decision.v1"
    ID_FIELD = "adjudication_id"
    PREFIX = "adjudication"

    @property
    def adjudication_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceDecision(_Record):
    SCHEMA_VERSION = "newsroom.increment8.release-evidence-decision.v1"
    ID_FIELD = "decision_id"
    PREFIX = "decision"

    @property
    def decision_id(self) -> str:
        return self.identifier


def build_evaluation_plan(
    *,
    approved_by_digest: str,
    approved_at: str,
    component_manifest_digest: str,
    authorised_primary_reviewer_digests: Sequence[str],
    authorised_secondary_reviewer_digests: Sequence[str],
    authorised_adjudicator_digests: Sequence[str],
    authorised_release_owner_digests: Sequence[str],
) -> EvaluationPlan:
    human_manifest = _human_authority_manifest(
        primary_reviewers=authorised_primary_reviewer_digests,
        secondary_reviewers=authorised_secondary_reviewer_digests,
        adjudicators=authorised_adjudicator_digests,
        release_owners=authorised_release_owner_digests,
    )
    payload = {
        "readiness_digest": INCREMENT_8_READINESS_DIGEST,
        "plan_definition": _thaw(INCREMENT_8_READINESS.evaluation_plan),
        "component_manifest_digest": _digest(
            component_manifest_digest, "component_manifest_digest"
        ),
        "approved_by_digest": _digest(approved_by_digest, "approved_by_digest"),
        "approved_at": _timestamp(approved_at, "approved_at"),
        "authorised_human_manifest": human_manifest,
        "qualification_allowed": True,
        "calibration_may_qualify_selected_values": False,
        "production_activation_authorised": False,
    }
    return EvaluationPlan.build(payload)


def freeze_epoch(
    *,
    plan: EvaluationPlan,
    target_manifest_digest: str,
    universe_manifest_digest: str,
    sampling_method_digest: str,
    cutoff_at: str,
    opened_at: str,
) -> EvaluationEpoch:
    if not isinstance(plan, EvaluationPlan):
        raise EvaluationAuthorityError("epoch requires a typed plan")
    reparsed = EvaluationPlan.from_canonical_bytes(plan.canonical_bytes)
    if reparsed != plan:
        raise EvaluationAuthorityError("epoch Plan differs")
    _not_after(plan.payload["approved_at"], cutoff_at, boundary="Plan to Epoch cutoff")
    _not_after(cutoff_at, opened_at, boundary="Epoch cutoff to open")
    payload = {
        "plan_id": plan.plan_id,
        "plan_digest": plan.digest,
        "target_manifest_digest": _digest(
            target_manifest_digest, "target_manifest_digest"
        ),
        "universe_manifest_digest": _digest(
            universe_manifest_digest, "universe_manifest_digest"
        ),
        "sampling_method_digest": _digest(
            sampling_method_digest, "sampling_method_digest"
        ),
        "cutoff_at": _timestamp(cutoff_at, "cutoff_at"),
        "opened_at": _timestamp(opened_at, "opened_at"),
        "frozen": True,
    }
    return EvaluationEpoch.build(payload)


def open_run(
    *, epoch: EvaluationEpoch, kind: RunKind, started_at: str
) -> EvaluationRun:
    if not isinstance(epoch, EvaluationEpoch) or not isinstance(kind, RunKind):
        raise EvaluationAuthorityError("run requires typed epoch and kind")
    reparsed = EvaluationEpoch.from_canonical_bytes(epoch.canonical_bytes)
    if reparsed != epoch:
        raise EvaluationAuthorityError("run Epoch differs")
    _not_after(epoch.payload["opened_at"], started_at, boundary="Epoch to Run")
    payload = {
        "epoch_id": epoch.epoch_id,
        "epoch_digest": epoch.digest,
        "plan_id": epoch.payload["plan_id"],
        "run_kind": kind.value,
        "started_at": _timestamp(started_at, "started_at"),
        "production_effect_allowed": False,
    }
    return EvaluationRun.build(payload)


def build_case(
    *,
    run: EvaluationRun,
    input_manifest_digest: str,
    cutoff_at: str,
    membership_facts: Mapping[str, object],
    rights_status: RightsStatus,
    prospective: bool,
    launch_blocker: bool = False,
    urgent: bool = False,
    zero_tolerance: bool = False,
) -> EvaluationCase:
    if not isinstance(run, EvaluationRun) or not isinstance(
        rights_status, RightsStatus
    ):
        raise EvaluationAuthorityError("case requires typed run and rights status")
    if (
        run.payload["run_kind"] == RunKind.QUALIFICATION.value
        and prospective is not True
    ):
        raise EvaluationAuthorityError("qualification Cases must be prospective")
    for name, value in (
        ("prospective", prospective),
        ("launch_blocker", launch_blocker),
        ("urgent", urgent),
        ("zero_tolerance", zero_tolerance),
    ):
        if not isinstance(value, bool):
            raise EvaluationAuthorityError(f"{name} must be boolean")
    facts = _membership_facts(membership_facts)
    if urgent is not (facts["case_metadata"]["urgency"] == "URGENT"):  # type: ignore[index]
        raise EvaluationAuthorityError("urgent flag differs from frozen Case facts")
    slices, strata = _memberships(facts)
    _not_after(run.payload["started_at"], cutoff_at, boundary="Run to Case cutoff")
    payload = {
        "run_id": run.run_id,
        "input_manifest_digest": _digest(
            input_manifest_digest, "input_manifest_digest"
        ),
        "cutoff_at": _timestamp(cutoff_at, "cutoff_at"),
        "membership_facts": facts,
        "required_slices": list(slices),
        "case_strata": list(strata),
        "rights_status": rights_status.value,
        "prospective": prospective,
        "launch_blocker": launch_blocker,
        "urgent": urgent,
        "zero_tolerance": zero_tolerance,
    }
    return EvaluationCase.build(payload)


def build_review_label(
    *,
    case: EvaluationCase,
    reviewer_identity_digest: str,
    role: ReviewRole,
    label: str,
    blinded: bool,
    recorded_at: str,
) -> ReviewLabel:
    if not isinstance(case, EvaluationCase) or not isinstance(role, ReviewRole):
        raise EvaluationAuthorityError("label requires typed Case and review role")
    if case.payload["rights_status"] != RightsStatus.REVIEWABLE.value:
        raise EvaluationAuthorityError("an unreviewable Case cannot be labelled")
    if not isinstance(blinded, bool):
        raise EvaluationAuthorityError("blinded must be boolean")
    _not_after(case.payload["cutoff_at"], recorded_at, boundary="Case to label")
    payload = {
        "case_id": case.case_id,
        "case_digest": case.digest,
        "reviewer_identity_digest": _digest(
            reviewer_identity_digest, "reviewer_identity_digest"
        ),
        "review_role": role.value,
        "label": _token(label, "label"),
        "blinded": blinded,
        "recorded_at": _timestamp(recorded_at, "recorded_at"),
    }
    return ReviewLabel.build(payload)


def build_adjudication(
    *,
    case: EvaluationCase,
    primary: ReviewLabel,
    secondary: ReviewLabel,
    adjudicator_identity_digest: str,
    final_label: str,
    decided_at: str,
) -> AdjudicationDecision:
    if not all(
        isinstance(item, expected)
        for item, expected in (
            (case, EvaluationCase),
            (primary, ReviewLabel),
            (secondary, ReviewLabel),
        )
    ):
        raise EvaluationAuthorityError("adjudication requires typed records")
    if (
        primary.payload["case_id"] != case.case_id
        or secondary.payload["case_id"] != case.case_id
    ):
        raise EvaluationAuthorityError("adjudication labels must belong to the Case")
    if (
        primary.payload["review_role"] != ReviewRole.PRIMARY.value
        or secondary.payload["review_role"] != ReviewRole.SECONDARY.value
    ):
        raise EvaluationAuthorityError(
            "adjudication requires primary and secondary labels"
        )
    if (
        primary.payload["reviewer_identity_digest"]
        == secondary.payload["reviewer_identity_digest"]
    ):
        raise EvaluationAuthorityError("second review must be independent")
    if primary.payload["label"] == secondary.payload["label"]:
        raise EvaluationAuthorityError("agreement does not require adjudication")
    adjudicator = _digest(adjudicator_identity_digest, "adjudicator_identity_digest")
    if adjudicator in {
        primary.payload["reviewer_identity_digest"],
        secondary.payload["reviewer_identity_digest"],
    }:
        raise EvaluationAuthorityError("adjudicator must be independent")
    _not_after(
        primary.payload["recorded_at"], decided_at, boundary="label to adjudication"
    )
    _not_after(
        secondary.payload["recorded_at"], decided_at, boundary="label to adjudication"
    )
    payload = {
        "case_id": case.case_id,
        "primary_label_digest": primary.digest,
        "secondary_label_digest": secondary.digest,
        "adjudicator_identity_digest": adjudicator,
        "final_label": _token(final_label, "final_label"),
        "decided_at": _timestamp(decided_at, "decided_at"),
    }
    return AdjudicationDecision.build(payload)


def build_release_decision(
    *,
    run: EvaluationRun,
    report_canonical_bytes: bytes,
    evidence_manifest_digest: str,
    verdict: ReleaseVerdict,
    owner_identity_digest: str,
    decided_at: str,
    early_stopped: bool = False,
) -> ReleaseEvidenceDecision:
    if not isinstance(run, EvaluationRun) or not isinstance(verdict, ReleaseVerdict):
        raise EvaluationAuthorityError("decision requires typed run and verdict")
    if (
        verdict is ReleaseVerdict.PASS
        and run.payload["run_kind"] != RunKind.QUALIFICATION.value
    ):
        raise EvaluationAuthorityError(
            "PASS differs from the pre-registered release rule"
        )
    if not isinstance(early_stopped, bool):
        raise EvaluationAuthorityError("early_stopped must be boolean")
    report, report_digest, report_summary = _verified_metric_report(
        report_canonical_bytes, run
    )
    report_payload = report["payload"]
    assert isinstance(report_payload, Mapping)
    manifest_digest = _digest(evidence_manifest_digest, "evidence_manifest_digest")
    if (
        report_payload["sampling_manifest_digest"] != manifest_digest
        or report_payload["label_manifest_digest"] != manifest_digest
    ):
        raise EvaluationAuthorityError(
            "Metric Report differs from the authority evidence manifest"
        )
    report_passed = report_summary["overall_status"] == "PASS"
    if verdict is ReleaseVerdict.PASS and (
        run.payload["run_kind"] != RunKind.QUALIFICATION.value
        or early_stopped
        or not report_passed
    ):
        raise EvaluationAuthorityError("PASS differs from the retained Metric Report")
    payload = {
        "run_id": run.run_id,
        "run_digest": run.digest,
        "report_digest": report_digest,
        "metric_report": _thaw(report),
        "evidence_manifest_digest": manifest_digest,
        "verdict": verdict.value,
        "owner_identity_digest": _digest(
            owner_identity_digest, "owner_identity_digest"
        ),
        "decided_at": _timestamp(decided_at, "decided_at"),
        "metrics_passed": report_summary["metric_status"] == "PASS",
        "required_slices_passed": report_summary["slice_status"] == "PASS",
        "zero_tolerance_failure_count": report_summary["zero_tolerance_failure_count"],
        "early_stopped": early_stopped,
        "production_activation_authorised": False,
    }
    return ReleaseEvidenceDecision.build(payload)


class EvaluationAuthority:
    """SQLite-backed append-only authority for Increment 8A records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise EvaluationAuthorityError("connection must be sqlite3.Connection")
        if connection.in_transaction:
            raise EvaluationAuthorityError("caller-owned transaction is active")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise EvaluationAuthorityError("foreign keys must already be active")
        if connection.execute("PRAGMA user_version").fetchone()[0] < 30:
            raise EvaluationAuthorityError("evaluation authority requires schema v30")
        self._connection = connection

    def _require_connection_ready(self) -> None:
        if self._connection.in_transaction:
            raise EvaluationAuthorityError("caller-owned transaction is active")
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise EvaluationAuthorityError("foreign keys must remain active")

    def _write(self, action: Callable[[], None]) -> None:
        self._require_connection_ready()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            action()
            self._connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise EvaluationAuthorityError(
                "evaluation authority rejected the record"
            ) from exc
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _insert(self, sql: str, values: tuple[object, ...]) -> None:
        self._write(lambda: self._connection.execute(sql, values))

    def _plan_for_run(self, run_id: str) -> EvaluationPlan:
        row = self._connection.execute(
            "SELECT p.plan_bytes FROM evaluation_plans p "
            "JOIN evaluation_runs r ON r.plan_id=p.plan_id WHERE r.run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise EvaluationAuthorityError("Run Plan is absent")
        return EvaluationPlan.from_canonical_bytes(bytes(row[0]))

    def _run_for_case(self, case_id: str) -> EvaluationRun:
        row = self._connection.execute(
            "SELECT r.run_bytes FROM evaluation_runs r "
            "JOIN evaluation_cases c ON c.run_id=r.run_id WHERE c.case_id=?",
            (case_id,),
        ).fetchone()
        if row is None:
            raise EvaluationAuthorityError("Case Run is absent")
        return EvaluationRun.from_canonical_bytes(bytes(row[0]))

    def _require_unsealed(self, run_id: str) -> None:
        if (
            self._connection.execute(
                "SELECT 1 FROM evaluation_release_decisions WHERE run_id=?", (run_id,)
            ).fetchone()
            is not None
        ):
            raise EvaluationAuthorityError("Run evidence is sealed by its decision")

    def evidence_manifest_digest(self, run_id: str) -> str:
        self._require_connection_ready()
        return self._evidence_manifest_digest(run_id)

    def _evidence_manifest_digest(self, run_id: str) -> str:
        run_row = self._connection.execute(
            "SELECT run_digest FROM evaluation_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if run_row is None:
            raise EvaluationAuthorityError("Run is absent")
        inventory: dict[str, list[str] | str] = {"run_digest": str(run_row[0])}
        for name, table, digest_column, join in (
            ("case_digests", "evaluation_cases", "case_digest", "run_id=?"),
            (
                "label_digests",
                "evaluation_labels",
                "label_digest",
                "case_id IN (SELECT case_id FROM evaluation_cases WHERE run_id=?)",
            ),
            (
                "adjudication_digests",
                "evaluation_adjudications",
                "adjudication_digest",
                "case_id IN (SELECT case_id FROM evaluation_cases WHERE run_id=?)",
            ),
        ):
            inventory[name] = [
                str(row[0])
                for row in self._connection.execute(
                    f"SELECT {digest_column} FROM {table} WHERE {join} ORDER BY {digest_column}",
                    (run_id,),
                )
            ]
        return digest_canonical(
            {
                "schema_version": "newsroom.increment8.evidence-manifest.v1",
                "inventory": inventory,
            }
        )

    @staticmethod
    def _require_record(
        record: _Record,
        expected_type: type[_Record],
        keys: frozenset[str],
    ) -> None:
        if not isinstance(record, expected_type):
            raise EvaluationAuthorityError("evaluation record has the wrong type")
        if digest_bytes(record.canonical_bytes) != record.digest:
            raise EvaluationAuthorityError("evaluation record digest differs")
        reparsed = expected_type.from_canonical_bytes(record.canonical_bytes)
        if reparsed != record or frozenset(record.payload) != keys:
            raise EvaluationAuthorityError("evaluation record fields differ")

    def register_plan(self, plan: EvaluationPlan) -> None:
        self._require_record(
            plan,
            EvaluationPlan,
            frozenset(
                {
                    "readiness_digest",
                    "plan_definition",
                    "component_manifest_digest",
                    "approved_by_digest",
                    "approved_at",
                    "authorised_human_manifest",
                    "qualification_allowed",
                    "calibration_may_qualify_selected_values",
                    "production_activation_authorised",
                }
            ),
        )
        if plan.payload["readiness_digest"] != INCREMENT_8_READINESS_DIGEST:
            raise EvaluationAuthorityError("plan differs from Increment 8R")
        if plan.payload["plan_definition"] != _thaw(
            INCREMENT_8_READINESS.evaluation_plan
        ):
            raise EvaluationAuthorityError("plan values differ from Increment 8R")
        if (
            plan.payload["qualification_allowed"] is not True
            or plan.payload["calibration_may_qualify_selected_values"] is not False
            or plan.payload["production_activation_authorised"] is not False
        ):
            raise EvaluationAuthorityError("plan authority boundary differs")
        minimum_primary = int(
            INCREMENT_8_READINESS.evaluation_plan[
                "minimum_authorised_primary_reviewers"
            ]
        )
        minimum_adjudicators = int(
            INCREMENT_8_READINESS.evaluation_plan["minimum_authorised_adjudicators"]
        )
        if (
            len(_authorised_identities(plan, HumanAuthorityRole.PRIMARY))
            < minimum_primary
            or len(_authorised_identities(plan, HumanAuthorityRole.ADJUDICATOR))
            < minimum_adjudicators
            or not _authorised_identities(plan, HumanAuthorityRole.SECONDARY)
            or not _authorised_identities(plan, HumanAuthorityRole.RELEASE_OWNER)
        ):
            raise EvaluationAuthorityError("authorised human manifest is insufficient")
        self._insert(
            "INSERT INTO evaluation_plans VALUES(?,?,?,?,?,?,?,?)",
            (
                plan.plan_id,
                plan.canonical_bytes,
                plan.digest,
                plan.payload["readiness_digest"],
                plan.payload["component_manifest_digest"],
                plan.payload["approved_by_digest"],
                plan.payload["approved_at"],
                1,
            ),
        )

    def register_epoch(self, epoch: EvaluationEpoch) -> None:
        self._require_record(
            epoch,
            EvaluationEpoch,
            frozenset(
                {
                    "plan_id",
                    "plan_digest",
                    "target_manifest_digest",
                    "universe_manifest_digest",
                    "sampling_method_digest",
                    "cutoff_at",
                    "opened_at",
                    "frozen",
                }
            ),
        )
        plan = self._connection.execute(
            "SELECT plan_digest,plan_bytes,approved_at FROM evaluation_plans WHERE plan_id=?",
            (epoch.payload["plan_id"],),
        ).fetchone()
        if (
            plan is None
            or plan[0] != epoch.payload["plan_digest"]
            or epoch.payload["frozen"] is not True
        ):
            raise EvaluationAuthorityError("epoch Plan or frozen boundary differs")
        retained_plan = EvaluationPlan.from_canonical_bytes(bytes(plan[1]))
        if retained_plan.digest != plan[0]:
            raise EvaluationAuthorityError("retained Plan identity differs")
        _not_after(plan[2], epoch.payload["cutoff_at"], boundary="Plan to Epoch cutoff")
        _not_after(
            epoch.payload["cutoff_at"],
            epoch.payload["opened_at"],
            boundary="Epoch cutoff to open",
        )
        self._insert(
            "INSERT INTO evaluation_epochs VALUES(?,?,?,?,?,?,?,?)",
            (
                epoch.epoch_id,
                epoch.canonical_bytes,
                epoch.digest,
                epoch.payload["plan_id"],
                epoch.payload["plan_digest"],
                epoch.payload["target_manifest_digest"],
                epoch.payload["universe_manifest_digest"],
                epoch.payload["opened_at"],
            ),
        )

    def register_run(self, run: EvaluationRun) -> None:
        self._require_record(
            run,
            EvaluationRun,
            frozenset(
                {
                    "epoch_id",
                    "epoch_digest",
                    "plan_id",
                    "run_kind",
                    "started_at",
                    "production_effect_allowed",
                }
            ),
        )
        if (
            run.payload["run_kind"] not in {item.value for item in RunKind}
            or run.payload["production_effect_allowed"] is not False
        ):
            raise EvaluationAuthorityError("run authority boundary differs")
        epoch_row = self._connection.execute(
            "SELECT epoch_bytes,epoch_digest,plan_id FROM evaluation_epochs WHERE epoch_id=?",
            (run.payload["epoch_id"],),
        ).fetchone()
        if epoch_row is None:
            raise EvaluationAuthorityError("Run Epoch is absent")
        retained_epoch = EvaluationEpoch.from_canonical_bytes(bytes(epoch_row[0]))
        if (
            retained_epoch.digest != epoch_row[1]
            or retained_epoch.digest != run.payload["epoch_digest"]
            or retained_epoch.payload["plan_id"] != run.payload["plan_id"]
        ):
            raise EvaluationAuthorityError("Run Epoch binding differs")
        _not_after(
            retained_epoch.payload["opened_at"],
            run.payload["started_at"],
            boundary="Epoch to Run",
        )
        self._insert(
            "INSERT INTO evaluation_runs VALUES(?,?,?,?,?,?,?,?)",
            (
                run.run_id,
                run.canonical_bytes,
                run.digest,
                run.payload["epoch_id"],
                run.payload["plan_id"],
                run.payload["epoch_digest"],
                run.payload["run_kind"],
                run.payload["started_at"],
            ),
        )

    def register_case(self, case: EvaluationCase) -> None:
        self._require_record(
            case,
            EvaluationCase,
            frozenset(
                {
                    "run_id",
                    "input_manifest_digest",
                    "membership_facts",
                    "cutoff_at",
                    "required_slices",
                    "case_strata",
                    "rights_status",
                    "prospective",
                    "launch_blocker",
                    "urgent",
                    "zero_tolerance",
                }
            ),
        )
        run = self._connection.execute(
            "SELECT run_kind,run_bytes FROM evaluation_runs WHERE run_id=?",
            (case.payload["run_id"],),
        ).fetchone()
        if run is None:
            raise EvaluationAuthorityError("Case Run is absent")
        if (
            run[0] == RunKind.QUALIFICATION.value
            and case.payload["prospective"] is not True
        ):
            raise EvaluationAuthorityError("qualification Cases must be prospective")
        if case.payload["rights_status"] not in {item.value for item in RightsStatus}:
            raise EvaluationAuthorityError("Case rights status differs")
        retained_run = EvaluationRun.from_canonical_bytes(bytes(run[1]))
        _not_after(
            retained_run.payload["started_at"],
            case.payload["cutoff_at"],
            boundary="Run to Case cutoff",
        )
        facts = _membership_facts(case.payload["membership_facts"])  # type: ignore[arg-type]
        slices, strata = _memberships(facts)
        if (
            tuple(case.payload["required_slices"]) != slices  # type: ignore[arg-type]
            or tuple(case.payload["case_strata"]) != strata  # type: ignore[arg-type]
            or case.payload["urgent"]
            is not (facts["case_metadata"]["urgency"] == "URGENT")  # type: ignore[index]
        ):
            raise EvaluationAuthorityError("Case membership differs from frozen rules")

        def insert_case() -> None:
            self._require_unsealed(str(case.payload["run_id"]))
            duplicate = self._connection.execute(
                "SELECT 1 FROM evaluation_cases WHERE run_id=? AND input_manifest_digest=?",
                (case.payload["run_id"], case.payload["input_manifest_digest"]),
            ).fetchone()
            if duplicate is not None:
                raise EvaluationAuthorityError(
                    "Run input manifests must represent distinct events"
                )
            self._connection.execute(
                "INSERT INTO evaluation_cases VALUES(?,?,?,?,?,?,?,?)",
                (
                    case.case_id,
                    case.canonical_bytes,
                    case.digest,
                    case.payload["run_id"],
                    int(case.payload["prospective"]),
                    case.payload["cutoff_at"],
                    case.payload["input_manifest_digest"],
                    case.payload["rights_status"],
                ),
            )

        self._write(insert_case)

    def record_label(self, label: ReviewLabel) -> None:
        self._require_record(
            label,
            ReviewLabel,
            frozenset(
                {
                    "case_id",
                    "case_digest",
                    "reviewer_identity_digest",
                    "review_role",
                    "label",
                    "blinded",
                    "recorded_at",
                }
            ),
        )
        case = self._connection.execute(
            "SELECT case_digest,rights_status,case_bytes,run_id FROM evaluation_cases WHERE case_id=?",
            (label.payload["case_id"],),
        ).fetchone()
        if case is None or case[0] != label.payload["case_digest"]:
            raise EvaluationAuthorityError("label Case binding differs")
        if case[1] != RightsStatus.REVIEWABLE.value:
            raise EvaluationAuthorityError("an unreviewable Case cannot be labelled")
        if label.payload["review_role"] not in {
            item.value for item in ReviewRole
        } or not isinstance(label.payload["blinded"], bool):
            raise EvaluationAuthorityError("review authority boundary differs")
        retained_case = EvaluationCase.from_canonical_bytes(bytes(case[2]))
        _not_after(
            retained_case.payload["cutoff_at"],
            label.payload["recorded_at"],
            boundary="Case to label",
        )
        plan = self._plan_for_run(str(case[3]))
        required_role = (
            HumanAuthorityRole.PRIMARY
            if label.payload["review_role"] == ReviewRole.PRIMARY.value
            else HumanAuthorityRole.SECONDARY
        )
        if label.payload["reviewer_identity_digest"] not in _authorised_identities(
            plan, required_role
        ):
            raise EvaluationAuthorityError("reviewer is not an authorised human")

        def insert_label() -> None:
            self._require_unsealed(str(case[3]))
            duplicate = self._connection.execute(
                "SELECT reviewer_identity_digest,review_role FROM evaluation_labels WHERE case_id=?",
                (label.payload["case_id"],),
            ).fetchall()
            if any(row[1] == label.payload["review_role"] for row in duplicate):
                raise EvaluationAuthorityError("a Case may retain one label per role")
            if any(
                row[0] == label.payload["reviewer_identity_digest"] for row in duplicate
            ):
                raise EvaluationAuthorityError("second review must be independent")
            self._connection.execute(
                "INSERT INTO evaluation_labels VALUES(?,?,?,?,?,?,?,?)",
                (
                    label.label_id,
                    label.canonical_bytes,
                    label.digest,
                    label.payload["case_id"],
                    label.payload["reviewer_identity_digest"],
                    label.payload["review_role"],
                    int(label.payload["blinded"]),
                    label.payload["recorded_at"],
                ),
            )

        self._write(insert_label)

    def record_adjudication(self, adjudication: AdjudicationDecision) -> None:
        self._require_record(
            adjudication,
            AdjudicationDecision,
            frozenset(
                {
                    "case_id",
                    "primary_label_digest",
                    "secondary_label_digest",
                    "adjudicator_identity_digest",
                    "final_label",
                    "decided_at",
                }
            ),
        )
        labels = self._connection.execute(
            "SELECT label_digest,case_id,reviewer_identity_digest,review_role,label_bytes "
            "FROM evaluation_labels WHERE label_digest IN (?,?)",
            (
                adjudication.payload["primary_label_digest"],
                adjudication.payload["secondary_label_digest"],
            ),
        ).fetchall()
        by_digest = {str(row[0]): row for row in labels}
        try:
            primary = by_digest[str(adjudication.payload["primary_label_digest"])]
            secondary = by_digest[str(adjudication.payload["secondary_label_digest"])]
        except KeyError as exc:
            raise EvaluationAuthorityError("adjudication label is absent") from exc
        if (
            primary[1] != adjudication.payload["case_id"]
            or secondary[1] != adjudication.payload["case_id"]
            or primary[3] != ReviewRole.PRIMARY.value
            or secondary[3] != ReviewRole.SECONDARY.value
            or primary[2] == secondary[2]
            or adjudication.payload["adjudicator_identity_digest"]
            in {primary[2], secondary[2]}
            or ReviewLabel.from_canonical_bytes(bytes(primary[4])).payload["label"]
            == ReviewLabel.from_canonical_bytes(bytes(secondary[4])).payload["label"]
        ):
            raise EvaluationAuthorityError("adjudication authority boundary differs")
        primary_label = ReviewLabel.from_canonical_bytes(bytes(primary[4]))
        secondary_label = ReviewLabel.from_canonical_bytes(bytes(secondary[4]))
        _not_after(
            primary_label.payload["recorded_at"],
            adjudication.payload["decided_at"],
            boundary="label to adjudication",
        )
        _not_after(
            secondary_label.payload["recorded_at"],
            adjudication.payload["decided_at"],
            boundary="label to adjudication",
        )
        run = self._run_for_case(str(adjudication.payload["case_id"]))
        plan = self._plan_for_run(run.run_id)
        if adjudication.payload[
            "adjudicator_identity_digest"
        ] not in _authorised_identities(plan, HumanAuthorityRole.ADJUDICATOR):
            raise EvaluationAuthorityError("adjudicator is not an authorised human")

        def insert_adjudication() -> None:
            self._require_unsealed(run.run_id)
            self._connection.execute(
                "INSERT INTO evaluation_adjudications VALUES(?,?,?,?,?,?,?,?)",
                (
                    adjudication.adjudication_id,
                    adjudication.canonical_bytes,
                    adjudication.digest,
                    adjudication.payload["case_id"],
                    adjudication.payload["primary_label_digest"],
                    adjudication.payload["secondary_label_digest"],
                    adjudication.payload["adjudicator_identity_digest"],
                    adjudication.payload["decided_at"],
                ),
            )

        self._write(insert_adjudication)

    def decide_release(self, decision: ReleaseEvidenceDecision) -> None:
        self._require_record(
            decision,
            ReleaseEvidenceDecision,
            frozenset(
                {
                    "run_id",
                    "run_digest",
                    "report_digest",
                    "metric_report",
                    "evidence_manifest_digest",
                    "verdict",
                    "owner_identity_digest",
                    "decided_at",
                    "metrics_passed",
                    "required_slices_passed",
                    "zero_tolerance_failure_count",
                    "early_stopped",
                    "production_activation_authorised",
                }
            ),
        )
        run = self._connection.execute(
            "SELECT run_kind,run_digest FROM evaluation_runs WHERE run_id=?",
            (decision.payload["run_id"],),
        ).fetchone()
        if run is None or run[1] != decision.payload["run_digest"]:
            raise EvaluationAuthorityError("decision Run binding differs")
        if decision.payload[
            "production_activation_authorised"
        ] is not False or decision.payload["verdict"] not in {
            item.value for item in ReleaseVerdict
        }:
            raise EvaluationAuthorityError("release authority boundary differs")
        retained_run_row = self._connection.execute(
            "SELECT run_bytes FROM evaluation_runs WHERE run_id=?",
            (decision.payload["run_id"],),
        ).fetchone()
        if retained_run_row is None:
            raise EvaluationAuthorityError("decision Run is absent")
        retained_run = EvaluationRun.from_canonical_bytes(bytes(retained_run_row[0]))
        report_raw = canonical_json_bytes(decision.payload["metric_report"])
        report_document, report_digest, report_summary = _verified_metric_report(
            report_raw, retained_run
        )
        if report_digest != decision.payload["report_digest"]:
            raise EvaluationAuthorityError("decision Metric Report digest differs")
        if (
            decision.payload["metrics_passed"]
            is not (report_summary["metric_status"] == "PASS")
            or decision.payload["required_slices_passed"]
            is not (report_summary["slice_status"] == "PASS")
            or decision.payload["zero_tolerance_failure_count"]
            != report_summary["zero_tolerance_failure_count"]
        ):
            raise EvaluationAuthorityError(
                "decision gates differ from the retained Metric Report"
            )
        current_manifest = self.evidence_manifest_digest(retained_run.run_id)
        if current_manifest != decision.payload["evidence_manifest_digest"]:
            raise EvaluationAuthorityError("decision evidence manifest differs")
        report_payload = report_document["payload"]
        if not isinstance(report_payload, Mapping) or any(
            report_payload[field] != current_manifest
            for field in ("sampling_manifest_digest", "label_manifest_digest")
        ):
            raise EvaluationAuthorityError(
                "Metric Report differs from the authority evidence manifest"
            )
        self._require_report_evidence_identity(retained_run.run_id, report_payload)
        plan = self._plan_for_run(retained_run.run_id)
        if decision.payload["owner_identity_digest"] not in _authorised_identities(
            plan, HumanAuthorityRole.RELEASE_OWNER
        ):
            raise EvaluationAuthorityError("release owner is not an authorised human")
        latest_evidence_at = self._latest_evidence_at(retained_run.run_id)
        _not_after(
            latest_evidence_at,
            decision.payload["decided_at"],
            boundary="evidence to release decision",
        )
        if decision.payload["verdict"] == ReleaseVerdict.PASS.value:
            if (
                run[0] != RunKind.QUALIFICATION.value
                or report_summary["overall_status"] != "PASS"
                or report_summary["metric_status"] != "PASS"
                or report_summary["slice_status"] != "PASS"
                or report_summary["zero_tolerance_status"] != "PASS"
                or decision.payload["early_stopped"] is not False
            ):
                raise EvaluationAuthorityError(
                    "PASS differs from the pre-registered release rule"
                )
            self._require_pass_exposure(
                str(decision.payload["run_id"]),
                report_document["payload"],  # type: ignore[arg-type]
            )
            if not corrective_gate_authorised(
                CorrectiveGate.QUALIFICATION_EVIDENCE_ACCEPTANCE
            ):
                raise EvaluationAuthorityError(
                    "qualification evidence acceptance is blocked by corrective readiness"
                )

        def insert_decision() -> None:
            if (
                self._evidence_manifest_digest(retained_run.run_id)
                != decision.payload["evidence_manifest_digest"]
            ):
                raise EvaluationAuthorityError(
                    "decision evidence changed before sealing"
                )
            self._connection.execute(
                "INSERT INTO evaluation_release_decisions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    decision.decision_id,
                    decision.canonical_bytes,
                    decision.digest,
                    decision.payload["run_id"],
                    decision.payload["report_digest"],
                    decision.payload["verdict"],
                    decision.payload["owner_identity_digest"],
                    decision.payload["decided_at"],
                    int(decision.payload["early_stopped"]),
                    0,
                ),
            )

        self._write(insert_decision)

    def _latest_evidence_at(self, run_id: str) -> str:
        values = [
            str(row[0])
            for query in (
                "SELECT started_at FROM evaluation_runs WHERE run_id=?",
                "SELECT cutoff_at FROM evaluation_cases WHERE run_id=?",
                "SELECT recorded_at FROM evaluation_labels WHERE case_id IN "
                "(SELECT case_id FROM evaluation_cases WHERE run_id=?)",
                "SELECT decided_at FROM evaluation_adjudications WHERE case_id IN "
                "(SELECT case_id FROM evaluation_cases WHERE run_id=?)",
            )
            for row in self._connection.execute(query, (run_id,))
        ]
        if not values:
            raise EvaluationAuthorityError("release evidence inventory is empty")
        return max(
            values, key=lambda item: _parse_timestamp(item, "evidence timestamp")
        )

    def _require_report_evidence_identity(
        self, run_id: str, report_payload: Mapping[str, object]
    ) -> None:
        evidence = report_payload.get("reviewed_case_outcome_evidence")
        if not isinstance(evidence, list):
            raise EvaluationAuthorityError(
                "Metric Report reviewed Case evidence differs"
            )
        reported: dict[str, tuple[str, str, str | None]] = {}
        for document in evidence:
            if not isinstance(document, Mapping) or not isinstance(
                document.get("payload"), Mapping
            ):
                raise EvaluationAuthorityError(
                    "Metric Report reviewed Case evidence differs"
                )
            outcome = document["payload"]
            case_id = str(outcome.get("case_id"))
            secondary = outcome.get("secondary_review_label_digest")
            if (
                case_id in reported
                or secondary is not None
                and not isinstance(secondary, str)
            ):
                raise EvaluationAuthorityError(
                    "Metric Report reviewed Case evidence differs"
                )
            reported[case_id] = (
                str(outcome.get("case_digest")),
                str(outcome.get("review_label_digest")),
                secondary,
            )
        retained: dict[str, tuple[str, str, str | None]] = {}
        rows = self._connection.execute(
            "SELECT c.case_id,c.case_digest,p.label_digest,"
            "(SELECT s.label_digest FROM evaluation_labels s "
            "WHERE s.case_id=c.case_id AND s.review_role='SECONDARY') "
            "FROM evaluation_cases c JOIN evaluation_labels p ON p.case_id=c.case_id "
            "WHERE c.run_id=? AND p.review_role='PRIMARY' ORDER BY c.case_id",
            (run_id,),
        ).fetchall()
        for case_id, case_digest, primary_digest, secondary_digest in rows:
            retained[str(case_id)] = (
                str(case_digest),
                str(primary_digest),
                None if secondary_digest is None else str(secondary_digest),
            )
        if reported != retained:
            raise EvaluationAuthorityError(
                "Metric Report outcomes differ from retained reviews"
            )

    def _require_pass_exposure(
        self, run_id: str, report_payload: Mapping[str, object]
    ) -> None:
        rows = self._connection.execute(
            "SELECT case_id,case_bytes,case_digest,rights_status,input_manifest_digest "
            "FROM evaluation_cases WHERE run_id=? ORDER BY case_id",
            (run_id,),
        ).fetchall()
        exposure = INCREMENT_8_READINESS.evaluation_plan["qualification_exposure"]
        minimum = int(exposure["minimum_completed_cases"])  # type: ignore[index]
        if len(rows) < minimum:
            raise EvaluationAuthorityError("qualification exposure is insufficient")

        slice_manifest = {
            str(item["slice_id"]): int(item["minimum_completed_cases"])
            for item in INCREMENT_8_READINESS.evaluation_plan["required_slice_manifest"]  # type: ignore[union-attr]
        }
        stratum_manifest = {
            str(item["stratum_id"]): int(item["minimum_completed_cases"])
            for item in INCREMENT_8_READINESS.evaluation_plan["case_strata_manifest"]  # type: ignore[union-attr]
        }
        slice_cases: dict[str, set[str]] = {name: set() for name in slice_manifest}
        stratum_cases: dict[str, set[str]] = {name: set() for name in stratum_manifest}
        required_secondary: set[str] = set()
        reviewable: set[str] = set()
        input_manifests: set[str] = set()
        case_memberships: dict[
            str, tuple[str, tuple[str, ...], tuple[str, ...], bool]
        ] = {}
        for case_id, raw, case_digest, rights_status, input_manifest_digest in rows:
            case = EvaluationCase.from_canonical_bytes(bytes(raw))
            facts = _membership_facts(case.payload["membership_facts"])  # type: ignore[arg-type]
            expected_slices, expected_strata = _memberships(facts)
            if (
                case.case_id != case_id
                or case.digest != case_digest
                or case.payload["run_id"] != run_id
                or case.payload["rights_status"] != rights_status
                or case.payload["input_manifest_digest"] != input_manifest_digest
                or tuple(case.payload["required_slices"]) != expected_slices  # type: ignore[arg-type]
                or tuple(case.payload["case_strata"]) != expected_strata  # type: ignore[arg-type]
                or case.payload["urgent"]
                is not (facts["case_metadata"]["urgency"] == "URGENT")  # type: ignore[index]
            ):
                raise EvaluationAuthorityError("retained Case identity differs")
            if input_manifest_digest in input_manifests:
                raise EvaluationAuthorityError(
                    "qualification exposure repeats an event manifest"
                )
            input_manifests.add(str(input_manifest_digest))
            case_memberships[str(case_id)] = (
                str(case_digest),
                expected_slices,
                expected_strata,
                bool(case.payload["zero_tolerance"]),
            )
            for slice_name in expected_slices:
                slice_cases[slice_name].add(str(case_digest))
            for stratum_name in expected_strata:
                stratum_cases[stratum_name].add(str(case_digest))
            if rights_status == RightsStatus.REVIEWABLE.value:
                reviewable.add(str(case_id))
            if any(
                bool(case.payload[name])
                for name in ("launch_blocker", "urgent", "zero_tolerance")
            ):
                required_secondary.add(str(case_id))

        if any(
            len(slice_cases[name]) < minimum_cases
            for name, minimum_cases in slice_manifest.items()
        ):
            raise EvaluationAuthorityError("required-slice exposure is insufficient")
        stratum_exposure = exposure
        expected_stratum_minima = {
            "NEGATIVE": int(stratum_exposure["minimum_negative_cases"]),  # type: ignore[index]
            "UNCHANGED": int(stratum_exposure["minimum_no_change_cases"]),  # type: ignore[index]
            "FAILURE_HEAVY": int(
                stratum_exposure["minimum_failure_heavy_cases"]  # type: ignore[index]
            ),
        }
        if expected_stratum_minima != stratum_manifest or any(
            len(stratum_cases[name]) < minimum_cases
            for name, minimum_cases in stratum_manifest.items()
        ):
            raise EvaluationAuthorityError("Case-stratum exposure is insufficient")
        if not reviewable:
            raise EvaluationAuthorityError("reviewable exposure is empty")

        labels = self._connection.execute(
            "SELECT case_id,label_bytes,review_role FROM evaluation_labels "
            "WHERE case_id IN (SELECT case_id FROM evaluation_cases WHERE run_id=?)",
            (run_id,),
        ).fetchall()
        primary: dict[str, ReviewLabel] = {}
        secondary: dict[str, ReviewLabel] = {}
        for case_id, raw, role in labels:
            label = ReviewLabel.from_canonical_bytes(bytes(raw))
            if label.payload["case_id"] != case_id or role not in {
                ReviewRole.PRIMARY.value,
                ReviewRole.SECONDARY.value,
            }:
                raise EvaluationAuthorityError("retained label identity differs")
            target = primary if role == ReviewRole.PRIMARY.value else secondary
            if str(case_id) in target:
                raise EvaluationAuthorityError("duplicate same-role label is retained")
            target[str(case_id)] = label
        if set(primary) != reviewable:
            raise EvaluationAuthorityError("primary review exposure is incomplete")
        if len(primary) < minimum:
            raise EvaluationAuthorityError(
                "reviewed qualification exposure is insufficient"
            )
        outcome_evidence = report_payload.get("reviewed_case_outcome_evidence")
        if not isinstance(outcome_evidence, list):
            raise EvaluationAuthorityError(
                "Metric Report reviewed Case evidence differs"
            )
        reported_outcomes: dict[str, tuple[str, str]] = {}
        for document in outcome_evidence:
            if not isinstance(document, Mapping) or not isinstance(
                document.get("payload"), Mapping
            ):
                raise EvaluationAuthorityError(
                    "Metric Report reviewed Case evidence differs"
                )
            outcome = document["payload"]
            case_id = str(outcome.get("case_id"))
            if case_id in reported_outcomes:
                raise EvaluationAuthorityError(
                    "Metric Report repeats reviewed Case evidence"
                )
            reported_outcomes[case_id] = (
                str(outcome.get("case_digest")),
                str(outcome.get("review_label_digest")),
            )
        if reported_outcomes != {
            case_id: (
                case_memberships[case_id][0],
                label.digest,
            )
            for case_id, label in primary.items()
        }:
            raise EvaluationAuthorityError(
                "Metric Report outcomes differ from retained reviews"
            )
        reviewed_slice_cases: dict[str, set[str]] = {
            name: set() for name in slice_manifest
        }
        reviewed_stratum_cases: dict[str, set[str]] = {
            name: set() for name in stratum_manifest
        }
        for case_id in primary:
            case_digest, slices, strata, _ = case_memberships[case_id]
            for name in slices:
                reviewed_slice_cases[name].add(case_digest)
            for name in strata:
                reviewed_stratum_cases[name].add(case_digest)
        if any(
            len(reviewed_slice_cases[name]) < minimum_cases
            for name, minimum_cases in slice_manifest.items()
        ):
            raise EvaluationAuthorityError(
                "reviewed required-slice exposure is insufficient"
            )
        if any(
            len(reviewed_stratum_cases[name]) < minimum_cases
            for name, minimum_cases in stratum_manifest.items()
        ):
            raise EvaluationAuthorityError(
                "reviewed Case-stratum exposure is insufficient"
            )
        if report_payload.get("case_count") != len(primary):
            raise EvaluationAuthorityError(
                "Metric Report Case count differs from reviewed evidence"
            )
        slice_evidence = report_payload.get("required_slice_evidence")
        if not isinstance(slice_evidence, list):
            raise EvaluationAuthorityError("Metric Report slice evidence differs")
        reported_slice_counts: dict[str, int] = {}
        for document in slice_evidence:
            if not isinstance(document, Mapping) or not isinstance(
                document.get("payload"), Mapping
            ):
                raise EvaluationAuthorityError("Metric Report slice evidence differs")
            payload = document["payload"]
            reported_slice_counts[str(payload["slice_id"])] = int(
                payload["completed_cases"]
            )
        if reported_slice_counts != {
            name: len(cases) for name, cases in reviewed_slice_cases.items()
        }:
            raise EvaluationAuthorityError(
                "Metric Report slices differ from reviewed evidence"
            )
        zero_document = report_payload.get("zero_tolerance_evidence")
        if not isinstance(zero_document, Mapping) or not isinstance(
            zero_document.get("payload"), Mapping
        ):
            raise EvaluationAuthorityError(
                "Metric Report zero-tolerance evidence differs"
            )
        zero_payload = zero_document["payload"]
        counts = zero_payload.get("counts")
        if not isinstance(counts, Mapping) or sum(counts.values()) != sum(  # type: ignore[arg-type]
            int(case_memberships[case_id][3]) for case_id in primary
        ):
            raise EvaluationAuthorityError(
                "Metric Report zero-tolerance count differs from reviewed evidence"
            )

        second_percent = int(
            INCREMENT_8_READINESS.evaluation_plan[
                "ordinary_independent_second_review_percent"
            ]
        )
        ordinary = reviewable - required_secondary
        ordinary_secondary = ordinary.intersection(secondary)
        ordinary_minimum = (len(ordinary) * second_percent + 99) // 100
        if len(ordinary_secondary) < ordinary_minimum or not required_secondary <= set(
            secondary
        ):
            raise EvaluationAuthorityError(
                "independent second-review exposure is incomplete"
            )
        plan = self._plan_for_run(run_id)
        used_primary = {
            str(item.payload["reviewer_identity_digest"]) for item in primary.values()
        }
        minimum_primary = int(
            INCREMENT_8_READINESS.evaluation_plan[
                "minimum_authorised_primary_reviewers"
            ]
        )
        if (
            len(used_primary) < minimum_primary
            or not used_primary
            <= _authorised_identities(plan, HumanAuthorityRole.PRIMARY)
            or any(
                item.payload["reviewer_identity_digest"]
                not in _authorised_identities(plan, HumanAuthorityRole.SECONDARY)
                for item in secondary.values()
            )
        ):
            raise EvaluationAuthorityError(
                "authorised reviewer exposure is insufficient"
            )
        adjudicated = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT case_id FROM evaluation_adjudications WHERE case_id IN "
                "(SELECT case_id FROM evaluation_cases WHERE run_id=?)",
                (run_id,),
            )
        }
        disagreements = {
            case_id
            for case_id in set(primary).intersection(secondary)
            if primary[case_id].payload["label"] != secondary[case_id].payload["label"]
        }
        if not disagreements <= adjudicated:
            raise EvaluationAuthorityError("reviewer disagreement is unresolved")

    def read_record(self, table: str, identity_column: str, identifier: str) -> bytes:
        allowed = {
            "evaluation_plans": ("plan_id", "plan_bytes"),
            "evaluation_epochs": ("epoch_id", "epoch_bytes"),
            "evaluation_runs": ("run_id", "run_bytes"),
            "evaluation_cases": ("case_id", "case_bytes"),
            "evaluation_labels": ("label_id", "label_bytes"),
            "evaluation_adjudications": ("adjudication_id", "adjudication_bytes"),
            "evaluation_release_decisions": ("decision_id", "decision_bytes"),
        }
        if table not in allowed or allowed[table][0] != identity_column:
            raise EvaluationAuthorityError("read surface is not allow-listed")
        row = self._connection.execute(
            f"SELECT {allowed[table][1]} FROM {table} WHERE {identity_column}=?",
            (_token(identifier, "identifier"),),
        ).fetchone()
        if row is None:
            raise EvaluationAuthorityError("evaluation record is absent")
        return bytes(row[0])


__all__ = [
    "AdjudicationDecision",
    "EvaluationAuthority",
    "EvaluationAuthorityError",
    "EvaluationCase",
    "EvaluationEpoch",
    "EvaluationPlan",
    "EvaluationRun",
    "HumanAuthorityRole",
    "ReleaseEvidenceDecision",
    "ReleaseVerdict",
    "ReviewLabel",
    "ReviewRole",
    "RightsStatus",
    "RunKind",
    "build_adjudication",
    "build_case",
    "build_evaluation_plan",
    "build_release_decision",
    "build_review_label",
    "freeze_epoch",
    "open_run",
]
