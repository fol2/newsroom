# Discovery search and coverage-audit specification

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Accepted record semantics:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Accepted source roles:** [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md)  
**Accepted change semantics:** [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md)  
**Accepted triage contract:** [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Related research:** [`../../research/2026-07-15-low-cost-news-discovery-options.md`](../../research/2026-07-15-low-cost-news-discovery-options.md), [`../../research/2026-07-15-concrete-news-source-map.md`](../../research/2026-07-15-concrete-news-source-map.md)  
**Decision state:** The search roles, request semantics, provider boundaries, budgets and coverage-audit rules below are proposals. Committing this Draft does not authorise queries, provider accounts, spending, shadow operation or production use.  
**Supersedes:** None

## Purpose

Define the limited roles that web search and media indexes may play in discovery, the controls on every query and result, and how search-assisted coverage auditing can identify real omissions without treating another index as ground truth.

The contract is designed to obtain the recall value of search without allowing a generic query loop to become the newsroom's implicit coverage model, recurring production clock, evidence source or uncontrolled cost centre.

## Scope

This specification defines:

- permitted search and index roles;
- prospective outer-radar and recall-audit boundaries;
- triggered gap, missed-expectation, supplemental and outage searches;
- Search Request, Attempt, Result Reference and review semantics;
- query construction, privacy and injection controls;
- provider rights, retention, model-use and operational admission;
- request, result, cost and amplification budgets;
- result deduplication, dependency and normal workflow entry;
- prospective versus retrospective coverage audit;
- Coverage Gap review and interpretation; and
- the current status of Brave, GDELT and self-hosted metasearch candidates.

It does not define:

- the final shadow protocol, sample size, labels or release thresholds, which belong to Topic 8;
- exact schedules, retry budgets, alerts or provider failover mechanisms, which belong to Topic 9;
- final reason strings or numeric prioritisation, which belong to Topic 10;
- locality expansion, which belongs to Topic 11;
- evidence extraction, drafting or publication; or
- implementation, credentials, billing accounts or database schema.

## Search boundary

Search is an index-mediated discovery channel. It is not:

- an Anchor for an Active coverage obligation;
- proof that an event exists or does not exist;
- proof that the returned publisher page is current or accurate;
- an evidence package;
- an automatic replacement for a failed direct source;
- a measure of independent source count;
- a licence to fetch, store or submit the underlying page to a model; or
- permission for a runtime agent to invent recurring queries.

An index may find a relevant page that the selected portfolio missed. The result still enters the accepted Source Item or approved channel-input identity, Signal, gate, Lead, triage and evidence boundaries.

## Accepted-search-role candidates

A Search Request must have exactly one primary role. A later review may attach secondary evaluation tags, but it cannot blur the authority or budget of the primary role.

### Prospective outer radar

A bounded, pre-authorised query or media-index lane intended to find important in-scope developments outside the registered source portfolio.

The proposed initial status is **Comparator and Best-effort only**. It does not count as an Anchor, does not repair a missing Active path and does not run one generic query per beat. A recurring production role may be considered only after Topic 8 demonstrates unique relevant contribution and Topic 9 qualifies provider reliability, rights and cost.

### Prospective recall-audit comparator

A pre-registered, time-bounded query used to compare the selected portfolio with another permitted index during a defined evaluation window.

The query, time range and result cap must be fixed before its results are reviewed. This prevents a known missed story from being used to construct a hindsight query and then presented as measured recall.

### Coverage-gap investigation

A bounded request tied to an existing Coverage Gap, suspected missing path or source-portfolio review question. It explores why the portfolio missed a development and what source role may close the gap.

It is retrospective diagnosis, not prospective recall measurement.

### Missed-Planned-occurrence recovery

A bounded request tied to a valid missed or unresolved Planned expectation after the accepted confirmation and failure checks have run.

It may find an occurrence or schedule update. It does not convert a source outage into a clean miss and does not prove cancellation or non-occurrence when it returns nothing.

### Supplemental discovery

A bounded request arising from an accepted Watch Condition, Triage Proposal, Evidence Intake feedback, editor lead or reader lead. It must state the exact public-source question or missing relationship it is trying to resolve.

The result re-enters normal discovery. It cannot be appended directly to a Candidate or Evidence Package.

### Source-outage contingency search

A separately authorised request that may find leads while an Anchor or Complement is unavailable.

Search does not become the failed source, close its Operational Finding or satisfy the affected Active obligation. The outage and coverage risk remain visible. This role is a lead-finding contingency, not silent fallback.

### Manual research search

An authorised operator may run a bounded request for source qualification, source-location or a specific discovery question. Manual execution receives no rights, evidence or workflow bypass and does not automatically create a recurring query.

## Roles that are not accepted

The following are prohibited by this Draft:

- broad generic `UK news`, `Hong Kong news`, `world news` or category firehoses as the primary production clock;
- one recurring search request per content category or beat merely because a schedule fires;
- autonomous recursive searching until the agent is satisfied;
- silent provider switching after failure or budget exhaustion;
- using result count or media volume as newsworthiness or coverage proof;
- treating a zero-result response as no news;
- retaining or redistributing provider result payloads contrary to terms;
- using search-result snippets as central evidence; and
- using a Comparator to conceal a missing Anchor.

## Search records

These are semantic contracts, not required database tables.

### Search Purpose

A stable policy identity for one accepted role, such as prospective outer radar, recall audit, Planned recovery or bounded supplemental discovery. It defines who may trigger the role, permitted coverage, query-data restrictions, budget class and allowed downstream routes.

### Search Request

One immutable, authorised semantic request under one Search Purpose. It includes:

- trigger and requester identity;
- accepted coverage basis or review question;
- provider and exact provider configuration version;
- query template and rendered query;
- language, geography, source-domain and time bounds where applicable;
- result, page, expansion and retry limits;
- rights and query-data classification;
- budget reservation;
- freshness or audit window;
- allowed downstream use; and
- governing policy versions.

Changing the purpose, provider, material query terms, time window or result scope creates a new Request.

### Search Attempt

One execution attempt for one Search Request. Retries create separate Attempts while preserving the Request identity.

### Search Attempt Outcome

An immutable outcome that distinguishes at least:

- successful with zero results;
- successful with one or more results;
- successful but truncated or partial;
- altered or corrected query used by the provider;
- rate limited;
- budget blocked;
- rights or privacy blocked;
- authentication or configuration failure;
- provider or transport failure; and
- cancelled or superseded request.

Zero results, partial response and provider failure are not interchangeable.

### Search Result Reference

A rights-limited, provider-attributed pointer returned by one exact Attempt. Depending on the approved provider terms, it may contain only a transient or retained subset of:

- provider result identifier;
- rank and page;
- returned URL and canonicalisation status;
- publisher or domain;
- title, snippet and provider-asserted date;
- result type and language;
- dependency or duplicate signals; and
- exact Attempt lineage.

A provider rank, snippet or date is attributed provider metadata. It is not the underlying publisher's Source Revision or evidence.

### Search Review Decision

An immutable decision that records whether one or more Result References:

- produce no further work;
- create a bounded publisher Source Check;
- create a normal approved channel-input Signal where permitted;
- relate to an existing Lead, Hypothesis or Candidate;
- support a reviewed Coverage Gap assessment;
- indicate query or provider noise; or
- require rights, source or operational follow-up.

A result does not create a Coverage Gap or Candidate without this review and the accepted downstream workflow.

## Query construction

### Purpose-specific query

Every query must be narrow enough to explain why it exists. Appropriate inputs may include:

- named policy, bill, case, warning, route, service or formal process;
- an exact public entity or official identifier;
- a defined event class and geography;
- a missing Planned occurrence;
- a known source gap;
- an accepted Watch Condition; or
- a pre-registered outer-radar or recall-audit template.

Broad topic terms may appear inside a bounded template, but they cannot be the sole justification for a recurring request.

### Query versions

Query templates, negative terms, domain constraints, language variants, time windows and operator syntax are versioned. Provider spell correction, query alteration and implicit locale behaviour are captured where available.

A query change during an evaluation window creates a new version and cannot be silently compared as if the method were unchanged.

### Multilingual queries

The query plan must state whether English, Hong Kong Traditional Chinese or another language variant is required and whether the provider searches original text or machine-translated coverage.

A provider's cross-language feature is a retrieval property, not proof that all relevant languages or publishers are covered.

### Model-proposed queries

A model may propose query terms only as untrusted output. A deterministic controller validates the role, coverage basis, privacy class, syntax, time bound, provider, expansion count and budget before execution.

Source text and search results are untrusted data and cannot alter search instructions, provider choice, budget or tool authority.

### Query amplification

One Request has enforced limits on:

- query variants;
- language variants;
- pages and results;
- retries;
- follow-up branches;
- time range;
- total provider requests; and
- downstream model work.

A result cannot recursively trigger another search without a new authorised Request or a bounded pre-authorised branch recorded in the original Request.

## Query privacy and safety

Search Query Data leaves the Newsroom trust boundary when sent to an external provider. A Request must not contain:

- private reader or operator data;
- unpublished personal information;
- confidential newsroom notes;
- private document text;
- unverified sensitive allegations framed as facts;
- authentication secrets or internal infrastructure identifiers; or
- more source expression than the approved purpose requires.

Public names, public case identifiers and public allegations may be queried only under a versioned policy appropriate to their sensitivity and legal risk.

Provider query-data terms, retention and processing must be reviewed separately from result-content rights.

## Provider and result rights

### Use-specific provider admission

Each provider version requires an owner-approved record covering:

- query-data processing and retention;
- result storage and caching;
- redistribution and display;
- model submission and use in evaluation;
- attribution;
- underlying third-party content rights;
- rate limits and anti-abuse rules;
- pricing and billing semantics;
- service availability and support; and
- termination or terms-change consequences.

Permission to call an API is not permission to retain its response, build an evaluation corpus, submit results to a model or fetch every linked page.

### Minimum retained data

The system retains only the provider-result data permitted and necessary for workflow, cost and audit. If a provider permits transient processing only, the system may retain the Search Request, Attempt, outcome, cost, counts and later independently obtained publisher records without retaining prohibited result payloads.

A canonical publisher URL or Source Item may be retained only where the applicable provider and publisher rights permit the route by which it was obtained and subsequently checked.

### Underlying publisher boundary

Search-provider permission does not grant rights to the underlying article. Before full retrieval, retention, model submission, quotation or evidence use, the publisher source must pass the normal Source Definition, rights or evidence-acquisition decision.

Search snippets remain lead-only and cannot be combined to reconstruct inaccessible or paywalled content.

## Provider candidates and current interpretation

These are candidate assessments, not provider selection or permission to run queries.

### GDELT DOC 2.0

Proposed role: multilingual media-index radar and Comparator.

The official DOC 2.0 documentation describes JSON and RSS ArticleList output, cross-language search over machine-translated coverage, bounded time ranges and up to 250 ArticleList results. GDELT states that its released datasets may be used without fee, with citation required when used or redistributed ([DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/), [terms](https://www.gdeltproject.org/about.html)).

Limits:

- it is a media index, not an underlying publisher or recall ground truth;
- machine translation, source selection and indexing may introduce noise and omissions;
- returned article rights remain publisher-specific;
- the newsroom-host smoke test returned `429`; and
- it remains Held until reliability and rate behaviour pass Topics 8 and 9.

### Brave Search and News API

Proposed role: paid, bounded web or news search for transient gap, supplemental or audit use where standard or negotiated terms permit.

Brave currently lists Search API pricing at US$5 per 1,000 requests with US$5 monthly credits, and its News endpoint supports bounded language, country, freshness and result-count parameters ([pricing](https://brave.com/search/api/), [News API](https://api-dashboard.search.brave.com/api-reference/news/news_search/get)).

The current standard terms restrict non-transient storage or caching and redistribution of Search Results and prohibit using Search Results to create or evaluate AI models or services ([terms](https://api-dashboard.search.brave.com/app/documentation/general/terms-of-service)). Those restrictions may conflict with a persistent shadow comparator corpus or model-evaluation workflow.

Therefore:

- Brave is **Rights Review Required**, not an approved shadow benchmark provider;
- standard monthly credit does not create authority or an automatic budget;
- any persistent audit, replay or model-evaluation use requires terms that explicitly permit it;
- transient operational use still requires an approved minimal-retention design; and
- Brave cannot be the recurring production clock or silent fallback.

### Self-hosted SearXNG

Proposed role: experimental metasearch adapter for manual or bounded comparison, not an Anchor.

SearXNG is an open-source metasearch engine that aggregates upstream engines and can be self-hosted without storing user search data by design. It does not provide its own independent web index. Its documentation notes that adapters are needed per upstream engine and that automated traffic may cause upstream CAPTCHAs or blocking ([about](https://docs.searxng.org/user/about.html), [engine model](https://docs.searxng.org/dev/engines/engine_overview.html), [limiter](https://docs.searxng.org/admin/searx.limiter.html)).

Therefore self-hosting does not remove upstream terms, result-rights review, source bias, blocking risk or operational cost. It remains a Research candidate until exact engines, rights and reliability are qualified.

### DDGS and other unofficial search wrappers

A wrapper without a contracted search API, stable provider terms and a qualified service boundary is not a production provider. It may be evaluated manually or experimentally under explicit rights and rate controls, but it cannot be an Anchor, silent fallback or assumed free production clock.

## Budget model

### Budget classes

Budgets are separate for:

- prospective outer radar;
- prospective recall audit;
- Coverage Gap investigation;
- Planned recovery;
- supplemental discovery;
- outage contingency; and
- manual research.

Unused budget in one class does not automatically authorise another class.

### Enforced limits

Every provider and Search Purpose has configured limits for:

- requests per operation, day and month;
- gross monetary cost, before credits or discounts;
- concurrent attempts;
- pages and results per Request;
- query and language variants;
- retries and follow-up branches;
- maximum query time range; and
- downstream triage or model work generated from results.

The agent cannot raise, pool or bypass these limits. Credits reduce billing but do not expand the approved gross request budget.

### Urgent reserve

A later policy may establish a small, separately authorised Urgent contingency reserve. It cannot be borrowed for Routine work and does not weaken rights, privacy, query or workflow rules.

### Exhaustion and failure

Budget exhaustion creates a visible blocked outcome. It is not a successful zero-result search, no-news result or permission to switch providers.

Rate limiting, provider outage and authentication failure remain operational outcomes and do not consume the editorial meaning of the Request.

## Result processing

### Normal workflow entry

A permitted result may create:

1. a bounded Check Request for the underlying publisher source; or
2. a search-channel Discovery Signal carrying equivalent identity, version, rights and lineage controls where the provider use is approved.

In either case it proceeds through deterministic gates, Lead triage and evidence acquisition. No result becomes a Candidate or evidence directly.

### Deduplication and dependency

The system may canonicalise URLs and suppress repeated processing while retaining Search Result occurrences and provider lineage.

The same publisher page returned by several queries or providers remains one underlying page, not several independent origins. Several outlets reproducing one wire, press release or originating report remain one dependency for corroboration.

### Provider ranking and dates

Rank, snippet order, provider freshness and provider-asserted dates may guide review only. They do not establish priority, publication time, source change or currentness.

### Partial and truncated results

Pagination limits, capped results, blocked engines, omitted languages and partial provider response remain explicit. A capped result set cannot be described as all matching coverage.

## Coverage audit

### Prospective audit

A prospective audit uses a pre-registered Search Request during a defined period. It records the query version, provider version, time window, result cap and selected discovery portfolio before outcomes are known.

This is the appropriate basis for later quantitative comparison under Topic 8.

### Retrospective gap investigation

A retrospective query begins after a suspected or known miss. It may explain the miss or identify a better source path, but it is not an unbiased recall measurement and must be labelled accordingly.

### Reviewed miss test

Before a search or comparator result becomes a Coverage Gap, review establishes:

- the development was in scope under the accepted contract;
- whether it belonged to Active or Best-effort coverage;
- the relevant event and publication window;
- which selected paths were expected to detect it;
- whether those paths were healthy and authorised;
- whether the comparator result was available within the evaluation window;
- whether the query was prospective or constructed with hindsight;
- whether the result is a duplicate, dependency or later republication;
- whether index delay, query language or source rights affected discovery; and
- whether the miss appears isolated, systemic, expected under Best effort or explained by a deferred gap.

Only a committed review creates a Coverage Gap or Coverage Gap Assessment.

### Search is not recall ground truth

A provider may miss pages, rank them beyond the cap, alter a query, index them late or include irrelevant coverage. Therefore:

- no-result does not prove no relevant development;
- more results do not prove better editorial coverage;
- a result absent from direct watch does not automatically prove a direct-watch defect;
- a result present only after the audit window is not a timely discovery success; and
- one provider cannot certify another system's recall.

Topic 8 must combine prospective comparators with editor-led review and replayable known cases.

### Audit feedback

A reviewed Gap may lead to:

- adding or changing an Anchor or Complement;
- changing an observation model or query template;
- fixing parser, rights or health failure;
- adding a Specialist or local source;
- retaining a bounded search role where it uniquely contributes;
- accepting a Best-effort limitation; or
- recording a launch-blocking Active-coverage deficiency.

Search should repair source selection where possible, not create a permanent generic dependency by default.

## Requirements

### Role and authority

**SRCH-001 — One accepted purpose.** Every Search Request MUST identify one accepted primary Search Purpose.

**SRCH-002 — Search is not an Anchor.** Search or an index MUST NOT be the sole Anchor for an Active coverage obligation or conceal a missing Anchor.

**SRCH-003 — No generic production clock.** Broad generic or one-query-per-beat search MUST NOT become the primary recurring production clock.

**SRCH-004 — Normal workflow.** Search results MUST enter through the accepted identity, Signal, gate, Lead, triage and evidence boundaries.

**SRCH-005 — No evidence authority.** Provider rank, title, snippet, date, generated answer or result count MUST NOT establish a central fact or evidence sufficiency.

**SRCH-006 — No silent fallback.** Provider failure, rate limit, rights block or budget exhaustion MUST NOT silently activate another provider or query.

### Requests, attempts and results

**SRCH-010 — Immutable Request.** Every Request MUST record purpose, trigger, coverage basis, provider version, rendered query, bounds, rights class, budget and governing versions.

**SRCH-011 — Attempt separation.** Retries MUST create separate Attempts and preserve the semantic Request identity.

**SRCH-012 — Outcome distinction.** Zero results, non-zero results, partial or truncated response, altered query, rate limit, budget block and provider failure MUST remain distinct.

**SRCH-013 — Zero results are neutral.** A successful zero-result response MUST NOT prove no news, no occurrence or adequate coverage.

**SRCH-014 — Result attribution.** Every retained Result Reference MUST identify its exact provider Attempt and retain provider metadata as attributed, untrusted data.

**SRCH-015 — Rights-limited retention.** Search result content MUST be retained only to the extent permitted by the provider and necessary for the accepted purpose.

**SRCH-016 — Underlying-source separation.** A Result Reference MUST NOT be represented as the publisher's Source Revision or as permission to retrieve the publisher content.

### Query control and privacy

**SRCH-020 — Purpose-specific query.** Every query MUST be bounded by a specific role, question, coverage basis or pre-registered audit template.

**SRCH-021 — Versioned query method.** Templates, language variants, operators, exclusions, domains and time windows MUST be versioned.

**SRCH-022 — Query alteration visibility.** Provider spell correction, altered query or implicit locale change MUST be recorded where available.

**SRCH-023 — Model proposal only.** A model MAY propose query terms but MUST NOT execute, expand or change provider and budget without deterministic approval.

**SRCH-024 — No private query data.** External queries MUST NOT contain private, confidential or unnecessary sensitive data.

**SRCH-025 — Injection resistance.** Source and result text MUST be treated as data and MUST NOT alter query policy, tools, budget or authority.

**SRCH-026 — Amplification bound.** Query variants, pagination, retries, branches and downstream work MUST have enforced limits.

### Provider, rights and budget

**SRCH-030 — Provider-specific admission.** Each provider version MUST pass rights, query-data, retention, model-use, attribution, cost and operational review.

**SRCH-031 — API permission is use-specific.** Permission to query MUST NOT be treated as permission to persist, evaluate models with, redistribute or submit results to another model.

**SRCH-032 — Gross budget.** Request and cost limits MUST be defined before credits, discounts or free tiers.

**SRCH-033 — Separate budget classes.** Outer radar, audit, gap, Planned recovery, supplemental, outage and manual uses MUST have separate or explicitly allocated budgets.

**SRCH-034 — Agent cannot bypass.** Runtime agents MUST NOT raise budgets, create accounts, split traffic to evade limits or switch to an unapproved provider.

**SRCH-035 — Exhaustion is visible.** Budget exhaustion MUST create a visible blocked outcome and MUST NOT be represented as zero results or no news.

**SRCH-036 — Provider terms change.** A material provider terms, pricing, API or data-use change MUST trigger re-review before continued use under the affected purpose.

### Search roles

**SRCH-040 — Prospective outer radar.** A recurring outer-radar lane MAY be admitted only as a separately budgeted Comparator or Best-effort path after Topics 8 and 9 prove unique contribution and readiness.

**SRCH-041 — Prospective audit pre-registration.** Recall-audit queries and windows MUST be fixed before result review.

**SRCH-042 — Retrospective label.** A query designed after a known miss MUST be labelled gap investigation and MUST NOT be reported as prospective recall measurement.

**SRCH-043 — Planned recovery preconditions.** Missed-occurrence recovery MAY run only after accepted Agenda, grace, confirmation and source-failure checks.

**SRCH-044 — Supplemental request bound.** Triage, Watch or Evidence feedback search MUST state the exact bounded public-source question and re-enter normal workflow.

**SRCH-045 — Outage does not transfer coverage.** Search during source outage MUST NOT close the outage or satisfy the failed Anchor's coverage obligation.

### Coverage audit

**CAUD-001 — Comparator is not ground truth.** No search provider, media index or feed is recall ground truth.

**CAUD-002 — Reviewed Gap only.** A result becomes a Coverage Gap only after a committed relevance, timing, expected-path and miss review.

**CAUD-003 — Prospective and retrospective separation.** Audit records MUST distinguish pre-registered comparison from hindsight investigation.

**CAUD-004 — Timeliness.** A result available only after the evaluation window MUST NOT count as timely comparator discovery.

**CAUD-005 — Dependency review.** Duplicate, wire, press-release, editorial-selection and later-republication dependencies MUST be considered before interpreting a miss.

**CAUD-006 — Health context.** Gap review MUST include direct-path health, rights, configuration and operational state.

**CAUD-007 — Isolated and systemic assessment.** Gap assessment MUST distinguish isolated, systemic, expected Best-effort and accepted deferred-gap outcomes.

**CAUD-008 — No-result neutrality.** Search failure or no results MUST NOT be interpreted as adequate portfolio recall.

**CAUD-009 — Remediation preference.** A reviewed Gap SHOULD improve direct source roles, adapters or workflow where feasible rather than defaulting to permanent broad search.

### Candidate providers

**SRCH-050 — GDELT candidate status.** GDELT remains a Held media-index Comparator candidate until rate behaviour, attribution, noise and shadow contribution pass review.

**SRCH-051 — Brave rights status.** Brave remains Rights Review Required; standard terms MUST NOT be assumed to permit persistent shadow corpora or model evaluation.

**SRCH-052 — SearXNG status.** Self-hosted SearXNG remains a Research candidate and MUST NOT be treated as an independent index, SLA or rights solution.

**SRCH-053 — Unofficial wrappers.** An unofficial or non-contracted wrapper MUST NOT become a production provider without explicit provider, terms, rate and reliability qualification.

## Acceptance criteria

1. A generic hourly `UK news` query cannot be configured as an Active-coverage Anchor.
2. A pre-registered daily audit query is distinguishable from a query written after a known miss.
3. A zero-result response creates no conclusion that no relevant event occurred.
4. Provider timeout and rate limit remain failures rather than zero results.
5. Search during an Anchor outage may find a Lead but cannot close the outage or claim the obligation is covered.
6. A search snippet can trigger a publisher check but cannot enter an Evidence Package.
7. The same publisher URL returned by several queries is not counted as several independent origins.
8. Query spell correction or alteration is captured and cannot be silently compared with an earlier method.
9. A model-proposed query cannot execute until purpose, privacy, provider and budget validation pass.
10. One result cannot trigger unbounded recursive searching.
11. Budget exhaustion is visible and cannot switch providers or weaken controls.
12. Brave standard terms are not used to build a persistent evaluation corpus without separately approved permission.
13. GDELT data use retains required attribution, while underlying publisher rights remain separate.
14. A self-hosted SearXNG instance is not assumed to eliminate upstream CAPTCHA, blocking or terms risk.
15. A comparator hit creates no Coverage Gap until relevance, timing, expected paths and health are reviewed.
16. A later-indexed article outside the audit window does not count as timely discovery.
17. Topic 8 can measure unique incremental value by Search Purpose and provider without treating any provider as ground truth.
18. No query, spending or provider account is authorised merely by accepting this specification.

## Owner decisions required to complete Topic 7

The Draft recommends these decisions:

1. Accept that search and media indexes are supplemental discovery channels and Comparators, never the sole Anchor for an Active obligation or the primary generic production clock.
2. Accept the seven bounded roles: prospective outer radar, prospective recall-audit comparator, Coverage Gap investigation, missed-Planned-occurrence recovery, supplemental discovery, source-outage contingency search and manual research search.
3. Accept that a recurring outer-radar search lane is initially Comparator or Best-effort only and may enter production only after Topic 8 proves unique contribution and Topic 9 qualifies rights, reliability and cost.
4. Accept Search Purpose, Request, Attempt, Outcome, Result Reference and Review Decision as conceptual records, with zero results, partial output, rate limits and failure kept distinct.
5. Accept purpose-specific, versioned queries with explicit language, geography, time, result and expansion bounds; broad one-query-per-beat polling and recursive agent search are prohibited.
6. Accept that models may propose but cannot execute or expand queries, and that external query data excludes private, confidential and unnecessary sensitive information.
7. Accept provider-specific rights and query-data review, minimum permitted retention and a separate underlying-publisher rights check before retrieval or evidence use.
8. Accept hard gross request, cost, pagination, expansion, retry and downstream-work budgets by Search Purpose, with visible exhaustion and no silent provider switching.
9. Accept that Search Results enter the normal Signal-to-Candidate workflow, provider rank and snippets are non-authoritative and duplicate or shared-origin results do not multiply independence.
10. Accept prospective versus retrospective audit separation and require a committed relevance, timing, expected-path and health review before creating a Coverage Gap.
11. Accept that search or index results are not recall ground truth, zero results are neutral and source improvement is preferred over permanent generic search after a reviewed Gap.
12. Accept GDELT as a Held media-index Comparator candidate, subject to rate, noise, attribution, shadow and operational qualification.
13. Accept Brave as Rights Review Required rather than an approved persistent shadow comparator because current standard terms restrict result storage and AI-model evaluation; any approved use must be scoped to permitted retention and terms.
14. Accept self-hosted SearXNG and unofficial wrappers as Research candidates only, not independent indexes, Anchors, SLAs or automatic free production fallbacks.
15. Accept that Topic 7 authorises no provider, query schedule, spending or run; final provider admission follows Topic 8 evidence and Topic 9 readiness.
