"""Durable governed-unit lease, cooldown and CONT writer backoff authority."""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.store import append_ledger, connect

CONT_WRITER_ROUTE: Final[str] = "CONT"
_UTC_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S.%fZ"
_MIN_NORMAL_COOLDOWN_SECONDS: Final[int] = 300
_MIN_UNPRODUCTIVE_COOLDOWN_SECONDS: Final[int] = 900
_MIN_HEALTH_PROBE_INTERVAL_SECONDS: Final[int] = 3_600

CycleOutcomeClass = Literal[
    "IDLE_QUALIFIED_ZERO",
    "PRODUCTIVE",
    "UNPRODUCTIVE_PROVIDER",
    "SYSTEMIC_PROVIDER_FAILURE",
]


@dataclass(frozen=True, slots=True)
class EvaluationCyclePolicy:
    """Versioned, checked-in EVALUATION cooldown and circuit policy."""

    policy_name: str = "newsroom.evaluation-cycle.v1"
    normal_cooldown_seconds: int = _MIN_NORMAL_COOLDOWN_SECONDS
    unproductive_cooldown_seconds: int = _MIN_UNPRODUCTIVE_COOLDOWN_SECONDS
    health_probe_interval_seconds: int = _MIN_HEALTH_PROBE_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        for value, minimum, label in (
            (
                self.normal_cooldown_seconds,
                _MIN_NORMAL_COOLDOWN_SECONDS,
                "normal cooldown",
            ),
            (
                self.unproductive_cooldown_seconds,
                _MIN_UNPRODUCTIVE_COOLDOWN_SECONDS,
                "unproductive cooldown",
            ),
            (
                self.health_probe_interval_seconds,
                _MIN_HEALTH_PROBE_INTERVAL_SECONDS,
                "health probe interval",
            ),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{label} must be at least {minimum} seconds")
        if not self.policy_name.strip():
            raise ValueError("cycle policy name is required")

    @property
    def version(self) -> str:
        values = {
            "policy_name": self.policy_name,
            "normal_cooldown_seconds": self.normal_cooldown_seconds,
            "unproductive_cooldown_seconds": self.unproductive_cooldown_seconds,
            "health_probe_interval_seconds": self.health_probe_interval_seconds,
        }
        return f"{self.policy_name}@{digest_bytes(canonical_json_bytes(values))}"


@dataclass(frozen=True, slots=True)
class CycleOutcomeInput:
    """Writer counters retained by #727 at the cycle reporting seam."""

    write_ready: int | None
    provider_dispatches: int | None
    accepted_payload_count: int | None
    admission_hold: int | None = 0
    admission_reject: int | None = 0
    systemic_provider_failure_reason: str = ""

    def __post_init__(self) -> None:
        for name in (
            "write_ready",
            "provider_dispatches",
            "accepted_payload_count",
            "admission_hold",
            "admission_reject",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            self.accepted_payload_count is not None
            and self.accepted_payload_count > 0
            and self.provider_dispatches == 0
        ):
            raise ValueError("accepted payloads require a retained provider dispatch")
        if self.systemic_provider_failure_reason and self.provider_dispatches == 0:
            raise ValueError("a systemic provider failure requires a provider dispatch")


@dataclass(frozen=True, slots=True)
class CycleLease:
    cycle_id: str
    owner_digest: str
    lease_state: str
    lease_acquired_at: str
    lease_expires_at: str
    work_started_at: str
    monotonic_started_at: float
    writer_unproductive_streak_before: int
    writer_circuit_state: str
    writer_circuit_open_reason: str
    writer_dispatch_permitted: bool
    restart_observations: tuple[str, ...]
    refused_early_start_count_before: int
    refused_early_start_reason_before: str


@dataclass(frozen=True, slots=True)
class CycleTerminalResult:
    cycle_id: str
    lease_owner_digest: str
    lease_state: str
    terminal_state: str
    outcome_class: CycleOutcomeClass
    admission_counts: dict[str, int | None]
    accepted_payload_count: int | None
    writer_provider_dispatch_count: int | None
    work_started_at: str
    terminal_at: str
    elapsed_seconds: float
    cooldown_policy_version: str
    cooldown_seconds: int
    cooldown_started_at: str
    next_cycle_eligible_at: str
    writer_unproductive_streak_before: int
    writer_unproductive_streak_after: int
    writer_circuit_state: str
    writer_circuit_open_reason: str
    writer_circuit_release_evidence: dict[str, object] | None
    restart_observations: tuple[str, ...]
    refused_early_start_count: int
    refused_early_start_reason: str


@dataclass(frozen=True, slots=True)
class CycleGovernorStatus:
    policy_version: str
    next_cycle_eligible_at: str | None
    last_observed_utc: str | None
    writer_unproductive_streak: int
    writer_circuit_state: str
    writer_circuit_open_reason: str
    writer_circuit_release_evidence: dict[str, object] | None
    refused_early_start_count: int
    refused_early_start_reason: str
    active_cycle_id: str | None
    active_lease_state: str | None
    active_lease_owner_digest: str | None
    latest_cycle: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class CircuitReleaseEvidence:
    route: str
    release_kind: str
    released_at: str
    policy_version: str
    bound_failure_reason: str
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class OperatorResetRequest:
    route: str
    bound_failure_reason: str
    policy_version: str
    authorised_by: str
    evidence_reference: str
    requested_at: str


@dataclass(frozen=True, slots=True)
class WriterRouteHealthProof:
    executable_ok: bool
    authentication_ok: bool
    configuration_ok: bool
    provider_available: bool
    provider_dispatched: bool
    provider_receipt_reference: str | None


class CycleNotEligible(RuntimeError):
    def __init__(
        self,
        reason: str,
        *,
        remaining_seconds: float,
        next_cycle_eligible_at: str | None,
    ) -> None:
        super().__init__(f"cycle is not eligible: {reason}")
        self.reason = reason
        self.remaining_seconds = remaining_seconds
        self.next_cycle_eligible_at = next_cycle_eligible_at


class CycleLeaseConflict(CycleNotEligible):
    def __init__(
        self,
        cycle_id: str,
        *,
        remaining_seconds: float,
        lease_expires_at: str,
    ) -> None:
        super().__init__(
            "ACTIVE_CYCLE_LEASE",
            remaining_seconds=remaining_seconds,
            next_cycle_eligible_at=lease_expires_at,
        )
        self.cycle_id = cycle_id
        self.lease_expires_at = lease_expires_at


OperatorResetVerifier = Callable[[OperatorResetRequest], bool]
WriterRouteHealthProbe = Callable[[], WriterRouteHealthProof]


_HEALTH_PROBE_TABLE_SQL = """
CREATE TABLE unpublished_route_health_probes(
    probe_id TEXT PRIMARY KEY,
    route TEXT NOT NULL,
    bound_failure_reason TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    probe_state TEXT NOT NULL
        CHECK(probe_state IN ('LEGACY_UNKNOWN','RESERVED','TERMINAL')),
    terminal_at TEXT,
    outcome TEXT CHECK(outcome IS NULL OR outcome IN ('PASSED','FAILED')),
    provider_dispatched INTEGER NOT NULL CHECK(provider_dispatched IN (0,1)),
    provider_receipt_reference TEXT,
    evidence_json TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    CHECK(
        (probe_state='LEGACY_UNKNOWN' AND terminal_at IS NULL AND outcome IS NULL)
        OR (probe_state='RESERVED' AND terminal_at IS NULL AND outcome IS NULL)
        OR (probe_state='TERMINAL' AND terminal_at IS NOT NULL AND outcome IS NOT NULL)
    )
)
"""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS unpublished_cycle_governor_state(
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    policy_version TEXT NOT NULL,
    next_cycle_eligible_at TEXT,
    last_observed_utc TEXT,
    writer_unproductive_streak INTEGER NOT NULL DEFAULT 0
        CHECK(writer_unproductive_streak>=0),
    refused_early_start_count INTEGER NOT NULL DEFAULT 0
        CHECK(refused_early_start_count>=0),
    refused_early_start_reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS unpublished_route_circuits(
    route TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('OPEN','CLOSED')),
    open_reason TEXT NOT NULL,
    opened_at TEXT,
    release_evidence_json TEXT,
    release_evidence_digest TEXT,
    last_probe_at TEXT
);
CREATE TABLE IF NOT EXISTS unpublished_governed_cycles(
    cycle_id TEXT PRIMARY KEY,
    owner_digest TEXT NOT NULL,
    lease_state TEXT NOT NULL CHECK(lease_state IN ('ACTIVE','TERMINAL','RECOVERED')),
    lease_acquired_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    work_started_at TEXT NOT NULL,
    terminal_at TEXT,
    elapsed_seconds REAL,
    terminal_state TEXT,
    outcome_class TEXT CHECK(outcome_class IS NULL OR outcome_class IN (
        'IDLE_QUALIFIED_ZERO','PRODUCTIVE','UNPRODUCTIVE_PROVIDER',
        'SYSTEMIC_PROVIDER_FAILURE'
    )),
    write_ready INTEGER,
    admission_hold INTEGER,
    admission_reject INTEGER,
    accepted_payload_count INTEGER,
    provider_dispatches INTEGER,
    cooldown_policy_version TEXT NOT NULL,
    cooldown_seconds INTEGER,
    cooldown_started_at TEXT,
    next_cycle_eligible_at TEXT,
    writer_unproductive_streak_before INTEGER NOT NULL,
    writer_unproductive_streak_after INTEGER,
    writer_circuit_state TEXT NOT NULL CHECK(writer_circuit_state IN ('OPEN','CLOSED')),
    writer_circuit_open_reason TEXT NOT NULL,
    writer_circuit_release_evidence_json TEXT,
    restart_observations_json TEXT NOT NULL,
    refused_early_start_count_before INTEGER NOT NULL,
    refused_early_start_reason_before TEXT NOT NULL,
    refused_early_start_count INTEGER,
    refused_early_start_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS unpublished_one_active_governed_cycle
ON unpublished_governed_cycles(lease_state) WHERE lease_state='ACTIVE';
"""


def _ensure_health_probe_schema(connection: sqlite3.Connection) -> None:
    retained = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND "
        "name='unpublished_route_health_probes'"
    ).fetchone()
    if retained is None:
        connection.execute(_HEALTH_PROBE_TABLE_SQL)
        return
    if "LEGACY_UNKNOWN" in str(retained[0]):
        return

    connection.execute(
        "ALTER TABLE unpublished_route_health_probes "
        "RENAME TO unpublished_route_health_probes_legacy_migration"
    )
    connection.execute(_HEALTH_PROBE_TABLE_SQL)
    connection.execute(
        "INSERT INTO unpublished_route_health_probes("
        "probe_id, route, bound_failure_reason, attempted_at, probe_state, "
        "terminal_at, outcome, provider_dispatched, provider_receipt_reference, "
        "evidence_json, evidence_digest) "
        "SELECT probe_id, route, bound_failure_reason, attempted_at, "
        "'LEGACY_UNKNOWN', NULL, NULL, provider_dispatched, "
        "provider_receipt_reference, evidence_json, evidence_digest "
        "FROM unpublished_route_health_probes_legacy_migration"
    )
    connection.execute("DROP TABLE unpublished_route_health_probes_legacy_migration")


def ensure_cycle_governor_schema(
    connection: sqlite3.Connection,
    *,
    policy_version: str | None = None,
) -> None:
    connection.executescript(_SCHEMA)
    _ensure_health_probe_schema(connection)
    configured_policy_version = policy_version or EvaluationCyclePolicy().version
    connection.execute(
        "INSERT OR IGNORE INTO unpublished_cycle_governor_state("
        "singleton, policy_version) VALUES(1, ?)",
        (configured_policy_version,),
    )
    connection.execute(
        "INSERT OR IGNORE INTO unpublished_route_circuits("
        "route, state, open_reason) VALUES(?, 'CLOSED', '')",
        (CONT_WRITER_ROUTE,),
    )
    cycle_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(unpublished_governed_cycles)")
    }
    for column, declaration in (
        ("refused_early_start_reason_before", "TEXT NOT NULL DEFAULT ''"),
        ("refused_early_start_count", "INTEGER"),
        ("refused_early_start_reason", "TEXT"),
    ):
        if column not in cycle_columns:
            connection.execute(
                f"ALTER TABLE unpublished_governed_cycles ADD COLUMN {column} {declaration}"
            )
    connection.commit()


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC clock must return a timezone-aware datetime")
    return value.astimezone(UTC).strftime(_UTC_FORMAT)


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, _UTC_FORMAT).replace(tzinfo=UTC)
    except (TypeError, ValueError) as exc:
        raise ValueError("durable UTC evidence is ambiguous") from exc
    if _utc_text(parsed) != value:
        raise ValueError("durable UTC evidence is ambiguous")
    return parsed


def _owner_digest(owner_id: str) -> str:
    if not owner_id.strip():
        raise ValueError("cycle lease owner is required")
    return digest_bytes(canonical_json_bytes({"cycle_lease_owner": owner_id}))


def _remaining_seconds(now: datetime, target: datetime) -> float:
    return max(0.0, (target - now).total_seconds())


class DurableCycleGovernor:
    """SQLite-backed authority for one complete intake-plus-cycle unit."""

    def __init__(
        self,
        unpublished_store: str,
        *,
        policy: EvaluationCyclePolicy | None = None,
        utc_clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
        monotonic_clock: Callable[[], float] = time.monotonic,
        lease_seconds: int = 21_600,
        operator_reset_verifier: OperatorResetVerifier | None = None,
        writer_route_health_probe: WriterRouteHealthProbe | None = None,
    ) -> None:
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds <= 0
        ):
            raise ValueError("cycle lease duration must be a positive integer")
        self._path = unpublished_store
        self._policy = policy or EvaluationCyclePolicy()
        self._utc_clock = utc_clock
        self._monotonic_clock = monotonic_clock
        self._lease_seconds = lease_seconds
        self._operator_reset_verifier = operator_reset_verifier
        self._writer_route_health_probe = writer_route_health_probe
        connection = connect(self._path)
        try:
            ensure_cycle_governor_schema(
                connection, policy_version=self._policy.version
            )
            row = connection.execute(
                "SELECT policy_version FROM unpublished_cycle_governor_state "
                "WHERE singleton=1"
            ).fetchone()
            if row is None or str(row[0]) != self._policy.version:
                raise ValueError("retained cycle policy differs from configured policy")
        finally:
            connection.close()

    def _now(self) -> tuple[datetime, str]:
        value = self._utc_clock()
        text = _utc_text(value)
        return value.astimezone(UTC), text

    @staticmethod
    def _refuse(
        connection: sqlite3.Connection,
        reason: str,
        *,
        observed_at: str | None = None,
    ) -> None:
        if observed_at is None:
            connection.execute(
                "UPDATE unpublished_cycle_governor_state SET "
                "refused_early_start_count=refused_early_start_count+1, "
                "refused_early_start_reason=? WHERE singleton=1",
                (reason,),
            )
        else:
            connection.execute(
                "UPDATE unpublished_cycle_governor_state SET "
                "refused_early_start_count=refused_early_start_count+1, "
                "refused_early_start_reason=?, last_observed_utc=? WHERE singleton=1",
                (reason, observed_at),
            )

    def claim(self, *, owner_id: str) -> CycleLease:
        owner_digest = _owner_digest(owner_id)
        now, now_text = self._now()
        connection = connect(self._path)
        try:
            ensure_cycle_governor_schema(
                connection, policy_version=self._policy.version
            )
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                "SELECT next_cycle_eligible_at, last_observed_utc, "
                "writer_unproductive_streak, refused_early_start_count, "
                "refused_early_start_reason "
                "FROM unpublished_cycle_governor_state WHERE singleton=1"
            ).fetchone()
            if state is None:
                raise RuntimeError("cycle governor state is missing")
            next_text = str(state[0]) if state[0] is not None else None
            last_text = str(state[1]) if state[1] is not None else None
            if last_text is not None and now < _parse_utc(last_text):
                self._refuse(connection, "UTC_CLOCK_BACKWARDS")
                connection.commit()
                raise CycleNotEligible(
                    "UTC_CLOCK_BACKWARDS",
                    remaining_seconds=math.inf,
                    next_cycle_eligible_at=next_text,
                )
            active = connection.execute(
                "SELECT cycle_id, lease_expires_at, work_started_at, "
                "writer_unproductive_streak_before, writer_circuit_open_reason, "
                "restart_observations_json "
                "FROM unpublished_governed_cycles WHERE lease_state='ACTIVE'"
            ).fetchone()
            if active is not None:
                expires_at = _parse_utc(str(active[1]))
                if now < expires_at:
                    self._refuse(connection, "ACTIVE_CYCLE_LEASE", observed_at=now_text)
                    connection.commit()
                    raise CycleLeaseConflict(
                        str(active[0]),
                        remaining_seconds=_remaining_seconds(now, expires_at),
                        lease_expires_at=str(active[1]),
                    )
                recovered_next = now + timedelta(
                    seconds=self._policy.normal_cooldown_seconds
                )
                recovered_next_text = _utc_text(recovered_next)
                recovered_reason = "STALE_LEASE_RECOVERY_AMBIGUOUS"
                recovery_observations = tuple(json.loads(str(active[5]))) + (
                    "STALE_LEASE_RECOVERED",
                )
                refused_count = int(state[3]) + 1
                connection.execute(
                    "UPDATE unpublished_governed_cycles SET lease_state='RECOVERED', "
                    "terminal_at=?, elapsed_seconds=?, "
                    "terminal_state='RECOVERED_STALE_LEASE', "
                    "outcome_class='SYSTEMIC_PROVIDER_FAILURE', write_ready=NULL, "
                    "admission_hold=NULL, admission_reject=NULL, "
                    "accepted_payload_count=NULL, provider_dispatches=NULL, "
                    "cooldown_seconds=?, cooldown_started_at=?, "
                    "next_cycle_eligible_at=?, writer_unproductive_streak_after=?, "
                    "writer_circuit_state='OPEN', writer_circuit_open_reason=?, "
                    "restart_observations_json=?, refused_early_start_count=?, "
                    "refused_early_start_reason='STALE_LEASE_RECOVERED' "
                    "WHERE cycle_id=? AND lease_state='ACTIVE'",
                    (
                        now_text,
                        max(
                            0.0,
                            (now - _parse_utc(str(active[2]))).total_seconds(),
                        ),
                        self._policy.normal_cooldown_seconds,
                        now_text,
                        recovered_next_text,
                        int(active[3]),
                        recovered_reason,
                        json.dumps(recovery_observations, separators=(",", ":")),
                        refused_count,
                        str(active[0]),
                    ),
                )
                connection.execute(
                    "UPDATE unpublished_route_circuits SET state='OPEN', "
                    "open_reason=?, opened_at=?, release_evidence_json=NULL, "
                    "release_evidence_digest=NULL WHERE route=?",
                    (recovered_reason, now_text, CONT_WRITER_ROUTE),
                )
                connection.execute(
                    "UPDATE unpublished_cycle_governor_state SET "
                    "next_cycle_eligible_at=?, last_observed_utc=?, "
                    "refused_early_start_count=?, "
                    "refused_early_start_reason='STALE_LEASE_RECOVERED' "
                    "WHERE singleton=1",
                    (recovered_next_text, now_text, refused_count),
                )
                append_ledger(
                    connection,
                    "PRIVATE_CYCLE_STALE_LEASE_RECOVERED",
                    {
                        "cycle_id": str(active[0]),
                        "terminal_at": now_text,
                        "next_cycle_eligible_at": recovered_next_text,
                        "writer_circuit_open_reason": recovered_reason,
                    },
                )
                connection.commit()
                raise CycleNotEligible(
                    "STALE_LEASE_RECOVERED",
                    remaining_seconds=float(self._policy.normal_cooldown_seconds),
                    next_cycle_eligible_at=recovered_next_text,
                )
            if next_text is not None:
                next_eligible = _parse_utc(next_text)
                if now < next_eligible:
                    self._refuse(
                        connection, "POST_CYCLE_COOLDOWN", observed_at=now_text
                    )
                    connection.commit()
                    raise CycleNotEligible(
                        "POST_CYCLE_COOLDOWN",
                        remaining_seconds=_remaining_seconds(now, next_eligible),
                        next_cycle_eligible_at=next_text,
                    )
            circuit = connection.execute(
                "SELECT state, open_reason, release_evidence_json "
                "FROM unpublished_route_circuits WHERE route=?",
                (CONT_WRITER_ROUTE,),
            ).fetchone()
            if circuit is None:
                raise RuntimeError("CONT writer circuit state is missing")
            streak = int(state[2])
            circuit_state = str(circuit[0])
            circuit_reason = str(circuit[1])
            cycle_id = str(uuid.uuid4())
            expires_text = _utc_text(now + timedelta(seconds=self._lease_seconds))
            restart_observations = (
                ("RETAINED_STATE_REUSED",)
                if last_text is not None
                else ("FRESH_STATE",)
            )
            connection.execute(
                "INSERT INTO unpublished_governed_cycles("
                "cycle_id, owner_digest, lease_state, lease_acquired_at, "
                "lease_expires_at, work_started_at, cooldown_policy_version, "
                "writer_unproductive_streak_before, writer_circuit_state, "
                "writer_circuit_open_reason, writer_circuit_release_evidence_json, "
                "restart_observations_json, refused_early_start_count_before, "
                "refused_early_start_reason_before) "
                "VALUES(?,?,'ACTIVE',?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cycle_id,
                    owner_digest,
                    now_text,
                    expires_text,
                    now_text,
                    self._policy.version,
                    streak,
                    circuit_state,
                    circuit_reason,
                    str(circuit[2]) if circuit[2] is not None else None,
                    json.dumps(restart_observations, separators=(",", ":")),
                    int(state[3]),
                    str(state[4]),
                ),
            )
            connection.execute(
                "UPDATE unpublished_cycle_governor_state SET last_observed_utc=? "
                "WHERE singleton=1",
                (now_text,),
            )
            append_ledger(
                connection,
                "PRIVATE_GOVERNED_CYCLE_LEASE_CLAIMED",
                {
                    "cycle_id": cycle_id,
                    "lease_owner_digest": owner_digest,
                    "lease_state": "ACTIVE",
                    "lease_acquired_at": now_text,
                    "lease_expires_at": expires_text,
                    "writer_circuit_state": circuit_state,
                    "restart_observations": list(restart_observations),
                },
            )
            connection.commit()
            return CycleLease(
                cycle_id=cycle_id,
                owner_digest=owner_digest,
                lease_state="ACTIVE",
                lease_acquired_at=now_text,
                lease_expires_at=expires_text,
                work_started_at=now_text,
                monotonic_started_at=self._monotonic_clock(),
                writer_unproductive_streak_before=streak,
                writer_circuit_state=circuit_state,
                writer_circuit_open_reason=circuit_reason,
                writer_dispatch_permitted=circuit_state == "CLOSED",
                restart_observations=restart_observations,
                refused_early_start_count_before=int(state[3]),
                refused_early_start_reason_before=str(state[4]),
            )
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def renew(self, lease: CycleLease) -> str:
        """Renew and fence an active unit before another governed-work boundary."""

        now, now_text = self._now()
        renewed_until = _utc_text(now + timedelta(seconds=self._lease_seconds))
        connection = connect(self._path)
        try:
            ensure_cycle_governor_schema(
                connection, policy_version=self._policy.version
            )
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                "SELECT last_observed_utc FROM unpublished_cycle_governor_state "
                "WHERE singleton=1"
            ).fetchone()
            if state is None:
                raise RuntimeError("cycle governor state is missing")
            if state[0] is not None and now < _parse_utc(str(state[0])):
                raise CycleNotEligible(
                    "UTC_CLOCK_BACKWARDS",
                    remaining_seconds=math.inf,
                    next_cycle_eligible_at=lease.lease_expires_at,
                )
            retained = connection.execute(
                "SELECT owner_digest, lease_state, lease_expires_at "
                "FROM unpublished_governed_cycles WHERE cycle_id=?",
                (lease.cycle_id,),
            ).fetchone()
            if retained is None or retained[:2] != (lease.owner_digest, "ACTIVE"):
                raise CycleLeaseConflict(
                    lease.cycle_id,
                    remaining_seconds=0.0,
                    lease_expires_at=lease.lease_expires_at,
                )
            retained_expiry = _parse_utc(str(retained[2]))
            if now >= retained_expiry:
                raise CycleNotEligible(
                    "STALE_LEASE_EXPIRED",
                    remaining_seconds=0.0,
                    next_cycle_eligible_at=str(retained[2]),
                )
            changed = connection.execute(
                "UPDATE unpublished_governed_cycles SET lease_expires_at=? "
                "WHERE cycle_id=? AND owner_digest=? AND lease_state='ACTIVE'",
                (renewed_until, lease.cycle_id, lease.owner_digest),
            ).rowcount
            if changed != 1:
                raise CycleLeaseConflict(
                    lease.cycle_id,
                    remaining_seconds=0.0,
                    lease_expires_at=lease.lease_expires_at,
                )
            connection.execute(
                "UPDATE unpublished_cycle_governor_state SET last_observed_utc=? "
                "WHERE singleton=1",
                (now_text,),
            )
            append_ledger(
                connection,
                "PRIVATE_GOVERNED_CYCLE_LEASE_RENEWED",
                {
                    "cycle_id": lease.cycle_id,
                    "lease_owner_digest": lease.owner_digest,
                    "lease_state": "ACTIVE",
                    "renewed_at": now_text,
                    "lease_expires_at": renewed_until,
                },
            )
            connection.commit()
            return renewed_until
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _classify(
        lease: CycleLease, outcome: CycleOutcomeInput
    ) -> tuple[CycleOutcomeClass, str]:
        if outcome.systemic_provider_failure_reason:
            return "SYSTEMIC_PROVIDER_FAILURE", outcome.systemic_provider_failure_reason
        if (
            outcome.accepted_payload_count is not None
            and outcome.accepted_payload_count > 0
        ):
            return "PRODUCTIVE", ""
        if outcome.provider_dispatches is None:
            raise ValueError(
                "unknown provider state requires a systemic failure reason"
            )
        if outcome.provider_dispatches > 0:
            return "UNPRODUCTIVE_PROVIDER", ""
        if outcome.write_ready == 0:
            return "IDLE_QUALIFIED_ZERO", ""
        if lease.writer_circuit_state == "OPEN":
            return "SYSTEMIC_PROVIDER_FAILURE", lease.writer_circuit_open_reason
        raise ValueError(
            "WRITE_READY work with no payload and no provider dispatch is inconsistent"
        )

    def complete(
        self,
        lease: CycleLease,
        outcome: CycleOutcomeInput,
        *,
        terminal_state: str = "COMPLETED",
    ) -> CycleTerminalResult:
        now, now_text = self._now()
        started = _parse_utc(lease.work_started_at)
        if now < started:
            raise CycleNotEligible(
                "UTC_CLOCK_BACKWARDS",
                remaining_seconds=math.inf,
                next_cycle_eligible_at=lease.lease_expires_at,
            )
        elapsed = self._monotonic_clock() - lease.monotonic_started_at
        if elapsed < 0:
            raise ValueError("monotonic cycle clock moved backwards")
        outcome_class, systemic_reason = self._classify(lease, outcome)
        before = lease.writer_unproductive_streak_before
        after = before
        cooldown = self._policy.normal_cooldown_seconds
        circuit_state = lease.writer_circuit_state
        circuit_reason = lease.writer_circuit_open_reason
        if outcome_class == "PRODUCTIVE":
            after = 0
        elif outcome_class == "UNPRODUCTIVE_PROVIDER":
            after = before + 1
            cooldown = self._policy.unproductive_cooldown_seconds
            if after >= 2:
                circuit_state = "OPEN"
                circuit_reason = "CONSECUTIVE_UNPRODUCTIVE_PROVIDER"
        elif outcome_class == "SYSTEMIC_PROVIDER_FAILURE":
            if outcome.accepted_payload_count:
                after = 0
            circuit_state = "OPEN"
            circuit_reason = systemic_reason or "SYSTEMIC_PROVIDER_FAILURE"
        cooldown_started_at = now_text
        next_text = _utc_text(now + timedelta(seconds=cooldown))
        connection = connect(self._path)
        try:
            ensure_cycle_governor_schema(
                connection, policy_version=self._policy.version
            )
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_digest, lease_state FROM unpublished_governed_cycles "
                "WHERE cycle_id=?",
                (lease.cycle_id,),
            ).fetchone()
            if row != (lease.owner_digest, "ACTIVE"):
                raise ValueError("cycle lease is no longer active for this owner")
            state = connection.execute(
                "SELECT last_observed_utc, refused_early_start_count, "
                "refused_early_start_reason FROM unpublished_cycle_governor_state "
                "WHERE singleton=1"
            ).fetchone()
            if state is None:
                raise RuntimeError("cycle governor state is missing")
            if state[0] is not None and now < _parse_utc(str(state[0])):
                raise CycleNotEligible(
                    "UTC_CLOCK_BACKWARDS",
                    remaining_seconds=math.inf,
                    next_cycle_eligible_at=lease.lease_expires_at,
                )
            circuit = connection.execute(
                "SELECT release_evidence_json FROM unpublished_route_circuits "
                "WHERE route=?",
                (CONT_WRITER_ROUTE,),
            ).fetchone()
            release_json = circuit[0] if circuit is not None else None
            connection.execute(
                "UPDATE unpublished_governed_cycles SET lease_state='TERMINAL', "
                "terminal_at=?, elapsed_seconds=?, terminal_state=?, outcome_class=?, "
                "write_ready=?, admission_hold=?, admission_reject=?, "
                "accepted_payload_count=?, provider_dispatches=?, cooldown_seconds=?, "
                "cooldown_started_at=?, next_cycle_eligible_at=?, "
                "writer_unproductive_streak_after=?, writer_circuit_state=?, "
                "writer_circuit_open_reason=?, writer_circuit_release_evidence_json=?, "
                "refused_early_start_count=?, refused_early_start_reason=? "
                "WHERE cycle_id=? AND owner_digest=? AND lease_state='ACTIVE'",
                (
                    now_text,
                    elapsed,
                    terminal_state,
                    outcome_class,
                    outcome.write_ready,
                    outcome.admission_hold,
                    outcome.admission_reject,
                    outcome.accepted_payload_count,
                    outcome.provider_dispatches,
                    cooldown,
                    cooldown_started_at,
                    next_text,
                    after,
                    circuit_state,
                    circuit_reason,
                    release_json,
                    int(state[1]),
                    str(state[2]),
                    lease.cycle_id,
                    lease.owner_digest,
                ),
            )
            if circuit_state == "OPEN":
                connection.execute(
                    "UPDATE unpublished_route_circuits SET state='OPEN', "
                    "open_reason=?, opened_at=COALESCE(opened_at, ?), "
                    "release_evidence_json=NULL, release_evidence_digest=NULL "
                    "WHERE route=?",
                    (circuit_reason, now_text, CONT_WRITER_ROUTE),
                )
                release_json = None
            connection.execute(
                "UPDATE unpublished_cycle_governor_state SET "
                "next_cycle_eligible_at=?, last_observed_utc=?, "
                "writer_unproductive_streak=? WHERE singleton=1",
                (next_text, now_text, after),
            )
            ledger_payload: dict[str, object] = {
                "cycle_id": lease.cycle_id,
                "lease_owner_digest": lease.owner_digest,
                "lease_state": "TERMINAL",
                "terminal_state": terminal_state,
                "outcome_class": outcome_class,
                "work_started_at": lease.work_started_at,
                "terminal_at": now_text,
                "elapsed_milliseconds": round(elapsed * 1_000),
                "admission_counts": {
                    "WRITE_READY": outcome.write_ready,
                    "HOLD": outcome.admission_hold,
                    "REJECT": outcome.admission_reject,
                },
                "accepted_payload_count": outcome.accepted_payload_count,
                "writer_provider_dispatch_count": outcome.provider_dispatches,
                "cooldown_policy_version": self._policy.version,
                "cooldown_seconds": cooldown,
                "cooldown_started_at": cooldown_started_at,
                "next_cycle_eligible_at": next_text,
                "writer_unproductive_streak_before": before,
                "writer_unproductive_streak_after": after,
                "writer_circuit_state": circuit_state,
                "writer_circuit_open_reason": circuit_reason,
                "writer_circuit_release_evidence": (
                    json.loads(str(release_json)) if release_json is not None else None
                ),
                "restart_observations": list(lease.restart_observations),
                "refused_early_start_count": int(state[1]),
                "refused_early_start_reason": str(state[2]),
            }
            append_ledger(connection, "PRIVATE_GOVERNED_CYCLE_TERMINAL", ledger_payload)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        release_evidence = (
            json.loads(str(release_json)) if release_json is not None else None
        )
        return CycleTerminalResult(
            cycle_id=lease.cycle_id,
            lease_owner_digest=lease.owner_digest,
            lease_state="TERMINAL",
            terminal_state=terminal_state,
            outcome_class=outcome_class,
            admission_counts={
                "WRITE_READY": outcome.write_ready,
                "HOLD": outcome.admission_hold,
                "REJECT": outcome.admission_reject,
            },
            accepted_payload_count=outcome.accepted_payload_count,
            writer_provider_dispatch_count=outcome.provider_dispatches,
            work_started_at=lease.work_started_at,
            terminal_at=now_text,
            elapsed_seconds=elapsed,
            cooldown_policy_version=self._policy.version,
            cooldown_seconds=cooldown,
            cooldown_started_at=cooldown_started_at,
            next_cycle_eligible_at=next_text,
            writer_unproductive_streak_before=before,
            writer_unproductive_streak_after=after,
            writer_circuit_state=circuit_state,
            writer_circuit_open_reason=circuit_reason,
            writer_circuit_release_evidence=release_evidence,
            restart_observations=lease.restart_observations,
            refused_early_start_count=int(state[1]),
            refused_early_start_reason=str(state[2]),
        )

    def fail_ambiguous(
        self,
        lease: CycleLease,
        *,
        failure_reason: str,
    ) -> CycleTerminalResult:
        """Terminalise a unit whose exception left provider dispatch ambiguous."""

        if not failure_reason.strip():
            raise ValueError("ambiguous cycle failure reason is required")
        return self.complete(
            lease,
            CycleOutcomeInput(
                write_ready=None,
                provider_dispatches=None,
                accepted_payload_count=None,
                admission_hold=None,
                admission_reject=None,
                systemic_provider_failure_reason=failure_reason,
            ),
            terminal_state="FAILED_AMBIGUOUS_PROVIDER_STATE",
        )

    def _release_circuit(
        self,
        *,
        bound_failure_reason: str,
        release_kind: str,
        evidence: dict[str, object],
    ) -> CircuitReleaseEvidence:
        now, now_text = self._now()
        connection = connect(self._path)
        try:
            ensure_cycle_governor_schema(
                connection, policy_version=self._policy.version
            )
            connection.execute("BEGIN IMMEDIATE")
            circuit = connection.execute(
                "SELECT state, open_reason, opened_at FROM unpublished_route_circuits "
                "WHERE route=?",
                (CONT_WRITER_ROUTE,),
            ).fetchone()
            if circuit is None or str(circuit[0]) != "OPEN":
                raise ValueError("route circuit is not open")
            if str(circuit[1]) != bound_failure_reason:
                raise ValueError("release is not bound to the current circuit failure")
            state = connection.execute(
                "SELECT last_observed_utc FROM unpublished_cycle_governor_state "
                "WHERE singleton=1"
            ).fetchone()
            if state is None:
                raise RuntimeError("cycle governor state is missing")
            if state[0] is not None and now < _parse_utc(str(state[0])):
                raise CycleNotEligible(
                    "UTC_CLOCK_BACKWARDS",
                    remaining_seconds=math.inf,
                    next_cycle_eligible_at=None,
                )
            record = {
                "route": CONT_WRITER_ROUTE,
                "release_kind": release_kind,
                "released_at": now_text,
                "policy_version": self._policy.version,
                "bound_failure_reason": bound_failure_reason,
                **evidence,
            }
            digest = digest_bytes(canonical_json_bytes(record))
            record["evidence_digest"] = digest
            raw = canonical_json_bytes(record).decode()
            connection.execute(
                "UPDATE unpublished_route_circuits SET state='CLOSED', open_reason='', "
                "opened_at=NULL, release_evidence_json=?, release_evidence_digest=? "
                "WHERE route=? AND state='OPEN' AND open_reason=?",
                (raw, digest, CONT_WRITER_ROUTE, bound_failure_reason),
            )
            connection.execute(
                "UPDATE unpublished_cycle_governor_state SET "
                "writer_unproductive_streak=0, last_observed_utc=? WHERE singleton=1",
                (now_text,),
            )
            append_ledger(connection, "PRIVATE_WRITER_CIRCUIT_RELEASED", record)
            connection.commit()
            return CircuitReleaseEvidence(
                route=CONT_WRITER_ROUTE,
                release_kind=release_kind,
                released_at=now_text,
                policy_version=self._policy.version,
                bound_failure_reason=bound_failure_reason,
                evidence_digest=digest,
            )
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def release_with_health_probe(
        self,
        *,
        bound_failure_reason: str,
    ) -> CircuitReleaseEvidence:
        if self._writer_route_health_probe is None:
            raise ValueError("CONT writer route health probe is not configured")
        now, now_text = self._now()
        probe_id = digest_bytes(
            canonical_json_bytes(
                {
                    "route": CONT_WRITER_ROUTE,
                    "bound_failure_reason": bound_failure_reason,
                    "attempted_at": now_text,
                }
            )
        )
        reservation: dict[str, object] = {
            "probe_id": probe_id,
            "route": CONT_WRITER_ROUTE,
            "bound_failure_reason": bound_failure_reason,
            "attempted_at": now_text,
            "probe_state": "RESERVED",
            "outcome": None,
            "no_content_probe": True,
            "provider_dispatched": False,
        }
        reservation_digest = digest_bytes(canonical_json_bytes(reservation))
        connection = connect(self._path)
        try:
            ensure_cycle_governor_schema(
                connection, policy_version=self._policy.version
            )
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state, open_reason, opened_at, last_probe_at "
                "FROM unpublished_route_circuits WHERE route=?",
                (CONT_WRITER_ROUTE,),
            ).fetchone()
            if row is None or str(row[0]) != "OPEN":
                raise ValueError("route circuit is not open")
            if str(row[1]) != bound_failure_reason:
                raise ValueError("release is not bound to the current circuit failure")
            state = connection.execute(
                "SELECT last_observed_utc FROM unpublished_cycle_governor_state "
                "WHERE singleton=1"
            ).fetchone()
            if state is None:
                raise RuntimeError("cycle governor state is missing")
            if state[0] is not None and now < _parse_utc(str(state[0])):
                raise CycleNotEligible(
                    "UTC_CLOCK_BACKWARDS",
                    remaining_seconds=math.inf,
                    next_cycle_eligible_at=None,
                )
            earliest = _parse_utc(str(row[2])) + timedelta(
                seconds=self._policy.health_probe_interval_seconds
            )
            if row[3] is not None:
                earliest = max(
                    earliest,
                    _parse_utc(str(row[3]))
                    + timedelta(seconds=self._policy.health_probe_interval_seconds),
                )
            if now < earliest:
                raise CycleNotEligible(
                    "HEALTH_PROBE_INTERVAL",
                    remaining_seconds=_remaining_seconds(now, earliest),
                    next_cycle_eligible_at=_utc_text(earliest),
                )
            connection.execute(
                "INSERT INTO unpublished_route_health_probes("
                "probe_id, route, bound_failure_reason, attempted_at, probe_state, "
                "terminal_at, outcome, provider_dispatched, "
                "provider_receipt_reference, evidence_json, evidence_digest) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    probe_id,
                    CONT_WRITER_ROUTE,
                    bound_failure_reason,
                    now_text,
                    "RESERVED",
                    None,
                    None,
                    0,
                    None,
                    canonical_json_bytes(reservation).decode(),
                    reservation_digest,
                ),
            )
            connection.execute(
                "UPDATE unpublished_route_circuits SET last_probe_at=? WHERE route=?",
                (now_text, CONT_WRITER_ROUTE),
            )
            connection.execute(
                "UPDATE unpublished_cycle_governor_state SET last_observed_utc=? "
                "WHERE singleton=1",
                (now_text,),
            )
            append_ledger(
                connection,
                "PRIVATE_WRITER_ROUTE_HEALTH_PROBE_RESERVED",
                reservation,
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

        probe_exception_class = ""
        try:
            proof = self._writer_route_health_probe()
        except (OSError, RuntimeError, ValueError) as exc:
            probe_exception_class = type(exc).__name__
            proof = WriterRouteHealthProof(
                executable_ok=False,
                authentication_ok=False,
                configuration_ok=False,
                provider_available=False,
                provider_dispatched=False,
                provider_receipt_reference=None,
            )
        provider_receipt_complete = (
            not proof.provider_dispatched
            or proof.provider_receipt_reference is not None
        )
        passed = provider_receipt_complete and all(
            (
                proof.executable_ok,
                proof.authentication_ok,
                proof.configuration_ok,
                proof.provider_available,
            )
        )
        terminal_now, terminal_text = self._now()
        if terminal_now < now:
            raise CycleNotEligible(
                "UTC_CLOCK_BACKWARDS",
                remaining_seconds=math.inf,
                next_cycle_eligible_at=None,
            )
        evidence: dict[str, object] = {
            "probe_id": probe_id,
            "route": CONT_WRITER_ROUTE,
            "bound_failure_reason": bound_failure_reason,
            "attempted_at": now_text,
            "terminal_at": terminal_text,
            "probe_state": "TERMINAL",
            "outcome": "PASSED" if passed else "FAILED",
            "no_content_probe": True,
            "executable_ok": proof.executable_ok,
            "authentication_ok": proof.authentication_ok,
            "configuration_ok": proof.configuration_ok,
            "provider_available": proof.provider_available,
            "provider_dispatched": proof.provider_dispatched,
            "provider_receipt_reference": proof.provider_receipt_reference,
            "provider_receipt_complete": provider_receipt_complete,
            "probe_exception_class": probe_exception_class,
        }
        evidence_digest = digest_bytes(canonical_json_bytes(evidence))
        connection = connect(self._path)
        try:
            ensure_cycle_governor_schema(
                connection, policy_version=self._policy.version
            )
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                "SELECT last_observed_utc FROM unpublished_cycle_governor_state "
                "WHERE singleton=1"
            ).fetchone()
            if state is None:
                raise RuntimeError("cycle governor state is missing")
            if state[0] is not None and terminal_now < _parse_utc(str(state[0])):
                raise CycleNotEligible(
                    "UTC_CLOCK_BACKWARDS",
                    remaining_seconds=math.inf,
                    next_cycle_eligible_at=None,
                )
            changed = connection.execute(
                "UPDATE unpublished_route_health_probes SET probe_state='TERMINAL', "
                "terminal_at=?, outcome=?, provider_dispatched=?, "
                "provider_receipt_reference=?, evidence_json=?, evidence_digest=? "
                "WHERE probe_id=? AND probe_state='RESERVED'",
                (
                    terminal_text,
                    "PASSED" if passed else "FAILED",
                    int(proof.provider_dispatched),
                    proof.provider_receipt_reference,
                    canonical_json_bytes(evidence).decode(),
                    evidence_digest,
                    probe_id,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("health probe reservation is no longer active")
            connection.execute(
                "UPDATE unpublished_cycle_governor_state SET last_observed_utc=? "
                "WHERE singleton=1",
                (terminal_text,),
            )
            append_ledger(connection, "PRIVATE_WRITER_ROUTE_HEALTH_PROBE", evidence)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        if not passed:
            raise ValueError("health probe did not prove every required route property")
        return self._release_circuit(
            bound_failure_reason=bound_failure_reason,
            release_kind="DETERMINISTIC_HEALTH_PROBE",
            evidence=evidence,
        )

    def authorised_operator_reset(
        self,
        *,
        bound_failure_reason: str,
        policy_version: str,
        authorised_by: str,
        evidence_reference: str,
    ) -> CircuitReleaseEvidence:
        if policy_version != self._policy.version:
            raise ValueError("operator reset policy version is not current")
        if not authorised_by.strip() or not evidence_reference.strip():
            raise ValueError("operator reset requires authority and evidence reference")
        requested_at = _utc_text(self._utc_clock())
        request = OperatorResetRequest(
            route=CONT_WRITER_ROUTE,
            bound_failure_reason=bound_failure_reason,
            policy_version=policy_version,
            authorised_by=authorised_by,
            evidence_reference=evidence_reference,
            requested_at=requested_at,
        )
        if self._operator_reset_verifier is None or not self._operator_reset_verifier(
            request
        ):
            raise ValueError("operator reset authority proof is absent or invalid")
        return self._release_circuit(
            bound_failure_reason=bound_failure_reason,
            release_kind="AUTHORISED_OPERATOR_RESET",
            evidence={
                "authorised_by": authorised_by,
                "evidence_reference": evidence_reference,
                "authority_request_digest": digest_bytes(
                    canonical_json_bytes(
                        {
                            "route": request.route,
                            "bound_failure_reason": request.bound_failure_reason,
                            "policy_version": request.policy_version,
                            "authorised_by": request.authorised_by,
                            "evidence_reference": request.evidence_reference,
                            "requested_at": request.requested_at,
                        }
                    )
                ),
            },
        )

    def status(self) -> CycleGovernorStatus:
        connection = connect(self._path)
        try:
            ensure_cycle_governor_schema(
                connection, policy_version=self._policy.version
            )
            state = connection.execute(
                "SELECT policy_version, next_cycle_eligible_at, last_observed_utc, "
                "writer_unproductive_streak, refused_early_start_count, "
                "refused_early_start_reason FROM unpublished_cycle_governor_state "
                "WHERE singleton=1"
            ).fetchone()
            circuit = connection.execute(
                "SELECT state, open_reason, release_evidence_json "
                "FROM unpublished_route_circuits WHERE route=?",
                (CONT_WRITER_ROUTE,),
            ).fetchone()
            active = connection.execute(
                "SELECT cycle_id, lease_state, owner_digest "
                "FROM unpublished_governed_cycles WHERE lease_state='ACTIVE'"
            ).fetchone()
            latest = connection.execute(
                "SELECT cycle_id, owner_digest, lease_state, terminal_state, outcome_class, "
                "work_started_at, terminal_at, elapsed_seconds, write_ready, "
                "admission_hold, admission_reject, accepted_payload_count, "
                "provider_dispatches, cooldown_policy_version, cooldown_seconds, "
                "cooldown_started_at, next_cycle_eligible_at, "
                "writer_unproductive_streak_before, writer_unproductive_streak_after, "
                "writer_circuit_state, writer_circuit_open_reason, "
                "restart_observations_json, refused_early_start_count, "
                "refused_early_start_reason "
                "FROM unpublished_governed_cycles ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if state is None or circuit is None:
            raise RuntimeError("cycle governor state is missing")
        latest_names = (
            "cycle_id",
            "lease_owner_digest",
            "lease_state",
            "terminal_state",
            "outcome_class",
            "work_started_at",
            "terminal_at",
            "elapsed_seconds",
            "write_ready",
            "admission_hold",
            "admission_reject",
            "accepted_payload_count",
            "writer_provider_dispatch_count",
            "cooldown_policy_version",
            "cooldown_seconds",
            "cooldown_started_at",
            "next_cycle_eligible_at",
            "writer_unproductive_streak_before",
            "writer_unproductive_streak_after",
            "writer_circuit_state",
            "writer_circuit_open_reason",
            "restart_observations",
            "refused_early_start_count",
            "refused_early_start_reason",
        )
        latest_record: dict[str, object] | None = (
            {str(name): value for name, value in zip(latest_names, latest, strict=True)}
            if latest
            else None
        )
        if latest_record is not None and latest_record["restart_observations"]:
            latest_record["restart_observations"] = json.loads(
                str(latest_record["restart_observations"])
            )
        release = json.loads(str(circuit[2])) if circuit[2] is not None else None
        return CycleGovernorStatus(
            policy_version=str(state[0]),
            next_cycle_eligible_at=str(state[1]) if state[1] is not None else None,
            last_observed_utc=str(state[2]) if state[2] is not None else None,
            writer_unproductive_streak=int(state[3]),
            writer_circuit_state=str(circuit[0]),
            writer_circuit_open_reason=str(circuit[1]),
            writer_circuit_release_evidence=release,
            refused_early_start_count=int(state[4]),
            refused_early_start_reason=str(state[5]),
            active_cycle_id=str(active[0]) if active else None,
            active_lease_state=str(active[1]) if active else None,
            active_lease_owner_digest=str(active[2]) if active else None,
            latest_cycle=latest_record,
        )
