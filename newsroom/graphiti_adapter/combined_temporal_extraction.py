"""Authority-private Newsroom combined-temporal extraction seam (#747).

Provider-free by default. Does not fork graphiti-core, mutate Neo4j, or
amend GING-010.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.edge_guard import guard_extracted_edges
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EXTRACTION_INSTRUCTIONS,
)
from newsroom.graphiti_adapter.identity import (
    configuration_digest,
    content_digest as revision_content_digest,
    ingest_key,
    uuid4_from_digest,
)
from newsroom.graphiti_adapter.result_mapping import is_source_registry_name
from newsroom.graphiti_adapter.temporal import map_reference_time
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION

CONTRACT_NAME = "NewsroomCombinedTemporalExtractionV1"
GROUP_ID = "newsroom-combined-temporal-v1"
MAX_SEGMENT_BYTES = 512
GOVERNED_ENTITY_TYPE_IDS = frozenset({0})
LOCAL_NEW = "LOCAL_NEW"
UNMEASURED = "UNMEASURED"
_REPO = Path(__file__).resolve().parents[2]
MEASUREMENTS_PATH = (
    _REPO
    / "docs"
    / "research"
    / "2026-08-22-graphiti-combined-temporal-extraction-measurements.json"
)
LIVE_PACKET_PATH = (
    _REPO
    / "docs"
    / "research"
    / "2026-08-22-graphiti-combined-temporal-extraction-packet.json"
)
CALL_SHAPES_PATH = (
    _REPO
    / "docs"
    / "research"
    / "2026-08-22-graphiti-combined-temporal-call-shapes.json"
)
_RELATION_TYPE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
_SPLIT = re.compile(rb"(?:(?<=[.!?])[ \t]+)|(?:\n+)")
_ISO_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)
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

SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "entities": {
            "items": {
                "additionalProperties": False,
                "properties": {
                    "entity_type_id": {"type": "integer"},
                    "evidence_segment_ids": {
                        "items": {"type": "integer"},
                        "type": "array",
                    },
                    "local_id": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": [
                    "local_id",
                    "name",
                    "entity_type_id",
                    "evidence_segment_ids",
                ],
                "type": "object",
            },
            "type": "array",
        },
        "facts": {
            "items": {
                "additionalProperties": False,
                "properties": {
                    "evidence_segment_ids": {
                        "items": {"type": "integer"},
                        "type": "array",
                    },
                    "fact": {"type": "string"},
                    "invalid_at": {"type": ["string", "null"]},
                    "relation_type": {"type": "string"},
                    "source_local_id": {"type": "integer"},
                    "target_local_id": {"type": "integer"},
                    "valid_at": {"type": ["string", "null"]},
                },
                "required": [
                    "source_local_id",
                    "target_local_id",
                    "relation_type",
                    "fact",
                    "valid_at",
                    "invalid_at",
                    "evidence_segment_ids",
                ],
                "type": "object",
            },
            "type": "array",
        },
    },
    "required": ["entities", "facts"],
    "type": "object",
}
SCHEMA_DIGEST = digest_canonical(SCHEMA)

EmbedEdges = Callable[[Any, list[Any]], Awaitable[None]]


class CombinedTemporalOutcome(StrEnum):
    TERMINAL_SUCCESS_WITH_PROPOSALS = "TERMINAL_SUCCESS_WITH_PROPOSALS"
    TERMINAL_SUCCESS_ZERO_PROPOSALS = "TERMINAL_SUCCESS_ZERO_PROPOSALS"
    TERMINAL_ATTEMPT_FAILURE = "TERMINAL_ATTEMPT_FAILURE"


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


@dataclass(frozen=True, slots=True)
class SourceRevisionInput:
    body: str
    revision_id: str
    source_id: str
    item_key: str
    representation_digest: str
    published_at: str | None
    updated_at: str | None
    observed_at: str
    ingested_at: str
    chunk_ordinal: int = 1
    predecessor_revision_id: str | None = None
    predecessor_body: str | None = None
    group_id: str = GROUP_ID
    episode_uuid: str | None = None

    @property
    def reference_time(self) -> str:
        return map_reference_time(
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
        ).reference_time.to_text()

    @property
    def temporal_basis(self) -> str:
        return map_reference_time(
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
        ).basis.value

    @property
    def content_digest(self) -> str:
        return revision_content_digest(
            headline="", body=self.body, canonical_url=""
        )

    @property
    def ingest_id(self) -> str:
        prompt = build_compact_prompt(self)
        return ingest_key(
            source_id=self.source_id,
            item_key=self.item_key,
            content_digest_value=self.content_digest,
            revision_id=self.revision_id,
            representation_digest=self.representation_digest,
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
            chunk_ordinal=self.chunk_ordinal,
            schema_digest=SCHEMA_DIGEST,
            prompt_digest=_candidate_prompt_digest(prompt),
        )


@dataclass(frozen=True, slots=True)
class CompactPrompt:
    text: str
    schema: dict[str, Any]
    segments: tuple[EvidenceSegment, ...]


@dataclass(frozen=True, slots=True)
class CombinedTemporalTransportResult:
    raw: object
    framework_version: str
    model_version: str | None
    token_usage: Mapping[str, object]
    provider_cost: object | None


@dataclass(frozen=True, slots=True)
class CombinedTemporalLeaf:
    outcome: CombinedTemporalOutcome
    failure_code: CombinedTemporalFailureCode
    prompt: CompactPrompt
    payload: dict[str, Any] | None
    payload_digest: str | None
    nodes: tuple[Any, ...]
    edges: tuple[Any, ...]
    guarded_edges: tuple[Any, ...]
    transport_calls: tuple[dict[str, object], ...]
    graph_effect_attempted: bool
    evidence_ranges: dict[str, tuple[EvidenceSegment, ...]] = field(
        default_factory=dict
    )
    node_resolutions: tuple[str, ...] = ()
    embedding_skipped: bool = True
    journal_skipped: bool = True
    rollback_skipped: bool = True
    raw_output_digest: str | None = None
    framework_version: str = GRAPHITI_CORE_RELEASE
    model_version: str | None = None
    prompt_digest: str | None = None
    invocation_count: int = 1
    token_usage: Mapping[str, object] = field(
        default_factory=lambda: {"basis": UNMEASURED}
    )
    provider_cost: object | None = None
    ingest_id: str | None = None
    temporal_basis: str | None = None
    configuration_digest: str | None = None
    temporal_policy_digest: str | None = None


class CombinedTemporalTransport(Protocol):
    def generate_response(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        response_model: str,
    ) -> CombinedTemporalTransportResult: ...


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
    return tuple(
        EvidenceSegment(
            segment_id=index,
            start_byte=start,
            end_byte=end,
            text=data[start:end].decode("utf-8"),
        )
        for index, (start, end) in enumerate(bounds)
    )


def build_compact_prompt(revision: SourceRevisionInput) -> CompactPrompt:
    segments = segment_source(revision.body)
    schema_text = canonical_json_bytes(SCHEMA).decode("utf-8")
    predecessor = revision.predecessor_revision_id or "null"
    lines = [
        CONTRACT_NAME,
        "Return exactly one JSON object. No prose, planning residue or schema echo.",
        "One effective source revision. Do not use any other revision's wording.",
        "Retain every supplied segment; do not summarise or truncate.",
        "Extract only named or source-grounded entities that participate in a retained fact.",
        "Zero facts requires zero entities.",
        "Use the source's certainty. Do not add outside knowledge.",
        "Put valid_at and invalid_at on each fact. Resolve relative dates against REFERENCE_TIME to ISO-8601 UTC, or null.",
        "Cite evidence with the integer segment IDs below. Do not invent byte offsets.",
        "A valid empty object is terminal success.",
        "Exclude source-registry identifiers and deterministic corpus metadata (SourceItem, SourceRevision, DERIVED_FROM, OBSERVED_IN).",
        GRAPHITI_EXTRACTION_INSTRUCTIONS,
        f"REFERENCE_TIME: {revision.reference_time}",
        f"TEMPORAL_BASIS: {revision.temporal_basis}",
        f"TEMPORAL_POLICY: {TEMPORAL_POLICY_VERSION}",
        f"REVISION_ID: {revision.revision_id}",
        f"PREDECESSOR_REVISION_ID: {predecessor}",
        "SCHEMA:",
        schema_text,
        "SEGMENTS:",
        *(f"[{item.segment_id}] {item.text}" for item in segments),
    ]
    return CompactPrompt("\n".join(lines), SCHEMA, segments)


def extract_combined_temporal(
    revision: SourceRevisionInput,
    *,
    transport: CombinedTemporalTransport,
    embed_edges: EmbedEdges | None = None,
) -> CombinedTemporalLeaf:
    ingest_id = revision.ingest_id
    temporal_basis = revision.temporal_basis
    UtcTimestamp.parse(revision.ingested_at)
    prompt = build_compact_prompt(revision)
    prompt_digest = _candidate_prompt_digest(prompt)
    result = transport.generate_response(
        prompt=prompt.text,
        schema=SCHEMA,
        response_model=CONTRACT_NAME,
    )
    raw = result.raw
    raw_digest = _raw_digest(raw)
    usage = dict(result.token_usage)
    calls = [
        {
            "response_model": CONTRACT_NAME,
            "prompt_bytes": len(prompt.text.encode("utf-8")),
            "schema_bytes": len(canonical_json_bytes(SCHEMA)),
            "raw_output_digest": raw_digest,
            "framework_version": result.framework_version,
            "model_version": result.model_version,
            "token_usage": usage,
            "provider_cost": result.provider_cost,
        }
    ]
    receipt = {
        "raw_output_digest": raw_digest,
        "framework_version": result.framework_version,
        "model_version": result.model_version,
        "prompt_digest": prompt_digest,
        "token_usage": usage,
        "provider_cost": result.provider_cost,
        "ingest_id": ingest_id,
        "temporal_basis": temporal_basis,
        "configuration_digest": configuration_digest(),
        "temporal_policy_digest": digest_canonical(TEMPORAL_POLICY_VERSION),
    }
    try:
        payload = _parse_payload(raw)
        normalised, ranges = _normalise(
            payload,
            prompt.segments,
            UtcTimestamp.parse(revision.reference_time).value,
        )
        nodes, edges = _expand(revision, normalised)
    except CombinedTemporalError as exc:
        return _leaf(
            CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE,
            exc.code,
            prompt,
            None,
            None,
            (),
            (),
            (),
            tuple(calls),
            {},
            (),
            embedding_skipped=True,
            journal_skipped=True,
            rollback_skipped=True,
            **receipt,
        )
    resolutions = _resolve_nodes_locally(nodes)
    journal = _MemoryJournal()
    journal.begin()
    try:
        guarded = _guard_edges(edges, embed_edges=embed_edges or _record_embeddings)
        journal.complete()
    except Exception:
        journal.rollback()
        return _leaf(
            CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE,
            CombinedTemporalFailureCode.PIPELINE_FAILED,
            prompt,
            None,
            None,
            (),
            (),
            (),
            tuple(calls),
            {},
            resolutions,
            embedding_skipped=False,
            journal_skipped=False,
            rollback_skipped=False,
            **receipt,
        )
    outcome = (
        CombinedTemporalOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
        if not normalised["facts"]
        else CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    )
    return _leaf(
        outcome,
        CombinedTemporalFailureCode.NONE,
        prompt,
        normalised,
        digest_canonical(normalised),
        nodes,
        edges,
        guarded,
        tuple(calls),
        ranges,
        resolutions,
        embedding_skipped=False,
        journal_skipped=False,
        rollback_skipped=True,
        **receipt,
    )


def _candidate_prompt_digest(prompt: CompactPrompt) -> str:
    return digest_canonical({"prompt": prompt.text, "schema": SCHEMA})


def _leaf(
    outcome: CombinedTemporalOutcome,
    failure_code: CombinedTemporalFailureCode,
    prompt: CompactPrompt,
    payload: dict[str, Any] | None,
    payload_digest: str | None,
    nodes: tuple[Any, ...],
    edges: tuple[Any, ...],
    guarded: tuple[Any, ...],
    calls: tuple[dict[str, object], ...],
    ranges: dict[str, tuple[EvidenceSegment, ...]],
    resolutions: tuple[str, ...],
    *,
    embedding_skipped: bool,
    journal_skipped: bool,
    rollback_skipped: bool,
    raw_output_digest: str | None,
    framework_version: str,
    model_version: str | None,
    prompt_digest: str | None,
    token_usage: Mapping[str, object],
    provider_cost: object | None,
    ingest_id: str | None,
    temporal_basis: str | None,
    configuration_digest: str | None,
    temporal_policy_digest: str | None,
) -> CombinedTemporalLeaf:
    return CombinedTemporalLeaf(
        outcome,
        failure_code,
        prompt,
        payload,
        payload_digest,
        nodes,
        edges,
        guarded,
        calls,
        False,
        ranges,
        resolutions,
        embedding_skipped,
        journal_skipped,
        rollback_skipped,
        raw_output_digest,
        framework_version,
        model_version,
        prompt_digest,
        1,
        token_usage,
        provider_cost,
        ingest_id,
        temporal_basis,
        configuration_digest,
        temporal_policy_digest,
    )


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
            parts.append((cursor, end))
            break
        cut = data.rfind(b" ", cursor, limit)
        if cut <= cursor:
            cut = limit
            while cut > cursor and data[cut] & 0xC0 == 0x80:
                cut -= 1
            if cut == cursor:
                cut = limit
        else:
            cut += 1
        parts.append((cursor, cut))
        cursor = cut
    return parts


def _parse_payload(raw: object) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        payload = dict(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
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
        source_name = next(
            item["name"] for item in entities if item["local_id"] == source
        )
        target_name = next(
            item["name"] for item in entities if item["local_id"] == target
        )
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
        cue_ok = all(
            re.search(rf"\b{re.escape(token)}\b", retained, flags=re.IGNORECASE)
            for token in fact["relation_type"].split("_")
        )
        if not cue_ok:
            raise CombinedTemporalError(
                CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
                "relation type is not supported by cited segments",
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
    marker = "Correction:"
    if marker not in retained:
        return
    before, _sep, after = retained.partition(marker)
    if before.strip() and after.strip():
        raise CombinedTemporalError(
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            "evidence cites assertion and correction",
        )


def _assert_temporal_policy(
    fact: Mapping[str, Any], retained: str, reference_time: datetime
) -> None:
    hits = [
        name
        for name in _RELATIVE_OFFSETS
        if re.search(rf"\b{name}\b", retained, flags=re.IGNORECASE)
    ]
    expected = {(reference_time + _RELATIVE_OFFSETS[name]).date() for name in hits}
    for field_name in ("valid_at", "invalid_at"):
        raw = fact[field_name]
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
        iso_date = value.date().isoformat()
        prose = f"{value.day} {_MONTH_NAMES[value.month - 1]} {value.year}"
        if iso_date not in retained and prose not in retained:
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
    if isinstance(type_id, bool) or type_id not in GOVERNED_ENTITY_TYPE_IDS:
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


def _expand(
    revision: SourceRevisionInput,
    payload: Mapping[str, Any],
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    created = UtcTimestamp.parse(revision.ingested_at).value
    reference = UtcTimestamp.parse(revision.reference_time).value
    ingest_id = revision.ingest_id
    nodes_by_id: dict[int, Any] = {}
    nodes: list[Any] = []
    for entity in payload["entities"]:
        node_uuid = _uuid(
            "node",
            ingest_id,
            entity["local_id"],
            entity["name"],
            entity["entity_type_id"],
        )
        node = _NamespaceNode(
            uuid=node_uuid,
            name=entity["name"],
            group_id=revision.group_id,
            labels=["Entity"],
            summary="",
            created_at=created,
            attributes={
                "entity_type_id": entity["entity_type_id"],
                "evidence_segment_ids": list(entity["evidence_segment_ids"]),
                "resolution": LOCAL_NEW,
                "ingest_id": ingest_id,
            },
        )
        nodes_by_id[entity["local_id"]] = node
        nodes.append(node)
    episode_uuid = revision.episode_uuid or ingest_id
    edges: list[Any] = []
    for fact in payload["facts"]:
        source = nodes_by_id[fact["source_local_id"]]
        target = nodes_by_id[fact["target_local_id"]]
        valid_at = (
            None
            if fact["valid_at"] is None
            else UtcTimestamp.parse(fact["valid_at"]).value
        )
        invalid_at = (
            None
            if fact["invalid_at"] is None
            else UtcTimestamp.parse(fact["invalid_at"]).value
        )
        edges.append(
            _NamespaceEdge(
                uuid=_uuid(
                    "edge",
                    ingest_id,
                    fact["source_local_id"],
                    fact["target_local_id"],
                    fact["relation_type"],
                    fact["fact"],
                ),
                group_id=revision.group_id,
                source_node_uuid=source.uuid,
                target_node_uuid=target.uuid,
                created_at=created,
                name=fact["relation_type"],
                fact=fact["fact"],
                episodes=[episode_uuid],
                valid_at=valid_at,
                invalid_at=invalid_at,
                reference_time=reference,
                attributes={
                    "evidence_segment_ids": list(fact["evidence_segment_ids"]),
                    "temporal_basis": revision.temporal_basis,
                    "temporal_policy": TEMPORAL_POLICY_VERSION,
                    "ingest_id": ingest_id,
                },
            )
        )
    return tuple(nodes), tuple(edges)


class _NamespaceNode(SimpleNamespace):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class _NamespaceEdge(SimpleNamespace):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class _MemoryJournal:
    def __init__(self) -> None:
        self.begun = False
        self.completed = False
        self.rolled_back = False

    def begin(self) -> None:
        self.begun = True

    def complete(self) -> None:
        self.completed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _resolve_nodes_locally(nodes: tuple[Any, ...]) -> tuple[str, ...]:
    resolutions: list[str] = []
    for node in nodes:
        attributes = dict(getattr(node, "attributes", {}) or {})
        attributes["resolution"] = LOCAL_NEW
        node.attributes = attributes
        resolutions.append(LOCAL_NEW)
    return tuple(resolutions)


def _guard_edges(
    edges: tuple[Any, ...], *, embed_edges: EmbedEdges
) -> tuple[Any, ...]:
    return tuple(
        _run_coroutine(
            guard_extracted_edges(
                extracted_edges=list(edges),
                uuid_map={},
                embedder=None,
                resolve_pointers=lambda items, uuid_map: items,
                create_embeddings=embed_edges,
            )
        )[0]
    )


def _run_coroutine(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _record_embeddings(embedder: Any, edges: list[Any]) -> None:
    del embedder
    for edge in edges:
        payload = canonical_json_bytes(
            {"uuid": str(edge.uuid), "fact": str(edge.fact)}
        )
        attributes = dict(getattr(edge, "attributes", {}) or {})
        attributes["embedding_digest"] = digest_bytes(payload)
        edge.attributes = attributes


def _uuid(*parts: object) -> str:
    digest = digest_bytes(canonical_json_bytes(list(parts)))
    return str(uuid4_from_digest(bytes.fromhex(digest.removeprefix("sha256:")[:32])))


__all__ = [
    "CALL_SHAPES_PATH",
    "CONTRACT_NAME",
    "CombinedTemporalError",
    "CombinedTemporalFailureCode",
    "CombinedTemporalLeaf",
    "CombinedTemporalOutcome",
    "CombinedTemporalTransport",
    "CombinedTemporalTransportResult",
    "CompactPrompt",
    "EvidenceSegment",
    "GOVERNED_ENTITY_TYPE_IDS",
    "GROUP_ID",
    "LIVE_PACKET_PATH",
    "LOCAL_NEW",
    "MEASUREMENTS_PATH",
    "SCHEMA",
    "SCHEMA_DIGEST",
    "SourceRevisionInput",
    "UNMEASURED",
    "build_compact_prompt",
    "extract_combined_temporal",
    "segment_source",
]
