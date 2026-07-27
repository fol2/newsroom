from __future__ import annotations

from typing import Any

from newsroom.authority.canonical import validate_sha256_digest
from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.authority.types import UUIDv4Id, UtcTimestamp, require_token
from newsroom.sources import SourceTime, VersionedPolicyRef

from .types import CheckContractError


def error(message: str) -> PayloadSchemaValidationError:
    return PayloadSchemaValidationError(message)


def exact(
    value: Any,
    *,
    fields: frozenset[str],
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise error(f"{name} payload fields differ from retained schema")
    return value


def uuid_text(
    value: Any,
    *,
    field: str,
    optional: bool = False,
) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise error(f"{field} must be canonical UUID text")
    try:
        UUIDv4Id.parse(value)
    except ValueError as exc:
        raise error(f"{field} must be canonical UUIDv4") from exc
    return value


def token(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise error(f"{field} must be a token")
    try:
        require_token(value, field=field)
    except ValueError as exc:
        raise error(f"{field} must be a token") from exc
    return value


def text(
    value: Any,
    *,
    field: str,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or "\x00" in value
        or (not allow_empty and not value)
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise error(f"{field} must be bounded canonical text")
    return value


def digest(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise error(f"{field} must be a sha256 digest")
    try:
        normalized = validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise error(f"{field} must be a sha256 digest") from exc
    if normalized != value:
        raise error(f"{field} must use canonical lowercase text")
    return value


def enum_value(value: Any, *, enum_type: type, field: str) -> str:
    if not isinstance(value, str):
        raise error(f"{field} must be an allow-listed string")
    try:
        enum_type(value)
    except ValueError as exc:
        raise error(f"{field} is not allow-listed") from exc
    return value


def boolean(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise error(f"{field} must be boolean")
    return value


def integer(
    value: Any,
    *,
    field: str,
    minimum: int = 0,
    maximum: int = 2_147_483_647,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise error(f"{field} is outside its integer bound")
    return value


def strings(
    value: Any,
    *,
    field: str,
    maximum_items: int = 64,
    maximum_item_bytes: int = 1024,
    allow_empty: bool = False,
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or len(value) > maximum_items
        or any(not isinstance(item, str) for item in value)
    ):
        raise error(f"{field} must be a bounded string list")
    result = [
        text(
            item,
            field=field,
            maximum_bytes=maximum_item_bytes,
        )
        for item in value
    ]
    if result != sorted(set(result)):
        raise error(f"{field} must be sorted and unique")
    return result


def policy_ref(value: Any, *, field: str) -> VersionedPolicyRef:
    item = exact(
        value,
        fields=frozenset({"policy_id", "policy_version"}),
        name=field,
    )
    try:
        return VersionedPolicyRef(
            policy_id=token(item["policy_id"], field=f"{field}.policy_id"),
            policy_version=token(
                item["policy_version"],
                field=f"{field}.policy_version",
            ),
        )
    except CheckContractError as exc:
        raise error(f"{field} is invalid") from exc


def timestamp(value: Any, *, field: str) -> UtcTimestamp:
    selected = text(value, field=field, maximum_bytes=64)
    try:
        parsed = UtcTimestamp.parse(selected)
    except ValueError as exc:
        raise error(f"{field} must be a UTC timestamp") from exc
    if parsed.to_text() != selected:
        raise error(f"{field} must use canonical UTC text")
    return parsed


def source_time(value: Any, *, field: str) -> SourceTime:
    item = exact(
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
        raise error(f"{field}.precision is not allow-listed")
    alternatives = strings(
        item["conflicting_values"],
        field=f"{field}.conflicting_values",
        maximum_items=8,
        maximum_item_bytes=128,
        allow_empty=True,
    )
    selected = item["value"]
    if precision == "UNKNOWN":
        if selected is not None or alternatives:
            raise error(f"{field} UNKNOWN cannot carry values")
    elif precision == "CONFLICTING":
        if selected is not None or len(alternatives) < 2:
            raise error(f"{field} CONFLICTING requires alternatives")
    else:
        text(selected, field=f"{field}.value", maximum_bytes=128)
        if alternatives:
            raise error(f"{field} non-conflicting time has alternatives")
    try:
        return SourceTime(
            precision=precision,
            value=selected,
            conflicting_values=tuple(alternatives),
        )
    except (TypeError, ValueError) as exc:
        raise error(f"{field} is invalid") from exc


__all__ = [
    "boolean",
    "digest",
    "enum_value",
    "error",
    "exact",
    "integer",
    "policy_ref",
    "source_time",
    "strings",
    "text",
    "timestamp",
    "token",
    "uuid_text",
]
