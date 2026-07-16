# Discovery search and coverage-audit specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Accepted by owner:** 2026-07-15  
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
**Implementation authority:** None. Acceptance defines search roles, records, budgets and coverage-audit semantics; it authorises no provider, query, account, spending, shadow operation or production use.  
**Supersedes:** None

## Purpose

Define the limited roles that web search and media indexes may play in discovery, the controls on every query and result, and how search-assisted coverage auditing may identify real omissions without treating another index as ground truth.

The contract preserves the recall value of search without allowing a generic query loop to become the Newsroom's implicit coverage model, recurring primary clock, evidence source, silent fallback or uncontrolled cost centre.

## Scope

This specification defines:

- permitted search and index roles;
- prospective outer-radar and recall-audit boundaries;
- bounded gap, missed-Planned-occurrence, supplemental, outage and manual searches;
- Search Purpose, Request, Attempt, Outcome, Result Reference and Review Decision semantics;
- query construction, privacy, injection and amplification controls;
- provider rights, retention, model-use and operational admission;
- request, result, cost and downstream-work budgets;
- result deduplication, dependency and normal workflow entry;
- prospective versus retrospective coverage audit;
- Coverage Gap review and interpretation; and
- the current candidate status of GDELT, Brave, SearXNG and unofficial wrappers.

It does not define the Topic 8 shadow protocol and thresholds, Topic 9 schedules and provider failover, Topic 10 reason vocabulary, Topic 11 locality expansion, evidence extraction, implementation, credentials, billing accounts or physical schema.

## Search boundary

Search is an index-mediated discovery channel. It is not:

- the sole Anchor for an Active coverage obligation;
- the primary generic production clock;
- proof that an event exists or does not exist;
- proof that a returned page is current or accurate;
- an Evidence Package;
- an automatic replacement for a failed direct source;
- a measure of independent source count;
- permission to retrieve, retain or submit an underlying page to a model; or
- permission for an agent to invent recurring or recursive queries.

A permitted search result enters the accepted identity, Signal, gate, Lead, triage and evidence boundaries. It receives no Candidate or evidence bypass.

## Accepted Search Purposes

Every Search Request has exactly one primary purpose.

### Prospective outer radar

A bounded, pre-authorised query or media-index lane intended to find important in-scope developments outside the registered portfolio.

Its initial status is Comparator or Best-effort only. It does not repair a missing Active Anchor and does not run one generic query per beat. A recurring production role requires Topic 8 evidence of unique contribution and Topic 9 qualification of rights, reliability and cost.

### Prospective recall-audit comparator

A pre-registered, time-bounded comparison whose query, time range, provider version, result cap and portfolio version are fixed before results are reviewed.

### Coverage Gap investigation

A retrospective, bounded request tied to an existing Gap, suspected missing path or source-portfolio question. It may diagnose a miss but is not prospective recall measurement.

### Missed-Planned-occurrence recovery

A bounded request tied to a valid missed or unresolved Planned expectation after the accepted Agenda, grace, confirmation and source-failure checks run.

It may find an occurrence or schedule update. No result does not prove cancellation, delay or non-occurrence.

### Supplemental discovery

A bounded request arising from a Watch Condition, Triage Proposal, Evidence Intake feedback, editor lead or reader lead. It states one exact public-source question and re-enters normal discovery.

### Source-outage contingency search

A separately authorised lead-finding request while an Anchor or Complement is unavailable. It does not become the failed source, close its Operational Finding or satisfy the affected Active obligation.

### Manual research search

A bounded operator request for source qualification, source location or a specific discovery question. One useful manual search does not create a recurring query.

## Prohibited roles

The following are prohibited:

- generic `UK news`, `Hong Kong news`, `world news` or category firehoses as the primary clock;
- one recurring search per beat merely because a schedule fires;
- autonomous recursive search until an agent is satisfied;
- silent provider switching after failure or budget exhaustion;
- using result count or media volume as newsworthiness or coverage proof;
- treating zero results as no news;
- retaining, redistributing or submitting results contrary to provider terms;
- using snippets as central evidence; and
- using a Comparator to conceal a missing Anchor.

## Search records

These are semantic contracts, not required database tables.

### Search Purpose

A stable policy identity defining the accepted role, authorised triggers, permitted coverage, query-data restrictions, budget class and downstream routes.

### Search Request

One immutable semantic request containing:

- trigger and requester identity;
- accepted purpose, coverage basis or review question;
- provider and provider-configuration version;
- query template and rendered query;
- language, geography, domain and time bounds where applicable;
- result, page, variant, expansion and retry limits;
- rights and query-data classification;
- budget reservation;
- freshness or audit window;
- allowed downstream use; and
- governing policy versions.

Changing purpose, provider, material terms, time window or result scope creates a new Request.

### Search Attempt and Outcome

Each execution is a separate Attempt. Its immutable Outcome distinguishes:

- successful with zero results;
- successful with one or more results;
- successful but partial or truncated;
- provider-altered or corrected query;
- rate limited;
- budget blocked;
- rights or privacy blocked;
- authentication or configuration failure;
- provider or transport failure; and
- cancelled or superseded request.

Zero results, partial output and failure are not interchangeable.

### Search Result Reference

A rights-limited, provider-attributed pointer tied to one Attempt. Depending on approved terms, it may retain only a subset of provider ID, rank, page, URL, publisher, title, snippet, asserted date, language, result type, dependency signals and lineage.

Provider rank, snippet and date are untrusted provider metadata. They are not the publisher's Source Revision or evidence.

### Search Review Decision

An immutable decision that records whether Result References:

- produce no work;
- create a bounded publisher Source Check;
- create a permitted search-channel Signal;
- relate to an existing Lead, Hypothesis or Candidate;
- support a reviewed Coverage Gap assessment;
- indicate query or provider noise; or
- require rights, source or operational follow-up.

## Query control

Every query is purpose-specific and versioned. Appropriate inputs include a named policy, bill, case, warning, route, service, formal identifier, missing Planned occurrence, accepted Gap, Watch Condition or pre-registered audit template.

Broad terms may appear inside a bounded template but cannot alone justify recurrence. English, Hong Kong Traditional Chinese and other language variants are declared explicitly; cross-language provider features are retrieval properties, not completeness claims.

A model may propose query terms only. A deterministic controller validates purpose, coverage, privacy, syntax, time range, provider, expansion and budget before execution.

Every Request has hard limits on variants, languages, pages, results, retries, branches, time range, provider calls and downstream model work. A result cannot recursively search again without a new authorised Request or an explicitly bounded branch.

## Query privacy and safety

External query data must not contain:

- private reader or operator data;
- unpublished personal information;
- confidential notes or private document text;
- secrets or internal infrastructure identifiers;
- unverified sensitive allegations framed as facts; or
- more source expression than the purpose requires.

Public names, public identifiers and public allegations require an appropriate versioned sensitivity policy. Retrieved text is untrusted data and cannot alter query policy, tools, budget or authority.

## Provider and result rights

Each provider version requires owner-approved review of:

- query-data processing and retention;
- result storage and caching;
- redistribution and display;
- model submission and evaluation use;
- attribution;
- underlying third-party rights;
- rate and anti-abuse rules;
- pricing and billing;
- availability and support; and
- terms-change or termination consequences.

Permission to call an API is not permission to retain its results, build a corpus, evaluate a model, redistribute content or fetch every linked page.

Only the minimum permitted result data is retained. Provider permission never grants rights to the underlying publisher page. Snippets remain lead-only and cannot reconstruct inaccessible or paywalled content.

## Provider candidate status

### GDELT DOC 2.0

GDELT is a Held multilingual media-index Comparator candidate. It is not a publisher or recall ground truth; machine translation, source selection and indexing may create noise and omissions; underlying publisher rights remain separate; and the newsroom-host smoke test returned `429`.

Its rate behaviour, attribution, noise, unique contribution and reliability must pass Topics 8 and 9.

### Brave Search and News API

Brave is Rights Review Required for bounded, transient gap, supplemental or audit use. Current standard terms must not be assumed to permit persistent result storage, a shadow corpus or AI-model evaluation.

Monthly credits do not create authority or expand the approved gross budget. Any use requires approved terms, retention, model-destination and audit handling. Brave is not the recurring primary clock or silent fallback.

### Self-hosted SearXNG

SearXNG remains a Research candidate. Self-hosting does not create an independent index, remove upstream terms, prevent CAPTCHA or blocking, or provide an SLA.

### DDGS and unofficial wrappers

A wrapper without a contracted provider boundary and stable terms is not production-ready. It cannot be an Anchor, silent fallback or assumed free clock.

## Budget model

Budget classes are separate for outer radar, prospective audit, Gap investigation, Planned recovery, supplemental discovery, outage contingency and manual research.

Each provider and Purpose has hard limits on:

- requests per operation, day and month;
- gross cost before credits or discounts;
- concurrent attempts;
- pages and results;
- language and query variants;
- retries and branches;
- maximum time range; and
- downstream triage or model work.

Runtime agents cannot raise, pool, evade or transfer these limits. Budget exhaustion is a visible blocked outcome, not zero results, no news or permission to switch providers. A later Urgent reserve must be separately authorised and cannot be borrowed for Routine work.

## Result processing

A permitted result may create a publisher Check Request or a search-channel Signal where approved. In both cases it passes normal gates, triage and evidence acquisition.

Canonicalisation may suppress repeated processing while retaining provider lineage. One publisher page returned by several queries remains one underlying page. Several outlets reproducing one wire, press release or origin remain one dependency.

Rank, snippet order, provider freshness and asserted dates guide review only. Partial, capped, blocked-engine and omitted-language results remain explicit and cannot be described as complete.

## Coverage audit

### Prospective audit

The query method, provider, time window, result cap and portfolio version are pre-registered before outcomes are known. This is the appropriate basis for Topic 8 quantitative comparison.

### Retrospective investigation

A query designed after a suspected or known miss may diagnose the failure or identify a better path but is labelled retrospective and is not unbiased recall measurement.

### Reviewed miss test

Before a Result Reference becomes a Coverage Gap, review establishes:

- in-scope relevance and Active or Best-effort class;
- event and publication window;
- expected selected paths;
- health, rights and authorisation of those paths;
- comparator availability within the evaluation window;
- prospective or hindsight query status;
- duplicate, wire, press-release, editorial-selection or later-republication dependency;
- language, indexing and rights effects; and
- isolated, systemic, expected Best-effort or deferred-gap interpretation.

No provider is recall ground truth. Zero results do not prove adequate portfolio recall, more results do not prove better coverage, and late-indexed results do not count as timely discovery.

Reviewed Gaps should improve direct sources, adapters or workflow where feasible rather than create permanent generic search dependency by default.

## Requirements

### Role and authority

**SRCH-001 — One accepted purpose.** Every Search Request MUST identify one accepted primary Search Purpose.

**SRCH-002 — Search is not an Anchor.** Search or an index MUST NOT be the sole Anchor for an Active obligation or conceal a missing Anchor.

**SRCH-003 — No generic production clock.** Broad generic or one-query-per-beat search MUST NOT become the primary recurring clock.

**SRCH-004 — Normal workflow.** Results MUST enter through accepted identity, Signal, gate, Lead, triage and evidence boundaries.

**SRCH-005 — No evidence authority.** Rank, title, snippet, date, generated answer and count MUST NOT establish a central fact or evidence sufficiency.

**SRCH-006 — No silent fallback.** Failure, rate limit, rights block or budget exhaustion MUST NOT silently activate another provider or query.

### Requests, attempts and results

**SRCH-010 — Immutable Request.** Every Request MUST record purpose, trigger, coverage, provider version, query, bounds, rights, budget and governing versions.

**SRCH-011 — Attempt separation.** Retries MUST create separate Attempts and preserve Request identity.

**SRCH-012 — Outcome distinction.** Zero, non-zero, partial, altered-query, rate-limit, budget-block and failure outcomes MUST remain distinct.

**SRCH-013 — Zero results are neutral.** Zero results MUST NOT prove no news, no occurrence or adequate coverage.

**SRCH-014 — Result attribution.** Every retained Result Reference MUST identify its exact Attempt and retain provider metadata as attributed, untrusted data.

**SRCH-015 — Rights-limited retention.** Result content MUST be retained only as permitted and necessary.

**SRCH-016 — Underlying-source separation.** A Result Reference MUST NOT be represented as a publisher Source Revision or permission to retrieve publisher content.

### Query control and privacy

**SRCH-020 — Purpose-specific query.** Every query MUST be bounded by a specific role, question, coverage basis or pre-registered template.

**SRCH-021 — Versioned query method.** Templates, languages, operators, exclusions, domains and windows MUST be versioned.

**SRCH-022 — Query alteration visibility.** Provider spell correction, query alteration and locale change MUST be recorded where available.

**SRCH-023 — Model proposal only.** A model MAY propose terms but MUST NOT execute, expand or change provider or budget without deterministic approval.

**SRCH-024 — No private query data.** External queries MUST NOT contain private, confidential or unnecessary sensitive data.

**SRCH-025 — Injection resistance.** Result text MUST NOT alter policy, tools, budget or authority.

**SRCH-026 — Amplification bound.** Variants, pagination, retries, branches and downstream work MUST have enforced limits.

### Provider, rights and budget

**SRCH-030 — Provider-specific admission.** Each provider version MUST pass rights, query-data, retention, model-use, attribution, cost and operational review.

**SRCH-031 — API permission is use-specific.** Query permission MUST NOT be treated as permission to persist, evaluate, redistribute or submit results elsewhere.

**SRCH-032 — Gross budget.** Limits MUST be defined before credits, discounts or free tiers.

**SRCH-033 — Separate budget classes.** Search roles MUST have separate or explicitly allocated budgets.

**SRCH-034 — Agent cannot bypass.** Runtime agents MUST NOT raise budgets, create accounts, split traffic or switch to an unapproved provider.

**SRCH-035 — Exhaustion is visible.** Exhaustion MUST be visible and MUST NOT become zero results or no news.

**SRCH-036 — Provider terms change.** Material terms, pricing, API or data-use change MUST trigger re-review.

### Search roles

**SRCH-040 — Prospective outer radar.** Recurring outer radar MAY be admitted only as a budgeted Comparator or Best-effort path after Topics 8 and 9 prove contribution and readiness.

**SRCH-041 — Prospective audit pre-registration.** Audit queries and windows MUST be fixed before result review.

**SRCH-042 — Retrospective label.** A hindsight query MUST be labelled Gap investigation and MUST NOT be reported as prospective recall.

**SRCH-043 — Planned recovery preconditions.** Planned recovery MAY run only after accepted Agenda, grace, confirmation and failure checks.

**SRCH-044 — Supplemental request bound.** Supplemental search MUST state the exact public-source question and re-enter normal workflow.

**SRCH-045 — Outage does not transfer coverage.** Search during outage MUST NOT close the outage or satisfy the failed Anchor obligation.

### Coverage audit

**CAUD-001 — Comparator is not ground truth.** No search provider, media index or feed is recall ground truth.

**CAUD-002 — Reviewed Gap only.** A result becomes a Gap only after committed relevance, timing, expected-path and miss review.

**CAUD-003 — Prospective and retrospective separation.** Audit records MUST distinguish pre-registered comparison from hindsight investigation.

**CAUD-004 — Timeliness.** A result available only after the window MUST NOT count as timely discovery.

**CAUD-005 — Dependency review.** Duplicate, wire, press-release, editorial-selection and later-republication dependencies MUST be considered.

**CAUD-006 — Health context.** Gap review MUST include direct-path health, rights, configuration and operational state.

**CAUD-007 — Isolated and systemic assessment.** Assessment MUST distinguish isolated, systemic, expected Best-effort and deferred-gap outcomes.

**CAUD-008 — No-result neutrality.** Failure or zero results MUST NOT be interpreted as adequate portfolio recall.

**CAUD-009 — Remediation preference.** Reviewed Gaps SHOULD improve direct source roles, adapters or workflow where feasible.

### Candidate providers

**SRCH-050 — GDELT candidate status.** GDELT remains a Held Comparator until rate behaviour, attribution, noise, shadow contribution and operations pass review.

**SRCH-051 — Brave rights status.** Brave remains Rights Review Required; standard terms MUST NOT be assumed to permit persistent corpora or model evaluation.

**SRCH-052 — SearXNG status.** SearXNG remains Research and MUST NOT be treated as an independent index, SLA or rights solution.

**SRCH-053 — Unofficial wrappers.** A non-contracted wrapper MUST NOT become production without provider, terms, rate and reliability qualification.

## Acceptance criteria

1. A generic hourly `UK news` query cannot be an Active Anchor.
2. A pre-registered audit is distinguishable from a hindsight query.
3. Zero results create no conclusion that no event occurred.
4. Timeout and rate limit remain failures.
5. Outage search may find a Lead but cannot close the outage or satisfy coverage.
6. A snippet may trigger a publisher check but cannot enter evidence.
7. Repeated provider or query results do not multiply independent origins.
8. Provider query alteration remains visible.
9. A model-proposed query cannot execute before deterministic validation.
10. One result cannot trigger unbounded recursive search.
11. Budget exhaustion cannot switch provider or weaken controls.
12. Brave standard terms are not used for a persistent evaluation corpus without approved permission.
13. GDELT attribution is preserved and publisher rights remain separate.
14. SearXNG is not assumed to remove upstream blocking or terms risk.
15. A comparator hit creates no Gap without review.
16. A late-indexed result is not timely discovery.
17. Topic 8 can measure incremental value by Purpose and provider without treating one as truth.
18. Acceptance authorises no query, account, spending or run.

## Completion record

The product owner accepted this specification on 2026-07-15 with these decisions:

- search and media indexes are supplemental channels and Comparators, never the sole Active Anchor or primary generic clock;
- accepted bounded roles are outer radar, recall audit, Gap investigation, Planned recovery, supplemental discovery, outage contingency and manual research;
- recurring outer radar starts as Comparator or Best-effort and requires Topic 8 contribution evidence and Topic 9 readiness before production;
- Search Purpose, Request, Attempt, Outcome, Result Reference and Review Decision are separate records, and zero, partial, rate-limit and failure outcomes remain distinct;
- queries are purpose-specific, versioned and bounded; one-query-per-beat and recursive agent search are prohibited;
- models may propose but not execute or expand queries, and external query data excludes private, confidential and unnecessary sensitive information;
- provider rights, query-data handling, result retention and underlying publisher rights are reviewed separately;
- gross request, cost, pagination, expansion, retry and downstream-work budgets are hard, purpose-specific and cannot trigger silent provider switching;
- results enter the normal workflow, ranks and snippets are non-authoritative, and duplicate or shared-origin results do not multiply independence;
- prospective and retrospective audit remain separate, and a Coverage Gap requires committed relevance, timing, expected-path and health review;
- search is not recall ground truth, zero results are neutral and direct-source or workflow improvement is preferred after a reviewed Gap;
- GDELT is a Held media-index Comparator candidate;
- Brave is Rights Review Required rather than an approved persistent shadow comparator under assumed standard terms;
- SearXNG and unofficial wrappers remain Research candidates rather than independent indexes, Anchors, SLAs or free fallbacks; and
- Topic 7 authorises no provider, schedule, spending or run. Final admission follows Topic 8 evidence and Topic 9 readiness.
