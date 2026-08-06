"""Deterministic fixture/replay vector retrieval for Increment 5B3.

The module implements one independently attributable VECTOR branch.  It is a
repository-owned fixture lane: no model, embedding service, provider client,
credential, network destination, Neo4j vector index, cross-branch call, fusion,
hydration, Candidate mutation, relation admission, publication, or production
activation surface exists here.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from fractions import Fraction
from functools import cmp_to_key
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from newsroom.increment5.branch_contracts import (
    BranchExclusionReason,
    BranchMode,
    BranchOutcome,
)


RETRIEVAL_CONTRACT_DIGEST = (
    "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
)
VECTOR_COMPONENT_DIGEST = (
    "sha256:efa34511338c4f28f7698db3aab7afbdde36c36e7d9ea36745367180b678db82"
)
EMBEDDING_COMPONENT_DIGEST = (
    "sha256:cb084be3748ace7a75f68e2f2641566248c53566365f8f802c6c24b75e99c5e9"
)
VECTOR_PROFILE_ID = "increment5-vector-fixture-replay-v1"
VECTOR_PROVIDER_ID = "vector-2026.06"
VECTOR_ACTOR_ID = "retrieval_worker"
VECTOR_PURPOSE = "vector_fixture_replay"
VECTOR_POLICY_ID = "increment5-vector-fixture-replay-v1"
VECTOR_SOURCE_DIMENSIONS = 16
VECTOR_OUTPUT_DIMENSIONS = 1_024
VECTOR_COMPONENT_SCALE = 1_000_000
VECTOR_MATERIALIZED_BYTES = 4_096
VECTOR_RESULT_LIMIT = 8
VECTOR_TIMEOUT_MS = 5_000
VECTOR_RESPONSE_LIMIT_BYTES = 262_144
VECTOR_EXTERNAL_CALLS = 0
VECTOR_PROVIDER_CALLS = 0
VECTOR_MODEL_CALLS = 0
VECTOR_EMBEDDING_CALLS = 0
VECTOR_PROVIDER_SPEND_MICROS = 0

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class VectorContractError(ValueError):
    """A vector request, catalog record, authority view, or receipt is malformed."""


class VectorJournalError(RuntimeError):
    """The immutable vector receipt journal is unavailable or inconsistent."""


class VectorFailureReason(StrEnum):
    NO_MATCH = "NO_MATCH"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    VECTOR_COMPONENT_MISMATCH = "VECTOR_COMPONENT_MISMATCH"
    EMBEDDING_COMPONENT_MISMATCH = "EMBEDDING_COMPONENT_MISMATCH"
    CATALOG_MISMATCH = "CATALOG_MISMATCH"
    QUERY_UNKNOWN = "QUERY_UNKNOWN"
    QUERY_DIGEST_MISMATCH = "QUERY_DIGEST_MISMATCH"
    AUTHORITY_VIEW_UNAVAILABLE = "AUTHORITY_VIEW_UNAVAILABLE"
    GENERATION_INACTIVE = "GENERATION_INACTIVE"
    GENERATION_INCOMPLETE = "GENERATION_INCOMPLETE"
    GENERATION_IDENTITY_MISMATCH = "GENERATION_IDENTITY_MISMATCH"
    RIGHTS_MANIFEST_MISMATCH = "RIGHTS_MANIFEST_MISMATCH"
    WATERMARK_BEHIND = "WATERMARK_BEHIND"
    REQUIRED_GAP_OPEN = "REQUIRED_GAP_OPEN"
    DEAD_LETTER_PRESENT = "DEAD_LETTER_PRESENT"
    AUTHORITY_VIEW_STALE = "AUTHORITY_VIEW_STALE"
    PASSAGE_BINDING_MISSING = "PASSAGE_BINDING_MISSING"
    PASSAGE_BINDING_INTEGRITY = "PASSAGE_BINDING_INTEGRITY"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    RESPONSE_LIMIT_EXCEEDED = "RESPONSE_LIMIT_EXCEEDED"
    ZERO_VECTOR = "ZERO_VECTOR"
    FIXTURE_INTEGRITY_ERROR = "FIXTURE_INTEGRITY_ERROR"


class PassageLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    UNRESOLVED = "UNRESOLVED"
    PROPOSAL_ONLY = "PROPOSAL_ONLY"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    TOMBSTONED = "TOMBSTONED"


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VectorContractError("value is not canonical JSON") from exc


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise VectorContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise VectorContractError(f"{field} must be a bounded canonical token")
    return value


def _require_text(value: str, *, field: str, maximum_bytes: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise VectorContractError(f"{field} must be bounded canonical text")
    return value


def _require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VectorContractError(f"{field} must be a non-negative integer")
    return value


def _parse_utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise VectorContractError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise VectorContractError(f"{field} must be canonical second-resolution UTC") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise VectorContractError(f"{field} must be canonical second-resolution UTC")
    return parsed


def _require_uuid4(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise VectorContractError(f"{field} must be a UUIDv4 string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise VectorContractError(f"{field} must be a UUIDv4 string") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise VectorContractError(f"{field} must be a canonical UUIDv4 string")
    return value


def _load_json_without_duplicates(text: str) -> object:
    def object_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise VectorContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=object_hook)
    except json.JSONDecodeError as exc:
        raise VectorContractError("fixture catalog is not valid JSON") from exc


def _require_exact_keys(
    value: Mapping[str, object], *, required: set[str], field: str
) -> None:
    actual = set(value)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        raise VectorContractError(
            f"{field} keys are not exact; missing={missing}, extra={extra}"
        )


def _source_vector(value: object, *, field: str) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != VECTOR_SOURCE_DIMENSIONS:
        raise VectorContractError(
            f"{field} must contain exactly {VECTOR_SOURCE_DIMENSIONS} fixed-point components"
        )
    result: list[int] = []
    for index, component in enumerate(value):
        if (
            isinstance(component, bool)
            or not isinstance(component, int)
            or not -8_000_000 <= component <= 8_000_000
        ):
            raise VectorContractError(
                f"{field}[{index}] must be a bounded fixed-point integer"
            )
        result.append(component)
    if not any(result):
        raise VectorContractError(f"{field} cannot be the zero vector")
    return tuple(result)


def _float32(value: Fraction) -> float:
    as_float = float(value)
    packed = struct.pack(">f", as_float)
    result = struct.unpack(">f", packed)[0]
    if result == float("inf") or result == float("-inf") or result != result:
        raise VectorContractError("fixed-point component cannot materialize to a finite float32")
    return result


def materialize_fixed_point_vector(
    source: Sequence[int],
) -> tuple[tuple[float, ...], bytes, str]:
    """Materialize 16 fixed-point values as 1024 big-endian IEEE-754 binary32 values."""

    normalized = _source_vector(list(source), field="source_vector")
    materialized = [
        _float32(Fraction(component, VECTOR_COMPONENT_SCALE)) for component in normalized
    ]
    materialized.extend([0.0] * (VECTOR_OUTPUT_DIMENSIONS - VECTOR_SOURCE_DIMENSIONS))
    vector = tuple(materialized)
    raw = b"".join(struct.pack(">f", component) for component in vector)
    if len(raw) != VECTOR_MATERIALIZED_BYTES:
        raise AssertionError("materialized vector byte length drifted")
    return vector, raw, _digest_bytes(raw)


def _fraction(value: float) -> Fraction:
    numerator, denominator = value.as_integer_ratio()
    return Fraction(numerator, denominator)


def _vector_fraction_tuple(vector: Sequence[float]) -> tuple[Fraction, ...]:
    if len(vector) != VECTOR_OUTPUT_DIMENSIONS:
        raise VectorContractError("materialized vector has the wrong dimension")
    return tuple(_fraction(component) for component in vector)


@dataclass(frozen=True, slots=True)
class VectorFixtureQuery:
    query_id: str
    source_vector: tuple[int, ...]
    query_digest: str

    def __post_init__(self) -> None:
        _require_token(self.query_id, field="fixture_query_id")
        normalized = _source_vector(list(self.source_vector), field="fixture_query_vector")
        object.__setattr__(self, "source_vector", normalized)
        expected = _digest_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": "newsroom.increment5.vector-fixture-query.v1",
                    "query_id": self.query_id,
                    "source_dimensions": VECTOR_SOURCE_DIMENSIONS,
                    "component_scale": VECTOR_COMPONENT_SCALE,
                    "source_vector": list(self.source_vector),
                }
            )
        )
        _require_digest(self.query_digest, field="fixture_query_digest")
        if self.query_digest != expected:
            raise VectorContractError("fixture query digest does not match canonical content")

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> "VectorFixtureQuery":
        _require_exact_keys(
            value,
            required={"query_id", "source_vector"},
            field="fixture_query",
        )
        query_id = value["query_id"]
        if not isinstance(query_id, str):
            raise VectorContractError("fixture query_id must be text")
        source = _source_vector(value["source_vector"], field="fixture_query_vector")
        digest = _digest_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": "newsroom.increment5.vector-fixture-query.v1",
                    "query_id": query_id,
                    "source_dimensions": VECTOR_SOURCE_DIMENSIONS,
                    "component_scale": VECTOR_COMPONENT_SCALE,
                    "source_vector": list(source),
                }
            )
        )
        return cls(query_id=query_id, source_vector=source, query_digest=digest)


@dataclass(frozen=True, slots=True)
class VectorFixtureDocument:
    passage_id: str
    dependency_root_id: str
    source_revision_id: str
    language: str
    query_ids: tuple[str, ...]
    source_vector: tuple[int, ...]
    valid_from: str
    valid_to: str
    document_digest: str
    rights_digest: str
    provenance_digest: str
    vector_digest: str

    def __post_init__(self) -> None:
        for field_name in ("passage_id", "dependency_root_id", "source_revision_id"):
            _require_text(getattr(self, field_name), field=field_name)
        _require_token(self.language, field="fixture_language")
        if not self.query_ids or len(set(self.query_ids)) != len(self.query_ids):
            raise VectorContractError("fixture document query bindings must be unique and non-empty")
        for query_id in self.query_ids:
            _require_token(query_id, field="fixture_document_query_id")
        normalized = _source_vector(list(self.source_vector), field="fixture_document_vector")
        object.__setattr__(self, "source_vector", normalized)
        valid_from = _parse_utc(self.valid_from, field="fixture_valid_from")
        valid_to = _parse_utc(self.valid_to, field="fixture_valid_to")
        if valid_from >= valid_to:
            raise VectorContractError("fixture validity window must be increasing")
        for field_name in (
            "document_digest",
            "rights_digest",
            "provenance_digest",
            "vector_digest",
        ):
            _require_digest(getattr(self, field_name), field=field_name)
        _, _, expected_vector_digest = materialize_fixed_point_vector(self.source_vector)
        if self.vector_digest != expected_vector_digest:
            raise VectorContractError("fixture document vector digest does not match materialized bytes")
        canonical_binding = {
            "schema_version": "newsroom.increment5.vector-fixture-document.v1",
            "passage_id": self.passage_id,
            "dependency_root_id": self.dependency_root_id,
            "source_revision_id": self.source_revision_id,
            "language": self.language,
            "query_ids": list(self.query_ids),
            "source_vector": list(self.source_vector),
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }
        expected_document_digest = _digest_bytes(_canonical_json_bytes(canonical_binding))
        if self.document_digest != expected_document_digest:
            raise VectorContractError("fixture document digest does not match canonical binding")
        expected_rights = _digest_bytes(f"rights:{self.passage_id}".encode("utf-8"))
        expected_provenance = _digest_bytes(
            f"provenance:{self.source_revision_id}".encode("utf-8")
        )
        if self.rights_digest != expected_rights:
            raise VectorContractError("fixture rights digest does not match passage identity")
        if self.provenance_digest != expected_provenance:
            raise VectorContractError("fixture provenance digest does not match revision identity")

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> "VectorFixtureDocument":
        _require_exact_keys(
            value,
            required={
                "passage_id",
                "dependency_root_id",
                "source_revision_id",
                "language",
                "query_ids",
                "source_vector",
                "valid_from",
                "valid_to",
            },
            field="fixture_document",
        )
        for name in (
            "passage_id",
            "dependency_root_id",
            "source_revision_id",
            "language",
            "valid_from",
            "valid_to",
        ):
            if not isinstance(value[name], str):
                raise VectorContractError(f"fixture document {name} must be text")
        raw_query_ids = value["query_ids"]
        if not isinstance(raw_query_ids, list) or not all(
            isinstance(item, str) for item in raw_query_ids
        ):
            raise VectorContractError("fixture document query_ids must be text values")
        query_ids = tuple(raw_query_ids)
        source = _source_vector(value["source_vector"], field="fixture_document_vector")
        canonical_binding = {
            "schema_version": "newsroom.increment5.vector-fixture-document.v1",
            "passage_id": value["passage_id"],
            "dependency_root_id": value["dependency_root_id"],
            "source_revision_id": value["source_revision_id"],
            "language": value["language"],
            "query_ids": list(query_ids),
            "source_vector": list(source),
            "valid_from": value["valid_from"],
            "valid_to": value["valid_to"],
        }
        _, _, vector_digest = materialize_fixed_point_vector(source)
        return cls(
            passage_id=value["passage_id"],
            dependency_root_id=value["dependency_root_id"],
            source_revision_id=value["source_revision_id"],
            language=value["language"],
            query_ids=query_ids,
            source_vector=source,
            valid_from=value["valid_from"],
            valid_to=value["valid_to"],
            document_digest=_digest_bytes(_canonical_json_bytes(canonical_binding)),
            rights_digest=_digest_bytes(f"rights:{value['passage_id']}".encode("utf-8")),
            provenance_digest=_digest_bytes(
                f"provenance:{value['source_revision_id']}".encode("utf-8")
            ),
            vector_digest=vector_digest,
        )


@dataclass(frozen=True, slots=True)
class VectorFixtureCatalog:
    catalog_id: str
    provider_id: str
    profile_id: str
    contract_digest: str
    vector_component_digest: str
    embedding_component_digest: str
    source_dimensions: int
    output_dimensions: int
    component_scale: int
    output_type: str
    byte_order: str
    similarity: str
    quantization: str
    queries: tuple[VectorFixtureQuery, ...]
    documents: tuple[VectorFixtureDocument, ...]
    catalog_digest: str

    def __post_init__(self) -> None:
        _require_token(self.catalog_id, field="fixture_catalog_id")
        _require_token(self.provider_id, field="fixture_provider_id")
        _require_token(self.profile_id, field="fixture_profile_id")
        for field_name in (
            "contract_digest",
            "vector_component_digest",
            "embedding_component_digest",
            "catalog_digest",
        ):
            _require_digest(getattr(self, field_name), field=field_name)
        if self.provider_id != VECTOR_PROVIDER_ID:
            raise VectorContractError("fixture provider identity drifted")
        if self.profile_id != VECTOR_PROFILE_ID:
            raise VectorContractError("fixture profile identity drifted")
        if self.contract_digest != RETRIEVAL_CONTRACT_DIGEST:
            raise VectorContractError("fixture retrieval contract identity drifted")
        if self.vector_component_digest != VECTOR_COMPONENT_DIGEST:
            raise VectorContractError("fixture vector component identity drifted")
        if self.embedding_component_digest != EMBEDDING_COMPONENT_DIGEST:
            raise VectorContractError("fixture embedding component identity drifted")
        if self.source_dimensions != VECTOR_SOURCE_DIMENSIONS:
            raise VectorContractError("fixture source dimension drifted")
        if self.output_dimensions != VECTOR_OUTPUT_DIMENSIONS:
            raise VectorContractError("fixture output dimension drifted")
        if self.component_scale != VECTOR_COMPONENT_SCALE:
            raise VectorContractError("fixture component scale drifted")
        if self.output_type != "FLOAT32":
            raise VectorContractError("fixture output type must remain FLOAT32")
        if self.byte_order != "BIG_ENDIAN":
            raise VectorContractError("fixture byte order must remain BIG_ENDIAN")
        if self.similarity != "COSINE":
            raise VectorContractError("fixture similarity must remain COSINE")
        if self.quantization != "NONE":
            raise VectorContractError("fixture quantization must remain NONE")
        query_ids = [query.query_id for query in self.queries]
        passage_ids = [document.passage_id for document in self.documents]
        if not self.queries or len(query_ids) != len(set(query_ids)):
            raise VectorContractError("fixture query identities must be unique and non-empty")
        if not self.documents or len(passage_ids) != len(set(passage_ids)):
            raise VectorContractError("fixture passage identities must be unique and non-empty")
        known_queries = set(query_ids)
        for document in self.documents:
            unknown = set(document.query_ids) - known_queries
            if unknown:
                raise VectorContractError(
                    f"fixture document references unknown queries: {sorted(unknown)}"
                )

    @classmethod
    def load(cls, path: Path) -> "VectorFixtureCatalog":
        raw = path.read_text(encoding="utf-8")
        value = _load_json_without_duplicates(raw)
        if not isinstance(value, dict):
            raise VectorContractError("fixture catalog root must be an object")
        required = {
            "schema_version",
            "catalog_id",
            "provider_id",
            "profile_id",
            "contract_digest",
            "vector_component_digest",
            "embedding_component_digest",
            "source_dimensions",
            "output_dimensions",
            "component_scale",
            "output_type",
            "byte_order",
            "similarity",
            "quantization",
            "queries",
            "documents",
        }
        _require_exact_keys(value, required=required, field="fixture_catalog")
        if value["schema_version"] != "newsroom.increment5.vector-fixture-catalog.v1":
            raise VectorContractError("fixture catalog schema version is not accepted")
        raw_queries = value["queries"]
        raw_documents = value["documents"]
        if not isinstance(raw_queries, list) or not all(
            isinstance(item, dict) for item in raw_queries
        ):
            raise VectorContractError("fixture queries must be objects")
        if not isinstance(raw_documents, list) or not all(
            isinstance(item, dict) for item in raw_documents
        ):
            raise VectorContractError("fixture documents must be objects")
        text_fields = {
            "catalog_id",
            "provider_id",
            "profile_id",
            "contract_digest",
            "vector_component_digest",
            "embedding_component_digest",
            "output_type",
            "byte_order",
            "similarity",
            "quantization",
        }
        for name in text_fields:
            if not isinstance(value[name], str):
                raise VectorContractError(f"fixture catalog {name} must be text")
        integer_fields = {"source_dimensions", "output_dimensions", "component_scale"}
        for name in integer_fields:
            if isinstance(value[name], bool) or not isinstance(value[name], int):
                raise VectorContractError(f"fixture catalog {name} must be an integer")
        canonical_payload = _canonical_json_bytes(value)
        return cls(
            catalog_id=value["catalog_id"],
            provider_id=value["provider_id"],
            profile_id=value["profile_id"],
            contract_digest=value["contract_digest"],
            vector_component_digest=value["vector_component_digest"],
            embedding_component_digest=value["embedding_component_digest"],
            source_dimensions=value["source_dimensions"],
            output_dimensions=value["output_dimensions"],
            component_scale=value["component_scale"],
            output_type=value["output_type"],
            byte_order=value["byte_order"],
            similarity=value["similarity"],
            quantization=value["quantization"],
            queries=tuple(VectorFixtureQuery.from_record(item) for item in raw_queries),
            documents=tuple(
                VectorFixtureDocument.from_record(item) for item in raw_documents
            ),
            catalog_digest=_digest_bytes(canonical_payload),
        )

    def query(self, query_id: str) -> VectorFixtureQuery | None:
        return next((query for query in self.queries if query.query_id == query_id), None)


@dataclass(frozen=True, slots=True)
class VectorAuthorityBinding:
    passage_id: str
    dependency_root_id: str
    source_revision_id: str
    document_digest: str
    rights_digest: str
    provenance_digest: str
    lifecycle: PassageLifecycle
    rights_current: bool

    def __post_init__(self) -> None:
        for field_name in ("passage_id", "dependency_root_id", "source_revision_id"):
            _require_text(getattr(self, field_name), field=field_name)
        for field_name in ("document_digest", "rights_digest", "provenance_digest"):
            _require_digest(getattr(self, field_name), field=field_name)
        if not isinstance(self.lifecycle, PassageLifecycle):
            raise VectorContractError("authority binding lifecycle must be typed")
        if not isinstance(self.rights_current, bool):
            raise VectorContractError("authority binding rights_current must be boolean")

    @classmethod
    def active(cls, document: VectorFixtureDocument) -> "VectorAuthorityBinding":
        return cls(
            passage_id=document.passage_id,
            dependency_root_id=document.dependency_root_id,
            source_revision_id=document.source_revision_id,
            document_digest=document.document_digest,
            rights_digest=document.rights_digest,
            provenance_digest=document.provenance_digest,
            lifecycle=PassageLifecycle.ACTIVE,
            rights_current=True,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "passage_id": self.passage_id,
            "dependency_root_id": self.dependency_root_id,
            "source_revision_id": self.source_revision_id,
            "document_digest": self.document_digest,
            "rights_digest": self.rights_digest,
            "provenance_digest": self.provenance_digest,
            "lifecycle": self.lifecycle.value,
            "rights_current": self.rights_current,
        }


@dataclass(frozen=True, slots=True)
class VectorAuthorityView:
    generation_id: str
    generation_digest: str
    active: bool
    complete: bool
    catalog_digest: str
    profile_id: str
    vector_component_digest: str
    embedding_component_digest: str
    rights_manifest_digest: str
    watermark_seq: int
    open_gap_count: int
    dead_letter_count: int
    validated_at: str
    maximum_age_seconds: int
    bindings: tuple[VectorAuthorityBinding, ...]

    def __post_init__(self) -> None:
        _require_token(self.generation_id, field="vector_generation_id")
        for field_name in (
            "generation_digest",
            "catalog_digest",
            "vector_component_digest",
            "embedding_component_digest",
            "rights_manifest_digest",
        ):
            _require_digest(getattr(self, field_name), field=field_name)
        _require_token(self.profile_id, field="vector_profile_id")
        if not isinstance(self.active, bool) or not isinstance(self.complete, bool):
            raise VectorContractError("generation active and complete flags must be boolean")
        for field_name in ("watermark_seq", "open_gap_count", "dead_letter_count"):
            _require_non_negative_int(getattr(self, field_name), field=field_name)
        _parse_utc(self.validated_at, field="vector_validated_at")
        if (
            isinstance(self.maximum_age_seconds, bool)
            or not isinstance(self.maximum_age_seconds, int)
            or self.maximum_age_seconds <= 0
        ):
            raise VectorContractError("maximum_age_seconds must be positive")
        passage_ids = [binding.passage_id for binding in self.bindings]
        if len(passage_ids) != len(set(passage_ids)):
            raise VectorContractError("authority passage bindings must be unique")
        expected_generation = _digest_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": "newsroom.increment5.vector-authority-generation.v1",
                    "generation_id": self.generation_id,
                    "catalog_digest": self.catalog_digest,
                    "profile_id": self.profile_id,
                    "vector_component_digest": self.vector_component_digest,
                    "embedding_component_digest": self.embedding_component_digest,
                    "rights_manifest_digest": self.rights_manifest_digest,
                    "watermark_seq": self.watermark_seq,
                    "bindings": [binding.canonical_value() for binding in self.bindings],
                }
            )
        )
        if self.generation_digest != expected_generation:
            raise VectorContractError("generation digest does not match canonical authority view")

    @classmethod
    def for_catalog(
        cls,
        catalog: VectorFixtureCatalog,
        *,
        validated_at: str,
        generation_id: str = "vector-fixture-generation-v1",
        watermark_seq: int = 1,
        maximum_age_seconds: int = 86_400,
        bindings: Sequence[VectorAuthorityBinding] | None = None,
        active: bool = True,
        complete: bool = True,
        open_gap_count: int = 0,
        dead_letter_count: int = 0,
        catalog_digest: str | None = None,
        profile_id: str | None = None,
        vector_component_digest: str | None = None,
        embedding_component_digest: str | None = None,
        rights_manifest_digest: str | None = None,
    ) -> "VectorAuthorityView":
        selected_bindings = tuple(
            bindings
            if bindings is not None
            else [VectorAuthorityBinding.active(document) for document in catalog.documents]
        )
        selected_catalog = catalog_digest or catalog.catalog_digest
        selected_profile = profile_id or catalog.profile_id
        selected_vector = vector_component_digest or catalog.vector_component_digest
        selected_embedding = embedding_component_digest or catalog.embedding_component_digest
        selected_rights = rights_manifest_digest or _digest_bytes(
            _canonical_json_bytes(
                [
                    {
                        "passage_id": binding.passage_id,
                        "rights_digest": binding.rights_digest,
                        "rights_current": binding.rights_current,
                    }
                    for binding in selected_bindings
                ]
            )
        )
        generation_payload = {
            "schema_version": "newsroom.increment5.vector-authority-generation.v1",
            "generation_id": generation_id,
            "catalog_digest": selected_catalog,
            "profile_id": selected_profile,
            "vector_component_digest": selected_vector,
            "embedding_component_digest": selected_embedding,
            "rights_manifest_digest": selected_rights,
            "watermark_seq": watermark_seq,
            "bindings": [binding.canonical_value() for binding in selected_bindings],
        }
        return cls(
            generation_id=generation_id,
            generation_digest=_digest_bytes(_canonical_json_bytes(generation_payload)),
            active=active,
            complete=complete,
            catalog_digest=selected_catalog,
            profile_id=selected_profile,
            vector_component_digest=selected_vector,
            embedding_component_digest=selected_embedding,
            rights_manifest_digest=selected_rights,
            watermark_seq=watermark_seq,
            open_gap_count=open_gap_count,
            dead_letter_count=dead_letter_count,
            validated_at=validated_at,
            maximum_age_seconds=maximum_age_seconds,
            bindings=selected_bindings,
        )


@dataclass(frozen=True, slots=True)
class VectorBranchRequest:
    request_id: str
    idempotency_key: str
    actor_id: str
    purpose: str
    policy_id: str
    contract_digest: str
    catalog_digest: str
    profile_id: str
    vector_component_digest: str
    embedding_component_digest: str
    query_id: str
    query_digest: str
    query_valid_time: str
    serving_time: str
    minimum_watermark_seq: int = 0
    result_limit: int = VECTOR_RESULT_LIMIT
    timeout_ms: int = VECTOR_TIMEOUT_MS
    response_limit_bytes: int = VECTOR_RESPONSE_LIMIT_BYTES

    def __post_init__(self) -> None:
        _require_uuid4(self.request_id, field="vector_request_id")
        _require_text(
            self.idempotency_key,
            field="vector_idempotency_key",
            maximum_bytes=256,
        )
        for field_name in ("actor_id", "purpose", "policy_id", "profile_id", "query_id"):
            _require_token(getattr(self, field_name), field=field_name)
        for field_name in (
            "contract_digest",
            "catalog_digest",
            "vector_component_digest",
            "embedding_component_digest",
            "query_digest",
        ):
            _require_digest(getattr(self, field_name), field=field_name)
        query_valid = _parse_utc(self.query_valid_time, field="vector_query_valid_time")
        serving = _parse_utc(self.serving_time, field="vector_serving_time")
        if query_valid > serving:
            raise VectorContractError("query-valid time cannot be after serving time")
        _require_non_negative_int(
            self.minimum_watermark_seq,
            field="vector_minimum_watermark_seq",
        )
        if self.result_limit != VECTOR_RESULT_LIMIT:
            raise VectorContractError("vector result limit must remain fixed at eight")
        if self.timeout_ms != VECTOR_TIMEOUT_MS:
            raise VectorContractError("vector timeout must remain fixed at 5000 ms")
        if self.response_limit_bytes != VECTOR_RESPONSE_LIMIT_BYTES:
            raise VectorContractError("vector response limit must remain fixed at 262144 bytes")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.vector-branch-request.v1",
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "actor_id": self.actor_id,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "contract_digest": self.contract_digest,
            "catalog_digest": self.catalog_digest,
            "profile_id": self.profile_id,
            "vector_component_digest": self.vector_component_digest,
            "embedding_component_digest": self.embedding_component_digest,
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "minimum_watermark_seq": self.minimum_watermark_seq,
            "result_limit": self.result_limit,
            "timeout_ms": self.timeout_ms,
            "response_limit_bytes": self.response_limit_bytes,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def request_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ExactCosineProof:
    sign: int
    dot_numerator: int
    dot_denominator: int
    query_norm_numerator: int
    query_norm_denominator: int
    document_norm_numerator: int
    document_norm_denominator: int
    squared_cosine_numerator: int
    squared_cosine_denominator: int

    def __post_init__(self) -> None:
        if self.sign not in {-1, 0, 1}:
            raise VectorContractError("cosine proof sign must be -1, 0, or 1")
        for field_name in (
            "dot_denominator",
            "query_norm_denominator",
            "document_norm_denominator",
            "squared_cosine_denominator",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise VectorContractError(f"{field_name} must be positive")
        for field_name in (
            "query_norm_numerator",
            "document_norm_numerator",
            "squared_cosine_numerator",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise VectorContractError(f"{field_name} must be non-negative")

    def canonical_value(self) -> dict[str, int]:
        return {
            "sign": self.sign,
            "dot_numerator": self.dot_numerator,
            "dot_denominator": self.dot_denominator,
            "query_norm_numerator": self.query_norm_numerator,
            "query_norm_denominator": self.query_norm_denominator,
            "document_norm_numerator": self.document_norm_numerator,
            "document_norm_denominator": self.document_norm_denominator,
            "squared_cosine_numerator": self.squared_cosine_numerator,
            "squared_cosine_denominator": self.squared_cosine_denominator,
        }


@dataclass(frozen=True, slots=True)
class VectorBranchHit:
    rank: int
    passage_id: str
    dependency_root_id: str
    source_revision_id: str
    language: str
    document_digest: str
    vector_digest: str
    rights_digest: str
    provenance_digest: str
    proof: ExactCosineProof

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not 1 <= self.rank <= VECTOR_RESULT_LIMIT:
            raise VectorContractError("vector hit rank exceeds the fixed bound")
        for field_name in ("passage_id", "dependency_root_id", "source_revision_id"):
            _require_text(getattr(self, field_name), field=field_name)
        _require_token(self.language, field="vector_hit_language")
        for field_name in (
            "document_digest",
            "vector_digest",
            "rights_digest",
            "provenance_digest",
        ):
            _require_digest(getattr(self, field_name), field=field_name)
        if not isinstance(self.proof, ExactCosineProof):
            raise VectorContractError("vector hit must retain exact cosine proof")

    def canonical_value(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "passage_id": self.passage_id,
            "dependency_root_id": self.dependency_root_id,
            "source_revision_id": self.source_revision_id,
            "language": self.language,
            "document_digest": self.document_digest,
            "vector_digest": self.vector_digest,
            "rights_digest": self.rights_digest,
            "provenance_digest": self.provenance_digest,
            "proof": self.proof.canonical_value(),
        }


@dataclass(frozen=True, slots=True)
class VectorBranchExclusion:
    passage_id: str
    reason: BranchExclusionReason

    def __post_init__(self) -> None:
        _require_text(self.passage_id, field="excluded_passage_id")
        if not isinstance(self.reason, BranchExclusionReason):
            raise VectorContractError("vector exclusion reason must be typed")

    def canonical_value(self) -> dict[str, str]:
        return {"passage_id": self.passage_id, "reason": self.reason.value}


@dataclass(frozen=True, slots=True)
class VectorBranchReceipt:
    receipt_id: str
    request_digest: str
    mode: BranchMode
    outcome: BranchOutcome
    reason: VectorFailureReason | None
    catalog_digest: str
    generation_id: str | None
    generation_digest: str | None
    profile_id: str
    vector_component_digest: str
    embedding_component_digest: str
    query_id: str
    query_digest: str
    query_valid_time: str
    serving_time: str
    elapsed_ms: int
    watermark_seq: int | None
    rights_manifest_digest: str | None
    hits: tuple[VectorBranchHit, ...]
    exclusions: tuple[VectorBranchExclusion, ...]
    authority_read_count: int
    fixture_vector_count: int
    external_call_count: int = VECTOR_EXTERNAL_CALLS
    provider_call_count: int = VECTOR_PROVIDER_CALLS
    model_call_count: int = VECTOR_MODEL_CALLS
    embedding_call_count: int = VECTOR_EMBEDDING_CALLS
    provider_spend_micros: int = VECTOR_PROVIDER_SPEND_MICROS
    replay_only: bool = True
    qualification_authority_granted: bool = False
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.receipt_id)
        except (ValueError, AttributeError) as exc:
            raise VectorContractError("vector receipt_id must be a UUID") from exc
        if str(parsed) != self.receipt_id:
            raise VectorContractError("vector receipt_id must be canonical")
        _require_digest(self.request_digest, field="vector_receipt_request_digest")
        if self.mode is not BranchMode.VECTOR:
            raise VectorContractError("vector receipt mode must remain VECTOR")
        if not isinstance(self.outcome, BranchOutcome):
            raise VectorContractError("vector receipt outcome must be typed")
        if self.reason is not None and not isinstance(self.reason, VectorFailureReason):
            raise VectorContractError("vector receipt reason must be typed")
        _require_digest(self.catalog_digest, field="vector_receipt_catalog_digest")
        if self.generation_id is not None:
            _require_token(self.generation_id, field="vector_receipt_generation_id")
        if self.generation_digest is not None:
            _require_digest(
                self.generation_digest,
                field="vector_receipt_generation_digest",
            )
        _require_token(self.profile_id, field="vector_receipt_profile_id")
        _require_digest(
            self.vector_component_digest,
            field="vector_receipt_component_digest",
        )
        _require_digest(
            self.embedding_component_digest,
            field="vector_receipt_embedding_digest",
        )
        _require_token(self.query_id, field="vector_receipt_query_id")
        _require_digest(self.query_digest, field="vector_receipt_query_digest")
        _parse_utc(self.query_valid_time, field="vector_receipt_query_valid_time")
        _parse_utc(self.serving_time, field="vector_receipt_serving_time")
        if isinstance(self.elapsed_ms, bool) or not 0 <= self.elapsed_ms <= VECTOR_TIMEOUT_MS:
            raise VectorContractError("vector receipt elapsed_ms is outside the fixed budget")
        if self.watermark_seq is not None:
            _require_non_negative_int(self.watermark_seq, field="vector_receipt_watermark")
        if self.rights_manifest_digest is not None:
            _require_digest(
                self.rights_manifest_digest,
                field="vector_receipt_rights_manifest",
            )
        for field_name in ("authority_read_count", "fixture_vector_count"):
            _require_non_negative_int(getattr(self, field_name), field=field_name)
        if any(
            value != 0
            for value in (
                self.external_call_count,
                self.provider_call_count,
                self.model_call_count,
                self.embedding_call_count,
                self.provider_spend_micros,
            )
        ):
            raise VectorContractError("fixture/replay receipt cannot report external work or spend")
        if not self.replay_only:
            raise VectorContractError("5B3 vector receipt must remain replay-only")
        if self.qualification_authority_granted or self.production_activation_authorized:
            raise VectorContractError("5B3 receipt cannot grant qualification or activation authority")
        if len(self.hits) > VECTOR_RESULT_LIMIT:
            raise VectorContractError("vector receipt exceeds the result bound")
        if [hit.rank for hit in self.hits] != list(range(1, len(self.hits) + 1)):
            raise VectorContractError("vector hit ranks must be contiguous")
        if self.outcome is BranchOutcome.COMPLETE:
            if self.hits and self.reason is not None:
                raise VectorContractError("complete vector hits cannot carry a failure reason")
            if not self.hits and self.reason is not VectorFailureReason.NO_MATCH:
                raise VectorContractError("empty complete vector receipt must state NO_MATCH")
        elif self.hits:
            raise VectorContractError("non-complete vector receipt cannot retain ranked hits")
        if self.reason is VectorFailureReason.QUERY_TIMEOUT and self.elapsed_ms != VECTOR_TIMEOUT_MS:
            raise VectorContractError("query timeout must retain the exact 5000 ms bound")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.vector-branch-receipt.v1",
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "mode": self.mode.value,
            "outcome": self.outcome.value,
            "reason": None if self.reason is None else self.reason.value,
            "catalog_digest": self.catalog_digest,
            "generation_id": self.generation_id,
            "generation_digest": self.generation_digest,
            "profile_id": self.profile_id,
            "vector_component_digest": self.vector_component_digest,
            "embedding_component_digest": self.embedding_component_digest,
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "elapsed_ms": self.elapsed_ms,
            "watermark_seq": self.watermark_seq,
            "rights_manifest_digest": self.rights_manifest_digest,
            "hits": [hit.canonical_value() for hit in self.hits],
            "exclusions": [exclusion.canonical_value() for exclusion in self.exclusions],
            "authority_read_count": self.authority_read_count,
            "fixture_vector_count": self.fixture_vector_count,
            "external_call_count": self.external_call_count,
            "provider_call_count": self.provider_call_count,
            "model_call_count": self.model_call_count,
            "embedding_call_count": self.embedding_call_count,
            "provider_spend_micros": self.provider_spend_micros,
            "replay_only": self.replay_only,
            "qualification_authority_granted": self.qualification_authority_granted,
            "production_activation_authorized": self.production_activation_authorized,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, value: bytes) -> "VectorBranchReceipt":
        try:
            payload = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VectorJournalError("retained vector receipt is not canonical JSON") from exc
        if not isinstance(payload, dict):
            raise VectorJournalError("retained vector receipt root is not an object")
        expected_schema = payload.pop("schema_version", None)
        if expected_schema != "newsroom.increment5.vector-branch-receipt.v1":
            raise VectorJournalError("retained vector receipt schema is not accepted")
        try:
            hits = tuple(
                VectorBranchHit(
                    rank=item["rank"],
                    passage_id=item["passage_id"],
                    dependency_root_id=item["dependency_root_id"],
                    source_revision_id=item["source_revision_id"],
                    language=item["language"],
                    document_digest=item["document_digest"],
                    vector_digest=item["vector_digest"],
                    rights_digest=item["rights_digest"],
                    provenance_digest=item["provenance_digest"],
                    proof=ExactCosineProof(**item["proof"]),
                )
                for item in payload["hits"]
            )
            exclusions = tuple(
                VectorBranchExclusion(
                    passage_id=item["passage_id"],
                    reason=BranchExclusionReason(item["reason"]),
                )
                for item in payload["exclusions"]
            )
            receipt = cls(
                receipt_id=payload["receipt_id"],
                request_digest=payload["request_digest"],
                mode=BranchMode(payload["mode"]),
                outcome=BranchOutcome(payload["outcome"]),
                reason=(
                    None
                    if payload["reason"] is None
                    else VectorFailureReason(payload["reason"])
                ),
                catalog_digest=payload["catalog_digest"],
                generation_id=payload["generation_id"],
                generation_digest=payload["generation_digest"],
                profile_id=payload["profile_id"],
                vector_component_digest=payload["vector_component_digest"],
                embedding_component_digest=payload["embedding_component_digest"],
                query_id=payload["query_id"],
                query_digest=payload["query_digest"],
                query_valid_time=payload["query_valid_time"],
                serving_time=payload["serving_time"],
                elapsed_ms=payload["elapsed_ms"],
                watermark_seq=payload["watermark_seq"],
                rights_manifest_digest=payload["rights_manifest_digest"],
                hits=hits,
                exclusions=exclusions,
                authority_read_count=payload["authority_read_count"],
                fixture_vector_count=payload["fixture_vector_count"],
                external_call_count=payload["external_call_count"],
                provider_call_count=payload["provider_call_count"],
                model_call_count=payload["model_call_count"],
                embedding_call_count=payload["embedding_call_count"],
                provider_spend_micros=payload["provider_spend_micros"],
                replay_only=payload["replay_only"],
                qualification_authority_granted=payload[
                    "qualification_authority_granted"
                ],
                production_activation_authorized=payload[
                    "production_activation_authorized"
                ],
            )
        except (KeyError, TypeError, ValueError, VectorContractError) as exc:
            raise VectorJournalError("retained vector receipt is malformed") from exc
        if receipt.canonical_bytes != value:
            raise VectorJournalError("retained vector receipt bytes are not canonical")
        return receipt


@dataclass(frozen=True, slots=True)
class _RankEvidence:
    document: VectorFixtureDocument
    dot: Fraction
    query_norm: Fraction
    document_norm: Fraction

    @property
    def sign(self) -> int:
        return (self.dot > 0) - (self.dot < 0)

    def proof(self) -> ExactCosineProof:
        squared = Fraction(0, 1)
        if self.dot:
            squared = self.dot * self.dot / (self.query_norm * self.document_norm)
        return ExactCosineProof(
            sign=self.sign,
            dot_numerator=self.dot.numerator,
            dot_denominator=self.dot.denominator,
            query_norm_numerator=self.query_norm.numerator,
            query_norm_denominator=self.query_norm.denominator,
            document_norm_numerator=self.document_norm.numerator,
            document_norm_denominator=self.document_norm.denominator,
            squared_cosine_numerator=squared.numerator,
            squared_cosine_denominator=squared.denominator,
        )


def _compare_rank_evidence(left: _RankEvidence, right: _RankEvidence) -> int:
    if left.sign != right.sign:
        return -1 if left.sign > right.sign else 1
    if left.sign == 0:
        return (left.document.passage_id > right.document.passage_id) - (
            left.document.passage_id < right.document.passage_id
        )
    left_cross = left.dot * left.dot * right.document_norm
    right_cross = right.dot * right.dot * left.document_norm
    if left_cross != right_cross:
        if left.sign > 0:
            return -1 if left_cross > right_cross else 1
        return -1 if left_cross < right_cross else 1
    return (left.document.passage_id > right.document.passage_id) - (
        left.document.passage_id < right.document.passage_id
    )


def rank_fixture_documents(
    query: VectorFixtureQuery,
    documents: Iterable[VectorFixtureDocument],
) -> tuple[_RankEvidence, ...]:
    query_vector, _, _ = materialize_fixed_point_vector(query.source_vector)
    query_fractions = _vector_fraction_tuple(query_vector)
    query_norm = sum((component * component for component in query_fractions), Fraction())
    if not query_norm:
        raise VectorContractError("fixture query materialized to the zero vector")
    evidence: list[_RankEvidence] = []
    for document in documents:
        materialized, _, _ = materialize_fixed_point_vector(document.source_vector)
        fractions = _vector_fraction_tuple(materialized)
        document_norm = sum((component * component for component in fractions), Fraction())
        if not document_norm:
            raise VectorContractError("fixture document materialized to the zero vector")
        dot = sum(
            (left * right for left, right in zip(query_fractions, fractions, strict=True)),
            Fraction(),
        )
        evidence.append(
            _RankEvidence(
                document=document,
                dot=dot,
                query_norm=query_norm,
                document_norm=document_norm,
            )
        )
    return tuple(sorted(evidence, key=cmp_to_key(_compare_rank_evidence)))


class VectorReceiptJournal:
    """Immutable SQLite journal with production outside its write reservation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialization_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._initialization_lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS increment5_vector_receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    receipt_bytes BLOB NOT NULL,
                    receipt_digest TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )

    @staticmethod
    def _decode(
        *, request_digest: str, receipt_bytes: bytes, receipt_digest: str
    ) -> VectorBranchReceipt:
        _require_digest(request_digest, field="journal_request_digest")
        _require_digest(receipt_digest, field="journal_receipt_digest")
        if _digest_bytes(receipt_bytes) != receipt_digest:
            raise VectorJournalError("retained vector receipt digest does not match bytes")
        receipt = VectorBranchReceipt.from_canonical_bytes(receipt_bytes)
        if receipt.request_digest != request_digest:
            raise VectorJournalError("retained vector receipt request binding is inconsistent")
        return receipt

    def _read_existing(
        self, request: VectorBranchRequest
    ) -> VectorBranchReceipt | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT request_digest, receipt_bytes, receipt_digest
                    FROM increment5_vector_receipts
                    WHERE idempotency_key = ?
                    """,
                    (request.idempotency_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise VectorJournalError("vector receipt journal read failed") from exc
        if row is None:
            return None
        if row[0] != request.request_digest:
            raise VectorJournalError("vector idempotency key was reused for another request")
        return self._decode(
            request_digest=row[0],
            receipt_bytes=bytes(row[1]),
            receipt_digest=row[2],
        )

    def execute(
        self,
        request: VectorBranchRequest,
        producer: Callable[[], VectorBranchReceipt],
    ) -> VectorBranchReceipt:
        existing = self._read_existing(request)
        if existing is not None:
            return existing

        receipt = producer()
        if receipt.request_digest != request.request_digest:
            raise VectorJournalError("produced vector receipt does not bind the request")
        receipt_bytes = receipt.canonical_bytes
        if len(receipt_bytes) > request.response_limit_bytes:
            raise VectorJournalError("produced vector receipt exceeds the response limit")
        receipt_digest = _digest_bytes(receipt_bytes)

        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_digest, receipt_bytes, receipt_digest
                FROM increment5_vector_receipts
                WHERE idempotency_key = ?
                """,
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                connection.execute("ROLLBACK")
                if row[0] != request.request_digest:
                    raise VectorJournalError(
                        "vector idempotency key was concurrently reused for another request"
                    )
                return self._decode(
                    request_digest=row[0],
                    receipt_bytes=bytes(row[1]),
                    receipt_digest=row[2],
                )
            connection.execute(
                """
                INSERT INTO increment5_vector_receipts (
                    idempotency_key,
                    request_digest,
                    receipt_bytes,
                    receipt_digest
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    request.idempotency_key,
                    request.request_digest,
                    receipt_bytes,
                    receipt_digest,
                ),
            )
            connection.execute("COMMIT")
        except VectorJournalError:
            raise
        except sqlite3.Error as exc:
            try:
                connection.execute("ROLLBACK")
            except (sqlite3.Error, UnboundLocalError):
                pass
            raise VectorJournalError("vector receipt journal write failed") from exc
        finally:
            try:
                connection.close()
            except UnboundLocalError:
                pass
        return receipt


class VectorFixtureRetriever:
    """Bounded deterministic fixture/replay VECTOR branch."""

    def __init__(
        self,
        *,
        catalog: VectorFixtureCatalog,
        authority_provider: Callable[[VectorBranchRequest], VectorAuthorityView],
        journal: VectorReceiptJournal,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.catalog = catalog
        self.authority_provider = authority_provider
        self.journal = journal
        self.monotonic_ns = monotonic_ns

    def retrieve(self, request: VectorBranchRequest) -> VectorBranchReceipt:
        return self.journal.execute(request, lambda: self._produce(request))

    def _produce(self, request: VectorBranchRequest) -> VectorBranchReceipt:
        started = self.monotonic_ns()
        deadline = started + VECTOR_TIMEOUT_MS * 1_000_000

        def elapsed_ms() -> int:
            current = self.monotonic_ns()
            if current >= deadline:
                return VECTOR_TIMEOUT_MS
            return max(0, (current - started) // 1_000_000)

        def timed_out() -> bool:
            return self.monotonic_ns() >= deadline

        query = self.catalog.query(request.query_id)
        if request.actor_id != VECTOR_ACTOR_ID or request.purpose != VECTOR_PURPOSE:
            return self._failure(
                request,
                BranchOutcome.POLICY_BLOCKED,
                VectorFailureReason.CONTRACT_MISMATCH,
                elapsed_ms=elapsed_ms(),
            )
        if request.policy_id != VECTOR_POLICY_ID or request.contract_digest != RETRIEVAL_CONTRACT_DIGEST:
            return self._failure(
                request,
                BranchOutcome.POLICY_BLOCKED,
                VectorFailureReason.CONTRACT_MISMATCH,
                elapsed_ms=elapsed_ms(),
            )
        if request.profile_id != VECTOR_PROFILE_ID:
            return self._failure(
                request,
                BranchOutcome.POLICY_BLOCKED,
                VectorFailureReason.PROFILE_MISMATCH,
                elapsed_ms=elapsed_ms(),
            )
        if request.vector_component_digest != VECTOR_COMPONENT_DIGEST:
            return self._failure(
                request,
                BranchOutcome.POLICY_BLOCKED,
                VectorFailureReason.VECTOR_COMPONENT_MISMATCH,
                elapsed_ms=elapsed_ms(),
            )
        if request.embedding_component_digest != EMBEDDING_COMPONENT_DIGEST:
            return self._failure(
                request,
                BranchOutcome.POLICY_BLOCKED,
                VectorFailureReason.EMBEDDING_COMPONENT_MISMATCH,
                elapsed_ms=elapsed_ms(),
            )
        if request.catalog_digest != self.catalog.catalog_digest:
            return self._failure(
                request,
                BranchOutcome.POLICY_BLOCKED,
                VectorFailureReason.CATALOG_MISMATCH,
                elapsed_ms=elapsed_ms(),
            )
        if query is None:
            return self._failure(
                request,
                BranchOutcome.POLICY_BLOCKED,
                VectorFailureReason.QUERY_UNKNOWN,
                elapsed_ms=elapsed_ms(),
            )
        if request.query_digest != query.query_digest:
            return self._failure(
                request,
                BranchOutcome.POLICY_BLOCKED,
                VectorFailureReason.QUERY_DIGEST_MISMATCH,
                elapsed_ms=elapsed_ms(),
            )
        if timed_out():
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.QUERY_TIMEOUT,
                elapsed_ms=VECTOR_TIMEOUT_MS,
            )

        try:
            view = self.authority_provider(request)
        except Exception:
            return self._failure(
                request,
                BranchOutcome.UNAVAILABLE,
                VectorFailureReason.AUTHORITY_VIEW_UNAVAILABLE,
                elapsed_ms=elapsed_ms(),
            )
        if not isinstance(view, VectorAuthorityView):
            return self._failure(
                request,
                BranchOutcome.UNAVAILABLE,
                VectorFailureReason.AUTHORITY_VIEW_UNAVAILABLE,
                elapsed_ms=elapsed_ms(),
            )
        if timed_out():
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.QUERY_TIMEOUT,
                elapsed_ms=VECTOR_TIMEOUT_MS,
                view=view,
            )
        if not view.active:
            return self._failure(
                request,
                BranchOutcome.STALE,
                VectorFailureReason.GENERATION_INACTIVE,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        if not view.complete:
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.GENERATION_INCOMPLETE,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        if view.catalog_digest != self.catalog.catalog_digest:
            return self._failure(
                request,
                BranchOutcome.STALE,
                VectorFailureReason.GENERATION_IDENTITY_MISMATCH,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        if view.profile_id != VECTOR_PROFILE_ID:
            return self._failure(
                request,
                BranchOutcome.STALE,
                VectorFailureReason.PROFILE_MISMATCH,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        if view.vector_component_digest != VECTOR_COMPONENT_DIGEST:
            return self._failure(
                request,
                BranchOutcome.STALE,
                VectorFailureReason.VECTOR_COMPONENT_MISMATCH,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        if view.embedding_component_digest != EMBEDDING_COMPONENT_DIGEST:
            return self._failure(
                request,
                BranchOutcome.STALE,
                VectorFailureReason.EMBEDDING_COMPONENT_MISMATCH,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        if view.watermark_seq < request.minimum_watermark_seq:
            return self._failure(
                request,
                BranchOutcome.STALE,
                VectorFailureReason.WATERMARK_BEHIND,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        if view.open_gap_count:
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.REQUIRED_GAP_OPEN,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        if view.dead_letter_count:
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.DEAD_LETTER_PRESENT,
                elapsed_ms=elapsed_ms(),
                view=view,
            )
        serving = _parse_utc(request.serving_time, field="vector_serving_time")
        validated = _parse_utc(view.validated_at, field="vector_validated_at")
        if serving < validated or (serving - validated).total_seconds() > view.maximum_age_seconds:
            return self._failure(
                request,
                BranchOutcome.STALE,
                VectorFailureReason.AUTHORITY_VIEW_STALE,
                elapsed_ms=elapsed_ms(),
                view=view,
            )

        binding_by_passage = {binding.passage_id: binding for binding in view.bindings}
        selected = [
            document for document in self.catalog.documents if request.query_id in document.query_ids
        ]
        exclusions: list[VectorBranchExclusion] = []
        eligible: list[VectorFixtureDocument] = []
        query_valid = _parse_utc(request.query_valid_time, field="vector_query_valid_time")
        for document in selected:
            binding = binding_by_passage.get(document.passage_id)
            if binding is None:
                return self._failure(
                    request,
                    BranchOutcome.INCOMPLETE,
                    VectorFailureReason.PASSAGE_BINDING_MISSING,
                    elapsed_ms=elapsed_ms(),
                    view=view,
                    exclusions=tuple(exclusions),
                )
            if (
                binding.dependency_root_id != document.dependency_root_id
                or binding.source_revision_id != document.source_revision_id
                or binding.document_digest != document.document_digest
                or binding.provenance_digest != document.provenance_digest
            ):
                return self._failure(
                    request,
                    BranchOutcome.UNAVAILABLE,
                    VectorFailureReason.PASSAGE_BINDING_INTEGRITY,
                    elapsed_ms=elapsed_ms(),
                    view=view,
                    exclusions=tuple(exclusions),
                )
            if binding.rights_digest != document.rights_digest:
                return self._failure(
                    request,
                    BranchOutcome.UNAVAILABLE,
                    VectorFailureReason.RIGHTS_MANIFEST_MISMATCH,
                    elapsed_ms=elapsed_ms(),
                    view=view,
                    exclusions=tuple(exclusions),
                )
            if not binding.rights_current:
                exclusions.append(
                    VectorBranchExclusion(
                        passage_id=document.passage_id,
                        reason=BranchExclusionReason.RIGHTS_NOT_CURRENT,
                    )
                )
                continue
            if binding.lifecycle is not PassageLifecycle.ACTIVE:
                reason = (
                    BranchExclusionReason.TOMBSTONED
                    if binding.lifecycle is PassageLifecycle.TOMBSTONED
                    else BranchExclusionReason.STALE_SOURCE_VERSION
                )
                exclusions.append(
                    VectorBranchExclusion(passage_id=document.passage_id, reason=reason)
                )
                continue
            if not (
                _parse_utc(document.valid_from, field="fixture_valid_from")
                <= query_valid
                < _parse_utc(document.valid_to, field="fixture_valid_to")
            ):
                exclusions.append(
                    VectorBranchExclusion(
                        passage_id=document.passage_id,
                        reason=BranchExclusionReason.OUTSIDE_QUERY_VALID_TIME,
                    )
                )
                continue
            eligible.append(document)

        if timed_out():
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.QUERY_TIMEOUT,
                elapsed_ms=VECTOR_TIMEOUT_MS,
                view=view,
                exclusions=tuple(exclusions),
            )
        if len(eligible) > VECTOR_RESULT_LIMIT:
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.RESULT_LIMIT_EXCEEDED,
                elapsed_ms=elapsed_ms(),
                view=view,
                exclusions=tuple(exclusions),
                fixture_vector_count=VECTOR_RESULT_LIMIT + 1,
            )
        try:
            ranked = rank_fixture_documents(query, eligible)
        except VectorContractError:
            return self._failure(
                request,
                BranchOutcome.UNAVAILABLE,
                VectorFailureReason.FIXTURE_INTEGRITY_ERROR,
                elapsed_ms=elapsed_ms(),
                view=view,
                exclusions=tuple(exclusions),
            )
        if timed_out():
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.QUERY_TIMEOUT,
                elapsed_ms=VECTOR_TIMEOUT_MS,
                view=view,
                exclusions=tuple(exclusions),
                fixture_vector_count=len(eligible),
            )
        hits = tuple(
            VectorBranchHit(
                rank=index,
                passage_id=evidence.document.passage_id,
                dependency_root_id=evidence.document.dependency_root_id,
                source_revision_id=evidence.document.source_revision_id,
                language=evidence.document.language,
                document_digest=evidence.document.document_digest,
                vector_digest=evidence.document.vector_digest,
                rights_digest=evidence.document.rights_digest,
                provenance_digest=evidence.document.provenance_digest,
                proof=evidence.proof(),
            )
            for index, evidence in enumerate(ranked, start=1)
        )
        receipt = self._receipt(
            request,
            outcome=BranchOutcome.COMPLETE,
            reason=None if hits else VectorFailureReason.NO_MATCH,
            elapsed_ms=elapsed_ms(),
            view=view,
            hits=hits,
            exclusions=tuple(exclusions),
            fixture_vector_count=len(eligible),
        )
        if len(receipt.canonical_bytes) > request.response_limit_bytes:
            return self._failure(
                request,
                BranchOutcome.INCOMPLETE,
                VectorFailureReason.RESPONSE_LIMIT_EXCEEDED,
                elapsed_ms=elapsed_ms(),
                view=view,
                exclusions=tuple(exclusions),
                fixture_vector_count=len(eligible),
            )
        return receipt

    @staticmethod
    def _receipt_id(
        request: VectorBranchRequest,
        *,
        outcome: BranchOutcome,
        reason: VectorFailureReason | None,
        generation_digest: str | None,
    ) -> str:
        material = "|".join(
            (
                request.request_digest,
                outcome.value,
                "NONE" if reason is None else reason.value,
                generation_digest or "NO_GENERATION",
            )
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, material))

    def _receipt(
        self,
        request: VectorBranchRequest,
        *,
        outcome: BranchOutcome,
        reason: VectorFailureReason | None,
        elapsed_ms: int,
        view: VectorAuthorityView | None = None,
        hits: tuple[VectorBranchHit, ...] = (),
        exclusions: tuple[VectorBranchExclusion, ...] = (),
        fixture_vector_count: int = 0,
    ) -> VectorBranchReceipt:
        return VectorBranchReceipt(
            receipt_id=self._receipt_id(
                request,
                outcome=outcome,
                reason=reason,
                generation_digest=None if view is None else view.generation_digest,
            ),
            request_digest=request.request_digest,
            mode=BranchMode.VECTOR,
            outcome=outcome,
            reason=reason,
            catalog_digest=self.catalog.catalog_digest,
            generation_id=None if view is None else view.generation_id,
            generation_digest=None if view is None else view.generation_digest,
            profile_id=VECTOR_PROFILE_ID,
            vector_component_digest=VECTOR_COMPONENT_DIGEST,
            embedding_component_digest=EMBEDDING_COMPONENT_DIGEST,
            query_id=request.query_id,
            query_digest=request.query_digest,
            query_valid_time=request.query_valid_time,
            serving_time=request.serving_time,
            elapsed_ms=elapsed_ms,
            watermark_seq=None if view is None else view.watermark_seq,
            rights_manifest_digest=(
                None if view is None else view.rights_manifest_digest
            ),
            hits=hits,
            exclusions=exclusions,
            authority_read_count=0 if view is None else 1,
            fixture_vector_count=fixture_vector_count,
        )

    def _failure(
        self,
        request: VectorBranchRequest,
        outcome: BranchOutcome,
        reason: VectorFailureReason,
        *,
        elapsed_ms: int,
        view: VectorAuthorityView | None = None,
        exclusions: tuple[VectorBranchExclusion, ...] = (),
        fixture_vector_count: int = 0,
    ) -> VectorBranchReceipt:
        return self._receipt(
            request,
            outcome=outcome,
            reason=reason,
            elapsed_ms=elapsed_ms,
            view=view,
            hits=(),
            exclusions=exclusions,
            fixture_vector_count=fixture_vector_count,
        )


__all__ = [
    "EMBEDDING_COMPONENT_DIGEST",
    "RETRIEVAL_CONTRACT_DIGEST",
    "VECTOR_ACTOR_ID",
    "VECTOR_COMPONENT_DIGEST",
    "VECTOR_COMPONENT_SCALE",
    "VECTOR_EMBEDDING_CALLS",
    "VECTOR_EXTERNAL_CALLS",
    "VECTOR_MATERIALIZED_BYTES",
    "VECTOR_MODEL_CALLS",
    "VECTOR_OUTPUT_DIMENSIONS",
    "VECTOR_POLICY_ID",
    "VECTOR_PROFILE_ID",
    "VECTOR_PROVIDER_CALLS",
    "VECTOR_PROVIDER_ID",
    "VECTOR_PROVIDER_SPEND_MICROS",
    "VECTOR_PURPOSE",
    "VECTOR_RESPONSE_LIMIT_BYTES",
    "VECTOR_RESULT_LIMIT",
    "VECTOR_SOURCE_DIMENSIONS",
    "VECTOR_TIMEOUT_MS",
    "ExactCosineProof",
    "PassageLifecycle",
    "VectorAuthorityBinding",
    "VectorAuthorityView",
    "VectorBranchExclusion",
    "VectorBranchHit",
    "VectorBranchReceipt",
    "VectorBranchRequest",
    "VectorContractError",
    "VectorFailureReason",
    "VectorFixtureCatalog",
    "VectorFixtureDocument",
    "VectorFixtureQuery",
    "VectorFixtureRetriever",
    "VectorJournalError",
    "VectorReceiptJournal",
    "materialize_fixed_point_vector",
    "rank_fixture_documents",
]
