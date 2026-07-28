from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.checks import (
    CheckContractError,
    ObservableTransitionId,
    ObservableTransitionKind,
    TransitionBasis,
)
from newsroom.sources import ObservationModel, SourceItemId
from newsroom.tests.check_3c_helpers import (
    ITEM_ID,
    LATER,
    PRIOR_REVISION_ID,
    REPRESENTATION_ID,
    REVISION_ID,
    absence_guard,
    first_transition,
)


def test_first_revised_and_reobserved_transitions_keep_distinct_semantics() -> None:
    first = first_transition()
    assert first.prior_revision_id is None
    assert first.current_revision_id == REVISION_ID

    revised = replace(
        first,
        transition_id=ObservableTransitionId.parse(
            "00000000-0000-4000-8000-000000006121"
        ),
        kind=ObservableTransitionKind.REVISED,
        prior_revision_id=PRIOR_REVISION_ID,
        current_revision_id=REVISION_ID,
        change_facets=("CONTENT",),
        transition_discriminator="revised-content",
        idempotency_key="fixture-transition-revised",
    )
    assert revised.prior_revision_id != revised.current_revision_id

    with pytest.raises(CheckContractError):
        replace(revised, change_facets=())

    reobserved = replace(
        first,
        transition_id=ObservableTransitionId.parse(
            "00000000-0000-4000-8000-000000006122"
        ),
        kind=ObservableTransitionKind.REOBSERVED,
        prior_revision_id=REVISION_ID,
        current_revision_id=REVISION_ID,
        change_facets=(),
        transition_discriminator="reobserved",
        idempotency_key="fixture-transition-reobserved",
    )
    assert reobserved.prior_revision_id == reobserved.current_revision_id

    with pytest.raises(CheckContractError):
        replace(reobserved, prior_revision_id=PRIOR_REVISION_ID)


def test_complete_snapshot_absence_can_end_only_with_full_guard() -> None:
    first = first_transition()
    ending = replace(
        first,
        transition_id=ObservableTransitionId.parse(
            "00000000-0000-4000-8000-000000006123"
        ),
        kind=ObservableTransitionKind.RESOLVED_OR_CLEARED,
        basis=TransitionBasis.COMPLETE_SNAPSHOT_ABSENCE,
        observation_model=ObservationModel.COMPLETE_CURRENT_STATE,
        prior_revision_id=PRIOR_REVISION_ID,
        current_revision_id=None,
        representation_id=None,
        absence_guard=absence_guard(),
        transition_discriminator="cleared-by-complete-absence",
        idempotency_key="fixture-transition-cleared",
    )
    assert ending.absence_guard is not None
    assert ending.absence_guard.authorizes_ending is True

    with pytest.raises(CheckContractError):
        replace(ending, absence_guard=absence_guard(authorizing=False))

    with pytest.raises(CheckContractError):
        replace(ending, observation_model=ObservationModel.ROLLING_LIST)

    with pytest.raises(CheckContractError):
        replace(ending, basis=TransitionBasis.REVISION)


def test_ambiguous_absence_requires_non_authorizing_evidence() -> None:
    first = first_transition()
    ambiguous = replace(
        first,
        transition_id=ObservableTransitionId.parse(
            "00000000-0000-4000-8000-000000006124"
        ),
        kind=ObservableTransitionKind.AMBIGUOUS_ABSENCE,
        basis=TransitionBasis.COMPLETE_SNAPSHOT_ABSENCE,
        observation_model=ObservationModel.ROLLING_LIST,
        prior_revision_id=PRIOR_REVISION_ID,
        current_revision_id=None,
        representation_id=None,
        absence_guard=absence_guard(authorizing=False),
        transition_discriminator="ambiguous-absence",
        idempotency_key="fixture-transition-ambiguous",
    )
    assert ambiguous.absence_guard is not None
    assert ambiguous.absence_guard.authorizes_ending is False

    with pytest.raises(CheckContractError):
        replace(ambiguous, absence_guard=absence_guard())


def test_replacement_requires_separate_item_and_change_facets() -> None:
    first = first_transition()
    replacement_item = SourceItemId.parse(
        "00000000-0000-4000-8000-000000006125"
    )
    replaced = replace(
        first,
        transition_id=ObservableTransitionId.parse(
            "00000000-0000-4000-8000-000000006126"
        ),
        kind=ObservableTransitionKind.REPLACED,
        prior_revision_id=PRIOR_REVISION_ID,
        current_revision_id=REVISION_ID,
        representation_id=REPRESENTATION_ID,
        related_item_id=replacement_item,
        change_facets=("REPLACEMENT_MARKER",),
        transition_discriminator="replacement",
        idempotency_key="fixture-transition-replaced",
    )
    assert replaced.related_item_id == replacement_item

    with pytest.raises(CheckContractError):
        replace(replaced, related_item_id=ITEM_ID)

    with pytest.raises(CheckContractError):
        replace(replaced, change_facets=())


def test_transition_semantic_identity_excludes_record_identity_and_observed_time() -> None:
    original = first_transition()
    equivalent = replace(
        original,
        transition_id=ObservableTransitionId.parse(
            "00000000-0000-4000-8000-000000006127"
        ),
        observed_at=LATER,
        idempotency_key="fixture-transition-equivalent",
    )
    assert equivalent.semantic_digest == original.semantic_digest
    assert equivalent.digest != original.digest
