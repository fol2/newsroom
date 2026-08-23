"""Provider-free measurements and owner-gated packet for #747."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from typing import Any, Mapping

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CALL_SHAPES_PATH,
    CONTRACT_NAME,
    LIVE_PACKET_PATH,
    MEASUREMENTS_PATH,
    SCHEMA,
    SCHEMA_DIGEST,
    EvidenceSegment,
    build_compact_prompt,
)
from newsroom.graphiti_adapter.combined_temporal_fixtures import FIXTURES
from scripts.graphiti_combined_temporal_upstream import (
    PINNED_NONZERO_EDGE_CALLS,
    PINNED_ZERO_EDGE_CALLS,
    pinned_upstream_call_shapes,
    record_upstream_extraction,
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


def _require_graphiti_core() -> None:
    if importlib.metadata.version("graphiti-core") != "0.29.3":
        raise RuntimeError("measurements require graphiti-core 0.29.3")


def _upstream_shapes(body: str, *, nonempty: bool) -> dict[str, int]:
    from graphiti_core.prompts.extract_edges import BatchEdgeTimestamps
    from graphiti_core.prompts.extract_nodes_and_edges import CombinedExtraction

    _require_graphiti_core()
    recorder = record_upstream_extraction(body, nonempty=nonempty)
    combined_schema = json.dumps(CombinedExtraction.model_json_schema())
    timestamp_schema = json.dumps(BatchEdgeTimestamps.model_json_schema())
    timestamp_prompt = recorder.prompts.get("BatchEdgeTimestamps", "")
    return {
        "combined_prompt_bytes": len(
            recorder.prompts["CombinedExtraction"].encode("utf-8")
        ),
        "combined_schema_bytes": len(combined_schema.encode("utf-8")),
        "timestamp_prompt_bytes": len(timestamp_prompt.encode("utf-8")),
        "timestamp_schema_bytes": 0
        if not timestamp_prompt
        else len(timestamp_schema.encode("utf-8")),
    }


def committed_call_shapes() -> dict[str, Any]:
    return json.loads(CALL_SHAPES_PATH.read_text(encoding="utf-8"))


def live_call_shapes_match_pin() -> dict[str, tuple[str, ...]]:
    _require_graphiti_core()
    live = pinned_upstream_call_shapes()
    committed = committed_call_shapes()
    if (
        tuple(committed["zero_edge"]) != PINNED_ZERO_EDGE_CALLS
        or tuple(committed["nonzero_edge"]) != PINNED_NONZERO_EDGE_CALLS
        or live["zero_edge"] != PINNED_ZERO_EDGE_CALLS
        or live["nonzero_edge"] != PINNED_NONZERO_EDGE_CALLS
    ):
        raise RuntimeError("upstream call shapes drifted from the committed pin")
    return live


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
        CALL_SHAPES_PATH.write_text(
            canonical_json_bytes(
                {
                    "graphiti_core_version": "0.29.3",
                    "nonzero_edge": list(PINNED_NONZERO_EDGE_CALLS),
                    "schema_version": (
                        "newsroom.graphiti-combined-temporal-call-shapes.v1"
                    ),
                    "zero_edge": list(PINNED_ZERO_EDGE_CALLS),
                }
            ).decode("utf-8")
            + "\n",
            encoding="utf-8",
        )
    sys.stdout.write(encoded)
    committed = json.loads(MEASUREMENTS_PATH.read_text(encoding="utf-8"))
    if measurements != committed:
        raise SystemExit("live measurements drifted from the committed pin")
    live_call_shapes_match_pin()
    packet = json.loads(LIVE_PACKET_PATH.read_text(encoding="utf-8"))
    if packet["live_authority"]["authorised"] is not False:
        raise SystemExit("committed live packet must remain unauthorised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
