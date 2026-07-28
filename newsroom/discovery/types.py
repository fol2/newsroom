from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest
from newsroom.authority.types import UUIDv4Id, UtcTimestamp, require_scope, require_token
from newsroom.checks.types import (
    CoverageBasis,
    bounded_text,
    require_policy,
    sorted_unique_text,
)
from newsroom.sources import VersionedPolicyRef


class DiscoveryAuthorityError(RuntimeError):
    """Base error for Signal, gate, and Lead authority."""


class DiscoveryContractError(ValueError):
    """A typed discovery-authority contract is malformed."""


class DiscoveryIdentifierReuse(DiscoveryAuthorityError):
    """A lifecycle identifier is already bound to another record."""


class DiscoverySemanticCollision(DiscoveryAuthorityError):
    """One semantic authority slot contains conflicting bytes."""


class DiscoveryStateError(DiscoveryAuthorityError):
    """Retained discovery authority is missing or internally inconsistent."""


class DiscoveryVersionConflict(DiscoveryAuthorityError):
    """A decision evaluated stale or conflicting governing versions."""


class DiscoverySignalId(UUIDv4Id):
    pass


class GateDecisionId(UUIDv4Id):
    pass


class NewsLeadId(UUIDv4Id):
    pass


class WatchConditionId(UUIDv4Id):
    pass


class LeadDispositionDecisionId(UUIDv4Id):
    pass


class GateOutcome(StrEnum):
    SUPPRESSED_DUPLICATE = "SIGNAL_SUPPRESSED_DUPLICATE"
    SUPPRESSED_NON_CHANGE = "SIGNAL_SUPPRESSED_NON_CHANGE"
    REJECTED_CLEAR_EXCLUSION = "SIGNAL_REJECTED_CLEAR_EXCLUSION"
    PROMOTED_TO_LEAD = "SIGNAL_PROMOTED_TO_LEAD"
    OPERATIONAL_HOLD = "SIGNAL_OPERATIONAL_HOLD"


class DecisionTerminality(StrEnum):
    TERMINAL_EXACT_VERSION = "TERMINAL_EXACT_VERSION"
    PENDING_CONDITION = "PENDING_CONDITION"
    RETRYABLE_SAME_REQUEST = "RETRYABLE_SAME_REQUEST"
    OCCURRENCE_ONLY = "OCCURRENCE_ONLY"


class ReasonBasisClass(StrEnum):
    DETERMINISTIC_OBSERVATION = "DETERMINISTIC_OBSERVATION"
    DETERMINISTIC_POLICY = "DETERMINISTIC_POLICY"
    SOURCE_ASSERTION = "SOURCE_ASSERTION"
    EDITORIAL_ASSESSMENT = "EDITORIAL_ASSESSMENT"
    OPERATIONAL_ASSESSMENT = "OPERATIONAL_ASSESSMENT"
    HUMAN_ADJUDICATION = "HUMAN_ADJUDICATION"
    DOWNSTREAM_FEEDBACK = "DOWNSTREAM_FEEDBACK"


GATE_ALLOWED_REASON_BASES = frozenset(
    {
        ReasonBasisClass.DETERMINISTIC_OBSERVATION,
        ReasonBasisClass.DETERMINISTIC_POLICY,
        ReasonBasisClass.SOURCE_ASSERTION,
        ReasonBasisClass.OPERATIONAL_ASSESSMENT,
    }
)


class ObservableNewness(StrEnum):
    GENUINE_TRANSITION = "GENUINE_TRANSITION"
    EXACT_REPEAT = "EXACT_REPEAT"
    PARSER_ONLY = "PARSER_ONLY"
    EXPECTATION_ONLY = "EXPECTATION_ONLY"
    UNKNOWN = "UNKNOWN"


class TimeValidity(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


class ScopeDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    CLEAR_EXCLUSION = "CLEAR_EXCLUSION"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class UrgencyRoute(StrEnum):
    URGENT = "URGENT"
    TIME_SENSITIVE = "TIME_SENSITIVE"
    PLANNED = "PLANNED"
    ROUTINE = "ROUTINE"


class LeadDispositionOutcome(StrEnum):
    QUEUED_FOR_TRIAGE = "LEAD_QUEUED_FOR_TRIAGE"
    OPERATIONAL_HOLD = "LEAD_OPERATIONAL_HOLD"
    WATCH_DEFER = "LEAD_WATCH_DEFER"
    EDITORIAL_REJECT = "LEAD_EDITORIAL_REJECT"
    ASSOCIATE_WITHOUT_CANDIDATE = "LEAD_ASSOCIATE_WITHOUT_CANDIDATE"
    SUPPLEMENTAL_DISCOVERY = "LEAD_SUPPLEMENTAL_DISCOVERY"
    ADMIT_NEW_CANDIDATE = "LEAD_ADMIT_NEW_CANDIDATE"
    ADMIT_DEVELOPMENT_CANDIDATE = "LEAD_ADMIT_DEVELOPMENT_CANDIDATE"
    ADMIT_CORRECTION_CANDIDATE = "LEAD_ADMIT_CORRECTION_CANDIDATE"


ACTIVE_INCREMENT_3D_DISPOSITIONS = frozenset(
    {
        LeadDispositionOutcome.QUEUED_FOR_TRIAGE,
        LeadDispositionOutcome.OPERATIONAL_HOLD,
        LeadDispositionOutcome.WATCH_DEFER,
    }
)


class NextActionKind(StrEnum):
    CLOSE = "CLOSE"
    QUEUE_TRIAGE = "QUEUE_TRIAGE"
    RETRY = "RETRY"
    REVIEW = "REVIEW"
    WAIT_DEPENDENCY = "WAIT_DEPENDENCY"
    RESUME_ON_WATCH = "RESUME_ON_WATCH"


@dataclass(frozen=True, slots=True)
class ReasonReference:
    reference_type: str
    identifier: str
    digest: str | None = None

    def __post_init__(self) -> None:
        require_token(self.reference_type, field="reason_reference_type")
        bounded_text(
            self.identifier,
            field="reason_reference_identifier",
            maximum_bytes=2048,
        )
        if self.digest is not None:
            validate_sha256_digest(self.digest, field="reason_reference_digest")

    def canonical_value(self) -> dict[str, object]:
        return {
            "reference_type": self.reference_type,
            "identifier": self.identifier,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class StructuredReason:
    code: str
    basis: ReasonBasisClass
    references: tuple[ReasonReference, ...]
    explanation: str

    def __post_init__(self) -> None:
        require_token(self.code, field="structured_reason_code")
        if not isinstance(self.basis, ReasonBasisClass):
            raise DiscoveryContractError("reason basis class must be typed")
        if (
            not isinstance(self.references, tuple)
            or not self.references
            or any(not isinstance(item, ReasonReference) for item in self.references)
        ):
            raise DiscoveryContractError(
                "structured reason requires immutable exact references"
            )
        canonical = tuple(
            sorted(
                self.references,
                key=lambda item: (
                    item.reference_type,
                    item.identifier,
                    item.digest or "",
                ),
            )
        )
        if canonical != self.references or len(canonical) != len(set(canonical)):
            raise DiscoveryContractError(
                "structured reason references must be sorted and unique"
            )
        bounded_text(
            self.explanation,
            field="structured_reason_explanation",
            maximum_bytes=4096,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "code": self.code,
            "basis": self.basis.value,
            "references": [item.canonical_value() for item in self.references],
            "explanation": self.explanation,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class NextAction:
    kind: NextActionKind
    action_code: str
    owner: str | None = None
    dependency: str | None = None
    due_at: UtcTimestamp | None = None
    expires_at: UtcTimestamp | None = None
    instructions: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NextActionKind):
            raise DiscoveryContractError("next action kind must be typed")
        require_token(self.action_code, field="next_action_code")
        if self.owner is not None:
            require_token(self.owner, field="next_action_owner")
        if self.dependency is not None:
            bounded_text(
                self.dependency,
                field="next_action_dependency",
                maximum_bytes=2048,
            )
        for field_name in ("due_at", "expires_at"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, UtcTimestamp):
                raise DiscoveryContractError(f"{field_name} must be typed UTC")
        if (
            self.due_at is not None
            and self.expires_at is not None
            and self.expires_at.value < self.due_at.value
        ):
            raise DiscoveryContractError("next-action expiry precedes due time")
        bounded_text(
            self.instructions,
            field="next_action_instructions",
            maximum_bytes=4096,
            allow_empty=True,
        )
        if self.kind in {
            NextActionKind.RETRY,
            NextActionKind.REVIEW,
            NextActionKind.WAIT_DEPENDENCY,
        } and not any(
            (
                self.owner,
                self.dependency,
                self.due_at,
                self.expires_at,
            )
        ):
            raise DiscoveryContractError(
                "pending next action requires owner, dependency, due time, or expiry"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "action_code": self.action_code,
            "owner": self.owner,
            "dependency": self.dependency,
            "due_at": None if self.due_at is None else self.due_at.to_text(),
            "expires_at": (
                None if self.expires_at is None else self.expires_at.to_text()
            ),
            "instructions": self.instructions,
        }


@dataclass(frozen=True, slots=True)
class GateBasis:
    identity_integrity: bool
    duplicate_signal_id: DiscoverySignalId | None
    duplicate_rule: VersionedPolicyRef | None
    observable_newness: ObservableNewness
    time_validity: TimeValidity
    scope_disposition: ScopeDisposition
    clear_exclusion_rule: VersionedPolicyRef | None
    rights_current: bool
    policy_current: bool
    operationally_executable: bool
    ambiguities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "identity_integrity",
            "rights_current",
            "policy_current",
            "operationally_executable",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise DiscoveryContractError(f"{field_name} must be boolean")
        if self.duplicate_signal_id is not None and not isinstance(
            self.duplicate_signal_id,
            DiscoverySignalId,
        ):
            raise DiscoveryContractError("duplicate Signal identity must be typed")
        if self.duplicate_rule is not None:
            require_policy(self.duplicate_rule, field="duplicate_rule")
        if not isinstance(self.observable_newness, ObservableNewness):
            raise DiscoveryContractError("observable newness must be typed")
        if not isinstance(self.time_validity, TimeValidity):
            raise DiscoveryContractError("time validity must be typed")
        if not isinstance(self.scope_disposition, ScopeDisposition):
            raise DiscoveryContractError("scope disposition must be typed")
        if self.clear_exclusion_rule is not None:
            require_policy(
                self.clear_exclusion_rule,
                field="clear_exclusion_rule",
            )
        sorted_unique_text(
            self.ambiguities,
            field="gate_ambiguities",
            maximum_items=32,
            maximum_item_bytes=1024,
            allow_empty=True,
        )
        if self.duplicate_signal_id is not None and self.duplicate_rule is None:
            raise DiscoveryContractError(
                "duplicate Signal target requires a versioned duplicate rule"
            )
        if self.scope_disposition is ScopeDisposition.CLEAR_EXCLUSION:
            if self.clear_exclusion_rule is None:
                raise DiscoveryContractError(
                    "clear exclusion requires an accepted versioned rule"
                )
            if self.ambiguities:
                raise DiscoveryContractError(
                    "ambiguous scope cannot be a clear deterministic exclusion"
                )
        elif self.clear_exclusion_rule is not None:
            raise DiscoveryContractError(
                "clear-exclusion rule is valid only for clear exclusion"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "identity_integrity": self.identity_integrity,
            "duplicate_signal_id": (
                None
                if self.duplicate_signal_id is None
                else str(self.duplicate_signal_id)
            ),
            "duplicate_rule": (
                None
                if self.duplicate_rule is None
                else self.duplicate_rule.canonical_value()
            ),
            "observable_newness": self.observable_newness.value,
            "time_validity": self.time_validity.value,
            "scope_disposition": self.scope_disposition.value,
            "clear_exclusion_rule": (
                None
                if self.clear_exclusion_rule is None
                else self.clear_exclusion_rule.canonical_value()
            ),
            "rights_current": self.rights_current,
            "policy_current": self.policy_current,
            "operationally_executable": self.operationally_executable,
            "ambiguities": list(self.ambiguities),
        }


@dataclass(frozen=True, slots=True)
class UrgencyBasis:
    route: UrgencyRoute
    primary_reason: StructuredReason
    hard_deadline: UtcTimestamp | None = None
    planned_window: str | None = None
    isolation_required: bool = False
    unknown_factors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.route, UrgencyRoute):
            raise DiscoveryContractError("urgency route must be typed")
        if not isinstance(self.primary_reason, StructuredReason):
            raise DiscoveryContractError("urgency requires a structured reason")
        if self.hard_deadline is not None and not isinstance(
            self.hard_deadline,
            UtcTimestamp,
        ):
            raise DiscoveryContractError("urgency deadline must be typed UTC")
        if self.planned_window is not None:
            bounded_text(
                self.planned_window,
                field="urgency_planned_window",
                maximum_bytes=1024,
            )
        if not isinstance(self.isolation_required, bool):
            raise DiscoveryContractError("urgency isolation flag must be boolean")
        sorted_unique_text(
            self.unknown_factors,
            field="urgency_unknown_factors",
            maximum_items=16,
            maximum_item_bytes=1024,
            allow_empty=True,
        )
        if self.route is UrgencyRoute.URGENT and not self.isolation_required:
            raise DiscoveryContractError(
                "Urgent Lead route requires explicit isolation"
            )
        if self.route is UrgencyRoute.PLANNED and self.planned_window is None:
            raise DiscoveryContractError(
                "Planned Lead route requires an inspectable window"
            )
        if self.route is not UrgencyRoute.PLANNED and self.planned_window is not None:
            raise DiscoveryContractError(
                "planned window is valid only for Planned route"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "route": self.route.value,
            "primary_reason": self.primary_reason.canonical_value(),
            "hard_deadline": (
                None
                if self.hard_deadline is None
                else self.hard_deadline.to_text()
            ),
            "planned_window": self.planned_window,
            "isolation_required": self.isolation_required,
            "unknown_factors": list(self.unknown_factors),
        }


@dataclass(frozen=True, slots=True)
class DiscoveryReadPolicy:
    policy_id: str
    purpose: str
    metadata_required_scope: str
    sensitive_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="discovery_read_policy_id")
        require_token(self.purpose, field="discovery_read_purpose")
        require_scope(
            self.metadata_required_scope,
            field="discovery_metadata_read_scope",
        )
        require_scope(
            self.sensitive_required_scope,
            field="discovery_sensitive_read_scope",
        )
        if self.metadata_required_scope == self.sensitive_required_scope:
            raise DiscoveryContractError(
                "discovery metadata and sensitive reads require distinct scopes"
            )
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise DiscoveryContractError(
                "discovery read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            require_token(principal_id, field="discovery_reader_principal")
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or not 1 <= self.max_results <= 10_000
        ):
            raise DiscoveryContractError(
                "discovery read maximum must be between 1 and 10000"
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
                "discovery reader principal is outside the read policy"
            )

    def require_limit(self, limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self.max_results
        ):
            raise PermissionError("discovery read limit exceeds the policy")


def sorted_reasons(values: Iterable[StructuredReason]) -> tuple[StructuredReason, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(item, StructuredReason) for item in values
    ):
        raise DiscoveryContractError("supporting reasons must be a typed tuple")
    result = tuple(sorted(values, key=lambda item: (item.code, item.digest)))
    if result != values or len(result) != len({item.digest for item in result}):
        raise DiscoveryContractError(
            "supporting reasons must be sorted and semantically unique"
        )
    return result


def is_active_disposition(value: LeadDispositionOutcome) -> bool:
    return value in ACTIVE_INCREMENT_3D_DISPOSITIONS


__all__ = [
    "ACTIVE_INCREMENT_3D_DISPOSITIONS",
    "DecisionTerminality",
    "DiscoveryAuthorityError",
    "DiscoveryContractError",
    "DiscoveryIdentifierReuse",
    "DiscoveryReadPolicy",
    "DiscoverySemanticCollision",
    "DiscoverySignalId",
    "DiscoveryStateError",
    "DiscoveryVersionConflict",
    "GATE_ALLOWED_REASON_BASES",
    "GateBasis",
    "GateDecisionId",
    "GateOutcome",
    "LeadDispositionDecisionId",
    "LeadDispositionOutcome",
    "NewsLeadId",
    "NextAction",
    "NextActionKind",
    "ObservableNewness",
    "ReasonBasisClass",
    "ReasonReference",
    "ScopeDisposition",
    "StructuredReason",
    "TimeValidity",
    "UrgencyBasis",
    "UrgencyRoute",
    "WatchConditionId",
    "is_active_disposition",
    "sorted_reasons",
]
