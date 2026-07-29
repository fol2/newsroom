from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, validate_sha256_digest
from newsroom.authority.types import UUIDv4Id, require_token


class ExtractionContractError(ValueError):
    """Raised when an Increment 4A extraction contract is invalid."""


class ExtractionStateError(RuntimeError):
    """Raised when an extraction transition is not currently permitted."""


class ExtractionSemanticCollision(ExtractionStateError):
    """Raised when equal semantics are presented under a new stable identity."""


class ExtractionIdentifierReuse(ExtractionStateError):
    """Raised when an opaque identity is reused for different semantics."""


class ExtractionVersionConflict(ExtractionStateError):
    """Raised when an immutable version does not extend the exact current head."""


class ExtractionRightsBlocked(ExtractionStateError):
    """Raised when current source rights or policy no longer permit use/replay."""


@dataclass(frozen=True, slots=True)
class ExtractorContractId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ExtractionRunId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ExtractionAttemptId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ExtractionOutputId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ProposalSetId(UUIDv4Id):
    pass


@dataclass(frozen=True, slots=True)
class ProposalEnvelopeId(UUIDv4Id):
    pass


class ExtractionExecutionProfile(StrEnum):
    FIXTURE = "FIXTURE"
    REPLAY = "REPLAY"


class ExtractionProducerKind(StrEnum):
    DETERMINISTIC_FAKE = "DETERMINISTIC_FAKE"
    APPROVED_REPLAY = "APPROVED_REPLAY"


class ExtractionAttemptOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    BLOCKING_FAILURE = "BLOCKING_FAILURE"
    INVALID_OUTPUT = "INVALID_OUTPUT"


class ExtractionOutputKind(StrEnum):
    INLINE_STRUCTURED = "INLINE_STRUCTURED"
    GOVERNED_OBJECT_REFERENCE = "GOVERNED_OBJECT_REFERENCE"


class ProposalSetCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class ProposalKind(StrEnum):
    ENTITY_MENTION = "ENTITY_MENTION"
    ENTITY_ALIAS = "ENTITY_ALIAS"
    ENTITY_EQUIVALENCE = "ENTITY_EQUIVALENCE"
    RELATION = "RELATION"
    TEMPORAL_CLAIM = "TEMPORAL_CLAIM"
    OTHER_STRUCTURED = "OTHER_STRUCTURED"


class ProposalEndpointKind(StrEnum):
    MENTION = "MENTION"
    LITERAL = "LITERAL"
    UNKNOWN = "UNKNOWN"


class ProposalUncertainty(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


RUNTIME_AUTHORITY_DISABLED = "FIXTURE_REPLAY_ONLY_DISABLED"
MAX_STRUCTURED_OUTPUT_BYTES = 1024 * 1024
MAX_PROPOSAL_ATTRIBUTES_BYTES = 64 * 1024


def bounded_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or "\x00" in value
        or (not allow_empty and not value)
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise ExtractionContractError(f"{field} must be bounded canonical text")
    return value


def bounded_text_tuple(
    values: tuple[str, ...],
    *,
    field: str,
    maximum_items: int = 64,
    maximum_item_bytes: int = 1024,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ExtractionContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not values:
        raise ExtractionContractError(f"{field} cannot be empty")
    if len(values) > maximum_items:
        raise ExtractionContractError(f"{field} exceeds its item bound")
    normalized = tuple(
        bounded_text(
            item,
            field=field,
            maximum_bytes=maximum_item_bytes,
        )
        for item in values
    )
    if normalized != tuple(sorted(set(normalized))):
        raise ExtractionContractError(f"{field} must be sorted and unique")
    return normalized


def canonical_digest(value: str, *, field: str) -> str:
    try:
        normalized = validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise ExtractionContractError(f"{field} must be a sha256 digest") from exc
    if normalized != value:
        raise ExtractionContractError(f"{field} must use canonical lowercase text")
    return value


def non_negative_int(value: int, *, field: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > maximum
    ):
        raise ExtractionContractError(f"{field} is outside its integer bound")
    return value


def positive_int(value: int, *, field: str, maximum: int) -> int:
    if non_negative_int(value, field=field, maximum=maximum) == 0:
        raise ExtractionContractError(f"{field} must be positive")
    return value


def canonical_json_value(
    value: Any,
    *,
    field: str,
    maximum_bytes: int,
    maximum_depth: int = 8,
    maximum_items: int = 512,
) -> Any:
    """Validate a bounded JSON value and return it unchanged.

    Floats are intentionally excluded so provider-specific NaN/rounding behaviour
    can never enter a canonical authority identity. Numeric confidence and cost
    fields use bounded integers elsewhere in the contract.
    """

    seen_items = 0

    def visit(item: Any, depth: int) -> Any:
        nonlocal seen_items
        if depth > maximum_depth:
            raise ExtractionContractError(f"{field} exceeds its nesting bound")
        seen_items += 1
        if seen_items > maximum_items:
            raise ExtractionContractError(f"{field} exceeds its item bound")
        if item is None or isinstance(item, (bool, str)):
            if isinstance(item, str):
                bounded_text(
                    item,
                    field=field,
                    maximum_bytes=maximum_bytes,
                    allow_empty=True,
                )
            return item
        if isinstance(item, int) and not isinstance(item, bool):
            if not -(2**63) <= item <= 2**63 - 1:
                raise ExtractionContractError(f"{field} integer is outside int64")
            return item
        if isinstance(item, list):
            return [visit(child, depth + 1) for child in item]
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ExtractionContractError(f"{field} object keys must be text")
            keys = list(item)
            if keys != sorted(keys) or len(keys) != len(set(keys)):
                raise ExtractionContractError(
                    f"{field} object keys must be sorted and unique"
                )
            return {key: visit(item[key], depth + 1) for key in keys}
        raise ExtractionContractError(
            f"{field} supports only null, boolean, integer, text, arrays and objects"
        )

    result = visit(value, 0)
    if len(canonical_json_bytes(result)) > maximum_bytes:
        raise ExtractionContractError(f"{field} exceeds its canonical byte bound")
    return result


def semantic_digest(value: Any) -> str:
    return digest_bytes(canonical_json_bytes(value))


def require_version_token(value: str, *, field: str) -> str:
    try:
        return require_token(value, field=field)
    except ValueError as exc:
        raise ExtractionContractError(f"{field} must be a version token") from exc


@dataclass(frozen=True, slots=True)
class ExtractionReadPolicy:
    policy_id: str
    purpose: str
    metadata_required_scope: str
    sensitive_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="extraction_read_policy_id")
        bounded_text(self.purpose, field="extraction_read_purpose", maximum_bytes=1024)
        from newsroom.authority.types import require_scope

        require_scope(self.metadata_required_scope, field="extraction_metadata_scope")
        require_scope(self.sensitive_required_scope, field="extraction_sensitive_scope")
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
            or any(not isinstance(item, str) for item in self.allowed_principal_ids)
        ):
            raise ExtractionContractError("extraction read principals must be a non-empty frozenset")
        for principal in self.allowed_principal_ids:
            require_token(principal, field="extraction_read_principal")
        positive_int(self.max_results, field="extraction_read_max_results", maximum=10_000)

    @property
    def digest(self) -> str:
        return semantic_digest(
            {
                "allowed_principal_ids": sorted(self.allowed_principal_ids),
                "max_results": self.max_results,
                "metadata_required_scope": self.metadata_required_scope,
                "policy_id": self.policy_id,
                "purpose": self.purpose,
                "sensitive_required_scope": self.sensitive_required_scope,
            }
        )

    def require_principal(self, principal_id: str) -> None:
        if principal_id not in self.allowed_principal_ids:
            raise PermissionError("principal is outside the extraction read policy")

    def require_limit(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.max_results:
            raise ValueError("extraction read limit is outside policy")


__all__ = [
    "ExtractionAttemptId",
    "ExtractionAttemptOutcome",
    "ExtractionContractError",
    "ExtractionExecutionProfile",
    "ExtractionIdentifierReuse",
    "ExtractionOutputId",
    "ExtractionOutputKind",
    "ExtractionProducerKind",
    "ExtractionReadPolicy",
    "ExtractionRightsBlocked",
    "ExtractionRunId",
    "ExtractionSemanticCollision",
    "ExtractionStateError",
    "ExtractionVersionConflict",
    "ExtractorContractId",
    "MAX_PROPOSAL_ATTRIBUTES_BYTES",
    "MAX_STRUCTURED_OUTPUT_BYTES",
    "ProposalEndpointKind",
    "ProposalEnvelopeId",
    "ProposalKind",
    "ProposalSetCompleteness",
    "ProposalSetId",
    "ProposalUncertainty",
    "RUNTIME_AUTHORITY_DISABLED",
    "bounded_text",
    "bounded_text_tuple",
    "canonical_digest",
    "canonical_json_value",
    "non_negative_int",
    "positive_int",
    "require_version_token",
    "semantic_digest",
]
