"""Durable coordinator for the single owner-approved issue #790 canary."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.issue_790_contract import (
    ISSUE_790_APPROVED_INVOCATION_ID,
    ISSUE_790_APPROVED_PLAN_DIGEST,
)
from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile
from newsroom.control_plane.veto import assert_private_store

CANARY_PREFLIGHT_SCHEMA = "newsroom.graphiti-fresh-event-preflight.v1"
CANARY_CONSUMPTION_SCHEMA = "newsroom.issue-790.canary-consumption.v2"
CANARY_OUTCOME_SCHEMA = "newsroom.issue-790.canary-outcome.v2"
RETRY_EXCLUSION_SCHEMA = "newsroom.issue-790.graphiti-retry-exclusion.v1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS issue_790_graphiti_retry_exclusions(
    exclusion_digest TEXT PRIMARY KEY,
    approved_plan_digest TEXT NOT NULL,
    disposition_digest TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    ledger_seq INTEGER NOT NULL UNIQUE CHECK(ledger_seq > 0),
    reason TEXT NOT NULL,
    excluded_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY(disposition_digest)
        REFERENCES model_usage_conservative_dispositions(disposition_digest)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS issue_790_bounded_canary_consumptions(
    consumption_digest TEXT PRIMARY KEY,
    approved_plan_digest TEXT NOT NULL UNIQUE,
    disposition_digest TEXT NOT NULL UNIQUE,
    event_id TEXT NOT NULL UNIQUE,
    ledger_seq INTEGER NOT NULL UNIQUE CHECK(ledger_seq > 0),
    owner_id TEXT NOT NULL UNIQUE,
    consumed_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY(disposition_digest)
        REFERENCES model_usage_conservative_dispositions(disposition_digest)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS issue_790_bounded_canary_outcomes(
    outcome_digest TEXT PRIMARY KEY,
    consumption_digest TEXT NOT NULL UNIQUE,
    event_id TEXT NOT NULL UNIQUE,
    ledger_seq INTEGER NOT NULL UNIQUE CHECK(ledger_seq > 0),
    completed_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY(consumption_digest)
        REFERENCES issue_790_bounded_canary_consumptions(consumption_digest)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
"""


class Issue790CanaryIntegrityError(ValueError):
    """The bounded authority, event or retained state is contradictory."""


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise Issue790CanaryIntegrityError("canary timestamp lacks a timezone")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _instant(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise Issue790CanaryIntegrityError(f"{field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Issue790CanaryIntegrityError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise Issue790CanaryIntegrityError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _token(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 1024
    ):
        raise Issue790CanaryIntegrityError(f"{field} is invalid")
    return value


def _object(value: object, *, field: str) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise Issue790CanaryIntegrityError(f"{field} is malformed") from exc
    if not isinstance(value, dict):
        raise Issue790CanaryIntegrityError(f"{field} is malformed")
    return dict(value)


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_addressed_record(
    value: object,
    *,
    digest_field: str,
    field: str,
) -> dict[str, object]:
    record = _object(value, field=field)
    without_digest = dict(record)
    supplied = without_digest.pop(digest_field, None)
    if supplied != digest_canonical(without_digest):
        raise Issue790CanaryIntegrityError(f"{field} digest differs")
    return record


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def graphiti_excluded_event_ids(connection: sqlite3.Connection) -> frozenset[str]:
    """Return exact events which a generic Graphiti worker must never claim."""

    values: set[str] = set()
    if _table_exists(connection, "issue_790_graphiti_retry_exclusions"):
        values.update(
            str(row[0])
            for row in connection.execute(
                "SELECT event_id FROM issue_790_graphiti_retry_exclusions"
            )
        )
    if _table_exists(connection, "issue_790_bounded_canary_consumptions"):
        values.update(
            str(row[0])
            for row in connection.execute(
                "SELECT event_id FROM issue_790_bounded_canary_consumptions"
            )
        )
    return frozenset(values)


def graphiti_retry_excluded(
    connection: sqlite3.Connection,
    *,
    event_id: str,
) -> bool:
    return bool(
        _table_exists(connection, "issue_790_graphiti_retry_exclusions")
        and connection.execute(
            "SELECT 1 FROM issue_790_graphiti_retry_exclusions WHERE event_id=?",
            (event_id,),
        ).fetchone()
        is not None
    )


def validate_graphiti_canary_claim(
    connection: sqlite3.Connection,
    *,
    consumption_digest: str,
    event_id: str,
    owner_id: str,
) -> None:
    if (
        not _table_exists(connection, "issue_790_bounded_canary_consumptions")
        or connection.execute(
            "SELECT 1 FROM issue_790_bounded_canary_consumptions "
            "WHERE consumption_digest=? AND event_id=? AND owner_id=?",
            (consumption_digest, event_id, owner_id),
        ).fetchone()
        is None
    ):
        raise ValueError("bounded canary claim authority differs")


def graphiti_event_has_canary_consumption(
    connection: sqlite3.Connection,
    *,
    event_id: str,
) -> bool:
    return bool(
        _table_exists(connection, "issue_790_bounded_canary_consumptions")
        and connection.execute(
            "SELECT 1 FROM issue_790_bounded_canary_consumptions WHERE event_id=?",
            (event_id,),
        ).fetchone()
        is not None
    )


def _stable_unit_ref(value: Mapping[str, object]) -> tuple[object, ...]:
    return (
        value.get("ingest_id"),
        value.get("revision_id"),
        value.get("representation_digest"),
        value.get("chunk_digest"),
        value.get("chunk_ordinal"),
        value.get("predecessor_ingest_id"),
    )


def _validated_preflight(
    value: Mapping[str, object],
    *,
    event_id: str,
    ledger_seq: int,
    manifest_digest: str,
    consumed_at: datetime,
) -> dict[str, object]:
    retained = dict(value)
    supplied_digest = retained.pop("evidence_digest", None)
    if supplied_digest != digest_canonical(retained):
        raise Issue790CanaryIntegrityError("bounded canary preflight digest differs")
    if (
        retained.get("schema_version") != CANARY_PREFLIGHT_SCHEMA
        or retained.get("event_id") != event_id
        or retained.get("ledger_seq") != ledger_seq
        or retained.get("event_state") != "QUEUED"
        or retained.get("event_attempt_count") != 0
        or retained.get("event_manifest_digest") != manifest_digest
        or retained.get("owner_emergency_stop_clear") is not True
        or retained.get("provider_calls") != 0
        or retained.get("store_mutations") != 0
    ):
        raise Issue790CanaryIntegrityError("bounded canary preflight differs")
    evaluated_at = _instant(retained.get("evaluated_at"), field="preflight time")
    if evaluated_at > consumed_at.astimezone(UTC):
        raise Issue790CanaryIntegrityError("bounded canary preflight follows consumption")
    resolved = retained.get("resolved_units")
    decisions = retained.get("rights_decision_digests")
    if (
        not isinstance(resolved, list)
        or not resolved
        or not all(isinstance(item, dict) for item in resolved)
        or not isinstance(decisions, list)
        or len(decisions) != len(resolved)
        or not all(
            isinstance(item, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", item)
            for item in decisions
        )
    ):
        raise Issue790CanaryIntegrityError("bounded canary preflight units differ")
    ingest_ids: list[str] = []
    ordinals: list[int] = []
    for raw in resolved:
        item = dict(raw)
        if set(item) != {
            "ingest_id",
            "revision_id",
            "representation_digest",
            "chunk_digest",
            "chunk_ordinal",
            "predecessor_ingest_id",
        }:
            raise Issue790CanaryIntegrityError(
                "bounded canary preflight unit fields differ"
            )
        ingest_ids.append(_token(item["ingest_id"], field="preflight ingest id"))
        ordinal = item["chunk_ordinal"]
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal <= 0:
            raise Issue790CanaryIntegrityError(
                "bounded canary preflight chunk ordinal is invalid"
            )
        ordinals.append(ordinal)
        for field in ("revision_id", "representation_digest", "chunk_digest"):
            _token(item[field], field=f"preflight {field}")
        predecessor = item["predecessor_ingest_id"]
        if predecessor is not None:
            _token(predecessor, field="preflight predecessor ingest id")
    if len(set(ingest_ids)) != len(ingest_ids) or ordinals != list(
        range(1, len(ordinals) + 1)
    ):
        raise Issue790CanaryIntegrityError("bounded canary preflight order differs")
    return {**retained, "evidence_digest": supplied_digest}


class Issue790CanaryRepository:
    """Own the #790 exclusion, consumption and zero-I/O finalisation state."""

    def __init__(self, path: str) -> None:
        assert_private_store(path)
        self.path = path
        connection = self._connection()
        try:
            connection.executescript(_SCHEMA)
            connection.commit()
        finally:
            connection.close()

    @classmethod
    def open_existing(cls, path: str) -> Issue790CanaryRepository:
        """Open an already-installed coordinator without a write-capable setup."""

        assert_private_store(path)
        instance = cls.__new__(cls)
        instance.path = path
        connection = instance._read_connection()
        try:
            required = {
                "issue_790_graphiti_retry_exclusions",
                "issue_790_bounded_canary_consumptions",
                "issue_790_bounded_canary_outcomes",
            }
            installed = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not required.issubset(installed):
                raise Issue790CanaryIntegrityError(
                    "bounded canary coordinator schema is absent"
                )
        finally:
            connection.close()
        return instance

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        apply_control_plane_sqlite_profile(connection)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _read_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"{Path(self.path).absolute().as_uri()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        apply_control_plane_sqlite_profile(connection, query_only=True)
        return connection

    def retain_retry_exclusions(
        self,
        *,
        approved_plan_digest: str,
        disposition_digest: str,
        events: Sequence[Mapping[str, object]],
        excluded_at: datetime,
    ) -> tuple[dict[str, object], ...]:
        if approved_plan_digest != ISSUE_790_APPROVED_PLAN_DIGEST:
            raise Issue790CanaryIntegrityError("retry exclusion plan differs")
        disposition_digest = _token(
            disposition_digest, field="retry exclusion disposition digest"
        )
        excluded_at_text = _utc_text(excluded_at)
        expected = tuple(events)
        if len(expected) != 2 or tuple(
            int(item.get("ledger_seq", 0)) for item in expected
        ) != (1932, 1972):
            raise Issue790CanaryIntegrityError("retry exclusion targets differ")
        connection = self._connection()
        retained: list[dict[str, object]] = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            disposition = connection.execute(
                "SELECT invocation_id FROM model_usage_conservative_dispositions "
                "WHERE disposition_digest=? AND approved_plan_digest=?",
                (disposition_digest, approved_plan_digest),
            ).fetchone()
            if disposition is None or str(disposition[0]) != ISSUE_790_APPROVED_INVOCATION_ID:
                raise Issue790CanaryIntegrityError("retry exclusion authority differs")
            for item in expected:
                event_id = _token(item.get("event_id"), field="retry exclusion event id")
                ledger_seq = int(item["ledger_seq"])
                row = connection.execute(
                    "SELECT event_id,ledger_seq,state,attempt_count,available_at,"
                    "last_failure_code,provider_dispatched "
                    "FROM unpublished_graphiti_revision_events "
                    "WHERE event_id=? AND ledger_seq=?",
                    (event_id, ledger_seq),
                ).fetchone()
                snapshot = {
                    "event_id": str(row[0]),
                    "ledger_seq": int(row[1]),
                    "state": str(row[2]),
                    "attempt_count": int(row[3]),
                    "available_at": str(row[4]),
                    "last_failure_code": str(row[5]),
                    "provider_dispatched": bool(row[6]),
                } if row is not None else None
                if snapshot != dict(item):
                    raise Issue790CanaryIntegrityError(
                        "retry exclusion event state differs"
                    )
                without_digest: dict[str, object] = {
                    "schema_version": RETRY_EXCLUSION_SCHEMA,
                    "approved_plan_digest": approved_plan_digest,
                    "disposition_digest": disposition_digest,
                    "event_id": event_id,
                    "ledger_seq": ledger_seq,
                    "reason": "ISSUE_790_RETRY_FORBIDDEN",
                    "event_snapshot": snapshot,
                    "excluded_at": excluded_at_text,
                }
                exclusion_digest = digest_canonical(without_digest)
                record = {**without_digest, "exclusion_digest": exclusion_digest}
                prior = connection.execute(
                    "SELECT record_json FROM issue_790_graphiti_retry_exclusions "
                    "WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                if prior is not None:
                    prior_record = _content_addressed_record(
                        prior[0],
                        digest_field="exclusion_digest",
                        field="retry exclusion",
                    )
                    stable_prior = dict(prior_record)
                    stable_prior.pop("excluded_at", None)
                    stable_record = dict(record)
                    stable_record.pop("excluded_at", None)
                    stable_prior.pop("exclusion_digest", None)
                    stable_record.pop("exclusion_digest", None)
                    if stable_prior != stable_record:
                        raise Issue790CanaryIntegrityError(
                            "conflicting retry exclusion replay"
                        )
                    retained.append(prior_record)
                    continue
                connection.execute(
                    "INSERT INTO issue_790_graphiti_retry_exclusions("
                    "exclusion_digest,approved_plan_digest,disposition_digest,"
                    "event_id,ledger_seq,reason,excluded_at,record_json) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        exclusion_digest,
                        approved_plan_digest,
                        disposition_digest,
                        event_id,
                        ledger_seq,
                        "ISSUE_790_RETRY_FORBIDDEN",
                        excluded_at_text,
                        _json(record),
                    ),
                )
                retained.append(record)
            connection.commit()
            return tuple(retained)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def retry_exclusions(self) -> tuple[dict[str, object], ...]:
        connection = self._read_connection()
        try:
            return tuple(
                _content_addressed_record(
                    row[0],
                    digest_field="exclusion_digest",
                    field="retry exclusion",
                )
                for row in connection.execute(
                    "SELECT record_json FROM issue_790_graphiti_retry_exclusions "
                    "ORDER BY ledger_seq"
                )
            )
        finally:
            connection.close()

    def existing_consumption(
        self, *, approved_plan_digest: str
    ) -> dict[str, object] | None:
        connection = self._read_connection()
        try:
            row = connection.execute(
                "SELECT record_json FROM issue_790_bounded_canary_consumptions "
                "WHERE approved_plan_digest=?",
                (approved_plan_digest,),
            ).fetchone()
            return (
                None
                if row is None
                else _content_addressed_record(
                    row[0],
                    digest_field="consumption_digest",
                    field="canary consumption",
                )
            )
        finally:
            connection.close()

    def existing_outcome(self, *, consumption_digest: str) -> dict[str, object] | None:
        connection = self._read_connection()
        try:
            row = connection.execute(
                "SELECT record_json FROM issue_790_bounded_canary_outcomes "
                "WHERE consumption_digest=?",
                (consumption_digest,),
            ).fetchone()
            return (
                None
                if row is None
                else _content_addressed_record(
                    row[0],
                    digest_field="outcome_digest",
                    field="canary outcome",
                )
            )
        finally:
            connection.close()

    def preflight_for_consumption(
        self,
        *,
        consumption_digest: str,
        event_id: str,
        owner_id: str,
    ) -> dict[str, object]:
        connection = self._read_connection()
        try:
            row = connection.execute(
                "SELECT record_json FROM issue_790_bounded_canary_consumptions "
                "WHERE consumption_digest=? AND event_id=? AND owner_id=?",
                (consumption_digest, event_id, owner_id),
            ).fetchone()
            if row is None:
                raise Issue790CanaryIntegrityError(
                    "bounded canary consumption authority differs"
                )
            record = _content_addressed_record(
                row[0],
                digest_field="consumption_digest",
                field="canary consumption",
            )
            return _content_addressed_record(
                record.get("preflight_evidence"),
                digest_field="evidence_digest",
                field="canary preflight",
            )
        finally:
            connection.close()

    def consume(
        self,
        *,
        approved_plan_digest: str,
        disposition_digest: str,
        event_id: str,
        ledger_seq: int,
        owner_id: str,
        preflight_evidence: Mapping[str, object],
        consumed_at: datetime,
    ) -> dict[str, object]:
        approved_plan_digest = _token(
            approved_plan_digest, field="approved plan digest"
        )
        disposition_digest = _token(disposition_digest, field="disposition digest")
        event_id = _token(event_id, field="canary event id")
        owner_id = _token(owner_id, field="canary owner id")
        if approved_plan_digest != ISSUE_790_APPROVED_PLAN_DIGEST:
            raise Issue790CanaryIntegrityError("bounded canary approved plan differs")
        if isinstance(ledger_seq, bool) or not isinstance(ledger_seq, int) or ledger_seq <= 0:
            raise Issue790CanaryIntegrityError("bounded canary ledger sequence is invalid")
        if ledger_seq in {1932, 1972}:
            raise Issue790CanaryIntegrityError("bounded canary targeted a retained failure")
        consumed_at_text = _utc_text(consumed_at)

        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM issue_790_bounded_canary_consumptions "
                "WHERE approved_plan_digest=? LIMIT 1",
                (approved_plan_digest,),
            ).fetchone() is not None:
                raise Issue790CanaryIntegrityError(
                    "bounded canary authority is already consumed"
                )
            disposition_row = connection.execute(
                "SELECT invocation_id,record_json "
                "FROM model_usage_conservative_dispositions "
                "WHERE disposition_digest=? AND approved_plan_digest=?",
                (disposition_digest, approved_plan_digest),
            ).fetchone()
            if disposition_row is None:
                raise Issue790CanaryIntegrityError(
                    "bounded canary disposition authority is absent"
                )
            disposition = _object(disposition_row[1], field="canary disposition")
            if (
                str(disposition_row[0]) != ISSUE_790_APPROVED_INVOCATION_ID
                or disposition.get("exact_usage_remains_unknown") is not True
                or disposition.get("unknown_spend_released") is not False
            ):
                raise Issue790CanaryIntegrityError(
                    "bounded canary disposition authority differs"
                )
            route = connection.execute(
                "SELECT state,reason FROM model_usage_route_circuit_events "
                "WHERE route='GRAPHITI_CHAT_PRIMARY' "
                "ORDER BY recorded_at DESC,rowid DESC LIMIT 1"
            ).fetchone()
            if route is None or tuple(route) != (
                "CLOSED",
                f"AUTHORISED_OPERATOR_RESET:{disposition_digest}",
            ):
                raise Issue790CanaryIntegrityError(
                    "bounded canary route release authority differs"
                )
            event_row = connection.execute(
                "SELECT state,attempt_count,available_at,claim_owner,claim_expires_at,"
                "manifest_json,unit_count,manifest_digest "
                "FROM unpublished_graphiti_revision_events "
                "WHERE event_id=? AND ledger_seq=?",
                (event_id, ledger_seq),
            ).fetchone()
            if (
                event_row is None
                or str(event_row[0]) != "QUEUED"
                or int(event_row[1]) != 0
                or str(event_row[2]) > consumed_at_text
                or event_row[3] is not None
                or event_row[4] is not None
            ):
                raise Issue790CanaryIntegrityError(
                    "bounded canary event is not fresh and claimable"
                )
            if graphiti_retry_excluded(connection, event_id=event_id):
                raise Issue790CanaryIntegrityError(
                    "bounded canary targeted a retry-excluded event"
                )
            event_circuit = connection.execute(
                "SELECT state,available_at FROM unpublished_graphiti_event_circuit "
                "WHERE singleton=1"
            ).fetchone()
            if (
                event_circuit is not None
                and str(event_circuit[0]) == "OPEN"
                and event_circuit[1] is not None
                and str(event_circuit[1]) > consumed_at_text
            ):
                raise Issue790CanaryIntegrityError(
                    "bounded canary event circuit is still open"
                )
            manifest = _object(event_row[5], field="canary event manifest")
            unit_refs = manifest.get("unit_refs")
            if (
                not isinstance(unit_refs, list)
                or not all(isinstance(item, dict) for item in unit_refs)
                or len(unit_refs) != int(event_row[6])
                or manifest.get("ledger_seq") != ledger_seq
                or digest_canonical(manifest) != str(event_row[7])
            ):
                raise Issue790CanaryIntegrityError(
                    "bounded canary event manifest differs"
                )
            preflight = _validated_preflight(
                preflight_evidence,
                event_id=event_id,
                ledger_seq=ledger_seq,
                manifest_digest=str(event_row[7]),
                consumed_at=consumed_at,
            )
            resolved_units = preflight["resolved_units"]
            assert isinstance(resolved_units, list)
            if unit_refs and tuple(
                _stable_unit_ref(item) for item in unit_refs if isinstance(item, dict)
            ) != tuple(
                _stable_unit_ref(item)
                for item in resolved_units
                if isinstance(item, dict)
            ):
                raise Issue790CanaryIntegrityError(
                    "bounded canary retained and preflight units differ"
                )
            ingest_ids = tuple(str(item["ingest_id"]) for item in resolved_units)
            placeholders = ",".join("?" for _ in ingest_ids)
            prior_tables = (
                "unpublished_graphiti_ingest",
                "unpublished_graphiti_failures",
                "unpublished_graphiti_receipts",
                "unpublished_graphiti_attempt_receipts",
                "unpublished_graphiti_spend",
            )
            if any(
                connection.execute(
                    f"SELECT 1 FROM {table} WHERE ingest_id IN ({placeholders}) LIMIT 1",
                    ingest_ids,
                ).fetchone()
                is not None
                for table in prior_tables
            ) or connection.execute(
                f"SELECT 1 FROM model_work_envelopes WHERE cycle_id=? "
                f"OR json_extract(record_json,'$.ingest_id') "
                f"IN ({placeholders}) LIMIT 1",
                (event_id, *ingest_ids),
            ).fetchone() is not None:
                raise Issue790CanaryIntegrityError(
                    "bounded canary target has prior execution evidence"
                )
            without_digest: dict[str, object] = {
                "schema_version": CANARY_CONSUMPTION_SCHEMA,
                "approved_plan_digest": approved_plan_digest,
                "disposition_digest": disposition_digest,
                "event_id": event_id,
                "ledger_seq": ledger_seq,
                "owner_id": owner_id,
                "preflight_evidence": preflight,
                "preflight_evidence_digest": preflight["evidence_digest"],
                "event_state_before": "QUEUED",
                "attempt_count_before": 0,
                "provider_io_authorised": True,
                "maximum_event_attempts": 1,
                "persistent_worker_must_remain_unloaded": True,
                "public_dispatch_authorised": False,
                "publication_authorised": False,
                "consumed_at": consumed_at_text,
            }
            consumption_digest = digest_canonical(without_digest)
            record = {**without_digest, "consumption_digest": consumption_digest}
            connection.execute(
                "INSERT INTO issue_790_bounded_canary_consumptions("
                "consumption_digest,approved_plan_digest,disposition_digest,"
                "event_id,ledger_seq,owner_id,consumed_at,record_json) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    consumption_digest,
                    approved_plan_digest,
                    disposition_digest,
                    event_id,
                    ledger_seq,
                    owner_id,
                    consumed_at_text,
                    _json(record),
                ),
            )
            connection.commit()
            return record
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def complete(
        self,
        *,
        consumption_digest: str,
        event_id: str,
        ledger_seq: int,
        owner_id: str,
        process_result: Mapping[str, object] | None,
        completed_at: datetime,
        exception_code: str | None = None,
        completion_mode: str = "FOREGROUND",
    ) -> dict[str, object]:
        consumption_digest = _token(
            consumption_digest, field="canary consumption digest"
        )
        event_id = _token(event_id, field="canary event id")
        owner_id = _token(owner_id, field="canary owner id")
        if completion_mode not in {"FOREGROUND", "ZERO_IO_RECOVERY"}:
            raise Issue790CanaryIntegrityError("bounded canary completion mode differs")
        if isinstance(ledger_seq, bool) or not isinstance(ledger_seq, int) or ledger_seq <= 0:
            raise Issue790CanaryIntegrityError("bounded canary ledger sequence is invalid")
        if process_result is not None and exception_code is not None:
            raise Issue790CanaryIntegrityError(
                "bounded canary outcome has both a result and an exception"
            )
        if exception_code is not None:
            exception_code = _token(exception_code, field="canary exception code")
        retained_result = None if process_result is None else dict(process_result)
        completed_at_text = _utc_text(completed_at)
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            consumption_row = connection.execute(
                "SELECT record_json FROM issue_790_bounded_canary_consumptions "
                "WHERE consumption_digest=? AND event_id=? AND ledger_seq=?",
                (consumption_digest, event_id, ledger_seq),
            ).fetchone()
            if consumption_row is None:
                raise Issue790CanaryIntegrityError(
                    "bounded canary consumption authority differs"
                )
            consumption = _content_addressed_record(
                consumption_row[0],
                digest_field="consumption_digest",
                field="canary consumption",
            )
            if consumption.get("owner_id") != owner_id:
                raise Issue790CanaryIntegrityError(
                    "bounded canary consumption owner differs"
                )
            prior = connection.execute(
                "SELECT record_json FROM issue_790_bounded_canary_outcomes "
                "WHERE consumption_digest=?",
                (consumption_digest,),
            ).fetchone()
            if prior is not None:
                retained_prior = _content_addressed_record(
                    prior[0],
                    digest_field="outcome_digest",
                    field="canary outcome",
                )
                if (
                    retained_prior.get("event_id") != event_id
                    or retained_prior.get("ledger_seq") != ledger_seq
                    or retained_prior.get("owner_id") != owner_id
                ):
                    raise Issue790CanaryIntegrityError(
                        "conflicting bounded canary outcome replay"
                    )
                connection.rollback()
                return retained_prior
            event_row = connection.execute(
                "SELECT state,attempt_count,claim_owner,last_failure_code,"
                "provider_dispatched FROM unpublished_graphiti_revision_events "
                "WHERE event_id=? AND ledger_seq=?",
                (event_id, ledger_seq),
            ).fetchone()
            if event_row is None:
                raise Issue790CanaryIntegrityError("bounded canary event disappeared")
            state_before_seal = str(event_row[0])
            attempt_count = int(event_row[1])
            claim_owner = None if event_row[2] is None else str(event_row[2])
            failure_code = None if event_row[3] is None else str(event_row[3])
            provider_dispatched = bool(event_row[4])
            if attempt_count not in {0, 1}:
                raise Issue790CanaryIntegrityError(
                    "bounded canary retained more than one attempt"
                )
            if retained_result is not None and (
                retained_result.get("event_id") != event_id
                or retained_result.get("ledger_seq") != ledger_seq
                or retained_result.get("attempt_count") != 1
                or retained_result.get("state") != state_before_seal
                or attempt_count != 1
            ):
                raise Issue790CanaryIntegrityError(
                    "bounded canary process result differs from retained event"
                )
            if state_before_seal in {"CLAIMED", "RUNNING"} and claim_owner != owner_id:
                raise Issue790CanaryIntegrityError(
                    "bounded canary active claim has a different owner"
                )
            if state_before_seal not in {
                "QUEUED",
                "CLAIMED",
                "RUNNING",
                "RETRY_HELD",
                "RIGHTS_HELD",
                "CONFIGURATION_HELD",
                "DEAD_LETTER",
                "TERMINAL",
            }:
                raise Issue790CanaryIntegrityError("bounded canary event state differs")
            sealed_state = state_before_seal
            sealed_failure_code = failure_code
            if state_before_seal != "TERMINAL":
                sealed_state = "CONFIGURATION_HELD"
                detail = exception_code or failure_code or "NO_EVENT_RESULT"
                if not str(detail).startswith("BOUNDED_CANARY_AUTHORITY_EXHAUSTED:"):
                    sealed_failure_code = (
                        f"BOUNDED_CANARY_AUTHORITY_EXHAUSTED:{detail}"
                    )
                cursor = connection.execute(
                    "UPDATE unpublished_graphiti_revision_events SET "
                    "state='CONFIGURATION_HELD',claim_owner=NULL,"
                    "claim_expires_at=NULL,last_failure_code=? "
                    "WHERE event_id=? AND ledger_seq=? AND state=? "
                    "AND attempt_count=?",
                    (
                        sealed_failure_code,
                        event_id,
                        ledger_seq,
                        state_before_seal,
                        attempt_count,
                    ),
                )
                if cursor.rowcount != 1:
                    raise Issue790CanaryIntegrityError(
                        "bounded canary event seal lost its exact state"
                    )
            without_digest: dict[str, object] = {
                "schema_version": CANARY_OUTCOME_SCHEMA,
                "consumption_digest": consumption_digest,
                "approved_plan_digest": consumption["approved_plan_digest"],
                "event_id": event_id,
                "ledger_seq": ledger_seq,
                "owner_id": owner_id,
                "process_result": retained_result,
                "exception_code": exception_code,
                "completion_mode": completion_mode,
                "state_before_seal": state_before_seal,
                "state_after_seal": sealed_state,
                "attempt_count": attempt_count,
                "provider_dispatched": provider_dispatched,
                "failure_code_before_seal": failure_code,
                "failure_code_after_seal": sealed_failure_code,
                "retry_authorised": False,
                "completed_at": completed_at_text,
            }
            outcome_digest = digest_canonical(without_digest)
            record = {**without_digest, "outcome_digest": outcome_digest}
            connection.execute(
                "INSERT INTO issue_790_bounded_canary_outcomes("
                "outcome_digest,consumption_digest,event_id,ledger_seq,"
                "completed_at,record_json) VALUES(?,?,?,?,?,?)",
                (
                    outcome_digest,
                    consumption_digest,
                    event_id,
                    ledger_seq,
                    completed_at_text,
                    _json(record),
                ),
            )
            connection.commit()
            return record
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def finalise_without_dispatch(
        self,
        *,
        consumption_digest: str,
        event_id: str,
        ledger_seq: int,
        owner_id: str,
        completed_at: datetime,
    ) -> dict[str, object]:
        """Seal an interrupted authority without starting another provider call."""

        prior = self.existing_outcome(consumption_digest=consumption_digest)
        if prior is not None:
            if (
                prior.get("event_id") != event_id
                or prior.get("ledger_seq") != ledger_seq
                or prior.get("owner_id") != owner_id
            ):
                raise Issue790CanaryIntegrityError(
                    "conflicting bounded canary finalisation replay"
                )
            return prior
        connection = self._connection()
        try:
            row = connection.execute(
                "SELECT state,attempt_count FROM unpublished_graphiti_revision_events "
                "WHERE event_id=? AND ledger_seq=?",
                (event_id, ledger_seq),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise Issue790CanaryIntegrityError("bounded canary event disappeared")
        attempt_count = int(row[1])
        process_result = (
            None
            if attempt_count == 0
            else {
                "event_id": event_id,
                "ledger_seq": ledger_seq,
                "state": str(row[0]),
                "attempt_count": attempt_count,
            }
        )
        return self.complete(
            consumption_digest=consumption_digest,
            event_id=event_id,
            ledger_seq=ledger_seq,
            owner_id=owner_id,
            process_result=process_result,
            completed_at=completed_at,
            completion_mode="ZERO_IO_RECOVERY",
        )


__all__ = [
    "CANARY_PREFLIGHT_SCHEMA",
    "Issue790CanaryIntegrityError",
    "Issue790CanaryRepository",
    "graphiti_event_has_canary_consumption",
    "graphiti_excluded_event_ids",
    "graphiti_retry_excluded",
    "validate_graphiti_canary_claim",
]
