from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from newsroom.increment6.outcomes import (
    CANONICAL_NEXT_ACTION,
    DECISION_TERMINALITY,
    OUTCOME_TAXONOMY_VERSION,
    PRIORITY_LANE,
    REASON_TAXONOMY_VERSION,
    SUPPLEMENTAL_ACTION_MAPPING,
    TRIAGE_OUTCOME,
    TRIAGE_REASON_CODE,
    WATCH_CONDITION_MAPPING,
    CanonicalNextAction,
    CanonicalOutcome,
    ContractAuthority,
    ContractEffect,
    DecisionTerminality,
    NextAction,
    NextActionKind,
    OutcomeContractError,
    OutcomeFamily,
    OutcomeSelection,
    PriorityLane,
    PrioritySelection,
    ReasonBasisClass,
    ReasonCode,
    ReasonFamily,
    ReasonReference,
    StructuredReason,
    outcome_family,
)
from newsroom.discovery import LeadDispositionOutcome


EXPECTED_OUTCOMES = {
    "NO_WORK_DUE",
    "PREFLIGHT_BLOCKED",
    "CHECK_UNCHANGED",
    "CHECK_CHANGED",
    "CHECK_PARTIAL",
    "CHECK_FAILED_RETRYABLE",
    "CHECK_FAILED_BLOCKING",
    "CHECK_QUARANTINED",
    "SIGNAL_SUPPRESSED_DUPLICATE",
    "SIGNAL_SUPPRESSED_NON_CHANGE",
    "SIGNAL_REJECTED_CLEAR_EXCLUSION",
    "SIGNAL_PROMOTED_TO_LEAD",
    "SIGNAL_OPERATIONAL_HOLD",
    "LEAD_EDITORIAL_REJECT",
    "LEAD_QUEUED_FOR_TRIAGE",
    "LEAD_WATCH_DEFER",
    "LEAD_ASSOCIATE_WITHOUT_CANDIDATE",
    "LEAD_SUPPLEMENTAL_DISCOVERY",
    "LEAD_OPERATIONAL_HOLD",
    "LEAD_ADMIT_NEW_CANDIDATE",
    "LEAD_ADMIT_DEVELOPMENT_CANDIDATE",
    "LEAD_ADMIT_CORRECTION_CANDIDATE",
    "REL_SAME_STATE",
    "REL_DEVELOPMENT_OF",
    "REL_CORRECTION_REVERSAL_OF",
    "REL_RELATED_DISTINCT",
    "REL_NO_ADEQUATE_PRIOR_MATCH",
    "REL_UNCERTAIN",
    "CANDIDATE_ADMITTED",
    "CANDIDATE_ADMISSION_INVALID",
    "CANDIDATE_ADMISSION_BLOCKED",
    "CANDIDATE_VERSION_SUPERSEDED",
    "HANDOFF_PENDING",
    "HANDOFF_ACKNOWLEDGED",
    "HANDOFF_RETRY_REQUIRED",
    "HANDOFF_OPERATIONAL_HOLD",
    "EVIDENCE_FEEDBACK_RECEIVED",
    "HEALTH_HEALTHY",
    "HEALTH_DEGRADED",
    "HEALTH_STALE",
    "HEALTH_UNAVAILABLE",
    "HEALTH_QUARANTINED",
    "HEALTH_BLOCKED",
    "HEALTH_UNKNOWN",
    "COVERAGE_AVAILABLE",
    "COVERAGE_DEGRADED",
    "COVERAGE_BLOCKED",
    "COVERAGE_UNKNOWN",
}


def _reason() -> StructuredReason:
    return StructuredReason(
        code=ReasonCode.CHANGE_GENUINE_TRANSITION,
        basis=ReasonBasisClass.DETERMINISTIC_OBSERVATION,
        references=(
            ReasonReference(
                reference_type="SOURCE_REVISION",
                identifier="revision-1",
            ),
        ),
        explanation="The exact source revision contains a qualifying transition.",
    )


def _selection() -> OutcomeSelection:
    return OutcomeSelection(
        outcome=CanonicalOutcome.SIGNAL_PROMOTED_TO_LEAD,
        terminality=DecisionTerminality.TERMINAL_EXACT_VERSION,
        primary_reason=_reason(),
        supporting_reasons=(),
        next_action=NextAction(
            kind=NextActionKind.QUEUE_TRIAGE,
            action_code=CanonicalNextAction.QUEUE_FOR_TRIAGE,
        ),
    )


def test_complete_closed_outcome_vocabulary_has_one_family_per_value() -> None:
    assert {item.value for item in CanonicalOutcome} == EXPECTED_OUTCOMES
    assert set(OutcomeFamily) == {
        OutcomeFamily.CHECK,
        OutcomeFamily.SIGNAL,
        OutcomeFamily.LEAD,
        OutcomeFamily.RELATIONSHIP,
        OutcomeFamily.CANDIDATE_HANDOFF,
        OutcomeFamily.HEALTH,
        OutcomeFamily.COVERAGE,
    }
    assert {outcome_family(item) for item in CanonicalOutcome} == set(OutcomeFamily)


def test_reason_vocabulary_is_closed_namespaced_and_typed() -> None:
    expected_families = {
        "AUTH",
        "SCOPE",
        "CHANGE",
        "NOVELTY",
        "UTILITY",
        "REL",
        "TIME",
        "SOURCE",
        "RIGHTS",
        "OPS",
        "CAPACITY",
        "SEARCH",
        "EVAL",
    }
    assert {item.family.value for item in ReasonCode} == expected_families
    assert {item.value for item in ReasonFamily} == expected_families
    assert len(ReasonCode) == 75
    assert len(ReasonCode.__members__) == len(ReasonCode)
    with pytest.raises(ValueError):
        ReasonCode("OPS.PRIVATE_ALIAS")
    assert ReasonCode.RIGHTS_RETENTION.value == "RIGHTS.RETENTION"


def test_allocated_public_contract_names_and_schema_identities_are_exact() -> None:
    assert TRIAGE_OUTCOME is CanonicalOutcome
    assert TRIAGE_REASON_CODE is ReasonCode
    assert PRIORITY_LANE is PriorityLane
    assert CANONICAL_NEXT_ACTION is CanonicalNextAction
    assert DECISION_TERMINALITY is DecisionTerminality
    assert OutcomeSelection.SCHEMA_VERSION == "newsroom.increment6.outcomes.v1"
    assert PrioritySelection.SCHEMA_VERSION == "newsroom.increment6.outcomes.v1"
    assert StructuredReason.SCHEMA_VERSION == "newsroom.increment6.reasons.v1"
    assert {OUTCOME_TAXONOMY_VERSION, REASON_TAXONOMY_VERSION} == {
        "newsroom.increment6.outcomes.v1",
        "newsroom.increment6.reasons.v1",
    }


def test_existing_discovery_watch_and_supplemental_routes_map_one_to_one() -> None:
    canonical_lead_outcomes = {
        item.value
        for item in CanonicalOutcome
        if outcome_family(item) is OutcomeFamily.LEAD
    }
    retained_triage_outcomes = {
        item.value for item in LeadDispositionOutcome
    }
    assert retained_triage_outcomes == canonical_lead_outcomes

    watch = WATCH_CONDITION_MAPPING[LeadDispositionOutcome.WATCH_DEFER]
    assert watch.source_outcome == LeadDispositionOutcome.WATCH_DEFER.value
    assert watch.outcome is CanonicalOutcome.LEAD_WATCH_DEFER
    assert watch.terminality is DecisionTerminality.PENDING_CONDITION
    assert watch.next_action is CanonicalNextAction.AWAIT_WATCH_CONDITION
    assert watch.requires_exact_watch_condition is True
    assert watch.requires_bounded_supplemental_action is False

    supplemental = SUPPLEMENTAL_ACTION_MAPPING[
        LeadDispositionOutcome.SUPPLEMENTAL_DISCOVERY
    ]
    assert supplemental.source_outcome == (
        LeadDispositionOutcome.SUPPLEMENTAL_DISCOVERY.value
    )
    assert supplemental.outcome is CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY
    assert supplemental.terminality is DecisionTerminality.PENDING_CONDITION
    assert supplemental.next_action is CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY
    assert supplemental.requires_exact_watch_condition is False
    assert supplemental.requires_bounded_supplemental_action is True
    assert watch.authorises_persistence is False
    with pytest.raises(TypeError):
        WATCH_CONDITION_MAPPING[LeadDispositionOutcome.EDITORIAL_REJECT] = watch  # type: ignore[index]


_DISCOVERY_LEAD_MATRIX = {
    CanonicalOutcome.LEAD_QUEUED_FOR_TRIAGE: {
        (
            DecisionTerminality.PENDING_CONDITION,
            CanonicalNextAction.QUEUE_FOR_TRIAGE,
        ),
    },
    CanonicalOutcome.LEAD_EDITORIAL_REJECT: {
        (
            DecisionTerminality.TERMINAL_EXACT_VERSION,
            CanonicalNextAction.CLOSE_DECISION,
        ),
    },
    CanonicalOutcome.LEAD_WATCH_DEFER: {
        (
            DecisionTerminality.PENDING_CONDITION,
            CanonicalNextAction.AWAIT_WATCH_CONDITION,
        ),
    },
    CanonicalOutcome.LEAD_ASSOCIATE_WITHOUT_CANDIDATE: {
        (
            DecisionTerminality.TERMINAL_EXACT_VERSION,
            CanonicalNextAction.CLOSE_DECISION,
        ),
    },
    CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY: {
        (
            DecisionTerminality.PENDING_CONDITION,
            CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY,
        ),
    },
    CanonicalOutcome.LEAD_OPERATIONAL_HOLD: {
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
    },
    CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE: {
        (
            DecisionTerminality.TERMINAL_EXACT_VERSION,
            CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ),
    },
    CanonicalOutcome.LEAD_ADMIT_DEVELOPMENT_CANDIDATE: {
        (
            DecisionTerminality.TERMINAL_EXACT_VERSION,
            CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ),
    },
    CanonicalOutcome.LEAD_ADMIT_CORRECTION_CANDIDATE: {
        (
            DecisionTerminality.TERMINAL_EXACT_VERSION,
            CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ),
    },
}


def _action(action: CanonicalNextAction) -> NextAction:
    condition = None
    if action.kind in {
        NextActionKind.RETRY,
        NextActionKind.REVIEW,
        NextActionKind.WAIT_DEPENDENCY,
        NextActionKind.RESUME_ON_WATCH,
        NextActionKind.REQUEST_SUPPLEMENTAL_DISCOVERY,
    }:
        condition = "condition-1"
    return NextAction(
        kind=action.kind,
        action_code=action,
        condition_reference=condition,
    )


def test_complete_retained_discovery_lead_semantic_matrix() -> None:
    assert set(_DISCOVERY_LEAD_MATRIX) == {
        CanonicalOutcome(item.value) for item in LeadDispositionOutcome
    }

    for outcome, permitted in _DISCOVERY_LEAD_MATRIX.items():
        with pytest.raises(OutcomeContractError, match="next action"):
            replace(
                _selection(),
                outcome=outcome,
                terminality=next(iter(permitted))[0],
                next_action=None,
            )
        for terminality, action in permitted:
            selection = replace(
                _selection(),
                outcome=outcome,
                terminality=terminality,
                next_action=_action(action),
            )
            assert selection.outcome is outcome

        for terminality in DecisionTerminality:
            for action in CanonicalNextAction:
                if (terminality, action) in permitted:
                    continue
                with pytest.raises(OutcomeContractError):
                    replace(
                        _selection(),
                        outcome=outcome,
                        terminality=terminality,
                        next_action=_action(action),
                    )


def test_watch_and_supplemental_actions_cannot_be_swapped() -> None:
    with pytest.raises(OutcomeContractError, match="next action"):
        replace(
            _selection(),
            outcome=CanonicalOutcome.LEAD_WATCH_DEFER,
            terminality=DecisionTerminality.PENDING_CONDITION,
            next_action=_action(CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY),
        )
    with pytest.raises(OutcomeContractError, match="next action"):
        replace(
            _selection(),
            outcome=CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY,
            terminality=DecisionTerminality.PENDING_CONDITION,
            next_action=_action(CanonicalNextAction.AWAIT_WATCH_CONDITION),
        )


def test_priority_lanes_are_fixed_ordinal_values_not_floating_scores() -> None:
    assert [(lane.value, lane.ordinal) for lane in PriorityLane] == [
        ("CONTAINMENT", 1),
        ("URGENT", 2),
        ("TIME_SENSITIVE", 3),
        ("PLANNED_WINDOW", 4),
        ("ROUTINE", 5),
        ("OPTIONAL_EVALUATION", 6),
    ]
    with pytest.raises(ValueError):
        PriorityLane("1.5")


def test_outcome_selection_is_immutable_canonical_and_round_trips_strictly() -> None:
    selection = _selection()
    assert selection.schema_version == "newsroom.increment6.outcomes.v1"
    assert selection.outcome_taxonomy_version == OUTCOME_TAXONOMY_VERSION
    assert selection.reason_taxonomy_version == REASON_TAXONOMY_VERSION
    assert OutcomeSelection.from_canonical_bytes(selection.canonical_bytes) == selection
    assert json.loads(selection.canonical_bytes) == selection.canonical_value()
    with pytest.raises(FrozenInstanceError):
        selection.outcome = CanonicalOutcome.CHECK_CHANGED  # type: ignore[misc]


def test_duplicate_unknown_noncanonical_and_cross_version_inputs_fail_closed() -> None:
    selection = _selection()
    raw = selection.canonical_bytes
    duplicate = raw.replace(
        b"{",
        b'{"schema_version":"newsroom.increment6.outcomes.v1",',
        1,
    )
    with pytest.raises(OutcomeContractError, match="duplicate"):
        OutcomeSelection.from_canonical_bytes(duplicate)

    value = json.loads(raw)
    value["private_alias"] = "PROMOTE"
    with pytest.raises(OutcomeContractError, match="fields"):
        OutcomeSelection.from_mapping(value)

    value = json.loads(raw)
    value["schema_version"] = "newsroom.increment6.outcomes.v2"
    with pytest.raises(OutcomeContractError, match="schema version"):
        OutcomeSelection.from_mapping(value)

    pretty = json.dumps(json.loads(raw), indent=2).encode()
    with pytest.raises(OutcomeContractError, match="canonical"):
        OutcomeSelection.from_canonical_bytes(pretty)


def test_unknown_nested_fields_and_untyped_or_duplicate_reasons_fail_closed() -> None:
    value = _selection().canonical_value()
    primary = dict(value["primary_reason"])
    primary["confidence"] = 0.9
    value["primary_reason"] = primary
    with pytest.raises(OutcomeContractError, match="fields"):
        OutcomeSelection.from_mapping(value)

    with pytest.raises(OutcomeContractError, match="typed"):
        replace(  # type: ignore[arg-type]
            _selection(), outcome="SIGNAL_PROMOTED_TO_LEAD"
        )

    with pytest.raises(OutcomeContractError, match="duplicate"):
        replace(_selection(), supporting_reasons=(_reason(),))

    reason = _reason()
    assert StructuredReason.from_canonical_bytes(reason.canonical_bytes) == reason
    reason_value = reason.canonical_value()
    reason_value["schema_version"] = "newsroom.increment6.reasons.v2"
    with pytest.raises(OutcomeContractError, match="schema version"):
        StructuredReason.from_mapping(reason_value)

    duplicate_reason = reason.canonical_bytes.replace(
        b"{",
        b'{"schema_version":"newsroom.increment6.reasons.v1",',
        1,
    )
    with pytest.raises(OutcomeContractError, match="duplicate"):
        StructuredReason.from_canonical_bytes(duplicate_reason)


def test_terminal_and_pending_semantics_require_explicit_compatible_actions() -> None:
    with pytest.raises(OutcomeContractError, match="pending"):
        replace(
            _selection(),
            outcome=CanonicalOutcome.LEAD_WATCH_DEFER,
            terminality=DecisionTerminality.PENDING_CONDITION,
            next_action=None,
        )

    pending = replace(
        _selection(),
        outcome=CanonicalOutcome.LEAD_WATCH_DEFER,
        terminality=DecisionTerminality.PENDING_CONDITION,
        next_action=NextAction(
            kind=NextActionKind.RESUME_ON_WATCH,
            action_code=CanonicalNextAction.AWAIT_WATCH_CONDITION,
            condition_reference="watch-condition-1",
        ),
    )
    assert pending.next_action is not None


def test_contract_values_explicitly_carry_no_authority_or_external_effect() -> None:
    selection = _selection()
    priority = PrioritySelection(
        work_identity="work-item-1",
        work_version="v1",
        lane=PriorityLane.URGENT,
        basis_references=(
            ReasonReference("DEADLINE", "deadline-1"),
        ),
    )
    for value in (selection, priority):
        assert value.authority is ContractAuthority.NONE
        assert value.effect is ContractEffect.NONE
        assert value.canonical_value()["authority"] == "NONE"
        assert value.canonical_value()["effect"] == "NONE"
        assert value.authorises_eligibility is False
        assert value.authorises_persistence is False
        assert value.authorises_external_effect is False
        assert value.authorises_publication is False

    outcome_value = selection.canonical_value()
    outcome_value["authority"] = "EDITORIAL"
    with pytest.raises(OutcomeContractError, match="authority"):
        OutcomeSelection.from_mapping(outcome_value)

    priority_value = priority.canonical_value()
    priority_value["effect"] = "QUEUE_WRITE"
    with pytest.raises(OutcomeContractError, match="effect"):
        PrioritySelection.from_mapping(priority_value)

    assert PrioritySelection.from_canonical_bytes(priority.canonical_bytes) == priority
    assert "outcome" not in priority.canonical_value()
    assert "priority_lane" not in selection.canonical_value()


def test_priority_selection_rejects_float_unknown_fields_and_cross_version() -> None:
    priority = PrioritySelection(
        work_identity="work-item-1",
        work_version="v1",
        lane=PriorityLane.ROUTINE,
        basis_references=(ReasonReference("QUEUE_AGE", "age-1"),),
    )
    value = priority.canonical_value()
    value["score"] = 0.5
    with pytest.raises(OutcomeContractError, match="fields"):
        PrioritySelection.from_mapping(value)

    value = priority.canonical_value()
    value["schema_version"] = "newsroom.increment6.outcomes.v2"
    with pytest.raises(OutcomeContractError, match="schema version"):
        PrioritySelection.from_mapping(value)


def test_next_action_codes_are_closed_and_match_their_kinds() -> None:
    with pytest.raises(OutcomeContractError, match="typed"):
        NextAction(  # type: ignore[arg-type]
            kind=NextActionKind.QUEUE_TRIAGE,
            action_code="PRIVATE_QUEUE_ALIAS",
        )
    with pytest.raises(OutcomeContractError, match="does not match"):
        NextAction(
            kind=NextActionKind.CLOSE,
            action_code=CanonicalNextAction.QUEUE_FOR_TRIAGE,
        )
