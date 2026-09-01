"""Provider-free forecast smokes that gate #790 live canary preflight."""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.issue_790_live_canary_preflight import (
    LATEST_FAILURE_COVERING_FULL_PATH_TESTS,
    REQUIRED_RETRY_LEDGER_SEQS,
    STEP21_FULL_PATH_TEST,
    STEP22_ABORTED_SPAWN_13689_BACKUP_DEST_FULL_PATH_TEST,
    STEP22_UNMATCHED_13689_CONSUMPTION_BLOCKS_13690_READY_FULL_PATH_TEST,
    STEP22_BROKERERROR_SETUP_FULL_PATH_TEST,
    STEP22_CANDIDATE_IDENTITY_FULL_PATH_TEST,
    STEP22_CONSUMED_13677_ZERO_FULL_PATH_TEST,
    STEP22_CONSUMED_13683_ZERO_FULL_PATH_TEST,
    STEP22_PERSISTABLE_EMPTY_FULL_PATH_TEST,
    STEP22_PREPARED_CANARY_HANDOFF_FULL_PATH_TEST,
    STEP22_PREPARED_CANARY_DECISION_DIGEST_PARITY_FULL_PATH_TEST,
    STEP22_PRODUCTION_UNTOUCHED_FULL_PATH_TEST,
    _blocker_smokes,
    _effective_retry_exclusion_status,
    _eligible_candidate_rows,
    _focus_gate_hits,
    _graphiti_runtime_status,
    _inspection_sql_smoke,
    _invalid_sha256_paths,
    _latest_failure_red_green,
    _ops_gates,
    _prepare_preflight_canary,
    _prepared_fresh_event_status,
    _retry_exclusion_append_smoke,
)


def test_issue_790_forecast_blocker_smokes_all_pass() -> None:
    root = Path(__file__).resolve().parents[2]
    rows = _blocker_smokes(root)
    failed = [(name, detail) for name, ok, detail in rows if not ok]
    assert not failed, failed
    assert len(rows) >= 26
    names = {name for name, _, _ in rows}
    assert "B10 TEMPORAL: REFERENCE_TIME stuffing ignored; projected null/cues OK" in names
    assert "B14 dry-replay Step 14 stuffing ignored → projected null success" in names
    assert "B21 Step 19 execute→ingest→bind accepts COMPLETE+0" in names
    assert (
        "B22 Steps 20-22 COMPLETE+0 avoid AMBIGUOUS_EFFECT"
        in names
    )
    assert "B23 failure/blocked/proposal-bearing ambiguity remains fail-closed" in names


def test_o07_accepts_only_exact_tip_focus_gates() -> None:
    tip = "a" * 40
    common = {
        "status": "completed",
        "conclusion": "success",
        "head_sha": tip,
    }
    assert _focus_gate_hits(
        [
            {**common, "name": "full-deterministic-health"},
            {**common, "name": "test"},
        ],
        tip=tip,
    ) == []
    assert _focus_gate_hits(
        [
            {**common, "name": "focus-gates", "head_sha": "b" * 40},
            {**common, "name": "focus-gates"},
        ],
        tip=tip,
    ) == [{**common, "name": "focus-gates"}]


def test_ops_gates_prepares_once_without_parallel_candidate_qualification() -> None:
    source = inspect.getsource(_ops_gates)
    helper = inspect.getsource(_prepare_preflight_canary)
    assert source.count("_prepare_preflight_canary(") == 1
    assert "activated_plan=activated_plan" in source
    assert helper.count("prepare_issue_790_canary(") == 1
    assert "plan=activated_plan" in helper
    assert "unused_queued_attempt_zero_candidates" not in source
    assert "qualify_fresh_graphiti_event" not in source
    assert "prepared_canary_record(prepared)" in helper
    assert "prepared_canary_from_record" in helper


def test_o18_uses_the_prepared_candidate_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.issue_790_live_canary_preflight as preflight
    from newsroom.control_plane.issue_790_prepared_canary import PreparedCanary

    event_id = "sha256:" + "11" * 32
    manifest_digest = "sha256:" + "22" * 32
    store = tmp_path / "unpublished.sqlite3"
    sqlite3.connect(store).close()
    prepared = PreparedCanary(
        exact_head="a" * 40,
        candidate_identity={
            "event_id": event_id,
            "event_manifest_digest": manifest_digest,
            "ledger_seq": 14000,
        },
        safety_state={
            "candidate_attempt_count": 0,
            "candidate_claim_present": False,
            "candidate_provider_dispatched": False,
            "candidate_state": "QUEUED",
            "consumption_present": False,
            "outcome_present": False,
            "receipt_present": False,
            "retry_claim_present": False,
        },
        plan_identity={},
        retry_exclusion_identity={"retry_forbidden_event_ids": []},
        runtime_identity={},
        non_effects=(),
        decision_digest="sha256:" + "33" * 32,
        qualification_evidence={
            "event_id": event_id,
            "event_manifest_digest": manifest_digest,
            "event_state": "QUEUED",
            "event_attempt_count": 0,
            "ledger_seq": 14000,
            "owner_emergency_stop_clear": True,
            "provider_calls": 0,
            "resolved_units": [{"ingest_id": "ingest-1"}],
            "store_mutations": 0,
        },
    )
    seen: list[tuple[str, list[str]]] = []

    def no_prior(
        _connection: sqlite3.Connection,
        *,
        event_id: str,
        ingest_ids: list[str],
    ) -> bool:
        seen.append((event_id, ingest_ids))
        return False

    monkeypatch.setattr(preflight, "_has_prior_execution", no_prior)
    event, detail = _prepared_fresh_event_status(prepared, store=store)
    assert event == (event_id, 14000)
    assert detail.endswith("QUEUED attempt=0 provider_dispatched=false")
    assert seen == [(event_id, ["ingest-1"])]

    monkeypatch.setattr(preflight, "_has_prior_execution", lambda *_a, **_k: True)
    assert _prepared_fresh_event_status(prepared, store=store) == (
        None,
        "PreparedCanary candidate has prior execution evidence",
    )


def test_owner_activation_digest_gate_requires_exact_lowercase_sha256() -> None:
    valid = "sha256:" + "ab" * 32
    assert _invalid_sha256_paths(
        {
            "activation_digest": valid,
            "approval_payload": {"checked_candidate_digest": valid},
        }
    ) == []
    invalid = _invalid_sha256_paths(
        {
            "activation_digest": "sha256:" + "ab" * 31,
            "approval_payload": {"checked_candidate_digest": "sha256:" + "A" * 64},
        }
    )
    assert invalid == [
        "$.activation_digest",
        "$.approval_payload.checked_candidate_digest",
    ]


def test_pinned_runtime_gate_uses_real_adapter_import_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsroom.graphiti_adapter import real
    import scripts.issue_790_live_canary_preflight as preflight

    monkeypatch.setattr(
        real,
        "_load_graphiti",
        lambda: SimpleNamespace(Graphiti=object()),
    )
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda _name: "0.29.3",
    )
    ok, detail = _graphiti_runtime_status()
    assert ok is True
    assert "graphiti-core 0.29.3" in detail

    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda _name: "0.29.2",
    )
    assert _graphiti_runtime_status()[0] is False


def test_latest_live_failure_requires_later_red_and_exact_main_green() -> None:
    tip = "a" * 40
    failure = {
        "created_at": "2026-08-30T21:32:36Z",
        "body": "## Step 21 live canary — **FAIL**\n- event: ledger `13361`",
    }
    diagnosis = {
        "created_at": "2026-08-30T21:38:43Z",
        "body": (
            "## Diagnosis\nFull-path red for ledger 13361\n"
            "Red commit: `" + "b" * 40 + "`\n"
            f"`uv run --frozen pytest -q {STEP21_FULL_PATH_TEST}`"
        ),
    }
    green = {
        "created_at": "2026-08-30T21:47:39Z",
        "body": (
            f"## Full-path repair\nexact-main {tip}; ledger 13361; "
            "Focus Gates succeeded"
        ),
    }
    assert _latest_failure_red_green([failure, diagnosis], tip=tip)[0] is False
    assert _latest_failure_red_green([failure, diagnosis, green], tip=tip) == (
        True,
        f"ledger 13361 red→green on {tip[:12]}",
    )
    later_failure = {
        "created_at": "2026-08-30T22:00:00Z",
        "body": "## Step 22 live canary — FAILED\nledger 14000",
    }
    assert _latest_failure_red_green(
        [failure, diagnosis, green, later_failure],
        tip=tip,
    )[0] is False


def _live_fail_comment(ledger: int, *, created_at: str) -> dict[str, str]:
    return {
        "created_at": created_at,
        "body": f"## Step 22 live canary — **FAIL**\n- event: ledger `{ledger}`",
    }


def _full_path_red_comment(
    ledger: int, test_node: str, *, created_at: str
) -> dict[str, str]:
    return {
        "created_at": created_at,
        "body": (
            f"## Diagnosis\nFull-path red for ledger {ledger}\n"
            f"Red commit: `{'b' * 40}`\n"
            f"`uv run --frozen pytest -q {test_node}`"
        ),
    }


def _full_path_green_comment(
    ledger: int, tip: str, *, created_at: str
) -> dict[str, str]:
    return {
        "created_at": created_at,
        "body": (
            f"## Full-path repair\nexact-main {tip}; ledger {ledger}; "
            "Focus Gates succeeded"
        ),
    }


def test_covering_full_path_nodes_are_the_allowlist() -> None:
    assert LATEST_FAILURE_COVERING_FULL_PATH_TESTS == frozenset(
        {
            STEP21_FULL_PATH_TEST,
            STEP22_PERSISTABLE_EMPTY_FULL_PATH_TEST,
            STEP22_CANDIDATE_IDENTITY_FULL_PATH_TEST,
            STEP22_PRODUCTION_UNTOUCHED_FULL_PATH_TEST,
            STEP22_BROKERERROR_SETUP_FULL_PATH_TEST,
            STEP22_CONSUMED_13677_ZERO_FULL_PATH_TEST,
            STEP22_CONSUMED_13683_ZERO_FULL_PATH_TEST,
            STEP22_ABORTED_SPAWN_13689_BACKUP_DEST_FULL_PATH_TEST,
            STEP22_UNMATCHED_13689_CONSUMPTION_BLOCKS_13690_READY_FULL_PATH_TEST,
            STEP22_PREPARED_CANARY_HANDOFF_FULL_PATH_TEST,
            STEP22_PREPARED_CANARY_DECISION_DIGEST_PARITY_FULL_PATH_TEST,
        }
    )


@pytest.mark.parametrize(
    ("ledger", "test_node"),
    (
        (13361, STEP21_FULL_PATH_TEST),
        (13665, STEP22_PERSISTABLE_EMPTY_FULL_PATH_TEST),
        (13665, STEP21_FULL_PATH_TEST),
        (13671, STEP22_CANDIDATE_IDENTITY_FULL_PATH_TEST),
        (13671, STEP22_PRODUCTION_UNTOUCHED_FULL_PATH_TEST),
        (13671, STEP22_BROKERERROR_SETUP_FULL_PATH_TEST),
        (13677, STEP22_CONSUMED_13677_ZERO_FULL_PATH_TEST),
        (13683, STEP22_CONSUMED_13683_ZERO_FULL_PATH_TEST),
        (13689, STEP22_ABORTED_SPAWN_13689_BACKUP_DEST_FULL_PATH_TEST),
        (13690, STEP22_UNMATCHED_13689_CONSUMPTION_BLOCKS_13690_READY_FULL_PATH_TEST),
        (13690, STEP22_PREPARED_CANARY_HANDOFF_FULL_PATH_TEST),
        (13690, STEP22_PREPARED_CANARY_DECISION_DIGEST_PARITY_FULL_PATH_TEST),
    ),
)
def test_latest_live_failure_accepts_step21_or_step22_covering_red(
    ledger: int, test_node: str
) -> None:
    tip = "c" * 40
    comments = [
        _live_fail_comment(ledger, created_at="2026-08-31T15:21:47Z"),
        _full_path_red_comment(
            ledger, test_node, created_at="2026-08-31T15:40:00Z"
        ),
        _full_path_green_comment(
            ledger, tip, created_at="2026-08-31T16:00:00Z"
        ),
    ]
    assert _latest_failure_red_green(comments, tip=tip) == (
        True,
        f"ledger {ledger} red→green on {tip[:12]}",
    )


def test_latest_live_failure_skips_superseded_unallowlisted_diagnosis() -> None:
    tip = "e" * 40
    old_containment = (
        "newsroom/tests/test_issue_790_prepared_canary.py::"
        "test_step22_fresh_missing_prepared_fails_before_any_effect"
    )
    comments = [
        _live_fail_comment(13690, created_at="2026-08-31T23:21:54Z"),
        _full_path_red_comment(
            13690,
            old_containment,
            created_at="2026-08-31T23:30:00Z",
        ),
        _full_path_red_comment(
            13690,
            STEP22_PREPARED_CANARY_HANDOFF_FULL_PATH_TEST,
            created_at="2026-08-31T23:40:00Z",
        ),
        _full_path_green_comment(
            13690,
            tip,
            created_at="2026-08-31T23:50:00Z",
        ),
    ]
    assert _latest_failure_red_green(comments, tip=tip) == (
        True,
        f"ledger 13690 red→green on {tip[:12]}",
    )


def test_latest_live_failure_rejects_newer_unallowlisted_diagnosis() -> None:
    tip = "f" * 40
    unknown = (
        "newsroom/tests/test_issue_790_prepared_canary.py::"
        "test_future_unreviewed_diagnosis"
    )
    comments = [
        _live_fail_comment(13690, created_at="2026-08-31T23:21:54Z"),
        _full_path_red_comment(
            13690,
            STEP22_PREPARED_CANARY_HANDOFF_FULL_PATH_TEST,
            created_at="2026-08-31T23:40:00Z",
        ),
        _full_path_green_comment(
            13690,
            tip,
            created_at="2026-08-31T23:50:00Z",
        ),
        _full_path_red_comment(
            13690,
            unknown,
            created_at="2026-09-01T00:00:00Z",
        ),
    ]
    assert _latest_failure_red_green(comments, tip=tip) == (
        False,
        f"unexpected latest red test {unknown}",
    )


def test_latest_live_failure_rejects_non_covering_full_path_red() -> None:
    tip = "d" * 40
    other = (
        "newsroom/tests/test_graphiti_corpus_ingest.py::"
        "test_step20_rolled_back_zero_proposal_completion_survives_full_cycle"
    )
    comments = [
        _live_fail_comment(13665, created_at="2026-08-31T15:21:47Z"),
        _full_path_red_comment(
            13665, other, created_at="2026-08-31T15:40:00Z"
        ),
        _full_path_green_comment(
            13665, tip, created_at="2026-08-31T16:00:00Z"
        ),
    ]
    ok, detail = _latest_failure_red_green(comments, tip=tip)
    assert ok is False
    assert detail == f"unexpected latest red test {other}"


def test_inspection_sql_uses_ingest_identity_without_receipt_event_column() -> None:
    assert _inspection_sql_smoke() == (
        True,
        "receipt schema has ingest_id and no event_id",
    )


def test_retry_exclusion_apply_appends_all_exhausted_events_idempotently() -> None:
    ok, detail = _retry_exclusion_append_smoke()
    assert ok is True
    assert "13361" in detail
    assert "replay=stable" in detail


def _o16_exclusion_args(
    *,
    plan_includes_consumed: bool,
    retry_authorised: bool = False,
) -> dict[str, object]:
    event_id = "sha256:" + "61" * 32
    base_seqs = (1932, 1972, 8834, 8835, 13284, 13337, 13362)
    sealed_at = "2026-08-30T20:58:43.662872Z"
    live_at = "2026-08-30T21:29:18.946358Z"
    plan_events = [
        {
            "attempt_count": 1,
            "available_at": sealed_at,
            "event_id": "sha256:" + f"{seq:064x}",
            "last_failure_code": "HELD",
            "ledger_seq": seq,
            "provider_dispatched": False,
            "state": "RETRY_HELD",
        }
        for seq in base_seqs
    ]
    if plan_includes_consumed:
        plan_events.append({"event_id": event_id, "ledger_seq": 13361})
    exclusions = [
        {
            "event_id": item["event_id"],
            "ledger_seq": item["ledger_seq"],
            "reason": "ISSUE_790_RETRY_FORBIDDEN",
            "event_snapshot": {**item, "available_at": live_at},
        }
        for item in plan_events
        if int(item["ledger_seq"]) != 13361
    ]
    consumption = {
        "approved_plan_digest": "sha256:" + "aa" * 32,
        "consumption_digest": "sha256:" + "bb" * 32,
        "event_id": event_id,
        "ledger_seq": 13361,
        "attempt_count_before": 0,
        "maximum_event_attempts": 1,
    }
    outcome = {
        "approved_plan_digest": consumption["approved_plan_digest"],
        "consumption_digest": consumption["consumption_digest"],
        "event_id": event_id,
        "ledger_seq": 13361,
        "attempt_count": 1,
        "provider_dispatched": True,
        "retry_authorised": retry_authorised,
        "state_after_seal": "CONFIGURATION_HELD",
        "failure_code_after_seal": "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:AMBIGUOUS_EFFECT",
    }
    event_snapshot = {
        "event_id": event_id,
        "ledger_seq": 13361,
        "state": "CONFIGURATION_HELD",
        "attempt_count": 1,
        "provider_dispatched": True,
        "last_failure_code": outcome["failure_code_after_seal"],
        "available_at": live_at,
    }
    return {
        "plan_events": plan_events,
        "exclusions": exclusions,
        "consumption": consumption,
        "outcome": outcome,
        "event_snapshot": event_snapshot,
        "activated_plan_digest": str(consumption["approved_plan_digest"]),
        "effectively_excluded_event_ids": {event_id},
    }


def test_o16_uses_exhausted_consumption_without_rewriting_step21_plan() -> None:
    args = _o16_exclusion_args(plan_includes_consumed=False)
    ok, detail = _effective_retry_exclusion_status(**args)
    assert ok is True
    assert "consumed=13361" in detail
    args["outcome"]["retry_authorised"] = True
    assert _effective_retry_exclusion_status(**args)[0] is False


def test_o16_successor_plan_may_list_13361_before_durable_apply() -> None:
    args = _o16_exclusion_args(plan_includes_consumed=True)
    ok, detail = _effective_retry_exclusion_status(**args)
    assert ok is True
    assert "consumed=13361" in detail
    assert "13361" in detail.split("durable=")[0]
    assert "13361" not in detail.split("durable=")[1].split("consumed=")[0]
    args["outcome"]["retry_authorised"] = True
    retry, retry_detail = _effective_retry_exclusion_status(**args)
    assert retry is False
    assert "consumed=INVALID" in retry_detail
    args["outcome"]["retry_authorised"] = False
    args["plan_events"] = [
        *args["plan_events"],
        {"event_id": "sha256:" + "99" * 32, "ledger_seq": 9999},
    ]
    assert _effective_retry_exclusion_status(**args)[0] is False


def test_o16_fail_closed_before_dispatch_durable_complete_successor_passes() -> None:
    args = _o16_exclusion_args(plan_includes_consumed=True)
    live_at = args["exclusions"][0]["event_snapshot"]["available_at"]
    sealed_at = args["plan_events"][0]["available_at"]
    consumed = next(
        item for item in args["plan_events"] if int(item["ledger_seq"]) == 13361
    )
    consumed.update(
        {
            "attempt_count": 1,
            "available_at": sealed_at,
            "last_failure_code": args["outcome"]["failure_code_after_seal"],
            "provider_dispatched": True,
            "state": "CONFIGURATION_HELD",
        }
    )
    args["exclusions"].append(
        {
            "event_id": consumed["event_id"],
            "ledger_seq": 13361,
            "reason": "ISSUE_790_RETRY_FORBIDDEN",
            "event_snapshot": {**consumed, "available_at": live_at},
        }
    )
    plan_seqs = {int(item["ledger_seq"]) for item in args["plan_events"]}
    durable_seqs = {int(item["ledger_seq"]) for item in args["exclusions"]}
    assert REQUIRED_RETRY_LEDGER_SEQS <= plan_seqs
    assert REQUIRED_RETRY_LEDGER_SEQS <= durable_seqs
    assert 13361 in plan_seqs
    assert 13361 in durable_seqs

    args["consumption"] = None
    args["outcome"] = None
    none_ok, none_detail = _effective_retry_exclusion_status(**args)
    assert none_ok is True
    assert "consumed=INVALID" in none_detail
    assert "13361" in none_detail.split("durable=")[1].split("consumed=")[0]

    args["consumption"] = {"approved_plan_digest": "sha256:" + "ff" * 32}
    args["outcome"] = {"retry_authorised": True}
    invalid_ok, invalid_detail = _effective_retry_exclusion_status(**args)
    assert invalid_ok is True
    assert "consumed=INVALID" in invalid_detail

    args["exclusions"] = [
        item for item in args["exclusions"] if int(item["ledger_seq"]) != 13361
    ]
    assert _effective_retry_exclusion_status(**args)[0] is False


def test_o16_preflight_rejects_durable_safety_field_mutation() -> None:
    args = _o16_exclusion_args(plan_includes_consumed=True)
    args["exclusions"][0]["event_snapshot"]["state"] = "QUEUED"
    assert _effective_retry_exclusion_status(**args)[0] is False


def test_o16_preflight_rejects_claimed_exhausted_row() -> None:
    args = _o16_exclusion_args(plan_includes_consumed=True)
    args["event_snapshot"]["claim_owner"] = "worker-1"
    assert _effective_retry_exclusion_status(**args)[0] is False


def test_o18_skips_old_backlog_before_proving_qualification() -> None:
    old = ("sha256:" + "11" * 32, 8819, "QUEUED", 0, 0)
    future = ("sha256:" + "22" * 32, 14000, "QUEUED", 0, 0)

    assert _eligible_candidate_rows(
        (old,), forbidden_event_ids=set(), forbidden_seqs=set()
    ) == ()
    assert _eligible_candidate_rows(
        (old, future), forbidden_event_ids=set(), forbidden_seqs=set()
    ) == (future,)
