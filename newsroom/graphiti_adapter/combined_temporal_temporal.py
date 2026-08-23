"""Temporal grounding for combined-temporal facts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.combined_temporal_attribution import (
    CJK_DATE,
    ISO_DATE,
    ISO_TIMESTAMP,
    MONTH_NAMES,
    PROSE_DATE,
    RELATIVE_DAY_OFFSETS,
    RELATIVE_PATTERNS,
    attributed_scope,
)
from newsroom.graphiti_adapter.combined_temporal_types import (
    CombinedTemporalError,
    CombinedTemporalFailureCode,
)

_ISO_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)
_INVALID_TEMPORAL_CUE = re.compile(
    r"(?i)(?:\b(?:until|ceased|ended|expired|invalidated|no longer)\b|"
    r"截至|直至|終止於|結束於|到期於|失效於|不再)"
)
_RELATIVE_OFFSETS = {
    name: timedelta(days=days) for name, days in RELATIVE_DAY_OFFSETS.items()
}


def _date_expectations(
    retained: str, reference_time: datetime
) -> tuple[set[datetime], set[datetime]]:
    valid_dates: set[datetime] = set()
    invalid_dates: set[datetime] = set()

    def retain(value: datetime, start: int) -> None:
        context = retained[max(0, start - 48) : start]
        target = invalid_dates if _INVALID_TEMPORAL_CUE.search(context) else valid_dates
        target.add(value)

    for name, offset in _RELATIVE_OFFSETS.items():
        for match in RELATIVE_PATTERNS[name].finditer(retained):
            retain(reference_time + offset, match.start())
    timestamp_spans: list[tuple[int, int]] = []
    for match in ISO_TIMESTAMP.finditer(retained):
        timestamp_spans.append(match.span())
        try:
            retain(UtcTimestamp.parse(match.group(0)).value, match.start())
        except ValueError as exc:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.TEMPORAL_INVALID,
                "source timestamp is invalid",
            ) from exc
    for match in ISO_DATE.finditer(retained):
        if any(start <= match.start() < end for start, end in timestamp_spans):
            continue
        try:
            parsed = datetime.strptime(match.group(0), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as exc:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.TEMPORAL_INVALID,
                "source date is invalid",
            ) from exc
        retain(parsed, match.start())
    for match in PROSE_DATE.finditer(retained):
        try:
            parsed = datetime.strptime(
                match.group(0).title(), "%d %B %Y"
            ).replace(tzinfo=UTC)
        except ValueError as exc:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.TEMPORAL_INVALID,
                "source date is invalid",
            ) from exc
        retain(parsed, match.start())
    for match in CJK_DATE.finditer(retained):
        try:
            parsed = datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=UTC,
            )
        except ValueError as exc:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.TEMPORAL_INVALID,
                "source date is invalid",
            ) from exc
        retain(parsed, match.start())
    return valid_dates, invalid_dates


def assert_temporal_policy(
    fact: Mapping[str, Any],
    retained: str,
    reference_time: datetime,
) -> None:
    retained = attributed_scope(retained, str(fact["fact"]))
    valid_dates, invalid_dates = _date_expectations(retained, reference_time)
    if len(valid_dates) > 1 or len(invalid_dates) > 1:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.TEMPORAL_INVALID,
            "fact evidence has ambiguous temporal attribution",
        )
    if (
        (valid_dates or invalid_dates)
        and fact["valid_at"] is None
        and fact["invalid_at"] is None
    ):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.TEMPORAL_INVALID,
            "cited evidence has a temporal cue but both bounds are null",
        )
    expected_by_field = {"valid_at": valid_dates, "invalid_at": invalid_dates}
    for field_name, expected in expected_by_field.items():
        raw = fact[field_name]
        if expected and raw is None:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.TEMPORAL_INVALID,
                f"{field_name} omits a source-grounded temporal bound",
            )
        if raw is None:
            continue
        value = UtcTimestamp.parse(raw).value
        if expected:
            if value not in expected:
                raise CombinedTemporalError(
                    CombinedTemporalFailureCode.TEMPORAL_INVALID,
                    f"{field_name} does not obey the reference-time policy",
                )
            continue
        if valid_dates or invalid_dates:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.TEMPORAL_INVALID,
                f"{field_name} uses the other temporal bound's semantics",
            )
        iso_date = value.date().isoformat()
        prose = f"{value.day} {MONTH_NAMES[value.month - 1]} {value.year}"
        cjk = f"{value.year}年{value.month}月{value.day}日"
        if (
            iso_date not in retained
            and prose.lower() not in retained.lower()
            and cjk not in retained
        ):
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.TEMPORAL_INVALID,
                f"{field_name} is not grounded in cited evidence",
            )


def parse_optional_timestamp(raw: object, field_name: str) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not _ISO_UTC.fullmatch(raw):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.TEMPORAL_INVALID,
            f"{field_name} must be ISO-8601 UTC or null",
        )
    try:
        return UtcTimestamp.parse(raw).value
    except ValueError as exc:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.TEMPORAL_INVALID,
            f"{field_name} must be ISO-8601 UTC or null",
        ) from exc


def iso_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = ["assert_temporal_policy", "iso_timestamp", "parse_optional_timestamp"]
