from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, RFC_4122, uuid4


class AuthorityTypeError(ValueError):
    """Raised when a typed authority value is invalid."""


@dataclass(frozen=True, slots=True)
class UUIDv4Id:
    """Base for opaque typed identifiers.

    UUIDv4 supplies identity only. It carries no ordering or causality; callers
    must use ledger sequence and explicit temporal fields for those meanings.
    Equality remains type-sensitive because distinct authority domains must not
    become interchangeable merely because their UUID bytes match.
    """

    value: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.value, UUID):
            raise AuthorityTypeError("typed identifier value must be a UUID")
        if self.value.version != 4 or self.value.variant != RFC_4122:
            raise AuthorityTypeError("typed identifiers must be RFC 9562 UUIDv4 values")

    @classmethod
    def new(cls) -> Self:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> Self:
        if not isinstance(value, str) or value != value.strip().lower():
            raise AuthorityTypeError("identifier must be lowercase canonical UUID text")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as exc:
            raise AuthorityTypeError("identifier is not valid UUID text") from exc
        if str(parsed) != value:
            raise AuthorityTypeError("identifier must use canonical hyphenated UUID text")
        return cls(parsed)

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CommandId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class EventId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class AuditId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class AggregateId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class AuthenticationContextId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class AuthorizationDecisionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class AggregateVersion:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise AuthorityTypeError("aggregate version must be an integer")
        if self.value <= 0:
            raise AuthorityTypeError("aggregate version must be positive")

    def __int__(self) -> int:
        return self.value


class TrustScope(StrEnum):
    OBSERVED = "OBSERVED"
    PROPOSED = "PROPOSED"
    ADMITTED = "ADMITTED"


class RightsStatus(StrEnum):
    PERMITTED = "PERMITTED"
    RESTRICTED = "RESTRICTED"
    PROHIBITED = "PROHIBITED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EXPIRED = "EXPIRED"
    CONFLICTING = "CONFLICTING"
    UNSUPPORTED = "UNSUPPORTED"

    @property
    def permits_installation(self) -> bool:
        return self in {RightsStatus.PERMITTED, RightsStatus.RESTRICTED}


class TimePrecision(StrEnum):
    EXACT = "EXACT"
    DATE_ONLY = "DATE_ONLY"
    APPROXIMATE = "APPROXIMATE"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


@dataclass(frozen=True, slots=True)
class UtcTimestamp:
    value: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.value, datetime):
            raise AuthorityTypeError("UTC timestamp must be a datetime")
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise AuthorityTypeError("UTC timestamp requires an explicit offset")
        object.__setattr__(self, "value", self.value.astimezone(UTC))

    @classmethod
    def now(cls) -> Self:
        return cls(datetime.now(UTC))

    @classmethod
    def parse(cls, value: str) -> Self:
        if not isinstance(value, str):
            raise AuthorityTypeError("UTC timestamp text must be a string")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AuthorityTypeError("invalid UTC timestamp") from exc
        return cls(parsed)

    def to_text(self) -> str:
        return self.value.isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class TemporalValue:
    """A source-asserted temporal value with explicit precision/uncertainty."""

    value: datetime | date | None
    precision: TimePrecision
    conflicting_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.precision is TimePrecision.UNKNOWN:
            if self.value is not None or self.conflicting_values:
                raise AuthorityTypeError("UNKNOWN time cannot carry a value")
            return
        if self.precision is TimePrecision.CONFLICTING:
            if self.value is not None or len(self.conflicting_values) < 2:
                raise AuthorityTypeError(
                    "CONFLICTING time requires at least two retained alternatives"
                )
            return
        if self.conflicting_values:
            raise AuthorityTypeError(
                "conflicting alternatives are valid only for CONFLICTING time"
            )
        if self.value is None:
            raise AuthorityTypeError(f"{self.precision} time requires a value")
        if self.precision is TimePrecision.DATE_ONLY:
            if isinstance(self.value, datetime) or not isinstance(self.value, date):
                raise AuthorityTypeError("DATE_ONLY time requires a date")
            return
        if not isinstance(self.value, datetime):
            raise AuthorityTypeError(
                f"{self.precision} time requires an offset-aware datetime"
            )
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise AuthorityTypeError("temporal datetime requires an explicit offset")
        object.__setattr__(self, "value", self.value.astimezone(UTC))
