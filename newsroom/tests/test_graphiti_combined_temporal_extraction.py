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

import asyncio
import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CONTRACT_NAME,
    LIVE_PACKET_PATH,
    MEASUREMENTS_PATH,
    SCHEMA,
    SCHEMA_DIGEST,
    CombinedTemporalFailureCode,
    CombinedTemporalOutcome,
    build_compact_prompt,
    extract_combined_temporal,
    measure_token_effectiveness,
    segment_source,
)
from newsroom.graphiti_adapter.combined_temporal_fixtures import (
    FIXTURES,
    MALFORMED_CASES,
    fixture,
)

_REPO = Path(__file__).resolve().parents[2]
_RESEARCH = _REPO / "docs" / "research"
GRAPHITI_MEMORY_PHRASE = "AI agent memory system"


def _graphiti_version() -> str | None:
    try:
        return importlib.metadata.version("graphiti-core")
    except importlib.metadata.PackageNotFoundError:
        return None


class _FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def generate_response(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        response_model: str,
    ) -> object:
        del prompt, schema, response_model
        return self.payload


def _extract(name: str, payload: object | None = None):
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
    assert leaf.embedding_skipped is True
    assert leaf.journal_skipped is True
    assert leaf.node_resolutions == ("DETERMINISTIC_NEW_NODE", "DETERMINISTIC_NEW_NODE")
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


@pytest.mark.skipif(
    _graphiti_version() != "0.29.3",
    reason="upstream prompt bytes are pinned to graphiti-core 0.29.3",
)
def test_measurements_record_one_leaf_and_beat_the_separate_pair_baseline() -> None:
    measurements = measure_token_effectiveness()
    committed = json.loads(MEASUREMENTS_PATH.read_text(encoding="utf-8"))
    assert measurements == committed
    assert committed["hermetic_separate_pair_chat_tokens"] == 46_105
    assert committed["do_not_compare_against_zero_edge_combined_as_complete"] is True
    assert committed["token_usage_basis"] == "UNMEASURED"
    assert committed["provider_free_proxy"] == "prompt_and_schema_bytes"
    pair = committed["fixtures"]["pair-current"]
    assert pair["compact_chat_leaves"] == 1
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
    assert "does not amend `GING-010`" in note
    assert "owner-gated" in note


@pytest.mark.skipif(
    _graphiti_version() != "0.29.3",
    reason="call-shape fixtures are pinned to graphiti-core 0.29.3",
)
def test_upstream_zero_and_nonzero_call_shapes_are_pinned() -> None:
    pytest.importorskip("graphiti_core")
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.nodes import EpisodeType, EpisodicNode
    from graphiti_core.prompts.extract_edges import BatchEdgeTimestamps
    from graphiti_core.prompts.extract_nodes_and_edges import CombinedExtraction
    from graphiti_core.utils.maintenance.combined_extraction import (
        extract_nodes_and_edges,
    )

    from newsroom.graphiti_adapter.cli_client import messages_to_prompt
    from newsroom.graphiti_adapter.evaluation_packet import (
        GRAPHITI_EXTRACTION_INSTRUCTIONS,
    )

    class _Recorder(LLMClient):
        def __init__(self, nonempty: bool) -> None:
            super().__init__(
                LLMConfig(model="composer-2.5", small_model="composer-2.5"),
                cache=False,
            )
            self.nonempty = nonempty
            self.calls: list[str] = []

        async def _generate_response(
            self,
            messages: list[Any],
            response_model: type[Any] | None = None,
            max_tokens: int = 0,
            model_size: object = None,
        ) -> dict[str, Any]:
            del messages, max_tokens, model_size
            name = None if response_model is None else response_model.__name__
            self.calls.append(str(name))
            if response_model is CombinedExtraction and not self.nonempty:
                return {"extracted_entities": [], "edges": []}
            if response_model is CombinedExtraction:
                return {
                    "extracted_entities": [
                        {"name": "Legislative Council", "entity_type_id": 0},
                        {
                            "name": "Technology and Living curriculum",
                            "entity_type_id": 0,
                        },
                    ],
                    "edges": [
                        {
                            "source_entity_name": "Legislative Council",
                            "target_entity_name": "Technology and Living curriculum",
                            "relation_type": "ASKED_ABOUT",
                            "fact": (
                                "The Legislative Council asked about the "
                                "Technology and Living curriculum."
                            ),
                            "episode_indices": [0],
                        }
                    ],
                }
            if response_model is BatchEdgeTimestamps:
                return {
                    "timestamps": [
                        {"valid_at": "2026-08-20T00:00:00Z", "invalid_at": None}
                    ]
                }
            raise AssertionError(name)

    def _episode(body: str) -> EpisodicNode:
        return EpisodicNode(
            name="call-shape",
            group_id="newsroom-call-shape",
            labels=[],
            source=EpisodeType.text,
            source_description="newsroom-eval-proposal",
            content=body,
            created_at=datetime(2026, 8, 21, tzinfo=UTC),
            valid_at=datetime(2026, 8, 20, tzinfo=UTC),
        )

    async def _run(nonempty: bool, body: str) -> list[str]:
        llm = _Recorder(nonempty)
        await extract_nodes_and_edges(
            SimpleNamespace(llm_client=llm),
            _episode(body),
            [],
            custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )
        return llm.calls

    zero = asyncio.run(
        _run(False, "A routine administrative reminder with no named entities.")
    )
    nonzero = asyncio.run(
        _run(
            True,
            "The Legislative Council asked about the Technology and Living curriculum.",
        )
    )
    assert zero == ["CombinedExtraction"]
    assert nonzero == ["CombinedExtraction", "BatchEdgeTimestamps"]
    del messages_to_prompt
