"""Statement and temporal attribution for combined-temporal evidence."""

from __future__ import annotations

import re
import unicodedata

_BOUNDARY = re.compile(
    r"(?i)(?:[.!?](?:\s+|$)|[。！？]+\s*|[;；\n]+|[,，]\s*|[()–—]+\s*|"
    r"\b(?:and|while|whereas|although)\b|\s+及\s+|(?<!anything )\bbut\b)"
)
_WORD = re.compile(r"[^\W_]+")
_CJK_RANGE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK = re.compile(rf"[{_CJK_RANGE}]")
_NAME_CONNECTORS = "-'’‐‑‒–—"
ISO_TIMESTAMP = re.compile(
    r"(?<![A-Za-z0-9])\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:[.,]\d+)?(?:Z|[+-]\d{2}(?::?\d{2})?)(?![A-Za-z0-9])"
)
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
PROSE_DATE = re.compile(
    r"\b\d{1,2} (" + "|".join(MONTH_NAMES) + r") \d{4}\b",
    flags=re.IGNORECASE,
)
CJK_DATE = re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日(?!\d)")
RELATIVE_DAY_OFFSETS = {
    "last week": -7,
    "上周": -7,
    "上週": -7,
    "yesterday": -1,
    "昨日": -1,
    "昨天": -1,
    "today": 0,
    "今日": 0,
    "今天": 0,
    "tomorrow": 1,
    "明日": 1,
    "明天": 1,
    "next week": 7,
    "下周": 7,
    "下週": 7,
}
_CJK_TEMPORAL_PREFIXES = ("日期為", "日期是", "於", "在", "截至", "自", "從")
_PREDICATE_CONNECTORS = {
    "a",
    "an",
    "and",
    "at",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "及",
    "向",
    "和",
    "在",
    "對",
    "於",
    "與",
    "跟",
    "日期是",
    "日期為",
}
_TEMPORAL_CONNECTOR = re.compile(
    r"(?i)(?:\b(?:on|at|as|of|since|from|until|before|after|around|by|dated|effective)\b|"
    r"日期[為是]|於|在|自|從|至|前|後|約|截至)"
)
_SOURCE_MODIFIER = re.compile(
    r"(?i)^\s*(?:according to .+|per .+|as (?:reported|confirmed) by .+|"
    r".+\s+(?:said|stated|say|says|reported|confirmed)|reportedly|allegedly)\s*$"
)


def _relative_pattern(name: str) -> str:
    escaped = re.escape(name)
    if name.isascii():
        return rf"\b{escaped}\b"
    standalone = rf"(?<![{_CJK_RANGE}]){escaped}(?![{_CJK_RANGE}])"
    prefixed = [
        rf"(?<={re.escape(prefix)}){escaped}(?![{_CJK_RANGE}])"
        for prefix in _CJK_TEMPORAL_PREFIXES
    ]
    return "(?:" + "|".join((standalone, *prefixed)) + ")"


RELATIVE_PATTERNS = {
    name: re.compile(_relative_pattern(name), flags=re.IGNORECASE)
    for name in RELATIVE_DAY_OFFSETS
}
_RELATIVE_CUE = re.compile(
    "|".join(pattern.pattern for pattern in RELATIVE_PATTERNS.values()),
    flags=re.IGNORECASE,
)


def _name_word(char: str) -> bool:
    return bool(char) and (
        unicodedata.category(char).startswith("M") or char.isalnum()
    )


def _span_is_bounded(
    value: str, start: int, end: int, *, cjk_is_boundary: bool = False
) -> bool:
    left = value[start - 1] if start else ""
    right = value[end] if end < len(value) else ""

    def is_word(char: str) -> bool:
        return _name_word(char) and not (
            cjk_is_boundary and _CJK.fullmatch(char) is not None
        )

    left_connected = (
        left in _NAME_CONNECTORS and start > 1 and is_word(value[start - 2])
    )
    right_connected = (
        right in _NAME_CONNECTORS
        and end + 1 < len(value)
        and is_word(value[end + 1])
    )
    return not any(
        (is_word(left), left_connected, is_word(right), right_connected)
    )


def name_spans(value: str, name: str) -> tuple[tuple[int, int], ...]:
    spans = tuple(match.span() for match in re.finditer(re.escape(name), value))
    cjk_is_boundary = name.isascii() or _CJK.search(name) is not None
    return tuple(
        span
        for span in spans
        if _span_is_bounded(
            value, *span, cjk_is_boundary=cjk_is_boundary
        )
    )


def contains_name(value: str, name: str) -> bool:
    return bool(name_spans(value, name))


def _without_names(value: str, *names: str) -> str:
    spans = {
        span
        for name in names
        for span in name_spans(value, name)
    }
    masked = value
    for start, end in sorted(spans, reverse=True):
        masked = masked[:start] + " " * (end - start) + masked[end:]
    return masked


def has_predicate_surface(value: str, *, source_name: str, target_name: str) -> bool:
    if source_name == target_name:
        if len(name_spans(value, source_name)) < 2:
            return False
    elif not all(contains_name(value, name) for name in (source_name, target_name)):
        return False
    retained = _without_names(value, source_name, target_name)
    for pattern in (ISO_TIMESTAMP, ISO_DATE, PROSE_DATE, CJK_DATE):
        retained = pattern.sub(" ", retained)
    for pattern in RELATIVE_PATTERNS.values():
        retained = pattern.sub(" ", retained)
    return any(
        token.lower() not in _PREDICATE_CONNECTORS and not token.isdigit()
        for token in _WORD.findall(retained)
    )


def _split_statements(
    retained: str, *, protected_values: tuple[str, ...] = ()
) -> tuple[str, ...]:
    protected = [
        span
        for value in protected_values
        for span in name_spans(retained, value)
    ] + [match.span() for match in ISO_TIMESTAMP.finditer(retained)]
    boundaries = [
        match
        for match in _BOUNDARY.finditer(retained)
        if not any(start <= match.start() < end for start, end in protected)
    ]
    statements: list[str] = []
    cursor = 0
    for match in boundaries:
        statements.append(retained[cursor : match.start()])
        cursor = match.end()
    statements.append(retained[cursor:])
    return tuple(statements)


def attributed_statements(
    retained: str,
    *,
    source_name: str,
    target_name: str,
) -> tuple[str, ...]:
    return tuple(
        statement
        for statement in _split_statements(
            retained, protected_values=(source_name, target_name)
        )
        if has_predicate_surface(
            statement,
            source_name=source_name,
            target_name=target_name,
        )
    )


def _is_temporal_modifier(statement: str) -> bool:
    retained = list(statement)
    matched = False
    for pattern in (ISO_TIMESTAMP, ISO_DATE, PROSE_DATE, CJK_DATE, _RELATIVE_CUE):
        for match in pattern.finditer(statement):
            matched = True
            retained[match.start() : match.end()] = " " * (match.end() - match.start())
    if not matched:
        return False
    residual = _TEMPORAL_CONNECTOR.sub(" ", "".join(retained))
    return not re.sub(r"[\W_]+", "", residual)


def _is_modifier(statement: str) -> bool:
    return (
        not statement.strip()
        or _SOURCE_MODIFIER.fullmatch(statement) is not None
        or _is_temporal_modifier(statement)
    )


def attributed_scope(retained: str, fact_text: str) -> str:
    statements = _split_statements(retained, protected_values=(fact_text,))
    needle = fact_text.strip().rstrip(".!?")
    matching = tuple(
        index for index, statement in enumerate(statements) if needle in statement
    )
    if len(matching) != 1:
        return fact_text if fact_text in retained else retained
    index = matching[0]
    left = index
    while left and _is_modifier(statements[left - 1]):
        left -= 1
    right = index + 1
    while right < len(statements) and _is_modifier(statements[right]):
        right += 1
    return " ".join(statements[left:right])


__all__ = [
    "CJK_DATE",
    "ISO_DATE",
    "ISO_TIMESTAMP",
    "MONTH_NAMES",
    "PROSE_DATE",
    "RELATIVE_DAY_OFFSETS",
    "RELATIVE_PATTERNS",
    "attributed_scope",
    "attributed_statements",
    "contains_name",
    "has_predicate_surface",
    "name_spans",
]
