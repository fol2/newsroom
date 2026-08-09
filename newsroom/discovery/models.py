from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.types import UtcTimestamp, require_token
from newsroom.checks import (
    CheckOutcomeId,
    CoverageBasis,
    ObservableTransitionId,
    ObservableTransitionKind,
    OperationalFindingId,
)
from newsroom.checks.types import bounded_text, require_uuid_text, sorted_unique_text
from newsroom.sources import (
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    PortfolioFunction,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceDependency,
    SourceItemId,
    SourceRevisionId,
    SourceRoleAssignment,
    VersionedPolicyRef,
    sorted_dependencies,
    sorted_role_assignments,
)

from .types import (
    DecisionTerminality,
    DiscoveryContractError,
    DiscoverySignalId,
    GATE_ALLOWED_REASON_BASES,
    INCREMENT_3D_ALLOWED_REASON_BASES,
    GateBasis,
    GateDecisionId,
    GateOutcome,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    NewsLeadId,
    NextAction,
    NextActionKind,
    ObservableNewness,
    ScopeDisposition,
    StructuredReason,
    UrgencyBasis,
    WatchConditionId,
    deterministic_gate_outcome,
    is_active_disposition,
    sorted_reasons,
)

MAX_NEWS_LEAD_SOURCE_DEPENDENCIES = 160
MAX_NEWS_LEAD_CANONICAL_BYTES = 384 * 1_024


def _require_idempotency_key(value: str) -> str:
    return bounded_text(value, field="idempotency_key", maximum_bytes=256)


def _require_policy(value: VersionedPolicyRef, *, field: str) -> None:
    if not isinstance(value, VersionedPolicyRef):
        raise DiscoveryContractError(f"{field} must be a versioned policy reference")


def _require_utc(value: UtcTimestamp, *, field: str) -> None:
    if not isinstance(value, UtcTimestamp):
        raise DiscoveryContractError(f"{field} must be typed UTC")


@dataclass(frozen=True, slots=True)
class DiscoverySignalRequest:
    signal_id: DiscoverySignalId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    item_id: SourceItemId
    revision_id: SourceRevisionId
    representation_id: DiscoveryRepresentationId
    check_outcome_id: CheckOutcomeId
    occurrence_id: DiscoveryOccurrenceId
    transition_id: ObservableTransitionId
    purpose: str
    discriminator: str
    admission_policy: VersionedPolicyRef
    incomplete: bool
    operational_finding_ids: tuple[OperationalFindingId, ...]
    admitted_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        typed = (
            (self.signal_id, DiscoverySignalId, "Signal identity"),
            (self.definition_id, SourceDefinitionId, "source definition"),
            (
                self.definition_version_id,
                SourceDefinitionVersionId,
                "source definition version",
            ),
            (self.item_id, SourceItemId, "source item"),
            (self.revision_id, SourceRevisionId, "source revision"),
            (
                self.representation_id,
                DiscoveryRepresentationId,
                "discovery representation",
            ),
            (self.check_outcome_id, CheckOutcomeId, "Check Outcome"),
            (self.occurrence_id, DiscoveryOccurrenceId, "Occurrence"),
            (self.transition_id, ObservableTransitionId, "Observable Transition"),
        )
        for value, expected, field in typed:
            if not isinstance(value, expected):
                raise DiscoveryContractError(f"{field} identity must be typed")
        require_token(self.purpose, field="signal_purpose")
        require_token(self.discriminator, field="signal_discriminator")
        _require_policy(self.admission_policy, field="signal_admission_policy")
        if not isinstance(self.incomplete, bool):
            raise DiscoveryContractError("Signal incomplete flag must be boolean")
        if (
            not isinstance(self.operational_finding_ids, tuple)
            or any(
                not isinstance(item, OperationalFindingId)
                for item in self.operational_finding_ids
            )
            or self.operational_finding_ids
            != tuple(sorted(set(self.operational_finding_ids), key=str))
        ):
            raise DiscoveryContractError(
                "Signal Finding identities must be a sorted unique typed tuple"
            )
        if self.incomplete != bool(self.operational_finding_ids):
            raise DiscoveryContractError(
                "Signal incompleteness and Operational Finding lineage must agree"
            )
        _require_utc(self.admitted_at, field="Signal admission time")
        _require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "signal_id": str(self.signal_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "item_id": str(self.item_id),
            "revision_id": str(self.revision_id),
            "representation_id": str(self.representation_id),
            "check_outcome_id": str(self.check_outcome_id),
            "occurrence_id": str(self.occurrence_id),
            "transition_id": str(self.transition_id),
            "purpose": self.purpose,
            "discriminator": self.discriminator,
            "admission_policy": self.admission_policy.canonical_value(),
            "incomplete": self.incomplete,
            "operational_finding_ids": [
                str(item) for item in self.operational_finding_ids
            ],
            "admitted_at": self.admitted_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        value = self.canonical_value()
        value.pop("signal_id")
        value.pop("admitted_at")
        # Operational degradation is retained lineage, not Signal identity.
        # The same exact source transition/purpose cannot allocate a second
        # Signal merely because its associated Finding set is represented
        # differently by a later caller.
        value.pop("incomplete")
        value.pop("operational_finding_ids")
        return digest_canonical(value)


@dataclass(frozen=True, slots=True)
class GateDecisionRequest:
    decision_id: GateDecisionId
    signal_id: DiscoverySignalId
    decision_ordinal: int
    previous_decision_id: GateDecisionId | None
    evaluated_definition_version_id: SourceDefinitionVersionId
    coverage: CoverageBasis
    rights_decision_id: str
    rights_policy_version: str
    signal_admission_policy: VersionedPolicyRef
    gate_policy: VersionedPolicyRef
    duplicate_policy: VersionedPolicyRef
    newness_policy: VersionedPolicyRef
    time_validity_policy: VersionedPolicyRef
    exclusion_policy: VersionedPolicyRef
    basis: GateBasis
    outcome: GateOutcome
    terminality: DecisionTerminality
    primary_reason: StructuredReason
    supporting_reasons: tuple[StructuredReason, ...]
    reason_taxonomy_version: str
    outcome_taxonomy_version: str
    next_action: NextAction | None
    decided_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, GateDecisionId):
            raise DiscoveryContractError("Gate Decision identity must be typed")
        if not isinstance(self.signal_id, DiscoverySignalId):
            raise DiscoveryContractError("Gate Signal identity must be typed")
        if (
            isinstance(self.decision_ordinal, bool)
            or not isinstance(self.decision_ordinal, int)
            or not 1 <= self.decision_ordinal <= 1_000_000
        ):
            raise DiscoveryContractError("Gate Decision ordinal is invalid")
        if self.previous_decision_id is not None and not isinstance(
            self.previous_decision_id,
            GateDecisionId,
        ):
            raise DiscoveryContractError("previous Gate Decision must be typed")
        if self.decision_ordinal == 1:
            if self.previous_decision_id is not None:
                raise DiscoveryContractError(
                    "first Gate Decision cannot name a predecessor"
                )
        elif self.previous_decision_id is None:
            raise DiscoveryContractError(
                "later Gate Decision requires exact predecessor identity"
            )
        if self.previous_decision_id == self.decision_id:
            raise DiscoveryContractError("Gate Decision cannot precede itself")
        if not isinstance(
            self.evaluated_definition_version_id,
            SourceDefinitionVersionId,
        ):
            raise DiscoveryContractError(
                "evaluated source definition version must be typed"
            )
        if not isinstance(self.coverage, CoverageBasis):
            raise DiscoveryContractError("Gate coverage basis must be typed")
        require_uuid_text(
            self.rights_decision_id,
            field="gate_rights_decision_id",
        )
        require_token(
            self.rights_policy_version,
            field="gate_rights_policy_version",
        )
        for field_name in (
            "signal_admission_policy",
            "gate_policy",
            "duplicate_policy",
            "newness_policy",
            "time_validity_policy",
            "exclusion_policy",
        ):
            _require_policy(getattr(self, field_name), field=field_name)
        if not isinstance(self.basis, GateBasis):
            raise DiscoveryContractError("Gate basis must be typed")
        if not isinstance(self.outcome, GateOutcome):
            raise DiscoveryContractError("Gate outcome must be typed")
        if not isinstance(self.terminality, DecisionTerminality):
            raise DiscoveryContractError("Gate terminality must be typed")
        if not isinstance(self.primary_reason, StructuredReason):
            raise DiscoveryContractError("Gate primary reason must be typed")
        if self.primary_reason.basis not in GATE_ALLOWED_REASON_BASES:
            raise DiscoveryContractError(
                "Gate reason basis requires later unavailable authority"
            )
        sorted_reasons(self.supporting_reasons)
        if any(
            item.basis not in GATE_ALLOWED_REASON_BASES
            for item in self.supporting_reasons
        ):
            raise DiscoveryContractError(
                "supporting Gate reason uses unavailable authority"
            )
        if self.primary_reason.digest in {
            item.digest for item in self.supporting_reasons
        }:
            raise DiscoveryContractError(
                "primary Gate reason cannot repeat as supporting reason"
            )
        require_token(
            self.reason_taxonomy_version,
            field="gate_reason_taxonomy_version",
        )
        require_token(
            self.outcome_taxonomy_version,
            field="gate_outcome_taxonomy_version",
        )
        if self.next_action is not None and not isinstance(
            self.next_action,
            NextAction,
        ):
            raise DiscoveryContractError("Gate next action must be typed")
        _require_utc(self.decided_at, field="Gate decision time")
        _require_idempotency_key(self.idempotency_key)
        self._validate_outcome_shape()

    def _validate_outcome_shape(self) -> None:
        authority_ready = all(
            (
                self.basis.identity_integrity,
                self.basis.rights_current,
                self.basis.policy_current,
                self.basis.operationally_executable,
            )
        )
        if self.outcome is not GateOutcome.OPERATIONAL_HOLD and not authority_ready:
            raise DiscoveryContractError(
                "non-hold Gate outcome requires current executable authority"
            )
        if self.basis.duplicate_signal_id == self.signal_id:
            raise DiscoveryContractError(
                "Gate duplicate target must be a distinct retained Signal"
            )

        if self.outcome is GateOutcome.SUPPRESSED_DUPLICATE:
            if self.basis.duplicate_signal_id is None:
                raise DiscoveryContractError(
                    "duplicate suppression requires exact prior Signal"
                )
            if self.terminality is not DecisionTerminality.TERMINAL_EXACT_VERSION:
                raise DiscoveryContractError(
                    "duplicate suppression is terminal for the exact Signal"
                )
            if self.next_action is None or self.next_action.kind is not NextActionKind.CLOSE:
                raise DiscoveryContractError(
                    "duplicate suppression requires an explicit close action"
                )
        elif self.outcome is GateOutcome.SUPPRESSED_NON_CHANGE:
            if self.basis.observable_newness not in {
                ObservableNewness.EXACT_REPEAT,
                ObservableNewness.PARSER_ONLY,
                ObservableNewness.EXPECTATION_ONLY,
            }:
                raise DiscoveryContractError(
                    "non-change suppression requires exact observable non-change"
                )
            if self.basis.duplicate_signal_id is not None:
                raise DiscoveryContractError(
                    "non-change suppression cannot masquerade as duplication"
                )
            if self.terminality is not DecisionTerminality.TERMINAL_EXACT_VERSION:
                raise DiscoveryContractError(
                    "non-change suppression is terminal for the exact Signal"
                )
            if self.next_action is None or self.next_action.kind is not NextActionKind.CLOSE:
                raise DiscoveryContractError(
                    "non-change suppression requires an explicit close action"
                )
        elif self.outcome is GateOutcome.REJECTED_CLEAR_EXCLUSION:
            if self.basis.scope_disposition is not ScopeDisposition.CLEAR_EXCLUSION:
                raise DiscoveryContractError(
                    "clear exclusion requires exact clear scope disposition"
                )
            if self.terminality is not DecisionTerminality.TERMINAL_EXACT_VERSION:
                raise DiscoveryContractError(
                    "clear exclusion is terminal for the exact Signal"
                )
            if self.next_action is None or self.next_action.kind is not NextActionKind.CLOSE:
                raise DiscoveryContractError(
                    "clear exclusion requires an explicit close action"
                )
        elif self.outcome is GateOutcome.PROMOTED_TO_LEAD:
            if not all(
                (
                    self.basis.identity_integrity,
                    self.basis.rights_current,
                    self.basis.policy_current,
                    self.basis.operationally_executable,
                )
            ):
                raise DiscoveryContractError(
                    "Lead promotion requires current executable authority"
                )
            if self.basis.duplicate_signal_id is not None:
                raise DiscoveryContractError(
                    "duplicate Signal cannot be promoted by the same decision"
                )
            if self.basis.observable_newness is not ObservableNewness.GENUINE_TRANSITION:
                raise DiscoveryContractError(
                    "Lead promotion requires a genuine source-observable transition"
                )
            if self.basis.scope_disposition is ScopeDisposition.CLEAR_EXCLUSION:
                raise DiscoveryContractError(
                    "clearly excluded Signal cannot be promoted"
                )
            if self.terminality is not DecisionTerminality.TERMINAL_EXACT_VERSION:
                raise DiscoveryContractError(
                    "promotion is terminal for the exact Gate evaluation"
                )
            if self.next_action is None or self.next_action.kind is not NextActionKind.QUEUE_TRIAGE:
                raise DiscoveryContractError(
                    "Lead promotion requires the exact queue-triage next action"
                )
        elif self.outcome is GateOutcome.OPERATIONAL_HOLD:
            if self.next_action is None or self.next_action.kind not in {
                NextActionKind.RETRY,
                NextActionKind.REVIEW,
                NextActionKind.WAIT_DEPENDENCY,
            }:
                raise DiscoveryContractError(
                    "operational hold requires inspectable operational next action"
                )
            if self.terminality not in {
                DecisionTerminality.PENDING_CONDITION,
                DecisionTerminality.RETRYABLE_SAME_REQUEST,
            }:
                raise DiscoveryContractError(
                    "operational hold must be pending or retryable"
                )

        expected = deterministic_gate_outcome(self.basis)
        if self.outcome is not expected:
            raise DiscoveryContractError(
                "Gate outcome differs from deterministic basis: "
                f"expected {expected.value}"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "decision_id": str(self.decision_id),
            "signal_id": str(self.signal_id),
            "decision_ordinal": self.decision_ordinal,
            "previous_decision_id": (
                None
                if self.previous_decision_id is None
                else str(self.previous_decision_id)
            ),
            "evaluated_definition_version_id": str(
                self.evaluated_definition_version_id
            ),
            "coverage": self.coverage.canonical_value(),
            "rights_decision_id": self.rights_decision_id,
            "rights_policy_version": self.rights_policy_version,
            "signal_admission_policy": (
                self.signal_admission_policy.canonical_value()
            ),
            "gate_policy": self.gate_policy.canonical_value(),
            "duplicate_policy": self.duplicate_policy.canonical_value(),
            "newness_policy": self.newness_policy.canonical_value(),
            "time_validity_policy": self.time_validity_policy.canonical_value(),
            "exclusion_policy": self.exclusion_policy.canonical_value(),
            "basis": self.basis.canonical_value(),
            "outcome": self.outcome.value,
            "terminality": self.terminality.value,
            "primary_reason": self.primary_reason.canonical_value(),
            "supporting_reasons": [
                item.canonical_value() for item in self.supporting_reasons
            ],
            "reason_taxonomy_version": self.reason_taxonomy_version,
            "outcome_taxonomy_version": self.outcome_taxonomy_version,
            "next_action": (
                None if self.next_action is None else self.next_action.canonical_value()
            ),
            "decided_at": self.decided_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        value = self.canonical_value()
        value.pop("decision_id")
        value.pop("decided_at")
        return digest_canonical(value)


@dataclass(frozen=True, slots=True)
class NewsLeadRequest:
    lead_id: NewsLeadId
    signal_id: DiscoverySignalId
    promoting_gate_decision_id: GateDecisionId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    item_id: SourceItemId
    revision_id: SourceRevisionId
    representation_id: DiscoveryRepresentationId
    occurrence_id: DiscoveryOccurrenceId
    transition_id: ObservableTransitionId
    transition_kind: ObservableTransitionKind
    coverage: CoverageBasis
    source_roles: tuple[SourceRoleAssignment, ...]
    portfolio_functions: tuple[PortfolioFunction, ...]
    source_dependencies: tuple[SourceDependency, ...]
    incompleteness_warnings: tuple[str, ...]
    urgency: UrgencyBasis
    lead_policy: VersionedPolicyRef
    reason_taxonomy_version: str
    outcome_taxonomy_version: str
    created_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        typed = (
            (self.lead_id, NewsLeadId, "Lead"),
            (self.signal_id, DiscoverySignalId, "Signal"),
            (self.promoting_gate_decision_id, GateDecisionId, "promoting Gate"),
            (self.definition_id, SourceDefinitionId, "source definition"),
            (
                self.definition_version_id,
                SourceDefinitionVersionId,
                "source definition version",
            ),
            (self.item_id, SourceItemId, "source item"),
            (self.revision_id, SourceRevisionId, "source revision"),
            (
                self.representation_id,
                DiscoveryRepresentationId,
                "representation",
            ),
            (self.occurrence_id, DiscoveryOccurrenceId, "occurrence"),
            (self.transition_id, ObservableTransitionId, "transition"),
        )
        for value, expected, field in typed:
            if not isinstance(value, expected):
                raise DiscoveryContractError(f"{field} identity must be typed")
        if not isinstance(self.transition_kind, ObservableTransitionKind):
            raise DiscoveryContractError("Lead transition kind must be typed")
        if not isinstance(self.coverage, CoverageBasis):
            raise DiscoveryContractError("Lead coverage basis must be typed")
        if self.source_roles != sorted_role_assignments(self.source_roles):
            raise DiscoveryContractError("Lead source roles must be canonical")
        if (
            not isinstance(self.portfolio_functions, tuple)
            or not self.portfolio_functions
            or any(
                not isinstance(item, PortfolioFunction)
                for item in self.portfolio_functions
            )
            or self.portfolio_functions
            != tuple(sorted(set(self.portfolio_functions), key=lambda item: item.value))
        ):
            raise DiscoveryContractError(
                "Lead portfolio functions must be sorted unique typed values"
            )
        if (
            not isinstance(self.source_dependencies, tuple)
            or len(self.source_dependencies) > MAX_NEWS_LEAD_SOURCE_DEPENDENCIES
            or self.source_dependencies != sorted_dependencies(self.source_dependencies)
        ):
            raise DiscoveryContractError(
                "Lead source dependencies must be bounded canonical values"
            )
        sorted_unique_text(
            self.incompleteness_warnings,
            field="lead_incompleteness_warnings",
            maximum_items=32,
            maximum_item_bytes=1024,
            allow_empty=True,
        )
        if not isinstance(self.urgency, UrgencyBasis):
            raise DiscoveryContractError("Lead urgency basis must be typed")
        if self.urgency.primary_reason.basis not in INCREMENT_3D_ALLOWED_REASON_BASES:
            raise DiscoveryContractError(
                "Lead urgency reason basis requires later unavailable authority"
            )
        _require_policy(self.lead_policy, field="lead_policy")
        require_token(
            self.reason_taxonomy_version,
            field="lead_reason_taxonomy_version",
        )
        require_token(
            self.outcome_taxonomy_version,
            field="lead_outcome_taxonomy_version",
        )
        _require_utc(self.created_at, field="Lead creation time")
        _require_idempotency_key(self.idempotency_key)
        if (
            len(canonical_json_bytes(self.canonical_value()))
            > MAX_NEWS_LEAD_CANONICAL_BYTES
        ):
            raise DiscoveryContractError("News Lead exceeds its canonical byte bound")

    def canonical_value(self) -> dict[str, object]:
        return {
            "lead_id": str(self.lead_id),
            "signal_id": str(self.signal_id),
            "promoting_gate_decision_id": str(self.promoting_gate_decision_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "item_id": str(self.item_id),
            "revision_id": str(self.revision_id),
            "representation_id": str(self.representation_id),
            "occurrence_id": str(self.occurrence_id),
            "transition_id": str(self.transition_id),
            "transition_kind": self.transition_kind.value,
            "coverage": self.coverage.canonical_value(),
            "source_roles": [item.canonical_value() for item in self.source_roles],
            "portfolio_functions": [
                item.value for item in self.portfolio_functions
            ],
            "source_dependencies": [
                item.canonical_value() for item in self.source_dependencies
            ],
            "incompleteness_warnings": list(self.incompleteness_warnings),
            "urgency": self.urgency.canonical_value(),
            "lead_policy": self.lead_policy.canonical_value(),
            "reason_taxonomy_version": self.reason_taxonomy_version,
            "outcome_taxonomy_version": self.outcome_taxonomy_version,
            "created_at": self.created_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        value = canonical_json_bytes(self.canonical_value())
        if len(value) > MAX_NEWS_LEAD_CANONICAL_BYTES:
            raise DiscoveryContractError("News Lead exceeds its canonical byte bound")
        return value

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        value = self.canonical_value()
        value.pop("lead_id")
        value.pop("created_at")
        return digest_canonical(value)


@dataclass(frozen=True, slots=True)
class WatchConditionRequest:
    watch_condition_id: WatchConditionId
    lead_id: NewsLeadId
    gate_decision_id: GateDecisionId
    resume_transition_kinds: tuple[ObservableTransitionKind, ...]
    expected_occurrence: str | None
    corroborating_lead_id: NewsLeadId | None
    review_at: UtcTimestamp | None
    expires_at: UtcTimestamp | None
    operator_review_condition: str | None
    closure_rule: str
    watch_policy: VersionedPolicyRef
    recorded_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.watch_condition_id, WatchConditionId):
            raise DiscoveryContractError("Watch Condition identity must be typed")
        if not isinstance(self.lead_id, NewsLeadId):
            raise DiscoveryContractError("Watch Lead identity must be typed")
        if not isinstance(self.gate_decision_id, GateDecisionId):
            raise DiscoveryContractError(
                "Watch Condition Gate Decision identity must be typed"
            )
        if (
            not isinstance(self.resume_transition_kinds, tuple)
            or any(
                not isinstance(item, ObservableTransitionKind)
                for item in self.resume_transition_kinds
            )
            or self.resume_transition_kinds
            != tuple(
                sorted(
                    set(self.resume_transition_kinds),
                    key=lambda item: item.value,
                )
            )
        ):
            raise DiscoveryContractError(
                "Watch transition kinds must be sorted unique typed values"
            )
        if self.expected_occurrence is not None:
            bounded_text(
                self.expected_occurrence,
                field="watch_expected_occurrence",
                maximum_bytes=2048,
            )
        if self.corroborating_lead_id is not None:
            if not isinstance(self.corroborating_lead_id, NewsLeadId):
                raise DiscoveryContractError(
                    "corroborating Lead identity must be typed"
                )
            if self.corroborating_lead_id == self.lead_id:
                raise DiscoveryContractError(
                    "Watch Condition corroborating Lead must be distinct"
                )
        for field_name in ("review_at", "expires_at"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, UtcTimestamp):
                raise DiscoveryContractError(f"{field_name} must be typed UTC")
        if self.operator_review_condition is not None:
            bounded_text(
                self.operator_review_condition,
                field="watch_operator_review_condition",
                maximum_bytes=2048,
            )
        require_token(self.closure_rule, field="watch_closure_rule")
        _require_policy(self.watch_policy, field="watch_policy")
        _require_utc(self.recorded_at, field="Watch Condition record time")
        if self.review_at is not None and self.review_at.value < self.recorded_at.value:
            raise DiscoveryContractError("Watch review time precedes record time")
        if self.expires_at is not None and self.expires_at.value <= self.recorded_at.value:
            raise DiscoveryContractError("Watch expiry must follow record time")
        if (
            self.review_at is not None
            and self.expires_at is not None
            and self.expires_at.value < self.review_at.value
        ):
            raise DiscoveryContractError("Watch expiry precedes review time")
        if not any(
            (
                self.resume_transition_kinds,
                self.expected_occurrence,
                self.corroborating_lead_id,
                self.review_at,
                self.expires_at,
                self.operator_review_condition,
            )
        ):
            raise DiscoveryContractError(
                "Watch Condition requires an inspectable resume or closure condition"
            )
        _require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "watch_condition_id": str(self.watch_condition_id),
            "lead_id": str(self.lead_id),
            "gate_decision_id": str(self.gate_decision_id),
            "resume_transition_kinds": [
                item.value for item in self.resume_transition_kinds
            ],
            "expected_occurrence": self.expected_occurrence,
            "corroborating_lead_id": (
                None
                if self.corroborating_lead_id is None
                else str(self.corroborating_lead_id)
            ),
            "review_at": (
                None if self.review_at is None else self.review_at.to_text()
            ),
            "expires_at": (
                None if self.expires_at is None else self.expires_at.to_text()
            ),
            "operator_review_condition": self.operator_review_condition,
            "closure_rule": self.closure_rule,
            "watch_policy": self.watch_policy.canonical_value(),
            "recorded_at": self.recorded_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        value = self.canonical_value()
        value.pop("watch_condition_id")
        value.pop("recorded_at")
        return digest_canonical(value)


@dataclass(frozen=True, slots=True)
class LeadDispositionDecisionRequest:
    decision_id: LeadDispositionDecisionId
    lead_id: NewsLeadId
    gate_decision_id: GateDecisionId
    decision_ordinal: int
    previous_decision_id: LeadDispositionDecisionId | None
    outcome: LeadDispositionOutcome
    terminality: DecisionTerminality
    primary_reason: StructuredReason
    supporting_reasons: tuple[StructuredReason, ...]
    watch_condition_id: WatchConditionId | None
    next_action: NextAction
    urgency_route: UrgencyBasis
    disposition_policy: VersionedPolicyRef
    reason_taxonomy_version: str
    outcome_taxonomy_version: str
    decided_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, LeadDispositionDecisionId):
            raise DiscoveryContractError(
                "Lead Disposition Decision identity must be typed"
            )
        if not isinstance(self.lead_id, NewsLeadId):
            raise DiscoveryContractError("Lead disposition Lead must be typed")
        if not isinstance(self.gate_decision_id, GateDecisionId):
            raise DiscoveryContractError(
                "Lead disposition Gate Decision identity must be typed"
            )
        if (
            isinstance(self.decision_ordinal, bool)
            or not isinstance(self.decision_ordinal, int)
            or not 1 <= self.decision_ordinal <= 1_000_000
        ):
            raise DiscoveryContractError("Lead disposition ordinal is invalid")
        if self.previous_decision_id is not None and not isinstance(
            self.previous_decision_id,
            LeadDispositionDecisionId,
        ):
            raise DiscoveryContractError(
                "previous Lead Disposition Decision must be typed"
            )
        if not isinstance(self.outcome, LeadDispositionOutcome):
            raise DiscoveryContractError("Lead disposition outcome must be typed")
        if not is_active_disposition(self.outcome):
            raise DiscoveryContractError(
                "Lead disposition outcome requires later triage/Candidate authority"
            )
        if self.decision_ordinal == 1:
            if self.previous_decision_id is not None:
                raise DiscoveryContractError(
                    "first Lead disposition cannot name a predecessor"
                )
            if self.outcome is not LeadDispositionOutcome.QUEUED_FOR_TRIAGE:
                raise DiscoveryContractError(
                    "initial Lead disposition must queue the Lead for triage"
                )
        elif self.previous_decision_id is None:
            raise DiscoveryContractError(
                "later Lead disposition requires exact predecessor identity"
            )
        if self.previous_decision_id == self.decision_id:
            raise DiscoveryContractError("Lead disposition cannot precede itself")
        if not isinstance(self.terminality, DecisionTerminality):
            raise DiscoveryContractError("Lead disposition terminality must be typed")
        if not isinstance(self.primary_reason, StructuredReason):
            raise DiscoveryContractError(
                "Lead disposition primary reason must be typed"
            )
        if self.primary_reason.basis not in INCREMENT_3D_ALLOWED_REASON_BASES:
            raise DiscoveryContractError(
                "Lead disposition reason basis requires later unavailable authority"
            )
        sorted_reasons(self.supporting_reasons)
        if any(
            item.basis not in INCREMENT_3D_ALLOWED_REASON_BASES
            for item in self.supporting_reasons
        ):
            raise DiscoveryContractError(
                "supporting Lead disposition reason uses unavailable authority"
            )
        if self.primary_reason.digest in {
            item.digest for item in self.supporting_reasons
        }:
            raise DiscoveryContractError(
                "primary Lead disposition reason cannot repeat"
            )
        if self.watch_condition_id is not None and not isinstance(
            self.watch_condition_id,
            WatchConditionId,
        ):
            raise DiscoveryContractError("Watch Condition identity must be typed")
        if not isinstance(self.next_action, NextAction):
            raise DiscoveryContractError(
                "Lead disposition requires a typed next action"
            )
        if not isinstance(self.urgency_route, UrgencyBasis):
            raise DiscoveryContractError("Lead disposition urgency must be typed")
        _require_policy(self.disposition_policy, field="lead_disposition_policy")
        require_token(
            self.reason_taxonomy_version,
            field="lead_disposition_reason_taxonomy_version",
        )
        require_token(
            self.outcome_taxonomy_version,
            field="lead_disposition_outcome_taxonomy_version",
        )
        _require_utc(self.decided_at, field="Lead disposition time")
        _require_idempotency_key(self.idempotency_key)
        self._validate_outcome_shape()

    def _validate_outcome_shape(self) -> None:
        if self.outcome is LeadDispositionOutcome.QUEUED_FOR_TRIAGE:
            if self.watch_condition_id is not None:
                raise DiscoveryContractError(
                    "queued Lead disposition cannot name a Watch Condition"
                )
            if self.next_action.kind is not NextActionKind.QUEUE_TRIAGE:
                raise DiscoveryContractError(
                    "queued Lead disposition requires queue-triage action"
                )
            if self.terminality is not DecisionTerminality.PENDING_CONDITION:
                raise DiscoveryContractError(
                    "queued Lead disposition remains pending triage"
                )
        elif self.outcome is LeadDispositionOutcome.WATCH_DEFER:
            if self.watch_condition_id is None:
                raise DiscoveryContractError(
                    "watch-defer disposition requires exact Watch Condition"
                )
            if self.next_action.kind is not NextActionKind.RESUME_ON_WATCH:
                raise DiscoveryContractError(
                    "watch-defer disposition requires resume-on-watch action"
                )
            if self.terminality is not DecisionTerminality.PENDING_CONDITION:
                raise DiscoveryContractError(
                    "watch-defer disposition remains pending its condition"
                )
        elif self.outcome is LeadDispositionOutcome.OPERATIONAL_HOLD:
            if self.watch_condition_id is not None:
                raise DiscoveryContractError(
                    "operational hold cannot masquerade as a Watch Condition"
                )
            if self.next_action.kind not in {
                NextActionKind.RETRY,
                NextActionKind.REVIEW,
                NextActionKind.WAIT_DEPENDENCY,
            }:
                raise DiscoveryContractError(
                    "Lead operational hold requires inspectable operational action"
                )
            if self.terminality not in {
                DecisionTerminality.PENDING_CONDITION,
                DecisionTerminality.RETRYABLE_SAME_REQUEST,
            }:
                raise DiscoveryContractError(
                    "Lead operational hold must be pending or retryable"
                )

    def canonical_value(self) -> dict[str, object]:
        return {
            "decision_id": str(self.decision_id),
            "lead_id": str(self.lead_id),
            "gate_decision_id": str(self.gate_decision_id),
            "decision_ordinal": self.decision_ordinal,
            "previous_decision_id": (
                None
                if self.previous_decision_id is None
                else str(self.previous_decision_id)
            ),
            "outcome": self.outcome.value,
            "terminality": self.terminality.value,
            "primary_reason": self.primary_reason.canonical_value(),
            "supporting_reasons": [
                item.canonical_value() for item in self.supporting_reasons
            ],
            "watch_condition_id": (
                None
                if self.watch_condition_id is None
                else str(self.watch_condition_id)
            ),
            "next_action": self.next_action.canonical_value(),
            "urgency_route": self.urgency_route.canonical_value(),
            "disposition_policy": self.disposition_policy.canonical_value(),
            "reason_taxonomy_version": self.reason_taxonomy_version,
            "outcome_taxonomy_version": self.outcome_taxonomy_version,
            "decided_at": self.decided_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        value = self.canonical_value()
        value.pop("decision_id")
        value.pop("decided_at")
        return digest_canonical(value)


__all__ = [
    "DiscoverySignalRequest",
    "GateDecisionRequest",
    "LeadDispositionDecisionRequest",
    "NewsLeadRequest",
    "WatchConditionRequest",
]
