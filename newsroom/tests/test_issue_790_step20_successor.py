"""#790 Step 20 mints a successor family after Step 19 exhausted post-provider."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import issue_790_canary as canary_module
from newsroom.control_plane import issue_790_contract as contract_module
from newsroom.control_plane import issue_790_disposition as disposition_module
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    ISSUE_790_STEP20_PENDING_PLAN_PATH,
    Issue790DispositionError,
    _retain_retry_exclusions_for_plan,
    _retry_event_snapshots,
    issue_790_checked_approval,
    qualify_issue_790_candidate_event,
    run_issue_790_canary,
    seal_issue_790_step16_plan,
    validate_issue_790_step16_candidate,
)

_ROOT = Path(__file__).resolve().parents[2]
_EVENT_8835 = (
    "sha256:2c6941748dce73271a0d4aae2e94766384d0dd16bc29707524f74b8026d7c3b9"
)
_EVENT_13284 = (
    "sha256:fb49a59d1c421c261bab4586873680e50e8181acfd0d6ebc03a14f889147d896"
)
_EVENT_13337 = (
    "sha256:e4ef6fd0af91d5d525af3f37f5cfb422733a1640c84c16cdc162f0e6d8bb0b5b"
)
_UNREGISTERED_PENDING = "sha256:" + "00" * 32


def _seal20() -> dict[str, object]:
    pending = json.loads((_ROOT / ISSUE_790_STEP20_PENDING_PLAN_PATH).read_text())
    pre_dispatch = json.loads(
        (_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text()
    )
    return seal_issue_790_step16_plan(
        pending,
        issue_790_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=pre_dispatch,
    )


def test_step20_is_new_family_and_binds_step19_and_the_reviewed_fix() -> None:
    candidate = _seal20()
    validate_issue_790_step16_candidate(candidate)
    assert candidate["canonical_digest"] == (
        contract_module.ISSUE_790_STEP20_CHECKED_CANDIDATE_DIGEST
    )
    assert candidate["canonical_digest"] != (
        contract_module.ISSUE_790_STEP19_CHECKED_CANDIDATE_DIGEST
    )
    sequence = candidate["sequence"]
    assert sequence["sequence_ordinal"] == 20
    assert sequence["predecessor"]["plan_digest"] == (
        contract_module.ISSUE_790_STEP19_ACTIVATED_PLAN_DIGEST
    )
    assert sequence["predecessor_activation_digest"] == (
        contract_module.ISSUE_790_STEP19_ACTIVATION_DIGEST
    )
    assert sequence["predecessor"]["event_id"] == _EVENT_13337
    assert sequence["predecessor"]["ledger_seq"] == 13337
    assert "consumption_digest" not in sequence["predecessor"]
    assert "candidate_event_qualification" not in sequence
    assert sequence["reviewed_fix"]["pull_request_url"].endswith("/855")
    assert [item["ledger_seq"] for item in candidate["retry_forbidden_events"]] == [
        1932,
        1972,
        8834,
        8835,
        13284,
        13337,
    ]
    assert candidate["retry_forbidden_events"][-1]["available_at"] == (
        "2026-08-30T13:00:55.782046Z"
    )
    assert candidate["executable"] is False
    assert candidate["live_canary_authorised"] is False
    assert contract_module.issue_790_owner_activated_sequence(20) is True
    assert contract_module.issue_790_owner_activated_sequence(21) is True
    assert contract_module.issue_790_owner_activated_sequence(22) is True
    assert contract_module.issue_790_owner_activated_sequence(23) is False
    contract = contract_module.issue_790_checked_candidate_contract(
        candidate["canonical_digest"]
    )
    assert contract.sequence_ordinal == 20
    assert contract.pending_digest == contract_module.ISSUE_790_STEP20_PENDING_DIGEST
    with pytest.raises(KeyError):
        contract_module.issue_790_approved_plan_contract(
            candidate["canonical_digest"]
        )


def test_step20_checked_candidate_cannot_execute_before_owner_activation(
    tmp_path: Path,
) -> None:
    candidate = _seal20()
    with pytest.raises(
        Issue790DispositionError,
        match="checked approval is not live authority",
    ):
        run_issue_790_canary(
            store=tmp_path / "unused-authority.sqlite3",
            proving_store=tmp_path / "unused-proving.sqlite3",
            backup_path=tmp_path / "unused-backup.sqlite3",
            plan=candidate,
            observed_at=datetime(2026, 8, 30, 18, tzinfo=UTC),
            repository_root=_ROOT,
            event_id="sha256:" + "ab" * 32,
            ledger_seq=13338,
            disposition_digest="sha256:" + "cd" * 32,
        )


def test_unregistered_pending_digest_fail_closed() -> None:
    with pytest.raises(Issue790DispositionError, match="pending digest differs"):
        issue_790_checked_approval(_UNREGISTERED_PENDING)
    with pytest.raises(KeyError):
        contract_module.issue_790_checked_candidate_contract_for_pending(
            _UNREGISTERED_PENDING
        )
    pending = json.loads((_ROOT / ISSUE_790_STEP20_PENDING_PLAN_PATH).read_text())
    pending["sequence"]["hold_comment"] = "0000000000"
    unsigned = {
        key: item for key, item in pending.items() if key != "canonical_digest"
    }
    invented = digest_canonical(unsigned)
    with pytest.raises(Issue790DispositionError, match="pending digest differs"):
        issue_790_checked_approval(invented)


@pytest.mark.parametrize(
    ("event_id", "ledger_seq"),
    (
        (_EVENT_13337, 13337),
        (_EVENT_8835, 8835),
        (_EVENT_13284, 13284),
    ),
)
def test_qualify_forbids_exhausted_ledgers_before_store_open(
    tmp_path: Path,
    event_id: str,
    ledger_seq: int,
) -> None:
    with pytest.raises(
        Issue790DispositionError,
        match="candidate event is forbidden",
    ):
        qualify_issue_790_candidate_event(
            store=tmp_path / "missing-unpublished.sqlite3",
            proving_store=tmp_path / "missing-proving.sqlite3",
            event_id=event_id,
            ledger_seq=ledger_seq,
            observed_at=datetime(2026, 8, 30, 18, tzinfo=UTC),
        )


def test_qualify_unknown_ledger_reaches_store_open(tmp_path: Path) -> None:
    with pytest.raises(
        Issue790DispositionError,
        match="source unpublished store is absent",
    ):
        qualify_issue_790_candidate_event(
            store=tmp_path / "missing-unpublished.sqlite3",
            proving_store=tmp_path / "missing-proving.sqlite3",
            event_id="sha256:" + "ab" * 32,
            ledger_seq=13338,
            observed_at=datetime(2026, 8, 30, 18, tzinfo=UTC),
        )


def test_event_13337_cannot_be_selected_for_canary(tmp_path: Path) -> None:
    store = tmp_path / "canary.sqlite"
    Issue790CanaryRepository(str(store))
    repository = Issue790CanaryRepository.open_existing(str(store))
    with pytest.raises(Issue790CanaryIntegrityError, match="retained failure"):
        repository.consume(
            approved_plan_digest="sha256:" + "ab" * 32,
            disposition_digest="sha256:" + "cd" * 32,
            event_id=_EVENT_13337,
            ledger_seq=13337,
            owner_id="issue-790-canary:test",
            preflight_evidence={},
            consumed_at=datetime(2026, 8, 30, tzinfo=UTC),
        )


def test_step20_can_retain_step19_target_as_retry_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "canary.sqlite"
    repository = Issue790CanaryRepository(str(store))
    events = _seal20()["retry_forbidden_events"]
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
        1932, 1972, 8834, 8835, 13284, 13337
    ]
    assert retained[-1]["event_snapshot"]["provider_dispatched"] is True
    assert _retry_event_snapshots(store, tuple(events)) == events


def test_step20_appends_new_exhausted_event_to_existing_retry_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "canary.sqlite"
    repository = Issue790CanaryRepository(str(store))
    events = _seal20()["retry_forbidden_events"]
    root_plan_digest = "sha256:" + "11" * 32
    disposition_digest = "sha256:" + "22" * 32
    connection = sqlite3.connect(store)
    try:
        connection.execute(
            "CREATE TABLE model_usage_conservative_dispositions("
            "invocation_id TEXT,approved_plan_digest TEXT,"
            "disposition_digest TEXT PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO model_usage_conservative_dispositions VALUES(?,?,?)",
            ("invocation", root_plan_digest, disposition_digest),
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
    monkeypatch.setattr(
        disposition_module,
        "issue_790_approved_plan_contract",
        lambda *_args, **_kwargs: SimpleNamespace(invocation_id="invocation"),
    )
    repository.retain_retry_exclusions(
        approved_plan_digest=root_plan_digest,
        disposition_digest=disposition_digest,
        events=events[:-1],
        excluded_at=datetime(2026, 8, 30, tzinfo=UTC),
    )

    retained = _retain_retry_exclusions_for_plan(
        repository,
        plan={
            "canonical_digest": root_plan_digest,
            "retry_forbidden_events": events,
        },
        disposition_digest=disposition_digest,
        observed_at=datetime(2026, 8, 30, 1, tzinfo=UTC),
    )

    assert [item["ledger_seq"] for item in retained] == [
        1932, 1972, 8834, 8835, 13284, 13337
    ]
