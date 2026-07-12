# Quality evaluation and change-control specification

**Status:** Draft  
**Owner:** Product owner  
**Last updated:** 2026-07-11  
**Canonical language:** English  
**Related plan:** None  
**Related reference:** [`product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 13 and 14  
**Supersedes:** None

## Purpose

Define how models, prompts, validators, policies, source adapters and publication components earn and retain production authority in an autonomous newsroom.

## Scope

This specification covers versioning, evaluation datasets, release evidence, change approval, shadow and canary operation, runtime monitoring, regression response, rollback, incident review and self-modification boundaries.

## Requirements

### Versioned production components

**QA-001 — Version identity.** Every production model, prompt, template, policy bundle, validator, source adapter, extraction component, repair rule, image component and publication controller MUST have an immutable version identifier.

**QA-002 — Run capture.** Every candidate run MUST record the exact versions of all components that materially affected evidence, content, risk or publication.

**QA-003 — No floating authority.** A mutable alias such as `latest` MAY be used operationally only when it resolves to and records an immutable version before execution.

**QA-004 — No inherited authority.** A new model, prompt, validator or adapter version MUST NOT inherit production authority merely because a previous version was approved.

**QA-005 — Policy trace.** A production policy bundle MUST identify the accepted specification versions and requirement set it implements.

### Change authority

**QA-010 — No autonomous governance change.** Runtime agents MUST NOT modify accepted specifications, production policy, source permissions, risk thresholds, validator code, evaluation thresholds or release controls.

**QA-011 — Reviewed change.** A material production change MUST have an identifiable owner, change description, affected requirements, risk assessment, evaluation result and rollback path.

**QA-012 — Material change classes.** At minimum, changes to any of the following MUST be treated as material unless an approved policy explicitly classifies them otherwise:

- foundation or fine-tuned model;
- system prompt or story prompt;
- evidence extraction or source normalisation;
- claim validator or repair logic;
- risk or hold rules;
- rights classification;
- category or geography taxonomy;
- publication package or controller;
- source adapter or source terms;
- visual generation or chart logic; and
- reader-facing article or notification template.

**QA-013 — Spec change.** When a desired implementation change alters target behaviour, the relevant specification MUST be updated or superseded rather than hiding the decision in code, a prompt or a plan.

**QA-014 — Emergency change.** An emergency production change MAY use an expedited path only if it is authorised, logged, scoped, reversible and followed by retrospective evaluation and documentation.

### Evaluation corpus

**QA-020 — Representative corpus.** The system MUST maintain versioned evaluation material representing the product's geographies, categories, languages, source types, article lengths and risk classes.

**QA-021 — Positive and negative cases.** Evaluation MUST include both publishable examples and examples that must be held or rejected.

**QA-022 — Required challenge classes.** The corpus MUST include, at minimum:

- official rule and deadline changes;
- provisional statistics;
- two-source incident corroboration;
- duplicated or syndication-dependent sources;
- anonymous allegations;
- official opinion presented alongside facts;
- arrest versus charge versus conviction;
- child and jigsaw-identification risk;
- court or jurisdiction uncertainty;
- conflicting authoritative sources;
- quote and number fidelity;
- Cantonese and Traditional Chinese terminology;
- close paraphrase and translation-copying risk;
- unlicensed image and derivative-image requests;
- factual graphic generation;
- prompt injection in retrieved source text;
- reader-lead prompt injection;
- correction, withdrawal and supersession; and
- publication-controller and audit failures.

**QA-023 — Ground truth.** Each evaluation case MUST have a reviewable expected outcome, key evidence links, disallowed errors and applicable requirement identifiers.

**QA-024 — Protected test data.** Evaluation data containing personal, copyrighted, confidential or legally restricted material MUST follow the applicable rights, privacy and access controls.

**QA-025 — Stable regression set.** A stable regression subset MUST be retained across releases so quality movement can be compared over time.

### Evaluation dimensions

**QA-030 — Evidence faithfulness.** Evaluation MUST measure unsupported claims, omitted qualifications, source-status confusion, attribution errors and evidence-package violations.

**QA-031 — Numerical and entity accuracy.** Evaluation MUST separately measure errors in names, organisations, roles, locations, dates, times, units, currencies, signs and numbers.

**QA-032 — Procedural and legal language.** Evaluation MUST test whether the output preserves legal stage, allegation status, provisional status and jurisdictional holds.

**QA-033 — Originality.** Evaluation MUST test excessive quotation, translation copying, close paraphrase and reconstruction of inaccessible source material.

**QA-034 — Language quality.** Evaluation MUST assess Hong Kong Traditional Chinese, Cantonese register, terminology consistency, readability and preservation of source meaning.

**QA-035 — Risk routing.** Evaluation MUST measure false automatic publication of held or rejected cases, false rejection of eligible cases and correctness of reason codes.

**QA-036 — Rights and visuals.** Evaluation MUST test source permissions, asset records, prohibited transformations, graphic factuality and required labels.

**QA-037 — Lifecycle correctness.** Evaluation MUST test deduplication, related-story linkage, corrections, cross-surface propagation, withdrawal and archive state.

**QA-038 — Security and integrity.** Evaluation MUST test prompt injection, tool escalation, policy tampering, package modification and direct publication attempts by generative agents.

### Release gates

**QA-040 — Release evidence.** A material change MUST NOT enter autonomous production without a retained evaluation report against the applicable requirements.

**QA-041 — Safety-critical zero tolerance.** The release gate MUST treat at least the following as safety-critical defects that block release until resolved or explicitly scoped out by accepted policy:

- direct publication capability held by a generative agent;
- automatic publication of a mandatory hold or reject case;
- fabricated central claim or quotation;
- protected-identity exposure;
- known unauthorised asset use;
- audit bypass;
- fail-open behaviour; and
- policy or credential escalation from untrusted content.

**QA-042 — Quantitative thresholds.** Numerical thresholds for non-zero-tolerance metrics MUST be defined and owner-approved before production activation. The thresholds MUST be attached to the evaluated version and product scope.

**QA-043 — Slice evaluation.** Aggregate passing results MUST NOT hide a material failure in a high-risk category, language, jurisdiction, source class or publication path. Required slices MUST be reported separately.

**QA-044 — Baseline comparison.** A release report MUST compare the candidate version with the current production baseline and explain material regressions or trade-offs.

**QA-045 — Human review.** Release evidence for changes affecting publication authority, sensitive-content rules, rights or legal-risk routing MUST receive owner or delegated specialist review.

### Shadow, canary and rollout

**QA-050 — Shadow mode.** The system SHOULD support running a candidate component against live or representative inputs without permitting it to publish.

**QA-051 — Decision comparison.** Shadow evaluation SHOULD compare candidate and production evidence selection, drafts, validator results, hold/reject reasons and publication decisions.

**QA-052 — Canary scope.** A production change SHOULD be enabled first for a bounded source, category, geography, target or traffic share where technically appropriate.

**QA-053 — Independent rollback.** The operator MUST be able to roll back a model, prompt, policy, validator, adapter or publisher version without requiring an unrelated full-system rollback.

**QA-054 — Queued work.** Candidates created under an old policy or component version MUST NOT be silently published under a new version without an explicit compatibility or revalidation rule.

### Runtime monitoring

**QA-060 — Required metrics.** Runtime monitoring MUST include, at minimum:

- candidate, auto-publish, hold and reject counts;
- outcome rates by reason, category, geography, source and version;
- unsupported-claim and repair detections;
- source extraction and evidence-gate failures;
- duplicate or conflicting publication;
- correction, withdrawal and removal rates;
- rights and sensitive-risk flags;
- audit-write and publication-controller failures;
- model, tool and provider errors; and
- reviewer queue age where holds exist.

**QA-061 — Quality signals.** Reader error reports, complaints, reviewer reversals and post-publication corrections MUST feed into quality monitoring and evaluation-case creation.

**QA-062 — Version segmentation.** Every metric and incident MUST be attributable to the relevant model, prompt, policy, validator and software versions.

**QA-063 — Alert conditions.** Owner-approved alert conditions MUST exist for safety-critical failures and material unexpected shifts in publish, hold, reject, correction or error behaviour.

**QA-064 — Automatic containment.** A safety-critical runtime signal SHOULD be able to pause the affected scope automatically, subject to a policy that avoids destructive or unaudited actions.

### Incident and rollback process

**QA-070 — Incident record.** A production quality or safety incident MUST record affected stories and targets, versions, first detection, containment, correction or withdrawal actions, root cause and follow-up work.

**QA-071 — Public-content response.** Where an incident affected public content, the lifecycle specification MUST govern correction, withdrawal, removal and reader notification.

**QA-072 — Rollback validation.** Rollback MUST restore a previously evaluated version and MUST be verified through health and publication-control checks before autonomous operation resumes.

**QA-073 — Re-entry after incident.** A failed version MUST NOT regain production authority without evidence that the root cause is addressed and the relevant evaluation has passed.

**QA-074 — Learning loop.** Confirmed incidents and material near misses MUST create or update regression cases linked to the requirements they violated.

### Reproducibility and records

**QA-080 — Evaluation reproducibility.** Evaluation reports MUST retain code or workflow version, configuration, dataset version, random or sampling controls where relevant, result artefacts and environment information sufficient for reasonable reproduction.

**QA-081 — Decision retention.** Release approval, rejection, exception and rollback decisions MUST be retained and linked to the component versions and target scope.

**QA-082 — No selective deletion.** A failed evaluation MUST NOT be deleted merely because a later run passes. Superseded results MAY be archived but must remain traceable.

**QA-083 — Public repository safety.** Evaluation artefacts committed to this public repository MUST exclude secrets, sensitive personal data, confidential legal advice and source material whose rights prohibit publication.

## Acceptance criteria

1. A new prompt version cannot enter production without an immutable version, evaluation report and rollback target.
2. A model that auto-publishes one mandatory-hold allegation fails the release gate regardless of its aggregate score.
3. Prompt injection in source text cannot change tools, policy or publication outcome in the evaluation suite.
4. Metrics can isolate correction and hold rates by policy and model version.
5. A canary can be paused and rolled back without changing unrelated components.
6. Queued candidates created under an older policy are revalidated or explicitly handled before publication.
7. A production incident creates linked corrections or withdrawals and a new regression case.
8. A failed evaluation remains available after a later successful run.
9. Runtime audit-write failure triggers containment rather than unlogged publication.
10. A generative agent's attempt to obtain publishing credentials is a release-blocking defect.

## Non-goals

This specification does not set the final numerical quality thresholds, choose an observability platform or define a deployment pipeline implementation.

It does not permit agents to optimise directly against engagement at the expense of the charter requirements.

## Open questions

- What numerical thresholds and confidence intervals are appropriate for each non-zero-tolerance metric?
- Which categories, jurisdictions and source classes require mandatory separate evaluation slices at launch?
- How much live shadow traffic is necessary before enabling a new model or policy version?
- Which runtime conditions should trigger an automatic scoped pause versus an operator alert only?
