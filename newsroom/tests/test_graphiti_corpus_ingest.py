from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane.corpus import (
    CorpusIngestUnit,
    EligibleCorpusRevision,
    revisions_from,
    units_from,
)
from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.editorial import GroupedObservation, StoryCandidateRecord
from newsroom.control_plane.evidence import EvidencePackage
from newsroom.control_plane.graphiti import GraphitiCycleResult
from newsroom.control_plane.items import SourceItem, parse_observation, parse_source_time
from newsroom.control_plane.veto import VetoError
from newsroom.control_plane.writer import FixtureWriter, WriterCopy
from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
from newsroom.graphiti_adapter.identity import MAX_EPISODE_BYTES
from newsroom.graphiti_adapter.models import GraphitiAdapterContractError
from newsroom.graphiti_adapter.real import _is_source_registry_name
from newsroom.graphiti_adapter.temporal import (
    OBSERVED_FALLBACK,
    SOURCE_PUBLISHED,
    SOURCE_UPDATED,
    map_reference_time,
)
from newsroom.tests.test_control_plane_private_beta import _proving


DATED_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <guid>dated-1</guid>
    <title>Dated source</title>
    <link>https://www.example.gov.uk/dated</link>
    <pubDate>Thu, 01 Jan 2026 09:00:00 +0000</pubDate>
    <description>A retained dated item.</description>
  </item>
</channel></rss>
""".encode("utf-8")


def test_parse_source_time_rfc822_and_iso() -> None:
    assert parse_source_time("Thu, 01 Jan 2026 09:00:00 +0000") == (
        "2026-01-01T09:00:00.000000Z"
    )
    assert parse_source_time("2026-03-01T12:00:00Z") == "2026-03-01T12:00:00.000000Z"
    assert parse_source_time("2026-03-01") == "2026-03-01T00:00:00.000000Z"


def test_rss_keeps_published_time() -> None:
    items = parse_observation(
        source_id="UK-01",
        url="https://www.example.gov.uk/feed.rss",
        body=DATED_RSS,
    )
    assert items[0].published_at == "2026-01-01T09:00:00.000000Z"
    assert "UK-01" not in items[0].headline
    assert "UK-01" not in items[0].body


def test_temporal_policy_prefers_updated_then_published_then_observed() -> None:
    updated = map_reference_time(
        published_at="2026-01-01T00:00:00.000000Z",
        updated_at="2026-03-01T00:00:00.000000Z",
        observed_at="2026-08-20T00:00:00.000000Z",
    )
    assert updated.basis == SOURCE_UPDATED
    assert updated.reference_time.to_text() == "2026-03-01T00:00:00.000000Z"
    published = map_reference_time(
        published_at="2026-01-01T00:00:00.000000Z",
        updated_at=None,
        observed_at="2026-08-20T00:00:00.000000Z",
    )
    assert published.basis == SOURCE_PUBLISHED
    fallback = map_reference_time(
        published_at=None,
        updated_at=None,
        observed_at="2026-08-20T00:00:00.000000Z",
    )
    assert fallback.basis == OBSERVED_FALLBACK


def test_temporal_policy_refuses_invalid_observed_at() -> None:
    with pytest.raises(ValueError, match="observed_at"):
        map_reference_time(
            published_at=None,
            updated_at=None,
            observed_at="not-a-timestamp",
        )


def test_ingest_identity_is_deterministic_and_episode_omits_source_id() -> None:
    unit = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs",
        observed_at="2026-08-16T21:41:34.000000Z",
        proving_run_id="run-1",
    )
    again = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs",
        observed_at="2026-08-16T21:41:34.000000Z",
        proving_run_id="run-1",
    )
    assert unit.ingest_id == again.ingest_id
    assert "HK-04" not in unit.episode_body
    first = evaluation_attempt_for((unit.episode_body,))
    second = evaluation_attempt_for((unit.episode_body,))
    assert str(first.attempt_id) == str(second.attempt_id)
    assert first.episode_uuid == second.episode_uuid
    assert first.reference_time is not None
    assert first.temporal_basis == OBSERVED_FALLBACK


def test_source_registry_ids_are_not_world_entities() -> None:
    assert _is_source_registry_name("HK-04") is True
    assert _is_source_registry_name("RAD-02") is True
    assert _is_source_registry_name("UK-01: Registration as...") is True
    assert _is_source_registry_name("Hong Kong Observatory") is False


def test_cycle_ingests_corpus_without_writes(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    calls: list[str] = []

    class StubGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            calls.append(unit.ingest_id)
            assert unit.source_id not in unit.episode_body
            return GraphitiCycleResult(
                ingest_id=unit.ingest_id,
                source_id=unit.source_id,
                item_key=unit.item_key,
                outcome="COMPLETE",
                proposal_count=3,
                entity_count=2,
                relation_count=1,
                failure_code="NONE",
                temporal_basis=unit.temporal().basis,
                reference_time=unit.temporal().reference_time.to_text(),
                entities=({"name": "Example", "uuid": "node-1"},),
                relations=(
                    {
                        "fact": "Example relates to curriculum",
                        "source_node_uuid": "node-1",
                        "target_node_uuid": "node-2",
                        "valid_at": unit.temporal().reference_time.to_text(),
                        "invalid_at": None,
                    },
                ),
                episode_uuid=unit.ingest_id,
                proposals=(
                    {
                        "local_id": "relation.0001",
                        "evidence": [
                            {
                                "passage_id": "passage-1",
                                "start_byte": 0,
                                "end_byte": 7,
                            }
                        ],
                    },
                ),
                passages=(
                    {
                        "passage_id": "passage-1",
                        "byte_offset": 0,
                        "byte_length": len(unit.episode_body.encode("utf-8")),
                    },
                ),
                chat_invocations=(
                    {
                        "provider": "cursor-agent-cli",
                        "model": "composer-2.5",
                        "outcome": "MALFORMED_OUTPUT",
                    },
                    {
                        "provider": "grok-build-cli",
                        "model": "grok-4.6",
                        "outcome": "COMPLETE",
                    },
                ),
            )

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=StubGraphiti(),
        max_graphiti=1,
    )
    assert report.minted == 0
    assert report.graphiti == 1
    assert report.eligible == 3
    assert len(calls) == 1
    connection = __import__("sqlite3").connect(unpublished)
    kinds = [row[0] for row in connection.execute("SELECT kind FROM ledger ORDER BY seq")]
    close = connection.execute(
        "SELECT kind FROM ledger WHERE kind='PRIVATE_CYCLE_CLOSE'"
    ).fetchone()
    ingest = connection.execute(
        "SELECT entity_count, relation_count FROM unpublished_graphiti_ingest"
    ).fetchone()
    stored = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_receipts"
        ).fetchone()[0]
    )
    coverage = json.loads(
        connection.execute(
            "SELECT coverage_json FROM unpublished_graphiti_coverage ORDER BY seq DESC"
        ).fetchone()[0]
    )
    connection.close()
    assert kinds.count("GRAPHITI_EVALUATION_ATTEMPT") == 1
    assert close is not None
    assert ingest == (2, 1)
    assert stored["entities"][0]["name"] == "Example"
    assert stored["relations"][0]["fact"] == "Example relates to curriculum"
    assert stored["relations"][0]["source_node_uuid"] == "node-1"
    assert stored["episode_uuid"] == calls[0]
    assert stored["proposals"][0]["evidence"][0]["passage_id"] == "passage-1"
    assert stored["passages"][0]["passage_id"] == "passage-1"
    assert [item["outcome"] for item in stored["chat_invocations"]] == [
        "MALFORMED_OUTPUT",
        "COMPLETE",
    ]
    assert stored["chat_subscription_not_debited"] is True
    assert stored["usage_basis"] == "UNOBSERVED"
    assert stored["prompt_version"]
    assert stored["proving_run_id"] == "run-1"
    assert stored["observed_at"]
    assert stored["chunk_ordinal"] == 1
    assert coverage["eligible_source_revisions"] == 3
    assert coverage["successfully_ingested_revisions"] == 1
    assert coverage["unresolved_gap"] == 2
    assert coverage["payload_count_is_not_coverage"] is True
    assert coverage["unpublished_payload_count"] == 0
    assert coverage["unpublished_payload_count"] != coverage["successfully_ingested_revisions"]
    assert coverage["reserved_spend"] is True
    assert coverage["actual_metered_spend_microunits"] == 0
    assert coverage["admission_backlog"] == 3
    assert coverage["retry_count"] == 0
    assert coverage["dead_letter_count"] == 0
    assert coverage["ingest_watermark_at"]


def test_units_from_observations_cover_items_not_candidates() -> None:
    item = SourceItem("HK-04", "k", "headline", "body", "https://example.invalid/a")
    rows = (
        GroupedObservation("HK-04", "sha256:a", item, "2026-08-16T21:41:34.000000Z"),
        GroupedObservation("RAD-02", "sha256:b", item, "2026-08-16T21:41:34.000000Z"),
    )
    # Same URL/item_key would collapse candidates; ingest still has two source rows
    # because source_id differs in ingest_key.
    units = units_from(rows, proving_run_id="run-1")
    assert len(units) == 2
    assert {unit.source_id for unit in units} == {"HK-04", "RAD-02"}


def _complete(unit: CorpusIngestUnit) -> GraphitiCycleResult:
    return GraphitiCycleResult(
        ingest_id=unit.ingest_id,
        source_id=unit.source_id,
        item_key=unit.item_key,
        outcome="COMPLETE",
        proposal_count=1,
        entity_count=1,
        relation_count=0,
        failure_code="NONE",
        temporal_basis=unit.temporal().basis,
        reference_time=unit.temporal().reference_time.to_text(),
    )


def test_same_body_new_observation_is_a_new_ingest() -> None:
    first = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs-a",
        observed_at="2026-08-16T21:41:34.000000Z",
        proving_run_id="run-1",
        published_at="2026-01-01T00:00:00.000000Z",
    )
    second = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs-b",
        observed_at="2026-08-20T00:00:00.000000Z",
        proving_run_id="run-1",
        published_at="2026-01-01T00:00:00.000000Z",
    )
    third = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs-a",
        observed_at="2026-08-16T21:41:34.000000Z",
        proving_run_id="run-1",
        published_at="2026-03-01T00:00:00.000000Z",
    )
    assert first.ingest_id != second.ingest_id
    assert first.ingest_id != third.ingest_id


def test_long_body_is_chunked_not_truncated() -> None:
    body = "a" * (MAX_EPISODE_BYTES + 50)
    item = SourceItem("UK-01", "long", "headline", body, "https://example.invalid/long")
    rows = (
        GroupedObservation(
            "UK-01", "sha256:long", item, "2026-08-16T21:41:34.000000Z"
        ),
    )
    units = units_from(rows, proving_run_id="run-1")
    assert len(units) >= 2
    assert {unit.chunk_ordinal for unit in units} == {1, 2}
    joined = "".join(
        unit.episode_body for unit in sorted(units, key=lambda item: item.chunk_ordinal)
    )
    assert "headline" in joined
    assert body in joined
    assert all(len(unit.episode_body.encode()) <= MAX_EPISODE_BYTES for unit in units)
    revisions = revisions_from(units)
    assert len(revisions) == 1
    assert len(revisions[0].ingest_ids) == 2


def test_parser_retains_long_corpus_text_before_ordered_chunking() -> None:
    retained = "long-source-text-" * 700
    feed = (
        "<rss><channel><item><guid>long</guid><title>Long</title>"
        f"<description>{retained}</description>"
        "</item></channel></rss>"
    ).encode("utf-8")
    item = parse_observation(
        source_id="UK-01", url="https://example.invalid/feed.rss", body=feed
    )[0]
    assert item.body == retained
    units = units_from(
        (
            GroupedObservation(
                "UK-01",
                "sha256:long-parser",
                item,
                "2026-08-16T21:41:34.000000Z",
            ),
        ),
        proving_run_id="run-1",
    )
    assert retained in "".join(
        unit.episode_body for unit in sorted(units, key=lambda value: value.chunk_ordinal)
    )


def test_coverage_uses_revision_denominator_and_contiguous_input_watermark(
    tmp_path: Path,
) -> None:
    from newsroom.control_plane.store import (
        connect,
        graphiti_coverage,
        insert_graphiti_ingest,
    )

    connection = connect(str(tmp_path / "coverage.sqlite3"))
    first = EligibleCorpusRevision(
        "revision-1",
        "UK-01",
        "item-1",
        "2026-08-01T00:00:00.000000Z",
        "2026-08-01T00:00:00.000000Z",
        ("chunk-1",),
    )
    second = EligibleCorpusRevision(
        "revision-2",
        "UK-02",
        "item-2",
        "2026-08-02T00:00:00.000000Z",
        "2026-08-02T00:00:00.000000Z",
        ("chunk-2a", "chunk-2b"),
    )
    for ingest_id in second.ingest_ids:
        insert_graphiti_ingest(
            connection,
            ingest_id=ingest_id,
            source_id="UK-02",
            item_key="item-2",
            outcome="COMPLETE",
            proposal_count=2,
            entity_count=2,
            relation_count=0,
            failure_code="NONE",
            temporal_basis="SOURCE_PUBLISHED",
            reference_time=second.source_time,
            generation_id="generation",
            receipt_digest="sha256:receipt",
        )
    coverage = graphiti_coverage(connection, revisions=(first, second))
    connection.close()
    assert coverage["eligible_source_revisions"] == 2
    assert coverage["eligible_ingest_chunks"] == 3
    assert coverage["successfully_ingested_revisions"] == 1
    assert coverage["contiguous_input_watermark"] is None
    assert coverage["ingest_watermark_at"] is None
    assert coverage["oldest_unresolved_gap"]["revision_id"] == "revision-1"
    assert coverage["admission_backlog"] == 4


def test_older_run_backlog_remains_queued_after_a_new_run_arrives(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    calls: list[tuple[str, str]] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            calls.append((unit.proving_run_id, unit.ingest_id))
            return _complete(unit)

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=1,
    )
    connection = __import__("sqlite3").connect(proving)
    connection.execute(
        "INSERT INTO proving_runs VALUES('run-2','2026-08-20T00:00:00.000000Z',0,0,0,0)"
    )
    for row in connection.execute(
        """
        SELECT source_id, url, status_code, body_digest, body, item_count, error
        FROM proving_observations WHERE run_id='run-1'
        """
    ).fetchall():
        source_id, url, status_code, digest, body, item_count, error = row
        connection.execute(
            "INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                "run-2",
                "2026-08-20T00:00:00.000000Z",
                url,
                status_code,
                f"{digest}-run-2",
                bytes(body) + b" ",
                item_count,
                error,
            ),
        )
    connection.execute(
        """
        INSERT INTO proving_gates
        SELECT 'run-2', gate_id, status, reason FROM proving_gates WHERE run_id='run-1'
        """
    )
    connection.commit()
    connection.close()

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=1,
    )
    assert report.proving_run_id == "run-2"
    assert report.eligible == 6
    assert calls[1][0] == "run-1"


def test_provider_reported_embedding_cost_is_reconciled_and_debited(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"

    class MeteredStub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            result = _complete(unit)
            return replace(
                result,
                embedding_usage={
                    "usage_basis": "PROVIDER_REPORTED",
                    "request_count": 2,
                    "embedding_tokens": 125,
                    "cost_usd_microunits": 17,
                    "requests": [],
                },
                request_tokens=125,
                cost_microunits=17,
                usage_basis="PROVIDER_REPORTED",
            )

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=MeteredStub(),
        max_graphiti=1,
    )
    connection = __import__("sqlite3").connect(unpublished)
    spend = connection.execute(
        """
        SELECT status, actual_usd_microunits, actual_gbp_microunits, usage_basis
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    receipt = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_receipts"
        ).fetchone()[0]
    )
    coverage = json.loads(
        connection.execute(
            "SELECT coverage_json FROM unpublished_graphiti_coverage ORDER BY seq DESC"
        ).fetchone()[0]
    )
    connection.close()
    assert spend == ("RECONCILED", 17, 17, "PROVIDER_REPORTED")
    assert receipt["accounting"]["fx_policy"] == "USD_GBP_CONSERVATIVE_PARITY_V1"
    assert receipt["accounting"]["unused_reservation_released"] is True
    assert coverage["actual_metered_spend_gbp_microunits"] == 17
    assert coverage["outstanding_reserved_spend_gbp_microunits"] == 0


def test_max_graphiti_counts_failed_attempts(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    calls: list[str] = []

    class Boom:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            calls.append(unit.ingest_id)
            raise RuntimeError("provider")

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Boom(),
        max_graphiti=1,
    )
    assert len(calls) == 1
    assert report.graphiti == 1


def test_cycle_rejects_foreign_graphiti_identity(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"

    class Liar:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            return GraphitiCycleResult(
                ingest_id="00000000-0000-4000-8000-000000000099",
                source_id="XX-99",
                item_key="foreign",
                outcome="COMPLETE",
                proposal_count=1,
                entity_count=1,
                relation_count=0,
                failure_code="NONE",
                temporal_basis=unit.temporal().basis,
                reference_time=unit.temporal().reference_time.to_text(),
            )

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Liar(),
        max_graphiti=1,
    )
    assert report.graphiti == 1
    connection = __import__("sqlite3").connect(unpublished)
    stored = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_ingest"
    ).fetchone()[0]
    failed = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_failures"
    ).fetchone()[0]
    connection.close()
    assert stored == 0
    assert failed == 1


def test_ingest_commits_when_writer_fails(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"

    class BrokenWriter:
        writer_id = "broken"

        def write(
            self, candidate: StoryCandidateRecord, package: EvidencePackage
        ) -> WriterCopy:
            raise RuntimeError("writer down")

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=BrokenWriter(),
        max_writes=5,
        graphiti=Stub(),
        max_graphiti=1,
    )
    assert report.minted == 0
    assert report.graphiti == 1
    connection = __import__("sqlite3").connect(unpublished)
    stored = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_ingest"
    ).fetchone()[0]
    connection.close()
    assert stored == 1


def test_ingest_survives_writer_veto(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"

    class VetoWriter:
        writer_id = "veto"

        def write(
            self, candidate: StoryCandidateRecord, package: EvidencePackage
        ) -> WriterCopy:
            raise VetoError("PUBLIC_DISPATCH")

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            return _complete(unit)

    with pytest.raises(VetoError, match="PUBLIC_DISPATCH"):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=VetoWriter(),
            max_writes=5,
            graphiti=Stub(),
            max_graphiti=1,
        )
    connection = __import__("sqlite3").connect(unpublished)
    stored = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_ingest"
    ).fetchone()[0]
    connection.close()
    assert stored == 1


def test_unattempted_units_run_before_retries(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    calls: list[str] = []

    class AlwaysFail:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            calls.append(unit.ingest_id)
            raise RuntimeError("timeout")

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=AlwaysFail(),
        max_graphiti=1,
    )
    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=AlwaysFail(),
        max_graphiti=1,
    )
    assert len(calls) == 2
    assert calls[0] != calls[1]


def test_dead_letter_stops_retrying_a_unit(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    connection.execute("DELETE FROM proving_observations WHERE source_id!='UK-01'")
    connection.execute("DELETE FROM proving_gates WHERE gate_id!='RIGHTS_UK-01'")
    connection.commit()
    connection.close()
    unpublished = tmp_path / "unpublished_store.sqlite3"
    calls: list[str] = []

    class AlwaysFail:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            calls.append(unit.ingest_id)
            raise RuntimeError("timeout")

    for _ in range(3):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=AlwaysFail(),
            max_graphiti=1,
        )
    fourth = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=AlwaysFail(),
        max_graphiti=1,
    )
    assert fourth.graphiti == 0
    assert len(calls) == 3
    assert len(set(calls)) == 1
    connection = __import__("sqlite3").connect(unpublished)
    dead = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_failures WHERE dead_lettered=1"
    ).fetchone()[0]
    coverage = json.loads(
        connection.execute(
            "SELECT coverage_json FROM unpublished_graphiti_coverage ORDER BY seq DESC"
        ).fetchone()[0]
    )
    connection.close()
    assert dead == 1
    assert coverage["dead_letter_count"] == 1


def test_missing_rights_gate_skips_source(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    connection.execute("DELETE FROM proving_gates WHERE gate_id='RIGHTS_UK-02'")
    connection.commit()
    connection.close()
    unpublished = tmp_path / "unpublished_store.sqlite3"

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            assert unit.source_id != "UK-02"
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=1,
    )
    assert report.eligible == 2
    assert report.sources == 2


def test_attempt_canonical_digest_covers_temporal_episode_and_generation() -> None:
    base = evaluation_attempt_for(("Hong Kong Observatory issued a warning.",))
    assert (
        replace(base, temporal_basis=SOURCE_PUBLISHED).canonical_digest
        != base.canonical_digest
    )
    assert (
        replace(
            base,
            reference_time=UtcTimestamp.parse("2026-01-01T00:00:00.000000Z"),
        ).canonical_digest
        != base.canonical_digest
    )
    assert (
        replace(
            base, episode_uuid="00000000-0000-4000-8000-000000000001"
        ).canonical_digest
        != base.canonical_digest
    )
    assert replace(base, generation_id="changedgen").canonical_digest != base.canonical_digest
    with pytest.raises(GraphitiAdapterContractError, match="temporal_basis"):
        replace(base, temporal_basis="STARTED_AT")
