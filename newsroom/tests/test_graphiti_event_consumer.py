from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.cycle import consume_next_graphiti_event, run_cycle
from newsroom.control_plane.graphiti import GraphitiCycleResult
from newsroom.control_plane.graphiti_events import (
    GraphitiDispatchGate,
    GraphitiDispatchResult,
    GraphitiEventQueue,
    SystemicGraphitiEventFailure,
    ensure_graphiti_event_schema,
    reconcile_graphiti_events,
)
from newsroom.control_plane.store import connect, emit_effective_revision_landed
from newsroom.control_plane.writer import FixtureWriter
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.graphiti_adapter.identity import MAX_EPISODE_BYTES, content_digest
from newsroom.tests.test_control_plane_private_beta import _proving
from newsroom.tests.test_graphiti_corpus_ingest import _complete, _with_provider_attempt


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _unit(number: int, *, source_id: str = "UK-01") -> CorpusIngestUnit:
    observed_at = f"2026-08-24T00:00:0{number}.000000Z"
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
        proving_run_id="run-1",
        effective_revision=identity,
        source_definition_url="https://example.test/feed",
        effective_pull_first_observed_at=observed_at,
    )


def _enqueue_fixture(
    path: Path,
    units: tuple[CorpusIngestUnit, ...],
    *,
    available_at: datetime,
) -> int:
    connection = connect(str(path))
    connection.execute("BEGIN IMMEDIATE")
    for unit in units:
        emit_effective_revision_landed(
            connection,
            unit.effective_revision,
            published_at=unit.published_at,
            updated_at=unit.updated_at,
            ingest_ids=(unit.ingest_id,),
            landed_at=unit.coverage_first_observed_at,
        )
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    inserted = reconcile_graphiti_events(connection, units, available_at=available_at)
    connection.commit()
    connection.close()
    return inserted


def test_committed_events_are_immediately_claimable_and_recover_after_restart(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 1, tzinfo=UTC))
    path = tmp_path / "unpublished.sqlite3"
    queue = GraphitiEventQueue(str(path), clock=clock)

    assert (
        _enqueue_fixture(path, (_unit(1), _unit(2), _unit(3)), available_at=clock.value)
        == 3
    )
    first = queue.claim(owner_id="worker-a", lease_for=timedelta(seconds=30))

    assert first is not None
    assert first.item_key == "item-1"
    assert queue.health().state_counts == {
        "QUEUED": 2,
        "CLAIMED": 1,
        "RUNNING": 0,
        "RETRY_HELD": 0,
        "RIGHTS_HELD": 0,
        "DEAD_LETTER": 0,
        "TERMINAL": 0,
    }

    restarted = GraphitiEventQueue(str(path), clock=clock)
    second = restarted.claim(owner_id="worker-b", lease_for=timedelta(seconds=30))
    assert second is not None
    assert second.item_key == "item-2"

    clock.value += timedelta(seconds=31)
    recovered_health = restarted.health()
    assert recovered_health.state_counts["CLAIMED"] == 0
    assert recovered_health.state_counts["QUEUED"] == 3
    recovered = restarted.claim(owner_id="worker-c", lease_for=timedelta(seconds=30))
    assert recovered is not None
    assert recovered.item_key == "item-1"


def test_landed_record_and_queue_event_roll_back_together(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    unit = _unit(1)
    connection = connect(str(path))
    ensure_graphiti_event_schema(connection)
    connection.execute("BEGIN IMMEDIATE")
    emit_effective_revision_landed(connection, unit.effective_revision)
    connection.rollback()
    connection.close()

    reopened = connect(str(path))
    assert (
        reopened.execute(
            "SELECT COUNT(*) FROM unpublished_effective_revision_landed"
        ).fetchone()[0]
        == 0
    )
    reopened.close()
    assert GraphitiEventQueue(str(path)).health().eligible_revision_count == 0


def test_zero_proposal_result_is_terminal_revision_coverage(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 1, tzinfo=UTC))
    queue = GraphitiEventQueue(str(tmp_path / "unpublished.sqlite3"), clock=clock)
    _enqueue_fixture(
        tmp_path / "unpublished.sqlite3", (_unit(1),), available_at=clock.value
    )

    result = queue.process_one(
        owner_id="worker",
        gate=lambda _event: GraphitiDispatchGate.allow(),
        dispatch=lambda _event: GraphitiDispatchResult.terminal(
            proposal_count=0, provider_dispatched=True
        ),
    )

    assert result is not None
    assert result.state == "TERMINAL"
    health = queue.health()
    assert health.state_counts["TERMINAL"] == 1
    assert health.eligible_revision_count == 1
    assert health.terminal_revision_count == 1
    assert health.terminal_coverage_percent == 100.0
    assert health.queue_depth == 0
    assert health.arrival_velocity_per_hour == 1.0
    assert health.service_velocity_per_hour == 1.0
    assert health.contiguous_coverage_watermark == result.ledger_seq


def test_oldest_unresolved_lag_uses_effective_landing_not_ledger_order(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 10, tzinfo=UTC))
    path = tmp_path / "unpublished.sqlite3"
    _enqueue_fixture(path, (_unit(2), _unit(1)), available_at=clock.value)

    health = GraphitiEventQueue(str(path), clock=clock).health()

    assert health.oldest_unresolved_lag_seconds == 599


def test_rights_hold_does_not_block_another_qualified_source(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 1, tzinfo=UTC))
    queue = GraphitiEventQueue(str(tmp_path / "unpublished.sqlite3"), clock=clock)
    _enqueue_fixture(
        tmp_path / "unpublished.sqlite3",
        (_unit(1, source_id="HELD"), _unit(2, source_id="OPEN")),
        available_at=clock.value,
    )

    held = queue.process_one(
        owner_id="worker",
        gate=lambda event: (
            GraphitiDispatchGate.hold("RIGHTS_LOST")
            if event.source_id == "HELD"
            else GraphitiDispatchGate.allow()
        ),
        dispatch=lambda _event: GraphitiDispatchResult.terminal(
            proposal_count=0, provider_dispatched=False
        ),
        hold_for=timedelta(minutes=5),
    )
    completed = queue.process_one(
        owner_id="worker",
        gate=lambda _event: GraphitiDispatchGate.allow(),
        dispatch=lambda _event: GraphitiDispatchResult.terminal(
            proposal_count=1, provider_dispatched=True
        ),
    )

    assert held is not None and held.state == "RIGHTS_HELD"
    assert completed is not None and completed.state == "TERMINAL"
    assert queue.health().state_counts["RIGHTS_HELD"] == 1


def test_systemic_failure_opens_circuit_without_walking_later_events(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 1, tzinfo=UTC))
    queue = GraphitiEventQueue(str(tmp_path / "unpublished.sqlite3"), clock=clock)
    _enqueue_fixture(
        tmp_path / "unpublished.sqlite3",
        (_unit(1), _unit(2), _unit(3)),
        available_at=clock.value,
    )

    failed = queue.process_one(
        owner_id="worker",
        gate=lambda _event: GraphitiDispatchGate.allow(),
        dispatch=lambda _event: (_ for _ in ()).throw(
            SystemicGraphitiEventFailure("ROUTE_UNAVAILABLE")
        ),
        retry_after=timedelta(seconds=10),
        circuit_for=timedelta(minutes=1),
    )

    assert failed is not None and failed.state == "RETRY_HELD"
    assert (
        queue.process_one(
            owner_id="worker",
            gate=lambda _event: GraphitiDispatchGate.allow(),
            dispatch=lambda _event: GraphitiDispatchResult.terminal(
                proposal_count=1, provider_dispatched=True
            ),
        )
        is None
    )
    health = queue.health()
    assert health.circuit_open is True
    assert health.state_counts["QUEUED"] == 2
    assert health.state_counts["RETRY_HELD"] == 1
    assert health.terminal_revision_count == 0
    for expected_attempt in range(2, 5):
        clock.value += timedelta(minutes=1, seconds=1)
        repeated = queue.process_one(
            owner_id="worker",
            gate=lambda _event: GraphitiDispatchGate.allow(),
            dispatch=lambda _event: (_ for _ in ()).throw(
                SystemicGraphitiEventFailure("ROUTE_UNAVAILABLE")
            ),
            retry_after=timedelta(seconds=10),
            circuit_for=timedelta(minutes=1),
            max_attempts=3,
        )
        assert repeated is not None
        assert repeated.state == "RETRY_HELD"
        assert repeated.attempt_count == expected_attempt
    repeated_health = queue.health()
    assert repeated_health.state_counts["QUEUED"] == 2
    assert repeated_health.state_counts["RETRY_HELD"] == 1
    assert repeated_health.state_counts["DEAD_LETTER"] == 0


def test_repeated_failure_becomes_dead_letter_without_event_loss(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 1, tzinfo=UTC))
    queue = GraphitiEventQueue(str(tmp_path / "unpublished.sqlite3"), clock=clock)
    _enqueue_fixture(
        tmp_path / "unpublished.sqlite3", (_unit(1),), available_at=clock.value
    )

    states: list[str] = []
    for _ in range(3):
        result = queue.process_one(
            owner_id="worker",
            gate=lambda _event: GraphitiDispatchGate.allow(),
            dispatch=lambda _event: GraphitiDispatchResult.retry_held(
                failure_code="PROVIDER_FAILURE", provider_dispatched=True
            ),
            retry_after=timedelta(seconds=1),
            max_attempts=3,
        )
        assert result is not None
        states.append(result.state)
        clock.value += timedelta(seconds=1)

    assert states == ["RETRY_HELD", "RETRY_HELD", "DEAD_LETTER"]
    health = queue.health()
    assert health.eligible_revision_count == 1
    assert health.state_counts["DEAD_LETTER"] == 1
    assert health.terminal_revision_count == 0


def test_burst_health_reports_partial_then_contiguous_full_coverage(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 1, tzinfo=UTC))
    queue = GraphitiEventQueue(str(tmp_path / "unpublished.sqlite3"), clock=clock)
    _enqueue_fixture(
        tmp_path / "unpublished.sqlite3",
        (_unit(1), _unit(2), _unit(3)),
        available_at=clock.value,
    )

    def process() -> None:
        result = queue.process_one(
            owner_id="worker",
            gate=lambda _event: GraphitiDispatchGate.allow(),
            dispatch=lambda _event: GraphitiDispatchResult.terminal(
                proposal_count=0, provider_dispatched=False
            ),
        )
        assert result is not None

    process()
    partial = queue.health()
    assert partial.queue_depth == 2
    assert partial.terminal_coverage_percent == 100 / 3
    process()
    process()
    complete = queue.health()
    assert complete.queue_depth == 0
    assert complete.terminal_coverage_percent == 100.0
    assert complete.contiguous_coverage_watermark is not None


def test_control_plane_cycle_atomically_enqueues_without_dispatching(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished.sqlite3"

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )
    queue = GraphitiEventQueue(str(unpublished), clock=clock)
    first_health = queue.health()

    assert first_health.eligible_revision_count == report.effective_pull_count
    assert first_health.state_counts["QUEUED"] == report.effective_pull_count

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )
    assert queue.health().eligible_revision_count == report.effective_pull_count


def test_independent_fixture_consumer_drains_burst_to_full_coverage(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished.sqlite3"
    calls: list[str] = []

    class FixtureGraphiti:
        def ingest(self, unit: CorpusIngestUnit):
            calls.append(unit.ingest_id)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )
    for index in range(report.effective_pull_count):
        result = consume_next_graphiti_event(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            graphiti=FixtureGraphiti(),
            owner_id=f"fixture-worker-{index}",
            clock=clock,
        )
        assert result is not None and result.state == "TERMINAL"

    health = GraphitiEventQueue(str(unpublished), clock=clock).health()
    assert health.terminal_revision_count == report.effective_pull_count
    assert health.terminal_coverage_percent == 100.0
    assert len(calls) == len(set(calls)) == report.effective_pull_count
    retained = sqlite3.connect(unpublished)
    manifests = retained.execute(
        "SELECT unit_count,manifest_json FROM unpublished_graphiti_revision_events"
    ).fetchall()
    retained.close()
    assert all(int(row[0]) > 0 for row in manifests)
    assert all(json.loads(str(row[1]))["unit_refs"] for row in manifests)


def test_projection_denominator_includes_landed_revision_without_input(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    ensure_graphiti_event_schema(connection)
    connection.execute("BEGIN IMMEDIATE")
    emit_effective_revision_landed(connection, _unit(1).effective_revision)
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    assert (
        reconcile_graphiti_events(
            connection,
            (),
            available_at=datetime(2026, 8, 24, 0, 1, tzinfo=UTC),
        )
        == 1
    )
    connection.commit()
    connection.close()

    queue = GraphitiEventQueue(str(path))
    health = queue.health()
    assert health.eligible_revision_count == 1
    assert health.terminal_coverage_percent == 0.0
    proving = _proving(tmp_path)

    class MustNotDispatch:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError(f"missing input reached provider: {unit.ingest_id}")

    result = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(path),
        graphiti=MustNotDispatch(),
        owner_id="worker",
    )
    assert result is not None and result.state == "RIGHTS_HELD"
    held = queue.health()
    assert held.terminal_coverage_percent == 0.0
    assert held.state_counts["RIGHTS_HELD"] == 1


def test_corrupt_object_is_dead_lettered_without_blocking_later_event(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    queue = GraphitiEventQueue(str(path))
    _enqueue_fixture(
        path,
        (_unit(1), _unit(2)),
        available_at=datetime(2026, 8, 24, 0, 1, tzinfo=UTC),
    )
    connection = sqlite3.connect(path)
    first_id = str(
        connection.execute(
            "SELECT event_id FROM unpublished_graphiti_revision_events "
            "ORDER BY ledger_seq LIMIT 1"
        ).fetchone()[0]
    )
    connection.execute(
        "UPDATE unpublished_graphiti_revision_events SET manifest_digest=? "
        "WHERE event_id=?",
        ("sha256:" + "0" * 64, first_id),
    )
    connection.commit()
    connection.close()

    claimed = queue.claim(owner_id="worker", lease_for=timedelta(seconds=30))

    assert claimed is not None and claimed.item_key == "item-2"
    health = queue.health()
    assert health.state_counts["DEAD_LETTER"] == 1
    assert health.contiguous_coverage_watermark is None


def test_resolved_ingest_identity_must_match_landed_obligation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    unit = _unit(1)
    connection = connect(str(path))
    connection.execute("BEGIN IMMEDIATE")
    emit_effective_revision_landed(
        connection,
        unit.effective_revision,
        ingest_ids=("sha256:historical-configuration-ingest",),
    )
    connection.commit()
    queue = GraphitiEventQueue(str(path))
    queue.health()
    dispatched = False

    def gate(event):
        queue.bind_resolved_units(event, owner_id="worker", units=(unit,))
        return GraphitiDispatchGate.allow()

    def dispatch(_event):
        nonlocal dispatched
        dispatched = True
        return GraphitiDispatchResult.terminal(
            proposal_count=0, provider_dispatched=False
        )

    result = queue.process_one(
        owner_id="worker",
        gate=gate,
        dispatch=dispatch,
    )

    assert result is not None and result.state == "RETRY_HELD"
    assert dispatched is False


def test_independent_consumer_drains_four_ordered_chunks_in_one_event_attempt(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving = _proving(tmp_path)
    long_body = "x" * (MAX_EPISODE_BYTES * 3 + 128)
    raw = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel><item><guid>hk-1</guid>'
        "<title>Long fixture</title><link>https://www.news.gov.hk/a</link>"
        f"<description>{long_body}</description></item></channel></rss>"
    ).encode()
    proving_connection = sqlite3.connect(proving)
    proving_connection.execute(
        "DELETE FROM proving_observations WHERE source_id!='HK-01'"
    )
    proving_connection.execute(
        "UPDATE proving_observations SET body=?,body_digest=? WHERE source_id='HK-01'",
        (raw, digest_bytes(raw)),
    )
    proving_connection.commit()
    proving_connection.close()
    unpublished = tmp_path / "four-chunks.sqlite3"
    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )
    calls: list[str] = []

    class FixtureGraphiti:
        def ingest(self, unit: CorpusIngestUnit):
            calls.append(unit.ingest_id)
            return _complete(unit)

    result = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=FixtureGraphiti(),
        owner_id="fixture-worker",
        clock=clock,
    )

    assert result is not None and result.state == "TERMINAL"
    assert result.attempt_count == 1
    assert len(calls) == 4


def test_actual_transport_failure_opens_systemic_circuit(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished.sqlite3"
    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )

    class UnavailableGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise OSError("route unavailable")

    result = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=UnavailableGraphiti(),
        owner_id="fixture-worker",
        clock=clock,
    )

    assert result is not None and result.state == "RETRY_HELD"
    health = GraphitiEventQueue(str(unpublished), clock=clock).health()
    assert health.circuit_open is True
    assert health.state_counts["QUEUED"] == health.eligible_revision_count - 1
    for _ in range(3):
        clock.value += timedelta(minutes=6)
        repeated = consume_next_graphiti_event(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            graphiti=UnavailableGraphiti(),
            owner_id="fixture-worker",
            clock=clock,
        )
        assert repeated is not None and repeated.state == "RETRY_HELD"
    repeated_health = GraphitiEventQueue(str(unpublished), clock=clock).health()
    assert repeated_health.state_counts["QUEUED"] == (
        repeated_health.eligible_revision_count - 1
    )
    assert repeated_health.state_counts["DEAD_LETTER"] == 0
    connection = sqlite3.connect(unpublished)
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_failures"
        ).fetchone()[0]
        == 0
    )
    connection.close()


def test_result_shaped_setup_failure_opens_systemic_circuit(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished.sqlite3"
    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )

    class SetupFailureGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            result = replace(
                _complete(unit),
                outcome="RETRYABLE_FAILURE",
                failure_code="PRODUCER_INTERNAL_ERROR",
            )
            raw = dict(result.raw_receipt or {})
            raw["dispatch_state"] = "NOT_DISPATCHED"
            raw["setup_failure"] = "BrokerError"
            raw.pop("raw_output_digest", None)
            raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
            return replace(
                result,
                receipt_digest=str(raw["raw_output_digest"]),
                raw_receipt=raw,
            )

    result = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=SetupFailureGraphiti(),
        owner_id="fixture-worker",
        clock=clock,
    )

    assert result is not None and result.state == "RETRY_HELD"
    health = GraphitiEventQueue(str(unpublished), clock=clock).health()
    assert health.circuit_open is True
    assert health.state_counts["QUEUED"] == health.eligible_revision_count - 1


def test_current_rights_run_can_hydrate_prior_landed_manifest(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished.sqlite3"
    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )

    class RetainRunOneManifest:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            return replace(
                _complete(unit),
                outcome="RETRYABLE_FAILURE",
                failure_code="FIXTURE_RETRYABLE",
            )

    first = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=RetainRunOneManifest(),
        owner_id="run-one-worker",
        clock=clock,
    )
    assert first is not None and first.state == "RETRY_HELD"
    retained = sqlite3.connect(unpublished)
    assert (
        retained.execute(
            "SELECT unit_count FROM unpublished_graphiti_revision_events "
            "WHERE event_id=?",
            (first.event_id,),
        ).fetchone()[0]
        == 1
    )
    retained.close()
    clock.value += timedelta(seconds=31)
    proving_connection = sqlite3.connect(proving)
    for table in (
        "proving_observations",
        "proving_gates",
        "proving_rights_packets",
        "proving_runs",
    ):
        proving_connection.execute(
            f"UPDATE {table} SET run_id='run-2' WHERE run_id='run-1'"
        )
    proving_connection.commit()
    proving_connection.close()
    calls: list[str] = []

    class CurrentRunGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            assert unit.proving_run_id == "run-2"
            calls.append(unit.ingest_id)
            return _complete(unit)

    result = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=CurrentRunGraphiti(),
        owner_id="fixture-worker",
        clock=clock,
    )

    assert result is not None and result.state == "TERMINAL"
    assert len(calls) == 1


def test_restart_after_provider_effect_recovers_marker_without_duplicate_effect(
    tmp_path: Path,
) -> None:
    class ProcessDeath(BaseException):
        pass

    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished.sqlite3"
    proving_connection = sqlite3.connect(proving)
    proving_connection.execute(
        "DELETE FROM proving_observations WHERE source_id!='HK-01'"
    )
    proving_connection.commit()
    proving_connection.close()
    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )
    effects: list[str] = []

    class DiesAfterEffect:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            effects.append(unit.ingest_id)
            raise ProcessDeath

    try:
        consume_next_graphiti_event(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            graphiti=DiesAfterEffect(),
            owner_id="worker-before-death",
            clock=clock,
        )
    except ProcessDeath:
        pass
    else:
        raise AssertionError("fixture process death did not escape")

    clock.value += timedelta(minutes=16)

    class MarkerRecovery:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            assert unit.ingest_id == effects[0]
            return _with_provider_attempt(
                _complete(unit),
                1,
                recovery=True,
            )

    recovered = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=MarkerRecovery(),
        owner_id="worker-after-restart",
        clock=clock,
    )

    assert recovered is not None and recovered.state == "TERMINAL"
    assert len(effects) == 1
    assert (
        GraphitiEventQueue(str(unpublished), clock=clock)
        .health()
        .terminal_revision_count
        == 1
    )
