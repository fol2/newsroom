from __future__ import annotations

from dataclasses import replace

import pytest

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
    ScopeDisposition,
    TimeValidity,
    UrgencyRoute,
)
from newsroom.discovery.models import LeadDispositionDecisionRequest
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
    with pytest.raises(DiscoveryContractError, match="may only close"):
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
