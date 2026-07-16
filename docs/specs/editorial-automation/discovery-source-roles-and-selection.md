# Discovery source roles and selection specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Accepted by owner:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Accepted record semantics:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Related research:** [`../../research/2026-07-15-concrete-news-source-map.md`](../../research/2026-07-15-concrete-news-source-map.md), [`../../research/2026-07-15-low-cost-news-discovery-options.md`](../../research/2026-07-15-low-cost-news-discovery-options.md)  
**Related proposal:** [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md)  
**Implementation authority:** None. Acceptance defines source roles, selection rules and candidate work; it does not authorise collection, shadow operation or production use.  
**Supersedes:** None

## Purpose

Define why a source is monitored, how sources combine into a credible discovery portfolio and what must be proven before a source may enter shadow or production use.

Source selection starts from the accepted coverage obligations. An endpoint list, an official label, a famous publisher, a search index or one successful HTTP response is not a coverage strategy.

## Scope

This specification defines:

- discovery source roles and their limits;
- portfolio functions such as Anchor, Complement and Comparator;
- source selection and readiness gates;
- dependency, redundancy and coverage mapping;
- the accepted candidate portfolio for later source qualification and shadow design; and
- explicit source gaps and Held candidates.

It does not define:

- source-change or Planned Agenda semantics, which belong to Topic 5;
- triage batching, event grouping or model prompts, which belong to Topic 6;
- search and index roles, providers or budgets, which belong to Topic 7;
- shadow metrics or production thresholds, which belong to Topic 8;
- polling intervals, retry budgets, alert thresholds or source-health tooling, which belong to Topic 9;
- final outcome codes or scoring, which belong to Topic 10;
- locality expansion, which belongs to Topic 11; or
- implementation, database schema and migration.

## Source-role principles

1. **Coverage obligation first.** A source is selected because it contributes to an accepted Active or Best-effort class, not because an interface happens to exist.
2. **Discovery role is not evidence authority.** Discovery usefulness does not establish which claims a source may prove in an Evidence Package.
3. **Official is not one role.** An official body may originate a rule, publish an agenda, operate a service, issue a warning or editorially select other official material. Those functions have different coverage properties.
4. **Portfolio, not firehose.** Coverage comes from complementary roles with explicit dependencies and gaps, not one generic search, media or government feed.
5. **Directness matters without eliminating radar.** Direct first-party sources are preferred for known decisions and states; unscheduled events and lived impact often need an independent radar path.
6. **No hidden equivalence.** A curated government news feed, a full press-release feed and a responsible department's maintained source are not presumed equivalent.
7. **Readiness is use-specific.** Permission and readiness for metadata discovery do not imply permission or readiness for full-text evidence acquisition, quotation, model submission or publication.
8. **Minimum means sufficient, not smallest count.** Sources are removed only after coverage, resilience and evaluation needs are met.

## Discovery source roles

One Source Definition may carry several roles only when each purpose, scope and limitation is explicit.

### Originating authority watch

Monitors the body that makes, adopts, publishes or maintains a relevant decision, rule, guidance document, official dataset, court output, warning or instruction.

This role is strongest for detecting the body's own act and current published version. It does not make the body's allegations, explanations, forecasts or self-assessment universally authoritative.

### Responsible operator watch

Monitors the organisation directly responsible for an essential service, route, infrastructure system, airport, transport network, utility or operational incident state.

This role supports start, escalation, mitigation and resolution detection. Routine service noise remains outside scope unless it passes the accepted materiality boundary.

### Planned agenda watch

Monitors a calendar, release schedule, proceeding list, consultation deadline, effective date or other expected development.

An agenda source establishes an expectation only. Planned coverage also requires an occurrence-confirmation path before a scheduled item may be treated as having occurred.

### Established media radar

Monitors an established news organisation for unscheduled incidents, breaking developments, lived impact, source failures and important events that do not begin with a registered official publication.

A media radar may be a required discovery path. It remains lead generation and receives no evidence bypass.

### Specialist or local radar

Monitors a publication, professional body or narrowly scoped source with distinctive subject, community, language or locality coverage not supplied by broader paths.

This role requires an accepted obligation, Best-effort lane or observed Coverage Gap. It does not authorise exhaustive UK locality monitoring before Topic 11.

### Manual, editor or reader lead channel

Accepts a bounded human-submitted pointer, tip or proposed source. It uses the accepted Signal-to-Candidate workflow and receives no evidence or Candidate bypass.

A useful submission does not automatically turn the channel into a recurring automated source.

### Search or index radar — reserved

GDELT, web search and other indexes remain reserved for Topic 7. This specification neither selects a provider nor counts an unapproved search path as coverage.

## Portfolio functions

Source role describes the source's relationship to a development. Portfolio function explains why the source is included in a particular portfolio.

### Anchor

An expected direct detection path for one or more Active obligations. An Anchor identifies the exact obligations, change classes and limitations it is expected to cover.

### Complement

A source that closes a known Anchor blind spot, adds a different source relationship or transport, or covers an adjacent part of the same obligation. A Complement is not automatically independent evidence.

### Comparator

A shadow or evaluation path used to identify potential misses, noise and source dependencies. Comparator results require review and do not automatically create Coverage Gaps or count as production coverage.

### Explicit contingency

A separately approved source or version used when a named Anchor or Complement is unavailable. Activation is visible and bounded. Silent fallback to a broader query, weaker rights assumption or unrelated source is prohibited.

### Manual-only

A source or channel consulted only through an authorised bounded request and not polled on a recurring clock.

## Source lifecycle and readiness stages

These are semantic stages; Topic 10 may later choose final labels.

- **Research candidate:** likely contribution is documented, but editorial, rights, technical, operational or evaluation gates remain open.
- **Held candidate:** a known blocker such as failed strict TLS, required registration, unresolved terms, missing parser contract, rate limiting or inaccessible content prevents use. It does not count as an available path.
- **Shadow-shortlisted source:** selected for a later owner-approved shadow protocol after applicable preconditions pass. Shortlisting is not execution authority.
- **Comparator-only source:** approved solely for a Topic 8 evaluation role and not an Anchor.
- **Production-eligible source:** exact Source Definition and rights versions have passed accepted rights, adapter, identity, baseline, health, shadow and release gates.
- **Retired or rejected source:** later removed because it is duplicative, unreliable, unlawful, too noisy, cost-ineffective or no longer contributes. History and reasons remain retained.

A successful `200` response proves only that one request returned usable transport at one time. It does not prove stable identity, revision detection, rights, acceptable noise, long-term availability or coverage sufficiency.

## Selection gates

### Editorial contribution gate

The source identifies:

- the accepted coverage obligation or Best-effort class served;
- its source role and portfolio function;
- the change or event classes it is expected to detect;
- geography, language and population limitations;
- known republishing, wire, press-release, shared-data or editorial-selection dependencies; and
- why the contribution is not already supplied more safely or efficiently.

### Rights and use gate

Before automated shadow or production use, the exact discovery behaviour has an owner-approved, versioned rights decision covering access method, permitted fields, retention, model destination and rate restrictions.

Permission to monitor metadata is not permission to retain or submit full content. Unknown or conflicting rights block the affected use.

### Technical contract gate

For its intended shadow scope, the source has:

- a successful newsroom-host smoke test using the approved access method;
- a parser or structured adapter contract with representative fixtures;
- source-specific Source Item and Source Revision identity rules;
- an explicit first-run and reset baseline policy;
- defined empty, malformed, partial and changed-output behaviour;
- separation between source change and parser or normaliser change; and
- no TLS, authentication, robots or technical-control bypass.

### Operational-readiness gate

The source has:

- an accountable source owner;
- an expected urgency or cadence class without fixing the final interval;
- health and quarantine expectations;
- retry and rate-limit constraints to be completed in Topic 9;
- volume and noise assumptions;
- cost and credential dependencies; and
- a declared coverage consequence when it fails.

### Evaluation gate

Topic 8 must be able to evaluate:

- true new items and revisions;
- unchanged behaviour;
- duplicate or dependent outputs;
- relevant misses;
- routine noise and false changes;
- operational failure; and
- unique contribution relative to the portfolio.

## Requirements

### Coverage and portfolio

**SRC-001 — Accepted coverage mapping.** Every selected source MUST map to an accepted obligation, Best-effort class, operational-resilience purpose or evaluation purpose.

**SRC-002 — Source role required.** Every Source Definition Version MUST declare its source role and portfolio function. “Official”, “media”, “RSS” and “search” alone are insufficient purposes.

**SRC-003 — Discovery role is not evidence class.** Source selection MUST NOT assign universal evidential authority. Evidence acquisition applies claim-specific authority and corroboration independently.

**SRC-004 — Dependency disclosure.** Known republishing, syndication, press-release, wire, editorial-selection and shared-data dependencies MUST be recorded. Two interfaces with one origin MUST NOT be presented as independent coverage.

**SRC-005 — Several obligations need explicit mappings.** One source MAY serve several obligations only where each contribution and limitation is explicit. Incidental keyword overlap is insufficient.

**SRC-006 — No source-created scope.** Adding a source MUST NOT create a coverage obligation or broaden an exclusion. Coverage changes follow `COV-044`.

**SRC-010 — Anchor for Active coverage.** Every Active class MUST have a credible candidate Anchor or a recorded launch-blocking gap under `COV-045`.

**SRC-011 — Planned dual path.** A Planned obligation MUST have an agenda path and a permitted occurrence-confirmation path. One source may perform both only when the distinction remains testable.

**SRC-012 — Existing-page revision path.** Guidance and rule-revision coverage MUST include a path capable of observing maintained page or document state. A feed that only reliably reports new URLs is insufficient by itself.

**SRC-013 — Urgent and unscheduled path.** Active urgent warnings and clearly major unscheduled incidents MUST have a credible fast path that does not depend solely on routine departmental publication. A responsible operator, warning service or established media radar may provide it.

**SRC-014 — Nation-level UK coverage.** UK-wide GOV.UK sources MUST NOT be assumed to cover Scotland, Wales and Northern Ireland policy and service changes. Applicable Active obligations need explicit candidate paths or a launch-blocking gap.

**SRC-015 — Hong Kong broad public-affairs portfolio.** Hong Kong Active coverage MUST combine broad public-affairs radar with direct official, legislative, warning, service and regulator paths. A curated government top-stories feed alone is insufficient.

**SRC-016 — Qualifying global path.** The portfolio MUST have a candidate path for qualifying or exceptional global developments and a separate UK, Hong Kong or connected-family relevance test. Broad world-news volume does not satisfy the qualification.

**SRC-017 — Locality boundary.** General local-source expansion is not required here. A local or specialist source needs an accepted Best-effort role, operational need or observed Gap and does not imply UK locality completeness.

**SRC-018 — Comparator cannot hide a missing Anchor.** A broad media or search Comparator MUST NOT be used to claim Active coverage when no credible production path exists.

**SRC-019 — No numeric minimum.** The portfolio is minimised by removing sources that add no justified contribution, not by setting an arbitrary endpoint count that weakens coverage or resilience.

### Selection and readiness

**SRC-020 — Rights before automated use.** A source MUST pass the applicable owner-approved rights and use gate before automated shadow or production collection.

**SRC-021 — Technical readiness before execution.** A source MUST NOT enter an executable shadow set until adapter, identity, revision, baseline and failure contracts pass against a live or approved replay sample.

**SRC-022 — Strict transport security.** Failed certificate verification or another unsafe transport condition keeps the source Held. Verification MUST NOT be disabled to obtain coverage.

**SRC-023 — Registration and credential honesty.** A source requiring registration, contract, API key or credential remains Research or Held until prerequisites and terms are satisfied.

**SRC-024 — Partial replacements remain gaps.** A temporary source declares the exact coverage it does and does not replace. A narrower editorial feed MUST NOT be documented as equivalent to a full official firehose.

**SRC-025 — Source-version admission.** Rights, locator, parser, extraction scope or identity-rule changes create a new Source Definition Version and require applicable review, testing and re-authorisation.

**SRC-026 — Controlled removal.** Removing an Anchor or Complement requires coverage-impact assessment. Urgent removal for rights or safety keeps the resulting gap explicit.

### Media, specialist and manual sources

**SRC-030 — Media radar is legitimate discovery.** Established media MAY be a required path for unscheduled events, lived impact and official blind spots, subject to rights, dependency and noise controls.

**SRC-031 — Media radar is not evidence bypass.** Media radar creates only normal discovery records and cannot establish a central claim without the evidence workflow.

**SRC-032 — Specialist and local justification.** A specialist or local source states the unique obligation, Best-effort role or Gap it addresses. Prestige, audience size or availability are insufficient.

**SRC-033 — Manual lead boundary.** Manual, editor and reader leads use the accepted workflow and do not bypass identity, rights, gates, triage or evidence intake.

**SRC-034 — Search boundary reserved.** Search and GDELT remain outside the clocked source portfolio until Topic 7 is accepted.

### Evaluation and change control

**SRC-040 — Shortlist is not authority.** Inclusion in a shortlist does not authorise execution or production and does not imply Topic 8 or Topic 9 has passed.

**SRC-041 — Unique contribution review.** Shadow evaluation MUST identify whether a source contributes unique relevant detections, revision visibility, urgency, language coverage or resilience.

**SRC-042 — Noise does not equal coverage.** High volume, broad topics or repeated coverage are not source value without relevant unique contribution.

**SRC-043 — Coverage failure remains explicit.** If no path credibly supports an Active obligation, the portfolio records a launch-blocking gap rather than adding a broad query and declaring coverage complete.

**SRC-044 — Versioned portfolio decision.** Selected Source Definitions, roles, functions, mappings, Held gaps and dependencies are owner-reviewable and versioned. Runtime agents MUST NOT autonomously add, remove or repurpose sources.

## Accepted candidate portfolio for later qualification

This section defines candidate work, not an instruction to enable every interface in one run.

### Foundation adapter and workflow validation shortlist

The following smoke-tested research candidates are accepted as an initial validation shortlist, not as complete coverage:

| Candidate | Role and function | Main contribution | Important limit |
|---|---|---|---|
| `UK-01` Home Office + UKVI Atom | Originating authority Anchor | Immigration, status, guidance and announcements | Entry metadata still needs maintained-page inspection |
| `UK-02` BN(O) Content API | Originating authority Anchor | Direct BN(O) guidance revision path | One page only |
| `UK-03` Immigration Rules Content API | Originating authority Anchor | Rules index and revision path | Changed index may require document follow-up |
| `UK-04` HMRC + DWP Atom | Originating authority Anchor | Tax, benefits, pensions and work-support changes | Broad, noisy and not devolved completeness |
| `UK-05` DfE + Ofqual Atom | Originating authority Anchor | Education and examination policy | England-centred |
| `UK-06` DHSC + UKHSA + MHRA Atom | Originating authority Anchor | Health policy, public health and medicine or device notices | No NHS operational or devolved-health completeness |
| `UK-07` Parliamentary Bills RSS | Originating authority Anchor | Bills and bill-stage changes | Not all proceedings, statements or votes |
| `UK-08` Parliamentary upcoming business | Planned agenda Anchor | Expected Commons and Lords business | Schedule is not occurrence evidence |
| `UK-09` ONS upcoming releases | Planned agenda and authority Anchor | Statistics releases and date changes | ONS only |
| `UK-10` Met Office warnings | Originating warning Anchor | Severe-weather warnings | Regional and transition semantics remain Topic 5 work |
| `UK-11` Environment Agency floods | Responsible warning Complement | Flood warnings in England | Not UK-wide and limited surface-water coverage |
| `HK-01` news.gov.hk top stories | Official editorial radar Anchor candidate | Selected major Hong Kong policy, service and breaking items | Curated, not the full government-release universe |
| `HK-02` HKO warning summary | Originating warning Anchor | Hong Kong weather warnings | Current-state transition semantics required |
| `HK-03` Transport Department special traffic news | Responsible operator Anchor | Material traffic and transport transitions | High-volume routine incidents need materiality filtering |
| `HK-04` Education Bureau latest news | Originating authority Anchor | Education and bureau-service changes | No school-level completeness |
| `HK-05` LegCo Bills | Originating authority Anchor | Bills and legislative progress | Committees, meetings and consultations need complements |
| `RAD-01` RTHK local news | Established media radar and Comparator | Hong Kong unscheduled events, public affairs and lived impact | Lead-only discovery role |
| `RAD-02` BBC UK news | Established media radar and Comparator | UK major incidents and official-list blind spots | Broad, duplicate-prone and weak on local completeness |

### Coverage-completion qualification shortlist

The following accepted candidates require their own rights and technical gates before any executable shortlist:

- MHCLG all-content updates for national housing, communities and local-government policy;
- FSA Food Alerts API for food recalls and allergy warnings;
- NCSC Threat Reports RSS for major cyber advisories;
- OPSS product-safety email for non-food recalls;
- National Highways breaking alerts for strategic-road incidents;
- Hong Kong C&SD releases for statistics and economy;
- LegCo meetings, panels and submission invitations for proceedings and consultations;
- HKMA press-release API for banking, payments and monetary developments;
- SFC press-release RSS for enforcement and investor warnings;
- OFCA RSS for communications policy, consultations and service information;
- Hong Kong Consumer Council press-release monitoring for consumer warnings; and
- news.gov.hk Health & Community only as a partial contingency while CHP remains unavailable.

### Mandatory unresolved source work before production completeness

The portfolio must qualify or explicitly resolve paths for:

- Scotland-wide policy and services;
- Wales-wide policy and services;
- Northern Ireland-wide policy and services;
- devolved flood, health and urgent warnings;
- courts and material judgments;
- elections and formal electoral updates;
- UK–Hong Kong travel-rule changes;
- major aviation, airspace and UK–Hong Kong route disruption;
- Hong Kong courts and judgments; and
- qualifying and exceptional global developments through a rights-reviewed international radar.

An unresolved Active path remains a visible design gap and cannot be hidden behind broad search or media volume.

### Held candidates

| Candidate | Reason Held | Consequence |
|---|---|---|
| HKSAR all-government press-release RSS | Strict TLS failed from the newsroom host and HTTP fallback failed | Does not count as available; do not disable verification |
| CHP press-release RSS | Strict TLS failed from the newsroom host | Health contingency remains partial and the gap stays explicit |
| National Rail disruption feeds | Registration and live credentialled smoke test required | Does not count as available until terms and access pass |
| GDELT DOC 2.0 | Newsroom-host test returned `429` | Reserved for Topics 7 and 8; not an Anchor |

### Not selected by default

- all UK councils, NHS bodies, police forces, schools and local transport operators;
- TfL or another locality-specific source without accepted locality or Gap justification;
- broad default feeds dominated by entertainment, sport, ordinary finance or general technology;
- paywalled or snippet-only publishers without approved discovery-use rights;
- social accounts as recurring sources before authenticity and source-role review;
- Brave, DDGS, SearXNG or another search provider before Topic 7; and
- any source reached by bypassing TLS, authentication, robots or access controls.

## Acceptance criteria

1. A source cannot be selected merely because it is official, popular, free or available as RSS.
2. `news.gov.hk` top stories and the full HKSAR press-release feed remain different coverage products.
3. BBC or RTHK may create a major-incident Lead but receive no evidence bypass.
4. GOV.UK organisation feeds do not stand in for Scotland, Wales or Northern Ireland.
5. Planned coverage has an occurrence-confirmation path separate from the expectation.
6. Existing guidance has a maintained-page revision path rather than relying only on new-article feeds.
7. Strict-TLS failure creates a Held source and cannot be solved by disabling verification.
8. Registration or credential requirements keep a source unavailable until access and terms pass.
9. The foundation shortlist is not described as coverage-complete because interfaces once returned `200`.
10. Shared origin and editorial-selection dependencies remain visible.
11. Every Active class has a credible candidate Anchor or a launch-blocking gap.
12. Topic 8 can distinguish Anchor, Complement and Comparator contribution.
13. Removing a source cannot silently remove the only Active path.
14. No search provider or generic recurring search loop is selected here.
15. Acceptance of this shortlist does not authorise collection or production.

## Completion record

The product owner accepted this specification on 2026-07-15 with the following decisions:

- source role is separate from evidence authority, and “official” is not a sufficient source purpose;
- the accepted non-search roles are Originating authority, Responsible operator, Planned agenda, Established media radar, Specialist or local radar, and Manual, editor or reader lead;
- the accepted portfolio functions are Anchor, Complement, Comparator, Explicit contingency and Manual-only, with no silent fallback;
- every Active class needs a credible candidate Anchor or launch-blocking gap; Planned coverage needs expectation and occurrence paths; guidance revisions need maintained-page monitoring; urgent unscheduled coverage needs a fast warning, operator or established-media path;
- GOV.UK does not satisfy devolved coverage by default, and Hong Kong broad public-affairs coverage needs broad radar plus direct official and sector paths;
- a source must pass editorial, rights, technical, operational and evaluation gates before executable shadow use;
- one successful host response is research evidence only, while failed TLS, missing credentials, unknown terms or missing identity and revision contracts keep a source Held;
- `UK-01`–`UK-11`, `HK-01`–`HK-05`, RTHK and BBC UK form the initial adapter and workflow validation shortlist, not a completeness claim;
- the coverage-completion shortlist and additional candidate paths are accepted as source-qualification work without automatic enablement;
- BBC UK and RTHK are legitimate established-media radar and Comparator candidates while remaining inside the evidence boundary;
- devolved administrations and warnings, courts and elections, UK–Hong Kong travel and aviation, Hong Kong court sources and a global radar remain mandatory unresolved pre-production source work; and
- the final production portfolio is decided only after Topic 8 shadow evidence and Topic 9 operational readiness. Acceptance of Topic 4 authorises no run.
