"""Shared validation helpers for independent Increment 5B branch contracts."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, validate_sha256_digest


_SCORE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,20})?(?:e-?[0-9]{1,3})?$")


class Increment5RetrievalContractError(ValueError):
    """A typed Increment 5B request, hit, receipt, or policy is malformed."""


class Increment5RetrievalStateError(RuntimeError):
    """Current state cannot safely produce the requested branch result."""


def bounded_text(
    value: object,
    *,
    field: str,
    maximum_bytes: int = 4096,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise Increment5RetrievalContractError(f"{field} must be text")
    if value != value.strip() or "\x00" in value:
        raise Increment5RetrievalContractError(f"{field} must be canonical text")
    if not allow_empty and not value:
        raise Increment5RetrievalContractError(f"{field} cannot be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise Increment5RetrievalContractError(f"{field} exceeds its byte bound")
    return value


def bounded_int(
    value: object,
    *,
    field: str,
    minimum: int = 0,
    maximum: int = 2**63 - 1,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Increment5RetrievalContractError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise Increment5RetrievalContractError(f"{field} is outside its fixed bound")
    return value


def require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise Increment5RetrievalContractError(f"{field} must be boolean")
    return value


def require_digest(value: object, *, field: str) -> str:
    try:
        return validate_sha256_digest(str(value), field=field)
    except (TypeError, ValueError) as exc:
        raise Increment5RetrievalContractError(
            f"{field} must use canonical sha256:<hex> text"
        ) from exc


def sorted_unique_text(
    value: object,
    *,
    field: str,
    allow_empty: bool = False,
    maximum_items: int = 64,
    maximum_item_bytes: int = 256,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise Increment5RetrievalContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not value:
        raise Increment5RetrievalContractError(f"{field} cannot be empty")
    if len(value) > maximum_items:
        raise Increment5RetrievalContractError(f"{field} exceeds its item bound")
    result = tuple(
        bounded_text(item, field=field, maximum_bytes=maximum_item_bytes)
        for item in value
    )
    if result != tuple(sorted(set(result))):
        raise Increment5RetrievalContractError(f"{field} must be sorted and unique")
    return result


def canonical_score(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Increment5RetrievalContractError("branch score must be numeric")
    score = float(value)
    if not math.isfinite(score):
        raise Increment5RetrievalContractError("branch score must be finite")
    text = format(score, ".17g").lower().replace("e+", "e")
    if _SCORE.fullmatch(text) is None:
        raise Increment5RetrievalContractError("branch score is not canonical")
    return text


def validate_canonical_score(value: object) -> str:
    if not isinstance(value, str) or _SCORE.fullmatch(value) is None:
        raise Increment5RetrievalContractError("branch score text is not canonical")
    parsed = float(value)
    if not math.isfinite(parsed) or canonical_score(parsed) != value:
        raise Increment5RetrievalContractError("branch score text is not canonical")
    return value


def without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise Increment5RetrievalContractError(f"duplicate object name: {name}")
        result[name] = value
    return result


def parse_canonical_json_object(raw: bytes, *, field: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw:
        raise Increment5RetrievalContractError(f"{field} bytes are required")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=without_duplicate_names,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5RetrievalContractError(f"{field} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise Increment5RetrievalContractError(f"{field} root must be an object")
    if canonical_json_bytes(value) != raw:
        raise Increment5RetrievalContractError(f"{field} must use canonical JSON")
    return value


def require_mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment5RetrievalContractError(f"{field} must be an object")
    return value


def require_sequence(value: object, *, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        raise Increment5RetrievalContractError(f"{field} must be an array")
    return value


__all__ = [
    "Increment5RetrievalContractError",
    "Increment5RetrievalStateError",
    "bounded_int",
    "bounded_text",
    "canonical_score",
    "parse_canonical_json_object",
    "require_bool",
    "require_digest",
    "require_mapping",
    "require_sequence",
    "sorted_unique_text",
    "validate_canonical_score",
]
