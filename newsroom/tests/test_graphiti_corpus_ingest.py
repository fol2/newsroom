from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane.corpus import (
    CorpusIngestUnit,
    EligibleCorpusRevision,
    revisions_from,
    units_from,
)
from newsroom.control_plane.cycle import _bind_result, run_cycle
from newsroom.control_plane.editorial import (
    GroupedObservation,
    StoryCandidateRecord,
    form_candidates,
)
from newsroom.control_plane.evidence import EvidencePackage, package_for
from newsroom.control_plane.graphiti import EvaluationGraphitiRunner, GraphitiCycleResult
from newsroom.control_plane.items import SourceItem, parse_observation, parse_source_time
from newsroom.control_plane.veto import VetoError
from newsroom.control_plane.writer import FixtureWriter, WriterCopy
from newsroom.graphiti_adapter.evaluation_attempt import (
    evaluation_attempt_for,
    evaluation_attempt_for_body,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
    OD_011_CASH_CEILING_GBP,
)
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


def _complete(
    unit: CorpusIngestUnit,
    *,
    proposal_count: int = 1,
    entity_count: int = 1,
    relation_count: int = 0,
    proposals: tuple[dict[str, object], ...] = (),
    entities: tuple[dict[str, object], ...] = (),
    relations: tuple[dict[str, object], ...] = (),
    chat_invocations: tuple[dict[str, object], ...] = (),
    embedding_usage: dict[str, object] | None = None,
) -> GraphitiCycleResult:
    authority_ids = None
    if unit.authority is not None:
        authority_ids = (
            unit.authority.admission_id,
            unit.authority.access_decision_id,
            unit.authority.definition_id,
            unit.authority.definition_version_id,
            unit.authority.item_id,
            unit.authority.revision_id,
            unit.authority.representation_id,
        )
    attempt = evaluation_attempt_for_body(
        episode_body=unit.episode_body,
        ingest_id=unit.ingest_id,
        proving_run_id=unit.proving_run_id,
        source_id=unit.source_id,
        item_key=unit.item_key,
        observation_digest=unit.observation_digest,
        published_at=unit.published_at,
        updated_at=unit.updated_at,
        observed_at=unit.observed_at,
        canonical_url=unit.canonical_url,
        revision_digest=unit.revision_digest,
        representation_digest=unit.representation_digest,
        authority_ids=authority_ids,
        attempt_number=unit.attempt_number,
        predecessor_episode_uuid=unit.predecessor_ingest_id,
    )
    passage_id = str(attempt.manifest.passages[0].passage_id)
    if len(proposals) < proposal_count:
        proposals = (*proposals, *tuple(
            {
                "local_id": f"entity.{index:04d}",
                "evidence": [
                    {
                        "passage_id": passage_id,
                        "start_byte": 0,
                        "end_byte": 1,
                    }
                ],
            }
            for index in range(len(proposals) + 1, proposal_count + 1)
        ))
    bound_proposals: tuple[dict[str, object], ...] = tuple(
        {
            **proposal,
            "evidence": [
                {**item, "passage_id": passage_id}
                for item in proposal.get("evidence", [])
                if isinstance(item, dict)
            ],
        }
        for proposal in proposals
    )
    embedding_receipt = embedding_usage or {
        "usage_basis": "NO_EMBEDDING_CALL",
        "request_count": 0,
        "embedding_tokens": 0,
        "cost_usd_microunits": 0,
        "requests": [],
    }
    raw: dict[str, object] = {
        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
        "generation_id": GRAPHITI_GENERATION_ID,
        "episode_uuid": unit.ingest_id,
        "attempt_number": unit.attempt_number,
        "provider_attempt_number": unit.attempt_number,
        "predecessor_episode_uuid": unit.predecessor_ingest_id,
        "temporal_basis": unit.temporal().basis,
        "reference_time": unit.temporal().reference_time.to_text(),
        "passages": [
            passage.canonical_value() for passage in attempt.manifest.passages
        ],
        "proposals": list(bound_proposals),
        "entities": list(entities),
        "relations": list(relations),
        "chat_invocations": list(chat_invocations),
        "entity_count": entity_count,
        "relation_count": relation_count,
        "proposal_count": proposal_count,
        "chat_invocation_count": len(chat_invocations),
        "embedding_usage": embedding_receipt,
        "usage_basis": str(embedding_receipt["usage_basis"]),
        "framework": GRAPHITI_CORE_RELEASE,
        "chat": GRAPHITI_CHAT_MODEL,
        "chat_fallback": GRAPHITI_CHAT_FALLBACK,
        "embedding": GRAPHITI_EMBEDDING_MODEL,
        "prompt_version": "v1",
    }
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    return GraphitiCycleResult(
        ingest_id=unit.ingest_id,
        source_id=unit.source_id,
        item_key=unit.item_key,
        outcome="COMPLETE",
        proposal_count=proposal_count,
        entity_count=entity_count,
        relation_count=relation_count,
        failure_code="NONE",
        temporal_basis=unit.temporal().basis,
        reference_time=unit.temporal().reference_time.to_text(),
        receipt_digest=str(raw["raw_output_digest"]),
        episode_uuid=unit.ingest_id,
        proposals=bound_proposals,
        passages=tuple(raw["passages"]),
        entities=entities,
        relations=relations,
        chat_invocations=chat_invocations,
        embedding_usage=dict(embedding_receipt),
        usage_basis=str(embedding_receipt["usage_basis"]),
        attempt_number=unit.attempt_number,
        provider_attempt_number=unit.attempt_number,
        predecessor_episode_uuid=unit.predecessor_ingest_id,
        raw_receipt=raw,
    )


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
            return _complete(
                unit,
                proposal_count=3,
                entity_count=2,
                relation_count=1,
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
    authority_count = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_authority_records"
    ).fetchone()[0]
    attempt_receipt = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
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
    assert stored["proposals"][0]["evidence"][0]["passage_id"] == (
        stored["passages"][0]["passage_id"]
    )
    assert [item["outcome"] for item in stored["chat_invocations"]] == [
        "MALFORMED_OUTPUT",
        "COMPLETE",
    ]
    assert stored["chat_subscription_not_debited"] is True
    assert stored["usage_basis"] == "NO_EMBEDDING_CALL"
    assert stored["prompt_version"]
    assert stored["proving_run_id"] == "run-1"
    assert stored["observed_at"]
    assert stored["chunk_ordinal"] == 1
    assert authority_count == 7
    assert len(stored["authority_record_ids"]) == 7
    retained_digest = attempt_receipt.pop("receipt_digest")
    assert retained_digest == digest_bytes(canonical_json_bytes(attempt_receipt))
    assert coverage["eligible_source_revisions"] == 3
    assert coverage["successfully_ingested_revisions"] == 1
    assert coverage["unresolved_gap"] == 2
    assert coverage["payload_count_is_not_coverage"] is True
    assert coverage["unpublished_payload_count"] == 0
    assert coverage["unpublished_payload_count"] != coverage["successfully_ingested_revisions"]
    assert coverage["reserved_spend"] is False
    assert coverage["outstanding_reserved_spend_gbp_microunits"] == 0
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


def test_authority_records_bind_each_item_and_source_definition_version() -> None:
    rows = (
        GroupedObservation(
            "UK-01",
            "sha256:response",
            SourceItem("UK-01", "one", "One", "Body one", "https://item/one"),
            "2026-08-20T00:00:00.000000Z",
        ),
        GroupedObservation(
            "UK-01",
            "sha256:response",
            SourceItem("UK-01", "two", "Two", "Body two", "https://item/two"),
            "2026-08-20T00:00:00.000000Z",
        ),
    )
    first = units_from(
        rows,
        proving_run_id="run-1",
        rights_authority_run_id="run-2",
        source_definition_url="https://source/feed-v1",
    )
    changed = units_from(
        rows[:1],
        proving_run_id="run-1",
        rights_authority_run_id="run-2",
        source_definition_url="https://source/feed-v2",
    )[0]
    assert first[0].authority is not None
    assert first[1].authority is not None
    assert {str(item["record_type"]) for item in first[0].authority.records} == {
        "SOURCE_DEFINITION",
        "SOURCE_DEFINITION_VERSION",
        "SOURCE_ITEM",
        "SOURCE_REVISION",
        "DISCOVERY_REPRESENTATION",
        "OBJECT_ADMISSION",
        "OBJECT_ACCESS_DECISION",
    }
    assert first[0].authority.representation_id != first[1].authority.representation_id
    assert (
        first[0].authority.definition_version_id
        != changed.authority.definition_version_id
    )


def test_revision_time_changes_rebind_admission_and_access_identities() -> None:
    first_row = GroupedObservation(
        "UK-01",
        "sha256:response",
        SourceItem(
            "UK-01",
            "one",
            "One",
            "Body one",
            "https://item/one",
            published_at="2026-08-20T00:00:00.000000Z",
        ),
        "2026-08-20T00:01:00.000000Z",
    )
    changed_row = replace(
        first_row,
        item=replace(
            first_row.item,
            published_at="2026-08-20T00:02:00.000000Z",
        ),
    )
    first = units_from((first_row,), proving_run_id="run-1")[0]
    changed = units_from((changed_row,), proving_run_id="run-1")[0]
    assert first.authority is not None
    assert changed.authority is not None
    assert first.authority.revision_id != changed.authority.revision_id
    assert first.authority.admission_id != changed.authority.admission_id
    assert first.authority.access_decision_id != changed.authority.access_decision_id


def test_source_item_authority_excludes_mutable_canonical_url(tmp_path: Path) -> None:
    from newsroom.control_plane.store import connect, retain_graphiti_authority_records

    first_row = GroupedObservation(
        "UK-01",
        "sha256:response-one",
        SourceItem("UK-01", "one", "One", "Body", "https://item/one"),
        "2026-08-20T00:00:00.000000Z",
    )
    changed_row = replace(
        first_row,
        observation_digest="sha256:response-two",
        item=replace(first_row.item, canonical_url="https://item/renamed"),
    )
    first = units_from((first_row,), proving_run_id="run-1")[0]
    changed = units_from((changed_row,), proving_run_id="run-2")[0]
    assert first.authority is not None
    assert changed.authority is not None
    first_item = next(
        record
        for record in first.authority.records
        if record["record_type"] == "SOURCE_ITEM"
    )
    changed_item = next(
        record
        for record in changed.authority.records
        if record["record_type"] == "SOURCE_ITEM"
    )
    assert first_item == changed_item
    assert "canonical_url" not in first_item
    connection = connect(str(tmp_path / "authority.sqlite3"))
    retain_graphiti_authority_records(connection, first.authority.records)
    retain_graphiti_authority_records(connection, changed.authority.records)
    connection.close()


def test_source_revision_authority_is_stable_across_repeat_observations(
    tmp_path: Path,
) -> None:
    from newsroom.control_plane.store import connect, retain_graphiti_authority_records

    first_row = GroupedObservation(
        "UK-01",
        "sha256:response-one",
        SourceItem(
            "UK-01",
            "one",
            "One",
            "Body",
            "https://item/one",
            published_at="2026-08-19T00:00:00.000000Z",
        ),
        "2026-08-20T00:00:00.000000Z",
    )
    repeated_row = replace(
        first_row,
        observation_digest="sha256:response-two",
        observed_at="2026-08-20T01:00:00.000000Z",
    )
    first = units_from((first_row,), proving_run_id="run-1")[0]
    repeated = units_from((repeated_row,), proving_run_id="run-2")[0]
    assert first.authority is not None
    assert repeated.authority is not None
    first_revision = next(
        record
        for record in first.authority.records
        if record["record_type"] == "SOURCE_REVISION"
    )
    repeated_revision = next(
        record
        for record in repeated.authority.records
        if record["record_type"] == "SOURCE_REVISION"
    )
    assert first_revision == repeated_revision
    connection = connect(str(tmp_path / "revision-authority.sqlite3"))
    retain_graphiti_authority_records(connection, first.authority.records)
    retain_graphiti_authority_records(connection, repeated.authority.records)
    connection.close()


def test_same_immutable_revision_is_not_reingested_after_polling() -> None:
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
    assert first.ingest_id == second.ingest_id
    assert first.ingest_id != third.ingest_id
    fallback_later = replace(
        first,
        published_at=None,
        observed_at="2026-08-20T00:00:00.000000Z",
    )
    fallback_earlier = replace(
        fallback_later,
        observed_at="2026-08-19T00:00:00.000000Z",
    )
    assert fallback_later.ingest_id != fallback_earlier.ingest_id
    assert fallback_later.revision_id != fallback_earlier.revision_id


def test_fallback_observations_are_separate_coverage_revisions() -> None:
    first_row = GroupedObservation(
        "UK-01",
        "sha256:response-one",
        SourceItem("UK-01", "one", "One", "Body", "https://item/one"),
        "2026-08-20T00:00:00.000000Z",
    )
    repeated_row = replace(
        first_row,
        observation_digest="sha256:response-two",
        observed_at="2026-08-20T01:00:00.000000Z",
    )

    revisions = revisions_from(
        units_from((first_row, repeated_row), proving_run_id="run-1")
    )

    assert len(revisions) == 2
    assert revisions[0].revision_id != revisions[1].revision_id
    assert all(len(revision.ingest_ids) == 1 for revision in revisions)


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
    assert len(item.body) == 4_000
    assert item.retained_corpus_body == retained
    package = package_for(
        form_candidates(
            (
                GroupedObservation(
                    "UK-01",
                    "sha256:long-parser",
                    item,
                    "2026-08-16T21:41:34.000000Z",
                ),
            )
        )[0]
    )
    assert retained not in package.passages[0]
    assert len(item.body) == 4_000
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


def test_coverage_batches_large_ingest_id_sets(tmp_path: Path) -> None:
    from newsroom.control_plane.store import connect, graphiti_coverage

    connection = connect(str(tmp_path / "large-coverage.sqlite3"))
    revisions = tuple(
        EligibleCorpusRevision(
            f"revision-{index}",
            "UK-01",
            f"item-{index}",
            "2026-08-20T00:00:00.000000Z",
            "2026-08-20T00:00:00.000000Z",
            (f"chunk-{index}",),
        )
        for index in range(1_201)
    )
    coverage = graphiti_coverage(connection, revisions=revisions)
    connection.close()
    assert coverage["eligible_source_revisions"] == 1_201
    assert coverage["eligible_ingest_chunks"] == 1_201
    assert coverage["unresolved_gap"] == 1_201


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
    connection = __import__("sqlite3").connect(unpublished)
    spend_runs = [
        row[0]
        for row in connection.execute(
            "SELECT proving_run_id FROM unpublished_graphiti_spend ORDER BY at"
        )
    ]
    connection.close()
    assert spend_runs == ["run-1", "run-1"]


def test_latest_rights_decision_blocks_historical_backlog(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    connection.execute(
        "INSERT INTO proving_runs VALUES('run-2','2026-08-20T00:00:00.000000Z',0,0,0,0)"
    )
    connection.execute(
        """
        INSERT INTO proving_gates
        SELECT 'run-2', gate_id, status, reason
        FROM proving_gates WHERE run_id='run-1' AND gate_id!='RIGHTS_UK-01'
        """
    )
    connection.commit()
    connection.close()
    seen: list[str] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            seen.append(unit.source_id)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
    )
    assert "UK-01" not in seen
    assert report.eligible == 2


def test_current_rights_decision_does_not_authorise_a_different_endpoint(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    connection.execute(
        "UPDATE proving_observations SET url=? WHERE source_id='UK-01'",
        ("https://www.gov.uk/retired-feed",),
    )
    connection.commit()
    connection.close()
    seen: list[str] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            seen.append(unit.source_id)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
    )
    assert "UK-01" not in seen
    assert report.eligible == 2


@pytest.mark.parametrize(
    "gate_id",
    [
        "KILL_SWITCH_READY",
        "NO_ACTIVE_HUMAN_EMERGENCY_STOP",
        "PROSPECTIVE_RUN_AUTHORITY",
    ],
)
def test_latest_global_veto_blocks_all_corpus_ingest(
    tmp_path: Path, gate_id: str
) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    connection.execute(
        "UPDATE proving_gates SET status='FAIL' WHERE gate_id=?", (gate_id,)
    )
    connection.commit()
    connection.close()
    seen: list[str] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            seen.append(unit.ingest_id)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / f"{gate_id}.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
    )

    assert seen == []
    assert report.graphiti == 0
    assert report.eligible == 0


def test_ordered_chunks_wait_for_predecessor_completion(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    long_body = "ordered-corpus-" * 2_000
    feed = (
        "<rss><channel><item><guid>long</guid><title>Long</title>"
        f"<description>{long_body}</description></item></channel></rss>"
    ).encode()
    connection.execute("DELETE FROM proving_observations WHERE source_id!='UK-01'")
    connection.execute(
        "DELETE FROM proving_gates "
        "WHERE gate_id LIKE 'RIGHTS_%' AND gate_id!='RIGHTS_UK-01'"
    )
    connection.execute(
        "UPDATE proving_observations SET body=?, body_digest=? WHERE source_id='UK-01'",
        (feed, digest_bytes(feed)),
    )
    connection.commit()
    connection.close()
    calls: list[tuple[int, str | None, str]] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            calls.append(
                (unit.chunk_ordinal, unit.predecessor_ingest_id, unit.ingest_id)
            )
            return _complete(unit)

    unpublished = tmp_path / "ordered.sqlite3"
    for _ in range(2):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=Stub(),
            max_graphiti=10,
        )
    assert calls[0][0:2] == (1, None)
    assert calls[1][0] == 2
    assert calls[1][1] == calls[0][2]


def test_provider_reported_embedding_cost_is_reconciled_and_debited(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"

    class MeteredStub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            usage = {
                "usage_basis": "PROVIDER_REPORTED",
                "request_count": 2,
                "embedding_tokens": 125,
                "cost_usd_microunits": 17,
                "requests": [],
            }
            result = _complete(unit, embedding_usage=usage)
            return replace(
                result,
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


def test_completed_retry_reconciles_original_metering_and_releases_retry_reserve(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "recovered-spend.sqlite3"
    calls = 0

    class ReconciledStub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("response lost after provider write")
            usage = {
                "usage_basis": "PROVIDER_REPORTED",
                "request_count": 1,
                "embedding_tokens": 25,
                "cost_usd_microunits": 9,
                "requests": [],
            }
            result = _complete(unit, embedding_usage=usage)
            assert result.raw_receipt is not None
            raw = dict(result.raw_receipt)
            raw["provider_attempt_number"] = 1
            raw_without_digest = dict(raw)
            raw_without_digest.pop("raw_output_digest")
            raw["raw_output_digest"] = digest_bytes(
                canonical_json_bytes(raw_without_digest)
            )
            return replace(
                result,
                provider_attempt_number=1,
                receipt_digest=str(raw["raw_output_digest"]),
                raw_receipt=raw,
            )

    for _ in range(2):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=ReconciledStub(),
            max_graphiti=1,
        )
    connection = __import__("sqlite3").connect(unpublished)
    spend = connection.execute(
        """
        SELECT attempt_number, status, actual_usd_microunits, usage_basis
        FROM unpublished_graphiti_spend ORDER BY attempt_number
        """
    ).fetchall()
    receipt = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_receipts"
        ).fetchone()[0]
    )
    connection.close()
    assert spend == [
        (1, "RECONCILED", 9, "PROVIDER_REPORTED"),
        (2, "RECONCILED", 0, "NO_EMBEDDING_CALL"),
    ]
    assert receipt["provider_attempt_number"] == 1
    assert receipt["accounting"]["provider_attempt"]["spend_id"].endswith(":1")
    assert receipt["accounting"]["current_attempt"]["spend_id"].endswith(":2")


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
    returned: list[GraphitiCycleResult] = []

    class Liar:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            result = _complete(
                unit,
                chat_invocations=(
                    {
                        "provider": "cursor-agent-cli",
                        "model": "composer-2.5",
                        "outcome": "COMPLETE",
                    },
                ),
                embedding_usage={
                    "usage_basis": "PROVIDER_REPORTED",
                    "request_count": 1,
                    "embedding_tokens": 11,
                    "cost_usd_microunits": 17,
                    "requests": [],
                },
            )
            rejected = replace(
                result,
                ingest_id="00000000-0000-4000-8000-000000000099",
            )
            returned.append(rejected)
            return rejected

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
    attempt = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    spend = connection.execute(
        "SELECT status, actual_usd_microunits, usage_basis "
        "FROM unpublished_graphiti_spend"
    ).fetchone()
    connection.close()
    assert stored == 0
    assert failed == 1
    assert attempt["returned_raw_receipt"] == returned[0].raw_receipt
    assert attempt["chat_invocations"][0]["outcome"] == "COMPLETE"
    assert attempt["embedding_usage"]["cost_usd_microunits"] == 17
    assert attempt["accounting"]["actual_usd_microunits"] == 17
    assert spend == ("RECONCILED", 17, "PROVIDER_REPORTED")


def test_graphiti_cash_ceiling_holds_ingest_but_writer_continues(
    tmp_path: Path,
) -> None:
    from newsroom.control_plane.store import (
        connect,
        reconcile_graphiti_spend,
        reserve_graphiti_spend,
    )

    proving = _proving(tmp_path)
    unpublished = tmp_path / "cash-ceiling.sqlite3"
    connection = connect(str(unpublished))
    assert reserve_graphiti_spend(
        connection,
        spend_id="prior:1",
        ingest_id="prior",
        attempt_number=1,
        proving_run_id="run-1",
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=OD_011_CASH_CEILING_GBP * 1_000_000,
    )
    reconcile_graphiti_spend(
        connection,
        spend_id="prior:1",
        embedding_usage={
            "usage_basis": "PROVIDER_REPORTED",
            "request_count": 1,
            "embedding_tokens": 1,
            "cost_usd_microunits": OD_011_CASH_CEILING_GBP * 1_000_000,
            "requests": [],
        },
    )
    connection.commit()
    connection.close()

    class MustNotRun:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError(f"Graphiti ran above its ceiling: {unit.ingest_id}")

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=1,
        graphiti=MustNotRun(),
        max_graphiti=1,
    )

    connection = __import__("sqlite3").connect(unpublished)
    ledger_kinds = [
        row[0] for row in connection.execute("SELECT kind FROM ledger ORDER BY seq")
    ]
    connection.close()
    assert report.graphiti == 0
    assert report.minted == 1
    assert "GRAPHITI_SPEND_HOLD" in ledger_kinds
    assert "PRIVATE_CYCLE_CLOSE" in ledger_kinds


def test_pre_dispatch_failure_releases_graphiti_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from newsroom.control_plane import broker
    import newsroom.graphiti_adapter.real as real

    def timeout(*_args: object, **_values: object) -> object:
        raise broker.subprocess.TimeoutExpired("security", 10)

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(broker.subprocess, "run", timeout)
    proving = _proving(tmp_path)
    unpublished = tmp_path / "pre-dispatch.sqlite3"

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=EvaluationGraphitiRunner(),
        max_graphiti=1,
    )

    connection = __import__("sqlite3").connect(unpublished)
    spend = connection.execute(
        "SELECT status, actual_usd_microunits, actual_gbp_microunits, usage_basis "
        "FROM unpublished_graphiti_spend"
    ).fetchone()
    receipt = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    connection.close()
    assert report.graphiti == 1
    assert spend == ("RECONCILED", 0, 0, "NO_EMBEDDING_CALL")
    assert receipt["dispatch_state"] == "NOT_DISPATCHED"
    assert receipt["embedding_usage"]["request_count"] == 0
    assert receipt["accounting"]["unused_reservation_released"] is True


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


def test_retries_are_bounded_before_fresh_units_run(tmp_path: Path) -> None:
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
    for _ in range(3):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=AlwaysFail(),
            max_graphiti=1,
        )
    assert len(calls) == 4
    assert calls[0] == calls[1] == calls[2]
    assert calls[3] != calls[0]


def test_dead_letter_stops_retrying_a_unit(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    connection.execute("DELETE FROM proving_observations WHERE source_id!='UK-01'")
    connection.execute(
        "DELETE FROM proving_gates "
        "WHERE gate_id LIKE 'RIGHTS_%' AND gate_id!='RIGHTS_UK-01'"
    )
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
    receipts = connection.execute(
        """
        SELECT attempt_number, outcome
        FROM unpublished_graphiti_attempt_receipts
        ORDER BY attempt_number
        """
    ).fetchall()
    coverage = json.loads(
        connection.execute(
            "SELECT coverage_json FROM unpublished_graphiti_coverage ORDER BY seq DESC"
        ).fetchone()[0]
    )
    connection.close()
    assert dead == 1
    assert receipts == [(1, "FAILED"), (2, "FAILED"), (3, "FAILED")]
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


def test_result_binding_rejects_generation_and_receipt_digest_drift() -> None:
    unit = units_from(
        (
            GroupedObservation(
                "UK-01",
                "sha256:observation",
                SourceItem("UK-01", "item", "Headline", "Body", "https://item"),
                "2026-08-20T00:00:00.000000Z",
            ),
        ),
        proving_run_id="run-1",
        rights_authority_run_id="run-2",
        rights_gate_reason="current PASS",
        source_definition_url="https://source/feed",
    )[0]
    result = _complete(unit)
    with pytest.raises(ValueError, match="generation"):
        _bind_result(unit, replace(result, generation_id="stale-generation"))
    assert result.raw_receipt is not None
    tampered = {**result.raw_receipt, "episode_uuid": "foreign"}
    with pytest.raises(ValueError, match="digest"):
        _bind_result(unit, replace(result, raw_receipt=tampered))


def test_evaluation_runner_reads_provider_attempt_after_adapter_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    calls: list[str] = []
    payload = {
        "provider_attempt_number": 1,
        "episode_uuid": "episode",
        "entities": [],
        "relations": [],
        "proposals": [],
        "passages": [],
        "chat_invocations": [],
        "embedding_usage": {
            "usage_basis": "NO_EMBEDDING_CALL",
            "request_count": 0,
        },
        "usage_basis": "NO_EMBEDDING_CALL",
        "raw_output_digest": "sha256:receipt",
    }

    class Adapter:
        def execute(self, *, attempt: object, workspace_root: object) -> object:
            del attempt, workspace_root
            calls.append("execute")
            return SimpleNamespace(
                outcome=SimpleNamespace(value="COMPLETE"),
                failure_code="NONE",
                produced=SimpleNamespace(
                    raw_output_value=payload,
                    attempt_receipt_value=None,
                    proposals=(),
                    usage=SimpleNamespace(
                        request_tokens=0,
                        response_tokens=0,
                        cost_microunits=0,
                    ),
                ),
            )

    monkeypatch.setattr(real, "RealGraphitiAdapter", Adapter)
    unit = CorpusIngestUnit(
        source_id="UK-01",
        item_key="item",
        headline="Headline",
        body="Body",
        canonical_url="https://item",
        observation_digest="sha256:observation",
        observed_at="2026-08-20T00:00:00.000000Z",
        proving_run_id="run-1",
        published_at="2026-08-19T00:00:00.000000Z",
        attempt_number=2,
    )
    result = EvaluationGraphitiRunner().ingest(unit)
    assert calls == ["execute"]
    assert result.attempt_number == 2
    assert result.provider_attempt_number == 1
