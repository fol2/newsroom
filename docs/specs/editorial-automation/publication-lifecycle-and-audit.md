# Publication lifecycle and audit specification

**Status:** Accepted
**Owner:** Product owner
**Last updated:** 2026-08-17
**Accepted by owner:** 2026-08-17
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

**LIFE-002 — Immutable versions.** Every public editorial content state MUST have a version identifier and content hash. A changed headline, body, editorial metadata, governed asset or source set MUST create a new version record. A change to an external `AccessPolicyAssignment`, target attempt, acknowledgement, observation or reconciliation record MUST NOT create a new story version unless reader-visible editorial bytes also change.

**LIFE-003 — Distinct publication clocks.** The system MUST record `primary_feed_published_at`, `first_public_effect_at`, `latest_update_at` where applicable and each target attempt's `target_acknowledged_at` as distinct fields with the meanings in [`../../../CONTEXT.md`](../../../CONTEXT.md). Reconciliation MAY establish an earlier `first_public_effect_at` after the fact but MUST NOT rewrite the primary-feed ordering time or target acknowledgement history.

**LIFE-004 — Status.** The product MUST represent at least `PUBLISHED`, `CORRECTED`, `WITHDRAWN`, `REMOVED` and `SUPERSEDED` semantics, even if internal names differ.

**LIFE-005 — Target mapping.** The system MUST record every public target and target-native identifier associated with each story version.

### Feed, filtering and product presentation

**LIFE-010 — Feed order.** The initial product's main feed MUST show published stories in reverse order of `primary_feed_published_at`.

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

**LIFE-023 — Publication-bundle binding.** A notification MUST use an exact validated notification `SurfacePayload` included in the authorised `PublicationBundle` for the same evidence package and story version. A target adapter MUST NOT generate or rewrite notification copy at dispatch time.

**LIFE-024 — Correction propagation.** The correction process MUST apply correction notification consistently:

- The system MUST dispatch a correction notification Surface Payload when (a) a previously dispatched notification Surface Payload contained the materially wrong claim and this action is a `LIFE-051` material correction, or (b) a previously notified story is withdrawn or removed. If the target cannot deliver, the system MUST record `TERMINAL_LIMITATION`; that MUST NOT count as full `LIFE-055` completion.
- The system MUST NOT dispatch a correction notification for a `LIFE-050` non-substantive correction; MUST NOT notify readers who never received the original notification; and MUST NOT treat an article or feed-card correction as a notification.
- A material new development remains a new article (`LIFE-030`), not a correction notice.
- `LIFE-023` stands: when a notification exists, it is an exact bundle Surface Payload. At launch there is no notification target (see Launch controlled surfaces); these MUST classes are unused until one is admitted.

### Developments and related stories

**LIFE-030 — Material development.** A new article MUST be created for a newly confirmed decision, rule, deadline, official finding, charge, judgment, measurable change or substantive incident outcome. At launch, a material development MUST create a new article with related-story linkage. It MUST NOT rewrite the original article into a timestamped live page.

**LIFE-031 — No continuous rewrite by default.** The original article MUST NOT be silently rewritten to absorb every later development. A live-page product revision is explicitly **Deferred**. It requires a later specification change. Fail-closed: in-place live-blog mutation is refused.

**LIFE-032 — Background restraint.** A development article MUST repeat only the background needed to understand the new fact.

**LIFE-033 — Related-story basis.** Stories MAY be linked as related only when they concern the same event, case, policy, bill or formal process. Shared keywords or broad categories are insufficient.

**LIFE-034 — Relationship provenance.** An automated related-story link MUST record the event or process identity and the evidence or deterministic rule supporting the relationship.

**LIFE-035 — Superseded policy.** An outdated policy article MUST link prominently to the later report that supersedes it and MUST carry a superseded status or equivalent reader-visible signal.

### Reader-facing metadata and accountability

**LIFE-040 — Header metadata.** The article header MUST show title, `primary_feed_published_at` labelled as the reader-facing publication time, `latest_update_at` labelled as the update time where applicable, geography, categories and the responsible publisher or automated newsroom identity. `first_public_effect_at` and target acknowledgements belong to authorised Admin and audit projections rather than the default reader header.

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

**AUDIT-001 — Candidate lineage.** The system MUST preserve applicable lineage from Source Definition and Planned Agenda Item through Discovery Signal, News Lead, event linkage, Story Candidate, `EvidencePackage`, draft, validation, `StoryVersion`, exact `SurfacePayload`, decision-free `PublicationBundle`, separate `PublicationDecision`, `TargetOperation`, attempt, acknowledgement or observation, reconciliation and later lifecycle actions. The lineage MUST NOT imply that every discovery record became evidence or a story.

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
- target-operation, attempt, acknowledgement and observation identifiers and their distinct timestamps; and
- parent decision or prior version where applicable.

**AUDIT-003 — Append-only history.** Decision history SHOULD be append-only or otherwise tamper-evident. Later correction or reviewer action MUST NOT erase the prior record.

**AUDIT-004 — Reconstructability.** Subject to rights and retention limits, an authorised operator MUST be able to reconstruct why a story was selected, what evidence supported it, which rules passed or failed and what exact package was published.

**AUDIT-005 — Audit required for publication.** Failure to persist the required audit record MUST block the public action.

**AUDIT-006 — Sensitive access.** Access to held candidates, personal data, legal-risk notes, complaints and reviewer identities MUST be restricted and logged.

**AUDIT-007 — Retention policy.** Audit, source and content records MUST follow an owner-approved **Retention Schedule** that balances provenance, rights, privacy, legal need and operational recovery.

A production Retention Schedule is an owner-approved, versioned production-policy artefact. Missing class or period fails closed: that class MUST NOT be retained; a publication-path class with no schedule entry MUST NOT be published (`AUDIT-005` remains).

A legal or privacy hold MUST suspend purge of the covered records until the hold is released by an authorised decision.

Source expression retention remains the Rights Record ceiling (see [`rights-and-visuals.md`](rights-and-visuals.md)). This specification MUST NOT restate per-source expression periods.

The Retention Schedule names the following locked classes; it does not silently replace them:

| Class | Period |
|---|---|
| Publication, correction, withdrawal, removal and reassessment decision records, plus tombstones | Permanent; no wall-clock TTL |
| Non-expressive provenance for any record that reached a public decision (source identity, URL, digest, retrieval time, Rights Record version, decision IDs, Target Attempt / Acknowledgement / Observation identities) | Permanent |
| Published Story Version, Surface Payload and Publication Bundle bytes | Retained while archived (`LIFE-064`); complete removal follows `LIFE-062` |
| Unpublished draft content bytes | 90 days, or earlier where a Rights Record requires ([`autonomy-and-publication-control.md`](autonomy-and-publication-control.md)) |
| Rejected-candidate decision records | Permanent; draft bytes follow the 90-day row |
| Unused reader leads not promoted to a News Lead or Story Candidate | 90 days |
| Complaints and error reports | Two years after closure, or while related public decision records remain, whichever is longer |

Support Case retention, cryptographic erasure, physical deletion and projection tombstones belong to [`publication-engineering-and-projection-control.md`](publication-engineering-and-projection-control.md). This specification does not define those periods.

After rights-driven deletion of source expression, audit MUST NOT claim it can reconstruct source wording (`RIGHTS-016`).

**AUDIT-008 — Export.** The system SHOULD support a machine-readable export of a story's provenance and decision history for review, complaint handling and incident investigation.

### Operational reconciliation

**AUDIT-010 — Target evidence.** A public action MUST record the target's acknowledgement or failure result as untrusted target input. Each acknowledgement or observation MUST be schema-validated and correlated to the authenticated adapter identity, target context, committed operation, exact attempt, target-native identity where available, observation time, raw-response or observed-content digest and verification result. Invalid, conflicting or unauthenticated evidence MUST be classified as ambiguous; it MUST NOT authorise publication, overwrite desired editorial state or be presented as clean reconciliation.

**AUDIT-011 — Reconciliation.** The system MUST periodically reconcile intended publication state against controlled public targets to detect missing, duplicated, stale or uncorrected content.

**AUDIT-012 — Partial failure.** A partial multi-target failure MUST be visible and retryable without duplicating successful targets.

**AUDIT-013 — Orphan detection.** A public item with no valid internal story and decision record MUST raise an operational incident.

### Launch controlled surfaces

**LIFE-075 — Launch target publication.** At launch, the product has one public Target Publication: the integrated Newsroom app-serving system. Launch Surface Payloads on that target are the article and feed card.

**LIFE-076 — Client targets.** Native iPhone, iPad and Android readers are clients of that target, not separate publication targets. Reconciliation is against the serving store.

**LIFE-077 — Non-public and refused surfaces.** Web Admin is not a public publication surface. At launch there is no reader Web client, Discord, OpenClaw, social network or other secondary external message target (ADR 0007 / ADR 0009).

**LIFE-078 — Notification target deferred.** Push notifications and `LIFE-020` as a launch Target Operation are explicitly **Deferred**, fail-closed. Launch MUST NOT create notification Target Operations. Optional geography-following notifications remain the product model but are not a launch reconciliation target. Admitting a notification target requires a later specification or policy change.

**LIFE-079 — Launch cross-surface consistency.** At launch, `LIFE-055` applies to the article, feed card and caches on the app-serving target. Notification and external-message rows apply only if those payloads were dispatched.

## Acceptance criteria

1. The app-serving article and feed-card Surface Payloads for one story version map to one story version on the single launch Target Publication.
2. A retry after one target succeeds and another fails does not duplicate the successful target.
3. A material headline correction creates a new version, visible note and cross-surface update.
4. A typo correction can be applied automatically only after meaning-preservation validation.
5. A withdrawn article remains visibly withdrawn rather than disappearing silently.
6. A later acquittal triggers reassessment of related archived coverage.
7. A submitted reader lead cannot inject instructions into the agent workflow.
8. Every public story can be reconstructed to its evidence, validators, policy version and decision actor.
9. Failure to save the audit record prevents publication.
10. Feed order and the reader-facing “Published” label use `primary_feed_published_at`; an earlier public effect found by reconciliation is preserved separately as `first_public_effect_at`, and acknowledgement time remains per target attempt.
11. A material development creates a new article, not an in-place live page.
12. Rewriting an original article into a live blog fails.
13. A `LIFE-050` typo correction does not trigger a correction notification.
14. A material correction of a never-notified story does not send a correction notification.
15. A missing Retention Schedule class or period cannot retain that class; a missing publication-path schedule entry cannot publish.
16. A launch notification Target Operation fails closed.
17. A Discord or other secondary public target is refused.

## Non-goals

This specification does not define a public comment system, recommendation engine, popularity ranking, emergency alert service or final complaints service-level agreement.

It does not prescribe the database, event log, queue or storage implementation.
