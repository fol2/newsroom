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

This suite converts selected principles from the Autonomous News Product and Editorial Charter into testable requirements for an autonomous, agentic news application.

The target is **risk-bounded autonomous publication**:

- eligible routine stories can move from discovery to publication without per-story human approval;
- models and agents operate only within versioned policy and tool boundaries;
- a separate publication controller enforces the final decision;
- unresolved high-risk cases are held for authorised review or rejected;
- the system fails closed and preserves an auditable decision trail.

The suite describes target behaviour. It does not claim that the current Discord newsroom already conforms.

## Normative language

`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT` and `MAY` are normative when a specification is `Accepted`.

Files remain review material until the owner changes their status to `Accepted` or explicitly authorises implementation. `discovery-coverage-contract.md` and `discovery-workflow.md` are currently Accepted; the other files in this suite remain Draft unless their own metadata says otherwise.

Requirement identifiers are stable references for plans, issues, tests and implementation notes. Renumbering an existing identifier should be avoided; superseded requirements should remain traceable.

## Specification map

| File | Stable concern | Main charter basis |
|---|---|---|
| [`autonomy-and-publication-control.md`](autonomy-and-publication-control.md) | Autonomy boundary, decision outcomes, agent separation, human exceptions and emergency control | Sections 2, 13 and 14 |
| [`discovery-coverage-contract.md`](discovery-coverage-contract.md) | Accepted active discovery obligations, best-effort coverage, explicit gaps, exclusions and qualitative urgency | Sections 3–6 |
| [`discovery-workflow.md`](discovery-workflow.md) | Accepted trigger-to-candidate workflow, authority boundaries, failure paths, queueing and evidence hand-off | Sections 2–6 and 13 |
| [`discovery-record-semantics.md`](discovery-record-semantics.md) | Proposed stable discovery identities, revisions, immutable versions, decisions and exact lineage | Sections 2–6 and 13 |
| [`news-discovery.md`](news-discovery.md) | Candidate source architecture, change detection, bounded search and coverage health | Sections 3–6 and 13 |
| [`story-eligibility-and-evidence.md`](story-eligibility-and-evidence.md) | Coverage, newsworthiness, sources, corroboration, analysis and claim evidence | Sections 3–7 |
| [`content-generation-and-presentation.md`](content-generation-and-presentation.md) | Original writing, language, attribution, headlines and article contract | Sections 8 and 10 |
| [`rights-and-visuals.md`](rights-and-visuals.md) | Source access, copyright, storage, asset rights and visual generation | Sections 8 and 9 |
| [`sensitive-content-and-escalation.md`](sensitive-content-and-escalation.md) | Personal information, courts, children, allegations and sensitive subject rules | Sections 11 and 14 |
| [`publication-lifecycle-and-audit.md`](publication-lifecycle-and-audit.md) | Feed behaviour, publication surfaces, corrections, withdrawal, archive and audit records | Sections 12 and 13 |
| [`publication-engineering-and-projection-control.md`](publication-engineering-and-projection-control.md) | Authoritative records, projections, immutable target payloads, dispatch, acknowledgement and reconciliation | Sections 12–14 plus adopted engineering constraints |
| [`quality-evaluation-and-change-control.md`](quality-evaluation-and-change-control.md) | Pre-release evaluation, versioning, monitoring, rollback and policy change control | Sections 13 and 14 |

## Cross-suite invariants

The following invariants apply across every module:

1. Public-source boundary: the system works from public, verifiable material and does not become an investigative service.
2. Evidence before prose: a candidate must have an approved evidence package before a publication draft can become eligible.
3. Models are untrusted producers, not policy authorities: generated output cannot approve itself or change the governing rules.
4. Separate publication authority: a generative agent never holds the credential that publishes to a public surface; credential-bearing adapters remain inside the deterministic publication-controller boundary.
5. Fail closed: missing policy, rights, evidence, validation, audit or infrastructure required for a safe decision blocks publication.
6. No quota pressure: volume, freshness, queue size and engagement targets cannot lower an evidence or risk gate.
7. Traceability: every central claim and public action must be reconstructable from retained decision evidence, subject to lawful retention limits.
8. Honest accountability: the product must not claim that a human wrote or approved content when the recorded workflow shows otherwise.
9. Discovery is not evidence: a Discovery Signal, News Lead or Story Candidate does not become publication evidence merely because it passed discovery triage.

## Conformance model

A candidate is conformant only when all applicable requirements across the suite are satisfied. Passing one module never bypasses another.

The implementation MAY use different internal names, services or state enums from those used in these documents, provided it preserves the required semantics and acceptance criteria.

Where two accepted requirements appear to conflict, the system MUST stop the affected path and surface the conflict for owner resolution. A development agent MUST NOT silently choose the less restrictive interpretation.

## Relationship between specifications and plans

Specifications and plans do not need a one-to-one relationship.

A stable behavioural boundary should remain one specification even when it takes several delivery phases to implement. Conversely, a practical implementation plan may need to change several specifications together to deliver one safe vertical slice.

Every plan targeting this suite MUST:

- list the exact specification files and requirement identifiers in scope;
- state which requirements remain out of scope;
- map milestones to observable acceptance evidence;
- record temporary gaps and compatibility behaviour;
- avoid changing a requirement merely through a task description; and
- update or supersede the relevant specification when implementation reveals a genuine product decision change.

A sensible future planning sequence may begin with publication control and audit, then evidence gates, generation, sensitive-risk routing, reader lifecycle and production rollout. That sequence is not approved by this draft and should follow a current-state gap analysis.

The discovery review is deliberately topic-by-topic. The review sequence does not authorise implementation, and committing a Draft discovery document does not make its proposed identity, source or later workflow choices accepted.

## Suite-level acceptance criteria

Before the suite can be treated as implemented:

1. Every accepted requirement has a trace to code, configuration, tests, operational control or an explicitly documented non-code procedure.
2. End-to-end tests demonstrate automatic publication of an eligible low-risk story and fail-closed handling of each mandatory hold and reject class.
3. No generative agent can reach a public publishing credential directly.
4. Every public story can be traced to its evidence package, policy version, validation results and decision actor.
5. The emergency stop prevents new public actions without destroying audit records.
6. Model, prompt, policy and validator changes can be evaluated, released and rolled back by version.
7. Known deviations from the charter are explicit and owner-approved.

## Non-goals

This suite does not select a cloud provider, model vendor, agent framework, database, identity provider, billing system or detailed deployment topology. `SERV-006` records the owner-selected Capacitor client boundary without selecting those other services.

It does not define investigative journalism, witness contact, leak handling, private-document collection, public comments or a general-purpose emergency alert service.

## Open questions

The following decisions remain open and are kept out of normative requirements unless a module states a safe default:

- the exact categories or jurisdictions that may receive narrowly scoped automatic-publication exceptions after legal review;
- quantitative release thresholds for model and prompt evaluation;
- retention periods for source material, decision logs and held candidates;
- whether reader-facing articles show an individual reviewer when a human exception review occurs;
- notification preferences beyond the charter's initial geography-based on/off model; and
- the controlled cutover date and whether any historical Discord content receives an explicitly approved one-time import.
