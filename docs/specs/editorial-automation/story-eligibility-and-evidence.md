# Story eligibility and evidence specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-08-17  
**Accepted by owner:** 2026-08-17  
**Canonical language:** English  
**Related plan:** None  
**Related reference:** [`product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 3–7  
**Supersedes:** None

## Purpose

Define which events may become stories and the minimum evidence package required before an autonomous writing and publication path may proceed.

## Scope

This specification covers geography, category, exclusions, newsworthiness, source authority, corroboration, official fact versus official opinion, anonymous sources, social media, data, published analysis and claim-to-evidence traceability.

## Requirements

### Product coverage

**EVID-001 — Geography.** Every candidate MUST carry at least one geography from `UK`, `Hong Kong` or `Global`. UK candidates MAY also carry a nation and locality supported by evidence.

**EVID-002 — No inferred precision.** A location MUST NOT be more precise than the approved evidence establishes.

**EVID-003 — Hong Kong intrinsic value.** A Hong Kong story MUST NOT be rejected solely because no direct UK effect is established.

**EVID-004 — Global qualification.** A Global candidate MUST establish at least one charter-defined UK, Hong Kong, connected-family or exceptional international public-interest effect.

**EVID-005 — Category.** Every candidate MUST carry at least one approved content category. Additional categories MUST require a substantive connection, not a passing mention.

**EVID-006 — Explicit exclusions.** Entertainment, celebrity gossip, ordinary sports, lifestyle recommendations, affiliate-style content, ordinary individual delays, general live tracking, unrelated world news, editorials and party-political advocacy MUST be rejected unless the event independently qualifies through a material public-service, safety or infrastructure effect.

**EVID-007 — Discovery hand-off.** A Discovery Signal or News Lead MUST NOT enter an evidence package. A Story Candidate MAY begin evidence acquisition, but its discovery promotion MUST NOT by itself establish substantive new information, qualification under `EVID-011` or `EVID-012`, source authority, corroboration or publication eligibility.

### Newsworthiness and volume

**EVID-010 — No publication quota.** The selection system MUST support zero qualifying stories in any run and MUST NOT create filler to satisfy a time, category, word-count or activity target.

**EVID-011 — Substantive new information.** A candidate MUST contain a newly confirmed fact, decision, rule, deadline, official finding, measurable change, material incident outcome or other substantive development before it can become a new story.

**EVID-012 — Qualification test.** A candidate MUST satisfy at least one of the following with verified evidence:

- change to a law, right, status, official deadline or public policy;
- credible material effect on safety or public health;
- material disruption to an essential service, route, school, workplace or locality;
- practical effect on household money, work, housing, education, healthcare or UK–Hong Kong travel;
- official instruction, process or deadline that affected readers may need to act on; or
- exceptional public importance in Hong Kong or internationally.

**EVID-013 — Material disruption.** Transport, aviation, weather and utility status MUST be rejected as ordinary service noise unless evidence supports a meaningful affected group, material duration or clear daily-life effect.

**EVID-014 — Selection rationale.** The decision package MUST record the qualifying test or tests satisfied and the evidence supporting them.

### Source records and authority

**EVID-020 — Source record.** Every source in an evidence package MUST record:

- stable source identifier and canonical URL or document identifier;
- publisher or responsible body;
- source type and authority class;
- publication time where available;
- retrieval time;
- applicable geography and language;
- extraction status;
- rights and permitted-use reference; and
- originating report or dependency where known.

**EVID-021 — Source classes.** The system MUST distinguish at least:

1. primary or official evidence;
2. established news organisations;
3. local or specialist publications; and
4. lead-only sources.

**EVID-022 — Authority is claim-specific.** A source class MUST NOT be treated as universal authority. The evidence package MUST identify what the source is competent to establish, such as a body's own decision, a published figure, an observed service state or a reported allegation.

**EVID-023 — Primary evidence preference.** Where current authoritative primary evidence exists and is permitted for use, the package MUST include it and the story MUST cite it for the fact it establishes.

**EVID-024 — Lead-only boundary.** A tier-four or lead-only source MAY trigger discovery but MUST NOT support a central factual claim, identity, allegation, number or publication decision.

**EVID-025 — Source independence.** Evidential-origin independence is a deterministic gate. Multiple publications derived from the same wire report, press release, pool report, syndication or originating article MUST count as one evidential origin for corroboration. A model MAY flag suspected shared origin to tighten corroboration only and MUST NOT create independence. Deterministic MUST signals include: Source Registry / `SRC-004` recorded dependency; identical canonical URL or document identifier; identical originating-artefact digest; structured wire, syndication, byline or copyright metadata; and the `EVID-020` originating-report field. Fail-closed: if two sources are not deterministically independent, they count as one evidential origin. Model silence is not independence.

**EVID-026 — Current version.** For rules, deadlines, official guidance and datasets, the package MUST identify the version, reference period or effective date needed to show that the evidence is current for the claim.

### Evidence gates by claim type

**EVID-030 — Official rule or decision.** A current primary document MAY establish what the responsible body decided, published or brought into force, but MUST NOT automatically establish the body's disputed assessment of another party or its own success.

**EVID-031 — Official number or dataset.** A reported figure MUST link to the originating publication, dataset, table, release or equivalent reference for the stated period.

**EVID-032 — Developing incident.** A developing incident or service disruption MUST be supported by a directly responsible authoritative body or operator. If no suitable primary source exists, at least two independent reliable published origins MUST corroborate the same narrow fact.

**EVID-033 — Other factual event.** A factual event MUST be supported by a directly responsible authoritative public source or by at least two independent reliable published origins that corroborate the same narrow fact.

**EVID-034 — Serious allegation.** A serious allegation, identity, motive or criminal-responsibility claim MUST satisfy the sensitive-content specification in addition to appropriate public, verifiable evidence. Evidence sufficiency alone does not authorise automatic publication.

**EVID-035 — Published analysis.** Analysis, a model or a forecast MUST come from a named, credible and traceable source with relevant expertise and an inspectable evidential basis. The story MUST attribute it and MUST NOT present it as the newsroom's own prediction.

**EVID-036 — Evidence failure.** If the minimum evidence gate is not met, the candidate MUST be rejected unless a defined, reviewable uncertainty justifies a hold. The system MUST NOT investigate through private contact or private-document requests.

### Claim-to-evidence contract

**EVID-040 — Central claims.** Before publication validation, the package MUST enumerate every central claim required by the headline, introduction and material conclusions. Each central claim MUST be bound to a Governed Claim admitted for that Evidence Package's publication-evidence use.

**EVID-041 — Evidence links.** Every central claim MUST link to one or more source records and to the exact extracted passage, table, field or structured fact that supports it.

**EVID-042 — Claim status.** Every central claim MUST be classified as one of:

- confirmed fact;
- expressly provisional fact;
- attributed claim or opinion;
- published analysis or forecast; or
- contextual background.

**EVID-043 — Unsupported output.** A draft sentence that introduces a new central claim, stronger certainty, new causal link, new identity, new number or new quotation absent from the evidence package MUST fail validation.

**EVID-044 — Conflict.** Materially conflicting authoritative evidence MUST be represented explicitly. The system MUST NOT select one version silently. The candidate MUST be held or rejected according to the conflict and risk policy.

**EVID-045 — Provisional marker.** If the authoritative source labels a figure, status or conclusion provisional, estimated, preliminary or subject to revision, the evidence package and final story MUST preserve that qualification.

**EVID-046 — Changed fact.** For a development story, the package MUST identify the new fact and the earlier state it changes. Background without a new fact MUST NOT qualify as a development.

### Official fact, attribution and anonymous material

**EVID-050 — Official act versus assertion.** The system MAY treat a body's own decision, filing, recorded action, document text or published data series as an official fact. It MUST treat allegations, blame, causation, guilt and self-assessment as attributed claims unless separately established.

**EVID-051 — Procedural precision.** Arrest, charge, trial, conviction, sentence, regulatory investigation, proposed rule, enacted rule and effective rule MUST remain distinct states.

**EVID-052 — Anonymous claims.** A core factual claim supported only by an unnamed official, anonymous source, leak or unverifiable screenshot MUST NOT be published as confirmed news, including when an established outlet reports it.

**EVID-053 — Official social accounts.** A verified official account MAY support what the responsible body publicly stated, subject to authenticity and currency checks. It does not prove a disputed underlying allegation merely by being official.

**EVID-054 — Other social media.** Non-official posts, reactions, videos, comments, likes and messaging-group material are lead-only unless independently verified through the normal evidence gate.

**EVID-055 — No reaction stories.** The system MUST NOT infer public opinion from a handful of posts or publish “online outrage” as a story. Formal polling MAY be reported only within its published method and result.

### Data and comparisons

**EVID-060 — Data provenance.** Data claims MUST identify the provider, publication, reference period and relevant dataset, table, series or section where applicable.

**EVID-061 — Definition consistency.** Figures MUST NOT be presented as directly comparable across a material definition, methodology, coverage or collection change unless an authoritative source itself makes and explains the comparison.

**EVID-062 — Derived calculations.** The system MUST NOT publish newly calculated rates, ratios, rankings, per-capita figures or comparisons.

**EVID-063 — Rounding and units.** A reproduced numerical claim MUST preserve material units, scale, reference period, currency and source qualification. Automated formatting MUST NOT change its meaning.

### Evidence-package integrity

**EVID-070 — Approved package.** The writer and validators MUST consume the same immutable evidence-package version.

**EVID-071 — Retrieval integrity.** Extraction errors, truncation, paywall fragments, missing table context, failed encoding or ambiguous document versions MUST be flagged. A partial extraction MUST NOT be treated as complete evidence.

**EVID-072 — No inaccessible reconstruction.** The system MUST NOT reconstruct a paywalled or inaccessible report from snippets, secondary quotations or search-result fragments as a substitute for lawful access.

**EVID-073 — Evidence freshness.** Freshness is governed by claim-class currency families, not global wall-clock minutes. A missing applicable rule MUST fail closed. Stale evidence MUST block or qualify the claim and MUST NOT be silently reused.

- **Current-version:** rules, deadlines, official guidance and datasets — bound to the effective instrument or stated reference period or series version. A still-in-force instrument is not stale by wall-clock age; a superseded instrument fails.
- **Observed-state:** developing incidents, service disruptions, warnings and official social statements — `publication_time` (else `retrieval_time`) MUST fall within that Source Definition's approved currency window; a missing window fails closed.
- **Completed historical event:** the originating record MAY support what happened then and MUST NOT be treated as live status.

Serious allegations also require the sensitive-content specification. Published analysis MUST use the source's dated current version and MUST NOT be silently treated as still current.

**EVID-074 — Package hash.** The package MUST have a stable version or content hash referenced by drafting, validation, review and publication records.

### Chart and map evidence

**EVID-080 — Visual element claims.** Every plotted or mapped element MUST be a central claim in the same Evidence Package, bound as a Governed Claim admitted for that package's publication-evidence use.

**EVID-081 — Visual evidence fields.** Each visual element MUST record claim identity, source-record identity, exact extracted passage, table or field, unit, reference period, provisional or revision marker, dataset or release identity, and package hash.

**EVID-082 — Map geography.** Each map location or boundary MUST record its evidenced geography and the `EVID-002` precision ceiling.

**EVID-083 — Source-published values only.** Charts and maps MUST plot only source-published values and MUST NOT plot newsroom-derived series. Base-map and icon licensing remain in the rights-and-visuals specification.

## Acceptance criteria

1. An official government rule change is supported by the current primary document, carries the correct effective date and does not repeat the government's self-assessment as fact.
2. Three outlets reproducing one wire report count as one evidential origin, not three independent sources.
3. A social-media rumour creates a lead but cannot create a Governed Claim, approved Evidence Package, authorising Publication Decision or dispatchable Target Operation.
4. A development story identifies the new confirmed fact rather than republishing unchanged background.
5. A writer-generated number absent from the evidence package fails validation.
6. A provisional official statistic remains labelled provisional in the story.
7. Conflicting authoritative casualty figures trigger a hold or rejection rather than silent selection.
8. An ordinary short train delay fails the material-disruption test and produces no story.
9. A Hong Kong policy story is not rejected merely because it lacks a direct UK effect.
10. A missing or truncated primary document invalidates dependent claims and blocks publication.
11. A writer-derived rate fails validation.
12. Two wire copies count as one evidential origin without a model flag.
13. Observed-state evidence with no currency window fails.
14. A superseded instrument fails current-version.
15. A chart element without a Governed Claim link fails.

## Non-goals

This specification does not define crawler implementation, source licensing terms, storage topology, semantic-search technology or specific LLM prompts.

It does not authorise investigation, witness contact, private-document collection or anonymous-source reporting.
