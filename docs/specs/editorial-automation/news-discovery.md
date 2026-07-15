# News discovery specification

**Status:** Draft  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Active review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Related record-semantics draft:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Related architecture plan:** [`../../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../../plans/2026-07-15-001-integrated-newsroom-architecture.md)  
**Related reference:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 3–6 and 13  
**Related proposal:** [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`; owner review pending)  
**Decision state:** The coverage boundary and end-to-end workflow are Accepted. This Draft still contains candidate source architecture, search, orchestration, change-detection and shadow requirements that remain under sequential owner review.  
**Supersedes:** None

## Purpose

Define candidate source-architecture and cross-cutting discovery controls for monitoring the accepted coverage boundary through the accepted workflow without treating discovery as evidence or spending model work merely to prove that nothing changed.

The accepted coverage contract defines what discovery is responsible for seeking. The accepted workflow defines the trigger-to-candidate lifecycle. The record-semantics Draft proposes the stable identities and lineage required by that workflow. This specification must not choose a source architecture first and then redefine coverage to match the available sources.

## Scope

This specification covers candidate source selection controls, source-native change detection, bounded search, coverage auditing and cross-cutting safeguards.

Detailed actors, transitions, queueing, triage routes, failures and evidence hand-off are defined in [`discovery-workflow.md`](discovery-workflow.md). Conceptual identities and lineage are under Topic 3 review in [`discovery-record-semantics.md`](discovery-record-semantics.md). Concrete source roles remain for Topic 4; exact change semantics for Topic 5; triage and grouping for Topic 6; search for Topic 7; and shadow evaluation for Topic 8.

It defines proposed target behaviour for the unresolved architecture topics. It does not claim that the current Brave-, RSS-, GDELT- and Gemini-based pool conforms, and it does not authorise implementation.

## Review state

The accepted coverage contract and workflow are required bases for later source, identity and operational decisions. The unresolved requirements below remain Draft proposals. In particular, direct-watch-first discovery, the Source Registry, the Planned Agenda, search-last and the smallest-source-subset approach must be reviewed through the active topic sequence before ADR 0004 may be accepted.

Topic 3 is currently under owner review through `discovery-record-semantics.md`. Topic 4 will review source roles and selection. Topic 7 will review search. Topic 8 will review shadow evaluation.

## Requirements

### Candidate source architecture

**DISC-001 — Direct-watch-first discovery.** The proposed primary production discovery boundary is an owner-approved source set aligned to the accepted coverage contract, not one recurring broad search query per beat. This requirement remains subject to ADR 0004 review.

**DISC-002 — Source purpose.** Every enabled source MUST identify the accepted coverage obligation or best-effort role it serves, geography, publisher, interface and permitted discovery use. Further implementation metadata is defined only when that source is activated.

**DISC-003 — Source-native transport.** An adapter SHOULD prefer the source's permitted structured interface, such as an API, webhook, calendar, RSS or Atom feed. Selector-based page change detection MAY fill an explicit high-value gap. General browser automation or whole-site crawling MUST NOT be the default transport.

**DISC-004 — No silent broad fallback.** A missing, invalid or empty production registry MUST fail closed. A collector MUST NOT silently replace it with built-in broad media feeds or generic search queries.

**DISC-005 — Rights before collection.** A production source definition MUST reference an owner-approved rights and permitted-use record before collection. Public availability, official status or an allowed robots path MUST NOT by itself authorise automated access, retention, model submission, quotation or display.

**DISC-006 — Planned Agenda.** Known releases, proceedings, effective dates and deadlines that fall within the accepted coverage contract SHOULD be represented independently from breaking or routine watch. A Planned Agenda Item MUST define an expected source and watch window, and a missed expected release MUST remain distinguishable from a successful check with no new item. Exact semantics remain for Topic 5.

**DISC-007 — Smallest justified launch set.** A proposed launch source set MUST be no larger than necessary to cover the accepted active obligations and approved best-effort roles. Additional sources MUST be justified by an accepted obligation, an operational resilience need or observed gap. This requirement makes no locality-completeness or detection-time commitment.

### Change-driven collection

**DISC-010 — Change before work.** Routine collection MUST determine whether a registered source emitted a new item or observable revision before creating downstream triage work. An unchanged poll MUST NOT invoke a model.

**DISC-011 — Per-source state.** Each enabled source MUST retain enough inspectable state to distinguish unchanged content, a new or revised item and a failed check. The storage representation is not defined here.

**DISC-012 — Conditional retrieval.** Where a source supports HTTP validators, collectors SHOULD send `If-None-Match` or `If-Modified-Since` and interpret valid `304 Not Modified` responses. Validators are an optimisation rather than proof of correctness; content hashes and source-specific sanity checks MUST still detect inconsistent source behaviour where applicable.

**DISC-013 — Failure semantics.** Parser failure, authentication or rights failure, transport failure, malformed content, quarantine and a successful unchanged check MUST be distinct outcomes. None may be represented as another.

**DISC-014 — Delivery semantics.** Collection MAY be at-least-once, but every downstream transition MUST be idempotent against a stable source item, revision or content identity.

**DISC-015 — Quarantine.** A source or parser that no longer satisfies its extraction contract MUST enter a visible degraded or quarantined state. Suspected layout churn MUST NOT be emitted as a substantive content change merely because a selector failed.

### Discovery states and gates

**DISC-020 — Discovery Signal.** Every adapter output that represents a candidate observable change MUST first be represented as a Discovery Signal carrying the minimum permitted source, item, time, observable-change and lineage metadata. A Discovery Signal is not a News Lead, Source Observation, verified fact or publication evidence. The lifecycle is defined in the accepted workflow, and Topic 3 defines the proposed identity contract.

**DISC-021 — Deterministic gates.** Before model work, the system MUST apply versioned deterministic checks for adapter integrity, stable identity, exact or rule-defined duplication, observable newness, time and version validity, and scope or exclusion rules that can be established without editorial inference.

**DISC-022 — Ambiguity preserves recall.** A deterministic rule MUST NOT silently reject a signal merely because materiality, cross-geography relevance, development status or another editorial judgement is ambiguous. Such a signal MUST be routed to an inspectable watch or triage outcome unless another accepted rule independently requires rejection.

**DISC-023 — News Lead.** Under the accepted workflow, a Discovery Signal becomes a News Lead only after the applicable deterministic gates pass. Promotion MUST retain lineage to the signal and gate outcome. A News Lead is eligible for triage; it is not evidence.

**DISC-024 — Story Candidate.** Under the accepted workflow, one or more News Leads become a Story Candidate only after event retrieval, triage proposal validation and deterministic candidate admission establish enough likely relevance, utility, materiality and novelty to begin evidence acquisition. This transition MUST record its input leads, route and decision basis.

**DISC-025 — Evidence boundary.** Passing discovery triage MUST NOT create a Source Observation, Governed Claim, Evidence Package or publication authority. Evidence acquisition MUST independently retrieve and govern the current permitted source material under the evidence and rights specifications.

**DISC-026 — Inspectable outcome.** Every processed signal and lead MUST retain an inspectable outcome. The accepted workflow defines semantic distinctions; Topic 10 will define final outcome and reason vocabulary.

### Model and search boundary

**DISC-030 — No model for an empty tick.** A scheduler, collector or pre-check MUST end silently when no new eligible signal exists. It MUST NOT wake a model merely to confirm that there is no work.

**DISC-031 — Bounded triage.** Model assistance MUST operate on bounded Triage Work Items rather than one unconditional model call per collected item. Prompts and outputs MUST be versioned, structured and treated as untrusted proposals. Topic 6 will decide urgent exceptions, exact batch formation and failure behaviour.

**DISC-032 — Deferred full acquisition.** Discovery SHOULD use source-supplied metadata and the minimum permitted changed fragment. Full source acquisition and evidence retention MUST be deferred until a Story Candidate enters the governed evidence workflow, except for a separately approved replay or evaluation fixture.

**DISC-033 — Search-last, not search-zero.** The current proposal is that search remains a provider-neutral, separately metered lane for roles accepted in Topic 7, such as outer-radar discovery, explicit coverage gaps and recall auditing. It MUST NOT become an unbounded generic firehose. Whether search participates in the recurring production clock remains unresolved until Topic 7.

**DISC-034 — Search triggers.** Automated search MAY be triggered only by a later accepted rule tied to an approved search role. Candidate triggers include an observed source gap, a failed selected source, a missing planned release, an editor or reader lead, or a bounded audit sample.

**DISC-035 — Enforced budget.** Every automated search provider MUST have a configured request and cost budget that the agent cannot bypass. Exhaustion MUST produce a visible bounded-search outcome rather than silently switching to an unapproved provider or weakening another gate.

**DISC-036 — Recall interpretation.** GDELT, media feeds and search indexes MUST NOT be treated as recall ground truth. Coverage evaluation MUST combine bounded comparison methods with an editor-led missed-story review and record actionable Coverage Gaps.

### Basic safeguards and validation

**DISC-040 — No scoring decision.** This specification does not define a score or numeric weights. Deterministic gates and editorial triage precede any later prioritisation design.

**DISC-041 — Origins, not volume.** The number of articles or domains covering an event MUST NOT by itself establish newsworthiness. Source-count signals MAY inform confidence only after common wires, press releases, syndication and other shared origins are deduplicated.

**DISC-042 — No discovery quota.** Discovery and triage MUST support zero News Leads and zero Story Candidates in any interval. Beat balance, publication cadence or unused capacity MUST NOT promote a weaker signal.

**DISC-050 — Shadow audit.** Any authorised shadow discovery MUST retain enough lineage to compare what each permitted path found and which relevant developments were missed. Topic 8 will define the protocol and interpretation.

**DISC-051 — Source health.** Operational checks MUST make failed or broken sources and bounded-search usage visible. Detailed service objectives are not defined here.

**DISC-052 — Shadow evaluation.** A selected source set and its change checks MUST pass an owner-approved shadow evaluation before production authority. Evaluation MUST include duplicates, unchanged content, source breakage and missed relevant developments. Committing this requirement does not authorise a shadow run.

**DISC-053 — Coverage feedback.** A relevant in-scope development found only through another permitted channel MUST create a reviewable Coverage Gap. Closing a gap SHOULD improve coverage, source selection or workflow where justified rather than create an unexamined permanent dependency on broad search.

## Acceptance criteria

1. An unchanged registered feed completes without a model call or News Lead.
2. An invalid production registry fails closed instead of activating broad default feeds.
3. A parser break is visible as a failure or quarantine and is not reported as either no news or a content change.
4. An exact duplicate collected twice creates at most one downstream semantic transition.
5. A clearly excluded entertainment item is rejected deterministically; an ambiguous public-safety effect is retained for triage.
6. A current official rule update can be considered without requiring several outlets to repeat it.
7. A search result may create a Discovery Signal or Coverage Gap but cannot enter an Evidence Package merely because search found it.
8. A missing planned release produces a distinct operational finding if Planned Agenda monitoring is later accepted.
9. Search budget exhaustion is visible and cannot be bypassed by an agent or an unapproved provider fallback.
10. A Story Candidate preserves lineage to every contributing News Lead and Discovery Signal while evidence acquisition independently establishes its Source Observations.
11. No source subset, shadow run or production implementation is authorised until the relevant identity, source-role, search and evaluation decisions are accepted.

## Non-goals

This specification does not select the concrete sources or implementation mechanisms, schedules, storage, evidence store or RAG technology.

It does not define source extraction for evidence, claim admission, drafting or publication gates except for their hand-off boundary from discovery.

## Open questions

- Will the owner accept, amend or reject the proposed record identities and lineage in `discovery-record-semantics.md`?
- Which source roles and candidate interfaces satisfy the accepted coverage obligations?
- What exact source-change and Planned Agenda semantics are required?
- What role, if any, does recurring or on-demand search play at launch?
- What shadow comparison and editorial labelling method is sufficient to justify production authority?
