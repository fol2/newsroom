"""Read-only Graphiti token consumption reporting from durable attempt receipts."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TypeGuard

from newsroom.control_plane.graphiti_spend_reconciliation import (
    GraphitiSpendDisposition,
)


_TOTAL_FIELDS = (
    "chat_request_count",
    "cursor_request_count",
    "grok_request_count",
    "chat_input_tokens",
    "chat_output_tokens",
    "chat_cached_read_tokens",
    "chat_cached_write_tokens",
    "chat_reasoning_tokens",
    "chat_total_tokens",
    "embedding_request_count",
    "embedding_tokens",
    "embedding_cost_usd_microunits",
    "observed_total_tokens",
    "unreported_chat_requests",
)
_SPEND_DISPOSITIONS = tuple(item.value for item in GraphitiSpendDisposition)


def _is_non_negative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _empty_totals() -> dict[str, int]:
    return {field: 0 for field in _TOTAL_FIELDS}


def _retained_count(target: dict[str, object], field: str) -> int:
    value = target[field]
    if not _is_non_negative_int(value):
        raise ValueError(f"retained Graphiti usage {field} is invalid")
    return value


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=UTC)
        if parsed.tzinfo is None
        else parsed.astimezone(UTC)
    )


def _window_start(value: datetime, seconds: int) -> datetime:
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)


def _text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_usage(target: dict[str, int], usage: object) -> bool:
    if not isinstance(usage, dict):
        return False
    for field in _TOTAL_FIELDS:
        value = usage.get(field)
        if _is_non_negative_int(value):
            target[field] += value
    return True


def graphiti_usage_report(path: str, *, window_seconds: int = 300) -> dict[str, object]:
    """Aggregate retained Graphiti usage into fixed UTC windows."""

    if window_seconds < 1:
        raise ValueError("Graphiti usage window must be positive")
    connection = sqlite3.connect(path)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='unpublished_graphiti_attempt_receipts'"
        ).fetchone()
        rows = (
            []
            if table is None
            else connection.execute(
                "SELECT outcome, receipt_json, at "
                "FROM unpublished_graphiti_attempt_receipts ORDER BY at"
            ).fetchall()
        )
        spend_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='unpublished_graphiti_spend'"
        ).fetchone()
        disposition_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='unpublished_graphiti_spend_dispositions'"
        ).fetchone()
        disposition_join = (
            "LEFT JOIN unpublished_graphiti_spend_dispositions d "
            "ON d.spend_id=s.spend_id"
            if disposition_table is not None
            else ""
        )
        disposition_column = (
            "d.disposition" if disposition_table is not None else "NULL"
        )
        spend_rows = (
            []
            if spend_table is None
            else connection.execute(
                f"""
                SELECT s.status, s.reserved_gbp_microunits,
                       s.dispatch_lease_expires_at,
                       {disposition_column} AS disposition
                FROM unpublished_graphiti_spend s
                {disposition_join}
                """
            ).fetchall()
        )
    finally:
        connection.close()

    totals = _empty_totals()
    windows: dict[datetime, dict[str, object]] = {}
    measured_attempts = 0
    unreported_attempts = 0
    for outcome, receipt_json, at in rows:
        try:
            receipt = json.loads(str(receipt_json))
            usage = receipt.get("token_usage") if isinstance(receipt, dict) else None
            instant = _instant(str(at))
        except (json.JSONDecodeError, TypeError, ValueError):
            unreported_attempts += 1
            continue
        start = _window_start(instant, window_seconds)
        window = windows.setdefault(
            start,
            {
                "window_start": _text(start),
                "window_end": _text(
                    datetime.fromtimestamp(start.timestamp() + window_seconds, tz=UTC)
                ),
                "attempt_count": 0,
                "complete_attempt_count": 0,
                "unreported_attempt_count": 0,
                **_empty_totals(),
            },
        )
        window["attempt_count"] = _retained_count(window, "attempt_count") + 1
        if str(outcome) in {"COMPLETE", "PARTIAL"}:
            window["complete_attempt_count"] = (
                _retained_count(window, "complete_attempt_count") + 1
            )
        if _add_usage(totals, usage):
            measured_attempts += 1
            _add_usage(window, usage)  # type: ignore[arg-type]
        else:
            unreported_attempts += 1
            window["unreported_attempt_count"] = (
                _retained_count(window, "unreported_attempt_count") + 1
            )

    disposition_counts = {item: 0 for item in _SPEND_DISPOSITIONS}
    unresolved_spend_attempt_count = 0
    unresolved_reserved_gbp_microunits = 0
    unexplained_reserved_spend_count = 0
    now = datetime.now(tz=UTC)
    for status, reserved, lease_expires_at, disposition in spend_rows:
        disposition_text = None if disposition is None else str(disposition)
        if disposition_text in disposition_counts:
            disposition_counts[disposition_text] += 1
        if disposition_text in {
            GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING.value,
            GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD.value,
        }:
            unresolved_spend_attempt_count += 1
            unresolved_reserved_gbp_microunits += int(reserved)
        if disposition_text is not None or str(status) not in {
            "RESERVED",
            "UNRECONCILED",
        }:
            continue
        live = False
        if str(status) == "RESERVED" and lease_expires_at:
            try:
                live = _instant(str(lease_expires_at)) > now
            except ValueError:
                live = False
        if not live:
            unexplained_reserved_spend_count += 1

    cost_complete = (
        unreported_attempts == 0
        and unresolved_spend_attempt_count == 0
        and unexplained_reserved_spend_count == 0
    )
    return {
        "window_seconds": window_seconds,
        "attempt_count": len(rows),
        "measured_attempt_count": measured_attempts,
        "unreported_attempt_count": unreported_attempts,
        "cost_complete": cost_complete,
        "missing_usage_is_zero": False,
        "terminal_spend_disposition_count": sum(disposition_counts.values()),
        "spend_disposition_counts": disposition_counts,
        "unresolved_spend_attempt_count": unresolved_spend_attempt_count,
        "unresolved_reserved_gbp_microunits": (
            unresolved_reserved_gbp_microunits
        ),
        "unexplained_reserved_spend_count": unexplained_reserved_spend_count,
        **totals,
        "windows": [windows[key] for key in sorted(windows)],
    }


__all__ = ["graphiti_usage_report"]
