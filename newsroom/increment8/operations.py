"""Bounded deterministic queue, lease, retry, quarantine and Handoff controls."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Self, TypeVar

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.increment8.readiness import (
    INCREMENT_8_READINESS,
    INCREMENT_8_READINESS_DIGEST,
)


class OperationalAuthorityError(ValueError):
    """Operational state differs from the frozen fixture Profile."""


_T = TypeVar("_T")


class Urgency(StrEnum):
    URGENT = "URGENT"
    TIME_SENSITIVE = "TIME_SENSITIVE"
    PLANNED = "PLANNED"
    ROUTINE = "ROUTINE"


class WorkState(StrEnum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    RETRY_PENDING = "RETRY_PENDING"
    COMPLETED = "COMPLETED"
    EXPLICITLY_CLOSED = "EXPLICITLY_CLOSED"
    QUARANTINED = "QUARANTINED"


class LeaseState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    ORPHANED = "ORPHANED"


class RetryClassification(StrEnum):
    RETRYABLE = "RETRYABLE"
    NON_RETRYABLE = "NON_RETRYABLE"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"


class QuarantineState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    RELEASED = "RELEASED"


class HandoffAnchorKind(StrEnum):
    ORIGINAL_REGISTRATION = "ORIGINAL_REGISTRATION"
    OBSERVED_AT_HARDENING = "OBSERVED_AT_HARDENING"


class HandoffOperationalStatus(StrEnum):
    ANCHORED_ORIGINAL = "ANCHORED_ORIGINAL"
    OBSERVED_ONLY = "OBSERVED_ONLY"
    GRANDFATHERED_UNANCHORED = "GRANDFATHERED_UNANCHORED"
    ANCHOR_MISMATCH = "ANCHOR_MISMATCH"


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise OperationalAuthorityError(f"{field} must be an integer >= {minimum}")
    return value


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 256:
        raise OperationalAuthorityError(f"{field} must be bounded text")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise OperationalAuthorityError(f"{field} contains control characters")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise OperationalAuthorityError(f"{field} must be a canonical digest") from exc


def _time(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise OperationalAuthorityError(f"{field} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise OperationalAuthorityError(f"{field} must be canonical UTC text") from exc
    if parsed.utcoffset() != timedelta(0):
        raise OperationalAuthorityError(f"{field} must be UTC")
    return value


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _canonical_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise OperationalAuthorityError("time must be UTC")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {name: _thaw(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _record(
    schema: str, id_field: str, prefix: str, payload: Mapping[str, object]
) -> tuple[str, bytes, str]:
    identity = digest_canonical({"schema_version": schema, "payload": payload})
    identifier = f"{prefix}:{identity.removeprefix('sha256:')}"
    raw = canonical_json_bytes(
        {"schema_version": schema, id_field: identifier, "payload": dict(payload)}
    )
    return identifier, raw, digest_bytes(raw)


def _decode(
    raw: bytes, schema: str, id_field: str, prefix: str
) -> tuple[str, Mapping[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OperationalAuthorityError("record bytes are not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise OperationalAuthorityError("record bytes are not canonical JSON")
    if (
        set(value) != {"schema_version", id_field, "payload"}
        or value["schema_version"] != schema
    ):
        raise OperationalAuthorityError("record envelope differs")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise OperationalAuthorityError("record payload differs")
    identifier, expected, _ = _record(schema, id_field, prefix, payload)
    if value[id_field] != identifier or expected != raw:
        raise OperationalAuthorityError("record identity differs")
    return identifier, MappingProxyType(payload)


@dataclass(frozen=True, slots=True)
class _Record:
    identifier: str
    canonical_bytes: bytes
    digest: str
    payload: Mapping[str, object]
    SCHEMA: ClassVar[str]
    ID_FIELD: ClassVar[str]
    PREFIX: ClassVar[str]

    @classmethod
    def build(cls, payload: Mapping[str, object]) -> Self:
        identifier, raw, record_digest = _record(
            cls.SCHEMA, cls.ID_FIELD, cls.PREFIX, payload
        )
        return cls(identifier, raw, record_digest, MappingProxyType(dict(payload)))

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        identifier, payload = _decode(raw, cls.SCHEMA, cls.ID_FIELD, cls.PREFIX)
        return cls(identifier, raw, digest_bytes(raw), payload)


@dataclass(frozen=True, slots=True)
class OperationalProfile(_Record):
    SCHEMA = "newsroom.increment8.operational-profile.v1"
    ID_FIELD = "profile_record_id"
    PREFIX = "profile"

    @property
    def profile_record_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class DueWork(_Record):
    SCHEMA = "newsroom.increment8.due-work.v1"
    ID_FIELD = "work_version_id"
    PREFIX = "work-version"

    @property
    def work_id(self) -> str:
        return str(self.payload["work_id"])


@dataclass(frozen=True, slots=True)
class WorkLease(_Record):
    SCHEMA = "newsroom.increment8.work-lease.v1"
    ID_FIELD = "lease_version_id"
    PREFIX = "lease-version"

    @property
    def lease_id(self) -> str:
        return str(self.payload["lease_id"])


@dataclass(frozen=True, slots=True)
class RetryFinding(_Record):
    SCHEMA = "newsroom.increment8.retry-finding.v1"
    ID_FIELD = "finding_id"
    PREFIX = "retry-finding"

    @property
    def finding_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class QuarantineRecord(_Record):
    SCHEMA = "newsroom.increment8.quarantine-record.v1"
    ID_FIELD = "quarantine_version_id"
    PREFIX = "quarantine-version"

    @property
    def quarantine_id(self) -> str:
        return str(self.payload["quarantine_id"])


@dataclass(frozen=True, slots=True)
class HandoffRegistrationAnchor(_Record):
    SCHEMA = "newsroom.increment8.handoff-registration-anchor.v1"
    ID_FIELD = "anchor_id"
    PREFIX = "handoff-anchor"

    @property
    def anchor_id(self) -> str:
        return self.identifier


@dataclass(frozen=True, slots=True)
class CapacityEvidence(_Record):
    SCHEMA = "newsroom.increment8.capacity-evidence.v1"
    ID_FIELD = "capacity_evidence_id"
    PREFIX = "capacity"


def build_operational_profile(
    *, approved_by_digest: str, approved_at: str
) -> OperationalProfile:
    payload = {
        "profile_id": INCREMENT_8_READINESS.operational_profile["profile_id"],
        "profile_definition": _thaw(INCREMENT_8_READINESS.operational_profile),
        "readiness_digest": INCREMENT_8_READINESS_DIGEST,
        "approved_by_digest": _digest(approved_by_digest, "approved_by_digest"),
        "approved_at": _time(approved_at, "approved_at"),
        "live_execution_authorised": False,
        "external_spend_authorised_pence": 0,
        "network_egress_destinations": 0,
        "live_credentials": 0,
    }
    return OperationalProfile.build(payload)


def enqueue_due_work(
    *,
    profile: OperationalProfile,
    logical_due_key: str,
    scope_kind: str,
    urgency: Urgency,
    due_at: str,
    deadline_at: str,
    authority_version_digest: str,
) -> DueWork:
    if not isinstance(profile, OperationalProfile) or not isinstance(urgency, Urgency):
        raise OperationalAuthorityError("due work requires typed Profile and urgency")
    kind = _token(scope_kind, "scope_kind")
    if kind not in INCREMENT_8_READINESS.operational_profile["scope_kinds"]:
        raise OperationalAuthorityError("scope_kind is outside the frozen Profile")
    due = _time(due_at, "due_at")
    deadline = _time(deadline_at, "deadline_at")
    if _dt(deadline) < _dt(due):
        raise OperationalAuthorityError("deadline precedes due time")
    key = _token(logical_due_key, "logical_due_key")
    work_id = "work:" + digest_canonical(
        {"profile_digest": profile.digest, "logical_due_key": key}
    ).removeprefix("sha256:")
    payload = {
        "work_id": work_id,
        "state_version": 1,
        "profile_record_id": profile.profile_record_id,
        "profile_digest": profile.digest,
        "logical_due_key": key,
        "scope_kind": kind,
        "urgency": urgency.value,
        "state": WorkState.QUEUED.value,
        "attempt_count": 0,
        "due_at": due,
        "deadline_at": deadline,
        "previous_digest": None,
        "authority_version_digest": _digest(
            authority_version_digest, "authority_version_digest"
        ),
        "editorial_rejection": False,
        "model_scheduling_used": False,
    }
    return DueWork.build(payload)


def transition_work(
    previous: DueWork,
    *,
    state: WorkState,
    attempt_count: int | None = None,
) -> DueWork:
    if not isinstance(previous, DueWork) or not isinstance(state, WorkState):
        raise OperationalAuthorityError("work transition requires typed state")
    current = WorkState(str(previous.payload["state"]))
    allowed = {
        WorkState.QUEUED: {
            WorkState.LEASED,
            WorkState.EXPLICITLY_CLOSED,
            WorkState.QUARANTINED,
        },
        WorkState.LEASED: {
            WorkState.RETRY_PENDING,
            WorkState.COMPLETED,
            WorkState.QUARANTINED,
        },
        WorkState.RETRY_PENDING: {
            WorkState.LEASED,
            WorkState.EXPLICITLY_CLOSED,
            WorkState.QUARANTINED,
        },
        WorkState.COMPLETED: set(),
        WorkState.EXPLICITLY_CLOSED: set(),
        WorkState.QUARANTINED: set(),
    }
    if state not in allowed[current]:
        raise OperationalAuthorityError("work state transition is not allowed")
    old_attempt = int(previous.payload["attempt_count"])
    attempts = (
        old_attempt
        if attempt_count is None
        else _integer(attempt_count, "attempt_count")
    )
    if state is WorkState.LEASED:
        if attempts != old_attempt + 1:
            raise OperationalAuthorityError("lease must advance exactly one attempt")
    elif attempts != old_attempt:
        raise OperationalAuthorityError("non-lease transition changed attempt_count")
    payload = dict(previous.payload)
    payload.update(
        state_version=int(previous.payload["state_version"]) + 1,
        state=state.value,
        attempt_count=attempts,
        previous_digest=previous.digest,
    )
    return DueWork.build(payload)


def acquire_lease(
    *,
    work: DueWork,
    owner_digest: str,
    acquired_at: str,
    progress_digest: str,
    authority_deadline_at: str | None = None,
) -> WorkLease:
    if not isinstance(work, DueWork) or WorkState(str(work.payload["state"])) not in {
        WorkState.QUEUED,
        WorkState.RETRY_PENDING,
    }:
        raise OperationalAuthorityError("only ready work can be leased")
    acquired = _time(acquired_at, "acquired_at")
    deadline = _dt(str(work.payload["deadline_at"]))
    if _dt(acquired) > deadline:
        raise OperationalAuthorityError("work deadline has expired")
    if (
        work.payload["state"] == WorkState.RETRY_PENDING.value
        and authority_deadline_at is None
    ):
        raise OperationalAuthorityError(
            "retry lease requires its exact authority deadline"
        )
    authority_deadline = (
        deadline
        if authority_deadline_at is None
        else min(deadline, _dt(_time(authority_deadline_at, "authority_deadline_at")))
    )
    if _dt(acquired) > authority_deadline:
        raise OperationalAuthorityError("lease authority deadline has expired")
    profile = INCREMENT_8_READINESS.operational_profile["execution"]
    expires = _canonical_time(
        min(
            authority_deadline,
            _dt(acquired) + timedelta(seconds=int(profile["lease_seconds"])),
        )
    )
    maximum = _canonical_time(
        min(
            authority_deadline,
            _dt(acquired) + timedelta(seconds=int(profile["maximum_lease_seconds"])),
        )
    )
    lease_id = "lease:" + digest_canonical(
        {
            "work_id": work.work_id,
            "attempt_count": int(work.payload["attempt_count"]) + 1,
        }
    ).removeprefix("sha256:")
    return WorkLease.build(
        {
            "lease_id": lease_id,
            "lease_version": 1,
            "work_id": work.work_id,
            "owner_digest": _digest(owner_digest, "owner_digest"),
            "progress_digest": _digest(progress_digest, "progress_digest"),
            "acquired_at": acquired,
            "expires_at": expires,
            "maximum_expires_at": maximum,
            "authority_deadline_at": _canonical_time(authority_deadline),
            "status": LeaseState.ACTIVE.value,
            "renewed_at": None,
            "closed_at": None,
            "previous_digest": None,
        }
    )


def renew_lease(
    lease: WorkLease,
    *,
    progress_digest: str,
    renewed_at: str,
    authority_deadline_at: str | None = None,
) -> WorkLease:
    if (
        not isinstance(lease, WorkLease)
        or lease.payload["status"] != LeaseState.ACTIVE.value
    ):
        raise OperationalAuthorityError("only an active lease can be renewed")
    progress = _digest(progress_digest, "progress_digest")
    if progress == lease.payload["progress_digest"]:
        raise OperationalAuthorityError("lease renewal requires valid progress")
    renewed = _time(renewed_at, "renewed_at")
    retained_authority_deadline = lease.payload.get("authority_deadline_at")
    if retained_authority_deadline is None and authority_deadline_at is None:
        raise OperationalAuthorityError(
            "legacy lease renewal requires its authority deadline"
        )
    authority_deadline = _time(
        retained_authority_deadline
        if retained_authority_deadline is not None
        else authority_deadline_at,
        "authority_deadline_at",
    )
    if authority_deadline_at is not None and _dt(
        _time(authority_deadline_at, "authority_deadline_at")
    ) != _dt(authority_deadline):
        raise OperationalAuthorityError("lease authority deadline differs")
    effective_expiry = min(
        _dt(str(lease.payload["expires_at"])), _dt(authority_deadline)
    )
    if (
        _dt(renewed) < _dt(str(lease.payload["acquired_at"]))
        or _dt(renewed) > effective_expiry
    ):
        raise OperationalAuthorityError("expired lease cannot be renewed")
    seconds = int(
        INCREMENT_8_READINESS.operational_profile["execution"]["lease_renewal_seconds"]
    )  # type: ignore[index]
    effective_maximum = min(
        _dt(str(lease.payload["maximum_expires_at"])), _dt(authority_deadline)
    )
    expires = max(
        effective_expiry,
        min(
            effective_maximum,
            _dt(renewed) + timedelta(seconds=seconds),
        ),
    )
    payload = dict(lease.payload)
    payload.update(
        lease_version=int(lease.payload["lease_version"]) + 1,
        progress_digest=progress,
        expires_at=_canonical_time(expires),
        maximum_expires_at=_canonical_time(effective_maximum),
        authority_deadline_at=_canonical_time(_dt(authority_deadline)),
        renewed_at=renewed,
        previous_digest=lease.digest,
    )
    return WorkLease.build(payload)


def close_lease(lease: WorkLease, state: LeaseState, *, closed_at: str) -> WorkLease:
    if not isinstance(lease, WorkLease) or state not in {
        LeaseState.RELEASED,
        LeaseState.ORPHANED,
    }:
        raise OperationalAuthorityError("lease close state differs")
    if lease.payload["status"] != LeaseState.ACTIVE.value:
        raise OperationalAuthorityError("lease is not active")
    closed = _time(closed_at, "closed_at")
    if _dt(closed) < _dt(str(lease.payload["acquired_at"])):
        raise OperationalAuthorityError("lease closure predates acquisition")
    if state is LeaseState.RELEASED and _dt(closed) > _dt(
        str(lease.payload["expires_at"])
    ):
        raise OperationalAuthorityError("released lease closure exceeds expiry")
    payload = dict(lease.payload)
    payload.update(
        lease_version=int(lease.payload["lease_version"]) + 1,
        status=state.value,
        closed_at=closed,
        previous_digest=lease.digest,
    )
    return WorkLease.build(payload)


def build_retry_finding(
    *,
    work: DueWork,
    classification: RetryClassification,
    dependency_scope: str,
    first_attempt_at: str,
    failed_at: str,
) -> RetryFinding:
    if not isinstance(work, DueWork) or not isinstance(
        classification, RetryClassification
    ):
        raise OperationalAuthorityError(
            "retry Finding requires typed work and classification"
        )
    attempt = int(work.payload["attempt_count"])
    if attempt < 1:
        raise OperationalAuthorityError("retry Finding requires a recorded attempt")
    retry = INCREMENT_8_READINESS.operational_profile["retry"]
    maximum = int(retry["maximum_attempts"])
    first = _time(first_attempt_at, "first_attempt_at")
    failed = _time(failed_at, "failed_at")
    if _dt(failed) < _dt(first):
        raise OperationalAuthorityError("retry failure predates first attempt")
    maximum_elapsed = int(retry["maximum_elapsed_seconds"])
    elapsed = _dt(failed) - _dt(first)
    next_due: str | None = None
    exhausted = attempt >= maximum or elapsed >= timedelta(seconds=maximum_elapsed)
    if classification is RetryClassification.RETRYABLE and not exhausted:
        base = int(retry["base_backoff_seconds"])
        cap = int(retry["maximum_backoff_seconds"])
        delay = min(cap, base * (2 ** (attempt - 1)))
        candidate_due = _dt(failed) + timedelta(seconds=delay)
        if candidate_due < _dt(first) + timedelta(seconds=maximum_elapsed):
            next_due = _canonical_time(candidate_due)
        else:
            exhausted = True
    payload = {
        "work_id": work.work_id,
        "work_digest": work.digest,
        "attempt_number": attempt,
        "classification": classification.value,
        "dependency_scope": _token(dependency_scope, "dependency_scope"),
        "first_attempt_at": first,
        "failed_at": failed,
        "elapsed_microseconds": elapsed // timedelta(microseconds=1),
        "next_due_at": next_due,
        "retry_exhausted": exhausted,
        "health_clock_refreshed": False,
        "editorial_no_news": False,
        "silent_fallback": False,
    }
    return RetryFinding.build(payload)


def quarantine_scope(
    *, scope_id: str, reason_class: str, evidence_digest: str, recorded_at: str
) -> QuarantineRecord:
    identity = "quarantine:" + digest_canonical({"scope_id": scope_id}).removeprefix(
        "sha256:"
    )
    return QuarantineRecord.build(
        {
            "quarantine_id": identity,
            "quarantine_version": 1,
            "scope_id": _token(scope_id, "scope_id"),
            "reason_class": _token(reason_class, "reason_class"),
            "status": QuarantineState.ACTIVE.value,
            "authorised_by_digest": None,
            "evidence_digest": _digest(evidence_digest, "evidence_digest"),
            "recorded_at": _time(recorded_at, "recorded_at"),
            "previous_digest": None,
            "automatic_release": False,
        }
    )


def approve_quarantine_release(
    previous: QuarantineRecord,
    *,
    authorised_by_digest: str,
    repair_evidence_digest: str,
    decided_at: str,
) -> QuarantineRecord:
    if (
        not isinstance(previous, QuarantineRecord)
        or previous.payload["status"] != QuarantineState.ACTIVE.value
    ):
        raise OperationalAuthorityError("quarantine is not active")
    payload = dict(previous.payload)
    payload.update(
        quarantine_version=int(previous.payload["quarantine_version"]) + 1,
        status=QuarantineState.RELEASE_APPROVED.value,
        authorised_by_digest=_digest(authorised_by_digest, "authorised_by_digest"),
        evidence_digest=_digest(repair_evidence_digest, "repair_evidence_digest"),
        recorded_at=_time(decided_at, "decided_at"),
        previous_digest=previous.digest,
    )
    return QuarantineRecord.build(payload)


def build_capacity_evidence(
    *,
    scenario_counts: Mapping[str, int],
    cpu_cores: int,
    memory_mib: int,
    free_disk_mib: int,
    peak_queue_items: int,
    urgent_capacity_items: int,
    worker_throughput_per_minute: int,
    operator_minutes: int,
) -> CapacityEvidence:
    expected = ("AVERAGE", "FAILURE_HEAVY", "NO_CHANGE_HEAVY", "PEAK")
    if tuple(sorted(scenario_counts)) != expected:
        raise OperationalAuthorityError("capacity scenario inventory differs")
    scenarios = {name: _integer(scenario_counts[name], name) for name in expected}
    capacity = INCREMENT_8_READINESS.operational_profile["capacity"]
    execution = INCREMENT_8_READINESS.operational_profile["execution"]
    checked = {
        "cpu_cores": _integer(cpu_cores, "cpu_cores"),
        "memory_mib": _integer(memory_mib, "memory_mib"),
        "free_disk_mib": _integer(free_disk_mib, "free_disk_mib"),
        "peak_queue_items": _integer(peak_queue_items, "peak_queue_items"),
        "urgent_capacity_items": _integer(
            urgent_capacity_items, "urgent_capacity_items"
        ),
        "worker_throughput_per_minute": _integer(
            worker_throughput_per_minute, "worker_throughput_per_minute", minimum=1
        ),
        "operator_minutes": _integer(operator_minutes, "operator_minutes"),
    }
    queue_capacity = int(execution["queue_capacity_items"])
    required_headroom = int(capacity["peak_queue_headroom_percent"])
    headroom = (queue_capacity - checked["peak_queue_items"]) * 100 // queue_capacity
    passed = (
        checked["cpu_cores"] >= int(capacity["minimum_cpu_cores"])
        and checked["memory_mib"] >= int(capacity["minimum_memory_mib"])
        and checked["free_disk_mib"] >= int(capacity["minimum_free_disk_mib"])
        and checked["peak_queue_items"] <= queue_capacity
        and checked["urgent_capacity_items"] >= int(execution["urgent_reserve_items"])
        and headroom >= required_headroom
    )
    payload = {
        "scenario_counts": scenarios,
        **checked,
        "queue_capacity_items": queue_capacity,
        "observed_headroom_percent": headroom,
        "required_headroom_percent": required_headroom,
        "status": "PASS" if passed else "FAIL",
        "live_execution_authorised": False,
    }
    return CapacityEvidence.build(payload)


def _handoff_anchor(
    *,
    handoff_id: str,
    candidate_version_id: str,
    governing_manifest_digest: str,
    sink_id: str,
    max_attempts: int,
    kind: HandoffAnchorKind,
    recorded_at: str,
) -> HandoffRegistrationAnchor:
    identity_payload = {
        "handoff_id": _token(handoff_id, "handoff_id"),
        "candidate_version_id": _token(candidate_version_id, "candidate_version_id"),
        "governing_manifest_digest": _digest(
            governing_manifest_digest, "governing_manifest_digest"
        ),
        "sink_id": _token(sink_id, "sink_id"),
        "max_attempts": _integer(max_attempts, "max_attempts", minimum=1),
    }
    if int(identity_payload["max_attempts"]) > 100:
        raise OperationalAuthorityError("max_attempts exceeds Handoff bound")
    payload = {
        **identity_payload,
        "handoff_identity_digest": digest_canonical(identity_payload),
        "anchor_kind": kind.value,
        "recorded_at": _time(recorded_at, "recorded_at"),
        "operational_eligible": kind is HandoffAnchorKind.ORIGINAL_REGISTRATION,
        "original_value_claimed": kind is HandoffAnchorKind.ORIGINAL_REGISTRATION,
        "production_activation_authorised": False,
    }
    return HandoffRegistrationAnchor.build(payload)


def _insert_handoff_anchor(
    connection: sqlite3.Connection, anchor: HandoffRegistrationAnchor
) -> None:
    row = connection.execute(
        "SELECT anchor_bytes FROM handoff_registration_anchors WHERE handoff_id=?",
        (anchor.payload["handoff_id"],),
    ).fetchone()
    if row is not None:
        if bytes(row[0]) != anchor.canonical_bytes:
            raise OperationalAuthorityError("Handoff registration anchor conflicts")
        return
    connection.execute(
        "INSERT INTO handoff_registration_anchors VALUES(?,?,?,?,?,?,?,?,?)",
        (
            anchor.payload["handoff_id"],
            anchor.anchor_id,
            anchor.canonical_bytes,
            anchor.digest,
            anchor.payload["handoff_identity_digest"],
            anchor.payload["max_attempts"],
            anchor.payload["anchor_kind"],
            anchor.payload["recorded_at"],
            int(bool(anchor.payload["operational_eligible"])),
        ),
    )


def anchor_new_handoff_registration(
    connection: sqlite3.Connection, handoff: object, *, registered_at: str
) -> None:
    """Atomically anchor a new v17 Handoff when the v31 table is present."""
    present = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='handoff_registration_anchors'"
    ).fetchone()
    if present is None:
        return
    profile = connection.execute("SELECT COUNT(*) FROM operational_profiles").fetchone()
    if profile != (1,):
        # A v31 database alone grants no operational scope. Registrations made
        # without the exact approved Profile remain visibly unanchored.
        return
    anchor = _handoff_anchor(
        handoff_id=str(handoff.handoff_id),
        candidate_version_id=str(handoff.candidate_version_id),
        governing_manifest_digest=str(handoff.governing_manifest_digest),
        sink_id=str(handoff.sink_id),
        max_attempts=int(handoff.max_attempts),
        kind=HandoffAnchorKind.ORIGINAL_REGISTRATION,
        recorded_at=registered_at,
    )
    _insert_handoff_anchor(connection, anchor)


def register_anchored_handoff(
    connection: sqlite3.Connection, handoff: object, *, registered_at: str
) -> object:
    """Register a pristine v17 Handoff and its v31 anchor atomically.

    The older v17 store remains byte-for-byte stable. Operational callers use
    this explicit v31 entry point; unprofiled legacy registrations stay visibly
    grandfathered and operationally ineligible.
    """
    from newsroom.increment6.handoffs import EVALUATION_HANDOFF, create_handoff

    profile = connection.execute("SELECT COUNT(*) FROM operational_profiles").fetchone()
    if profile != (1,) or connection.in_transaction:
        raise OperationalAuthorityError(
            "anchored Handoff registration requires one Profile and an idle connection"
        )
    try:
        pristine = create_handoff(
            str(handoff.candidate_version_id),
            str(handoff.governing_manifest_digest),
            str(handoff.sink_id),
            max_attempts=int(handoff.max_attempts),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise OperationalAuthorityError("Handoff registration value differs") from exc
    if handoff != pristine:
        raise OperationalAuthorityError(
            "anchored registration requires a pristine Handoff"
        )
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "INSERT OR IGNORE INTO evaluation_handoffs("
            "handoff_id,schema_identity,candidate_version_id,governing_manifest_digest,"
            "sink_id,max_attempts,transport_state,retry_exhausted,ambiguity_reason,"
            "evaluation_only,publication_authority,evidence_authority) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                handoff.handoff_id,
                EVALUATION_HANDOFF,
                handoff.candidate_version_id,
                handoff.governing_manifest_digest,
                handoff.sink_id,
                handoff.max_attempts,
                handoff.state.value,
                int(handoff.retry_exhausted),
                handoff.ambiguity_reason,
                1,
                0,
                0,
            ),
        )
        retained = connection.execute(
            "SELECT candidate_version_id,governing_manifest_digest,sink_id,max_attempts,"
            "transport_state,retry_exhausted,ambiguity_reason FROM evaluation_handoffs "
            "WHERE handoff_id=?",
            (handoff.handoff_id,),
        ).fetchone()
        if retained != (
            handoff.candidate_version_id,
            handoff.governing_manifest_digest,
            handoff.sink_id,
            handoff.max_attempts,
            handoff.state.value,
            int(handoff.retry_exhausted),
            handoff.ambiguity_reason,
        ):
            raise OperationalAuthorityError("Handoff replay conflicts with authority")
        anchor_new_handoff_registration(
            connection, handoff, registered_at=_time(registered_at, "registered_at")
        )
        connection.execute("COMMIT")
        return handoff
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def record_observed_handoff_at_hardening(
    connection: sqlite3.Connection, *, handoff_id: str, observed_at: str
) -> HandoffRegistrationAnchor:
    row = connection.execute(
        "SELECT candidate_version_id,governing_manifest_digest,sink_id,max_attempts "
        "FROM evaluation_handoffs WHERE handoff_id=?",
        (_token(handoff_id, "handoff_id"),),
    ).fetchone()
    if row is None:
        raise OperationalAuthorityError("Handoff is absent")
    anchor = _handoff_anchor(
        handoff_id=handoff_id,
        candidate_version_id=str(row[0]),
        governing_manifest_digest=str(row[1]),
        sink_id=str(row[2]),
        max_attempts=int(row[3]),
        kind=HandoffAnchorKind.OBSERVED_AT_HARDENING,
        recorded_at=observed_at,
    )
    _insert_handoff_anchor(connection, anchor)
    return anchor


def handoff_operational_status(
    connection: sqlite3.Connection,
    handoff_id: str,
    *,
    expected_anchor_digest: str | None = None,
) -> HandoffOperationalStatus:
    row = connection.execute(
        "SELECT h.candidate_version_id,h.governing_manifest_digest,h.sink_id,h.max_attempts,"
        "a.anchor_id,a.anchor_bytes,a.anchor_digest,a.handoff_identity_digest,a.max_attempts,"
        "a.anchor_kind,a.recorded_at,a.operational_eligible "
        "FROM evaluation_handoffs h LEFT JOIN handoff_registration_anchors a "
        "ON a.handoff_id=h.handoff_id WHERE h.handoff_id=?",
        (_token(handoff_id, "handoff_id"),),
    ).fetchone()
    if row is None:
        raise OperationalAuthorityError("Handoff is absent")
    if row[4] is None:
        return HandoffOperationalStatus.GRANDFATHERED_UNANCHORED
    try:
        anchor = HandoffRegistrationAnchor.from_canonical_bytes(bytes(row[5]))
    except OperationalAuthorityError:
        return HandoffOperationalStatus.ANCHOR_MISMATCH
    scalar_fields = {
        "anchor_id": row[4],
        "anchor_digest": row[6],
        "handoff_identity_digest": row[7],
        "max_attempts": row[8],
        "anchor_kind": row[9],
        "recorded_at": row[10],
        "operational_eligible": bool(row[11]),
    }
    expected_scalars = {
        "anchor_id": anchor.anchor_id,
        "anchor_digest": anchor.digest,
        "handoff_identity_digest": anchor.payload["handoff_identity_digest"],
        "max_attempts": anchor.payload["max_attempts"],
        "anchor_kind": anchor.payload["anchor_kind"],
        "recorded_at": anchor.payload["recorded_at"],
        "operational_eligible": anchor.payload["operational_eligible"],
    }
    if scalar_fields != expected_scalars:
        return HandoffOperationalStatus.ANCHOR_MISMATCH
    if expected_anchor_digest is not None and anchor.digest != _digest(
        expected_anchor_digest, "expected_anchor_digest"
    ):
        return HandoffOperationalStatus.ANCHOR_MISMATCH
    expected = {
        "candidate_version_id": row[0],
        "governing_manifest_digest": row[1],
        "sink_id": row[2],
        "max_attempts": row[3],
    }
    if any(anchor.payload[name] != value for name, value in expected.items()):
        return HandoffOperationalStatus.ANCHOR_MISMATCH
    if anchor.payload["anchor_kind"] == HandoffAnchorKind.ORIGINAL_REGISTRATION.value:
        return HandoffOperationalStatus.ANCHORED_ORIGINAL
    return HandoffOperationalStatus.OBSERVED_ONLY


class OperationalAuthority:
    """Single-connection append-only fixture operational authority."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection) or connection.in_transaction:
            raise OperationalAuthorityError(
                "authority requires an idle SQLite connection"
            )
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise OperationalAuthorityError("authority requires foreign keys enabled")
        if connection.execute("PRAGMA user_version").fetchone()[0] < 31:
            raise OperationalAuthorityError(
                "operational authority requires schema v31 or later"
            )
        self._connection = connection

    def _write(self, operation: Callable[[], _T]) -> _T:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
            self._connection.execute("COMMIT")
            return result
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def _insert(self, sql: str, values: tuple[object, ...]) -> int:
        return self._write(lambda: self._connection.execute(sql, values).rowcount)

    def _leased_work_authority_deadline(self, work: DueWork) -> datetime:
        if work.payload["state"] != WorkState.LEASED.value:
            raise OperationalAuthorityError("lease work is not LEASED")
        authority_deadline = _dt(str(work.payload["deadline_at"]))
        predecessor_row = self._connection.execute(
            "SELECT work_bytes FROM due_work WHERE work_id=? AND state_version=?",
            (work.work_id, int(work.payload["state_version"]) - 1),
        ).fetchone()
        if predecessor_row is None:
            raise OperationalAuthorityError("lease work predecessor is absent")
        predecessor = DueWork.from_canonical_bytes(bytes(predecessor_row[0]))
        if predecessor.payload["state"] != WorkState.RETRY_PENDING.value:
            return authority_deadline
        retry_row = self._connection.execute(
            "SELECT finding_bytes FROM retry_findings WHERE work_id=? "
            "AND attempt_number=?",
            (predecessor.work_id, predecessor.payload["attempt_count"]),
        ).fetchone()
        if retry_row is None:
            raise OperationalAuthorityError("lease retry authority is absent")
        retry = RetryFinding.from_canonical_bytes(bytes(retry_row[0]))
        return min(
            authority_deadline,
            _dt(str(retry.payload["first_attempt_at"]))
            + timedelta(
                seconds=int(
                    INCREMENT_8_READINESS.operational_profile["retry"][
                        "maximum_elapsed_seconds"
                    ]
                )
            ),
        )

    def register_profile(self, profile: OperationalProfile) -> None:
        if (
            not isinstance(profile, OperationalProfile)
            or OperationalProfile.from_canonical_bytes(profile.canonical_bytes)
            != profile
        ):
            raise OperationalAuthorityError("Profile is forged or non-canonical")
        if profile.payload["profile_definition"] != _thaw(
            INCREMENT_8_READINESS.operational_profile
        ):
            raise OperationalAuthorityError("Profile differs from frozen values")
        self._insert(
            "INSERT INTO operational_profiles VALUES(?,?,?,?,?,?,?)",
            (
                profile.profile_record_id,
                profile.canonical_bytes,
                profile.digest,
                profile.payload["readiness_digest"],
                profile.payload["approved_by_digest"],
                profile.payload["approved_at"],
                0,
            ),
        )

    def append_work(self, work: DueWork) -> None:
        if (
            not isinstance(work, DueWork)
            or DueWork.from_canonical_bytes(work.canonical_bytes) != work
        ):
            raise OperationalAuthorityError("work is forged or non-canonical")
        if work.payload["state"] == WorkState.LEASED.value:
            raise OperationalAuthorityError(
                "LEASED work must be committed by lease acquisition"
            )
        version = int(work.payload["state_version"])
        if version == 1:
            profile = self._connection.execute(
                "SELECT profile_digest,profile_bytes FROM operational_profiles "
                "WHERE profile_id=?",
                (work.payload["profile_record_id"],),
            ).fetchone()
            if profile is None or profile[0] != work.payload["profile_digest"]:
                raise OperationalAuthorityError("work Profile authority differs")
            retained_profile = OperationalProfile.from_canonical_bytes(
                bytes(profile[1])
            )
            expected_origin = enqueue_due_work(
                profile=retained_profile,
                logical_due_key=str(work.payload["logical_due_key"]),
                scope_kind=str(work.payload["scope_kind"]),
                urgency=Urgency(str(work.payload["urgency"])),
                due_at=str(work.payload["due_at"]),
                deadline_at=str(work.payload["deadline_at"]),
                authority_version_digest=str(work.payload["authority_version_digest"]),
            )
            if expected_origin != work:
                raise OperationalAuthorityError("initial work record differs")
        else:
            previous = self._connection.execute(
                "SELECT work_digest,work_bytes FROM due_work WHERE work_id=? AND state_version=?",
                (work.work_id, version - 1),
            ).fetchone()
            if previous is None or previous[0] != work.payload["previous_digest"]:
                raise OperationalAuthorityError("work predecessor differs")
            retained = DueWork.from_canonical_bytes(bytes(previous[1]))
            if retained.payload["state"] == WorkState.LEASED.value:
                raise OperationalAuthorityError(
                    "LEASED work must transition with lease closure"
                )
            expected = transition_work(
                retained,
                state=WorkState(str(work.payload["state"])),
                attempt_count=int(work.payload["attempt_count"]),
            )
            if expected != work:
                raise OperationalAuthorityError("work transition differs")
            if work.payload["state"] == WorkState.RETRY_PENDING.value:
                finding = self._connection.execute(
                    "SELECT finding_bytes FROM retry_findings WHERE work_id=? "
                    "AND attempt_number=?",
                    (retained.work_id, retained.payload["attempt_count"]),
                ).fetchone()
                if finding is None:
                    raise OperationalAuthorityError(
                        "retry transition lacks its Finding"
                    )
                retained_finding = RetryFinding.from_canonical_bytes(bytes(finding[0]))
                if (
                    retained_finding.payload["work_digest"] != retained.digest
                    or retained_finding.payload["classification"]
                    != RetryClassification.RETRYABLE.value
                    or retained_finding.payload["retry_exhausted"] is not False
                    or retained_finding.payload["next_due_at"] is None
                ):
                    raise OperationalAuthorityError("retry transition Finding differs")
        values = (
            work.work_id,
            work.payload["state_version"],
            work.canonical_bytes,
            work.digest,
            work.payload["profile_record_id"],
            work.payload["logical_due_key"],
            work.payload["scope_kind"],
            work.payload["urgency"],
            work.payload["state"],
            work.payload["attempt_count"],
            work.payload["due_at"],
            work.payload["deadline_at"],
            work.payload["previous_digest"],
            work.payload["authority_version_digest"],
        )
        if version == 1:
            execution = INCREMENT_8_READINESS.operational_profile["execution"]
            queue_capacity = int(execution["queue_capacity_items"])
            non_urgent_limit = queue_capacity - int(execution["urgent_reserve_items"])
            inserted = self._insert(
                "INSERT INTO due_work SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,? WHERE "
                "(SELECT COUNT(*) FROM due_work d WHERE d.state_version=("
                "SELECT MAX(x.state_version) FROM due_work x WHERE x.work_id=d.work_id) "
                "AND d.state IN('QUEUED','LEASED','RETRY_PENDING')) < ? AND "
                "(?='URGENT' OR (SELECT COUNT(*) FROM due_work d WHERE d.state_version=("
                "SELECT MAX(x.state_version) FROM due_work x WHERE x.work_id=d.work_id) "
                "AND d.state IN('QUEUED','LEASED','RETRY_PENDING') "
                "AND d.urgency!='URGENT') < ?)",
                (*values, queue_capacity, work.payload["urgency"], non_urgent_limit),
            )
            if inserted != 1:
                raise OperationalAuthorityError(
                    "queue capacity or urgent reserve is exhausted"
                )
            return
        inserted = self._insert(
            "INSERT INTO due_work SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,? WHERE "
            "EXISTS(SELECT 1 FROM due_work d WHERE d.work_id=? "
            "AND d.work_digest=? AND d.state_version=(SELECT MAX(x.state_version) "
            "FROM due_work x WHERE x.work_id=d.work_id)) AND "
            "(? != 'LEASED' OR NOT EXISTS(SELECT 1 FROM work_leases l "
            "WHERE l.work_id=? AND l.lease_version=(SELECT MAX(x.lease_version) "
            "FROM work_leases x WHERE x.lease_id=l.lease_id) AND l.status='ACTIVE'))",
            (
                *values,
                retained.work_id,
                retained.digest,
                retained.payload["state"],
                retained.work_id,
            ),
        )
        if inserted != 1:
            raise OperationalAuthorityError(
                "work predecessor changed or active lease remains"
            )

    def append_lease(self, lease: WorkLease) -> None:
        if (
            not isinstance(lease, WorkLease)
            or WorkLease.from_canonical_bytes(lease.canonical_bytes) != lease
        ):
            raise OperationalAuthorityError("lease is forged or non-canonical")
        version = int(lease.payload["lease_version"])
        lease_values = (
            lease.lease_id,
            lease.payload["lease_version"],
            lease.canonical_bytes,
            lease.digest,
            lease.payload["work_id"],
            lease.payload["owner_digest"],
            lease.payload["progress_digest"],
            lease.payload["acquired_at"],
            lease.payload["expires_at"],
            lease.payload["maximum_expires_at"],
            lease.payload["status"],
            lease.payload["previous_digest"],
        )
        if version == 1:
            work_row = self._connection.execute(
                "SELECT work_bytes FROM due_work WHERE work_id=? "
                "ORDER BY state_version DESC LIMIT 1",
                (lease.payload["work_id"],),
            ).fetchone()
            if work_row is None:
                raise OperationalAuthorityError("lease work is absent")
            retained_work = DueWork.from_canonical_bytes(bytes(work_row[0]))
            expected = acquire_lease(
                work=retained_work,
                owner_digest=str(lease.payload["owner_digest"]),
                acquired_at=str(lease.payload["acquired_at"]),
                progress_digest=str(lease.payload["progress_digest"]),
                authority_deadline_at=str(lease.payload["authority_deadline_at"]),
            )
            if expected != lease:
                raise OperationalAuthorityError("lease acquisition differs")
            limit = int(
                INCREMENT_8_READINESS.operational_profile["execution"][
                    "host_concurrency"
                ]
            )

            def commit_acquisition() -> None:
                latest_row = self._connection.execute(
                    "SELECT work_bytes FROM due_work WHERE work_id=? "
                    "ORDER BY state_version DESC LIMIT 1",
                    (lease.payload["work_id"],),
                ).fetchone()
                if latest_row is None:
                    raise OperationalAuthorityError("lease work is absent")
                latest = DueWork.from_canonical_bytes(bytes(latest_row[0]))
                if latest != retained_work:
                    raise OperationalAuthorityError("lease work authority changed")
                acquired = _dt(str(lease.payload["acquired_at"]))
                if acquired > _dt(str(latest.payload["deadline_at"])):
                    raise OperationalAuthorityError("work deadline has expired")
                if latest.payload["state"] == WorkState.QUEUED.value:
                    expected_authority_deadline = _canonical_time(
                        _dt(str(latest.payload["deadline_at"]))
                    )
                    if acquired < _dt(str(latest.payload["due_at"])):
                        raise OperationalAuthorityError("queued work is not due")
                elif latest.payload["state"] == WorkState.RETRY_PENDING.value:
                    retry_row = self._connection.execute(
                        "SELECT finding_bytes FROM retry_findings WHERE work_id=? "
                        "AND attempt_number=?",
                        (latest.work_id, latest.payload["attempt_count"]),
                    ).fetchone()
                    if retry_row is None:
                        raise OperationalAuthorityError("retry Finding is absent")
                    finding = RetryFinding.from_canonical_bytes(bytes(retry_row[0]))
                    next_due = finding.payload["next_due_at"]
                    retry_horizon = _dt(
                        str(finding.payload["first_attempt_at"])
                    ) + timedelta(
                        seconds=int(
                            INCREMENT_8_READINESS.operational_profile["retry"][
                                "maximum_elapsed_seconds"
                            ]
                        )
                    )
                    expected_authority_deadline = _canonical_time(
                        min(_dt(str(latest.payload["deadline_at"])), retry_horizon)
                    )
                    if (
                        finding.payload["work_digest"]
                        != latest.payload["previous_digest"]
                        or finding.payload["classification"]
                        != RetryClassification.RETRYABLE.value
                        or finding.payload["retry_exhausted"] is not False
                        or next_due is None
                        or acquired < _dt(str(next_due))
                        or acquired >= retry_horizon
                    ):
                        raise OperationalAuthorityError("retry backoff is not due")
                else:
                    raise OperationalAuthorityError("only ready work can be leased")
                if (
                    lease.payload["authority_deadline_at"]
                    != expected_authority_deadline
                    or _dt(str(lease.payload["expires_at"]))
                    > _dt(expected_authority_deadline)
                    or _dt(str(lease.payload["maximum_expires_at"]))
                    > _dt(expected_authority_deadline)
                ):
                    raise OperationalAuthorityError("lease authority bound differs")
                if self.active_lease_count() >= limit:
                    raise OperationalAuthorityError("host concurrency is exhausted")
                self._connection.execute(
                    "INSERT INTO work_leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    lease_values,
                )
                leased_work = transition_work(
                    latest,
                    state=WorkState.LEASED,
                    attempt_count=int(latest.payload["attempt_count"]) + 1,
                )
                self._connection.execute(
                    "INSERT INTO due_work VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        leased_work.work_id,
                        leased_work.payload["state_version"],
                        leased_work.canonical_bytes,
                        leased_work.digest,
                        leased_work.payload["profile_record_id"],
                        leased_work.payload["logical_due_key"],
                        leased_work.payload["scope_kind"],
                        leased_work.payload["urgency"],
                        leased_work.payload["state"],
                        leased_work.payload["attempt_count"],
                        leased_work.payload["due_at"],
                        leased_work.payload["deadline_at"],
                        leased_work.payload["previous_digest"],
                        leased_work.payload["authority_version_digest"],
                    ),
                )

            self._write(commit_acquisition)
            return

        previous = self._connection.execute(
            "SELECT lease_digest,lease_bytes FROM work_leases WHERE lease_id=? AND lease_version=?",
            (lease.lease_id, version - 1),
        ).fetchone()
        if previous is None or previous[0] != lease.payload["previous_digest"]:
            raise OperationalAuthorityError("lease predecessor differs")
        retained = WorkLease.from_canonical_bytes(bytes(previous[1]))
        work_row = self._connection.execute(
            "SELECT work_bytes FROM due_work WHERE work_id=? "
            "ORDER BY state_version DESC LIMIT 1",
            (lease.payload["work_id"],),
        ).fetchone()
        if work_row is None:
            raise OperationalAuthorityError("lease work is absent")
        retained_work = DueWork.from_canonical_bytes(bytes(work_row[0]))
        if lease.payload["status"] == LeaseState.ACTIVE.value:
            unchanged = {
                name: retained.payload[name]
                for name in (
                    "lease_id",
                    "work_id",
                    "owner_digest",
                    "acquired_at",
                    "status",
                    "closed_at",
                )
            }
            derived_authority_deadline = self._leased_work_authority_deadline(
                retained_work
            )
            try:
                expected_renewal = renew_lease(
                    retained,
                    progress_digest=str(lease.payload["progress_digest"]),
                    renewed_at=str(lease.payload["renewed_at"]),
                    authority_deadline_at=_canonical_time(derived_authority_deadline),
                )
            except (KeyError, TypeError, OperationalAuthorityError) as exc:
                raise OperationalAuthorityError("lease renewal differs") from exc
            if (
                any(lease.payload[name] != value for name, value in unchanged.items())
                or expected_renewal != lease
                or retained_work.payload["state"] != WorkState.LEASED.value
                or retained_work.work_id != lease.payload["work_id"]
                or _dt(str(lease.payload["expires_at"]))
                > _dt(str(retained_work.payload["deadline_at"]))
            ):
                raise OperationalAuthorityError("lease renewal differs")
        else:
            raise OperationalAuthorityError(
                "lease closure must include its work transition"
            )

        def commit_renewal() -> None:
            latest_lease_row = self._connection.execute(
                "SELECT lease_bytes FROM work_leases WHERE lease_id=? "
                "ORDER BY lease_version DESC LIMIT 1",
                (lease.lease_id,),
            ).fetchone()
            latest_work_row = self._connection.execute(
                "SELECT work_bytes FROM due_work WHERE work_id=? "
                "ORDER BY state_version DESC LIMIT 1",
                (lease.payload["work_id"],),
            ).fetchone()
            if (
                latest_lease_row is None
                or WorkLease.from_canonical_bytes(bytes(latest_lease_row[0]))
                != retained
                or latest_work_row is None
                or DueWork.from_canonical_bytes(bytes(latest_work_row[0]))
                != retained_work
            ):
                raise OperationalAuthorityError("lease renewal authority changed")
            self._connection.execute(
                "INSERT INTO work_leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                lease_values,
            )

        self._write(commit_renewal)

    def close_lease_and_transition(
        self,
        *,
        lease: WorkLease,
        lease_state: LeaseState,
        work_state: WorkState,
        transitioned_at: str,
    ) -> tuple[WorkLease, DueWork]:
        """Atomically close an active lease and append its work transition."""

        if lease_state not in {LeaseState.RELEASED, LeaseState.ORPHANED}:
            raise OperationalAuthorityError("lease close state differs")
        if work_state not in {
            WorkState.RETRY_PENDING,
            WorkState.COMPLETED,
            WorkState.QUARANTINED,
        }:
            raise OperationalAuthorityError("lease work close state differs")
        transition_time = _time(transitioned_at, "transitioned_at")
        try:
            checked_lease = WorkLease.from_canonical_bytes(lease.canonical_bytes)
        except (AttributeError, TypeError, ValueError) as exc:
            raise OperationalAuthorityError("lease is forged or non-canonical") from exc
        if checked_lease != lease or lease.payload["status"] != LeaseState.ACTIVE.value:
            raise OperationalAuthorityError("only an active canonical lease can close")
        work_row = self._connection.execute(
            "SELECT work_bytes FROM due_work WHERE work_id=? "
            "ORDER BY state_version DESC LIMIT 1",
            (lease.payload["work_id"],),
        ).fetchone()
        if work_row is None:
            raise OperationalAuthorityError("lease work is absent")
        retained_work = DueWork.from_canonical_bytes(bytes(work_row[0]))
        if retained_work.payload["state"] != WorkState.LEASED.value:
            raise OperationalAuthorityError("lease work is not LEASED")
        authority_deadline = self._leased_work_authority_deadline(retained_work)
        if (
            lease_state is LeaseState.RELEASED
            and _dt(transition_time) > authority_deadline
        ):
            raise OperationalAuthorityError(
                "released work transition exceeds lease authority deadline"
            )
        if lease_state is LeaseState.RELEASED and _dt(transition_time) > _dt(
            str(retained_work.payload["deadline_at"])
        ):
            raise OperationalAuthorityError("released work transition exceeds deadline")
        if (
            lease_state is LeaseState.ORPHANED
            and work_state is not WorkState.QUARANTINED
        ):
            raise OperationalAuthorityError("orphaned lease must quarantine its work")
        closed = close_lease(checked_lease, lease_state, closed_at=transition_time)
        transitioned = transition_work(retained_work, state=work_state)

        def commit_close() -> None:
            latest_lease_row = self._connection.execute(
                "SELECT lease_bytes FROM work_leases WHERE lease_id=? "
                "ORDER BY lease_version DESC LIMIT 1",
                (lease.lease_id,),
            ).fetchone()
            latest_work_row = self._connection.execute(
                "SELECT work_bytes FROM due_work WHERE work_id=? "
                "ORDER BY state_version DESC LIMIT 1",
                (retained_work.work_id,),
            ).fetchone()
            if latest_lease_row is None or latest_work_row is None:
                raise OperationalAuthorityError("lease close authority is absent")
            latest_lease = WorkLease.from_canonical_bytes(bytes(latest_lease_row[0]))
            latest_work = DueWork.from_canonical_bytes(bytes(latest_work_row[0]))
            if latest_lease != checked_lease or latest_work != retained_work:
                raise OperationalAuthorityError("lease close authority changed")
            if work_state is WorkState.RETRY_PENDING:
                finding_row = self._connection.execute(
                    "SELECT finding_bytes FROM retry_findings WHERE work_id=? "
                    "AND attempt_number=?",
                    (latest_work.work_id, latest_work.payload["attempt_count"]),
                ).fetchone()
                if finding_row is None:
                    raise OperationalAuthorityError(
                        "retry transition lacks its Finding"
                    )
                finding = RetryFinding.from_canonical_bytes(bytes(finding_row[0]))
                if (
                    finding.payload["work_digest"] != latest_work.digest
                    or finding.payload["classification"]
                    != RetryClassification.RETRYABLE.value
                    or finding.payload["retry_exhausted"] is not False
                    or finding.payload["next_due_at"] is None
                    or _dt(str(finding.payload["failed_at"])) > _dt(transition_time)
                ):
                    raise OperationalAuthorityError("retry transition Finding differs")
            self._connection.execute(
                "INSERT INTO work_leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    closed.lease_id,
                    closed.payload["lease_version"],
                    closed.canonical_bytes,
                    closed.digest,
                    closed.payload["work_id"],
                    closed.payload["owner_digest"],
                    closed.payload["progress_digest"],
                    closed.payload["acquired_at"],
                    closed.payload["expires_at"],
                    closed.payload["maximum_expires_at"],
                    closed.payload["status"],
                    closed.payload["previous_digest"],
                ),
            )
            self._connection.execute(
                "INSERT INTO due_work VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    transitioned.work_id,
                    transitioned.payload["state_version"],
                    transitioned.canonical_bytes,
                    transitioned.digest,
                    transitioned.payload["profile_record_id"],
                    transitioned.payload["logical_due_key"],
                    transitioned.payload["scope_kind"],
                    transitioned.payload["urgency"],
                    transitioned.payload["state"],
                    transitioned.payload["attempt_count"],
                    transitioned.payload["due_at"],
                    transitioned.payload["deadline_at"],
                    transitioned.payload["previous_digest"],
                    transitioned.payload["authority_version_digest"],
                ),
            )

        self._write(commit_close)
        return closed, transitioned

    def append_retry_finding(self, finding: RetryFinding) -> None:
        if (
            not isinstance(finding, RetryFinding)
            or RetryFinding.from_canonical_bytes(finding.canonical_bytes) != finding
        ):
            raise OperationalAuthorityError("retry Finding is forged or non-canonical")
        retained = self._connection.execute(
            "SELECT work_bytes,work_digest FROM due_work WHERE work_id=? "
            "ORDER BY state_version DESC LIMIT 1",
            (finding.payload["work_id"],),
        ).fetchone()
        if retained is None or retained[1] != finding.payload["work_digest"]:
            raise OperationalAuthorityError("retry work authority differs")
        retained_work = DueWork.from_canonical_bytes(bytes(retained[0]))
        if retained_work.payload["state"] != WorkState.LEASED.value:
            raise OperationalAuthorityError("retry Finding requires latest leased work")
        expected = build_retry_finding(
            work=retained_work,
            classification=RetryClassification(str(finding.payload["classification"])),
            dependency_scope=str(finding.payload["dependency_scope"]),
            first_attempt_at=str(finding.payload["first_attempt_at"]),
            failed_at=str(finding.payload["failed_at"]),
        )
        if expected != finding:
            raise OperationalAuthorityError("retry Finding differs")
        active_leases = self._connection.execute(
            "SELECT l.acquired_at,l.expires_at FROM work_leases l WHERE l.work_id=? "
            "AND l.lease_version=(SELECT MAX(x.lease_version) FROM work_leases x "
            "WHERE x.lease_id=l.lease_id) AND l.status='ACTIVE' "
            "ORDER BY l.lease_id",
            (finding.payload["work_id"],),
        ).fetchall()
        attempts = self._connection.execute(
            "SELECT acquired_at FROM work_leases WHERE work_id=?",
            (finding.payload["work_id"],),
        ).fetchall()
        active_lease = (
            None
            if not active_leases
            else max(active_leases, key=lambda row: _dt(str(row[0])))
        )
        first_attempt = (
            None if not attempts else min((str(row[0]) for row in attempts), key=_dt)
        )
        failure_time = _dt(str(finding.payload["failed_at"]))
        if (
            active_lease is None
            or first_attempt != finding.payload["first_attempt_at"]
            or failure_time < _dt(str(active_lease[0]))
            or failure_time > _dt(str(active_lease[1]))
        ):
            raise OperationalAuthorityError("retry failure is outside its active lease")
        inserted = self._insert(
            "INSERT INTO retry_findings SELECT ?,?,?,?,?,?,?,?,? WHERE "
            "EXISTS(SELECT 1 FROM due_work d WHERE d.work_id=? "
            "AND d.work_digest=? AND d.state='LEASED' "
            "AND d.state_version=(SELECT MAX(x.state_version) FROM due_work x "
            "WHERE x.work_id=d.work_id)) AND EXISTS(SELECT 1 FROM work_leases l "
            "WHERE l.work_id=? AND l.acquired_at=? AND l.expires_at=? "
            "AND l.status='ACTIVE' "
            "AND l.lease_version=(SELECT MAX(x.lease_version) FROM work_leases x "
            "WHERE x.lease_id=l.lease_id)) AND "
            "(SELECT COUNT(*) FROM work_leases WHERE work_id=?)=?",
            (
                finding.finding_id,
                finding.canonical_bytes,
                finding.digest,
                finding.payload["work_id"],
                finding.payload["attempt_number"],
                finding.payload["classification"],
                finding.payload["dependency_scope"],
                finding.payload["next_due_at"],
                0,
                finding.payload["work_id"],
                finding.payload["work_digest"],
                finding.payload["work_id"],
                active_lease[0],
                active_lease[1],
                finding.payload["work_id"],
                len(attempts),
            ),
        )
        if inserted != 1:
            raise OperationalAuthorityError("retry latest-work authority changed")

    def append_quarantine(self, record: QuarantineRecord) -> None:
        if (
            not isinstance(record, QuarantineRecord)
            or QuarantineRecord.from_canonical_bytes(record.canonical_bytes) != record
        ):
            raise OperationalAuthorityError(
                "quarantine record is forged or non-canonical"
            )
        version = int(record.payload["quarantine_version"])
        if version == 1:
            expected = quarantine_scope(
                scope_id=str(record.payload["scope_id"]),
                reason_class=str(record.payload["reason_class"]),
                evidence_digest=str(record.payload["evidence_digest"]),
                recorded_at=str(record.payload["recorded_at"]),
            )
            if expected != record:
                raise OperationalAuthorityError("initial quarantine record differs")
        else:
            previous = self._connection.execute(
                "SELECT quarantine_digest,quarantine_bytes FROM quarantine_records "
                "WHERE quarantine_id=? AND quarantine_version=?",
                (record.quarantine_id, version - 1),
            ).fetchone()
            if previous is None or previous[0] != record.payload["previous_digest"]:
                raise OperationalAuthorityError("quarantine predecessor differs")
            retained = QuarantineRecord.from_canonical_bytes(bytes(previous[1]))
            if (
                approve_quarantine_release(
                    retained,
                    authorised_by_digest=str(record.payload["authorised_by_digest"]),
                    repair_evidence_digest=str(record.payload["evidence_digest"]),
                    decided_at=str(record.payload["recorded_at"]),
                )
                != record
            ):
                raise OperationalAuthorityError("quarantine transition differs")
        self._insert(
            "INSERT INTO quarantine_records VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.quarantine_id,
                record.payload["quarantine_version"],
                record.canonical_bytes,
                record.digest,
                record.payload["scope_id"],
                record.payload["reason_class"],
                record.payload["status"],
                record.payload["authorised_by_digest"],
                record.payload["evidence_digest"],
                record.payload["previous_digest"],
                record.payload["recorded_at"],
            ),
        )

    def due_work(self, now: str) -> tuple[DueWork, ...]:
        instant = _time(now, "now")
        rows = self._connection.execute(
            "SELECT d.work_bytes FROM due_work d WHERE d.state_version=("
            "SELECT MAX(x.state_version) FROM due_work x WHERE x.work_id=d.work_id) "
            "AND d.state IN('QUEUED','RETRY_PENDING')"
        ).fetchall()
        ready: list[DueWork] = []
        for row in rows:
            work = DueWork.from_canonical_bytes(bytes(row[0]))
            if work.payload["state"] == WorkState.QUEUED.value:
                if _dt(str(work.payload["due_at"])) <= _dt(instant):
                    ready.append(work)
                continue
            retry = self._connection.execute(
                "SELECT finding_bytes FROM retry_findings WHERE work_id=? "
                "AND attempt_number=?",
                (work.work_id, work.payload["attempt_count"]),
            ).fetchone()
            if retry is None:
                continue
            finding = RetryFinding.from_canonical_bytes(bytes(retry[0]))
            next_due = finding.payload["next_due_at"]
            if (
                finding.payload["work_digest"] == work.payload["previous_digest"]
                and next_due is not None
                and _dt(str(next_due)) <= _dt(instant)
            ):
                ready.append(work)
        priority = {
            Urgency.URGENT.value: 0,
            Urgency.TIME_SENSITIVE.value: 1,
            Urgency.PLANNED.value: 2,
            Urgency.ROUTINE.value: 3,
        }
        starvation_limit = int(
            INCREMENT_8_READINESS.operational_profile["execution"][
                "routine_starvation_limit_seconds"
            ]
        )
        ready.sort(
            key=lambda item: (
                priority[str(item.payload["urgency"])],
                _dt(str(item.payload["deadline_at"])),
                item.work_id,
            )
        )
        limit = int(
            INCREMENT_8_READINESS.operational_profile["schedule"][
                "maximum_catch_up_items"
            ]
        )
        selected = ready[:limit]
        starved = sorted(
            (
                item
                for item in ready
                if item.payload["urgency"] == Urgency.ROUTINE.value
                and _dt(instant) - _dt(str(item.payload["due_at"]))
                >= timedelta(seconds=starvation_limit)
            ),
            key=lambda item: (
                _dt(str(item.payload["due_at"])),
                _dt(str(item.payload["deadline_at"])),
                item.work_id,
            ),
        )
        if starved and starved[0] not in selected and selected:
            selected_counts = {
                urgency.value: sum(
                    item.payload["urgency"] == urgency.value for item in selected
                )
                for urgency in Urgency
            }
            replaceable = next(
                (
                    index
                    for index in range(len(selected) - 1, -1, -1)
                    if selected[index].payload["urgency"] == Urgency.ROUTINE.value
                    or selected_counts[str(selected[index].payload["urgency"])] > 1
                ),
                None,
            )
            if replaceable is not None:
                selected[replaceable] = starved[0]
        return tuple(selected)

    def active_lease_count(self) -> int:
        return int(
            self._connection.execute(
                "SELECT COUNT(*) FROM work_leases l WHERE l.lease_version=("
                "SELECT MAX(x.lease_version) FROM work_leases x WHERE x.lease_id=l.lease_id) "
                "AND l.status='ACTIVE'"
            ).fetchone()[0]
        )


__all__ = [
    "CapacityEvidence",
    "DueWork",
    "HandoffAnchorKind",
    "HandoffOperationalStatus",
    "HandoffRegistrationAnchor",
    "LeaseState",
    "OperationalAuthority",
    "OperationalAuthorityError",
    "OperationalProfile",
    "QuarantineRecord",
    "QuarantineState",
    "RetryClassification",
    "RetryFinding",
    "Urgency",
    "WorkLease",
    "WorkState",
    "acquire_lease",
    "anchor_new_handoff_registration",
    "approve_quarantine_release",
    "build_capacity_evidence",
    "build_operational_profile",
    "build_retry_finding",
    "close_lease",
    "enqueue_due_work",
    "handoff_operational_status",
    "quarantine_scope",
    "record_observed_handoff_at_hardening",
    "register_anchored_handoff",
    "renew_lease",
    "transition_work",
]
