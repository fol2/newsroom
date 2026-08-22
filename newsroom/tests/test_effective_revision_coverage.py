from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from newsroom.authority.canonical import digest_bytes
from newsroom.control_plane.corpus import CorpusIngestUnit, revisions_from, units_from
from newsroom.control_plane.cycle import CycleReport, run_cycle
from newsroom.control_plane.editorial import GroupedObservation
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.writer import FixtureWriter
from newsroom.effective_revision import retain_observation_revision_first_seen
from newsroom.increment9.proving import SOURCE_URLS
from newsroom.tests.test_control_plane_private_beta import _proving
from newsroom.tests.test_graphiti_corpus_ingest import (
    _complete,
    _effective_revision_resolver,
)


def _clock() -> datetime:
    return datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_REPEAT_AT = "2026-08-20T00:00:00.000000Z"


def _latest_coverage(unpublished: Path) -> dict[str, object]:
    connection = sqlite3.connect(unpublished)
    row = connection.execute(
        "SELECT coverage_json FROM unpublished_graphiti_coverage ORDER BY seq DESC"
    ).fetchone()
    connection.close()
    if row is None:
        raise AssertionError("cycle did not record coverage")
    return json.loads(row[0])


def _keep_source(proving: Path, source_id: str) -> None:
    connection = sqlite3.connect(proving)
    connection.execute(
        "DELETE FROM proving_observations WHERE source_id!=?",
        (source_id,),
    )
    connection.execute(
        "DELETE FROM proving_gates "
        "WHERE gate_id LIKE 'RIGHTS_%' AND gate_id!=?",
        (f"RIGHTS_{source_id}",),
    )
    connection.commit()
    connection.close()


def _set_body(proving: Path, *, source_id: str, body: bytes) -> None:
    connection = sqlite3.connect(proving)
    url, fetched_at = connection.execute(
        "SELECT url, fetched_at FROM proving_observations WHERE source_id=?",
        (source_id,),
    ).fetchone()
    connection.execute(
        """
        UPDATE proving_observations
        SET body=?, body_digest=?
        WHERE source_id=?
        """,
        (body, digest_bytes(body), source_id),
    )
    connection.execute(
        "DELETE FROM proving_revision_first_seen WHERE source_id=?",
        (source_id,),
    )
    retain_observation_revision_first_seen(
        connection,
        source_id=source_id,
        url=str(url),
        body=body,
        observed_at=str(fetched_at),
    )
    connection.commit()
    connection.close()


def _add_unchanged_poll(
    proving: Path,
    *,
    run_id: str,
    fetched_at: str,
) -> None:
    connection = sqlite3.connect(proving)
    latest = connection.execute(
        "SELECT run_id FROM proving_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES(?,?,0,0,0,0)
        """,
        (run_id, fetched_at),
    )
    rows = connection.execute(
        """
        SELECT source_id, url, status_code, body_digest, body, item_count, error
        FROM proving_observations WHERE run_id=?
        """,
        (latest,),
    ).fetchall()
    for source_id, url, status_code, digest, body, item_count, error in rows:
        body_bytes = bytes(body)
        connection.execute(
            "INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                run_id,
                fetched_at,
                url,
                status_code,
                digest,
                body_bytes,
                item_count,
                error,
            ),
        )
        retain_observation_revision_first_seen(
            connection,
            source_id=str(source_id),
            url=str(url),
            body=body_bytes,
            observed_at=fetched_at,
        )
    connection.execute(
        """
        INSERT INTO proving_gates
        SELECT ?, gate_id, status, reason FROM proving_gates WHERE run_id=?
        """,
        (run_id, latest),
    )
    connection.execute(
        """
        INSERT INTO proving_rights_packets
        SELECT ?, gate_id, packet_digest, packet_json, assessed_at
        FROM proving_rights_packets WHERE run_id=?
        """,
        (run_id, latest),
    )
    connection.commit()
    connection.close()


def _run(
    proving: Path,
    unpublished: Path,
    *,
    graphiti=None,
    max_graphiti: int = 0,
) -> CycleReport:
    return run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=graphiti,
        max_graphiti=max_graphiti,
        clock=_clock,
    )


def test_chunked_revision_has_one_denominator_without_observation_amplification(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    _keep_source(proving, "UK-01")
    long_body = "ordered-corpus-" * 2_000
    feed = (
        "<rss><channel><item><guid>long</guid><title>Long</title>"
        f"<description>{long_body}</description></item></channel></rss>"
    ).encode()
    _set_body(proving, source_id="UK-01", body=feed)
    first_at = "2026-08-16T21:41:34.000000Z"
    item = parse_observation(
        source_id="UK-01", url=SOURCE_URLS["UK-01"], body=feed
    )[0]
    first_row = GroupedObservation(
        "UK-01",
        digest_bytes(feed),
        item,
        first_at,
    )
    repeated_row = GroupedObservation(
        "UK-01",
        digest_bytes(feed),
        first_row.item,
        _REPEAT_AT,
    )
    amplified = units_from(
        (first_row, repeated_row),
        proving_run_id="run-1",
        effective_revision_resolver=_effective_revision_resolver(
            (first_row, repeated_row)
        ),
    )
    revisions = revisions_from(amplified)
    assert len(amplified) >= 4
    assert len(revisions) == 1
    chunk_count = len(revisions[0].ingest_ids)
    first_chunks = tuple(
        unit for unit in amplified if unit.observed_at == first_at
    )
    assert len(first_chunks) == chunk_count
    ordered = sorted(first_chunks, key=lambda unit: unit.chunk_ordinal)
    assert [unit.chunk_ordinal for unit in ordered] == list(range(1, chunk_count + 1))
    assert ordered[0].predecessor_ingest_id is None
    assert all(
        ordered[index].predecessor_ingest_id == ordered[index - 1].ingest_id
        for index in range(1, len(ordered))
    )

    _add_unchanged_poll(proving, run_id="run-2", fetched_at=_REPEAT_AT)
    calls: list[tuple[int, str | None, str]] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit):
            calls.append(
                (unit.chunk_ordinal, unit.predecessor_ingest_id, unit.ingest_id)
            )
            return _complete(unit)

    unpublished = tmp_path / "chunked.sqlite3"
    for _ in range(len(revisions[0].ingest_ids)):
        _run(proving, unpublished, graphiti=Stub(), max_graphiti=10)
    coverage = _latest_coverage(unpublished)
    assert coverage["effective_pull_count"] == 1
    assert coverage["eligible_source_revisions"] == 1
    assert coverage["poll_observation_count"] == 2
    assert coverage["feed_snapshot_item_count"] == 1
    assert coverage["eligible_ingest_chunks"] == len(revisions[0].ingest_ids)
    assert [item[0] for item in calls] == list(range(1, len(calls) + 1))
    assert len(calls) == coverage["eligible_ingest_chunks"]
    assert calls[0][1] is None
    assert all(calls[index][1] == calls[index - 1][2] for index in range(1, len(calls)))


def test_three_retries_count_one_coverage_obligation(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    _keep_source(proving, "UK-01")
    _add_unchanged_poll(proving, run_id="run-2", fetched_at=_REPEAT_AT)
    unpublished = tmp_path / "retries.sqlite3"
    calls: list[str] = []

    class AlwaysFail:
        def ingest(self, unit: CorpusIngestUnit):
            calls.append(unit.ingest_id)
            raise RuntimeError("timeout")

    for _ in range(3):
        _run(proving, unpublished, graphiti=AlwaysFail(), max_graphiti=1)
    fourth = _run(proving, unpublished, graphiti=AlwaysFail(), max_graphiti=1)
    coverage = _latest_coverage(unpublished)
    assert fourth.graphiti == 0
    assert len(calls) == 3
    assert len(set(calls)) == 1
    assert coverage["effective_pull_count"] == 1
    assert coverage["poll_observation_count"] == 2
    assert coverage["feed_snapshot_item_count"] == 1
    assert coverage["unresolved_gap"] == 1
    assert coverage["retry_attempt_count"] == 3
    assert coverage["dead_letter_count"] == 1


def test_source_coverage_reaches_100_percent_without_repeat_provider_work(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    _keep_source(proving, "UK-01")
    unpublished = tmp_path / "complete.sqlite3"

    class Complete:
        def ingest(self, unit: CorpusIngestUnit):
            return _complete(unit)

    first = _run(proving, unpublished, graphiti=Complete(), max_graphiti=1)
    first_coverage = _latest_coverage(unpublished)
    assert first.graphiti == 1
    assert first_coverage["effective_pull_count"] == 1
    assert first_coverage["successfully_ingested_revisions"] == 1
    assert first_coverage["unresolved_gap"] == 0
    assert first_coverage["poll_observation_count"] == 1

    _add_unchanged_poll(proving, run_id="run-2", fetched_at=_REPEAT_AT)

    class MustNotDispatch:
        def ingest(self, unit: CorpusIngestUnit):
            raise AssertionError("unchanged observations must not require provider work")

    second = _run(proving, unpublished, graphiti=MustNotDispatch(), max_graphiti=1)
    second_coverage = _latest_coverage(unpublished)
    assert second.graphiti == 0
    assert second_coverage["effective_pull_count"] == 1
    assert second_coverage["successfully_ingested_revisions"] == 1
    assert second_coverage["unresolved_gap"] == 0
    assert second_coverage["poll_observation_count"] == 2
    assert second_coverage["feed_snapshot_item_count"] == 1


def test_unchanged_poll_increases_observations_not_coverage(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "telemetry.sqlite3"
    first = _run(proving, unpublished, max_graphiti=0)
    first_coverage = _latest_coverage(unpublished)
    coverage_fields = (
        "effective_pull_count",
        "eligible_source_revisions",
        "successfully_ingested_revisions",
        "unresolved_gap",
        "eligible_ingest_chunks",
        "held_or_failed_revisions",
        "dead_letter_count",
    )
    first_snapshot = {field: first_coverage[field] for field in coverage_fields}
    assert first.poll_observation_count == 3
    assert first.feed_snapshot_item_count == 3
    assert first.effective_pull_count == 3
    assert first_coverage["poll_observation_count"] == 3
    assert first_coverage["feed_snapshot_item_count"] == 3
    assert first_coverage["effective_pull_count"] == 3
    assert first_coverage["unresolved_gap"] == 3

    _add_unchanged_poll(proving, run_id="run-2", fetched_at=_REPEAT_AT)
    second = _run(proving, unpublished, max_graphiti=0)
    second_coverage = _latest_coverage(unpublished)
    assert {field: second_coverage[field] for field in coverage_fields} == first_snapshot
    assert second.poll_observation_count == 6
    assert second.feed_snapshot_item_count == 3
    assert second.effective_pull_count == 3
    assert second_coverage["poll_observation_count"] == 6
    assert second_coverage["feed_snapshot_item_count"] == 3
    assert second_coverage["effective_pull_count"] == 3
