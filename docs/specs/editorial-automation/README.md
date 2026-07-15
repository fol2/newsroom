# Autonomous Editorial System specification suite

**Status:** Draft  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Related architecture plan:** [`../../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../../plans/2026-07-15-001-integrated-newsroom-architecture.md)  
**Active discovery review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Canonical reference:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md)  
**Development translation:** [`../../reference/editorial/product-editorial-charter.en.md`](../../reference/editorial/product-editorial-charter.en.md)  
**Supersedes:** None

## Purpose

This suite converts selected principles from the Autonomous News Product and Editorial Charter into testable requirements for a risk-bounded autonomous news application.

The suite describes target behaviour. It does not claim that the current Discord newsroom conforms.

## Normative language

`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT` and `MAY` are normative only when the individual specification is `Accepted` or the owner explicitly authorises implementation.

The Topic 1–8 discovery specifications are Accepted. `discovery-reliability-and-operations.md` and later-topic documents remain Draft unless their metadata says otherwise.

Requirement identifiers are stable references. Existing identifiers should not be renumbered; superseded requirements remain traceable.

## Specification map

| File | Stable concern | Main charter basis |
|---|---|---|
| [`autonomy-and-publication-control.md`](autonomy-and-publication-control.md) | Autonomy boundary, decisions, agent separation and emergency control | Sections 2, 13 and 14 |
| [`discovery-coverage-contract.md`](discovery-coverage-contract.md) | Accepted Active, Best-effort, deferred and excluded coverage | Sections 3–6 |
| [`discovery-workflow.md`](discovery-workflow.md) | Accepted trigger-to-Candidate workflow and evidence handoff | Sections 2–6 and 13 |
| [`discovery-record-semantics.md`](discovery-record-semantics.md) | Accepted identities, revisions, decisions and lineage | Sections 2–6 and 13 |
| [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md) | Accepted source roles, portfolio functions, readiness and candidate paths | Sections 2–6 and 13 |
| [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md) | Accepted observation models, transitions, baselines and Agenda lifecycle | Sections 3–6 and 13 |
| [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md) | Accepted Work Items, retrieval, relationships, Hypotheses and Candidate formation | Sections 3–6 and 13 |
| [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md) | Accepted bounded search roles, query controls, provider boundaries and coverage audit | Sections 3–6 and 13 |
| [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md) | Accepted shadow isolation, Plans and Epochs, event-level review, metrics, blockers and release evidence | Sections 3–6 and 13–14 |
| [`discovery-reliability-and-operations.md`](discovery-reliability-and-operations.md) | Proposed Operational Profiles, scheduling, health, retries, quarantine, capacity, recovery and admission | Sections 3–6 and 13–14 |
| [`news-discovery.md`](news-discovery.md) | Cross-cutting discovery architecture, collection and safeguards | Sections 3–6 and 13 |
| [`story-eligibility-and-evidence.md`](story-eligibility-and-evidence.md) | Story qualification, source authority, corroboration and evidence | Sections 3–7 |
| [`content-generation-and-presentation.md`](content-generation-and-presentation.md) | Original writing, language, attribution and article contract | Sections 8 and 10 |
| [`rights-and-visuals.md`](rights-and-visuals.md) | Source access, copyright, storage and visual rights | Sections 8 and 9 |
| [`sensitive-content-and-escalation.md`](sensitive-content-and-escalation.md) | Personal information, courts, children and sensitive-risk rules | Sections 11 and 14 |
| [`publication-lifecycle-and-audit.md`](publication-lifecycle-and-audit.md) | Publication surfaces, corrections, withdrawal, archive and audit | Sections 12 and 13 |
| [`publication-engineering-and-projection-control.md`](publication-engineering-and-projection-control.md) | Authority, projections, immutable payloads, dispatch and reconciliation | Sections 12–14 |
| [`quality-evaluation-and-change-control.md`](quality-evaluation-and-change-control.md) | General versioning, evaluation, monitoring and rollback | Sections 13 and 14 |

## Cross-suite invariants

1. The system works from public, verifiable material and does not become an investigative service.
2. A Candidate needs an approved Evidence Package before a draft may become publication-eligible.
3. Models are untrusted producers, not policy authorities.
4. Generative agents never hold public publishing credentials.
5. Missing required policy, rights, evidence, validation, audit or infrastructure fails closed.
6. Volume, freshness, queue size and engagement cannot lower gates.
7. Central claims and public actions remain reconstructable, subject to lawful retention.
8. Accountability must reflect the recorded workflow honestly.
9. Discovery Signals, Leads and Candidates are not evidence.
10. A shadow result is not production authority.
11. Operational admission is scoped and versioned and remains separate from activation.

## Conformance model

A Candidate is conformant only when every applicable Accepted requirement is satisfied. Passing one module never bypasses another.

Implementation names and internal topology may differ only if required semantics and acceptance criteria are preserved.

Conflicts between Accepted requirements stop the affected path and require owner resolution.

## Relationship between specifications and plans

Plans organise accepted requirements and cannot create or change them. A plan must identify exact files and requirement IDs, exclusions, milestones, acceptance evidence, temporary gaps and rollback.

The discovery review remains topic-by-topic. Committing a Draft operational, prioritisation or locality document does not make it accepted and authorises no run.

## Suite-level acceptance criteria

Before the suite is implemented:

1. Every Accepted requirement traces to code, configuration, tests, controls or a documented procedure.
2. End-to-end tests show eligible low-risk publication and fail-closed hold and reject paths.
3. No generative agent can reach a publishing credential.
4. Every public story traces to evidence, policy, validation and decision authority.
5. Emergency stop preserves audit while preventing new public effects.
6. Model, prompt, policy, adapter and validator versions can be evaluated, monitored and rolled back.
7. Known deviations are explicit and owner-approved.

## Non-goals

This suite does not select cloud, model, agent, database, identity, billing, observability or deployment vendors except where an individual Accepted requirement says otherwise. It does not define investigative journalism, private-source collection, public comments or a general emergency-alert service.

## Open questions

Open suite questions include quantitative operational and release thresholds, retention periods, reviewer attribution, notification preferences and controlled cutover or historical import. Discovery-specific open questions remain in the active review sequence.
