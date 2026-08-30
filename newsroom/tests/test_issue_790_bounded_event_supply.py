from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.cycle import load_graphiti_units
from newsroom.control_plane.graphiti_events import reconcile_graphiti_events
from newsroom.control_plane.intake import IntakeReport, run_intake
from newsroom.control_plane.issue_790_event_supply import (
    BoundedEventSupplyResult,
    BoundedEventSupplyError,
    supply_one_graphiti_event,
)
from newsroom.control_plane.store import connect, emit_effective_revision_landed
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.graphiti_adapter.identity import content_digest
from newsroom.increment9.proving import SOURCE_URLS
from newsroom.tests.test_control_plane_private_beta import ATOM, JSON_DOC, RSS
from scripts import issue_790_conservative_disposition as supply_cli


NOW = datetime(2026, 8, 30, 23, 30, tzinfo=UTC)
NOW_TEXT = "2026-08-30T23:30:00.000000Z"


def _unit(
    number: int, *, run_id: str, observed_at: str | None = None
) -> CorpusIngestUnit:
    observed_at = observed_at or f"2026-08-30T23:2{number}:00.000000Z"
    headline = f"Headline {number}"
    body = f"Body {number}"
    canonical_url = f"https://example.test/{number}"
    identity = EffectiveRevisionIdentity(
        source_id="UK-01",
        item_key=f"item-{number}",
        revision_digest=content_digest(
            headline=headline,
            body=body,
            canonical_url=canonical_url,
        ),
        first_observed_at=observed_at,
    )
    return CorpusIngestUnit(
        source_id=identity.source_id,
        item_key=identity.item_key,
        headline=headline,
        body=body,
        canonical_url=canonical_url,
        observation_digest=f"sha256:observation-{number}",
        observed_at=observed_at,
        proving_run_id=run_id,
        effective_revision=identity,
        source_definition_url="https://example.test/feed",
        effective_pull_first_observed_at=observed_at,
    )


def _intake_report(run_id: str = "run-fresh") -> IntakeReport:
    return IntakeReport(
        proving_run_id=run_id,
        complete=True,
        authorised=True,
        ok=10,
        sources=10,
        health="ACTIVE",
        active=10,
        degraded=0,
        held=0,
        blocked=0,
    )


def _seed_frontier(path: Path) -> None:
    unit = _unit(0, run_id="run-old")
    connection = connect(str(path))
    connection.execute("BEGIN IMMEDIATE")
    assert emit_effective_revision_landed(
        connection,
        unit.effective_revision,
        ingest_ids=(unit.ingest_id,),
        landed_at=unit.coverage_first_observed_at,
    )
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    assert reconcile_graphiti_events(connection, (unit,), available_at=NOW) == 1
    connection.commit()
    connection.close()


def _rows(path: Path) -> tuple[list[tuple[object, ...]], int]:
    connection = sqlite3.connect(path)
    try:
        events = connection.execute(
            "SELECT ledger_seq,state,attempt_count,provider_dispatched,"
            "claim_owner,claim_expires_at,unit_count "
            "FROM unpublished_graphiti_revision_events ORDER BY ledger_seq"
        ).fetchall()
        landed = int(
            connection.execute(
                "SELECT COUNT(*) FROM unpublished_effective_revision_landed"
            ).fetchone()[0]
        )
        return events, landed
    finally:
        connection.close()


def test_supply_intakes_and_projects_only_one_fresh_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    proving.touch()
    _seed_frontier(unpublished)
    fresh = _unit(1, run_id="run-fresh", observed_at=NOW_TEXT)
    old_backlog = _unit(2, run_id="run-fresh")
    intake_calls: list[str] = []

    def intake(**kwargs: object) -> IntakeReport:
        intake_calls.append(str(kwargs["proving_store"]))
        return _intake_report()

    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.run_intake", intake
    )
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.load_graphiti_units",
        lambda **_: (old_backlog, fresh),
    )

    result = supply_one_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        expected_frontier_ledger_seq=1,
        clock=lambda: NOW,
    )

    assert intake_calls == [str(proving)]
    assert result.proving_run_id == "run-fresh"
    assert result.ledger_seq == 2
    assert result.state == "QUEUED"
    assert result.attempt_count == 0
    assert result.provider_dispatched is False
    assert result.claim_owner is None
    assert result.claim_expires_at is None
    assert result.unit_count == 1
    assert _rows(unpublished) == (
        [
            (1, "QUEUED", 0, 0, None, None, 1),
            (2, "QUEUED", 0, 0, None, None, 1),
        ],
        2,
    )


def test_supply_full_path_uses_new_intake_not_existing_backlog(tmp_path: Path) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    baseline_at = NOW.replace(hour=22)

    def baseline_fetch(url: str) -> tuple[int, bytes]:
        if "atom" in url:
            return 200, ATOM
        if url.endswith(".xml") or "rss" in url.lower() or "WarningsRSS" in url:
            return 200, RSS
        return 200, JSON_DOC

    baseline = run_intake(
        proving_store=str(proving),
        fetch=baseline_fetch,
        clock=lambda: baseline_at,
    )
    baseline_units = load_graphiti_units(
        proving_store=str(proving),
        evaluated_at=baseline_at,
    )
    assert all(unit.proving_run_id == baseline.proving_run_id for unit in baseline_units)
    connection = connect(str(unpublished))
    connection.execute("BEGIN IMMEDIATE")
    for unit in baseline_units:
        assert emit_effective_revision_landed(
            connection,
            unit.effective_revision,
            published_at=unit.published_at,
            updated_at=unit.updated_at,
            ingest_ids=(unit.ingest_id,),
            landed_at=unit.coverage_first_observed_at,
        )
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    assert (
        reconcile_graphiti_events(
            connection,
            baseline_units,
            available_at=baseline_at,
        )
        == 10
    )
    connection.commit()
    frontier = int(
        connection.execute(
            "SELECT MAX(ledger_seq) FROM unpublished_graphiti_revision_events"
        ).fetchone()[0]
    )
    connection.close()

    target = SOURCE_URLS["UK-02"]

    def one_change_fetch(url: str) -> tuple[int, bytes]:
        if url == target:
            return (
                200,
                b'{"title":"BNO visa changed","base_path":"/british-national-'
                b'overseas-bno-visa","content_id":"abc","description":"Apply."}',
            )
        return baseline_fetch(url)

    result = supply_one_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        expected_frontier_ledger_seq=frontier,
        fetch=one_change_fetch,
        clock=lambda: NOW,
    )

    assert result.ledger_seq == frontier + 1
    assert result.state == "QUEUED"
    connection = sqlite3.connect(unpublished)
    try:
        assert connection.execute(
            "SELECT source_id,item_key,state,attempt_count,provider_dispatched,"
            "claim_owner FROM unpublished_graphiti_revision_events "
            "WHERE event_id=?",
            (result.event_id,),
        ).fetchone() == ("UK-02", "abc", "QUEUED", 0, 0, None)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("report", "units", "message"),
    [
        (_intake_report(), (), "exactly one new landed revision"),
        (
            _intake_report(),
            (
                _unit(1, run_id="run-fresh", observed_at=NOW_TEXT),
                _unit(2, run_id="run-fresh", observed_at=NOW_TEXT),
            ),
            "exactly one new landed revision",
        ),
        (
            IntakeReport(
                proving_run_id="run-fresh",
                complete=False,
                authorised=True,
                ok=9,
                sources=10,
                health="DEGRADED",
                active=9,
                degraded=1,
                held=0,
                blocked=0,
            ),
            (_unit(1, run_id="run-fresh", observed_at=NOW_TEXT),),
            "complete and authorised",
        ),
    ],
)
def test_supply_fails_closed_without_exactly_one_complete_new_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report: IntakeReport,
    units: tuple[CorpusIngestUnit, ...],
    message: str,
) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    proving.touch()
    _seed_frontier(unpublished)
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.run_intake",
        lambda **_: report,
    )
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.load_graphiti_units",
        lambda **_: units,
    )

    with pytest.raises(BoundedEventSupplyError, match=message):
        supply_one_graphiti_event(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            expected_frontier_ledger_seq=1,
            clock=lambda: NOW,
        )

    assert _rows(unpublished) == (
        [(1, "QUEUED", 0, 0, None, None, 1)],
        1,
    )


def test_registered_cli_binds_frontier_and_has_no_consumer_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    observed_at = "2026-08-30T23:30:00+00:00"
    calls: list[dict[str, object]] = []

    def supply(**kwargs: object) -> BoundedEventSupplyResult:
        calls.append(kwargs)
        return BoundedEventSupplyResult(
            proving_run_id="run-fresh",
            event_id="sha256:event",
            ledger_seq=13363,
            state="QUEUED",
            attempt_count=0,
            provider_dispatched=False,
            claim_owner=None,
            claim_expires_at=None,
            unit_count=1,
        )

    monkeypatch.setattr(supply_cli, "supply_one_graphiti_event", supply)
    assert (
        supply_cli.main(
            [
                "supply-event",
                "--proving-store",
                str(proving),
                "--store",
                str(unpublished),
                "--expected-frontier-ledger-seq",
                "13362",
                "--observed-at",
                observed_at,
            ]
        )
        == 0
    )
    assert calls == [
        {
            "proving_store": str(proving),
            "unpublished_store": str(unpublished),
            "expected_frontier_ledger_seq": 13362,
            "clock": calls[0]["clock"],
        }
    ]
    assert calls[0]["clock"]() == NOW
    assert '"ledger_seq": 13363' in capsys.readouterr().out

    sources = inspect.getsource(
        __import__(
            "newsroom.control_plane.issue_790_event_supply", fromlist=["*"]
        )
    ) + inspect.getsource(supply_cli._supply_event)
    for forbidden in (
        "GraphitiEventQueue",
        "consume_next_graphiti_event",
        "run_cycle(",
        ".health(",
        ".claim(",
        "hermes_graphiti_worker",
        "hermes_control_plane",
    ):
        assert forbidden not in sources


def test_supply_rejects_aliased_stores_before_intake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "unpublished_store.sqlite3"
    store.touch()
    invoked = False

    def intake(**_: object) -> IntakeReport:
        nonlocal invoked
        invoked = True
        return _intake_report()

    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.run_intake", intake
    )
    with pytest.raises(BoundedEventSupplyError, match="must be distinct"):
        supply_one_graphiti_event(
            proving_store=str(store),
            unpublished_store=str(store),
            expected_frontier_ledger_seq=1,
            clock=lambda: NOW,
        )
    assert invoked is False
