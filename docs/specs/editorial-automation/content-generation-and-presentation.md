# Content generation and presentation specification

**Status:** Draft  
**Owner:** Product owner  
**Last updated:** 2026-07-11  
**Canonical language:** English  
**Related plan:** None  
**Related reference:** [`product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 8 and 10  
**Supersedes:** None

## Purpose

Define the output contract for original Hong Kong Traditional Chinese news reports generated from an approved evidence package.

## Scope

This specification covers writing authority, originality, attribution, quotation, language, neutrality, headlines, dates, article structure, metadata and generation validation. Visual assets and rights are handled separately.

## Requirements

### Generation input and authority

**CONT-001 — Approved input only.** The writing agent MUST generate from the approved evidence package and permitted structured context. It MUST NOT browse, call an unapproved source tool or introduce outside factual material during drafting.

**CONT-002 — Evidence over model memory.** Model memory, general world knowledge and prior conversation context MUST NOT serve as publication evidence for a current factual claim.

**CONT-003 — Original report.** The output MUST be an original report with its own structure and wording. It MUST NOT translate an entire source article, follow it paragraph by paragraph or reproduce its distinctive selection and analysis as a substitute.

**CONT-004 — No unsupported analysis.** The output MUST NOT originate predictions, causal analysis, motives, collective behaviour, guilt or other conclusions not present in approved attributed analysis or appropriate official evidence.

**CONT-005 — No filler.** The writer MUST stop when the verified story is adequately explained. It MUST NOT add generic conclusions, repetitive context, invented reader impact or boilerplate to meet a length target.

### Language and terminology

**CONT-010 — Output language.** Reader-facing news content MUST use Hong Kong Traditional Chinese in a Hong Kong written register, with a natural Cantonese voice where appropriate.

**CONT-011 — Serious tone.** The system MUST NOT force colloquial Cantonese, slang, humour or sensational phrasing into serious, tragic, legal, medical or safety coverage.

**CONT-012 — Official terms.** On first reference to an unfamiliar UK institution, law, policy or technical term, the story SHOULD give a clear Chinese explanation and preserve the official English name or abbreviation.

**CONT-013 — Unknown translation.** Where no settled Chinese translation exists, the system MUST retain the official English term rather than invent a misleading translation.

**CONT-014 — Named entities.** People, organisations, places, statutes and programmes MUST be rendered consistently within an article and, where a maintained terminology record exists, across the product.

**CONT-015 — Cross-language meaning.** Translation or paraphrase MUST preserve legal stage, uncertainty, attribution, quantity, time, negation and source qualification. A fluent sentence that changes any of those meanings MUST fail validation.

### Neutrality and attribution

**CONT-020 — Non-partisan output.** The product MUST NOT endorse a party, candidate, campaign or policy position, publish an editorial, or disguise opinion as news.

**CONT-021 — Evidence is not false balance.** Confirmed facts MUST be stated clearly. An unsupported claim MUST NOT receive equal status merely to simulate neutrality.

**CONT-022 — Attribution at first use.** A source MUST be identified clearly when its fact or claim is first introduced. Consecutive facts from the same clearly identified source MAY avoid repetitive attribution when meaning remains unambiguous.

**CONT-023 — Individual attribution.** Disputed claims, allegations, opinions, forecasts, estimates, published analysis and an organisation's assessment of its own performance MUST be attributed individually.

**CONT-024 — Attribution precision.** The article MUST distinguish “said”, “announced”, “recorded”, “alleged”, “estimated”, “forecast”, “found”, “ruled” and equivalent concepts according to the evidence status.

**CONT-025 — Official opinion.** A public body's claim about blame, success, motive or causation MUST remain attributed unless separately established.

**CONT-026 — No anonymous elevation.** Attribution to an established outlet MUST NOT transform its anonymous or unverifiable claim into a confirmed fact.

### Quotations and source expression

**CONT-030 — Necessary quotation only.** Direct quotation MUST be limited to wording whose exact expression materially matters, such as statutory text, an official commitment or a consequential statement.

**CONT-031 — Quote provenance.** Every direct quotation MUST link to the exact approved source passage and identify the speaker or document and date where available.

**CONT-032 — Quote length.** Quotation MUST be no longer than necessary for the editorial purpose and MUST comply with the applicable rights policy.

**CONT-033 — Translation of quotation.** A translated quotation MUST preserve meaning and MAY show the original wording where precision matters. It MUST NOT be presented as a verbatim Chinese quote without making the translation context clear.

**CONT-034 — No reconstructed quote.** The system MUST NOT combine fragments, paraphrases or secondary reports into a synthetic direct quotation.

### Headline and introduction

**CONT-040 — Confirmed lead.** The headline and introduction MUST state the most important confirmed development supported by the evidence package.

**CONT-041 — Location.** The headline SHOULD include the place when it materially disambiguates the event or reader relevance.

**CONT-042 — No clickbait.** The headline MUST NOT use emotional bait, withheld-information formulas, exaggerated stakes or curiosity gaps.

**CONT-043 — No certainty inflation.** The headline MUST NOT turn a proposal, possibility, estimate, allegation or provisional fact into certainty.

**CONT-044 — Procedural accuracy.** Arrest or charge MUST NOT be described as conviction. A consultation, bill, draft guidance or announced intention MUST NOT be described as law already in force.

**CONT-045 — Identity restraint.** Nationality, immigration status, race, religion, health status or other identity detail MUST NOT appear in a headline unless materially relevant, appropriately established and permitted by the sensitive-content specification.

**CONT-046 — Headline evidence link.** Every factual component of the headline MUST map to a central claim in the evidence package.

### Structure and length

**CONT-050 — No fixed word count.** The system MUST NOT require a fixed article length. Length MUST reflect the verified information and explanatory need.

**CONT-051 — Core understanding.** The article MUST give readers enough verified information to understand:

- what happened;
- what is confirmed and expressly provisional;
- what changed;
- any evidence-backed UK, Hong Kong or connected-family effect; and
- any official action or deadline that matters.

These are content checks, not mandatory visible headings.

**CONT-052 — Background restraint.** A development story MUST repeat only the background needed to understand the new development.

**CONT-053 — No formulaic relevance section.** The system MUST NOT insert a repetitive “why this matters to you” section when the impact is unsupported, obvious from the report or better explained naturally.

**CONT-054 — Paragraph support.** Each factual paragraph MUST be supportable by the evidence package. A paragraph containing mixed source statuses MUST preserve the distinction.

### Dates, times and numbers

**CONT-060 — Event-local time.** Event times MUST use the local time at the event location unless another convention is clearly more useful and labelled.

**CONT-061 — Cross-border deadline.** A material UK–Hong Kong deadline MAY show both UK and Hong Kong time and MUST identify GMT, BST or HKT where ambiguity matters.

**CONT-062 — Archive clarity.** Full dates SHOULD replace relative terms such as “today” or “yesterday” where the article must remain clear in an archive.

**CONT-063 — Numerical fidelity.** Numbers MUST preserve units, currency, scale, period, sign, range and source qualification. Formatting or localisation MUST NOT alter value.

**CONT-064 — Relative change.** The writer MUST NOT introduce a percentage, ratio or comparison that the evidence package does not authorise.

### Article contract

**CONT-070 — Required fields.** A publishable article package MUST contain at least:

- stable story and version identifiers;
- headline;
- body;
- geography labels;
- category labels;
- first-publication and update timestamps or placeholders assigned by the publisher;
- source references;
- related-story references where applicable;
- publisher or automated newsroom identity;
- correction or withdrawal status; and
- content-language identifier.

**CONT-071 — Source footer.** Full source links approved for reader display MUST remain attached to the article package.

**CONT-072 — Production honesty.** A human MUST NOT be identified as author, editor or approver unless the audit record shows that the person performed that role.

**CONT-073 — Automation explanation.** The product MUST provide an accessible product-level explanation of automated production. Per-article model logs are not required unless another requirement mandates disclosure.

**CONT-074 — Synthetic visual disclosure.** Any permitted factual graphic or other non-photographic visual MUST carry the description and source label required by the visual specification.

### Generation validation

**CONT-080 — Claim coverage.** The validator MUST confirm that every central draft claim maps to an approved claim-evidence record.

**CONT-081 — Entailment strength.** Draft certainty MUST NOT exceed the supporting evidence. A validator MUST detect material changes from “may” to “will”, “said” to “proved”, “estimated” to “confirmed” and equivalent shifts.

**CONT-082 — Named-entity check.** Names, roles, locations, organisations, dates and numbers in the draft MUST be checked against structured evidence.

**CONT-083 — Quote check.** Every quoted string MUST match or be an approved translation of the source passage and MUST retain attribution.

**CONT-084 — Originality check.** The system MUST assess whether the draft is excessively close to source wording, order or distinctive expression. A failed originality check blocks publication.

**CONT-085 — Repair and revalidation.** A repaired draft MUST run through all content validators again. Repair MUST NOT merely suppress a validation error without resolving the underlying text.

**CONT-086 — Ambiguity.** Where the system cannot confidently preserve a legal, numerical or attribution distinction, it MUST omit the uncertain detail or hold the candidate rather than improvise.

## Acceptance criteria

1. A source article cannot be translated paragraph by paragraph and pass the originality check.
2. A draft that changes “proposed” to “will take effect” fails certainty validation.
3. A direct quotation absent from the approved source passage fails validation.
4. An unfamiliar UK policy is explained in Chinese while retaining its official English name or abbreviation.
5. A serious incident article uses a restrained tone rather than forced colloquial language.
6. A headline stating conviction when the evidence shows only charge fails procedural validation.
7. A generated percentage not present in the evidence package fails numerical validation.
8. A human is not shown as approver for an automatically published story.
9. A development article omits repetitive background that adds no understanding of the new fact.
10. Every central headline and introduction claim is traceable to the evidence package.

## Non-goals

This specification does not prescribe a prompt template, model, article renderer, typography system or mobile layout.

It does not define visual licensing, legal escalation or source retrieval implementation.

## Open questions

- Should the product maintain a versioned bilingual terminology registry, and who approves changes?
- What quantitative or hybrid method should enforce originality without rejecting common factual language?
- Which article-level automation disclosures, if any, will be required at launch?
- Should future article types such as explainers or official action guides receive separate output contracts?
