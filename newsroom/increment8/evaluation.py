"""Immutable Increment 8 evaluation and release-evidence authority.

The API retains pre-registered fixture qualification records.  It cannot start
shadow or production work and every decision explicitly records no activation.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
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
    *, approved_by_digest: str, approved_at: str, component_manifest_digest: str
) -> EvaluationPlan:
    payload = {
        "readiness_digest": INCREMENT_8_READINESS_DIGEST,
        "plan_definition": _thaw(INCREMENT_8_READINESS.evaluation_plan),
        "component_manifest_digest": _digest(
            component_manifest_digest, "component_manifest_digest"
        ),
        "approved_by_digest": _digest(approved_by_digest, "approved_by_digest"),
        "approved_at": _timestamp(approved_at, "approved_at"),
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
    required_slices: Sequence[str],
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
    payload = {
        "run_id": run.run_id,
        "input_manifest_digest": _digest(
            input_manifest_digest, "input_manifest_digest"
        ),
        "cutoff_at": _timestamp(cutoff_at, "cutoff_at"),
        "required_slices": list(_strings(required_slices, "required_slices")),
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
    report_digest: str,
    verdict: ReleaseVerdict,
    owner_identity_digest: str,
    decided_at: str,
    metrics_passed: bool,
    required_slices_passed: bool,
    zero_tolerance_failure_count: int,
    early_stopped: bool = False,
) -> ReleaseEvidenceDecision:
    if not isinstance(run, EvaluationRun) or not isinstance(verdict, ReleaseVerdict):
        raise EvaluationAuthorityError("decision requires typed run and verdict")
    if (
        isinstance(zero_tolerance_failure_count, bool)
        or not isinstance(zero_tolerance_failure_count, int)
        or zero_tolerance_failure_count < 0
    ):
        raise EvaluationAuthorityError(
            "zero_tolerance_failure_count must be non-negative"
        )
    if not all(
        isinstance(value, bool)
        for value in (metrics_passed, required_slices_passed, early_stopped)
    ):
        raise EvaluationAuthorityError("decision gates must be boolean")
    if verdict is ReleaseVerdict.PASS and (
        run.payload["run_kind"] != RunKind.QUALIFICATION.value
        or early_stopped
        or not metrics_passed
        or not required_slices_passed
        or zero_tolerance_failure_count != 0
    ):
        raise EvaluationAuthorityError(
            "PASS differs from the pre-registered release rule"
        )
    payload = {
        "run_id": run.run_id,
        "run_digest": run.digest,
        "report_digest": _digest(report_digest, "report_digest"),
        "verdict": verdict.value,
        "owner_identity_digest": _digest(
            owner_identity_digest, "owner_identity_digest"
        ),
        "decided_at": _timestamp(decided_at, "decided_at"),
        "metrics_passed": metrics_passed,
        "required_slices_passed": required_slices_passed,
        "zero_tolerance_failure_count": zero_tolerance_failure_count,
        "early_stopped": early_stopped,
        "production_activation_authorised": False,
    }
    return ReleaseEvidenceDecision.build(payload)


class EvaluationAuthority:
    """SQLite-backed append-only authority for Increment 8A records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise EvaluationAuthorityError("connection must be sqlite3.Connection")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA user_version").fetchone()[0] < 30:
            raise EvaluationAuthorityError("evaluation authority requires schema v30")
        self._connection = connection

    def _insert(self, sql: str, values: tuple[object, ...]) -> None:
        try:
            with self._connection:
                self._connection.execute(sql, values)
        except sqlite3.IntegrityError as exc:
            raise EvaluationAuthorityError(
                "evaluation authority rejected the record"
            ) from exc

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
            "SELECT plan_digest FROM evaluation_plans WHERE plan_id=?",
            (epoch.payload["plan_id"],),
        ).fetchone()
        if (
            plan is None
            or plan[0] != epoch.payload["plan_digest"]
            or epoch.payload["frozen"] is not True
        ):
            raise EvaluationAuthorityError("epoch Plan or frozen boundary differs")
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
                    "cutoff_at",
                    "required_slices",
                    "rights_status",
                    "prospective",
                    "launch_blocker",
                    "urgent",
                    "zero_tolerance",
                }
            ),
        )
        run = self._connection.execute(
            "SELECT run_kind FROM evaluation_runs WHERE run_id=?",
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
        self._insert(
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
            "SELECT case_digest,rights_status FROM evaluation_cases WHERE case_id=?",
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
        duplicate = self._connection.execute(
            "SELECT 1 FROM evaluation_labels WHERE case_id=? AND reviewer_identity_digest=?",
            (label.payload["case_id"], label.payload["reviewer_identity_digest"]),
        ).fetchone()
        if duplicate is not None:
            raise EvaluationAuthorityError("second review must be independent")
        self._insert(
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
        self._insert(
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

    def decide_release(self, decision: ReleaseEvidenceDecision) -> None:
        self._require_record(
            decision,
            ReleaseEvidenceDecision,
            frozenset(
                {
                    "run_id",
                    "run_digest",
                    "report_digest",
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
        if decision.payload["verdict"] == ReleaseVerdict.PASS.value:
            if (
                run[0] != RunKind.QUALIFICATION.value
                or decision.payload["metrics_passed"] is not True
                or decision.payload["required_slices_passed"] is not True
                or decision.payload["zero_tolerance_failure_count"] != 0
                or decision.payload["early_stopped"] is not False
            ):
                raise EvaluationAuthorityError(
                    "PASS differs from the pre-registered release rule"
                )
            self._require_pass_exposure(str(decision.payload["run_id"]))
        self._insert(
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

    def _require_pass_exposure(self, run_id: str) -> None:
        rows = self._connection.execute(
            "SELECT case_id,case_bytes,rights_status FROM evaluation_cases WHERE run_id=? ORDER BY case_id",
            (run_id,),
        ).fetchall()
        exposure = INCREMENT_8_READINESS.evaluation_plan["qualification_exposure"]
        minimum = int(exposure["minimum_completed_cases"])  # type: ignore[index]
        if len(rows) < minimum:
            raise EvaluationAuthorityError("qualification exposure is insufficient")

        slice_counts: dict[str, int] = {}
        required_secondary: set[str] = set()
        reviewable: set[str] = set()
        for case_id, raw, rights_status in rows:
            case = EvaluationCase.from_canonical_bytes(bytes(raw))
            if case.case_id != case_id or case.payload["run_id"] != run_id:
                raise EvaluationAuthorityError("retained Case identity differs")
            for slice_name in case.payload["required_slices"]:  # type: ignore[union-attr]
                slice_counts[str(slice_name)] = slice_counts.get(str(slice_name), 0) + 1
            if rights_status == RightsStatus.REVIEWABLE.value:
                reviewable.add(str(case_id))
            if any(
                bool(case.payload[name])
                for name in ("launch_blocker", "urgent", "zero_tolerance")
            ):
                required_secondary.add(str(case_id))

        minimum_slices = int(exposure["minimum_completed_required_slices"])  # type: ignore[index]
        minimum_per_slice = int(
            INCREMENT_8_READINESS.evaluation_plan["required_slice_minimum_cases"]
        )
        if len(slice_counts) < minimum_slices or any(
            count < minimum_per_slice for count in slice_counts.values()
        ):
            raise EvaluationAuthorityError("required-slice exposure is insufficient")

        labels = self._connection.execute(
            "SELECT case_id,label_bytes,review_role FROM evaluation_labels "
            "WHERE case_id IN (SELECT case_id FROM evaluation_cases WHERE run_id=?)",
            (run_id,),
        ).fetchall()
        primary: dict[str, ReviewLabel] = {}
        secondary: dict[str, ReviewLabel] = {}
        for case_id, raw, role in labels:
            label = ReviewLabel.from_canonical_bytes(bytes(raw))
            if label.payload["case_id"] != case_id:
                raise EvaluationAuthorityError("retained label identity differs")
            target = primary if role == ReviewRole.PRIMARY.value else secondary
            target[str(case_id)] = label
        if set(primary) != reviewable:
            raise EvaluationAuthorityError("primary review exposure is incomplete")

        second_percent = int(
            INCREMENT_8_READINESS.evaluation_plan[
                "ordinary_independent_second_review_percent"
            ]
        )
        ordinary_minimum = (len(reviewable) * second_percent + 99) // 100
        if len(secondary) < ordinary_minimum or not required_secondary <= set(
            secondary
        ):
            raise EvaluationAuthorityError(
                "independent second-review exposure is incomplete"
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
