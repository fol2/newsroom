"""#790 Step 23 binds its qualified fresh event exactly."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from newsroom.control_plane import issue_790_canary as canary_module
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane.issue_790_prepared_canary import (
    BOUNDED_CANARY_AUTHORITY_CONSUMED,
    PreparedCanaryError,
    _candidate_from_plan,
)
from newsroom.tests.test_issue_790_rehearsal_fixtures import (
    build_rehearsal_stores,
    insert_unused_queued_attempt_zero,
)

_EVENT_13696 = (
    "sha256:a50799d126f82a229e1630816ea27a0e3fff2731fee87b48c986bc0f9b51b7f2"
)
_EVENT_13702 = (
    "sha256:bf467ee5908bca49b84d8309cceb225503e627177e7065efefb0a54196e8ef15"
)
_UNRELATED_HIGHER_EVENT = "sha256:" + "f0" * 32


def test_step23_plan_selects_only_qualified_event_not_higher_unrelated_queue(
    tmp_path,
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_EVENT_13702,
        ledger_seq=13702,
    )
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_UNRELATED_HIGHER_EVENT,
        ledger_seq=13708,
    )
    plan = dict(stores.plan)
    sequence = dict(plan["sequence"])
    sequence["sequence_ordinal"] = 22
    sequence["candidate_event_qualification"] = {
        "schema_version": "newsroom.issue-790.candidate-event-qualification.v1",
        "status": "READY_FOR_OWNER_PACKET",
        "event_id": _EVENT_13702,
        "ledger_seq": 13702,
        "event_manifest_digest": (
            "sha256:3e3fb1143091b9e8f364a1db22503b803a859da098a67dcc36964cf1565f774b"
        ),
        "event_preflight_digest": (
            "sha256:22dda71d2a9ae6a6ef69a679b5662300ff9adf4c2263d2b7920f29a0defe5f7a"
        ),
        "resolved_unit_count": 1,
        "provider_calls": 0,
        "store_mutations": 0,
        "observed_at": "2026-09-01T01:31:53.722227Z",
        "qualification_digest": (
            "sha256:c1dca544d0de449d7a951d3673858ce7700e5271ad56a372ba0706a3fae6604c"
        ),
    }
    plan["sequence"] = sequence

    assert _candidate_from_plan(
        plan,
        event_id=None,
        ledger_seq=None,
        role="preflight",
        store=stores.work_unpublished,
    ) == (_EVENT_13702, 13702)


def test_completed_consumption_exhausts_plan_before_dynamic_successor_selection(
    tmp_path,
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    insert_unused_queued_attempt_zero(
        stores.work_unpublished,
        source_ledger_seq=13665,
        event_id=_UNRELATED_HIGHER_EVENT,
        ledger_seq=13702,
    )
    plan_digest = str(stores.plan["canonical_digest"])
    connection = sqlite3.connect(stores.work_unpublished)
    try:
        connection.execute(
            "INSERT INTO issue_790_bounded_canary_consumptions VALUES(?,?,?,?,?,?,?,?)",
            (
                "sha256:" + "11" * 32,
                plan_digest,
                "sha256:" + "22" * 32,
                _EVENT_13696,
                13696,
                "issue-790-canary:spent",
                "2026-09-01T01:00:00.000000Z",
                "{}",
            ),
        )
        connection.execute(
            "INSERT INTO issue_790_bounded_canary_outcomes VALUES(?,?,?,?,?,?)",
            (
                "sha256:" + "33" * 32,
                "sha256:" + "11" * 32,
                _EVENT_13696,
                13696,
                "2026-09-01T01:01:00.000000Z",
                "{}",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(PreparedCanaryError) as caught:
        _candidate_from_plan(
            stores.plan,
            event_id=None,
            ledger_seq=None,
            role="preflight",
            store=stores.work_unpublished,
        )
    assert caught.value.failure_code == BOUNDED_CANARY_AUTHORITY_CONSUMED


def test_consume_rejects_second_event_for_same_completed_plan(
    tmp_path, monkeypatch
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan_digest = str(stores.plan["canonical_digest"])
    connection = sqlite3.connect(stores.work_unpublished)
    try:
        connection.execute(
            "INSERT INTO issue_790_bounded_canary_consumptions VALUES(?,?,?,?,?,?,?,?)",
            (
                "sha256:" + "11" * 32,
                plan_digest,
                "sha256:" + "22" * 32,
                _EVENT_13696,
                13696,
                "issue-790-canary:spent",
                "2026-09-01T01:00:00.000000Z",
                "{}",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setattr(
        canary_module,
        "_require_effective_plan_contract",
        lambda *_args, **_kwargs: SimpleNamespace(invocation_id="invocation"),
    )

    repository = Issue790CanaryRepository.open_existing(
        str(stores.work_unpublished)
    )
    with pytest.raises(
        Issue790CanaryIntegrityError,
        match="bounded canary authority is already consumed",
    ):
        repository.consume(
            approved_plan_digest=plan_digest,
            disposition_digest="sha256:" + "44" * 32,
            event_id=_EVENT_13702,
            ledger_seq=13702,
            owner_id="issue-790-canary:successor",
            preflight_evidence={},
            consumed_at=datetime(2026, 9, 1, 1, 2, tzinfo=UTC),
        )
