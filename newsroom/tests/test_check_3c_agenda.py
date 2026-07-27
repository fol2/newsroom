from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.checks import (
    CheckContractError,
    ObservableTransitionId,
    ObservableTransitionKind,
    TransitionBasis,
)
from newsroom.sources import ObservationModel
from newsroom.tests.check_3c_helpers import (
    PRIOR_REVISION_ID,
    REPRESENTATION_ID,
    REVISION_ID,
    agenda_guard,
    first_transition,
)


def test_agenda_guard_requires_complete_confirmation_without_source_failure() -> None:
    complete = agenda_guard()
    assert complete.authorizes_miss is True

    assert agenda_guard(authorizing=False).authorizes_miss is False
    assert replace(complete, source_failure_absent=False).authorizes_miss is False
    assert (
        replace(complete, no_reschedule_or_cancellation=False).authorizes_miss
        is False
    )


def test_agenda_creation_is_expectation_only_with_current_revision() -> None:
    first = first_transition()
    created = replace(
        first,
        transition_id=ObservableTransitionId.parse(
            "00000000-0000-4000-8000-000000006131"
        ),
        kind=ObservableTransitionKind.AGENDA_CREATED,
        basis=TransitionBasis.AGENDA_EXPECTATION,
        observation_model=ObservationModel.PLANNED_AGENDA,
        prior_revision_id=None,
        current_revision_id=REVISION_ID,
        representation_id=REPRESENTATION_ID,
        transition_discriminator="agenda-created",
        idempotency_key="fixture-agenda-created",
    )
    assert created.agenda_guard is None
    assert created.current_revision_id == REVISION_ID

    with pytest.raises(CheckContractError):
        replace(created, observation_model=ObservationModel.MUTABLE_ITEM)


def test_missed_expectation_requires_exact_complete_guard_and_no_current_revision() -> None:
    first = first_transition()
    missed = replace(
        first,
        transition_id=ObservableTransitionId.parse(
            "00000000-0000-4000-8000-000000006132"
        ),
        kind=ObservableTransitionKind.AGENDA_MISSED_EXPECTATION,
        basis=TransitionBasis.AGENDA_EXPECTATION,
        observation_model=ObservationModel.PLANNED_AGENDA,
        prior_revision_id=PRIOR_REVISION_ID,
        current_revision_id=None,
        representation_id=None,
        agenda_guard=agenda_guard(),
        transition_discriminator="agenda-missed",
        idempotency_key="fixture-agenda-missed",
    )
    assert missed.agenda_guard is not None
    assert missed.agenda_guard.authorizes_miss is True

    with pytest.raises(CheckContractError):
        replace(missed, agenda_guard=agenda_guard(authorizing=False))

    with pytest.raises(CheckContractError):
        replace(missed, current_revision_id=REVISION_ID)

    with pytest.raises(CheckContractError):
        replace(missed, representation_id=REPRESENTATION_ID)


def test_non_agenda_transition_cannot_carry_agenda_guard() -> None:
    with pytest.raises(CheckContractError):
        replace(first_transition(), agenda_guard=agenda_guard())
