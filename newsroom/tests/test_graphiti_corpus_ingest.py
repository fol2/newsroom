from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Never

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane.corpus import (
    CorpusIngestUnit,
    EligibleCorpusRevision,
    RemappedIngestEffect,
    merge_durable_revisions,
    revisions_from,
    unique_chunk_units,
    units_from,
)
from newsroom.control_plane.cycle import (
    CycleReport,
    _bind_result,
    _dispatch_rights_decision,
    _latest_run_id,
    _latest_run_with_global_authority,
    _reconcile_result_spend,
)
from newsroom.control_plane.cycle import (
    run_cycle as _run_cycle,
)
from newsroom.control_plane.editorial import (
    GroupedObservation,
    StoryCandidateRecord,
    form_candidates,
)
from newsroom.control_plane.evidence import EvidencePackage, package_for
from newsroom.control_plane.graphiti import (
    EvaluationGraphitiRunner,
    GraphitiCycleResult,
    GraphitiResultStageError,
)
from newsroom.control_plane.items import (
    SourceItem,
    parse_observation,
    parse_source_time,
)
from newsroom.control_plane.model_usage import ModelUsageService
from newsroom.control_plane.store import (
    claim_graphiti_attempt,
    connect,
    next_graphiti_attempt_number,
    reconcile_graphiti_spend,
    reserve_graphiti_spend,
)
from newsroom.control_plane.veto import VetoError
from newsroom.control_plane.writer import FixtureWriter, WriterCopy
from newsroom.effective_revision import (
    EffectiveRevisionIdentity,
    EffectiveRevisionIdentityResolver,
    create_effective_revision_schema,
    retain_effective_pull_first_seen,
    retain_effective_revision_first_seen,
    retain_observation_revision_first_seen,
)
from newsroom.graphiti_adapter.evaluation_attempt import (
    evaluation_attempt_for,
    evaluation_attempt_for_body,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_EVALUATION_DESTINATION_TOKENS,
    GRAPHITI_EVALUATION_PROVIDER_DESTINATIONS,
    GRAPHITI_EXTRACTION_TIMEOUT_MS,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_MAX_CLEANUP_TIMEOUT_MS,
    GRAPHITI_WORKSPACE_GROUP,
    OD_011_CASH_CEILING_GBP,
    OPENROUTER_EMBEDDING_SLUG,
)
from newsroom.graphiti_adapter.identity import MAX_EPISODE_BYTES, content_digest
from newsroom.graphiti_adapter.models import GraphitiAdapterContractError
from newsroom.graphiti_adapter.real import _is_source_registry_name
from newsroom.graphiti_adapter.recovery_vocabulary import (
    GraphitiRecoveryClassification,
)
from newsroom.graphiti_adapter.temporal import (
    OBSERVED_FALLBACK,
    SOURCE_PUBLISHED,
    SOURCE_UPDATED,
    map_reference_time,
)
from newsroom.increment9.proving import (
    PROVING_WRITE_TIMEOUT_SECONDS,
    SOURCE_URLS,
    ProvingError,
)
from newsroom.increment9.proving import (
    _connect as connect_proving,
)
from newsroom.increment9.rights import (
    FIXTURE_DESTINATIONS,
    RAD_01_ENDPOINT,
    RAD_01_RETIRED_ENDPOINT,
    UK_10_ENDPOINT,
    UK_10_RETIRED_ENDPOINT,
    fixture_inventory,
)
from newsroom.tests.test_control_plane_private_beta import (
    _cycle_rights_inventory,
    _evaluation_cycle_destinations,
    _fixture_evidence_package,
    _proving,
)


def run_cycle(*args: Any, **kwargs: Any) -> CycleReport:
    kwargs.setdefault("clock", lambda: datetime(2026, 8, 20, tzinfo=UTC))
    kwargs.setdefault("evidence_package_builder", _fixture_evidence_package)
    return _run_cycle(*args, **kwargs)


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


def _effective_revision_resolver(
    rows: tuple[GroupedObservation, ...],
) -> EffectiveRevisionIdentityResolver:
    connection = sqlite3.connect(":memory:")
    create_effective_revision_schema(connection)
    for row in rows:
        revision_digest = content_digest(
            headline=row.item.headline,
            body=row.item.retained_corpus_body,
            canonical_url=row.item.canonical_url,
        )
        retain_effective_revision_first_seen(
            connection,
            source_id=row.source_id,
            item_key=row.item.item_key,
            revision_digest=revision_digest,
            observed_at=row.observed_at,
        )
        retain_effective_pull_first_seen(
            connection,
            source_id=row.source_id,
            item_key=row.item.item_key,
            revision_digest=revision_digest,
            published_at=row.item.published_at,
            updated_at=row.item.updated_at,
            observed_at=row.observed_at,
        )
    return EffectiveRevisionIdentityResolver(connection)


def _effective_revision(
    *,
    source_id: str,
    item_key: str,
    headline: str,
    body: str,
    canonical_url: str,
    first_observed_at: str,
) -> EffectiveRevisionIdentity:
    return EffectiveRevisionIdentity(
        source_id=source_id,
        item_key=item_key,
        revision_digest=content_digest(
            headline=headline,
            body=body,
            canonical_url=canonical_url,
        ),
        first_observed_at=first_observed_at,
    )


def _grouped_rows(
    *, source_id: str, url: str, body: bytes, observed_at: str
) -> tuple[GroupedObservation, ...]:
    return tuple(
        GroupedObservation(
            source_id,
            digest_bytes(body),
            item,
            observed_at,
        )
        for item in parse_observation(source_id=source_id, url=url, body=body)
    )


def _insert_failed_proving_run(proving: Path, *, run_id: str, reason: str) -> None:
    connection = connect_proving(str(proving))
    connection.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES(?,'2026-08-21T00:00:00.000000Z',0,0,0,0)
        """,
        (run_id,),
    )
    connection.execute(
        """
        INSERT INTO proving_gates
        SELECT ?, gate_id,
               CASE WHEN gate_id='KILL_SWITCH_READY' THEN 'FAIL' ELSE status END,
               ?
        FROM proving_gates WHERE run_id='run-1'
        """,
        (run_id, reason),
    )
    connection.execute(
        """
        INSERT INTO proving_rights_packets
        SELECT ?, gate_id, packet_digest, packet_json, assessed_at
        FROM proving_rights_packets WHERE run_id='run-1'
        """,
        (run_id,),
    )
    connection.commit()
    connection.close()


def test_content_api_keeps_description_for_drafting_and_details_for_corpus() -> None:
    payload = json.dumps(
        {
            "title": "Immigration Rules",
            "base_path": "/guidance/immigration-rules",
            "content_id": "rules-v1",
            "description": "Short drafting summary.",
            "details": {
                "body": "<p>Complete retained policy body with material changes.</p>"
            },
        }
    ).encode("utf-8")
    item = parse_observation(
        source_id="UK-03",
        url="https://www.gov.uk/api/content/guidance/immigration-rules",
        body=payload,
    )[0]
    assert item.body == "Short drafting summary."
    assert item.retained_corpus_body == (
        "Complete retained policy body with material changes."
    )


def test_feed_keeps_summary_for_drafting_and_full_content_for_corpus() -> None:
    payload = """
    <rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
      <channel><item>
        <guid>complete-1</guid><title>Complete feed item</title>
        <description>Short feed summary.</description>
        <content:encoded><![CDATA[<p>Full retained feed content.</p>]]></content:encoded>
      </item></channel>
    </rss>
    """.encode("utf-8")
    item = parse_observation(
        source_id="UK-01",
        url="https://www.gov.uk/feed/news.atom",
        body=payload,
    )[0]
    assert item.body == "Short feed summary."
    assert item.retained_corpus_body == "Full retained feed content."


def test_feed_prefers_full_content_even_when_summary_comes_first() -> None:
    payload = """
    <rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
      <channel><item>
        <guid>order-1</guid><title>Ordered feed item</title>
        <description>Summary listed first.</description>
        <content:encoded><![CDATA[<p>Full body listed second.</p>]]></content:encoded>
      </item></channel>
    </rss>
    """.encode("utf-8")
    later_summary = """
    <rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
      <channel><item>
        <guid>order-2</guid><title>Ordered feed item</title>
        <content:encoded><![CDATA[<p>Full body listed first.</p>]]></content:encoded>
        <description>Summary listed second.</description>
      </item></channel>
    </rss>
    """.encode("utf-8")
    first = parse_observation(
        source_id="UK-01",
        url="https://www.gov.uk/feed/news.rss",
        body=payload,
    )[0]
    second = parse_observation(
        source_id="UK-01",
        url="https://www.gov.uk/feed/news.rss",
        body=later_summary,
    )[0]
    assert first.body == "Summary listed first."
    assert first.retained_corpus_body == "Full body listed second."
    assert second.body == "Summary listed second."
    assert second.retained_corpus_body == "Full body listed first."


def test_atom_keeps_summary_for_drafting_and_content_for_corpus() -> None:
    payload = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>atom-1</id>
        <title>Complete atom item</title>
        <summary>Short atom summary.</summary>
        <content type="html"><![CDATA[<p>Full retained atom content.</p>]]></content>
      </entry>
    </feed>
    """.encode("utf-8")
    item = parse_observation(
        source_id="UK-01",
        url="https://www.gov.uk/search/all.atom",
        body=payload,
    )[0]
    assert item.body == "Short atom summary."
    assert item.retained_corpus_body == "Full retained atom content."


def test_feed_without_summary_clips_full_content_for_drafting() -> None:
    retained = "full-feed-content-" * 700
    payload = (
        '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">'
        "<channel><item><guid>full-only</guid><title>Full only</title>"
        f"<content:encoded><![CDATA[{retained}]]></content:encoded>"
        "</item></channel></rss>"
    ).encode("utf-8")
    item = parse_observation(
        source_id="UK-01",
        url="https://www.gov.uk/feed/news.rss",
        body=payload,
    )[0]
    assert item.body == retained[:3_999] + "…"
    assert item.retained_corpus_body == retained


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
    timeout_diagnostics: tuple[dict[str, object], ...] = (),
    producer_failure: str | None = None,
    combined_temporal_failure_code: str | None = None,
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
        effective_revision=unit.effective_revision,
        canonical_url=unit.canonical_url,
        revision_digest=unit.revision_digest,
        representation_digest=unit.representation_digest,
        authority_ids=authority_ids,
        attempt_number=unit.attempt_number,
        predecessor_episode_uuid=unit.predecessor_ingest_id,
    )
    passage_id = str(attempt.manifest.passages[0].passage_id)
    passage_bytes = " ".join(unit.episode_body.split()).encode("utf-8")
    if len(proposals) < proposal_count:
        proposals = (
            *proposals,
            *tuple(
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
            ),
        )
    bound_proposals: list[dict[str, object]] = []
    for proposal in proposals:
        bound_evidence: list[dict[str, object]] = []
        for item in proposal.get("evidence", []):
            if not isinstance(item, dict):
                continue
            bound_item = {**item, "passage_id": passage_id}
            start_byte = bound_item.get("start_byte")
            end_byte = bound_item.get("end_byte")
            if (
                "evidence_text_digest" not in bound_item
                and isinstance(start_byte, int)
                and isinstance(end_byte, int)
            ):
                bound_item["evidence_text_digest"] = digest_bytes(
                    passage_bytes[start_byte:end_byte]
                )
            bound_evidence.append(bound_item)
        bound_proposals.append({**proposal, "evidence": bound_evidence})
    proposals_tuple = tuple(bound_proposals)
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
        "proposals": list(proposals_tuple),
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
    if timeout_diagnostics:
        raw["timeout_diagnostics"] = [dict(item) for item in timeout_diagnostics]
    if producer_failure is not None:
        raw["producer_failure"] = producer_failure
    if combined_temporal_failure_code is not None:
        raw["combined_temporal_failure_code"] = combined_temporal_failure_code
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
        proposals=proposals_tuple,
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


def _with_provider_attempt(
    result: GraphitiCycleResult,
    provider_attempt: int,
    *,
    recovery: bool = False,
) -> GraphitiCycleResult:
    raw = dict(result.raw_receipt or {})
    original_digest = raw.get("raw_output_digest")
    raw["provider_attempt_number"] = provider_attempt
    if recovery:
        raw["recovery_classification"] = (
            GraphitiRecoveryClassification.RECOVERED_IMMUTABLE_COMPLETE
        )
        raw["recovered_validated_raw_digest"] = original_digest
    raw.pop("raw_output_digest", None)
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    return replace(
        result,
        provider_attempt_number=provider_attempt,
        receipt_digest=str(raw["raw_output_digest"]),
        raw_receipt=raw,
    )


def _marker_recovery_result(
    unit: CorpusIngestUnit,
    recovery_classification: GraphitiRecoveryClassification,
) -> GraphitiCycleResult:
    result = replace(
        _complete(unit),
        outcome="AMBIGUOUS_EFFECT",
        failure_code="AMBIGUOUS_EFFECT",
    )
    raw = dict(result.raw_receipt or {})
    raw["recovery_classification"] = recovery_classification
    raw.pop("raw_output_digest", None)
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    return replace(
        result,
        receipt_digest=str(raw["raw_output_digest"]),
        raw_receipt=raw,
    )


def _provider_usage(
    *,
    cost_usd_microunits: int,
    embedding_tokens: int,
    request_count: int = 1,
) -> dict[str, object]:
    token_base, token_remainder = divmod(embedding_tokens, request_count)
    cost_base, cost_remainder = divmod(cost_usd_microunits, request_count)
    requests = [
        {
            "provider": "openrouter",
            "model": OPENROUTER_EMBEDDING_SLUG,
            "request_id": f"request-{index}",
            "prompt_tokens": token_base + int(index < token_remainder),
            "total_tokens": token_base + int(index < token_remainder),
            "cost_usd_microunits": cost_base + int(index < cost_remainder),
            "cost_reported": True,
            "outcome": "COMPLETE",
        }
        for index in range(request_count)
    ]
    return {
        "usage_basis": "PROVIDER_REPORTED",
        "requests": requests,
        "request_count": request_count,
        "embedding_tokens": embedding_tokens,
        "cost_usd_microunits": cost_usd_microunits,
    }


def _provider_usage_variant(
    *,
    top_updates: dict[str, object] | None = None,
    request_updates: dict[str, object] | None = None,
    omit_top: str | None = None,
    omit_request: str | None = None,
) -> dict[str, object]:
    usage = _provider_usage(cost_usd_microunits=9, embedding_tokens=25)
    if top_updates is not None:
        usage.update(top_updates)
    if request_updates is not None:
        requests = usage["requests"]
        assert isinstance(requests, list) and len(requests) == 1
        request = requests[0]
        assert isinstance(request, dict)
        request.update(request_updates)
    if omit_request is not None:
        requests = usage["requests"]
        assert isinstance(requests, list) and len(requests) == 1
        request = requests[0]
        assert isinstance(request, dict)
        request.pop(omit_request)
    if omit_top is not None:
        usage.pop(omit_top)
    return usage


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
    effective_revision = _effective_revision(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        first_observed_at="2026-08-16T21:41:34.000000Z",
    )
    unit = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs",
        observed_at="2026-08-16T21:41:34.000000Z",
        proving_run_id="run-1",
        effective_revision=effective_revision,
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
        effective_revision=effective_revision,
    )
    assert unit.ingest_id == again.ingest_id
    assert "HK-04" not in unit.episode_body
    drifted = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs-later",
        observed_at="2026-08-20T00:00:00.000000Z",
        proving_run_id="run-2",
        effective_revision=_effective_revision(
            source_id="HK-04",
            item_key="q7",
            headline="立法會質詢",
            body="科技與生活科課程",
            canonical_url="https://www.edb.gov.hk/example",
            first_observed_at="2026-08-20T00:00:00.000000Z",
        ),
    )
    assert drifted.ingest_id == unit.ingest_id
    assert drifted.revision_id == unit.revision_id
    assert drifted.representation_digest == unit.representation_digest
    assert unit.temporal().basis == OBSERVED_FALLBACK
    assert unit.temporal().reference_time.to_text() == ("2026-08-16T21:41:34.000000Z")
    assert drifted.temporal().reference_time.to_text() == (
        "2026-08-20T00:00:00.000000Z"
    )
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
    kinds = [
        row[0] for row in connection.execute("SELECT kind FROM ledger ORDER BY seq")
    ]
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
    assert (
        stored["proposals"][0]["evidence"][0]["passage_id"]
        == (stored["passages"][0]["passage_id"])
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
    assert (
        coverage["unpublished_payload_count"]
        != coverage["successfully_ingested_revisions"]
    )
    assert coverage["reserved_spend"] is False
    assert coverage["outstanding_reserved_spend_gbp_microunits"] == 0
    assert coverage["actual_metered_spend_microunits"] == 0
    assert coverage["admission_backlog"] == 3
    assert coverage["retry_count"] == 0
    assert coverage["dead_letter_count"] == 0
    assert coverage["ingest_watermark_at"]


def test_graphiti_owner_stop_proof_reuses_the_active_rights_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsroom.control_plane import paths as control_paths

    proving = _proving(tmp_path)
    unpublished = tmp_path / "owner-stop-rights-fence.sqlite3"
    monkeypatch.setattr(control_paths, "CANONICAL_PROVING_STORE", proving)
    monkeypatch.setattr(control_paths, "CANONICAL_UNPUBLISHED_STORE", unpublished)
    owner_stop_checks = 0

    class FencedUsageGraphiti:
        requires_canonical_control_plane_stores = True

        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError("governed usage path required")

        def ingest_until(
            self, unit: CorpusIngestUnit, *, deadline: datetime
        ) -> GraphitiCycleResult:
            raise AssertionError("governed usage path required")

        def ingest_with_usage(
            self,
            unit: CorpusIngestUnit,
            *,
            model_usage: ModelUsageService,
            cycle_id: str,
            dispatch_authority: dict[str, object],
            owner_stop_check: Any,
            deadline: datetime | None = None,
        ) -> GraphitiCycleResult:
            nonlocal owner_stop_checks
            del model_usage, cycle_id, dispatch_authority, deadline
            owner_stop_check()
            owner_stop_check()
            owner_stop_checks += 2
            return _complete(unit, proposal_count=0)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=FencedUsageGraphiti(),
        max_graphiti=1,
        model_usage=ModelUsageService(str(unpublished)),
    )

    assert report.graphiti == 1
    assert owner_stop_checks == 2


def test_units_from_observations_cover_items_not_candidates() -> None:
    item = SourceItem("HK-04", "k", "headline", "body", "https://example.invalid/a")
    rows = (
        GroupedObservation("HK-04", "sha256:a", item, "2026-08-16T21:41:34.000000Z"),
        GroupedObservation("RAD-02", "sha256:b", item, "2026-08-16T21:41:34.000000Z"),
    )
    # Same URL/item_key would collapse candidates; ingest still has two source rows
    # because source_id differs in ingest_key.
    units = units_from(
        rows,
        proving_run_id="run-1",
        effective_revision_resolver=_effective_revision_resolver(rows),
    )
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
    resolver = _effective_revision_resolver(rows)
    first = units_from(
        rows,
        proving_run_id="run-1",
        rights_authority_run_id="run-2",
        source_definition_url="https://source/feed-v1",
        effective_revision_resolver=resolver,
    )
    changed = units_from(
        rows[:1],
        proving_run_id="run-1",
        rights_authority_run_id="run-2",
        source_definition_url="https://source/feed-v2",
        effective_revision_resolver=resolver,
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
    resolver = _effective_revision_resolver((first_row, changed_row))
    first = units_from(
        (first_row,),
        proving_run_id="run-1",
        effective_revision_resolver=resolver,
    )[0]
    changed = units_from(
        (changed_row,),
        proving_run_id="run-1",
        effective_revision_resolver=resolver,
    )[0]
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
    resolver = _effective_revision_resolver((first_row, changed_row))
    first = units_from(
        (first_row,),
        proving_run_id="run-1",
        effective_revision_resolver=resolver,
    )[0]
    changed = units_from(
        (changed_row,),
        proving_run_id="run-2",
        effective_revision_resolver=resolver,
    )[0]
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
    resolver = _effective_revision_resolver((first_row, repeated_row))
    first = units_from(
        (first_row,),
        proving_run_id="run-1",
        effective_revision_resolver=resolver,
    )[0]
    repeated = units_from(
        (repeated_row,),
        proving_run_id="run-2",
        effective_revision_resolver=resolver,
    )[0]
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
    effective_revision = _effective_revision(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        first_observed_at="2026-08-16T21:41:34.000000Z",
    )
    first = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs-a",
        observed_at="2026-08-16T21:41:34.000000Z",
        proving_run_id="run-1",
        effective_revision=effective_revision,
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
        effective_revision=effective_revision,
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
        effective_revision=effective_revision,
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
    assert fallback_later.ingest_id == fallback_earlier.ingest_id
    assert fallback_later.revision_id == fallback_earlier.revision_id


def test_fallback_observations_share_one_effective_revision() -> None:
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
        units_from(
            (first_row, repeated_row),
            proving_run_id="run-1",
            effective_revision_resolver=_effective_revision_resolver(
                (first_row, repeated_row)
            ),
        )
    )

    assert len(revisions) == 1
    assert len(revisions[0].ingest_ids) == 1


def test_174_unchanged_polls_retain_one_effective_revision() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE proving_observations(run_id TEXT PRIMARY KEY, body BLOB NOT NULL)"
    )
    create_effective_revision_schema(connection)
    body = b"<feed><entry><title>a</title></entry></feed>"
    url = "https://www.gov.uk/search/all.atom"
    rows: list[GroupedObservation] = []
    for ordinal in range(174):
        observed_at = f"2026-08-20T00:00:00.{ordinal:06d}Z"
        connection.execute(
            "INSERT INTO proving_observations VALUES(?,?)",
            (f"run-{ordinal}", body),
        )
        retain_observation_revision_first_seen(
            connection,
            source_id="UK-01",
            url=url,
            body=body,
            observed_at=observed_at,
        )
        rows.extend(
            _grouped_rows(
                source_id="UK-01", url=url, body=body, observed_at=observed_at
            )
        )
    units = units_from(
        tuple(rows),
        proving_run_id="run-173",
        effective_revision_resolver=EffectiveRevisionIdentityResolver(connection),
    )
    assert (
        connection.execute("SELECT COUNT(*) FROM proving_observations").fetchone()[0]
        == 174
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM proving_revision_first_seen"
        ).fetchone()[0]
        == 1
    )
    assert (
        connection.execute(
            "SELECT first_seen_at FROM proving_revision_first_seen"
        ).fetchone()[0]
        == "2026-08-20T00:00:00.000000Z"
    )
    assert len(revisions_from(units)) == 1
    assert len({unit.ingest_id for unit in units}) == 1
    connection.close()


def test_200_item_repeat_has_zero_new_effective_pulls() -> None:
    body = (
        "<feed>"
        + "".join(
            f"<entry><id>{ordinal}</id><title>Item {ordinal}</title></entry>"
            for ordinal in range(200)
        )
        + "</feed>"
    ).encode()
    url = "https://www.gov.uk/search/all.atom"
    first_rows = _grouped_rows(
        source_id="UK-01",
        url=url,
        body=body,
        observed_at="2026-08-20T00:00:00.000000Z",
    )
    repeated_rows = _grouped_rows(
        source_id="UK-01",
        url=url,
        body=body,
        observed_at="2026-08-20T01:00:00.000000Z",
    )
    resolver = _effective_revision_resolver(first_rows + repeated_rows)
    first = units_from(
        first_rows,
        proving_run_id="run-1",
        effective_revision_resolver=resolver,
    )
    repeated = units_from(
        repeated_rows,
        proving_run_id="run-2",
        effective_revision_resolver=resolver,
    )
    assert len(first) == 200
    assert {unit.ingest_id for unit in repeated} - {
        unit.ingest_id for unit in first
    } == set()


def test_two_added_entries_mint_exactly_two_effective_revisions() -> None:
    def feed(count: int) -> bytes:
        return (
            "<feed>"
            + "".join(
                f"<entry><id>{ordinal}</id><title>Item {ordinal}</title></entry>"
                for ordinal in range(count)
            )
            + "</feed>"
        ).encode()

    url = "https://www.gov.uk/search/all.atom"
    first_rows = _grouped_rows(
        source_id="UK-01",
        url=url,
        body=feed(200),
        observed_at="2026-08-20T00:00:00.000000Z",
    )
    expanded_rows = _grouped_rows(
        source_id="UK-01",
        url=url,
        body=feed(202),
        observed_at="2026-08-20T01:00:00.000000Z",
    )
    resolver = _effective_revision_resolver(first_rows + expanded_rows)
    first = units_from(
        first_rows,
        proving_run_id="run-1",
        effective_revision_resolver=resolver,
    )
    expanded = units_from(
        expanded_rows,
        proving_run_id="run-2",
        effective_revision_resolver=resolver,
    )
    assert (
        len(
            {unit.revision_id for unit in expanded}
            - {unit.revision_id for unit in first}
        )
        == 2
    )


def test_changed_retained_content_uses_changed_revision_first_observation() -> None:
    url = "https://www.gov.uk/search/all.atom"
    first_body = (
        b"<feed><entry><id>one</id><title>One</title>"
        b"<summary>first</summary></entry></feed>"
    )
    changed_body = (
        b"<feed><entry><id>one</id><title>One</title>"
        b"<summary>changed</summary></entry></feed>"
    )
    first_rows = _grouped_rows(
        source_id="UK-01",
        url=url,
        body=first_body,
        observed_at="2026-08-20T00:00:00.000000Z",
    )
    changed_rows = _grouped_rows(
        source_id="UK-01",
        url=url,
        body=changed_body,
        observed_at="2026-08-20T01:00:00.000000Z",
    )
    resolver = _effective_revision_resolver(first_rows + changed_rows)
    first = units_from(
        first_rows,
        proving_run_id="run-1",
        effective_revision_resolver=resolver,
    )[0]
    changed = units_from(
        changed_rows,
        proving_run_id="run-2",
        effective_revision_resolver=resolver,
    )[0]
    assert first.revision_id != changed.revision_id
    assert changed.effective_revision.first_observed_at == (
        "2026-08-20T01:00:00.000000Z"
    )
    assert changed.authority is not None
    revision_record = next(
        record
        for record in changed.authority.records
        if record["record_type"] == "SOURCE_REVISION"
    )
    assert revision_record["observed_fallback_at"] == ("2026-08-20T01:00:00.000000Z")


def test_changed_source_marker_is_deterministic_and_covered_once() -> None:
    first_row = GroupedObservation(
        "UK-01",
        "sha256:first",
        SourceItem(
            "UK-01",
            "one",
            "One",
            "Body",
            "https://item/one",
            updated_at="2026-08-20T00:00:00.000000Z",
        ),
        "2026-08-20T00:01:00.000000Z",
    )
    changed_row = replace(
        first_row,
        observation_digest="sha256:changed",
        item=replace(
            first_row.item,
            updated_at="2026-08-20T02:00:00.000000Z",
        ),
        observed_at="2026-08-20T02:01:00.000000Z",
    )
    repeated_row = replace(
        changed_row,
        observation_digest="sha256:repeated",
        observed_at="2026-08-20T03:01:00.000000Z",
    )
    resolver = _effective_revision_resolver((first_row, changed_row, repeated_row))
    first = units_from(
        (first_row,),
        proving_run_id="run-1",
        effective_revision_resolver=resolver,
    )[0]
    changed = units_from(
        (changed_row, repeated_row),
        proving_run_id="run-2",
        effective_revision_resolver=resolver,
    )
    assert first.revision_id != changed[0].revision_id
    assert changed[0].revision_id == changed[1].revision_id
    assert len(revisions_from(changed)) == 1
    assert len(revisions_from(changed)[0].ingest_ids) == 1
    combined = (first, changed[0])
    assert len(unique_chunk_units(combined)) == 2
    assert len(revisions_from(combined)) == 2
    assert {unit.ingest_id for unit in unique_chunk_units(combined)} == {
        first.ingest_id,
        changed[0].ingest_id,
    }
    coverage = revisions_from(combined)
    by_updated = {item.updated_at: item for item in coverage}
    assert by_updated[first_row.item.updated_at].observed_at == first_row.observed_at
    assert (
        by_updated[changed_row.item.updated_at].observed_at == changed_row.observed_at
    )
    assert changed[0].effective_revision.first_observed_at == (
        first.effective_revision.first_observed_at
    )
    assert by_updated[changed_row.item.updated_at].observed_at != (
        first.effective_revision.first_observed_at
    )


def test_undated_marker_transition_uses_effective_pull_first_observation() -> None:
    dated = GroupedObservation(
        "UK-01",
        "sha256:dated",
        SourceItem(
            "UK-01",
            "one",
            "One",
            "Body",
            "https://item/one",
            updated_at="2026-08-20T00:00:00.000000Z",
        ),
        "2026-08-20T00:01:00.000000Z",
    )
    undated = replace(
        dated,
        observation_digest="sha256:undated",
        item=replace(dated.item, updated_at=None),
        observed_at="2026-08-20T02:01:00.000000Z",
    )
    unit = units_from(
        (undated,),
        proving_run_id="run-2",
        effective_revision_resolver=_effective_revision_resolver((dated, undated)),
    )[0]
    assert unit.temporal().reference_time.to_text() == undated.observed_at
    assert revisions_from((unit,))[0].source_time == undated.observed_at
    assert unit.authority is not None
    revision_record = next(
        record
        for record in unit.authority.records
        if record["record_type"] == "SOURCE_REVISION"
    )
    assert revision_record["observed_fallback_at"] == undated.observed_at


def test_rights_renewal_restart_and_replay_create_zero_new_revisions(
    tmp_path: Path,
) -> None:
    state = tmp_path / "effective-revisions.sqlite3"
    connection = sqlite3.connect(state)
    create_effective_revision_schema(connection)
    row = GroupedObservation(
        "UK-01",
        "sha256:first",
        SourceItem("UK-01", "one", "One", "Body", "https://item/one"),
        "2026-08-20T00:00:00.000000Z",
    )
    retain_effective_revision_first_seen(
        connection,
        source_id=row.source_id,
        item_key=row.item.item_key,
        revision_digest=content_digest(
            headline=row.item.headline,
            body=row.item.retained_corpus_body,
            canonical_url=row.item.canonical_url,
        ),
        observed_at=row.observed_at,
    )
    connection.commit()
    first = units_from(
        (row,),
        proving_run_id="run-1",
        rights_authority_run_id="rights-1",
        effective_revision_resolver=EffectiveRevisionIdentityResolver(connection),
    )[0]
    connection.close()
    restarted = sqlite3.connect(state)
    replayed = units_from(
        (replace(row, observed_at="2026-08-21T00:00:00.000000Z"),),
        proving_run_id="run-2",
        rights_authority_run_id="rights-2",
        effective_revision_resolver=EffectiveRevisionIdentityResolver(restarted),
    )[0]
    restarted.close()
    assert first.revision_id == replayed.revision_id
    assert first.ingest_id == replayed.ingest_id


def test_backlog_with_recent_first_seen_row_still_backsills_older_revisions(
    tmp_path: Path,
) -> None:
    """Verify backfill detects missing rows even when MAX(first_seen) >= MAX(obs).

    Reproduces: store with some missing rows, a recent first-seen row whose timestamp
    equals the latest observation. Without watermark, guard incorrectly skips backfill.
    """
    proving = _proving(tmp_path)
    connection = connect_proving(str(proving))

    body = b"<feed><entry><id>item</id><title>Item</title></entry></feed>"
    url = "https://www.gov.uk/search/all.atom"
    digest = digest_bytes(body)

    # Insert old observations (these will be missing first-seen rows)
    for i in range(5):
        connection.execute(
            """
            INSERT INTO proving_observations(
                source_id, run_id, fetched_at, url, status_code, body_digest, body, item_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "UK-01",
                f"run-old-{i}",
                f"2026-08-20T{i:02d}:00:00.000000Z",
                url,
                200,
                digest,
                body,
                1,
            ),
        )

    # Insert a recent observation that will be added to first-seen by _put()-like logic
    latest_time = "2026-08-20T10:00:00.000000Z"
    connection.execute(
        """
        INSERT INTO proving_observations(
            source_id, run_id, fetched_at, url, status_code, body_digest, body, item_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "UK-01",
            "run-recent",
            latest_time,
            url,
            200,
            digest,
            body,
            1,
        ),
    )

    # Simulate _put() having written ONE first-seen row with the latest timestamp
    # This makes MAX(first_seen_at) == MAX(fetched_at) but many rows are still missing
    connection.execute(
        """
        INSERT INTO proving_revision_first_seen(
            source_id, item_key, revision_digest, first_seen_at
        ) VALUES(?, ?, ?, ?)
        """,
        ("UK-01", "item", "sha256:dummy", latest_time),
    )
    connection.commit()
    connection.close()

    # Now call backfill: the old bug's guard would return 0 because MAX(first_seen) == MAX(obs)
    # But there are still missing rows from older observations
    connection = connect_proving(str(proving))
    from newsroom.effective_revision import backfill_missing_first_seen

    rows_written = backfill_missing_first_seen(connection)
    connection.close()

    # Verify backfill actually ran and found missing rows
    assert rows_written > 0, "Backfill should have written rows for old observations"

    # Verify watermark was set
    connection = connect_proving(str(proving))
    watermark = connection.execute(
        "SELECT processed_until FROM proving_backfill_watermark"
    ).fetchone()
    assert watermark is not None, "Watermark should have been written"
    assert watermark[0] == latest_time, (
        f"Watermark should equal latest observation: {watermark[0]} vs {latest_time}"
    )
    connection.close()


def test_backlog_revisions_without_first_seen_self_heal_deterministically(
    tmp_path: Path,
) -> None:
    """Verify run_cycle backfills pre-existing revisions without first-seen rows.

    Simulates transition: observations exist without first-seen rows.
    run_cycle must backfill deterministically and produce stable identities.
    """
    proving = _proving(tmp_path)

    # Insert observations without first-seen rows (simulating backlog)
    body = b"<feed><entry><id>item-one</id><title>Item One</title><summary>Content</summary></entry></feed>"
    url = "https://www.gov.uk/search/all.atom"
    connection = connect_proving(str(proving))

    for observed_at in (
        "2026-08-20T00:00:00.000000Z",
        "2026-08-20T01:00:00.000000Z",
        "2026-08-20T02:00:00.000000Z",
    ):
        connection.execute(
            """
            INSERT INTO proving_observations(
                source_id, run_id, fetched_at, url, status_code, body_digest, body, item_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "UK-01",
                "backlog-run",
                observed_at,
                url,
                200,
                digest_bytes(body),
                body,
                1,
            ),
        )
    connection.commit()
    connection.close()

    # First run_cycle with backlog: backfill should run and complete successfully
    unpublished_1 = tmp_path / "unpublished-1.sqlite3"
    report_1 = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished_1),
        writer=FixtureWriter(),
        max_writes=0,
        max_graphiti=0,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert report_1.eligible >= 1, (
        "First run_cycle should backfill and process observations"
    )

    # Verify that first-seen rows were written
    connection = connect_proving(str(proving))
    first_seen_count = connection.execute(
        "SELECT COUNT(*) FROM proving_revision_first_seen"
    ).fetchone()[0]
    connection.close()
    assert first_seen_count > 0, "Backfill should have written first-seen rows"

    # Second run_cycle with same data: should skip backfill (no-op case)
    unpublished_2 = tmp_path / "unpublished-2.sqlite3"
    report_2 = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished_2),
        writer=FixtureWriter(),
        max_writes=0,
        max_graphiti=0,
        clock=lambda: datetime(2026, 8, 22, tzinfo=UTC),
    )
    # Second run should have same eligible count (same observations, no new data)
    assert report_2.eligible == report_1.eligible, (
        "Identical input should produce identical eligible count"
    )


def test_legacy_store_without_watermark_table_self_heals(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    connection = sqlite3.connect(proving)
    connection.execute("DROP TABLE IF EXISTS proving_backfill_watermark")
    connection.commit()
    from newsroom.effective_revision import backfill_missing_first_seen

    written = backfill_missing_first_seen(connection)
    watermark = connection.execute(
        "SELECT processed_until FROM proving_backfill_watermark"
    ).fetchone()
    connection.close()
    assert written >= 0
    assert watermark is not None


def test_long_body_is_chunked_not_truncated() -> None:
    body = "a" * (MAX_EPISODE_BYTES + 50)
    item = SourceItem("UK-01", "long", "headline", body, "https://example.invalid/long")
    rows = (
        GroupedObservation("UK-01", "sha256:long", item, "2026-08-16T21:41:34.000000Z"),
    )
    units = units_from(
        rows,
        proving_run_id="run-1",
        effective_revision_resolver=_effective_revision_resolver(rows),
    )
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
    ordered = sorted(units, key=lambda unit: unit.chunk_ordinal)
    assert ordered[0].predecessor_ingest_id is None
    assert ordered[1].predecessor_ingest_id == ordered[0].ingest_id
    repeated_rows = (
        replace(
            rows[0],
            observation_digest="sha256:long-repeat",
            observed_at="2026-08-20T00:00:00.000000Z",
        ),
    )
    repeated = units_from(
        repeated_rows,
        proving_run_id="run-2",
        effective_revision_resolver=_effective_revision_resolver(rows + repeated_rows),
    )
    assert {unit.revision_id for unit in repeated} == {revisions[0].revision_id}
    assert {unit.ingest_id for unit in repeated} == set(revisions[0].ingest_ids)


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
        effective_revision_resolver=_effective_revision_resolver(
            (
                GroupedObservation(
                    "UK-01",
                    "sha256:long-parser",
                    item,
                    "2026-08-16T21:41:34.000000Z",
                ),
            )
        ),
    )
    assert retained in "".join(
        unit.episode_body
        for unit in sorted(units, key=lambda value: value.chunk_ordinal)
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
    assert coverage["effective_pull_count"] == 2
    assert coverage["eligible_source_revisions"] == 2
    assert coverage["eligible_ingest_chunks"] == 3
    assert coverage["successfully_ingested_revisions"] == 1
    assert coverage["contiguous_input_watermark"] is None
    assert coverage["ingest_watermark_at"] is None
    assert coverage["oldest_unresolved_gap"]["revision_id"] == "revision-1"
    assert coverage["admission_backlog"] == 4


def test_remapped_effect_does_not_cover_a_different_version_marker(
    tmp_path: Path,
) -> None:
    from newsroom.control_plane.store import (
        connect,
        graphiti_coverage,
        insert_graphiti_ingest,
    )

    connection = connect(str(tmp_path / "alias-coverage.sqlite3"))
    digest = "sha256:" + ("ab" * 32)
    first_marker = "2026-08-20T00:00:00.000000Z"
    later_marker = "2026-08-20T02:00:00.000000Z"
    insert_graphiti_ingest(
        connection,
        ingest_id="ingest-old",
        source_id="UK-01",
        item_key="one",
        outcome="COMPLETE",
        proposal_count=1,
        entity_count=1,
        relation_count=0,
        failure_code="NONE",
        temporal_basis="SOURCE_UPDATED",
        reference_time=first_marker,
        generation_id="generation",
        receipt_digest="sha256:receipt",
    )
    connection.execute(
        """
        INSERT INTO unpublished_effective_revision_remap(
            mapping_id, source_id, item_key, revision_digest, published_at,
            updated_at, old_observed_fallback_at, new_first_observed_at, kind,
            retention_window_bounded_inaccuracy, old_ingest_id, new_ingest_id, at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "sha256:" + ("11" * 32),
            "UK-01",
            "one",
            digest,
            "",
            first_marker,
            None,
            first_marker,
            "RETAINED_EFFECT_REMAP",
            0,
            "ingest-old",
            "ingest-new",
            first_marker,
        ),
    )
    covered = EligibleCorpusRevision(
        "revision-a",
        "UK-01",
        "one",
        first_marker,
        first_marker,
        ("ingest-new",),
        digest,
        None,
        first_marker,
    )
    uncovered = EligibleCorpusRevision(
        "revision-b",
        "UK-01",
        "one",
        later_marker,
        later_marker,
        ("ingest-later",),
        digest,
        None,
        later_marker,
    )
    coverage = graphiti_coverage(connection, revisions=(covered, uncovered))
    connection.close()
    assert coverage["successfully_ingested_revisions"] == 1
    assert coverage["unresolved_gap"] == 1
    assert coverage["oldest_unresolved_gap"]["revision_id"] == "revision-b"


def test_remapped_chunks_preserve_success_and_dead_letter_lineage(
    tmp_path: Path,
) -> None:
    from newsroom.control_plane.store import (
        graphiti_coverage,
        graphiti_failure_state,
        has_graphiti_ingest,
        insert_graphiti_ingest,
    )

    connection = connect(str(tmp_path / "chunk-lineage.sqlite3"))
    insert_graphiti_ingest(
        connection,
        ingest_id="old-1",
        source_id="UK-01",
        item_key="one",
        outcome="COMPLETE",
        proposal_count=1,
        entity_count=1,
        relation_count=0,
        failure_code="NONE",
        temporal_basis="OBSERVED_FALLBACK",
        reference_time="2026-08-20T00:00:00.000000Z",
        generation_id="generation",
        receipt_digest="sha256:receipt",
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_failures VALUES(?,?,?,?,?,?,?,?)",
        (
            "old-2",
            "UK-01",
            "one",
            3,
            "FAILED",
            "PROVIDER_ERROR",
            1,
            "2026-08-20T00:00:00.000000Z",
        ),
    )
    for ordinal, old_id, new_id in (
        (1, "old-1", "new-1"),
        (2, "old-2", "new-2"),
    ):
        connection.execute(
            """
            INSERT INTO unpublished_effective_revision_remap(
                mapping_id, source_id, item_key, revision_digest, published_at,
                updated_at, new_first_observed_at, kind,
                retention_window_bounded_inaccuracy, old_ingest_id,
                new_ingest_id, at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"mapping-{ordinal}",
                "UK-01",
                "one",
                "sha256:revision",
                "",
                "",
                "2026-08-20T00:00:00.000000Z",
                "RETAINED_LINEAGE_REMAP",
                0,
                old_id,
                new_id,
                "2026-08-20T00:00:00.000000Z",
            ),
        )
    revision = EligibleCorpusRevision(
        "revision",
        "UK-01",
        "one",
        "2026-08-20T00:00:00.000000Z",
        "2026-08-20T00:00:00.000000Z",
        ("new-1", "new-2"),
        "sha256:revision",
    )

    coverage = graphiti_coverage(connection, revisions=(revision,))
    assert has_graphiti_ingest(connection, "new-1") is True
    assert has_graphiti_ingest(connection, "new-2") is False
    assert graphiti_failure_state(connection, "new-2") == (3, True)
    assert coverage["successfully_ingested_revisions"] == 0
    assert coverage["unresolved_gap"] == 1
    assert coverage["dead_letter_revisions"] == 1
    connection.close()


def test_marker_specific_effect_survives_after_raw_body_retention() -> None:
    digest = "sha256:" + ("ab" * 32)
    first_seen = "2026-08-20T00:00:00.000000Z"
    marker = "2026-08-20T02:00:00.000000Z"

    revisions = merge_durable_revisions(
        window_revisions=(),
        first_seen=(("UK-01", "one", digest, first_seen),),
        remapped_effects=(
            RemappedIngestEffect(
                "UK-01", "one", digest, "", marker, "ingest-old", "ingest-new"
            ),
        ),
        permitted_source_ids=frozenset({"UK-01"}),
    )

    assert len(revisions) == 1
    assert revisions[0].published_at is None
    assert revisions[0].updated_at == marker
    assert revisions[0].ingest_ids == ("ingest-old",)


def test_durable_landed_time_wins_over_window_reconstruction() -> None:
    digest = "sha256:" + ("ab" * 32)
    landed = EligibleCorpusRevision(
        "revision",
        "UK-01",
        "one",
        "2026-08-20T00:00:00.000000Z",
        "2026-08-20T00:00:00.000000Z",
        (),
        digest,
    )
    reconstructed = replace(
        landed,
        observed_at="2026-08-20T06:00:00.000000Z",
        source_time="2026-08-20T06:00:00.000000Z",
    )

    revisions = merge_durable_revisions(
        window_revisions=(reconstructed,),
        first_seen=(),
        landed=(landed,),
    )

    assert revisions == (landed,)


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
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES('run-2','2026-08-20T00:00:00.000000Z',0,0,0,0)
        """
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
    connection.execute(
        """
        INSERT INTO proving_rights_packets
        SELECT 'run-2', gate_id, packet_digest, packet_json, assessed_at
        FROM proving_rights_packets WHERE run_id='run-1'
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
    assert report.eligible == 3
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


@pytest.mark.parametrize(
    ("stored_error", "body"),
    [
        ("content-malformed-xml", None),
        (None, b"<rss><channel>"),
        (None, b"<rss><channel><item/></channel></rss>"),
        (
            None,
            b"<rss><channel><item><title>&lt;br&gt;</title></item></channel></rss>",
        ),
        (
            None,
            (
                "<rss><channel><item>"
                + "&lt;br&gt;" * 60
                + "Useful headline</item></channel></rss>"
            ).encode(),
        ),
    ],
)
def test_malformed_success_observation_is_not_admitted_to_cycle(
    tmp_path: Path, stored_error: str | None, body: bytes | None
) -> None:
    proving = _proving(tmp_path)
    connection = sqlite3.connect(proving)
    connection.execute(
        """
        UPDATE proving_observations
        SET error=?, body=COALESCE(?, body)
        WHERE run_id='run-1' AND source_id='UK-01'
        """,
        (stored_error, body),
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
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
    )

    assert "UK-01" not in seen
    assert report.sources == 2
    assert report.eligible == 3


def test_raw_http_older_than_seven_days_is_not_admitted_to_cycle(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    seen: list[str] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            seen.append(unit.source_id)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
        clock=lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert seen == []
    assert report.sources == 0
    assert report.eligible == 3
    assert report.effective_pull_count == 3


def test_latest_rights_decision_blocks_historical_backlog(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    connection.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES('run-2','2026-08-20T00:00:00.000000Z',0,0,0,0)
        """
    )
    connection.execute(
        """
        INSERT INTO proving_gates
        SELECT 'run-2', gate_id, status, reason
        FROM proving_gates WHERE run_id='run-1' AND gate_id!='RIGHTS_UK-01'
        """
    )
    connection.execute(
        """
        INSERT INTO proving_rights_packets
        SELECT 'run-2', gate_id, packet_digest, packet_json, assessed_at
        FROM proving_rights_packets
        WHERE run_id='run-1' AND gate_id!='RIGHTS_UK-01'
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


def test_dispatch_veto_and_source_rights_use_one_sqlite_snapshot(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    decision = _dispatch_rights_decision(
        connection,
        source_id="UK-01",
        source_url=SOURCE_URLS["UK-01"],
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    connection.close()
    assert decision is not None
    assert decision["rights_authority_run_id"] == "run-1"
    reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    assert len(reads) == 1
    combined = reads[0].upper()
    assert "PROVING_RUNS" in combined
    assert "PROVING_GATES" in combined
    assert "PROVING_RIGHTS_PACKETS" in combined


def test_dispatch_requires_rights_beyond_the_full_extraction_deadline(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    gate_id = "RIGHTS_UK-01"
    evaluated_at = "2026-08-21T00:00:00.000000Z"
    required_valid_until = "2026-08-21T00:03:00.000000Z"

    def replace_expiry(expires_at: str, gate_ids: tuple[str, ...] = (gate_id,)) -> None:
        connection = sqlite3.connect(proving)
        for target_gate_id in gate_ids:
            packet = fixture_inventory(
                gate=target_gate_id,
                destinations=_evaluation_cycle_destinations(),
                now=evaluated_at,
                issued_at="2026-01-01T00:00:00.000000Z",
                expires_at=expires_at,
            )
            packet_bytes = canonical_json_bytes(packet)
            connection.execute(
                """
                UPDATE proving_rights_packets
                SET packet_digest=?, packet_json=?
                WHERE run_id='run-1' AND gate_id=?
                """,
                (
                    digest_bytes(packet_bytes),
                    packet_bytes.decode("utf-8"),
                    target_gate_id,
                ),
            )
        connection.commit()
        connection.close()

    connection = sqlite3.connect(proving)
    for expires_at in (
        "2026-08-21T00:02:59.000000Z",
        "2026-08-21T00:03:00.000000Z",
    ):
        connection.close()
        replace_expiry(expires_at)
        connection = sqlite3.connect(proving)
        assert (
            _dispatch_rights_decision(
                connection,
                source_id="UK-01",
                source_url=SOURCE_URLS["UK-01"],
                evaluated_at=evaluated_at,
                required_valid_until=required_valid_until,
            )
            is None
        )
    connection.close()

    replace_expiry("2026-08-21T00:03:00.000001Z")
    connection = sqlite3.connect(proving)
    assert (
        _dispatch_rights_decision(
            connection,
            source_id="UK-01",
            source_url=SOURCE_URLS["UK-01"],
            evaluated_at=evaluated_at,
            required_valid_until=required_valid_until,
        )
        is not None
    )
    connection.close()

    connection = sqlite3.connect(proving)
    all_gate_ids = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT gate_id FROM proving_rights_packets WHERE run_id='run-1'"
        )
    )
    connection.close()
    replace_expiry("2026-08-21T00:03:00.000000Z", all_gate_ids)

    class MustNotDispatch:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError(f"expiring rights reached provider: {unit.ingest_id}")

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "expiring-rights.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=MustNotDispatch(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert report.graphiti == 0
    assert report.eligible == 0


def test_newer_failed_proving_run_blocks_dispatch_despite_older_pass(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    connection = __import__("sqlite3").connect(proving)
    passing = _dispatch_rights_decision(
        connection,
        source_id="UK-01",
        source_url=SOURCE_URLS["UK-01"],
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    connection.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES('run-2','2026-08-21T00:00:00.000000Z',0,0,0,0)
        """
    )
    connection.execute(
        """
        INSERT INTO proving_gates
        SELECT 'run-2', gate_id,
               CASE WHEN gate_id='KILL_SWITCH_READY' THEN 'FAIL' ELSE status END,
               'later veto'
        FROM proving_gates WHERE run_id='run-1'
        """
    )
    connection.execute(
        """
        INSERT INTO proving_rights_packets
        SELECT 'run-2', gate_id, packet_digest, packet_json, assessed_at
        FROM proving_rights_packets WHERE run_id='run-1'
        """
    )
    connection.commit()
    blocked = _dispatch_rights_decision(
        connection,
        source_id="UK-01",
        source_url=SOURCE_URLS["UK-01"],
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    connection.close()
    assert passing is not None
    assert passing["rights_authority_run_id"] == "run-1"
    assert blocked is None
    seen: list[str] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            seen.append(unit.ingest_id)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert seen == []
    assert report.graphiti == 0
    assert report.eligible == 0


def test_newer_failed_run_before_fenced_claim_blocks_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.cycle as cycle

    proving = _proving(tmp_path)
    original_reserve = cycle.reserve_graphiti_spend
    original_append = cycle.append_ledger
    events: list[tuple[str, dict[str, object]]] = []

    def capture_ledger(
        connection: sqlite3.Connection, kind: str, payload: dict[str, object]
    ) -> str:
        events.append((kind, dict(payload)))
        return original_append(connection, kind, payload)

    def reserve_then_revoke(
        connection: sqlite3.Connection,
        *,
        spend_id: str,
        ingest_id: str,
        attempt_number: int,
        proving_run_id: str,
        generation_id: str,
        reserved_gbp_microunits: int,
        ceiling_gbp_microunits: int,
    ) -> bool:
        reserved = original_reserve(
            connection,
            spend_id=spend_id,
            ingest_id=ingest_id,
            attempt_number=attempt_number,
            proving_run_id=proving_run_id,
            generation_id=generation_id,
            reserved_gbp_microunits=reserved_gbp_microunits,
            ceiling_gbp_microunits=ceiling_gbp_microunits,
        )
        assert reserved
        _insert_failed_proving_run(
            proving,
            run_id="run-2",
            reason="revoked before provider dispatch",
        )
        return reserved

    monkeypatch.setattr(cycle, "reserve_graphiti_spend", reserve_then_revoke)
    monkeypatch.setattr(cycle, "append_ledger", capture_ledger)

    class MustNotDispatch:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError(f"revoked unit reached provider: {unit.ingest_id}")

    unpublished = tmp_path / "revoked-before-dispatch.sqlite3"
    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=MustNotDispatch(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        "SELECT status, usage_basis, dispatch_owner FROM unpublished_graphiti_spend"
    ).fetchone()
    connection.close()
    holds = [payload for kind, payload in events if kind == "GRAPHITI_RIGHTS_HOLD"]
    reconciliations = [
        payload for kind, payload in events if kind == "GRAPHITI_SPEND_RECONCILE"
    ]
    reserved_spend_id = next(
        str(payload["spend_id"])
        for kind, payload in events
        if kind == "GRAPHITI_SPEND_RESERVE"
    )
    assert report.graphiti == 0
    assert spend == ("RECONCILED", "NO_EMBEDDING_CALL", None)
    boundary_hold = next(
        payload
        for payload in holds
        if payload["reason"] == "AUTHORITY_REVOKED_BEFORE_PROVIDER_DISPATCH"
    )
    assert boundary_hold["provider_dispatched"] is False
    assert reconciliations == [
        {
            "spend_id": reserved_spend_id,
            "usage_basis": "NO_EMBEDDING_CALL",
            "status": "RECONCILED",
            "actual_usd_microunits": 0,
            "actual_gbp_microunits": 0,
            "fx_policy": "USD_GBP_CONSERVATIVE_PARITY_V1",
            "unused_reservation_released": True,
        }
    ]


def test_reused_reservation_is_untouched_when_final_rights_are_revoked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.cycle as cycle

    proving = _proving(tmp_path)
    original_reserve = cycle.reserve_graphiti_spend
    original_append = cycle.append_ledger
    events: list[tuple[str, dict[str, object]]] = []

    def capture_ledger(
        connection: sqlite3.Connection, kind: str, payload: dict[str, object]
    ) -> str:
        events.append((kind, dict(payload)))
        return original_append(connection, kind, payload)

    def retain_then_revoke(
        connection: sqlite3.Connection,
        *,
        spend_id: str,
        ingest_id: str,
        attempt_number: int,
        proving_run_id: str,
        generation_id: str,
        reserved_gbp_microunits: int,
        ceiling_gbp_microunits: int,
    ) -> bool:
        assert original_reserve(
            connection,
            spend_id=spend_id,
            ingest_id=ingest_id,
            attempt_number=attempt_number,
            proving_run_id=proving_run_id,
            generation_id=generation_id,
            reserved_gbp_microunits=reserved_gbp_microunits,
            ceiling_gbp_microunits=ceiling_gbp_microunits,
        )
        _insert_failed_proving_run(
            proving,
            run_id="run-revoked-reused",
            reason="revoked before reused provider dispatch",
        )
        return False

    monkeypatch.setattr(cycle, "reserve_graphiti_spend", retain_then_revoke)
    monkeypatch.setattr(cycle, "append_ledger", capture_ledger)

    class MustNotDispatch:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError(
                f"revoked reused unit reached provider: {unit.ingest_id}"
            )

    unpublished = tmp_path / "revoked-reused.sqlite3"
    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=MustNotDispatch(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        """
        SELECT status, usage_basis, dispatch_owner, dispatch_lease_expires_at
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    connection.close()
    assert report.graphiti == 0
    assert spend == ("RESERVED", "PENDING_PROVIDER_REPORT", None, None)
    assert not any(kind == "GRAPHITI_ATTEMPT_CLAIM" for kind, _ in events)
    assert not any(kind == "GRAPHITI_SPEND_RECONCILE" for kind, _ in events)


def test_reused_unreceipted_reservation_survives_unknown_and_setup_no_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.cycle as cycle

    class ProcessDeath(BaseException):
        pass

    proving = _proving(tmp_path)
    unpublished = tmp_path / "reused-setup-no-call.sqlite3"
    events: list[tuple[str, dict[str, object]]] = []
    original_append = cycle.append_ledger

    def capture_ledger(
        connection: sqlite3.Connection, kind: str, payload: dict[str, object]
    ) -> str:
        events.append((kind, dict(payload)))
        return original_append(connection, kind, payload)

    monkeypatch.setattr(cycle, "append_ledger", capture_ledger)

    class DiesAfterClaim:
        def ingest(self, _unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise ProcessDeath

    with pytest.raises(ProcessDeath):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=DiesAfterClaim(),
            max_graphiti=1,
            clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
        )

    class UnknownAfterDispatch:
        def ingest(self, _unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise RuntimeError("response lost after possible provider dispatch")

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=UnknownAfterDispatch(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, 0, 16, tzinfo=UTC),
    )

    class SetupNoCall:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            result = replace(
                _complete(unit),
                outcome="FAILED",
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

    class TimeoutNoCall:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            timeout_chat = ({"provider": "cursor-agent-cli", "status": "FAILED"},)
            result = replace(
                _complete(unit, chat_invocations=timeout_chat),
                outcome="FAILED",
                failure_code="EXECUTION_TIMEOUT",
            )
            raw = dict(result.raw_receipt or {})
            assert "dispatch_state" not in raw
            raw.pop("raw_output_digest", None)
            raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
            return replace(
                result,
                receipt_digest=str(raw["raw_output_digest"]),
                raw_receipt=raw,
            )

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=TimeoutNoCall(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, 0, 32, tzinfo=UTC),
    )

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=SetupNoCall(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, 0, 48, tzinfo=UTC),
    )
    connection = sqlite3.connect(unpublished)
    retained = connection.execute(
        """
        SELECT status, usage_basis, actual_usd_microunits,
               dispatch_owner, dispatch_lease_expires_at
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    attempt_receipts = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_attempt_receipts"
    ).fetchone()[0]
    connection.close()
    held_attempts = [
        payload for kind, payload in events if kind == "GRAPHITI_EVALUATION_RETRY_HELD"
    ]
    assert retained == (
        "RESERVED",
        "PENDING_PROVIDER_REPORT",
        None,
        None,
        None,
    )
    assert attempt_receipts == 0
    assert [item["provider_dispatch_state"] for item in held_attempts] == [
        "UNKNOWN",
        "UNKNOWN",
        "NOT_DISPATCHED",
    ]
    assert held_attempts[1]["chat_invocations"] == [
        {"provider": "cursor-agent-cli", "status": "FAILED"}
    ]
    assert held_attempts[1]["embedding_usage"] == {
        "usage_basis": "NO_EMBEDDING_CALL",
        "request_count": 0,
        "embedding_tokens": 0,
        "cost_usd_microunits": 0,
        "requests": [],
    }


@pytest.mark.parametrize("terminal_outcome", ["COMPLETE", "PARTIAL"])
def test_reused_unreceipted_reservation_accepts_bound_terminal_no_call(
    tmp_path: Path,
    terminal_outcome: Literal["COMPLETE", "PARTIAL"],
) -> None:
    class ProcessDeath(BaseException):
        pass

    proving = _proving(tmp_path)
    unpublished = tmp_path / f"reused-{terminal_outcome.lower()}-no-call.sqlite3"

    class DiesAfterClaim:
        def ingest(self, _unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise ProcessDeath

    with pytest.raises(ProcessDeath):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=DiesAfterClaim(),
            max_graphiti=1,
            clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
        )

    class TerminalSameAttempt:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            assert unit.attempt_number == 1
            return replace(_complete(unit), outcome=terminal_outcome)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=TerminalSameAttempt(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, 0, 16, tzinfo=UTC),
    )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        """
        SELECT status, usage_basis, actual_usd_microunits,
               dispatch_owner, dispatch_lease_expires_at
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    attempt_receipts = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_attempt_receipts"
    ).fetchone()[0]
    ingests = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_ingest"
    ).fetchone()[0]
    connection.close()

    assert report.graphiti == 1
    assert spend == ("RECONCILED", "NO_EMBEDDING_CALL", 0, None, None)
    assert attempt_receipts == 1
    assert ingests == 1


@pytest.mark.parametrize(
    "recovery_classification",
    [
        GraphitiRecoveryClassification.RECOVERED_AMBIGUOUS,
        GraphitiRecoveryClassification.RECOVERED_PENDING_PROCESS_DEATH,
    ],
)
def test_marker_recovery_closes_reused_attempt_but_preserves_spend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recovery_classification: GraphitiRecoveryClassification,
) -> None:
    from newsroom.control_plane import cycle

    class ProcessDeath(BaseException):
        pass

    proving = _proving(tmp_path)
    unpublished = tmp_path / f"marker-{recovery_classification}.sqlite3"
    events: list[tuple[str, dict[str, object]]] = []
    original_append = cycle.append_ledger

    def capture_ledger(
        connection: sqlite3.Connection, kind: str, payload: dict[str, object]
    ) -> str:
        events.append((kind, dict(payload)))
        return original_append(connection, kind, payload)

    monkeypatch.setattr(cycle, "append_ledger", capture_ledger)

    class DiesAfterClaim:
        def ingest(self, _unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise ProcessDeath

    with pytest.raises(ProcessDeath):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=DiesAfterClaim(),
            max_graphiti=1,
            clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
        )

    class MarkerRecovery:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            assert unit.attempt_number == 1
            return _marker_recovery_result(unit, recovery_classification)

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=MarkerRecovery(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, 0, 16, tzinfo=UTC),
    )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        """
        SELECT status, usage_basis, actual_usd_microunits, dispatch_owner
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    receipt_row = connection.execute(
        "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
    ).fetchone()
    failure = connection.execute(
        """
        SELECT retry_count, last_outcome, last_failure_code
        FROM unpublished_graphiti_failures
        """
    ).fetchone()
    ingest_id = connection.execute(
        "SELECT ingest_id FROM unpublished_graphiti_spend"
    ).fetchone()[0]
    next_attempt = next_graphiti_attempt_number(connection, str(ingest_id))
    connection.close()

    assert spend == ("RESERVED", "PENDING_PROVIDER_REPORT", None, None)
    assert receipt_row is not None
    receipt = json.loads(receipt_row[0])
    assert receipt["recovery_classification"] == recovery_classification
    assert failure == (1, "AMBIGUOUS_EFFECT", "AMBIGUOUS_EFFECT")
    assert next_attempt == 2
    recovery_events = [
        payload
        for kind, payload in events
        if kind == "GRAPHITI_EVALUATION_RECOVERY_CLOSED"
    ]
    assert len(recovery_events) == 1
    assert recovery_events[0]["recovery_classification"] == recovery_classification
    recovery_accounting = recovery_events[0]["accounting"]
    assert isinstance(recovery_accounting, dict)
    assert recovery_accounting["status"] == "RESERVED"
    assert recovery_events[0]["chat_invocations"] == []
    assert recovery_events[0]["embedding_usage"] == {
        "usage_basis": "NO_EMBEDDING_CALL",
        "request_count": 0,
        "embedding_tokens": 0,
        "cost_usd_microunits": 0,
        "requests": [],
    }
    assert not any(kind == "GRAPHITI_EVALUATION_RETRY_HELD" for kind, _ in events)
    assert any(kind == "GRAPHITI_EVALUATION_ATTEMPT" for kind, _ in events)


def test_marker_recovery_advances_attempts_until_dead_letter(
    tmp_path: Path,
) -> None:
    class ProcessDeath(BaseException):
        pass

    proving = _proving(tmp_path)
    proving_connection = sqlite3.connect(proving)
    proving_connection.execute(
        "DELETE FROM proving_observations WHERE source_id!='HK-01'"
    )
    proving_connection.commit()
    proving_connection.close()
    unpublished = tmp_path / "marker-recovery-dead-letter.sqlite3"
    port_transitions: list[tuple[str, int]] = []

    for expected_attempt in range(1, 4):

        class DiesAfterClaim:
            def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
                port_transitions.append(("PROCESS_DEATH", unit.attempt_number))
                assert unit.attempt_number == expected_attempt
                raise ProcessDeath

        with pytest.raises(ProcessDeath):
            run_cycle(
                proving_store=str(proving),
                unpublished_store=str(unpublished),
                writer=FixtureWriter(),
                max_writes=0,
                graphiti=DiesAfterClaim(),
                max_graphiti=1,
                clock=lambda: datetime(2026, 8, 21, expected_attempt - 1, tzinfo=UTC),
            )

        class MarkerRecovery:
            def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
                port_transitions.append(("MARKER_RECOVERY", unit.attempt_number))
                assert unit.attempt_number == expected_attempt
                return _marker_recovery_result(
                    unit, GraphitiRecoveryClassification.RECOVERED_PENDING_PROCESS_DEATH
                )

        report = run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=MarkerRecovery(),
            max_graphiti=1,
            clock=lambda: datetime(2026, 8, 21, expected_attempt - 1, 16, tzinfo=UTC),
        )
        assert report.graphiti == 1

    class MustNotDispatch:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError(
                f"dead-lettered marker recovery reached provider: {unit.ingest_id}"
            )

    final_report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=MustNotDispatch(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, 3, tzinfo=UTC),
    )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        """
        SELECT attempt_number, status, usage_basis, reserved_gbp_microunits,
               dispatch_owner
        FROM unpublished_graphiti_spend ORDER BY attempt_number
        """
    ).fetchall()
    receipts = connection.execute(
        """
        SELECT attempt_number FROM unpublished_graphiti_attempt_receipts
        ORDER BY attempt_number
        """
    ).fetchall()
    failure = connection.execute(
        """
        SELECT retry_count, dead_lettered FROM unpublished_graphiti_failures
        """
    ).fetchone()
    ceiling_commitment = connection.execute(
        """
        SELECT SUM(
            CASE WHEN status='RECONCILED'
                 THEN COALESCE(actual_gbp_microunits, 0)
                 ELSE reserved_gbp_microunits END
        ) FROM unpublished_graphiti_spend
        """
    ).fetchone()[0]
    ledger_kinds = [
        row[0] for row in connection.execute("SELECT kind FROM ledger ORDER BY seq")
    ]
    connection.close()

    assert port_transitions == [
        ("PROCESS_DEATH", 1),
        ("MARKER_RECOVERY", 1),
        ("PROCESS_DEATH", 2),
        ("MARKER_RECOVERY", 2),
        ("PROCESS_DEATH", 3),
        ("MARKER_RECOVERY", 3),
    ]
    assert spend == [
        (1, "RESERVED", "PENDING_PROVIDER_REPORT", 500_000, None),
        (2, "RESERVED", "PENDING_PROVIDER_REPORT", 500_000, None),
        (3, "RESERVED", "PENDING_PROVIDER_REPORT", 500_000, None),
    ]
    assert receipts == [(1,), (2,), (3,)]
    assert failure == (3, 1)
    assert ceiling_commitment == 1_500_000
    assert ledger_kinds.count("GRAPHITI_EVALUATION_RECOVERY_CLOSED") == 3
    assert ledger_kinds.count("GRAPHITI_EVALUATION_ATTEMPT") == 3
    assert "GRAPHITI_EVALUATION_RETRY_HELD" not in ledger_kinds
    assert final_report.graphiti == 0


@pytest.mark.parametrize(
    "malformed_usage",
    [
        pytest.param(
            {
                "usage_basis": "NO_EMBEDDING_CALL",
                "requests": [],
                "embedding_tokens": 0,
                "cost_usd_microunits": 0,
            },
            id="missing-request-count",
        ),
        pytest.param(
            {
                "usage_basis": "NO_EMBEDDING_CALL",
                "requests": [{"provider": "unexpected"}],
                "request_count": 0,
                "embedding_tokens": 0,
                "cost_usd_microunits": 0,
            },
            id="non-empty-requests",
        ),
        pytest.param(
            {
                "usage_basis": "NO_EMBEDDING_CALL",
                "requests": [],
                "request_count": 0,
                "embedding_tokens": 1,
                "cost_usd_microunits": 0,
            },
            id="positive-tokens",
        ),
        pytest.param(
            {
                "usage_basis": "NO_EMBEDDING_CALL",
                "requests": [],
                "request_count": 0,
                "embedding_tokens": 0,
                "cost_usd_microunits": 1,
            },
            id="positive-cost",
        ),
        pytest.param(
            {
                "usage_basis": "NO_EMBEDDING_CALL",
                "requests": [],
                "request_count": False,
                "embedding_tokens": 0,
                "cost_usd_microunits": 0,
            },
            id="boolean-count",
        ),
        pytest.param(
            {
                "usage_basis": "NO_EMBEDDING_CALL",
                "requests": [],
                "request_count": 0,
                "embedding_tokens": 0,
                "cost_usd_microunits": 0,
                "unexpected": 0,
            },
            id="unexpected-key",
        ),
    ],
)
def test_no_call_reconciliation_requires_exact_zero_usage_shape(
    tmp_path: Path,
    malformed_usage: dict[str, object],
) -> None:
    connection = connect(str(tmp_path / "exact-zero-shape.sqlite3"))
    assert reserve_graphiti_spend(
        connection,
        spend_id="ingest-1:1",
        ingest_id="ingest-1",
        attempt_number=1,
        proving_run_id="run-1",
        generation_id=GRAPHITI_GENERATION_ID,
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=5_000_000,
    )
    assert claim_graphiti_attempt(
        connection,
        spend_id="ingest-1:1",
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="malformed-no-call-owner",
        claimed_at="2026-08-21T00:00:00.000000Z",
        lease_expires_at="2026-08-21T00:15:00.000000Z",
    )

    accounting = reconcile_graphiti_spend(
        connection,
        spend_id="ingest-1:1",
        embedding_usage=malformed_usage,
    )
    connection.commit()
    connection.close()

    reopened = sqlite3.connect(tmp_path / "exact-zero-shape.sqlite3")
    durable_spend = reopened.execute(
        """
        SELECT status, actual_usd_microunits, actual_gbp_microunits,
               dispatch_owner, dispatch_lease_expires_at, usage_basis
        FROM unpublished_graphiti_spend WHERE spend_id='ingest-1:1'
        """
    ).fetchone()
    reopened.close()

    assert accounting["status"] == "UNRECONCILED"
    assert accounting["actual_usd_microunits"] is None
    assert accounting["actual_gbp_microunits"] is None
    assert accounting["unused_reservation_released"] is False
    assert durable_spend == (
        "UNRECONCILED",
        None,
        None,
        None,
        None,
        "NO_EMBEDDING_CALL",
    )


@pytest.mark.parametrize(
    "malformed_usage",
    [
        pytest.param(
            _provider_usage_variant(
                top_updates={"cost_usd_microunits": -1},
            ),
            id="negative-top-cost",
        ),
        pytest.param(
            _provider_usage_variant(
                request_updates={"cost_usd_microunits": -1},
            ),
            id="negative-request-cost",
        ),
        pytest.param(
            _provider_usage_variant(
                top_updates={"cost_usd_microunits": True},
            ),
            id="boolean-top-cost",
        ),
        pytest.param(
            _provider_usage_variant(
                request_updates={"cost_usd_microunits": True},
            ),
            id="boolean-request-cost",
        ),
        pytest.param(
            _provider_usage_variant(omit_top="cost_usd_microunits"),
            id="missing-cost",
        ),
        pytest.param(
            _provider_usage_variant(omit_request="cost_usd_microunits"),
            id="missing-request-cost",
        ),
        pytest.param(
            _provider_usage_variant(top_updates={"requests": []}),
            id="empty-requests",
        ),
        pytest.param(
            _provider_usage_variant(top_updates={"request_count": 2}),
            id="request-count-mismatch",
        ),
        pytest.param(
            _provider_usage_variant(top_updates={"request_count": True}),
            id="boolean-request-count",
        ),
        pytest.param(
            _provider_usage_variant(top_updates={"embedding_tokens": 26}),
            id="token-total-mismatch",
        ),
        pytest.param(
            _provider_usage_variant(top_updates={"embedding_tokens": True}),
            id="boolean-token-total",
        ),
        pytest.param(
            _provider_usage_variant(
                request_updates={"prompt_tokens": 26},
            ),
            id="prompt-tokens-exceed-total",
        ),
        pytest.param(
            _provider_usage_variant(request_updates={"cost_usd_microunits": "9"}),
            id="malformed-request-cost",
        ),
        pytest.param(
            _provider_usage_variant(
                request_updates={"cost_reported": False},
            ),
            id="cost-not-reported",
        ),
        pytest.param(
            _provider_usage_variant(
                request_updates={"outcome": "FAILED"},
            ),
            id="request-not-complete",
        ),
        pytest.param(
            _provider_usage_variant(
                top_updates={"cost_usd_microunits": 10},
            ),
            id="cost-total-mismatch",
        ),
    ],
)
def test_provider_reconciliation_requires_exact_typed_receipt(
    tmp_path: Path,
    malformed_usage: dict[str, object],
) -> None:
    store_path = tmp_path / "strict-provider-receipt.sqlite3"
    connection = connect(str(store_path))
    assert reserve_graphiti_spend(
        connection,
        spend_id="ingest-1:1",
        ingest_id="ingest-1",
        attempt_number=1,
        proving_run_id="run-1",
        generation_id=GRAPHITI_GENERATION_ID,
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=5_000_000,
    )
    accounting = reconcile_graphiti_spend(
        connection,
        spend_id="ingest-1:1",
        embedding_usage=malformed_usage,
    )
    connection.commit()
    connection.close()

    reopened = sqlite3.connect(store_path)
    durable_spend = reopened.execute(
        """
        SELECT status, actual_usd_microunits, actual_gbp_microunits, usage_basis
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    ceiling_commitment = reopened.execute(
        """
        SELECT SUM(
            CASE WHEN status='RECONCILED'
                 THEN COALESCE(actual_gbp_microunits, 0)
                 ELSE reserved_gbp_microunits END
        ) FROM unpublished_graphiti_spend
        """
    ).fetchone()[0]
    reopened.close()

    assert accounting["status"] == "UNRECONCILED"
    assert accounting["actual_usd_microunits"] is None
    assert accounting["actual_gbp_microunits"] is None
    assert accounting["unused_reservation_released"] is False
    assert durable_spend == ("UNRECONCILED", None, None, "PROVIDER_REPORTED")
    assert ceiling_commitment == 500_000


@pytest.mark.parametrize("cost", [0, 9])
def test_valid_provider_receipt_reconciles_zero_and_positive_cost(
    tmp_path: Path,
    cost: int,
) -> None:
    connection = connect(str(tmp_path / f"valid-provider-{cost}.sqlite3"))
    assert reserve_graphiti_spend(
        connection,
        spend_id="ingest-1:1",
        ingest_id="ingest-1",
        attempt_number=1,
        proving_run_id="run-1",
        generation_id=GRAPHITI_GENERATION_ID,
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=5_000_000,
    )
    usage = _provider_usage(
        cost_usd_microunits=cost,
        embedding_tokens=25,
    )
    if cost == 0:
        usage["forward_compatible_top"] = "retained"
        requests = usage["requests"]
        assert isinstance(requests, list) and len(requests) == 1
        request = requests[0]
        assert isinstance(request, dict)
        request["request_id"] = ""
        request["prompt_tokens"] = None
        request["forward_compatible_request"] = "retained"
    accounting = reconcile_graphiti_spend(
        connection,
        spend_id="ingest-1:1",
        embedding_usage=usage,
    )
    connection.commit()
    connection.close()

    assert accounting["status"] == "RECONCILED"
    assert accounting["actual_usd_microunits"] == cost
    assert accounting["actual_gbp_microunits"] == cost
    assert accounting["unused_reservation_released"] is True


def test_reused_malformed_no_call_is_receipted_not_retry_held(
    tmp_path: Path,
) -> None:
    class ProcessDeath(BaseException):
        pass

    proving = _proving(tmp_path)
    unpublished = tmp_path / "reused-malformed-no-call.sqlite3"

    class DiesAfterClaim:
        def ingest(self, _unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise ProcessDeath

    with pytest.raises(ProcessDeath):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=DiesAfterClaim(),
            max_graphiti=1,
            clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
        )

    malformed_usage: dict[str, object] = {
        "usage_basis": "NO_EMBEDDING_CALL",
        "requests": [{"provider": "unexpected"}],
        "request_count": 0,
        "embedding_tokens": 0,
        "cost_usd_microunits": 0,
    }
    timeout_diagnostic = {
        "schema_version": "newsroom.graphiti-timeout-diagnostic.v1",
        "boundary": "CLEANUP_DEADLINE",
        "phase": "CONNECTION_CLEANUP",
        "cause": "CLEANUP_DEADLINE_EXPIRED",
        "provider_cause": "UNOBSERVED",
        "configured_timeout_ms": 10_000,
        "elapsed_ms": 10_000,
        "deadline_at": "2026-08-21T00:15:59.000000Z",
        "last_progress": "CONNECTION_CLOSE_INCOMPLETE",
        "termination": "TASK_CANCELLED",
    }

    class MalformedNoCall:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            assert unit.attempt_number == 1
            return replace(
                _complete(
                    unit,
                    embedding_usage=malformed_usage,
                    timeout_diagnostics=(timeout_diagnostic,),
                    producer_failure="GraphitiCleanupTimeout",
                ),
                outcome="TIMEOUT",
                failure_code="EXECUTION_TIMEOUT",
            )

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=MalformedNoCall(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, 0, 16, tzinfo=UTC),
    )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        """
        SELECT status, actual_usd_microunits, actual_gbp_microunits,
               dispatch_owner, dispatch_lease_expires_at, usage_basis
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    receipt_row = connection.execute(
        "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
    ).fetchone()
    failure = connection.execute(
        """
        SELECT retry_count, last_outcome, last_failure_code
        FROM unpublished_graphiti_failures
        """
    ).fetchone()
    ledger_rows = connection.execute(
        "SELECT kind, payload_json FROM ledger ORDER BY seq"
    ).fetchall()
    connection.close()

    assert report.graphiti == 1
    assert spend == (
        "UNRECONCILED",
        None,
        None,
        None,
        None,
        "NO_EMBEDDING_CALL",
    )
    assert receipt_row is not None
    receipt = json.loads(receipt_row[0])
    assert receipt["embedding_usage"] == malformed_usage
    assert receipt["timeout_diagnostics"] == [timeout_diagnostic]
    assert receipt["producer_failure"] == "GraphitiCleanupTimeout"
    receipt_accounting = receipt["accounting"]
    assert isinstance(receipt_accounting, dict)
    assert receipt_accounting["status"] == "UNRECONCILED"
    assert failure == (1, "TIMEOUT", "EXECUTION_TIMEOUT")
    ledger_kinds = [row[0] for row in ledger_rows]
    assert "GRAPHITI_EVALUATION_RETRY_HELD" not in ledger_kinds
    assert ledger_kinds.count("GRAPHITI_EVALUATION_ATTEMPT") == 1
    attempt_payload = next(
        json.loads(payload)
        for kind, payload in ledger_rows
        if kind == "GRAPHITI_EVALUATION_ATTEMPT"
    )
    assert attempt_payload["timeout_diagnostics"] == [timeout_diagnostic]
    assert attempt_payload["producer_failure"] == "GraphitiCleanupTimeout"
    assert attempt_payload["receipt_digest"] == receipt["receipt_digest"]


def test_attempt_receipt_retains_combined_temporal_failure_code() -> None:
    from newsroom.control_plane.cycle import _receipt

    unit = CorpusIngestUnit(
        source_id="HK-04",
        item_key="q7",
        headline="立法會質詢",
        body="科技與生活科課程",
        canonical_url="https://www.edb.gov.hk/example",
        observation_digest="sha256:obs",
        observed_at="2026-08-16T21:41:34.000000Z",
        proving_run_id="run-1",
        effective_revision=_effective_revision(
            source_id="HK-04",
            item_key="q7",
            headline="立法會質詢",
            body="科技與生活科課程",
            canonical_url="https://www.edb.gov.hk/example",
            first_observed_at="2026-08-16T21:41:34.000000Z",
        ),
    )
    result = replace(
        _complete(
            unit,
            proposal_count=0,
            entity_count=0,
            relation_count=0,
            combined_temporal_failure_code="EVIDENCE_UNRESOLVED",
        ),
        outcome="MALFORMED_OUTPUT",
        failure_code="OUTPUT_SCHEMA_INVALID",
    )
    receipt = _receipt(unit, result, accounting={"status": "RECONCILED"})
    assert receipt["combined_temporal_failure_code"] == "EVIDENCE_UNRESOLVED"
    assert receipt["failure_code"] == "OUTPUT_SCHEMA_INVALID"
    blank = dict(result.raw_receipt or {})
    blank["combined_temporal_failure_code"] = ""
    assert "combined_temporal_failure_code" not in _receipt(
        unit,
        replace(result, raw_receipt=blank),
        accounting={"status": "RECONCILED"},
    )


def test_reused_malformed_provider_receipt_preserves_ceiling_reservation(
    tmp_path: Path,
) -> None:
    class ProcessDeath(BaseException):
        pass

    proving = _proving(tmp_path)
    unpublished = tmp_path / "reused-malformed-provider.sqlite3"

    class DiesAfterClaim:
        def ingest(self, _unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise ProcessDeath

    with pytest.raises(ProcessDeath):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=DiesAfterClaim(),
            max_graphiti=1,
            clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
        )

    malformed_usage = _provider_usage_variant(
        top_updates={"cost_usd_microunits": -1},
        request_updates={"cost_usd_microunits": -1},
    )

    class MalformedProviderReceipt:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            assert unit.attempt_number == 1
            return replace(
                _complete(unit, embedding_usage=malformed_usage),
                outcome="TIMEOUT",
                failure_code="EXECUTION_TIMEOUT",
            )

    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=MalformedProviderReceipt(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, 0, 16, tzinfo=UTC),
    )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        """
        SELECT status, actual_usd_microunits, actual_gbp_microunits, usage_basis
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    ceiling_commitment = connection.execute(
        """
        SELECT SUM(
            CASE WHEN status='RECONCILED'
                 THEN COALESCE(actual_gbp_microunits, 0)
                 ELSE reserved_gbp_microunits END
        ) FROM unpublished_graphiti_spend
        """
    ).fetchone()[0]
    receipts = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_attempt_receipts"
    ).fetchone()[0]
    connection.close()

    assert spend == ("UNRECONCILED", None, None, "PROVIDER_REPORTED")
    assert ceiling_commitment == 500_000
    assert receipts == 1


def test_proving_writer_cannot_commit_during_provider_handoff(
    tmp_path: Path,
) -> None:
    assert (
        PROVING_WRITE_TIMEOUT_SECONDS * 1_000
        > GRAPHITI_EXTRACTION_TIMEOUT_MS + GRAPHITI_MAX_CLEANUP_TIMEOUT_MS
    )
    proving = _proving(tmp_path)
    writer_started = threading.Event()
    writer_committed = threading.Event()
    writer_errors: list[BaseException] = []
    writer_thread: threading.Thread | None = None

    def insert_veto() -> None:
        writer_started.set()
        try:
            _insert_failed_proving_run(
                proving,
                run_id="run-during-dispatch",
                reason="concurrent provider-boundary veto",
            )
            writer_committed.set()
        except BaseException as exc:
            writer_errors.append(exc)

    class FencedDispatch:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            nonlocal writer_thread
            writer_thread = threading.Thread(target=insert_veto, daemon=True)
            writer_thread.start()
            assert writer_started.wait(timeout=1)
            assert not writer_committed.wait(timeout=0.2)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "fenced-dispatch.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=FencedDispatch(),
        max_graphiti=1,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert writer_thread is not None
    writer_thread.join(timeout=2)
    assert writer_errors == []
    assert writer_committed.is_set()
    assert report.graphiti == 1


def test_provider_waits_for_transient_proving_writer_lock(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    blocker = sqlite3.connect(proving)
    blocker.execute("BEGIN IMMEDIATE")
    provider_called = threading.Event()
    reports: list[CycleReport] = []
    errors: list[BaseException] = []

    class DispatchAfterFence:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            provider_called.set()
            return _complete(unit)

    def cycle_worker() -> None:
        try:
            reports.append(
                run_cycle(
                    proving_store=str(proving),
                    unpublished_store=str(tmp_path / "transient-fence.sqlite3"),
                    writer=FixtureWriter(),
                    max_writes=0,
                    graphiti=DispatchAfterFence(),
                    max_graphiti=1,
                    clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
                )
            )
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=cycle_worker, daemon=True)
    worker.start()
    assert not provider_called.wait(timeout=0.2)
    blocker.rollback()
    blocker.close()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors == []
    assert len(reports) == 1
    assert provider_called.is_set()


def test_proving_writer_lock_timeout_is_bounded_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.increment9.proving as proving_module

    proving = _proving(tmp_path)
    blocker = sqlite3.connect(proving)
    blocker.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr(proving_module, "PROVING_WRITE_TIMEOUT_SECONDS", 0.01)
    try:
        with pytest.raises(ProvingError, match="writer lock timed out"):
            connect_proving(str(proving))
    finally:
        blocker.rollback()
        blocker.close()


def test_unavailable_proving_fence_releases_new_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.cycle as cycle

    proving = _proving(tmp_path)
    blocker = sqlite3.connect(proving)
    blocker.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr(cycle, "_PROVING_FENCE_TIMEOUT_SECONDS", 0.01)
    events: list[tuple[str, dict[str, object]]] = []
    original_append = cycle.append_ledger

    def capture_ledger(
        connection: sqlite3.Connection, kind: str, payload: dict[str, object]
    ) -> str:
        events.append((kind, dict(payload)))
        return original_append(connection, kind, payload)

    monkeypatch.setattr(cycle, "append_ledger", capture_ledger)

    class MustNotDispatch:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            raise AssertionError(f"unfenced unit reached provider: {unit.ingest_id}")

    unpublished = tmp_path / "unavailable-fence.sqlite3"
    try:
        report = run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=MustNotDispatch(),
            max_graphiti=1,
            clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
        )
    finally:
        blocker.rollback()
        blocker.close()

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        "SELECT status, usage_basis, dispatch_owner FROM unpublished_graphiti_spend"
    ).fetchone()
    connection.close()
    assert report.graphiti == 0
    assert spend == ("RECONCILED", "NO_EMBEDDING_CALL", None)
    assert any(
        kind == "GRAPHITI_SPEND_RECONCILE"
        and payload["usage_basis"] == "NO_EMBEDDING_CALL"
        for kind, payload in events
    )
    assert any(
        kind == "GRAPHITI_RIGHTS_HOLD"
        and payload["reason"] == "PROVING_FENCE_UNAVAILABLE"
        and payload["provider_dispatched"] is False
        for kind, payload in events
    )


def test_backdated_later_fail_blocks_despite_smaller_run_id(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    started_at = "2025-08-16T21:41:34.000000Z"
    later_fail_id = "aaa-later-fail"
    connection = __import__("sqlite3").connect(proving)
    assert (
        started_at
        < connection.execute(
            "SELECT started_at FROM proving_runs WHERE run_id='run-1'"
        ).fetchone()[0]
    )
    connection.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES(?,?,0,0,0,0)
        """,
        (later_fail_id, started_at),
    )
    connection.execute(
        """
        INSERT INTO proving_gates
        SELECT ?, gate_id,
               CASE WHEN gate_id='KILL_SWITCH_READY' THEN 'FAIL' ELSE status END,
               'later backdated veto'
        FROM proving_gates WHERE run_id='run-1'
        """,
        (later_fail_id,),
    )
    connection.execute(
        """
        INSERT INTO proving_rights_packets
        SELECT ?, gate_id, packet_digest, packet_json, assessed_at
        FROM proving_rights_packets WHERE run_id='run-1'
        """,
        (later_fail_id,),
    )
    connection.commit()
    assert later_fail_id < "run-1"
    assert _latest_run_id(connection) == later_fail_id
    assert _latest_run_with_global_authority(connection) is None
    decision = _dispatch_rights_decision(
        connection,
        source_id="UK-01",
        source_url=SOURCE_URLS["UK-01"],
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    connection.close()
    assert decision is None
    seen: list[str] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            seen.append(unit.ingest_id)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert seen == []
    assert report.graphiti == 0
    assert report.eligible == 0
    assert report.proving_run_id == later_fail_id


def _retain_source(
    proving: Path,
    *,
    source_id: str,
    url: str,
    body: bytes,
    destinations: tuple[str, ...],
) -> None:
    gate_id = f"RIGHTS_{source_id}"
    packet = _cycle_rights_inventory(gate_id, destinations)
    packet_bytes = canonical_json_bytes(packet)
    connection = __import__("sqlite3").connect(proving)
    connection.execute(
        "INSERT INTO proving_gates VALUES(?,?,?,?)",
        ("run-1", gate_id, "PASS", "fixture"),
    )
    connection.execute(
        "INSERT INTO proving_rights_packets VALUES(?,?,?,?,?)",
        (
            "run-1",
            gate_id,
            digest_bytes(packet_bytes),
            packet_bytes.decode("utf-8"),
            "2026-08-20T00:00:00.000000Z",
        ),
    )
    connection.execute(
        "INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
        (
            source_id,
            "run-1",
            "2026-08-16T21:41:34.000000Z",
            url,
            200,
            digest_bytes(body),
            body,
            1,
            None,
        ),
    )
    connection.commit()
    connection.close()


def _rewrite_destinations(proving: Path, destinations: tuple[str, ...]) -> None:
    connection = __import__("sqlite3").connect(proving)
    rows = connection.execute(
        "SELECT gate_id FROM proving_rights_packets WHERE run_id='run-1'"
    ).fetchall()
    for (gate_id,) in rows:
        packet = _cycle_rights_inventory(str(gate_id), destinations)
        packet_bytes = canonical_json_bytes(packet)
        connection.execute(
            """
            UPDATE proving_rights_packets
            SET packet_digest=?, packet_json=?
            WHERE run_id='run-1' AND gate_id=?
            """,
            (digest_bytes(packet_bytes), packet_bytes.decode("utf-8"), gate_id),
        )
    connection.commit()
    connection.close()


def test_source_endpoint_destinations_cannot_dispatch_graphiti_providers(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    _rewrite_destinations(proving, FIXTURE_DESTINATIONS)
    connection = __import__("sqlite3").connect(proving)
    decision = _dispatch_rights_decision(
        connection,
        source_id="UK-01",
        source_url=SOURCE_URLS["UK-01"],
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    connection.close()
    assert decision is None
    seen: list[str] = []

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            seen.append(unit.ingest_id)
            return _complete(unit)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert seen == []
    assert report.graphiti == 0
    assert report.eligible == 3


def test_graphiti_dispatch_requires_every_evaluation_provider_destination(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    embedding_token = next(
        item.destination_token
        for item in GRAPHITI_EVALUATION_PROVIDER_DESTINATIONS
        if item.route == GRAPHITI_EMBEDDING_MODEL
    )
    missing_openrouter = tuple(
        destination
        for destination in _evaluation_cycle_destinations()
        if destination != embedding_token
    )
    _rewrite_destinations(proving, missing_openrouter)
    connection = __import__("sqlite3").connect(proving)
    decision = _dispatch_rights_decision(
        connection,
        source_id="UK-01",
        source_url=SOURCE_URLS["UK-01"],
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    connection.close()
    assert GRAPHITI_EVALUATION_DESTINATION_TOKENS - set(missing_openrouter) == {
        embedding_token
    }
    assert decision is None


def test_uk10_and_rad01_canonical_endpoints_dispatch_with_evaluation_destinations(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    destinations = _evaluation_cycle_destinations()
    _retain_source(
        proving,
        source_id="UK-10",
        url=SOURCE_URLS["UK-10"],
        body=DATED_RSS,
        destinations=destinations,
    )
    _retain_source(
        proving,
        source_id="RAD-01",
        url=SOURCE_URLS["RAD-01"],
        body=DATED_RSS,
        destinations=destinations,
    )
    connection = __import__("sqlite3").connect(proving)
    uk10 = _dispatch_rights_decision(
        connection,
        source_id="UK-10",
        source_url=SOURCE_URLS["UK-10"],
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    rad01 = _dispatch_rights_decision(
        connection,
        source_id="RAD-01",
        source_url=SOURCE_URLS["RAD-01"],
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    connection.close()
    assert SOURCE_URLS["UK-10"] == UK_10_ENDPOINT
    assert SOURCE_URLS["RAD-01"] == RAD_01_ENDPOINT
    assert uk10 is not None
    assert uk10["rights_endpoint"] == UK_10_ENDPOINT
    assert GRAPHITI_EVALUATION_DESTINATION_TOKENS.issubset(uk10["rights_destinations"])
    assert rad01 is not None
    assert rad01["rights_endpoint"] == RAD_01_ENDPOINT
    assert GRAPHITI_EVALUATION_DESTINATION_TOKENS.issubset(rad01["rights_destinations"])


def test_uk10_and_rad01_retired_aliases_remain_binding_mismatch_held(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    destinations = _evaluation_cycle_destinations()
    _retain_source(
        proving,
        source_id="UK-10",
        url=UK_10_RETIRED_ENDPOINT,
        body=DATED_RSS,
        destinations=destinations,
    )
    _retain_source(
        proving,
        source_id="RAD-01",
        url=RAD_01_RETIRED_ENDPOINT,
        body=DATED_RSS,
        destinations=destinations,
    )
    connection = __import__("sqlite3").connect(proving)
    uk10 = _dispatch_rights_decision(
        connection,
        source_id="UK-10",
        source_url=UK_10_RETIRED_ENDPOINT,
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    rad01 = _dispatch_rights_decision(
        connection,
        source_id="RAD-01",
        source_url=RAD_01_RETIRED_ENDPOINT,
        evaluated_at="2026-08-21T00:00:00.000000Z",
    )
    connection.close()
    assert "weather.metoffice.gov.uk" in UK_10_RETIRED_ENDPOINT
    assert "rthk.hk" in RAD_01_RETIRED_ENDPOINT
    assert UK_10_RETIRED_ENDPOINT != UK_10_ENDPOINT
    assert RAD_01_RETIRED_ENDPOINT != RAD_01_ENDPOINT
    assert uk10 is None
    assert rad01 is None


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


def test_expired_rights_are_rechecked_at_actual_dispatch_time(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
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
        clock=lambda: datetime(2100, 1, 1, tzinfo=UTC),
    )
    assert seen == []
    assert report.eligible == 0


def test_process_death_reenters_unreceipted_reserved_attempt(tmp_path: Path) -> None:
    connection = connect(str(tmp_path / "unpublished.sqlite3"))
    assert reserve_graphiti_spend(
        connection,
        spend_id="ingest-1:1",
        ingest_id="ingest-1",
        attempt_number=1,
        proving_run_id="run-1",
        generation_id=GRAPHITI_GENERATION_ID,
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=5_000_000,
    )
    connection.commit()
    assert next_graphiti_attempt_number(connection, "ingest-1") == 1
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_attempt_receipts(
            ingest_id, attempt_number, outcome, receipt_digest, receipt_json, at
        ) VALUES(?,?,?,?,?,?)
        """,
        ("ingest-1", 1, "FAILED", "sha256:receipt", "{}", "2026-08-21T00:00:00Z"),
    )
    assert next_graphiti_attempt_number(connection, "ingest-1") == 2
    connection.close()


def test_unreceipted_attempt_requires_expired_dispatch_lease(
    tmp_path: Path,
) -> None:
    connection = connect(str(tmp_path / "unpublished.sqlite3"))
    assert reserve_graphiti_spend(
        connection,
        spend_id="ingest-1:1",
        ingest_id="ingest-1",
        attempt_number=1,
        proving_run_id="run-1",
        generation_id=GRAPHITI_GENERATION_ID,
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=5_000_000,
    )
    assert claim_graphiti_attempt(
        connection,
        spend_id="ingest-1:1",
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="owner-1",
        claimed_at="2026-08-21T00:00:00.000000Z",
        lease_expires_at="2026-08-21T00:15:00.000000Z",
    )
    connection.commit()
    assert not claim_graphiti_attempt(
        connection,
        spend_id="ingest-1:1",
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="owner-2",
        claimed_at="2026-08-21T00:05:00.000000Z",
        lease_expires_at="2026-08-21T00:20:00.000000Z",
    )
    assert claim_graphiti_attempt(
        connection,
        spend_id="ingest-1:1",
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="owner-2",
        claimed_at="2026-08-21T00:15:00.000000Z",
        lease_expires_at="2026-08-21T00:30:00.000000Z",
    )
    connection.close()


def test_dispatch_lease_serialises_distinct_units_in_one_generation(
    tmp_path: Path,
) -> None:
    connection = connect(str(tmp_path / "unpublished.sqlite3"))
    for ingest_id in ("ingest-1", "ingest-2"):
        assert reserve_graphiti_spend(
            connection,
            spend_id=f"{ingest_id}:1",
            ingest_id=ingest_id,
            attempt_number=1,
            proving_run_id="run-1",
            generation_id=GRAPHITI_GENERATION_ID,
            reserved_gbp_microunits=500_000,
            ceiling_gbp_microunits=5_000_000,
        )
    assert claim_graphiti_attempt(
        connection,
        spend_id="ingest-1:1",
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="owner-1",
        claimed_at="2026-08-21T00:00:00.000000Z",
        lease_expires_at="2026-08-21T00:15:00.000000Z",
    )
    connection.commit()
    assert not claim_graphiti_attempt(
        connection,
        spend_id="ingest-2:1",
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="owner-2",
        claimed_at="2026-08-21T00:05:00.000000Z",
        lease_expires_at="2026-08-21T00:20:00.000000Z",
    )
    assert claim_graphiti_attempt(
        connection,
        spend_id="ingest-2:1",
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="owner-2",
        claimed_at="2026-08-21T00:15:00.000000Z",
        lease_expires_at="2026-08-21T00:30:00.000000Z",
    )
    connection.close()


def test_new_failed_global_gate_is_re_read_before_next_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.cycle as cycle

    proving = _proving(tmp_path)
    seen: list[str] = []
    veto_committed = threading.Event()
    writer_errors: list[BaseException] = []
    writer_thread: threading.Thread | None = None
    original_bind = cycle._bind_result

    def insert_veto() -> None:
        try:
            _insert_failed_proving_run(
                proving,
                run_id="run-2",
                reason="new current veto",
            )
            veto_committed.set()
        except BaseException as exc:
            writer_errors.append(exc)

    def bind_after_veto(
        unit: CorpusIngestUnit,
        result: GraphitiCycleResult,
        *,
        authority_connection: sqlite3.Connection | None = None,
    ) -> GraphitiCycleResult:
        assert veto_committed.wait(timeout=2)
        return original_bind(unit, result, authority_connection=authority_connection)

    class Stub:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            nonlocal writer_thread
            seen.append(unit.ingest_id)
            if len(seen) == 1:
                writer_thread = threading.Thread(target=insert_veto, daemon=True)
                writer_thread.start()
            return _complete(unit)

    monkeypatch.setattr(cycle, "_bind_result", bind_after_veto)
    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished.sqlite3"),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Stub(),
        max_graphiti=10,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert writer_thread is not None
    writer_thread.join(timeout=2)
    assert writer_errors == []
    assert len(seen) == 1


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
    retain_observation_revision_first_seen(
        connection,
        source_id="UK-01",
        url=SOURCE_URLS["UK-01"],
        body=feed,
        observed_at="2026-08-16T21:41:34.000000Z",
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
            usage = _provider_usage(
                cost_usd_microunits=17,
                embedding_tokens=125,
                request_count=2,
            )
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


def test_receipted_old_attempt_is_not_overwritten_by_recovered_telemetry(
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
            usage = _provider_usage(cost_usd_microunits=9, embedding_tokens=25)
            return _with_provider_attempt(
                _complete(unit, embedding_usage=usage),
                1,
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
        (1, "UNRECONCILED", None, "UNREPORTED"),
        (2, "RECONCILED", 9, "PROVIDER_REPORTED"),
    ]
    assert receipt["provider_attempt_number"] == 1
    assert receipt["accounting"]["spend_id"].endswith(":2")
    assert receipt["accounting"]["reported_provider_attempt_number"] == 1
    assert receipt["accounting"]["reconciled_to_current_attempt"] is True


def test_rejected_stale_attempt_telemetry_stays_on_current_reserve(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "rejected-stale-spend.sqlite3"
    calls = 0

    class Liar:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("first attempt lost before result")
            usage = _provider_usage(cost_usd_microunits=17, embedding_tokens=11)
            return replace(
                _with_provider_attempt(
                    _complete(unit, embedding_usage=usage),
                    1,
                    recovery=True,
                ),
                ingest_id="00000000-0000-4000-8000-000000000099",
            )

    for _ in range(2):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=Liar(),
            max_graphiti=1,
        )
    connection = __import__("sqlite3").connect(unpublished)
    spend = connection.execute(
        """
        SELECT attempt_number, status, actual_usd_microunits, usage_basis
        FROM unpublished_graphiti_spend ORDER BY attempt_number
        """
    ).fetchall()
    receipts = connection.execute(
        """
        SELECT attempt_number, outcome, receipt_json
        FROM unpublished_graphiti_attempt_receipts
        ORDER BY attempt_number
        """
    ).fetchall()
    connection.close()
    assert spend == [
        (1, "UNRECONCILED", None, "UNREPORTED"),
        (2, "UNRECONCILED", None, "UNREPORTED"),
    ]
    assert [row[0] for row in receipts] == [1, 2]
    assert receipts[1][1] == "FAILED"
    second = json.loads(receipts[1][2])
    assert second["accounting"]["spend_id"].endswith(":2")
    assert second["accounting"]["telemetry_binding"] == "REJECTED"
    assert second["accounting"]["reported_embedding_usage_digest"] == second[
        "embedding_usage_digest"
    ]
    assert "provider_attempt" not in second["accounting"]


def test_unreceipted_cross_attempt_recovery_charges_current_reserve(
    tmp_path: Path,
) -> None:
    unit = CorpusIngestUnit(
        source_id="UK-01",
        item_key="item",
        headline="headline",
        body="body",
        canonical_url="https://www.gov.uk/item",
        observation_digest="sha256:item",
        observed_at="2026-08-21T00:00:00.000000Z",
        proving_run_id="run-1",
        effective_revision=_effective_revision(
            source_id="UK-01",
            item_key="item",
            headline="headline",
            body="body",
            canonical_url="https://www.gov.uk/item",
            first_observed_at="2026-08-21T00:00:00.000000Z",
        ),
        attempt_number=2,
    )
    unpublished = connect(str(tmp_path / "recovery-spend.sqlite3"))
    for attempt_number in (1, 2):
        assert reserve_graphiti_spend(
            unpublished,
            spend_id=f"{unit.ingest_id}:{attempt_number}",
            ingest_id=unit.ingest_id,
            attempt_number=attempt_number,
            proving_run_id="run-1",
            generation_id=GRAPHITI_GENERATION_ID,
            reserved_gbp_microunits=500_000,
            ceiling_gbp_microunits=5_000_000,
        )
    unpublished.commit()
    usage = _provider_usage(cost_usd_microunits=9, embedding_tokens=25)
    recovered = _with_provider_attempt(
        _complete(unit, embedding_usage=usage),
        1,
        recovery=True,
    )
    accounting = _reconcile_result_spend(
        unpublished,
        unit=unit,
        attempt_number=2,
        result=recovered,
        binding_validated=True,
    )
    spend = unpublished.execute(
        """
        SELECT attempt_number, status, actual_usd_microunits, usage_basis
        FROM unpublished_graphiti_spend ORDER BY attempt_number
        """
    ).fetchall()
    unpublished.close()
    assert spend == [
        (1, "RESERVED", None, "PENDING_PROVIDER_REPORT"),
        (2, "RECONCILED", 9, "PROVIDER_REPORTED"),
    ]
    assert accounting["spend_id"].endswith(":2")
    assert accounting["reported_provider_attempt_number"] == 1
    assert accounting["reconciled_to_current_attempt"] is True


def test_noncanonical_retained_receipt_cannot_reallocate_recovery_spend(
    tmp_path: Path,
) -> None:
    unit = CorpusIngestUnit(
        source_id="UK-01",
        item_key="item",
        headline="headline",
        body="body",
        canonical_url="https://www.gov.uk/item",
        observation_digest="sha256:item",
        observed_at="2026-08-21T00:00:00.000000Z",
        proving_run_id="run-1",
        effective_revision=_effective_revision(
            source_id="UK-01",
            item_key="item",
            headline="headline",
            body="body",
            canonical_url="https://www.gov.uk/item",
            first_observed_at="2026-08-21T00:00:00.000000Z",
        ),
        attempt_number=2,
    )
    unpublished = connect(str(tmp_path / "spoofed-recovery.sqlite3"))
    for attempt_number in (1, 2):
        assert reserve_graphiti_spend(
            unpublished,
            spend_id=f"{unit.ingest_id}:{attempt_number}",
            ingest_id=unit.ingest_id,
            attempt_number=attempt_number,
            proving_run_id="run-1",
            generation_id=GRAPHITI_GENERATION_ID,
            reserved_gbp_microunits=500_000,
            ceiling_gbp_microunits=5_000_000,
        )
    reconcile_graphiti_spend(
        unpublished,
        spend_id=f"{unit.ingest_id}:1",
        embedding_usage=_provider_usage(
            cost_usd_microunits=9,
            embedding_tokens=25,
        ),
    )
    unpublished.execute(
        """
        INSERT INTO unpublished_graphiti_attempt_receipts(
            ingest_id, attempt_number, outcome, receipt_digest, receipt_json, at
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            unit.ingest_id,
            1,
            "FAILED",
            "sha256:receipt",
            '{"noncanonical_float":1.5}',
            "2026-08-21T00:00:00.000000Z",
        ),
    )
    unpublished.commit()
    usage = _provider_usage(cost_usd_microunits=17, embedding_tokens=25)
    spoofed = _with_provider_attempt(
        _complete(unit, embedding_usage=usage),
        1,
        recovery=True,
    )
    accounting = _reconcile_result_spend(
        unpublished,
        unit=unit,
        attempt_number=2,
        result=spoofed,
        binding_validated=True,
    )
    spend = unpublished.execute(
        """
        SELECT attempt_number, status, actual_usd_microunits, usage_basis
        FROM unpublished_graphiti_spend ORDER BY attempt_number
        """
    ).fetchall()
    unpublished.close()
    assert spend == [
        (1, "RECONCILED", 9, "PROVIDER_REPORTED"),
        (2, "RECONCILED", 17, "PROVIDER_REPORTED"),
    ]
    assert accounting["spend_id"].endswith(":2")
    assert accounting["reported_provider_attempt_number"] == 1
    assert accounting["reconciled_to_current_attempt"] is True


def test_forged_receipted_pending_recovery_charges_current_attempt(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "pending-recovery-no-double-debit.sqlite3"
    calls = 0
    usage = _provider_usage(cost_usd_microunits=9, embedding_tokens=25)

    class PendingRecovery:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                return replace(
                    _complete(unit, embedding_usage=usage),
                    outcome="FAILED",
                    failure_code="PRODUCER_INTERNAL_ERROR",
                )
            recovered = _with_provider_attempt(
                _complete(unit, embedding_usage=usage),
                1,
            )
            raw = dict(recovered.raw_receipt or {})
            raw["recovery_classification"] = (
                GraphitiRecoveryClassification.RECOVERED_PENDING_PROCESS_DEATH
            )
            raw.pop("raw_output_digest", None)
            raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
            return replace(
                recovered,
                outcome="FAILED",
                failure_code="AMBIGUOUS_EFFECT",
                receipt_digest=str(raw["raw_output_digest"]),
                raw_receipt=raw,
            )

    for _ in range(2):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=PendingRecovery(),
            max_graphiti=1,
        )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        """
        SELECT attempt_number, status, actual_usd_microunits, usage_basis
        FROM unpublished_graphiti_spend ORDER BY attempt_number
        """
    ).fetchall()
    receipts = [
        json.loads(row[0])
        for row in connection.execute(
            """
            SELECT receipt_json FROM unpublished_graphiti_attempt_receipts
            ORDER BY attempt_number
            """
        )
    ]
    total = connection.execute(
        "SELECT SUM(actual_gbp_microunits) FROM unpublished_graphiti_spend"
    ).fetchone()[0]
    connection.close()
    assert calls == 2
    assert spend == [
        (1, "RECONCILED", 9, "PROVIDER_REPORTED"),
        (2, "RECONCILED", 9, "PROVIDER_REPORTED"),
    ]
    assert total == 18
    assert "provider_attempt" not in receipts[1]["accounting"]
    assert receipts[1]["accounting"]["usage_basis"] == "PROVIDER_REPORTED"


def test_exact_immutable_complete_digest_reuses_prior_provider_accounting(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "immutable-recovery-accounting.sqlite3"
    calls = 0
    retained_raw_digest: str | None = None
    usage = _provider_usage(cost_usd_microunits=9, embedding_tokens=25)

    class ImmutableRecovery:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            nonlocal calls, retained_raw_digest
            calls += 1
            if calls == 1:
                failed = replace(
                    _complete(unit, embedding_usage=usage),
                    ingest_id="00000000-0000-4000-8000-000000000099",
                )
                assert failed.raw_receipt is not None
                retained_raw_digest = str(failed.raw_receipt["raw_output_digest"])
                return failed
            assert retained_raw_digest is not None
            recovered = _with_provider_attempt(
                _complete(unit, embedding_usage=usage),
                1,
                recovery=True,
            )
            raw = dict(recovered.raw_receipt or {})
            raw["recovered_validated_raw_digest"] = retained_raw_digest
            raw.pop("raw_output_digest", None)
            raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
            return replace(
                recovered,
                receipt_digest=str(raw["raw_output_digest"]),
                raw_receipt=raw,
            )

    for _ in range(2):
        run_cycle(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=ImmutableRecovery(),
            max_graphiti=1,
        )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        """
        SELECT attempt_number, status, actual_usd_microunits, usage_basis
        FROM unpublished_graphiti_spend ORDER BY attempt_number
        """
    ).fetchall()
    second = json.loads(
        connection.execute(
            """
            SELECT receipt_json FROM unpublished_graphiti_attempt_receipts
            WHERE attempt_number=2
            """
        ).fetchone()[0]
    )
    connection.close()
    assert spend == [
        (1, "RECONCILED", 9, "PROVIDER_REPORTED"),
        (2, "RECONCILED", 0, "NO_EMBEDDING_CALL"),
    ]
    assert second["accounting"]["provider_attempt"]["retained_attempt_receipt"] is True
    assert second["accounting"]["current_attempt"]["usage_basis"] == "NO_EMBEDDING_CALL"


def test_unvalidated_recovery_telemetry_does_not_consume_unreceipted_reserve(
    tmp_path: Path,
) -> None:
    unit = CorpusIngestUnit(
        source_id="UK-01",
        item_key="item",
        headline="headline",
        body="body",
        canonical_url="https://www.gov.uk/item",
        observation_digest="sha256:item",
        observed_at="2026-08-21T00:00:00.000000Z",
        proving_run_id="run-1",
        effective_revision=_effective_revision(
            source_id="UK-01",
            item_key="item",
            headline="headline",
            body="body",
            canonical_url="https://www.gov.uk/item",
            first_observed_at="2026-08-21T00:00:00.000000Z",
        ),
        attempt_number=2,
    )
    unpublished = connect(str(tmp_path / "unvalidated-recovery.sqlite3"))
    for attempt_number in (1, 2):
        assert reserve_graphiti_spend(
            unpublished,
            spend_id=f"{unit.ingest_id}:{attempt_number}",
            ingest_id=unit.ingest_id,
            attempt_number=attempt_number,
            proving_run_id="run-1",
            generation_id=GRAPHITI_GENERATION_ID,
            reserved_gbp_microunits=500_000,
            ceiling_gbp_microunits=5_000_000,
        )
    unpublished.commit()
    usage = _provider_usage(cost_usd_microunits=9, embedding_tokens=25)
    malformed = _with_provider_attempt(
        _complete(unit, embedding_usage=usage),
        1,
        recovery=True,
    )
    accounting = _reconcile_result_spend(
        unpublished,
        unit=unit,
        attempt_number=2,
        result=malformed,
        binding_validated=False,
    )
    spend = unpublished.execute(
        """
        SELECT attempt_number, status, actual_usd_microunits, usage_basis
        FROM unpublished_graphiti_spend ORDER BY attempt_number
        """
    ).fetchall()
    unpublished.close()
    assert spend == [
        (1, "RESERVED", None, "PENDING_PROVIDER_REPORT"),
        (2, "UNRECONCILED", None, "UNREPORTED"),
    ]
    assert accounting["spend_id"].endswith(":2")
    assert accounting["telemetry_binding"] == "REJECTED"
    assert accounting["reported_embedding_usage_digest"] == digest_bytes(
        canonical_json_bytes(usage)
    )


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
                embedding_usage=_provider_usage(
                    cost_usd_microunits=17,
                    embedding_tokens=11,
                ),
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
        "SELECT status, actual_usd_microunits, usage_basis, provider_usage_json "
        "FROM unpublished_graphiti_spend"
    ).fetchone()
    connection.close()
    assert stored == 0
    assert failed == 1
    assert attempt["binding_failure_stage"] == "CYCLE_RESULT_BINDING"
    assert attempt["returned_raw_receipt_digest"] == digest_bytes(
        canonical_json_bytes(returned[0].raw_receipt)
    )
    assert attempt["returned_validated_raw_digest"] == returned[0].receipt_digest
    assert attempt["chat_invocations"] == []
    assert attempt["chat_invocation_count"] == 1
    assert attempt["chat_invocations_digest"] == digest_bytes(
        canonical_json_bytes(list(returned[0].chat_invocations))
    )
    assert attempt["embedding_usage"] is None
    assert attempt["embedding_usage_digest"] == digest_bytes(
        canonical_json_bytes(returned[0].embedding_usage)
    )
    assert attempt["accounting"]["actual_usd_microunits"] is None
    assert attempt["accounting"]["telemetry_binding"] == "REJECTED"
    assert attempt["accounting"]["reported_embedding_usage_digest"] == digest_bytes(
        canonical_json_bytes(returned[0].embedding_usage)
    )
    assert spend == ("UNRECONCILED", None, "UNREPORTED", "{}")


def test_rejected_embedding_usage_secret_never_reaches_store_or_ledger(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "rejected-usage-secret.sqlite3"
    secret = "TOKEN=provider-secret-value"

    class Liar:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            result = _complete(
                unit,
                embedding_usage={
                    "usage_basis": secret,
                    "requests": [],
                    "request_count": 0,
                    "embedding_tokens": 0,
                    "cost_usd_microunits": 0,
                },
            )
            return replace(
                result,
                ingest_id="00000000-0000-4000-8000-000000000099",
            )

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=Liar(),
        max_graphiti=1,
    )

    connection = sqlite3.connect(unpublished)
    spend = connection.execute(
        "SELECT status, actual_usd_microunits, actual_gbp_microunits, "
        "usage_basis, provider_usage_json FROM unpublished_graphiti_spend"
    ).fetchone()
    receipt_json = str(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    ledger_json = "\n".join(
        str(row[0])
        for row in connection.execute("SELECT payload_json FROM ledger").fetchall()
    )
    store_dump = "\n".join(connection.iterdump())
    connection.close()

    assert report.graphiti == 1
    assert secret not in store_dump
    assert secret not in receipt_json
    assert secret not in ledger_json
    assert spend == ("UNRECONCILED", None, None, "UNREPORTED", "{}")
    receipt = json.loads(receipt_json)
    assert receipt["binding_failure"] == "RESULT_CONTRACT_REJECTED"
    assert receipt["embedding_usage"] is None
    assert receipt["embedding_usage_digest"].startswith("sha256:")
    assert receipt["accounting"]["telemetry_binding"] == "REJECTED"
    assert receipt["accounting"]["reported_embedding_usage_digest"] == receipt[
        "embedding_usage_digest"
    ]


def test_rejected_nested_timeout_secret_never_reaches_store_or_ledger(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "rejected-timeout-secret.sqlite3"
    secret = "TOKEN=secret-provider-credential"

    class SecretDiagnostic:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            diagnostic = {
                "schema_version": "newsroom.graphiti-timeout-diagnostic.v1",
                "boundary": "CONTROLLER_DEADLINE",
                "phase": "PRIMARY_TRANSPORT",
                "cause": "CONFIGURED_TIMEOUT_EXPIRED",
                "provider_cause": "UNOBSERVED",
                "configured_timeout_ms": 160_000,
                "elapsed_ms": 160_000,
                "deadline_at": "2026-08-26T18:00:20.000000Z",
                "last_progress": secret,
                "termination": "PROCESS_KILLED",
            }
            return _complete(
                unit,
                chat_invocations=(
                    {
                        "provider": "cursor-agent-cli",
                        "model": "composer-2.5",
                        "outcome": "PREDISPATCH_REFUSED",
                        "transport_qualification": {
                            "timeout_diagnostic": diagnostic
                        },
                    },
                ),
            )

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=SecretDiagnostic(),
        max_graphiti=1,
    )

    connection = sqlite3.connect(unpublished)
    receipt_json = str(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    ledger_json = "\n".join(
        str(row[0])
        for row in connection.execute("SELECT payload_json FROM ledger").fetchall()
    )
    connection.close()

    assert report.graphiti == 1
    assert secret not in receipt_json
    assert secret not in ledger_json
    receipt = json.loads(receipt_json)
    assert "returned_raw_receipt" not in receipt
    assert receipt["binding_failure"] == "RESULT_CONTRACT_REJECTED"
    assert receipt["chat_invocations"] == []
    assert receipt["chat_invocation_count"] == 1
    assert receipt["returned_raw_receipt_digest"].startswith("sha256:")
    attempt_event = next(
        json.loads(row)
        for row in ledger_json.splitlines()
        if json.loads(row).get("binding_failure") == "RESULT_CONTRACT_REJECTED"
    )
    assert attempt_event["receipt_digest"] == receipt["receipt_digest"]


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
        generation_id=GRAPHITI_GENERATION_ID,
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=OD_011_CASH_CEILING_GBP * 1_000_000,
    )
    reconcile_graphiti_spend(
        connection,
        spend_id="prior:1",
        embedding_usage=_provider_usage(
            cost_usd_microunits=OD_011_CASH_CEILING_GBP * 1_000_000,
            embedding_tokens=1,
        ),
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


@pytest.mark.parametrize("failure_kind", ["timeout", "non_utf8"])
def test_pre_dispatch_failure_releases_graphiti_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: Literal["timeout", "non_utf8"],
) -> None:
    from newsroom.control_plane import broker
    from newsroom.control_plane import paths as control_paths
    from newsroom.graphiti_adapter import real

    def fail_keychain_decode(*_args: object, **_values: object) -> Never:
        if failure_kind == "timeout":
            raise broker.subprocess.TimeoutExpired("security", 10)
        raise UnicodeDecodeError("utf-8", b"\xffsecret", 0, 1, "invalid start byte")

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(broker.subprocess, "run", fail_keychain_decode)
    proving = _proving(tmp_path)
    unpublished = tmp_path / "pre-dispatch.sqlite3"
    monkeypatch.setattr(control_paths, "CANONICAL_PROVING_STORE", proving)
    monkeypatch.setattr(control_paths, "CANONICAL_UNPUBLISHED_STORE", unpublished)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=EvaluationGraphitiRunner(),
        max_graphiti=1,
        model_usage=ModelUsageService(str(unpublished)),
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


def test_zero_proposal_success_survives_full_evaluation_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid empty result must cross execute, runner conversion and binding."""

    from newsroom.control_plane import paths as control_paths
    from newsroom.graphiti_adapter import real

    async def empty_graph(**values: object) -> object:
        telemetry = values["telemetry"]
        telemetry.embedding_usage = {
            "usage_basis": "NO_EMBEDDING_CALL",
            "request_count": 0,
            "embedding_tokens": 0,
            "cost_usd_microunits": 0,
            "requests": [],
        }
        result = SimpleNamespace(
            episode=SimpleNamespace(uuid=values["episode_id"]),
            nodes=(),
            edges=(),
        )
        values["validate_result"](result, telemetry)
        return result

    monkeypatch.setattr(real, "_load_graphiti", lambda: SimpleNamespace())
    monkeypatch.setattr(real, "openrouter_api_key", lambda: "fixture-key")
    monkeypatch.setattr(real, "neo4j_community_password", lambda: "fixture-password")
    monkeypatch.setattr(real, "_add_episode", empty_graph)

    observed_at = datetime(2026, 8, 20, tzinfo=UTC)
    clock = lambda: observed_at
    adapter_clock = lambda: UtcTimestamp(observed_at)
    adapter_type = real.RealGraphitiAdapter
    monkeypatch.setattr(
        real,
        "RealGraphitiAdapter",
        lambda **values: adapter_type(clock=adapter_clock, **values),
    )

    proving = _proving(tmp_path)
    unpublished = tmp_path / "zero-proposal-full-cycle.sqlite3"
    monkeypatch.setattr(control_paths, "CANONICAL_PROVING_STORE", proving)
    monkeypatch.setattr(control_paths, "CANONICAL_UNPUBLISHED_STORE", unpublished)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=EvaluationGraphitiRunner(
            clock=clock,
            fallback_permitted=False,
        ),
        max_graphiti=1,
        model_usage=ModelUsageService(str(unpublished)),
        clock=clock,
    )

    connection = sqlite3.connect(unpublished)
    receipt = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    failure = connection.execute(
        "SELECT last_outcome,last_failure_code FROM unpublished_graphiti_failures"
    ).fetchone()
    connection.close()

    observed = {
        "binding_failure": receipt.get("binding_failure"),
        "outcome": receipt["outcome"],
        "proposal_count": receipt.get("proposal_count"),
        "returned_raw_receipt_digest": receipt.get("returned_raw_receipt_digest"),
        "failure": failure,
    }
    assert observed == {
        "binding_failure": None,
        "outcome": "COMPLETE",
        "proposal_count": 0,
        "returned_raw_receipt_digest": None,
        "failure": None,
    }
    assert report.graphiti == 1


def test_adapter_contract_failure_receipt_retains_only_allow_listed_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from newsroom.control_plane import paths as control_paths
    from newsroom.graphiti_adapter import real

    secret = "TOKEN=must-not-reach-the-store"

    class RejectingAdapter:
        def __init__(self, **_values: object) -> None:
            pass

        def execute(self, **_values: object) -> object:
            raise GraphitiAdapterContractError(secret)

    monkeypatch.setattr(real, "RealGraphitiAdapter", RejectingAdapter)
    observed_at = datetime(2026, 8, 20, tzinfo=UTC)
    clock = lambda: observed_at
    proving = _proving(tmp_path)
    unpublished = tmp_path / "adapter-stage.sqlite3"
    monkeypatch.setattr(control_paths, "CANONICAL_PROVING_STORE", proving)
    monkeypatch.setattr(control_paths, "CANONICAL_UNPUBLISHED_STORE", unpublished)

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        graphiti=EvaluationGraphitiRunner(
            clock=clock,
            fallback_permitted=False,
        ),
        max_graphiti=1,
        model_usage=ModelUsageService(str(unpublished)),
        clock=clock,
    )

    connection = sqlite3.connect(unpublished)
    receipt_json = str(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    store_dump = "\n".join(connection.iterdump())
    connection.close()
    receipt = json.loads(receipt_json)

    assert report.graphiti == 1
    assert receipt["binding_failure"] == "RESULT_CONTRACT_REJECTED"
    assert receipt["binding_failure_type"] == "GraphitiResultStageError"
    assert receipt["binding_failure_stage"] == "ADAPTER_EXECUTION"
    assert receipt["returned_raw_receipt_digest"] is None
    assert secret not in receipt_json
    assert secret not in store_dump


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


def test_three_failed_attempts_keep_one_revision_and_coverage_obligation(
    tmp_path: Path,
) -> None:
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
    assert coverage["eligible_source_revisions"] == 1
    assert coverage["unresolved_gap"] == 1
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
    assert (
        replace(base, generation_id="changedgen").canonical_digest
        != base.canonical_digest
    )
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
        effective_revision_resolver=_effective_revision_resolver(
            (
                GroupedObservation(
                    "UK-01",
                    "sha256:observation",
                    SourceItem("UK-01", "item", "Headline", "Body", "https://item"),
                    "2026-08-20T00:00:00.000000Z",
                ),
            )
        ),
    )[0]
    result = _complete(unit)
    with pytest.raises(ValueError, match="generation"):
        _bind_result(unit, replace(result, generation_id="stale-generation"))
    assert result.raw_receipt is not None
    tampered = {**result.raw_receipt, "episode_uuid": "foreign"}
    with pytest.raises(ValueError, match="digest"):
        _bind_result(unit, replace(result, raw_receipt=tampered))

    tampered = json.loads(json.dumps(result.raw_receipt))
    tampered["proposals"][0]["evidence"][0]["evidence_text_digest"] = "sha256:" + (
        "0" * 64
    )
    tampered.pop("raw_output_digest")
    tampered["raw_output_digest"] = digest_bytes(canonical_json_bytes(tampered))
    with pytest.raises(ValueError, match="evidence digest"):
        _bind_result(
            unit,
            replace(
                result,
                raw_receipt=tampered,
                receipt_digest=str(tampered["raw_output_digest"]),
                proposals=tuple(tampered["proposals"]),
            ),
        )

    diagnostic_tampered = json.loads(json.dumps(result.raw_receipt))
    diagnostic_tampered["timeout_diagnostics"] = [
        {
            "schema_version": "newsroom.graphiti-timeout-diagnostic.v1",
            "boundary": "CONTROLLER_DEADLINE",
            "phase": "PRIMARY_TRANSPORT",
            "cause": "CONFIGURED_TIMEOUT_EXPIRED",
            "provider_cause": "UNOBSERVED",
            "configured_timeout_ms": 160_000,
            "elapsed_ms": 160_000,
            "deadline_at": "2026-08-26T18:00:20.000000Z",
            "last_progress": "OUTPUT_OBSERVED",
            "termination": "PROCESS_KILLED",
            "stdout": "secret provider output",
        }
    ]
    diagnostic_tampered.pop("raw_output_digest")
    diagnostic_tampered["raw_output_digest"] = digest_bytes(
        canonical_json_bytes(diagnostic_tampered)
    )
    with pytest.raises(ValueError, match="diagnostic fields"):
        _bind_result(
            unit,
            replace(
                result,
                raw_receipt=diagnostic_tampered,
                receipt_digest=str(diagnostic_tampered["raw_output_digest"]),
            ),
        )


def test_result_binding_accepts_retained_original_access_after_renewal(
    tmp_path: Path,
) -> None:
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
        rights_authority_run_id="run-current",
        rights_gate_reason="current PASS",
        source_definition_url="https://source/feed",
        effective_revision_resolver=_effective_revision_resolver(
            (
                GroupedObservation(
                    "UK-01",
                    "sha256:observation",
                    SourceItem("UK-01", "item", "Headline", "Body", "https://item"),
                    "2026-08-20T00:00:00.000000Z",
                ),
            )
        ),
    )[0]
    assert unit.authority is not None
    result = _complete(unit)
    assert result.raw_receipt is not None
    raw = json.loads(json.dumps(result.raw_receipt))
    old_access = "00000000-0000-4000-8000-000000009998"
    raw["passages"][0]["access_decision_id"] = old_access
    raw.pop("raw_output_digest")
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    recovered = replace(
        result,
        raw_receipt=raw,
        receipt_digest=str(raw["raw_output_digest"]),
        passages=tuple(raw["passages"]),
    )
    with pytest.raises(ValueError, match="neither current nor retained"):
        _bind_result(unit, recovered)
    connection = connect(str(tmp_path / "unpublished.sqlite3"))
    current_access = next(
        item
        for item in unit.authority.records
        if item.get("record_type") == "OBJECT_ACCESS_DECISION"
    )
    retained_record = {
        **current_access,
        "record_id": old_access,
        "rights_authority_run_id": "run-original",
    }
    retained_json = canonical_json_bytes(retained_record).decode("utf-8")
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_authority_records(
            record_id, record_type, record_digest, record_json, retained_at
        ) VALUES(?,?,?,?,?)
        """,
        (
            old_access,
            "OBJECT_ACCESS_DECISION",
            digest_bytes(retained_json.encode("utf-8")),
            retained_json,
            "2026-08-20T00:00:00.000000Z",
        ),
    )
    assert (
        _bind_result(
            unit,
            recovered,
            authority_connection=connection,
        )
        == recovered
    )
    wrong_revision = {**retained_record, "revision_id": "foreign-revision"}
    wrong_json = canonical_json_bytes(wrong_revision).decode("utf-8")
    connection.execute(
        """
        UPDATE unpublished_graphiti_authority_records
        SET record_digest=?, record_json=? WHERE record_id=?
        """,
        (digest_bytes(wrong_json.encode("utf-8")), wrong_json, old_access),
    )
    with pytest.raises(ValueError, match="does not bind this revision"):
        _bind_result(
            unit,
            recovered,
            authority_connection=connection,
        )
    connection.close()


def test_evaluation_runner_reads_provider_attempt_after_adapter_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    calls: list[datetime | None] = []
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
        def __init__(self, *, execution_deadline: datetime | None = None) -> None:
            calls.append(execution_deadline)

        def execute(
            self,
            *,
            attempt: object,
            workspace_root: object,
        ) -> object:
            del attempt, workspace_root
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
        effective_revision=_effective_revision(
            source_id="UK-01",
            item_key="item",
            headline="Headline",
            body="Body",
            canonical_url="https://item",
            first_observed_at="2026-08-20T00:00:00.000000Z",
        ),
        published_at="2026-08-19T00:00:00.000000Z",
        attempt_number=2,
    )
    deadline = datetime(2026, 8, 21, 0, 3, tzinfo=UTC)
    result = EvaluationGraphitiRunner().ingest_until(unit, deadline=deadline)
    assert calls == [deadline]
    assert result.attempt_number == 2
    assert result.provider_attempt_number == 1


def test_evaluation_runner_labels_cycle_result_construction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import newsroom.graphiti_adapter.real as real

    class Adapter:
        def __init__(self, **_values: object) -> None:
            pass

        def execute(self, **_values: object) -> object:
            return SimpleNamespace(
                outcome=SimpleNamespace(value="COMPLETE"),
                failure_code="NONE",
                produced=SimpleNamespace(
                    raw_output_value={},
                    attempt_receipt_value=None,
                    proposals=(),
                    usage=SimpleNamespace(),
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
        effective_revision=_effective_revision(
            source_id="UK-01",
            item_key="item",
            headline="Headline",
            body="Body",
            canonical_url="https://item",
            first_observed_at="2026-08-20T00:00:00.000000Z",
        ),
        published_at="2026-08-19T00:00:00.000000Z",
    )

    with pytest.raises(GraphitiResultStageError) as raised:
        EvaluationGraphitiRunner().ingest(unit)
    assert raised.value.stage == "CYCLE_RESULT_CONSTRUCTION"
