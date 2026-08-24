# Graphiti token effectiveness: second-stage research and local calibration plan

- Role: Dated research addendum and executable experiment plan
- Status: Retained #746 live result and merged #747 provider-free qualification; #748 ready
- Owner: fol2
- Canonical language: English
- Date: 2026-08-21
- Parent research: [#739](https://github.com/fol2/newsroom/issues/739)
- First-stage report: [`2026-08-21-graphiti-cursor-subscription-bootstrap.md`](2026-08-21-graphiti-cursor-subscription-bootstrap.md)
- Machine-readable plan: [`2026-08-21-graphiti-token-effectiveness-experiment-plan.json`](2026-08-21-graphiti-token-effectiveness-experiment-plan.json)
- Serial local research: [#746](https://github.com/fol2/newsroom/issues/746) → [#747](https://github.com/fol2/newsroom/issues/747) → [#748](https://github.com/fol2/newsroom/issues/748)

This addendum is non-normative research evidence. It corrects the first-stage interpretation of the graphiti-core combined path, retains the completed #746 calibration and incorporates the merged #747 provider-free qualification. It does not amend `GING-010`, authorise a further live call, or authorise implementation.

## 1. Decision objective

The useful planning measure is average model usage per **terminal effective source revision**, not the cheapest isolated prompt and not tokens per proposal:

```text
T_avg_revision = Σ_class E[Σ_(i=1..N_class(revision)) T_(class,i)]
               + E[T_embedding(revision)]

planning approximation:
T_avg_revision ≈ E[N_primary]   × T̄_primary
               + E[N_timestamp] × T̄_timestamp
               + E[N_dedupe]    × T̄_dedupe
               + E[N_summary]   × T̄_summary
               + E[N_fallback]  × T̄_fallback
               + E[T_embedding]

E[N_primary] includes E[chunks per effective revision].
```

Bernoulli probabilities are insufficient because one revision can dispatch more than one leaf in the same conditional class and can contain more than one admitted chunk.

A valid zero-proposal extraction remains a terminal result. A low-token malformed, incomplete or weakly evidenced extraction does not count as effective work.

The target is to remove fixed context and avoidable conditional leaves while retaining the complete admitted source chunk and every authority, evidence, temporal and rollback rule.

## 2. Supported route materially removed the CLI floor but did not qualify extraction

The first-stage CLI calibration reported 20,103 input tokens for a 49-character prompt even under the tested hermetic `HOME`. Workspace isolation removed about 2.3k input tokens per call but did not remove the dominant residual.

The official Cursor Python SDK now exposes a materially different local execution shape:

- `tools=[]` means no built-in tools are available and the model can only return text;
- omitting `local.setting_sources` avoids project, user, team, MDM and plugin setting sources; only explicitly supplied inline MCP servers may load;
- `Agent.prompt()` is a one-shot lifecycle that creates an agent, sends one prompt, waits and disposes;
- the SDK uses the same Cursor pricing and request pools as IDE and Cloud Agent runs; and
- `RunResult.usage` exposes input, output, cache-read, cache-write, total and optional reasoning tokens when reported.

At the time of this addendum, the official [`cursor/sdk-bridge`](https://github.com/cursor/sdk-bridge) manifest identified protocol `sdk.v1` and SDK version `1.0.28`. The local experiment must re-read and pin the exact installed SDK and bridge versions before dispatch.

The candidate shape is:

```python
from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

result = Agent.prompt(
    prompt,
    AgentOptions(
        model="composer-2.5",
        tools=[],
        mcp_servers={},
        agents={},
        local=LocalAgentOptions(
            cwd=fresh_empty_non_git_directory,
            custom_tools={},
            # setting_sources deliberately omitted
        ),
    ),
)
```

The experiment must use a purpose-created Cursor user or service-account API key. It must not copy the operator's ambient Cursor home, rules, skills, MCP catalogue, history or account metadata into the fixture.

### Qualification threshold

The SDK route is not accepted merely because it exists. On the predeclared tiny fixture:

```text
minimum useful reduction:  at least 50% below 20,103 input tokens
preferred reduction:       at least 75% below 20,103 input tokens
minimum-effect ceiling:    10,051 input tokens
```

This threshold qualifies a research effect size; it is not a production token quota. The route must also prove zero tool calls, zero MCP, zero subagents, zero ambient setting sources, zero prior messages and non-regressing extraction quality.

The owner-authorised #746 packet later measured 3,430 input tokens on the 49-character fixture, an 82.9% reduction from 20,103. The SDK is therefore a useful **text-only Cursor agent route** for research; `tools=[]` removes built-in tools but does not turn the SDK into raw model inference. The packet recommendation remains `REJECT`: four of eight leaves carried historical pre-v3 FAIL labels, the exact repeat changed from failure to pass while input rose by 29.7%, and the long result was invalid JSON. Provider-free re-review found that both supposed zero-result fixtures actually contain explicit entities and a relation, so those two labels are not proof of model failure. The retained binary receipts did not keep model text, so their original failure reasons cannot be reconstructed; provider-free validator v3 now emits redaction-safe strict-schema, duplicate-key, fixture-validity, model-basis, tool-observation, temporal, evidence, count and key-set diagnostics for future packets. SDK 1.0.28 `Agent.prompt` returns a `RunResult` without stream events, so the historical zero tool-call field proves the configured empty tool surface, not observed execution. The historical default-bridge workspace was also not retained. These limitations independently prevent qualification.

## 3. Correction: upstream combined extraction is conditional two-leaf work

The first-stage calibration measured one `CombinedExtraction` response with zero entities and zero edges. That result used 25,000 chat tokens and correctly showed that one CLI bootstrap can be removed relative to the separate node-plus-edge pair.

However, graphiti-core 0.29.3 does more work when the combined response contains a valid edge:

1. `extract_nodes_and_edges()` requests `CombinedExtraction`.
2. It converts the returned facts into `EntityEdge` objects.
3. If `extracted_edges` is non-empty, it immediately requests `BatchEdgeTimestamps` through `extract_timestamps_batch`.

Therefore the realistic upstream call shape is:

```text
combined zero-edge revision:      1 chat leaf
combined non-zero-edge revision:  2 chat leaves
```

The 25,000-token first-stage sample is a valid zero-edge measurement, but it is not a complete token estimate for an ordinary relation-bearing revision. The provider-free regression test added with this addendum pins the non-zero response-model sequence exactly:

```text
CombinedExtraction → BatchEdgeTimestamps
```

This second call is avoidable. The separate graphiti-core edge schema already carries `valid_at` and `invalid_at` in the primary edge object.

## 4. Preferred semantic contract: one compact combined-temporal leaf

[#747](https://github.com/fol2/newsroom/issues/747) is complete and merged through [PR #751](https://github.com/fol2/newsroom/pull/751). It provider-free qualifies the Newsroom-specific `NewsroomCombinedTemporalExtractionV1` contract to return in one primary object:

```text
entities[]
    local_id
    name
    entity_type_id
    evidence_segment_ids

facts[]
    source_local_id
    target_local_id
    relation_type
    fact
    valid_at
    invalid_at
    evidence_segment_ids
```

This contract has four efficiency advantages without cutting source content:

1. Entity and relation extraction share one model leaf.
2. Temporal bounds are returned with each fact, eliminating the ordinary timestamp leaf.
3. Facts reference local integer entity IDs instead of repeating full names.
4. Evidence references deterministic input segment IDs instead of asking the model for byte offsets or repeated long quotations.

The controller resolves segment IDs to exact retained byte ranges and rejects missing, duplicated, out-of-range or unsupported references. The model never becomes evidence authority.

One admitted chunk receives one primary prompt. One effective revision may contain multiple ordered chunks, so revision-level planning must use `E[N_primary] = E[chunks per effective revision]`. Cross-revision batching remains rejected because co-concatenated items can create false cross-item relations and weaken exact episode attribution.

## 5. Reduce conditional work after the primary leaf

[#748](https://github.com/fol2/newsroom/issues/748) owns the remaining average-token terms.

### Deterministic corpus-fact sidecar

Do not pay a model to rediscover facts already proved by governed records, including source/item/revision lineage, predecessor/chunk identity, first-seen/version markers, reference time, rights and admission identities. These may be projected as typed deterministic proposals with exact authority record IDs and digests.

The sidecar is not a second authority. The full source still receives semantic extraction, and duplicate semantic/sidecar facts are deterministically collapsed.

### Local common-case node resolution

Graphiti already performs retrieval and deterministic similarity before an LLM dedupe call. The Newsroom runtime currently injects an identity cross-encoder whose equal scores add no discriminating evidence. The follow-on research should qualify exact names/types, governed aliases, normalisation, constrained embedding similarity and optionally a pinned local reranker.

Outcomes remain:

```text
DETERMINISTIC_EXISTING_NODE
DETERMINISTIC_NEW_NODE
AMBIGUOUS_HOLD
```

Ambiguity is held, not guessed merely to avoid tokens.

### Deterministic short summaries

Graphiti already appends short accepted edge facts directly to node summaries and calls the summary model only when the resulting text is absent or too long. Newsroom should make that common-case deterministic rule explicit and keep overlong or complex cases separate. A convenience summary is not authority.

### Duplicate, fallback and circuit controls

An unchanged prompt/schema digest cannot be redispatched inside one attempt. Auth, configuration, timeout, cancellation and systemic failures are not fallback-eligible. A malformed object may receive at most one separately receipted fallback only under the later accepted policy.

## 6. Serial execution graph

The retained serial graph is now:

1. [#746](https://github.com/fol2/newsroom/issues/746) — **complete evidence / retained `REJECT`**: no-tool SDK floor reduced, original compact prompt quality failed.
2. [#747](https://github.com/fol2/newsroom/issues/747) — **complete / merged**: corrected one-leaf combined-temporal contract qualified provider-free; live quality and tokens remain unmeasured.
3. [#748](https://github.com/fol2/newsroom/issues/748) — **ready**: remove deterministic metadata, common dedupe and short-summary provider work without provider calls.

PR #745 consolidates the retained research records without collapsing their proof lanes: #746 live transport evidence, #747 provider-free contract evidence and #748 future provider-free research remain separately attributable.

## 7. Fixed local experiment packet

The machine-readable plan fixed eight SDK leaves before the completed #746 execution:

1. tiny no-tool floor;
2. upstream combined zero result;
3. upstream combined non-zero initial leaf;
4. upstream conditional batch timestamp leaf;
5. compact combined-temporal zero result;
6. compact combined-temporal non-zero result;
7. compact combined-temporal long retained chunk; and
8. one predeclared exact repeat of experiment 6.

The completed packet used all eight calls. A failed or malformed leaf consumed its slot; no adaptive call, unchanged-request retry, Grok/OpenRouter call, Neo4j mutation, backlog activation or publication occurred.

The seventh historical live leaf used the exact 8,192-byte boundary and did not prove cross-chunk reconstruction. Provider-free evidence now separately uses `MAX_EPISODE_BYTES + 50`, requires two ordered chunks and reconstructs the complete revision. No further live call is authorised by this addendum.

## 8. Expected effect

The first-stage measured baselines remain:

| Path | Chat tokens per sampled revision | Limitation |
|---|---:|---|
| Ambient separate nodes + edges | 51,058 | Ambient user context; two CLI bootstraps |
| Hermetic separate nodes + edges | 46,105 | Two CLI bootstraps remain |
| Hermetic upstream combined, zero edges | 25,000 | Does not include the conditional timestamp leaf |
| SDK no-tool tiny | 3,878 total; 3,430 input | PASS; observed floor, not a guarantee |
| SDK upstream combined, relation-bearing + timestamp | 12,588 across two leaves | Both semantic fixtures PASS; not the #747 compact contract |
| Original SDK compact packet | 4/8 historical FAIL labels; two zero expectations invalid | `REJECT`; repeat changed outcome and input |

The second-stage architecture aims for:

```text
1 no-tool compact combined-temporal primary leaf
+ 0 ordinary timestamp leaves
+ 0 ordinary metadata leaves
+ local common-case node resolution
+ deterministic common-case summaries
+ rare typed exceptional leaves only
```

The actual average cannot be claimed until the corrected #747 contract has live gold evidence and #748 measures expected conditional leaf counts over the retained effective-revision distribution. Missing usage remains uncertainty, never zero.

## 9. Sources

### Cursor first-party

- [Python SDK](https://cursor.com/docs/sdk/python)
- [Models and pricing](https://cursor.com/docs/models-and-pricing)
- [`cursor/sdk-bridge` manifest](https://github.com/cursor/sdk-bridge/blob/main/proto/manifest.json)

### graphiti-core 0.29.3

- [`combined_extraction.py`](https://github.com/getzep/graphiti/blob/v0.29.3/graphiti_core/utils/maintenance/combined_extraction.py)
- [`extract_edges.py`](https://github.com/getzep/graphiti/blob/v0.29.3/graphiti_core/prompts/extract_edges.py)
- [`extract_nodes_and_edges.py`](https://github.com/getzep/graphiti/blob/v0.29.3/graphiti_core/prompts/extract_nodes_and_edges.py)
- [`node_operations.py`](https://github.com/getzep/graphiti/blob/v0.29.3/graphiti_core/utils/maintenance/node_operations.py)

## 10. Non-effects

This addendum does not amend `GING-010`, switch the active Graphiti transport, authorise Cursor SDK use in runtime, authorise a provider call, install a local model, weaken duplicate or temporal rules, truncate source content, mutate production Neo4j, activate a backlog, publish or create production authority.
