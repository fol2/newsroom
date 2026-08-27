"""Provider-free Cursor SDK no-tool calibration harness for #746.

These tests never call Cursor, Grok or OpenRouter. Live dispatch remains
owner-gated and is injected only through an explicit dispatcher seam.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import sys
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Self

import pytest
from jsonschema import Draft202012Validator

pytest.importorskip("graphiti_core")

from newsroom.control_plane.corpus import chunk_text
from newsroom.graphiti_adapter.identity import MAX_EPISODE_BYTES
from newsroom.research.graphiti_sdk_no_tool_calibration import (
    CLI_TINY_INPUT_TOKENS,
    LEAF_LABELS,
    MINIMUM_EFFECT_CEILING,
    PINNED_MODEL,
    PINNED_SDK_VERSION,
    TINY_PROMPT,
    VALIDATOR_VERSION,
    CalibrationClosed,
    DispatchRequest,
    IsolatedLeaf,
    IsolationViolation,
    LeafBudget,
    assess_result,
    compare_to_cli_baseline,
    inspect_isolation,
    live_dispatcher,
    long_retained_chunk,
    main,
    normalise_usage,
    over_limit_revision,
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
_RECEIPT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "2026-08-21-graphiti-sdk-no-tool-calibration.schema.json"
)
_RECEIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "2026-08-21-graphiti-sdk-no-tool-calibration-receipts"
)
_COMBINED_ZERO_SHA256 = (
    "aac0a07a75af3290409f79fd50e5b6f8838a9bd2fcb899e90d33961b30ac7b2d"
)
_TINY_SHA256 = "32e612e97c74afda5f116d596361e1a174eabaa758d8966b146c7ba98df92ca7"


def test_cursor_sdk_is_locked_in_graphiti_and_research_extras() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    extras = project["project"]["optional-dependencies"]
    pin = f"cursor-sdk=={PINNED_SDK_VERSION}"
    assert extras["cursor-research"] == [pin]
    assert pin in extras["graphiti"]
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "cursor-sdk"' in lock
    assert f'version = "{PINNED_SDK_VERSION}"' in lock


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
    validator = Draft202012Validator(
        json.loads(_RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    )

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
        validator.validate(json.loads(receipt.read_text(encoding="utf-8")))
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
    assert (
        aggregate["cli_path_comparison"][0]["cli_input_tokens"] == CLI_TINY_INPUT_TOKENS
    )
    assert aggregate["cli_path_comparison"][0]["sdk_input_tokens"] is None
    assert aggregate["cli_path_comparison"][1]["cli_chat_total"] == 25_000


def test_packet_refuses_to_mix_with_prior_output(tmp_path: Path) -> None:
    run_packet(output_dir=tmp_path)

    with pytest.raises(CalibrationClosed, match="must be empty"):
        run_packet(output_dir=tmp_path)


def test_retained_receipts_validate_with_content_free_diagnostics() -> None:
    schema = json.loads(_RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    receipts = sorted(_RECEIPT_DIR.glob("sdk-*.json"))
    retained_by_label: dict[str, object] = {}

    assert len(receipts) == 8
    for path in receipts:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validator.validate(payload)
        retained_by_label[payload["label"]] = payload
        assert "prompt" not in payload
        assert "result" not in payload
        assert "response" not in payload
        assert payload["tool_call_observation_basis"] == "ROUTE_CONFIGURATION_ONLY"
        assert payload["observed_model"] is None
        assert payload["model_identity_basis"] == "REQUEST_AND_CATALOGUE"
        expected_validity = (
            "INVALID_ZERO_EXPECTATION"
            if payload["label"]
            in {"sdk-upstream-combined-zero", "sdk-compact-temporal-zero"}
            else "VALID"
        )
        assert payload["fixture_validity"] == expected_validity

    aggregate = json.loads((_RECEIPT_DIR / "aggregate.json").read_text())
    assert {leaf["label"]: leaf for leaf in aggregate["leaves"]} == retained_by_label
    assert aggregate["recommendation"] == "REJECT"
    assert aggregate["semantic_summary"]["pass_count"] == 4
    assert aggregate["semantic_summary"]["fail_count"] == 4
    assert aggregate["semantic_summary"]["invalid_fixture_count"] == 2
    assert aggregate["semantic_summary"]["retained_label_basis"] == (
        "HISTORICAL_PRE_V3"
    )
    assert aggregate["exact_repeat"]["prompt_digest_matches"] is True
    assert aggregate["exact_repeat"]["semantic_outcome_matches"] is False
    assert aggregate["exact_repeat"]["input_token_delta"] == 6_463
    assert aggregate["evidence_limitations"] == {
        "agent_prompt_stream_events_observed": False,
        "bridge_workspace_isolation_proved": False,
        "model_catalogue_identity_verified": True,
        "run_result_model_identity_retained": False,
        "tool_call_count_basis": "ROUTE_CONFIGURATION_ONLY",
        "invalid_zero_expectation_leaf_count": 2,
    }


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
    assert (
        _sha256(prompts["sdk-upstream-combined-zero"].prompt) == _COMBINED_ZERO_SHA256
    )
    assert (
        prompts["sdk-predeclared-repeat"].prompt
        == prompts["sdk-compact-temporal-relations"].prompt
    )
    assert _sha256(prompts["sdk-predeclared-repeat"].prompt) == _sha256(
        prompts["sdk-compact-temporal-relations"].prompt
    )
    calibration = json.loads(_CALIBRATION_PATH.read_text(encoding="utf-8"))
    hermetic = next(
        call for call in calibration["calls"] if call["label"] == "hermetic-combined"
    )
    assert hermetic["prompt_sha256"] == _COMBINED_ZERO_SHA256
    tiny = next(
        call for call in calibration["calls"] if call["label"] == "hermetic-tiny"
    )
    assert tiny["prompt_sha256"] == _TINY_SHA256
    assert tiny["usage"]["inputTokens"] == CLI_TINY_INPUT_TOKENS


def test_over_limit_revision_reconstructs_every_chunk_without_truncation() -> None:
    body = over_limit_revision()
    chunks = chunk_text(body)

    assert len(body.encode("utf-8")) == MAX_EPISODE_BYTES + 50
    assert len(chunks) == 2
    assert "".join(chunks) == body
    assert all(len(chunk.encode("utf-8")) <= MAX_EPISODE_BYTES for chunk in chunks)


def test_semantic_diagnostics_are_content_free_and_actionable() -> None:
    prompts = {item.label: item for item in reconstruct_packet_prompts()}
    zero = assess_result(
        '{"entities":[{"name":"unexpected"}],"facts":[]}',
        prompt=prompts["sdk-compact-temporal-zero"],
    )
    assert zero.result == "FAIL"
    assert zero.failure_codes == (
        "SCHEMA_VALIDATION_FAILED",
        "FIXTURE_EXPECTATION_INVALID",
        "MISSING_EXPECTED_ENTITY",
        "MISSING_RELATION_TYPE",
        "MISSING_EVIDENCE_SEGMENT_IDS",
        "INVALID_LOCAL_REFERENCE",
        "EVIDENCE_CONTRACT_UNVERIFIABLE",
    )
    assert zero.entity_count == 1
    assert zero.fact_count == 0
    assert str(zero.key_set_digest).startswith("sha256:")

    relations = assess_result(
        '{"entities":[],"facts":[{"relation_type":"OTHER"}]}',
        prompt=prompts["sdk-compact-temporal-relations"],
    )
    assert relations.result == "FAIL"
    assert relations.failure_codes == (
        "SCHEMA_VALIDATION_FAILED",
        "MISSING_EXPECTED_ENTITY",
        "MISSING_RELATION_TYPE",
        "MISSING_TEMPORAL_KEYS",
        "MISSING_EVIDENCE_SEGMENT_IDS",
        "INVALID_LOCAL_REFERENCE",
        "MISSING_FACT_TEXT",
        "EVIDENCE_CONTRACT_UNVERIFIABLE",
    )

    invalid = assess_result("not-json", prompt=prompts["sdk-compact-temporal-long"])
    assert invalid.json_valid is False
    assert invalid.failure_codes == ("INVALID_JSON",)

    duplicate = assess_result(
        '{"ok":true,"ok":false}', prompt=prompts["sdk-no-tool-tiny"]
    )
    assert duplicate.json_valid is False
    assert duplicate.failure_codes == ("DUPLICATE_JSON_KEY",)


def test_strict_validator_rejects_unqualifiable_historical_contracts() -> None:
    prompts = {item.label: item for item in reconstruct_packet_prompts()}
    relation_body = (
        "The Legislative Council asked about the Technology and Living curriculum."
    )
    upstream_relations = {
        "extracted_entities": [
            {"name": "Legislative Council", "entity_type_id": 0},
            {"name": "Technology and Living curriculum", "entity_type_id": 0},
        ],
        "edges": [
            {
                "source_entity_name": "Legislative Council",
                "target_entity_name": "Technology and Living curriculum",
                "relation_type": "ASKED_ABOUT",
                "fact": relation_body,
                "episode_indices": [0],
            }
        ],
    }
    compact_relations = {
        "entities": [
            {
                "local_id": 1,
                "name": "Legislative Council",
                "entity_type_id": 0,
                "evidence_segment_ids": ["segment-1"],
            },
            {
                "local_id": 2,
                "name": "Technology and Living curriculum",
                "entity_type_id": 0,
                "evidence_segment_ids": ["segment-1"],
            },
        ],
        "facts": [
            {
                "source_local_id": 1,
                "target_local_id": 2,
                "relation_type": "ASKED_ABOUT",
                "fact": relation_body,
                "valid_at": "2026-08-20T00:00:00Z",
                "invalid_at": None,
                "evidence_segment_ids": ["segment-1"],
            }
        ],
    }
    payloads = {
        "sdk-no-tool-tiny": {"ok": True},
        "sdk-upstream-combined-zero": {"extracted_entities": [], "edges": []},
        "sdk-upstream-combined-relations": upstream_relations,
        "sdk-upstream-batch-timestamps": {
            "timestamps": [{"valid_at": "2026-08-20T00:00:00Z", "invalid_at": None}]
        },
        "sdk-compact-temporal-zero": {"entities": [], "facts": []},
        "sdk-compact-temporal-relations": compact_relations,
        "sdk-compact-temporal-long": compact_relations,
        "sdk-predeclared-repeat": compact_relations,
    }

    qualified = {
        "sdk-no-tool-tiny",
        "sdk-upstream-combined-relations",
        "sdk-upstream-batch-timestamps",
    }
    invalid_zero = {"sdk-upstream-combined-zero", "sdk-compact-temporal-zero"}
    for label, payload in payloads.items():
        assessment = assess_result(json.dumps(payload), prompt=prompts[label])
        if label in qualified:
            assert assessment.result == "PASS", (label, assessment.failure_codes)
        elif label in invalid_zero:
            assert "FIXTURE_EXPECTATION_INVALID" in assessment.failure_codes
        else:
            assert assessment.failure_codes == ("EVIDENCE_CONTRACT_UNVERIFIABLE",)


def test_compact_validator_checks_temporal_evidence_and_local_references() -> None:
    prompt = next(
        item
        for item in reconstruct_packet_prompts()
        if item.label == "sdk-compact-temporal-relations"
    )
    payload = {
        "entities": [
            {
                "local_id": 1,
                "name": "Legislative Council",
                "entity_type_id": 0,
                "evidence_segment_ids": [],
            },
            {
                "local_id": 2,
                "name": "Technology and Living curriculum",
                "entity_type_id": 0,
                "evidence_segment_ids": ["segment-1"],
            },
        ],
        "facts": [
            {
                "source_local_id": 1,
                "target_local_id": 99,
                "relation_type": "ASKED_ABOUT",
                "fact": "relation",
                "valid_at": "not-a-timestamp",
                "invalid_at": None,
                "evidence_segment_ids": [],
            }
        ],
    }

    assessment = assess_result(json.dumps(payload), prompt=prompt)
    assert assessment.failure_codes == (
        "INVALID_TEMPORAL_VALUE",
        "MISSING_EVIDENCE_SEGMENT_IDS",
        "INVALID_LOCAL_REFERENCE",
        "EVIDENCE_CONTRACT_UNVERIFIABLE",
    )

    timestamp_prompt = next(
        item
        for item in reconstruct_packet_prompts()
        if item.label == "sdk-upstream-batch-timestamps"
    )
    invalid_timestamp = assess_result(
        '{"timestamps":[{"valid_at":"not-a-timestamp","invalid_at":null}]}',
        prompt=timestamp_prompt,
    )
    assert invalid_timestamp.failure_codes == ("INVALID_TEMPORAL_VALUE",)


def test_observed_model_mismatch_fails_the_leaf(tmp_path: Path) -> None:
    def dispatcher(request: object) -> object:
        del request
        result = _finished(text='{"ok":true}', input_tokens=4_000)
        result.model = SimpleNamespace(id="different-model")
        return result

    result = run_packet(
        output_dir=tmp_path,
        execute=True,
        authorised=True,
        call_cap=1,
        api_key="purpose-created",
        dispatcher=dispatcher,
    )

    leaf = result["leaves"][0]
    assert leaf["observed_model"] == "different-model"
    assert leaf["semantic_failure_codes"] == ["MODEL_IDENTITY_MISMATCH"]
    assert leaf["semantic_fixture_result"] == "FAIL"
    assert result["recommendation"] == "REJECT"


def test_agent_prompt_without_stream_observation_is_not_qualified(
    tmp_path: Path,
) -> None:
    def dispatcher(request: object) -> object:
        del request
        result = _finished(text='{"ok":true}', input_tokens=4_000)
        delattr(result, "messages")
        return result

    result = run_packet(
        output_dir=tmp_path,
        execute=True,
        authorised=True,
        call_cap=1,
        api_key="purpose-created",
        dispatcher=dispatcher,
    )

    leaf = result["leaves"][0]
    assert leaf["tool_call_count"] is None
    assert leaf["tool_call_observation_basis"] == "NOT_EXPOSED_BY_AGENT_PROMPT"
    assert result["recommendation"] == "REJECT"


def test_live_dispatcher_launches_a_fresh_isolated_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}

    class _Options:
        def __init__(self, **kwargs: object) -> None:
            self.values = kwargs

    class _Models:
        def list(self, *, api_key: str) -> list[object]:
            calls["catalogue_api_key"] = api_key
            return [SimpleNamespace(id=PINNED_MODEL)]

    class _Client:
        models = _Models()

        @classmethod
        def launch_bridge(cls, **kwargs: object) -> _Client:
            calls["bridge"] = kwargs
            return cls()

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> None:
            calls["closed"] = True

    class _Agent:
        @classmethod
        def prompt(cls, prompt: str, options: _Options, *, client: _Client) -> object:
            calls["prompt"] = prompt
            calls["agent_options"] = options.values
            calls["client"] = client
            return _finished(text='{"ok":true}', input_tokens=4_000)

    fake_sdk = ModuleType("cursor_sdk")
    fake_sdk.Agent = _Agent  # type: ignore[attr-defined]
    fake_sdk.AgentOptions = _Options  # type: ignore[attr-defined]
    fake_sdk.Client = _Client  # type: ignore[attr-defined]
    fake_sdk.LocalAgentOptions = _Options  # type: ignore[attr-defined]
    fake_sdk.LocalAgentStoreConfig = _Options  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cursor_sdk", fake_sdk)
    real_version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: PINNED_SDK_VERSION if name == "cursor-sdk" else real_version(name),
    )

    isolated = prepare_isolated_leaf(api_key="purpose-created")
    before = dict(os.environ)
    try:
        request = DispatchRequest(
            prompt=TINY_PROMPT,
            options={
                "local": {
                    "cwd": str(isolated.cwd),
                    "custom_tools": {},
                    "store": {"type": "jsonl", "root_dir": str(isolated.store)},
                }
            },
            environ=isolated.environ,
        )
        result = live_dispatcher(request)
    finally:
        isolated.cleanup()

    bridge = calls["bridge"]
    assert bridge["workspace"] == str(isolated.cwd)
    assert Path(bridge["state_root"]).name == "bridge-state"
    assert bridge["allow_api_key_env_fallback"] is False
    assert calls["closed"] is True
    assert calls["prompt"] == TINY_PROMPT
    assert calls["agent_options"]["tools"] == []
    assert calls["catalogue_api_key"] == "purpose-created"
    assert result.model.id == PINNED_MODEL
    assert dict(os.environ) == before


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


@pytest.mark.parametrize("interruption", [KeyboardInterrupt(), asyncio.CancelledError()])
def test_cancellation_writes_unreported_receipts_before_cleanup_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    dispatches = 0
    original_cleanup = IsolatedLeaf.cleanup

    def dispatcher(request: object) -> object:
        nonlocal dispatches
        del request
        dispatches += 1
        raise interruption

    def cleanup(isolated: IsolatedLeaf) -> None:
        assert (tmp_path / f"{LEAF_LABELS[0]}.json").is_file()
        assert (tmp_path / "aggregate.json").is_file()
        original_cleanup(isolated)

    monkeypatch.setattr(IsolatedLeaf, "cleanup", cleanup)

    with pytest.raises(type(interruption)):
        run_packet(
            output_dir=tmp_path,
            execute=True,
            authorised=True,
            call_cap=2,
            api_key="purpose-created",
            dispatcher=dispatcher,
        )

    assert dispatches == 1
    leaf = json.loads(
        (tmp_path / f"{LEAF_LABELS[0]}.json").read_text(encoding="utf-8")
    )
    aggregate = json.loads(
        (tmp_path / "aggregate.json").read_text(encoding="utf-8")
    )
    assert leaf["status"] == "CANCELLED"
    assert leaf["failure"] == type(interruption).__name__
    assert leaf["usage_status"] == "UNREPORTED"
    assert leaf["usage"]["total_tokens"] is None
    assert aggregate["provider_calls"] == 1
    assert aggregate["leaves"] == [leaf]
    assert aggregate["recommendation"] == "REJECT"


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
    assert result["semantic_summary"] == {
        "pass_count": 1,
        "fail_count": 0,
        "pending_count": 0,
        "unresolved_count": 0,
        "invalid_json_count": 0,
    }
    assert result["exact_repeat"]["available"] is False
    assert result["leaves"][0]["validator_version"] == VALIDATOR_VERSION
    assert result["leaves"][0]["semantic_failure_codes"] == []
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

    pending = {**relations, "semantic_fixture_result": "PENDING", "json_valid": None}
    assert recommend([tiny, pending]) == "REJECT"
    assert recommend([relations]) == "REJECT"


def test_owner_gated_packet_remains_unauthorised_in_git() -> None:
    payload = json.loads(_PACKET_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == (
        "newsroom.graphiti-sdk-no-tool-calibration-packet.v1"
    )
    assert payload["issue"] == 746
    assert payload["sdk_version"] == "1.0.28"
    assert payload["model"] == PINNED_MODEL
    assert payload["live_authority"]["authorised"] is False
    assert payload["live_authority"]["maximum_cursor_sdk_model_leaves"] == 8
    assert payload["live_authority"]["maximum_grok_model_leaves"] == 0
    assert payload["live_authority"]["maximum_openrouter_calls"] == 0
    assert [item["label"] for item in payload["experiments"]] == list(LEAF_LABELS)
