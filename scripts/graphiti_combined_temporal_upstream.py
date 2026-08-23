"""Shared graphiti-core 0.29.3 upstream recorder for #747 measurements."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.cli_client import messages_to_prompt
from newsroom.graphiti_adapter.combined_temporal_extraction import GROUP_ID
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_EXTRACTION_INSTRUCTIONS,
)


ZERO_EDGE_BODY = "A routine administrative reminder with no named entities."
NONZERO_EDGE_BODY = (
    "The Legislative Council asked about the Technology and Living curriculum."
)
PINNED_ZERO_EDGE_CALLS = ("CombinedExtraction",)
PINNED_NONZERO_EDGE_CALLS = ("CombinedExtraction", "BatchEdgeTimestamps")


def upstream_response_payload(
    response_model: type[Any] | None, *, nonempty: bool
) -> dict[str, Any]:
    from graphiti_core.prompts.extract_edges import BatchEdgeTimestamps
    from graphiti_core.prompts.extract_nodes_and_edges import CombinedExtraction

    if response_model is CombinedExtraction and not nonempty:
        return {"extracted_entities": [], "edges": []}
    if response_model is CombinedExtraction:
        return {
            "extracted_entities": [
                {"name": "Legislative Council", "entity_type_id": 0},
                {"name": "Technology and Living curriculum", "entity_type_id": 0},
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
    raise AssertionError(
        None if response_model is None else response_model.__name__
    )


def record_upstream_extraction(body: str, *, nonempty: bool) -> Any:
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.nodes import EpisodeType, EpisodicNode
    from graphiti_core.utils.maintenance.combined_extraction import (
        extract_nodes_and_edges,
    )

    class Recorder(LLMClient):
        def __init__(self) -> None:
            super().__init__(
                LLMConfig(model="composer-2.5", small_model="composer-2.5"),
                cache=False,
            )
            self.calls: list[str] = []
            self.prompts: dict[str, str] = {}

        async def _generate_response(
            self,
            messages: list[Any],
            response_model: type[Any] | None = None,
            max_tokens: int = 0,
            model_size: object = None,
        ) -> dict[str, Any]:
            del max_tokens, model_size
            name = None if response_model is None else response_model.__name__
            self.calls.append(str(name))
            self.prompts[str(name)] = messages_to_prompt(messages)
            return upstream_response_payload(
                response_model, nonempty=nonempty
            )

    recorder = Recorder()
    episode = EpisodicNode(
        name="measure",
        group_id=GROUP_ID,
        labels=[],
        source=EpisodeType.text,
        source_description="newsroom-eval-proposal",
        content=body,
        created_at=UtcTimestamp.parse("2026-08-21T00:00:00Z").value,
        valid_at=UtcTimestamp.parse("2026-08-20T00:00:00Z").value,
    )

    async def _run() -> None:
        await extract_nodes_and_edges(
            SimpleNamespace(llm_client=recorder),
            episode,
            [],
            custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
    return recorder


def pinned_upstream_call_shapes() -> dict[str, tuple[str, ...]]:
    zero = record_upstream_extraction(ZERO_EDGE_BODY, nonempty=False)
    nonzero = record_upstream_extraction(NONZERO_EDGE_BODY, nonempty=True)
    return {
        "zero_edge": tuple(zero.calls),
        "nonzero_edge": tuple(nonzero.calls),
    }
