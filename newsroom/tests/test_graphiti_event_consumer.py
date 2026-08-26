from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.cycle import consume_next_graphiti_event, run_cycle
from newsroom.control_plane.graphiti import GraphitiCycleResult
from newsroom.control_plane.graphiti_events import (
    ConfigurationGraphitiEventFailure,
    GraphitiDispatchGate,
    GraphitiDispatchResult,
    GraphitiEventQueue,
    SystemicGraphitiEventFailure,
    ensure_graphiti_event_schema,
    reconcile_graphiti_events,
)
from newsroom.control_plane.model_usage import ModelUsageService
from newsroom.control_plane.store import (
    EFFECTIVE_REVISION_LANDED,
    append_ledger,
    connect,
    emit_effective_revision_landed,
)
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


def _predispatch_refusal(unit: CorpusIngestUnit) -> GraphitiCycleResult:
    result = replace(
        _complete(unit),
        outcome="RETRYABLE_FAILURE",
        failure_code="PRODUCER_INTERNAL_ERROR",
        chat_invocations=(
            {
                "provider": "cursor-agent-cli",
                "outcome": "PREDISPATCH_REFUSED",
                "usage": {
                    "usage_basis": "NO_PROVIDER_CALL",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_read_tokens": 0,
                    "cached_write_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                },
            },
        ),
        embedding_usage={
            "usage_basis": "NO_EMBEDDING_CALL",
            "request_count": 0,
            "embedding_tokens": 0,
            "cost_usd_microunits": 0,
            "requests": [],
        },
    )
    raw = dict(result.raw_receipt or {})
    raw["chat_invocations"] = list(result.chat_invocations)
    raw["chat_invocation_count"] = len(result.chat_invocations)
    raw["embedding_usage"] = result.embedding_usage
    raw["producer_failure"] = "CliPredispatchRefusal"
    raw.pop("raw_output_digest", None)
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    return replace(
        result,
        receipt_digest=str(raw["raw_output_digest"]),
        raw_receipt=raw,
    )


def _insert_legacy_landed(path: Path, unit: CorpusIngestUnit) -> tuple[str, str]:
    payload = {
        "source_id": unit.source_id,
        "item_key": unit.item_key,
        "revision_digest": unit.revision_digest,
        "first_observed_at": unit.coverage_first_observed_at,
    }
    payload_digest = digest_canonical(payload)
    connection = connect(str(path))
    ledger_digest = append_ledger(connection, EFFECTIVE_REVISION_LANDED, payload)
    connection.execute(
        """
        INSERT INTO unpublished_effective_revision_landed(
            source_id,item_key,revision_digest,published_at,updated_at,
            first_observed_at,ingest_ids_json,legacy_v10,payload_digest,
            ledger_digest,at
        ) VALUES(?,?,?,'','',?,'[]',1,?,?,?)
        """,
        (
            unit.source_id,
            unit.item_key,
            unit.revision_digest,
            unit.coverage_first_observed_at,
            payload_digest,
            ledger_digest,
            unit.coverage_first_observed_at,
        ),
    )
    connection.commit()
    connection.close()
    return ledger_digest, payload_digest


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
        "CONFIGURATION_HELD": 0,
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


def test_exact_fresh_claim_never_falls_through_to_another_or_touched_event(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 1, tzinfo=UTC))
    path = tmp_path / "unpublished.sqlite3"
    assert (
        _enqueue_fixture(path, (_unit(1), _unit(2), _unit(3)), available_at=clock.value)
        == 3
    )
    connection = connect(str(path))
    identities = {
        str(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT item_key,event_id FROM unpublished_graphiti_revision_events"
        )
    }
    connection.execute(
        "UPDATE unpublished_graphiti_revision_events SET state='RETRY_HELD',"
        "attempt_count=1 WHERE event_id=?",
        (identities["item-1"],),
    )
    connection.execute(
        "UPDATE unpublished_graphiti_revision_events SET state='CLAIMED',"
        "claim_owner='other-worker',claim_expires_at=? WHERE event_id=?",
        (
            (clock.value - timedelta(seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            identities["item-2"],
        ),
    )
    connection.commit()
    connection.close()
    queue = GraphitiEventQueue(str(path), clock=clock)

    with pytest.raises(ValueError, match="exact event identity"):
        queue.claim(
            owner_id="canary",
            lease_for=timedelta(seconds=30),
            require_fresh=True,
        )
    assert (
        queue.claim(
            owner_id="canary",
            lease_for=timedelta(seconds=30),
            event_id=identities["item-1"],
            require_fresh=True,
        )
        is None
    )
    selected = queue.claim(
        owner_id="canary",
        lease_for=timedelta(seconds=30),
        event_id=identities["item-3"],
        require_fresh=True,
    )

    assert selected is not None
    assert selected.item_key == "item-3"
    retained = sqlite3.connect(path)
    states = dict(
        retained.execute(
            "SELECT item_key,state FROM unpublished_graphiti_revision_events"
        )
    )
    retained.close()
    assert states == {
        "item-1": "RETRY_HELD",
        "item-2": "CLAIMED",
        "item-3": "CLAIMED",
    }


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


def test_projection_rejects_landed_payload_not_authorised_by_ledger(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    unit = _unit(1)
    connection = connect(str(path))
    connection.execute("BEGIN IMMEDIATE")
    emit_effective_revision_landed(
        connection,
        unit.effective_revision,
        ingest_ids=(unit.ingest_id,),
        landed_at=unit.coverage_first_observed_at,
    )
    connection.commit()
    forged_payload = {
        "source_id": unit.source_id,
        "item_key": "forged",
        "revision_digest": unit.effective_revision.revision_digest,
        "published_at": unit.published_at,
        "updated_at": unit.updated_at,
        "first_observed_at": unit.coverage_first_observed_at,
        "ingest_ids": [unit.ingest_id],
    }
    connection.execute(
        "UPDATE unpublished_effective_revision_landed "
        "SET item_key=?,payload_digest=?",
        ("forged", digest_bytes(canonical_json_bytes(forged_payload))),
    )
    connection.commit()
    connection.close()
    queue = GraphitiEventQueue(str(path))
    dispatched = False

    def dispatch(_event):
        nonlocal dispatched
        dispatched = True
        return GraphitiDispatchResult.terminal(
            proposal_count=0, provider_dispatched=False
        )

    try:
        queue.process_one(
            owner_id="worker",
            gate=lambda _event: GraphitiDispatchGate.allow(),
            dispatch=dispatch,
        )
    except ValueError as exc:
        assert str(exc) == "landed Graphiti payload digest differs from ledger"
    else:
        raise AssertionError("forged landed payload was projected")

    assert dispatched is False
    retained = sqlite3.connect(path)
    assert (
        retained.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
        ).fetchone()[0]
        == 0
    )
    retained.close()


def test_projection_validates_exact_legacy_v10_landed_payload(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    unit = _unit(1)
    ledger_digest, payload_digest = _insert_legacy_landed(path, unit)

    event = GraphitiEventQueue(str(path)).claim(
        owner_id="worker", lease_for=timedelta(seconds=30)
    )

    assert event is not None
    assert event.event_id == ledger_digest
    assert event.published_at == ""
    assert event.updated_at == ""
    assert event.landed_ingest_ids == ()
    assert event.landed_payload_digest == payload_digest


@pytest.mark.parametrize(
    ("legacy_v10", "published_at", "updated_at", "ingest_ids_json"),
    (
        (1, "2099-01-01T00:00:00Z", "", "[]"),
        (1, "", "2099-01-01T00:00:00Z", "[]"),
        (1, "", "", '["forged-ingest"]'),
        (0.5, "", "", "[]"),
        (2, "", "", "[]"),
    ),
)
def test_projection_rejects_malformed_legacy_v10_metadata(
    tmp_path: Path,
    legacy_v10: object,
    published_at: str,
    updated_at: str,
    ingest_ids_json: str,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    _insert_legacy_landed(path, _unit(1))
    connection = connect(str(path))
    connection.execute(
        "UPDATE unpublished_effective_revision_landed "
        "SET legacy_v10=?,published_at=?,updated_at=?,ingest_ids_json=?",
        (legacy_v10, published_at, updated_at, ingest_ids_json),
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="landed Graphiti .*malformed"):
        GraphitiEventQueue(str(path)).claim(
            owner_id="worker", lease_for=timedelta(seconds=30)
        )

    retained = sqlite3.connect(path)
    assert (
        retained.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
        ).fetchone()[0]
        == 0
    )
    retained.close()


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


def test_v12_event_state_check_migrates_without_losing_queue_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    now = datetime(2026, 8, 24, 0, 1, tzinfo=UTC)
    _enqueue_fixture(path, (_unit(1),), available_at=now)
    legacy = sqlite3.connect(path)
    table_sql = str(
        legacy.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='unpublished_graphiti_revision_events'"
        ).fetchone()[0]
    )
    legacy_sql = table_sql.replace(
        "CREATE TABLE unpublished_graphiti_revision_events",
        "CREATE TABLE unpublished_graphiti_revision_events_v12_fixture",
        1,
    ).replace("'CONFIGURATION_HELD',", "", 1)
    assert "CONFIGURATION_HELD" not in legacy_sql
    legacy.execute("DROP INDEX idx_graphiti_revision_events_claim")
    legacy.execute(legacy_sql)
    legacy.execute(
        "INSERT INTO unpublished_graphiti_revision_events_v12_fixture "
        "SELECT * FROM unpublished_graphiti_revision_events"
    )
    legacy.execute("DROP TABLE unpublished_graphiti_revision_events")
    legacy.execute(
        "ALTER TABLE unpublished_graphiti_revision_events_v12_fixture "
        "RENAME TO unpublished_graphiti_revision_events"
    )
    legacy.execute(
        "CREATE INDEX idx_graphiti_revision_events_claim ON "
        "unpublished_graphiti_revision_events(state,available_at,ledger_seq)"
    )
    legacy.commit()
    legacy.close()

    migrated = connect(str(path))
    assert migrated.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
    ).fetchone() == (1,)
    migrated.execute(
        "UPDATE unpublished_graphiti_revision_events SET state='CONFIGURATION_HELD'"
    )
    migrated.commit()
    schema = str(
        migrated.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='unpublished_graphiti_revision_events'"
        ).fetchone()[0]
    )
    migrated.close()
    assert "CONFIGURATION_HELD" in schema


def test_configuration_failure_is_held_after_one_attempt_without_retry(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 24, 0, 1, tzinfo=UTC))
    path = tmp_path / "unpublished.sqlite3"
    queue = GraphitiEventQueue(str(path), clock=clock)
    _enqueue_fixture(path, (_unit(1), _unit(2)), available_at=clock.value)

    first = queue.process_one(
        owner_id="worker",
        gate=lambda _event: GraphitiDispatchGate.allow(),
        dispatch=lambda _event: (_ for _ in ()).throw(
            ConfigurationGraphitiEventFailure(
                "CLI_PREDISPATCH_CONFIGURATION_REFUSED",
                provider_dispatched=False,
            )
        ),
        circuit_for=timedelta(seconds=1),
    )

    assert first is not None
    assert first.state == "CONFIGURATION_HELD"
    assert first.attempt_count == 1
    clock.value += timedelta(seconds=2)
    second = queue.process_one(
        owner_id="worker",
        gate=lambda _event: GraphitiDispatchGate.allow(),
        dispatch=lambda _event: GraphitiDispatchResult.terminal(
            proposal_count=0, provider_dispatched=False
        ),
    )
    assert second is not None and second.event_id != first.event_id
    retained = sqlite3.connect(path)
    held = retained.execute(
        "SELECT state,attempt_count,provider_dispatched,last_failure_code "
        "FROM unpublished_graphiti_revision_events WHERE event_id=?",
        (first.event_id,),
    ).fetchone()
    retained.close()
    assert held == (
        "CONFIGURATION_HELD",
        1,
        0,
        "CLI_PREDISPATCH_CONFIGURATION_REFUSED",
    )
    health = queue.health()
    assert health.state_counts["CONFIGURATION_HELD"] == 1
    assert health.state_counts["DEAD_LETTER"] == 0
    assert health.queue_depth == 1


def test_event_consumer_does_not_infer_dispatch_from_an_ingest_attempt(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished.sqlite3"

    class FixtureGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            return _complete(unit)

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=None,
        max_graphiti=0,
        clock=clock,
    )
    result = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=FixtureGraphiti(),
        owner_id="fixture-worker",
        clock=clock,
        model_usage=ModelUsageService(str(unpublished)),
    )

    assert result is not None and result.state == "TERMINAL"
    retained = sqlite3.connect(unpublished)
    provider_dispatched = retained.execute(
        "SELECT provider_dispatched FROM unpublished_graphiti_revision_events "
        "WHERE event_id=?",
        (result.event_id,),
    ).fetchone()
    retained.close()
    assert provider_dispatched == (0,)


def test_result_shaped_cli_predispatch_refusal_becomes_configuration_hold(
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

    class PredispatchRefusalGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            return _predispatch_refusal(unit)

    result = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=PredispatchRefusalGraphiti(),
        owner_id="fixture-worker",
        clock=clock,
    )

    assert result is not None
    assert result.state == "CONFIGURATION_HELD"
    assert result.attempt_count == 1
    retained = sqlite3.connect(unpublished)
    row = retained.execute(
        "SELECT state,attempt_count,provider_dispatched,last_failure_code "
        "FROM unpublished_graphiti_revision_events WHERE event_id=?",
        (result.event_id,),
    ).fetchone()
    retained.close()
    assert row == (
        "CONFIGURATION_HELD",
        1,
        0,
        "CLI_PREDISPATCH_CONFIGURATION_REFUSED",
    )


def test_committed_leaf_dispatch_marker_overrides_a_no_call_claim(
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

    class ContradictoryGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            return _predispatch_refusal(unit)

    class CommittedMarker:
        def has_committed_provider_dispatch(self, *, cycle_id: str) -> bool:
            return bool(cycle_id)

    result = consume_next_graphiti_event(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        graphiti=ContradictoryGraphiti(),
        owner_id="fixture-worker",
        clock=clock,
        model_usage=CommittedMarker(),  # type: ignore[arg-type]
    )

    assert result is not None
    assert result.state == "RETRY_HELD"
    assert result.attempt_count == 1
    retained = sqlite3.connect(unpublished)
    provider_dispatched = retained.execute(
        "SELECT provider_dispatched FROM unpublished_graphiti_revision_events "
        "WHERE event_id=?",
        (result.event_id,),
    ).fetchone()
    retained.close()
    assert provider_dispatched == (1,)
