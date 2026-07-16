# Autonomous Editorial System specification suite

**Status:** Draft suite; authority is controlled by each individual file  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Active architecture review:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Topic 13 implementation Draft:** [`../../plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md`](../../plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md)  
**Canonical charter:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md)

## Purpose

Convert selected charter principles into testable requirements for a risk-bounded autonomous news application. The suite describes target behaviour and does not claim that the current Discord newsroom conforms.

`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT` and `MAY` are normative only when the individual specification is `Accepted` or the owner explicitly authorises implementation.

Topic 1–12 focused discovery and GraphRAG specifications are Accepted. Acceptance authorises no source, graph engine, extractor, embedding, model, search, shadow run, queue, spending, canary or production activation. Topic 13, cross-cutting `news-discovery.md` and ADR 0004 remain under final owner review.

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
| [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md) | **Accepted:** authority boundary, trust, ontology, proposal/admission, projection, hybrid retrieval and first POC |
| [`news-discovery.md`](news-discovery.md) | **Draft:** cross-cutting architecture pending ADR 0004 and Topic 13 |
| [`story-eligibility-and-evidence.md`](story-eligibility-and-evidence.md) | Story qualification, source authority, corroboration and evidence |
| [`content-generation-and-presentation.md`](content-generation-and-presentation.md) | Original writing, language, attribution and article contract |
| [`rights-and-visuals.md`](rights-and-visuals.md) | Source access, copyright, storage and visual rights |
| [`sensitive-content-and-escalation.md`](sensitive-content-and-escalation.md) | Personal information, courts, children and sensitive-risk rules |
| [`publication-lifecycle-and-audit.md`](publication-lifecycle-and-audit.md) | Publication surfaces, corrections, withdrawal, archive and audit |
| [`publication-engineering-and-projection-control.md`](publication-engineering-and-projection-control.md) | Authority, projections, payloads, dispatch and reconciliation |
| [`quality-evaluation-and-change-control.md`](quality-evaluation-and-change-control.md) | General versioning, evaluation, monitoring and rollback |

## Accepted architecture decisions

- [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md): relational ledger and governed objects are authority; graph, vector and full-text are rebuildable projections.
- [`../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md): the initial canonical single-host ledger uses SQLite and is delivered with the graph workstream, not as a graph-less stage.

ADR 0004 remains Proposed until the integrated Topic 13 plan is accepted or amended.

## Cross-suite invariants

1. The system works from public, verifiable material and does not become an investigative service.
2. A Candidate requires an approved Evidence Package before a draft may become publication-eligible.
3. Models and extractors are untrusted producers, not policy authorities.
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
15. Rebuildable graph projection is not permission to postpone graph-aware canonical identity, trust and event contracts.
16. Graph outage is not no prior match.
17. A plan organises Accepted requirements and cannot create or weaken them.

## Conformance model

A record or Candidate is conformant only when every applicable Accepted requirement is satisfied. Passing one module never bypasses another. Implementation names and topology may differ only where required semantics and acceptance criteria remain intact.

Conflicts between Accepted requirements stop the affected path and require owner resolution.

## Plans and implementation

The first implementation Draft is retained as a Superseded Draft because it deferred GraphRAG behind a discovery-only semantic implementation.

The current Topic 13 Draft proposes one canonical schema v1, an Accepted SQLite authority plane, governed object storage, graph ontology and projection from the first milestones, Neo4j/Graphiti qualification, hybrid retrieval, named tools and later integrated shadow. It remains a plan and authorises no implementation.

Every later code pull request must list exact specification files and requirement IDs, exclusions, acceptance evidence, temporary gaps and rollback. No runtime source, provider, model, extractor, graph engine or budget is enabled as a side effect of merging the documentation pull request.

## Suite-level acceptance criteria

Before the suite can be treated as implemented:

1. Every Accepted requirement traces to code, configuration, tests, controls or a documented procedure.
2. A fresh canonical schema supports relational authority and graph projection without semantic migration.
3. End-to-end tests demonstrate eligible low-risk publication and fail-closed hold and reject paths.
4. No generative agent can reach a publishing or graph-write credential.
5. Every public story traces to evidence, policy, validation and decision authority.
6. Emergency stop preserves audit while preventing new public effects.
7. Model, prompt, policy, adapter, ontology, graph projector and validator versions can be evaluated, monitored and rolled back.
8. Governed graph and index projections rebuild from retained authority without stochastic historical rewrite.
9. Known deviations are explicit and owner-approved.

## Non-goals

The suite does not select cloud, model, agent framework, final graph engine, billing, observability or deployment vendors except where an individual Accepted requirement says otherwise. It does not define investigative journalism, private-source collection, public comments or a general emergency-alert service.

Open questions include Topic 13 sequencing, ADR 0004, exact schema and command-service mechanisms, Neo4j and licence qualification, ontology details, retrieval thresholds, evidence-based release and operational thresholds, retention, downstream Evidence Intake, production hosting, reviewer attribution and controlled cutover.