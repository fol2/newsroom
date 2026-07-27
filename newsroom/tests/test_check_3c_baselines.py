from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.checks import (
    BaselineDecisionId,
    BaselineDecisionKind,
    BaselineDisposition,
    BaselineEntryDisposition,
    BaselineManifestEntry,
    CheckContractError,
)
from newsroom.sources import ObservationModel
from newsroom.tests.check_3c_helpers import (
    BASELINE_ID,
    DIGEST_A,
    DIGEST_C,
    DIGEST_D,
    ITEM_ID,
    LATER,
    PRIOR_REVISION_ID,
    baseline_decision,
    baseline_entry,
)


def test_baseline_disposition_is_bound_to_observation_model() -> None:
    maintained = baseline_decision()
    assert maintained.observation_model is ObservationModel.MUTABLE_ITEM
    assert (
        maintained.disposition
        is BaselineDisposition.MAINTAINED_BASELINE_ONLY
    )

    with pytest.raises(CheckContractError):
        baseline_decision(
            observation_model=ObservationModel.ROLLING_LIST,
            disposition=BaselineDisposition.MAINTAINED_BASELINE_ONLY,
        )

    active = baseline_decision(
        observation_model=ObservationModel.COMPLETE_CURRENT_STATE,
        disposition=BaselineDisposition.FIRST_OBSERVED_ACTIVE,
    )
    assert active.entries[0].item_id == ITEM_ID

    with pytest.raises(CheckContractError):
        baseline_decision(
            observation_model=ObservationModel.COMPLETE_CURRENT_STATE,
            disposition=BaselineDisposition.FIRST_OBSERVED_ACTIVE,
            entries=(),
        )


def test_baseline_reset_and_rebuild_require_exact_predecessor() -> None:
    established = baseline_decision()

    with pytest.raises(CheckContractError):
        replace(
            established,
            previous_decision_id=BASELINE_ID,
        )

    reset_id = BaselineDecisionId.parse(
        "00000000-0000-4000-8000-000000006112"
    )
    reset = replace(
        established,
        decision_id=reset_id,
        kind=BaselineDecisionKind.RESET,
        previous_decision_id=BASELINE_ID,
        decided_at=LATER,
        idempotency_key="fixture-baseline-reset",
    )
    assert reset.previous_decision_id == BASELINE_ID

    with pytest.raises(CheckContractError):
        replace(
            established,
            decision_id=reset_id,
            kind=BaselineDecisionKind.REBUILD,
            previous_decision_id=None,
        )


def test_bounded_backfill_retains_included_and_excluded_manifest_entries() -> None:
    included = baseline_entry()
    excluded = BaselineManifestEntry(
        item_key=DIGEST_D,
        disposition=BaselineEntryDisposition.EXCLUDED,
        reason_code="OUTSIDE_WINDOW",
    )
    decision = baseline_decision(
        observation_model=ObservationModel.APPEND_ONLY,
        disposition=BaselineDisposition.BOUNDED_BACKFILL,
        entries=(included, excluded),
    )

    assert tuple(item.disposition for item in decision.entries) == (
        BaselineEntryDisposition.INCLUDED,
        BaselineEntryDisposition.EXCLUDED,
    )
    assert decision.item_keys_digest

    with pytest.raises(CheckContractError):
        BaselineManifestEntry(
            item_key=DIGEST_A,
            disposition=BaselineEntryDisposition.INCLUDED,
            reason_code="MISSING_LINEAGE",
        )

    with pytest.raises(CheckContractError):
        BaselineManifestEntry(
            item_key=DIGEST_A,
            disposition=BaselineEntryDisposition.EXCLUDED,
            reason_code="PARTIAL_LINEAGE",
            item_id=ITEM_ID,
            revision_id=None,
        )


def test_baseline_parser_lineage_digests_move_together() -> None:
    decision = baseline_decision()
    with pytest.raises(CheckContractError):
        replace(decision, representation_digest=None)

    held = replace(
        decision,
        disposition=BaselineDisposition.MANUAL_HOLD,
        entries=(),
        source_body_digest=None,
        producer_slot_digest=None,
        representation_digest=None,
        reason_codes=("MANUAL_HOLD",),
    )
    assert held.entries == ()


def test_baseline_semantic_identity_excludes_decision_identity_and_time() -> None:
    original = baseline_decision()
    later = replace(
        original,
        decision_id=BaselineDecisionId.parse(
            "00000000-0000-4000-8000-000000006113"
        ),
        decided_at=LATER,
        idempotency_key="fixture-baseline-equivalent",
    )
    assert later.semantic_digest == original.semantic_digest
    assert later.digest != original.digest

    changed = replace(
        original,
        entries=(
            BaselineManifestEntry(
                item_key=DIGEST_C,
                disposition=BaselineEntryDisposition.INCLUDED,
                reason_code="INITIAL_INCLUDED",
                item_id=ITEM_ID,
                revision_id=PRIOR_REVISION_ID,
            ),
        ),
    )
    assert changed.semantic_digest != original.semantic_digest
