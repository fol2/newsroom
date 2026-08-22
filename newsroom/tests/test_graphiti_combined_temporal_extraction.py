"""Provider-free proofs for NewsroomCombinedTemporalExtractionV1 (#747).

Seams under test, taken from issue #747:

- compact schema and canonical digest
- deterministic evidence segmentation of one retained revision
- Newsroom prompt builder (no graphiti-core conversational-memory prompt)
- injected fake transport: one generate_response leaf, never BatchEdgeTimestamps
- normalisation to Graphiti-compatible node/edge proposals with temporal fields
- fail-closed malformed / temporal / evidence leaves
- prompt/schema byte comparison versus graphiti-core 0.29.3
- owner-gated live packet remains unauthorised
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_canonical
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CALL_SHAPES_PATH,
    CONTRACT_NAME,
    LIVE_PACKET_PATH,
    LOCAL_NEW,
    MEASUREMENTS_PATH,
    SCHEMA,
    SCHEMA_DIGEST,
    UNMEASURED,
    CombinedTemporalFailureCode,
    CombinedTemporalLeaf,
    CombinedTemporalOutcome,
    CombinedTemporalTransportResult,
    build_compact_prompt,
    extract_combined_temporal,
    segment_source,
)
from newsroom.graphiti_adapter.combined_temporal_fixtures import (
    FIXTURES,
    INGESTED_AT,
    MALFORMED_CASES,
    GoldFixture,
    fixture,
)
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_CORE_RELEASE
from newsroom.graphiti_adapter.identity import configuration_digest, content_digest
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION

_REPO = Path(__file__).resolve().parents[2]
_RESEARCH = _REPO / "docs" / "research"
GRAPHITI_MEMORY_PHRASE = "AI agent memory system"


class _FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def generate_response(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        response_model: str,
    ) -> CombinedTemporalTransportResult:
        del prompt, schema, response_model
        return CombinedTemporalTransportResult(
            raw=self.payload,
            framework_version=GRAPHITI_CORE_RELEASE,
            model_version=None,
            token_usage={"basis": UNMEASURED},
            provider_cost=None,
        )


def _extract(
    name: str, payload: object | None = None
) -> tuple[CombinedTemporalLeaf, GoldFixture]:
    case = fixture(name)
    transport = _FakeTransport(case.gold if payload is None else payload)
    return extract_combined_temporal(case.revision, transport=transport), case


def test_compact_schema_matches_the_ticket_contract() -> None:
    assert CONTRACT_NAME == "NewsroomCombinedTemporalExtractionV1"
    assert SCHEMA["type"] == "object"
    assert SCHEMA["additionalProperties"] is False
    assert SCHEMA["required"] == ["entities", "facts"]
    entity = SCHEMA["properties"]["entities"]["items"]
    fact = SCHEMA["properties"]["facts"]["items"]
    assert entity["properties"]["evidence_segment_ids"]["items"]["type"] == "integer"
    assert fact["properties"]["evidence_segment_ids"]["items"]["type"] == "integer"
    assert fact["properties"]["valid_at"]["type"] == ["string", "null"]
    assert fact["properties"]["invalid_at"]["type"] == ["string", "null"]
    assert SCHEMA_DIGEST == digest_canonical(SCHEMA)
    assert SCHEMA_DIGEST.startswith("sha256:")


def test_segmentation_round_trips_retained_bytes_and_uses_integer_ids() -> None:
    body = fixture("pair-current").revision.body
    segments = segment_source(body)
    encoded = b"".join(
        body.encode("utf-8")[item.start_byte : item.end_byte] for item in segments
    )
    assert encoded == body.encode("utf-8")
    assert [item.segment_id for item in segments] == list(range(len(segments)))
    assert all(item.end_byte > item.start_byte for item in segments)


def test_long_chunk_keeps_the_8192_byte_boundary() -> None:
    body = fixture("long-8192").revision.body
    assert len(body.encode("utf-8")) == 8192
    segments = segment_source(body)
    assert b"".join(item.text.encode("utf-8") for item in segments) == body.encode(
        "utf-8"
    )


def test_prompt_retains_every_segment_and_excludes_predecessor_body() -> None:
    case = fixture("correction-revision")
    prompt = build_compact_prompt(case.revision)
    assert case.revision.body in prompt.text
    assert "Technology and Living curriculum" not in prompt.text
    assert "Design and Applied Technology" in prompt.text
    assert case.revision.predecessor_revision_id in prompt.text
    assert str(SCHEMA["required"]) not in prompt.text or "entities" in prompt.text
    for segment in prompt.segments:
        assert f"[{segment.segment_id}]" in prompt.text
    assert "Do not fork" not in prompt.text
    assert "BatchEdgeTimestamps" not in prompt.text
    assert GRAPHITI_MEMORY_PHRASE not in prompt.text


def test_zero_result_makes_exactly_one_generate_response_request() -> None:
    leaf, _case = _extract("zero-result")
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
    assert leaf.failure_code is CombinedTemporalFailureCode.NONE
    assert [call["response_model"] for call in leaf.transport_calls] == [
        CONTRACT_NAME
    ]
    assert leaf.payload == {"entities": [], "facts": []}
    assert leaf.nodes == ()
    assert leaf.edges == ()
    assert leaf.graph_effect_attempted is False
    assert leaf.embedding_skipped is False
    assert leaf.journal_skipped is False
    assert leaf.rollback_skipped is True
    assert leaf.node_resolutions == ()


def test_nonzero_relation_makes_one_request_and_sets_temporal_fields() -> None:
    leaf, case = _extract("pair-current")
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert [call["response_model"] for call in leaf.transport_calls] == [
        CONTRACT_NAME
    ]
    assert "BatchEdgeTimestamps" not in [
        call["response_model"] for call in leaf.transport_calls
    ]
    names = {node.name for node in leaf.nodes}
    assert names == {
        "Legislative Council",
        "Technology and Living curriculum",
    }
    assert len(leaf.edges) == 1
    assert leaf.edges[0].name == "ASKED_ABOUT"
    assert leaf.edges[0].valid_at is None
    assert leaf.edges[0].invalid_at is None
    assert leaf.graph_effect_attempted is False
    assert leaf.embedding_skipped is False
    assert leaf.journal_skipped is False
    assert leaf.rollback_skipped is True
    assert leaf.node_resolutions == (LOCAL_NEW, LOCAL_NEW)
    assert all(node.attributes["resolution"] == LOCAL_NEW for node in leaf.nodes)
    assert all("embedding_digest" in edge.attributes for edge in leaf.edges)
    assert all(node.attributes["entity_type_id"] == 0 for node in leaf.nodes)
    assert leaf.edges[0].attributes["evidence_segment_ids"] == [0]
    assert case.gold["facts"][0]["source_local_id"] != case.gold["facts"][0][
        "target_local_id"
    ]


@pytest.mark.parametrize(
    ("name", "expect_valid", "expect_invalid"),
    (
        ("explicit-valid-at", datetime(2026, 8, 20, tzinfo=UTC), None),
        ("explicit-invalid-at", None, datetime(2026, 3, 31, tzinfo=UTC)),
        ("relative-date", datetime(2026, 8, 20, tzinfo=UTC), None),
        ("null-temporal", None, None),
    ),
)
def test_temporal_bounds_parse_from_the_primary_object(
    name: str,
    expect_valid: datetime | None,
    expect_invalid: datetime | None,
) -> None:
    leaf, _case = _extract(name)
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert len(leaf.edges) == 1
    assert leaf.edges[0].valid_at == expect_valid
    assert leaf.edges[0].invalid_at == expect_invalid
    assert len(leaf.transport_calls) == 1


def test_every_success_fixture_connects_entities_and_resolves_evidence() -> None:
    for case in FIXTURES:
        if case.gold["facts"] == []:
            continue
        leaf, _ = _extract(case.name)
        assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
        local_ids = {entity["local_id"] for entity in leaf.payload["entities"]}
        connected: set[int] = set()
        for fact in leaf.payload["facts"]:
            source = fact["source_local_id"]
            target = fact["target_local_id"]
            assert source in local_ids
            assert target in local_ids
            assert source != target
            connected.update((source, target))
            ranges = leaf.evidence_ranges[fact["fact"]]
            retained = b"".join(
                case.revision.body.encode("utf-8")[item.start_byte : item.end_byte]
                for item in ranges
            ).decode("utf-8")
            assert fact["fact"] in retained
        assert connected == local_ids


def test_normalisation_is_stable_under_key_and_order_variation() -> None:
    case = fixture("several-relations")
    shuffled = {
        "facts": list(reversed(case.gold["facts"])),
        "entities": list(reversed(case.gold["entities"])),
    }
    first, _ = _extract("several-relations")
    second = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(shuffled),
    )
    assert first.payload_digest == second.payload_digest
    assert first.payload == second.payload


def test_same_name_entities_keep_distinct_local_identities() -> None:
    leaf, _case = _extract("same-name")
    names = [node.name for node in leaf.nodes]
    assert names.count("Lee") == 2
    assert len({node.uuid for node in leaf.nodes}) == 3
    sources = {edge.source_node_uuid for edge in leaf.edges}
    assert len(sources) == 2


def test_implied_relation_is_absent_from_gold_and_rejected_if_emitted() -> None:
    leaf, case = _extract("no-implied-relation")
    types = {edge.name for edge in leaf.edges}
    assert "WORKS_FOR" not in types
    assert types == {"ATTENDED", "HOSTED"}

    forged = {
        "entities": case.gold["entities"],
        "facts": [
            *case.gold["facts"],
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "WORKS_FOR",
                "fact": "Ms Chan works for the Education Bureau.",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            },
        ],
    }
    failed = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(forged),
    )
    assert failed.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert failed.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED
    assert len(failed.transport_calls) == 1
    assert failed.graph_effect_attempted is False
    assert failed.raw_output_digest is not None

    lexical = {
        "entities": case.gold["entities"],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 2,
                "relation_type": "WORKS_FOR",
                "fact": "Ms Chan attended the briefing.",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }
    rejected = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(lexical),
    )
    assert rejected.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert rejected.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


@pytest.mark.parametrize("name", [case.name for case in MALFORMED_CASES])
def test_malformed_primary_object_fails_closed_without_retry(name: str) -> None:
    case = next(item for item in MALFORMED_CASES if item.name == name)
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.payload),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is case.failure_code
    assert len(leaf.transport_calls) == 1
    assert leaf.nodes == ()
    assert leaf.edges == ()
    assert leaf.graph_effect_attempted is False


def test_relative_date_text_is_not_accepted_as_a_timestamp() -> None:
    case = fixture("relative-date")
    payload = json.loads(json.dumps(case.gold))
    payload["facts"][0]["valid_at"] = "yesterday"
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(payload),
    )
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert len(leaf.transport_calls) == 1


def test_correction_revision_does_not_contaminate_the_prompt() -> None:
    leaf, case = _extract("correction-revision")
    names = {node.name for node in leaf.nodes}
    assert "Design and Applied Technology" in names
    assert "Technology and Living curriculum" not in names
    assert case.revision.predecessor_body not in leaf.prompt.text


def test_edge_guard_keeps_primary_temporal_fields() -> None:
    leaf, _ = _extract("explicit-valid-at")
    assert leaf.edges[0].valid_at == datetime(2026, 8, 20, tzinfo=UTC)
    assert leaf.guarded_edges[0].valid_at == datetime(2026, 8, 20, tzinfo=UTC)
    assert leaf.guarded_edges[0].invalid_at is None


def test_ingest_time_does_not_replace_source_reference_time() -> None:
    leaf, case = _extract("pair-current")
    ingested = datetime(2026, 8, 22, 12, tzinfo=UTC)
    source = datetime(2026, 8, 21, tzinfo=UTC)
    assert case.revision.ingested_at == INGESTED_AT
    assert leaf.nodes[0].created_at == ingested
    assert leaf.edges[0].created_at == ingested
    assert leaf.edges[0].reference_time == source
    assert leaf.temporal_basis == "SOURCE_PUBLISHED"
    assert leaf.edges[0].attributes["temporal_policy"] == TEMPORAL_POLICY_VERSION


def test_episode_identity_binds_source_digests_and_source_timestamps() -> None:
    leaf, case = _extract("pair-current")
    assert leaf.ingest_id == case.revision.ingest_id
    assert leaf.edges[0].episodes == [case.revision.ingest_id]
    assert leaf.configuration_digest == configuration_digest()
    shifted = replace(case.revision, published_at="2026-01-01T00:00:00Z")
    other = extract_combined_temporal(
        shifted, transport=_FakeTransport(case.gold)
    )
    assert other.ingest_id != leaf.ingest_id
    assert {node.uuid for node in other.nodes} != {node.uuid for node in leaf.nodes}
    assert {edge.uuid for edge in other.edges} != {edge.uuid for edge in leaf.edges}
    later = extract_combined_temporal(
        replace(case.revision, ingested_at="2026-08-23T00:00:00Z"),
        transport=_FakeTransport(case.gold),
    )
    assert later.ingest_id == leaf.ingest_id
    assert {node.uuid for node in later.nodes} == {node.uuid for node in leaf.nodes}
    assert later.nodes[0].created_at != leaf.nodes[0].created_at
    assert leaf.prompt_digest is not None
    assert case.revision.ingest_id == leaf.ingest_id


def test_leaf_receipt_retains_raw_digest_usage_and_versions() -> None:
    leaf, _case = _extract("pair-current")
    call = leaf.transport_calls[0]
    assert leaf.raw_output_digest is not None
    assert leaf.raw_output_digest.startswith("sha256:")
    assert call["raw_output_digest"] == leaf.raw_output_digest
    assert leaf.framework_version == GRAPHITI_CORE_RELEASE
    assert leaf.model_version is None
    assert leaf.prompt_digest is not None
    assert leaf.prompt_digest.startswith("sha256:")
    assert leaf.invocation_count == 1
    assert leaf.token_usage["basis"] == UNMEASURED
    assert leaf.provider_cost is None
    wrapped = extract_combined_temporal(
        fixture("pair-current").revision,
        transport=_FakeTransport("Here is the JSON:\n{}"),
    )
    assert wrapped.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert wrapped.raw_output_digest is not None
    assert wrapped.transport_calls[0]["raw_output_digest"] == wrapped.raw_output_digest


def test_live_packet_is_owner_gated_and_redacted() -> None:
    payload = json.loads(LIVE_PACKET_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == (
        "newsroom.graphiti-combined-temporal-live-packet.v1"
    )
    assert payload["issue"] == 747
    assert payload["parent_issue"] == 739
    assert payload["live_authority"]["authorised"] is False
    assert payload["live_authority"]["requires_explicit_owner_instruction"] is True
    assert payload["live_authority"]["maximum_cursor_sdk_model_leaves"] == 8
    assert payload["live_authority"]["neo4j_mutation_permitted"] is False
    raw = LIVE_PACKET_PATH.read_text(encoding="utf-8")
    for forbidden in ("CURSOR_API_KEY", "/Users/", '"prompt":', '"result":'):
        assert forbidden not in raw


def test_measurements_record_one_leaf_and_beat_the_separate_pair_baseline() -> None:
    committed = json.loads(MEASUREMENTS_PATH.read_text(encoding="utf-8"))
    assert committed["hermetic_separate_pair_chat_tokens"] == 46_105
    assert committed["do_not_compare_against_zero_edge_combined_as_complete"] is True
    assert committed["token_usage_basis"] == "UNMEASURED"
    assert committed["provider_free_proxy"] == "prompt_and_schema_bytes"
    assert committed["schema_digest"] == SCHEMA_DIGEST
    assert committed["graphiti_core_version"] == "0.29.3"
    for case in FIXTURES:
        prompt = build_compact_prompt(case.revision)
        recorded = committed["fixtures"][case.name]
        assert recorded["compact_chat_leaves"] == 1
        assert recorded["compact_prompt_bytes"] == len(prompt.text.encode("utf-8"))
        assert recorded["compact_schema_bytes"] == len(canonical_json_bytes(SCHEMA))
    pair = committed["fixtures"]["pair-current"]
    assert pair["upstream_nonzero_chat_leaves"] == 2
    assert pair["leaf_count_reduction"] == 1
    assert pair["compact_prompt_bytes"] < pair["upstream_combined_prompt_bytes"]
    assert pair["compact_schema_bytes"] < (
        pair["upstream_combined_schema_bytes"]
        + pair["upstream_batch_timestamp_schema_bytes"]
    )
    assert pair["entity_name_bytes_avoided"] > 0
    assert pair["evidence_bytes_avoided"] > 0


def test_research_note_recommends_without_amending_ging_010() -> None:
    note = (
        _RESEARCH / "2026-08-22-graphiti-combined-temporal-extraction.md"
    ).read_text(encoding="utf-8")
    assert "GING-010" in note
    assert "does not amend `GING-010`" in note
    assert "#731" in note
    assert "QUALIFIED_PROVIDER_FREE" in note
    assert "owner-gated" in note
    assert "LOCAL_NEW" in note
    assert "RESOLUTION_DEFERRED" not in note


def test_upstream_zero_and_nonzero_call_shapes_are_pinned() -> None:
    committed = json.loads(CALL_SHAPES_PATH.read_text(encoding="utf-8"))
    assert committed["schema_version"] == (
        "newsroom.graphiti-combined-temporal-call-shapes.v1"
    )
    assert committed["graphiti_core_version"] == "0.29.3"
    assert tuple(committed["zero_edge"]) == ("CombinedExtraction",)
    assert tuple(committed["nonzero_edge"]) == (
        "CombinedExtraction",
        "BatchEdgeTimestamps",
    )


def test_segment_source_rejects_non_positive_max_bytes() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        segment_source("hello", max_bytes=0)
    with pytest.raises(ValueError, match="positive integer"):
        segment_source("hello", max_bytes=-1)
    with pytest.raises(ValueError, match="positive integer"):
        segment_source("hello", max_bytes=True)
    parts = segment_source("ab", max_bytes=1)
    assert [item.text for item in parts] == ["a", "b"]
    with pytest.raises(ValueError, match="valid UTF-8"):
        segment_source("漢", max_bytes=1)
    han = segment_source("漢", max_bytes=3)
    assert [item.text for item in han] == ["漢"]


def test_raw_receipt_is_exact_and_survives_malformed_mapping() -> None:
    revision = fixture("pair-current").revision
    empty = extract_combined_temporal(revision, transport=_FakeTransport([]))
    one = extract_combined_temporal(revision, transport=_FakeTransport([1]))
    two = extract_combined_temporal(revision, transport=_FakeTransport([2]))
    assert empty.raw_output_digest != one.raw_output_digest
    assert one.raw_output_digest != two.raw_output_digest
    assert empty.failure_code is CombinedTemporalFailureCode.MALFORMED_OBJECT
    floated = extract_combined_temporal(
        revision,
        transport=_FakeTransport({"entities": [], "facts": [], "x": 1.5}),
    )
    assert floated.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert floated.failure_code is CombinedTemporalFailureCode.MALFORMED_OBJECT
    assert floated.raw_output_digest is not None
    assert floated.raw_output_digest.startswith("sha256:")


def test_content_digest_follows_the_existing_chunk_pattern() -> None:
    revision = fixture("pair-current").revision
    assert revision.content_digest == content_digest(
        headline="", body=revision.body, canonical_url=""
    )


def test_prompt_or_schema_binding_mints_a_new_ingest_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaf, case = _extract("pair-current")
    shifted = extract_combined_temporal(
        replace(case.revision, predecessor_revision_id="other-rev"),
        transport=_FakeTransport(case.gold),
    )
    assert shifted.ingest_id != leaf.ingest_id
    assert {node.uuid for node in shifted.nodes} != {node.uuid for node in leaf.nodes}
    assert {edge.uuid for edge in shifted.edges} != {edge.uuid for edge in leaf.edges}
    monkeypatch.setattr(
        "newsroom.graphiti_adapter.combined_temporal_extraction.SCHEMA_DIGEST",
        "sha256:" + "ab" * 32,
    )
    schema_shifted = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.gold),
    )
    assert schema_shifted.ingest_id != leaf.ingest_id
    assert {node.uuid for node in schema_shifted.nodes} != {
        node.uuid for node in leaf.nodes
    }
    assert configuration_digest() == leaf.configuration_digest


def test_failing_embedder_rolls_back_without_graph_effect() -> None:
    async def _boom(_embedder: Any, _edges: list[Any]) -> None:
        raise RuntimeError("embed failed")

    case = fixture("pair-current")
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.gold),
        embed_edges=_boom,
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.PIPELINE_FAILED
    assert leaf.embedding_skipped is False
    assert leaf.journal_skipped is False
    assert leaf.rollback_skipped is False
    assert leaf.graph_effect_attempted is False
    assert leaf.nodes == ()
    assert leaf.edges == ()


@pytest.mark.parametrize(
    "name",
    ("explicit-valid-at", "explicit-invalid-at", "relative-date"),
)
def test_omitted_temporal_bounds_fail_when_evidence_has_a_cue(name: str) -> None:
    case = fixture(name)
    payload = json.loads(json.dumps(case.gold))
    payload["facts"][0]["valid_at"] = None
    payload["facts"][0]["invalid_at"] = None
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(payload),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert leaf.graph_effect_attempted is False


def test_duplicate_json_facts_key_is_a_typed_failure() -> None:
    leaf = extract_combined_temporal(
        fixture("pair-current").revision,
        transport=_FakeTransport(
            '{"entities":[],"facts":[{"bad":true}],"facts":[]}'
        ),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.MALFORMED_OBJECT
    assert leaf.payload is None
