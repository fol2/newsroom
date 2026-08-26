"""Durable Graphiti projection of effective-revision ledger events."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.store import EFFECTIVE_REVISION_LANDED
from newsroom.control_plane.veto import assert_private_store

GRAPHITI_EVENT_STATES = (
    "QUEUED",
    "CLAIMED",
    "RUNNING",
    "RETRY_HELD",
    "RIGHTS_HELD",
    "CONFIGURATION_HELD",
    "DEAD_LETTER",
    "TERMINAL",
)
GRAPHITI_EVENT_PROJECTOR_VERSION = "newsroom.graphiti-event-projector.v1"
GRAPHITI_EVENT_PROJECTION_GENERATION = "graphiti-event-projection-2026-08"
_MAX_MANIFEST_BYTES = 1024 * 1024


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _connect(path: str) -> sqlite3.Connection:
    from newsroom.control_plane.store import connect

    assert_private_store(path)
    connection = connect(path)
    ensure_graphiti_event_schema(connection)
    return connection


def _recover_expired_claims(connection: sqlite3.Connection, *, now_text: str) -> None:
    connection.execute(
        """
        UPDATE unpublished_graphiti_revision_events
        SET state='QUEUED', claim_owner=NULL, claim_expires_at=NULL
        WHERE state IN ('CLAIMED','RUNNING')
          AND claim_expires_at IS NOT NULL AND claim_expires_at<=?
        """,
        (now_text,),
    )


def ensure_graphiti_event_schema(connection: sqlite3.Connection) -> None:
    """Fail closed unless the unpublished-store migration installed the schema."""

    required = {
        "unpublished_graphiti_revision_events",
        "unpublished_graphiti_event_checkpoint",
        "unpublished_graphiti_event_circuit",
    }
    installed = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not required.issubset(installed):
        raise RuntimeError("Graphiti event projection schema is not installed")


@dataclass(frozen=True, slots=True)
class GraphitiRevisionEvent:
    event_id: str
    ledger_seq: int
    source_id: str
    item_key: str
    revision_digest: str
    published_at: str
    updated_at: str
    expected_unit_count: int
    landed_ingest_ids: tuple[str, ...]
    landed_payload_digest: str
    unit_refs: tuple[dict[str, object], ...]
    state: str
    attempt_count: int
    units: tuple[CorpusIngestUnit, ...]


@dataclass(frozen=True, slots=True)
class GraphitiQueueHealth:
    state_counts: dict[str, int]
    eligible_revision_count: int
    terminal_revision_count: int
    terminal_coverage_percent: float
    queue_depth: int
    arrival_velocity_per_hour: float
    service_velocity_per_hour: float
    oldest_unresolved_lag_seconds: int | None
    p50_terminal_latency_seconds: float | None
    p95_terminal_latency_seconds: float | None
    contiguous_coverage_watermark: int | None
    circuit_open: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "state_counts": self.state_counts,
            "eligible_revision_count": self.eligible_revision_count,
            "terminal_revision_count": self.terminal_revision_count,
            "terminal_coverage_percent": self.terminal_coverage_percent,
            "queue_depth": self.queue_depth,
            "arrival_velocity_per_hour": self.arrival_velocity_per_hour,
            "service_velocity_per_hour": self.service_velocity_per_hour,
            "oldest_unresolved_lag_seconds": self.oldest_unresolved_lag_seconds,
            "p50_terminal_latency_seconds": self.p50_terminal_latency_seconds,
            "p95_terminal_latency_seconds": self.p95_terminal_latency_seconds,
            "contiguous_coverage_watermark": self.contiguous_coverage_watermark,
            "circuit_open": self.circuit_open,
        }


@dataclass(frozen=True, slots=True)
class GraphitiDispatchGate:
    allowed: bool
    reason: str | None = None

    @classmethod
    def allow(cls) -> GraphitiDispatchGate:
        return cls(True)

    @classmethod
    def hold(cls, reason: str) -> GraphitiDispatchGate:
        if not reason:
            raise ValueError("Graphiti dispatch hold requires a reason")
        return cls(False, reason)


@dataclass(frozen=True, slots=True)
class GraphitiDispatchResult:
    state: str
    proposal_count: int
    failure_code: str | None
    provider_dispatched: bool

    @classmethod
    def terminal(
        cls, *, proposal_count: int, provider_dispatched: bool
    ) -> GraphitiDispatchResult:
        if type(proposal_count) is not int or proposal_count < 0:
            raise ValueError("terminal proposal_count must be non-negative")
        return cls("TERMINAL", proposal_count, None, provider_dispatched)

    @classmethod
    def retry_held(
        cls, *, failure_code: str, provider_dispatched: bool
    ) -> GraphitiDispatchResult:
        return cls("RETRY_HELD", 0, failure_code, provider_dispatched)

    @classmethod
    def dead_letter(
        cls, *, failure_code: str, provider_dispatched: bool
    ) -> GraphitiDispatchResult:
        return cls("DEAD_LETTER", 0, failure_code, provider_dispatched)


@dataclass(frozen=True, slots=True)
class GraphitiProcessResult:
    event_id: str
    ledger_seq: int
    state: str
    attempt_count: int


class SystemicGraphitiEventFailure(RuntimeError):
    """A route-level failure that must pause the whole Graphiti consumer."""

    def __init__(self, message: str, *, provider_dispatched: bool = False) -> None:
        super().__init__(message)
        self.provider_dispatched = provider_dispatched


class ConfigurationGraphitiEventFailure(SystemicGraphitiEventFailure):
    """A deterministic local configuration refusal requiring operator change."""


def _landed_rows(
    connection: sqlite3.Connection,
) -> list[
    tuple[int, str, str, str, str, str, str, str, str, str, str, str, object]
]:
    raw_rows = connection.execute(
        """
        SELECT ledger.seq,ledger.digest,landed.source_id,landed.item_key,
               landed.revision_digest,landed.published_at,landed.updated_at,
               landed.first_observed_at,landed.ingest_ids_json,
               landed.payload_digest,ledger.kind,ledger.payload_digest,
               landed.legacy_v10
        FROM unpublished_effective_revision_landed AS landed
        JOIN ledger ON ledger.digest=landed.ledger_digest
        WHERE NOT (
            landed.legacy_v10=1 AND EXISTS (
                SELECT 1 FROM unpublished_effective_revision_landed AS marker
                WHERE marker.legacy_v10=0
                  AND marker.source_id=landed.source_id
                  AND marker.item_key=landed.item_key
                  AND marker.revision_digest=landed.revision_digest
                  AND marker.first_observed_at=landed.first_observed_at
                  AND (marker.published_at<>'' OR marker.updated_at<>'')
            )
        )
        ORDER BY ledger.seq
        """
    )
    return [
        (
            int(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5] or ""),
            str(row[6] or ""),
            str(row[7]),
            str(row[8]),
            str(row[9]),
            str(row[10]),
            str(row[11]),
            row[12],
        )
        for row in raw_rows
    ]


def _unit_refs(units: tuple[CorpusIngestUnit, ...]) -> list[dict[str, object]]:
    return [
        {
            "ingest_id": item.ingest_id,
            "proving_run_id": item.proving_run_id,
            "observation_digest": item.observation_digest,
            "revision_id": item.revision_id,
            "representation_digest": item.representation_digest,
            "chunk_digest": item.digest,
            "chunk_ordinal": item.chunk_ordinal,
            "predecessor_ingest_id": item.predecessor_ingest_id,
            "observed_at": item.observed_at,
            "effective_pull_first_observed_at": (item.effective_pull_first_observed_at),
            "authority_record_ids": (
                []
                if item.authority is None
                else [str(record["record_id"]) for record in item.authority.records]
            ),
        }
        for item in units
    ]


def _manifest_json(manifest: dict[str, object]) -> str:
    value = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if len(value.encode("utf-8")) > _MAX_MANIFEST_BYTES:
        raise ValueError("Graphiti routing manifest exceeds its byte bound")
    return value


def reconcile_graphiti_events(
    connection: sqlite3.Connection,
    units: tuple[CorpusIngestUnit, ...],
    *,
    available_at: datetime,
) -> int:
    """Project committed landed ledger obligations in a consumer transaction."""

    if not connection.in_transaction:
        raise RuntimeError("Graphiti event reconciliation requires a transaction")
    grouped: dict[tuple[str, str, str, str, str], list[CorpusIngestUnit]] = {}
    for unit in units:
        coverage = unit.coverage_key()
        key = (
            coverage.source_id,
            coverage.item_key,
            coverage.revision_digest,
            coverage.published_at,
            coverage.updated_at,
        )
        grouped.setdefault(key, []).append(unit)
    inserted = 0
    for row in _landed_rows(connection):
        ledger_seq, ledger_digest = int(row[0]), str(row[1])
        key = (row[2], row[3], row[4], row[5], row[6])
        landed_ingest_ids_value = json.loads(row[8])
        if not isinstance(landed_ingest_ids_value, list) or not all(
            isinstance(item, str) for item in landed_ingest_ids_value
        ):
            raise ValueError("landed Graphiti ingest identities are malformed")
        landed_ingest_ids = tuple(landed_ingest_ids_value)
        if type(row[12]) is not int or row[12] not in (0, 1):
            raise ValueError("landed Graphiti legacy marker is malformed")
        landed_payload = {
            "source_id": row[2],
            "item_key": row[3],
            "revision_digest": row[4],
            "first_observed_at": row[7],
        }
        if row[12]:
            if row[5] or row[6] or landed_ingest_ids:
                raise ValueError("legacy landed Graphiti fields are malformed")
        else:
            landed_payload.update(
                {
                    "published_at": row[5],
                    "updated_at": row[6],
                    "ingest_ids": list(landed_ingest_ids),
                }
            )
        reconstructed_payload_digest = digest_canonical(landed_payload)
        if row[10] != EFFECTIVE_REVISION_LANDED:
            raise ValueError("landed Graphiti ledger kind differs")
        if not (
            reconstructed_payload_digest == row[9]
            and reconstructed_payload_digest == row[11]
        ):
            raise ValueError("landed Graphiti payload digest differs from ledger")
        ordered = tuple(
            sorted(grouped.get(key, ()), key=lambda item: item.chunk_ordinal)
        )
        if ordered:
            expected = tuple(range(1, ordered[0].chunk_count + 1))
            if tuple(item.chunk_ordinal for item in ordered) != expected:
                raise ValueError("effective-revision event chunks are incomplete")
        resolved_refs = _unit_refs(ordered)
        manifest: dict[str, object] = {
            "event_type": "EFFECTIVE_SOURCE_REVISION_LANDED",
            "ledger_seq": ledger_seq,
            "ledger_digest": ledger_digest,
            "landed_ingest_ids": list(landed_ingest_ids),
            "landed_payload_digest": row[9],
            "unit_refs": resolved_refs,
        }
        manifest_json = _manifest_json(manifest)
        cursor = connection.execute(
            """
            INSERT INTO unpublished_graphiti_revision_events(
                event_id,ledger_seq,ledger_digest,source_id,item_key,
                revision_digest,published_at,updated_at,landed_at,
                manifest_json,manifest_digest,unit_count,projector_version,
                projection_generation,state,available_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'QUEUED',?)
            ON CONFLICT(event_id) DO UPDATE SET
                manifest_json=excluded.manifest_json,
                manifest_digest=excluded.manifest_digest,
                unit_count=excluded.unit_count,
                state='QUEUED',available_at=excluded.available_at
            WHERE unpublished_graphiti_revision_events.unit_count=0
              AND excluded.unit_count>0
            """,
            (
                ledger_digest,
                ledger_seq,
                ledger_digest,
                *(str(item or "") for item in row[2:8]),
                manifest_json,
                digest_canonical(manifest),
                len(ordered),
                GRAPHITI_EVENT_PROJECTOR_VERSION,
                GRAPHITI_EVENT_PROJECTION_GENERATION,
                _utc_text(available_at),
            ),
        )
        inserted += cursor.rowcount
    return inserted


class GraphitiEventQueue:
    """At-least-once consumer projection at effective-revision grain."""

    def __init__(
        self, path: str, *, clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)
    ) -> None:
        self._path = path
        self._clock = clock
        connection = _connect(path)
        connection.close()

    def claim(
        self, *, owner_id: str, lease_for: timedelta
    ) -> GraphitiRevisionEvent | None:
        if not owner_id or lease_for <= timedelta(0):
            raise ValueError("claim requires an owner and positive lease")
        now, now_text = self._clock(), _utc_text(self._clock())
        connection = _connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            reconcile_graphiti_events(connection, (), available_at=now)
            circuit = connection.execute(
                "SELECT state,available_at FROM unpublished_graphiti_event_circuit WHERE singleton=1"
            ).fetchone()
            if (
                circuit
                and str(circuit[0]) == "OPEN"
                and circuit[1]
                and str(circuit[1]) > now_text
            ):
                connection.commit()
                return None
            if circuit and str(circuit[0]) == "OPEN":
                connection.execute(
                    "UPDATE unpublished_graphiti_event_circuit SET state='CLOSED',"
                    "opened_at=NULL,available_at=NULL,failure_code=NULL WHERE singleton=1"
                )
            _recover_expired_claims(connection, now_text=now_text)
            while True:
                row = connection.execute(
                    """
                    SELECT event_id,ledger_seq,source_id,item_key,revision_digest,
                           published_at,updated_at,unit_count,manifest_json,
                           manifest_digest,attempt_count
                    FROM unpublished_graphiti_revision_events
                    WHERE state IN ('QUEUED','RETRY_HELD','RIGHTS_HELD') AND available_at<=?
                    ORDER BY ledger_seq LIMIT 1
                    """,
                    (now_text,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                try:
                    manifest = json.loads(str(row[8]))
                    if not isinstance(manifest, dict):
                        raise TypeError("effective-revision manifest is malformed")
                    if digest_canonical(manifest) != str(row[9]):
                        raise ValueError("effective-revision manifest digest differs")
                    if manifest.get("ledger_seq") != int(row[1]):
                        raise ValueError("event object ledger sequence differs")
                    unit_refs = manifest.get("unit_refs")
                    if not isinstance(unit_refs, list) or not all(
                        isinstance(item, dict) for item in unit_refs
                    ):
                        raise TypeError("effective-revision unit refs are malformed")
                    landed_ingest_ids = manifest.get("landed_ingest_ids")
                    if not isinstance(landed_ingest_ids, list) or not all(
                        isinstance(item, str) for item in landed_ingest_ids
                    ):
                        raise TypeError("landed ingest identities are malformed")
                    landed_payload_digest = manifest.get("landed_payload_digest")
                    if not isinstance(landed_payload_digest, str):
                        raise TypeError("landed payload digest is malformed")
                except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                    connection.execute(
                        "UPDATE unpublished_graphiti_revision_events SET state='DEAD_LETTER',"
                        "last_failure_code='EVENT_OBJECT_INVALID',claim_owner=NULL,"
                        "claim_expires_at=NULL WHERE event_id=?",
                        (str(row[0]),),
                    )
                    continue
                connection.execute(
                    "UPDATE unpublished_graphiti_revision_events SET state='CLAIMED',"
                    "claim_owner=?,claim_expires_at=? WHERE event_id=?",
                    (owner_id, _utc_text(now + lease_for), str(row[0])),
                )
                connection.commit()
                return GraphitiRevisionEvent(
                    event_id=str(row[0]),
                    ledger_seq=int(row[1]),
                    source_id=str(row[2]),
                    item_key=str(row[3]),
                    revision_digest=str(row[4]),
                    published_at=str(row[5]),
                    updated_at=str(row[6]),
                    expected_unit_count=int(row[7]),
                    landed_ingest_ids=tuple(landed_ingest_ids),
                    landed_payload_digest=landed_payload_digest,
                    unit_refs=tuple(unit_refs),
                    state="CLAIMED",
                    attempt_count=int(row[10]),
                    units=(),
                )
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def process_one(
        self,
        *,
        owner_id: str,
        gate: Callable[[GraphitiRevisionEvent], GraphitiDispatchGate],
        dispatch: Callable[[GraphitiRevisionEvent], GraphitiDispatchResult],
        lease_for: timedelta = timedelta(minutes=15),
        hold_for: timedelta = timedelta(minutes=5),
        retry_after: timedelta = timedelta(seconds=30),
        circuit_for: timedelta = timedelta(minutes=5),
        max_attempts: int = 3,
    ) -> GraphitiProcessResult | None:
        event = self.claim(owner_id=owner_id, lease_for=lease_for)
        if event is None:
            return None
        attempt = self._start(event.event_id, owner_id=owner_id)
        running = GraphitiRevisionEvent(
            event_id=event.event_id,
            ledger_seq=event.ledger_seq,
            source_id=event.source_id,
            item_key=event.item_key,
            revision_digest=event.revision_digest,
            published_at=event.published_at,
            updated_at=event.updated_at,
            expected_unit_count=event.expected_unit_count,
            landed_ingest_ids=event.landed_ingest_ids,
            landed_payload_digest=event.landed_payload_digest,
            unit_refs=event.unit_refs,
            state="RUNNING",
            attempt_count=attempt,
            units=event.units,
        )
        try:
            decision = gate(running)
            if not isinstance(decision, GraphitiDispatchGate):
                raise TypeError(
                    "Graphiti dispatch gate must return GraphitiDispatchGate"
                )
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
            self._transition(
                event.event_id,
                owner_id=owner_id,
                state="RETRY_HELD",
                available_at=self._clock() + retry_after,
                failure_code=f"GATE_{type(exc).__name__}",
                provider_dispatched=False,
            )
            return GraphitiProcessResult(
                event.event_id, event.ledger_seq, "RETRY_HELD", attempt
            )
        if not decision.allowed:
            self._transition(
                event.event_id,
                owner_id=owner_id,
                state="RIGHTS_HELD",
                available_at=self._clock() + hold_for,
                failure_code=decision.reason,
                provider_dispatched=False,
            )
            return GraphitiProcessResult(
                event.event_id, event.ledger_seq, "RIGHTS_HELD", attempt
            )
        try:
            result = dispatch(running)
            if not isinstance(result, GraphitiDispatchResult):
                raise TypeError("Graphiti dispatch must return GraphitiDispatchResult")
        except ConfigurationGraphitiEventFailure as exc:
            code = str(exc) or type(exc).__name__
            self._open_circuit(code, duration=circuit_for)
            self._transition(
                event.event_id,
                owner_id=owner_id,
                state="CONFIGURATION_HELD",
                available_at=self._clock() + circuit_for,
                failure_code=code,
                provider_dispatched=exc.provider_dispatched,
            )
            return GraphitiProcessResult(
                event.event_id, event.ledger_seq, "CONFIGURATION_HELD", attempt
            )
        except SystemicGraphitiEventFailure as exc:
            code = str(exc) or type(exc).__name__
            self._open_circuit(code, duration=circuit_for)
            state = "RETRY_HELD"
            self._transition(
                event.event_id,
                owner_id=owner_id,
                state=state,
                available_at=self._clock() + retry_after,
                failure_code=code,
                provider_dispatched=exc.provider_dispatched,
            )
            return GraphitiProcessResult(
                event.event_id, event.ledger_seq, state, attempt
            )
        except (
            json.JSONDecodeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            state = "DEAD_LETTER" if attempt >= max_attempts else "RETRY_HELD"
            self._transition(
                event.event_id,
                owner_id=owner_id,
                state=state,
                available_at=self._clock() + retry_after,
                failure_code=type(exc).__name__,
                provider_dispatched=False,
            )
            return GraphitiProcessResult(
                event.event_id, event.ledger_seq, state, attempt
            )
        if result.state not in {"TERMINAL", "RETRY_HELD", "DEAD_LETTER"}:
            raise ValueError("Graphiti dispatch result state is invalid")
        state = (
            "DEAD_LETTER"
            if result.state == "RETRY_HELD" and attempt >= max_attempts
            else result.state
        )
        self._transition(
            event.event_id,
            owner_id=owner_id,
            state=state,
            available_at=self._clock() + retry_after,
            failure_code=result.failure_code,
            provider_dispatched=result.provider_dispatched,
            proposal_count=result.proposal_count if state == "TERMINAL" else None,
        )
        return GraphitiProcessResult(event.event_id, event.ledger_seq, state, attempt)

    def bind_resolved_units(
        self,
        event: GraphitiRevisionEvent,
        *,
        owner_id: str,
        units: tuple[CorpusIngestUnit, ...],
    ) -> None:
        """Durably bind hydrated chunk identities before provider dispatch."""

        ordered = tuple(sorted(units, key=lambda item: item.chunk_ordinal))
        if not ordered or tuple(item.chunk_ordinal for item in ordered) != tuple(
            range(1, ordered[0].chunk_count + 1)
        ):
            raise ValueError("resolved Graphiti chunks are incomplete")
        if any(
            (
                item.source_id,
                item.item_key,
                item.revision_digest,
                item.published_at or "",
                item.updated_at or "",
            )
            != (
                event.source_id,
                event.item_key,
                event.revision_digest,
                event.published_at,
                event.updated_at,
            )
            for item in ordered
        ):
            raise ValueError("resolved Graphiti chunks differ from the ledger event")
        resolved_refs = _unit_refs(ordered)
        resolved_ingest_ids = tuple(item.ingest_id for item in ordered)
        if event.landed_ingest_ids and (resolved_ingest_ids != event.landed_ingest_ids):
            raise ValueError("resolved Graphiti ingest IDs differ from landed IDs")
        manifest: dict[str, object] = {
            "event_type": "EFFECTIVE_SOURCE_REVISION_LANDED",
            "ledger_seq": event.ledger_seq,
            "ledger_digest": event.event_id,
            "landed_ingest_ids": list(event.landed_ingest_ids),
            "landed_payload_digest": event.landed_payload_digest,
            "unit_refs": resolved_refs,
        }
        manifest_json = _manifest_json(manifest)
        connection = _connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT unit_count,manifest_json
                FROM unpublished_graphiti_revision_events
                WHERE event_id=? AND state='RUNNING' AND claim_owner=?
                """,
                (event.event_id, owner_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("Graphiti event binding lost its claim")
            if int(row[0]) > 0:
                retained = json.loads(str(row[1]))
                retained_refs = (
                    retained.get("unit_refs") if isinstance(retained, dict) else None
                )
                stable = lambda ref: (
                    ref.get("ingest_id"),
                    ref.get("revision_id"),
                    ref.get("representation_digest"),
                    ref.get("chunk_digest"),
                    ref.get("chunk_ordinal"),
                    ref.get("predecessor_ingest_id"),
                )
                if not isinstance(retained_refs, list) or tuple(
                    stable(ref) for ref in retained_refs if isinstance(ref, dict)
                ) != tuple(stable(ref) for ref in resolved_refs):
                    raise ValueError(
                        "resolved Graphiti chunks differ from retained refs"
                    )
            else:
                connection.execute(
                    """
                    UPDATE unpublished_graphiti_revision_events
                    SET manifest_json=?,manifest_digest=?,unit_count=?
                    WHERE event_id=? AND state='RUNNING' AND claim_owner=?
                    """,
                    (
                        manifest_json,
                        digest_canonical(manifest),
                        len(ordered),
                        event.event_id,
                        owner_id,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _start(self, event_id: str, *, owner_id: str) -> int:
        connection = _connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE unpublished_graphiti_revision_events SET state='RUNNING',"
                "attempt_count=attempt_count+1 WHERE event_id=? AND state='CLAIMED' AND claim_owner=?",
                (event_id, owner_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Graphiti event claim is no longer owned")
            attempt = int(
                connection.execute(
                    "SELECT attempt_count FROM unpublished_graphiti_revision_events WHERE event_id=?",
                    (event_id,),
                ).fetchone()[0]
            )
            connection.commit()
            return attempt
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _advance_checkpoint(connection: sqlite3.Connection, *, now: str) -> None:
        gap = connection.execute(
            "SELECT MIN(ledger_seq) FROM unpublished_graphiti_revision_events WHERE state<>'TERMINAL'"
        ).fetchone()[0]
        head = int(
            connection.execute("SELECT COALESCE(MAX(seq),0) FROM ledger").fetchone()[0]
        )
        watermark = head if gap is None else max(int(gap) - 1, 0)
        connection.execute(
            "UPDATE unpublished_graphiti_event_checkpoint SET ledger_seq=?,projector_version=?,"
            "projection_generation=?,updated_at=? WHERE singleton=1",
            (
                watermark,
                GRAPHITI_EVENT_PROJECTOR_VERSION,
                GRAPHITI_EVENT_PROJECTION_GENERATION,
                now,
            ),
        )

    def _transition(
        self,
        event_id: str,
        *,
        owner_id: str,
        state: str,
        available_at: datetime,
        failure_code: str | None,
        provider_dispatched: bool,
        proposal_count: int | None = None,
    ) -> None:
        now = _utc_text(self._clock())
        connection = _connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE unpublished_graphiti_revision_events
                SET state=?,available_at=?,claim_owner=NULL,claim_expires_at=NULL,
                    last_failure_code=?,provider_dispatched=?,terminal_at=?,proposal_count=?
                WHERE event_id=? AND state='RUNNING' AND claim_owner=?
                """,
                (
                    state,
                    _utc_text(available_at),
                    failure_code,
                    int(provider_dispatched),
                    now if state == "TERMINAL" else None,
                    proposal_count,
                    event_id,
                    owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Graphiti event transition lost its claim")
            self._advance_checkpoint(connection, now=now)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _open_circuit(self, failure_code: str, *, duration: timedelta) -> None:
        now = self._clock()
        connection = _connect(self._path)
        try:
            connection.execute(
                "UPDATE unpublished_graphiti_event_circuit SET state='OPEN',opened_at=?,"
                "available_at=?,failure_code=? WHERE singleton=1",
                (_utc_text(now), _utc_text(now + duration), failure_code),
            )
            connection.commit()
        finally:
            connection.close()

    def health(self) -> GraphitiQueueHealth:
        connection = _connect(self._path)
        try:
            now = self._clock().astimezone(UTC)
            connection.execute("BEGIN IMMEDIATE")
            reconcile_graphiti_events(connection, (), available_at=now)
            _recover_expired_claims(connection, now_text=_utc_text(now))
            counts = Counter(
                {
                    str(state): int(count)
                    for state, count in connection.execute(
                        "SELECT state,COUNT(*) FROM unpublished_graphiti_revision_events GROUP BY state"
                    )
                }
            )
            state_counts = {state: counts[state] for state in GRAPHITI_EVENT_STATES}
            rows = list(
                connection.execute(
                    "SELECT ledger_seq,landed_at,state,terminal_at FROM unpublished_graphiti_revision_events ORDER BY ledger_seq"
                )
            )
            hour_ago = _utc_text(now - timedelta(hours=1))
            arrivals = sum(str(row[1]) >= hour_ago for row in rows)
            services = sum(
                row[3] is not None and str(row[3]) >= hour_ago for row in rows
            )
            unresolved = [row for row in rows if str(row[2]) != "TERMINAL"]
            oldest_lag = None
            if unresolved:
                landed_times = [
                    datetime.fromisoformat(str(row[1])) for row in unresolved
                ]
                oldest_landed = min(
                    landed.replace(tzinfo=UTC)
                    if landed.tzinfo is None
                    else landed.astimezone(UTC)
                    for landed in landed_times
                )
                oldest_lag = max(int((now - oldest_landed).total_seconds()), 0)
            latencies = sorted(
                max(
                    (
                        datetime.fromisoformat(str(row[3]))
                        - datetime.fromisoformat(str(row[1]))
                    ).total_seconds(),
                    0.0,
                )
                for row in rows
                if row[3] is not None
            )

            def percentile(fraction: float) -> float | None:
                if not latencies:
                    return None
                return float(
                    latencies[max(0, int((len(latencies) - 1) * fraction + 0.5))]
                )

            watermark_row = connection.execute(
                "SELECT ledger_seq FROM unpublished_graphiti_event_checkpoint WHERE singleton=1"
            ).fetchone()
            circuit = connection.execute(
                "SELECT state,available_at FROM unpublished_graphiti_event_circuit WHERE singleton=1"
            ).fetchone()
            terminal, eligible = state_counts["TERMINAL"], len(rows)
            health = GraphitiQueueHealth(
                state_counts,
                eligible,
                terminal,
                100.0 * terminal / eligible if eligible else 0.0,
                sum(
                    state_counts[state]
                    for state in (
                        "QUEUED",
                        "CLAIMED",
                        "RUNNING",
                        "RETRY_HELD",
                        "RIGHTS_HELD",
                        "CONFIGURATION_HELD",
                    )
                ),
                float(arrivals),
                float(services),
                oldest_lag,
                percentile(0.5),
                percentile(0.95),
                int(watermark_row[0])
                if watermark_row and int(watermark_row[0]) > 0
                else None,
                bool(
                    circuit
                    and str(circuit[0]) == "OPEN"
                    and circuit[1]
                    and str(circuit[1]) > _utc_text(now)
                ),
            )
            connection.commit()
            return health
        finally:
            connection.close()


__all__ = [
    "GRAPHITI_EVENT_STATES",
    "ConfigurationGraphitiEventFailure",
    "GraphitiDispatchGate",
    "GraphitiDispatchResult",
    "GraphitiEventQueue",
    "GraphitiProcessResult",
    "GraphitiQueueHealth",
    "GraphitiRevisionEvent",
    "SystemicGraphitiEventFailure",
    "ensure_graphiti_event_schema",
    "reconcile_graphiti_events",
]
