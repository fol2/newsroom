"""Provider-free Cursor SDK no-tool calibration harness (#746).

Default execution is a dry-run. Live ``Agent.prompt`` dispatch requires an
explicit owner flag, a call cap, and an injected or locally constructed
dispatcher. This module does not amend GING-010 or the production transport.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.graphiti_adapter.cli_client import messages_to_prompt
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_EXTRACTION_INSTRUCTIONS,
)
from newsroom.graphiti_adapter.identity import MAX_EPISODE_BYTES
from newsroom.graphiti_adapter.cursor_transport import (
    PINNED_MODEL,
    PINNED_SDK_VERSION,
    select_composer_model,
    sdk_version_meets_floor,
)
from newsroom.graphiti_adapter.usage_meter import unreported_cli_usage

PINNED_BRIDGE_PROTOCOL = "sdk.v1"
CLI_TINY_INPUT_TOKENS = 20_103
MINIMUM_EFFECT_CEILING = 10_051
PREFERRED_REDUCTION_FRACTION = 0.75
MINIMUM_REDUCTION_FRACTION = 0.5
MAXIMUM_LEAVES = 8
TINY_PROMPT = 'Reply with exactly {"ok":true} and no other text.'
RELATIONS_BODY = (
    "The Legislative Council asked about the Technology and Living curriculum."
)
REFERENCE_TIME = "2026-08-20T00:00:00Z"
SCHEMA_VERSION = "newsroom.graphiti-sdk-no-tool-calibration.v1"
VALIDATOR_VERSION = "newsroom.graphiti-sdk-no-tool-validator.v3"
FORBIDDEN_SETTING_SOURCES = frozenset(
    {"project", "user", "team", "mdm", "plugins", "all"}
)
ENVIRONMENT_ALLOW_LIST = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "CURSOR_API_KEY",
)
AMBIENT_CURSOR_NAMES = frozenset(
    {
        "hooks.json",
        "mcp.json",
        "rules",
        "skills",
        "plugins",
        "agents",
        "argv.json",
        "cli-config.json",
        "ide_state.json",
        "chats",
        "projects",
        "extensions",
        "worktrees",
        "plans",
        "skills-cursor",
        "agent-cli-state.json",
        "ai-tracking",
        "browser-logs",
        "statsig-cache.json",
    }
)
COMPACT_SCHEMA: dict[str, Any] = {
    "properties": {
        "entities": {
            "items": {
                "properties": {
                    "entity_type_id": {"type": "integer"},
                    "evidence_segment_ids": {
                        "items": {"type": "string"},
                        "type": "array",
                    },
                    "local_id": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": [
                    "local_id",
                    "name",
                    "entity_type_id",
                    "evidence_segment_ids",
                ],
                "type": "object",
            },
            "type": "array",
        },
        "facts": {
            "items": {
                "properties": {
                    "evidence_segment_ids": {
                        "items": {"type": "string"},
                        "type": "array",
                    },
                    "fact": {"type": "string"},
                    "invalid_at": {"type": ["string", "null"]},
                    "relation_type": {"type": "string"},
                    "source_local_id": {"type": "integer"},
                    "target_local_id": {"type": "integer"},
                    "valid_at": {"type": ["string", "null"]},
                },
                "required": [
                    "source_local_id",
                    "target_local_id",
                    "relation_type",
                    "fact",
                    "valid_at",
                    "invalid_at",
                    "evidence_segment_ids",
                ],
                "type": "object",
            },
            "type": "array",
        },
    },
    "required": ["entities", "facts"],
    "type": "object",
}
TINY_SCHEMA: dict[str, Any] = {
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "type": "object",
}
LEAF_LABELS = (
    "sdk-no-tool-tiny",
    "sdk-upstream-combined-zero",
    "sdk-upstream-combined-relations",
    "sdk-upstream-batch-timestamps",
    "sdk-compact-temporal-zero",
    "sdk-compact-temporal-relations",
    "sdk-compact-temporal-long",
    "sdk-predeclared-repeat",
)


class CalibrationClosed(RuntimeError):
    """Live calibration was refused before provider dispatch."""


class IsolationViolation(RuntimeError):
    """Ambient Cursor state was present before dispatch."""


class ToolCallRejected(RuntimeError):
    """A tool-call stream event occurred on a no-tool route."""


class _DuplicateJsonKey(ValueError):
    """A model result repeated a key and therefore has ambiguous semantics."""


@dataclass(frozen=True, slots=True)
class LeafPrompt:
    ordinal: int
    label: str
    prompt: str
    schema: dict[str, Any]
    prompt_class: str
    fixture_id: str


@dataclass(frozen=True, slots=True)
class SemanticAssessment:
    """Content-free semantic diagnostics retained beside one model leaf."""

    json_valid: bool
    result: str
    failure_codes: tuple[str, ...]
    entity_count: int | None
    fact_count: int | None
    key_set_digest: str | None


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    prompt: str
    options: dict[str, object]
    environ: dict[str, str]


@dataclass(frozen=True, slots=True)
class IsolatedLeaf:
    root: Path
    home: Path
    cwd: Path
    tmp: Path
    store: Path
    environ: dict[str, str]
    manifest: dict[str, object]

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)


class LeafBudget:
    """Monotonic live-leaf budget consumed before each provider dispatch."""

    __slots__ = ("cap", "consumed")

    def __init__(self, cap: int) -> None:
        if cap < 1 or cap > MAXIMUM_LEAVES:
            raise CalibrationClosed("call cap must be between 1 and 8")
        self.cap = cap
        self.consumed = 0

    def consume(self) -> int:
        if self.consumed >= self.cap:
            raise CalibrationClosed("leaf-call budget exhausted")
        self.consumed += 1
        return self.consumed


Dispatcher = Callable[[DispatchRequest], object]


def source_safe_body(*, size: int = 368) -> str:
    seed = (
        "The Legislative Council asked about the Technology and Living curriculum. " * 8
    )
    return seed.encode("utf-8")[:size].decode("utf-8")


def long_retained_chunk() -> str:
    """Return the exact historical 8,192-byte live-packet fixture."""

    seed = source_safe_body().encode("utf-8")
    return (seed * ((MAX_EPISODE_BYTES // len(seed)) + 1))[:MAX_EPISODE_BYTES].decode(
        "utf-8"
    )


def over_limit_revision() -> str:
    """Return a provider-free fixture that crosses the episode chunk boundary."""

    return long_retained_chunk() + ("x" * 50)


def compact_prompt(body: str) -> str:
    schema = json.dumps(COMPACT_SCHEMA, separators=(",", ":"), sort_keys=True)
    return (
        "Extract a NewsroomCombinedTemporalExtractionV1 JSON object from the source. "
        "Entities use local integer IDs. Facts reference those IDs and include "
        "valid_at and invalid_at. Evidence uses deterministic segment IDs. "
        "A valid zero-result is an empty entities array and empty facts array.\n"
        f"{GRAPHITI_EXTRACTION_INSTRUCTIONS}\n"
        "Respond with a JSON object in the following format:\n"
        f"{schema}\n\n"
        f"SOURCE:\n{body}\n\n"
        f"REFERENCE_TIME: {REFERENCE_TIME}"
    )


def reconstruct_packet_prompts() -> tuple[LeafPrompt, ...]:
    zero_body = source_safe_body()
    combined_zero = _combined_prompt(zero_body, nonempty=False)
    combined_rel, timestamps = _nonzero_prompts()
    compact_rel = compact_prompt(RELATIONS_BODY)
    compact_schema = COMPACT_SCHEMA
    prompts = (
        LeafPrompt(1, LEAF_LABELS[0], TINY_PROMPT, TINY_SCHEMA, "tiny", "tiny-json"),
        LeafPrompt(
            2,
            LEAF_LABELS[1],
            combined_zero,
            _combined_schema(),
            "upstream_combined",
            "zero-result-368",
        ),
        LeafPrompt(
            3,
            LEAF_LABELS[2],
            combined_rel,
            _combined_schema(),
            "upstream_combined",
            "relations",
        ),
        LeafPrompt(
            4,
            LEAF_LABELS[3],
            timestamps,
            _timestamp_schema(),
            "upstream_batch_timestamps",
            "relations-timestamps",
        ),
        LeafPrompt(
            5,
            LEAF_LABELS[4],
            compact_prompt(zero_body),
            compact_schema,
            "compact_combined_temporal",
            "zero-result-368",
        ),
        LeafPrompt(
            6,
            LEAF_LABELS[5],
            compact_rel,
            compact_schema,
            "compact_combined_temporal",
            "relations",
        ),
        LeafPrompt(
            7,
            LEAF_LABELS[6],
            compact_prompt(long_retained_chunk()),
            compact_schema,
            "compact_combined_temporal",
            "long-8192",
        ),
        LeafPrompt(
            8,
            LEAF_LABELS[7],
            compact_rel,
            compact_schema,
            "compact_combined_temporal",
            "relations-repeat",
        ),
    )
    return prompts


def route_options() -> dict[str, object]:
    return {
        **_empty_route(),
        "lifecycle": "Agent.prompt",
        "runtime": "local",
        "local": {
            "cwd": "REDACTED",
            "custom_tools": {},
            "store": {"type": "jsonl", "root_dir": "REDACTED"},
        },
    }


def inspect_isolation(*, home: Path, cwd: Path, store: Path) -> dict[str, object]:
    home_cursor = _cursor_entries(home)
    cwd_cursor = _cursor_entries(cwd)
    store_entries = _entry_names(store)
    hooks = _hook_paths(home, cwd)
    unclassified = [
        name
        for name in (*home_cursor, *cwd_cursor)
        if name not in AMBIENT_CURSOR_NAMES and name != "hooks.json"
    ]
    git = (cwd / ".git").exists()
    cwd_names = _entry_names(cwd)
    manifest = {
        "hook_count": len(hooks),
        "tool_count": 0,
        "mcp_count": 0,
        "subagent_count": 0,
        "custom_tool_count": 0,
        "prior_message_count": 0,
        "prior_store_entry_count": len(store_entries),
        "setting_sources": "OMITTED",
        "cwd_empty": cwd_names == (),
        "cwd_has_git": git,
        "home_cursor_entry_count": len(home_cursor),
        "cwd_cursor_entry_count": len(cwd_cursor),
        "unclassified_cursor_entry_count": len(unclassified),
        "environment_allow_list": list(ENVIRONMENT_ALLOW_LIST),
    }
    if (
        hooks
        or git
        or cwd_names
        or home_cursor
        or cwd_cursor
        or store_entries
        or unclassified
    ):
        raise IsolationViolation("ambient Cursor or workspace state is present")
    return manifest


def prepare_isolated_leaf(*, api_key: str | None = None) -> IsolatedLeaf:
    root = Path(tempfile.mkdtemp(prefix="newsroom-746-sdk-"))
    home = root / "home"
    cwd = root / "cwd"
    tmp = root / "tmp"
    store = root / "store"
    xdg_config = home / ".config"
    xdg_data = home / ".local" / "share"
    xdg_cache = home / ".cache"
    xdg_state = home / ".local" / "state"
    xdg_runtime = root / "runtime"
    for path in (
        home,
        cwd,
        tmp,
        store,
        xdg_config,
        xdg_data,
        xdg_cache,
        xdg_state,
        xdg_runtime,
    ):
        path.mkdir(parents=True)
    environ = isolated_environ(
        home=home,
        tmp=tmp,
        store=store,
        xdg_config=xdg_config,
        xdg_data=xdg_data,
        xdg_cache=xdg_cache,
        xdg_state=xdg_state,
        xdg_runtime=xdg_runtime,
        api_key=api_key,
    )
    manifest = inspect_isolation(home=home, cwd=cwd, store=store)
    return IsolatedLeaf(
        root=root,
        home=home,
        cwd=cwd,
        tmp=tmp,
        store=store,
        environ=environ,
        manifest=manifest,
    )


def isolated_environ(
    *,
    home: Path,
    tmp: Path,
    store: Path,
    xdg_config: Path,
    xdg_data: Path,
    xdg_cache: Path,
    xdg_state: Path,
    xdg_runtime: Path,
    api_key: str | None,
) -> dict[str, str]:
    overlay = {
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_DATA_HOME": str(xdg_data),
        "XDG_CACHE_HOME": str(xdg_cache),
        "XDG_STATE_HOME": str(xdg_state),
        "XDG_RUNTIME_DIR": str(xdg_runtime),
    }
    environ: dict[str, str] = {}
    for name in ENVIRONMENT_ALLOW_LIST:
        if name in overlay:
            environ[name] = overlay[name]
            continue
        if name == "CURSOR_API_KEY":
            if api_key:
                environ[name] = api_key
            continue
        value = os.environ.get(name)
        if value:
            environ[name] = value
    return environ


def normalise_usage(value: object) -> dict[str, object]:
    if value is None:
        return unreported_cli_usage()
    mapping: Mapping[str, object]
    if isinstance(value, Mapping):
        mapping = value
    else:
        mapping = {
            "input_tokens": getattr(value, "input_tokens", None),
            "output_tokens": getattr(value, "output_tokens", None),
            "cached_read_tokens": getattr(value, "cache_read_tokens", None),
            "cached_write_tokens": getattr(value, "cache_write_tokens", None),
            "total_tokens": getattr(value, "total_tokens", None),
            "reasoning_tokens": getattr(value, "reasoning_tokens", None),
        }
    fields = {
        "input_tokens": _token(
            _first_present(mapping.get("input_tokens"), mapping.get("inputTokens"))
        ),
        "output_tokens": _token(
            _first_present(mapping.get("output_tokens"), mapping.get("outputTokens"))
        ),
        "cached_read_tokens": _token(
            _first_present(
                mapping.get("cached_read_tokens"),
                mapping.get("cache_read_tokens"),
                mapping.get("cacheReadTokens"),
            )
        ),
        "cached_write_tokens": _token(
            _first_present(
                mapping.get("cached_write_tokens"),
                mapping.get("cache_write_tokens"),
                mapping.get("cacheWriteTokens"),
            )
        ),
        "total_tokens": _token(
            _first_present(mapping.get("total_tokens"), mapping.get("totalTokens"))
        ),
    }
    reasoning = _first_present(
        mapping.get("reasoning_tokens"), mapping.get("reasoningTokens")
    )
    if any(item is None for item in fields.values()):
        return unreported_cli_usage()
    if reasoning is not None:
        reasoning_token = _token(reasoning)
        if reasoning_token is None:
            return unreported_cli_usage()
    else:
        reasoning_token = None
    return {
        "usage_basis": "PROVIDER_REPORTED",
        **fields,
        "reasoning_tokens": reasoning_token,
    }


def compare_to_cli_baseline(usage: Mapping[str, object]) -> dict[str, object]:
    input_tokens = usage.get("input_tokens")
    if not isinstance(input_tokens, int):
        return {
            "cli_tiny_input_tokens": CLI_TINY_INPUT_TOKENS,
            "sdk_tiny_input_tokens": None,
            "input_reduction_fraction": None,
            "meets_minimum_effect": False,
            "meets_preferred_effect": False,
            "fails_minimum_useful_reduction": False,
        }
    reduction = (CLI_TINY_INPUT_TOKENS - input_tokens) / CLI_TINY_INPUT_TOKENS
    return {
        "cli_tiny_input_tokens": CLI_TINY_INPUT_TOKENS,
        "sdk_tiny_input_tokens": input_tokens,
        "input_reduction_fraction": reduction,
        "meets_minimum_effect": reduction >= MINIMUM_REDUCTION_FRACTION
        and input_tokens <= MINIMUM_EFFECT_CEILING,
        "meets_preferred_effect": reduction >= PREFERRED_REDUCTION_FRACTION,
        "fails_minimum_useful_reduction": input_tokens > MINIMUM_EFFECT_CEILING,
    }


def recommend(leaves: Sequence[Mapping[str, object]]) -> str:
    if not leaves:
        return "UNMEASURED"
    if all(
        leaf.get("tool_call_observation_basis") == "NOT_DISPATCHED" for leaf in leaves
    ):
        return "UNMEASURED"
    if any(
        leaf.get("tool_call_count") != 0
        or leaf.get("isolation", {}).get("hook_count") != 0
        or leaf.get("isolation", {}).get("mcp_count") != 0
        or leaf.get("isolation", {}).get("subagent_count") != 0
        or leaf.get("isolation", {}).get("custom_tool_count") != 0
        or leaf.get("isolation", {}).get("prior_message_count") != 0
        or leaf.get("isolation", {}).get("prior_store_entry_count") != 0
        for leaf in leaves
    ):
        return "REJECT"
    if any(
        leaf.get("usage", {}).get("usage_basis") != "PROVIDER_REPORTED"
        for leaf in leaves
    ):
        return "UNMEASURED"
    tiny = next((leaf for leaf in leaves if leaf.get("label") == LEAF_LABELS[0]), None)
    if tiny is None or not isinstance(tiny.get("usage"), Mapping):
        return "REJECT"
    comparison = compare_to_cli_baseline(tiny["usage"])  # type: ignore[arg-type]
    if comparison["fails_minimum_useful_reduction"]:
        return "REJECT"
    quality_ok = all(
        leaf.get("semantic_fixture_result") == "PASS" and leaf.get("json_valid") is True
        for leaf in leaves
    )
    if not quality_ok:
        return "REJECT"
    relations = [
        leaf
        for leaf in leaves
        if leaf.get("fixture_id") in {"relations", "relations-repeat"}
        and leaf.get("semantic_fixture_result") == "PASS"
    ]
    if comparison["meets_preferred_effect"] and relations:
        return "ADOPT_FOR_QUALIFICATION"
    if comparison["meets_minimum_effect"]:
        return "RESEARCH_ONLY"
    return "REJECT"


def _build_packet_aggregate(
    leaves: Sequence[Mapping[str, object]],
    *,
    execute: bool,
    authorised: bool,
    call_cap: int | None,
) -> dict[str, object]:
    tiny_usage = next(
        (
            leaf["usage"]
            for leaf in leaves
            if leaf.get("label") == LEAF_LABELS[0]
        ),
        unreported_cli_usage(),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "issue": 746,
        "mode": "EXECUTE" if execute else "DRY_RUN",
        "authorised": authorised,
        "provider_calls": 0 if not execute else len(leaves),
        "sdk_version": PINNED_SDK_VERSION,
        "bridge_protocol": PINNED_BRIDGE_PROTOCOL,
        "model": PINNED_MODEL,
        "maximum_leaves": MAXIMUM_LEAVES,
        "call_cap": call_cap,
        "leaves": list(leaves),
        "cli_baseline": compare_to_cli_baseline(tiny_usage),  # type: ignore[arg-type]
        "cli_path_comparison": compare_packet_to_cli(leaves),
        "semantic_summary": _semantic_summary(leaves),
        "exact_repeat": _exact_repeat_summary(leaves),
        "recommendation": recommend(leaves),
        "no_grok": True,
        "no_openrouter": True,
    }


def run_packet(
    *,
    output_dir: Path,
    dispatcher: Dispatcher | None = None,
    execute: bool = False,
    call_cap: int | None = None,
    authorised: bool = False,
    api_key: str | None = None,
) -> dict[str, object]:
    _prepare_output_dir(output_dir)
    if execute:
        if not authorised:
            raise CalibrationClosed("live calibration is owner-gated")
        if call_cap is None:
            raise CalibrationClosed("call cap is required for live execution")
        if dispatcher is None:
            dispatcher = live_dispatcher
        if not api_key:
            raise CalibrationClosed("purpose-created Cursor API key is required")
        budget = LeafBudget(call_cap)
        selected = reconstruct_packet_prompts()[:call_cap]
    else:
        if dispatcher is not None:
            # Dry-run may receive a dispatcher only so tests can prove it is unused.
            pass
        budget = None
        selected = reconstruct_packet_prompts()
    options = route_options()
    _assert_omitted_setting_sources(options)
    leaves: list[dict[str, object]] = []
    for prompt in selected:
        isolated = prepare_isolated_leaf(api_key=api_key if execute else None)
        started = _now()
        outcome: dict[str, object] = {
            "status": "DRY_RUN",
            "json_valid": None,
            "semantic_fixture_result": "PENDING",
            "semantic_failure_codes": [],
            "entity_count": None,
            "fact_count": None,
            "key_set_digest": None,
            "validator_version": VALIDATOR_VERSION,
            "stream_message_classes": [],
            "tool_call_count": None,
            "tool_call_observation_basis": "NOT_DISPATCHED",
            "observed_model": None,
            "model_identity_basis": "REQUEST_ONLY",
            "usage": unreported_cli_usage(),
            "latency_ms": None,
            "agent_id_sha256": None,
            "sdk_version": PINNED_SDK_VERSION,
            "bridge_protocol": PINNED_BRIDGE_PROTOCOL,
            "model": PINNED_MODEL,
        }
        try:
            inspect_isolation(
                home=isolated.home, cwd=isolated.cwd, store=isolated.store
            )
            if execute:
                if dispatcher is None or budget is None:
                    raise CalibrationClosed("live dispatcher or budget is unavailable")
                budget.consume()
                request = DispatchRequest(
                    prompt=prompt.prompt,
                    options=_live_options(isolated.cwd, isolated.store),
                    environ=isolated.environ,
                )
                try:
                    outcome.update(
                        _observe_dispatch(dispatcher(request), prompt=prompt)
                    )
                except (KeyboardInterrupt, asyncio.CancelledError) as exc:
                    outcome.update(_failure_outcome(exc, started=started))
                    leaves.append(
                        _write_leaf(
                            output_dir,
                            prompt=prompt,
                            isolated=isolated,
                            options=options,
                            outcome=outcome,
                            started=started,
                        )
                    )
                    aggregate = _build_packet_aggregate(
                        leaves,
                        execute=execute,
                        authorised=authorised,
                        call_cap=call_cap,
                    )
                    _write_json(output_dir / "aggregate.json", aggregate)
                    raise
                except ToolCallRejected as exc:
                    outcome.update(_failure_outcome(exc, started=started))
                    outcome["status"] = "TOOL_CALL_REJECTED"
                    outcome["tool_call_count"] = 1
                    outcome["tool_call_observation_basis"] = "OBSERVED_STREAM"
                except Exception as exc:  # noqa: BLE001 - retain a redacted failure receipt
                    outcome.update(_failure_outcome(exc, started=started))
            leaves.append(
                _write_leaf(
                    output_dir,
                    prompt=prompt,
                    isolated=isolated,
                    options=options,
                    outcome=outcome,
                    started=started,
                )
            )
        finally:
            isolated.cleanup()
    aggregate = _build_packet_aggregate(
        leaves,
        execute=execute,
        authorised=authorised,
        call_cap=call_cap,
    )
    _write_json(output_dir / "aggregate.json", aggregate)
    return aggregate


def live_dispatcher(request: DispatchRequest) -> object:
    try:
        import importlib.metadata

        from cursor_sdk import (
            Agent,
            AgentOptions,
            Client,
            LocalAgentOptions,
            LocalAgentStoreConfig,
        )
    except ImportError as exc:
        raise CalibrationClosed("cursor-sdk is not installed") from exc
    version = importlib.metadata.version("cursor-sdk")
    if not sdk_version_meets_floor(version):
        raise CalibrationClosed(
            f"cursor-sdk {version} is below the compatibility floor {PINNED_SDK_VERSION}"
        )
    api_key = request.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise CalibrationClosed("purpose-created Cursor API key is required")
    local = request.options["local"]
    if not isinstance(local, Mapping):
        raise CalibrationClosed("isolated local options are required")
    if "setting_sources" in local:
        raise CalibrationClosed("setting_sources must be omitted")
    store_cfg = local["store"]
    if not isinstance(store_cfg, Mapping):
        raise CalibrationClosed("ephemeral JSONL store is required")
    local_options = LocalAgentOptions(
        cwd=str(local["cwd"]),
        custom_tools={},
        store=LocalAgentStoreConfig(
            type=str(store_cfg["type"]),
            root_dir=str(store_cfg["root_dir"]),
        ),
    )
    bridge_state = Path(str(local["cwd"])).parent / "bridge-state"
    previous = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(request.environ)
        with Client.launch_bridge(
            workspace=str(local["cwd"]),
            state_root=str(bridge_state),
            local=local_options,
            client_timeout=180,
            allow_api_key_env_fallback=False,
        ) as client:
            models = client.models.list(api_key=api_key)
            identities = [
                model_id
                for model_id in (
                    getattr(model, "id", None) for model in models
                )
                if isinstance(model_id, str)
            ]
            selected_model = select_composer_model(identities)
            options = AgentOptions(
                model=selected_model,
                api_key=api_key,
                tools=[],
                mcp_servers={},
                agents={},
                local=local_options,
            )
            return Agent.prompt(request.prompt, options, client=client)
    finally:
        os.environ.clear()
        os.environ.update(previous)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Provider-free Cursor SDK no-tool calibration (#746)."
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--call-cap", type=int)
    parser.add_argument("--authorised-by-owner", action="store_true")
    parser.add_argument(
        "--api-key-env",
        default="CURSOR_API_KEY",
        help="Environment variable holding the purpose-created Cursor API key.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    api_key = os.environ.get(args.api_key_env) if args.execute else None
    try:
        run_packet(
            output_dir=args.output,
            execute=args.execute,
            call_cap=args.call_cap,
            authorised=args.authorised_by_owner,
            api_key=api_key,
        )
    except (CalibrationClosed, IsolationViolation, ToolCallRejected) as exc:
        print(str(exc), flush=True)
        return 2
    return 0


def _combined_schema() -> dict[str, Any]:
    from graphiti_core.prompts.extract_nodes_and_edges import CombinedExtraction

    return CombinedExtraction.model_json_schema()


def _timestamp_schema() -> dict[str, Any]:
    from graphiti_core.prompts.extract_edges import BatchEdgeTimestamps

    return BatchEdgeTimestamps.model_json_schema()


def _combined_prompt(body: str, *, nonempty: bool) -> str:
    prompt, _timestamps = _record_upstream(body, nonempty=nonempty)
    return prompt


def _nonzero_prompts() -> tuple[str, str]:
    return _record_upstream(RELATIONS_BODY, nonempty=True)


def _record_upstream(body: str, *, nonempty: bool) -> tuple[str, str]:
    import asyncio

    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.nodes import EpisodeType, EpisodicNode
    from graphiti_core.prompts.extract_edges import BatchEdgeTimestamps
    from graphiti_core.prompts.extract_nodes_and_edges import CombinedExtraction
    from graphiti_core.utils.maintenance.combined_extraction import (
        extract_nodes_and_edges,
    )

    class Recorder(LLMClient):
        def __init__(self) -> None:
            super().__init__(
                LLMConfig(model=PINNED_MODEL, small_model=PINNED_MODEL),
                cache=False,
            )
            self.calls: list[tuple[str, str]] = []

        async def _generate_response(
            self,
            messages: list[Any],
            response_model: type[Any] | None = None,
            max_tokens: int = 0,
            model_size: object = None,
        ) -> dict[str, Any]:
            del max_tokens, model_size
            name = "None" if response_model is None else response_model.__name__
            prompt = messages_to_prompt(messages)
            self.calls.append((name, prompt))
            if response_model is CombinedExtraction:
                if not nonempty:
                    return {"extracted_entities": [], "edges": []}
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
                            "fact": RELATIONS_BODY,
                            "episode_indices": [0],
                        }
                    ],
                }
            if response_model is BatchEdgeTimestamps:
                return {
                    "timestamps": [{"valid_at": REFERENCE_TIME, "invalid_at": None}]
                }
            raise AssertionError(name)

    recorder = Recorder()
    episode = EpisodicNode(
        name="sdk-calibration-fixture",
        group_id="newsroom-call-shape",
        labels=[],
        source=EpisodeType.text,
        source_description="newsroom-eval-proposal",
        content=body,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        valid_at=datetime.fromisoformat(REFERENCE_TIME),
    )
    asyncio.run(
        extract_nodes_and_edges(
            SimpleNamespace(llm_client=recorder),
            episode,
            [],
            custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )
    )
    combined = next(
        prompt for name, prompt in recorder.calls if name == "CombinedExtraction"
    )
    timestamps = next(
        (prompt for name, prompt in recorder.calls if name == "BatchEdgeTimestamps"),
        "",
    )
    return combined, timestamps


def _empty_route() -> dict[str, object]:
    return {
        "model": PINNED_MODEL,
        "tools": [],
        "mcp_servers": {},
        "agents": {},
    }


def _live_options(cwd: Path, store: Path) -> dict[str, object]:
    return {
        **_empty_route(),
        "local": {
            "cwd": str(cwd),
            "custom_tools": {},
            "store": {"type": "jsonl", "root_dir": str(store)},
        },
    }


def _route_isolation(
    options: Mapping[str, object], fs_manifest: Mapping[str, object]
) -> dict[str, object]:
    local = options.get("local")
    custom_tools: object = {}
    if isinstance(local, Mapping):
        custom_tools = local.get("custom_tools") or {}
    return {
        **fs_manifest,
        "tool_count": len(options.get("tools") or ()),
        "mcp_count": len(options.get("mcp_servers") or {}),
        "subagent_count": len(options.get("agents") or {}),
        "custom_tool_count": (
            len(custom_tools) if isinstance(custom_tools, Mapping) else 0
        ),
        "prior_message_count": 0,
    }


def compare_packet_to_cli(
    leaves: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_label = {str(leaf.get("label")): leaf for leaf in leaves}
    rows = (
        ("sdk-no-tool-tiny", "hermetic-tiny", 20_103, None),
        ("sdk-upstream-combined-zero", "hermetic-combined", 23_674, 25_000),
        ("sdk-upstream-combined-relations", None, None, None),
        ("sdk-upstream-batch-timestamps", None, None, None),
        ("sdk-compact-temporal-zero", None, None, None),
        ("sdk-compact-temporal-relations", None, None, None),
        ("sdk-compact-temporal-long", None, None, None),
        ("sdk-predeclared-repeat", None, None, None),
    )
    comparison: list[dict[str, object]] = []
    for label, cli_label, cli_input, cli_chat_total in rows:
        leaf = by_label.get(label, {})
        usage = leaf.get("usage") if isinstance(leaf.get("usage"), Mapping) else {}
        comparison.append(
            {
                "label": label,
                "cli_label": cli_label,
                "cli_input_tokens": cli_input,
                "cli_chat_total": cli_chat_total,
                "sdk_input_tokens": (
                    usage.get("input_tokens") if isinstance(usage, Mapping) else None
                ),
                "sdk_total_tokens": (
                    usage.get("total_tokens") if isinstance(usage, Mapping) else None
                ),
                "usage_status": (
                    usage.get("usage_basis")
                    if isinstance(usage, Mapping)
                    else "UNREPORTED"
                ),
            }
        )
    return comparison


def _observe_dispatch(result: object, *, prompt: LeafPrompt) -> dict[str, object]:
    classes: list[str] = []
    tool_calls: int | None = 0
    messages = getattr(result, "messages", None)
    if callable(messages):
        messages = messages()
    if messages is None:
        messages = getattr(result, "stream_messages", None)
    if messages is None:
        tool_calls = None
        tool_observation_basis = "NOT_EXPOSED_BY_AGENT_PROMPT"
        messages = ()
    else:
        tool_observation_basis = "OBSERVED_STREAM"
    for message in messages:
        kind = str(
            getattr(message, "type", None) or getattr(message, "kind", "unknown")
        )
        classes.append(kind)
        if kind in {"tool_call", "tool-call", "tool_use"}:
            if tool_calls is None:
                raise CalibrationClosed("tool-call observation state is inconsistent")
            tool_calls += 1
    if tool_calls:
        raise ToolCallRejected("no-tool route emitted a tool-call event")
    text = getattr(result, "result", None)
    if text is None:
        text = getattr(result, "text", None)
        if callable(text):
            text = text()
    assessment = assess_result(text, prompt=prompt)
    observed_model = _model_id(result)
    failure_codes = list(assessment.failure_codes)
    if observed_model is None:
        failure_codes.append("MODEL_IDENTITY_UNREPORTED")
        model_identity_basis = "REQUEST_AND_CATALOGUE"
    elif observed_model != PINNED_MODEL:
        failure_codes.append("MODEL_IDENTITY_MISMATCH")
        model_identity_basis = "RUN_RESULT"
    else:
        model_identity_basis = "RUN_RESULT"
    semantic_result = "PASS" if assessment.json_valid and not failure_codes else "FAIL"
    agent_id = getattr(result, "agent_id", None) or getattr(result, "id", None)
    duration = getattr(result, "duration_ms", None)
    status = getattr(result, "status", "finished")
    status = str(getattr(status, "value", status))
    return {
        "status": status,
        "json_valid": assessment.json_valid,
        "semantic_fixture_result": semantic_result,
        "semantic_failure_codes": failure_codes,
        "entity_count": assessment.entity_count,
        "fact_count": assessment.fact_count,
        "key_set_digest": assessment.key_set_digest,
        "validator_version": VALIDATOR_VERSION,
        "stream_message_classes": classes,
        "tool_call_count": tool_calls,
        "tool_call_observation_basis": tool_observation_basis,
        "usage": normalise_usage(getattr(result, "usage", None)),
        "latency_ms": duration if isinstance(duration, int) else None,
        "agent_id_sha256": (
            digest_bytes(str(agent_id).encode("utf-8")) if agent_id else None
        ),
        "sdk_version": PINNED_SDK_VERSION,
        "bridge_protocol": PINNED_BRIDGE_PROTOCOL,
        "model": PINNED_MODEL,
        "observed_model": observed_model,
        "model_identity_basis": model_identity_basis,
    }


def assess_result(text: object, *, prompt: LeafPrompt) -> SemanticAssessment:
    """Score a leaf while retaining only content-free failure diagnostics."""

    if not isinstance(text, str) or not text.strip():
        return _assessment(False, ("INVALID_JSON",))
    try:
        payload = json.loads(
            text[text.find("{") : text.rfind("}") + 1],
            object_pairs_hook=_unique_json_object,
        )
    except _DuplicateJsonKey:
        return _assessment(False, ("DUPLICATE_JSON_KEY",))
    except json.JSONDecodeError:
        return _assessment(False, ("INVALID_JSON",))
    if not isinstance(payload, dict):
        return _assessment(False, ("INVALID_TOP_LEVEL",))
    entity_count, fact_count = _diagnostic_counts(payload, prompt=prompt)
    key_set_digest = _key_set_digest(payload)
    schema_codes = list(_schema_failure_codes(payload, prompt=prompt))
    if prompt.prompt_class == "tiny":
        codes = schema_codes
        if payload.get("ok") is not True:
            codes.append("MISSING_EXPECTED_OK")
        return _assessment(
            True,
            codes,
            entity_count=entity_count,
            fact_count=fact_count,
            key_set_digest=key_set_digest,
        )
    if (
        prompt.prompt_class == "upstream_combined"
        and prompt.fixture_id == "zero-result-368"
    ):
        codes = schema_codes + ["FIXTURE_EXPECTATION_INVALID"]
        codes.extend(
            _relation_failure_codes(
                payload,
                entity_key="extracted_entities",
                fact_key="edges",
                require_temporal=False,
            )
        )
        return _assessment(
            True,
            codes,
            entity_count=entity_count,
            fact_count=fact_count,
            key_set_digest=key_set_digest,
        )
    if prompt.prompt_class == "upstream_combined" and prompt.fixture_id == "relations":
        codes = schema_codes + list(
            _relation_failure_codes(
                payload,
                entity_key="extracted_entities",
                fact_key="edges",
                require_temporal=False,
            )
        )
        return _assessment(
            True,
            codes,
            entity_count=entity_count,
            fact_count=fact_count,
            key_set_digest=key_set_digest,
        )
    if prompt.prompt_class == "upstream_batch_timestamps":
        stamps = payload.get("timestamps")
        codes = schema_codes
        if not isinstance(stamps, list) or not stamps:
            codes.append("MISSING_TIMESTAMP_LIST")
        elif any(
            not isinstance(item, dict) or "valid_at" not in item for item in stamps
        ):
            codes.append("MISSING_VALID_AT")
        if (
            isinstance(stamps, list)
            and stamps
            and any(
                not isinstance(item, dict)
                or not _valid_optional_timestamp(item.get("valid_at"))
                or not _valid_optional_timestamp(item.get("invalid_at"))
                for item in stamps
            )
        ):
            codes.append("INVALID_TEMPORAL_VALUE")
        return _assessment(
            True,
            codes,
            entity_count=entity_count,
            fact_count=fact_count,
            key_set_digest=key_set_digest,
        )
    if prompt.prompt_class == "compact_combined_temporal":
        if prompt.fixture_id == "zero-result-368":
            codes = schema_codes + ["FIXTURE_EXPECTATION_INVALID"]
            codes.extend(
                _relation_failure_codes(
                    payload,
                    entity_key="entities",
                    fact_key="facts",
                    require_temporal=True,
                )
            )
        else:
            codes = schema_codes + list(
                _relation_failure_codes(
                    payload,
                    entity_key="entities",
                    fact_key="facts",
                    require_temporal=True,
                )
            )
        return _assessment(
            True,
            codes,
            entity_count=entity_count,
            fact_count=fact_count,
            key_set_digest=key_set_digest,
        )
    return _assessment(
        True,
        ("UNCLASSIFIED_CONTRACT_MISMATCH",),
        entity_count=entity_count,
        fact_count=fact_count,
        key_set_digest=key_set_digest,
    )


def _assessment(
    json_valid: bool,
    codes: Sequence[str],
    *,
    entity_count: int | None = None,
    fact_count: int | None = None,
    key_set_digest: str | None = None,
) -> SemanticAssessment:
    failures = tuple(dict.fromkeys(codes))
    return SemanticAssessment(
        json_valid=json_valid,
        result="PASS" if json_valid and not failures else "FAIL",
        failure_codes=failures,
        entity_count=entity_count,
        fact_count=fact_count,
        key_set_digest=key_set_digest,
    )


def _diagnostic_counts(
    payload: Mapping[str, object], *, prompt: LeafPrompt
) -> tuple[int | None, int | None]:
    if prompt.prompt_class == "upstream_combined":
        entities = payload.get("extracted_entities")
        facts = payload.get("edges")
    elif prompt.prompt_class == "upstream_batch_timestamps":
        entities = []
        facts = payload.get("timestamps")
    elif prompt.prompt_class == "compact_combined_temporal":
        entities = payload.get("entities")
        facts = payload.get("facts")
    else:
        entities = []
        facts = []
    return (
        len(entities) if isinstance(entities, list) else None,
        len(facts) if isinstance(facts, list) else None,
    )


def _key_set_digest(payload: Mapping[str, object]) -> str:
    shape: dict[str, object] = {"top_level": sorted(map(str, payload))}
    for name, value in sorted(payload.items()):
        if isinstance(value, list):
            shape[str(name)] = [
                (
                    sorted(map(str, item))
                    if isinstance(item, Mapping)
                    else type(item).__name__
                )
                for item in value
            ]
    return digest_bytes(canonical_json_bytes(shape))


def _relation_failure_codes(
    payload: Mapping[str, object],
    *,
    entity_key: str,
    fact_key: str,
    require_temporal: bool,
) -> tuple[str, ...]:
    entities = payload.get(entity_key)
    facts = payload.get(fact_key)
    codes: list[str] = []
    if not isinstance(entities, list):
        codes.append("MISSING_ENTITY_LIST")
    if not isinstance(facts, list):
        codes.append("MISSING_FACT_LIST")
    if not isinstance(entities, list) or not isinstance(facts, list):
        return tuple(codes)
    names = {item.get("name") for item in entities if isinstance(item, dict)}
    expected = {
        "Legislative Council",
        "Technology and Living curriculum",
    }
    if not expected <= names:
        codes.append("MISSING_EXPECTED_ENTITY")
    types = {item.get("relation_type") for item in facts if isinstance(item, dict)}
    if "ASKED_ABOUT" not in types:
        codes.append("MISSING_RELATION_TYPE")
    if require_temporal and any(
        not isinstance(item, dict) or "valid_at" not in item or "invalid_at" not in item
        for item in facts
    ):
        codes.append("MISSING_TEMPORAL_KEYS")
    if require_temporal:
        if any(
            not isinstance(item, dict)
            or not _valid_optional_timestamp(item.get("valid_at"))
            or not _valid_optional_timestamp(item.get("invalid_at"))
            for item in facts
        ):
            codes.append("INVALID_TEMPORAL_VALUE")
        if any(
            not isinstance(item, dict)
            or not _nonempty_string_list(item.get("evidence_segment_ids"))
            for item in (*entities, *facts)
        ):
            codes.append("MISSING_EVIDENCE_SEGMENT_IDS")
        local_ids = [
            item.get("local_id") for item in entities if isinstance(item, dict)
        ]
        valid_local_ids = {
            item
            for item in local_ids
            if isinstance(item, int) and not isinstance(item, bool)
        }
        if len(valid_local_ids) != len(entities) or any(
            not isinstance(item, dict)
            or item.get("source_local_id") not in valid_local_ids
            or item.get("target_local_id") not in valid_local_ids
            for item in facts
        ):
            codes.append("INVALID_LOCAL_REFERENCE")
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("fact"), str)
            or not str(item.get("fact")).strip()
            for item in facts
        ):
            codes.append("MISSING_FACT_TEXT")
        codes.append("EVIDENCE_CONTRACT_UNVERIFIABLE")
    return tuple(codes)


def _valid_optional_timestamp(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _nonempty_string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _schema_failure_codes(
    payload: Mapping[str, object], *, prompt: LeafPrompt
) -> tuple[str, ...]:
    validator = Draft202012Validator(prompt.schema, format_checker=FormatChecker())
    return () if validator.is_valid(payload) else ("SCHEMA_VALIDATION_FAILED",)


def _unique_json_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise _DuplicateJsonKey
        payload[key] = value
    return payload


def _model_id(result: object) -> str | None:
    model = getattr(result, "model", None)
    if isinstance(model, str):
        return model
    if isinstance(model, Mapping):
        candidate = model.get("id")
    else:
        candidate = getattr(model, "id", None)
    return candidate if isinstance(candidate, str) and candidate else None


def _failure_outcome(exc: BaseException, *, started: datetime) -> dict[str, object]:
    name = type(exc).__name__
    status = {
        "CancelledError": "CANCELLED",
        "TimeoutError": "TIMEOUT",
        "KeyboardInterrupt": "CANCELLED",
    }.get(name, "FAILED")
    return {
        "status": status,
        "json_valid": None,
        "semantic_fixture_result": "UNRESOLVED",
        "semantic_failure_codes": ["DISPATCH_FAILED"],
        "entity_count": None,
        "fact_count": None,
        "key_set_digest": None,
        "validator_version": VALIDATOR_VERSION,
        "stream_message_classes": [],
        "tool_call_count": None,
        "tool_call_observation_basis": "NOT_AVAILABLE_AFTER_DISPATCH_FAILURE",
        "usage": unreported_cli_usage(),
        "latency_ms": _elapsed_ms(started),
        "agent_id_sha256": None,
        "failure": name,
        "observed_model": None,
        "model_identity_basis": "REQUEST_ONLY",
    }


def _write_leaf(
    output_dir: Path,
    *,
    prompt: LeafPrompt,
    isolated: IsolatedLeaf,
    options: Mapping[str, object],
    outcome: Mapping[str, object],
    started: datetime,
) -> dict[str, object]:
    prompt_bytes = prompt.prompt.encode("utf-8")
    schema_bytes = canonical_json_bytes(prompt.schema)
    isolation = _route_isolation(options, isolated.manifest)
    isolation_digest = digest_bytes(canonical_json_bytes(isolation))
    route_digest = digest_bytes(canonical_json_bytes(options))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "ordinal": prompt.ordinal,
        "label": prompt.label,
        "prompt_class": prompt.prompt_class,
        "fixture_id": prompt.fixture_id,
        "fixture_validity": (
            "INVALID_ZERO_EXPECTATION"
            if prompt.fixture_id == "zero-result-368"
            else "VALID"
        ),
        "prompt_chars": len(prompt.prompt),
        "prompt_bytes": len(prompt_bytes),
        "prompt_sha256": digest_bytes(prompt_bytes),
        "schema_bytes": len(schema_bytes),
        "schema_sha256": digest_bytes(schema_bytes),
        "route_option_digest": route_digest,
        "isolation": isolation,
        "isolation_digest": isolation_digest,
        "environment_allow_list_digest": digest_bytes(
            canonical_json_bytes(isolation["environment_allow_list"])
        ),
        "sdk_version": outcome.get("sdk_version"),
        "bridge_protocol": outcome.get("bridge_protocol"),
        "model": outcome.get("model"),
        "agent_id_sha256": outcome.get("agent_id_sha256"),
        "usage": dict(outcome["usage"]),  # type: ignore[arg-type]
        "usage_status": outcome["usage"]["usage_basis"],  # type: ignore[index]
        "latency_ms": outcome.get("latency_ms") or _elapsed_ms(started),
        "json_valid": outcome.get("json_valid"),
        "semantic_fixture_result": outcome.get("semantic_fixture_result"),
        "semantic_failure_codes": list(outcome.get("semantic_failure_codes") or ()),
        "entity_count": outcome.get("entity_count"),
        "fact_count": outcome.get("fact_count"),
        "key_set_digest": outcome.get("key_set_digest"),
        "validator_version": outcome.get("validator_version"),
        "stream_message_classes": list(outcome.get("stream_message_classes") or ()),
        "tool_call_count": outcome.get("tool_call_count"),
        "tool_call_observation_basis": outcome.get("tool_call_observation_basis"),
        "status": outcome.get("status"),
        "observed_model": outcome.get("observed_model"),
        "model_identity_basis": outcome.get("model_identity_basis"),
    }
    if "failure" in outcome:
        receipt["failure"] = outcome["failure"]
    _write_json(output_dir / f"{prompt.label}.json", receipt)
    return receipt


def _semantic_summary(
    leaves: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    outcomes = [leaf.get("semantic_fixture_result") for leaf in leaves]
    return {
        "pass_count": outcomes.count("PASS"),
        "fail_count": outcomes.count("FAIL"),
        "pending_count": outcomes.count("PENDING"),
        "unresolved_count": outcomes.count("UNRESOLVED"),
        "invalid_json_count": sum(leaf.get("json_valid") is False for leaf in leaves),
    }


def _exact_repeat_summary(
    leaves: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    by_label = {str(leaf.get("label")): leaf for leaf in leaves}
    original = by_label.get("sdk-compact-temporal-relations")
    repeat = by_label.get("sdk-predeclared-repeat")
    if original is None or repeat is None:
        return {
            "available": False,
            "prompt_digest_matches": None,
            "semantic_outcome_matches": None,
            "input_token_delta": None,
            "input_token_delta_fraction": None,
        }
    original_usage = original.get("usage")
    repeat_usage = repeat.get("usage")
    original_input = (
        original_usage.get("input_tokens")
        if isinstance(original_usage, Mapping)
        else None
    )
    repeat_input = (
        repeat_usage.get("input_tokens") if isinstance(repeat_usage, Mapping) else None
    )
    delta = (
        repeat_input - original_input
        if isinstance(original_input, int) and isinstance(repeat_input, int)
        else None
    )
    fraction = (
        delta / original_input
        if isinstance(delta, int) and isinstance(original_input, int) and original_input
        else None
    )
    return {
        "available": True,
        "prompt_digest_matches": original.get("prompt_sha256")
        == repeat.get("prompt_sha256"),
        "semantic_outcome_matches": original.get("semantic_fixture_result")
        == repeat.get("semantic_fixture_result"),
        "input_token_delta": delta,
        "input_token_delta_fraction": fraction,
    }


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    rendered = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _prepare_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise CalibrationClosed("output directory must be empty for a new packet")


def _assert_omitted_setting_sources(options: Mapping[str, object]) -> None:
    blob = json.dumps(options)
    if "setting_sources" in blob:
        raise CalibrationClosed("setting_sources must be omitted")
    for name in FORBIDDEN_SETTING_SOURCES:
        if f'"{name}"' in blob:
            raise CalibrationClosed(f"forbidden setting source {name}")


def _cursor_entries(root: Path) -> tuple[str, ...]:
    cursor = root / ".cursor"
    if not cursor.exists():
        return ()
    return _entry_names(cursor)


def _entry_names(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    return tuple(sorted(path.name for path in root.iterdir()))


def _hook_paths(*roots: Path) -> tuple[Path, ...]:
    found: list[Path] = []
    for root in roots:
        candidate = root / ".cursor" / "hooks.json"
        if candidate.exists():
            found.append(candidate)
        nested = root / "hooks.json"
        if nested.exists():
            found.append(nested)
    return tuple(found)


def _first_present(*values: object) -> object:
    for value in values:
        if value is not None:
            return value
    return None


def _token(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _elapsed_ms(started: datetime) -> int:
    return max(0, int((_now() - started).total_seconds() * 1000))


__all__ = [
    "CLI_TINY_INPUT_TOKENS",
    "ENVIRONMENT_ALLOW_LIST",
    "LEAF_LABELS",
    "MAXIMUM_LEAVES",
    "MINIMUM_EFFECT_CEILING",
    "PINNED_MODEL",
    "PINNED_SDK_VERSION",
    "TINY_PROMPT",
    "VALIDATOR_VERSION",
    "CalibrationClosed",
    "DispatchRequest",
    "IsolationViolation",
    "LeafBudget",
    "LeafPrompt",
    "SemanticAssessment",
    "ToolCallRejected",
    "assess_result",
    "compact_prompt",
    "compare_to_cli_baseline",
    "inspect_isolation",
    "isolated_environ",
    "live_dispatcher",
    "long_retained_chunk",
    "main",
    "normalise_usage",
    "over_limit_revision",
    "prepare_isolated_leaf",
    "recommend",
    "reconstruct_packet_prompts",
    "route_options",
    "run_packet",
    "source_safe_body",
]
