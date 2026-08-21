"""Read-only Graphiti token consumption reporting from durable attempt receipts."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TypeGuard


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


def _is_non_negative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _empty_totals() -> dict[str, int]:
    return {field: 0 for field in _TOTAL_FIELDS}


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
        window["attempt_count"] = int(window["attempt_count"]) + 1
        if str(outcome) in {"COMPLETE", "PARTIAL"}:
            window["complete_attempt_count"] = (
                int(window["complete_attempt_count"]) + 1
            )
        if _add_usage(totals, usage):
            measured_attempts += 1
            _add_usage(window, usage)  # type: ignore[arg-type]
        else:
            unreported_attempts += 1
            window["unreported_attempt_count"] = (
                int(window["unreported_attempt_count"]) + 1
            )

    return {
        "window_seconds": window_seconds,
        "attempt_count": len(rows),
        "measured_attempt_count": measured_attempts,
        "unreported_attempt_count": unreported_attempts,
        **totals,
        "windows": [windows[key] for key in sorted(windows)],
    }


__all__ = ["graphiti_usage_report"]
