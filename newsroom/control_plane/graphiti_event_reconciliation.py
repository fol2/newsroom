"""Provider-free repair of missing durable Graphiti revision events."""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.control_plane.command_auth import HERMES_COMMAND_PRINCIPAL
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.cycle import load_graphiti_units_from_connection
from newsroom.control_plane.graphiti_events import (
    GRAPHITI_EVENT_PROJECTION_GENERATION,
    GRAPHITI_EVENT_PROJECTOR_VERSION,
    graphiti_unit_refs,
    reconcile_graphiti_events,
)
from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile
from newsroom.control_plane.store import (
    EFFECTIVE_REVISION_LANDED,
    LEDGER_GENESIS,
    append_ledger,
    connect,
)
from newsroom.control_plane.veto import assert_private_store


GRAPHITI_EVENT_REPAIR_COMMAND_TYPE = "RECONCILE_GRAPHITI_EVENTS"
_PLAN_SCHEMA = "newsroom.control-plane.graphiti-event-reconciliation-plan.v1"
_RECEIPT_SCHEMA = "newsroom.control-plane.graphiti-event-reconciliation-receipt.v1"


class GraphitiEventReconciliationError(RuntimeError):
    """The retained stores do not support the requested event repair."""


class GraphitiEventRepairDisposition(StrEnum):
    PROJECT_EVENT = "PROJECT_EVENT"
    HOLD = "HOLD"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class _GraphitiEventReconciliationCommand:
    caller_principal: str
    writer_principal: str
    command_type: str
    idempotency_key: str
    expected_plan_digest: str


@dataclass(frozen=True, slots=True)
class GraphitiEventRepairDecision:
    event_id: str
    ledger_seq: int
    source_id: str
    item_key: str
    revision_digest: str
    published_at: str
    updated_at: str
    landed_ingest_ids: tuple[str, ...]
    resolved_ingest_ids: tuple[str, ...]
    resolved_chunk_ordinals: tuple[int, ...]
    resolved_unit_refs_digest: str
    disposition: GraphitiEventRepairDisposition
    reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "ledger_seq": self.ledger_seq,
            "source_id": self.source_id,
            "item_key": self.item_key,
            "revision_digest": self.revision_digest,
            "published_at": self.published_at,
            "updated_at": self.updated_at,
            "landed_ingest_ids": list(self.landed_ingest_ids),
            "resolved_ingest_ids": list(self.resolved_ingest_ids),
            "resolved_chunk_ordinals": list(self.resolved_chunk_ordinals),
            "resolved_unit_refs_digest": self.resolved_unit_refs_digest,
            "disposition": self.disposition.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GraphitiEventRepairHold:
    event_id: str
    ledger_seq: int
    reason: str

    def __post_init__(self) -> None:
        if not self.event_id or not self.reason or self.ledger_seq <= 0:
            raise GraphitiEventReconciliationError(
                "event-repair hold identity is invalid"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "ledger_seq": self.ledger_seq,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GraphitiEventRepairProjection:
    event_id: str
    ledger_seq: int
    manifest_digest: str
    unit_count: int

    def __post_init__(self) -> None:
        if not self.event_id or self.ledger_seq <= 0 or self.unit_count <= 0:
            raise GraphitiEventReconciliationError(
                "event-repair projection identity is invalid"
            )
        try:
            validate_sha256_digest(
                self.manifest_digest,
                field="event-repair projection manifest digest",
            )
        except (TypeError, ValueError) as exc:
            raise GraphitiEventReconciliationError(str(exc)) from exc

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "ledger_seq": self.ledger_seq,
            "manifest_digest": self.manifest_digest,
            "unit_count": self.unit_count,
        }


@dataclass(frozen=True, slots=True)
class GraphitiEventReconciliationPlan:
    evaluated_at: str
    store_identity: dict[str, dict[str, object]]
    decisions: tuple[GraphitiEventRepairDecision, ...]
    provider_calls: int = 0

    def _unsigned(self) -> dict[str, object]:
        counts = Counter(item.disposition.value for item in self.decisions)
        return {
            "schema": _PLAN_SCHEMA,
            "evaluated_at": self.evaluated_at,
            "store_identity": self.store_identity,
            "provider_calls": self.provider_calls,
            "decision_counts": dict(sorted(counts.items())),
            "decisions": [item.as_dict() for item in self.decisions],
        }

    @property
    def plan_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self._unsigned()))

    @property
    def unclassified_count(self) -> int:
        return sum(
            item.disposition is GraphitiEventRepairDisposition.UNCLASSIFIED
            for item in self.decisions
        )

    def as_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "plan_digest": self.plan_digest}


@dataclass(frozen=True, slots=True)
class GraphitiEventReconciliationReceipt:
    idempotency_key: str
    plan_digest: str
    store_identity: dict[str, dict[str, object]]
    authenticated_principal: str
    applied_at: str
    projected_event_count: int
    projected_events: tuple[GraphitiEventRepairProjection, ...]
    hold_count: int
    held_events: tuple[GraphitiEventRepairHold, ...]
    unclassified_count: int
    provider_calls: int
    ledger_digest: str
    receipt_digest: str

    def _unsigned(self) -> dict[str, object]:
        return {
            "schema": _RECEIPT_SCHEMA,
            "idempotency_key": self.idempotency_key,
            "plan_digest": self.plan_digest,
            "store_identity": self.store_identity,
            "authenticated_principal": self.authenticated_principal,
            "applied_at": self.applied_at,
            "projected_event_count": self.projected_event_count,
            "projected_events": [item.as_dict() for item in self.projected_events],
            "hold_count": self.hold_count,
            "held_events": [item.as_dict() for item in self.held_events],
            "unclassified_count": self.unclassified_count,
            "provider_calls": self.provider_calls,
            "public_dispatch": False,
            "graph_mutation": False,
            "ledger_digest": self.ledger_digest,
        }

    def as_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> GraphitiEventReconciliationReceipt:
        identity = value.get("store_identity")
        if not isinstance(identity, Mapping) or any(
            not isinstance(key, str) or not isinstance(item, Mapping)
            for key, item in identity.items()
        ):
            raise GraphitiEventReconciliationError(
                "retained event-repair store identity is invalid"
            )
        raw_projected = value.get("projected_events")
        if not isinstance(raw_projected, list) or not all(
            isinstance(item, Mapping)
            and set(item) == {"event_id", "ledger_seq", "manifest_digest", "unit_count"}
            for item in raw_projected
        ):
            raise GraphitiEventReconciliationError(
                "retained event-repair projections are invalid"
            )
        projected_events = tuple(
            GraphitiEventRepairProjection(
                event_id=str(item["event_id"]),
                ledger_seq=_positive_int(
                    item["ledger_seq"], field="projected event ledger_seq"
                ),
                manifest_digest=str(item["manifest_digest"]),
                unit_count=_positive_int(
                    item["unit_count"], field="projected event unit_count"
                ),
            )
            for item in raw_projected
        )
        raw_holds = value.get("held_events")
        if not isinstance(raw_holds, list) or not all(
            isinstance(item, Mapping) and set(item) == {"event_id", "ledger_seq", "reason"}
            for item in raw_holds
        ):
            raise GraphitiEventReconciliationError(
                "retained event-repair holds are invalid"
            )
        held_events = tuple(
            GraphitiEventRepairHold(
                event_id=str(item["event_id"]),
                ledger_seq=_positive_int(
                    item["ledger_seq"], field="held event ledger_seq"
                ),
                reason=str(item["reason"]),
            )
            for item in raw_holds
        )
        receipt = cls(
            idempotency_key=str(value.get("idempotency_key", "")),
            plan_digest=str(value.get("plan_digest", "")),
            store_identity={
                str(key): {str(k): v for k, v in item.items()}
                for key, item in identity.items()
            },
            authenticated_principal=str(value.get("authenticated_principal", "")),
            applied_at=str(value.get("applied_at", "")),
            projected_event_count=_non_negative_int(
                value.get("projected_event_count"), field="projected_event_count"
            ),
            projected_events=projected_events,
            hold_count=_non_negative_int(value.get("hold_count"), field="hold_count"),
            held_events=held_events,
            unclassified_count=_non_negative_int(
                value.get("unclassified_count"), field="unclassified_count"
            ),
            provider_calls=_non_negative_int(
                value.get("provider_calls"), field="provider_calls"
            ),
            ledger_digest=str(value.get("ledger_digest", "")),
            receipt_digest=str(value.get("receipt_digest", "")),
        )
        if (
            value.get("schema") != _RECEIPT_SCHEMA
            or value.get("public_dispatch") is not False
            or value.get("graph_mutation") is not False
            or receipt.authenticated_principal != HERMES_COMMAND_PRINCIPAL
            or receipt.provider_calls != 0
            or receipt.unclassified_count != 0
            or receipt.projected_event_count != len(receipt.projected_events)
            or tuple(
                sorted(
                    receipt.projected_events,
                    key=lambda item: (item.ledger_seq, item.event_id),
                )
            )
            != receipt.projected_events
            or len({item.event_id for item in receipt.projected_events})
            != len(receipt.projected_events)
            or len({item.ledger_seq for item in receipt.projected_events})
            != len(receipt.projected_events)
            or receipt.hold_count != len(receipt.held_events)
            or tuple(
                sorted(
                    receipt.held_events,
                    key=lambda item: (item.ledger_seq, item.event_id),
                )
            )
            != receipt.held_events
            or len({item.event_id for item in receipt.held_events})
            != len(receipt.held_events)
            or len({item.ledger_seq for item in receipt.held_events})
            != len(receipt.held_events)
            or {item.event_id for item in receipt.projected_events}
            & {item.event_id for item in receipt.held_events}
            or {item.ledger_seq for item in receipt.projected_events}
            & {item.ledger_seq for item in receipt.held_events}
            or receipt.receipt_digest
            != digest_bytes(canonical_json_bytes(receipt._unsigned()))
            or canonical_json_bytes(value) != canonical_json_bytes(receipt.as_dict())
        ):
            raise GraphitiEventReconciliationError(
                "retained event-repair receipt violates its canonical contract"
            )
        return receipt


def _non_negative_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GraphitiEventReconciliationError(
            f"event-repair receipt {field} is invalid"
        )
    return value


def _positive_int(value: object, *, field: str) -> int:
    result = _non_negative_int(value, field=field)
    if result == 0:
        raise GraphitiEventReconciliationError(
            f"event-repair receipt {field} is invalid"
        )
    return result


def _utc_text(value: datetime) -> str:
    instant = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _read_connection(path: str) -> sqlite3.Connection:
    assert_private_store(path)
    resolved = Path(path).expanduser().resolve()
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    apply_control_plane_sqlite_profile(connection, query_only=True)
    connection.execute("BEGIN")
    return connection


def _store_identity(path: str, connection: sqlite3.Connection) -> dict[str, object]:
    resolved = Path(path).expanduser().resolve()
    stat = os.stat(resolved)
    tables = [
        tuple(str(value or "") for value in row)
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    ]
    ledger = (
        connection.execute(
            "SELECT seq,digest FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if any(row[1] == "ledger" and row[0] == "table" for row in tables)
        else None
    )
    return {
        "path": str(resolved),
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "mtime_ns": str(stat.st_mtime_ns),
        "schema_digest": digest_canonical(tables),
        "ledger_watermark": 0 if ledger is None else int(ledger[0]),
        "ledger_digest": None if ledger is None else str(ledger[1]),
    }


def _assert_distinct_store_paths(
    proving_store: str,
    unpublished_store: str,
) -> None:
    proving = Path(proving_store).expanduser().resolve()
    unpublished = Path(unpublished_store).expanduser().resolve()
    proving_stat = os.stat(proving)
    unpublished_stat = os.stat(unpublished)
    if proving == unpublished or (
        proving_stat.st_dev,
        proving_stat.st_ino,
    ) == (
        unpublished_stat.st_dev,
        unpublished_stat.st_ino,
    ):
        raise GraphitiEventReconciliationError(
            "proving and unpublished event-repair stores must be distinct"
        )


def _landed_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    required = {"ledger", "unpublished_effective_revision_landed", "unpublished_graphiti_revision_events"}
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if not required.issubset(present):
        raise GraphitiEventReconciliationError(
            "event repair requires the landed ledger and existing Graphiti queue"
        )
    return connection.execute(
        """
        SELECT ledger.seq,ledger.digest,landed.source_id,landed.item_key,
               landed.revision_digest,landed.published_at,landed.updated_at,
               landed.first_observed_at,landed.ingest_ids_json,
               landed.payload_digest,ledger.kind,ledger.payload_digest,
               landed.legacy_v10
        FROM unpublished_effective_revision_landed AS landed
        JOIN ledger ON ledger.digest=landed.ledger_digest
        LEFT JOIN unpublished_graphiti_revision_events AS event
          ON event.event_id=ledger.digest
        WHERE event.event_id IS NULL AND NOT (
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
    ).fetchall()


def _row_identity(row: sqlite3.Row) -> tuple[str, str, str, str, str]:
    return (
        str(row[2]),
        str(row[3]),
        str(row[4]),
        str(row[5] or ""),
        str(row[6] or ""),
    )


def _validate_landed_row(row: sqlite3.Row) -> tuple[tuple[str, ...], str | None]:
    try:
        raw_ids = json.loads(str(row[8]))
    except (TypeError, json.JSONDecodeError):
        return (), "LANDED_INGEST_IDENTITIES_MALFORMED"
    if (
        not isinstance(raw_ids, list)
        or not all(isinstance(item, str) and item for item in raw_ids)
        or len(set(raw_ids)) != len(raw_ids)
    ):
        return (), "LANDED_INGEST_IDENTITIES_MALFORMED"
    if type(row[0]) is not int or type(row[12]) is not int or row[12] not in (0, 1):
        return tuple(raw_ids), "LANDED_LEDGER_IDENTITY_MALFORMED"
    payload: dict[str, object] = {
        "source_id": str(row[2]),
        "item_key": str(row[3]),
        "revision_digest": str(row[4]),
        "first_observed_at": str(row[7]),
    }
    if row[12]:
        if row[5] or row[6] or raw_ids:
            return tuple(raw_ids), "LEGACY_LANDED_FIELDS_MALFORMED"
    else:
        payload.update(
            {
                "published_at": str(row[5] or ""),
                "updated_at": str(row[6] or ""),
                "ingest_ids": raw_ids,
            }
        )
    reconstructed = digest_canonical(payload)
    if row[10] != EFFECTIVE_REVISION_LANDED:
        return tuple(raw_ids), "LANDED_LEDGER_KIND_DIFFERS"
    if reconstructed != row[9] or reconstructed != row[11]:
        return tuple(raw_ids), "LANDED_PAYLOAD_IDENTITY_DIFFERS"
    return tuple(raw_ids), None


def _resolved_reason(
    units: tuple[CorpusIngestUnit, ...], landed_ingest_ids: tuple[str, ...]
) -> str | None:
    if not units:
        return "RESOLVED_CHUNKS_INCOMPLETE"
    ordinals = tuple(item.chunk_ordinal for item in units)
    chunk_counts = {item.chunk_count for item in units}
    if len(chunk_counts) != 1 or ordinals != tuple(range(1, next(iter(chunk_counts)) + 1)):
        return "RESOLVED_CHUNKS_INCOMPLETE"
    ingest_ids = tuple(item.ingest_id for item in units)
    if len(set(ingest_ids)) != len(ingest_ids):
        return "RESOLVED_CHUNKS_INCOMPLETE"
    if ingest_ids != landed_ingest_ids:
        return "RESOLVED_INGEST_IDS_DIFFER_FROM_LANDED"
    return None


def _build_plan(
    *,
    proving_store: str,
    unpublished_store: str,
    proving: sqlite3.Connection,
    unpublished: sqlite3.Connection,
    evaluated_at: datetime,
) -> tuple[GraphitiEventReconciliationPlan, dict[str, tuple[CorpusIngestUnit, ...]]]:
    identities = {
        "proving_store": _store_identity(proving_store, proving),
        "unpublished_store": _store_identity(unpublished_store, unpublished),
    }
    proving_identity = identities["proving_store"]
    unpublished_identity = identities["unpublished_store"]
    if (
        proving_identity["path"] == unpublished_identity["path"]
        or (
            proving_identity["device"],
            proving_identity["inode"],
        )
        == (
            unpublished_identity["device"],
            unpublished_identity["inode"],
        )
    ):
        raise GraphitiEventReconciliationError(
            "proving and unpublished event-repair stores must be distinct"
        )
    _validate_event_repair_ledger_chain(unpublished)
    decisions, selected_by_event = _classify_event_gaps(
        proving=proving,
        unpublished=unpublished,
        evaluated_at=evaluated_at,
    )
    relevant_state_digest = digest_canonical(
        [item.as_dict() for item in decisions]
    )
    for identity in identities.values():
        identity["event_repair_state_digest"] = relevant_state_digest
    plan = GraphitiEventReconciliationPlan(
        evaluated_at=_utc_text(evaluated_at),
        store_identity=identities,
        decisions=decisions,
    )
    return plan, selected_by_event


def _classify_event_gaps(
    *,
    proving: sqlite3.Connection,
    unpublished: sqlite3.Connection,
    evaluated_at: datetime,
    resolved_units: tuple[CorpusIngestUnit, ...] | None = None,
    unit_resolution_failure: str | None = None,
) -> tuple[
    tuple[GraphitiEventRepairDecision, ...],
    dict[str, tuple[CorpusIngestUnit, ...]],
]:
    if resolved_units is None:
        try:
            units = load_graphiti_units_from_connection(
                proving,
                evaluated_at=evaluated_at,
            )
        except (sqlite3.Error, ValueError):
            units = ()
            unit_resolution_failure = "CURRENT_UNIT_RESOLUTION_UNAVAILABLE"
    else:
        units = resolved_units
    grouped: dict[tuple[str, str, str, str, str], list[CorpusIngestUnit]] = {}
    for unit in units:
        key = (
            unit.source_id,
            unit.item_key,
            unit.revision_digest,
            unit.published_at or "",
            unit.updated_at or "",
        )
        grouped.setdefault(key, []).append(unit)
    retained_holds = retained_graphiti_event_holds(
        unpublished,
        validate_effects=False,
    )
    decisions: list[GraphitiEventRepairDecision] = []
    selected_by_event: dict[str, tuple[CorpusIngestUnit, ...]] = {}
    observed_event_ids: set[str] = set()
    for row in _landed_rows(unpublished):
        event_id = str(row[1])
        observed_event_ids.add(event_id)
        landed_ids, unclassified_reason = _validate_landed_row(row)
        selected = tuple(
            sorted(grouped.get(_row_identity(row), ()), key=lambda item: item.chunk_ordinal)
        )
        retained_hold = retained_holds.get(event_id)
        if unclassified_reason is not None:
            disposition = GraphitiEventRepairDisposition.UNCLASSIFIED
            reason = unclassified_reason
        elif retained_hold is not None:
            if retained_hold.ledger_seq != int(row[0]):
                raise GraphitiEventReconciliationError(
                    "retained event-repair hold ledger identity differs"
                )
            disposition = GraphitiEventRepairDisposition.HOLD
            reason = retained_hold.reason
        elif unit_resolution_failure is not None:
            disposition = GraphitiEventRepairDisposition.UNCLASSIFIED
            reason = unit_resolution_failure
        else:
            reason = _resolved_reason(selected, landed_ids)
            disposition = (
                GraphitiEventRepairDisposition.PROJECT_EVENT
                if reason is None
                else GraphitiEventRepairDisposition.HOLD
            )
        decisions.append(
            GraphitiEventRepairDecision(
                event_id=event_id,
                ledger_seq=int(row[0]),
                source_id=str(row[2]),
                item_key=str(row[3]),
                revision_digest=str(row[4]),
                published_at=str(row[5] or ""),
                updated_at=str(row[6] or ""),
                landed_ingest_ids=landed_ids,
                resolved_ingest_ids=tuple(item.ingest_id for item in selected),
                resolved_chunk_ordinals=tuple(item.chunk_ordinal for item in selected),
                resolved_unit_refs_digest=digest_canonical(
                    graphiti_unit_refs(selected)
                ),
                disposition=disposition,
                reason=reason,
            )
        )
        if disposition is GraphitiEventRepairDisposition.PROJECT_EVENT:
            selected_by_event[event_id] = selected
    if set(retained_holds) - observed_event_ids:
        raise GraphitiEventReconciliationError(
            "retained event-repair hold has no exact missing landing"
        )
    return tuple(decisions), selected_by_event


def classify_graphiti_event_gaps(
    proving: sqlite3.Connection,
    unpublished: sqlite3.Connection,
    *,
    evaluated_at: datetime,
    resolved_units: tuple[CorpusIngestUnit, ...] | None = None,
    unit_resolution_failure: str | None = None,
) -> tuple[GraphitiEventRepairDecision, ...]:
    """Classify every current event gap without changing either store."""

    decisions, _selected = _classify_event_gaps(
        proving=proving,
        unpublished=unpublished,
        evaluated_at=evaluated_at,
        resolved_units=resolved_units,
        unit_resolution_failure=unit_resolution_failure,
    )
    return decisions


def plan_graphiti_event_reconciliation(
    proving_store: str,
    unpublished_store: str,
    *,
    evaluated_at: datetime,
) -> GraphitiEventReconciliationPlan:
    """Build a content-addressed repair plan without canonical writes."""

    _assert_distinct_store_paths(proving_store, unpublished_store)
    proving = _read_connection(proving_store)
    unpublished = _read_connection(unpublished_store)
    try:
        plan, _selected = _build_plan(
            proving_store=proving_store,
            unpublished_store=unpublished_store,
            proving=proving,
            unpublished=unpublished,
            evaluated_at=evaluated_at,
        )
        return plan
    finally:
        proving.rollback()
        unpublished.rollback()
        proving.close()
        unpublished.close()


def _validate_supplied_plan(
    dry_run_plan: Mapping[str, object], expected_plan_digest: str
) -> None:
    supplied = dict(dry_run_plan)
    digest = supplied.pop("plan_digest", None)
    if (
        supplied.get("schema") != _PLAN_SCHEMA
        or supplied.get("provider_calls") != 0
        or digest != expected_plan_digest
        or digest_bytes(canonical_json_bytes(supplied)) != expected_plan_digest
    ):
        raise GraphitiEventReconciliationError(
            "dry-run event-repair plan differs from its expected digest"
        )


def _assert_command(command: _GraphitiEventReconciliationCommand) -> None:
    if command.caller_principal != HERMES_COMMAND_PRINCIPAL:
        raise PermissionError("Graphiti event repair requires Hermes")
    if command.writer_principal != "newsroom.control-plane.command-service":
        raise PermissionError("Graphiti event repair requires command service")
    if command.command_type != GRAPHITI_EVENT_REPAIR_COMMAND_TYPE:
        raise PermissionError("Graphiti event-repair command type differs")
    if not command.idempotency_key or not command.expected_plan_digest:
        raise GraphitiEventReconciliationError(
            "Graphiti event-repair command identity is incomplete"
        )


def _retained_receipt(
    connection: sqlite3.Connection,
    command: _GraphitiEventReconciliationCommand,
) -> GraphitiEventReconciliationReceipt | None:
    row = connection.execute(
        "SELECT caller_principal,writer_principal,command_type,"
        "expected_mapping_digest,receipt_json FROM "
        "unpublished_reconciliation_commands WHERE idempotency_key=?",
        (command.idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    if (
        row[0] != command.caller_principal
        or row[1] != command.writer_principal
        or row[2] != command.command_type
        or row[3] != command.expected_plan_digest
    ):
        raise GraphitiEventReconciliationError(
            "event-repair idempotency key was reused for another command"
        )
    return _validate_retained_receipt(
        connection,
        idempotency_key=command.idempotency_key,
        caller_principal=str(row[0]),
        writer_principal=str(row[1]),
        command_type=str(row[2]),
        expected_plan_digest=str(row[3]),
        receipt_json=str(row[4]),
    )


def _validate_retained_receipt(
    connection: sqlite3.Connection,
    *,
    idempotency_key: str,
    caller_principal: str,
    writer_principal: str,
    command_type: str,
    expected_plan_digest: str,
    receipt_json: str,
    validate_effects: bool = True,
    validate_ledger_chain: bool = True,
) -> GraphitiEventReconciliationReceipt:
    if (
        caller_principal != HERMES_COMMAND_PRINCIPAL
        or writer_principal != "newsroom.control-plane.command-service"
        or command_type != GRAPHITI_EVENT_REPAIR_COMMAND_TYPE
    ):
        raise GraphitiEventReconciliationError(
            "retained event-repair command authority is invalid"
        )
    try:
        value = json.loads(receipt_json)
    except json.JSONDecodeError as exc:
        raise GraphitiEventReconciliationError(
            "retained event-repair receipt is malformed"
        ) from exc
    if not isinstance(value, Mapping):
        raise GraphitiEventReconciliationError(
            "retained event-repair receipt is not an object"
        )
    receipt = GraphitiEventReconciliationReceipt.from_dict(value)
    if (
        receipt.idempotency_key != idempotency_key
        or receipt.plan_digest != expected_plan_digest
    ):
        raise GraphitiEventReconciliationError(
            "retained event-repair receipt command binding differs"
        )
    if validate_effects:
        _validate_projected_event_effects(connection, receipt.projected_events)
        _validate_held_event_effects(connection, receipt.held_events)
    if validate_ledger_chain:
        _validate_event_repair_ledger_chain(connection)
    ledger_event = {
        "idempotency_key": receipt.idempotency_key,
        "plan_digest": receipt.plan_digest,
        "store_identity": receipt.store_identity,
        "authenticated_principal": receipt.authenticated_principal,
        "applied_at": receipt.applied_at,
        "projected_event_count": receipt.projected_event_count,
        "projected_events": [item.as_dict() for item in receipt.projected_events],
        "hold_count": receipt.hold_count,
        "held_events": [item.as_dict() for item in receipt.held_events],
        "unclassified_count": receipt.unclassified_count,
        "provider_calls": receipt.provider_calls,
        "public_dispatch": False,
        "graph_mutation": False,
    }
    ledger_row = connection.execute(
        "SELECT kind,payload_digest,payload_json FROM ledger WHERE digest=?",
        (receipt.ledger_digest,),
    ).fetchone()
    expected_ledger_bytes = canonical_json_bytes(ledger_event)
    if (
        ledger_row is None
        or ledger_row[0] != "GRAPHITI_EVENT_RECONCILIATION_APPLIED"
        or ledger_row[1] != digest_bytes(expected_ledger_bytes)
        or str(ledger_row[2]).encode("utf-8") != expected_ledger_bytes
    ):
        raise GraphitiEventReconciliationError(
            "retained event-repair receipt differs from its ledger record"
        )
    return receipt


def _validate_event_repair_ledger_chain(connection: sqlite3.Connection) -> None:
    previous_digest = LEDGER_GENESIS
    for expected_seq, row in enumerate(
        connection.execute(
            "SELECT seq,at,kind,payload_digest,prev_digest,digest "
            "FROM ledger ORDER BY seq"
        ).fetchall(),
        start=1,
    ):
        expected_digest = digest_canonical(
            {
                "at": row[1],
                "kind": row[2],
                "payload_digest": row[3],
                "prev": row[4],
            }
        )
        if (
            row[0] != expected_seq
            or row[4] != previous_digest
            or row[5] != expected_digest
        ):
            raise GraphitiEventReconciliationError(
                "retained event-repair ledger chain differs"
            )
        previous_digest = str(row[5])


def _validate_projected_event_effects(
    connection: sqlite3.Connection,
    projected_events: tuple[GraphitiEventRepairProjection, ...],
) -> None:
    for projected in projected_events:
        landed = _validated_landed_effect(
            connection,
            event_id=projected.event_id,
            ledger_seq=projected.ledger_seq,
        )
        row = connection.execute(
            "SELECT ledger_seq,ledger_digest,source_id,item_key,revision_digest,"
            "published_at,updated_at,landed_at,manifest_json,manifest_digest,"
            "unit_count,projector_version,projection_generation FROM "
            "unpublished_graphiti_revision_events WHERE event_id=?",
            (projected.event_id,),
        ).fetchone()
        if row is None:
            raise GraphitiEventReconciliationError(
                "retained event-repair projection is missing"
            )
        try:
            manifest = json.loads(str(row[8]))
        except json.JSONDecodeError as exc:
            raise GraphitiEventReconciliationError(
                "retained event-repair projection manifest is malformed"
            ) from exc
        unit_refs = manifest.get("unit_refs") if isinstance(manifest, Mapping) else None
        if (
            int(row[0]) != projected.ledger_seq
            or str(row[1]) != projected.event_id
            or tuple(str(value or "") for value in row[2:7])
            != tuple(str(value or "") for value in landed[2:7])
            or str(row[7]) != str(landed[7])
            or not isinstance(manifest, Mapping)
            or digest_canonical(manifest) != projected.manifest_digest
            or str(row[9]) != projected.manifest_digest
            or int(row[10]) != projected.unit_count
            or not isinstance(unit_refs, list)
            or len(unit_refs) != projected.unit_count
            or manifest.get("ledger_seq") != projected.ledger_seq
            or manifest.get("ledger_digest") != projected.event_id
            or str(row[11]) != GRAPHITI_EVENT_PROJECTOR_VERSION
            or str(row[12]) != GRAPHITI_EVENT_PROJECTION_GENERATION
        ):
            raise GraphitiEventReconciliationError(
                "retained event-repair projection identity differs"
            )


def _validated_landed_effect(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    ledger_seq: int,
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT ledger.seq,ledger.digest,landed.source_id,landed.item_key,"
        "landed.revision_digest,landed.published_at,landed.updated_at,"
        "landed.first_observed_at,landed.ingest_ids_json,landed.payload_digest,"
        "ledger.kind,ledger.payload_digest,landed.legacy_v10 FROM "
        "unpublished_effective_revision_landed AS landed JOIN ledger "
        "ON ledger.digest=landed.ledger_digest WHERE ledger.digest=?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise GraphitiEventReconciliationError(
            "retained event-repair landing is missing"
        )
    _landed_ids, reason = _validate_landed_row(row)
    if reason is not None or int(row[0]) != ledger_seq or str(row[1]) != event_id:
        raise GraphitiEventReconciliationError(
            "retained event-repair landing identity differs"
        )
    return row


def _validate_held_event_effects(
    connection: sqlite3.Connection,
    held_events: tuple[GraphitiEventRepairHold, ...],
) -> None:
    for held in held_events:
        _validated_landed_effect(
            connection,
            event_id=held.event_id,
            ledger_seq=held.ledger_seq,
        )
        if connection.execute(
            "SELECT 1 FROM unpublished_graphiti_revision_events WHERE event_id=?",
            (held.event_id,),
        ).fetchone() is not None:
            raise GraphitiEventReconciliationError(
                "retained event-repair hold was projected"
            )


def retained_graphiti_event_holds(
    connection: sqlite3.Connection,
    *,
    validate_effects: bool = True,
) -> dict[str, GraphitiEventRepairHold]:
    """Return authenticated durable event holds from the existing command ledger."""

    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='unpublished_reconciliation_commands'"
    ).fetchone()
    if table is None:
        command_rows = []
    else:
        command_rows = connection.execute(
            "SELECT idempotency_key,caller_principal,writer_principal,command_type,"
            "expected_mapping_digest,receipt_json FROM "
            "unpublished_reconciliation_commands WHERE command_type=? "
            "ORDER BY idempotency_key",
            (GRAPHITI_EVENT_REPAIR_COMMAND_TYPE,),
        ).fetchall()
    ledger_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger'"
    ).fetchone()
    if ledger_table is None:
        if command_rows:
            raise GraphitiEventReconciliationError(
                "retained event-repair commands have no ledger"
            )
        return {}
    ledger_digests = {
        str(row[0])
        for row in connection.execute(
            "SELECT digest FROM ledger "
            "WHERE kind='GRAPHITI_EVENT_RECONCILIATION_APPLIED'"
        ).fetchall()
    }
    holds: dict[str, GraphitiEventRepairHold] = {}
    ledger_sequences: dict[int, str] = {}
    receipt_ledger_owners: dict[str, str] = {}
    if command_rows or ledger_digests:
        _validate_event_repair_ledger_chain(connection)
    for row in command_rows:
        receipt = _validate_retained_receipt(
            connection,
            idempotency_key=str(row[0]),
            caller_principal=str(row[1]),
            writer_principal=str(row[2]),
            command_type=str(row[3]),
            expected_plan_digest=str(row[4]),
            receipt_json=str(row[5]),
            validate_effects=validate_effects,
            validate_ledger_chain=False,
        )
        prior_owner = receipt_ledger_owners.get(receipt.ledger_digest)
        if prior_owner is not None and prior_owner != receipt.idempotency_key:
            raise GraphitiEventReconciliationError(
                "retained event-repair ledger identity conflicts"
            )
        receipt_ledger_owners[receipt.ledger_digest] = receipt.idempotency_key
        for hold in receipt.held_events:
            prior = holds.get(hold.event_id)
            prior_event = ledger_sequences.get(hold.ledger_seq)
            if (prior is not None and prior != hold) or (
                prior_event is not None and prior_event != hold.event_id
            ):
                raise GraphitiEventReconciliationError(
                    "retained event-repair hold identity conflicts"
                )
            holds[hold.event_id] = hold
            ledger_sequences[hold.ledger_seq] = hold.event_id
    if set(receipt_ledger_owners) != ledger_digests:
        raise GraphitiEventReconciliationError(
            "retained event-repair commands differ from their ledger events"
        )
    return holds


def _apply_graphiti_event_reconciliation(
    proving_store: str,
    unpublished_store: str,
    *,
    dry_run_plan: Mapping[str, object],
    evaluated_at: datetime,
    applied_at: datetime,
    command: _GraphitiEventReconciliationCommand,
) -> GraphitiEventReconciliationReceipt:
    _assert_command(command)
    _assert_distinct_store_paths(proving_store, unpublished_store)
    _validate_supplied_plan(dry_run_plan, command.expected_plan_digest)
    proving = _read_connection(proving_store)
    unpublished = connect(unpublished_store)
    try:
        unpublished.execute("BEGIN IMMEDIATE")
        retained = _retained_receipt(unpublished, command)
        if retained is not None:
            unpublished.commit()
            return retained
        live_plan, selected_by_event = _build_plan(
            proving_store=proving_store,
            unpublished_store=unpublished_store,
            proving=proving,
            unpublished=unpublished,
            evaluated_at=evaluated_at,
        )
        if live_plan.unclassified_count:
            raise GraphitiEventReconciliationError(
                "event-repair plan contains unclassified landed revisions"
            )
        if (
            live_plan.plan_digest != command.expected_plan_digest
            or canonical_json_bytes(live_plan.as_dict())
            != canonical_json_bytes(dry_run_plan)
        ):
            raise GraphitiEventReconciliationError(
                "stores changed after the dry-run event-repair plan"
            )
        projected = 0
        for decision in live_plan.decisions:
            if decision.disposition is not GraphitiEventRepairDisposition.PROJECT_EVENT:
                continue
            projected += reconcile_graphiti_events(
                unpublished,
                selected_by_event[decision.event_id],
                available_at=evaluated_at,
                event_id=decision.event_id,
            )
        expected_projected = sum(
            item.disposition is GraphitiEventRepairDisposition.PROJECT_EVENT
            for item in live_plan.decisions
        )
        if projected != expected_projected:
            raise GraphitiEventReconciliationError(
                "projected Graphiti event count differs from the repair plan"
            )
        projected_events: list[GraphitiEventRepairProjection] = []
        for decision in live_plan.decisions:
            if decision.disposition is not GraphitiEventRepairDisposition.PROJECT_EVENT:
                continue
            row = unpublished.execute(
                "SELECT ledger_seq,manifest_digest,unit_count FROM "
                "unpublished_graphiti_revision_events WHERE event_id=?",
                (decision.event_id,),
            ).fetchone()
            if row is None:
                raise GraphitiEventReconciliationError(
                    "projected Graphiti event is missing after repair"
                )
            projected_events.append(
                GraphitiEventRepairProjection(
                    event_id=decision.event_id,
                    ledger_seq=int(row[0]),
                    manifest_digest=str(row[1]),
                    unit_count=int(row[2]),
                )
            )
        projected_event_records = tuple(projected_events)
        held_events = tuple(
            GraphitiEventRepairHold(
                event_id=item.event_id,
                ledger_seq=item.ledger_seq,
                reason=str(item.reason),
            )
            for item in live_plan.decisions
            if item.disposition is GraphitiEventRepairDisposition.HOLD
        )
        hold_count = len(held_events)
        applied_text = _utc_text(applied_at)
        ledger_event = {
            "idempotency_key": command.idempotency_key,
            "plan_digest": live_plan.plan_digest,
            "store_identity": live_plan.store_identity,
            "authenticated_principal": command.caller_principal,
            "applied_at": applied_text,
            "projected_event_count": projected,
            "projected_events": [
                item.as_dict() for item in projected_event_records
            ],
            "hold_count": hold_count,
            "held_events": [item.as_dict() for item in held_events],
            "unclassified_count": 0,
            "provider_calls": 0,
            "public_dispatch": False,
            "graph_mutation": False,
        }
        ledger_digest = append_ledger(
            unpublished, "GRAPHITI_EVENT_RECONCILIATION_APPLIED", ledger_event
        )
        unsigned = GraphitiEventReconciliationReceipt(
            idempotency_key=command.idempotency_key,
            plan_digest=live_plan.plan_digest,
            store_identity=live_plan.store_identity,
            authenticated_principal=command.caller_principal,
            applied_at=applied_text,
            projected_event_count=projected,
            projected_events=projected_event_records,
            hold_count=hold_count,
            held_events=held_events,
            unclassified_count=0,
            provider_calls=0,
            ledger_digest=ledger_digest,
            receipt_digest="",
        )
        receipt = GraphitiEventReconciliationReceipt(
            **{
                **{field: getattr(unsigned, field) for field in (
                    "idempotency_key", "plan_digest", "store_identity",
                    "authenticated_principal", "applied_at",
                    "projected_event_count", "projected_events", "hold_count",
                    "held_events", "unclassified_count",
                    "provider_calls", "ledger_digest",
                )},
                "receipt_digest": digest_bytes(canonical_json_bytes(unsigned._unsigned())),
            }
        )
        unpublished.execute(
            """
            INSERT INTO unpublished_reconciliation_commands(
                idempotency_key,caller_principal,writer_principal,command_type,
                expected_mapping_digest,receipt_json,at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                command.idempotency_key,
                command.caller_principal,
                command.writer_principal,
                command.command_type,
                command.expected_plan_digest,
                canonical_json_bytes(receipt.as_dict()).decode("utf-8"),
                applied_text,
            ),
        )
        unpublished.commit()
        return receipt
    except Exception:
        if unpublished.in_transaction:
            unpublished.rollback()
        raise
    finally:
        proving.rollback()
        proving.close()
        unpublished.close()


__all__ = [
    "classify_graphiti_event_gaps",
    "GraphitiEventRepairDisposition",
    "GraphitiEventRepairHold",
    "GraphitiEventRepairProjection",
    "GraphitiEventReconciliationError",
    "GraphitiEventReconciliationPlan",
    "GraphitiEventReconciliationReceipt",
    "plan_graphiti_event_reconciliation",
    "retained_graphiti_event_holds",
]
