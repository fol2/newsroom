from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest
from newsroom.authority.types import UUIDv4Id, require_scope, require_token
from newsroom.sources import (
    CheckOutcomeId,
    CoverageContribution,
    CoverageResponsibility,
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    VersionedPolicyRef,
)


class CheckAuthorityError(RuntimeError):
    """Base error for deterministic Check and transition authority."""


class CheckContractError(ValueError):
    """A Check, baseline, transition or Finding contract is malformed."""


class CheckStateError(CheckAuthorityError):
    """Retained authority cannot support the requested transition."""


class CheckSemanticCollision(CheckStateError):
    """Different stable identities claim one exact semantic record."""


class CheckIdentifierReuse(CheckStateError):
    """A retained identifier is being reused for different semantics."""


class CheckVersionConflict(CheckStateError):
    """A write is not pinned to exact retained source or workflow state."""


class CheckRequestId(UUIDv4Id):
    pass


class CheckAttemptId(UUIDv4Id):
    pass


class BaselineDecisionId(UUIDv4Id):
    pass


class ObservableTransitionId(UUIDv4Id):
    pass


class OperationalFindingId(UUIDv4Id):
    pass


class OperationalFindingOccurrenceId(UUIDv4Id):
    pass


class TriggerKind(StrEnum):
    FIXTURE_MANUAL = "FIXTURE_MANUAL"
    APPROVED_REPLAY = "APPROVED_REPLAY"
    PLANNED_WINDOW = "PLANNED_WINDOW"
    DELIVERED_INPUT = "DELIVERED_INPUT"
    LINKED_FOLLOWUP = "LINKED_FOLLOWUP"
    RESET_REBUILD = "RESET_REBUILD"


class CheckAttemptKind(StrEnum):
    PRIMARY = "PRIMARY"
    RETRY = "RETRY"
    REPLAY = "REPLAY"
    CONFIRMATION = "CONFIRMATION"


class CheckOutcomeKind(StrEnum):
    BLOCKED = "BLOCKED"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    SUCCESS_UNCHANGED = "SUCCESS_UNCHANGED"
    SUCCESS_CHANGED = "SUCCESS_CHANGED"
    SUCCESS_PARTIAL = "SUCCESS_PARTIAL"
    SUCCESS_TRUNCATED = "SUCCESS_TRUNCATED"
    REDIRECTED = "REDIRECTED"
    RATE_LIMITED = "RATE_LIMITED"
    UNAUTHORISED = "UNAUTHORISED"
    NOT_FOUND = "NOT_FOUND"
    GONE = "GONE"
    MALFORMED = "MALFORMED"
    SHAPE_DRIFT = "SHAPE_DRIFT"
    TRANSPORT_FAILED = "TRANSPORT_FAILED"
    QUARANTINED_DISABLED = "QUARANTINED_DISABLED"


class QuarantineDisposition(StrEnum):
    NONE = "NONE"
    REVIEW = "REVIEW"
    QUARANTINE = "QUARANTINE"


class BaselineDecisionKind(StrEnum):
    ESTABLISH = "ESTABLISH"
    RESET = "RESET"
    REBUILD = "REBUILD"


class BaselineDisposition(StrEnum):
    MAINTAINED_BASELINE_ONLY = "MAINTAINED_BASELINE_ONLY"
    BOUNDED_BACKFILL = "BOUNDED_BACKFILL"
    FIRST_OBSERVED_ACTIVE = "FIRST_OBSERVED_ACTIVE"
    FUTURE_EXPECTATIONS_ONLY = "FUTURE_EXPECTATIONS_ONLY"
    EXPLICIT_DELTA_SEQUENCE = "EXPLICIT_DELTA_SEQUENCE"
    MANUAL_HOLD = "MANUAL_HOLD"


class BaselineEntryDisposition(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class ObservableTransitionKind(StrEnum):
    FIRST_OBSERVED = "FIRST_OBSERVED"
    REVISED = "REVISED"
    REOBSERVED = "REOBSERVED"
    ACTIVATED = "ACTIVATED"
    ESCALATED = "ESCALATED"
    DEESCALATED = "DEESCALATED"
    RESOLVED_OR_CLEARED = "RESOLVED_OR_CLEARED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    WITHDRAWN = "WITHDRAWN"
    REPLACED = "REPLACED"
    REACTIVATED = "REACTIVATED"
    AGENDA_CREATED = "AGENDA_CREATED"
    AGENDA_RESCHEDULED = "AGENDA_RESCHEDULED"
    AGENDA_CANCELLED = "AGENDA_CANCELLED"
    AGENDA_MISSED_EXPECTATION = "AGENDA_MISSED_EXPECTATION"
    AGENDA_LATE_OCCURRENCE = "AGENDA_LATE_OCCURRENCE"
    AMBIGUOUS_ABSENCE = "AMBIGUOUS_ABSENCE"


class TransitionBasis(StrEnum):
    REVISION = "REVISION"
    EXPLICIT_DELTA = "EXPLICIT_DELTA"
    COMPLETE_SNAPSHOT_ABSENCE = "COMPLETE_SNAPSHOT_ABSENCE"
    AGENDA_EXPECTATION = "AGENDA_EXPECTATION"


class FindingCategory(StrEnum):
    IDENTITY_INTEGRITY = "IDENTITY_INTEGRITY"
    BASELINE_INTEGRITY = "BASELINE_INTEGRITY"
    PARSER = "PARSER"
    RIGHTS = "RIGHTS"
    POLICY = "POLICY"
    TRANSPORT = "TRANSPORT"
    SOURCE_CONTRACT = "SOURCE_CONTRACT"
    QUARANTINE = "QUARANTINE"
    CONFIRMATION = "CONFIRMATION"
    STORE = "STORE"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    DEGRADED = "DEGRADED"
    BLOCKING = "BLOCKING"
    INTEGRITY = "INTEGRITY"


class FindingScopeKind(StrEnum):
    SOURCE_DEFINITION = "SOURCE_DEFINITION"
    SOURCE_VERSION = "SOURCE_VERSION"
    CHECK_REQUEST = "CHECK_REQUEST"
    CHECK_ATTEMPT = "CHECK_ATTEMPT"
    CHECK_OUTCOME = "CHECK_OUTCOME"
    SOURCE_ITEM = "SOURCE_ITEM"
    ADAPTER = "ADAPTER"


_SUCCESS_OUTCOMES = frozenset(
    {
        CheckOutcomeKind.SUCCESS_EMPTY,
        CheckOutcomeKind.SUCCESS_UNCHANGED,
        CheckOutcomeKind.SUCCESS_CHANGED,
        CheckOutcomeKind.SUCCESS_PARTIAL,
        CheckOutcomeKind.SUCCESS_TRUNCATED,
    }
)
_CANDIDATE_OUTCOMES = frozenset(
    {
        CheckOutcomeKind.SUCCESS_CHANGED,
        CheckOutcomeKind.SUCCESS_PARTIAL,
        CheckOutcomeKind.SUCCESS_TRUNCATED,
    }
)
_INCOMPLETE_OUTCOMES = frozenset(
    {
        CheckOutcomeKind.BLOCKED,
        CheckOutcomeKind.SUCCESS_PARTIAL,
        CheckOutcomeKind.SUCCESS_TRUNCATED,
        CheckOutcomeKind.REDIRECTED,
        CheckOutcomeKind.RATE_LIMITED,
        CheckOutcomeKind.UNAUTHORISED,
        CheckOutcomeKind.NOT_FOUND,
        CheckOutcomeKind.GONE,
        CheckOutcomeKind.MALFORMED,
        CheckOutcomeKind.SHAPE_DRIFT,
        CheckOutcomeKind.TRANSPORT_FAILED,
        CheckOutcomeKind.QUARANTINED_DISABLED,
    }
)
_ENDING_TRANSITIONS = frozenset(
    {
        ObservableTransitionKind.RESOLVED_OR_CLEARED,
        ObservableTransitionKind.EXPIRED,
        ObservableTransitionKind.CANCELLED,
        ObservableTransitionKind.WITHDRAWN,
    }
)
_AGENDA_TRANSITIONS = frozenset(
    {
        ObservableTransitionKind.AGENDA_CREATED,
        ObservableTransitionKind.AGENDA_RESCHEDULED,
        ObservableTransitionKind.AGENDA_CANCELLED,
        ObservableTransitionKind.AGENDA_MISSED_EXPECTATION,
        ObservableTransitionKind.AGENDA_LATE_OCCURRENCE,
    }
)


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
    ):
        raise CheckContractError(f"{field} must be canonical text")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise CheckContractError(f"{field} exceeds its byte bound")
    return value


def sorted_unique_text(
    values: Iterable[str],
    *,
    field: str,
    maximum_items: int = 64,
    maximum_item_bytes: int = 1024,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise CheckContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not values:
        raise CheckContractError(f"{field} cannot be empty")
    if len(values) > maximum_items:
        raise CheckContractError(f"{field} exceeds its item bound")
    result = tuple(
        bounded_text(
            item,
            field=field,
            maximum_bytes=maximum_item_bytes,
        )
        for item in values
    )
    if result != tuple(sorted(set(result))):
        raise CheckContractError(f"{field} must be sorted and unique")
    return result


def typed_enum_tuple(
    values: tuple[StrEnum, ...],
    *,
    enum_type: type[StrEnum],
    field: str,
    allow_empty: bool = False,
) -> tuple[StrEnum, ...]:
    if not isinstance(values, tuple):
        raise CheckContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not values:
        raise CheckContractError(f"{field} cannot be empty")
    if any(not isinstance(item, enum_type) for item in values):
        raise CheckContractError(f"{field} entries must be typed")
    if values != tuple(sorted(set(values), key=lambda item: item.value)):
        raise CheckContractError(f"{field} must be sorted and unique")
    return values


def canonical_digest(value: str, *, field: str) -> str:
    try:
        normalized = validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise CheckContractError(f"{field} must be a sha256 digest") from exc
    if normalized != value:
        raise CheckContractError(f"{field} must use canonical lowercase text")
    return value


def positive_int(
    value: int,
    *,
    field: str,
    maximum: int = 2_147_483_647,
    allow_zero: bool = False,
) -> int:
    minimum = 0 if allow_zero else 1
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise CheckContractError(f"{field} is outside its integer bound")
    return value


def require_policy(value: VersionedPolicyRef, *, field: str) -> VersionedPolicyRef:
    if not isinstance(value, VersionedPolicyRef):
        raise CheckContractError(f"{field} must be a versioned policy reference")
    return value


def require_uuid_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise CheckContractError(f"{field} must be UUID text")
    try:
        UUIDv4Id.parse(value)
    except ValueError as exc:
        raise CheckContractError(f"{field} must be canonical UUIDv4") from exc
    return value


@dataclass(frozen=True, slots=True)
class TriggerRef:
    kind: TriggerKind
    trigger_id: str
    trigger_version: str
    expected_window_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TriggerKind):
            raise CheckContractError("trigger kind must be typed")
        require_token(self.trigger_id, field="trigger_id")
        require_token(self.trigger_version, field="trigger_version")
        if self.expected_window_digest is not None:
            canonical_digest(
                self.expected_window_digest,
                field="expected_window_digest",
            )
        if (
            self.kind is TriggerKind.PLANNED_WINDOW
            and self.expected_window_digest is None
        ):
            raise CheckContractError(
                "planned-window trigger requires an exact window digest"
            )
        if (
            self.kind is not TriggerKind.PLANNED_WINDOW
            and self.expected_window_digest is not None
        ):
            raise CheckContractError(
                "only a planned-window trigger may carry a window digest"
            )

    def canonical_value(self) -> dict[str, str | None]:
        return {
            "kind": self.kind.value,
            "trigger_id": self.trigger_id,
            "trigger_version": self.trigger_version,
            "expected_window_digest": self.expected_window_digest,
        }


@dataclass(frozen=True, slots=True)
class CoverageBasis:
    obligation_id: str
    responsibility: CoverageResponsibility
    contribution: CoverageContribution
    coverage_policy: VersionedPolicyRef

    def __post_init__(self) -> None:
        require_token(self.obligation_id, field="coverage_obligation_id")
        if not isinstance(self.responsibility, CoverageResponsibility):
            raise CheckContractError("coverage responsibility must be typed")
        if not isinstance(self.contribution, CoverageContribution):
            raise CheckContractError("coverage contribution must be typed")
        require_policy(self.coverage_policy, field="coverage_policy")

    def canonical_value(self) -> dict[str, object]:
        return {
            "obligation_id": self.obligation_id,
            "responsibility": self.responsibility.value,
            "contribution": self.contribution.value,
            "coverage_policy": self.coverage_policy.canonical_value(),
        }


@dataclass(frozen=True, slots=True)
class CheckReadPolicy:
    policy_id: str
    purpose: str
    metadata_required_scope: str
    sensitive_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="check_read_policy_id")
        require_token(self.purpose, field="check_read_purpose")
        require_scope(
            self.metadata_required_scope,
            field="check_metadata_read_scope",
        )
        require_scope(
            self.sensitive_required_scope,
            field="check_sensitive_read_scope",
        )
        if self.metadata_required_scope == self.sensitive_required_scope:
            raise CheckContractError(
                "check metadata and sensitive reads require distinct scopes"
            )
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise CheckContractError(
                "check read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            require_token(principal_id, field="check_reader_principal")
        positive_int(
            self.max_results,
            field="check_read_maximum",
            maximum=10_000,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "purpose": self.purpose,
            "metadata_required_scope": self.metadata_required_scope,
            "sensitive_required_scope": self.sensitive_required_scope,
            "allowed_principal_ids": sorted(self.allowed_principal_ids),
            "max_results": self.max_results,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_principal(self, principal_id: str) -> None:
        if principal_id not in self.allowed_principal_ids:
            raise PermissionError(
                "check reader principal is outside the read policy"
            )

    def require_limit(self, limit: int) -> None:
        try:
            positive_int(limit, field="check_read_limit", maximum=self.max_results)
        except CheckContractError as exc:
            raise PermissionError("check read limit exceeds the policy") from exc


def is_success_outcome(value: CheckOutcomeKind) -> bool:
    return value in _SUCCESS_OUTCOMES


def is_candidate_outcome(value: CheckOutcomeKind) -> bool:
    return value in _CANDIDATE_OUTCOMES


def outcome_requires_incomplete(value: CheckOutcomeKind) -> bool:
    return value in _INCOMPLETE_OUTCOMES


def is_ending_transition(value: ObservableTransitionKind) -> bool:
    return value in _ENDING_TRANSITIONS


def is_agenda_transition(value: ObservableTransitionKind) -> bool:
    return value in _AGENDA_TRANSITIONS


__all__ = [
    "BaselineDecisionId",
    "BaselineDecisionKind",
    "BaselineDisposition",
    "BaselineEntryDisposition",
    "CheckAttemptId",
    "CheckAttemptKind",
    "CheckAuthorityError",
    "CheckContractError",
    "CheckIdentifierReuse",
    "CheckOutcomeId",
    "CheckOutcomeKind",
    "CheckReadPolicy",
    "CheckRequestId",
    "CheckSemanticCollision",
    "CheckStateError",
    "CheckVersionConflict",
    "CoverageBasis",
    "FindingCategory",
    "FindingScopeKind",
    "FindingSeverity",
    "ObservableTransitionId",
    "ObservableTransitionKind",
    "OperationalFindingId",
    "OperationalFindingOccurrenceId",
    "QuarantineDisposition",
    "TransitionBasis",
    "TriggerKind",
    "TriggerRef",
    "bounded_text",
    "canonical_digest",
    "is_agenda_transition",
    "is_candidate_outcome",
    "is_ending_transition",
    "is_success_outcome",
    "outcome_requires_incomplete",
    "positive_int",
    "require_policy",
    "require_uuid_text",
    "sorted_unique_text",
    "typed_enum_tuple",
]
