from __future__ import annotations

from typing import Any

from newsroom.authority.canonical import validate_sha256_digest
from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.authority.types import UUIDv4Id, require_scope, require_token


def _error(message: str) -> PayloadSchemaValidationError:
    return PayloadSchemaValidationError(message)


def _exact(value: Any, *, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise _error(f"{name} payload fields differ from retained schema")
    return value


def _uuid(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise _error(f"{field} must be canonical UUID text")
    try:
        UUIDv4Id.parse(value)
    except ValueError as exc:
        raise _error(f"{field} must be canonical UUIDv4") from exc
    return value


def _token(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise _error(f"{field} must be a token")
    try:
        require_token(value, field=field)
    except ValueError as exc:
        raise _error(f"{field} must be a token") from exc
    return value


def _scope(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise _error(f"{field} must be a scope")
    try:
        require_scope(value, field=field)
    except ValueError as exc:
        raise _error(f"{field} must be a scope") from exc
    return value


def _text(
    value: Any,
    *,
    field: str,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or (not allow_empty and not value)
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise _error(f"{field} must be bounded canonical text")
    return value


def _digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise _error(f"{field} must be a sha256 digest")
    try:
        normalized = validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise _error(f"{field} must be a sha256 digest") from exc
    if normalized != value:
        raise _error(f"{field} must use canonical lowercase text")
    return value


def _enum(value: Any, *, enum_type: type, field: str) -> str:
    if not isinstance(value, str):
        raise _error(f"{field} must be an allow-listed string")
    try:
        enum_type(value)
    except ValueError as exc:
        raise _error(f"{field} is not allow-listed") from exc
    return value


def _strings(
    value: Any,
    *,
    field: str,
    maximum_items: int = 64,
    allow_empty: bool = False,
    maximum_item_bytes: int = 1024,
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or len(value) > maximum_items
        or any(not isinstance(item, str) for item in value)
    ):
        raise _error(f"{field} must be a bounded string list")
    items = [
        _text(
            item,
            field=field,
            maximum_bytes=maximum_item_bytes,
        )
        for item in value
    ]
    if items != sorted(set(items)):
        raise _error(f"{field} must be sorted and unique")
    return items


def _policy_ref(value: Any, *, field: str) -> dict[str, Any]:
    item = _exact(
        value,
        fields=frozenset({"policy_id", "policy_version"}),
        name=field,
    )
    _token(item["policy_id"], field=f"{field}.policy_id")
    _token(item["policy_version"], field=f"{field}.policy_version")
    return item


def _source_time(value: Any, *, field: str) -> dict[str, Any]:
    item = _exact(
        value,
        fields=frozenset({"precision", "value", "conflicting_values"}),
        name=field,
    )
    precision = item["precision"]
    if precision not in {
        "EXACT",
        "DATE_ONLY",
        "APPROXIMATE",
        "UNKNOWN",
        "CONFLICTING",
    }:
        raise _error(f"{field}.precision is not allow-listed")
    alternatives = item["conflicting_values"]
    if not isinstance(alternatives, list) or len(alternatives) > 8:
        raise _error(f"{field}.conflicting_values must be bounded")
    if any(not isinstance(entry, str) for entry in alternatives):
        raise _error(f"{field}.conflicting_values must be text")
    if alternatives != sorted(set(alternatives)):
        raise _error(f"{field}.conflicting_values must be sorted and unique")
    if precision == "UNKNOWN":
        if item["value"] is not None or alternatives:
            raise _error(f"{field} UNKNOWN cannot carry values")
    elif precision == "CONFLICTING":
        if item["value"] is not None or len(alternatives) < 2:
            raise _error(f"{field} CONFLICTING requires alternatives")
    else:
        _text(item["value"], field=f"{field}.value", maximum_bytes=128)
        if alternatives:
            raise _error(f"{field} non-conflicting time has alternatives")
    return item


__all__ = [
    "_digest",
    "_enum",
    "_error",
    "_exact",
    "_policy_ref",
    "_scope",
    "_source_time",
    "_strings",
    "_text",
    "_token",
    "_uuid",
]
