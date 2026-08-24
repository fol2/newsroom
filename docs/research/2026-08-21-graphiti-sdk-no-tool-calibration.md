# Graphiti Cursor SDK no-tool calibration (#746)

- Role: Dated research harness, setup instructions and owner-gated packet
- Status: Provider-free harness checked in; owner-authorised eight-leaf live packet completed on 2026-08-22; recommendation `REJECT`
- Owner: fol2
- Canonical language: English
- Date: 2026-08-21
- Parent: [#739](https://github.com/fol2/newsroom/issues/739)
- Ticket: [#746](https://github.com/fol2/newsroom/issues/746)
- Packet: [`2026-08-21-graphiti-sdk-no-tool-calibration-packet.json`](2026-08-21-graphiti-sdk-no-tool-calibration-packet.json)
- Receipt schema: [`2026-08-21-graphiti-sdk-no-tool-calibration.schema.json`](2026-08-21-graphiti-sdk-no-tool-calibration.schema.json)

This note is non-normative research evidence. It does not amend `GING-010`, authorise SDK use in runtime, call Grok or OpenRouter, mutate Neo4j, or publish.

## 1. What is checked in

The default runner is provider-free and lives under `newsroom.research`, outside the protected production Graphiti adapter boundary. It reconstructs the #739 source-safe 368-byte fixture, the 49-character tiny prompt, graphiti-core 0.29.3 combined and batch-timestamp prompt shapes, and the historical compact combined-temporal candidate prompts. Dry-run writes one redacted receipt per leaf plus an aggregate manifest into a required-empty output directory. Missing usage is `UNREPORTED`, never zero.

```text
uv sync --dev --extra graphiti --locked
uv run python -m scripts.graphiti_sdk_no_tool_calibration \
  --output /tmp/newsroom-746-dry
```

Live dispatch is refused unless `--execute`, `--call-cap` and `--authorised-by-owner` are all supplied. The committed packet keeps `"authorised": false`. A later live run records owner authorisation on that run's aggregate only.

On 2026-08-21 the owner authorised the local eight-leaf packet in-session. A purpose-created User API key was supplied on 2026-08-22. The live execute completed with eight requested and catalogue-verified `composer-2.5` leaves and recommendation `REJECT`. The historical receipts did not retain each `RunResult.model`. Redacted receipts: [`2026-08-21-graphiti-sdk-no-tool-calibration-receipts/`](2026-08-21-graphiti-sdk-no-tool-calibration-receipts/).

Live command:

```text
uv sync --dev --extra graphiti --extra cursor-research --locked
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

Install the locked research-only SDK extra on the measuring host. It remains separate from the production Graphiti extra:

```text
uv sync --dev --extra graphiti --extra cursor-research --locked
uv run python -c "import importlib.metadata as m; print(m.version('cursor-sdk'))"
```

Create a purpose-created Cursor user or service-account API key. Export it as `CURSOR_API_KEY` for that shell only. Do not copy `~/.cursor`, `cli-config.json`, transcripts, rules, skills, MCP catalogues or login cookies into the fixture.

The runner then:

1. lists models and refuses anything other than exact `composer-2.5` (no Auto, no Fast);
2. builds a fresh isolated `HOME`, XDG config/data/cache/state, `TMPDIR` and JSONL store per leaf;
3. launches and closes a fresh SDK bridge per leaf with its workspace, state root and agent `cwd` inside that isolated root;
4. fails before dispatch if hooks, `.cursor` files, git metadata or prior store entries are present;
5. calls `Agent.prompt` with `tools=[]`, empty MCP/subagents/custom tools, and `setting_sources` omitted;
6. consumes one slot from a monotonic 1–8 leaf budget and never retries an unchanged request; and
7. records a `CANCELLED` leaf and aggregate with `UNREPORTED` usage before temporary cleanup, stops later leaves, then propagates cancellation.

## 3. Decision rule

Compared with the #739 hermetic CLI tiny observation of 20,103 input tokens:

```text
minimum useful reduction:  input <= 10,051
preferred reduction:       at least 75% below 20,103
```

The route is a successor candidate only when every leaf also proves zero hooks, zero tool calls, zero MCP, zero subagents, zero custom tools, omitted setting sources, zero prior store entries and no prior messages, and the multi-entity fixture keeps exact entity, relation and temporal contracts. Cheaper-but-invalid JSON is not success.

Allowed recommendations: `ADOPT_FOR_QUALIFICATION`, `RESEARCH_ONLY`, `REJECT`. Dry-run reports `UNMEASURED`.

### Per-path comparison against #739 CLI receipts

Live execute on 2026-08-22, `cursor-sdk==1.0.28`, requested and catalogue-verified `composer-2.5`, `tools=[]`, `setting_sources` omitted and eight provider-reported leaves. The retained isolation manifests are all zero, but the historical runner used the SDK default bridge and did not retain bridge-workspace evidence. `Agent.prompt` returned `RunResult`, which exposes no stream messages in SDK 1.0.28, so the retained zero `tool_call_count` is derived from the empty configured tool surface rather than direct event observation.

| SDK leaf | CLI counterpart | CLI input / chat total | SDK input / total | Semantic |
|---|---|---:|---:|---|
| `sdk-no-tool-tiny` | `hermetic-tiny` | 20,103 input | 3,430 / 3,878 | PASS |
| `sdk-upstream-combined-zero` | `hermetic-combined` | 23,674 input / 25,000 chat | 7,152 / 8,002 | retained FAIL label; zero expectation invalid |
| `sdk-upstream-combined-relations` | none | — | 7,100 / 7,810 | PASS |
| `sdk-upstream-batch-timestamps` | none | — | 3,984 / 4,778 | PASS |
| `sdk-compact-temporal-zero` | none | — | 17,356 / 29,322 | retained FAIL label; zero expectation invalid |
| `sdk-compact-temporal-relations` | none | — | 21,758 / 31,912 | FAIL |
| `sdk-compact-temporal-long` | none | — | 4,958 / 10,169 | FAIL (`json_valid` false) |
| `sdk-predeclared-repeat` | exact repeat of leaf 6 | — | 28,221 / 35,705 | PASS |

Tiny-prompt input fell 82.9% below the CLI floor of 20,103, which meets both the 50% minimum and the 75% preferred reduction. Upstream combined input also fell well below the hermetic CLI 23,674 / 25,000 observation. The packet still recommends `REJECT`: four of eight leaves carried historical pre-v3 FAIL labels, the exact repeat of leaf 6 changed from failure to pass while input increased by 6,463 tokens (29.7%), and the long result was invalid JSON. Provider-free re-review found that the two supposed zero-result leaves actually used a relation-bearing source naming the Legislative Council and the Technology and Living curriculum. Their zero expectations were invalid, so the four retained labels must not be presented as four proved model-quality failures. The invalid fixtures weaken the packet further; they do not rescue it.

The no-tool SDK floor is therefore a useful **text-only Cursor agent research transport**. `tools=[]` removes built-in tools; it does not prove a raw inference path or a guaranteed fixed floor. The original compact prompt contract remains rejected. #747 subsequently qualified a corrected contract provider-free and merged it through PR #751; its live quality and token usage remain separately unmeasured.

### Redaction-safe diagnostics

The historical v1 receipts correctly omitted model text, full prompts and account data, but retained only binary semantic results. The original causes of three JSON-valid FAIL labels are therefore unrecoverable and remain `UNCLASSIFIED_RETAINED_FAILURE`; the invalid long response remains `INVALID_JSON`. Provider-free fixture inspection separately marks the two relation-bearing sources that were mislabelled as zero-result fixtures. It does not invent a model-output cause after the fact.

Provider-free validator v3 now retains only content-free diagnostics:

- strict JSON Schema qualification plus typed failure codes such as `DUPLICATE_JSON_KEY`, `SCHEMA_VALIDATION_FAILED`, `FIXTURE_EXPECTATION_INVALID`, `EVIDENCE_CONTRACT_UNVERIFIABLE`, `MISSING_EXPECTED_ENTITY`, `MISSING_RELATION_TYPE`, `MISSING_TEMPORAL_KEYS` and `INVALID_JSON`;
- entity and fact counts;
- a digest of object key sets, never values;
- fixture validity, requested-versus-observed model identity basis, tool-call observation basis and validator version; and
- aggregate pass/fail counts plus exact-repeat token and outcome divergence.

The future live seam now fails closed unless the output directory is empty, launches a fresh isolated bridge per leaf and refuses qualification when the `Agent.prompt` lifecycle cannot expose tool-call events. A later accepted qualification may use a separately measured event-observable SDK lifecycle; it must not relabel the historical `Agent.prompt` token packet as equivalent.

The seventh historical live leaf was exactly 8,192 bytes and did not cross the chunk boundary. A separate provider-free fixture now uses `MAX_EPISODE_BYTES + 50`, requires two bounded chunks and proves complete ordered reconstruction. No further provider call was made or authorised.

## 4. Non-effects

This harness does not change the production Graphiti transport, install a token ceiling, activate backlog ingest, or retain API keys, full prompts, model text, account email, transcripts or local home paths.
