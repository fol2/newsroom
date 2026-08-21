"""Provider-free proof of graphiti-core 0.29.3's non-zero combined call shape.

The first #739 calibration returned no edges, so upstream combined extraction
made only one LLM request. A relation-bearing result makes a second
BatchEdgeTimestamps request. This fixture pins that conditional behavior and
validates the owner-gated second-stage experiment manifest.
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

pytestmark = pytest.mark.skipif(
    importlib.metadata.version("graphiti-core") != "0.29.3",
    reason="call-shape fixtures are pinned to graphiti-core 0.29.3",
)

_PLAN_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "2026-08-21-graphiti-token-effectiveness-experiment-plan.json"
)


class _NonZeroCombinedRecordingLlm(LLMClient):
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
            }
        )

        if response_model is CombinedExtraction:
            return {
                "extracted_entities": [
                    {
                        "name": "Legislative Council",
                        "entity_type_id": 0,
                    },
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
                            "The Legislative Council asked about the Technology "
                            "and Living curriculum."
                        ),
                        "episode_indices": [0],
                    }
                ],
            }

        if response_model is BatchEdgeTimestamps:
            return {
                "timestamps": [
                    {
                        "valid_at": "2026-08-20T00:00:00Z",
                        "invalid_at": None,
                    }
                ]
            }

        raise AssertionError(f"unexpected response model: {response_model!r}")


def _episode() -> EpisodicNode:
    return EpisodicNode(
        name="nonzero-combined-fixture",
        group_id="newsroom-call-shape",
        labels=[],
        source=EpisodeType.text,
        source_description="newsroom-eval-proposal",
        content=(
            "The Legislative Council asked about the Technology and Living "
            "curriculum."
        ),
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        valid_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def test_upstream_nonzero_combined_path_dispatches_timestamp_request() -> None:
    llm = _NonZeroCombinedRecordingLlm()
    clients = SimpleNamespace(llm_client=llm)

    async def run() -> tuple[list[Any], list[Any], dict[str, list[int]]]:
        return await extract_nodes_and_edges(
            clients,
            _episode(),
            [],
            custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )

    nodes, edges, node_episode_index_map = asyncio.run(run())

    assert [call["response_model"] for call in llm.calls] == [
        "CombinedExtraction",
        "BatchEdgeTimestamps",
    ]
    assert len(nodes) == 2
    assert len(edges) == 1
    assert edges[0].name == "ASKED_ABOUT"
    assert edges[0].valid_at == datetime(2026, 8, 20, tzinfo=UTC)
    assert edges[0].invalid_at is None
    assert sorted(node_episode_index_map.values()) == [[0], [0]]


def test_second_stage_experiment_plan_is_serial_bounded_and_owner_gated() -> None:
    payload = json.loads(_PLAN_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == (
        "newsroom.graphiti-token-effectiveness-experiment-plan.v1"
    )
    assert payload["parent_issue"] == 739
    assert payload["pull_request"] == 745
    assert payload["serial_issues"] == [746, 747, 748]

    authority = payload["live_authority"]
    assert authority["authorised"] is False
    assert authority["requires_explicit_owner_instruction"] is True
    assert authority["maximum_cursor_sdk_model_leaves"] == 8
    assert authority["maximum_grok_model_leaves"] == 0
    assert authority["maximum_openrouter_calls"] == 0
    assert authority["adaptive_extra_calls_permitted"] is False
    assert authority["unchanged_request_retry_permitted"] is False
    assert authority["neo4j_mutation_permitted"] is False
    assert authority["publication_permitted"] is False

    sdk = payload["sdk_candidate"]
    assert sdk["model"] == "composer-2.5"
    assert sdk["runtime"] == "local"
    assert sdk["lifecycle"] == "Agent.prompt"
    assert sdk["tools"] == []
    assert sdk["mcp_servers"] == {}
    assert sdk["agents"] == {}
    assert sdk["custom_tools"] == {}
    assert sdk["setting_sources"] == "OMITTED"
    assert sdk["prior_messages"] == 0
    assert sdk["required_stream_tool_call_count"] == 0

    shape = payload["call_shape"]
    assert shape["graphiti_core_version"] == "0.29.3"
    assert shape["upstream_combined_zero_edge_chat_leaves"] == 1
    assert shape["upstream_combined_nonzero_edge_chat_leaves"] == 2
    assert shape["upstream_nonzero_second_class"] == "BatchEdgeTimestamps"
    assert shape["candidate_compact_combined_temporal_zero_edge_chat_leaves"] == 1
    assert shape["candidate_compact_combined_temporal_nonzero_edge_chat_leaves"] == 1

    experiments = payload["experiments"]
    assert [item["ordinal"] for item in experiments] == list(range(1, 9))
    assert len({item["label"] for item in experiments}) == 8

    decision = payload["decision_rule"]
    assert decision["minimum_tiny_input_reduction_fraction"] == 0.5
    assert decision["preferred_tiny_input_reduction_fraction"] == 0.75
    assert decision["maximum_tiny_input_tokens_for_minimum_effect"] == 10_051
    assert decision["quality_must_not_regress"] is True
    assert decision["source_content_must_not_be_truncated"] is True
    assert decision["tool_call_count_must_equal"] == 0
    assert decision["missing_usage_is_zero"] is False
