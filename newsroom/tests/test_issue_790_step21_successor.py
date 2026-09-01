"""#790 Step 21 qualifies one fresh provider-free successor path."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.control_plane import issue_790_canary as canary_module
from newsroom.control_plane import issue_790_contract as contract_module
from newsroom.control_plane import issue_790_disposition as disposition_module
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    ISSUE_790_STEP21_PENDING_PLAN_PATH,
    Issue790DispositionError,
    _retain_retry_exclusions_for_plan,
    issue_790_checked_approval,
    qualify_issue_790_candidate_event,
    run_issue_790_canary,
    seal_issue_790_step16_plan,
    validate_issue_790_step16_candidate,
)

_ROOT = Path(__file__).resolve().parents[2]
_EVENT_8835 = "sha256:2c6941748dce73271a0d4aae2e94766384d0dd16bc29707524f74b8026d7c3b9"
_EVENT_13284 = "sha256:fb49a59d1c421c261bab4586873680e50e8181acfd0d6ebc03a14f889147d896"
_EVENT_13337 = "sha256:e4ef6fd0af91d5d525af3f37f5cfb422733a1640c84c16cdc162f0e6d8bb0b5b"
_EVENT_13362 = "sha256:98d0ffbca828f6937b687751c711fec3be9182e679b2fcd041d3d14160f00c85"
_EVENT_13361 = "sha256:90c3b4de731f2df8d4353e516762f65450570e1e8372ed7b703423f717351ae7"


def _seal21() -> dict[str, object]:
    pending = json.loads((_ROOT / ISSUE_790_STEP21_PENDING_PLAN_PATH).read_text())
    pre_dispatch = json.loads((_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text())
    return seal_issue_790_step16_plan(
        pending,
        issue_790_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=pre_dispatch,
    )


def test_step21_binds_exhausted_step20_fix_and_fresh_attempt_zero_event() -> None:
    candidate = _seal21()
    validate_issue_790_step16_candidate(candidate)
    assert candidate["canonical_digest"] == (
        contract_module.ISSUE_790_STEP21_CHECKED_CANDIDATE_DIGEST
    )
    sequence = candidate["sequence"]
    assert sequence["sequence_ordinal"] == 21
    assert sequence["predecessor"]["plan_digest"] == (
        contract_module.ISSUE_790_STEP20_ACTIVATED_PLAN_DIGEST
    )
    assert sequence["predecessor_activation_digest"] == (
        contract_module.ISSUE_790_STEP20_ACTIVATION_DIGEST
    )
    assert sequence["predecessor"]["event_id"] == _EVENT_13362
    assert sequence["predecessor"]["ledger_seq"] == 13362
    assert sequence["reviewed_fix"]["pull_request_url"].endswith("/859")
    qualification = sequence["candidate_event_qualification"]
    assert qualification == {
        "event_id": _EVENT_13361,
        "event_manifest_digest": "sha256:c75596c1344ec017d6f4980849cc18d4d59212faa71d85bc428e437a0d8f81c7",
        "event_preflight_digest": "sha256:1d333431d96e6ffe9c02b235143016116682c187d9420506a899fecf838f0eaa",
        "ledger_seq": 13361,
        "observed_at": "2026-08-30T20:58:43.662872Z",
        "provider_calls": 0,
        "qualification_digest": "sha256:dc45e4f2e78217e0bd151a18af284ed007e0ddb94fe94394a131217618f9556a",
        "resolved_unit_count": 1,
        "schema_version": "newsroom.issue-790.candidate-event-qualification.v1",
        "status": "READY_FOR_OWNER_PACKET",
        "store_mutations": 0,
    }
    assert sequence["candidate_event_preparation_digest"] == (
        "sha256:ddb0605ab09cf39bd4f8c62ef0a7897d947db9ed8eef8c81afa5874b9700c436"
    )
    assert [item["ledger_seq"] for item in candidate["retry_forbidden_events"]] == [
        1932, 1972, 8834, 8835, 13284, 13337, 13362
    ]
    assert candidate["executable"] is False
    assert candidate["live_canary_authorised"] is False
    assert contract_module.issue_790_owner_activated_sequence(21) is True
    assert contract_module.issue_790_owner_activated_sequence(22) is True
    assert contract_module.issue_790_owner_activated_sequence(23) is True
    assert contract_module.issue_790_owner_activated_sequence(24) is False
    with pytest.raises(KeyError):
        contract_module.issue_790_approved_plan_contract(candidate["canonical_digest"])


def test_step21_checked_candidate_cannot_execute_without_future_live_authority(
    tmp_path: Path,
) -> None:
    with pytest.raises(Issue790DispositionError, match="checked approval is not live authority"):
        run_issue_790_canary(
            store=tmp_path / "unused.sqlite3",
            proving_store=tmp_path / "unused-proving.sqlite3",
            backup_path=tmp_path / "unused-backup.sqlite3",
            plan=_seal21(),
            observed_at=datetime(2026, 8, 30, 21, tzinfo=UTC),
            repository_root=_ROOT,
            event_id=_EVENT_13361,
            ledger_seq=13361,
            disposition_digest="sha256:" + "cd" * 32,
        )


@pytest.mark.parametrize(
    ("event_id", "ledger_seq"),
    ((_EVENT_13362, 13362), (_EVENT_13337, 13337), (_EVENT_8835, 8835), (_EVENT_13284, 13284)),
)
def test_qualification_rejects_every_exhausted_canary_before_store_open(
    tmp_path: Path, event_id: str, ledger_seq: int
) -> None:
    with pytest.raises(Issue790DispositionError, match="candidate event is forbidden"):
        qualify_issue_790_candidate_event(
            store=tmp_path / "missing.sqlite3",
            proving_store=tmp_path / "missing-proving.sqlite3",
            event_id=event_id,
            ledger_seq=ledger_seq,
            observed_at=datetime(2026, 8, 30, 21, tzinfo=UTC),
        )


def test_event_13362_cannot_be_consumed_again(tmp_path: Path) -> None:
    store = tmp_path / "canary.sqlite3"
    Issue790CanaryRepository(str(store))
    repository = Issue790CanaryRepository.open_existing(str(store))
    with pytest.raises(Issue790CanaryIntegrityError, match="retained failure"):
        repository.consume(
            approved_plan_digest="sha256:" + "ab" * 32,
            disposition_digest="sha256:" + "cd" * 32,
            event_id=_EVENT_13362,
            ledger_seq=13362,
            owner_id="issue-790-canary:test",
            preflight_evidence={},
            consumed_at=datetime(2026, 8, 30, tzinfo=UTC),
        )


def test_step21_appends_13362_to_the_existing_retry_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "canary.sqlite3"
    repository = Issue790CanaryRepository(str(store))
    events = _seal21()["retry_forbidden_events"]
    root_plan_digest = "sha256:" + "11" * 32
    disposition_digest = "sha256:" + "22" * 32
    connection = sqlite3.connect(store)
    try:
        connection.execute(
            "CREATE TABLE model_usage_conservative_dispositions("
            "invocation_id TEXT,approved_plan_digest TEXT,disposition_digest TEXT PRIMARY KEY)"
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
        plan={"canonical_digest": root_plan_digest, "retry_forbidden_events": events},
        disposition_digest=disposition_digest,
        observed_at=datetime(2026, 8, 30, 1, tzinfo=UTC),
    )
    assert [item["ledger_seq"] for item in retained] == [
        1932, 1972, 8834, 8835, 13284, 13337, 13362
    ]
