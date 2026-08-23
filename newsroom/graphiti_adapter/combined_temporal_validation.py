"""Pure validation for NewsroomCombinedTemporalExtractionV1."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from newsroom.authority.canonical import (
    CanonicalizationError,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.result_mapping import is_source_registry_name


class CombinedTemporalFailureCode(StrEnum):
    NONE = "NONE"
    MALFORMED_OBJECT = "MALFORMED_OBJECT"
    TEMPORAL_INVALID = "TEMPORAL_INVALID"
    EVIDENCE_UNRESOLVED = "EVIDENCE_UNRESOLVED"
    IDENTITY_INVALID = "IDENTITY_INVALID"
    PIPELINE_FAILED = "PIPELINE_FAILED"


class CombinedTemporalError(ValueError):
    def __init__(self, code: CombinedTemporalFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class EvidenceSegment:
    segment_id: int
    start_byte: int
    end_byte: int
    text: str


MAX_SEGMENT_BYTES = 512
GOVERNED_ENTITY_TYPE_IDS = frozenset({0})
_RELATION_TYPE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
_SPLIT = re.compile(rb"(?:(?<=[.!?])[ \t]+)|(?:\n+)")
_ISO_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CORRECTION = re.compile(r"(?i)\bcorrection\s*:")
_INVALID_TEMPORAL_CUE = re.compile(
    r"(?i)\b(?:until|ceased|ended|expired|invalidated|no longer)\b"
)
_WORD = re.compile(r"[A-Za-z0-9]+")
_RELATIVE_OFFSETS = {
    "yesterday": timedelta(days=-1),
    "today": timedelta(days=0),
    "tomorrow": timedelta(days=1),
}
_MONTH_NAMES = (
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
_PROSE_DATE = re.compile(
    r"\b\d{1,2} (" + "|".join(_MONTH_NAMES) + r") \d{4}\b",
    flags=re.IGNORECASE,
)


def segment_source(
    body: str, *, max_bytes: int = MAX_SEGMENT_BYTES
) -> tuple[EvidenceSegment, ...]:
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    data = body.encode("utf-8")
    if not data:
        return (EvidenceSegment(0, 0, 0, ""),)
    cuts = [0]
    for match in _SPLIT.finditer(data):
        end = match.end()
        if end > cuts[-1]:
            cuts.append(end)
    if cuts[-1] < len(data):
        cuts.append(len(data))
    bounds: list[tuple[int, int]] = []
    for start, end in zip(cuts, cuts[1:]):
        if end > start:
            bounds.extend(_split_oversize(data, start, end, max_bytes))
    segments: list[EvidenceSegment] = []
    for index, (start, end) in enumerate(bounds):
        try:
            text = data[start:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("segment is not valid UTF-8") from exc
        segments.append(
            EvidenceSegment(
                segment_id=index,
                start_byte=start,
                end_byte=end,
                text=text,
            )
        )
    return tuple(segments)


def _raw_digest(raw: object) -> str:
    try:
        return _raw_digest_body(raw)
    except (CanonicalizationError, TypeError, ValueError, UnicodeError):
        return digest_bytes(
            f"{type(raw).__name__}\n{_raw_repr(raw)}".encode("utf-8", errors="replace")
        )


def _raw_digest_body(raw: object) -> str:
    if isinstance(raw, Mapping):
        return digest_canonical(dict(raw))
    if isinstance(raw, str):
        return digest_bytes(raw.encode("utf-8"))
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return digest_bytes(bytes(raw))
    if isinstance(raw, Sequence):
        return digest_canonical(list(raw))
    return digest_canonical({"unsupported": type(raw).__name__, "repr": _raw_repr(raw)})


def _raw_repr(raw: object) -> str:
    try:
        return repr(raw)
    except Exception:
        return "<unreprable>"


def _split_oversize(
    data: bytes, start: int, end: int, max_bytes: int
) -> list[tuple[int, int]]:
    parts: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        limit = min(cursor + max_bytes, end)
        if limit == end:
            cut = _utf8_cut(data, cursor, end)
            if cut != end:
                raise ValueError("segment is not valid UTF-8")
            parts.append((cursor, end))
            break
        cut = data.rfind(b" ", cursor, limit)
        if cut <= cursor:
            cut = _utf8_cut(data, cursor, limit)
        else:
            cut = _utf8_cut(data, cursor, cut + 1)
        if cut <= cursor:
            raise ValueError("segment is not valid UTF-8")
        parts.append((cursor, cut))
        cursor = cut
    return parts


def _utf8_cut(data: bytes, start: int, limit: int) -> int:
    piece = data[start:limit]
    while piece:
        try:
            piece.decode("utf-8")
            return start + len(piece)
        except UnicodeDecodeError:
            piece = piece[:-1]
    return start


def _parse_payload(raw: object) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        payload = dict(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        try:
            decoded = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except CombinedTemporalError:
            raise
        except (ValueError, RecursionError) as exc:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.MALFORMED_OBJECT,
                "response is not one JSON object",
            ) from exc
        if not isinstance(decoded, dict):
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.MALFORMED_OBJECT,
                "response is not a JSON object",
            )
        payload = decoded
    else:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "response is not a JSON object",
        )
    extra = set(payload) - {"entities", "facts"}
    if extra or "entities" not in payload or "facts" not in payload:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "object keys are not exactly entities and facts",
        )
    if not isinstance(payload["entities"], list) or not isinstance(
        payload["facts"], list
    ):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "entities and facts must be arrays",
        )
    return payload


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.MALFORMED_OBJECT,
                "duplicate object keys are not allowed",
            )
        payload[key] = value
    return payload


def _normalise(
    payload: Mapping[str, Any],
    segments: tuple[EvidenceSegment, ...],
    reference_time: datetime,
) -> tuple[dict[str, Any], dict[str, tuple[EvidenceSegment, ...]]]:
    entities = [_entity(item) for item in payload["entities"]]
    facts = [_fact(item) for item in payload["facts"]]
    ids = [item["local_id"] for item in entities]
    if len(ids) != len(set(ids)):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "local_id values must be unique",
        )
    id_set = set(ids)
    entity_by_id = {item["local_id"]: item for item in entities}
    if facts and not entities:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "facts require entities",
        )
    if entities and not facts:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "zero facts requires zero entities",
        )
    _assert_unique_facts(facts)
    connected: set[int] = set()
    ranges: dict[str, tuple[EvidenceSegment, ...]] = {}
    for fact in facts:
        source = fact["source_local_id"]
        target = fact["target_local_id"]
        if source == target or source not in id_set or target not in id_set:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.IDENTITY_INVALID,
                "facts must reference two present distinct local IDs",
            )
        connected.update((source, target))
        cited = _resolve_segments(fact["evidence_segment_ids"], segments)
        retained = "".join(item.text for item in cited)
        source_entity = entity_by_id[source]
        target_entity = entity_by_id[target]
        source_name = source_entity["name"]
        target_name = target_entity["name"]
        if fact["fact"] not in retained:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "fact is not present in cited segments",
            )
        if source_name not in retained or target_name not in retained:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "source and target names are not present in cited segments",
            )
        fact_text = fact["fact"]
        if source_name not in fact_text or target_name not in fact_text:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "fact must name both endpoints",
            )
        if source_name == target_name and fact_text.count(source_name) < 2:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "same-name endpoints require two grounded mentions",
            )
        fact_segment_ids = set(fact["evidence_segment_ids"])
        source_evidence = set(source_entity["evidence_segment_ids"])
        target_evidence = set(target_entity["evidence_segment_ids"])
        if (
            not fact_segment_ids & source_evidence
            or not fact_segment_ids & target_evidence
        ):
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "fact endpoints do not share their entity evidence",
            )
        _assert_relation_grounding(
            fact=fact,
            source_name=source_name,
            target_name=target_name,
        )
        _assert_single_attribution(retained)
        _assert_temporal_policy(fact, retained, reference_time)
        ranges[fact["fact"]] = cited
    if connected != id_set:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "every entity must participate in a fact",
        )
    for entity in entities:
        cited = _resolve_segments(entity["evidence_segment_ids"], segments)
        retained = "".join(item.text for item in cited)
        if entity["name"] not in retained:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "entity name is not present in cited segments",
            )
    entities_out = tuple(
        sorted(
            (_canonical_entity(item) for item in entities),
            key=lambda item: item["local_id"],
        )
    )
    facts_out = tuple(
        sorted(
            (_canonical_fact(item) for item in facts),
            key=lambda item: (
                item["source_local_id"],
                item["target_local_id"],
                item["relation_type"],
                item["fact"],
            ),
        )
    )
    return {"entities": list(entities_out), "facts": list(facts_out)}, ranges


def _assert_unique_facts(facts: list[dict[str, Any]]) -> None:
    seen: set[tuple[object, ...]] = set()
    locators: dict[str, tuple[object, ...]] = {}
    for fact in facts:
        duplicate = (
            fact["source_local_id"],
            fact["target_local_id"],
            fact["relation_type"],
            fact["fact"],
        )
        if duplicate in seen:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.IDENTITY_INVALID,
                "duplicate facts are not allowed",
            )
        seen.add(duplicate)
        locator = (
            fact["source_local_id"],
            fact["target_local_id"],
            fact["relation_type"],
            tuple(fact["evidence_segment_ids"]),
        )
        prior = locators.get(fact["fact"])
        if prior is not None and prior != locator:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "fact text maps to contradictory attribution",
            )
        locators[fact["fact"]] = locator


def _assert_single_attribution(retained: str) -> None:
    match = _CORRECTION.search(retained)
    if match is None:
        return
    before = retained[: match.start()]
    after = retained[match.end() :]
    if before.strip() and after.strip():
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence cites assertion and correction",
        )


def _words(value: str) -> set[str]:
    return {item.lower() for item in _WORD.findall(value)}


def _assert_relation_grounding(
    *,
    fact: Mapping[str, Any],
    source_name: str,
    target_name: str,
) -> None:
    relation_words = {item.lower() for item in fact["relation_type"].split("_")}
    fact_words = _words(str(fact["fact"]))
    entity_words = _words(source_name) | _words(target_name)
    if not relation_words <= fact_words or not (relation_words - entity_words):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "relation type is not supported by relation words in the fact",
        )


def _date_expectations(
    retained: str, reference_time: datetime
) -> tuple[set[date], set[date]]:
    valid_dates: set[date] = set()
    invalid_dates: set[date] = set()

    def retain(value: date, start: int) -> None:
        context = retained[max(0, start - 48) : start]
        target = invalid_dates if _INVALID_TEMPORAL_CUE.search(context) else valid_dates
        target.add(value)

    for name, offset in _RELATIVE_OFFSETS.items():
        for match in re.finditer(
            rf"\b{re.escape(name)}\b", retained, flags=re.IGNORECASE
        ):
            retain((reference_time + offset).date(), match.start())
    for match in _ISO_DATE.finditer(retained):
        retain(datetime.strptime(match.group(0), "%Y-%m-%d").date(), match.start())
    for match in _PROSE_DATE.finditer(retained):
        retain(
            datetime.strptime(match.group(0).title(), "%d %B %Y").date(),
            match.start(),
        )
    return valid_dates, invalid_dates


def _assert_temporal_policy(
    fact: Mapping[str, Any], retained: str, reference_time: datetime
) -> None:
    valid_dates, invalid_dates = _date_expectations(retained, reference_time)
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
            if value.date() not in expected:
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
        prose = f"{value.day} {_MONTH_NAMES[value.month - 1]} {value.year}"
        if iso_date not in retained and prose.lower() not in retained.lower():
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.TEMPORAL_INVALID,
                f"{field_name} is not grounded in cited evidence",
            )


def _entity(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "entity is not an object",
        )
    extra = set(raw) - {"local_id", "name", "entity_type_id", "evidence_segment_ids"}
    if extra:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "entity has unknown keys",
        )
    local_id = raw.get("local_id")
    name = raw.get("name")
    type_id = raw.get("entity_type_id")
    if not isinstance(local_id, int) or isinstance(local_id, bool) or local_id < 0:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "local_id must be a non-negative integer",
        )
    if not isinstance(name, str) or not name.strip():
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "entity name must be a non-empty string",
        )
    name = " ".join(name.split())
    if is_source_registry_name(name) or name in {
        "SourceItem",
        "SourceRevision",
        "DERIVED_FROM",
        "OBSERVED_IN",
    }:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "deterministic metadata is excluded from semantic extraction",
        )
    if (
        isinstance(type_id, bool)
        or not isinstance(type_id, int)
        or type_id not in GOVERNED_ENTITY_TYPE_IDS
    ):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "entity_type_id is not in the governed ontology",
        )
    return {
        "local_id": local_id,
        "name": name,
        "entity_type_id": type_id,
        "evidence_segment_ids": _ids(raw.get("evidence_segment_ids")),
    }


def _fact(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "fact is not an object",
        )
    extra = set(raw) - {
        "source_local_id",
        "target_local_id",
        "relation_type",
        "fact",
        "valid_at",
        "invalid_at",
        "evidence_segment_ids",
    }
    if extra:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "fact has unknown keys",
        )
    if "valid_at" not in raw or "invalid_at" not in raw:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "fact must include valid_at and invalid_at",
        )
    source = raw.get("source_local_id")
    target = raw.get("target_local_id")
    relation = raw.get("relation_type")
    fact = raw.get("fact")
    if not isinstance(source, int) or isinstance(source, bool):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "source_local_id must be an integer",
        )
    if not isinstance(target, int) or isinstance(target, bool):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "target_local_id must be an integer",
        )
    if not isinstance(relation, str) or not _RELATION_TYPE.fullmatch(relation):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "relation_type must be SCREAMING_SNAKE_CASE",
        )
    if not isinstance(fact, str) or not fact.strip():
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
            "fact must be a non-empty string",
        )
    valid_at = _timestamp(raw.get("valid_at"), "valid_at")
    invalid_at = _timestamp(raw.get("invalid_at"), "invalid_at")
    if valid_at is not None and invalid_at is not None and valid_at >= invalid_at:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.TEMPORAL_INVALID,
            "valid_at must precede invalid_at",
        )
    return {
        "source_local_id": source,
        "target_local_id": target,
        "relation_type": relation,
        "fact": fact,
        "valid_at": None if valid_at is None else _iso(valid_at),
        "invalid_at": None if invalid_at is None else _iso(invalid_at),
        "evidence_segment_ids": _ids(raw.get("evidence_segment_ids")),
    }


def _canonical_entity(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entity_type_id": item["entity_type_id"],
        "evidence_segment_ids": list(item["evidence_segment_ids"]),
        "local_id": item["local_id"],
        "name": item["name"],
    }


def _canonical_fact(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "evidence_segment_ids": list(item["evidence_segment_ids"]),
        "fact": item["fact"],
        "invalid_at": item["invalid_at"],
        "relation_type": item["relation_type"],
        "source_local_id": item["source_local_id"],
        "target_local_id": item["target_local_id"],
        "valid_at": item["valid_at"],
    }


def _ids(raw: object) -> list[int]:
    if not isinstance(raw, list) or not raw:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence_segment_ids must be a non-empty integer array",
        )
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in raw
    ):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence_segment_ids must be non-negative integers",
        )
    if len(raw) != len(set(raw)):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence_segment_ids must be unique",
        )
    return sorted(raw)


def _resolve_segments(
    ids: list[int],
    segments: tuple[EvidenceSegment, ...],
) -> tuple[EvidenceSegment, ...]:
    by_id = {item.segment_id: item for item in segments}
    try:
        return tuple(by_id[item] for item in ids)
    except KeyError as exc:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence segment id is out of range",
        ) from exc


def _timestamp(raw: object, field_name: str) -> datetime | None:
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


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "CombinedTemporalError",
    "CombinedTemporalFailureCode",
    "EvidenceSegment",
    "segment_source",
]
