# Graphiti corpus ingestion, temporal currency and governed drafting-context amendment

**Status:** Accepted
**Owner:** Product owner
**Last updated:** 2026-08-20
**Accepted by owner:** 2026-08-20
**Canonical language:** English
**Issue:** [#722](https://github.com/fol2/newsroom/issues/722)
**Single source of truth:** [`../../decisions/2026-08-20-graphiti.md`](../../decisions/2026-08-20-graphiti.md)
**Amends:** [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md)
**Does not rewrite:** `GRAG-*`, the core sentence of `CONT-001`, or [#707](https://github.com/fol2/newsroom/issues/707)
**Implementation authority:** Slice A only. Slice B (admitted retrieval into Hypothesis, Candidate, Evidence and drafting) remains gated.
**Supersedes:** The EVALUATION “five writes then one Graphiti extract” sequence as the target corpus schedule.

## Purpose

Lock Graphiti as a corpus-owned temporal proposal engine with exact ingest identity, versioned source time, durable entity and relation receipts, and a governed drafting-context boundary.

## Model pin

**GING-010 — Graphiti chat models.** Graphiti chat MUST use cursor-agent CLI `composer-2.5` first, then Grok Build CLI `grok-4.6` with reasoning effort `medium`. It MUST NOT use OpenRouter `openai/gpt-5-mini` for chat. Embeddings MAY remain OpenRouter `openai/text-embedding-3-large` and remain inside OD-011. CLI chat is subscription usage: it MUST be ledgered and MUST NOT be debited from OD-011.

## Requirements

**GING-001 — Corpus-owned scheduling.** Graphiti ingest MUST be driven by rights-permitted `SourceRevision` / `DiscoveryRepresentation` readiness. It MUST NOT be driven by draft count or writer completion. An EVALUATION throttle MAY cap ingest units per cycle. That throttle is not the target corpus schedule.

**GING-002 — Exact ingest identity.** Each Graphiti episode MUST bind one immutable source revision or representation. It MUST NOT mix several source revisions. Episode identity and idempotency MUST be deterministic from source identity, observation or representation digest, source timestamps, chunk digest or ordinal, Graphiti configuration semantic digest and temporal policy digest. Newsroom retains that key. graphiti-core 0.29.3 `add_episode(uuid=...)` is lookup, not create, so a never-written UUID MUST NOT be passed on first ingest.

**GING-003 — Versioned temporal mapping.** `reference_time` MUST be derived from retained source times by a versioned policy. Adapter start time MUST NOT replace source time. Missing source time MAY fall back to `observed_at` only when labelled `OBSERVED_FALLBACK`. Published, updated, asserted, observed, ledger-recorded and ingested times MUST remain distinct.

**GING-004 — Proposal-generation lifecycle.** The untrusted Graphiti graph MUST persist across episodes so the corpus can link. It MUST belong to an explicit generation that can rotate, quarantine or wipe. Attempt scratch cleanup MUST NOT delete the proposal generation. A generation MUST bind framework, model, prompt, embedding, ontology, temporal policy, generation ID and input watermark.

**GING-005 — Complete durable proposal receipt.** Before admission the system MUST retain entities, relations, source and target identities, fact text, episode and passage provenance, `reference_time`, `valid_at` / `invalid_at`, raw output digest, framework / model / prompt versions, invocation counts, token usage where the provider supplies it, and provider cost for metered calls. A disposable Neo4j workspace or a proposal count is not a receipt.

**GING-006 — Currency and coverage telemetry.** The system MUST expose the eligible source-revision denominator, ingest watermark, unresolved gap, lag, retry, dead letter, admission backlog, reserved spend and actual metered spend. Unpublished payload count MUST NOT stand for graph coverage.

**GING-007 — Governed context boundary.** Writer, Hypothesis and Candidate controllers MUST receive only ADMITTED, provenance-hydrated, trust-labelled context. Graphiti raw nodes, edges, rank and invalidations MUST NOT become publication evidence. During Slice A the CONT writer MUST remain Evidence Package-only. Internal source IDs such as `HK-04` or `RAD-02` MUST NOT become world entities or editorial relations merely because they appear in an episode prefix.

## Slice B (gated)

When Slice B is authorised, `CONT-001` permitted structured context MUST be ADMITTED, trust-labelled and provenance-hydrated, and MUST carry projection watermark and gap metadata. PROPOSED Graphiti workspace data MUST NOT enter the writer.

## Acceptance

Internal source-registry identifiers do not become world entities. Slice A proves corpus ingest identity, source `reference_time`, relation receipts and coverage telemetry without feeding Graphiti output to CONT.
