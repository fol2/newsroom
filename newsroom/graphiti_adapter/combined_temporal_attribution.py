"""Shared statement attribution for combined-temporal evidence."""

from __future__ import annotations

import re
import unicodedata


_BOUNDARY = re.compile(
    r"(?i)(?:[.!?](?:\s+|$)|[。！？]+\s*|[;；\n]+|[,，]\s*|[()–—]+\s*|"
    r"\b(?:and|while|whereas|although)\b|(?<!anything )\bbut\b)"
)
_WORD = re.compile(r"[^\W_]+")
_CJK_RANGE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK = re.compile(rf"[{_CJK_RANGE}]")
_CJK_RELATION_TERMS = {
    "ACQUIRED": ("收購",),
    "ADMINISTERS": ("管理", "主管"),
    "ANSWERED": ("回答", "回應"),
    "ASKED": ("詢問", "提問", "質詢"),
    "ASKED_ABOUT": ("問及", "詢問", "質詢"),
    "ATTENDED": ("出席", "參加"),
    "CONDEMNED": ("譴責",),
    "HAS_CONTRACT_WITH": ("簽約", "訂立合約", "訂立合同"),
    "HOSTED": ("主持", "舉辦"),
    "IS_MEMBER_OF": ("是成員", "是會員", "隸屬"),
    "JOINED": ("加入",),
    "QUESTIONED": ("質詢",),
    "SUPPORTED": ("支持",),
    "WORKS_FOR": ("任職於", "效力於"),
}
_CJK_RELATION_FORMS = {
    "ASKED": (
        r"{source}\s*{polarity}\s*(?:向|對)\s*{target}\s*(?:詢問|提問|質詢)",
    ),
    "HAS_CONTRACT_WITH": (
        r"{source}\s*{polarity}\s*(?:與|和|跟)\s*{target}\s*"
        r"(?:簽約|訂立合約|訂立合同)",
    ),
    "IS_MEMBER_OF": (
        r"{source}\s*{polarity}\s*是\s*{target}\s*(?:的)?\s*(?:成員|會員)",
    ),
}
_RELATION_BASE_ALIASES = {"MEMBER_OF": "IS_MEMBER_OF"}
_NAME_CONNECTORS = "-'’‐‑‒–—"
_NEGATIVE_RELATION_WORDS = {"CANNOT", "NEVER", "NO", "NOT", "WITHOUT"}
_NEGATIVE_AUXILIARIES = {
    "ARE",
    "CAN",
    "DID",
    "DO",
    "DOES",
    "IS",
    "WAS",
    "WERE",
    "WILL",
}
_CONTRACTION = re.compile(r"(?i)\b([A-Za-z]+)n['’]t\b")
_IRREGULAR_CONTRACTIONS = re.compile(r"(?i)\b(won|shan|can)['’]t\b")
_IRREGULAR_BASE = {"won": "will", "shan": "shall", "can": "can"}
_CANNOT = re.compile(r"(?i)\bcannot\b")
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
_TEMPORAL_CONNECTOR = re.compile(
    r"(?i)(?:\b(?:on|at|as|of|since|from|until|before|after|around|by|dated|effective)\b|"
    r"日期[為是]|於|在|自|從|至|前|後|約|截至)"
)
_SOURCE_MODIFIER = re.compile(
    r"(?i)^\s*(?:according to .+|per .+|as (?:reported|confirmed) by .+|"
    r".+\s+(?:said|stated|say|says|reported|confirmed)|reportedly|allegedly)\s*$"
)


def _stem(value: str) -> str:
    value = value.lower()
    if value.endswith("ied") and len(value) > 3:
        return value[:-3] + "y"
    if value.endswith("ed") and len(value) > 3:
        return value[:-2]
    return value


def words(value: str) -> set[str]:
    expanded = _CANNOT.sub("can not", value)
    expanded = _IRREGULAR_CONTRACTIONS.sub(
        lambda match: f"{_IRREGULAR_BASE[match.group(1).lower()]} not",
        expanded,
    )
    expanded = _CONTRACTION.sub(r"\1 not", expanded)
    return {_stem(item) for item in _WORD.findall(expanded)}


def name_spans(value: str, name: str) -> tuple[tuple[int, int], ...]:
    return tuple(
        match.span()
        for match in re.finditer(re.escape(name), value)
        if _span_is_bounded(value, *match.span())
    )


def _name_word(char: str) -> bool:
    return bool(char) and (
        unicodedata.category(char).startswith("M")
        or char.isalnum()
    )


def _span_is_bounded(value: str, start: int, end: int) -> bool:
    left = value[start - 1] if start else ""
    right = value[end] if end < len(value) else ""
    left_connected = (
        left in _NAME_CONNECTORS
        and start > 1
        and _name_word(value[start - 2])
    )
    right_connected = (
        right in _NAME_CONNECTORS
        and end + 1 < len(value)
        and _name_word(value[end + 1])
    )
    return not any(
        (_name_word(left), left_connected, _name_word(right), right_connected)
    )


def contains_name(value: str, name: str) -> bool:
    return bool(name_spans(value, name))


def relation_polarity(relation_type: str) -> tuple[str, bool]:
    parts = relation_type.split("_")
    negative = bool(_NEGATIVE_RELATION_WORDS & set(parts))
    if not negative:
        return relation_type, False
    without_negative = "_".join(
        part for part in parts if part not in _NEGATIVE_RELATION_WORDS
    )
    if (
        without_negative in _CJK_RELATION_TERMS
        or without_negative in _CJK_RELATION_FORMS
    ):
        return without_negative, True
    base = "_".join(
        part
        for part in parts
        if part not in _NEGATIVE_RELATION_WORDS | _NEGATIVE_AUXILIARIES
    )
    return _RELATION_BASE_ALIASES.get(base, base or relation_type), True


def relation_is_grounded(
    value: str,
    relation_type: str,
    *,
    source_name: str,
    target_name: str,
) -> bool:
    relation_words = words(relation_type.replace("_", " "))
    if relation_words <= words(value):
        return all(contains_name(value, name) for name in (source_name, target_name))
    return bool(
        grounded_endpoint_spans(
            value,
            relation_type,
            source_name=source_name,
            target_name=target_name,
        )
    )


def grounded_endpoint_spans(
    value: str,
    relation_type: str,
    *,
    source_name: str,
    target_name: str,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    matches = _grounded_cjk_matches(
        value,
        relation_type,
        source_name=source_name,
        target_name=target_name,
    )
    if not matches:
        return None
    match = matches[0]
    matched = match.group(0)
    source_start = match.start() + matched.find(source_name)
    target_start = match.start() + matched.rfind(target_name)
    return (
        (source_start, source_start + len(source_name)),
        (target_start, target_start + len(target_name)),
    )


def grounded_relation_polarities(
    value: str,
    relation_type: str,
    *,
    source_name: str,
    target_name: str,
) -> tuple[bool, ...]:
    matches = _grounded_cjk_matches(
        value,
        relation_type,
        source_name=source_name,
        target_name=target_name,
    )
    return tuple(
        match.groupdict().get("negative") is not None for match in matches
    )


def _grounded_cjk_matches(
    value: str,
    relation_type: str,
    *,
    source_name: str,
    target_name: str,
) -> tuple[re.Match[str], ...]:
    if not _CJK.search(value):
        return ()
    base_relation_type, negative_relation = relation_polarity(relation_type)
    connector = r"\s*(?:向|對)?\s*"
    negative = r"(?P<negative>不(?!但|只|僅)|未|沒有|無|從未)"
    polarity = negative if negative_relation else rf"(?:{negative})?"
    patterns = [
        (
            rf"{re.escape(source_name)}{connector}"
            rf"{polarity}\s*"
            rf"{re.escape(term)}\s*{re.escape(target_name)}"
        )
        for term in _CJK_RELATION_TERMS.get(base_relation_type, ())
    ]
    patterns.extend(
        form.format(
            source=re.escape(source_name),
            target=re.escape(target_name),
            polarity=polarity,
        )
        for form in _CJK_RELATION_FORMS.get(base_relation_type, ())
    )
    return tuple(
        match
        for pattern in patterns
        for match in re.finditer(pattern, value)
        if _span_is_bounded(value, *match.span())
    )


def attributed_statements(
    retained: str,
    *,
    source_name: str,
    target_name: str,
    relation_type: str,
) -> tuple[str, ...]:
    statements = _split_statements(
        retained, source_name=source_name, target_name=target_name
    )
    return tuple(
        statement
        for statement in statements
        if relation_is_grounded(
            statement,
            relation_type,
            source_name=source_name,
            target_name=target_name,
        )
    )


def _split_statements(
    retained: str, *, source_name: str, target_name: str
) -> tuple[str, ...]:
    protected = [
        span
        for name in (source_name, target_name)
        for span in name_spans(retained, name)
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


def _is_modifier(statement: str) -> bool:
    return (
        not statement.strip()
        or _SOURCE_MODIFIER.fullmatch(statement) is not None
        or _is_temporal_modifier(statement)
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
    residual = re.sub(r"[\W_]+", "", residual)
    return not residual


def attributed_scope(
    retained: str,
    fact_text: str,
    *,
    source_name: str,
    target_name: str,
    relation_type: str,
) -> str:
    statements = _split_statements(
        retained, source_name=source_name, target_name=target_name
    )
    attributed = tuple(
        index
        for index, statement in enumerate(statements)
        if relation_is_grounded(
            statement,
            relation_type,
            source_name=source_name,
            target_name=target_name,
        )
    )
    needle = fact_text.strip().rstrip(".!?")
    matching = tuple(
        index for index in attributed if needle and needle in statements[index]
    )
    if len(matching) == 1:
        attributed = matching
    if attributed:
        scopes: list[str] = []
        attributed_set = set(attributed)
        for index in attributed:
            left = index
            while (
                left
                and left - 1 not in attributed_set
                and _is_modifier(statements[left - 1])
            ):
                left -= 1
            right = index + 1
            while (
                right < len(statements)
                and right not in attributed_set
                and _is_modifier(statements[right])
            ):
                right += 1
            scopes.append(" ".join(statements[left:right]))
        return " ".join(scopes)
    return fact_text if fact_text in retained else retained


__all__ = [
    "ISO_DATE",
    "ISO_TIMESTAMP",
    "CJK_DATE",
    "MONTH_NAMES",
    "PROSE_DATE",
    "RELATIVE_DAY_OFFSETS",
    "RELATIVE_PATTERNS",
    "attributed_scope",
    "attributed_statements",
    "contains_name",
    "grounded_endpoint_spans",
    "grounded_relation_polarities",
    "name_spans",
    "relation_is_grounded",
    "relation_polarity",
    "words",
]
