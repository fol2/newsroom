"""Untrusted response decoding and exact raw-output receipts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from newsroom.authority.canonical import (
    CanonicalizationError,
    digest_bytes,
    digest_canonical,
)
from newsroom.graphiti_adapter.combined_temporal_types import (
    CombinedTemporalError,
    CombinedTemporalFailureCode,
)


def raw_digest(raw: object) -> str:
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


def parse_payload(raw: object) -> dict[str, Any]:
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


__all__ = ["parse_payload", "raw_digest"]
