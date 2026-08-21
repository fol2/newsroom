# Graphiti Cursor subscription bootstrap: productive limits without content cuts

- Role: Dated research and current-state evidence
- Status: Completed
- Owner: fol2
- Canonical language: English
- Date: 2026-08-21
- Related issue: [#739](https://github.com/fol2/newsroom/issues/739)
- Related: [#726](https://github.com/fol2/newsroom/issues/726) (parent), [#731](https://github.com/fol2/newsroom/issues/731) (unblocked by this), [#728](https://github.com/fol2/newsroom/issues/728), [#730](https://github.com/fol2/newsroom/issues/730), [#736](https://github.com/fol2/newsroom/issues/736), [#737](https://github.com/fol2/newsroom/issues/737)
- Measurement worktree HEAD: `d24663236b99453088f07c018e498b1ff4643f61` (source inspection and calibration preparation; PR exact state is recorded in #745)
- Cursor Agent CLI: `2026.08.11-e8db854` (`~/.local/bin/cursor-agent`)
- graphiti-core: `0.29.3` (optional extra; `pyproject.toml`)
- Local host observation: `cursor-agent about --format json` reports `subscriptionTier` Ultra (email omitted)
- Owner-approved calibration: 2026-08-21; 6 of 8 Cursor print-mode calls; no Grok; no OpenRouter. Redacted receipts: [`2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json`](2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json)

This note is decision evidence for #731. The owner approved the §13 bound on 2026-08-21. No further live call, credential, spend, publication or production change is authorised by this note.

## 1. Research question and non-goals

**Question.** How can Graphiti retain the pinned Cursor subscription / Composer 2.5 route while removing avoidable agent heading, tool/bootstrap context, repeated schema work and retry waste, so that every call and every token contributes to a terminal, governed extraction result?

**Productive limitation.** Identify restrictions that stop waste. Do not recommend a normal hard token cut that truncates retained source content, refuses legitimate effective revisions, or treats low usage as success when extraction quality fails.

**Non-goals**

- Switching product or model to save tokens. Chat remains cursor-agent CLI `composer-2.5`, then Grok Build CLI `grok-4.6` reasoning `medium`. Embeddings remain OpenRouter `text-embedding-3-large` under OD-011. ([`docs/decisions/2026-08-20-graphiti.md`](../decisions/2026-08-20-graphiti.md) Model pin; `GING-010`.)
- Making Graphiti authoritative. Zero-proposal terminal extraction is a valid completed result. (#731; `GING-007`.)
- Unbounded calibration. The owner approved at most eight Cursor print-mode calls; six were used. Further Composer traffic remains a separate approval.
- Owning CONT hermetic writer implementation (#730), usage-receipt schema (#728), or effective-pull identity (#737).
- Inventing a combined Graphiti API that 0.29.3 does not ship.

## 2. Evidence classification legend

| Label | Meaning |
|---|---|
| **Measured** | Observed on this worktree, in #739's metered episode, in a provider-free fixture, or in non-secret local CLI/config inventory |
| **Documented** | First-party Cursor docs, Cursor CLI `--help`, graphiti-core 0.29.3 source, or an Accepted Newsroom decision/spec |
| **Inferred** | Derived from measured plus documented facts; not a live calibration |
| **Unresolved** | Would require an authorised live call, unpublished Cursor internals, or a missing local artefact |

Every factual claim below is one of these four.

## 3. Current invocation anatomy

Command actually dispatched (Graphiti primary):

```text
cursor-agent --print --mode ask --output-format json --sandbox enabled --trust --model composer-2.5 <prompt>
```

Evidence: `newsroom/graphiti_adapter/cli_client.py:135-149`; model id `composer-2.5` from `evaluation_packet.py:34`.

| Aspect | Current behaviour | Evidence |
|---|---|---|
| Working directory | Fresh `TemporaryDirectory(prefix="newsroom-cursor-graphiti-")` | `cli_client.py:234-241` |
| Environment / `HOME` | Inherited. `subprocess.run` / `create_subprocess_exec` pass no `env=` | `cli_client.py:73-91`, `103-132` |
| Workspace | CLI `--workspace` omitted; docs default to cwd | [Cursor CLI parameters](https://cursor.com/docs/cli/reference/parameters) |
| Graphiti `max_tokens` | Received then discarded (`del max_tokens, model_size`) | `cli_client.py:433-440` |
| Schema on Cursor | Included in the prompt because graphiti-core `generate_response` appends `response_model.model_json_schema()` to the last message *before* `_generate_response` | `graphiti_core/llm_client/client.py:215-221`; fixture `test_graphiti_core_0293_call_shape.py` |
| Schema on Grok | Same prompt plus `--json-schema` | `cli_client.py:152-173`, `442-446` |
| Fallback | Cursor then Grok; Grok `--max-turns 3`, `--reasoning-effort medium` | `cli_client.py:152-173`, `321-407`; `evaluation_packet.py:35-36` |
| Timeout | 80 s per CLI child | `cli_client.py:30` |
| Retry above the adapter | graphiti-core retries `_generate_response` up to **4** times on `EmptyResponseError`, rate-limit, JSON decode and HTTP 5xx | `client.py:120-139`, `62-71`; Newsroom maps `CliResponseError` to `EmptyResponseError` (`cli_client.py:455-456`) |
| Usage parse | Cursor JSON `usage.{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens}`; `reasoning_tokens` always `None` | `usage_meter.py:31-52` |
| Episode cap | `MAX_EPISODE_BYTES = 8192` | `identity.py:32` |

CONT comparison (same defect class, different command): `run_cursor_agent_cli` uses `--print --mode ask --output-format text --sandbox enabled --trust` with **no** `--model`, **no** temporary cwd, inherited environment (`writer.py:179-194`). Graphiti is already stricter on cwd and model pin; it is not hermetic on `HOME`.

Official JSON `--output-format json` success object documents `type`, `subtype`, `is_error`, `duration_ms`, `duration_api_ms`, `result`, `session_id`, `request_id`. It does **not** document `usage`. Field additions are permitted. ([output format](https://cursor.com/docs/cli/reference/output-format).) **Measured:** the 2026.08.11 CLI emits `usage` on successful print-mode JSON; Newsroom retains it. **Unresolved:** whether every failure path emits `usage` (docs: failure writes stderr and no well-formed JSON).

## 4. Track A: the ~21,960-token per-call delta

### 4.1 Measured sample (#739; treat as sample, not upper bound)

One fully metered successful Graphiti episode:

```text
Cursor Composer calls:        2
Cursor input tokens:     47,235
Cursor output tokens:     5,536
Cursor cache-read tokens: 1,152
Cursor chat total:       53,923
OpenRouter embedding:       364 tokens across 3 calls
observed total:           54,287 tokens
retained episode:           368 UTF-8 bytes
```

Offline reconstruction reported in #739:

```text
call 1 application prompt: 5,268 characters   provider input: 23,278 tokens   extra ≈ 21,961
call 2 application prompt: 7,962 characters   provider input: 23,957 tokens   extra ≈ 21,967
cache read: 576 tokens per call
```

Three later adapter-construction failures retained `UNRECONCILED` accounting without SQLite token telemetry. (#739 body; related hotfix #736.)

### 4.2 What the application prompt actually is

Provider-free reconstruction on graphiti-core 0.29.3 with a 368-byte `EpisodeType.text` body and Newsroom `GRAPHITI_EXTRACTION_INSTRUCTIONS` (297 characters):

| Internal request | `response_model` | `max_tokens` | Application prompt characters | Schema JSON characters |
|---|---|---:|---:|---:|
| `extract_nodes` / `extract_text` | `ExtractedEntities` | 16,384 | 5,452 | 896 |
| `extract_edges` / `edge` | `ExtractedEdges` | 16,384 | 7,867 | 1,747 |
| `combined_extraction.extract_nodes_and_edges` | `CombinedExtraction` | 16,384 | 15,931 | 2,144 |

**Measured** in `newsroom/tests/test_graphiti_core_0293_call_shape.py` (injected LLM; no provider). The live 5,268 / 7,962 character pair is the same order of magnitude as extract-nodes then extract-edges, including schema injection and the multilingual instruction (`client.py:223-224`). Call 2 is larger because it also serialises the entity list; a zero-entity fixture therefore under-shoots the live 7,962 figure.

**Inferred:** ~5–8 k characters of Graphiti prompt is roughly 1.3–2 k tokens, not ~23 k. The near-identical ~21,960-token remainder per call is **not** source-content size and **not** Graphiti schema bulk (schemas are 0.9–2.1 k characters).

### 4.3 What can sit in the remainder

| Component | Classification | What is known | Token count |
|---|---|---|---|
| Graphiti messages + appended JSON schema + language instruction | **Measured** | 5.3–8.0 k characters on the sample shape | Not the 21,960 |
| Irreducible Cursor system prompt | **Unresolved** | Not exposed in CLI help or print-mode JSON | unknown |
| Cursor-agent residual context (system/tool/built-in-skill mix) | **Measured** + **Documented**, exact attribution **Unresolved** | `--print` exposes tools and the CLI has no `--no-tools`. The hermetic tiny run still reported 20,103 input tokens for a 49-character prompt, and the isolated HOME materialised 22 `skills-cursor` files | **20,103 total input observed**; exact component split unknown |
| Workspace / repository / project rules / `AGENTS.md` | **Documented** + **Inferred** | CLI loads `.cursor/rules`, `AGENTS.md`, `CLAUDE.md` from the project. Graphiti cwd is an empty temp dir, so **project** rules are expected to be absent | likely ~0 from cwd; not provider-exposed |
| User rules, user MCP, user skills, plugins | **Measured** 2026-08-21 | Ambient HOME has `mcp.json`, user rules, 642 Claude skills and 43 agents skills. Hermetic HOME (Keychains symlink only) has none of those. Cursor still materialises 22 built-in `skills-cursor` files plus a `plugins/` dir into isolated `~/.cursor` | **2,281–2,284 input tokens** saved by the tested ambient-vs-hermetic boundary as a whole; no per-component split |
| Team rules | **Documented** | Team rules apply across repositories when enabled | unknown on this host |
| Built-in skills | **Documented** | Cursor ships built-in skills (`/sdk`, `/shell`, `/create-rule`, …) and “may also use some automatically” | unknown |
| Prior conversation | **Measured** | Each invocation is a new process; `--resume` / `--continue` are not passed | 0 by command shape |
| Hidden / reasoning tokens | **Documented** + **Measured** | Print mode suppresses `thinking` events. Newsroom records `reasoning_tokens: None` for Cursor. SDK: `reasoningTokens` is a subset of `outputTokens` and excluded from `totalTokens` | Cursor reasoning **unresolved**; not in the 21,960 **input** remainder |
| Prompt cache | **Measured** + **Documented** | 576 cache-read tokens/call. Composer 2.5 cache-read list price $0.20 / 1M vs $0.50 / 1M input. SDK `totalTokens` **includes** cache-read/write | cache is small here; see §7 |
| What counts against the Cursor Models pool | **Documented** | Composer 2.5 draws from the Cursor Models pool (with Grok 4.6 / 4.5). CLI, IDE, SDK and Cloud Agent runs share pricing/request pools. Input, output and cached tokens are the metered dimensions | the 23 k input/call counts; cache-read counts at the cache-read rate |

**Bound (measured 2026-08-21).** The ~21,960-token per-call delta is dominated by Cursor-agent-side context outside the application prompt; source size and Graphiti schema bulk cannot explain it. The exact split among system prompt, tool schemas, built-in skills and any other provider-side heading remains unresolved.

| Layer | Input tokens | Evidence |
|---|---:|---|
| Application prompt (nodes 5,452 chars / edges 7,867 chars) | ~1.4–2.0 k **inferred** from chars/4 | Provider-free reconstruction + live input |
| HOME-inherited user MCP / Claude / agents skills / user rules | **2,281–2,284 measured** | Ambient minus hermetic, same prompt; boundary-level difference only |
| Observed hermetic tiny-run total input | **20,103 measured** | 49-character application prompt; exact prompt-token numerator and residual component split unresolved |
| Cache-read | 576 **measured** every call, both paths | Does not remove the residual input |

Hermetic isolation is real and required. It does **not** remove the roughly 20 k observed residual input on the tested CLI path. That residual is dominant, but the calibration cannot partition it exactly. It is not a source-truncation problem.

## 5. graphiti-core 0.29.3 internal call-shape

Newsroom `add_episode` (`real.py:382-393`) uses `EpisodeType.text`, `update_communities=False`, `custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS`, and does not pass `entity_types` / `edge_types`. `GuardedGraphiti._extract_and_resolve_edges` (`real.py:160-192`) calls `extract_edges` then `guard_extracted_edges` (`edge_guard.py:9-32`), which returns an empty invalidation set and **does not** call `resolve_extracted_edges`.

`add_episode` sequence (`graphiti.py:1084-1167`) on this runtime:

| Ordinal class | Function | LLM? | When |
|---|---|---|---|
| `EXTRACT_NODES` | `extract_nodes` → `_call_extraction_llm` → `extract_text` | **Always 1** `generate_response` | Every episode, including zero entities |
| `DEDUPE_NODES` | `resolve_extracted_nodes` → `_resolve_with_llm` | 0 or 1 | Only if semantic candidates exist and similarity does not resolve them (`node_operations.py:627-689`) |
| `EXTRACT_EDGES` | `extract_edges` | **Always 1**, `max_tokens=16384` | Every episode, including zero nodes (`edge_operations.py:141-208`) |
| `DEDUPE_EDGES` / invalidation | `resolve_extracted_edges` → `dedupe_edges.resolve_edge` | **Disabled** on this runtime | Guard returns `[], []` invalidations (`edge_guard.py:30-32`) |
| `EXTRACT_ATTRIBUTES` | `_extract_entity_attributes` | 0 | `entity_types` is `None`; function returns `{}` when `entity_type is None` (`node_operations.py:790-791`) |
| `SUMMARISE_NODES` | `_extract_entity_summaries_batch` | 0 or 1 per 30 nodes | Skipped when a short summary-plus-edge-facts string exists (`<= 2 × 1000` chars). If summary is empty and episode is present, the node is sent to the LLM (`node_operations.py:854-890`) |

Embeddings remain separate OpenRouter calls (sample: 3 calls, 364 tokens).

**Why the sample had two Cursor calls.** That shape matches `EXTRACT_NODES` + `EXTRACT_EDGES` with no unresolved node-dedupe LLM and with summaries satisfied by fact-append. It is **not** an upper bound. A later corpus with similar names can add `DEDUPE_NODES`. Entities without short edge facts can add `SUMMARISE_NODES`. graphiti-core may then retry each `_generate_response` up to four times.

**Combined entity+relation extraction.** 0.29.3 **does** ship `graphiti_core.utils.maintenance.combined_extraction.extract_nodes_and_edges`: one `generate_response` with `CombinedExtraction` (“single LLM call per episode for both nodes and edges”, `combined_extraction.py:41-55`, `128-133`). Bulk wrapping exists (`bulk_utils.py:271-327`, `use_combined_extraction=True`). **`add_episode` does not call it.** `add_episode_bulk` calls `extract_nodes_and_edges_bulk` **without** that flag, so it stays on the separate two-call path (`graphiti.py:1348-1360`; `bulk_utils.py:271-292`). Using combined extraction on Newsroom therefore requires a `GuardedGraphiti` override (already the invalidation seam), not a fork of graphiti-core, and not an invented API.

Caveat: combined extraction always uses `prompt_library.extract_nodes_and_edges.extract_message`, not `extract_text`. Newsroom episodes are `EpisodeType.text`. **Do not adopt combined extraction until fixtures prove text-episode quality.** `CombinedEntity` has no `episode_indices`; node attribution is derived from facts (`combined_extraction.py:147-176`).

**Retry waste.** `LLMClient._generate_response_with_retry` is `stop_after_attempt(4)` (`client.py:120-129`). Newsroom's `_generate_response` already runs Cursor then Grok inside that one attempt; a terminal `CliResponseError` becomes `EmptyResponseError` and is retryable. Worst case per internal class is therefore **four identical Cursor+Grok chains**, not four Cursor-only calls. Grok `--max-turns 3` (`cli_client.py:164-165`) multiplies each Grok leaf. #731 must refuse the identical prompt+schema digest before the first redispatch and must not treat graphiti-core's retry as useful work.

## 6. Track B per-path qualification

Cursor CLI version **2026.08.11-e8db854**. Local interface discovery used `cursor-agent --help` and subcommand help only. Separately, the owner-approved calibration in §13 ran six bounded `--print` calls against `composer-2.5`; no other model call was made by this research.

Columns: fixed context = bootstrap/tools/skills/MCP/rules; variable = Graphiti prompt + source; total / latency / quality = live values only where measured.

| Path | Fixed context | Variable context | Total tokens | Latency | Result quality | Verdict |
|---|---|---|---|---|---|---|
| 1. Current `cursor-agent --print --mode ask` in empty temp dir | Extra ≈ 22.3 k **inferred** from measured provider input minus a coarse chars/4 prompt estimate. Ambient HOME still has mcp + 642 Claude skills + 43 agents skills | Nodes 5,452 / edges 7,867 chars **measured** | This calibration pair **51,058** (nodes 23,713+917+576; edges 24,283+993+576). Historic sample 54,287 | Wall 25.3 s / 30.9 s; API 11.5 s / 13.1 s | `extract_json_ok` true | **Baseline.** Empty cwd is not enough |
| 2. Hermetic zero-repo, zero-rule, zero-MCP, zero-plugin, no-tool / single-turn **if CLI exposes it** | CLI still has no `--no-tools`. Isolated HOME still materialises 22 built-in `skills-cursor` files and a `plugins/` dir | Same Graphiti prompts | Tiny prompt still reports **20,103 total input**. Not a proved no-tool path | Wall 46 s (tiny) | JSON ok | **Rejected as a CLI-only configuration.** Isolation ≠ no-tool |
| 3. Explicit workspace / config / env isolation | Isolated `HOME` + Keychains symlink only; no copied mcp/skills/rules. `--workspace` = empty cwd | Unchanged source | **Measured** −2,281 to −2,284 input vs ambient same prompt (~10% of the 22 k extra) | Wall *slower* (61 s / 53 s vs 25 s / 31 s); API ms similar or lower | JSON ok; no ambient canary in result | **Accepted as mandatory #730-style seam.** It is not the large saving. Fail closed if keychain/auth missing; never fall back to ambient `HOME` |
| 4. Persistent session / prompt-cache reuse (`--resume`, `--continue`, `create-chat`) | Bootstrap may become cache-read | Prior turns become extra variable context | Fresh-process cache-read already **576/call** on both paths and still bills. `--resume` **unresolved**: `create-chat` timed out at 30 s; print-mode calls 7–8 unused | — | — | **Rejected as the default Graphiti path.** Violates one-episode isolation |
| 5. Structured inference / API under the **same** subscription | SDK `tools: []` is the only documented no-tool Composer 2.5 surface identified in this research | Graphiti prompt only, if tools are empty | **Unresolved** (not in this bound; GING-010 unamended) | **Unresolved** | **Unresolved** | **Not a silent #731 switch.** Now the only credible way to attack the **20 k** floor |
| 6. Combine entity + relation in one structured call | One observed CLI residual instead of two | Combined prompt 15,931 chars **measured** | Hermetic combined **25,000** (23,674+750+576). Hermetic two-call pair **46,105**. Saving **21,105 measured** | Wall 54 s / API 9.2 s | JSON ok on the 368-byte fixture; semantic equivalence is unproved | **Preferred candidate, gated.** Do not adopt until text-episode quality and attribution fixtures pass |
| 7. Bounded multi-episode extraction with exact attribution | One bootstrap for N episodes | Concatenated `[Episode 0]…` bodies; `episode_indices` on facts | Lower bootstrap per revision **inferred if** N>1 | Lower latency **inferred** | Cross-item relations: `extract_edges` / combined facts may join entities that only co-occur because several revisions were concatenated. `GING-002` forbids mixing source revisions in one episode | **Rejected for distinct effective revisions.** Ordered chunks of **one** revision with predecessor UUIDs remain in contract |
| 8. Alternative client, same Composer 2.5, no coding-agent bootstrap | SDK `tools: []` + empty `cwd` + no `settingSources`. ACP/CLI still tool-bearing | Graphiti prompt | Should fall toward prompt size **if** tools are empty; **inferred and unresolved** | **Unresolved** | **Unresolved** | **Rejected as a silent #731 switch.** Hermetic CLI still reported ~20 k total input on the tiny prompt; amending GING-010 is an owner pin |

Undocumented flags and ambient `HOME` fallback are rejected.

## 7. Cache: quota versus latency

**Documented.** SDK `TokenUsage.totalTokens = input + output + cacheRead + cacheWrite` (reasoning excluded). Composer 2.5 list prices: input $0.50 / 1M, cache-read $0.20 / 1M, output $2.50 / 1M; no separate cache-write column. ([models and pricing](https://cursor.com/docs/models-and-pricing); [SDK token usage](https://cursor.com/docs/sdk/typescript).) Newsroom `cursor_cli_usage` uses the same four-field sum (`usage_meter.py:44-51`).

**Measured.** Historic sample: 1,152 cache-read vs 47,235 uncached input. This calibration: **576 cache-read on every one of the six print-mode calls**, ambient and hermetic, tiny prompt included.

**Inference.** Fresh process per call is a plausible explanation for weak reuse, but causal attribution is unresolved. Cache-read is **not** latency-only: it still consumes the Cursor Models pool, at a discount to uncached input. Hermetic isolation does not improve cache-read. Turning the 20 k heading into cache-read via `--resume` would still bill it. Removing the heading (no-tool) reduces quota; caching the heading mainly changes the rate.

**Unresolved.** `create-chat` under isolated HOME timed out at 30 s in this bound; `--resume` was not run. Not retried, so print-mode calls 7–8 remain unused.

## 8. Combined / batched path: attribution and contamination

| Design | Attribution | Contamination | Decision |
|---|---|---|---|
| One Graphiti episode per effective revision (current + #737) | Episode UUID is the ingest identity (`GING-002`) | None across revisions | **Keep** |
| Ordered chunks of one revision with `previous_episode_uuids` | Predecessor is explicit (`real.py:377-390`) | Same-revision continuity is intended | **Keep** |
| `extract_nodes` / `extract_edges` list-of-episodes concatenate with `episode_indices` | Facts carry indices; combined **entities** do not | Model can invent edges between co-concatenated items | **Reject** for distinct revisions until fixtures show zero cross-item edges |
| `add_episode_bulk` | Per-episode maps exist, then in-memory dedupe across the batch (`bulk_utils.py:374-411`) | Cross-episode node merge is the point of bulk; Newsroom admission still needs per-revision receipts | **Reject** as the #731 default; it also still uses separate extract calls unless `use_combined_extraction=True` |
| Combined extract on **one** episode | Single-episode indices default `[0]` | No cross-revision join | **Allow** after text-episode quality fixtures |

#739 requires either a fixture proof of attribution or a contamination reject. This research **rejects cross-revision batching** on contamination plus `GING-002`. Combined extract on a single episode is not a batch.

## 9. Versioned proposed policy (`graphiti-cursor-efficiency-v1`)

**Advisory only.** This section records a candidate implementation policy for #731; it is non-normative research evidence. Implementation requires an Accepted specification or decision, or an explicit owner instruction. Nothing in this section independently authorises runtime or product changes.

**Call classes (current GuardedGraphiti `add_episode`):**

1. `EXTRACT_NODES` — always.
2. `EXTRACT_EDGES` — always, until combined extract replaces both.
3. `DEDUPE_NODES` — only if unresolved semantic candidates exist.
4. `SUMMARISE_NODES` — only if short fact-append cannot satisfy the summary bound.
5. `GRAPHITI_CHAT_FALLBACK` — at most one Grok leaf per distinct internal request, and only after a typed Cursor `MALFORMED_OUTPUT` (not auth/config/timeout/cancel).
6. `GRAPHITI_EMBEDDING` — OpenRouter; OD-011; not this subscription.

Disabled on this runtime: `DEDUPE_EDGES` / automatic invalidation LLM; `EXTRACT_ATTRIBUTES` (no custom entity types); `update_communities`.

**Prompt / schema digest**

- One stable internal request identity per `(ingest, attempt, ordinal, prompt_digest, schema_digest, max_tokens)`.
- Digest the Graphiti messages after `generate_response` mutation (schema + language instruction included), never the full source expression in the usage row (#728).
- Refuse an identical digest inside the same attempt before dispatch, including graphiti-core’s four-attempt retry. Surface a stable non-retryable duplicate-request / call-shape error, or translate it outside graphiti-core’s retry decorator. Do **not** map the refusal back to `EmptyResponseError`, which would re-enter the four-attempt retry loop.

**Output limits**

- Retain Graphiti’s requested `max_tokens` (default 16,384; extract-edges hard-codes 16,384) on the #728 leaf.
- Cursor CLI 2026.08.11 has **no** `--max-tokens` flag (**documented**). Enforcement on the CLI path is **unresolved**. Do not pretend the discard in `cli_client.py:440` is enforcement. Keep the requested value in the receipt.
- Do not lower 16,384 as a “save tokens” cut if that truncates legitimate JSON. Emergency output ceiling is containment only.

**Fallback eligibility**

- Eligible: Cursor returned a process, stdout was not JSON-object-shaped, no auth/config/systemic class.
- Ineligible: missing binary, not logged in, timeout, cancel, HTTP/CLI non-zero without usage, `HOME`/workspace isolation failure. Open the Cursor circuit (#729 style); do not walk Grok; do not walk the next corpus unit in-cycle (#731).

**Headroom / drift**

Until live calibration, qualified extract-pair count from fake transport is **2** (or **1** if combined extract is admitted). Conditional classes are +1 each when their predicates fire. Proposed:

```text
max_distinct_internal_requests =
    maximum distinct generate_response classes observed on the checked fixture set
    + max(2, ceil(25% of that maximum))
```

A later distinct class is `CALL_SHAPE_DRIFT`: stop before dispatch, roll back PENDING effects, open the Graphiti route circuit. Do not invent 8-calls-per-ingest or 100,000-token envelopes (#731 owner correction).

**Circuit / backoff**

- No-result or systemic failure: Graphiti-route circuit, not a daily token quota.
- Emergency total-token ceiling: owner stop / containment, never the definition of useful work.
- Daily and 300-second totals: telemetry (#728), not refusal.

**Metrics**

- Context-efficiency: `application_prompt_tokens / provider_input_tokens`. Cursor CLI does not expose the provider tokenizer here, so the tiny-run numerator is unresolved. A coarse four-characters-per-token estimate gives `(49 / 4) / 20,103 ≈ 0.061%` (**inferred**, not measured); 49 characters must never be treated as 49 tokens. Retain exact prompt bytes and provider input tokens separately until a tokenizer-qualified numerator exists.
- Terminal-result yield: tokens per terminal ingest, split by proposals / zero-proposals. Never tokens per proposal as a quota.

**Batching**

- Only when every revision remains independently attributable. Default: no cross-revision batch.

## 10. Recommendation for #731

**Preferred invocation seam (stay inside GING-010):**

1. Keep `cursor-agent --print --mode ask --output-format json --sandbox enabled --trust --model composer-2.5`.
2. Apply the #730 hermetic boundary: dedicated `HOME` / XDG, empty non-git cwd, `--workspace` pointed at that cwd, **no copy of user skills/MCP/plugins/rules**. Auth on this host is the login keychain: symlink only `$HOME/Library/Keychains` into the isolated HOME. `CURSOR_API_KEY` / `CURSOR_AUTH_TOKEN` / copying `cli-config.json` did **not** authenticate. Fail closed if that keychain is missing; never fall back to ambient `HOME`. Expect **~2.3 k input saved per call**, not 22 k.
3. One primary turn (ask, no `--force` / `--yolo`). Kill the child on deadline (already cancellable). Do not treat isolation as a latency win (hermetic wall-clock was slower).
4. Stop graphiti-core’s four-attempt identical retry at the adapter.
5. At most one Grok fallback per distinct internal request; Grok `--max-turns 1` (not 3); still `grok-4.6` / `medium`.
6. Pass requested `max_tokens` into the receipt; CLI cannot enforce it today.
7. After provider-free quality fixtures, replace the extract **pair** with `combined_extraction.extract_nodes_and_edges` inside `GuardedGraphiti`, still one episode per effective revision. **This is the large measured saving** (~21 k vs a hermetic two-call pair).

**Rejected alternatives:** model/product switch; hard input truncation; `--resume` pooling; `add_episode_bulk` of unrelated revisions; CLI flags that do not exist; ambient `HOME` fallback; silent SDK swap; daily/300 s quotas as success; treating cache-read as “free”; declaring the 2-call sample an upper bound; treating hermetic CLI as having removed the 22 k heading.

**Follow-on owner pin (not #731 silent work):** hermetic CLI still shows **20,103 total input tokens** on a 49-character prompt. The only documented no-tool Composer 2.5 surface identified by this research is Cursor SDK `tools: []` under the same Ultra Cursor Models pool. That requires amending GING-010 from “cursor-agent CLI” to “Composer 2.5 on the Cursor subscription via a no-tool SDK run”.

## 11. Integration with #728, #730, #731

| Ticket | Seam this research consumes or supplies |
|---|---|
| #728 | Every Cursor, Grok and embedding leaf is a `ModelInvocationReceipt` under one ingest `ModelWorkEnvelope`. `chat_invocations` must reference those IDs. Missing/post-provider usage is `UNREPORTED` / `AMBIGUOUS` / `INVALID`, never zero. Cursor `usage` may be absent on failure (**documented** JSON failure path). |
| #730 | Graphiti reuses the CONT hermetic isolation **concept** (fresh dir, isolated `HOME`, allow-listed env, context manifest). Cursor materialises 22 `skills-cursor` files into isolated `~/.cursor`; materialisation does **not** prove that all 22 were loaded into provider context. A manifest may truthfully claim zero copied user MCP/Claude/agents skills, but not zero materialised built-in skill files. #730 owns the CONT writer path; Graphiti must not invent a second incompatible isolation protocol. |
| #731 | Implements call-shape policy, digest refusal, fallback eligibility, combined-extract optional seam, and joins receipts. Blocked on this evidence plus #728/#730/#737. |
| #737 | Coverage grain is **effective pulls**, 24 h **7.08 / h**. Do not multiply 54,287 by poll-observation identity growth (~2,092 / h). |
| #736 | Embedder must remain an `EmbedderClient`. Efficiency work must not regress that contract. |

## 12. Tokens per effective revision and per hour

Arrival rates (**measured** in #737; stable revisions / hour): 1 h 18.00; 3 h 17.67; 6 h 13.17; 12 h 9.83; **24 h 7.08**; 48 h 7.79.

Wrong grain (poll identities): 54,287 × ~2,092 / h ≈ **113.6 M tokens / h**. Do not use.

| Scenario | Tokens / effective revision | × 7.08 / h | Notes |
|---|---:|---:|---|
| Historic live sample (#739) | **54,287 measured** | **384 k** | 368-byte episode, 2 Cursor calls, 364 embedding tokens |
| Current path, this calibration pair | **51,058 measured** chat only | **361 k** | Ambient nodes+edges; no embeddings |
| Hermetic CLI, still 2 extract calls | **46,105 measured** chat only | **326 k** | −4,953 vs this ambient pair (~10%) |
| Current path, high | **~96 k inferred** | **~680 k** | 2 extract + `DEDUPE_NODES` + `SUMMARISE_NODES`, each carrying ~20–22 k extra |
| Current path, retry failure mode | up to **4 ×** a full Cursor+Grok chain | — | graphiti-core `EmptyResponseError` retry; not useful work |
| Recommended: hermetic CLI + combined extract | **25,000 measured** chat only | **177 k** | One combined call; still includes the observed ~20 k CLI-side total-input floor |
| Recommended + no-tool SDK (owner pin) | **unresolved**; extra should fall toward Graphiti prompt size | — | Only if GING-010 is amended |

Uncertainty: six print-mode calls on one 368-byte fixture; no embeddings in this bound; combined-extract quality beyond JSON-parse not scored against a gold entity list; `create-chat`/`--resume` unused; conditional LLM classes not in the sample; CLI may omit `usage` on failure; cache-write unobserved (0).

At 18 / h (1-hour window) the historic sample current path is ~977 k tokens / h — still two orders below the poll-identity fantasy, and still the wrong planning grain versus 24 h 7.08 / h.

## 13. Bounded calibration (owner-approved 2026-08-21)

Bound: at most eight Cursor print-mode calls, no Grok, no OpenRouter, chat-only. Used **6**. `create-chat` timed out at 30 s; calls 7–8 unused.

Same 368-byte fixture, `composer-2.5`, `cursor-agent --print --mode ask --output-format json --sandbox enabled --trust --workspace <cwd>`.

Hermetic auth that worked: isolated `HOME` + symlink of `Library/Keychains` only. Isolated `HOME` without that symlink stayed unauthenticated. `CURSOR_API_KEY`, `CURSOR_AUTH_TOKEN`, and copying `cli-config.json` did not authenticate `status`.

Redacted receipts: [`2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json`](2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json). Prompts are retained only as SHA-256 and byte counts.

| n | Label | Input | Output | Cache-read | Wall ms | JSON ok |
|---|---|---:|---:|---:|---:|---|
| 1 | ambient-nodes | 23,713 | 917 | 576 | 25,282 | yes |
| 2 | hermetic-nodes | 21,429 | 860 | 576 | 61,262 | yes |
| 3 | ambient-edges | 24,283 | 993 | 576 | 30,882 | yes |
| 4 | hermetic-edges | 22,002 | 662 | 576 | 52,622 | yes |
| 5 | hermetic-combined | 23,674 | 750 | 576 | 53,909 | yes |
| 6 | hermetic-tiny | 20,103 | 122 | 576 | 46,059 | yes |

SDK `tools: []` was out of scope (GING-010 unamended).

## 14. Fixture harness specification

**Checked-in (this change):** `newsroom/tests/test_graphiti_core_0293_call_shape.py`. Injected `LLMClient`; counts `_generate_response` for `extract_nodes`, `extract_edges`, combined extract, zero-proposal, schema injection, and Newsroom `max_tokens` discard. It also validates the bounded/redacted calibration receipt and the arithmetic behind the comparison table. graphiti-core 0.29.3 only. No provider I/O.

**Permanent execution:** the existing `CI / test` job first completes the ordinary `uv sync --dev --locked` compatibility gate, then runs `Sync Graphiti extra`, verifies `graphiti-core==0.29.3`, and executes this fixture plus `test_graphiti_token_meter.py`. Keeping the optional-extra steps inside the single retained CI job preserves the workflow contract while preventing `pytest.importorskip("graphiti_core")` from silently converting the research fixture into a skip.

**Required fixtures for #731 (fake transport; no live calls):**

| Fixture | Purpose |
|---|---|
| Short new entity | `EXTRACT_NODES` + `EXTRACT_EDGES`; proposals non-empty |
| Several entities and relations | Same classes; relation names must match entity list |
| Existing-node semantic resolution | Force `DEDUPE_NODES` with injected candidates |
| Valid zero-proposal | Empty lists; still 2 extract calls today; outcome terminal-success-zero-proposals |
| Long retained chunk (≤ 8,192 bytes) | Prompt grows; no silent truncation |
| Correction / new revision | Predecessor UUID; no mixed revisions |
| Malformed primary, eligible fallback | Cursor `MALFORMED_OUTPUT` then one Grok |
| Timeout / post-provider failure | Child killed; usage `UNREPORTED`; PENDING rollback |

Per-path table columns (fill measured/documented/inferred/empty):

```text
application prompt bytes/tokens
provider input/output/cache/reasoning/total tokens
number and semantic class of internal calls
latency
terminal extraction outcome
entity/relation/proposal validity
rollback/effect result
usage reporting completeness
subscription/interface constraints
```

Fake runner must record `max_tokens`, `response_model` name, prompt digest/length, and must not concatenate a second schema for Cursor beyond what `generate_response` already appended.

## 15. Unresolved limitations

- Exact split of the remaining ~20,100 observed input tokens among application-prompt tokens, system prompt, built-in tool schemas, materialised built-in skills and any other provider-side heading.
- Provider-tokenizer count for the application prompt; chars/4 is only a coarse inference.
- Whether the 22 materialised `skills-cursor` files were loaded into provider context, and if so how much each contributed.
- Whether `--mode ask` actually withholds write/shell tools in print mode despite `--print` advertising all tools.
- CLI enforcement of Graphiti `max_tokens`.
- Presence of `usage` on failed/timeout CLI runs.
- Cursor reasoning-token accounting on Composer 2.5 print mode.
- Combined-extract quality on `EpisodeType.text` beyond JSON-parse on one short fixture.
- `--resume` / `create-chat` quota vs latency (`create-chat` timed out here).
- SDK `tools: []` quality and whether it shares the Ultra Cursor Models pool identically with CLI for this account.
- Historical Graphiti chat before the #733 meter; `UNRECONCILED` construction failures.

## 16. Sources

**Newsroom**

- [#739](https://github.com/fol2/newsroom/issues/739), [#731](https://github.com/fol2/newsroom/issues/731), [#730](https://github.com/fol2/newsroom/issues/730), [#728](https://github.com/fol2/newsroom/issues/728), [#737](https://github.com/fol2/newsroom/issues/737), [#736](https://github.com/fol2/newsroom/issues/736), [#726](https://github.com/fol2/newsroom/issues/726)
- [`docs/decisions/2026-08-20-graphiti.md`](../decisions/2026-08-20-graphiti.md), [`docs/specs/editorial-automation/graphiti-corpus-ingestion-amendment.md`](../specs/editorial-automation/graphiti-corpus-ingestion-amendment.md)
- [`docs/research/2026-08-21-control-plane-token-consumption-investigation.md`](2026-08-21-control-plane-token-consumption-investigation.md)
- `newsroom/graphiti_adapter/cli_client.py`, `usage_meter.py`, `evaluation_packet.py`, `real.py`, `edge_guard.py`, `identity.py`
- `newsroom/control_plane/writer.py`
- `newsroom/tests/test_graphiti_core_0293_call_shape.py`, `newsroom/tests/test_graphiti_token_meter.py`
- [`docs/research/2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json`](2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json) — owner-approved 6-call print-mode receipts (no prompts, no secrets)

**graphiti-core 0.29.3** (site-packages)

- `graphiti_core/graphiti.py` (`add_episode`, `_extract_and_resolve_edges`, `add_episode_bulk`)
- `graphiti_core/llm_client/client.py`, `config.py` (`DEFAULT_MAX_TOKENS = 16384`)
- `graphiti_core/utils/maintenance/node_operations.py`, `edge_operations.py`, `combined_extraction.py`
- `graphiti_core/utils/bulk_utils.py`
- `graphiti_core/prompts/extract_nodes.py`, `extract_edges.py`, `extract_nodes_and_edges.py`

**Cursor first-party**

- CLI `cursor-agent --version` → `2026.08.11-e8db854`; `--help`; `mcp|plugin|models|about|create-chat|agent|status|login --help`
- [CLI using](https://cursor.com/docs/cli/using), [parameters](https://cursor.com/docs/cli/reference/parameters), [headless](https://cursor.com/docs/cli/headless), [output format](https://cursor.com/docs/cli/reference/output-format), [ACP](https://cursor.com/docs/cli/acp), [authentication](https://cursor.com/docs/cli/reference/authentication)
- [Composer 2.5](https://cursor.com/docs/models/cursor-composer-2-5), [models and pricing](https://cursor.com/docs/models-and-pricing), [team pricing](https://cursor.com/docs/account/teams/pricing)
- [TypeScript SDK](https://cursor.com/docs/sdk/typescript) (`tools: []`, `settingSources`, `TokenUsage`)
- [Rules](https://cursor.com/docs/rules), [skills](https://cursor.com/docs/skills)

**Local non-secret inventory (this host, 2026-08-21)**

- `~/.cursor/mcp.json` present; user rules / plugins / `skills-cursor` present; `~/.claude/skills` contains 642 `SKILL.md` files. No secrets, prompts or source passages copied into this file.
