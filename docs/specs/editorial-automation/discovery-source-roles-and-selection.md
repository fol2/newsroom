# Discovery source roles and selection specification

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Accepted record semantics:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Related research:** [`../../research/2026-07-15-concrete-news-source-map.md`](../../research/2026-07-15-concrete-news-source-map.md), [`../../research/2026-07-15-low-cost-news-discovery-options.md`](../../research/2026-07-15-low-cost-news-discovery-options.md)  
**Related proposal:** [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md)  
**Decision state:** The source roles, portfolio functions, selection gates and candidate portfolio below are proposals. Committing this Draft does not authorise collection, shadow operation or production use.  
**Supersedes:** None

## Purpose

Define why a source is monitored, how sources combine into a credible discovery portfolio and what must be proven before a source can enter shadow or production use.

This specification starts from the accepted coverage obligations. It does not treat an endpoint list, an official label, a famous publisher, a search index or a successful HTTP response as a coverage strategy.

## Scope

This specification covers:

- discovery source roles and their limits;
- portfolio functions such as anchor, complement and comparator;
- source selection and readiness gates;
- dependency, redundancy and coverage mapping;
- a proposed candidate portfolio for later shadow evaluation; and
- explicit source gaps and held candidates.

It does not define:

- the detailed meaning of source changes or Planned Agenda transitions; Topic 5 owns those semantics;
- triage batching, event grouping or model prompts; Topic 6 owns those decisions;
- search and index roles, providers or budgets beyond reserving their boundary; Topic 7 owns those decisions;
- the shadow protocol, metrics or production thresholds; Topic 8 owns those decisions;
- polling intervals, retry budgets, alert thresholds or source-health tooling; Topic 9 owns those decisions;
- final outcome codes or scoring; Topic 10 owns those decisions;
- locality expansion; Topic 11 owns that decision; or
- implementation, database schema and migration.

## Source-role principles

1. **Coverage obligation first.** A source is selected because it contributes to an accepted Active or Best-effort coverage class, not because an interface happens to exist.
2. **Discovery role is not evidence authority.** A source's usefulness for discovery does not establish what claims it may prove in an Evidence Package.
3. **Official is not one role.** An official body may originate a rule, publish a calendar, operate a service, issue a warning or editorially select other official material. Those functions have different coverage properties.
4. **Portfolio, not firehose.** Coverage is provided by complementary source roles with explicit dependencies and gaps, not by one generic search, media or government feed.
5. **Directness matters, but does not eliminate radar.** Direct first-party sources are preferred for known decisions and states; unscheduled events and lived impact often require an independent radar path.
6. **No hidden equivalence.** A curated government news feed, a full press-release feed and the responsible department's source are not assumed to provide equivalent coverage.
7. **Readiness is use-specific.** Permission and technical readiness for metadata discovery do not imply permission or readiness for full-text evidence acquisition, quotation, model submission or publication.
8. **Minimum means sufficient, not smallest count.** The portfolio is reduced only after coverage, resilience and evaluation needs are met.

## Discovery source roles

A Source Definition MAY carry more than one role when each purpose and scope is explicit.

### Originating authority watch

Monitors a body that makes, adopts, publishes or maintains the relevant decision, rule, guidance, official dataset, court output, warning or instruction.

This role is strongest for detecting the body's own act and current published version. It does not make the body's allegations, explanations, forecasts or self-assessment universally authoritative.

Examples include government departments, legislatures, regulators, courts, statistical authorities, weather agencies and public-health bodies.

### Responsible operator watch

Monitors the organisation directly responsible for an essential service, route, infrastructure system, airport, transport network, utility or operational incident state.

This role is useful for start, escalation, mitigation and resolution signals. Routine service noise remains subject to the accepted materiality boundary.

### Planned agenda watch

Monitors a calendar, release schedule, proceeding list, consultation deadline, effective date or other expected development.

An agenda source establishes an expectation only. The portfolio also needs an occurrence-confirmation path before a scheduled item may become a News Lead merely because it was due.

### Established media radar

Monitors an established news organisation for unscheduled incidents, breaking developments, lived impact, source failures and important events that do not begin with a registered official publication.

A media radar may be an essential discovery path. Its role remains lead generation; it does not bypass evidence acquisition or become claim authority merely because it is established or fast.

### Specialist or local radar

Monitors a publication, professional body or narrowly scoped source with distinctive subject, community, language or locality coverage not supplied by broader paths.

This role is selected only for an accepted obligation, Best-effort lane or observed Coverage Gap. It is not a licence to expand into exhaustive UK locality monitoring before Topic 11.

### Manual, editor or reader lead channel

Accepts a bounded human-submitted pointer, tip or proposed source. It uses the accepted Signal-to-Candidate workflow and receives no evidence or Candidate bypass.

A reader or editor lead does not become a clocked automated source merely because one submission was useful.

### Search or index radar

Represents GDELT, web search or another index that may later be approved for outer-radar, explicit-gap or evaluation work.

Topic 7 will decide its role. This specification does not count an unapproved search or index as a coverage path and does not select a provider.

## Portfolio functions

Source role describes the source's relationship to a development. Portfolio function describes why the source is included in a particular coverage design.

### Anchor

An expected direct detection path for one or more Active coverage obligations. An Anchor must identify the exact obligations, change types and limitations it is expected to cover.

### Complement

A source that closes a known blind spot in an Anchor, adds a different source relationship or transport, or covers an adjacent part of the same obligation. A Complement is not automatically independent evidence.

### Comparator

A shadow or evaluation path used to identify potential misses, noise and source dependencies. Comparator results require review and do not automatically create Coverage Gaps.

A Comparator does not count as production coverage merely because it finds more items.

### Explicit contingency

A separately approved source or version used when a named Anchor or Complement is unavailable. Contingency activation is visible and bounded. The system MUST NOT silently switch to a broader query, weaker rights assumption or unrelated source.

### Manual-only

A source or channel consulted only through an authorised bounded request. It is not polled on a recurring clock.

## Source-selection and readiness stages

The following are semantic stages; Topic 10 may choose final labels.

### Research candidate

The interface and likely contribution are documented, but one or more editorial, rights, technical or operational gates remain open.

A successful `200` response establishes only that one request returned usable transport at one time. It does not prove stable identity, revision detection, rights, acceptable noise, long-term availability or coverage sufficiency.

### Held candidate

The source has a known blocker such as failed strict TLS, required registration, unresolved terms, missing parser contract, rate limiting, inaccessible content or an unverified dependency. A Held candidate does not count as an available coverage path.

### Shadow-shortlisted source

The source is selected for a later owner-approved shadow protocol after its applicable rights, technical and operational preconditions pass. Shortlisting does not authorise collection or confer production authority.

### Comparator-only source

The source is approved only for the evaluation role defined by Topic 8. It is not an Anchor and must not silently become one.

### Production-eligible source

A source may become production-eligible only after the accepted rights, adapter, identity, baseline, source-health, shadow and release requirements pass. Production eligibility remains scoped to exact Source Definition and rights versions.

### Retired or rejected source

A later decision may retire or reject a source because it is duplicative, unreliable, unlawful, too noisy, cost-ineffective or no longer contributes to coverage. Historical records and reasons remain retained.

## Selection gates

### Editorial contribution gate

The source must identify:

- the accepted coverage obligation or Best-effort class served;
- its discovery source role and portfolio function;
- the change or event classes it is expected to detect;
- known geography, language and population limitations;
- known dependencies on another publisher, press release, wire or editorial selection; and
- why the same contribution is not already supplied more safely or efficiently.

### Rights and use gate

Before any automated shadow or production use, the source must have an owner-approved, versioned rights decision for the exact discovery behaviour, including access method, permitted fields, retention, model destination and rate restrictions.

Permission to monitor metadata is not permission to retain or submit full content. Unknown or conflicting rights block the affected use.

### Technical contract gate

The candidate must have, for its intended shadow scope:

- a successful newsroom-host smoke test using the approved access method;
- a parser or structured adapter contract with representative fixtures;
- a source-specific Item and Revision identity rule;
- an explicit first-run and reset baseline policy;
- a defined response to empty, malformed, partial and changed output;
- a way to distinguish source change from parser or normaliser change; and
- no bypass of TLS, authentication, robots or other technical controls.

### Operational-readiness gate

The candidate must have:

- an accountable source owner;
- an expected urgency or cadence class, without requiring the final interval yet;
- health and quarantine expectations;
- retry and rate-limit constraints to be finalised in Topic 9;
- expected volume and noise assumptions;
- cost and credential dependencies; and
- a declared consequence when the source fails.

### Evaluation gate

The source must identify how Topic 8 can test:

- true new items and revisions;
- unchanged behaviour;
- duplicate or dependent outputs;
- relevant misses;
- routine noise and false changes;
- operational failure; and
- its unique contribution relative to the rest of the portfolio.

## Coverage-portfolio requirements

**SRC-001 — Accepted coverage mapping.** Every selected source MUST map to at least one accepted coverage obligation, Best-effort class, operational resilience purpose or evaluation purpose.

**SRC-002 — Source role required.** Every Source Definition Version MUST declare its discovery source role and portfolio function. “Official”, “media”, “RSS” and “search” alone are insufficient purposes.

**SRC-003 — Discovery role is not evidence class.** Source selection MUST NOT assign universal evidential authority. Evidence acquisition independently applies claim-specific authority and corroboration rules.

**SRC-004 — Dependency disclosure.** Known republishing, syndication, press-release, wire, editorial-selection and shared-data dependencies MUST be recorded. Two interfaces with one originating dependency MUST NOT be presented as independent coverage.

**SRC-005 — One source may serve several obligations.** A source MAY map to several accepted obligations only where each mapping and limitation is explicit. Incidental keyword overlap is insufficient.

**SRC-006 — No source-created scope.** Adding a source MUST NOT create a new coverage obligation or broaden an exclusion. Coverage changes require the process in `COV-044`.

**SRC-010 — Anchor for Active coverage.** Every Active coverage class MUST have at least one credible candidate Anchor or a recorded launch-blocking gap under `COV-045`.

**SRC-011 — Planned dual path.** A Planned obligation MUST have both an agenda path and a permitted occurrence-confirmation path. One source MAY perform both only when the distinction remains testable.

**SRC-012 — Existing-page revision path.** An Active obligation covering guidance or rule revisions MUST include a source path capable of observing the maintained page or document state. A feed that only reliably reports new URLs is insufficient by itself.

**SRC-013 — Urgent and unscheduled path.** Active urgent warnings and clearly major unscheduled incidents MUST have a credible fast path that does not depend solely on routine departmental publication. A responsible operator, warning service or established media radar MAY supply that path according to its role.

**SRC-014 — Nation-level UK coverage.** UK-wide GOV.UK sources MUST NOT be assumed to cover devolved policy and service changes in Scotland, Wales and Northern Ireland. Accepted nation-level Active obligations require explicit candidate paths for the applicable administrations or a launch-blocking gap.

**SRC-015 — Hong Kong broad public-affairs portfolio.** Hong Kong Active coverage MUST combine broad public-affairs radar with direct official, legislative, warning, service and regulator paths. A curated government top-stories feed alone is not sufficient to claim the accepted breadth.

**SRC-016 — Qualifying global path.** The portfolio MUST have a candidate path for exceptional or qualifying global developments and a separate triage test for UK, Hong Kong or connected-family relevance. Broad world-news volume MUST NOT itself satisfy the qualification.

**SRC-017 — Locality boundary.** General local-source expansion is not required by this Topic. Selected local or specialist sources require an accepted Best-effort role, operational need or observed Gap and do not imply UK locality completeness.

**SRC-018 — Comparator cannot hide a missing Anchor.** A broad media or search Comparator MUST NOT be used to claim an Active obligation is covered when no credible production path exists.

**SRC-019 — No numeric minimum.** The portfolio MUST be minimised by removing sources that add no justified contribution, not by setting an arbitrary endpoint count that weakens coverage or resilience.

### Selection and readiness

**SRC-020 — Rights before automated use.** A source MUST pass the applicable owner-approved rights and use gate before automated shadow or production collection.

**SRC-021 — Technical readiness before shortlisting.** A source MUST NOT enter an executable shadow set until the adapter, identity, revision, baseline and failure contracts pass against a live or approved replay sample.

**SRC-022 — Strict transport security.** A source with failed certificate verification or another unsafe transport condition MUST remain Held. The system MUST NOT disable verification to obtain coverage.

**SRC-023 — Registration and credential honesty.** A source requiring registration, contract, API key or credential remains a Research or Held candidate until those prerequisites and terms are satisfied.

**SRC-024 — Partial replacements remain gaps.** A source used temporarily for another unavailable source MUST declare the exact coverage it does and does not replace. A narrower editorial feed MUST NOT be documented as equivalent to a full official firehose.

**SRC-025 — Source version admission.** Rights, locator, parser, extraction-scope or identity-rule changes create a new Source Definition Version and require the applicable review, testing and re-authorisation.

**SRC-026 — Source removal is controlled.** Removing an Anchor or Complement requires a coverage-impact assessment. A source may be removed promptly for rights or safety reasons, but the resulting gap remains explicit.

### Media, specialist and manual sources

**SRC-030 — Media radar is legitimate discovery.** An established media radar MAY be a required discovery path for unscheduled events, lived impact and official blind spots. It remains subject to rights, dependency and noise controls.

**SRC-031 — Media radar is not evidence bypass.** A media radar result creates only normal discovery records. It MUST NOT create a Source Observation or establish a central claim without the evidence workflow.

**SRC-032 — Specialist and local justification.** A specialist or local source MUST state the unique accepted obligation, Best-effort role or Gap it addresses. Prestige, audience size or local availability alone are insufficient.

**SRC-033 — Manual lead boundary.** Manual, editor and reader leads use the accepted workflow and MUST NOT bypass identity, rights, gates, triage or evidence intake.

**SRC-034 — Search boundary reserved.** No search or index provider is selected by this specification. Search and GDELT candidates remain outside the clocked source portfolio until Topic 7 is accepted.

### Evaluation and change control

**SRC-040 — Shadow shortlist is not authority.** Inclusion in the proposed shortlist does not authorise execution or production and does not imply that the source passed Topic 8 or Topic 9.

**SRC-041 — Unique contribution review.** Shadow evaluation MUST be able to identify whether a source contributes unique relevant detections, revision visibility, urgency, language or resilience relative to the portfolio.

**SRC-042 — Noise does not equal coverage.** High item volume, broad topic range or repeated media coverage MUST NOT be treated as source value without relevant unique contribution.

**SRC-043 — Coverage failure remains explicit.** If no candidate path can credibly support an Active obligation, the source portfolio records a launch-blocking gap rather than adding a generic broad query and declaring coverage complete.

**SRC-044 — Versioned portfolio decision.** The selected Source Definitions, roles, functions, mappings, held gaps and dependencies MUST be owner-reviewable and versioned. Runtime agents MUST NOT add, remove or repurpose sources autonomously.

## Proposed source portfolio for later shadow design

The proposal separates a foundation adapter-validation set, a coverage-completion shortlist, comparator candidates and unresolved mandatory source slots. It is not a command to enable every listed interface in one run.

### Foundation candidates already smoke-tested in the research appendix

| Candidate | Proposed role and function | Main contribution | Important limit |
|---|---|---|---|
| `UK-01` Home Office + UKVI Atom | Originating authority Anchor | Immigration, status, guidance and announcements | Entry metadata still needs maintained-page inspection for substantive revision |
| `UK-02` BN(O) Content API | Originating authority Anchor | Direct BN(O) guidance revision path | One page; related guidance needs separate identity |
| `UK-03` Immigration Rules Content API | Originating authority Anchor | Rules index and revision path | Changed index may require affected-document follow-up |
| `UK-04` HMRC + DWP Atom | Originating authority Anchor | Tax, benefits, pensions and work-support changes | Broad and noisy; not devolved completeness |
| `UK-05` DfE + Ofqual Atom | Originating authority Anchor | Education and examination policy | England-centred; no school or devolved completeness |
| `UK-06` DHSC + UKHSA + MHRA Atom | Originating authority Anchor | Health policy, public health and medicine/device notices | Does not cover NHS operational disruption or devolved health systems |
| `UK-07` Parliamentary Bills RSS | Originating authority Anchor | Bills and bill-stage change | Does not cover all proceedings, statements or votes |
| `UK-08` Parliamentary upcoming business | Planned Agenda Anchor | Expected Commons and Lords business | Schedule is not occurrence evidence |
| `UK-09` ONS upcoming releases | Planned Agenda and authority Anchor | Statistics releases and date changes | ONS only |
| `UK-10` Met Office warnings | Originating warning Anchor | Severe-weather warnings | Regional relevance and warning transitions require Topic 5 semantics |
| `UK-11` Environment Agency floods | Responsible warning Complement | Flood warnings in England | Not UK-wide; limited surface-water coverage |
| `HK-01` news.gov.hk top stories | Official editorial radar Anchor candidate | Broad selected Hong Kong policy, service and breaking items | Curated selection; not the full government release universe |
| `HK-02` HKO warning summary | Originating warning Anchor | Hong Kong weather warnings | Current-state source; opening and cancellation semantics required |
| `HK-03` Transport Department special traffic news | Responsible operator Anchor | Material traffic and public-transport transitions | High-volume routine incidents need the accepted materiality gate |
| `HK-04` Education Bureau latest news | Originating authority Anchor | Education and bureau-service changes | No school-level completeness |
| `HK-05` LegCo Bills | Originating authority Anchor | Bills and legislative progress | Committees, meetings and consultations need complements |
| `RAD-01` RTHK local news | Established media radar and Comparator | Hong Kong unscheduled events, public affairs and lived impact | Lead-only discovery role; not a substitute for the responsible source |
| `RAD-02` BBC UK news | Established media radar and Comparator | UK major incidents and official-list blind spots | Broad and duplicate-prone; weak on local completeness |

These candidates establish a useful adapter and workflow foundation but do not, by themselves, satisfy every accepted Active obligation.

### Coverage-completion shortlist from existing research

The following are proposed Shadow-shortlisted or Research candidates after their own rights and technical gates:

| Candidate | Proposed role | Coverage contribution | Present state |
|---|---|---|---|
| MHCLG all-content updates | Originating authority Anchor | National housing, communities and local-government policy | Host-tested research candidate |
| FSA Food Alerts API | Originating authority Anchor | Food recalls and allergy warnings | Host-tested research candidate |
| NCSC Threat Reports RSS | Originating authority Anchor | Major cyber advisories | Host-tested research candidate |
| OPSS product-safety email route | Originating authority Complement | Non-food product recalls | Route verified; mailbox adapter and terms still required |
| National Highways breaking alerts | Responsible operator Complement | Strategic-road incidents | Host-tested; materiality filter required |
| Hong Kong C&SD press releases | Originating authority Anchor | Hong Kong statistics and economy | Host-tested research candidate |
| LegCo meetings, panels and submission invitations | Planned Agenda and authority Complements | Proceedings, committees and consultations | Host-tested research candidates |
| HKMA press releases API | Originating authority Anchor | Banking, payments and monetary developments | Host-tested research candidate |
| SFC press releases RSS | Originating authority Anchor | Enforcement and investor warnings | Host-tested research candidate |
| OFCA RSS | Originating authority Complement | Telecom policy, consultations and service information | Host-tested research candidate |
| Hong Kong Consumer Council press-release page | Specialist public-interest Anchor candidate | Consumer warnings and practical action | Page tested; selector contract required |
| news.gov.hk Health & Community feed | Official editorial contingency candidate | Selected health developments while CHP feed is unavailable | Narrower than CHP; must retain the unresolved coverage gap |

### Additional candidate paths requiring research or newsroom-host validation

These are required to avoid falsely treating the existing source map as complete:

| Needed path | Proposed source role | Candidate direction | Why unresolved |
|---|---|---|---|
| Scotland-wide policy and services | Originating authority Anchor | Scottish Government news, publications and alerts | Official page and subscriptions exist, but newsroom-host adapter, identity and scope are not yet qualified |
| Wales-wide policy and services | Originating authority Anchor | GOV.WALES announcements RSS and relevant maintained pages | RSS is publicly exposed; host smoke test, rights and revision contract remain |
| Northern Ireland-wide policy and services | Originating authority Anchor | nidirect news RSS plus selected NI department news paths | Candidate interfaces exist; portfolio scope and host qualification remain |
| Devolved flood, health and urgent warnings | Warning or responsible-operator Anchors | Nation-specific official services for Scotland, Wales and Northern Ireland | England-only sources cannot satisfy UK nation-level obligations |
| Courts and material judgments | Originating authority Anchor | Find Case Law/Judiciary judgments and selected court outputs | Filtering, publication coverage, legal-risk workflow and reuse terms require qualification |
| Elections and formal electoral updates | Originating authority and Planned Agenda paths | UK Electoral Commission and Hong Kong election authorities | Exact interfaces and event semantics are not yet registered |
| UK–Hong Kong travel-rule changes | Originating authority maintained-page Anchor | FCDO Hong Kong travel advice and relevant border/aviation guidance | Current page exists, but direct revision adapter and rights review remain |
| Major aviation and airspace developments | Responsible operator and authority paths | CAA/DfT plus selected airports, airspace or route operators | A regulator news page alone may not detect live route disruption |
| Major UK–Hong Kong route disruption | Responsible operator Complement plus media radar | Selected airport, airline or airspace sources after coverage analysis | Ordinary flight tracking is excluded; the material-event path is unresolved |
| Hong Kong courts and judgments | Originating authority Anchor | Hong Kong Judiciary judgment and hearing sources | Exact permitted automated interface and identity rules remain to be qualified |
| Global qualifying and exceptional events | Established international media radar | One or more rights-reviewed global radar sources | No source is yet selected; broad volume must not replace the relevance gate |

An unresolved path for an Active class is a visible design gap. It may be included in a shadow study as a known limitation, but it cannot be presented as production-complete coverage.

### Held candidates

| Candidate | Reason held | Consequence |
|---|---|---|
| HKSAR all-government press-release RSS | Strict TLS failed from the newsroom host and HTTP fallback failed | Does not count as available; do not disable certificate verification |
| CHP press-release RSS | Strict TLS failed from the newsroom host | Health fallback remains partial; the gap stays explicit |
| National Rail disruption feeds | Registration and live credentialled smoke test required | Does not count as available until terms and access pass |
| GDELT DOC 2.0 | Newsroom-host test returned `429` | Reserved for Topic 7 and Topic 8; not an Anchor |

### Not selected by default at this stage

- all UK councils, NHS bodies, police forces, schools and local transport operators;
- TfL or another locality-specific transport source without an accepted locality or Gap justification;
- broad default feeds whose main contribution is entertainment, sport, ordinary finance or general technology volume;
- paywalled or snippet-only publishers without an approved discovery-use decision;
- official or unofficial social accounts as clocked sources before a later source-role and authenticity decision;
- Brave, DDGS, SearXNG or another search provider before Topic 7; and
- any source reached by bypassing TLS, authentication, robots or access controls.

## Accepted-coverage mapping proposed for Topic 4

| Accepted development class | Required source-role shape | Proposed candidate paths | Current gap interpretation |
|---|---|---|---|
| Law, rights, immigration, policy and deadlines | Originating authority + Planned Agenda where applicable | `UK-01`–`UK-09`, `HK-01`, `HK-05`, broader LegCo; devolved and election candidates | Devolved, election and some Hong Kong official breadth remain unresolved |
| Existing guidance and rule revisions | Maintained-page or document revision Anchor | `UK-02`, `UK-03`, FCDO Hong Kong travel advice candidate; source-specific pages | Hong Kong maintained-page portfolio not yet selected |
| Severe weather, disaster, public health and safety | Warning/authority Anchor + independent urgent radar | `UK-10`, `UK-11`, `HK-02`, `UK-06`, BBC and RTHK | Devolved flood/health warning paths remain mandatory research |
| Material transport, aviation and essential-service disruption | Responsible operator + radar | `HK-03`, National Highways, CAA/DfT and route candidates, BBC/RTHK | Rail registration and major UK–Hong Kong route path unresolved |
| Health, education, tax, welfare, work and housing | Originating authority portfolio across jurisdictions | `UK-04`–`UK-06`, MHCLG, devolved government candidates, `HK-01`, `HK-04` | Devolved systems and NHS operational change not complete |
| Consumer protection, scams, recalls and material data breach | Regulator/authority + media radar | FSA, MHRA within `UK-06`, NCSC, OPSS, SFC, OFCA, Consumer Council, BBC/RTHK | General product and cross-sector incident coverage requires shadow evidence |
| Politics, legislation, elections, courts and civil rights | Legislature, agenda, court/election authority + media radar | `UK-07`, `UK-08`, Judiciary/Find Case Law candidates, `HK-05`, broader LegCo, BBC/RTHK | Election and Hong Kong court paths unresolved |
| Major crime and unscheduled incidents | Established media radar + event-specific responsible authority | BBC UK and RTHK; later event-specific official sources enter through normal workflow | No routine police-firehose promise; other incidents remain Best effort |
| Statistics, inflation, interest rates and household cost | Official release authority + Planned Agenda | `UK-09`, C&SD, HKMA | Other UK official-statistics producers may be added by Gap |
| Major cyber incident and widespread outage | Cyber/sector authority + responsible operator + media radar | NCSC, OFCA, BBC/RTHK, later affected operators | Cross-sector outage source portfolio remains evaluation-dependent |
| Community and public-service change | National/devolved authority + broad radar | MHCLG, Scotland/Wales/NI candidates, `HK-01`, BBC/RTHK | Exhaustive locality remains the accepted deferred gap |
| Qualifying or exceptional global development | International radar + relevant official/sector follow-up | FCDO/travel sources plus a later-selected global media radar | Global radar selection remains unresolved, but search is not assumed |

## Acceptance criteria

1. A source cannot be selected merely because it is official, popular, free or available as RSS.
2. `news.gov.hk` top stories and the full HKSAR press-release feed are documented as different coverage products.
3. A BBC or RTHK item can create a Lead for a major incident but cannot bypass evidence acquisition.
4. GOV.UK organisation feeds do not silently stand in for Scotland, Wales or Northern Ireland policy sources.
5. A Planned Agenda source has a separate occurrence-confirmation path.
6. Existing immigration guidance has a maintained-page revision path rather than relying only on new-article feeds.
7. A strict-TLS failure produces a Held candidate and cannot be solved by disabling verification.
8. A source requiring registration or credentials does not count as available until access and terms pass.
9. The foundation candidate set is not described as coverage-complete merely because all interfaces returned `200` once.
10. Cross-source media and official items retain their dependencies and do not automatically count as independent coverage.
11. Every Active coverage class has a candidate Anchor or a visible launch-blocking gap.
12. The later shadow protocol can distinguish Anchor, Complement and Comparator contribution.
13. Removing a source cannot silently remove the only path for an Active obligation.
14. No search provider or generic recurring search loop is selected by this Topic.
15. The proposed shortlist can be accepted without authorising collection or production.

## Owner decisions required to complete Topic 4

The Draft recommends the following decisions:

1. Accept that discovery source role is separate from evidence authority and that “official” is not a sufficient source purpose.
2. Accept the six non-search source roles: Originating authority, Responsible operator, Planned agenda, Established media radar, Specialist/local radar and Manual/editor/reader lead; reserve Search/index radar for Topic 7.
3. Accept the portfolio functions Anchor, Complement, Comparator, Explicit contingency and Manual-only, with no silent fallback.
4. Accept that every Active class requires a credible candidate Anchor or a launch-blocking gap; Planned coverage needs agenda plus occurrence confirmation; guidance revisions need maintained-page monitoring; urgent unscheduled coverage needs a fast operator, warning or established-media path.
5. Accept that GOV.UK sources do not satisfy devolved-nation coverage by default and that Hong Kong broad public-affairs coverage requires both broad radar and direct official or sector paths.
6. Accept the editorial, rights, technical, operational and evaluation gates before a source may enter an executable shadow set.
7. Accept that one successful host response is research evidence only and that failed TLS, missing credentials, unknown terms or missing identity/revision contracts keep a source Held.
8. Accept the foundation candidates `UK-01`–`UK-11`, `HK-01`–`HK-05`, `RAD-01` and `RAD-02` as the initial adapter and workflow validation shortlist, not as a claim of complete coverage.
9. Accept the coverage-completion shortlist and additional candidate paths as the next source-qualification work, while retaining their individual blockers and without enabling every interface automatically.
10. Accept BBC UK and RTHK local as legitimate established-media radar and comparator candidates for major unscheduled events and blind spots, while keeping them inside the normal evidence boundary.
11. Accept the listed mandatory unresolved paths—devolved administrations and warnings, courts/elections, UK–Hong Kong travel and aviation, Hong Kong court sources and a global radar—as explicit pre-production source-selection work rather than hiding them behind broad search.
12. Accept that the final production source set is determined only after Topic 8 shadow evidence and Topic 9 operational readiness; Topic 4 selects roles and candidates but authorises no run.
