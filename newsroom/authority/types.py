from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
import re
from typing import Self
from uuid import UUID, RFC_4122, uuid4


class AuthorityTypeError(ValueError):
    """Raised when a typed authority value is invalid."""


_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,255}$")


def require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise AuthorityTypeError(f"{field} is not a valid authority token")
    return value


def require_scope(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SCOPE.fullmatch(value) is None:
        raise AuthorityTypeError(f"{field} is not a valid scope token")
    return value


@dataclass(frozen=True, slots=True)
class UUIDv4Id:
    """Opaque typed identity; never an ordering or causality source."""

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
class ObjectAdmissionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class RightsDecisionId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class CorrelationId(UUIDv4Id):
    """Opaque trace/workflow identity; it does not need to resolve to authority."""


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


class PayloadMode(StrEnum):
    INLINE = "INLINE"
    OBJECT_ADMISSION = "OBJECT_ADMISSION"
    NO_PAYLOAD = "NO_PAYLOAD"


class CausationKind(StrEnum):
    COMMAND = "COMMAND"
    EVENT = "EVENT"
    EXTERNAL = "EXTERNAL"


@dataclass(frozen=True, slots=True)
class CausationRef:
    kind: CausationKind
    identifier: str
    external_system: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CausationKind):
            raise AuthorityTypeError("causation kind must be typed")
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise AuthorityTypeError("causation identifier must be non-empty")
        if self.kind is CausationKind.COMMAND:
            CommandId.parse(self.identifier)
            if self.external_system is not None:
                raise AuthorityTypeError("command causation cannot name an external system")
        elif self.kind is CausationKind.EVENT:
            EventId.parse(self.identifier)
            if self.external_system is not None:
                raise AuthorityTypeError("event causation cannot name an external system")
        else:
            require_token(self.external_system or "", field="external_system")
            require_token(self.identifier, field="external causation identifier")


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
    value: datetime | date | None
    precision: TimePrecision
    conflicting_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.precision, TimePrecision):
            raise AuthorityTypeError("time precision must be typed")
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
