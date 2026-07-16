# Discovery locality scope and expansion specification

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Accepted record semantics:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Accepted source roles:** [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md)  
**Accepted change semantics:** [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md)  
**Accepted triage contract:** [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md)  
**Accepted search contract:** [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md)  
**Accepted evaluation contract:** [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md)  
**Accepted operations contract:** [`discovery-reliability-and-operations.md`](discovery-reliability-and-operations.md)  
**Accepted outcome contract:** [`discovery-prioritisation-and-outcomes.md`](discovery-prioritisation-and-outcomes.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Decision state:** The launch locality boundary, locality records, event-scoped watch and evidence-based expansion rules below are proposals. Committing this Draft does not select a locality, activate a local source, create a coverage promise, authorise a run or change product navigation.  
**Supersedes:** None

## Purpose

Define how UK local developments remain discoverable without claiming that the launch system systematically monitors every council, NHS body, police force, school, court, utility, transport operator or local publication.

The specification separates:

- an evidence-supported locality label on a story;
- a material local event found through any permitted path;
- a bounded event-scoped local watch;
- a selected locality and source-class monitoring portfolio; and
- a public promise of systematic locality coverage.

These are not equivalent.

## Scope

This specification defines:

- the initial UK locality coverage boundary;
- the distinction between nation-level and local coverage;
- locality and service-boundary identity;
- selected locality and source-class scope;
- event-scoped local monitoring;
- evidence-based locality proposal, evaluation, admission and retirement;
- privacy, fairness, materiality and disclosure controls; and
- the treatment of Hong Kong district information and global locations.

It does not define:

- a final list of councils, cities, police forces, health bodies or operators;
- source endpoints, polling intervals, budgets or parser implementation;
- reader geolocation or personalised local feeds;
- publication prominence or notification targeting;
- administrative-boundary data provider selection; or
- physical storage or migration.

Actual selected localities, source classes and quantitative admission thresholds remain **Needs experiment** until owner-approved evaluation and operational evidence exists.

## Accepted baseline carried forward

The Accepted coverage contract already establishes:

- qualifying UK-wide and England-, Scotland-, Wales- and Northern-Ireland-level developments are Active for the accepted subject classes;
- material local UK developments remain within product scope;
- exhaustive local-source monitoring is an explicit deferred gap;
- no locality is mandatory at launch under Topic 1;
- a local story may proceed normally when found; and
- Hong Kong is one geography and does not promise district-level completeness.

Topic 11 must therefore make the deferred boundary explicit without either silently broadening it or treating all local news as out of scope.

## Core distinctions

### A local story is not a locality promise

A Story Candidate may carry an evidence-supported city, county, borough, council or other locality even when the Newsroom does not systematically monitor that place.

Publishing one story about Leeds, Glasgow or Croydon does not imply complete or recurring coverage of that locality.

### Nation-level is not local

England, Scotland, Wales and Northern Ireland are accepted nation-level geographies. Explicit paths for their Active obligations are required independently of Topic 11.

Failure to select local councils or cities does not defer nation-level coverage.

### Localised national sources are not locality-complete portfolios

A national or nation-level source may emit geographically specific warnings or service states across many places, such as severe-weather, flood, strategic-road or nationally managed infrastructure alerts.

Such a source may support an accepted event class across its declared scope. It does not establish systematic coverage of every local policy, school, health body, council service, police incident or transport operator in the same places.

### Locality label is not service boundary

A city name, postcode, council area, police-force area, NHS geography, transport network, utility region and court circuit may overlap without being identical.

The system must retain the exact boundary or service scope relevant to the source and must not silently infer one from another.

### Event-scoped watch is not permanent selection

A clearly major incident may justify bounded monitoring of the responsible local authorities, operators and established local media for that event.

That temporary watch does not create an ongoing locality portfolio or public completeness promise.

### A selected locality is not all local news

A locality may be selected for one or more source classes or coverage obligations. Selection of a council feed does not automatically select local policing, health, schools, transport, utilities, courts or media.

## Proposed initial launch boundary

The proposed launch posture is **locality-aware and locality-uncommitted**:

1. No fixed UK city, county, borough, council area or service region is promised systematic all-topic local monitoring at initial launch.
2. No local source class is enabled merely to claim that local news is covered.
3. Material local events found through national or nation-level sources, established media radar, approved search, manual or reader leads, or event-scoped checks remain eligible for normal Signal-to-Candidate workflow.
4. Nationally scoped sources that emit localised warnings or incidents may serve their accepted event-class obligations without creating a broad locality promise.
5. Any permanent locality or source-class addition requires a separate, versioned Locality Coverage Decision after the accepted source, evaluation and operational gates.
6. Launch documentation must state that systematic UK locality completeness remains deferred unless an exact selected scope is later accepted.

This posture avoids an arbitrary London-first or city-popularity assumption while preserving the product's ability to report material local news wherever it occurs.

## Locality semantic records

These are conceptual contracts, not required database tables.

### Locality Reference

A stable internal reference to a geographic or service area. It records:

- locality type, such as city, county, borough, council, combined authority or service area;
- canonical name and recognised aliases;
- parent geography where applicable;
- authoritative boundary or service-definition source;
- boundary version and validity period;
- known overlaps or non-nesting relationships; and
- uncertainty or disputed scope.

A name alone is not sufficient identity.

### Locality Coverage Unit

One exact proposed or selected combination of:

- Locality Reference and boundary version;
- coverage obligations or Best-effort classes;
- local source classes;
- population, service or event scope;
- languages where relevant;
- source roles and portfolio functions;
- exclusions and known gaps; and
- governing evaluation and Operational Profile versions.

A Coverage Unit is deliberately narrower than “all news in this place”.

### Locality Source-Class Scope

The local institutional or radar class included in one Coverage Unit. Proposed classes are:

1. local government and combined-authority decisions;
2. NHS, public-health and local healthcare bodies;
3. police, fire, resilience and public-safety authorities;
4. schools, education authorities and major campuses;
5. local and regional transport operators;
6. utilities, infrastructure and environmental services;
7. courts, planning, housing and building-safety bodies where an accepted public interface exists; and
8. established local or community media radar.

Each class is admitted separately. A source that republishes another origin retains that dependency.

### Locality Coverage Proposal

An immutable proposal that identifies:

- the exact Coverage Unit;
- the accepted coverage or Gap basis;
- why a permanent portfolio is preferable to event-scoped or Best-effort discovery;
- candidate source roles and dependencies;
- expected unique or earlier detections;
- rights, technical, cost and operational assumptions;
- privacy-safe audience or need evidence where used;
- evaluation design and required slices;
- alternatives considered; and
- the consequence of not selecting the locality or class.

### Locality Coverage Decision

An owner decision for an exact Coverage Unit and version. Possible semantic decisions include:

- not selected;
- Research or qualification candidate;
- evaluation-only or Comparator-only;
- selected for systematic monitoring within an exact scope;
- selected with an explicit deferred sub-gap;
- temporarily paused or operationally degraded;
- retired; or
- rejected.

Selection does not itself activate sources. Source and operational activation remain separate.

### Event-Scoped Local Watch

A bounded monitoring decision tied to one exact Event Hypothesis, Lead, Candidate or major incident question. It records:

- triggering event and coverage basis;
- locality and service boundaries;
- exact sources or source classes;
- permitted purpose and expected transitions;
- start, review and expiry conditions;
- rights, request and cost limits;
- owner and Operational Profile; and
- closure or conversion criteria.

Its default outcome at expiry is closure, not permanent locality selection.

### Locality Coverage Assessment

A rebuildable, versioned view of what locality and source-class scopes are selected, evaluated, deferred, degraded or unavailable. It remains separate from individual source health and from story geography labels.

## Boundary and location rules

### Evidence-supported precision

A Signal, Lead, Candidate or Story may use only the most specific location supported by permitted source material. The system must not infer a council, borough, postcode, campus or service area from a nearby city name.

### Multiple applicable geographies

One event may carry several supported references, such as:

- a council area where a decision was made;
- a wider transport network affected;
- a nation-level policy basis; and
- the UK label required by the product taxonomy.

These relationships remain explicit rather than flattened into one place string.

### Boundary versions

Administrative and service boundaries change. A Locality Coverage Unit and source mapping must identify the boundary version used. Boundary change creates later configuration and assessment rather than rewriting historical stories or decisions.

### Boundary ambiguity

When source scope and event location cannot be mapped defensibly, the system retains broader geography or explicit ambiguity. It must not guess precision to make local filtering appear complete.

## Local materiality and editorial boundary

Locality does not lower the accepted newsworthiness threshold.

Potentially qualifying local developments include:

- authoritative public-safety warning or clearly major incident;
- material disruption to an essential local service or route;
- actionable council, school, health, housing, planning, utility or support change affecting a meaningful group;
- building-safety, environmental, consumer or public-health warning;
- local democratic, court or civil-rights outcome with substantive public consequence; or
- a local development that creates a material UK–Hong Kong family or travel effect.

Ordinary local noise remains excluded, including routine meeting notices, minor roadworks, isolated delays, ordinary event listings, small administrative updates, promotional material and crime-roundup volume without a qualifying public impact.

A local source's output volume cannot create materiality.

## Event-scoped local watch

### Permitted triggers

A bounded watch may be proposed after:

- an authoritative major warning or incident;
- an established-media or reader Lead that plausibly meets Active or Best-effort materiality;
- an existing Candidate requiring local state transitions;
- a Watch Condition requiring a responsible local source; or
- Evidence Intake feedback requesting one bounded public-source question.

### Limits

An Event-Scoped Local Watch:

- uses the normal source, rights, operational, Signal and triage boundaries;
- has an exact event purpose and expiry;
- cannot become recursive whole-locality crawling;
- cannot silently add unrelated local stories to the Candidate;
- cannot bypass evidence acquisition;
- cannot imply that the locality is systematically covered; and
- cannot convert one useful source into a recurring portfolio without a Locality Coverage Proposal and Decision.

### Conversion to permanent coverage

Repeated event-scoped watches may provide evidence for permanent selection. Conversion still requires Topic 8 evaluation, Topic 9 qualification and owner approval; repeated manual use alone is not authority.

## Evidence-based selection and expansion

A permanent Locality Coverage Proposal may be justified by a combination of:

- repeated reviewed Coverage Gaps in one locality or source class;
- an Active obligation lacking an adequate path for a materially affected population;
- unique or materially earlier detections during prospective evaluation;
- a recurring pattern of material local events relevant to the audience;
- privacy-safe, aggregated audience need evidence;
- a distinct resilience or failure mode not supplied by national paths;
- a necessary responsible-operator, Agenda or occurrence-confirmation path;
- acceptable rights, technical and operational readiness;
- manageable noise, cost, review burden and amplification; and
- reasonable geographic and community representation within the product strategy.

No one factor is sufficient by itself.

### Prohibited selection shortcuts

A locality or source class must not be selected solely because:

- an RSS feed or API exists;
- it is London or another large or famous city;
- it has the largest population;
- one viral or tragic event occurred;
- it generates many articles or social reactions;
- a publisher offers convenient access;
- individual readers' addresses or identifiable location history are available;
- a category quota needs filling; or
- the system wants to claim UK-local completeness.

### Privacy-safe audience evidence

Audience distribution MAY inform a proposal only through aggregated, minimised and policy-approved data. Individual addresses, precise reader locations or small identifiable cohorts must not enter source selection or external queries.

## Qualification and admission path

A selected systematic Locality Coverage Unit progresses through:

```text
Coverage or Gap basis
→ Locality Coverage Proposal
→ source-role and rights qualification
→ fixtures and replay
→ prospective evaluation and source contribution review
→ Operational Profiles and capacity evidence
→ Locality Coverage Decision
→ source-specific admission and canary
→ separate activation decision
```

The decision must identify exact sources, source classes, obligations, boundaries, languages, expected gaps, operational objectives, alerts, runbooks, rollback and disclosure.

Selection of one class does not inherit authority for another class. A new source, parser, boundary or Operational Profile version does not inherit prior authority.

## Evaluation requirements

A locality proposal is assessed using event-level and source-level evidence, including:

- relevant events and material misses;
- unique and earlier detections;
- overlap and shared-origin dependency;
- false positives, ordinary local noise and reviewer burden;
- boundary and location accuracy;
- language and community relevance where applicable;
- rights and source stability;
- health, latency, cost and amplification;
- Event-Scoped Watch frequency and whether it would have been a safer alternative;
- resilience contribution; and
- effect on required national, nation-level and Urgent capacity.

Raw article count, population or one quiet evaluation window is not sufficient evidence.

A selected locality or source class must still report insufficient exposure for rare event classes rather than claiming complete local recall.

## Lifecycle, pause and retirement

### Scope change

Adding a locality, source class, obligation or boundary is a material product and operational change. It creates a new proposal, evaluation scope and decision.

### Degraded or paused coverage

When selected local paths fail, the system records the exact affected Coverage Unit and source class. A national Comparator or generic search cannot silently restore selected local coverage.

### Retirement

Retirement requires:

- event-level contribution and coverage-impact assessment;
- confirmation that no sole Active path is removed silently;
- rights, cost, noise, reliability or strategy rationale;
- treatment of pending watches and work;
- updated user and operator disclosure; and
- preserved historical decisions and source lineage.

A short quiet period is not enough to retire a rare-event local Anchor.

## Hong Kong and Global treatment

### Hong Kong

Hong Kong remains one geography for product filtering and navigation. The system may retain evidence-supported local place details in a story, but Topic 11 does not create district filters, district quotas or a systematic district-monitoring promise.

A Hong Kong district name does not need to be suppressed when material to a story; it simply does not become a separate coverage section or automatic source-selection unit.

### Global

Global remains one product geography. Evidence-supported event locations may be retained for factual precision, but Topic 11 does not create country-by-country or city-by-city global monitoring promises.

## Disclosure and diagnostics

Internal and launch documentation must distinguish:

- nation-level Active coverage;
- national sources that emit localised items;
- selected systematic Locality Coverage Units and source classes;
- event-scoped local watches;
- Best-effort local discovery; and
- explicit deferred local gaps.

If no Locality Coverage Unit is selected, documentation must say so plainly. Story locality labels and the number of local stories published must not be presented as evidence of systematic local monitoring.

Coverage diagnostics may show locality and source-class counts, but they cannot create quotas or filler under the Accepted Topic 10 contract.

## Requirements

### Scope and identity

**LOC-001 — Local story is not local promise.** An evidence-supported locality label MUST NOT be represented as proof of systematic monitoring of that locality.

**LOC-002 — Nation-level remains distinct.** England-, Scotland-, Wales- and Northern-Ireland-level obligations MUST NOT be deferred as local coverage.

**LOC-003 — Exact Locality Reference.** Locality identity MUST include type, authoritative boundary or service definition, version and known ambiguity where applicable.

**LOC-004 — No inferred precision.** The system MUST NOT infer a more precise locality or service area than permitted evidence establishes.

**LOC-005 — Boundary separation.** Administrative, police, health, transport, utility, court and other service geographies MUST remain distinguishable.

**LOC-006 — Boundary versioning.** Material boundary or service-scope change MUST create later configuration and MUST NOT rewrite historical geography.

### Launch boundary

**LOC-010 — No fixed launch locality by default.** Initial launch MUST NOT claim systematic all-topic monitoring of a fixed UK locality unless an exact later Locality Coverage Decision accepts it.

**LOC-011 — Local stories remain eligible.** Material local developments found through permitted paths MUST remain eligible for normal discovery and evidence workflows.

**LOC-012 — National localised path limit.** A national or nation-level source emitting localised items MAY satisfy its event-class role but MUST NOT be represented as complete locality coverage.

**LOC-013 — Deferred-gap disclosure.** Exhaustive local-body and institution monitoring MUST remain an explicit deferred gap wherever no selected Coverage Unit exists.

**LOC-014 — No locality quota.** Local geography counts MUST NOT promote weaker work, create filler or imply equal completeness.

### Coverage Units and source classes

**LOC-020 — Coverage Unit required.** Systematic locality selection MUST identify exact geography, boundary version, obligations, source classes, roles, exclusions and known gaps.

**LOC-021 — Source-class independence.** Selecting one local source class MUST NOT automatically select another class or all local news.

**LOC-022 — Exact owner decision.** Permanent selection, deferral, pause and retirement MUST use an immutable owner decision for the exact Coverage Unit version.

**LOC-023 — Selection is not activation.** A Locality Coverage Decision MUST NOT itself enable sources or create production authority.

**LOC-024 — No inherited authority.** New local source, parser, boundary or Operational Profile versions MUST qualify independently.

### Event-scoped watch

**LOC-030 — Bounded event watch.** A local watch MUST identify one exact event purpose, locality or service scope, source set, budget, owner and expiry.

**LOC-031 — Normal workflow.** Event-scoped local results MUST enter through accepted source, Signal, Lead, triage and evidence boundaries.

**LOC-032 — No permanent inference.** One or repeated event-scoped watches MUST NOT silently create permanent locality selection.

**LOC-033 — No recursive locality crawl.** A watch MUST NOT expand into unrelated whole-locality discovery without a new authorised purpose.

**LOC-034 — Explicit closure.** Watch expiry, conversion, extension and closure MUST be recorded rather than left indefinite.

### Selection and evaluation

**LOC-040 — Evidence-based proposal.** Locality expansion MUST cite accepted coverage, reviewed Gaps, prospective contribution, audience need, resilience or another explicit basis.

**LOC-041 — No single-factor selection.** Population, city prominence, one event, article volume, API availability or audience concentration MUST NOT alone select a locality.

**LOC-042 — Privacy restraint.** Locality decisions MUST NOT use individual addresses, precise reader histories or identifiable small cohorts.

**LOC-043 — Full qualification path.** Permanent local coverage MUST pass source-role, rights, Topic 8 evaluation and Topic 9 operational qualification before activation.

**LOC-044 — Contribution metrics.** Evaluation MUST measure event-level unique and earlier detection, misses, overlap, noise, boundary accuracy, cost, health and reviewer burden rather than raw output count.

**LOC-045 — Alternative assessment.** Evaluation MUST consider whether national localised sources, Best-effort radar or event-scoped watch can meet the need more safely than permanent locality monitoring.

**LOC-046 — Rare-event honesty.** Quiet periods or absent rare events MUST NOT be treated as proof that a locality source is useless or fully evaluated.

### Materiality and operations

**LOC-050 — Same materiality boundary.** Locality MUST NOT lower scope, novelty, utility, rights, evidence or sensitive-content gates.

**LOC-051 — Ordinary local noise excluded.** Routine notices, small delays, listings and low-impact administrative updates MUST NOT become Candidates merely because they are local.

**LOC-052 — Coverage posture.** Selected local coverage health MUST be assessed by exact Coverage Unit and source class, separately from individual source and national portfolio health.

**LOC-053 — Comparator non-substitution.** Generic media or search availability MUST NOT repair a failed selected local Anchor or conceal the gap.

**LOC-054 — Retirement impact.** Retirement MUST preserve history and assess the resulting coverage, pending work, disclosure and rollback consequences.

### Hong Kong, Global and disclosure

**LOC-060 — Hong Kong remains one section.** Topic 11 MUST NOT create district filters, quotas or a systematic district-completeness promise.

**LOC-061 — Hong Kong place precision permitted.** Evidence-supported local Hong Kong details MAY appear without becoming a district coverage unit.

**LOC-062 — No global locality promise.** Evidence-supported global locations MAY be retained, but no country- or city-completeness promise is created.

**LOC-063 — Public and operator honesty.** Documentation MUST list selected systematic locality scopes and explicit gaps, or state plainly that none is selected.

**LOC-064 — Published volume is not coverage proof.** Local story count MUST NOT be used as evidence of systematic monitoring completeness.

## Acceptance criteria

1. A material Glasgow incident found by a national radar can proceed without Glasgow being a selected locality.
2. Publishing that incident does not claim systematic Glasgow coverage.
3. Scotland nation-level policy remains Active even when no Scottish council is selected.
4. A national flood service may detect local warnings without implying that every council service is monitored.
5. A London transport source is not enabled solely because London has a large population or the API is convenient.
6. A selected council feed does not imply selected police, NHS, school or utility coverage.
7. A major incident may activate a bounded local watch that expires without creating a permanent portfolio.
8. A city label is not inferred from an operator area that extends beyond the city.
9. A local source producing many routine notices does not gain priority or Candidate authority from volume.
10. A local story outside selected scopes remains eligible when discovered.
11. Audience evidence used for selection is aggregated and privacy-safe.
12. Repeated Coverage Gaps may justify a proposal but do not activate sources automatically.
13. A quiet pilot does not prove a rare-event local source has no value.
14. A failed selected local Anchor remains degraded even when a generic search finds one related result.
15. Retiring a locality source cannot silently remove the only path for an accepted selected obligation.
16. Hong Kong district names may appear in stories without district navigation or completeness promises.
17. Launch documentation states whether any systematic Locality Coverage Units are selected.
18. Acceptance of Topic 11 authorises no locality, source, query, run, spending, product filter or production activation.

## Owner decisions required to complete Topic 11

The Draft recommends these decisions:

1. Accept a **locality-aware, locality-uncommitted** initial launch: no fixed UK locality receives systematic all-topic monitoring by default.
2. Accept that material local stories remain in scope and may proceed wherever discovered, without creating a monitoring promise.
3. Accept that UK-wide and nation-level coverage is separate from locality expansion and remains governed by the Active coverage contract.
4. Accept that nationally scoped sources may emit localised warnings or incidents for an accepted event class without establishing locality completeness.
5. Accept Locality Reference, Locality Coverage Unit, Locality Source-Class Scope, Locality Coverage Proposal, Locality Coverage Decision, Event-Scoped Local Watch and Locality Coverage Assessment as conceptual records.
6. Accept that a selected Coverage Unit is an exact geography-plus-source-class-plus-obligation scope, never “all news in this place”.
7. Accept source-class independence across local government, health, public safety, education, transport, utilities, courts or planning, and local media.
8. Accept bounded Event-Scoped Local Watch for a major incident or exact discovery question, with normal workflow, budget, owner and expiry, and no permanent-selection inference.
9. Accept evidence-supported location precision, versioned boundaries and explicit separation of administrative and service geographies.
10. Accept evidence-based selection using reviewed Gaps, prospective contribution, audience need, resilience, rights, cost and operational readiness, with no single-factor London-first, population, volume, API-availability or viral-event shortcut.
11. Accept privacy-safe aggregated audience evidence only; individual or identifiable precise location data cannot drive source selection or external queries.
12. Accept the full progression from proposal through rights, Topic 8 evaluation, Topic 9 qualification, owner decision, canary and separate activation.
13. Accept that local materiality uses the same scope and utility gates as national coverage, and routine local noise remains excluded.
14. Accept event-level contribution, boundary accuracy, noise, cost, health and reviewer burden as evaluation evidence rather than raw article count.
15. Accept explicit pause, degradation and retirement decisions with coverage-impact assessment and preserved history.
16. Accept that Hong Kong remains one product geography with no district filter or completeness promise, while evidence-supported local details may still appear.
17. Accept that actual selected localities, source classes and numeric thresholds remain **Needs experiment**; no locality is selected merely by accepting Topic 11.
18. Accept that Topic 11 authorises no locality, source, query, run, spending, navigation change or production activation.
