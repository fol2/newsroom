"""Provider-free measurements and owner-gated packet for #747."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import sys
from types import SimpleNamespace
from typing import Any, Mapping

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.cli_client import messages_to_prompt
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CONTRACT_NAME,
    GROUP_ID,
    LIVE_PACKET_PATH,
    MEASUREMENTS_PATH,
    SCHEMA,
    SCHEMA_DIGEST,
    EvidenceSegment,
    build_compact_prompt,
)
from newsroom.graphiti_adapter.combined_temporal_fixtures import FIXTURES
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_EXTRACTION_INSTRUCTIONS,
)


def measure_token_effectiveness() -> dict[str, Any]:
    fixtures: dict[str, Any] = {}
    for case in FIXTURES:
        prompt = build_compact_prompt(case.revision)
        compact_prompt_bytes = len(prompt.text.encode("utf-8"))
        compact_schema_bytes = len(canonical_json_bytes(SCHEMA))
        name_avoided, evidence_avoided = _avoided_bytes(case.gold, prompt.segments)
        nonempty = bool(case.gold["facts"])
        upstream = _upstream_shapes(case.revision.body, nonempty=nonempty)
        upstream_leaves = 1 + int(nonempty)
        fixtures[case.name] = {
            "compact_chat_leaves": 1,
            "upstream_nonzero_chat_leaves": 2,
            "upstream_zero_chat_leaves": 1,
            "leaf_count_reduction": upstream_leaves - 1,
            "compact_prompt_bytes": compact_prompt_bytes,
            "compact_schema_bytes": compact_schema_bytes,
            "upstream_combined_prompt_bytes": upstream["combined_prompt_bytes"],
            "upstream_combined_schema_bytes": upstream["combined_schema_bytes"],
            "upstream_batch_timestamp_prompt_bytes": upstream[
                "timestamp_prompt_bytes"
            ],
            "upstream_batch_timestamp_schema_bytes": upstream[
                "timestamp_schema_bytes"
            ],
            "entity_name_bytes_avoided": name_avoided,
            "evidence_bytes_avoided": evidence_avoided,
        }
    return {
        "schema_version": "newsroom.graphiti-combined-temporal-measurements.v1",
        "issue": 747,
        "contract": CONTRACT_NAME,
        "schema_digest": SCHEMA_DIGEST,
        "hermetic_separate_pair_chat_tokens": 46_105,
        "hermetic_combined_zero_edge_chat_tokens": 25_000,
        "do_not_compare_against_zero_edge_combined_as_complete": True,
        "token_usage_basis": "UNMEASURED",
        "provider_free_proxy": "prompt_and_schema_bytes",
        "graphiti_core_version": "0.29.3",
        "fixtures": fixtures,
    }


def _avoided_bytes(
    gold: Mapping[str, Any],
    segments: tuple[EvidenceSegment, ...],
) -> tuple[int, int]:
    name_by_id = {item["local_id"]: item["name"] for item in gold["entities"]}
    name_avoided = 0
    evidence_avoided = 0
    by_id = {item.segment_id: item for item in segments}
    for fact in gold["facts"]:
        source = name_by_id[fact["source_local_id"]]
        target = name_by_id[fact["target_local_id"]]
        name_avoided += max(
            0,
            len(source)
            + len(target)
            - len(str(fact["source_local_id"]))
            - len(str(fact["target_local_id"])),
        )
        for segment_id in fact["evidence_segment_ids"]:
            text = by_id[segment_id].text
            evidence_avoided += max(0, len(text.encode("utf-8")) - len(str(segment_id)))
    return name_avoided, evidence_avoided


def _upstream_shapes(body: str, *, nonempty: bool) -> dict[str, int]:
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.nodes import EpisodeType, EpisodicNode
    from graphiti_core.prompts.extract_edges import BatchEdgeTimestamps
    from graphiti_core.prompts.extract_nodes_and_edges import CombinedExtraction
    from graphiti_core.utils.maintenance.combined_extraction import (
        extract_nodes_and_edges,
    )

    if importlib.metadata.version("graphiti-core") != "0.29.3":
        raise RuntimeError("measurements require graphiti-core 0.29.3")

    class _Recorder(LLMClient):
        def __init__(self) -> None:
            super().__init__(
                LLMConfig(model="composer-2.5", small_model="composer-2.5"),
                cache=False,
            )
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
            self.prompts[str(name)] = messages_to_prompt(messages)
            if response_model is CombinedExtraction and not nonempty:
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
            return {}

    llm = _Recorder()
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
            SimpleNamespace(llm_client=llm),
            episode,
            [],
            custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
    combined_schema = json.dumps(CombinedExtraction.model_json_schema())
    timestamp_schema = json.dumps(BatchEdgeTimestamps.model_json_schema())
    timestamp_prompt = llm.prompts.get("BatchEdgeTimestamps", "")
    return {
        "combined_prompt_bytes": len(llm.prompts["CombinedExtraction"].encode("utf-8")),
        "combined_schema_bytes": len(combined_schema.encode("utf-8")),
        "timestamp_prompt_bytes": len(timestamp_prompt.encode("utf-8")),
        "timestamp_schema_bytes": 0
        if not timestamp_prompt
        else len(timestamp_schema.encode("utf-8")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record provider-free #747 combined-temporal measurements."
    )
    parser.add_argument(
        "--write-measurements",
        action="store_true",
        help="overwrite the committed measurements JSON",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="refused: live dispatch is owner-gated and not implemented here",
    )
    parser.add_argument("--authorised-by-owner", action="store_true")
    args = parser.parse_args(argv)
    if args.execute or args.authorised_by_owner:
        raise SystemExit(
            "live calibration is owner-gated; this runner is provider-free only"
        )
    measurements = measure_token_effectiveness()
    encoded = canonical_json_bytes(measurements).decode("utf-8") + "\n"
    if args.write_measurements:
        MEASUREMENTS_PATH.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    packet = json.loads(LIVE_PACKET_PATH.read_text(encoding="utf-8"))
    if packet["live_authority"]["authorised"] is not False:
        raise SystemExit("committed live packet must remain unauthorised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
