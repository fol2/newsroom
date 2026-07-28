from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.checks import (
    BaselineAction,
    BaselineControl,
    BaselineDecisionId,
    CheckContractError,
    ObservableTransitionKind,
    TransitionDirective,
)

from .check_3c_helpers import DIGEST_A, DIGEST_B, absence_guard, agenda_guard


def test_baseline_reset_and_rebuild_require_exact_typed_predecessor() -> None:
    predecessor = BaselineDecisionId.parse(
        "00000000-0000-4000-8000-000000009001"
    )
    reset = BaselineControl(
        action=BaselineAction.RESET,
        previous_decision_id=predecessor,
        reason_codes=("OPERATOR_RESET",),
    )
    rebuild = BaselineControl(
        action=BaselineAction.REBUILD,
        previous_decision_id=predecessor,
        reason_codes=("SOURCE_CONTRACT_CHANGED",),
    )

    assert reset.canonical_value()["previous_decision_id"] == str(predecessor)
    assert rebuild.canonical_value()["action"] == "REBUILD"
    with pytest.raises(CheckContractError, match="requires exact predecessor"):
        BaselineControl(action=BaselineAction.RESET)
    with pytest.raises(CheckContractError, match="cannot name a predecessor"):
        BaselineControl(previous_decision_id=predecessor)
    with pytest.raises(CheckContractError, match="sorted and unique"):
        BaselineControl(
            action=BaselineAction.REBUILD,
            previous_decision_id=predecessor,
            reason_codes=("Z", "A"),
        )


def test_transition_directive_guards_are_kind_specific_and_fail_closed() -> None:
    ambiguous = TransitionDirective(
        item_key=DIGEST_A,
        kind=ObservableTransitionKind.AMBIGUOUS_ABSENCE,
        transition_discriminator="rolling-absence",
        absence_guard=absence_guard(authorizing=False),
    )
    missed = TransitionDirective(
        item_key=DIGEST_A,
        kind=ObservableTransitionKind.AGENDA_MISSED_EXPECTATION,
        transition_discriminator="agenda-miss",
        agenda_guard=agenda_guard(authorizing=True),
    )

    assert ambiguous.absence_guard is not None
    assert not ambiguous.absence_guard.authorizes_ending
    assert missed.agenda_guard is not None
    assert missed.agenda_guard.authorizes_miss

    with pytest.raises(CheckContractError, match="non-authorizing guard"):
        replace(ambiguous, absence_guard=absence_guard(authorizing=True))
    with pytest.raises(CheckContractError, match="authorizing Agenda guard"):
        replace(missed, agenda_guard=agenda_guard(authorizing=False))
    with pytest.raises(CheckContractError, match="reserved for missed-expectation"):
        TransitionDirective(
            item_key=DIGEST_A,
            kind=ObservableTransitionKind.AGENDA_CREATED,
            transition_discriminator="agenda-created",
            agenda_guard=agenda_guard(authorizing=True),
        )


def test_state_change_and_replacement_directives_bind_exact_facets() -> None:
    escalation = TransitionDirective(
        item_key=DIGEST_A,
        kind=ObservableTransitionKind.ESCALATED,
        transition_discriminator="severity-increased",
        change_facets=("SEVERITY",),
    )
    replacement = TransitionDirective(
        item_key=DIGEST_A,
        kind=ObservableTransitionKind.REPLACED,
        transition_discriminator="superseded",
        change_facets=("REPLACEMENT",),
        related_item_key=DIGEST_B,
    )

    assert escalation.change_facets == ("SEVERITY",)
    assert replacement.related_item_key == DIGEST_B
    with pytest.raises(CheckContractError, match="requires change facets"):
        replace(escalation, change_facets=())
    with pytest.raises(CheckContractError, match="requires related item key"):
        replace(replacement, related_item_key=None)
    with pytest.raises(CheckContractError, match="reserved for replacement"):
        TransitionDirective(
            item_key=DIGEST_A,
            kind=ObservableTransitionKind.REVISED,
            transition_discriminator="revised",
            change_facets=("BODY",),
            related_item_key=DIGEST_B,
        )
