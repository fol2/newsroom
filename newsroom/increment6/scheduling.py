"""Pure urgency, deadline, reserved-capacity and starvation policy.

The module calculates an inspectable scheduling order from exact caller-supplied
UTC observations.  It owns no queue, clock, Work Item state, authority read or
effect.  Priority can order only explicitly current and eligible work; it cannot
turn stale, closed, blocked or dependency-bound work into schedulable work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.increment6.outcomes import (
    PriorityLane,
    PrioritySelection,
    ReasonReference,
)

SCHEDULING_POLICY_SCHEMA_VERSION = "newsroom.increment6.triage-scheduling-policy.v1"

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_ZONE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-/]{0,255}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LOCAL_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
_UTC_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_TIE_BREAK = "WORK_ITEM_VERSION_ID_ASC"
_MAX_CAPACITY_ITEM_BYTES = 16_384
_MAX_CAPACITY_POPULATION = 48
_MAX_CANONICAL_OVERHEAD_BYTES = 131_072
_MAX_JSON_DEPTH = 64
_MAX_CANONICAL_BYTES = (
    _MAX_CAPACITY_POPULATION * _MAX_CAPACITY_ITEM_BYTES + _MAX_CANONICAL_OVERHEAD_BYTES
)
_MAX_INTEGER = 2_147_483_647
_MAX_DURATION_SECONDS = 315_576_000  # ten years, including leap-day headroom


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
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > _MAX_INTEGER
    ):
        raise SchedulingContractError(f"{field} must be a bounded non-negative integer")
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
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise SchedulingContractError(f"{field} bounded bytes are required")
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
        elif byte == ord('"'):
            in_string = True
        elif byte in {ord("{"), ord("[")}:
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise SchedulingContractError(f"{field} exceeds the JSON depth bound")
        elif byte in {ord("}"), ord("]")}:
            depth -= 1
            if depth < 0:
                raise SchedulingContractError(f"{field} has invalid JSON depth")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        MemoryError,
        RecursionError,
    ) as exc:
        raise SchedulingContractError(f"{field} is not JSON") from exc
    if not isinstance(value, dict):
        raise SchedulingContractError(f"{field} must be an object")
    try:
        canonical = canonical_json_bytes(value)
    except (
        CanonicalizationError,
        ValueError,
        OverflowError,
        MemoryError,
        RecursionError,
    ) as exc:
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
            local = datetime.strptime(  # noqa: DTZ007 - local wall time by contract
                self.source_local_time, _LOCAL_TIME_FORMAT
            )
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError(
                "deadline source local time is not canonical"
            ) from exc
        if local.strftime(_LOCAL_TIME_FORMAT) != self.source_local_time:
            raise SchedulingContractError("deadline source local time is not canonical")
        if self.source_fold not in (0, 1) or isinstance(self.source_fold, bool):
            raise SchedulingContractError("deadline fold must be zero or one")
        if (
            isinstance(self.source_utc_offset_minutes, bool)
            or not isinstance(self.source_utc_offset_minutes, int)
            or not -24 * 60 < self.source_utc_offset_minutes < 24 * 60
        ):
            raise SchedulingContractError("deadline UTC offset is invalid")
        try:
            aware = local.replace(tzinfo=zone, fold=self.source_fold)
            offset = aware.utcoffset()
            if offset is None or offset.total_seconds() % 60 != 0:
                raise SchedulingContractError("deadline UTC offset cannot be resolved")
            if int(offset.total_seconds() // 60) != self.source_utc_offset_minutes:
                raise SchedulingContractError("deadline UTC offset differs")
            if aware.astimezone(UTC) != due:
                raise SchedulingContractError("deadline UTC and local boundary differ")
            round_trip = due.astimezone(zone)
        except (OverflowError, OSError, ValueError) as exc:
            raise SchedulingContractError(
                "deadline boundary is not representable"
            ) from exc
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
    def from_mapping(cls, value: Mapping[str, object]) -> DeadlineBoundary:
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
        if limit > _MAX_DURATION_SECONDS:
            raise SchedulingContractError(
                "starvation duration exceeds the representable policy bound"
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
    def from_mapping(cls, value: Mapping[str, object]) -> LaneTimingRule:
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
        if (
            isinstance(value["lane_ordinal"], bool)
            or not isinstance(value["lane_ordinal"], int)
            or value["lane_ordinal"] != lane.ordinal
        ):
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
            "production_activation_authorised": (self.production_activation_authorised),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def policy_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> UrgencyDeadlinePolicy:
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
            production_activation_authorised=value["production_activation_authorised"],  # type: ignore[arg-type]
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
            raise SchedulingContractError("scheduling priority selection must be typed")
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
            "deadline": None
            if self.deadline is None
            else self.deadline.canonical_value(),
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
    def from_mapping(cls, value: Mapping[str, object]) -> UrgencyDeadlineInput:
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
            raise SchedulingContractError(
                "scheduling deadline must be an object or null"
            )
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
            raise SchedulingContractError(
                "urgency deadline input is malformed"
            ) from exc
        if (
            isinstance(value["lane_ordinal"], bool)
            or not isinstance(value["lane_ordinal"], int)
            or value["lane_ordinal"] != lane.ordinal
        ):
            raise SchedulingContractError("scheduling lane ordinal differs")
        if value["priority_selection_digest"] != digest_bytes(priority.canonical_bytes):
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
    if queue_age > _MAX_INTEGER:
        raise SchedulingContractError(
            "queue age exceeds the representable policy bound"
        )
    explicit = item.deadline is not None
    if item.deadline is not None:
        effective = _parse_utc(item.deadline.due_at, field="deadline_due_at")
    else:
        try:
            effective = enqueued + timedelta(seconds=rule.starvation_limit_seconds)
        except (OverflowError, ValueError) as exc:
            raise SchedulingContractError(
                "derived starvation deadline is not representable"
            ) from exc
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
        try:
            effective_epoch = int(effective.timestamp())
            enqueued_epoch = int(enqueued.timestamp())
        except (OverflowError, OSError, ValueError) as exc:
            raise SchedulingContractError(
                "scheduling timestamp is not representable"
            ) from exc
        order_key = (
            item.lane.ordinal,
            0 if explicit else 1,
            effective_epoch,
            -item.delay_consequence_ordinal,
            -item.staleness_risk_ordinal,
            _STARVATION_ORDER[starvation],
            enqueued_epoch,
            0 if item.dependency_ready else 1,
            item.work_item_version_id,
        )
    return {
        "effective_deadline": _format_utc(effective),
        "deadline_source": "EXPLICIT" if explicit else "STARVATION_LIMIT",
        "queue_age_seconds": queue_age,
        "deadline_overdue": deadline_overdue,
        "starvation_state": starvation,
        "starvation_overrun_seconds": max(0, queue_age - rule.starvation_limit_seconds),
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
            "production_activation_authorised": (self.production_activation_authorised),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def decision_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> StarvationObservation:
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
        raise SchedulingContractError("urgency deadline policy must be typed")
    if not isinstance(item, UrgencyDeadlineInput):
        raise SchedulingContractError("urgency deadline input must be typed")
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
    """Derive capacity only from the canonical Priority Selection lane."""

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


class CapacityWorkState(StrEnum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"


class CapacityRevalidationResult(StrEnum):
    REVALIDATED = "REVALIDATED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class CapacityAllocationDisposition(StrEnum):
    GRANTED = "GRANTED"
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
            self.urgent_reserved_slots, field="urgent_reserved_slots"
        )
        ordinary = _require_positive_int(
            self.minimum_ordinary_slots, field="minimum_ordinary_slots"
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
            "production_activation_authorised": self.production_activation_authorised,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def policy_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ReservedCapacityPolicy:
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
                policy_id=value["policy_id"],
                policy_version=value["policy_version"],
                total_slots=value["total_slots"],
                urgent_reserved_slots=value["urgent_reserved_slots"],
                minimum_ordinary_slots=value["minimum_ordinary_slots"],
                degraded_urgent_disposition=ReservedCapacityDisposition(
                    value["degraded_urgent_disposition"]
                ),
                schema_version=value["schema_version"],
                authority=value["authority"],
                effect=value["effect"],
                production_activation_authorised=value[
                    "production_activation_authorised"
                ],
            )  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError(
                "reserved capacity policy is malformed"
            ) from exc
        for field, expected in (
            ("max_urgent_slots", result.max_urgent_slots),
            ("ordinary_capacity_ceiling", result.ordinary_capacity_ceiling),
        ):
            actual = value[field]
            if (
                isinstance(actual, bool)
                or not isinstance(actual, int)
                or actual != expected
            ):
                raise SchedulingContractError("reserved capacity derived bounds differ")
        return result


@dataclass(frozen=True, slots=True)
class CapacityRevalidationEvidence:
    """Bounded input seam for a downstream authoritative currentness receipt.

    This pure contract carries no authority itself.  A downstream authority may
    bind its receipt to these exact bytes before presenting it to allocation.
    """

    work_item_id: str
    work_item_version_id: str
    work_item_version_digest: str
    starvation_observation_digest: str
    governing_policy_digest: str
    snapshot_observed_at: str
    currentness_basis: tuple[ReasonReference, ...]
    result: CapacityRevalidationResult
    authority: str = "NONE"
    effect: str = "NONE"

    def __post_init__(self) -> None:
        _require_token(self.work_item_id, field="revalidation_work_item_id")
        _require_token(
            self.work_item_version_id,
            field="revalidation_work_item_version_id",
        )
        _require_digest(
            self.work_item_version_digest,
            field="revalidation_work_item_version_digest",
        )
        _require_digest(
            self.starvation_observation_digest,
            field="revalidation_starvation_observation_digest",
        )
        _require_digest(
            self.governing_policy_digest,
            field="revalidation_governing_policy_digest",
        )
        _parse_utc(
            self.snapshot_observed_at,
            field="revalidation_snapshot_observed_at",
        )
        if (
            not isinstance(self.currentness_basis, tuple)
            or len(self.currentness_basis) != 1
            or any(
                not isinstance(item, ReasonReference) for item in self.currentness_basis
            )
        ):
            raise SchedulingContractError(
                "revalidation currentness basis must be an immutable typed tuple"
            )
        basis_bytes = tuple(
            canonical_json_bytes(item.canonical_value())
            for item in self.currentness_basis
        )
        if basis_bytes != tuple(sorted(basis_bytes)) or len(basis_bytes) != len(
            set(basis_bytes)
        ):
            raise SchedulingContractError(
                "revalidation currentness basis must be sorted and unique"
            )
        if not isinstance(self.result, CapacityRevalidationResult):
            raise SchedulingContractError("revalidation result must be typed")
        expected_basis_type = f"revalidation-{self.result.value.lower()}"
        if self.currentness_basis[0].reference_type != expected_basis_type:
            raise SchedulingContractError(
                "revalidation result differs from its currentness basis"
            )
        if self.authority != "NONE" or self.effect != "NONE":
            raise SchedulingContractError(
                "revalidation evidence cannot claim authority or effect"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "work_item_id": self.work_item_id,
            "work_item_version_id": self.work_item_version_id,
            "work_item_version_digest": self.work_item_version_digest,
            "starvation_observation_digest": self.starvation_observation_digest,
            "governing_policy_digest": self.governing_policy_digest,
            "snapshot_observed_at": self.snapshot_observed_at,
            "currentness_basis": [
                item.canonical_value() for item in self.currentness_basis
            ],
            "result": self.result.value,
            "authority": self.authority,
            "effect": self.effect,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def evidence_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CapacityRevalidationEvidence:
        _strict_keys(
            value,
            required={
                "work_item_id",
                "work_item_version_id",
                "work_item_version_digest",
                "starvation_observation_digest",
                "governing_policy_digest",
                "snapshot_observed_at",
                "currentness_basis",
                "result",
                "authority",
                "effect",
            },
            field="capacity_revalidation_evidence",
        )
        raw_basis = value["currentness_basis"]
        if not isinstance(raw_basis, list) or any(
            not isinstance(item, dict) for item in raw_basis
        ):
            raise SchedulingContractError(
                "revalidation currentness basis must be an array of objects"
            )
        try:
            return cls(
                work_item_id=value["work_item_id"],
                work_item_version_id=value["work_item_version_id"],
                work_item_version_digest=value["work_item_version_digest"],
                starvation_observation_digest=value["starvation_observation_digest"],
                governing_policy_digest=value["governing_policy_digest"],
                snapshot_observed_at=value["snapshot_observed_at"],
                currentness_basis=tuple(
                    ReasonReference.from_mapping(item) for item in raw_basis
                ),
                result=CapacityRevalidationResult(value["result"]),
                authority=value["authority"],
                effect=value["effect"],
            )  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError(
                "capacity revalidation evidence is malformed"
            ) from exc


@dataclass(frozen=True, slots=True)
class CapacityPopulationItem:
    """One immutable population member with no duplicated identity or lane state."""

    observation: StarvationObservation
    state: CapacityWorkState
    revalidation_evidence: CapacityRevalidationEvidence | None

    def __post_init__(self) -> None:
        if not isinstance(self.observation, StarvationObservation):
            raise SchedulingContractError("capacity item observation must be typed")
        try:
            if len(self.observation.canonical_bytes) > _MAX_CAPACITY_ITEM_BYTES:
                raise SchedulingContractError(
                    "capacity item exceeds the canonical byte bound"
                )
        except (
            CanonicalizationError,
            ValueError,
            OverflowError,
            MemoryError,
            RecursionError,
        ) as exc:
            raise SchedulingContractError(
                "capacity item is not canonically representable"
            ) from exc
        if not isinstance(self.state, CapacityWorkState):
            raise SchedulingContractError("capacity item state must be typed")
        if self.revalidation_evidence is not None and not isinstance(
            self.revalidation_evidence, CapacityRevalidationEvidence
        ):
            raise SchedulingContractError(
                "capacity item revalidation evidence must be typed or null"
            )
        if not self.observation.schedulable:
            raise SchedulingContractError(
                "capacity population may contain only canonical schedulable work"
            )
        evidence = self.revalidation_evidence
        if self.observation.revalidation_required and evidence is None:
            raise SchedulingContractError(
                "capacity item must expose exact revalidation evidence"
            )
        if not self.observation.revalidation_required and evidence is not None:
            raise SchedulingContractError(
                "capacity item has conflicting revalidation evidence"
            )
        if evidence is not None:
            source = self.observation.item
            if (
                evidence.work_item_id != source.work_item_id
                or evidence.work_item_version_id != source.work_item_version_id
                or evidence.work_item_version_digest != source.work_item_version_digest
                or evidence.starvation_observation_digest
                != self.observation.decision_digest
                or evidence.governing_policy_digest
                != self.observation.policy.policy_digest
                or evidence.snapshot_observed_at != source.observed_at
            ):
                raise SchedulingContractError(
                    "revalidation evidence differs from its exact observation"
                )
            if (
                self.state is CapacityWorkState.ACTIVE
                and evidence.result is not CapacityRevalidationResult.REVALIDATED
            ):
                raise SchedulingContractError(
                    "active work requires current revalidated evidence"
                )
        try:
            if (
                len(canonical_json_bytes(self.canonical_value()))
                > _MAX_CAPACITY_ITEM_BYTES
            ):
                raise SchedulingContractError(
                    "capacity item exceeds the canonical byte bound"
                )
        except (
            CanonicalizationError,
            ValueError,
            OverflowError,
            MemoryError,
            RecursionError,
        ) as exc:
            raise SchedulingContractError(
                "capacity item is not canonically representable"
            ) from exc

    @property
    def work_item_id(self) -> str:
        return self.observation.item.work_item_id

    @property
    def work_item_version_id(self) -> str:
        return self.observation.item.work_item_version_id

    @property
    def work_item_version_digest(self) -> str:
        return self.observation.item.work_item_version_digest

    @property
    def priority_selection(self) -> PrioritySelection:
        return self.observation.item.priority_selection

    @property
    def lane(self) -> PriorityLane:
        return self.priority_selection.lane

    @property
    def capacity_class(self) -> CapacityClass:
        return capacity_class_for_lane(self.lane)

    @property
    def identity_key(self) -> tuple[str, str]:
        return (self.work_item_id, self.work_item_version_id)

    @property
    def revalidation_result(self) -> CapacityRevalidationResult | None:
        return (
            None
            if self.revalidation_evidence is None
            else self.revalidation_evidence.result
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "observation": self.observation.canonical_value(),
            "observation_digest": self.observation.decision_digest,
            "state": self.state.value,
            "revalidation_evidence": (
                None
                if self.revalidation_evidence is None
                else self.revalidation_evidence.canonical_value()
            ),
            "revalidation_evidence_digest": (
                None
                if self.revalidation_evidence is None
                else self.revalidation_evidence.evidence_digest
            ),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CapacityPopulationItem:
        _strict_keys(
            value,
            required={
                "observation",
                "observation_digest",
                "state",
                "revalidation_evidence",
                "revalidation_evidence_digest",
            },
            field="capacity_population_item",
        )
        raw_observation = value["observation"]
        raw_evidence = value["revalidation_evidence"]
        if not isinstance(raw_observation, dict) or (
            raw_evidence is not None and not isinstance(raw_evidence, dict)
        ):
            raise SchedulingContractError(
                "capacity item observation and evidence are malformed"
            )
        try:
            observation = StarvationObservation.from_canonical_bytes(
                canonical_json_bytes(raw_observation)
            )
            evidence = (
                None
                if raw_evidence is None
                else CapacityRevalidationEvidence.from_mapping(raw_evidence)
            )
            result = cls(
                observation=observation,
                state=CapacityWorkState(value["state"]),
                revalidation_evidence=evidence,
            )
        except (
            TypeError,
            ValueError,
            CanonicalizationError,
            MemoryError,
            OverflowError,
            RecursionError,
        ) as exc:
            raise SchedulingContractError(
                "capacity population item is malformed"
            ) from exc
        if value["observation_digest"] != observation.decision_digest or value[
            "revalidation_evidence_digest"
        ] != (None if evidence is None else evidence.evidence_digest):
            raise SchedulingContractError("capacity item derived binding differs")
        return result


@dataclass(frozen=True, slots=True)
class CapacitySnapshot:
    observed_at: str
    urgency_policy: UrgencyDeadlinePolicy
    population: tuple[CapacityPopulationItem, ...]
    urgent_path_state: CapacityPathState

    def __post_init__(self) -> None:
        _parse_utc(self.observed_at, field="capacity_observed_at")
        if not isinstance(self.urgency_policy, UrgencyDeadlinePolicy):
            raise SchedulingContractError(
                "capacity snapshot urgency policy must be typed"
            )
        if not isinstance(self.population, tuple) or any(
            not isinstance(item, CapacityPopulationItem) for item in self.population
        ):
            raise SchedulingContractError(
                "capacity population must be a typed immutable tuple"
            )
        if len(self.population) > _MAX_CAPACITY_POPULATION:
            raise SchedulingContractError(
                "capacity population exceeds the bounded size"
            )
        if not isinstance(self.urgent_path_state, CapacityPathState):
            raise SchedulingContractError("Urgent capacity path state must be typed")
        identities: set[str] = set()
        versions: set[tuple[str, str]] = set()
        for item in self.population:
            if item.observation.policy != self.urgency_policy:
                raise SchedulingContractError(
                    "capacity item uses a different exact urgency policy"
                )
            if item.observation.item.observed_at != self.observed_at:
                raise SchedulingContractError(
                    "capacity item observation time differs from snapshot"
                )
            if item.work_item_id in identities or item.identity_key in versions:
                raise SchedulingContractError(
                    "duplicate or conflicting capacity population identity"
                )
            identities.add(item.work_item_id)
            versions.add(item.identity_key)
        if tuple(item.identity_key for item in self.population) != tuple(
            sorted(item.identity_key for item in self.population)
        ):
            raise SchedulingContractError(
                "capacity population must use canonical identity order"
            )

    def items(
        self, *, state: CapacityWorkState, capacity_class: CapacityClass
    ) -> tuple[CapacityPopulationItem, ...]:
        return tuple(
            item
            for item in self.population
            if item.state is state and item.capacity_class is capacity_class
        )

    @property
    def active_urgent_slots(self) -> int:
        return len(
            self.items(
                state=CapacityWorkState.ACTIVE,
                capacity_class=CapacityClass.URGENT_RESERVED,
            )
        )

    @property
    def active_ordinary_slots(self) -> int:
        return len(
            self.items(
                state=CapacityWorkState.ACTIVE, capacity_class=CapacityClass.ORDINARY
            )
        )

    @property
    def pending_urgent(self) -> int:
        return len(
            self.items(
                state=CapacityWorkState.PENDING,
                capacity_class=CapacityClass.URGENT_RESERVED,
            )
        )

    @property
    def pending_ordinary(self) -> int:
        return len(
            self.items(
                state=CapacityWorkState.PENDING, capacity_class=CapacityClass.ORDINARY
            )
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "observed_at": self.observed_at,
            "urgency_policy": self.urgency_policy.canonical_value(),
            "urgency_policy_digest": self.urgency_policy.policy_digest,
            "population": [item.canonical_value() for item in self.population],
            "urgent_path_state": self.urgent_path_state.value,
            "active_urgent_slots": self.active_urgent_slots,
            "active_ordinary_slots": self.active_ordinary_slots,
            "pending_urgent": self.pending_urgent,
            "pending_ordinary": self.pending_ordinary,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CapacitySnapshot:
        _strict_keys(
            value,
            required={
                "observed_at",
                "urgency_policy",
                "urgency_policy_digest",
                "population",
                "urgent_path_state",
                "active_urgent_slots",
                "active_ordinary_slots",
                "pending_urgent",
                "pending_ordinary",
            },
            field="capacity_snapshot",
        )
        raw_population = value["population"]
        raw_urgency_policy = value["urgency_policy"]
        if not isinstance(raw_urgency_policy, dict):
            raise SchedulingContractError(
                "capacity snapshot urgency policy must be an object"
            )
        if not isinstance(raw_population, list) or any(
            not isinstance(item, dict) for item in raw_population
        ):
            raise SchedulingContractError(
                "capacity population must be an array of objects"
            )
        try:
            urgency_policy = UrgencyDeadlinePolicy.from_mapping(raw_urgency_policy)
            result = cls(
                observed_at=value["observed_at"],
                urgency_policy=urgency_policy,
                population=tuple(
                    CapacityPopulationItem.from_mapping(item) for item in raw_population
                ),
                urgent_path_state=CapacityPathState(value["urgent_path_state"]),
            )  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError("capacity snapshot is malformed") from exc
        if value["urgency_policy_digest"] != urgency_policy.policy_digest:
            raise SchedulingContractError(
                "capacity snapshot urgency policy digest differs"
            )
        for field in (
            "active_urgent_slots",
            "active_ordinary_slots",
            "pending_urgent",
            "pending_ordinary",
        ):
            actual = value[field]
            if (
                isinstance(actual, bool)
                or not isinstance(actual, int)
                or actual != getattr(result, field)
            ):
                raise SchedulingContractError("capacity snapshot derived count differs")
        return result


@dataclass(frozen=True, slots=True)
class CapacityItemAllocation:
    item: CapacityPopulationItem
    disposition: CapacityAllocationDisposition
    protected_routine_grant: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.item, CapacityPopulationItem)
            or self.item.state is not CapacityWorkState.PENDING
        ):
            raise SchedulingContractError(
                "capacity allocation must bind one pending item"
            )
        if (
            not isinstance(self.disposition, CapacityAllocationDisposition)
            or type(self.protected_routine_grant) is not bool
        ):
            raise SchedulingContractError(
                "capacity allocation disposition must be typed"
            )
        if self.protected_routine_grant and (
            self.disposition is not CapacityAllocationDisposition.GRANTED
            or self.item.lane is not PriorityLane.ROUTINE
            or self.item.observation.starvation_state is not StarvationState.STARVED
            or self.item.revalidation_result
            is not CapacityRevalidationResult.REVALIDATED
        ):
            raise SchedulingContractError("protected Routine grant is not eligible")

    def canonical_value(self) -> dict[str, object]:
        return {
            "work_item_id": self.item.work_item_id,
            "work_item_version_id": self.item.work_item_version_id,
            "work_item_version_digest": self.item.work_item_version_digest,
            "priority_selection_digest": digest_bytes(
                self.item.priority_selection.canonical_bytes
            ),
            "observation_digest": self.item.observation.decision_digest,
            "lane": self.item.lane.value,
            "capacity_class": self.item.capacity_class.value,
            "disposition": self.disposition.value,
            "revalidation_result": (
                None
                if self.revalidation_result is None
                else self.revalidation_result.value
            ),
            "revalidation_evidence_digest": (
                None
                if self.item.revalidation_evidence is None
                else self.item.revalidation_evidence.evidence_digest
            ),
            "protected_routine_grant": self.protected_routine_grant,
        }

    @property
    def revalidation_result(self) -> CapacityRevalidationResult | None:
        return self.item.revalidation_result


@dataclass(frozen=True, slots=True)
class ReservedCapacityDecision:
    policy: ReservedCapacityPolicy
    snapshot: CapacitySnapshot
    allocations: tuple[CapacityItemAllocation, ...]
    unallocated_slots: int
    authority: str = "NONE"
    effect: str = "NONE"
    production_activation_authorised: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.policy, ReservedCapacityPolicy) or not isinstance(
            self.snapshot, CapacitySnapshot
        ):
            raise SchedulingContractError("capacity decision inputs must be typed")
        if not isinstance(self.allocations, tuple) or any(
            not isinstance(item, CapacityItemAllocation) for item in self.allocations
        ):
            raise SchedulingContractError(
                "capacity allocations must be a typed immutable tuple"
            )
        _require_non_negative_int(self.unallocated_slots, field="unallocated_slots")
        expected = _capacity_values(policy=self.policy, snapshot=self.snapshot)
        if (
            self.allocations != expected["allocations"]
            or self.unallocated_slots != expected["unallocated_slots"]
        ):
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
    def granted_items(self) -> tuple[CapacityPopulationItem, ...]:
        return tuple(
            allocation.item
            for allocation in self.allocations
            if allocation.disposition is CapacityAllocationDisposition.GRANTED
        )

    @property
    def urgent_grants(self) -> int:
        return sum(
            item.capacity_class is CapacityClass.URGENT_RESERVED
            for item in self.granted_items
        )

    @property
    def ordinary_grants(self) -> int:
        return sum(
            item.capacity_class is CapacityClass.ORDINARY for item in self.granted_items
        )

    @property
    def active_after_urgent(self) -> int:
        return self.snapshot.active_urgent_slots + self.urgent_grants

    @property
    def active_after_ordinary(self) -> int:
        return self.snapshot.active_ordinary_slots + self.ordinary_grants

    @property
    def urgent_disposition(self) -> ReservedCapacityDisposition:
        pending = [
            a
            for a in self.allocations
            if a.item.capacity_class is CapacityClass.URGENT_RESERVED
        ]
        if not pending:
            return ReservedCapacityDisposition.NO_PENDING_WORK
        if any(a.disposition is CapacityAllocationDisposition.GRANTED for a in pending):
            return ReservedCapacityDisposition.ADMITTED
        if any(
            a.disposition
            is CapacityAllocationDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD
            for a in pending
        ):
            return ReservedCapacityDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD
        return ReservedCapacityDisposition.CAPACITY_DEFERRED

    @property
    def ordinary_disposition(self) -> ReservedCapacityDisposition:
        pending = [
            a
            for a in self.allocations
            if a.item.capacity_class is CapacityClass.ORDINARY
        ]
        if not pending:
            return ReservedCapacityDisposition.NO_PENDING_WORK
        if any(a.disposition is CapacityAllocationDisposition.GRANTED for a in pending):
            return ReservedCapacityDisposition.ADMITTED
        return ReservedCapacityDisposition.CAPACITY_DEFERRED

    @property
    def downgraded_urgent_to_ordinary(self) -> bool:
        return False

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
            "allocations": [item.canonical_value() for item in self.allocations],
            "granted_item_keys": [
                [
                    item.work_item_id,
                    item.work_item_version_id,
                    item.work_item_version_digest,
                ]
                for item in self.granted_items
            ],
            "urgent_grants": self.urgent_grants,
            "ordinary_grants": self.ordinary_grants,
            "unallocated_slots": self.unallocated_slots,
            "active_after_urgent": self.active_after_urgent,
            "active_after_ordinary": self.active_after_ordinary,
            "urgent_disposition": self.urgent_disposition.value,
            "ordinary_disposition": self.ordinary_disposition.value,
            "downgraded_urgent_to_ordinary": False,
            "authority": self.authority,
            "effect": self.effect,
            "production_activation_authorised": self.production_activation_authorised,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def decision_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> ReservedCapacityDecision:
        value = _decode_canonical_object(raw, field="reserved_capacity_decision")
        _strict_keys(
            value,
            required={
                "schema_version",
                "record_type",
                "policy",
                "policy_digest",
                "snapshot",
                "allocations",
                "granted_item_keys",
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
        raw_policy, raw_snapshot = value["policy"], value["snapshot"]
        if (
            not isinstance(raw_policy, dict)
            or not isinstance(raw_snapshot, dict)
            or not isinstance(value["allocations"], list)
        ):
            raise SchedulingContractError(
                "capacity decision nested values are malformed"
            )
        policy = ReservedCapacityPolicy.from_mapping(raw_policy)
        snapshot = CapacitySnapshot.from_mapping(raw_snapshot)
        if value["policy_digest"] != policy.policy_digest:
            raise SchedulingContractError("capacity policy digest differs")
        # Allocations are policy-derived, never trusted from the caller.
        expected = _capacity_values(policy=policy, snapshot=snapshot)
        try:
            result = cls(
                policy=policy,
                snapshot=snapshot,
                allocations=expected["allocations"],
                unallocated_slots=value["unallocated_slots"],
                authority=value["authority"],
                effect=value["effect"],
                production_activation_authorised=value[
                    "production_activation_authorised"
                ],
            )  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise SchedulingContractError(
                "reserved capacity decision is malformed"
            ) from exc
        if result.canonical_bytes != raw:
            raise SchedulingContractError("reserved capacity decision is not canonical")
        return result


def _canonical_pending(
    items: tuple[CapacityPopulationItem, ...],
) -> list[CapacityPopulationItem]:
    return sorted(items, key=lambda item: item.observation.order_key or ())


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
    urgent = _canonical_pending(
        snapshot.items(
            state=CapacityWorkState.PENDING,
            capacity_class=CapacityClass.URGENT_RESERVED,
        )
    )
    ordinary = _canonical_pending(
        snapshot.items(
            state=CapacityWorkState.PENDING, capacity_class=CapacityClass.ORDINARY
        )
    )
    urgent_eligible = [
        item
        for item in urgent
        if item.revalidation_result in {None, CapacityRevalidationResult.REVALIDATED}
    ]
    urgent_limit = (
        0
        if snapshot.urgent_path_state is not CapacityPathState.AVAILABLE
        else min(available, policy.max_urgent_slots - snapshot.active_urgent_slots)
    )
    urgent_selected = {item.identity_key for item in urgent_eligible[:urgent_limit]}
    remaining = available - len(urgent_selected)
    ordinary_limit = min(
        remaining, policy.ordinary_capacity_ceiling - snapshot.active_ordinary_slots
    )
    ordinary_eligible = [
        item
        for item in ordinary
        if item.revalidation_result in {None, CapacityRevalidationResult.REVALIDATED}
    ]
    protected = next(
        (
            item
            for item in ordinary_eligible
            if item.lane is PriorityLane.ROUTINE
            and item.observation.starvation_state is StarvationState.STARVED
            and item.revalidation_result is CapacityRevalidationResult.REVALIDATED
        ),
        None,
    )
    selected_ordinary: list[CapacityPopulationItem] = []
    if ordinary_limit and protected is not None:
        selected_ordinary.append(protected)
    selected_ordinary.extend(
        item for item in ordinary_eligible if item is not protected
    )
    selected_ordinary = selected_ordinary[:ordinary_limit]
    ordinary_selected = {item.identity_key for item in selected_ordinary}
    allocations: list[CapacityItemAllocation] = []
    for item in urgent + ordinary:
        if (
            item.capacity_class is CapacityClass.URGENT_RESERVED
            and snapshot.urgent_path_state is not CapacityPathState.AVAILABLE
        ):
            disposition = CapacityAllocationDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD
        elif (
            item.identity_key in urgent_selected
            or item.identity_key in ordinary_selected
        ):
            disposition = CapacityAllocationDisposition.GRANTED
        else:
            disposition = CapacityAllocationDisposition.CAPACITY_DEFERRED
        allocations.append(
            CapacityItemAllocation(
                item=item,
                disposition=disposition,
                protected_routine_grant=(
                    protected is item
                    and disposition is CapacityAllocationDisposition.GRANTED
                ),
            )
        )
    grants = sum(
        item.disposition is CapacityAllocationDisposition.GRANTED
        for item in allocations
    )
    return {"allocations": tuple(allocations), "unallocated_slots": available - grants}


def allocate_reserved_capacity(
    *, policy: ReservedCapacityPolicy, snapshot: CapacitySnapshot
) -> ReservedCapacityDecision:
    """Select exact population members; this pure function owns no queue effect."""

    if not isinstance(policy, ReservedCapacityPolicy) or not isinstance(
        snapshot, CapacitySnapshot
    ):
        raise SchedulingContractError("reserved capacity inputs must be typed")
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
    "CapacityAllocationDisposition",
    "CapacityClass",
    "CapacityItemAllocation",
    "CapacityPathState",
    "CapacityPopulationItem",
    "CapacityRevalidationEvidence",
    "CapacityRevalidationResult",
    "CapacitySnapshot",
    "CapacityWorkState",
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
    "calculate_urgency_deadline",
    "capacity_class_for_lane",
]
