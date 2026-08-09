from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.checks import ObservableTransitionKind, OperationalFindingId
from newsroom.discovery import (
    DecisionTerminality,
    DiscoveryContractError,
    GateBasis,
    GateOutcome,
    LeadDispositionOutcome,
    NextAction,
    NextActionKind,
    ObservableNewness,
    ReasonBasisClass,
    ReasonReference,
    ScopeDisposition,
    StructuredReason,
    TimeValidity,
    deterministic_gate_outcome,
    permitted_newness_for_transition,
    UrgencyRoute,
)
from newsroom.discovery.models import (
    MAX_LEAD_DISPOSITION_SUPPORTING_REASONS,
    LeadDispositionDecisionRequest,
)
from newsroom.discovery.types import MAX_STRUCTURED_REASON_REFERENCES
from newsroom.sources import VersionedPolicyRef

from .discovery_3d_helpers import (
    EXPIRY,
    OTHER_SIGNAL_ID,
    REVIEW_AT,
    disposition_request,
    gate_request,
    lead_request,
    promoted_basis,
    reason,
    signal_request,
    urgency,
    watch_request,
)


def test_signal_semantics_ignore_lifecycle_identity_and_record_time() -> None:
    first = signal_request()
    second = replace(
        first,
        signal_id=OTHER_SIGNAL_ID,
        admitted_at=REVIEW_AT,
        idempotency_key="fixture-signal-second",
    )
    assert first.semantic_digest == second.semantic_digest
    assert first.digest != second.digest


def test_signal_identity_ignores_operational_degradation_lineage() -> None:
    complete = signal_request()
    degraded = replace(
        complete,
        signal_id=OTHER_SIGNAL_ID,
        incomplete=True,
        operational_finding_ids=(
            OperationalFindingId.parse(
                "00000000-0000-4000-8000-000000007099"
            ),
        ),
        idempotency_key="fixture-signal-degraded",
    )
    assert complete.semantic_digest == degraded.semantic_digest
    assert complete.digest != degraded.digest


def test_signal_discriminator_allocates_distinct_semantic_signal() -> None:
    first = signal_request(discriminator="primary")
    second = signal_request(
        signal_id=OTHER_SIGNAL_ID,
        discriminator="safety-purpose",
    )
    assert first.semantic_digest != second.semantic_digest


def test_promoted_gate_requires_genuine_current_executable_basis() -> None:
    with pytest.raises(DiscoveryContractError, match="current executable"):
        gate_request(
            basis=replace(promoted_basis(), rights_current=False),
        )
    with pytest.raises(DiscoveryContractError, match="genuine"):
        gate_request(
            basis=replace(
                promoted_basis(),
                observable_newness=ObservableNewness.PARSER_ONLY,
            ),
        )


def test_duplicate_gate_requires_exact_signal_and_rule() -> None:
    with pytest.raises(DiscoveryContractError, match="versioned duplicate rule"):
        GateBasis(
            identity_integrity=True,
            duplicate_signal_id=OTHER_SIGNAL_ID,
            duplicate_rule=None,
            observable_newness=ObservableNewness.GENUINE_TRANSITION,
            time_validity=TimeValidity.CURRENT,
            scope_disposition=ScopeDisposition.ACCEPTED,
            clear_exclusion_rule=None,
            rights_current=True,
            policy_current=True,
            operationally_executable=True,
        )
    basis = replace(
        promoted_basis(),
        duplicate_signal_id=OTHER_SIGNAL_ID,
        duplicate_rule=VersionedPolicyRef("fixture-duplicate", "v1"),
    )
    decision = gate_request(
        outcome=GateOutcome.SUPPRESSED_DUPLICATE,
        basis=basis,
        next_action=NextAction(
            NextActionKind.CLOSE,
            "CLOSE_DUPLICATE",
            instructions="Retain both Signals and close this exact gate scope.",
        ),
    )
    assert decision.basis.duplicate_signal_id == OTHER_SIGNAL_ID


def test_non_change_gate_is_not_editorial_rejection() -> None:
    decision = gate_request(
        outcome=GateOutcome.SUPPRESSED_NON_CHANGE,
        basis=replace(
            promoted_basis(),
            observable_newness=ObservableNewness.PARSER_ONLY,
        ),
        next_action=NextAction(
            NextActionKind.CLOSE,
            "CLOSE_NON_CHANGE",
            instructions="Retain source lineage without creating a Lead.",
        ),
    )
    assert decision.outcome is GateOutcome.SUPPRESSED_NON_CHANGE


def test_clear_exclusion_cannot_relabel_ambiguity() -> None:
    with pytest.raises(DiscoveryContractError, match="ambiguous scope"):
        GateBasis(
            identity_integrity=True,
            duplicate_signal_id=None,
            duplicate_rule=None,
            observable_newness=ObservableNewness.GENUINE_TRANSITION,
            time_validity=TimeValidity.CURRENT,
            scope_disposition=ScopeDisposition.CLEAR_EXCLUSION,
            clear_exclusion_rule=VersionedPolicyRef("fixture-exclusion", "v1"),
            rights_current=True,
            policy_current=True,
            operationally_executable=True,
            ambiguities=("MATERIALITY_UNKNOWN",),
        )


def test_operational_hold_requires_inspectable_action() -> None:
    with pytest.raises(DiscoveryContractError, match="operational next action"):
        gate_request(
            outcome=GateOutcome.OPERATIONAL_HOLD,
            basis=replace(promoted_basis(), policy_current=False),
            terminality=DecisionTerminality.PENDING_CONDITION,
            next_action=NextAction(
                NextActionKind.CLOSE,
                "CLOSE",
                instructions="Invalid hold action.",
            ),
        )


def test_gate_rejects_later_editorial_reason_basis() -> None:
    with pytest.raises(DiscoveryContractError, match="later unavailable authority"):
        replace(
            gate_request(),
            primary_reason=reason(
                "UTILITY.EDITORIAL_MATERIALITY",
                ReasonBasisClass.EDITORIAL_ASSESSMENT,
            ),
        )


def test_lead_preserves_qualitative_route_without_numeric_score() -> None:
    lead = lead_request(route=UrgencyRoute.URGENT)
    assert lead.urgency.route is UrgencyRoute.URGENT
    assert lead.urgency.isolation_required is True
    assert "score" not in lead.canonical_value()["urgency"]


def test_urgent_route_requires_explicit_isolation() -> None:
    with pytest.raises(DiscoveryContractError, match="explicit isolation"):
        replace(urgency(UrgencyRoute.URGENT), isolation_required=False)


def test_planned_route_requires_inspectable_window() -> None:
    with pytest.raises(DiscoveryContractError, match="inspectable window"):
        replace(urgency(UrgencyRoute.ROUTINE), route=UrgencyRoute.PLANNED)


def test_watch_condition_cannot_be_indefinite() -> None:
    watch = watch_request()
    with pytest.raises(DiscoveryContractError, match="inspectable resume"):
        replace(
            watch,
            resume_transition_kinds=(),
            expected_occurrence=None,
            corroborating_lead_id=None,
            review_at=None,
            expires_at=None,
            operator_review_condition=None,
        )


def test_watch_expiry_must_follow_record_time() -> None:
    with pytest.raises(DiscoveryContractError, match="expiry"):
        replace(watch_request(), expires_at=watch_request().recorded_at)


def test_watch_defer_requires_exact_watch_condition() -> None:
    with pytest.raises(DiscoveryContractError, match="Watch Condition"):
        replace(
            disposition_request(outcome=LeadDispositionOutcome.WATCH_DEFER),
            watch_condition_id=None,
        )


def test_operational_hold_cannot_masquerade_as_watch() -> None:
    held = disposition_request(outcome=LeadDispositionOutcome.OPERATIONAL_HOLD)
    with pytest.raises(DiscoveryContractError, match="masquerade"):
        replace(held, watch_condition_id=watch_request().watch_condition_id)


def test_increment_3d_rejects_later_candidate_dispositions() -> None:
    queued = disposition_request()
    with pytest.raises(DiscoveryContractError, match="later triage"):
        LeadDispositionDecisionRequest(
            decision_id=queued.decision_id,
            lead_id=queued.lead_id,
            gate_decision_id=queued.gate_decision_id,
            decision_ordinal=1,
            previous_decision_id=None,
            outcome=LeadDispositionOutcome.ADMIT_NEW_CANDIDATE,
            terminality=queued.terminality,
            primary_reason=queued.primary_reason,
            supporting_reasons=(),
            watch_condition_id=None,
            next_action=queued.next_action,
            urgency_route=queued.urgency_route,
            disposition_policy=queued.disposition_policy,
            reason_taxonomy_version=queued.reason_taxonomy_version,
            outcome_taxonomy_version=queued.outcome_taxonomy_version,
            decided_at=queued.decided_at,
            idempotency_key="invalid-candidate-disposition",
        )


def test_disposition_reason_producer_bounds_are_shared_and_closed() -> None:
    references = tuple(
        ReasonReference("fixture", f"reference-{index:05d}")
        for index in range(MAX_STRUCTURED_REASON_REFERENCES)
    )
    maximum_reason = StructuredReason(
        "FIXTURE.MAXIMUM_REFERENCES",
        ReasonBasisClass.DETERMINISTIC_OBSERVATION,
        references,
        "The maximum retained reference set remains bounded.",
    )
    maximum = replace(disposition_request(), primary_reason=maximum_reason)
    assert maximum.digest

    with pytest.raises(DiscoveryContractError, match="reference count bound"):
        over_bound = replace(
            maximum_reason,
            references=references + (ReasonReference("fixture", "reference-over"),),
        )
        _ = over_bound.digest

    supporting = tuple(
        StructuredReason(
            f"FIXTURE.SUPPORTING.{index:02d}",
            ReasonBasisClass.DETERMINISTIC_OBSERVATION,
            (ReasonReference("fixture", f"supporting-{index:02d}"),),
            "A bounded supporting reason.",
        )
        for index in range(MAX_LEAD_DISPOSITION_SUPPORTING_REASONS + 1)
    )
    with pytest.raises(DiscoveryContractError, match="too many supporting"):
        over_bound = replace(disposition_request(), supporting_reasons=supporting)
        _ = over_bound.digest


def test_later_gate_and_disposition_require_exact_predecessors() -> None:
    gate = gate_request()
    with pytest.raises(DiscoveryContractError, match="exact predecessor"):
        replace(gate, decision_ordinal=2, previous_decision_id=None)
    disposition = disposition_request()
    with pytest.raises(DiscoveryContractError, match="exact predecessor"):
        replace(disposition, decision_ordinal=2, previous_decision_id=None)


def test_watch_review_cannot_follow_expiry() -> None:
    with pytest.raises(DiscoveryContractError, match="precedes review"):
        replace(watch_request(), review_at=EXPIRY, expires_at=REVIEW_AT)


def test_signal_incompleteness_requires_exact_finding_lineage() -> None:
    complete = signal_request()
    with pytest.raises(DiscoveryContractError, match="incompleteness"):
        replace(complete, incomplete=True)


def test_non_hold_gate_requires_current_authority() -> None:
    basis = replace(promoted_basis(), identity_integrity=False)
    with pytest.raises(DiscoveryContractError, match="current executable authority"):
        gate_request(
            outcome=GateOutcome.SUPPRESSED_NON_CHANGE,
            basis=replace(
                basis,
                observable_newness=ObservableNewness.PARSER_ONLY,
            ),
            next_action=NextAction(
                NextActionKind.CLOSE,
                "CLOSE_NON_CHANGE",
                instructions="Invalid because authority is not current.",
            ),
        )


def test_duplicate_gate_cannot_target_its_own_signal() -> None:
    with pytest.raises(DiscoveryContractError, match="distinct retained Signal"):
        gate_request(
            outcome=GateOutcome.SUPPRESSED_DUPLICATE,
            basis=replace(
                promoted_basis(),
                duplicate_signal_id=signal_request().signal_id,
                duplicate_rule=VersionedPolicyRef("fixture-duplicate", "v1"),
            ),
            next_action=NextAction(
                NextActionKind.CLOSE,
                "CLOSE_DUPLICATE",
                instructions="Invalid self-duplicate.",
            ),
        )


def test_gate_outcomes_require_exact_next_action_shape() -> None:
    with pytest.raises(DiscoveryContractError, match="queue-triage"):
        gate_request(
            next_action=NextAction(
                NextActionKind.CLOSE,
                "CLOSE_PROMOTION",
                instructions="Promotion cannot close before Lead creation.",
            )
        )
    with pytest.raises(DiscoveryContractError, match="explicit close"):
        gate_request(
            outcome=GateOutcome.SUPPRESSED_NON_CHANGE,
            basis=replace(
                promoted_basis(),
                observable_newness=ObservableNewness.PARSER_ONLY,
            ),
            next_action=NextAction(
                NextActionKind.QUEUE_TRIAGE,
                "QUEUE_NON_CHANGE",
                instructions="Non-change cannot enter triage.",
            ),
        )
    for outcome, basis in (
        (
            GateOutcome.SUPPRESSED_NON_CHANGE,
            replace(
                promoted_basis(),
                observable_newness=ObservableNewness.PARSER_ONLY,
            ),
        ),
        (
            GateOutcome.SUPPRESSED_DUPLICATE,
            replace(
                promoted_basis(),
                duplicate_signal_id=OTHER_SIGNAL_ID,
                duplicate_rule=VersionedPolicyRef("fixture-duplicate", "v1"),
            ),
        ),
        (
            GateOutcome.REJECTED_CLEAR_EXCLUSION,
            replace(
                promoted_basis(),
                scope_disposition=ScopeDisposition.CLEAR_EXCLUSION,
                clear_exclusion_rule=VersionedPolicyRef(
                    "fixture-exclusion",
                    "v1",
                ),
            ),
        ),
    ):
        with pytest.raises(DiscoveryContractError, match="explicit close"):
            gate_request(outcome=outcome, basis=basis, next_action=None)


def test_lead_urgency_rejects_later_editorial_reason_basis() -> None:
    editorial_urgency = replace(
        urgency(),
        primary_reason=reason(
            "UTILITY.EDITORIAL_MATERIALITY",
            ReasonBasisClass.EDITORIAL_ASSESSMENT,
        ),
    )
    with pytest.raises(DiscoveryContractError, match="later unavailable authority"):
        replace(lead_request(), urgency=editorial_urgency)


def test_foundation_disposition_rejects_later_editorial_reason_basis() -> None:
    with pytest.raises(DiscoveryContractError, match="later unavailable authority"):
        replace(
            disposition_request(),
            primary_reason=reason(
                "UTILITY.EDITORIAL_MATERIALITY",
                ReasonBasisClass.EDITORIAL_ASSESSMENT,
            ),
        )


def test_duplicate_rule_cannot_exist_without_duplicate_signal() -> None:
    with pytest.raises(DiscoveryContractError, match="duplicate rule requires"):
        replace(
            promoted_basis(),
            duplicate_rule=VersionedPolicyRef("fixture-duplicate", "v1"),
        )


def test_close_action_cannot_retain_pending_metadata() -> None:
    with pytest.raises(DiscoveryContractError, match="close action cannot retain"):
        NextAction(
            NextActionKind.CLOSE,
            "CLOSE",
            due_at=REVIEW_AT,
        )


def test_deterministic_gate_outcome_precedence_is_fail_closed() -> None:
    promoted = promoted_basis()
    assert deterministic_gate_outcome(promoted) is GateOutcome.PROMOTED_TO_LEAD
    assert deterministic_gate_outcome(
        replace(promoted, time_validity=TimeValidity.STALE)
    ) is GateOutcome.OPERATIONAL_HOLD
    assert deterministic_gate_outcome(
        replace(
            promoted,
            duplicate_signal_id=OTHER_SIGNAL_ID,
            duplicate_rule=VersionedPolicyRef("fixture-duplicate", "v1"),
        )
    ) is GateOutcome.SUPPRESSED_DUPLICATE
    assert deterministic_gate_outcome(
        replace(promoted, observable_newness=ObservableNewness.PARSER_ONLY)
    ) is GateOutcome.SUPPRESSED_NON_CHANGE
    assert deterministic_gate_outcome(
        replace(
            promoted,
            scope_disposition=ScopeDisposition.CLEAR_EXCLUSION,
            clear_exclusion_rule=VersionedPolicyRef("fixture-exclusion", "v1"),
        )
    ) is GateOutcome.REJECTED_CLEAR_EXCLUSION
    assert deterministic_gate_outcome(
        replace(
            promoted,
            scope_disposition=ScopeDisposition.AMBIGUOUS,
            ambiguities=("MATERIALITY_UNKNOWN",),
        )
    ) is GateOutcome.PROMOTED_TO_LEAD


def test_gate_request_cannot_choose_outcome_inconsistent_with_basis() -> None:
    with pytest.raises(DiscoveryContractError, match="deterministic basis"):
        gate_request(
            outcome=GateOutcome.OPERATIONAL_HOLD,
            basis=promoted_basis(),
            terminality=DecisionTerminality.PENDING_CONDITION,
            next_action=NextAction(
                NextActionKind.REVIEW,
                "REVIEW_FALSE_HOLD",
                owner="discovery-operator",
                due_at=REVIEW_AT,
                instructions="A fully valid basis cannot be held arbitrarily.",
            ),
        )
    with pytest.raises(DiscoveryContractError, match="deterministic basis"):
        gate_request(
            basis=replace(
                promoted_basis(),
                time_validity=TimeValidity.STALE,
            ),
        )


def test_transition_kind_limits_deterministic_newness_classification() -> None:
    assert permitted_newness_for_transition(
        ObservableTransitionKind.REOBSERVED
    ) == frozenset(
        {ObservableNewness.EXACT_REPEAT, ObservableNewness.PARSER_ONLY}
    )
    assert permitted_newness_for_transition(
        ObservableTransitionKind.AGENDA_RESCHEDULED
    ) == frozenset({ObservableNewness.EXPECTATION_ONLY})
    assert permitted_newness_for_transition(
        ObservableTransitionKind.AMBIGUOUS_ABSENCE
    ) == frozenset({ObservableNewness.UNKNOWN})
    assert permitted_newness_for_transition(
        ObservableTransitionKind.FIRST_OBSERVED
    ) == frozenset(
        {ObservableNewness.GENUINE_TRANSITION, ObservableNewness.UNKNOWN}
    )
    assert permitted_newness_for_transition(
        ObservableTransitionKind.REVISED
    ) == frozenset({ObservableNewness.GENUINE_TRANSITION})


def test_transition_kind_bounds_permitted_observable_newness() -> None:
    assert permitted_newness_for_transition(
        ObservableTransitionKind.REVISED
    ) == frozenset({ObservableNewness.GENUINE_TRANSITION})
    assert permitted_newness_for_transition(
        ObservableTransitionKind.REOBSERVED
    ) == frozenset(
        {ObservableNewness.EXACT_REPEAT, ObservableNewness.PARSER_ONLY}
    )
    assert permitted_newness_for_transition(
        ObservableTransitionKind.AGENDA_CREATED
    ) == frozenset({ObservableNewness.EXPECTATION_ONLY})
    assert permitted_newness_for_transition(
        ObservableTransitionKind.AMBIGUOUS_ABSENCE
    ) == frozenset({ObservableNewness.UNKNOWN})
    assert permitted_newness_for_transition(
        ObservableTransitionKind.FIRST_OBSERVED
    ) == frozenset(
        {ObservableNewness.GENUINE_TRANSITION, ObservableNewness.UNKNOWN}
    )
