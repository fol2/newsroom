# Rights and visuals specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-08-17  
**Accepted by owner:** 2026-08-17  
**Canonical language:** English  
**Related plan:** None  
**Related reference:** [`product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 8 and 9  
**Supersedes:** None

## Purpose

Define the rights, access, storage and visual controls that must pass before source material or an asset can be used by the autonomous newsroom.

## Scope

This specification covers source-access review, automated retrieval, extraction, storage, model submission, text reuse, quotations, photographs, file images, maps, charts, factual graphics, generated assets, asset metadata and prohibited visual use.

## Requirements

### Source and rights register

**RIGHTS-001 — Rights Record required.** Every source adapter, feed, publisher domain, dataset and asset provider used in production MUST have an owner-approved **Rights Record** before automated use.

**RIGHTS-002 — Minimum Rights Record fields.** A Rights Record MUST include, where applicable:

- provider and source identifier;
- access method;
- applicable terms or licence reference;
- whether automated retrieval is permitted;
- access-control and rate-limit restrictions;
- permitted use of full text, headline, snippet and metadata;
- caching, retention, deletion and repeated-extraction limits;
- embedding or indexing permission;
- whether content may be submitted to a model or external service;
- commercial reuse conditions;
- quotation and attribution requirements;
- territory or platform limits;
- review date and reviewer; and
- status: `PERMITTED`, `RESTRICTED`, `PROHIBITED` or `REVIEW_REQUIRED`.

**RIGHTS-003 — No assumption from public availability.** Public access, a search-result appearance or the absence of an obvious paywall MUST NOT be treated as permission for automated retrieval, copying, storage, model submission or commercial reuse.

**RIGHTS-004 — Unknown rights.** A source or use with unknown, expired or conflicting rights status MUST NOT enter an approved `EvidencePackage`, authorised `PublicationBundle` or dispatchable `TargetOperation`.

**RIGHTS-005 — Use-specific decision.** Permission to read or retrieve a source MUST NOT be treated as permission to store, quote, submit to a model, redistribute, display an image or create a derivative.

**RIGHTS-006 — Versioned review.** Rights Records MUST be versioned. A material change to terms, licence, access control or provider policy MUST trigger review before continued automated use.

**RIGHTS-007 — Prohibited list.** The system MUST maintain an enforceable prohibited-source and prohibited-use list independent of model judgement.

**RIGHTS-008 — Production Rights Record.** A production **Rights Record** is an owner-approved, versioned production-policy artefact stating permitted access method, use classes, destinations and retention for one Source Definition, dataset or asset provider. A Rights Review Record, First I/O Gate PASS or Qualification Evidence MUST NOT mint or substitute for a production Rights Record.

**RIGHTS-009 — Launch automated-use set.** At launch, automated retrieval, storage and model submission is limited to the ten OD-001 Source Definitions only: `UK-01`, `UK-02`, `UK-03`, `UK-05`, `UK-10`, `HK-01`, `HK-02`, `HK-04`, `RAD-01` and `RAD-02`. Each MUST have a current Rights Record before automated retrieval, storage or model submission. The Topic 4 remaining shortlist stays candidate; a missing Rights Record MUST fail closed. Brave and GDELT remain prohibited (ADR 0009). Adding a source is a Source Registry and Rights Record change, not a silent specification amendment. The Rights Records for `RAD-01` and `RAD-02` MUST permit discovery and News Lead use only: they MUST NOT permit republishing publisher body or photographs, and MUST NOT permit submitting publisher body to an image model.

### Retrieval, storage and model submission

**RIGHTS-010 — Adapter enforcement.** Source adapters MUST enforce the approved access method, rate limits, content scope and retention rules for their Rights Record.

**RIGHTS-011 — Access-control respect.** The system MUST NOT bypass paywalls, authentication, robots or technical access controls unless a documented agreement explicitly permits the method.

**RIGHTS-012 — Minimum necessary content.** Retrieval and storage SHOULD be limited to the minimum content necessary for evidence extraction, validation and lawful audit.

**RIGHTS-013 — Model destination.** Source content MUST NOT be submitted to a model, provider or other service unless the Rights Record and data-governance configuration permit that destination and retention behaviour.

**RIGHTS-014 — Retention enforcement.** Cached source text, screenshots, documents, images, embeddings and derived extracts MUST expire or be deleted according to the applicable rights and retention rule.

**RIGHTS-015 — No paywall reconstruction.** The system MUST NOT combine fragments, snippets, cached text or secondary quotations to reconstruct a paywalled article or substitute for authorised access.

**RIGHTS-016 — Audit without over-retention.** The audit design MUST preserve provenance and decision evidence without retaining more protected source expression than the approved Rights Record allows.

**RIGHTS-017 — Source expression ceiling.** The Rights Record is the hard ceiling for **source expression** (full text, screenshot, binary, embedding and derived extract). A missing retention period, content class or permitted destination MUST fail closed: that class MUST NOT be retained, and a Claim that depends on it MUST NOT be admitted.

**RIGHTS-018 — Ephemeral full-body cache.** Even when a licence is more generous, launch cache of full source body MUST be ephemeral: delete after Evidence Package admission or when the retrieval window ends. An exact cited passage MAY be retained only when the Rights Record permits that use and the passage is bound into that Evidence Package.

**RIGHTS-019 — Non-expressive provenance and draft purge.** Non-expressive provenance (source identity, URL, digest, retrieval time, Rights Record version and decision identifiers) is not source expression; its retention schedule belongs to [`publication-lifecycle-and-audit.md`](publication-lifecycle-and-audit.md). After rights-driven deletion of expression, audit MUST NOT claim it can reconstruct source wording. The 90-day draft-byte purge in [`autonomy-and-publication-control.md`](autonomy-and-publication-control.md) is an outer bound; a Rights Record MAY require earlier deletion of source expression.

### Text originality and quotation rights

**RIGHTS-020 — Facts versus expression.** The system MAY use verified facts and lawfully reusable data to write an original report, but MUST NOT copy protected wording, structure, selection, tables, charts or images merely because the underlying facts are reportable.

**RIGHTS-021 — Close paraphrase prohibited.** Translation, sentence-by-sentence substitution or close structural paraphrase of a source article MUST fail the originality and rights gate.

**RIGHTS-022 — Quotation purpose.** A direct quotation MUST have an identified editorial purpose, be no longer than necessary, carry sufficient acknowledgement and satisfy the applicable rights rule.

**RIGHTS-023 — Attribution is not permission.** Adding a source name or link MUST NOT convert an otherwise unauthorised copy or derivative into permitted use.

**RIGHTS-024 — Source link.** Source linking is required for evidence transparency where permitted, but it MUST NOT be treated as transferring checking responsibility to the reader.

### Asset record

**VIS-001 — Asset Record required.** Every public visual MUST have an **Asset Record** linked to the article package.

**VIS-002 — Minimum Asset Record fields.** An Asset Record MUST include:

- stable asset identifier and hash;
- asset type and provenance;
- creator, rights holder or licensor;
- licence or permission reference;
- permitted platform, territory and duration;
- required credit;
- cropping, editing and reuse limits;
- source time and factual-source references where applicable;
- privacy, protected-identity and reporting-restriction checks;
- generation tool and input provenance when generated; and
- final rights and risk decision.

**VIS-003 — Independent asset validation.** Copyright clearance MUST be separate from privacy, child, victim, court, medical and other subject-matter checks.

**VIS-004 — Unknown asset status.** A visual with incomplete rights or subject-risk status MUST NOT be automatically published.

### Visual selection hierarchy

**VIS-010 — Preferred hierarchy.** The system SHOULD select visuals in this order:

1. a real, event-specific image with valid editorial permission and completed subject-risk checks;
2. an independently created factual information graphic based only on verified material and Governed Claims; or
3. a consistent branded news card when neither of the first two is suitable.

At launch, `AUTO_PUBLISH` MAY select rungs 2 and 3 only. Rung 1 requires a complete Asset Record and `owner-reviewer` clearance; it MUST NOT `AUTO_PUBLISH`.

**VIS-011 — Visual optionality.** A story MUST be allowed to publish without an event image when no compliant visual exists. Visual availability MUST NOT weaken the story or evidence gate.

**VIS-012 — No misleading substitution.** A generic or file image MUST NOT imply that it depicts the reported event.

**VIS-013 — Launch visual contract.** At launch there are no generative visuals beyond branded news cards and deterministic factual graphics: no image model, AI illustration, style-transfer, or photorealistic or cartoon reconstruction (`VIS-030`–`VIS-032` remain in force). There is no third-party stock-photo, map-tile or icon provider; factual graphics MUST use independently generated geometry and the branded icon set. OpenStreetMap, Ordnance Survey, Mapbox and named stock vendors require a later specification or policy change.

### Real and file photographs

**VIS-020 — Event photo permission.** An event-specific photograph MUST NOT be used unless the Asset Record establishes the rights holder or authorised licensor, permission, platform, territory, duration, credit and editing limits.

**VIS-021 — Government and police images.** An image appearing on a government, police or other official page MUST NOT be presumed reusable. An applicable licence or explicit permission and any third-party exclusion MUST be recorded. A government-page image is not a photo-library approval of GOV.UK, news.gov.hk or any other official site.

**VIS-022 — Protected detail check.** Automation MUST NOT clear a real photograph for `AUTO_PUBLISH`; it MAY only tighten (hold or reject). A missing, uncertain or hold-trigger result MUST fail closed. Branded cards and deterministic factual graphics with no people and no scene photograph skip photo-subject checks. The system MUST tighten on: face present; child-like appearance; plate-like detail; EXIF GPS or location metadata. These triggers MUST NOT be claimed to identify every protected class. Human clearance is `owner-reviewer` ([`autonomy-and-publication-control.md`](autonomy-and-publication-control.md)). Extra sensitive-content reviewer roles remain [`sensitive-content-and-escalation.md`](sensitive-content-and-escalation.md). `VIS-051` remains in force.

**VIS-023 — File-image label.** A permitted generic or file image MUST carry a clear file-image label and MUST add genuine context.

### AI and derivative-image boundary

**VIS-030 — No unlicensed transformation.** The system MUST NOT submit an unlicensed publisher, agency, social-media or other third-party photograph to an image model for cartooning, tracing, painting, recolouring, restyling or any other derivative output.

**VIS-031 — No scene reconstruction.** The product MUST NOT use photorealistic or cartoon reconstructions of accidents, crimes, wars or disasters as if they depict the event.

**VIS-032 — No fabricated evidence.** Generated people, places, vehicles, damage, emergency response, weather or spatial arrangements MUST NOT be presented as evidence or as a factual depiction of a reported scene.

**VIS-033 — Input provenance.** A generated asset MUST record every source asset or structured factual input used. An untraceable or unauthorised input blocks publication.

### Factual information graphics

**VIS-040 — Verified elements only.** Every factual element in a map, timeline, comparison card or chart MUST link to approved evidence.

**VIS-041 — No invented detail.** A factual graphic MUST NOT invent or imply an unverified vehicle type, colour, person, injury, cause, weather condition, emergency-service count, route shape or spatial arrangement.

**VIS-042 — Independent drawing.** Icons, lines, maps and layouts MUST be independently created or properly licensed. The system MUST NOT trace a proprietary map, chart or source-photo composition.

**VIS-043 — Source label.** A factual graphic MUST show or accompany:

- the source or sources;
- source or update time; and
- a description making clear that it is an information graphic and not a scene photograph.

**VIS-044 — Chart fidelity.** A chart MUST preserve units, axes, time periods, scale, missing data, revisions and source qualifications. The visual MUST NOT exaggerate or hide material variation through misleading scale or cropping.

**VIS-045 — Map fidelity.** A map MUST show only locations and boundaries supported by evidence and a permitted base map or independently generated geometry.

**VIS-046 — Regeneration.** A change to factual data MUST invalidate the previous visual package and trigger regeneration and validation.

### Prohibited visuals

**VIS-050 — Prohibited classes.** The product MUST reject:

- unlicensed publisher images, thumbnails or screenshots;
- unauthorised derivatives of third-party images;
- fabricated people or scenes presented as evidence;
- accident, crime, war or disaster reconstructions;
- unnecessary graphic injury or death imagery;
- visuals containing unsourced factual detail;
- visuals that expose a protected or unnecessarily private identity; and
- assets whose provenance, licence or model inputs cannot be established.

**VIS-051 — No model override.** A model's statement that an asset is “fair use”, “public domain”, “official” or “safe” MUST NOT satisfy the rights gate without the required record.

## Acceptance criteria

1. A publicly accessible publisher image with no recorded licence is rejected.
2. Adding attribution to an unlicensed image does not make it publishable.
3. An unlicensed photograph cannot be submitted to an image model for a cartoon derivative.
4. A compliant incident card uses only verified location, closure and update facts and labels itself as an information graphic.
5. A generic file image is clearly labelled and does not imply it shows the event.
6. A rights-record expiry blocks new automated retrieval until review.
7. Source content cannot be sent to a model destination not permitted by the rights record.
8. A changed dataset invalidates and regenerates the associated chart.
9. A government-page image is held until the applicable licence and third-party credits are recorded.
10. A story can publish without an image rather than using a non-compliant visual.
11. A 9Q Rights Gate PASS without a production Rights Record cannot authorise automated use.
12. `RAD-02` publisher body in a Publication Bundle fails.
13. A generative illustration or style-transferred publisher photograph fails.
14. A third-party stock or map-tile asset without a launch provider (there is none) fails.
15. An event photograph cannot `AUTO_PUBLISH` even with a completed Asset Record.
16. Missing Rights Record retention period cannot retain full source text.
17. A model “safe” verdict cannot waive a face or plate hold-trigger.

## Non-goals

This specification does not provide legal advice or guarantee that a recorded permission is legally sufficient; launch still requires appropriate professional review.

At launch there is no approved stock-photo provider, map-tile provider or image-generation model. Branded news cards and deterministic factual graphics from Governed Claims are the only permitted generated visual outputs.
