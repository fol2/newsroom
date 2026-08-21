from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path


def test_cursor_json_output_retains_provider_reported_tokens() -> None:
    from newsroom.graphiti_adapter.cli_client import parse_cursor_output

    execution = parse_cursor_output(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": '{"value":"primary"}',
                "usage": {
                    "inputTokens": 20_685,
                    "outputTokens": 140,
                    "cacheReadTokens": 576,
                    "cacheWriteTokens": 0,
                },
            }
        )
    )

    assert execution.text == '{"value":"primary"}'
    assert execution.usage == {
        "usage_basis": "PROVIDER_REPORTED",
        "input_tokens": 20_685,
        "output_tokens": 140,
        "cached_read_tokens": 576,
        "cached_write_tokens": 0,
        "reasoning_tokens": None,
        "total_tokens": 21_401,
    }


def test_grok_stream_output_retains_provider_reported_tokens() -> None:
    from newsroom.graphiti_adapter.cli_client import parse_grok_stream_output

    output = "\n".join(
        (
            json.dumps(
                {
                    "method": "_x.ai/session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": '{"value":'},
                        }
                    },
                }
            ),
            json.dumps(
                {
                    "method": "_x.ai/session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": '"fallback"}'},
                        }
                    },
                }
            ),
            json.dumps(
                {
                    "method": "_x.ai/session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "turn_completed",
                            "usage": {
                                "inputTokens": 51_884,
                                "outputTokens": 535,
                                "totalTokens": 52_419,
                                "cachedReadTokens": 128,
                                "cacheCreationTokens": 0,
                                "reasoningTokens": 97,
                            },
                        }
                    },
                }
            ),
        )
    )

    execution = parse_grok_stream_output(output)

    assert execution.text == '{"value":"fallback"}'
    assert execution.usage == {
        "usage_basis": "PROVIDER_REPORTED",
        "input_tokens": 51_884,
        "output_tokens": 535,
        "cached_read_tokens": 128,
        "cached_write_tokens": 0,
        "reasoning_tokens": 97,
        "total_tokens": 52_419,
    }


def test_graphiti_usage_summary_combines_chat_and_embeddings() -> None:
    from newsroom.graphiti_adapter.usage_meter import summarise_graphiti_usage

    summary = summarise_graphiti_usage(
        chat_invocations=(
            {
                "provider": "cursor-agent-cli",
                "usage": {
                    "usage_basis": "PROVIDER_REPORTED",
                    "input_tokens": 20_685,
                    "output_tokens": 140,
                    "cached_read_tokens": 576,
                    "cached_write_tokens": 0,
                    "reasoning_tokens": None,
                    "total_tokens": 21_401,
                },
            },
            {
                "provider": "grok-build-cli",
                "usage": {
                    "usage_basis": "PROVIDER_REPORTED",
                    "input_tokens": 51_884,
                    "output_tokens": 535,
                    "cached_read_tokens": 128,
                    "cached_write_tokens": 0,
                    "reasoning_tokens": 97,
                    "total_tokens": 52_419,
                },
            },
        ),
        embedding_usage={
            "usage_basis": "PROVIDER_REPORTED",
            "request_count": 2,
            "embedding_tokens": 19,
            "cost_usd_microunits": 3,
            "requests": [{}, {}],
        },
    )

    assert summary["usage_basis"] == "PROVIDER_REPORTED"
    assert summary["chat_request_count"] == 2
    assert summary["cursor_request_count"] == 1
    assert summary["grok_request_count"] == 1
    assert summary["chat_input_tokens"] == 72_569
    assert summary["chat_output_tokens"] == 675
    assert summary["chat_cached_read_tokens"] == 704
    assert summary["chat_reasoning_tokens"] == 97
    assert summary["chat_total_tokens"] == 73_820
    assert summary["embedding_request_count"] == 2
    assert summary["embedding_tokens"] == 19
    assert summary["observed_total_tokens"] == 73_839
    assert summary["unreported_chat_requests"] == 0


def test_cli_chain_retains_cursor_usage_on_the_invocation() -> None:
    from newsroom.graphiti_adapter.cli_client import CliExecution, run_cli_chain

    usage = {
        "usage_basis": "PROVIDER_REPORTED",
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_read_tokens": 5,
        "cached_write_tokens": 0,
        "reasoning_tokens": None,
        "total_tokens": 125,
    }
    invocations: list[dict[str, object]] = []
    result = asyncio.run(
        run_cli_chain(
            prompt="prompt",
            schema=None,
            cursor_runner=lambda _prompt: CliExecution(
                text='{"value":"primary"}', usage=usage
            ),
            grok_runner=lambda _prompt, _schema: "not called",
            invocations=invocations,
        )
    )

    assert result == {"value": "primary"}
    assert invocations == [
        {
            "provider": "cursor-agent-cli",
            "model": "composer-2.5",
            "outcome": "COMPLETE",
            "usage": usage,
        }
    ]


def test_usage_report_groups_attempt_receipts_into_300_second_windows(
    tmp_path: Path,
) -> None:
    from newsroom.control_plane.usage import graphiti_usage_report

    path = tmp_path / "unpublished.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE unpublished_graphiti_attempt_receipts(
            ingest_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            outcome TEXT NOT NULL,
            receipt_digest TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            at TEXT NOT NULL,
            PRIMARY KEY(ingest_id, attempt_number)
        )
        """
    )
    usage = {
        "usage_basis": "PROVIDER_REPORTED",
        "chat_request_count": 1,
        "cursor_request_count": 1,
        "grok_request_count": 0,
        "chat_input_tokens": 100,
        "chat_output_tokens": 20,
        "chat_cached_read_tokens": 5,
        "chat_cached_write_tokens": 0,
        "chat_reasoning_tokens": 0,
        "chat_total_tokens": 125,
        "embedding_request_count": 1,
        "embedding_tokens": 10,
        "embedding_cost_usd_microunits": 2,
        "observed_total_tokens": 135,
        "unreported_chat_requests": 0,
    }
    rows = (
        ("one", "2026-08-21T12:00:01.000000Z"),
        ("two", "2026-08-21T12:04:59.000000Z"),
        ("three", "2026-08-21T12:05:00.000000Z"),
    )
    for ingest_id, at in rows:
        connection.execute(
            "INSERT INTO unpublished_graphiti_attempt_receipts VALUES(?,?,?,?,?,?)",
            (
                ingest_id,
                1,
                "COMPLETE",
                "sha256:test",
                json.dumps({"token_usage": usage}),
                at,
            ),
        )
    connection.commit()
    connection.close()

    report = graphiti_usage_report(str(path), window_seconds=300)

    assert report["attempt_count"] == 3
    assert report["observed_total_tokens"] == 405
    assert len(report["windows"]) == 2
    assert report["windows"][0]["window_start"] == "2026-08-21T12:00:00Z"
    assert report["windows"][0]["attempt_count"] == 2
    assert report["windows"][0]["observed_total_tokens"] == 270
    assert report["windows"][1]["window_start"] == "2026-08-21T12:05:00Z"
    assert report["windows"][1]["observed_total_tokens"] == 135
