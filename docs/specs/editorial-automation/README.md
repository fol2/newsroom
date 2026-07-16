# Autonomous Editorial System specification suite

**Status:** Draft suite; authority is controlled by each individual file  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Active architecture review:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted Topic 13 plan:** [`../../plans/2026-07-16-005-native-graphrag-production-implementation.md`](../../plans/2026-07-16-005-native-graphrag-production-implementation.md)  
**Canonical charter:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md)

## Purpose

Convert selected charter principles into testable requirements for a risk-bounded autonomous news application. The suite describes target behaviour and does not claim that the current Discord newsroom conforms.

`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT` and `MAY` are normative only when the individual specification is `Accepted` or the owner explicitly authorises implementation.

Topic 1–13 focused discovery, GraphRAG and implementation records are Accepted except for the cross-cutting `news-discovery.md` and ADR 0004, which remain under final owner review. Acceptance authorises no source, graph engine, extractor, embedding, model, search, shadow run, queue, spending, canary or production activation.

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
| [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md) | **Accepted:** authority, trust, ontology, proposal/admission, projection and hybrid retrieval |
| [`graphrag-native-production-deployment.md`](graphrag-native-production-deployment.md) | **Accepted:** initial production target, repository ownership, graph-required profiles, CI and release mechanics |
| [`news-discovery.md`](news-discovery.md) | **Draft:** cross-cutting architecture pending final ADR 0004 |
| [`story-eligibility-and-evidence.md`](story-eligibility-and-evidence.md) | Story qualification, source authority, corroboration and evidence |
| [`content-generation-and-presentation.md`](content-generation-and-presentation.md) | Original writing, language, attribution and article contract |
| [`rights-and-visuals.md`](rights-and-visuals.md) | Source access, copyright, storage and visual rights |
| [`sensitive-content-and-escalation.md`](sensitive-content-and-escalation.md) | Personal information, courts, children and sensitive-risk rules |
| [`publication-lifecycle-and-audit.md`](publication-lifecycle-and-audit.md) | Publication surfaces, corrections, withdrawal, archive and audit |
| [`publication-engineering-and-projection-control.md`](publication-engineering-and-projection-control.md) | Authority, projections, payloads, dispatch and reconciliation |
| [`quality-evaluation-and-change-control.md`](quality-evaluation-and-change-control.md) | General versioning, evaluation, monitoring and rollback |

## Architecture decisions

Accepted:

- [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md): relational ledger and governed objects are authority; graph, vector and full-text are rebuildable projections.
- [`../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md): the initial canonical single-host ledger uses SQLite and is delivered with the graph workstream, not as a graph-less stage.
- [`../../adr/0005-native-graphrag-production-deployment.md`](../../adr/0005-native-graphrag-production-deployment.md): GraphRAG is repository-native and mandatory in the first production deployment; POC and optional-plugin interpretations are rejected.

Proposed:

- [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md): final graph-aware discovery architecture, pending the explicit owner decision.

## Cross-suite invariants

1. The system works from public, verifiable material and does not become an investigative service.
2. A Candidate requires an approved Evidence Package before a draft may become publication-eligible.
3. Models and extractors are untrusted producers, not policy authorities.
4. Generative agents never hold public publishing credentials.
5. Missing required policy, rights, evidence, validation, audit or infrastructure fails closed.
6. Volume, freshness, queue size and engagement cannot lower gates.
7. Central claims and public actions remain reconstructable, subject to lawful retention.
8. Discovery Signals, Leads, Event Hypotheses and Candidates are not evidence.
9. Graph, vector and full-text retrieval cannot become ungoverned editorial authority.
10. Rebuildable graph projection is not permission to postpone GraphRAG.
11. GraphRAG is mandatory in production but remains a projection rather than authority.
12. No production, canary or complete live-shadow profile omits GraphRAG.
13. Temporary graph outage is explicit degraded operation and not a supported graph-free product.
14. Shadow results and Operational Admission are not production activation.
15. Outcome, reason, next action, current status and priority remain separate.
16. Locality label and Event-Scoped Local Watch create no systematic locality promise.
17. A plan organises Accepted requirements and cannot create, weaken or omit them.

## Plans and implementation

The two earlier Topic 13 Drafts are retained as Superseded tombstones:

- the first deferred GraphRAG behind a discovery-only semantic model;
- the second integrated GraphRAG but still described it as a POC lane.

The Accepted Topic 13 plan defines one production system with repository-native GraphRAG, a production profile that cannot omit it, graph integration in the first code increment and a graph-native first complete vertical slice.

Every later code pull request must list exact specification files and requirement IDs, exclusions, acceptance evidence, temporary gaps and rollback. No runtime source, provider, model, extractor, embedding, graph engine or budget is enabled as a side effect of merging the documentation pull request.

## Suite-level acceptance criteria

Before the suite can be treated as implemented:

1. Every Accepted requirement traces to code, configuration, tests, controls or a documented procedure.
2. A fresh canonical schema supports relational authority and graph projection without semantic migration.
3. The production deployment definition requires admitted GraphRAG components and cannot substitute fakes.
4. The first complete vertical slice traverses ledger, graph, hybrid retrieval, triage and Candidate admission.
5. End-to-end tests demonstrate eligible low-risk publication and fail-closed hold and reject paths.
6. No generative agent can reach a publishing or graph-write credential.
7. Every public story traces to evidence, policy, validation and decision authority.
8. Governed graph and index projections rebuild from retained authority without stochastic historical rewrite.
9. Model, prompt, policy, adapter, ontology, projector and validator versions can be evaluated, monitored and rolled back.
10. Known deviations are explicit and owner-approved.

## Non-goals and open questions

The suite does not select cloud, model, agent framework, final admitted graph-engine version, billing, observability or deployment vendor except where an individual Accepted decision says otherwise. It does not define investigative journalism, private-source collection, public comments or a general emergency-alert service.

Open questions include ADR 0004, exact schema and command-service mechanisms, Neo4j edition and licence qualification, ontology details, retrieval thresholds, release and operational thresholds, retention, Evidence Intake, production hosting and controlled cutover.
