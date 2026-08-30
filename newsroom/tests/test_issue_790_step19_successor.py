"""#790 Step 19 binds a fresh event after Step 18 exhausted pre-provider."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.control_plane import issue_790_canary as canary_module
from newsroom.control_plane import issue_790_contract as contract_module
from newsroom.control_plane.issue_790_canary import Issue790CanaryRepository
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    ISSUE_790_STEP19_PENDING_PLAN_PATH,
    Issue790DispositionError,
    _retry_event_snapshots,
    issue_790_checked_approval,
    run_issue_790_canary,
    seal_issue_790_step16_plan,
    validate_issue_790_step16_candidate,
)

_ROOT = Path(__file__).resolve().parents[2]
_EVENT_13284 = (
    "sha256:fb49a59d1c421c261bab4586873680e50e8181acfd0d6ebc03a14f889147d896"
)
_EVENT_13337 = (
    "sha256:e4ef6fd0af91d5d525af3f37f5cfb422733a1640c84c16cdc162f0e6d8bb0b5b"
)


def _seal19() -> dict[str, object]:
    pending = json.loads((_ROOT / ISSUE_790_STEP19_PENDING_PLAN_PATH).read_text())
    pre_dispatch = json.loads(
        (_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text()
    )
    return seal_issue_790_step16_plan(
        pending,
        issue_790_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=pre_dispatch,
    )


def test_step19_is_new_and_binds_the_runtime_fix_and_fresh_event() -> None:
    candidate = _seal19()
    validate_issue_790_step16_candidate(candidate)
    assert candidate["canonical_digest"] == (
        contract_module.ISSUE_790_STEP19_CHECKED_CANDIDATE_DIGEST
    )
    assert candidate["canonical_digest"] != (
        contract_module.ISSUE_790_STEP18_CHECKED_CANDIDATE_DIGEST
    )
    sequence = candidate["sequence"]
    assert sequence["sequence_ordinal"] == 19
    assert sequence["predecessor"]["plan_digest"] == (
        contract_module.ISSUE_790_STEP18_ACTIVATED_PLAN_DIGEST
    )
    assert sequence["predecessor_activation_digest"] == (
        contract_module.ISSUE_790_STEP18_ACTIVATION_DIGEST
    )
    assert sequence["predecessor"]["event_id"] == _EVENT_13284
    qualification = sequence["candidate_event_qualification"]
    assert qualification["event_id"] == _EVENT_13337
    assert qualification["ledger_seq"] == 13337
    assert qualification["provider_calls"] == 0
    assert qualification["store_mutations"] == 0
    assert [item["ledger_seq"] for item in candidate["retry_forbidden_events"]] == [
        1932,
        1972,
        8834,
        8835,
        13284,
    ]
    assert candidate["executable"] is False
    assert candidate["live_canary_authorised"] is False


def test_step19_checked_candidate_cannot_execute_before_owner_activation(tmp_path: Path) -> None:
    candidate = _seal19()
    with pytest.raises(
        Issue790DispositionError,
        match="checked approval is not live authority",
    ):
        run_issue_790_canary(
            store=tmp_path / "unused-authority.sqlite3",
            proving_store=tmp_path / "unused-proving.sqlite3",
            backup_path=tmp_path / "unused-backup.sqlite3",
            plan=candidate,
            observed_at=datetime(2026, 8, 30, 13, tzinfo=UTC),
            repository_root=_ROOT,
            event_id="sha256:" + "ab" * 32,
            ledger_seq=13338,
            disposition_digest="sha256:" + "cd" * 32,
        )


def test_step19_can_retain_step18_target_as_retry_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "canary.sqlite"
    repository = Issue790CanaryRepository(str(store))
    events = _seal19()["retry_forbidden_events"]
    connection = sqlite3.connect(store)
    try:
        connection.execute(
            "CREATE TABLE model_usage_conservative_dispositions("
            "invocation_id TEXT,approved_plan_digest TEXT,"
            "disposition_digest TEXT PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO model_usage_conservative_dispositions VALUES(?,?,?)",
            ("invocation", "sha256:" + "11" * 32, "sha256:" + "22" * 32),
        )
        connection.execute(
            "CREATE TABLE unpublished_graphiti_revision_events("
            "event_id TEXT,ledger_seq INTEGER,state TEXT,attempt_count INTEGER,"
            "available_at TEXT,last_failure_code TEXT,provider_dispatched INTEGER)"
        )
        connection.executemany(
            "INSERT INTO unpublished_graphiti_revision_events VALUES(?,?,?,?,?,?,?)",
            [
                (
                    item["event_id"], item["ledger_seq"], item["state"],
                    item["attempt_count"], item["available_at"],
                    item["last_failure_code"], int(item["provider_dispatched"]),
                )
                for item in events
            ],
        )
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setattr(
        canary_module,
        "_require_effective_plan_contract",
        lambda *_args, **_kwargs: SimpleNamespace(invocation_id="invocation"),
    )
    retained = repository.retain_retry_exclusions(
        approved_plan_digest="sha256:" + "11" * 32,
        disposition_digest="sha256:" + "22" * 32,
        events=events,
        excluded_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    assert [item["ledger_seq"] for item in retained] == [
        1932, 1972, 8834, 8835, 13284
    ]
    assert _retry_event_snapshots(store, tuple(events)) == events
