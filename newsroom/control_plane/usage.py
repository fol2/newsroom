"""Read-only Graphiti token consumption reporting from durable attempt receipts."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TypeGuard

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.control_plane.graphiti_spend_reconciliation import (
    GraphitiSpendDisposition,
    _has_live_graphiti_dispatch_lease,
    _validate_retained_dispositions,
)
from newsroom.graphiti_adapter.embedding_meter import is_exact_provider_reported_usage
from newsroom.graphiti_adapter.usage_meter import summarise_graphiti_usage

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


def _is_exact_zero(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _empty_totals() -> dict[str, int]:
    return {field: 0 for field in _TOTAL_FIELDS}


def _retained_count(target: dict[str, object], field: str) -> int:
    value = target[field]
    if not _is_non_negative_int(value):
        raise ValueError(f"retained Graphiti usage {field} is invalid")
    return value


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def _window_start(value: datetime, seconds: int) -> datetime:
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)


def _text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_usage(target: dict[str, int], usage: object) -> bool | None:
    if not isinstance(usage, dict) or set(usage) != {
        "usage_basis",
        *_TOTAL_FIELDS,
    }:
        return None
    basis = usage["usage_basis"]
    if basis not in {
        "PROVIDER_REPORTED",
        "NO_PROVIDER_CALL",
        "PROVIDER_PARTIALLY_UNREPORTED",
        "UNREPORTED",
    }:
        return None
    for field in _TOTAL_FIELDS:
        value = usage[field]
        if not _is_non_negative_int(value):
            return None
    for field in _TOTAL_FIELDS:
        target[field] += usage[field]
    return basis in {"PROVIDER_REPORTED", "NO_PROVIDER_CALL"}


def _is_provider_free_immutable_recovery(
    receipt: object, *, disposition: object, evidence: object
) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    if not isinstance(evidence, Mapping):
        return False
    accounting = receipt.get("accounting")
    if not isinstance(accounting, Mapping):
        return False
    provider_attempt = accounting.get("provider_attempt")
    current_attempt = accounting.get("current_attempt")
    journal = evidence.get("graph_journal_evidence")
    provider_attempt_number = receipt.get("provider_attempt_number")
    attempt_number = receipt.get("attempt_number")
    return (
        disposition == GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO.value
        and evidence.get("disposition") == disposition
        and evidence.get("evidence_basis")
        == "RECOVERED_COMPLETE_WITHOUT_SECOND_PROVIDER_DISPATCH"
        and isinstance(journal, Mapping)
        and journal.get("state") == "COMPLETE"
        and journal.get("recovery_classification") == "RECOVERED_IMMUTABLE_COMPLETE"
        and journal.get("provider_dispatch_state") == "NOT_DISPATCHED"
        and isinstance(provider_attempt_number, int)
        and not isinstance(provider_attempt_number, bool)
        and isinstance(attempt_number, int)
        and not isinstance(attempt_number, bool)
        and 0 < provider_attempt_number < attempt_number
        and journal.get("provider_attempt_number") == provider_attempt_number
        and journal.get("reconciliation_attempt_number") == attempt_number
        and accounting.get("recovery_classification") == "RECOVERED_IMMUTABLE_COMPLETE"
        and isinstance(provider_attempt, Mapping)
        and provider_attempt.get("retained_attempt_receipt") is True
        and provider_attempt.get("spend_id")
        == f"{receipt.get('ingest_id')}:{provider_attempt_number}"
        and isinstance(current_attempt, Mapping)
        and current_attempt.get("spend_id")
        == f"{receipt.get('ingest_id')}:{attempt_number}"
        and current_attempt.get("status") == "RECONCILED"
        and current_attempt.get("usage_basis") == "NO_EMBEDDING_CALL"
        and _is_exact_zero(current_attempt.get("actual_usd_microunits"))
        and _is_exact_zero(current_attempt.get("actual_gbp_microunits"))
        and current_attempt.get("unused_reservation_released") is True
    )


def _is_duplicate_cross_attempt_attribution(
    receipt: object, *, disposition: object, evidence: object
) -> bool:
    if not isinstance(receipt, Mapping) or not isinstance(evidence, Mapping):
        return False
    provider_attempt = receipt.get("provider_attempt_number")
    attempt_number = receipt.get("attempt_number")
    provider_usage = evidence.get("provider_usage")
    return (
        disposition == GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD.value
        and evidence.get("disposition") == disposition
        and evidence.get("evidence_basis")
        == "DUPLICATE_CROSS_ATTEMPT_PROVIDER_ATTRIBUTION"
        and isinstance(provider_attempt, int)
        and not isinstance(provider_attempt, bool)
        and isinstance(attempt_number, int)
        and not isinstance(attempt_number, bool)
        and 0 < provider_attempt < attempt_number
        and isinstance(provider_usage, Mapping)
        and is_exact_provider_reported_usage(provider_usage)
        and isinstance(receipt.get("embedding_usage"), Mapping)
        and canonical_json_bytes(provider_usage)
        == canonical_json_bytes(receipt["embedding_usage"])
    )


def _validated_receipt_token_usage(
    receipt: object, *, disposition: object, evidence: object
) -> dict[str, object] | None:
    if not isinstance(receipt, Mapping):
        return None
    leaves = receipt.get("chat_invocations")
    if not isinstance(leaves, list) or any(
        not isinstance(item, Mapping) for item in leaves
    ):
        return None
    embedding_usage = receipt.get("embedding_usage")
    if embedding_usage is not None and not isinstance(embedding_usage, Mapping):
        return None
    if (
        embedding_usage is None
        and disposition == GraphitiSpendDisposition.RECONCILED.value
        and isinstance(evidence, Mapping)
        and isinstance(evidence.get("provider_usage"), Mapping)
        and is_exact_provider_reported_usage(evidence["provider_usage"])
    ):
        embedding_usage = evidence["provider_usage"]
    retained = receipt.get("token_usage")
    if not isinstance(retained, dict):
        return None
    expected = summarise_graphiti_usage(
        chat_invocations=leaves,
        embedding_usage=embedding_usage,
    )
    if canonical_json_bytes(retained) != canonical_json_bytes(expected):
        return None
    return retained


def _usage_without_current_embedding(
    receipt: object,
) -> dict[str, object] | None:
    """Retain current chat usage while removing duplicated embedding usage."""

    if not isinstance(receipt, Mapping):
        return None
    leaves = receipt.get("chat_invocations")
    if not isinstance(leaves, list) or any(
        not isinstance(item, Mapping) for item in leaves
    ):
        return None
    return summarise_graphiti_usage(
        chat_invocations=leaves,
        embedding_usage={
            "requests": [],
            "request_count": 0,
            "embedding_tokens": 0,
            "cost_usd_microunits": 0,
            "usage_basis": "NO_EMBEDDING_CALL",
        },
    )


def graphiti_usage_report(path: str, *, window_seconds: int = 300) -> dict[str, object]:
    """Aggregate retained Graphiti usage into fixed UTC windows."""

    if window_seconds < 1:
        raise ValueError("Graphiti usage window must be positive")
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='unpublished_graphiti_attempt_receipts'"
        ).fetchone()
        spend_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='unpublished_graphiti_spend'"
        ).fetchone()
        disposition_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='unpublished_graphiti_spend_dispositions'"
        ).fetchone()
        _validate_retained_dispositions(connection)
        rows = (
            []
            if table is None
            else connection.execute(
                """
                SELECT r.outcome, r.receipt_json, r.at,
                       d.disposition, d.evidence_json
                FROM unpublished_graphiti_attempt_receipts r
                LEFT JOIN unpublished_graphiti_spend_dispositions d
                  ON d.ingest_id=r.ingest_id
                 AND d.attempt_number=r.attempt_number
                ORDER BY r.at
                """
                if disposition_table is not None
                else """
                SELECT outcome, receipt_json, at, NULL, NULL
                FROM unpublished_graphiti_attempt_receipts ORDER BY at
                """
            ).fetchall()
        )
        terminal_disposition_count = (
            0
            if disposition_table is None or table is None
            else int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM unpublished_graphiti_spend_dispositions d
                    JOIN unpublished_graphiti_attempt_receipts r
                      ON r.ingest_id=d.ingest_id
                     AND r.attempt_number=d.attempt_number
                    """
                ).fetchone()[0]
            )
        )
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
                       s.dispatch_owner, s.dispatch_lease_expires_at,
                       {disposition_column} AS disposition
                FROM unpublished_graphiti_spend s
                {disposition_join}
                """
            ).fetchall()
        )
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()

    totals = _empty_totals()
    windows: dict[datetime, dict[str, object]] = {}
    measured_attempts = 0
    unreported_attempts = 0
    for outcome, receipt_json, at, disposition, evidence_json in rows:
        try:
            receipt = json.loads(str(receipt_json))
            evidence = None if evidence_json is None else json.loads(str(evidence_json))
            retained_usage = _validated_receipt_token_usage(
                receipt, disposition=disposition, evidence=evidence
            )
            if retained_usage is not None and _is_provider_free_immutable_recovery(
                receipt, disposition=disposition, evidence=evidence
            ):
                usage = {"usage_basis": "NO_PROVIDER_CALL", **_empty_totals()}
            elif retained_usage is not None and _is_duplicate_cross_attempt_attribution(
                receipt, disposition=disposition, evidence=evidence
            ):
                usage = _usage_without_current_embedding(receipt)
            else:
                usage = retained_usage
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
        usage_complete = _add_usage(totals, usage)
        if usage_complete is not None:
            measured_attempts += 1
            _add_usage(window, usage)  # type: ignore[arg-type]
        if usage_complete is not True:
            unreported_attempts += 1
            window["unreported_attempt_count"] = (
                _retained_count(window, "unreported_attempt_count") + 1
            )

    disposition_counts = {item: 0 for item in _SPEND_DISPOSITIONS}
    unresolved_spend_attempt_count = 0
    unresolved_reserved_gbp_microunits = 0
    undispositioned_spend_count = 0
    unexplained_reserved_spend_count = 0
    now = datetime.now(tz=UTC)
    for status, reserved, dispatch_owner, lease_expires_at, disposition in spend_rows:
        disposition_text = None if disposition is None else str(disposition)
        if disposition_text in disposition_counts:
            disposition_counts[disposition_text] += 1
        if disposition_text in {
            GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING.value,
            GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD.value,
        }:
            unresolved_spend_attempt_count += 1
            unresolved_reserved_gbp_microunits += int(reserved)
        if disposition_text is not None:
            continue
        live = _has_live_graphiti_dispatch_lease(
            status=status,
            owner=dispatch_owner,
            lease_expires_at=lease_expires_at,
            at=now,
        )
        if not live:
            undispositioned_spend_count += 1
            if str(status) in {"RESERVED", "UNRECONCILED"}:
                unexplained_reserved_spend_count += 1

    cost_complete = (
        unreported_attempts == 0
        and unresolved_spend_attempt_count == 0
        and undispositioned_spend_count == 0
        and terminal_disposition_count == len(rows)
    )
    return {
        "window_seconds": window_seconds,
        "attempt_count": len(rows),
        "measured_attempt_count": measured_attempts,
        "unreported_attempt_count": unreported_attempts,
        "cost_complete": cost_complete,
        "missing_usage_is_zero": False,
        "terminal_spend_disposition_count": terminal_disposition_count,
        "spend_disposition_counts": disposition_counts,
        "unresolved_spend_attempt_count": unresolved_spend_attempt_count,
        "unresolved_reserved_gbp_microunits": (unresolved_reserved_gbp_microunits),
        "undispositioned_spend_count": undispositioned_spend_count,
        "unexplained_reserved_spend_count": unexplained_reserved_spend_count,
        **totals,
        "windows": [windows[key] for key in sorted(windows)],
    }


__all__ = ["graphiti_usage_report"]
