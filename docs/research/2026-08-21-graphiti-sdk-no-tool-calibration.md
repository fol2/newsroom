# Graphiti Cursor SDK no-tool calibration (#746)

- Role: Dated research harness, setup instructions and owner-gated packet
- Status: Provider-free harness checked in; live calibration requires an explicit owner instruction on the local host
- Owner: fol2
- Canonical language: English
- Date: 2026-08-21
- Parent: [#739](https://github.com/fol2/newsroom/issues/739)
- Ticket: [#746](https://github.com/fol2/newsroom/issues/746)
- Packet: [`2026-08-21-graphiti-sdk-no-tool-calibration-packet.json`](2026-08-21-graphiti-sdk-no-tool-calibration-packet.json)
- Receipt schema: [`2026-08-21-graphiti-sdk-no-tool-calibration.schema.json`](2026-08-21-graphiti-sdk-no-tool-calibration.schema.json)

This note is non-normative research evidence. It does not amend `GING-010`, authorise SDK use in runtime, call Grok or OpenRouter, mutate Neo4j, or publish.

## 1. What is checked in

The default runner is provider-free. It reconstructs the #739 source-safe 368-byte fixture, the 49-character tiny prompt, graphiti-core 0.29.3 combined and batch-timestamp prompt shapes, and the compact combined-temporal candidate prompts. Dry-run writes one redacted receipt per leaf plus an aggregate manifest. Missing usage is `UNREPORTED`, never zero.

```text
uv sync --dev --extra graphiti --locked
uv run python -m scripts.graphiti_sdk_no_tool_calibration \
  --output /tmp/newsroom-746-dry
```

Live dispatch is refused unless `--execute`, `--call-cap` and `--authorised-by-owner` are all supplied. The committed packet keeps `"authorised": false`. A later live run records owner authorisation on that run's aggregate only.

On 2026-08-21 the owner authorised the local eight-leaf packet in-session. The measuring shell had no purpose-created `CURSOR_API_KEY`, so the runner made **zero** provider calls rather than falling back to ambient Cursor login or Keychain tokens.

Live command after the key is exported:

```text
uv pip install cursor-sdk==1.0.28
export CURSOR_API_KEY=...   # purpose-created key only
uv run python -m scripts.graphiti_sdk_no_tool_calibration \
  --output docs/research/2026-08-21-graphiti-sdk-no-tool-calibration-receipts \
  --execute --call-cap 8 --authorised-by-owner
```

## 2. Exact local setup for a live packet

Pin and verify before any provider call:

```text
cursor-sdk==1.0.28
bridge protocol sdk.v1
model identity composer-2.5
graphiti-core==0.29.3
```

Install the SDK only on the measuring host. Do not add it to the production Graphiti extra:

```text
uv pip install cursor-sdk==1.0.28
python -c "import importlib.metadata as m; print(m.version('cursor-sdk'))"
```

Create a purpose-created Cursor user or service-account API key. Export it as `CURSOR_API_KEY` for that shell only. Do not copy `~/.cursor`, `cli-config.json`, transcripts, rules, skills, MCP catalogues or login cookies into the fixture.

The runner then:

1. lists models and refuses anything other than exact `composer-2.5` (no Auto, no Fast);
2. builds a fresh isolated `HOME`, XDG config/data/cache/state, `TMPDIR` and JSONL store per leaf;
3. uses a fresh empty non-git `cwd`;
4. fails before dispatch if hooks, `.cursor` files, git metadata or prior store entries are present;
5. calls `Agent.prompt` with `tools=[]`, empty MCP/subagents/custom tools, and `setting_sources` omitted;
6. consumes one slot from a monotonic 1–8 leaf budget and never retries an unchanged request.

## 3. Decision rule

Compared with the #739 hermetic CLI tiny observation of 20,103 input tokens:

```text
minimum useful reduction:  input <= 10,051
preferred reduction:       at least 75% below 20,103
```

The route is a successor candidate only when every leaf also proves zero hooks, zero tool calls, zero MCP, zero subagents, zero custom tools, omitted setting sources, zero prior store entries and no prior messages, and the multi-entity fixture keeps exact entity, relation and temporal contracts. Cheaper-but-invalid JSON is not success.

Allowed recommendations: `ADOPT_FOR_QUALIFICATION`, `RESEARCH_ONLY`, `REJECT`. Dry-run reports `UNMEASURED`.

### Per-path comparison against #739 CLI receipts

| SDK leaf | CLI counterpart | CLI input / chat total | SDK tokens |
|---|---|---:|---|
| `sdk-no-tool-tiny` | `hermetic-tiny` | 20,103 input | live / `UNREPORTED` until executed |
| `sdk-upstream-combined-zero` | `hermetic-combined` | 23,674 input / 25,000 chat | live / `UNREPORTED` until executed |
| remaining six leaves | none in the six-call CLI packet | — | live / `UNREPORTED` until executed |

The dry-run aggregate writes this table as `cli_path_comparison` with `UNREPORTED` SDK usage. A later authorised execute fills the SDK columns without rewriting the CLI baselines.

## 4. Non-effects

This harness does not change the production Graphiti transport, install a token ceiling, activate backlog ingest, or retain API keys, full prompts, model text, account email, transcripts or local home paths.
