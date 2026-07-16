# Autonomous Editorial System specification suite

**Status:** Draft suite; authority is controlled by each individual file  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Active discovery review:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Implementation Draft requiring revision:** [`../../plans/2026-07-16-003-discovery-implementation-and-migration.md`](../../plans/2026-07-16-003-discovery-implementation-and-migration.md)  
**Canonical charter:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md)

## Purpose

Convert selected charter principles into testable requirements for a risk-bounded autonomous news application. The suite describes target behaviour and does not claim that the current Discord newsroom conforms.

`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT` and `MAY` are normative only when the individual specification is `Accepted` or the owner explicitly authorises implementation.

Topic 1–11 focused discovery specifications are Accepted. Acceptance authorises no source, model, search, shadow run, queue, spending, canary or production activation. The governed GraphRAG Topic 12, revised implementation Topic 13, cross-cutting `news-discovery.md` and relevant ADRs remain under owner review.

Requirement identifiers are stable. Existing identifiers should not be renumbered; superseded requirements remain traceable.

## Specification map

| File | Status and stable concern |
|---|---|
| [`autonomy-and-publication-control.md`](autonomy-and-publication-control.md) | Autonomy boundary, decisions, agent separation and emergency control |
| [`discovery-coverage-contract.md`](discovery-coverage-contract.md) | **Accepted:** Active, Best-effort, deferred and excluded coverage |
| [`discovery-workflow.md`](discovery-workflow.md) | **Accepted:** trigger-to-Candidate workflow and Evidence Handoff |
| [`discovery-record-semantics.md`](discovery-record-semantics.md) | **Accepted:** identities, revisions, immutable decisions and lineage |
| [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md) | **Accepted:** source roles, portfolio functions, readiness and candidate paths |
| [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md) | **Accepted:** observation models, transitions, baselines and Planned Agenda |
| [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md) | **Accepted:** Work Items, retrieval, relationships, Hypotheses and Candidate formation |
| [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md) | **Accepted:** bounded search roles, query controls, providers and coverage audit |
| [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md) | **Accepted:** shadow isolation, Plans, Epochs, event-level review and release evidence |
| [`discovery-reliability-and-operations.md`](discovery-reliability-and-operations.md) | **Accepted:** Profiles, scheduling, health, retry, quarantine, recovery and admission |
| [`discovery-prioritisation-and-outcomes.md`](discovery-prioritisation-and-outcomes.md) | **Accepted:** decision order, canonical outcomes, reasons, ordinal lanes and scoring boundary |
| [`discovery-locality-scope-and-expansion.md`](discovery-locality-scope-and-expansion.md) | **Accepted:** locality-aware launch, Coverage Units, Event-Scoped Watch and expansion |
| [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md) | **Draft:** graph authority boundary, trust, ontology, projection, Graphiti admission, hybrid retrieval and first POC |
| [`news-discovery.md`](news-discovery.md) | **Draft:** cross-cutting architecture and safeguards pending GraphRAG and final ADR decisions |
| [`story-eligibility-and-evidence.md`](story-eligibility-and-evidence.md) | Story qualification, source authority, corroboration and evidence |
| [`content-generation-and-presentation.md`](content-generation-and-presentation.md) | Original writing, language, attribution and article contract |
| [`rights-and-visuals.md`](rights-and-visuals.md) | Source access, copyright, storage and visual rights |
| [`sensitive-content-and-escalation.md`](sensitive-content-and-escalation.md) | Personal information, courts, children and sensitive-risk rules |
| [`publication-lifecycle-and-audit.md`](publication-lifecycle-and-audit.md) | Publication surfaces, corrections, withdrawal, archive and audit |
| [`publication-engineering-and-projection-control.md`](publication-engineering-and-projection-control.md) | Authority, projections, payloads, dispatch and reconciliation |
| [`quality-evaluation-and-change-control.md`](quality-evaluation-and-change-control.md) | General versioning, evaluation, monitoring and rollback |

## Cross-suite invariants

1. The system works from public, verifiable material and does not become an investigative service.
2. A Candidate requires an approved Evidence Package before a draft may become publication-eligible.
3. Models are untrusted producers, not policy authorities.
4. Generative agents never hold public publishing credentials.
5. Missing required policy, rights, evidence, validation, audit or infrastructure fails closed.
6. Volume, freshness, queue size and engagement cannot lower gates.
7. Central claims and public actions remain reconstructable, subject to lawful retention.
8. Accountability reflects the recorded workflow honestly.
9. Discovery Signals, Leads, Event Hypotheses and Candidates are not evidence.
10. Shadow results are not production authority.
11. Operational Admission is scoped, versioned and separate from activation.
12. Outcome, reason, next action, current status and priority remain separate.
13. Locality label and Event-Scoped Local Watch create no systematic locality promise.
14. Graph, vector and full-text retrieval cannot become ungoverned editorial authority.
15. Rebuildable graph projection is not permission to postpone graph-aware canonical identity and event contracts.
16. A plan organises requirements and cannot create or weaken them.

## Conformance model

A record or Candidate is conformant only when every applicable Accepted requirement is satisfied. Passing one module never bypasses another. Implementation names and topology may differ only where the required semantics and acceptance criteria remain intact.

Conflicts between Accepted requirements stop the affected path and require owner resolution.

## Plans and implementation

The first implementation Draft proposed a side-by-side discovery v2 with an isolated discovery store but deferred GraphRAG. The owner rejected that sequencing. Topic 12 now reviews a canonical relational-plus-GraphRAG architecture; Topic 13 will rewrite the implementation plan after the graph authority, ontology, projector, extraction and retrieval boundaries are accepted.

No plan currently authorises implementation. Every later code PR must list exact specification files and requirement IDs, exclusions, acceptance evidence, temporary gaps and rollback. No runtime source, provider, model, graph engine or budget is enabled as a side effect of merging the specification PR.

## Suite-level acceptance criteria

Before the suite can be treated as implemented:

1. Every Accepted requirement traces to code, configuration, tests, controls or a documented procedure.
2. End-to-end tests demonstrate eligible low-risk publication and fail-closed hold and reject paths.
3. No generative agent can reach a publishing credential.
4. Every public story traces to evidence, policy, validation and decision authority.
5. Emergency stop preserves audit while preventing new public effects.
6. Model, prompt, policy, adapter, graph projector and validator versions can be evaluated, monitored and rolled back.
7. Known deviations are explicit and owner-approved.

## Non-goals

The suite does not select cloud, model, agent framework, final graph engine, identity, billing, observability or deployment vendors except where an individual Accepted requirement says otherwise. It does not define investigative journalism, private-source collection, public comments or a general emergency-alert service.

Open questions include the GraphRAG authority and POC decisions, revised implementation sequencing, evidence-based release and operational thresholds, retention, downstream Evidence Intake implementation, production hosting, reviewer attribution, notification preferences and controlled cutover.
