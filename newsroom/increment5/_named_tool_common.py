"""Shared closed types and validators for Increment 5C named-tool mechanics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
import uuid

NAMED_TOOL_POLICY_ID = "increment5-named-tool-local-auth-v1"
NAMED_TOOL_PROFILE_ID = "increment5-named-tool-local-auth-profile-v1"
NAMED_TOOL_RESULT_LIMIT = 8
NAMED_TOOL_TIMEOUT_MS = 5_000
NAMED_TOOL_BYTE_BUDGET = 262_144
NAMED_TOOL_GRAPH_DEPTH = 2
NAMED_TOOL_GRAPH_FAN_OUT = 32
NAMED_TOOL_DATE_WINDOW_DAYS = 31
NAMED_TOOL_EXTERNAL_CALLS = 0
NAMED_TOOL_PROVIDER_CALLS = 0
NAMED_TOOL_MODEL_CALLS = 0
NAMED_TOOL_EMBEDDING_CALLS = 0
NAMED_TOOL_PROVIDER_SPEND_MICROS = 0

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-/]{0,255}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LOCALE_VALUES = frozenset({"en-GB", "zh-Hant-HK", "mixed"})
_FORBIDDEN_QUERY_FRAGMENTS = (
    "&&",
    "||",
    "\\",
    "*",
    "?",
    "~",
    "^",
    "[",
    "]",
    "{",
    "}",
    "(",
    ")",
)
_FORBIDDEN_WRITE_WORDS = re.compile(
    r"(?:^|\s)(?:CREATE|DELETE|DETACH|DROP|MERGE|REMOVE|SET)(?:\s|$)",
    re.IGNORECASE,
)
_FORBIDDEN_FIELD_QUERY = re.compile(
    r"(?:^|\s)[A-Za-z_][A-Za-z0-9_.-]{0,63}:[^\s]"
)


class NamedToolContractError(ValueError):
    """A named-tool payload, grant, receipt, or retained row is malformed."""


class NamedToolJournalError(RuntimeError):
    """The non-authoritative local authorization journal is inconsistent."""


class NamedToolIdempotencyConflict(NamedToolJournalError):
    """A stable idempotency key was reused for a materially different call."""


class ToolIdentity(StrEnum):
    EXACT_AUTHORITY_LOOKUP = "EXACT_AUTHORITY_LOOKUP"
    BOUNDED_FULL_TEXT_RETRIEVAL = "BOUNDED_FULL_TEXT_RETRIEVAL"
    BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL = "BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL"
    BOUNDED_ADMITTED_GRAPH_TRAVERSAL = "BOUNDED_ADMITTED_GRAPH_TRAVERSAL"
    COLLISION_AUTHORITY_HYDRATION_LOOKUP = "COLLISION_AUTHORITY_HYDRATION_LOOKUP"
    SOURCE_REVISION_IMPACT_LOOKUP = "SOURCE_REVISION_IMPACT_LOOKUP"


class ToolPurpose(StrEnum):
    EXACT_IDENTITY_LOOKUP = "EXACT_IDENTITY_LOOKUP"
    RETRIEVE_TEXT_CONTEXT = "RETRIEVE_TEXT_CONTEXT"
    RETRIEVE_VECTOR_CONTEXT = "RETRIEVE_VECTOR_CONTEXT"
    RETRIEVE_ADMITTED_GRAPH_CONTEXT = "RETRIEVE_ADMITTED_GRAPH_CONTEXT"
    HYDRATE_COLLISION_AUTHORITY = "HYDRATE_COLLISION_AUTHORITY"
    ASSESS_SOURCE_REVISION_IMPACT = "ASSESS_SOURCE_REVISION_IMPACT"


TOOL_PURPOSE_BY_IDENTITY: Mapping[ToolIdentity, ToolPurpose] = MappingProxyType(
    {
        ToolIdentity.EXACT_AUTHORITY_LOOKUP: ToolPurpose.EXACT_IDENTITY_LOOKUP,
        ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL: ToolPurpose.RETRIEVE_TEXT_CONTEXT,
        ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: (
            ToolPurpose.RETRIEVE_VECTOR_CONTEXT
        ),
        ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: (
            ToolPurpose.RETRIEVE_ADMITTED_GRAPH_CONTEXT
        ),
        ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP: (
            ToolPurpose.HYDRATE_COLLISION_AUTHORITY
        ),
        ToolIdentity.SOURCE_REVISION_IMPACT_LOOKUP: (
            ToolPurpose.ASSESS_SOURCE_REVISION_IMPACT
        ),
    }
)


class AuthenticationMethod(StrEnum):
    MTLS = "MTLS"
    OIDC = "OIDC"
    LOCAL_SIGNED_ASSERTION = "LOCAL_SIGNED_ASSERTION"


class ToolAuthorizationOutcome(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    MALFORMED = "MALFORMED"


class ToolAuthorizationReason(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    MALFORMED_REQUEST = "MALFORMED_REQUEST"
    ACTOR_PROOF_MISMATCH = "ACTOR_PROOF_MISMATCH"
    PROOF_NOT_YET_VALID = "PROOF_NOT_YET_VALID"
    PROOF_EXPIRED = "PROOF_EXPIRED"
    POLICY_ID_MISMATCH = "POLICY_ID_MISMATCH"
    POLICY_DIGEST_MISMATCH = "POLICY_DIGEST_MISMATCH"
    NO_EXACT_GRANT = "NO_EXACT_GRANT"
    AMBIGUOUS_GRANT = "AMBIGUOUS_GRANT"
    GRANT_NOT_YET_VALID = "GRANT_NOT_YET_VALID"
    GRANT_EXPIRED = "GRANT_EXPIRED"
    NO_CURRENT_GRANT = "NO_CURRENT_GRANT"
    SCOPE_NOT_GRANTED = "SCOPE_NOT_GRANTED"


class ExactLookupKind(StrEnum):
    SOURCE_NATIVE_ID = "SOURCE_NATIVE_ID"
    SOURCE_REVISION_ID = "SOURCE_REVISION_ID"
    SOURCE_NATIVE_REVISION_TOKEN = "SOURCE_NATIVE_REVISION_TOKEN"
    REPRESENTATION_ID = "REPRESENTATION_ID"
    CANONICAL_ENTITY_ID = "CANONICAL_ENTITY_ID"
    AUTHORITY_ALIAS = "AUTHORITY_ALIAS"
    FORMAL_PROCESS_ID = "FORMAL_PROCESS_ID"


@dataclass(frozen=True, slots=True, order=True)
class CanonicalUtc:
    value: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.value, datetime) or self.value.tzinfo is None:
            raise NamedToolContractError("timestamp must be timezone-aware")
        normalized = self.value.astimezone(UTC)
        if normalized.microsecond:
            raise NamedToolContractError("timestamp must use second resolution")
        object.__setattr__(self, "value", normalized)

    @classmethod
    def parse(cls, value: object, *, field: str) -> CanonicalUtc:
        if not isinstance(value, str):
            raise NamedToolContractError(f"{field} must be canonical UTC text")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError as exc:
            raise NamedToolContractError(
                f"{field} must be canonical second-resolution UTC"
            ) from exc
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
            raise NamedToolContractError(
                f"{field} must be canonical second-resolution UTC"
            )
        return cls(parsed)

    def to_text(self) -> str:
        return self.value.strftime("%Y-%m-%dT%H:%M:%SZ")


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
        raise NamedToolContractError("value is not canonical JSON") from exc


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise NamedToolContractError(f"{field} must be an object with text keys")
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    *,
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise NamedToolContractError(
            f"{field} keys differ; missing={missing!r}, extra={extra!r}"
        )


def _require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise NamedToolContractError(f"{field} must be text")
    return value


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field=field)


def _bounded_text(value: str, *, field: str, maximum_bytes: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
        or "\x00" in value
    ):
        raise NamedToolContractError(f"{field} must be bounded canonical text")
    return value


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a bounded canonical token")
    return value


def _require_digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _require_uuid4(value: str, *, field: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise NamedToolContractError(f"{field} must be canonical UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise NamedToolContractError(f"{field} must be canonical UUIDv4")
    return value


def _require_uuid5(value: str, *, field: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise NamedToolContractError(f"{field} must be canonical UUIDv5") from exc
    if parsed.version != 5 or str(parsed) != value:
        raise NamedToolContractError(f"{field} must be canonical UUIDv5")
    return value


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NamedToolContractError(f"{field} must be an integer")
    return value


def _parse_enum(enum_type: type[StrEnum], value: object, *, field: str):
    if not isinstance(value, str):
        raise NamedToolContractError(f"{field} must be a typed enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise NamedToolContractError(f"{field} is not an allowed value") from exc


def _decode_text_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise NamedToolContractError(f"{field} must be a text array")
    return tuple(value)


def _bounded_unique_tokens(
    values: Sequence[str],
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise NamedToolContractError(f"{field} must be a bounded token sequence")
    normalized = tuple(sorted(values))
    if (not normalized and not allow_empty) or len(normalized) > maximum:
        raise NamedToolContractError(f"{field} exceeds its fixed cardinality")
    if len(set(normalized)) != len(normalized):
        raise NamedToolContractError(f"{field} must not contain duplicates")
    for value in normalized:
        _require_token(value, field=field)
    return normalized


def _require_fixed_bounds(*, result_limit: int, byte_budget: int, timeout_ms: int) -> None:
    _require_int(result_limit, field="result_limit")
    _require_int(byte_budget, field="byte_budget")
    _require_int(timeout_ms, field="timeout_ms")
    if result_limit != NAMED_TOOL_RESULT_LIMIT:
        raise NamedToolContractError("named-tool result limit must remain fixed at 8")
    if byte_budget != NAMED_TOOL_BYTE_BUDGET:
        raise NamedToolContractError(
            "named-tool byte budget must remain fixed at 262144"
        )
    if timeout_ms != NAMED_TOOL_TIMEOUT_MS:
        raise NamedToolContractError("named-tool timeout must remain fixed at 5000 ms")


def _require_window(start: CanonicalUtc, end: CanonicalUtc) -> None:
    if not isinstance(start, CanonicalUtc) or not isinstance(end, CanonicalUtc):
        raise NamedToolContractError("tool date-window endpoints must be typed")
    if start >= end:
        raise NamedToolContractError("tool date window is empty or reversed")
    if end.value - start.value > timedelta(days=NAMED_TOOL_DATE_WINDOW_DAYS):
        raise NamedToolContractError("tool date window exceeds 31 days")


def _require_locale(value: str) -> None:
    if not isinstance(value, str) or value not in _LOCALE_VALUES:
        raise NamedToolContractError("tool locale is not repository-approved")


def _reject_raw_query_surface(value: str) -> None:
    if any(fragment in value for fragment in _FORBIDDEN_QUERY_FRAGMENTS):
        raise NamedToolContractError("raw query syntax is prohibited")
    if _FORBIDDEN_FIELD_QUERY.search(value):
        raise NamedToolContractError("raw field-query syntax is prohibited")
    if _FORBIDDEN_WRITE_WORDS.search(value):
        raise NamedToolContractError("write-like query content is prohibited")
