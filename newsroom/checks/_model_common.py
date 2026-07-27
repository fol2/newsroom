from __future__ import annotations

from typing import Protocol

from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.sources import SourceDefinitionId, SourceDefinitionVersionId

from .types import (
    CheckContractError,
    canonical_digest,
    require_uuid_text,
)


class DigestRequest(Protocol):
    @property
    def digest(self) -> str: ...


def require_idempotency_key(value: str) -> str:
    from .types import bounded_text

    bounded_text(
        value,
        field="check_idempotency_key",
        maximum_bytes=256,
    )
    return value


def require_source_identity(
    definition_id: SourceDefinitionId,
    version_id: SourceDefinitionVersionId,
    *,
    identity: str,
) -> None:
    if not isinstance(definition_id, SourceDefinitionId):
        raise CheckContractError(f"{identity} source definition must be typed")
    if not isinstance(version_id, SourceDefinitionVersionId):
        raise CheckContractError(f"{identity} source version must be typed")


def optional_digest(value: str | None, *, field: str) -> None:
    if value is not None:
        canonical_digest(value, field=field)


def optional_uuid(value: object | None, expected: type, *, field: str) -> None:
    if value is not None and not isinstance(value, expected):
        raise CheckContractError(f"{field} must be a typed identifier")


def require_scope_uuid(value: str, *, field: str) -> str:
    return require_uuid_text(value, field=field)


def validate_committed(
    *,
    request: DigestRequest,
    event_id: EventId,
    aggregate_version: int,
    recorded_at: UtcTimestamp,
    record_digest: str,
    replayed: bool,
) -> None:
    if not isinstance(event_id, EventId):
        raise CheckContractError("Check authority event identity must be typed")
    if (
        isinstance(aggregate_version, bool)
        or not isinstance(aggregate_version, int)
        or aggregate_version != 1
    ):
        raise CheckContractError(
            "immutable Check records must have aggregate version one"
        )
    if not isinstance(recorded_at, UtcTimestamp):
        raise CheckContractError("Check recording time must be typed")
    canonical_digest(record_digest, field="check_record_digest")
    if record_digest != request.digest:
        raise CheckContractError("Check record digest differs from request")
    if not isinstance(replayed, bool):
        raise CheckContractError("Check replay flag must be boolean")


__all__ = [
    "DigestRequest",
    "optional_digest",
    "optional_uuid",
    "require_idempotency_key",
    "require_scope_uuid",
    "require_source_identity",
    "validate_committed",
]
