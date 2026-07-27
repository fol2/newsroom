from __future__ import annotations

from urllib.parse import urlsplit

from newsroom.authority.types import UtcTimestamp

from .types import (
    SourceContractError,
    SourceTime,
    VersionedPolicyRef,
    bounded_text,
)


def require_idempotency_key(value: str) -> str:
    return bounded_text(value, field="idempotency_key", maximum_bytes=256)


def require_locator(value: str, *, field: str = "locator") -> str:
    bounded_text(value, field=field, maximum_bytes=8192)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SourceContractError(f"{field} contains control characters")
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"}:
        if not parsed.netloc:
            raise SourceContractError(f"{field} HTTP locator requires an authority")
        if parsed.username is not None or parsed.password is not None:
            raise SourceContractError(f"{field} cannot embed credentials")
        if parsed.fragment:
            raise SourceContractError(f"{field} cannot use a fragment as identity")
    return value


def require_versioned_ref(
    value: VersionedPolicyRef, *, field: str
) -> VersionedPolicyRef:
    if not isinstance(value, VersionedPolicyRef):
        raise SourceContractError(f"{field} must be a versioned policy reference")
    return value


def require_source_time(value: SourceTime, *, field: str) -> SourceTime:
    if not isinstance(value, SourceTime):
        raise SourceContractError(f"{field} must be typed source time")
    return value


def require_utc(value: UtcTimestamp, *, field: str) -> UtcTimestamp:
    if not isinstance(value, UtcTimestamp):
        raise SourceContractError(f"{field} must be typed UTC")
    return value


__all__ = [
    "require_idempotency_key",
    "require_locator",
    "require_source_time",
    "require_utc",
    "require_versioned_ref",
]
