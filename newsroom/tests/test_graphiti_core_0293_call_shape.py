"""Provider-free graphiti-core 0.29.3 internal call-shape fixtures.

These tests inject a recording LLMClient. They never call Cursor, Grok or
OpenRouter. They pin the extract-call sequence that #739 / #731 must qualify.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("graphiti_core")

from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig
from graphiti_core.nodes import EpisodeType, EpisodicNode
from graphiti_core.prompts.extract_edges import ExtractedEdges
from graphiti_core.prompts.extract_nodes import ExtractedEntities
from graphiti_core.prompts.extract_nodes_and_edges import CombinedExtraction
from graphiti_core.utils.maintenance.combined_extraction import (
    extract_nodes_and_edges,
)
from graphiti_core.utils.maintenance.edge_operations import extract_edges
from graphiti_core.utils.maintenance.node_operations import extract_nodes

from newsroom.graphiti_adapter.cli_client import (
    CliExecution,
    build_cli_llm_client,
    messages_to_prompt,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_EXTRACTION_INSTRUCTIONS,
)
from newsroom.graphiti_adapter.usage_meter import unreported_cli_usage

pytestmark = pytest.mark.skipif(
    importlib.metadata.version("graphiti-core") != "0.29.3",
    reason="call-shape fixtures are pinned to graphiti-core 0.29.3",
)


_CALIBRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json"
)
_USAGE_KEYS = (
    "inputTokens",
    "outputTokens",
    "cacheReadTokens",
    "cacheWriteTokens",
)


def _calibration() -> dict[str, Any]:
    return json.loads(_CALIBRATION_PATH.read_text(encoding="utf-8"))


def _chat_total(call: dict[str, Any]) -> int:
    usage = call["usage"]
    return sum(usage[key] for key in _USAGE_KEYS)


def test_calibration_receipt_is_bounded_and_redacted() -> None:
    payload = _calibration()
    calls = payload["calls"]

    assert payload["issue"] == 739
    assert payload["approved_by"] == "owner"
    assert payload["cursor_agent"] == "2026.08.11-e8db854"
    assert payload["model"] == "composer-2.5"
    assert payload["print_mode_calls_used"] == len(calls) == 6
    assert len(calls) <= payload["print_mode_call_cap"] == 8
    assert payload["no_grok"] is True
    assert payload["no_openrouter"] is True

    raw = _CALIBRATION_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "/Users/",
        '"prompt":',
        '"result":',
        '"session_id":',
        '"request_id":',
        '"email":',
    ):
        assert forbidden not in raw

    assert [call["n"] for call in calls] == list(range(1, len(calls) + 1))
    assert len({call["label"] for call in calls}) == len(calls)
    for call in calls:
        assert call["returncode"] == 0
        assert call["extract_json_ok"] is True
        assert re.fullmatch(r"[0-9a-f]{64}", call["prompt_sha256"])
        assert call["prompt_bytes"] >= call["prompt_chars"] > 0
        assert call["elapsed_ms"] > 0
        usage = call["usage"]
        assert set(usage) == set(_USAGE_KEYS)
        assert all(
            isinstance(usage[key], int) and usage[key] >= 0 for key in _USAGE_KEYS
        )


def test_calibration_arithmetic_matches_research_table() -> None:
    calls = {call["label"]: call for call in _calibration()["calls"]}

    ambient_pair = _chat_total(calls["ambient-nodes"]) + _chat_total(
        calls["ambient-edges"]
    )
    hermetic_pair = _chat_total(calls["hermetic-nodes"]) + _chat_total(
        calls["hermetic-edges"]
    )

    assert ambient_pair == 51_058
    assert hermetic_pair == 46_105
    assert ambient_pair - hermetic_pair == 4_953
    combined_total = _chat_total(calls["hermetic-combined"])
    assert combined_total == 25_000
    assert hermetic_pair - combined_total == 21_105

    ambient_nodes_input = calls["ambient-nodes"]["usage"]["inputTokens"]
    hermetic_nodes_input = calls["hermetic-nodes"]["usage"]["inputTokens"]
    ambient_edges_input = calls["ambient-edges"]["usage"]["inputTokens"]
    hermetic_edges_input = calls["hermetic-edges"]["usage"]["inputTokens"]

    assert ambient_nodes_input - hermetic_nodes_input == 2_284
    assert ambient_edges_input - hermetic_edges_input == 2_281
    assert calls["hermetic-tiny"]["usage"]["inputTokens"] == 20_103


class _RecordingLlm(LLMClient):
    def __init__(self) -> None:
        super().__init__(
            LLMConfig(model="composer-2.5", small_model="composer-2.5"),
            cache=False,
        )
        self.calls: list[dict[str, object]] = []

    async def _generate_response(
        self,
        messages: list[Any],
        response_model: type[Any] | None = None,
        max_tokens: int = 0,
        model_size: object = None,
    ) -> dict[str, Any]:
        prompt = messages_to_prompt(messages)
        self.calls.append(
            {
                "response_model": (
                    None if response_model is None else response_model.__name__
                ),
                "max_tokens": max_tokens,
                "model_size": getattr(model_size, "value", model_size),
                "prompt_chars": len(prompt),
                "schema_in_prompt": (
                    "Respond with a JSON object in the following format:" in prompt
                ),
            }
        )
        if response_model is ExtractedEntities:
            return {"extracted_entities": []}
        if response_model is ExtractedEdges:
            return {"edges": []}
        if response_model is CombinedExtraction:
            return {"extracted_entities": [], "edges": []}
        return {}


def _episode(*, body: str) -> EpisodicNode:
    return EpisodicNode(
        name="fixture-revision",
        group_id="newsroom-call-shape",
        labels=[],
        source=EpisodeType.text,
        source_description="newsroom-eval-proposal",
        content=body,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        valid_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def _body(size: int = 368) -> str:
    seed = (
        "The Legislative Council asked about the Technology and Living curriculum. " * 8
    )
    encoded = seed.encode("utf-8")[:size]
    return encoded.decode("utf-8", errors="ignore")


def test_separate_extract_path_is_two_generate_response_calls() -> None:
    llm = _RecordingLlm()
    clients = SimpleNamespace(llm_client=llm)
    episode = _episode(body=_body())

    async def run() -> None:
        nodes, _map = await extract_nodes(
            clients,
            episode,
            [],
            None,
            None,
            GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )
        await extract_edges(
            clients,
            episode,
            nodes,
            [],
            {("Entity", "Entity"): []},
            "newsroom-call-shape",
            None,
            GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )

    asyncio.run(run())

    assert [call["response_model"] for call in llm.calls] == [
        "ExtractedEntities",
        "ExtractedEdges",
    ]
    assert all(call["max_tokens"] == DEFAULT_MAX_TOKENS for call in llm.calls)
    assert all(call["schema_in_prompt"] is True for call in llm.calls)
    assert llm.calls[0]["prompt_chars"] > 4_000
    assert llm.calls[1]["prompt_chars"] > 6_000


def test_zero_proposal_text_episode_still_makes_both_extract_calls() -> None:
    llm = _RecordingLlm()
    clients = SimpleNamespace(llm_client=llm)
    episode = _episode(body="Weather note with no named entities.")

    async def run() -> tuple[int, int]:
        nodes, _map = await extract_nodes(
            clients,
            episode,
            [],
            None,
            None,
            GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )
        edges = await extract_edges(
            clients,
            episode,
            nodes,
            [],
            {("Entity", "Entity"): []},
            "newsroom-call-shape",
            None,
            GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )
        return len(nodes), len(edges)

    node_count, edge_count = asyncio.run(run())
    assert node_count == 0
    assert edge_count == 0
    assert len(llm.calls) == 2


def test_combined_extraction_is_one_generate_response_call() -> None:
    llm = _RecordingLlm()
    clients = SimpleNamespace(llm_client=llm)
    episode = _episode(body=_body())

    async def run() -> None:
        nodes, edges, _map = await extract_nodes_and_edges(
            clients,
            episode,
            [],
            custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )
        assert nodes == []
        assert edges == []

    asyncio.run(run())
    assert [call["response_model"] for call in llm.calls] == ["CombinedExtraction"]
    assert llm.calls[0]["max_tokens"] == DEFAULT_MAX_TOKENS
    assert llm.calls[0]["schema_in_prompt"] is True


def test_graphiti_core_response_schemas_are_stable() -> None:
    assert len(json.dumps(ExtractedEntities.model_json_schema())) == 896
    assert len(json.dumps(ExtractedEdges.model_json_schema())) == 1_747
    assert len(json.dumps(CombinedExtraction.model_json_schema())) == 2_144


def test_newsroom_cli_client_receipts_requested_max_tokens() -> None:
    captured: dict[str, object] = {}

    async def cursor_runner(prompt: str) -> CliExecution:
        captured["prompt"] = prompt
        return CliExecution(
            text='{"extracted_entities":[]}',
            usage=unreported_cli_usage(),
        )

    async def grok_runner(prompt: str, schema: str | None) -> CliExecution:
        captured["grok_schema"] = schema
        raise AssertionError("Grok fallback must not run on well-formed Cursor JSON")

    client = build_cli_llm_client(
        cursor_runner=cursor_runner,
        grok_runner=grok_runner,
    )
    from graphiti_core.prompts.models import Message

    payload = asyncio.run(
        client._generate_response(
            [
                Message(role="system", content="system"),
                Message(role="user", content="user"),
            ],
            response_model=ExtractedEntities,
            max_tokens=99,
        )
    )
    assert payload == {"extracted_entities": []}
    assert captured["prompt"] == (
        "system:\nsystem\n\nuser:\nuser\n\n"
        "<newsroom_controller_output_contract>\n"
        "maximum_output_tokens=99\n"
        "</newsroom_controller_output_contract>"
    )
    assert client.invocations[0]["outcome"] == "COMPLETE"
    assert client.invocations[0]["requested_max_tokens"] == 99
