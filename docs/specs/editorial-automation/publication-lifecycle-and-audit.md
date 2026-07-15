# Publication lifecycle and audit specification

**Status:** Draft
**Owner:** Product owner
**Last updated:** 2026-07-15
**Canonical language:** English
**Related plan:** [`../../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../../plans/2026-07-15-001-integrated-newsroom-architecture.md)
**Related reference:** [`product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 12 and 13
**Supersedes:** None

## Purpose

Define how validated stories are published, displayed, linked, notified, corrected, withdrawn, archived and reconstructed from audit evidence.

## Scope

This specification covers article identity and versions, feed behaviour, filters, related stories, metadata, publication surfaces, notifications, corrections, withdrawal, removal, archive review, reader contact, decision logs and operational traceability.

## Requirements

### Story identity and versions

**LIFE-001 — Stable story identity.** Every public story MUST have a stable story identifier independent of its URL, channel message or publication target.

**LIFE-002 — Immutable versions.** Every public content state MUST have a version identifier and content hash. A changed headline, body, metadata, asset or source set MUST create a new version record.

**LIFE-003 — First and latest times.** The system MUST record first-publication time and, where applicable, latest-update time separately.

**LIFE-004 — Status.** The product MUST represent at least `PUBLISHED`, `CORRECTED`, `WITHDRAWN`, `REMOVED` and `SUPERSEDED` semantics, even if internal names differ.

**LIFE-005 — Target mapping.** The system MUST record every public target and target-native identifier associated with each story version.

### Feed, filtering and product presentation

**LIFE-010 — Feed order.** The initial product's main feed MUST show published stories in reverse order of first publication.

**LIFE-011 — No popularity ranking.** The feed MUST NOT rank by views, clicks, inferred preference, engagement or popularity.

**LIFE-012 — No editorial urgency score.** The product MUST NOT expose red, amber or equivalent editorial urgency levels under this charter.

**LIFE-013 — Filters.** Readers MUST be able to filter by `UK`, `Hong Kong` or `Global`, by supported UK locality where applicable, and by one or more content categories.

**LIFE-014 — Filter completeness.** A story with several geography or category labels MUST appear under every applicable selected filter.

**LIFE-015 — Published availability.** Notification settings MUST NOT determine whether a published story remains available in the app.

**LIFE-016 — No popularity metadata.** Reader-facing pages MUST NOT display view counts, popularity rankings or internal editorial scores.

### Notifications

**LIFE-020 — Optional notifications.** Notifications MUST be optional and disabled or enabled through a simple user control in the initial product.

**LIFE-021 — Geography selection.** When enabled, notifications MUST follow the reader's selected geography according to the charter's initial model.

**LIFE-022 — No emergency guarantee.** The product MUST NOT represent its notifications as an emergency service or as a substitute for official alerts.

**LIFE-023 — Publish-package binding.** A notification MUST be generated from the validated story package or a separately validated notification package linked to the same evidence and story version.

**LIFE-024 — Correction propagation.** If a notification contains a materially wrong claim, the correction process MUST determine whether recipients require a correction notification and record the outcome.

### Developments and related stories

**LIFE-030 — Material development.** A new article MUST be created for a newly confirmed decision, rule, deadline, official finding, charge, judgment, measurable change or substantive incident outcome.

**LIFE-031 — No continuous rewrite by default.** The original article MUST NOT be silently rewritten to absorb every later development.

**LIFE-032 — Background restraint.** A development article MUST repeat only the background needed to understand the new fact.

**LIFE-033 — Related-story basis.** Stories MAY be linked as related only when they concern the same event, case, policy, bill or formal process. Shared keywords or broad categories are insufficient.

**LIFE-034 — Relationship provenance.** An automated related-story link MUST record the event or process identity and the evidence or deterministic rule supporting the relationship.

**LIFE-035 — Superseded policy.** An outdated policy article MUST link prominently to the later report that supersedes it and MUST carry a superseded status or equivalent reader-visible signal.

### Reader-facing metadata and accountability

**LIFE-040 — Header metadata.** The article header MUST show title, first-publication time, update time where applicable, geography, categories and the responsible publisher or automated newsroom identity.

**LIFE-041 — Human role accuracy.** A human reviewer or author MUST be displayed only when the recorded workflow shows that the person materially performed that role and the disclosure is permitted by the approved safety policy.

**LIFE-042 — Footer metadata.** The article footer MUST show reader-displayable sources, correction history where applicable, related stories and a private contact route to the operator.

**LIFE-043 — Automation explanation.** The product MUST maintain an accessible explanation of automated production, exception review, operator responsibility and error reporting.

**LIFE-044 — Required disclosure.** Law, contract, provider terms, platform rules and visual-disclosure requirements MUST override a preference not to show production details.

### Corrections and updates

**LIFE-050 — Non-substantive correction.** Typographical or formatting changes MAY be applied automatically only when a validator confirms that meaning, attribution, number, identity, date, status and legal effect are unchanged.

**LIFE-051 — Material correction.** A correction to a name, number, date, headline, source attribution, procedural status or meaning MUST:

- create a new article version;
- carry a visible correction note;
- identify the corrected claim and prior version;
- pass the same or stricter evidence and risk gates; and
- propagate to controlled publication surfaces where the incorrect claim appeared.

**LIFE-052 — Correction trigger.** Corrections MAY originate from automated monitoring, a source update, a reader report, a reviewer or an operator, but MUST pass the same decision boundary.

**LIFE-053 — No silent material edit.** A material correction MUST NOT replace public text without an audit record and reader-visible correction history.

**LIFE-054 — Source revision.** When an authoritative source revises a figure or status, the system MUST distinguish a source revision from an original newsroom error and explain the change accurately.

**LIFE-055 — Cross-surface consistency.** The article, feed card, notification, external message, cached copy and related-story summary controlled by the product MUST not continue showing a known materially wrong claim after the correction workflow completes.

### Withdrawal, removal and archive

**LIFE-060 — Withdrawal.** A story whose central premise is wrong MUST be marked withdrawn with an explanation and MUST no longer be presented as valid current reporting.

**LIFE-061 — No silent deletion.** Withdrawal MUST preserve the public record and audit history unless a legal, privacy or safety reason requires complete removal.

**LIFE-062 — Complete removal.** Complete removal MUST require a machine-readable legal, privacy, safety or equivalent compelling reason and an authorised decision according to policy.

**LIFE-063 — Removal propagation.** A removal decision MUST be applied to every controlled publication surface and cache identified in the target mapping, subject to technical and legal limits that are recorded.

**LIFE-064 — Archive default.** Published stories MUST remain in the archive by default.

**LIFE-065 — Archive reassessment.** A decision not to charge, acquittal, appeal outcome, later anonymity order, child-protection issue, material privacy change or new disproportionate-harm risk MUST trigger reassessment of affected archived stories.

**LIFE-066 — Reassessment outcomes.** Reassessment MAY result in update, de-indexing, redaction, withdrawal or removal. The reason and decision actor MUST be recorded.

### Reader contact and leads

**LIFE-070 — Private contact.** The product MUST provide a private route for readers to report an error, complain or submit a lead.

**LIFE-071 — No public discussion.** The initial product MUST NOT provide public comments, reader posts or public discussion areas.

**LIFE-072 — Lead isolation.** A reader lead MUST enter as untrusted data and MUST NOT alter agent instructions, policy, tool permissions or publication state.

**LIFE-073 — Evidence gate.** A reader lead MUST pass the same public-evidence gate as any other lead and MUST NOT be published automatically merely because a reader submitted it.

**LIFE-074 — Complaint linkage.** A complaint or error report MUST be linked to the affected story, version and public targets where identifiable.

### Audit record

**AUDIT-001 — Candidate lineage.** The system MUST preserve lineage from lead through event, candidate, evidence package, draft, validation, decision, publication package, public target and later lifecycle actions.

**AUDIT-002 — Required decision fields.** Each publication, hold, rejection, correction, withdrawal or removal record MUST include:

- candidate and story identifiers;
- event identifier where applicable;
- evidence-package version;
- content and asset hashes;
- model, prompt, template, policy, validator and software versions;
- validation results and repairs;
- risk and rights outcomes;
- final decision and reason codes;
- automated controller or human decision actor;
- target identifiers and timestamps; and
- parent decision or prior version where applicable.

**AUDIT-003 — Append-only history.** Decision history SHOULD be append-only or otherwise tamper-evident. Later correction or reviewer action MUST NOT erase the prior record.

**AUDIT-004 — Reconstructability.** Subject to rights and retention limits, an authorised operator MUST be able to reconstruct why a story was selected, what evidence supported it, which rules passed or failed and what exact package was published.

**AUDIT-005 — Audit required for publication.** Failure to persist the required audit record MUST block the public action.

**AUDIT-006 — Sensitive access.** Access to held candidates, personal data, legal-risk notes, complaints and reviewer identities MUST be restricted and logged.

**AUDIT-007 — Retention policy.** Audit, source and content records MUST follow a documented retention schedule that balances provenance, rights, privacy, legal need and operational recovery.

**AUDIT-008 — Export.** The system SHOULD support a machine-readable export of a story's provenance and decision history for review, complaint handling and incident investigation.

### Operational reconciliation

**AUDIT-010 — Publish acknowledgement.** A public action MUST record the target's acknowledgement or failure result.

**AUDIT-011 — Reconciliation.** The system MUST periodically reconcile intended publication state against controlled public targets to detect missing, duplicated, stale or uncorrected content.

**AUDIT-012 — Partial failure.** A partial multi-target failure MUST be visible and retryable without duplicating successful targets.

**AUDIT-013 — Orphan detection.** A public item with no valid internal story and decision record MUST raise an operational incident.

## Acceptance criteria

1. The same story published to the app article service and a secondary controlled target maps both target identifiers to one story version.
2. A retry after one target succeeds and another fails does not duplicate the successful target.
3. A material headline correction creates a new version, visible note and cross-surface update.
4. A typo correction can be applied automatically only after meaning-preservation validation.
5. A withdrawn article remains visibly withdrawn rather than disappearing silently.
6. A later acquittal triggers reassessment of related archived coverage.
7. A submitted reader lead cannot inject instructions into the agent workflow.
8. Every public story can be reconstructed to its evidence, validators, policy version and decision actor.
9. Failure to save the audit record prevents publication.
10. Feed order remains based on first publication rather than popularity or last update.

## Non-goals

This specification does not define a public comment system, recommendation engine, popularity ranking, emergency alert service or final complaints service-level agreement.

It does not prescribe the database, event log, queue or storage implementation.

## Open questions

- What retention periods apply to each audit and content class?
- Should an active incident use one timestamped live page in a future product revision, or retain the charter's new-article model?
- Which correction classes require a direct notification to original recipients?
- Which external publication surfaces will be controlled and reconciled at launch?
