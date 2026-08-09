"""Shared primitives for the bounded Increment 5E1 qualification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes


class RetrievalQualificationError(ValueError):
    """Frozen qualification input or retained evidence is inconsistent."""


class QualificationSystem(StrEnum):
    ADMITTED_GRAPH_ONLY = "ADMITTED_GRAPH_ONLY"
    EXACT_ONLY = "EXACT_ONLY"
    FULL_TEXT_ONLY = "FULL_TEXT_ONLY"
    HYBRID = "HYBRID"
    VECTOR_ONLY = "VECTOR_ONLY"


class QualificationMode(StrEnum):
    EXACT = "EXACT"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"
    ADMITTED_GRAPH = "ADMITTED_GRAPH"


class QualificationOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class QualificationDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


SYSTEM_ORDER = tuple(QualificationSystem)
MODE_ORDER = tuple(QualificationMode)
RESULT_LIMIT = 12
RRF_K = 60
PPM = 1_000_000

DATA_ROOT = Path(__file__).resolve().parent / "data"
TARGET_SPEC_PATH = DATA_ROOT / "increment5_retrieval_qualification_target_v1.json"
CORPUS_SPEC_PATH = DATA_ROOT / "increment5_retrieval_qualification_corpus_v1.json"
TARGET_SPEC_DIGEST = (
    "sha256:fd88328d9ed74573a9b0aa2e7900dc437a7f8a4963c96da59869b9dddbad7271"
)
CORPUS_SPEC_DIGEST = (
    "sha256:07f5f0cceb26c0744aadd6feacb056aa09503b0552ec1223a4f3228af6fbeb70"
)

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TREE_RE = re.compile(r"[0-9a-f]{40}\Z")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


def digest(value: object) -> str:
    return digest_bytes(canonical_json_bytes(value))


def require_token(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise RetrievalQualificationError(f"{field} must be a bounded token")
    return value


def require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise RetrievalQualificationError(f"{field} must be a SHA-256 digest")
    return value


def require_uint(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RetrievalQualificationError(f"{field} must be non-negative")
    return value


def parse_utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise RetrievalQualificationError(f"{field} must be canonical UTC")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise RetrievalQualificationError(f"{field} must be canonical UTC") from exc


def require_tree_sha(value: object, *, field: str = "code_tree_sha") -> str:
    if not isinstance(value, str) or _TREE_RE.fullmatch(value) is None:
        raise RetrievalQualificationError(f"{field} must be a Git tree SHA")
    return value


def canonical_text_tuple(
    values: Sequence[object],
    *,
    field: str,
    required: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise RetrievalQualificationError(f"{field} must be a sequence")
    result = tuple(require_token(value, field=field) for value in values)
    if result != tuple(sorted(set(result))) or (required and not result):
        raise RetrievalQualificationError(f"{field} must be sorted and unique")
    return result


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RetrievalQualificationError(f"duplicate JSON name: {key}")
        result[key] = value
    return result


def read_frozen_spec(
    path: Path,
    *,
    expected_digest: str,
    field: str,
) -> Mapping[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RetrievalQualificationError(f"cannot read frozen {field}") from exc
    if (
        not isinstance(value, dict)
        or canonical_json_bytes(value) != raw
        or digest_bytes(raw) != expected_digest
    ):
        raise RetrievalQualificationError(f"frozen {field} differs from reviewed v1")
    return freeze(value)


TARGET_SPEC = read_frozen_spec(
    TARGET_SPEC_PATH,
    expected_digest=TARGET_SPEC_DIGEST,
    field="qualification target",
)
CORPUS_SPEC = read_frozen_spec(
    CORPUS_SPEC_PATH,
    expected_digest=CORPUS_SPEC_DIGEST,
    field="qualification corpus",
)
