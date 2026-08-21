"""Provider-free Cursor SDK no-tool calibration harness for #746.

These tests never call Cursor, Grok or OpenRouter. Live dispatch remains
owner-gated and is injected only through an explicit dispatcher seam.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("graphiti_core")

from newsroom.graphiti_adapter.identity import MAX_EPISODE_BYTES
from newsroom.graphiti_adapter.sdk_no_tool_calibration import (
    CLI_TINY_INPUT_TOKENS,
    LEAF_LABELS,
    MINIMUM_EFFECT_CEILING,
    PINNED_MODEL,
    PINNED_SDK_VERSION,
    TINY_PROMPT,
    CalibrationClosed,
    IsolationViolation,
    LeafBudget,
    compare_to_cli_baseline,
    inspect_isolation,
    long_retained_chunk,
    main,
    normalise_usage,
    prepare_isolated_leaf,
    recommend,
    reconstruct_packet_prompts,
    route_options,
    run_packet,
    source_safe_body,
)

pytestmark = pytest.mark.skipif(
    importlib.metadata.version("graphiti-core") != "0.29.3",
    reason="SDK calibration fixtures are pinned to graphiti-core 0.29.3",
)

_CALIBRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json"
)
_PACKET_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "2026-08-21-graphiti-sdk-no-tool-calibration-packet.json"
)
_COMBINED_ZERO_SHA256 = (
    "aac0a07a75af3290409f79fd50e5b6f8838a9bd2fcb899e90d33961b30ac7b2d"
)
_TINY_SHA256 = "32e612e97c74afda5f116d596361e1a174eabaa758d8966b146c7ba98df92ca7"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _finished(
    *,
    text: str,
    input_tokens: int,
    messages: tuple[object, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        status="finished",
        result=text,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=8,
            cache_read_tokens=0,
            cache_write_tokens=0,
            total_tokens=input_tokens + 8,
            reasoning_tokens=None,
        ),
        duration_ms=15,
        agent_id="agent-fixture-1",
        messages=messages,
        model=SimpleNamespace(id=PINNED_MODEL),
    )


def test_packet_defaults_to_dry_run_and_does_not_dispatch(tmp_path: Path) -> None:
    calls: list[object] = []

    def dispatcher(request: object) -> object:
        calls.append(request)
        raise AssertionError("provider dispatch is forbidden in dry-run")

    result = run_packet(output_dir=tmp_path, dispatcher=dispatcher)

    assert calls == []
    assert result["mode"] == "DRY_RUN"
    assert result["authorised"] is False
    assert result["provider_calls"] == 0
    assert len(result["leaves"]) == 8
    for leaf in result["leaves"]:
        assert leaf["usage"]["usage_basis"] == "UNREPORTED"
        assert leaf["usage"]["input_tokens"] is None
        assert "api_key" not in json.dumps(leaf)
        assert leaf["prompt_bytes"] > 0
        digest = str(leaf["prompt_sha256"])
        assert digest.startswith("sha256:")
        assert len(digest.removeprefix("sha256:")) == 64
        receipt = tmp_path / f"{leaf['label']}.json"
        assert receipt.is_file()
        raw = receipt.read_text(encoding="utf-8")
        for forbidden in (
            "/Users/",
            '"prompt":',
            '"result":',
            '"api_key"',
            '"email"',
        ):
            assert forbidden not in raw
    aggregate = json.loads((tmp_path / "aggregate.json").read_text(encoding="utf-8"))
    assert aggregate["recommendation"] == "UNMEASURED"
    assert aggregate["cli_path_comparison"][0]["cli_label"] == "hermetic-tiny"
    assert aggregate["cli_path_comparison"][0]["cli_input_tokens"] == CLI_TINY_INPUT_TOKENS
    assert aggregate["cli_path_comparison"][0]["sdk_input_tokens"] is None
    assert aggregate["cli_path_comparison"][1]["cli_chat_total"] == 25_000


def test_live_execute_fails_closed_without_owner_flag_and_call_cap(
    tmp_path: Path,
) -> None:
    with pytest.raises(CalibrationClosed, match="owner-gated"):
        run_packet(output_dir=tmp_path, execute=True, call_cap=8, api_key="secret")
    with pytest.raises(CalibrationClosed, match="call cap"):
        run_packet(
            output_dir=tmp_path,
            execute=True,
            authorised=True,
            api_key="secret",
        )
    assert main(["--output", str(tmp_path / "cli-dry")]) == 0
    assert main(["--output", str(tmp_path / "cli-live"), "--execute"]) == 2


def test_reconstructed_prompts_match_739_source_safe_fixtures() -> None:
    prompts = {item.label: item for item in reconstruct_packet_prompts()}
    assert _sha256(TINY_PROMPT) == _TINY_SHA256
    assert len(TINY_PROMPT) == 49
    assert len(source_safe_body().encode("utf-8")) == 368
    assert len(long_retained_chunk().encode("utf-8")) == MAX_EPISODE_BYTES
    assert _sha256(prompts["sdk-no-tool-tiny"].prompt) == _TINY_SHA256
    assert _sha256(prompts["sdk-upstream-combined-zero"].prompt) == _COMBINED_ZERO_SHA256
    assert (
        prompts["sdk-predeclared-repeat"].prompt
        == prompts["sdk-compact-temporal-relations"].prompt
    )
    assert (
        _sha256(prompts["sdk-predeclared-repeat"].prompt)
        == _sha256(prompts["sdk-compact-temporal-relations"].prompt)
    )
    calibration = json.loads(_CALIBRATION_PATH.read_text(encoding="utf-8"))
    hermetic = next(
        call for call in calibration["calls"] if call["label"] == "hermetic-combined"
    )
    assert hermetic["prompt_sha256"] == _COMBINED_ZERO_SHA256
    tiny = next(call for call in calibration["calls"] if call["label"] == "hermetic-tiny")
    assert tiny["prompt_sha256"] == _TINY_SHA256
    assert tiny["usage"]["inputTokens"] == CLI_TINY_INPUT_TOKENS


def test_route_options_are_no_tool_and_omit_setting_sources() -> None:
    options = route_options()
    rendered = json.dumps(options)
    assert options["model"] == PINNED_MODEL
    assert options["tools"] == []
    assert options["mcp_servers"] == {}
    assert options["agents"] == {}
    assert options["local"]["custom_tools"] == {}
    assert "setting_sources" not in options
    assert "setting_sources" not in options["local"]
    for name in ("project", "user", "team", "mdm", "plugins", "all"):
        assert name not in rendered


def test_isolated_leaf_rejects_hooks_and_ambient_cursor_files(
    tmp_path: Path,
) -> None:
    isolated = prepare_isolated_leaf()
    try:
        manifest = inspect_isolation(
            home=isolated.home, cwd=isolated.cwd, store=isolated.store
        )
        assert manifest["hook_count"] == 0
        assert manifest["tool_count"] == 0
        assert manifest["mcp_count"] == 0
        assert manifest["subagent_count"] == 0
        assert manifest["custom_tool_count"] == 0
        assert manifest["prior_message_count"] == 0
        assert manifest["prior_store_entry_count"] == 0
        assert manifest["cwd_empty"] is True
        assert manifest["cwd_has_git"] is False
    finally:
        isolated.cleanup()

    dirty = tmp_path / "dirty"
    home = dirty / "home"
    cwd = dirty / "cwd"
    store = dirty / "store"
    for path in (home / ".cursor", cwd, store):
        path.mkdir(parents=True)
    (home / ".cursor" / "hooks.json").write_text("{}", encoding="utf-8")
    with pytest.raises(IsolationViolation):
        inspect_isolation(home=home, cwd=cwd, store=store)


def test_leaf_budget_is_monotonic_and_closed_at_capacity() -> None:
    budget = LeafBudget(2)
    assert budget.consume() == 1
    assert budget.consume() == 2
    with pytest.raises(CalibrationClosed, match="exhausted"):
        budget.consume()
    with pytest.raises(CalibrationClosed, match="between 1 and 8"):
        LeafBudget(9)


def test_missing_usage_is_unreported_never_zero() -> None:
    usage = normalise_usage(None)
    assert usage["usage_basis"] == "UNREPORTED"
    assert usage["input_tokens"] is None
    assert usage["total_tokens"] is None
    zero = normalise_usage(
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
        }
    )
    assert zero["usage_basis"] == "PROVIDER_REPORTED"
    assert zero["input_tokens"] == 0


def test_tool_call_stream_event_is_rejected_without_retry(tmp_path: Path) -> None:
    def dispatcher(request: object) -> object:
        del request
        return _finished(
            text='{"ok":true}',
            input_tokens=100,
            messages=(SimpleNamespace(type="tool_call"),),
        )

    result = run_packet(
        output_dir=tmp_path,
        execute=True,
        authorised=True,
        call_cap=1,
        api_key="purpose-created",
        dispatcher=dispatcher,
    )
    assert result["leaves"][0]["tool_call_count"] == 1
    assert result["leaves"][0]["status"] == "TOOL_CALL_REJECTED"
    assert result["recommendation"] == "REJECT"


def test_injected_execute_compares_tiny_floor_to_cli_baseline(
    tmp_path: Path,
) -> None:
    def dispatcher(request: object) -> object:
        options = request.options  # type: ignore[attr-defined]
        assert options["tools"] == []
        assert "setting_sources" not in options["local"]
        assert request.environ["CURSOR_API_KEY"] == "purpose-created"
        return _finished(text='{"ok":true}', input_tokens=4_000)

    result = run_packet(
        output_dir=tmp_path,
        execute=True,
        authorised=True,
        call_cap=1,
        api_key="purpose-created",
        dispatcher=dispatcher,
    )
    comparison = result["cli_baseline"]
    assert comparison["cli_tiny_input_tokens"] == CLI_TINY_INPUT_TOKENS
    assert comparison["sdk_tiny_input_tokens"] == 4_000
    assert comparison["meets_minimum_effect"] is True
    assert comparison["meets_preferred_effect"] is True
    assert comparison["fails_minimum_useful_reduction"] is False
    assert result["recommendation"] == "RESEARCH_ONLY"
    assert result["provider_calls"] == 1
    assert result["cli_path_comparison"][0]["cli_label"] == "hermetic-tiny"
    assert result["cli_path_comparison"][0]["sdk_input_tokens"] == 4_000
    assert result["cli_path_comparison"][1]["cli_chat_total"] == 25_000


def test_tiny_input_above_minimum_effect_ceiling_is_rejected() -> None:
    usage = {
        "usage_basis": "PROVIDER_REPORTED",
        "input_tokens": MINIMUM_EFFECT_CEILING + 1,
        "output_tokens": 1,
        "cached_read_tokens": 0,
        "cached_write_tokens": 0,
        "total_tokens": MINIMUM_EFFECT_CEILING + 2,
        "reasoning_tokens": None,
    }
    comparison = compare_to_cli_baseline(usage)
    assert comparison["fails_minimum_useful_reduction"] is True
    leaf = {
        "label": LEAF_LABELS[0],
        "usage": usage,
        "tool_call_count": 0,
        "json_valid": True,
        "semantic_fixture_result": "PASS",
        "isolation": {
            "hook_count": 0,
            "mcp_count": 0,
            "subagent_count": 0,
            "custom_tool_count": 0,
            "prior_message_count": 0,
            "prior_store_entry_count": 0,
        },
    }
    assert recommend([leaf]) == "REJECT"


def test_adopt_requires_relations_quality_not_tiny_floor_alone() -> None:
    isolation = {
        "hook_count": 0,
        "mcp_count": 0,
        "subagent_count": 0,
        "custom_tool_count": 0,
        "prior_message_count": 0,
        "prior_store_entry_count": 0,
    }
    usage = {
        "usage_basis": "PROVIDER_REPORTED",
        "input_tokens": 4_000,
        "output_tokens": 8,
        "cached_read_tokens": 0,
        "cached_write_tokens": 0,
        "total_tokens": 4_008,
        "reasoning_tokens": None,
    }
    tiny = {
        "label": LEAF_LABELS[0],
        "fixture_id": "tiny-49",
        "usage": usage,
        "tool_call_count": 0,
        "json_valid": True,
        "semantic_fixture_result": "PASS",
        "isolation": isolation,
    }
    relations = {
        **tiny,
        "label": "sdk-compact-temporal-relations",
        "fixture_id": "relations",
    }
    assert recommend([tiny]) == "RESEARCH_ONLY"
    assert recommend([tiny, relations]) == "ADOPT_FOR_QUALIFICATION"


def test_owner_gated_packet_remains_unauthorised_in_git() -> None:
    payload = json.loads(_PACKET_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == (
        "newsroom.graphiti-sdk-no-tool-calibration-packet.v1"
    )
    assert payload["issue"] == 746
    assert payload["sdk_version"] == PINNED_SDK_VERSION
    assert payload["model"] == PINNED_MODEL
    assert payload["live_authority"]["authorised"] is False
    assert payload["live_authority"]["maximum_cursor_sdk_model_leaves"] == 8
    assert payload["live_authority"]["maximum_grok_model_leaves"] == 0
    assert payload["live_authority"]["maximum_openrouter_calls"] == 0
    assert [item["label"] for item in payload["experiments"]] == list(LEAF_LABELS)
