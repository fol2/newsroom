# Discovery locality scope and expansion specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Accepted by owner:** 2026-07-16  
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
**Implementation authority:** None. Acceptance defines the locality boundary and expansion semantics; it selects no locality or source, creates no coverage promise, authorises no run or spending and changes no product navigation.  
**Supersedes:** None

## Purpose

Define how material UK local developments remain discoverable without claiming that launch systematically monitors every council, NHS body, police force, school, court, utility, transport operator or local publication.

The contract separates:

- an evidence-supported locality label on one story;
- a material local event found through any permitted path;
- a bounded Event-Scoped Local Watch;
- a selected locality-plus-source-class portfolio; and
- a public promise of systematic locality coverage.

These are not equivalent.

## Scope

This specification defines the initial UK locality boundary, locality and service-area identity, Event-Scoped Local Watch, evidence-based expansion, source-class independence, privacy and disclosure controls, and the treatment of Hong Kong district details and global locations.

It does not select councils, cities, police forces, health bodies, operators, endpoints, polling intervals, budgets, administrative-boundary providers, reader geolocation or personalised local feeds. Actual selected localities, source classes and numerical admission thresholds remain **Needs experiment**.

## Accepted launch boundary

The initial launch posture is **locality-aware and locality-uncommitted**:

1. No fixed UK city, county, borough, council area or service region receives systematic all-topic monitoring by default.
2. No local source class is enabled merely to claim local-news coverage.
3. Material local events found through national or nation-level sources, established-media radar, approved search, manual or reader leads, or an Event-Scoped Local Watch remain eligible for the normal Signal-to-Candidate workflow.
4. National or nation-level sources may emit localised warnings or incidents for an accepted event class without establishing locality completeness.
5. Permanent locality or source-class selection requires a versioned Locality Coverage Decision after source, rights, evaluation and operational qualification.
6. Launch and operator documentation must state plainly that systematic UK locality completeness remains deferred unless an exact Locality Coverage Unit is later accepted.

England-, Scotland-, Wales- and Northern-Ireland-level Active obligations remain separate from local expansion and cannot be deferred because no council or city is selected.

## Core distinctions

### Local story is not locality promise

A Candidate or Story may carry the most specific locality supported by permitted evidence even where that place is not systematically monitored. Publishing one story about Leeds, Glasgow or Croydon does not imply recurring or complete coverage there.

### Localised national path is not locality completeness

A national flood, weather, road or infrastructure source may detect localised events within its declared event class. It does not establish coverage of every council service, school, police incident, health body, local operator or local policy in those places.

### Locality is not service boundary

A city, postcode, council area, police-force area, NHS geography, transport network, utility region and court circuit may overlap without being identical. The exact applicable administrative or service boundary remains explicit and versioned.

### Selected locality is not all local news

A locality is selected only for exact obligations and exact source classes. Selecting a council source does not select policing, health, schools, transport, utilities, courts or local media automatically.

### Event-Scoped Local Watch is not permanent selection

A major incident or bounded discovery question may justify temporary monitoring of responsible local authorities, operators and established local media. The watch expires or closes explicitly and creates no permanent locality portfolio or completeness promise.

## Locality semantic records

These are conceptual contracts rather than required tables.

### Locality Reference

A stable internal reference containing locality type, canonical name and aliases, parent geography where applicable, authoritative boundary or service-definition source, boundary version and validity, known overlaps and uncertainty. A name alone is not sufficient identity.

### Locality Coverage Unit

One exact combination of:

- Locality Reference and boundary version;
- accepted obligations or Best-effort classes;
- selected local source classes;
- population, service or event scope;
- languages where applicable;
- source roles and portfolio functions;
- exclusions and known gaps; and
- governing evaluation and Operational Profile versions.

It is deliberately narrower than “all news in this place”.

### Locality Source-Class Scope

Source classes are independently admitted:

1. local government and combined-authority decisions;
2. NHS, public-health and local healthcare bodies;
3. police, fire, resilience and public-safety authorities;
4. schools, education authorities and major campuses;
5. local and regional transport operators;
6. utilities, infrastructure and environmental services;
7. courts, planning, housing and building-safety bodies with an accepted public interface; and
8. established local or community media radar.

### Locality Coverage Proposal

An immutable proposal identifying the exact Coverage Unit, accepted Gap or coverage basis, reason permanent monitoring is preferable to Best-effort or event-scoped discovery, candidate sources and dependencies, expected contribution, rights and operational assumptions, privacy-safe audience evidence where used, evaluation design, alternatives and the consequence of not selecting it.

### Locality Coverage Decision

An immutable owner decision for one exact Coverage Unit version. Outcomes may include not selected, Research candidate, evaluation-only, selected for exact systematic scope, selected with an explicit sub-gap, paused, degraded, retired or rejected. Selection does not activate sources.

### Event-Scoped Local Watch

A bounded decision tied to one exact Event Hypothesis, Lead, Candidate or major-incident question. It records purpose, locality and service boundaries, exact sources, permitted transitions, start, review and expiry, rights, budget, owner, Operational Profile and closure or conversion conditions. Its default expiry outcome is closure.

### Locality Coverage Assessment

A rebuildable, versioned view of selected, evaluated, deferred, degraded and unavailable locality-plus-source-class scopes. It remains separate from individual-source health and story geography labels.

## Boundary, precision and materiality

The system uses only the most specific location supported by permitted source material. It must not infer a council, borough, postcode, campus or service area from a nearby city name.

One event may retain several explicit geographies and service areas. Boundary changes create later configuration and assessment; they do not rewrite historical stories or decisions. Where mapping is uncertain, broader geography or explicit ambiguity is retained.

Locality does not lower the accepted scope, novelty, utility, rights, evidence or sensitive-content gates. Potentially qualifying local developments include major safety incidents, meaningful essential-service disruption, actionable public-service or housing changes affecting a meaningful group, building or environmental safety warnings, and substantive local democratic, court or civil-rights outcomes. Routine meeting notices, minor works, isolated delays, listings, promotional material and routine crime-roundup volume remain excluded.

## Event-Scoped Local Watch

A bounded watch may follow an authoritative major warning, a plausible established-media or reader Lead, a Candidate requiring local state transitions, a Watch Condition or a bounded Evidence Intake question.

It must:

- use the accepted source, rights, operational, Signal, Lead, triage and evidence boundaries;
- identify one exact event purpose, source set, budget, owner and expiry;
- avoid recursive whole-locality crawling;
- keep unrelated local stories outside the watched Candidate;
- create no evidence bypass; and
- require a separate Locality Coverage Proposal before permanent conversion.

Repeated watches may inform a future proposal but do not create authority by repetition.

## Evidence-based expansion

A permanent proposal may cite a combination of reviewed Coverage Gaps, missing Active paths, unique or materially earlier prospective detections, recurring material local events, privacy-safe aggregated audience need, resilience, necessary operator or Agenda paths, rights readiness, manageable noise and cost, and reasonable community representation.

No single factor is sufficient. A locality or source class must not be selected solely because an API exists, it is London or another prominent city, it has the largest population, one viral event occurred, it generates many articles, access is convenient, individual reader locations are available, a quota needs filling or the product wants to claim UK-local completeness.

Audience evidence must be aggregated, minimised and policy-approved. Individual addresses, precise reader histories and identifiable small cohorts must not drive source selection or external queries.

The qualification path is:

```text
Coverage or Gap basis
→ Locality Coverage Proposal
→ source-role and rights qualification
→ fixtures and replay
→ prospective evaluation and contribution review
→ Operational Profiles and capacity evidence
→ Locality Coverage Decision
→ source-specific admission and canary
→ separate activation decision
```

Evaluation considers event-level misses and contribution, earlier detection, overlap and dependency, ordinary local noise, boundary accuracy, language relevance, rights, health, latency, cost, amplification, reviewer burden, resilience and whether Event-Scoped Local Watch is the safer alternative. Raw article count, population and one quiet window are insufficient.

## Lifecycle and disclosure

Adding a locality, source class, obligation or boundary is a material change. Pause, degradation and retirement require explicit decisions, coverage-impact assessment, treatment of pending work and preserved history. A generic search or national Comparator cannot restore a failed selected local Anchor.

Hong Kong remains one product geography with no district filter, quota or systematic district-completeness promise. Evidence-supported district and place details may appear in stories. Global also remains one product geography; factual locations create no country- or city-completeness promise.

Documentation must list selected Locality Coverage Units and explicit gaps, or state plainly that none is selected. Local story volume cannot be presented as proof of systematic monitoring.

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

**LOC-045 — Alternative assessment.** Evaluation MUST consider whether national localised sources, Best-effort radar or Event-Scoped Local Watch can meet the need more safely than permanent locality monitoring.

**LOC-046 — Rare-event honesty.** Quiet periods or absent rare events MUST NOT be treated as proof that a locality source is useless or fully evaluated.

### Materiality and operations

**LOC-050 — Same materiality boundary.** Locality MUST NOT lower scope, novelty, utility, rights, evidence or sensitive-content gates.

**LOC-051 — Ordinary local noise excluded.** Routine notices, small delays, listings and low-impact administrative updates MUST NOT become Candidates merely because they are local.

**LOC-052 — Coverage posture.** Selected local coverage health MUST be assessed by exact Coverage Unit and source class, separately from individual-source and national-portfolio health.

**LOC-053 — Comparator non-substitution.** Generic media or search availability MUST NOT repair a failed selected local Anchor or conceal the gap.

**LOC-054 — Retirement impact.** Retirement MUST preserve history and assess resulting coverage, pending work, disclosure and rollback consequences.

### Hong Kong, Global and disclosure

**LOC-060 — Hong Kong remains one section.** Topic 11 MUST NOT create district filters, quotas or a systematic district-completeness promise.

**LOC-061 — Hong Kong place precision permitted.** Evidence-supported local Hong Kong details MAY appear without becoming a district coverage unit.

**LOC-062 — No global locality promise.** Evidence-supported global locations MAY be retained, but no country- or city-completeness promise is created.

**LOC-063 — Public and operator honesty.** Documentation MUST list selected systematic locality scopes and explicit gaps, or state plainly that none is selected.

**LOC-064 — Published volume is not coverage proof.** Local story count MUST NOT be used as evidence of systematic monitoring completeness.

## Acceptance criteria

1. A material Glasgow incident found by a national radar can proceed without Glasgow being selected.
2. Publishing it does not claim systematic Glasgow coverage.
3. Scotland nation-level policy remains Active even when no Scottish council is selected.
4. A national flood service may detect local warnings without implying every council service is monitored.
5. A London transport source is not enabled solely because London is large or its API is convenient.
6. A selected council feed does not imply selected police, NHS, school or utility coverage.
7. A major incident may activate a bounded local watch that expires without creating a permanent portfolio.
8. A city label is not inferred from a wider operator area.
9. Local-source volume creates no priority or Candidate authority.
10. A local story outside selected scopes remains eligible when discovered.
11. Audience evidence used for selection is aggregated and privacy-safe.
12. Repeated Gaps may justify a proposal but do not activate sources automatically.
13. A quiet pilot does not prove a rare-event source has no value.
14. Generic search cannot repair a failed selected local Anchor.
15. Retirement cannot remove a sole accepted path silently.
16. Hong Kong district names may appear without district navigation or completeness claims.
17. Launch documentation states whether any systematic Locality Coverage Units are selected.
18. Acceptance authorises no locality, source, query, run, spending, filter, navigation change or production activation.

## Completion record

The product owner accepted this specification on 2026-07-16 with these decisions:

- initial launch is locality-aware and locality-uncommitted, with no fixed UK locality receiving systematic all-topic monitoring by default;
- material local stories remain in scope wherever discovered and create no monitoring promise;
- nation-level coverage remains separate from locality expansion;
- nationally scoped sources may provide localised event-class detection without establishing locality completeness;
- Locality Reference, Coverage Unit, Source-Class Scope, Proposal, Decision, Event-Scoped Local Watch and Coverage Assessment are accepted conceptual records;
- selected coverage is exact geography plus source classes plus obligations, never all news in one place;
- local source classes are independently selected;
- Event-Scoped Local Watch is bounded, owned, budgeted and expiring and creates no permanent-selection inference;
- location precision is evidence-supported and administrative and service boundaries remain distinct and versioned;
- permanent selection uses reviewed Gaps, prospective contribution, privacy-safe audience need, resilience, rights, cost and operational readiness rather than London-first, population, volume, API convenience or one viral event;
- expansion follows proposal, rights, Topic 8 evaluation, Topic 9 qualification, owner decision, canary and separate activation;
- local materiality uses the same gates as national coverage and routine local noise remains excluded;
- evaluation uses event contribution, boundary accuracy, noise, cost, health and reviewer burden rather than article count;
- pause, degradation and retirement are explicit and preserve history;
- Hong Kong remains one product geography without district filters or completeness promises, while supported local details remain permitted;
- actual localities, source classes and numerical thresholds remain **Needs experiment**; and
- Topic 11 authorises no locality, source, query, run, spending, navigation change or production activation.
