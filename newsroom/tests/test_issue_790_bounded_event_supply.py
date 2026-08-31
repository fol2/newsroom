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
STRANDED_AT = datetime(2026, 8, 31, 9, 23, 20, tzinfo=UTC)
STRANDED_TEXT = "2026-08-31T09:23:20.000000Z"
LATER = datetime(2026, 8, 31, 9, 48, 27, tzinfo=UTC)


def _unit(
    number: int,
    *,
    run_id: str,
    observed_at: str | None = None,
    source_id: str = "UK-01",
) -> CorpusIngestUnit:
    observed_at = observed_at or f"2026-08-30T23:2{number}:00.000000Z"
    headline = f"Headline {number}"
    body = f"Body {number}"
    canonical_url = f"https://example.test/{number}"
    identity = EffectiveRevisionIdentity(
        source_id=source_id,
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


def _fixture_fetch(url: str) -> tuple[int, bytes]:
    if "atom" in url:
        return 200, ATOM
    if url.endswith(".xml") or "rss" in url.lower() or "WarningsRSS" in url:
        return 200, RSS
    return 200, JSON_DOC


def _land_units(path: Path, units: tuple[CorpusIngestUnit, ...]) -> None:
    connection = connect(str(path))
    connection.execute("BEGIN IMMEDIATE")
    for unit in units:
        assert emit_effective_revision_landed(
            connection,
            unit.effective_revision,
            published_at=unit.published_at,
            updated_at=unit.updated_at,
            ingest_ids=(unit.ingest_id,),
            landed_at=unit.coverage_first_observed_at,
        )
    connection.commit()
    connection.close()


def _live_shaped_current_run_units(
    *, run_id: str = "run-fresh", observed_at: str = NOW_TEXT
) -> tuple[CorpusIngestUnit, ...]:
    units: list[CorpusIngestUnit] = []
    number = 1
    for source_id, count in (
        ("HK-01", 1),
        ("HK-04", 3),
        ("RAD-01", 20),
        ("RAD-02", 22),
        ("UK-05", 1),
    ):
        for _ in range(count):
            units.append(
                _unit(
                    number,
                    run_id=run_id,
                    observed_at=observed_at,
                    source_id=source_id,
                )
            )
            number += 1
    return tuple(units)


def _retain_stranded_first_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, tuple[CorpusIngestUnit, ...]]:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    _seed_frontier(unpublished)
    retained = run_intake(
        proving_store=str(proving),
        fetch=_fixture_fetch,
        clock=lambda: STRANDED_AT,
    )
    stranded = _live_shaped_current_run_units(
        run_id=retained.proving_run_id, observed_at=STRANDED_TEXT
    )
    assert len({unit.coverage_key() for unit in stranded}) == 47
    old_run = _unit(90, run_id="run-old", observed_at=NOW_TEXT, source_id="AA-00")
    other_timestamp = _unit(
        91, run_id=retained.proving_run_id, source_id="AA-01"
    )
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.run_intake",
        lambda **_: _intake_report("run-later"),
    )
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.load_graphiti_units",
        lambda **_: (*stranded, old_run, other_timestamp),
    )
    return proving, unpublished, stranded


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

    baseline = run_intake(
        proving_store=str(proving),
        fetch=_fixture_fetch,
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
        return _fixture_fetch(url)

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


def test_supply_projects_one_event_from_several_current_run_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    proving.touch()
    _seed_frontier(unpublished)
    later_source = _unit(1, run_id="run-fresh", observed_at=NOW_TEXT, source_id="UK-01")
    middle_source = _unit(2, run_id="run-fresh", observed_at=NOW_TEXT, source_id="UK-02")
    first_by_tuple = _unit(3, run_id="run-fresh", observed_at=NOW_TEXT, source_id="HK-04")
    old_run = _unit(4, run_id="run-old", observed_at=NOW_TEXT, source_id="AA-00")
    other_timestamp = _unit(5, run_id="run-fresh", source_id="AA-01")
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.run_intake",
        lambda **_: _intake_report(),
    )
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.load_graphiti_units",
        lambda **_: (
            later_source,
            middle_source,
            first_by_tuple,
            old_run,
            other_timestamp,
        ),
    )

    result = supply_one_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        expected_frontier_ledger_seq=1,
        clock=lambda: NOW,
    )

    assert result.ledger_seq == 2
    assert result.state == "QUEUED"
    assert result.attempt_count == 0
    assert result.unit_count == 1
    connection = sqlite3.connect(unpublished)
    try:
        assert connection.execute(
            "SELECT source_id,item_key,state,attempt_count,provider_dispatched,"
            "claim_owner FROM unpublished_graphiti_revision_events "
            "WHERE event_id=?",
            (result.event_id,),
        ).fetchone() == ("HK-04", "item-3", "QUEUED", 0, 0, None)
        assert connection.execute(
            "SELECT source_id,item_key FROM unpublished_effective_revision_landed "
            "ORDER BY source_id,item_key"
        ).fetchall() == [("HK-04", "item-3"), ("UK-01", "item-0")]
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_effective_revision_landed"
        ).fetchone() == (2,)
    finally:
        connection.close()


def test_supply_selects_first_key_from_many_current_run_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    proving.touch()
    _seed_frontier(unpublished)
    current = _live_shaped_current_run_units()
    old_run = _unit(90, run_id="run-old", observed_at=NOW_TEXT, source_id="AA-00")
    other_timestamp = _unit(91, run_id="run-fresh", source_id="AA-01")
    assert len({unit.coverage_key() for unit in current}) == 47
    assert {unit.source_id for unit in current} == {
        "HK-01",
        "HK-04",
        "RAD-01",
        "RAD-02",
        "UK-05",
    }
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.run_intake",
        lambda **_: _intake_report(),
    )
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.load_graphiti_units",
        lambda **_: (*current, old_run, other_timestamp),
    )

    result = supply_one_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        expected_frontier_ledger_seq=1,
        clock=lambda: NOW,
    )

    assert result.ledger_seq == 2
    assert result.state == "QUEUED"
    assert result.attempt_count == 0
    assert result.provider_dispatched is False
    assert result.unit_count == 1
    connection = sqlite3.connect(unpublished)
    try:
        assert connection.execute(
            "SELECT source_id,item_key,state,attempt_count,provider_dispatched,"
            "claim_owner,unit_count FROM unpublished_graphiti_revision_events "
            "WHERE event_id=?",
            (result.event_id,),
        ).fetchone() == ("HK-01", "item-1", "QUEUED", 0, 0, None, 1)
        assert connection.execute(
            "SELECT source_id,item_key FROM unpublished_effective_revision_landed "
            "ORDER BY source_id,item_key"
        ).fetchall() == [("HK-01", "item-1"), ("UK-01", "item-0")]
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_effective_revision_landed"
        ).fetchone() == (2,)
    finally:
        connection.close()


def test_supply_selects_stranded_first_seen_key_on_later_empty_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished, stranded = _retain_stranded_first_seen(
        tmp_path, monkeypatch
    )
    keys = sorted({unit.coverage_key() for unit in stranded})

    result = supply_one_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        expected_frontier_ledger_seq=1,
        clock=lambda: LATER,
    )

    assert result.proving_run_id == "run-later"
    assert result.ledger_seq == 2
    assert result.state == "QUEUED"
    assert result.attempt_count == 0
    assert result.provider_dispatched is False
    assert result.claim_owner is None
    assert result.unit_count == 1
    connection = sqlite3.connect(unpublished)
    try:
        assert connection.execute(
            "SELECT source_id,item_key,state,attempt_count,provider_dispatched,"
            "claim_owner,unit_count FROM unpublished_graphiti_revision_events "
            "WHERE event_id=?",
            (result.event_id,),
        ).fetchone() == ("HK-01", "item-1", "QUEUED", 0, 0, None, 1)
        assert connection.execute(
            "SELECT source_id,item_key FROM unpublished_effective_revision_landed "
            "ORDER BY source_id,item_key"
        ).fetchall() == [("HK-01", "item-1"), ("UK-01", "item-0")]
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
        ).fetchone() == (2,)
        landed = {
            (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]))
            for row in connection.execute(
                "SELECT source_id,item_key,revision_digest,published_at,updated_at "
                "FROM unpublished_effective_revision_landed"
            )
        }
        assert set(keys[1:]).isdisjoint(landed)
    finally:
        connection.close()


def test_supply_fails_closed_when_stranded_keys_already_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished, stranded = _retain_stranded_first_seen(
        tmp_path, monkeypatch
    )
    _land_units(unpublished, stranded)

    with pytest.raises(
        BoundedEventSupplyError, match=r"at least one new landed revision \(0\)"
    ):
        supply_one_graphiti_event(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            expected_frontier_ledger_seq=1,
            clock=lambda: LATER,
        )

    events, landed = _rows(unpublished)
    assert events == [(1, "QUEUED", 0, 0, None, None, 1)]
    assert landed == 1 + len({unit.coverage_key() for unit in stranded})


def test_supply_skips_landed_stranded_key_and_selects_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished, stranded = _retain_stranded_first_seen(
        tmp_path, monkeypatch
    )
    keys = sorted({unit.coverage_key() for unit in stranded})
    first = next(unit for unit in stranded if unit.coverage_key() == keys[0])
    second = next(unit for unit in stranded if unit.coverage_key() == keys[1])
    _land_units(unpublished, (first,))

    result = supply_one_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        expected_frontier_ledger_seq=1,
        clock=lambda: LATER,
    )

    assert result.ledger_seq == 2
    assert result.state == "QUEUED"
    assert result.attempt_count == 0
    connection = sqlite3.connect(unpublished)
    try:
        assert connection.execute(
            "SELECT source_id,item_key,state,attempt_count,provider_dispatched,"
            "claim_owner FROM unpublished_graphiti_revision_events "
            "WHERE event_id=?",
            (result.event_id,),
        ).fetchone() == (second.source_id, second.item_key, "QUEUED", 0, 0, None)
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_effective_revision_landed"
        ).fetchone() == (3,)
    finally:
        connection.close()


def test_supply_fails_closed_when_selected_revision_already_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    proving.touch()
    _seed_frontier(unpublished)
    fresh = _unit(1, run_id="run-fresh", observed_at=NOW_TEXT)
    _land_units(unpublished, (fresh,))
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.run_intake",
        lambda **_: _intake_report(),
    )
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_event_supply.load_graphiti_units",
        lambda **_: (fresh,),
    )

    with pytest.raises(BoundedEventSupplyError, match="already landed"):
        supply_one_graphiti_event(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            expected_frontier_ledger_seq=1,
            clock=lambda: NOW,
        )

    assert _rows(unpublished) == (
        [(1, "QUEUED", 0, 0, None, None, 1)],
        2,
    )


def test_supply_full_path_projects_stranded_first_seen_after_later_poll(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    _seed_frontier(unpublished)
    first = run_intake(
        proving_store=str(proving),
        fetch=_fixture_fetch,
        clock=lambda: STRANDED_AT,
    )
    first_units = load_graphiti_units(
        proving_store=str(proving),
        evaluated_at=STRANDED_AT,
    )
    assert first.complete and first.authorised
    keys = sorted({unit.coverage_key() for unit in first_units})
    assert keys
    expected = next(unit for unit in first_units if unit.coverage_key() == keys[0])

    result = supply_one_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        expected_frontier_ledger_seq=1,
        fetch=_fixture_fetch,
        clock=lambda: LATER,
    )

    assert result.ledger_seq == 2
    assert result.state == "QUEUED"
    assert result.attempt_count == 0
    assert result.provider_dispatched is False
    assert result.unit_count == 1
    connection = sqlite3.connect(unpublished)
    try:
        assert connection.execute(
            "SELECT source_id,item_key,state,attempt_count,provider_dispatched,"
            "claim_owner FROM unpublished_graphiti_revision_events "
            "WHERE event_id=?",
            (result.event_id,),
        ).fetchone() == (
            expected.source_id,
            expected.item_key,
            "QUEUED",
            0,
            0,
            None,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM unpublished_effective_revision_landed"
        ).fetchone() == (2,)
        remaining = {
            unit.coverage_key()
            for unit in first_units
            if unit.coverage_key() != keys[0]
        }
        landed = {
            (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]))
            for row in connection.execute(
                "SELECT source_id,item_key,revision_digest,published_at,updated_at "
                "FROM unpublished_effective_revision_landed"
            )
        }
        assert remaining
        assert remaining.isdisjoint(landed)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("report", "units", "message"),
    [
        (_intake_report(), (), r"at least one new landed revision \(0\)"),
        (
            _intake_report(),
            (_unit(1, run_id="run-old", observed_at=NOW_TEXT, source_id="AA-00"),),
            r"at least one new landed revision \(0\)",
        ),
        (
            _intake_report(),
            (_unit(1, run_id="run-fresh", source_id="AA-01"),),
            r"at least one new landed revision \(0\)",
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
def test_supply_fails_closed_without_a_complete_new_revision(
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
