"""PreparedCanary is the unique pre-dispatch authority after #870."""

from __future__ import annotations

import ast
import inspect
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import issue_790_disposition as disposition
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    ISSUE_790_STEP22_PENDING_PLAN_PATH,
    Issue790DispositionError,
    _require_step16_code_identity,
    _require_step16_runtime_semantics,
    finalise_issue_790_step16_plan,
    issue_790_checked_approval,
    seal_issue_790_step16_plan,
)
from newsroom.control_plane.issue_790_prepared_canary import (
    CANDIDATE_EVENT_ID,
    CANDIDATE_LEDGER_SEQ,
    FAIL_BRANCH_INVENTORY,
    FIELD_CLASSIFICATION,
    LIVE_ONLY_PREDISPATCH_GATES,
    PREPARED_CANARY_ABSENT,
    PREPARED_CANARY_DIGEST_DRIFT,
    PreparedCanaryError,
    consume_prepared_canary,
    prepare_issue_790_canary,
    unused_queued_attempt_zero_candidates,
    _candidate_from_plan,
)
from newsroom.control_plane.issue_790_rehearsal import (
    RehearsalRealGraphitiAdapter,
    live_issue_790_store_paths,
    refuse_live_issue_790_store_paths,
    run_prepared_canary_rehearsal,
    sqlite_backup_copy,
)
from newsroom.tests.test_issue_790_rehearsal_fixtures import (
    EVENT_13361,
    EXACT_HEAD,
    LIVE_13361_AVAILABLE_AT,
    OBSERVED_AT,
    SEALED_13361_AVAILABLE_AT,
    SUCCESSOR_EVENT_ID,
    SUCCESSOR_LEDGER_SEQ,
    build_rehearsal_stores,
    candidate_identity,
    dispatch_started_count,
    event_identity,
    file_digest,
    mutate_retry_field,
    retry_available_at,
)

_TEST_FILE = Path(__file__)
_ROOT = _TEST_FILE.resolve().parents[2]
_STEP22_ACTIVATION_SHA = "f7946e8a53620b56a09bb4ae923a8003b92da760"
_STEP22_ACTIVATION_TREE = "8c443bde47adc34d8e9a38dd6ba80359fd56fa16"
_STEP22_ACTIVATION_FG_RUN = 33387559058
_SUCCESSOR_SHA = "a1f24f4e069af95ac94e8744f8f94c3e28e10d32"
_SUCCESSOR_TREE = "a59e5c620cb9a15a509bced75b96e9a44da940ff"
_SUCCESSOR_FG_RUN = 33404219327
_ACTIVATION_PARENT_SHA = "00f7df954c21816e9be13d783871186efaa84073"
_LIVE_13671_AVAILABLE_AT = "2026-08-31T16:17:39.354162Z"
_LIVE_OBSERVED_AT = datetime(2026, 8, 31, 17, 39, 23, 783082, tzinfo=UTC)


def _prepare(stores, *, store=None, role="preflight", **kwargs):
    return prepare_issue_790_canary(
        store=store or stores.work_unpublished,
        proving_store=stores.proving,
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        exact_head=EXACT_HEAD,
        role=role,
        **kwargs,
    )


def _step22_activated_plan() -> dict[str, object]:
    pending = json.loads((_ROOT / ISSUE_790_STEP22_PENDING_PLAN_PATH).read_text())
    pre_dispatch = json.loads((_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text())
    candidate = seal_issue_790_step16_plan(
        pending,
        issue_790_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=pre_dispatch,
    )
    plan = finalise_issue_790_step16_plan(
        candidate,
        {
            "approved_by": "github:fol2",
            "approval_reference": (
                "https://github.com/fol2/newsroom/issues/790#issuecomment-5477950294"
            ),
            "approved_at": "2026-08-31T11:55:32.000000Z",
            "scope": "CONSERVATIVE_SUBSCRIPTION_CLI_USAGE_DISPOSITION",
            "reviewed_correction_revision": _STEP22_ACTIVATION_SHA,
            "reviewed_correction_tree": _STEP22_ACTIVATION_TREE,
        },
        pre_dispatch=pre_dispatch,
    )
    sequence = dict(plan["sequence"])
    binding = dict(sequence["owner_activation"])
    binding["focus_gate_run_id"] = _STEP22_ACTIVATION_FG_RUN
    binding["focus_gate_run_url"] = (
        f"https://github.com/fol2/newsroom/actions/runs/{_STEP22_ACTIVATION_FG_RUN}"
    )
    sequence["owner_activation"] = binding
    plan["sequence"] = sequence
    return plan


def _closed_circuit() -> dict[str, object]:
    return {
        "state": "CLOSED",
        "opened_at": None,
        "available_at": None,
        "failure_code": None,
    }


def _sqlite_canary_event(store: Path, *, ledger_seq: int) -> dict[str, object]:
    connection = sqlite3.connect(store)
    try:
        row = connection.execute(
            "SELECT event_id,ledger_seq,state,attempt_count,provider_dispatched,"
            "claim_owner,claim_expires_at,terminal_at,available_at "
            "FROM unpublished_graphiti_revision_events WHERE ledger_seq=?",
            (ledger_seq,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return {
        "event_id": row[0],
        "ledger_seq": row[1],
        "state": row[2],
        "attempt_count": row[3],
        "provider_dispatched": row[4],
        "claim_owner": row[5],
        "claim_expires_at": row[6],
        "terminal_at": row[7],
        "available_at": row[8],
    }


def _runtime_semantics_kwargs(
    event: dict[str, object],
    *,
    observed_at: datetime = OBSERVED_AT,
) -> dict[str, object]:
    return {
        "evidence": _successor_evidence(),
        "route_state": {"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
        "circuit_state": _closed_circuit(),
        "observed_at": observed_at,
        "canary_event": event,
    }


def _production_runtime_evidence() -> dict[str, object]:
    return {
        "revision": EXACT_HEAD,
        "store_quick_check": "ok",
        "worker": {
            "label": "com.jamesto.newsroom-graphiti-worker",
            "launchctl_loaded": False,
            "process_ids": [],
        },
    }


def _patch_production_predispatch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: dict[str, object],
) -> None:
    retry = plan["retry_forbidden_events"]
    monkeypatch.setattr(disposition, "_require_approved_plan", lambda *a, **k: plan)
    monkeypatch.setattr(disposition, "_assert_exact_target", lambda *a, **k: None)
    monkeypatch.setattr(
        disposition, "_require_sequence_predecessor", lambda *a, **k: None
    )
    monkeypatch.setattr(disposition, "_require_retry_exclusions", lambda *a, **k: [])
    monkeypatch.setattr(
        disposition, "_retain_retry_exclusions_for_plan", lambda *a, **k: []
    )
    monkeypatch.setattr(
        disposition, "_require_retry_events_unchanged", lambda *a, **k: retry
    )
    monkeypatch.setattr(disposition, "_retry_event_snapshots", lambda *a, **k: retry)
    monkeypatch.setattr(
        disposition,
        "collect_issue_790_operational_evidence",
        lambda **k: _production_runtime_evidence(),
    )
    monkeypatch.setattr(
        disposition,
        "_validate_operational_evidence",
        lambda evidence, **k: evidence,
    )
    monkeypatch.setattr(
        disposition,
        "_worker_state",
        lambda: _production_runtime_evidence()["worker"],
    )
    monkeypatch.setattr(
        disposition, "_require_issue_790_canary_route", lambda **k: None
    )
    monkeypatch.setattr(
        disposition.ModelUsageService,
        "route_state",
        lambda self, route: {
            "state": "CLOSED",
            "reason": "AUTHORISED_OPERATOR_RESET",
        },
    )
    unsigned = {
        "schema_version": "newsroom.issue-790.graphiti-runtime-readiness.v1",
        "framework": "graphiti-core",
        "framework_version": "0.29.3",
        "provider_calls": 0,
        "credential_resolution": False,
    }
    monkeypatch.setattr(
        disposition,
        "_qualify_real_graphiti_runtime",
        lambda: {**unsigned, "runtime_digest": digest_canonical(unsigned)},
    )


def _successor_evidence() -> dict[str, object]:
    return {
        "revision": _SUCCESSOR_SHA,
        "tree": _SUCCESSOR_TREE,
        "github_main_revision": _SUCCESSOR_SHA,
        "repository_root": str(_ROOT),
        "store_quick_check": "ok",
        "worker": {
            "label": "com.jamesto.newsroom-graphiti-worker",
            "launchctl_loaded": False,
            "process_ids": [],
        },
        "ci_test": {
            "name": "focus-gates",
            "status": "completed",
            "conclusion": "success",
            "head_sha": _SUCCESSOR_SHA,
            "url": (
                "https://github.com/fol2/newsroom/actions/runs/"
                f"{_SUCCESSOR_FG_RUN}"
            ),
        },
    }


def test_field_classification_keeps_available_at_as_audit_only() -> None:
    assert FIELD_CLASSIFICATION["available_at"] == "C"
    assert FIELD_CLASSIFICATION["exact_head"] == "A"
    assert FIELD_CLASSIFICATION["retry_safety_states"] == "B"
    assert FIELD_CLASSIFICATION["provider_response"] == "D"


def test_prepared_canary_accepts_13361_available_at_drift(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    assert retry_available_at(stores.work_unpublished, 13361) == LIVE_13361_AVAILABLE_AT
    sealed = next(
        item
        for item in stores.plan["retry_forbidden_events"]
        if item["ledger_seq"] == 13361
    )
    assert sealed["available_at"] == SEALED_13361_AVAILABLE_AT
    prepared = _prepare(stores)
    assert prepared.candidate_identity["event_id"] == CANDIDATE_EVENT_ID
    assert prepared.candidate_identity["ledger_seq"] == CANDIDATE_LEDGER_SEQ
    assert prepared.decision_digest.startswith("sha256:")
    assert candidate_identity(stores.sealed_unpublished)[0] == CANDIDATE_EVENT_ID


def test_ready_digest_is_stable_for_unchanged_copy(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    first = _prepare(stores)
    second = _prepare(stores, role="canary")
    assert first.decision_digest == second.decision_digest
    assert first.as_decision_payload() == second.as_decision_payload()
    assert file_digest(stores.sealed_unpublished) == stores.sealed_digest
    assert file_digest(stores.work_unpublished) == stores.sealed_digest


def test_ready_implies_dispatch_started(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    before = file_digest(stores.work_unpublished)
    prepared = _prepare(stores)
    assert file_digest(stores.work_unpublished) == before
    result = run_prepared_canary_rehearsal(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        exact_head=EXACT_HEAD,
        prepared=prepared,
    )
    assert result["decision_digest"] == prepared.decision_digest
    assert result["dispatch_started"] is True
    assert result["provider_calls"] == 0
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert dispatch_started_count(stores.work_unpublished) >= 1
    assert file_digest(stores.sealed_unpublished) == stores.sealed_digest
    assert candidate_identity(stores.sealed_unpublished)[0] == CANDIDATE_EVENT_ID


def test_ready_implies_dispatch_started_for_successor_unused_attempt_zero(
    tmp_path: Path,
) -> None:
    stores = build_rehearsal_stores(tmp_path, successor=True)
    before = file_digest(stores.work_unpublished)
    prepared = _prepare(stores)
    assert prepared.candidate_identity["event_id"] == SUCCESSOR_EVENT_ID
    assert prepared.candidate_identity["ledger_seq"] == SUCCESSOR_LEDGER_SEQ
    assert file_digest(stores.work_unpublished) == before
    result = run_prepared_canary_rehearsal(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        exact_head=EXACT_HEAD,
        prepared=prepared,
        event_id=SUCCESSOR_EVENT_ID,
        ledger_seq=SUCCESSOR_LEDGER_SEQ,
    )
    assert result["decision_digest"] == prepared.decision_digest
    assert result["dispatch_started"] is True
    assert result["provider_calls"] == 0
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert dispatch_started_count(stores.work_unpublished) >= 1
    assert file_digest(stores.sealed_unpublished) == stores.sealed_digest
    assert candidate_identity(stores.sealed_unpublished) == (
        CANDIDATE_EVENT_ID,
        CANDIDATE_LEDGER_SEQ,
        "CONFIGURATION_HELD",
    )
    assert event_identity(stores.sealed_unpublished, SUCCESSOR_LEDGER_SEQ)[0] == (
        SUCCESSOR_EVENT_ID
    )


def test_ready_successor_exact_head_implies_dispatch_started(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan = _step22_activated_plan()
    sequence = plan["sequence"]
    assert sequence["reviewed_correction_revision"] == _STEP22_ACTIVATION_SHA
    assert sequence["owner_activation"]["focus_gate_run_id"] == _STEP22_ACTIVATION_FG_RUN
    _require_step16_code_identity(plan, evidence=_successor_evidence())
    before = file_digest(stores.work_unpublished)
    prepared = prepare_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        plan=plan,
        observed_at=OBSERVED_AT,
        exact_head=_SUCCESSOR_SHA,
        role="preflight",
    )
    assert file_digest(stores.work_unpublished) == before
    result = disposition.run_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        backup_path=tmp_path / "unused-backup.sqlite3",
        plan=plan,
        observed_at=OBSERVED_AT,
        repository_root=_ROOT,
        event_id=CANDIDATE_EVENT_ID,
        ledger_seq=CANDIDATE_LEDGER_SEQ,
        disposition_digest="sha256:" + "cd" * 32,
        prepared=prepared,
        rehearsal=True,
        exact_head=_SUCCESSOR_SHA,
    )
    assert result["decision_digest"] == prepared.decision_digest
    assert result["dispatch_started"] is True
    assert result["provider_calls"] == 0
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert dispatch_started_count(stores.work_unpublished) >= 1
    assert file_digest(stores.sealed_unpublished) == stores.sealed_digest
    assert candidate_identity(stores.sealed_unpublished) == (
        CANDIDATE_EVENT_ID,
        CANDIDATE_LEDGER_SEQ,
        "QUEUED",
    )


def test_step22_activation_rejects_non_ancestor_exact_head() -> None:
    plan = _step22_activated_plan()
    evidence = _successor_evidence()
    evidence["revision"] = _ACTIVATION_PARENT_SHA
    evidence["github_main_revision"] = _ACTIVATION_PARENT_SHA
    evidence["ci_test"] = dict(evidence["ci_test"])
    evidence["ci_test"]["head_sha"] = _ACTIVATION_PARENT_SHA
    with pytest.raises(
        Issue790DispositionError, match="reviewed correction identity"
    ):
        _require_step16_code_identity(plan, evidence=evidence)


def test_step22_activation_rejects_focus_gates_not_on_current_exact_head() -> None:
    plan = _step22_activated_plan()
    evidence = _successor_evidence()
    evidence["ci_test"] = {
        "name": "focus-gates",
        "status": "completed",
        "conclusion": "success",
        "head_sha": _STEP22_ACTIVATION_SHA,
        "url": (
            "https://github.com/fol2/newsroom/actions/runs/"
            f"{_STEP22_ACTIVATION_FG_RUN}"
        ),
    }
    with pytest.raises(Issue790DispositionError, match="focus gate evidence differs"):
        _require_step16_code_identity(plan, evidence=evidence)


def test_successor_safety_drift_fail_closes_before_dispatch(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan = _step22_activated_plan()
    mutate_retry_field(
        stores.work_unpublished, ledger_seq=13361, field="state", value="QUEUED"
    )
    RehearsalRealGraphitiAdapter.provider_calls = 0
    RehearsalRealGraphitiAdapter.dispatch_started = False
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=plan,
            observed_at=OBSERVED_AT,
            exact_head=_SUCCESSOR_SHA,
            role="preflight",
        )
    assert caught.value.failure_code == "RETRY_FORBIDDEN_SAFETY_STATE"
    assert RehearsalRealGraphitiAdapter.dispatch_started is False
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert dispatch_started_count(stores.work_unpublished) == 0
    assert candidate_identity(stores.sealed_unpublished)[0] == CANDIDATE_EVENT_ID
    assert candidate_identity(stores.work_unpublished)[0] == CANDIDATE_EVENT_ID


def test_successor_digest_drift_fail_closes_before_dispatch(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan = _step22_activated_plan()
    prepared = prepare_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        plan=plan,
        observed_at=OBSERVED_AT,
        exact_head=_SUCCESSOR_SHA,
        role="preflight",
    )
    drifted = replace(prepared, decision_digest="sha256:" + "00" * 32)
    RehearsalRealGraphitiAdapter.provider_calls = 0
    RehearsalRealGraphitiAdapter.dispatch_started = False
    with pytest.raises(PreparedCanaryError) as caught:
        disposition.run_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            backup_path=tmp_path / "unused-backup.sqlite3",
            plan=plan,
            observed_at=OBSERVED_AT,
            repository_root=_ROOT,
            event_id=CANDIDATE_EVENT_ID,
            ledger_seq=CANDIDATE_LEDGER_SEQ,
            disposition_digest="sha256:" + "cd" * 32,
            prepared=drifted,
            rehearsal=True,
            exact_head=_SUCCESSOR_SHA,
        )
    assert caught.value.failure_code == PREPARED_CANARY_DIGEST_DRIFT
    assert RehearsalRealGraphitiAdapter.dispatch_started is False
    assert dispatch_started_count(stores.work_unpublished) == 0
    assert candidate_identity(stores.work_unpublished)[0] == CANDIDATE_EVENT_ID


def test_event_13665_identity_is_not_mutated(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    _prepare(stores)
    mutate_retry_field(
        stores.work_unpublished, ledger_seq=13361, field="state", value="QUEUED"
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _prepare(stores)
    assert caught.value.failure_code == "RETRY_FORBIDDEN_SAFETY_STATE"
    event_id, ledger_seq, _state = candidate_identity(stores.work_unpublished)
    assert event_id == CANDIDATE_EVENT_ID
    assert ledger_seq == CANDIDATE_LEDGER_SEQ
    assert candidate_identity(stores.sealed_unpublished)[0] == CANDIDATE_EVENT_ID


def test_spent_13665_is_retry_forbidden_target(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path, successor=True)
    RehearsalRealGraphitiAdapter.provider_calls = 0
    RehearsalRealGraphitiAdapter.dispatch_started = False
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            event_id=CANDIDATE_EVENT_ID,
            ledger_seq=CANDIDATE_LEDGER_SEQ,
            role="canary",
        )
    assert caught.value.failure_code == "RETRY_FORBIDDEN_TARGET"
    assert RehearsalRealGraphitiAdapter.dispatch_started is False
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert dispatch_started_count(stores.work_unpublished) == 0
    assert candidate_identity(stores.work_unpublished) == (
        CANDIDATE_EVENT_ID,
        CANDIDATE_LEDGER_SEQ,
        "CONFIGURATION_HELD",
    )
    assert candidate_identity(stores.sealed_unpublished) == (
        CANDIDATE_EVENT_ID,
        CANDIDATE_LEDGER_SEQ,
        "CONFIGURATION_HELD",
    )


def test_cli_flags_disagree_with_unused_candidate_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            event_id=SUCCESSOR_EVENT_ID,
            ledger_seq=SUCCESSOR_LEDGER_SEQ,
            role="canary",
        )
    assert caught.value.failure_code == "CANDIDATE_IDENTITY"
    assert candidate_identity(stores.work_unpublished)[2] == "QUEUED"


def test_step22_spent_13665_successor_unused_attempt_zero_survives_full_path(
    tmp_path: Path,
) -> None:
    """Live 13671 CANDIDATE_IDENTITY: READY unused and CLI agree after spent 13665."""

    stores = build_rehearsal_stores(tmp_path, successor=True)
    named = unused_queued_attempt_zero_candidates(stores.work_unpublished, stores.plan)
    assert named[0] == (SUCCESSOR_EVENT_ID, SUCCESSOR_LEDGER_SEQ)
    prepared = _prepare(stores)
    assert prepared.candidate_identity["event_id"] == SUCCESSOR_EVENT_ID
    assert prepared.candidate_identity["ledger_seq"] == SUCCESSOR_LEDGER_SEQ
    with_flags = prepare_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        exact_head=EXACT_HEAD,
        event_id=SUCCESSOR_EVENT_ID,
        ledger_seq=SUCCESSOR_LEDGER_SEQ,
        role="canary",
    )
    assert with_flags.decision_digest == prepared.decision_digest
    bound = _candidate_from_plan(
        stores.plan,
        event_id=SUCCESSOR_EVENT_ID,
        ledger_seq=SUCCESSOR_LEDGER_SEQ,
        role="canary",
        store=stores.work_unpublished,
    )
    assert bound == (SUCCESSOR_EVENT_ID, SUCCESSOR_LEDGER_SEQ)
    RehearsalRealGraphitiAdapter.provider_calls = 0
    RehearsalRealGraphitiAdapter.dispatch_started = False
    result = disposition.run_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        backup_path=tmp_path / "unused-backup.sqlite3",
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        repository_root=tmp_path,
        event_id=SUCCESSOR_EVENT_ID,
        ledger_seq=SUCCESSOR_LEDGER_SEQ,
        disposition_digest="sha256:" + "cd" * 32,
        prepared=prepared,
        rehearsal=True,
        exact_head=EXACT_HEAD,
    )
    assert result["decision_digest"] == prepared.decision_digest
    assert result["dispatch_started"] is True
    assert result["provider_calls"] == 0
    assert dispatch_started_count(stores.work_unpublished) >= 1
    assert candidate_identity(stores.sealed_unpublished) == (
        CANDIDATE_EVENT_ID,
        CANDIDATE_LEDGER_SEQ,
        "CONFIGURATION_HELD",
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _candidate_from_plan(
            stores.plan,
            event_id=CANDIDATE_EVENT_ID,
            ledger_seq=CANDIDATE_LEDGER_SEQ,
            role="canary",
            store=stores.work_unpublished,
        )
    assert caught.value.failure_code == "RETRY_FORBIDDEN_TARGET"


def test_step22_sqlite_integer_zero_provider_dispatched_is_untouched(
    tmp_path: Path,
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan = _step22_activated_plan()
    assert plan["sequence"]["candidate_event_qualification"]["ledger_seq"] == (
        CANDIDATE_LEDGER_SEQ
    )
    event = _sqlite_canary_event(
        stores.work_unpublished, ledger_seq=CANDIDATE_LEDGER_SEQ
    )
    assert event["state"] == "QUEUED"
    assert event["attempt_count"] == 0
    assert type(event["attempt_count"]) is int
    assert event["provider_dispatched"] == 0
    assert type(event["provider_dispatched"]) is int
    _require_step16_runtime_semantics(
        plan, **_runtime_semantics_kwargs(event)
    )
    event["provider_dispatched"] = 1
    with pytest.raises(Issue790DispositionError, match="not untouched"):
        _require_step16_runtime_semantics(
            plan, **_runtime_semantics_kwargs(event)
        )


def test_step22_sqlite_successor_attempt_zero_is_pre_dispatch_untouched(
    tmp_path: Path,
) -> None:
    stores = build_rehearsal_stores(tmp_path, successor=True)
    plan = _step22_activated_plan()
    qualification = plan["sequence"]["candidate_event_qualification"]
    assert qualification["ledger_seq"] == CANDIDATE_LEDGER_SEQ
    assert qualification["event_id"] == CANDIDATE_EVENT_ID
    connection = sqlite3.connect(stores.work_unpublished)
    try:
        connection.execute(
            "UPDATE unpublished_graphiti_revision_events SET available_at=? "
            "WHERE ledger_seq=?",
            (_LIVE_13671_AVAILABLE_AT, SUCCESSOR_LEDGER_SEQ),
        )
        connection.commit()
    finally:
        connection.close()
    event = _sqlite_canary_event(
        stores.work_unpublished, ledger_seq=SUCCESSOR_LEDGER_SEQ
    )
    assert event["event_id"] == SUCCESSOR_EVENT_ID
    assert event["ledger_seq"] == SUCCESSOR_LEDGER_SEQ
    assert event["state"] == "QUEUED"
    assert event["attempt_count"] == 0
    assert event["provider_dispatched"] == 0
    assert type(event["provider_dispatched"]) is int
    assert event["available_at"] == _LIVE_13671_AVAILABLE_AT
    assert event["claim_owner"] is None
    _require_step16_runtime_semantics(
        plan,
        **_runtime_semantics_kwargs(event, observed_at=_LIVE_OBSERVED_AT),
    )
    spent = _sqlite_canary_event(
        stores.work_unpublished, ledger_seq=CANDIDATE_LEDGER_SEQ
    )
    assert spent["state"] == "CONFIGURATION_HELD"
    assert spent["provider_dispatched"] == 1
    with pytest.raises(Issue790DispositionError, match="not untouched"):
        _require_step16_runtime_semantics(
            plan,
            **_runtime_semantics_kwargs(spent, observed_at=_LIVE_OBSERVED_AT),
        )


def test_step22_unused_13671_survives_production_pre_dispatch_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails on 6c101627 with 'pre-dispatch event is not untouched'."""

    stores = build_rehearsal_stores(tmp_path, successor=True)
    plan = _step22_activated_plan()
    assert plan["sequence"]["candidate_event_qualification"]["ledger_seq"] == (
        CANDIDATE_LEDGER_SEQ
    )
    event = _sqlite_canary_event(
        stores.work_unpublished, ledger_seq=SUCCESSOR_LEDGER_SEQ
    )
    assert event["provider_dispatched"] == 0
    assert type(event["provider_dispatched"]) is int
    assert event["attempt_count"] == 0
    _patch_production_predispatch(monkeypatch, plan=plan)
    consume_calls: list[str] = []

    def consume_successor(**values: object) -> None:
        consume_calls.append(str(values["event_id"]))
        assert values["event_id"] == SUCCESSOR_EVENT_ID
        return None

    monkeypatch.setattr(disposition, "_consume_issue_790_event", consume_successor)
    backup = tmp_path / "pre-dispatch-13671.sqlite3"
    receipt = disposition.run_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        backup_path=backup,
        plan=plan,
        observed_at=OBSERVED_AT,
        repository_root=tmp_path,
        event_id=SUCCESSOR_EVENT_ID,
        ledger_seq=SUCCESSOR_LEDGER_SEQ,
        disposition_digest="sha256:" + "cd" * 32,
        rehearsal=False,
        exact_head=EXACT_HEAD,
    )
    assert backup.is_file()
    assert consume_calls == [SUCCESSOR_EVENT_ID]
    assert receipt["resumed_zero_io_finalisation"] is False
    assert receipt["consumption"]["event_id"] == SUCCESSOR_EVENT_ID
    assert receipt["consumption"]["ledger_seq"] == SUCCESSOR_LEDGER_SEQ
    with pytest.raises(PreparedCanaryError) as caught:
        _candidate_from_plan(
            plan,
            event_id=CANDIDATE_EVENT_ID,
            ledger_seq=CANDIDATE_LEDGER_SEQ,
            role="canary",
            store=stores.work_unpublished,
        )
    assert caught.value.failure_code == "RETRY_FORBIDDEN_TARGET"
    resumed = disposition.run_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        backup_path=tmp_path / "resume-13671.sqlite3",
        plan=plan,
        observed_at=OBSERVED_AT,
        repository_root=tmp_path,
        event_id=SUCCESSOR_EVENT_ID,
        ledger_seq=SUCCESSOR_LEDGER_SEQ,
        disposition_digest="sha256:" + "cd" * 32,
        rehearsal=False,
        exact_head=EXACT_HEAD,
    )
    assert resumed["resumed_zero_io_finalisation"] is True
    assert consume_calls == [SUCCESSOR_EVENT_ID]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("state", "QUEUED"),
        ("attempt_count", 2),
        ("provider_dispatched", 0),
        (
            "last_failure_code",
            "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:PRODUCER_INTERNAL_ERROR",
        ),
    ),
)
def test_exhausted_safety_mutation_fail_closes(
    tmp_path: Path, field: str, value: object
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    mutate_retry_field(
        stores.work_unpublished, ledger_seq=13361, field=field, value=value
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _prepare(stores)
    assert caught.value.failure_code == "RETRY_FORBIDDEN_SAFETY_STATE"
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert candidate_identity(stores.work_unpublished)[0] == CANDIDATE_EVENT_ID


def test_claim_or_lease_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    mutate_retry_field(
        stores.work_unpublished,
        ledger_seq=13361,
        field="claim_owner",
        value="issue-790-canary:test",
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _prepare(stores)
    assert caught.value.failure_code == "RETRY_FORBIDDEN_SAFETY_STATE"


def test_candidate_claim_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    mutate_retry_field(
        stores.work_unpublished,
        ledger_seq=CANDIDATE_LEDGER_SEQ,
        field="claim_owner",
        value="issue-790-canary:test",
    )
    with pytest.raises(PreparedCanaryError) as caught:
        _prepare(stores)
    assert caught.value.failure_code == "CANDIDATE_NOT_FRESH"


def test_alias_proving_live_paths_fail_close(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.work_unpublished,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            role="preflight",
        )
    assert caught.value.failure_code == "PATHS_ALIAS"


def test_missing_store_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=tmp_path / "missing.sqlite3",
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            role="preflight",
        )
    assert caught.value.failure_code == "STORE_ABSENT"


def test_missing_exact_head_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head="",
            role="preflight",
        )
    assert caught.value.failure_code == "EXACT_HEAD_ABSENT"


def test_retry_forbidden_target_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan = dict(stores.plan)
    sequence = dict(plan["sequence"])
    sequence["sequence_ordinal"] = 16
    sequence.pop("candidate_event_qualification", None)
    plan["sequence"] = sequence
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            event_id=EVENT_13361,
            ledger_seq=13361,
            role="preflight",
        )
    assert caught.value.failure_code == "RETRY_FORBIDDEN_TARGET"


def test_unique_prepare_is_consumed_by_preflight_apply_and_canary() -> None:
    root = _TEST_FILE.resolve().parents[2]
    sources = (
        (root / "scripts/issue_790_live_canary_preflight.py").read_text(encoding="utf-8"),
        inspect.getsource(disposition._execute_issue_790_plan),
        inspect.getsource(disposition.run_issue_790_canary),
    )
    for source in sources:
        assert "prepare_issue_790_canary" in source
    definitions = [
        node
        for node in ast.parse(
            (
                root / "newsroom/control_plane/issue_790_prepared_canary.py"
            ).read_text(encoding="utf-8")
        ).body
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_issue_790_canary"
    ]
    assert len(definitions) == 1


def test_event_identity_invalid_fail_closes(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    plan = dict(stores.plan)
    sequence = dict(plan["sequence"])
    sequence["sequence_ordinal"] = 16
    sequence.pop("candidate_event_qualification", None)
    plan["sequence"] = sequence
    with pytest.raises(PreparedCanaryError) as caught:
        prepare_issue_790_canary(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            event_id="not-a-digest",
            ledger_seq=2000,
            role="canary",
        )
    assert caught.value.failure_code == "EVENT_IDENTITY_INVALID"


def test_missing_prepared_canary_fail_closes_before_dispatch(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    RehearsalRealGraphitiAdapter.provider_calls = 0
    RehearsalRealGraphitiAdapter.dispatch_started = False
    with pytest.raises(PreparedCanaryError) as caught:
        run_prepared_canary_rehearsal(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            prepared=None,
        )
    assert caught.value.failure_code == PREPARED_CANARY_ABSENT
    assert RehearsalRealGraphitiAdapter.dispatch_started is False
    assert RehearsalRealGraphitiAdapter.provider_calls == 0
    assert dispatch_started_count(stores.work_unpublished) == 0
    assert candidate_identity(stores.work_unpublished)[2] == "QUEUED"


def test_digest_drift_fail_closes_before_dispatch(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    prepared = _prepare(stores)
    drifted = replace(prepared, decision_digest="sha256:" + "00" * 32)
    with pytest.raises(PreparedCanaryError) as caught:
        run_prepared_canary_rehearsal(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            prepared=drifted,
        )
    assert caught.value.failure_code == PREPARED_CANARY_DIGEST_DRIFT
    assert RehearsalRealGraphitiAdapter.dispatch_started is False
    assert dispatch_started_count(stores.work_unpublished) == 0
    assert candidate_identity(stores.work_unpublished)[0] == CANDIDATE_EVENT_ID


def test_dispatch_before_crash_leaves_candidate_unconsumed(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    prepared = _prepare(stores)
    with pytest.raises(PreparedCanaryError) as caught:
        run_prepared_canary_rehearsal(
            store=stores.work_unpublished,
            proving_store=stores.proving,
            plan=stores.plan,
            observed_at=OBSERVED_AT,
            exact_head=EXACT_HEAD,
            prepared=prepared,
            crash_before_dispatch=True,
        )
    assert caught.value.failure_code == "REHEARSAL_CRASH_BEFORE_DISPATCH"
    event_id, ledger_seq, state = candidate_identity(stores.work_unpublished)
    assert event_id == CANDIDATE_EVENT_ID
    assert ledger_seq == CANDIDATE_LEDGER_SEQ
    assert state == "QUEUED"
    assert dispatch_started_count(stores.work_unpublished) == 0
    assert RehearsalRealGraphitiAdapter.provider_calls == 0


def test_rehearsal_refuses_canonical_live_store_paths() -> None:
    forbidden = next(iter(live_issue_790_store_paths()))
    with pytest.raises(PreparedCanaryError) as caught:
        refuse_live_issue_790_store_paths(forbidden)
    assert caught.value.failure_code == "LIVE_STORE_WRITE_REFUSED"


def test_sqlite_backup_refuses_overwrite(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    with pytest.raises(PreparedCanaryError) as caught:
        sqlite_backup_copy(stores.sealed_unpublished, stores.work_unpublished)
    assert caught.value.failure_code == "LIVE_STORE_WRITE_REFUSED"


def test_canary_consumes_prepared_digest_only() -> None:
    source = inspect.getsource(disposition.run_issue_790_canary)
    pre_consume, _sep, _post = source.partition("_consume_issue_790_event")
    assert "prepare_issue_790_canary" in pre_consume
    assert "consume_prepared_canary" in pre_consume
    assert "_require_retry_events_unchanged" not in pre_consume
    assert "retry_forbidden_safety_states_match" not in pre_consume
    assert "validate_retry_forbidden_safety_state" not in pre_consume
    assert "_validate_operational_evidence" in source
    assert "_require_step16_code_identity" in inspect.getsource(
        disposition._validate_operational_evidence
    )
    identity_src = inspect.getsource(disposition._require_step16_code_identity)
    assert "_git_commit_is_ancestor" in identity_src
    assert "ci_test.get(\"head_sha\") != exact_head" in identity_src
    assert "merge-base" in inspect.getsource(disposition._git_commit_is_ancestor)
    resume = source.split("prior_consumption = canary_repository.existing_consumption", 1)[1]
    resume = resume.split("resuming_zero_io_finalisation", 1)[0]
    assert "event_id=event_id" in resume
    assert "ledger_seq=ledger_seq" in resume


def test_fail_branch_inventory_has_named_parity_tests() -> None:
    names = {
        node.name
        for node in ast.parse(_TEST_FILE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }
    for branch in FAIL_BRANCH_INVENTORY:
        assert branch.positive_test in names, branch.invariant
        assert branch.negative_test in names, branch.invariant
        assert branch.zero_provider_calls is True


def test_prepared_failure_codes_are_inventoried() -> None:
    root = Path(__file__).resolve().parents[2]
    modules = (
        root / "newsroom/control_plane/issue_790_prepared_canary.py",
        root / "newsroom/control_plane/issue_790_rehearsal.py",
    )
    codes: set[str] = set()
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        codes.update(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.isupper()
            and "_" in node.value
            and node.value
            not in {
                "UTC",
                "QUEUED",
                "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT",
                "DISABLED_BEFORE_PROVIDER_DISPATCH",
                "PREDISPATCH_BINDING_FAILURE",
                "DISPATCH_STARTED",
                "NO_PROVIDER_CALL",
                "UNSTRUCTURED",
            }
        )
    inventoried = {branch.failure_code for branch in FAIL_BRANCH_INVENTORY}
    named = {
        "PREPARED_CANARY_ABSENT",
        "PREPARED_CANARY_DIGEST_DRIFT",
        "EXACT_HEAD_ABSENT",
        "CANDIDATE_IDENTITY",
        "STORE_ABSENT",
        "PATHS_ALIAS",
        "RETRY_FORBIDDEN_SAFETY_STATE",
        "RETRY_FORBIDDEN_TARGET",
        "EVENT_IDENTITY_INVALID",
        "CANDIDATE_NOT_FRESH",
        "LIVE_STORE_WRITE_REFUSED",
        "REHEARSAL_CRASH_BEFORE_DISPATCH",
    }
    assert named <= inventoried
    assert named <= codes | inventoried
    local_raise_codes = {
        code
        for code in codes
        if code.endswith(("_ABSENT", "_DRIFT", "_STATE", "_TARGET", "_INVALID", "_FRESH", "_REFUSED", "_DISPATCH", "_ALIAS", "_IDENTITY"))
        or code in named
    }
    assert local_raise_codes <= inventoried | named


def test_rehearsal_skips_live_only_predispatch_gates() -> None:
    source = inspect.getsource(run_prepared_canary_rehearsal)
    assert LIVE_ONLY_PREDISPATCH_GATES
    for gate in (
        "_require_approved_plan",
        "_validate_operational_evidence",
        "_require_issue_790_canary_route",
        "_require_step16_runtime_semantics",
        "_require_worker_unloaded",
        "_assert_exact_target",
        "_require_sequence_predecessor",
    ):
        assert gate not in source


def test_canary_rehearsal_path_uses_run_issue_790_canary(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)
    prepared = _prepare(stores)
    result = disposition.run_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        backup_path=tmp_path / "unused-backup.sqlite3",
        plan=stores.plan,
        observed_at=OBSERVED_AT,
        repository_root=tmp_path,
        event_id=CANDIDATE_EVENT_ID,
        ledger_seq=CANDIDATE_LEDGER_SEQ,
        disposition_digest="sha256:" + "cd" * 32,
        prepared=prepared,
        rehearsal=True,
        exact_head=EXACT_HEAD,
    )
    assert result["dispatch_started"] is True
    assert result["provider_calls"] == 0
    assert consume_prepared_canary(prepared, expected=prepared) is prepared
