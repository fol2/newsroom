# Graphiti corpus ingestion, temporal currency and governed drafting-context amendment

**Status:** Accepted
**Owner:** Product owner
**Last updated:** 2026-08-27
**Accepted by owner:** 2026-08-20
**Canonical language:** English
**Issue:** [#722](https://github.com/fol2/newsroom/issues/722)
**Transport amendment:** [#807](https://github.com/fol2/newsroom/issues/807) replaces the production Graphiti `cursor-agent` CLI path with the current official `cursor-sdk`.
**Compatibility-floor amendment:** [`../../decisions/2026-08-27-cursor-sdk-composer-compatibility-floor.md`](../../decisions/2026-08-27-cursor-sdk-composer-compatibility-floor.md) and [#816](https://github.com/fol2/newsroom/issues/816) supersede exact SDK/model pins for active and future execution.
**Single source of truth:** [`../../decisions/2026-08-20-graphiti.md`](../../decisions/2026-08-20-graphiti.md)
**Amends:** [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md)
**Does not rewrite:** `GRAG-*`, the core sentence of `CONT-001`, or [#707](https://github.com/fol2/newsroom/issues/707)
**Implementation authority:** Slice A only. Slice B (admitted retrieval into Hypothesis, Candidate, Evidence and drafting) remains gated.
**Supersedes:** The EVALUATION “five writes then one Graphiti extract” sequence as the target corpus schedule.
**Owner correction:** [#737](https://github.com/fol2/newsroom/issues/737) defines coverage over effective pulls, not poll observations. It corrects the [#724](https://github.com/fol2/newsroom/issues/724) closeout statement that gave every `OBSERVED_FALLBACK` observation its own timestamp-bound revision / representation identity, and supersedes [#731](https://github.com/fol2/newsroom/issues/731)’s source-revision-identity lock wherever that lock would preserve poll-observation amplification. #731 remains the separate internal-call efficiency atom and is not closed by this correction.

## Purpose

Lock Graphiti as a corpus-owned temporal proposal engine with exact ingest identity, versioned source time, durable entity and relation receipts, and a governed drafting-context boundary.

## Compatibility floor

**GING-010 — Graphiti chat models.** Graphiti chat MUST use an official stable `cursor-sdk` release at or above `1.0.29`, authenticated only by a purpose-provisioned `CURSOR_API_KEY`. The controller MUST query the catalogue once, accept only canonical numeric Composer IDs matching `composer-<major>.<minor>[.<patch>]` at or above semantic version `2.5`, and deterministically select the highest compatible candidate. It MUST reject Auto, Fast, aliases, prerelease/non-numeric identities and non-Composer models. It MUST retain the actual installed SDK version, the selected catalogue model and the actual resolved run model. A dependency lock MAY retain one exact resolved SDK artifact for reproducibility, but that lock MUST NOT become an upper compatibility ceiling.

The production Cursor path MUST NOT use `cursor-agent` CLI, browser login, IDE login state, Keychain credentials or an ambient Cursor home. It MUST pass no tools, MCP servers, custom tools, subagents or project/user/team/MDM/plugin setting sources, MUST use a fresh isolated run with typed stream/run/usage receipts, and MUST NOT automatically retry or fall back after a Cursor provider or network failure. A newer SDK/model MUST still pass the same provider-free supported-surface, isolation and receipt qualification; incompatible drift fails closed before dispatch.

After a typed Cursor-eligible failure, the separately governed fallback remains Grok Build CLI `grok-4.6` with reasoning effort `medium` only where an active authority explicitly permits it. #790's bounded canary keeps fallback disabled. Graphiti chat MUST NOT use OpenRouter `openai/gpt-5-mini`. Embeddings MAY remain OpenRouter `openai/text-embedding-3-large` and remain inside OD-011. Cursor SDK chat and Grok fallback chat are subscription usage: they MUST be ledgered and MUST NOT be debited from OD-011. [#746](https://github.com/fol2/newsroom/issues/746) remains a rejection of that issue's compact prompt/output experiment and old SDK surface; it is not a rejection of API-key SDK transport.

## Requirements

**GING-001 — Corpus-owned scheduling.** Graphiti ingest MUST be driven by rights-permitted `SourceRevision` / `DiscoveryRepresentation` readiness. It MUST NOT be driven by draft count or writer completion. An EVALUATION throttle MAY cap ingest units per cycle. That throttle is not the target corpus schedule.

**GING-002 — Exact ingest identity.** Each Graphiti episode MUST bind one immutable source revision or representation. It MUST NOT mix several source revisions. Episode identity and idempotency MUST be deterministic from the effective-revision identity `(source_id, item_key, revision_digest)`, chunk digest or ordinal, Graphiti configuration semantic digest and temporal policy digest. Observation time MUST NOT enter that key: a repeated observation of unchanged content MUST converge on one identity and MUST NOT create a further revision, ingest unit, coverage obligation or provider dispatch. A repeated observation MAY update or derive `last_seen`, but is never itself a `SourceRevision`. Newsroom retains that key. graphiti-core 0.29.3 `add_episode(uuid=...)` is lookup, not create, so a never-written UUID MUST NOT be passed on first ingest.

**GING-003 — Versioned temporal mapping.** `reference_time` MUST be derived from retained source times by a versioned policy. Adapter start time MUST NOT replace source time. Missing source time MAY fall back to `observed_at` only when labelled `OBSERVED_FALLBACK`. `OBSERVED_FALLBACK` governs `reference_time` only and MUST NOT enter revision, representation or episode identity. Published, updated, asserted, observed, ledger-recorded and ingested times MUST remain distinct.

**GING-004 — Proposal-generation lifecycle.** The untrusted Graphiti graph MUST persist across episodes so the corpus can link. It MUST belong to an explicit generation that can rotate, quarantine or wipe. Attempt scratch cleanup MUST NOT delete the proposal generation. A generation MUST bind framework, model, prompt, embedding, ontology, temporal policy, generation ID and input watermark.

**GING-005 — Complete durable proposal receipt.** Before admission the system MUST retain entities, relations, source and target identities, fact text, episode and passage provenance, `reference_time`, `valid_at` / `invalid_at`, raw output digest, framework / model / prompt versions, invocation counts, token usage where the provider supplies it, and provider cost for metered calls. A disposable Neo4j workspace or a proposal count is not a receipt.

**GING-006 — Currency and coverage telemetry.** The system MUST expose the eligible source-revision denominator, ingest watermark, unresolved gap, lag, retry, dead letter, admission backlog, reserved spend and actual metered spend. Unpublished payload count MUST NOT stand for graph coverage.

Three grains MUST be exposed under unambiguous names so downstream scheduling cannot confuse them: feed-snapshot count (items present in one fetched snapshot), poll-observation count (authorised fetches retained as evidence) and effective-pull count (first landings and materially new canonical revisions). Coverage, gaps, lag and watermarks MUST be computed over effective pulls. One effective pull is the first landing of a source item, or a materially new canonical source revision. Each effective revision creates one idempotent Graphiti episode and one coverage obligation. 100% coverage is measured over effective pulls, never over poll sightings; retry attempts remain attempts against one obligation, and chunk work stays separately counted under one source revision.

**GING-007 — Governed context boundary.** Writer, Hypothesis and Candidate controllers MUST receive only ADMITTED, provenance-hydrated, trust-labelled context. Graphiti raw nodes, edges, rank and invalidations MUST NOT become publication evidence. During Slice A the CONT writer MUST remain Evidence Package-only. Internal source IDs such as `HK-04` or `RAD-02` MUST NOT become world entities or editorial relations merely because they appear in an episode prefix.

## Slice B (gated)

When Slice B is authorised, `CONT-001` permitted structured context MUST be ADMITTED, trust-labelled and provenance-hydrated, and MUST carry projection watermark and gap metadata. PROPOSED Graphiti workspace data MUST NOT enter the writer.

## Acceptance

Internal source-registry identifiers do not become world entities. Slice A proves corpus ingest identity, source `reference_time`, relation receipts and coverage telemetry without feeding Graphiti output to CONT.