from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsroom.control_plane.corpus import CorpusIngestUnit, units_from
from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.editorial import GroupedObservation
from newsroom.control_plane.graphiti import GraphitiCycleResult
from newsroom.control_plane.items import SourceItem, parse_observation, parse_source_time
from newsroom.control_plane.writer import FixtureWriter
from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
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
    )
    again = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs",
        observed_at="2026-08-16T21:41:34.000000Z",
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
        def ingest(self, unit):
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
    assert stored["chat_subscription_not_debited"] is True
    assert coverage["eligible_source_revisions"] == 3
    assert coverage["successfully_ingested_revisions"] == 1
    assert coverage["unresolved_gap"] == 2
    assert coverage["payload_count_is_not_coverage"] is True
    assert coverage["unpublished_payload_count"] == 0
    assert coverage["unpublished_payload_count"] != coverage["successfully_ingested_revisions"]
    assert coverage["reserved_spend"] is True
    assert coverage["actual_metered_spend_microunits"] == 0
    assert coverage["admission_backlog"] == 1
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
    units = units_from(rows)
    assert len(units) == 2
    assert {unit.source_id for unit in units} == {"HK-04", "RAD-02"}
