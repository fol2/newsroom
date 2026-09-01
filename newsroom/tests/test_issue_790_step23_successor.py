"""#790 Step 23 binds its qualified fresh event exactly."""

from __future__ import annotations

from newsroom.control_plane import issue_790_contract as contract_module
from newsroom.control_plane.issue_790_prepared_canary import _candidate_from_plan
from newsroom.tests.test_issue_790_rehearsal_fixtures import (
    build_rehearsal_stores,
    insert_unused_queued_attempt_zero,
)

_EVENT_13696 = (
    "sha256:a50799d126f82a229e1630816ea27a0e3fff2731fee87b48c986bc0f9b51b7f2"
)
_UNRELATED_HIGHER_EVENT = "sha256:" + "f0" * 32


def test_step23_contract_is_registered_as_the_only_next_ordinal() -> None:
    assert hasattr(contract_module, "ISSUE_790_STEP23_PENDING_DIGEST")
    assert hasattr(contract_module, "ISSUE_790_STEP23_CHECKED_CANDIDATE_DIGEST")
    assert contract_module.issue_790_owner_activated_sequence(23) is True
    assert contract_module.issue_790_owner_activated_sequence(24) is False


def test_step23_plan_selects_only_qualified_event_not_higher_unrelated_queue(
    tmp_path,
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_EVENT_13696,
        ledger_seq=13696,
    )
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_UNRELATED_HIGHER_EVENT,
        ledger_seq=13702,
    )
    plan = dict(stores.plan)
    sequence = dict(plan["sequence"])
    sequence["sequence_ordinal"] = 23
    sequence["candidate_event_qualification"] = {
        "event_id": _EVENT_13696,
        "ledger_seq": 13696,
    }
    plan["sequence"] = sequence

    assert _candidate_from_plan(
        plan,
        event_id=None,
        ledger_seq=None,
        role="preflight",
        store=stores.work_unpublished,
    ) == (_EVENT_13696, 13696)
