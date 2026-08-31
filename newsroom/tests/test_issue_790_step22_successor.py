"""#790 Step 22 qualifies one fresh provider-free successor path."""

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
    ISSUE_790_STEP22_PENDING_PLAN_PATH,
    Issue790DispositionError,
    _require_retry_events_unchanged,
    _require_retry_exclusions,
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
_EVENT_13665 = "sha256:b39a1e6ea465ca4a993893d4ae51c94ca9ac3e0db7f4fd70a8c780367263be6b"
_LIVE_13361_AVAILABLE_AT = "2026-08-30T21:29:18.946358Z"


def _seal22() -> dict[str, object]:
    pending = json.loads((_ROOT / ISSUE_790_STEP22_PENDING_PLAN_PATH).read_text())
    pre_dispatch = json.loads((_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text())
    return seal_issue_790_step16_plan(
        pending,
        issue_790_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=pre_dispatch,
    )


def test_step22_binds_exhausted_step21_fix_and_fresh_attempt_zero_event() -> None:
    pending = json.loads((_ROOT / ISSUE_790_STEP22_PENDING_PLAN_PATH).read_text())
    assert pending["canonical_digest"] == (
        contract_module.ISSUE_790_STEP22_PENDING_DIGEST
    )
    assert pending["executable"] is False
    assert pending["live_canary_authorised"] is False
    assert pending["approval"] is None
    assert pending["plan_status"] == "PENDING_OWNER_REVIEW"
    candidate = _seal22()
    validate_issue_790_step16_candidate(candidate)
    assert candidate["canonical_digest"] == (
        contract_module.ISSUE_790_STEP22_CHECKED_CANDIDATE_DIGEST
    )
    sequence = candidate["sequence"]
    assert sequence["sequence_ordinal"] == 22
    assert sequence["predecessor"]["plan_digest"] == (
        contract_module.ISSUE_790_STEP21_ACTIVATED_PLAN_DIGEST
    )
    assert sequence["predecessor_activation_digest"] == (
        contract_module.ISSUE_790_STEP21_ACTIVATION_DIGEST
    )
    assert sequence["predecessor"]["event_id"] == _EVENT_13361
    assert sequence["predecessor"]["ledger_seq"] == 13361
    assert sequence["reviewed_fix"]["pull_request_url"].endswith("/861")
    qualification = sequence["candidate_event_qualification"]
    assert qualification == {
        "event_id": _EVENT_13665,
        "event_manifest_digest": (
            "sha256:43ae5b036c46427d2ef7d55c1290c32e23ae5aa313dd7c66cac384272ed97404"
        ),
        "event_preflight_digest": (
            "sha256:eafdefe613fa509e9f3ee878931041aed970242f1062f2de1aaf1d33492e95ea"
        ),
        "ledger_seq": 13665,
        "observed_at": "2026-08-31T10:11:17.609260Z",
        "provider_calls": 0,
        "qualification_digest": (
            "sha256:df39aa693e712bc8d9b1c8c691f9effa6f1ff40bf945e20b9b997dbf32a16ed5"
        ),
        "resolved_unit_count": 1,
        "schema_version": "newsroom.issue-790.candidate-event-qualification.v1",
        "status": "READY_FOR_OWNER_PACKET",
        "store_mutations": 0,
    }
    assert sequence["candidate_event_preparation_digest"] == (
        "sha256:4e8d4759b8dcacb8fdb0d2e49a0432fe15c8ffba6a1b1b36fbab1e9be0cad4e0"
    )
    assert [item["ledger_seq"] for item in candidate["retry_forbidden_events"]] == [
        1932, 1972, 8834, 8835, 13284, 13337, 13361, 13362
    ]
    assert candidate["canary"]["event_binding"] == (
        "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT"
    )
    assert candidate["executable"] is False
    assert candidate["live_canary_authorised"] is False
    assert contract_module.issue_790_owner_activated_sequence(22) is True
    assert contract_module.issue_790_owner_activated_sequence(23) is False
    with pytest.raises(KeyError):
        contract_module.issue_790_approved_plan_contract(candidate["canonical_digest"])


def test_step22_checked_candidate_cannot_execute_without_future_live_authority(
    tmp_path: Path,
) -> None:
    with pytest.raises(Issue790DispositionError, match="checked approval is not live authority"):
        run_issue_790_canary(
            store=tmp_path / "unused.sqlite3",
            proving_store=tmp_path / "unused-proving.sqlite3",
            backup_path=tmp_path / "unused-backup.sqlite3",
            plan=_seal22(),
            observed_at=datetime(2026, 8, 31, 10, 12, tzinfo=UTC),
            repository_root=_ROOT,
            event_id=_EVENT_13665,
            ledger_seq=13665,
            disposition_digest="sha256:" + "cd" * 32,
        )


@pytest.mark.parametrize(
    ("event_id", "ledger_seq"),
    (
        (_EVENT_13361, 13361),
        (_EVENT_13362, 13362),
        (_EVENT_13337, 13337),
        (_EVENT_8835, 8835),
        (_EVENT_13284, 13284),
    ),
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
            observed_at=datetime(2026, 8, 31, 10, 12, tzinfo=UTC),
        )


def test_event_13361_cannot_be_consumed_again(tmp_path: Path) -> None:
    store = tmp_path / "canary.sqlite3"
    Issue790CanaryRepository(str(store))
    repository = Issue790CanaryRepository.open_existing(str(store))
    with pytest.raises(Issue790CanaryIntegrityError, match="retained failure"):
        repository.consume(
            approved_plan_digest="sha256:" + "ab" * 32,
            disposition_digest="sha256:" + "cd" * 32,
            event_id=_EVENT_13361,
            ledger_seq=13361,
            owner_id="issue-790-canary:test",
            preflight_evidence={},
            consumed_at=datetime(2026, 8, 31, tzinfo=UTC),
        )


def test_step22_appends_13361_to_the_existing_retry_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "canary.sqlite3"
    repository = Issue790CanaryRepository(str(store))
    events = _seal22()["retry_forbidden_events"]
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
        events=[item for item in events if item["ledger_seq"] != 13361],
        excluded_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    retained = _retain_retry_exclusions_for_plan(
        repository,
        plan={"canonical_digest": root_plan_digest, "retry_forbidden_events": events},
        disposition_digest=disposition_digest,
        observed_at=datetime(2026, 8, 31, 10, 12, tzinfo=UTC),
    )
    assert [item["ledger_seq"] for item in retained] == [
        1932, 1972, 8834, 8835, 13284, 13337, 13361, 13362
    ]


def test_live_apply_does_not_treat_o16_consumption_as_durable_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "canary.sqlite3"
    repository = Issue790CanaryRepository(str(store))
    events = _seal22()["retry_forbidden_events"]
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
        events=[item for item in events if item["ledger_seq"] != 13361],
        excluded_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    plan = {"canonical_digest": root_plan_digest, "retry_forbidden_events": events}
    with pytest.raises(
        Issue790DispositionError,
        match="durable retry exclusions differ",
    ):
        _require_retry_exclusions(repository, plan=plan)
    retained = _retain_retry_exclusions_for_plan(
        repository,
        plan=plan,
        disposition_digest=disposition_digest,
        observed_at=datetime(2026, 8, 31, 10, 12, tzinfo=UTC),
    )
    assert [item["ledger_seq"] for item in retained] == [
        1932, 1972, 8834, 8835, 13284, 13337, 13361, 13362
    ]
    exhausted = next(item for item in events if item["ledger_seq"] == 13361)
    assert exhausted["state"] == "CONFIGURATION_HELD"
    assert exhausted["attempt_count"] == 1


def _plan_retry_events() -> list[dict[str, object]]:
    return [dict(item) for item in _seal22()["retry_forbidden_events"]]


def _event(events: list[dict[str, object]], ledger_seq: int) -> dict[str, object]:
    return next(item for item in events if item["ledger_seq"] == ledger_seq)


def _with_available_at(
    events: list[dict[str, object]], ledger_seq: int, available_at: str
) -> list[dict[str, object]]:
    retained = [dict(item) for item in events]
    _event(retained, ledger_seq)["available_at"] = available_at
    return retained


def _write_retry_event_table(store: Path, events: list[dict[str, object]]) -> None:
    connection = sqlite3.connect(store)
    try:
        connection.execute(
            "CREATE TABLE unpublished_graphiti_revision_events("
            "event_id TEXT,ledger_seq INTEGER,state TEXT,attempt_count INTEGER,"
            "available_at TEXT,last_failure_code TEXT,provider_dispatched INTEGER)"
        )
        connection.executemany(
            "INSERT INTO unpublished_graphiti_revision_events VALUES(?,?,?,?,?,?,?)",
            [
                (
                    item["event_id"],
                    item["ledger_seq"],
                    item["state"],
                    item["attempt_count"],
                    item["available_at"],
                    item["last_failure_code"],
                    int(item["provider_dispatched"]),
                )
                for item in events
            ],
        )
        connection.commit()
    finally:
        connection.close()


def test_require_retry_events_unchanged_accepts_13361_seal_available_at_drift(
    tmp_path: Path,
) -> None:
    plan_events = _plan_retry_events()
    live_events = _with_available_at(
        plan_events, 13361, _LIVE_13361_AVAILABLE_AT
    )
    store = tmp_path / "unpublished.sqlite3"
    _write_retry_event_table(store, live_events)
    retained = _require_retry_events_unchanged(
        store, {"retry_forbidden_events": plan_events}
    )
    live_13361 = _event(retained, 13361)
    assert live_13361["available_at"] == _LIVE_13361_AVAILABLE_AT
    assert live_13361["event_id"] == _EVENT_13361
    assert live_13361["state"] == "CONFIGURATION_HELD"
    assert live_13361["attempt_count"] == 1
    assert live_13361["provider_dispatched"] is True
    assert all(item["ledger_seq"] != 13665 for item in retained)


def test_require_retry_events_unchanged_accepts_retry_held_available_at_drift(
    tmp_path: Path,
) -> None:
    plan_events = _plan_retry_events()
    live_events = _with_available_at(plan_events, 1932, _LIVE_13361_AVAILABLE_AT)
    store = tmp_path / "unpublished.sqlite3"
    _write_retry_event_table(store, live_events)
    retained = _require_retry_events_unchanged(
        store, {"retry_forbidden_events": plan_events}
    )
    assert _event(retained, 1932)["available_at"] == _LIVE_13361_AVAILABLE_AT
    assert _event(retained, 1932)["state"] == "RETRY_HELD"


def test_require_retry_events_unchanged_rejects_13361_state_change(
    tmp_path: Path,
) -> None:
    plan_events = _plan_retry_events()
    live_events = _with_available_at(
        plan_events, 13361, _LIVE_13361_AVAILABLE_AT
    )
    _event(live_events, 13361)["state"] = "QUEUED"
    store = tmp_path / "unpublished.sqlite3"
    _write_retry_event_table(store, live_events)
    with pytest.raises(
        Issue790DispositionError,
        match="issue #790 retry-forbidden event state differs",
    ):
        _require_retry_events_unchanged(
            store, {"retry_forbidden_events": plan_events}
        )


def test_require_retry_events_unchanged_rejects_claimed_13361(
    tmp_path: Path,
) -> None:
    plan_events = _plan_retry_events()
    live_events = _with_available_at(
        plan_events, 13361, _LIVE_13361_AVAILABLE_AT
    )
    store = tmp_path / "unpublished.sqlite3"
    connection = sqlite3.connect(store)
    try:
        connection.execute(
            "CREATE TABLE unpublished_graphiti_revision_events("
            "event_id TEXT,ledger_seq INTEGER,state TEXT,attempt_count INTEGER,"
            "available_at TEXT,last_failure_code TEXT,provider_dispatched INTEGER,"
            "claim_owner TEXT,claim_expires_at TEXT)"
        )
        connection.executemany(
            "INSERT INTO unpublished_graphiti_revision_events "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (
                    item["event_id"],
                    item["ledger_seq"],
                    item["state"],
                    item["attempt_count"],
                    item["available_at"],
                    item["last_failure_code"],
                    int(item["provider_dispatched"]),
                    "worker-1" if item["ledger_seq"] == 13361 else None,
                    None,
                )
                for item in live_events
            ],
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(
        Issue790DispositionError,
        match="RETRY_FORBIDDEN_SAFETY_STATE",
    ):
        _require_retry_events_unchanged(
            store, {"retry_forbidden_events": plan_events}
        )


def test_retain_retry_exclusions_accepts_13361_seal_available_at_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "canary.sqlite3"
    repository = Issue790CanaryRepository(str(store))
    plan_events = _plan_retry_events()
    live_events = _with_available_at(
        plan_events, 13361, _LIVE_13361_AVAILABLE_AT
    )
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
        connection.commit()
    finally:
        connection.close()
    _write_retry_event_table(store, live_events)
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
    retained = _retain_retry_exclusions_for_plan(
        repository,
        plan={
            "canonical_digest": root_plan_digest,
            "retry_forbidden_events": plan_events,
        },
        disposition_digest=disposition_digest,
        observed_at=datetime(2026, 8, 31, 10, 12, tzinfo=UTC),
    )
    assert [item["ledger_seq"] for item in retained] == [
        1932, 1972, 8834, 8835, 13284, 13337, 13361, 13362
    ]
    snapshot = next(
        item["event_snapshot"] for item in retained if item["ledger_seq"] == 13361
    )
    assert isinstance(snapshot, dict)
    assert snapshot["available_at"] == _LIVE_13361_AVAILABLE_AT
    later_available_at = "2026-08-31T11:55:58.545912Z"
    connection = sqlite3.connect(store)
    try:
        connection.execute(
            "UPDATE unpublished_graphiti_revision_events "
            "SET available_at=? WHERE ledger_seq=13361",
            (later_available_at,),
        )
        connection.commit()
    finally:
        connection.close()
    replayed = repository.retain_retry_exclusions(
        approved_plan_digest=root_plan_digest,
        disposition_digest=disposition_digest,
        events=plan_events,
        excluded_at=datetime(2026, 8, 31, 11, 55, tzinfo=UTC),
    )
    replayed_snapshot = next(
        item["event_snapshot"] for item in replayed if item["ledger_seq"] == 13361
    )
    assert isinstance(replayed_snapshot, dict)
    assert replayed_snapshot["available_at"] == _LIVE_13361_AVAILABLE_AT
