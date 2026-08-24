# Graphiti Cursor subscription bootstrap: productive limits without content cuts

- Role: Dated first-stage research and current-state evidence
- Status: Completed first stage; the upstream-combined recommendation is corrected by the second-stage evidence
- Owner: fol2
- Canonical language: English
- Date: 2026-08-21
- Related issue: [#739](https://github.com/fol2/newsroom/issues/739)
- Related: [#726](https://github.com/fol2/newsroom/issues/726), [#731](https://github.com/fol2/newsroom/issues/731), [#728](https://github.com/fol2/newsroom/issues/728), [#730](https://github.com/fol2/newsroom/issues/730), [#736](https://github.com/fol2/newsroom/issues/736), [#737](https://github.com/fol2/newsroom/issues/737)
- Second-stage correction and experiment plan: [`2026-08-21-graphiti-token-effectiveness-second-stage.md`](2026-08-21-graphiti-token-effectiveness-second-stage.md)
- Redacted live receipts: [`2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json`](2026-08-21-graphiti-cursor-subscription-bootstrap-calibration.json)
- Cursor Agent CLI: `2026.08.11-e8db854`
- graphiti-core: `0.29.3`

This note is non-normative research evidence for #731. It records the owner-approved six-call cursor-agent calibration and the first-stage decomposition. No further live call, credential, spend, publication or production change is authorised by this note.

## 1. Research question

How can Graphiti preserve the pinned Cursor subscription / `composer-2.5` product contract while removing avoidable agent context, repeated schema work and retry waste, so that tokens contribute to a terminal governed extraction result?

The optimisation must not:

- truncate an admitted retained source chunk;
- omit legitimate facts merely to meet a token number;
- weaken entity, relation, temporal, evidence or rollback contracts;
- require a proposal quota; or
- call low usage successful when extraction quality fails.

A valid zero-proposal extraction remains a useful terminal result.

## 2. Evidence labels

| Label | Meaning |
|---|---|
| **Measured** | Observed in the retained live calibration, the earlier metered episode, or a provider-free executable fixture |
| **Documented** | First-party Cursor documentation, local CLI help, graphiti-core 0.29.3 source, or an Accepted Newsroom contract |
| **Inferred** | Derived from measured/documented values but not directly provider-reported |
| **Unresolved** | Requires an authorised live call or unavailable provider internals |

## 3. Baseline incident sample

One fully metered successful Graphiti episode used:

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

Offline reconstruction reported:

```text
call 1 application prompt: 5,268 characters
call 1 provider input:     23,278 tokens
estimated extra context:   ~21,961 tokens

call 2 application prompt: 7,962 characters
call 2 provider input:     23,957 tokens
estimated extra context:   ~21,967 tokens
```

Three later adapter-construction failures retained `UNRECONCILED` accounting without complete SQLite token telemetry. The 54,287-token episode is a baseline sample, not a whole-system upper bound.

## 4. Current invocation anatomy

The Graphiti primary route dispatches:

```text
cursor-agent --print --mode ask --output-format json \
  --sandbox enabled --trust --model composer-2.5 <prompt>
```

| Aspect | Current behaviour | Evidence class |
|---|---|---|
| Working directory | Fresh temporary directory | Measured from Newsroom source |
| `HOME` / environment | Ambient unless deliberately isolated | Measured from Newsroom source |
| Prior conversation | None; no resume/continue flag | Measured command shape |
| Tools | CLI has no supported `--no-tools` flag | Documented CLI surface |
| Graphiti `max_tokens` | Received by adapter but not enforceable on this CLI | Measured source + documented CLI surface |
| Cursor schema | Appended to the application prompt by graphiti-core | Measured provider-free fixture |
| Fallback | Cursor then Grok; historical Grok leaf allowed three turns | Measured Newsroom source |
| Retry above adapter | Up to four attempts for retry-class exceptions | Documented graphiti-core 0.29.3 source |
| Cursor usage | Input/output/cache fields on successful JSON output | Measured; failure-path completeness unresolved |
| Episode chunk limit | 8,192 bytes | Measured Newsroom source |

## 5. Application prompt versus provider input

Provider-free reconstruction with the same 368-byte text fixture produced:

| Internal request | Response model | Requested output | Prompt characters | Schema characters |
|---|---|---:|---:|---:|
| nodes | `ExtractedEntities` | 16,384 | 5,452 | 896 |
| edges | `ExtractedEdges` | 16,384 | 7,867 | 1,747 |
| upstream combined initial request | `CombinedExtraction` | 16,384 | 15,931 | 2,144 |

The 5–8k-character application prompts cannot explain approximately 23k provider input tokens per call. Source size and Graphiti schema bulk are not the dominant term.

The exact residual split among provider system text, tool schemas, built-in skills and other agent heading remains unresolved.

## 6. Hermetic cursor-agent calibration

The owner approved at most eight Cursor print-mode leaves, with no Grok and no OpenRouter. Six were used.

Authentication that worked on the measured host was an isolated `HOME` with only the login keychain made available. Copying `cli-config.json` or setting the attempted auth environment variables did not authenticate the CLI route.

| n | Label | Input | Output | Cache read | Wall ms | JSON shape |
|---|---|---:|---:|---:|---:|---|
| 1 | ambient nodes | 23,713 | 917 | 576 | 25,282 | valid |
| 2 | hermetic nodes | 21,429 | 860 | 576 | 61,262 | valid |
| 3 | ambient edges | 24,283 | 993 | 576 | 30,882 | valid |
| 4 | hermetic edges | 22,002 | 662 | 576 | 52,622 | valid |
| 5 | hermetic upstream combined, zero-edge fixture | 23,674 | 750 | 576 | 53,909 | valid |
| 6 | hermetic tiny, 49 characters | 20,103 | 122 | 576 | 46,059 | valid |

Measured conclusions:

- Ambient-to-hermetic isolation saved 2,281–2,284 input tokens per like-for-like call.
- Hermetic separate nodes+edges used 46,105 chat tokens.
- The zero-edge upstream-combined sample used 25,000 chat tokens.
- The tiny hermetic prompt still reported 20,103 input tokens.

The tiny result is an observed CLI-path floor for that run. It does not prove that all 20,103 tokens are irreducible system/tool context.

A coarse four-characters-per-token estimate gives `(49 / 4) / 20,103 ≈ 0.061%` context efficiency. That percentage is inferred; 49 characters must never be treated as 49 measured prompt tokens.

## 7. graphiti-core 0.29.3 call shape

For the current Newsroom `add_episode()` path:

| Class | Ordinary count | Condition |
|---|---:|---|
| `EXTRACT_NODES` | 1 | Every episode, including zero result |
| `EXTRACT_EDGES` | 1 | Every episode, including zero nodes |
| `DEDUPE_NODES` | 0 or more | Ambiguous semantic candidates |
| `SUMMARISE_NODES` | 0 or more | Short accepted facts cannot satisfy the persisted summary bound |
| edge invalidation LLM | 0 | Disabled by the current Newsroom guard |
| attribute extraction | 0 | No custom entity types on this runtime |

Graphiti-core may retry a retry-class internal request up to four times. Because the Newsroom adapter historically contains Cursor→Grok fallback inside one internal attempt, the failure shape can multiply the same request substantially.

An unchanged prompt/schema digest must therefore be refused with a stable **non-retryable** outcome. Mapping duplicate refusal back to `EmptyResponseError` would re-enter the four-attempt loop and recreate the waste.

## 8. Correction: upstream combined is not a general one-leaf path

The first-stage live `hermetic-combined` fixture returned zero entities and zero edges. In that exact shape, upstream `extract_nodes_and_edges()` made one `CombinedExtraction` request.

The new provider-free non-zero fixture proves the realistic relation-bearing sequence:

```text
CombinedExtraction → BatchEdgeTimestamps
```

Therefore:

```text
upstream combined, zero edges:      1 chat leaf
upstream combined, non-zero edges:  2 chat leaves
```

The second leaf assigns `valid_at` / `invalid_at` after the initial response. It means the measured 25,000-token zero-edge result must not be presented as the ordinary cost of a relation-bearing revision.

The separate graphiti-core edge schema already carries `valid_at` and `invalid_at` in its primary relation object. The better general successor candidate is the Newsroom compact combined-temporal contract in #747, not unmodified upstream combined extraction.

## 9. Path qualification

| Path | Fixed-context result | Internal leaves | Quality status | Decision |
|---|---:|---:|---|---|
| Ambient CLI separate path | High; inherited user context | 2 ordinary + conditional | Existing baseline | Reject as efficient route |
| Hermetic CLI separate path | About 2.3k input saved per call | 2 ordinary + conditional | JSON-valid calibration | Mandatory containment while CLI remains pinned |
| CLI no-tool configuration | No supported CLI switch; tiny run still 20,103 input | unchanged | Not proved no-tool | Reject |
| Persistent/resumed CLI session | Cache benefit unresolved; carries prior conversation | shared state | Violates one-revision isolation | Reject as default |
| Upstream combined, zero-edge fixture | 25,000 measured chat tokens | 1 | JSON shape only | Measurement only, not general recommendation |
| Upstream combined, relation-bearing fixture | No live token measurement | 2 before other conditional work | Provider-free call shape proved | Not an efficiency successor by itself |
| Cross-revision batching | Amortises fixed context | fewer per item | Can invent cross-item relations | Reject |
| Official Cursor SDK `tools=[]` | 3,430 tiny input measured; 82.9% below CLI | one-shot text-only agent route | #746 transport useful; 4/8 historical FAIL labels, including two invalid zero expectations | Research transport only; packet `REJECT` |
| `NewsroomCombinedTemporalExtractionV1` | Live usage unmeasured | 1 per admitted chunk for zero and non-zero | #747 qualified provider-free and merged | Candidate requires live gold before adoption |

## 10. Cache is discounted usage, not token removal

Every retained print-mode calibration leaf reported 576 cache-read tokens. Cache-read still consumes the Cursor model pool at its applicable rate; it is not free and not merely a latency statistic.

Hermetic isolation did not increase cache-read in the measured set. A resumed conversation might convert some repeated heading to cache-read, but it would also add prior-turn state and violate the one-effective-revision isolation contract. That path remains rejected as the default.

## 11. Advisory efficiency controls for #731

This section is non-normative research evidence. Implementation requires an Accepted decision/specification or an explicit owner instruction.

### Stable leaf identity

Bind every internal chat request to:

```text
ingest identity
Graphiti attempt identity
internal ordinal and semantic class
post-mutation prompt digest
schema digest
requested max_tokens
provider/model/route identity
```

### Duplicate and drift control

- Refuse an identical prompt+schema digest before redispatch.
- Duplicate refusal must not map to a retry-class graphiti-core exception.
- Derive the call-shape limit from qualified fixtures plus explicit headroom.
- A new class beyond policy is `CALL_SHAPE_DRIFT` before provider dispatch.

### Fallback

- At most one fallback leaf for the same distinct request.
- Only typed malformed output may be fallback-eligible under the later accepted policy.
- Missing executable, auth/config failure, timeout, cancellation, quota refusal and systemic transport failure receive no fallback.
- Each fallback has its own receipt and usage status.

### Output limits

Retain Graphiti's requested output limit in the receipt. The measured CLI did not expose a supported max-output switch, so enforcement on that route remains unresolved. Do not lower the requested 16,384 merely to obtain a smaller token number if valid JSON may be truncated.

### Circuits

Use route-specific systemic/no-result circuits and durable backoff. Fixed UTC-day or 300-second totals remain telemetry, not a generic definition of useful work.

## 12. Corrected recommendation for #731

### While GING-010 remains cursor-agent CLI

1. Keep exact `composer-2.5` and the current single-turn print shape.
2. Apply the hermetic `HOME`/XDG/empty-workspace boundary and fail closed rather than falling back to ambient state.
3. Stop identical graphiti-core retries before redispatch.
4. Limit Grok to one separately receipted, typed eligible fallback and one turn.
5. Retain requested `max_tokens`, exact prompt/schema digests and usage uncertainty.
6. Keep one effective revision per episode; reject cross-revision batching.
7. **Do not adopt unmodified upstream combined extraction as the general efficiency route.** Its measured approximately 21k saving applies to the zero-edge fixture; a relation-bearing result dispatches `BatchEdgeTimestamps` and remains two chat leaves.

### Successor research state

- #746 is complete as retained evidence: the official Cursor Python SDK local `Agent.prompt` path materially reduced the fixed floor, but the original compact prompts failed quality and the packet recommendation is `REJECT`.
- #747 is complete and merged: the corrected provider-free `NewsroomCombinedTemporalExtractionV1` contract contains entities, facts, temporal bounds and deterministic evidence segment references in one leaf per admitted chunk. Live quality and token usage remain unmeasured.
- #748 is ready: remove deterministic corpus metadata, common node-resolution and short-summary provider work without provider calls.

The target is:

```text
1 no-tool compact combined-temporal primary leaf
+ 0 ordinary timestamp leaves
+ 0 ordinary metadata leaves
+ local common-case node resolution
+ deterministic common-case summaries
+ rare typed exceptional leaves only
```

Changing GING-010 from cursor-agent CLI to the official SDK remains an owner decision; this report does not authorise it.

## 13. Tokens per effective revision and per hour

Revision-level planning uses expected call counts, not one Bernoulli probability per conditional class:

```text
T_avg_revision ≈ Σ_class E[N_class per revision] × T̄_class
               + E[T_embedding per revision]
```

`E[N_primary]` includes expected admitted chunks per effective revision. Dedupe, summary and fallback classes may also dispatch more than once; a single `P(condition) × T_class` term would understate them.

The retained effective-revision arrival rates from #737 are:

```text
1 h: 18.00 / h
3 h: 17.67 / h
6 h: 13.17 / h
12 h: 9.83 / h
24 h: 7.08 / h
48 h: 7.79 / h
```

| Scenario | Tokens / sampled effective revision | At 7.08 / h | Limitation |
|---|---:|---:|---|
| Historic metered episode | 54,287 measured | about 384k / h | Includes 364 embedding tokens |
| Ambient separate calibration pair | 51,058 measured chat | about 361k / h | No embeddings |
| Hermetic separate calibration pair | 46,105 measured chat | about 326k / h | No embeddings |
| Current high conditional shape | about 96k inferred | about 680k / h | Extract + dedupe + summary assumptions |
| Retry failure mode | up to 4× one internal chain | unresolved | Pure waste if digest is unchanged |
| Upstream combined zero-edge sample | 25,000 measured chat | about 177k / h | Not representative of non-zero edges |
| Upstream combined non-zero result | unresolved live usage | unresolved | Provider-free proof shows 2 chat leaves |
| SDK no-tool tiny fixture | 3,878 measured total; 3,430 input | about 27k total / h | Fixed-floor observation only; semantic tiny PASS |
| SDK upstream relation + timestamp | 12,588 measured across two leaves | about 89k / h | Source-safe bounded fixture; not the corrected #747 contract |
| Original SDK compact packet | unresolved as a valid route | unresolved | 4/8 historical FAIL labels; two zero expectations invalid; recommendation `REJECT` |
| Corrected #747 combined-temporal contract | provider-free qualified; live usage unmeasured | unresolved | One leaf per admitted chunk; live gold still required |

The wrong polling grain would multiply 54,287 by approximately 2,092 observation identities per hour and produce a fictitious approximately 113.6 million tokens/hour. Coverage planning must use effective revisions, not repeated poll observations.

## 14. Provider-free fixture evidence

The retained CI Graphiti path installs and verifies `graphiti-core==0.29.3`, then runs the pinned call-shape, SDK calibration and combined-temporal fixtures. The ordinary deterministic core path separately retains token-meter arithmetic. Together they cover:

- separate node/edge call-shape fixtures;
- zero-result combined fixture;
- non-zero combined→timestamp fixture;
- schema/prompt-shape assertions;
- `max_tokens` discard evidence;
- token-meter arithmetic and calibration redaction checks; and
- the second-stage owner-gated experiment-plan assertions.

No provider call occurs in these fixtures.

Required follow-on gold fixtures include:

- one relation;
- several entities/relations;
- explicit and relative temporal bounds;
- existing-node ambiguity;
- valid zero result;
- exact 8,192-byte historical live leaf plus provider-free `MAX_EPISODE_BYTES + 50` reconstruction across every chunk;
- correction/new revision;
- same-name distinct entities;
- malformed primary; and
- timeout/post-provider failure.

## 15. Unresolved limitations

- Exact provider-tokenizer count for the application prompt.
- Exact split of the CLI residual among system text, tool schemas, built-in skills and other heading.
- Cursor usage completeness on failure/timeout paths.
- Cursor reasoning-token accounting in print mode.
- Exact no-tool SDK fixed floor and account-pool behaviour for this host.
- Compact combined-temporal semantic quality and token usage.
- Conditional dedupe/summary/fallback probabilities on the retained effective-revision distribution.
- Historical Graphiti chat before exact metering and the retained `UNRECONCILED` failures.

## 16. Sources

### Newsroom

- [#739](https://github.com/fol2/newsroom/issues/739), [#731](https://github.com/fol2/newsroom/issues/731), [#730](https://github.com/fol2/newsroom/issues/730), [#728](https://github.com/fol2/newsroom/issues/728), [#737](https://github.com/fol2/newsroom/issues/737), [#736](https://github.com/fol2/newsroom/issues/736), [#746](https://github.com/fol2/newsroom/issues/746), [#747](https://github.com/fol2/newsroom/issues/747), [#748](https://github.com/fol2/newsroom/issues/748)
- [`2026-08-21-graphiti-token-effectiveness-second-stage.md`](2026-08-21-graphiti-token-effectiveness-second-stage.md)
- [`2026-08-21-graphiti-token-effectiveness-experiment-plan.json`](2026-08-21-graphiti-token-effectiveness-experiment-plan.json)
- `newsroom/graphiti_adapter/cli_client.py`, `real.py`, `usage_meter.py`, `evaluation_packet.py`, `edge_guard.py`, `identity.py`
- `newsroom/tests/test_graphiti_core_0293_call_shape.py`
- `newsroom/tests/test_graphiti_core_0293_nonzero_combined_call_shape.py`
- `newsroom/tests/test_graphiti_token_meter.py`

### graphiti-core 0.29.3

- `graphiti_core/graphiti.py`
- `graphiti_core/llm_client/client.py`
- `graphiti_core/utils/maintenance/combined_extraction.py`
- `graphiti_core/utils/maintenance/node_operations.py`
- `graphiti_core/utils/maintenance/edge_operations.py`
- `graphiti_core/prompts/extract_nodes.py`
- `graphiti_core/prompts/extract_edges.py`
- `graphiti_core/prompts/extract_nodes_and_edges.py`

### Cursor first-party

- [CLI parameters](https://cursor.com/docs/cli/reference/parameters)
- [CLI output format](https://cursor.com/docs/cli/reference/output-format)
- [Composer 2.5 and model pricing](https://cursor.com/docs/models-and-pricing)
- [Python SDK](https://cursor.com/docs/sdk/python)
- [`cursor/sdk-bridge` manifest](https://github.com/cursor/sdk-bridge/blob/main/proto/manifest.json)
