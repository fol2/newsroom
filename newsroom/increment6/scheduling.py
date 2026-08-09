"""Pure urgency, deadline, reserved-capacity and starvation policy.

The module calculates an inspectable scheduling order from exact caller-supplied
UTC observations.  It owns no queue, clock, Work Item state, authority read or
effect.  Priority can order only explicitly current and eligible work; it cannot
turn stale, closed, blocked or dependency-bound work into schedulable work.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.increment6.outcomes import PriorityLane, PrioritySelection


SCHEDULING_POLICY_SCHEMA_VERSION = (
    "newsroom.increment6.triage-scheduling-policy.v1"
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_ZONE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-/]{0,255}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LOCAL_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
_UTC_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_TIE_BREAK = "WORK_ITEM_VERSION_ID_ASC"


class SchedulingContractError(ValueError):
    """A scheduling policy, input, observation or decision is malformed."""


def _require_token(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise SchedulingContractError(f"{field} must be a bounded canonical token")
    return value


def _require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise SchedulingContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _require_non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SchedulingContractError(f"{field} must be a non-negative integer")
    return value


def _require_positive_int(value: object, *, field: str) -> int:
    result = _require_non_negative_int(value, field=field)
    if result == 0:
        raise SchedulingContractError(f"{field} must be positive")
    return result


def _parse_utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise SchedulingContractError(f"{field} must be canonical UTC")
    try:
        parsed = datetime.strptime(value, _UTC_TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise SchedulingContractError(f"{field} must be canonical UTC") from exc
    if parsed.strftime(_UTC_TIME_FORMAT) != value:
        raise SchedulingContractError(f"{field} must be canonical UTC")
    return parsed


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime(_UTC_TIME_FORMAT)


def _strict_keys(
    value: Mapping[str, object], *, required: set[str], field: str
) -> None:
    if set(value) != required:
        raise SchedulingContractError(f"{field} keys are not exact")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if name in value:
            raise SchedulingContractError(f"duplicate JSON key: {name}")
        value[name] = item
    return value


def _decode_canonical_object(raw: bytes, *, field: str) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw:
        raise SchedulingContractError(f"{field} bytes are required")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchedulingContractError(f"{field} is not JSON") from exc
    if not isinstance(value, dict):
        raise SchedulingContractError(f"{field} must be an object")
    try:
        canonical = canonical_json_bytes(value)
    except CanonicalizationError as exc:
        raise SchedulingContractError(f"{field} is not canonical JSON") from exc
    if canonical != raw:
        raise SchedulingContractError(f"{field} is not canonical JSON")
    return value


class DeadlineKind(StrEnum):
    HARD_ACTION = "HARD_ACTION"
    LEGAL_OR_REGULATORY = "LEGAL_OR_REGULATORY"
    PLANNED_WINDOW_END = "PLANNED_WINDOW_END"
    WATCH_REVIEW = "WATCH_REVIEW"


@dataclass(frozen=True, slots=True)
class DeadlineBoundary:
    """One exact local-time boundary resolved to one canonical UTC instant."""

    kind: DeadlineKind
    due_at: str
    source_time_zone: str
    source_local_time: str
    source_utc_offset_minutes: int
    source_fold: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DeadlineKind):
            raise SchedulingContractError("deadline kind must be typed")
        due = _parse_utc(self.due_at, field="deadline_due_at")
        if (
            not isinstance(self.source_time_zone, str)
            or _ZONE_RE.fullmatch(self.source_time_zone) is None
        ):
            raise SchedulingContractError(
                "deadline source time zone must be a canonical IANA name"
            )
        try:
            zone = ZoneInfo(self.source_time_zone)
        except ZoneInfoNotFoundError as exc:
            raise SchedulingContractError(
                "deadline source time zone is not available"
            ) from exc
        try:
            local = datetime.strptime(self.source_local_time, _LOCAL_TIME_FORMAT)
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError(
                "deadline source local time is not canonical"
            ) from exc
        if local.strftime(_LOCAL_TIME_FORMAT) != self.source_local_time:
            raise SchedulingContractError(
                "deadline source local time is not canonical"
            )
        if self.source_fold not in (0, 1) or isinstance(self.source_fold, bool):
            raise SchedulingContractError("deadline fold must be zero or one")
        if (
            isinstance(self.source_utc_offset_minutes, bool)
            or not isinstance(self.source_utc_offset_minutes, int)
            or not -24 * 60 < self.source_utc_offset_minutes < 24 * 60
        ):
            raise SchedulingContractError("deadline UTC offset is invalid")
        aware = local.replace(tzinfo=zone, fold=self.source_fold)
        offset = aware.utcoffset()
        if offset is None or offset.total_seconds() % 60 != 0:
            raise SchedulingContractError("deadline UTC offset cannot be resolved")
        if int(offset.total_seconds() // 60) != self.source_utc_offset_minutes:
            raise SchedulingContractError("deadline UTC offset differs")
        if aware.astimezone(UTC) != due:
            raise SchedulingContractError("deadline UTC and local boundary differ")
        round_trip = due.astimezone(zone)
        if (
            round_trip.strftime(_LOCAL_TIME_FORMAT) != self.source_local_time
            or round_trip.fold != self.source_fold
        ):
            raise SchedulingContractError(
                "deadline local boundary is ambiguous or nonexistent"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "due_at": self.due_at,
            "source_time_zone": self.source_time_zone,
            "source_local_time": self.source_local_time,
            "source_utc_offset_minutes": self.source_utc_offset_minutes,
            "source_fold": self.source_fold,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "DeadlineBoundary":
        _strict_keys(
            value,
            required={
                "kind",
                "due_at",
                "source_time_zone",
                "source_local_time",
                "source_utc_offset_minutes",
                "source_fold",
            },
            field="deadline_boundary",
        )
        try:
            return cls(
                kind=DeadlineKind(value["kind"]),
                due_at=value["due_at"],  # type: ignore[arg-type]
                source_time_zone=value["source_time_zone"],  # type: ignore[arg-type]
                source_local_time=value["source_local_time"],  # type: ignore[arg-type]
                source_utc_offset_minutes=value["source_utc_offset_minutes"],  # type: ignore[arg-type]
                source_fold=value["source_fold"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError("deadline boundary is malformed") from exc


@dataclass(frozen=True, slots=True)
class LaneTimingRule:
    lane: PriorityLane
    starvation_warning_seconds: int
    starvation_limit_seconds: int
    explicit_deadline_required: bool

    def __post_init__(self) -> None:
        if not isinstance(self.lane, PriorityLane):
            raise SchedulingContractError("lane timing rule lane must be typed")
        warning = _require_positive_int(
            self.starvation_warning_seconds,
            field="starvation_warning_seconds",
        )
        limit = _require_positive_int(
            self.starvation_limit_seconds,
            field="starvation_limit_seconds",
        )
        if warning >= limit:
            raise SchedulingContractError(
                "starvation warning must precede the starvation limit"
            )
        if type(self.explicit_deadline_required) is not bool:
            raise SchedulingContractError(
                "explicit deadline requirement must be boolean"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "lane": self.lane.value,
            "lane_ordinal": self.lane.ordinal,
            "starvation_warning_seconds": self.starvation_warning_seconds,
            "starvation_limit_seconds": self.starvation_limit_seconds,
            "explicit_deadline_required": self.explicit_deadline_required,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "LaneTimingRule":
        _strict_keys(
            value,
            required={
                "lane",
                "lane_ordinal",
                "starvation_warning_seconds",
                "starvation_limit_seconds",
                "explicit_deadline_required",
            },
            field="lane_timing_rule",
        )
        try:
            lane = PriorityLane(value["lane"])
            result = cls(
                lane=lane,
                starvation_warning_seconds=value["starvation_warning_seconds"],  # type: ignore[arg-type]
                starvation_limit_seconds=value["starvation_limit_seconds"],  # type: ignore[arg-type]
                explicit_deadline_required=value["explicit_deadline_required"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError("lane timing rule is malformed") from exc
        if value["lane_ordinal"] != lane.ordinal:
            raise SchedulingContractError("lane timing ordinal differs")
        return result


@dataclass(frozen=True, slots=True)
class UrgencyDeadlinePolicy:
    policy_id: str
    policy_version: str
    clock_time_zone: str
    tie_break: str
    lane_rules: tuple[LaneTimingRule, ...]
    schema_version: str = SCHEDULING_POLICY_SCHEMA_VERSION
    authority: str = "NONE"
    effect: str = "NONE"
    production_activation_authorised: bool = False

    def __post_init__(self) -> None:
        _require_token(self.policy_id, field="scheduling_policy_id")
        _require_token(self.policy_version, field="scheduling_policy_version")
        if self.schema_version != SCHEDULING_POLICY_SCHEMA_VERSION:
            raise SchedulingContractError("scheduling policy schema differs")
        if self.clock_time_zone != "UTC":
            raise SchedulingContractError(
                "scheduling calculation clock must be exact UTC"
            )
        if self.tie_break != _TIE_BREAK:
            raise SchedulingContractError(
                "scheduling policy tie-break must remain exact"
            )
        if not isinstance(self.lane_rules, tuple) or not all(
            isinstance(item, LaneTimingRule) for item in self.lane_rules
        ):
            raise SchedulingContractError("lane timing rules must be typed")
        expected = tuple(PriorityLane)
        if tuple(item.lane for item in self.lane_rules) != expected:
            raise SchedulingContractError(
                "lane timing rules must cover every lane in ordinal order"
            )
        if (
            self.authority != "NONE"
            or self.effect != "NONE"
            or self.production_activation_authorised is not False
        ):
            raise SchedulingContractError(
                "scheduling policy cannot claim authority, effect or activation"
            )

    def rule_for(self, lane: PriorityLane) -> LaneTimingRule:
        if not isinstance(lane, PriorityLane):
            raise SchedulingContractError("scheduling lane must be typed")
        return self.lane_rules[lane.ordinal - 1]

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "record_type": "urgency_deadline_policy",
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "clock_time_zone": self.clock_time_zone,
            "tie_break": self.tie_break,
            "lane_rules": [item.canonical_value() for item in self.lane_rules],
            "authority": self.authority,
            "effect": self.effect,
            "production_activation_authorised": (
                self.production_activation_authorised
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def policy_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "UrgencyDeadlinePolicy":
        _strict_keys(
            value,
            required={
                "schema_version",
                "record_type",
                "policy_id",
                "policy_version",
                "clock_time_zone",
                "tie_break",
                "lane_rules",
                "authority",
                "effect",
                "production_activation_authorised",
            },
            field="urgency_deadline_policy",
        )
        if value["record_type"] != "urgency_deadline_policy":
            raise SchedulingContractError("urgency deadline record type differs")
        raw_rules = value["lane_rules"]
        if not isinstance(raw_rules, list) or not all(
            isinstance(item, dict) for item in raw_rules
        ):
            raise SchedulingContractError("lane timing rules must be objects")
        return cls(
            policy_id=value["policy_id"],  # type: ignore[arg-type]
            policy_version=value["policy_version"],  # type: ignore[arg-type]
            clock_time_zone=value["clock_time_zone"],  # type: ignore[arg-type]
            tie_break=value["tie_break"],  # type: ignore[arg-type]
            lane_rules=tuple(LaneTimingRule.from_mapping(item) for item in raw_rules),
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            authority=value["authority"],  # type: ignore[arg-type]
            effect=value["effect"],  # type: ignore[arg-type]
            production_activation_authorised=value[
                "production_activation_authorised"
            ],  # type: ignore[arg-type]
        )


class SchedulingEligibility(StrEnum):
    CURRENT_ELIGIBLE = "CURRENT_ELIGIBLE"
    CURRENT_DEPENDENCY_BLOCKED = "CURRENT_DEPENDENCY_BLOCKED"
    STALE = "STALE"
    CLOSED = "CLOSED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


@dataclass(frozen=True, slots=True)
class UrgencyDeadlineInput:
    work_item_id: str
    work_item_version_id: str
    work_item_version_digest: str
    priority_selection: PrioritySelection
    lane: PriorityLane
    enqueued_at: str
    observed_at: str
    deadline: DeadlineBoundary | None
    eligibility: SchedulingEligibility
    delay_consequence_ordinal: int
    staleness_risk_ordinal: int
    dependency_ready: bool

    def __post_init__(self) -> None:
        _require_token(self.work_item_id, field="scheduling_work_item_id")
        _require_token(
            self.work_item_version_id,
            field="scheduling_work_item_version_id",
        )
        _require_digest(
            self.work_item_version_digest,
            field="scheduling_work_item_version_digest",
        )
        if not isinstance(self.priority_selection, PrioritySelection):
            raise SchedulingContractError(
                "scheduling priority selection must be typed"
            )
        if not isinstance(self.lane, PriorityLane):
            raise SchedulingContractError("scheduling input lane must be typed")
        if (
            self.priority_selection.work_identity != self.work_item_id
            or self.priority_selection.work_version != self.work_item_version_id
            or self.priority_selection.lane is not self.lane
        ):
            raise SchedulingContractError(
                "scheduling input differs from its exact priority selection"
            )
        enqueued = _parse_utc(self.enqueued_at, field="scheduling_enqueued_at")
        observed = _parse_utc(self.observed_at, field="scheduling_observed_at")
        if observed < enqueued:
            raise SchedulingContractError(
                "scheduling observation cannot precede queue admission"
            )
        if self.deadline is not None and not isinstance(
            self.deadline, DeadlineBoundary
        ):
            raise SchedulingContractError("scheduling deadline must be typed or null")
        if not isinstance(self.eligibility, SchedulingEligibility):
            raise SchedulingContractError("scheduling eligibility must be typed")
        for field, value in (
            ("delay_consequence_ordinal", self.delay_consequence_ordinal),
            ("staleness_risk_ordinal", self.staleness_risk_ordinal),
        ):
            number = _require_non_negative_int(value, field=field)
            if number > 3:
                raise SchedulingContractError(f"{field} must be between zero and three")
        if type(self.dependency_ready) is not bool:
            raise SchedulingContractError(
                "scheduling dependency readiness must be boolean"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "work_item_id": self.work_item_id,
            "work_item_version_id": self.work_item_version_id,
            "work_item_version_digest": self.work_item_version_digest,
            "priority_selection": self.priority_selection.canonical_value(),
            "priority_selection_digest": digest_bytes(
                self.priority_selection.canonical_bytes
            ),
            "lane": self.lane.value,
            "lane_ordinal": self.lane.ordinal,
            "enqueued_at": self.enqueued_at,
            "observed_at": self.observed_at,
            "deadline": None if self.deadline is None else self.deadline.canonical_value(),
            "eligibility": self.eligibility.value,
            "delay_consequence_ordinal": self.delay_consequence_ordinal,
            "staleness_risk_ordinal": self.staleness_risk_ordinal,
            "dependency_ready": self.dependency_ready,
        }

    @property
    def input_digest(self) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "schema_version": SCHEDULING_POLICY_SCHEMA_VERSION,
                    "record_type": "urgency_deadline_input",
                    "input": self.canonical_value(),
                }
            )
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "UrgencyDeadlineInput":
        _strict_keys(
            value,
            required={
                "work_item_id",
                "work_item_version_id",
                "work_item_version_digest",
                "priority_selection",
                "priority_selection_digest",
                "lane",
                "lane_ordinal",
                "enqueued_at",
                "observed_at",
                "deadline",
                "eligibility",
                "delay_consequence_ordinal",
                "staleness_risk_ordinal",
                "dependency_ready",
            },
            field="urgency_deadline_input",
        )
        raw_deadline = value["deadline"]
        if raw_deadline is not None and not isinstance(raw_deadline, dict):
            raise SchedulingContractError("scheduling deadline must be an object or null")
        raw_priority = value["priority_selection"]
        if not isinstance(raw_priority, dict):
            raise SchedulingContractError(
                "scheduling priority selection must be an object"
            )
        try:
            lane = PriorityLane(value["lane"])
            priority = PrioritySelection.from_mapping(raw_priority)
            result = cls(
                work_item_id=value["work_item_id"],  # type: ignore[arg-type]
                work_item_version_id=value["work_item_version_id"],  # type: ignore[arg-type]
                work_item_version_digest=value["work_item_version_digest"],  # type: ignore[arg-type]
                priority_selection=priority,
                lane=lane,
                enqueued_at=value["enqueued_at"],  # type: ignore[arg-type]
                observed_at=value["observed_at"],  # type: ignore[arg-type]
                deadline=(
                    None
                    if raw_deadline is None
                    else DeadlineBoundary.from_mapping(raw_deadline)
                ),
                eligibility=SchedulingEligibility(value["eligibility"]),
                delay_consequence_ordinal=value["delay_consequence_ordinal"],  # type: ignore[arg-type]
                staleness_risk_ordinal=value["staleness_risk_ordinal"],  # type: ignore[arg-type]
                dependency_ready=value["dependency_ready"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError("urgency deadline input is malformed") from exc
        if value["lane_ordinal"] != lane.ordinal:
            raise SchedulingContractError("scheduling lane ordinal differs")
        if value["priority_selection_digest"] != digest_bytes(
            priority.canonical_bytes
        ):
            raise SchedulingContractError("priority selection digest differs")
        return result


class StarvationState(StrEnum):
    WITHIN_BOUND = "WITHIN_BOUND"
    AT_RISK = "AT_RISK"
    STARVED = "STARVED"
    NOT_CURRENT = "NOT_CURRENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


_STARVATION_ORDER = {
    StarvationState.STARVED: 0,
    StarvationState.AT_RISK: 1,
    StarvationState.WITHIN_BOUND: 2,
}


def _urgency_deadline_values(
    *, policy: UrgencyDeadlinePolicy, item: UrgencyDeadlineInput
) -> dict[str, object]:
    rule = policy.rule_for(item.lane)
    if rule.explicit_deadline_required and item.deadline is None:
        raise SchedulingContractError(
            f"{item.lane.value} requires an exact deadline boundary"
        )
    enqueued = _parse_utc(item.enqueued_at, field="scheduling_enqueued_at")
    observed = _parse_utc(item.observed_at, field="scheduling_observed_at")
    queue_age = int((observed - enqueued).total_seconds())
    explicit = item.deadline is not None
    effective = (
        _parse_utc(item.deadline.due_at, field="deadline_due_at")
        if item.deadline is not None
        else enqueued + timedelta(seconds=rule.starvation_limit_seconds)
    )
    if item.eligibility is SchedulingEligibility.STALE:
        starvation = StarvationState.NOT_CURRENT
    elif item.eligibility in {
        SchedulingEligibility.CLOSED,
        SchedulingEligibility.POLICY_BLOCKED,
    }:
        starvation = StarvationState.NOT_APPLICABLE
    elif queue_age >= rule.starvation_limit_seconds:
        starvation = StarvationState.STARVED
    elif queue_age >= rule.starvation_warning_seconds:
        starvation = StarvationState.AT_RISK
    else:
        starvation = StarvationState.WITHIN_BOUND
    deadline_overdue = observed > effective
    revalidation_required = (
        item.eligibility is SchedulingEligibility.STALE
        or starvation is StarvationState.STARVED
        or deadline_overdue
    )
    schedulable = (
        item.eligibility is SchedulingEligibility.CURRENT_ELIGIBLE
        and item.dependency_ready
    )
    order_key: tuple[int | str, ...] | None = None
    if schedulable:
        order_key = (
            item.lane.ordinal,
            0 if explicit else 1,
            int(effective.timestamp()),
            -item.delay_consequence_ordinal,
            -item.staleness_risk_ordinal,
            _STARVATION_ORDER[starvation],
            int(enqueued.timestamp()),
            0 if item.dependency_ready else 1,
            item.work_item_version_id,
        )
    return {
        "effective_deadline": _format_utc(effective),
        "deadline_source": "EXPLICIT" if explicit else "STARVATION_LIMIT",
        "queue_age_seconds": queue_age,
        "deadline_overdue": deadline_overdue,
        "starvation_state": starvation,
        "starvation_overrun_seconds": max(
            0, queue_age - rule.starvation_limit_seconds
        ),
        "revalidation_required": revalidation_required,
        "schedulable": schedulable,
        "order_key": order_key,
    }


@dataclass(frozen=True, slots=True)
class StarvationObservation:
    policy: UrgencyDeadlinePolicy
    item: UrgencyDeadlineInput
    effective_deadline: str
    deadline_source: str
    queue_age_seconds: int
    deadline_overdue: bool
    starvation_state: StarvationState
    starvation_overrun_seconds: int
    revalidation_required: bool
    schedulable: bool
    order_key: tuple[int | str, ...] | None
    authority: str = "NONE"
    effect: str = "NONE"
    production_activation_authorised: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.policy, UrgencyDeadlinePolicy):
            raise SchedulingContractError("starvation observation policy must be typed")
        if not isinstance(self.item, UrgencyDeadlineInput):
            raise SchedulingContractError("starvation observation input must be typed")
        _parse_utc(
            self.effective_deadline,
            field="starvation_effective_deadline",
        )
        if self.deadline_source not in {"EXPLICIT", "STARVATION_LIMIT"}:
            raise SchedulingContractError("starvation deadline source differs")
        _require_non_negative_int(
            self.queue_age_seconds,
            field="starvation_queue_age_seconds",
        )
        _require_non_negative_int(
            self.starvation_overrun_seconds,
            field="starvation_overrun_seconds",
        )
        if not isinstance(self.starvation_state, StarvationState):
            raise SchedulingContractError("starvation state must be typed")
        for field in (
            "deadline_overdue",
            "revalidation_required",
            "schedulable",
        ):
            if type(getattr(self, field)) is not bool:
                raise SchedulingContractError(f"{field} must be boolean")
        if self.order_key is not None:
            if (
                not isinstance(self.order_key, tuple)
                or len(self.order_key) != 9
                or any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in self.order_key[:8]
                )
                or not isinstance(self.order_key[8], str)
            ):
                raise SchedulingContractError(
                    "starvation order key has invalid field types"
                )
            _require_token(self.order_key[8], field="starvation_tie_break")
        expected = _urgency_deadline_values(policy=self.policy, item=self.item)
        actual = {
            "effective_deadline": self.effective_deadline,
            "deadline_source": self.deadline_source,
            "queue_age_seconds": self.queue_age_seconds,
            "deadline_overdue": self.deadline_overdue,
            "starvation_state": self.starvation_state,
            "starvation_overrun_seconds": self.starvation_overrun_seconds,
            "revalidation_required": self.revalidation_required,
            "schedulable": self.schedulable,
            "order_key": self.order_key,
        }
        if actual != expected:
            raise SchedulingContractError(
                "starvation observation differs from deterministic policy"
            )
        if (
            self.authority != "NONE"
            or self.effect != "NONE"
            or self.production_activation_authorised is not False
        ):
            raise SchedulingContractError(
                "starvation observation cannot claim authority, effect or activation"
            )

    @property
    def schema_version(self) -> str:
        return SCHEDULING_POLICY_SCHEMA_VERSION

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "record_type": "starvation_observation",
            "policy": self.policy.canonical_value(),
            "policy_digest": self.policy.policy_digest,
            "input": self.item.canonical_value(),
            "input_digest": self.item.input_digest,
            "effective_deadline": self.effective_deadline,
            "deadline_source": self.deadline_source,
            "queue_age_seconds": self.queue_age_seconds,
            "deadline_overdue": self.deadline_overdue,
            "starvation_state": self.starvation_state.value,
            "starvation_overrun_seconds": self.starvation_overrun_seconds,
            "revalidation_required": self.revalidation_required,
            "schedulable": self.schedulable,
            "order_key": None if self.order_key is None else list(self.order_key),
            "authority": self.authority,
            "effect": self.effect,
            "production_activation_authorised": (
                self.production_activation_authorised
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def decision_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "StarvationObservation":
        value = _decode_canonical_object(raw, field="starvation_observation")
        _strict_keys(
            value,
            required={
                "schema_version",
                "record_type",
                "policy",
                "policy_digest",
                "input",
                "input_digest",
                "effective_deadline",
                "deadline_source",
                "queue_age_seconds",
                "deadline_overdue",
                "starvation_state",
                "starvation_overrun_seconds",
                "revalidation_required",
                "schedulable",
                "order_key",
                "authority",
                "effect",
                "production_activation_authorised",
            },
            field="starvation_observation",
        )
        if (
            value["schema_version"] != SCHEDULING_POLICY_SCHEMA_VERSION
            or value["record_type"] != "starvation_observation"
        ):
            raise SchedulingContractError("starvation observation schema differs")
        raw_policy = value["policy"]
        raw_input = value["input"]
        if not isinstance(raw_policy, dict) or not isinstance(raw_input, dict):
            raise SchedulingContractError(
                "starvation observation policy and input must be objects"
            )
        policy = UrgencyDeadlinePolicy.from_mapping(raw_policy)
        item = UrgencyDeadlineInput.from_mapping(raw_input)
        if value["policy_digest"] != policy.policy_digest:
            raise SchedulingContractError("starvation policy digest differs")
        if value["input_digest"] != item.input_digest:
            raise SchedulingContractError("starvation input digest differs")
        raw_order = value["order_key"]
        if raw_order is not None and not isinstance(raw_order, list):
            raise SchedulingContractError("starvation order key must be a list or null")
        try:
            result = cls(
                policy=policy,
                item=item,
                effective_deadline=value["effective_deadline"],  # type: ignore[arg-type]
                deadline_source=value["deadline_source"],  # type: ignore[arg-type]
                queue_age_seconds=value["queue_age_seconds"],  # type: ignore[arg-type]
                deadline_overdue=value["deadline_overdue"],  # type: ignore[arg-type]
                starvation_state=StarvationState(value["starvation_state"]),
                starvation_overrun_seconds=value["starvation_overrun_seconds"],  # type: ignore[arg-type]
                revalidation_required=value["revalidation_required"],  # type: ignore[arg-type]
                schedulable=value["schedulable"],  # type: ignore[arg-type]
                order_key=None if raw_order is None else tuple(raw_order),
                authority=value["authority"],  # type: ignore[arg-type]
                effect=value["effect"],  # type: ignore[arg-type]
                production_activation_authorised=value[
                    "production_activation_authorised"
                ],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError(
                "starvation observation is malformed"
            ) from exc
        if result.canonical_bytes != raw:
            raise SchedulingContractError("starvation observation is not canonical")
        return result


UrgencyDeadlineDecision = StarvationObservation


def calculate_urgency_deadline(
    *, policy: UrgencyDeadlinePolicy, item: UrgencyDeadlineInput
) -> UrgencyDeadlineDecision:
    """Calculate one pure observation using no ambient clock or queue state."""

    if not isinstance(policy, UrgencyDeadlinePolicy):
        raise TypeError("urgency deadline policy must be typed")
    if not isinstance(item, UrgencyDeadlineInput):
        raise TypeError("urgency deadline input must be typed")
    values = _urgency_deadline_values(policy=policy, item=item)
    return StarvationObservation(policy=policy, item=item, **values)  # type: ignore[arg-type]


class CapacityPathState(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class CapacityClass(StrEnum):
    URGENT_RESERVED = "URGENT_RESERVED"
    ORDINARY = "ORDINARY"


def capacity_class_for_lane(lane: PriorityLane) -> CapacityClass:
    """Map only canonical lanes; this classification grants no admission."""

    if not isinstance(lane, PriorityLane):
        raise SchedulingContractError("capacity classification lane must be typed")
    if lane in {PriorityLane.CONTAINMENT, PriorityLane.URGENT}:
        return CapacityClass.URGENT_RESERVED
    return CapacityClass.ORDINARY


class ReservedCapacityDisposition(StrEnum):
    ADMITTED = "ADMITTED"
    NO_PENDING_WORK = "NO_PENDING_WORK"
    CAPACITY_DEFERRED = "CAPACITY_DEFERRED"
    URGENT_VISIBLE_OPERATIONAL_HOLD = "URGENT_VISIBLE_OPERATIONAL_HOLD"


@dataclass(frozen=True, slots=True)
class ReservedCapacityPolicy:
    policy_id: str
    policy_version: str
    total_slots: int
    urgent_reserved_slots: int
    minimum_ordinary_slots: int
    degraded_urgent_disposition: ReservedCapacityDisposition
    schema_version: str = SCHEDULING_POLICY_SCHEMA_VERSION
    authority: str = "NONE"
    effect: str = "NONE"
    production_activation_authorised: bool = False

    def __post_init__(self) -> None:
        _require_token(self.policy_id, field="capacity_policy_id")
        _require_token(self.policy_version, field="capacity_policy_version")
        total = _require_positive_int(self.total_slots, field="capacity_total_slots")
        urgent = _require_positive_int(
            self.urgent_reserved_slots,
            field="urgent_reserved_slots",
        )
        ordinary = _require_positive_int(
            self.minimum_ordinary_slots,
            field="minimum_ordinary_slots",
        )
        if urgent + ordinary > total:
            raise SchedulingContractError(
                "urgent and ordinary reservations exceed total capacity"
            )
        if (
            self.degraded_urgent_disposition
            is not ReservedCapacityDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD
        ):
            raise SchedulingContractError(
                "degraded Urgent work must remain a visible operational hold"
            )
        if self.schema_version != SCHEDULING_POLICY_SCHEMA_VERSION:
            raise SchedulingContractError("reserved capacity schema differs")
        if (
            self.authority != "NONE"
            or self.effect != "NONE"
            or self.production_activation_authorised is not False
        ):
            raise SchedulingContractError(
                "reserved capacity policy cannot claim authority or effect"
            )

    @property
    def max_urgent_slots(self) -> int:
        return self.total_slots - self.minimum_ordinary_slots

    @property
    def ordinary_capacity_ceiling(self) -> int:
        return self.total_slots - self.urgent_reserved_slots

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "record_type": "reserved_capacity_policy",
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "total_slots": self.total_slots,
            "urgent_reserved_slots": self.urgent_reserved_slots,
            "minimum_ordinary_slots": self.minimum_ordinary_slots,
            "max_urgent_slots": self.max_urgent_slots,
            "ordinary_capacity_ceiling": self.ordinary_capacity_ceiling,
            "degraded_urgent_disposition": self.degraded_urgent_disposition.value,
            "authority": self.authority,
            "effect": self.effect,
            "production_activation_authorised": (
                self.production_activation_authorised
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def policy_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ReservedCapacityPolicy":
        _strict_keys(
            value,
            required={
                "schema_version",
                "record_type",
                "policy_id",
                "policy_version",
                "total_slots",
                "urgent_reserved_slots",
                "minimum_ordinary_slots",
                "max_urgent_slots",
                "ordinary_capacity_ceiling",
                "degraded_urgent_disposition",
                "authority",
                "effect",
                "production_activation_authorised",
            },
            field="reserved_capacity_policy",
        )
        if value["record_type"] != "reserved_capacity_policy":
            raise SchedulingContractError("reserved capacity record type differs")
        try:
            result = cls(
                policy_id=value["policy_id"],  # type: ignore[arg-type]
                policy_version=value["policy_version"],  # type: ignore[arg-type]
                total_slots=value["total_slots"],  # type: ignore[arg-type]
                urgent_reserved_slots=value["urgent_reserved_slots"],  # type: ignore[arg-type]
                minimum_ordinary_slots=value["minimum_ordinary_slots"],  # type: ignore[arg-type]
                degraded_urgent_disposition=ReservedCapacityDisposition(
                    value["degraded_urgent_disposition"]
                ),
                schema_version=value["schema_version"],  # type: ignore[arg-type]
                authority=value["authority"],  # type: ignore[arg-type]
                effect=value["effect"],  # type: ignore[arg-type]
                production_activation_authorised=value[
                    "production_activation_authorised"
                ],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError("reserved capacity policy is malformed") from exc
        if (
            value["max_urgent_slots"] != result.max_urgent_slots
            or value["ordinary_capacity_ceiling"]
            != result.ordinary_capacity_ceiling
        ):
            raise SchedulingContractError("reserved capacity derived bounds differ")
        return result


@dataclass(frozen=True, slots=True)
class CapacitySnapshot:
    observed_at: str
    active_urgent_slots: int
    active_ordinary_slots: int
    pending_urgent: int
    pending_ordinary: int
    urgent_path_state: CapacityPathState

    def __post_init__(self) -> None:
        _parse_utc(self.observed_at, field="capacity_observed_at")
        for field in (
            "active_urgent_slots",
            "active_ordinary_slots",
            "pending_urgent",
            "pending_ordinary",
        ):
            _require_non_negative_int(getattr(self, field), field=field)
        if not isinstance(self.urgent_path_state, CapacityPathState):
            raise SchedulingContractError("Urgent capacity path state must be typed")

    def canonical_value(self) -> dict[str, object]:
        return {
            "observed_at": self.observed_at,
            "active_urgent_slots": self.active_urgent_slots,
            "active_ordinary_slots": self.active_ordinary_slots,
            "pending_urgent": self.pending_urgent,
            "pending_ordinary": self.pending_ordinary,
            "urgent_path_state": self.urgent_path_state.value,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CapacitySnapshot":
        _strict_keys(
            value,
            required={
                "observed_at",
                "active_urgent_slots",
                "active_ordinary_slots",
                "pending_urgent",
                "pending_ordinary",
                "urgent_path_state",
            },
            field="capacity_snapshot",
        )
        try:
            return cls(
                observed_at=value["observed_at"],  # type: ignore[arg-type]
                active_urgent_slots=value["active_urgent_slots"],  # type: ignore[arg-type]
                active_ordinary_slots=value["active_ordinary_slots"],  # type: ignore[arg-type]
                pending_urgent=value["pending_urgent"],  # type: ignore[arg-type]
                pending_ordinary=value["pending_ordinary"],  # type: ignore[arg-type]
                urgent_path_state=CapacityPathState(value["urgent_path_state"]),
            )
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError("capacity snapshot is malformed") from exc


def _capacity_values(
    *, policy: ReservedCapacityPolicy, snapshot: CapacitySnapshot
) -> dict[str, object]:
    active_total = snapshot.active_urgent_slots + snapshot.active_ordinary_slots
    if active_total > policy.total_slots:
        raise SchedulingContractError("active work exceeds total capacity")
    if snapshot.active_urgent_slots > policy.max_urgent_slots:
        raise SchedulingContractError("active Urgent work consumed ordinary reserve")
    if snapshot.active_ordinary_slots > policy.ordinary_capacity_ceiling:
        raise SchedulingContractError("active ordinary work consumed Urgent reserve")
    available = policy.total_slots - active_total
    if snapshot.pending_urgent == 0:
        urgent_grants = 0
        urgent_disposition = ReservedCapacityDisposition.NO_PENDING_WORK
    elif snapshot.urgent_path_state is not CapacityPathState.AVAILABLE:
        urgent_grants = 0
        urgent_disposition = policy.degraded_urgent_disposition
    else:
        urgent_grants = min(
            snapshot.pending_urgent,
            available,
            policy.max_urgent_slots - snapshot.active_urgent_slots,
        )
        urgent_disposition = (
            ReservedCapacityDisposition.ADMITTED
            if urgent_grants
            else ReservedCapacityDisposition.CAPACITY_DEFERRED
        )
    remaining = available - urgent_grants
    ordinary_grants = min(
        snapshot.pending_ordinary,
        remaining,
        policy.ordinary_capacity_ceiling - snapshot.active_ordinary_slots,
    )
    if snapshot.pending_ordinary == 0:
        ordinary_disposition = ReservedCapacityDisposition.NO_PENDING_WORK
    elif ordinary_grants:
        ordinary_disposition = ReservedCapacityDisposition.ADMITTED
    else:
        ordinary_disposition = ReservedCapacityDisposition.CAPACITY_DEFERRED
    return {
        "urgent_grants": urgent_grants,
        "ordinary_grants": ordinary_grants,
        "unallocated_slots": remaining - ordinary_grants,
        "urgent_disposition": urgent_disposition,
        "ordinary_disposition": ordinary_disposition,
        "downgraded_urgent_to_ordinary": False,
    }


@dataclass(frozen=True, slots=True)
class ReservedCapacityDecision:
    policy: ReservedCapacityPolicy
    snapshot: CapacitySnapshot
    urgent_grants: int
    ordinary_grants: int
    unallocated_slots: int
    urgent_disposition: ReservedCapacityDisposition
    ordinary_disposition: ReservedCapacityDisposition
    downgraded_urgent_to_ordinary: bool
    authority: str = "NONE"
    effect: str = "NONE"
    production_activation_authorised: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.policy, ReservedCapacityPolicy):
            raise SchedulingContractError("capacity decision policy must be typed")
        if not isinstance(self.snapshot, CapacitySnapshot):
            raise SchedulingContractError("capacity decision snapshot must be typed")
        for field in (
            "urgent_grants",
            "ordinary_grants",
            "unallocated_slots",
        ):
            _require_non_negative_int(getattr(self, field), field=field)
        if not isinstance(
            self.urgent_disposition, ReservedCapacityDisposition
        ) or not isinstance(
            self.ordinary_disposition, ReservedCapacityDisposition
        ):
            raise SchedulingContractError("capacity dispositions must be typed")
        if type(self.downgraded_urgent_to_ordinary) is not bool:
            raise SchedulingContractError(
                "Urgent downgrade indicator must be boolean"
            )
        expected = _capacity_values(policy=self.policy, snapshot=self.snapshot)
        actual = {
            "urgent_grants": self.urgent_grants,
            "ordinary_grants": self.ordinary_grants,
            "unallocated_slots": self.unallocated_slots,
            "urgent_disposition": self.urgent_disposition,
            "ordinary_disposition": self.ordinary_disposition,
            "downgraded_urgent_to_ordinary": self.downgraded_urgent_to_ordinary,
        }
        if actual != expected:
            raise SchedulingContractError(
                "capacity decision differs from deterministic policy"
            )
        if (
            self.authority != "NONE"
            or self.effect != "NONE"
            or self.production_activation_authorised is not False
        ):
            raise SchedulingContractError(
                "capacity decision cannot claim authority, effect or activation"
            )

    @property
    def active_after_urgent(self) -> int:
        return self.snapshot.active_urgent_slots + self.urgent_grants

    @property
    def active_after_ordinary(self) -> int:
        return self.snapshot.active_ordinary_slots + self.ordinary_grants

    @property
    def schema_version(self) -> str:
        return SCHEDULING_POLICY_SCHEMA_VERSION

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "record_type": "reserved_capacity_decision",
            "policy": self.policy.canonical_value(),
            "policy_digest": self.policy.policy_digest,
            "snapshot": self.snapshot.canonical_value(),
            "urgent_grants": self.urgent_grants,
            "ordinary_grants": self.ordinary_grants,
            "unallocated_slots": self.unallocated_slots,
            "active_after_urgent": self.active_after_urgent,
            "active_after_ordinary": self.active_after_ordinary,
            "urgent_disposition": self.urgent_disposition.value,
            "ordinary_disposition": self.ordinary_disposition.value,
            "downgraded_urgent_to_ordinary": self.downgraded_urgent_to_ordinary,
            "authority": self.authority,
            "effect": self.effect,
            "production_activation_authorised": (
                self.production_activation_authorised
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def decision_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "ReservedCapacityDecision":
        value = _decode_canonical_object(raw, field="reserved_capacity_decision")
        _strict_keys(
            value,
            required={
                "schema_version",
                "record_type",
                "policy",
                "policy_digest",
                "snapshot",
                "urgent_grants",
                "ordinary_grants",
                "unallocated_slots",
                "active_after_urgent",
                "active_after_ordinary",
                "urgent_disposition",
                "ordinary_disposition",
                "downgraded_urgent_to_ordinary",
                "authority",
                "effect",
                "production_activation_authorised",
            },
            field="reserved_capacity_decision",
        )
        if (
            value["schema_version"] != SCHEDULING_POLICY_SCHEMA_VERSION
            or value["record_type"] != "reserved_capacity_decision"
        ):
            raise SchedulingContractError("reserved capacity decision schema differs")
        raw_policy = value["policy"]
        raw_snapshot = value["snapshot"]
        if not isinstance(raw_policy, dict) or not isinstance(raw_snapshot, dict):
            raise SchedulingContractError(
                "capacity decision policy and snapshot must be objects"
            )
        policy = ReservedCapacityPolicy.from_mapping(raw_policy)
        snapshot = CapacitySnapshot.from_mapping(raw_snapshot)
        if value["policy_digest"] != policy.policy_digest:
            raise SchedulingContractError("capacity policy digest differs")
        try:
            result = cls(
                policy=policy,
                snapshot=snapshot,
                urgent_grants=value["urgent_grants"],  # type: ignore[arg-type]
                ordinary_grants=value["ordinary_grants"],  # type: ignore[arg-type]
                unallocated_slots=value["unallocated_slots"],  # type: ignore[arg-type]
                urgent_disposition=ReservedCapacityDisposition(
                    value["urgent_disposition"]
                ),
                ordinary_disposition=ReservedCapacityDisposition(
                    value["ordinary_disposition"]
                ),
                downgraded_urgent_to_ordinary=value[
                    "downgraded_urgent_to_ordinary"
                ],  # type: ignore[arg-type]
                authority=value["authority"],  # type: ignore[arg-type]
                effect=value["effect"],  # type: ignore[arg-type]
                production_activation_authorised=value[
                    "production_activation_authorised"
                ],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError(
                "reserved capacity decision is malformed"
            ) from exc
        if (
            value["active_after_urgent"] != result.active_after_urgent
            or value["active_after_ordinary"] != result.active_after_ordinary
        ):
            raise SchedulingContractError("capacity active totals differ")
        if result.canonical_bytes != raw:
            raise SchedulingContractError(
                "reserved capacity decision is not canonical"
            )
        return result


def allocate_reserved_capacity(
    *, policy: ReservedCapacityPolicy, snapshot: CapacitySnapshot
) -> ReservedCapacityDecision:
    """Return grants only; this pure function owns no queue admission effect."""

    if not isinstance(policy, ReservedCapacityPolicy):
        raise TypeError("reserved capacity policy must be typed")
    if not isinstance(snapshot, CapacitySnapshot):
        raise TypeError("capacity snapshot must be typed")
    values = _capacity_values(policy=policy, snapshot=snapshot)
    return ReservedCapacityDecision(policy=policy, snapshot=snapshot, **values)  # type: ignore[arg-type]


URGENCY_DEADLINE_POLICY = UrgencyDeadlinePolicy
RESERVED_CAPACITY_POLICY = ReservedCapacityPolicy
STARVATION_OBSERVATION = StarvationObservation


__all__ = [
    "RESERVED_CAPACITY_POLICY",
    "SCHEDULING_POLICY_SCHEMA_VERSION",
    "STARVATION_OBSERVATION",
    "URGENCY_DEADLINE_POLICY",
    "CapacityPathState",
    "CapacityClass",
    "CapacitySnapshot",
    "DeadlineBoundary",
    "DeadlineKind",
    "LaneTimingRule",
    "ReservedCapacityDecision",
    "ReservedCapacityDisposition",
    "ReservedCapacityPolicy",
    "SchedulingContractError",
    "SchedulingEligibility",
    "StarvationObservation",
    "StarvationState",
    "UrgencyDeadlineDecision",
    "UrgencyDeadlineInput",
    "UrgencyDeadlinePolicy",
    "allocate_reserved_capacity",
    "capacity_class_for_lane",
    "calculate_urgency_deadline",
]
