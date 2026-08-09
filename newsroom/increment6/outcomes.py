"""Pure Increment 6 outcome, reason and priority contract values.

These immutable values standardise vocabulary and canonical wire shapes only.
They do not admit work, write authority, persist state, invoke a model, enqueue
work, publish, or authorise any external effect.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Self

from newsroom.authority.canonical import canonical_json_bytes, validate_sha256_digest
from newsroom.discovery import LeadDispositionOutcome


OUTCOME_TAXONOMY_VERSION = "newsroom.increment6.outcomes.v1"
REASON_TAXONOMY_VERSION = "newsroom.increment6.reasons.v1"

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_MAX_TEXT_BYTES = 4_096


class OutcomeContractError(ValueError):
    """An Increment 6A1 contract value is malformed or incompatible."""


class ContractAuthority(StrEnum):
    NONE = "NONE"


class ContractEffect(StrEnum):
    NONE = "NONE"


class OutcomeFamily(StrEnum):
    CHECK = "CHECK"
    SIGNAL = "SIGNAL"
    LEAD = "LEAD"
    RELATIONSHIP = "RELATIONSHIP"
    CANDIDATE_HANDOFF = "CANDIDATE_HANDOFF"
    HEALTH = "HEALTH"
    COVERAGE = "COVERAGE"


class CanonicalOutcome(StrEnum):
    NO_WORK_DUE = "NO_WORK_DUE"
    PREFLIGHT_BLOCKED = "PREFLIGHT_BLOCKED"
    CHECK_UNCHANGED = "CHECK_UNCHANGED"
    CHECK_CHANGED = "CHECK_CHANGED"
    CHECK_PARTIAL = "CHECK_PARTIAL"
    CHECK_FAILED_RETRYABLE = "CHECK_FAILED_RETRYABLE"
    CHECK_FAILED_BLOCKING = "CHECK_FAILED_BLOCKING"
    CHECK_QUARANTINED = "CHECK_QUARANTINED"

    SIGNAL_SUPPRESSED_DUPLICATE = "SIGNAL_SUPPRESSED_DUPLICATE"
    SIGNAL_SUPPRESSED_NON_CHANGE = "SIGNAL_SUPPRESSED_NON_CHANGE"
    SIGNAL_REJECTED_CLEAR_EXCLUSION = "SIGNAL_REJECTED_CLEAR_EXCLUSION"
    SIGNAL_PROMOTED_TO_LEAD = "SIGNAL_PROMOTED_TO_LEAD"
    SIGNAL_OPERATIONAL_HOLD = "SIGNAL_OPERATIONAL_HOLD"

    LEAD_EDITORIAL_REJECT = "LEAD_EDITORIAL_REJECT"
    LEAD_QUEUED_FOR_TRIAGE = "LEAD_QUEUED_FOR_TRIAGE"
    LEAD_WATCH_DEFER = "LEAD_WATCH_DEFER"
    LEAD_ASSOCIATE_WITHOUT_CANDIDATE = "LEAD_ASSOCIATE_WITHOUT_CANDIDATE"
    LEAD_SUPPLEMENTAL_DISCOVERY = "LEAD_SUPPLEMENTAL_DISCOVERY"
    LEAD_OPERATIONAL_HOLD = "LEAD_OPERATIONAL_HOLD"
    LEAD_ADMIT_NEW_CANDIDATE = "LEAD_ADMIT_NEW_CANDIDATE"
    LEAD_ADMIT_DEVELOPMENT_CANDIDATE = "LEAD_ADMIT_DEVELOPMENT_CANDIDATE"
    LEAD_ADMIT_CORRECTION_CANDIDATE = "LEAD_ADMIT_CORRECTION_CANDIDATE"

    REL_SAME_STATE = "REL_SAME_STATE"
    REL_DEVELOPMENT_OF = "REL_DEVELOPMENT_OF"
    REL_CORRECTION_REVERSAL_OF = "REL_CORRECTION_REVERSAL_OF"
    REL_RELATED_DISTINCT = "REL_RELATED_DISTINCT"
    REL_NO_ADEQUATE_PRIOR_MATCH = "REL_NO_ADEQUATE_PRIOR_MATCH"
    REL_UNCERTAIN = "REL_UNCERTAIN"

    CANDIDATE_ADMITTED = "CANDIDATE_ADMITTED"
    CANDIDATE_ADMISSION_INVALID = "CANDIDATE_ADMISSION_INVALID"
    CANDIDATE_ADMISSION_BLOCKED = "CANDIDATE_ADMISSION_BLOCKED"
    CANDIDATE_VERSION_SUPERSEDED = "CANDIDATE_VERSION_SUPERSEDED"
    HANDOFF_PENDING = "HANDOFF_PENDING"
    HANDOFF_ACKNOWLEDGED = "HANDOFF_ACKNOWLEDGED"
    HANDOFF_RETRY_REQUIRED = "HANDOFF_RETRY_REQUIRED"
    HANDOFF_OPERATIONAL_HOLD = "HANDOFF_OPERATIONAL_HOLD"
    EVIDENCE_FEEDBACK_RECEIVED = "EVIDENCE_FEEDBACK_RECEIVED"

    HEALTH_HEALTHY = "HEALTH_HEALTHY"
    HEALTH_DEGRADED = "HEALTH_DEGRADED"
    HEALTH_STALE = "HEALTH_STALE"
    HEALTH_UNAVAILABLE = "HEALTH_UNAVAILABLE"
    HEALTH_QUARANTINED = "HEALTH_QUARANTINED"
    HEALTH_BLOCKED = "HEALTH_BLOCKED"
    HEALTH_UNKNOWN = "HEALTH_UNKNOWN"

    COVERAGE_AVAILABLE = "COVERAGE_AVAILABLE"
    COVERAGE_DEGRADED = "COVERAGE_DEGRADED"
    COVERAGE_BLOCKED = "COVERAGE_BLOCKED"
    COVERAGE_UNKNOWN = "COVERAGE_UNKNOWN"


_OUTCOME_FAMILIES: Mapping[CanonicalOutcome, OutcomeFamily] = MappingProxyType({
    **{
        item: OutcomeFamily.CHECK
        for item in CanonicalOutcome
        if item.value.startswith("CHECK_")
        or item is CanonicalOutcome.NO_WORK_DUE
        or item is CanonicalOutcome.PREFLIGHT_BLOCKED
    },
    **{
        item: OutcomeFamily.SIGNAL
        for item in CanonicalOutcome
        if item.value.startswith("SIGNAL_")
    },
    **{
        item: OutcomeFamily.LEAD
        for item in CanonicalOutcome
        if item.value.startswith("LEAD_")
    },
    **{
        item: OutcomeFamily.RELATIONSHIP
        for item in CanonicalOutcome
        if item.value.startswith("REL_")
    },
    **{
        item: OutcomeFamily.CANDIDATE_HANDOFF
        for item in CanonicalOutcome
        if item.value.startswith(("CANDIDATE_", "HANDOFF_", "EVIDENCE_"))
    },
    **{
        item: OutcomeFamily.HEALTH
        for item in CanonicalOutcome
        if item.value.startswith("HEALTH_")
    },
    **{
        item: OutcomeFamily.COVERAGE
        for item in CanonicalOutcome
        if item.value.startswith("COVERAGE_")
    },
})


def outcome_family(outcome: CanonicalOutcome) -> OutcomeFamily:
    if not isinstance(outcome, CanonicalOutcome):
        raise OutcomeContractError("outcome must be typed")
    return _OUTCOME_FAMILIES[outcome]


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


class ReasonFamily(StrEnum):
    AUTH = "AUTH"
    SCOPE = "SCOPE"
    CHANGE = "CHANGE"
    NOVELTY = "NOVELTY"
    UTILITY = "UTILITY"
    REL = "REL"
    TIME = "TIME"
    SOURCE = "SOURCE"
    RIGHTS = "RIGHTS"
    OPS = "OPS"
    CAPACITY = "CAPACITY"
    SEARCH = "SEARCH"
    EVAL = "EVAL"


class ReasonCode(StrEnum):
    AUTH_VERSION_CURRENT = "AUTH.VERSION_CURRENT"
    AUTH_PROFILE_CURRENT = "AUTH.PROFILE_CURRENT"
    AUTH_POLICY_CURRENT = "AUTH.POLICY_CURRENT"
    AUTH_STATE_STORE_AVAILABLE = "AUTH.STATE_STORE_AVAILABLE"
    AUTH_AUDIT_AVAILABLE = "AUTH.AUDIT_AVAILABLE"
    SCOPE_ACTIVE = "SCOPE.ACTIVE"
    SCOPE_BEST_EFFORT = "SCOPE.BEST_EFFORT"
    SCOPE_DEFERRED = "SCOPE.DEFERRED"
    SCOPE_EXCLUDED = "SCOPE.EXCLUDED"
    SCOPE_GEOGRAPHICALLY_QUALIFIED = "SCOPE.GEOGRAPHICALLY_QUALIFIED"
    CHANGE_UNCHANGED = "CHANGE.UNCHANGED"
    CHANGE_NEW_ITEM = "CHANGE.NEW_ITEM"
    CHANGE_REVISION = "CHANGE.REVISION"
    CHANGE_GENUINE_TRANSITION = "CHANGE.GENUINE_TRANSITION"
    CHANGE_WITHDRAWAL = "CHANGE.WITHDRAWAL"
    CHANGE_AGENDA_CHANGE = "CHANGE.AGENDA_CHANGE"
    CHANGE_LEAD_CREATED = "CHANGE.LEAD_CREATED"
    NOVELTY_EXACT_DUPLICATE = "NOVELTY.EXACT_DUPLICATE"
    NOVELTY_SAME_STATE_REPEAT = "NOVELTY.SAME_STATE_REPEAT"
    NOVELTY_LIKELY_DEVELOPMENT = "NOVELTY.LIKELY_DEVELOPMENT"
    NOVELTY_LIKELY_NEW_EVENT = "NOVELTY.LIKELY_NEW_EVENT"
    NOVELTY_INSUFFICIENT_INFORMATION = "NOVELTY.INSUFFICIENT_INFORMATION"
    UTILITY_ACTION = "UTILITY.ACTION"
    UTILITY_SAFETY = "UTILITY.SAFETY"
    UTILITY_SERVICE = "UTILITY.SERVICE"
    UTILITY_HOUSEHOLD = "UTILITY.HOUSEHOLD"
    UTILITY_TRAVEL = "UTILITY.TRAVEL"
    UTILITY_EDITORIAL_MATERIALITY = "UTILITY.EDITORIAL_MATERIALITY"
    REL_SAME_STATE = "REL.SAME_STATE"
    REL_DEVELOPMENT = "REL.DEVELOPMENT"
    REL_CORRECTION_REVERSAL = "REL.CORRECTION_REVERSAL"
    REL_RELATED_DISTINCT = "REL.RELATED_DISTINCT"
    REL_NO_ADEQUATE_PRIOR_MATCH = "REL.NO_ADEQUATE_PRIOR_MATCH"
    REL_UNCERTAIN = "REL.UNCERTAIN"
    TIME_URGENT = "TIME.URGENT"
    TIME_DEADLINE = "TIME.DEADLINE"
    TIME_PLANNED_WINDOW = "TIME.PLANNED_WINDOW"
    TIME_WATCH_REVIEW = "TIME.WATCH_REVIEW"
    TIME_STALE_WORK = "TIME.STALE_WORK"
    SOURCE_ROLE = "SOURCE.ROLE"
    SOURCE_DIRECTNESS = "SOURCE.DIRECTNESS"
    SOURCE_DEPENDENCY = "SOURCE.DEPENDENCY"
    SOURCE_IDENTITY = "SOURCE.IDENTITY"
    SOURCE_PUBLISHER_CHECK = "SOURCE.PUBLISHER_CHECK"
    RIGHTS_RETRIEVAL = "RIGHTS.RETRIEVAL"
    RIGHTS_RETENTION = "RIGHTS.RETENTION"
    RIGHTS_MODEL = "RIGHTS.MODEL"
    RIGHTS_QUERY_DATA = "RIGHTS.QUERY_DATA"
    RIGHTS_USE_SCOPE = "RIGHTS.USE_SCOPE"
    OPS_TRANSPORT = "OPS.TRANSPORT"
    OPS_PARSER = "OPS.PARSER"
    OPS_PARTIAL = "OPS.PARTIAL"
    OPS_RETRIEVAL = "OPS.RETRIEVAL"
    OPS_COLLISION = "OPS.COLLISION"
    OPS_MODEL = "OPS.MODEL"
    OPS_QUEUE = "OPS.QUEUE"
    OPS_HANDOFF = "OPS.HANDOFF"
    OPS_QUARANTINE = "OPS.QUARANTINE"
    OPS_STALE_STATE = "OPS.STALE_STATE"
    CAPACITY_SEARCH = "CAPACITY.SEARCH"
    CAPACITY_MODEL = "CAPACITY.MODEL"
    CAPACITY_QUEUE = "CAPACITY.QUEUE"
    CAPACITY_URGENT_RESERVE = "CAPACITY.URGENT_RESERVE"
    CAPACITY_REVIEWER = "CAPACITY.REVIEWER"
    SEARCH_ZERO_RESULTS = "SEARCH.ZERO_RESULTS"
    SEARCH_PARTIAL_RESULTS = "SEARCH.PARTIAL_RESULTS"
    SEARCH_PROVIDER_FAILURE = "SEARCH.PROVIDER_FAILURE"
    SEARCH_ALTERED_QUERY = "SEARCH.ALTERED_QUERY"
    SEARCH_COMPARATOR_ONLY = "SEARCH.COMPARATOR_ONLY"
    SEARCH_LEAD_ONLY = "SEARCH.LEAD_ONLY"
    EVAL_EXPOSURE = "EVAL.EXPOSURE"
    EVAL_REVIEWABILITY = "EVAL.REVIEWABILITY"
    EVAL_BLOCKER = "EVAL.BLOCKER"
    EVAL_SLICE_FAILURE = "EVAL.SLICE_FAILURE"
    EVAL_RELEASE_EVIDENCE = "EVAL.RELEASE_EVIDENCE"

    @property
    def family(self) -> ReasonFamily:
        return ReasonFamily(self.value.partition(".")[0])


class PriorityLane(StrEnum):
    CONTAINMENT = "CONTAINMENT"
    URGENT = "URGENT"
    TIME_SENSITIVE = "TIME_SENSITIVE"
    PLANNED_WINDOW = "PLANNED_WINDOW"
    ROUTINE = "ROUTINE"
    OPTIONAL_EVALUATION = "OPTIONAL_EVALUATION"

    @property
    def ordinal(self) -> int:
        return _LANE_ORDINALS[self]


_LANE_ORDINALS = {
    PriorityLane.CONTAINMENT: 1,
    PriorityLane.URGENT: 2,
    PriorityLane.TIME_SENSITIVE: 3,
    PriorityLane.PLANNED_WINDOW: 4,
    PriorityLane.ROUTINE: 5,
    PriorityLane.OPTIONAL_EVALUATION: 6,
}


class NextActionKind(StrEnum):
    CLOSE = "CLOSE"
    QUEUE_TRIAGE = "QUEUE_TRIAGE"
    RETRY = "RETRY"
    REVIEW = "REVIEW"
    WAIT_DEPENDENCY = "WAIT_DEPENDENCY"
    RESUME_ON_WATCH = "RESUME_ON_WATCH"
    HANDOFF = "HANDOFF"
    REQUEST_SUPPLEMENTAL_DISCOVERY = "REQUEST_SUPPLEMENTAL_DISCOVERY"


class CanonicalNextAction(StrEnum):
    """Closed action vocabulary; action codes cannot become private aliases."""

    CLOSE_DECISION = "CLOSE_DECISION"
    QUEUE_FOR_TRIAGE = "QUEUE_FOR_TRIAGE"
    RETRY_SAME_REQUEST = "RETRY_SAME_REQUEST"
    REQUEST_REVIEW = "REQUEST_REVIEW"
    WAIT_FOR_DEPENDENCY = "WAIT_FOR_DEPENDENCY"
    AWAIT_WATCH_CONDITION = "AWAIT_WATCH_CONDITION"
    HANDOFF_FOR_EVALUATION = "HANDOFF_FOR_EVALUATION"
    REQUEST_SUPPLEMENTAL_DISCOVERY = "REQUEST_SUPPLEMENTAL_DISCOVERY"

    @property
    def kind(self) -> NextActionKind:
        return _NEXT_ACTION_KINDS[self]


_NEXT_ACTION_KINDS = {
    CanonicalNextAction.CLOSE_DECISION: NextActionKind.CLOSE,
    CanonicalNextAction.QUEUE_FOR_TRIAGE: NextActionKind.QUEUE_TRIAGE,
    CanonicalNextAction.RETRY_SAME_REQUEST: NextActionKind.RETRY,
    CanonicalNextAction.REQUEST_REVIEW: NextActionKind.REVIEW,
    CanonicalNextAction.WAIT_FOR_DEPENDENCY: NextActionKind.WAIT_DEPENDENCY,
    CanonicalNextAction.AWAIT_WATCH_CONDITION: NextActionKind.RESUME_ON_WATCH,
    CanonicalNextAction.HANDOFF_FOR_EVALUATION: NextActionKind.HANDOFF,
    CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY: (
        NextActionKind.REQUEST_SUPPLEMENTAL_DISCOVERY
    ),
}


def _require_exact_fields(
    value: Mapping[str, object], *, required: frozenset[str], field: str
) -> None:
    if set(value) != required:
        raise OutcomeContractError(f"{field} fields must be exactly {sorted(required)}")


def _require_token(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise OutcomeContractError(f"{field} must be canonical token text")
    return value


def _require_text(value: object, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise OutcomeContractError(f"{field} must be text")
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise OutcomeContractError(f"{field} exceeds {_MAX_TEXT_BYTES} bytes")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise OutcomeContractError(f"{field} contains control characters")
    return value


def _enum(enum_type: type[Any], value: object, *, field: str) -> Any:
    if not isinstance(value, str):
        raise OutcomeContractError(f"{field} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise OutcomeContractError(f"unknown {field}: {value}") from exc


@dataclass(frozen=True, slots=True)
class ReasonReference:
    reference_type: str
    identifier: str
    digest: str | None = None

    def __post_init__(self) -> None:
        _require_token(self.reference_type, field="reason reference type")
        _require_text(self.identifier, field="reason reference identifier")
        if self.digest is not None:
            try:
                validate_sha256_digest(self.digest, field="reason reference digest")
            except ValueError as exc:
                raise OutcomeContractError(str(exc)) from exc

    def canonical_value(self) -> dict[str, object]:
        return {
            "reference_type": self.reference_type,
            "identifier": self.identifier,
            "digest": self.digest,
        }

    @classmethod
    def from_mapping(cls, value: object) -> Self:
        if not isinstance(value, Mapping):
            raise OutcomeContractError("reason reference must be an object")
        _require_exact_fields(
            value,
            required=frozenset({"reference_type", "identifier", "digest"}),
            field="reason reference",
        )
        digest = value["digest"]
        if digest is not None and not isinstance(digest, str):
            raise OutcomeContractError("reason reference digest must be text or null")
        return cls(
            reference_type=_require_token(
                value["reference_type"], field="reason reference type"
            ),
            identifier=_require_text(
                value["identifier"], field="reason reference identifier"
            ),
            digest=digest,
        )


def _reference_key(value: ReasonReference) -> tuple[str, str, str]:
    return (value.reference_type, value.identifier, value.digest or "")


@dataclass(frozen=True, slots=True)
class StructuredReason:
    SCHEMA_VERSION: ClassVar[str] = REASON_TAXONOMY_VERSION

    code: ReasonCode
    basis: ReasonBasisClass
    references: tuple[ReasonReference, ...]
    explanation: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise OutcomeContractError("unsupported reason schema version")
        if not isinstance(self.code, ReasonCode):
            raise OutcomeContractError("reason code must be typed")
        if not isinstance(self.basis, ReasonBasisClass):
            raise OutcomeContractError("reason basis must be typed")
        if (
            not isinstance(self.references, tuple)
            or not self.references
            or any(not isinstance(item, ReasonReference) for item in self.references)
        ):
            raise OutcomeContractError(
                "structured reason requires typed exact references"
            )
        keys = tuple(_reference_key(item) for item in self.references)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise OutcomeContractError("reason references must be sorted and unique")
        _require_text(self.explanation, field="reason explanation")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "code": self.code.value,
            "basis": self.basis.value,
            "references": [item.canonical_value() for item in self.references],
            "explanation": self.explanation,
        }

    @classmethod
    def from_mapping(cls, value: object) -> Self:
        if not isinstance(value, Mapping):
            raise OutcomeContractError("structured reason must be an object")
        _require_exact_fields(
            value,
            required=frozenset(
                {"schema_version", "code", "basis", "references", "explanation"}
            ),
            field="structured reason",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise OutcomeContractError("unsupported reason schema version")
        raw_references = value["references"]
        if not isinstance(raw_references, list):
            raise OutcomeContractError("reason references must be an array")
        return cls(
            schema_version=cls.SCHEMA_VERSION,
            code=_enum(ReasonCode, value["code"], field="reason code"),
            basis=_enum(ReasonBasisClass, value["basis"], field="reason basis"),
            references=tuple(
                ReasonReference.from_mapping(item) for item in raw_references
            ),
            explanation=_require_text(value["explanation"], field="reason explanation"),
        )

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        reason = cls.from_mapping(_decode_canonical(raw))
        if reason.canonical_bytes != raw:
            raise OutcomeContractError("structured reason is not canonical JSON")
        return reason


def _reason_key(value: StructuredReason) -> bytes:
    return canonical_json_bytes(value.canonical_value())


@dataclass(frozen=True, slots=True)
class NextAction:
    kind: NextActionKind
    action_code: CanonicalNextAction
    condition_reference: str | None = None
    instructions: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NextActionKind):
            raise OutcomeContractError("next action kind must be typed")
        if not isinstance(self.action_code, CanonicalNextAction):
            raise OutcomeContractError("next action code must be typed")
        if self.action_code.kind is not self.kind:
            raise OutcomeContractError("next action code does not match its kind")
        if self.condition_reference is not None:
            _require_text(
                self.condition_reference,
                field="next action condition reference",
            )
        _require_text(
            self.instructions,
            field="next action instructions",
            allow_empty=True,
        )
        if self.kind in {
            NextActionKind.RETRY,
            NextActionKind.REVIEW,
            NextActionKind.WAIT_DEPENDENCY,
            NextActionKind.RESUME_ON_WATCH,
            NextActionKind.REQUEST_SUPPLEMENTAL_DISCOVERY,
        } and self.condition_reference is None:
            raise OutcomeContractError(
                "pending next action requires a condition reference"
            )
        if self.kind is NextActionKind.CLOSE and self.condition_reference is not None:
            raise OutcomeContractError(
                "close action cannot retain a condition reference"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "action_code": self.action_code.value,
            "condition_reference": self.condition_reference,
            "instructions": self.instructions,
        }

    @classmethod
    def from_mapping(cls, value: object) -> Self:
        if not isinstance(value, Mapping):
            raise OutcomeContractError("next action must be an object")
        _require_exact_fields(
            value,
            required=frozenset(
                {"kind", "action_code", "condition_reference", "instructions"}
            ),
            field="next action",
        )
        condition = value["condition_reference"]
        if condition is not None and not isinstance(condition, str):
            raise OutcomeContractError(
                "next action condition reference must be text or null"
            )
        return cls(
            kind=_enum(NextActionKind, value["kind"], field="next action kind"),
            action_code=_enum(
                CanonicalNextAction,
                value["action_code"],
                field="next action code",
            ),
            condition_reference=condition,
            instructions=_require_text(
                value["instructions"],
                field="next action instructions",
                allow_empty=True,
            ),
        )


_PENDING_OUTCOMES = frozenset(
    {
        CanonicalOutcome.PREFLIGHT_BLOCKED,
        CanonicalOutcome.SIGNAL_OPERATIONAL_HOLD,
        CanonicalOutcome.LEAD_QUEUED_FOR_TRIAGE,
        CanonicalOutcome.LEAD_WATCH_DEFER,
        CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY,
        CanonicalOutcome.CANDIDATE_ADMISSION_BLOCKED,
        CanonicalOutcome.HANDOFF_PENDING,
        CanonicalOutcome.HANDOFF_OPERATIONAL_HOLD,
    }
)
_RETRYABLE_OUTCOMES = frozenset(
    {
        CanonicalOutcome.CHECK_FAILED_RETRYABLE,
        CanonicalOutcome.HANDOFF_RETRY_REQUIRED,
    }
)
_OCCURRENCE_OUTCOMES = frozenset(
    {
        *(
            item
            for item in CanonicalOutcome
            if outcome_family(item) is OutcomeFamily.RELATIONSHIP
        ),
        *(
            item
            for item in CanonicalOutcome
            if outcome_family(item) is OutcomeFamily.HEALTH
        ),
        *(
            item
            for item in CanonicalOutcome
            if outcome_family(item) is OutcomeFamily.COVERAGE
        ),
        CanonicalOutcome.CHECK_CHANGED,
        CanonicalOutcome.CHECK_PARTIAL,
        CanonicalOutcome.EVIDENCE_FEEDBACK_RECEIVED,
    }
)


def _validate_outcome_terminality(
    outcome: CanonicalOutcome, terminality: DecisionTerminality
) -> None:
    if outcome is CanonicalOutcome.LEAD_OPERATIONAL_HOLD:
        permitted = {
            DecisionTerminality.PENDING_CONDITION,
            DecisionTerminality.RETRYABLE_SAME_REQUEST,
        }
    elif outcome in _PENDING_OUTCOMES:
        permitted = {DecisionTerminality.PENDING_CONDITION}
    elif outcome in _RETRYABLE_OUTCOMES:
        permitted = {DecisionTerminality.RETRYABLE_SAME_REQUEST}
    elif outcome in _OCCURRENCE_OUTCOMES:
        permitted = {
            DecisionTerminality.OCCURRENCE_ONLY,
            DecisionTerminality.TERMINAL_EXACT_VERSION,
        }
    else:
        permitted = {DecisionTerminality.TERMINAL_EXACT_VERSION}
    if terminality not in permitted:
        raise OutcomeContractError(
            f"{outcome.value} does not permit terminality {terminality.value}"
        )


class _NoAuthorityContract:
    """Shared explicit non-authority semantics for pure contract values."""

    @property
    def authorises_eligibility(self) -> bool:
        return False

    @property
    def authorises_persistence(self) -> bool:
        return False

    @property
    def authorises_external_effect(self) -> bool:
        return False

    @property
    def authorises_publication(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class _DiscoveryDispositionMapping(_NoAuthorityContract):
    """One-to-one interpretation of a retained Discovery disposition."""

    source_outcome: str
    outcome: CanonicalOutcome
    terminality: DecisionTerminality
    next_action: CanonicalNextAction
    requires_exact_watch_condition: bool
    requires_bounded_supplemental_action: bool
    authority: ContractAuthority = ContractAuthority.NONE
    effect: ContractEffect = ContractEffect.NONE

    def __post_init__(self) -> None:
        _require_token(self.source_outcome, field="Discovery source outcome")
        if not isinstance(self.outcome, CanonicalOutcome):
            raise OutcomeContractError("mapped outcome must be typed")
        if not isinstance(self.terminality, DecisionTerminality):
            raise OutcomeContractError("mapped terminality must be typed")
        if not isinstance(self.next_action, CanonicalNextAction):
            raise OutcomeContractError("mapped next action must be typed")
        if self.authority is not ContractAuthority.NONE:
            raise OutcomeContractError("Discovery mapping cannot carry authority")
        if self.effect is not ContractEffect.NONE:
            raise OutcomeContractError("Discovery mapping cannot carry an effect")


WATCH_CONDITION_MAPPING: Mapping[
    LeadDispositionOutcome, _DiscoveryDispositionMapping
] = MappingProxyType(
    {
        LeadDispositionOutcome.WATCH_DEFER: _DiscoveryDispositionMapping(
            source_outcome=LeadDispositionOutcome.WATCH_DEFER.value,
            outcome=CanonicalOutcome.LEAD_WATCH_DEFER,
            terminality=DecisionTerminality.PENDING_CONDITION,
            next_action=CanonicalNextAction.AWAIT_WATCH_CONDITION,
            requires_exact_watch_condition=True,
            requires_bounded_supplemental_action=False,
        )
    }
)

SUPPLEMENTAL_ACTION_MAPPING: Mapping[
    LeadDispositionOutcome, _DiscoveryDispositionMapping
] = MappingProxyType(
    {
        LeadDispositionOutcome.SUPPLEMENTAL_DISCOVERY: _DiscoveryDispositionMapping(
            source_outcome=LeadDispositionOutcome.SUPPLEMENTAL_DISCOVERY.value,
            outcome=CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY,
            terminality=DecisionTerminality.PENDING_CONDITION,
            next_action=CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY,
            requires_exact_watch_condition=False,
            requires_bounded_supplemental_action=True,
        )
    }
)

_DISCOVERY_LEAD_SEMANTIC_MATRIX: Mapping[
    CanonicalOutcome,
    frozenset[tuple[DecisionTerminality, CanonicalNextAction]],
] = MappingProxyType(
    {
        CanonicalOutcome.LEAD_QUEUED_FOR_TRIAGE: frozenset(
            {
                (
                    DecisionTerminality.PENDING_CONDITION,
                    CanonicalNextAction.QUEUE_FOR_TRIAGE,
                )
            }
        ),
        CanonicalOutcome.LEAD_EDITORIAL_REJECT: frozenset(
            {
                (
                    DecisionTerminality.TERMINAL_EXACT_VERSION,
                    CanonicalNextAction.CLOSE_DECISION,
                )
            }
        ),
        CanonicalOutcome.LEAD_WATCH_DEFER: frozenset(
            {
                (
                    WATCH_CONDITION_MAPPING[
                        LeadDispositionOutcome.WATCH_DEFER
                    ].terminality,
                    WATCH_CONDITION_MAPPING[
                        LeadDispositionOutcome.WATCH_DEFER
                    ].next_action,
                )
            }
        ),
        CanonicalOutcome.LEAD_ASSOCIATE_WITHOUT_CANDIDATE: frozenset(
            {
                (
                    DecisionTerminality.TERMINAL_EXACT_VERSION,
                    CanonicalNextAction.CLOSE_DECISION,
                )
            }
        ),
        CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY: frozenset(
            {
                (
                    SUPPLEMENTAL_ACTION_MAPPING[
                        LeadDispositionOutcome.SUPPLEMENTAL_DISCOVERY
                    ].terminality,
                    SUPPLEMENTAL_ACTION_MAPPING[
                        LeadDispositionOutcome.SUPPLEMENTAL_DISCOVERY
                    ].next_action,
                )
            }
        ),
        CanonicalOutcome.LEAD_OPERATIONAL_HOLD: frozenset(
            {
                (
                    DecisionTerminality.PENDING_CONDITION,
                    CanonicalNextAction.RETRY_SAME_REQUEST,
                ),
                (
                    DecisionTerminality.PENDING_CONDITION,
                    CanonicalNextAction.REQUEST_REVIEW,
                ),
                (
                    DecisionTerminality.PENDING_CONDITION,
                    CanonicalNextAction.WAIT_FOR_DEPENDENCY,
                ),
                (
                    DecisionTerminality.RETRYABLE_SAME_REQUEST,
                    CanonicalNextAction.RETRY_SAME_REQUEST,
                ),
            }
        ),
        **{
            outcome: frozenset(
                {
                    (
                        DecisionTerminality.TERMINAL_EXACT_VERSION,
                        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
                    )
                }
            )
            for outcome in (
                CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
                CanonicalOutcome.LEAD_ADMIT_DEVELOPMENT_CANDIDATE,
                CanonicalOutcome.LEAD_ADMIT_CORRECTION_CANDIDATE,
            )
        },
    }
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if name in value:
            raise OutcomeContractError(f"duplicate JSON object name: {name}")
        value[name] = item
    return value


def _decode_canonical(raw: bytes) -> Mapping[str, object]:
    if not isinstance(raw, bytes):
        raise OutcomeContractError("canonical input must be immutable bytes")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except OutcomeContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OutcomeContractError("canonical input must be valid UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise OutcomeContractError("canonical input must contain one object")
    return value


@dataclass(frozen=True, slots=True)
class OutcomeSelection(_NoAuthorityContract):
    """A strict, non-authoritative selection of outcome, reasons and action."""

    SCHEMA_VERSION: ClassVar[str] = OUTCOME_TAXONOMY_VERSION

    outcome: CanonicalOutcome
    terminality: DecisionTerminality
    primary_reason: StructuredReason
    supporting_reasons: tuple[StructuredReason, ...]
    next_action: NextAction | None
    schema_version: str = SCHEMA_VERSION
    outcome_taxonomy_version: str = OUTCOME_TAXONOMY_VERSION
    reason_taxonomy_version: str = REASON_TAXONOMY_VERSION
    authority: ContractAuthority = ContractAuthority.NONE
    effect: ContractEffect = ContractEffect.NONE

    def __post_init__(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise OutcomeContractError("unsupported outcome-selection schema version")
        if self.outcome_taxonomy_version != OUTCOME_TAXONOMY_VERSION:
            raise OutcomeContractError("unsupported outcome taxonomy version")
        if self.reason_taxonomy_version != REASON_TAXONOMY_VERSION:
            raise OutcomeContractError("unsupported reason taxonomy version")
        if self.authority is not ContractAuthority.NONE:
            raise OutcomeContractError("outcome selection cannot carry authority")
        if self.effect is not ContractEffect.NONE:
            raise OutcomeContractError("outcome selection cannot carry an effect")
        if not isinstance(self.outcome, CanonicalOutcome):
            raise OutcomeContractError("outcome must be typed")
        if not isinstance(self.terminality, DecisionTerminality):
            raise OutcomeContractError("terminality must be typed")
        if not isinstance(self.primary_reason, StructuredReason):
            raise OutcomeContractError("primary reason must be typed")
        if (
            not isinstance(self.supporting_reasons, tuple)
            or any(
                not isinstance(item, StructuredReason)
                for item in self.supporting_reasons
            )
        ):
            raise OutcomeContractError("supporting reasons must be a typed tuple")
        reason_keys = tuple(_reason_key(item) for item in self.supporting_reasons)
        if reason_keys != tuple(sorted(reason_keys)):
            raise OutcomeContractError("supporting reasons must be canonically sorted")
        if len(reason_keys) != len(set(reason_keys)) or _reason_key(
            self.primary_reason
        ) in set(reason_keys):
            raise OutcomeContractError(
                "primary and supporting reasons must not duplicate"
            )
        if self.next_action is not None and not isinstance(
            self.next_action, NextAction
        ):
            raise OutcomeContractError("next action must be typed")
        _validate_outcome_terminality(self.outcome, self.terminality)
        if self.terminality is DecisionTerminality.PENDING_CONDITION:
            if self.next_action is None or self.next_action.kind not in {
                NextActionKind.QUEUE_TRIAGE,
                NextActionKind.RETRY,
                NextActionKind.REVIEW,
                NextActionKind.WAIT_DEPENDENCY,
                NextActionKind.RESUME_ON_WATCH,
                NextActionKind.REQUEST_SUPPLEMENTAL_DISCOVERY,
            }:
                raise OutcomeContractError(
                    "pending outcome requires a pending next action"
                )
        if self.terminality is DecisionTerminality.RETRYABLE_SAME_REQUEST:
            if (
                self.next_action is None
                or self.next_action.kind is not NextActionKind.RETRY
            ):
                raise OutcomeContractError(
                    "retryable outcome requires a retry next action"
                )
        if outcome_family(self.outcome) is OutcomeFamily.LEAD:
            if self.next_action is None:
                raise OutcomeContractError(
                    "Lead outcome requires its canonical next action"
                )
            permitted = _DISCOVERY_LEAD_SEMANTIC_MATRIX[self.outcome]
            if (self.terminality, self.next_action.action_code) not in permitted:
                raise OutcomeContractError(
                    f"{self.outcome.value} does not permit next action "
                    f"{self.next_action.action_code.value} with terminality "
                    f"{self.terminality.value}"
                )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "outcome_taxonomy_version": self.outcome_taxonomy_version,
            "reason_taxonomy_version": self.reason_taxonomy_version,
            "authority": self.authority.value,
            "effect": self.effect.value,
            "outcome": self.outcome.value,
            "terminality": self.terminality.value,
            "primary_reason": self.primary_reason.canonical_value(),
            "supporting_reasons": [
                item.canonical_value() for item in self.supporting_reasons
            ],
            "next_action": (
                None if self.next_action is None else self.next_action.canonical_value()
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> Self:
        if not isinstance(value, Mapping):
            raise OutcomeContractError("outcome selection must be an object")
        _require_exact_fields(
            value,
            required=frozenset(
                {
                    "schema_version",
                    "outcome_taxonomy_version",
                    "reason_taxonomy_version",
                    "authority",
                    "effect",
                    "outcome",
                    "terminality",
                    "primary_reason",
                    "supporting_reasons",
                    "next_action",
                }
            ),
            field="outcome selection",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise OutcomeContractError("unsupported outcome-selection schema version")
        if value["outcome_taxonomy_version"] != OUTCOME_TAXONOMY_VERSION:
            raise OutcomeContractError("unsupported outcome taxonomy version")
        if value["reason_taxonomy_version"] != REASON_TAXONOMY_VERSION:
            raise OutcomeContractError("unsupported reason taxonomy version")
        if value["authority"] != ContractAuthority.NONE.value:
            raise OutcomeContractError("outcome selection cannot carry authority")
        if value["effect"] != ContractEffect.NONE.value:
            raise OutcomeContractError("outcome selection cannot carry an effect")
        raw_supporting = value["supporting_reasons"]
        if not isinstance(raw_supporting, list):
            raise OutcomeContractError("supporting reasons must be an array")
        raw_action = value["next_action"]
        return cls(
            schema_version=cls.SCHEMA_VERSION,
            outcome_taxonomy_version=OUTCOME_TAXONOMY_VERSION,
            reason_taxonomy_version=REASON_TAXONOMY_VERSION,
            authority=ContractAuthority.NONE,
            effect=ContractEffect.NONE,
            outcome=_enum(CanonicalOutcome, value["outcome"], field="outcome"),
            terminality=_enum(
                DecisionTerminality, value["terminality"], field="terminality"
            ),
            primary_reason=StructuredReason.from_mapping(value["primary_reason"]),
            supporting_reasons=tuple(
                StructuredReason.from_mapping(item) for item in raw_supporting
            ),
            next_action=(
                None if raw_action is None else NextAction.from_mapping(raw_action)
            ),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        selection = cls.from_mapping(_decode_canonical(raw))
        if selection.canonical_bytes != raw:
            raise OutcomeContractError("outcome selection is not canonical JSON")
        return selection


@dataclass(frozen=True, slots=True)
class PrioritySelection(_NoAuthorityContract):
    """A lane assignment only; it grants neither eligibility nor authority."""

    SCHEMA_VERSION: ClassVar[str] = OUTCOME_TAXONOMY_VERSION

    work_identity: str
    work_version: str
    lane: PriorityLane
    basis_references: tuple[ReasonReference, ...]
    schema_version: str = SCHEMA_VERSION
    authority: ContractAuthority = ContractAuthority.NONE
    effect: ContractEffect = ContractEffect.NONE

    def __post_init__(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise OutcomeContractError("unsupported priority-selection schema version")
        if self.authority is not ContractAuthority.NONE:
            raise OutcomeContractError("priority selection cannot carry authority")
        if self.effect is not ContractEffect.NONE:
            raise OutcomeContractError("priority selection cannot carry an effect")
        _require_token(self.work_identity, field="work identity")
        _require_token(self.work_version, field="work version")
        if not isinstance(self.lane, PriorityLane):
            raise OutcomeContractError("priority lane must be typed")
        if (
            not isinstance(self.basis_references, tuple)
            or not self.basis_references
            or any(
                not isinstance(item, ReasonReference)
                for item in self.basis_references
            )
        ):
            raise OutcomeContractError("priority requires typed exact basis references")
        keys = tuple(_reference_key(item) for item in self.basis_references)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise OutcomeContractError(
                "priority basis references must be sorted and unique"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority.value,
            "effect": self.effect.value,
            "work_identity": self.work_identity,
            "work_version": self.work_version,
            "lane": self.lane.value,
            "lane_ordinal": self.lane.ordinal,
            "basis_references": [
                item.canonical_value() for item in self.basis_references
            ],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> Self:
        if not isinstance(value, Mapping):
            raise OutcomeContractError("priority selection must be an object")
        _require_exact_fields(
            value,
            required=frozenset(
                {
                    "schema_version",
                    "authority",
                    "effect",
                    "work_identity",
                    "work_version",
                    "lane",
                    "lane_ordinal",
                    "basis_references",
                }
            ),
            field="priority selection",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise OutcomeContractError("unsupported priority-selection schema version")
        if value["authority"] != ContractAuthority.NONE.value:
            raise OutcomeContractError("priority selection cannot carry authority")
        if value["effect"] != ContractEffect.NONE.value:
            raise OutcomeContractError("priority selection cannot carry an effect")
        lane = _enum(PriorityLane, value["lane"], field="priority lane")
        ordinal = value["lane_ordinal"]
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise OutcomeContractError("priority lane ordinal must be an integer")
        if ordinal != lane.ordinal:
            raise OutcomeContractError("priority lane ordinal does not match its lane")
        raw_references = value["basis_references"]
        if not isinstance(raw_references, list):
            raise OutcomeContractError("priority basis references must be an array")
        return cls(
            schema_version=cls.SCHEMA_VERSION,
            authority=ContractAuthority.NONE,
            effect=ContractEffect.NONE,
            work_identity=_require_token(value["work_identity"], field="work identity"),
            work_version=_require_token(value["work_version"], field="work version"),
            lane=lane,
            basis_references=tuple(
                ReasonReference.from_mapping(item) for item in raw_references
            ),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        selection = cls.from_mapping(_decode_canonical(raw))
        if selection.canonical_bytes != raw:
            raise OutcomeContractError("priority selection is not canonical JSON")
        return selection


TRIAGE_OUTCOME = CanonicalOutcome
TRIAGE_REASON_CODE = ReasonCode
PRIORITY_LANE = PriorityLane
CANONICAL_NEXT_ACTION = CanonicalNextAction
DECISION_TERMINALITY = DecisionTerminality


__all__ = [
    "TRIAGE_OUTCOME",
    "TRIAGE_REASON_CODE",
    "PRIORITY_LANE",
    "CANONICAL_NEXT_ACTION",
    "DECISION_TERMINALITY",
    "WATCH_CONDITION_MAPPING",
    "SUPPLEMENTAL_ACTION_MAPPING",
    "OUTCOME_TAXONOMY_VERSION",
    "REASON_TAXONOMY_VERSION",
    "CanonicalOutcome",
    "CanonicalNextAction",
    "ContractAuthority",
    "ContractEffect",
    "DecisionTerminality",
    "NextAction",
    "NextActionKind",
    "OutcomeContractError",
    "OutcomeFamily",
    "OutcomeSelection",
    "PriorityLane",
    "PrioritySelection",
    "ReasonBasisClass",
    "ReasonCode",
    "ReasonFamily",
    "ReasonReference",
    "StructuredReason",
    "outcome_family",
]
