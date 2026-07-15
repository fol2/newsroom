# Discovery coverage contract

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Accepted by owner:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Related reference:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 3–6  
**Supersedes:** None

## Purpose

Define what launch news discovery is responsible for actively seeking, what remains best effort, what is an explicit deferred coverage gap and what is outside the product. This contract describes editorial coverage obligations independently from source selection, transport, search provider, polling cadence, model, database or orchestration technology.

A source set cannot be judged sufficient until it is assessed against this contract. Endpoint availability, a long feed list or broad search recall does not by itself establish coverage.

## Scope

This specification covers:

- geographic discovery responsibility for the United Kingdom, Hong Kong and qualifying global events;
- classes of developments that launch discovery should actively seek;
- the boundary between active coverage, best effort, deferred gaps and explicit exclusions;
- qualitative urgency classes needed for later workflow design; and
- how later source selection and shadow evaluation must account for coverage.

It does not define:

- the end-to-end discovery state machine;
- concrete sources, feeds, APIs, page selectors, search providers or reader-lead channels;
- polling intervals or quantitative detection service levels;
- storage schema, retention, evidence acquisition or RAG;
- scoring, ranking weights, reason-code strings or publication volume; or
- automatic-publication eligibility.

## Coverage responsibility classes

The contract uses four editorial responsibility classes. They are specification concepts, not required database enums.

### Active coverage obligation

Launch design must provide at least one explicit, owned discovery path and representative evaluation cases for the development class. A relevant miss indicates a coverage, source, workflow or operational defect that must be reviewed.

An active obligation is not an absolute promise that every event will be detected and does not create a quantitative detection-time guarantee. Those claims require later source and evaluation evidence.

### Best-effort coverage

The event remains within product scope and may become a Story Candidate when discovered, but launch does not claim systematic or complete detection. Relevant misses may create Coverage Gaps and inform later expansion without automatically blocking launch.

### Explicit deferred gap

The event remains within the charter's product scope, but systematic launch monitoring is intentionally incomplete. The gap must be visible, owner-approved and revisited; it must not be presented as completed coverage.

### Out of scope

The event does not qualify for the product unless a separate material public-impact development independently brings it into an approved category.

## Qualitative urgency classes

These classes establish workflow ordering without setting numerical service levels.

- **Urgent:** an active or imminent safety, public-health, severe-weather, disaster or material essential-service threat where delay can materially harm readers.
- **Time-sensitive:** a rule, status, deadline, travel requirement, service change or instruction that readers may need to understand or act on promptly.
- **Planned:** a known release, proceeding, consultation deadline, effective date or other expected development with a monitoring window.
- **Routine:** another substantive in-scope development without an immediate safety or action deadline.

A later workflow specification must decide queueing, batching and escalation behaviour for these classes. This contract does not assign minutes or hours.

## Requirements

### Charter and coverage classes

**COV-001 — Charter precedence.** Discovery coverage MUST preserve the geography, category, newsworthiness and exclusion boundaries in the canonical product and editorial charter. This specification MUST NOT broaden ordinary entertainment, sports, lifestyle, market or service-status material into the product merely to fill a discovery lane.

**COV-002 — Explicit responsibility.** Every material development class considered for launch MUST be assigned one of: active coverage obligation, best-effort coverage, explicit deferred gap or out of scope.

**COV-003 — Active-path requirement.** Before launch, every accepted active coverage obligation MUST have at least one explicit candidate detection path, representative positive and negative evaluation cases, and a defined way to record a relevant miss. Source selection is reviewed separately.

**COV-004 — Best-effort honesty.** Best-effort coverage MUST NOT be described as comprehensive, complete or reliably monitored. A best-effort event that is discovered remains eligible for normal triage and evidence rules.

**COV-005 — Deferred-gap honesty.** An explicit deferred gap MUST identify what is not systematically covered and why. A deferred gap MUST NOT be hidden by a broad media feed, generic search query or aggregate source count.

**COV-006 — No inferred service promise.** An accepted coverage class MUST NOT be interpreted as a detection-time, locality-completeness or recall guarantee unless a later accepted specification defines and validates that promise.

### Geography

**COV-010 — UK-wide and nation-level coverage.** Qualifying UK-wide and England-, Scotland-, Wales- or Northern-Ireland-level developments are active coverage obligations for the active subject classes below.

**COV-011 — UK local scope without false completeness.** Local UK developments remain in product scope. Launch does not claim systematic monitoring of every council, NHS body, police force, school, court, utility or local transport operator. Material local developments found through a permitted path may proceed normally; exhaustive local-source coverage is an explicit deferred gap until Topic 11 accepts a locality boundary. No locality or local-source class is mandatory at launch under this contract.

**COV-012 — Hong Kong intrinsic value.** A qualifying Hong Kong development MUST NOT require a direct UK effect. Major Hong Kong public-affairs, safety, policy, service and practical-impact developments are active coverage obligations across the approved categories. Hong Kong coverage is not limited to utility notices, but district-level completeness is not promised.

**COV-013 — Global qualification.** A global development is within active coverage only when available information establishes a material UK, Hong Kong, UK–Hong Kong travel, connected-family or exceptional international public-interest basis. Broad unrelated world-news completeness is out of scope.

**COV-014 — Early exceptional global awareness.** A genuinely exceptional international event whose UK or Hong Kong effect is not yet established may be treated as best effort until triage can assess the charter qualification. Discovery MUST NOT invent a local effect merely to retain it.

### Developments that coverage must recognise

**COV-020 — New and revised official action.** Active coverage includes substantive new decisions, rules, rights, statuses, official instructions, processes, deadlines and policy changes within the active geography and subject classes.

**COV-021 — Existing-page revisions.** Active coverage includes substantive revision, replacement, withdrawal or supersession of an existing guidance, rule, service or policy page. Monitoring only newly published URLs is not sufficient coverage.

**COV-022 — Planned developments.** Active coverage includes known releases, proceedings, effective dates, consultation deadlines and similar expected developments within an active subject class. A planned item is an expectation and MUST NOT be treated as evidence that the development occurred.

**COV-023 — Incident and service transitions.** Coverage may need to recognise the start, escalation, de-escalation, resolution, cancellation or expiry of an incident, warning or service state. Topic 5 will define exact change semantics.

**COV-024 — Data releases and revisions.** Active coverage includes relevant official statistics releases, material revisions, cancellations and provisional-status changes where the data qualifies under the charter. Discovery does not authorise new newsroom calculations.

**COV-025 — Substantive new information.** Discovery coverage is satisfied by finding a potentially substantive development, not by reproducing unchanged background, routine commentary or multiple copies of the same originating material.

### Exclusions and impact exceptions

**COV-030 — Explicit exclusions.** Ordinary entertainment, celebrity gossip, sports results and transfers, lifestyle recommendations, affiliate-style content, event listings, ordinary individual delays, live tracking, unrelated world news, editorials and party-political advocacy are out of scope.

**COV-031 — Public-impact exception.** An entertainment, sporting, commercial or otherwise excluded subject MAY enter active or best-effort coverage only through a separate qualifying safety, transport, infrastructure, public-service, rights or other material public-impact development. It is then classified by that impact, not by the excluded subject.

**COV-032 — Ordinary service noise.** Routine short-lived or isolated transport, utility and service-status items are out of scope unless evidence supports a meaningful affected group, material duration or clear daily-life effect.

**COV-033 — Ordinary market and technology noise.** Routine share-price movement, company earnings, product launches, general AI releases and technology commentary are out of scope unless they independently qualify through household impact, policy, safety, cyber security, major outage or exceptional public importance.

### Coverage governance

**COV-040 — Coverage before source selection.** Concrete sources and source counts MUST be assessed against this contract. The existence of an official feed, media feed, API, search result or tested endpoint MUST NOT create a coverage obligation or prove that an obligation is met.

**COV-041 — Source-role neutrality.** This contract does not require official-only, RSS-only, search-first, search-zero, Hermes-specific or any other source architecture. Topic 4 will decide which source roles and candidate interfaces satisfy each accepted obligation.

**COV-042 — Coverage Gap.** A relevant development within an active or best-effort class that is found through another permitted channel but missed by the selected discovery paths MUST create a reviewable Coverage Gap. The gap record is evidence for source and workflow review, not automatically proof of a service-level breach.

**COV-043 — No volume substitution.** Large source counts, repeated coverage and media density MUST NOT compensate for an uncovered active obligation.

**COV-044 — Change control.** Adding, removing or reclassifying a coverage obligation is a product and editorial decision. It MUST be reviewed against the charter and recorded rather than changed silently through a query, source configuration or model prompt.

**COV-045 — Launch-blocking coverage failure.** Launch MUST be blocked when an accepted active coverage class has no credible detection path, or when shadow evidence shows a systemic failure that makes the path incapable of meeting the class. An isolated miss MUST create a Coverage Gap and remediation decision; it blocks launch only when it reveals such a systemic deficiency or another accepted release gate requires it.

## Accepted launch coverage matrix

“Active” means the launch design needs an explicit path and evaluation; it does not claim perfect recall or a numeric detection time.

| Development class | Responsibility | Geography and boundary | Typical urgency |
|---|---|---|---|
| Law, rights, immigration/status, policy, official process and actionable deadline changes | Active | UK and Hong Kong; global only where the qualifying effect is established | Time-sensitive or Planned |
| Substantive revision, withdrawal or replacement of existing guidance or rules | Active | UK and Hong Kong active subject classes | Time-sensitive or Routine |
| Severe weather, disaster, public-health warning and imminent safety instruction | Active | UK and Hong Kong; qualifying global effects | Urgent |
| Material transport, aviation, infrastructure, utility or essential-service disruption | Active when the materiality test is plausibly met | UK, Hong Kong and UK–Hong Kong travel; ordinary individual delays excluded | Urgent or Time-sensitive |
| Health, education, tax, welfare, pensions, employment rights, housing, utilities and household-support changes | Active for UK-wide, nation-level, Hong Kong-wide or otherwise materially affected groups | Exhaustive UK local-body and institution monitoring is a deferred gap | Time-sensitive, Planned or Routine |
| Consumer protection, scams, recalls, material service failure and significant data breach | Active when there is an official warning, material scale or practical reader action | UK and Hong Kong | Urgent or Time-sensitive |
| Politics, legislation, elections, courts and civil rights | Active for decisions, formal proceedings and outcomes with substantive public consequence | UK and Hong Kong; routine statements, commentary and advocacy excluded | Planned, Time-sensitive or Routine |
| Crime and unscheduled incidents | Active for authoritative public-safety warnings and clearly major incidents; Best effort for other unscheduled verified crime or incident discovery | UK and Hong Kong; no routine incident completeness | Urgent or Routine |
| Official statistics, inflation, interest rates, currency and major household-cost developments | Active where the charter's practical-impact test is met | UK and Hong Kong; ordinary stocks, earnings and trading coverage excluded | Planned or Routine |
| Major cyber incident, widespread outage, technology policy or safety development | Active where scale, safety, rights or service impact qualifies | UK and Hong Kong; ordinary product and AI news excluded | Urgent, Time-sensitive or Routine |
| Community and public-service change | Active for national, nation-level, Hong Kong-wide or clearly material changes | Exhaustive UK locality coverage is a deferred gap | Time-sensitive or Routine |
| War, sanctions, diplomacy, supply-chain and other global developments | Active when a material UK, Hong Kong or connected-family effect is established; otherwise Best effort only for exceptional international importance | No general world-news completeness | Urgent or Routine |
| Material local UK developments outside later selected localities or source classes | Best effort, with systematic completeness deferred | Story remains eligible when found | Depends on event |
| Entertainment, celebrity, ordinary sports, lifestyle, affiliate, listings and unrelated world news | Out of scope except through a separate public-impact qualification | All geographies | None |

## Acceptance criteria

1. A later source-selection proposal maps every active coverage row to at least one explicit candidate detection path or records an owner-approved blocking gap.
2. A substantive edit to an existing immigration guidance URL remains within active discovery coverage even when no new URL is published.
3. A known consultation deadline or statistics release is within Planned coverage, but its calendar entry is not treated as proof that it occurred.
4. A qualifying Hong Kong policy or public-affairs development is not rejected merely because it has no direct UK effect.
5. An unrelated overseas political statement does not qualify as global coverage without a charter-defined effect or exceptional public importance.
6. An ordinary delayed train, isolated road closure or individual flight delay is not an active discovery obligation.
7. A stadium event causing a material transport or safety impact is covered through transport or safety, not sport or entertainment.
8. A routine company earnings release, share-price move or AI product announcement is out of scope unless it independently passes an approved practical-impact, policy, safety, outage or exceptional-importance test.
9. Launch documentation states that exhaustive UK local-source coverage is incomplete unless and until Topic 11 accepts a locality boundary.
10. A long source list or a high number of media results cannot be used as evidence that the accepted coverage obligations are complete.
11. The coverage contract remains independent of Hermes, RSS, Brave, GDELT, database, numeric scoring and polling-interval choices.
12. A missing detection path or systemic failure for an active class blocks launch, while an isolated miss creates a Coverage Gap unless it demonstrates the systemic deficiency.

## Completion record

The product owner accepted this contract on 2026-07-15 with the following decisions:

- the launch coverage matrix and its active, best-effort, deferred and out-of-scope distinctions are accepted;
- authoritative public-safety warnings and clearly major unscheduled incidents are Active, while other unscheduled crime and incident discovery is Best effort;
- Hong Kong active coverage includes broad major public affairs and is not utility-only, without a district-completeness promise;
- exhaustive UK local-body and institution monitoring is an explicit deferred gap, with no mandatory launch locality under this contract;
- ordinary global coverage requires a UK, Hong Kong or connected-family material effect, while genuinely exceptional international events may enter Best effort triage without invented relevance; and
- missing or systemically ineffective detection for an Active class blocks launch, while an isolated miss normally creates a Coverage Gap and remediation decision.
