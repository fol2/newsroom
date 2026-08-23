"""Semantic validation for NewsroomCombinedTemporalExtractionV1."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from newsroom.graphiti_adapter.combined_temporal_temporal import (
    assert_temporal_policy,
    iso_timestamp,
    parse_optional_timestamp,
)
from newsroom.graphiti_adapter.combined_temporal_types import (
    CombinedTemporalError,
    CombinedTemporalFailureCode,
    EvidenceSegment,
)
from newsroom.graphiti_adapter.result_mapping import is_source_registry_name

GOVERNED_ENTITY_TYPE_IDS = frozenset({0})
_RELATION_TYPE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
_CORRECTION = re.compile(r"(?i)\bcorrection\s*[:\-–—]")
_NEGATION = re.compile(
    r"(?i)(?:\b(?:not|never|no longer|cannot|neither|nor)\b|"
    r"\b[A-Za-z]+n['’]t\b)"
)
_STATEMENT_BOUNDARY = re.compile(
    r"(?i)(?:(?<=[.!?])\s+|[;\n]+|\b(?:and|but|while|whereas|although)\b)"
)
_WORD = re.compile(r"[A-Za-z0-9]+")


def normalise(
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
        cited = _resolve_segments(
            fact["evidence_segment_ids"], segments, contiguous=True
        )
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
        _assert_single_attribution(
            retained,
            source_name=source_name,
            target_name=target_name,
            relation_type=fact["relation_type"],
        )
        assert_temporal_policy(
            fact,
            retained,
            reference_time,
            source_name=source_name,
            target_name=target_name,
        )
        ranges[fact["fact"]] = cited
    if connected != id_set:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            "every entity must participate in a fact",
        )
    for entity in entities:
        cited = _resolve_segments(entity["evidence_segment_ids"], segments)
        if any(entity["name"] not in item.text for item in cited):
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "entity name is not present in every cited segment",
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


def _assert_single_attribution(
    retained: str,
    *,
    source_name: str,
    target_name: str,
    relation_type: str,
) -> None:
    match = _CORRECTION.search(retained)
    if match is not None:
        before = retained[: match.start()]
        after = retained[match.end() :]
        if before.strip() and after.strip():
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "evidence cites assertion and correction",
            )
    relation_words = {_stem(item) for item in relation_type.split("_")}
    statements = [
        item
        for item in _STATEMENT_BOUNDARY.split(retained)
        if source_name in item
        and target_name in item
        and relation_words <= {_stem(word) for word in _WORD.findall(item)}
    ]
    if statements and any(_NEGATION.search(item) for item in statements) and any(
        not _NEGATION.search(item) for item in statements
    ):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence cites contradictory attribution",
        )


def _stem(value: str) -> str:
    value = value.lower()
    if value.endswith("ied") and len(value) > 3:
        return value[:-3] + "y"
    if value.endswith("ed") and len(value) > 3:
        return value[:-2]
    return value


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
    valid_at = parse_optional_timestamp(raw.get("valid_at"), "valid_at")
    invalid_at = parse_optional_timestamp(raw.get("invalid_at"), "invalid_at")
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
        "valid_at": None if valid_at is None else iso_timestamp(valid_at),
        "invalid_at": None if invalid_at is None else iso_timestamp(invalid_at),
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
    *,
    contiguous: bool = False,
) -> tuple[EvidenceSegment, ...]:
    if contiguous and any(right != left + 1 for left, right in zip(ids, ids[1:])):
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence segments must form one contiguous range",
        )
    by_id = {item.segment_id: item for item in segments}
    try:
        return tuple(by_id[item] for item in ids)
    except KeyError as exc:
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence segment id is out of range",
        ) from exc


__all__ = ["GOVERNED_ENTITY_TYPE_IDS", "normalise"]
