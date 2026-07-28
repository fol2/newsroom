from __future__ import annotations

from newsroom.authority.types import UtcTimestamp
from newsroom.checks import (
    CheckOutcomeId,
    CoverageBasis,
    ObservableTransitionId,
    ObservableTransitionKind,
)
from newsroom.discovery.models import (
    DiscoverySignalRequest,
    GateDecisionRequest,
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
    WatchConditionRequest,
)
from newsroom.discovery.types import (
    DecisionTerminality,
    DiscoverySignalId,
    GateBasis,
    GateDecisionId,
    GateOutcome,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    NewsLeadId,
    NextAction,
    NextActionKind,
    ObservableNewness,
    ReasonBasisClass,
    ReasonReference,
    ScopeDisposition,
    StructuredReason,
    TimeValidity,
    UrgencyBasis,
    UrgencyRoute,
    WatchConditionId,
)
from newsroom.sources import (
    CoverageContribution,
    CoverageResponsibility,
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    PortfolioFunction,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceDependency,
    SourceDependencyKind,
    SourceItemId,
    SourceRevisionId,
    SourceRole,
    SourceRoleAssignment,
    VersionedPolicyRef,
)

NOW = UtcTimestamp.parse("2042-03-12T10:00:00.000000Z")
LATER = UtcTimestamp.parse("2042-03-12T10:05:00.000000Z")
REVIEW_AT = UtcTimestamp.parse("2042-03-13T10:00:00.000000Z")
EXPIRY = UtcTimestamp.parse("2042-03-14T10:00:00.000000Z")

DEFINITION_ID = SourceDefinitionId.parse("00000000-0000-4000-8000-000000007001")
VERSION_ID = SourceDefinitionVersionId.parse(
    "00000000-0000-4000-8000-000000007002"
)
ITEM_ID = SourceItemId.parse("00000000-0000-4000-8000-000000007003")
REVISION_ID = SourceRevisionId.parse("00000000-0000-4000-8000-000000007004")
REPRESENTATION_ID = DiscoveryRepresentationId.parse(
    "00000000-0000-4000-8000-000000007005"
)
OUTCOME_ID = CheckOutcomeId.parse("00000000-0000-4000-8000-000000007006")
OCCURRENCE_ID = DiscoveryOccurrenceId.parse(
    "00000000-0000-4000-8000-000000007007"
)
TRANSITION_ID = ObservableTransitionId.parse(
    "00000000-0000-4000-8000-000000007008"
)
SIGNAL_ID = DiscoverySignalId.parse("00000000-0000-4000-8000-000000007009")
OTHER_SIGNAL_ID = DiscoverySignalId.parse(
    "00000000-0000-4000-8000-000000007010"
)
GATE_ID = GateDecisionId.parse("00000000-0000-4000-8000-000000007011")
LEAD_ID = NewsLeadId.parse("00000000-0000-4000-8000-000000007012")
OTHER_LEAD_ID = NewsLeadId.parse("00000000-0000-4000-8000-000000007013")
WATCH_ID = WatchConditionId.parse("00000000-0000-4000-8000-000000007014")
DISPOSITION_ID = LeadDispositionDecisionId.parse(
    "00000000-0000-4000-8000-000000007015"
)
PRIOR_DISPOSITION_ID = LeadDispositionDecisionId.parse(
    "00000000-0000-4000-8000-000000007016"
)


def policy(name: str) -> VersionedPolicyRef:
    return VersionedPolicyRef(name, "v1")


def reference(kind: str, identifier: str) -> ReasonReference:
    return ReasonReference(kind, identifier)


def reason(
    code: str = "CHANGE.GENUINE_TRANSITION",
    basis: ReasonBasisClass = ReasonBasisClass.DETERMINISTIC_OBSERVATION,
) -> StructuredReason:
    return StructuredReason(
        code=code,
        basis=basis,
        references=(reference("OBSERVABLE_TRANSITION", str(TRANSITION_ID)),),
        explanation="Exact fixture source transition supports this decision.",
    )


def coverage() -> CoverageBasis:
    return CoverageBasis(
        "COV-030",
        CoverageResponsibility.ACTIVE,
        CoverageContribution.DETECTION_PATH,
        policy("fixture-coverage"),
    )


def promoted_basis() -> GateBasis:
    return GateBasis(
        identity_integrity=True,
        duplicate_signal_id=None,
        duplicate_rule=None,
        observable_newness=ObservableNewness.GENUINE_TRANSITION,
        time_validity=TimeValidity.CURRENT,
        scope_disposition=ScopeDisposition.ACCEPTED,
        clear_exclusion_rule=None,
        rights_current=True,
        policy_current=True,
        operationally_executable=True,
    )


def signal_request(
    *,
    signal_id: DiscoverySignalId = SIGNAL_ID,
    purpose: str = "SOURCE_TRANSITION",
    discriminator: str = "primary",
) -> DiscoverySignalRequest:
    return DiscoverySignalRequest(
        signal_id=signal_id,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        item_id=ITEM_ID,
        revision_id=REVISION_ID,
        representation_id=REPRESENTATION_ID,
        check_outcome_id=OUTCOME_ID,
        occurrence_id=OCCURRENCE_ID,
        transition_id=TRANSITION_ID,
        purpose=purpose,
        discriminator=discriminator,
        admission_policy=policy("fixture-signal-admission"),
        incomplete=False,
        operational_finding_ids=(),
        admitted_at=NOW,
        idempotency_key=f"fixture-signal:{signal_id}",
    )


def gate_request(
    *,
    decision_id: GateDecisionId = GATE_ID,
    signal_id: DiscoverySignalId = SIGNAL_ID,
    outcome: GateOutcome = GateOutcome.PROMOTED_TO_LEAD,
    basis: GateBasis | None = None,
    terminality: DecisionTerminality = DecisionTerminality.TERMINAL_EXACT_VERSION,
    next_action: NextAction | None = None,
) -> GateDecisionRequest:
    selected_basis = basis or promoted_basis()
    if next_action is None and outcome is GateOutcome.PROMOTED_TO_LEAD:
        next_action = NextAction(
            NextActionKind.QUEUE_TRIAGE,
            "QUEUE_FOR_TRIAGE",
            instructions="Create one immutable Lead and initial disposition.",
        )
    return GateDecisionRequest(
        decision_id=decision_id,
        signal_id=signal_id,
        decision_ordinal=1,
        previous_decision_id=None,
        evaluated_definition_version_id=VERSION_ID,
        coverage=coverage(),
        rights_decision_id="00000000-0000-4000-8000-000000007099",
        rights_policy_version="fixture-rights-v1",
        signal_admission_policy=policy("fixture-signal-admission"),
        gate_policy=policy("fixture-gate"),
        duplicate_policy=policy("fixture-duplicate"),
        newness_policy=policy("fixture-newness"),
        time_validity_policy=policy("fixture-time-validity"),
        exclusion_policy=policy("fixture-exclusion"),
        basis=selected_basis,
        outcome=outcome,
        terminality=terminality,
        primary_reason=reason(),
        supporting_reasons=(),
        reason_taxonomy_version="fixture-reasons-v1",
        outcome_taxonomy_version="fixture-outcomes-v1",
        next_action=next_action,
        decided_at=LATER,
        idempotency_key=f"fixture-gate:{decision_id}",
    )


def urgency(
    route: UrgencyRoute = UrgencyRoute.ROUTINE,
) -> UrgencyBasis:
    return UrgencyBasis(
        route=route,
        primary_reason=reason(
            code=(
                "TIME.IMMEDIATE_SAFETY"
                if route is UrgencyRoute.URGENT
                else "TIME.ROUTINE_SOURCE_CHANGE"
            )
        ),
        hard_deadline=(REVIEW_AT if route is UrgencyRoute.URGENT else None),
        planned_window=("fixture-window" if route is UrgencyRoute.PLANNED else None),
        isolation_required=route is UrgencyRoute.URGENT,
    )


def lead_request(
    *,
    lead_id: NewsLeadId = LEAD_ID,
    signal_id: DiscoverySignalId = SIGNAL_ID,
    gate_id: GateDecisionId = GATE_ID,
    route: UrgencyRoute = UrgencyRoute.ROUTINE,
) -> NewsLeadRequest:
    return NewsLeadRequest(
        lead_id=lead_id,
        signal_id=signal_id,
        promoting_gate_decision_id=gate_id,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        item_id=ITEM_ID,
        revision_id=REVISION_ID,
        representation_id=REPRESENTATION_ID,
        occurrence_id=OCCURRENCE_ID,
        transition_id=TRANSITION_ID,
        transition_kind=ObservableTransitionKind.REVISED,
        coverage=coverage(),
        source_roles=(
            SourceRoleAssignment(
                SourceRole.ORIGINATING_AUTHORITY,
                "Observe fixture authority changes.",
                ("Fixture and approved replay only.",),
            ),
        ),
        portfolio_functions=(PortfolioFunction.ANCHOR,),
        source_dependencies=(
            SourceDependency(
                "fixture-origin",
                SourceDependencyKind.ORIGINATING_MATERIAL,
                "Fixture material is the originating source state.",
            ),
        ),
        incompleteness_warnings=(),
        urgency=urgency(route),
        lead_policy=policy("fixture-lead"),
        reason_taxonomy_version="fixture-reasons-v1",
        outcome_taxonomy_version="fixture-outcomes-v1",
        created_at=LATER,
        idempotency_key=f"fixture-lead:{lead_id}",
    )


def watch_request() -> WatchConditionRequest:
    return WatchConditionRequest(
        watch_condition_id=WATCH_ID,
        lead_id=LEAD_ID,
        resume_transition_kinds=(ObservableTransitionKind.REVISED,),
        expected_occurrence="Fixture source publishes a later revision.",
        corroborating_lead_id=None,
        review_at=REVIEW_AT,
        expires_at=EXPIRY,
        operator_review_condition=None,
        closure_rule="CLOSE_ON_EXPIRY",
        watch_policy=policy("fixture-watch"),
        recorded_at=LATER,
        idempotency_key="fixture-watch",
    )


def disposition_request(
    *,
    outcome: LeadDispositionOutcome = LeadDispositionOutcome.QUEUED_FOR_TRIAGE,
) -> LeadDispositionDecisionRequest:
    if outcome is LeadDispositionOutcome.WATCH_DEFER:
        watch_condition_id = WATCH_ID
        action = NextAction(
            NextActionKind.RESUME_ON_WATCH,
            "RESUME_ON_FIXTURE_WATCH",
            due_at=REVIEW_AT,
            expires_at=EXPIRY,
            instructions="Resume when the exact Watch Condition is satisfied.",
        )
    elif outcome is LeadDispositionOutcome.OPERATIONAL_HOLD:
        watch_condition_id = None
        action = NextAction(
            NextActionKind.REVIEW,
            "REVIEW_OPERATIONAL_DEPENDENCY",
            owner="discovery-operator",
            due_at=REVIEW_AT,
            instructions="Review retained operational dependency.",
        )
    else:
        watch_condition_id = None
        action = NextAction(
            NextActionKind.QUEUE_TRIAGE,
            "QUEUE_FOR_TRIAGE",
            instructions="Queue without creating a Triage Work Item.",
        )
    is_initial = outcome is LeadDispositionOutcome.QUEUED_FOR_TRIAGE
    return LeadDispositionDecisionRequest(
        decision_id=DISPOSITION_ID,
        lead_id=LEAD_ID,
        decision_ordinal=1 if is_initial else 2,
        previous_decision_id=None if is_initial else PRIOR_DISPOSITION_ID,
        outcome=outcome,
        terminality=DecisionTerminality.PENDING_CONDITION,
        primary_reason=reason("CHANGE.LEAD_CREATED"),
        supporting_reasons=(),
        watch_condition_id=watch_condition_id,
        next_action=action,
        urgency_route=urgency(),
        disposition_policy=policy("fixture-lead-disposition"),
        reason_taxonomy_version="fixture-reasons-v1",
        outcome_taxonomy_version="fixture-outcomes-v1",
        decided_at=LATER,
        idempotency_key=f"fixture-disposition:{outcome.value}",
    )
