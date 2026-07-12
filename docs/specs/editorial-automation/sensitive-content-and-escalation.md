# Sensitive content and escalation specification

**Status:** Draft  
**Owner:** Product owner  
**Last updated:** 2026-07-11  
**Canonical language:** English  
**Related plan:** None  
**Related reference:** [`product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 11 and 14  
**Supersedes:** None

## Purpose

Define the machine-actionable boundary for personal information, allegations, legal proceedings and other sensitive subjects so the autonomous path can publish routine low-risk reporting while holding or rejecting unresolved high-risk material.

## Scope

This specification covers identifiable people, private persons, public office-holders, children, schools, crime, courts, health, finance, war, suicide and self-harm, jurisdictional checks, structured risk records and escalation outcomes.

## Requirements

### General risk processing

**RISK-001 — Risk classification required.** Every candidate MUST run through sensitive-content classification before publication, including candidates whose category is not obviously sensitive.

**RISK-002 — Structured flags.** Risk classification MUST record machine-readable flags for at least:

- identifiable person or organisation;
- private person;
- child or school pupil;
- complainant, victim, witness or protected identity;
- allegation or disputed conduct;
- arrest, charge, active proceeding, judgment or sentence;
- health or medical information;
- special-category or criminal-offence personal data;
- suicide or self-harm;
- war or operational-security detail;
- financial recommendation risk;
- legal jurisdiction; and
- potential reporting restriction or privacy harm.

**RISK-003 — Jurisdiction.** The system MUST identify every materially relevant jurisdiction for defamation, privacy, child protection, court reporting and distribution. Unknown or conflicting jurisdiction MUST block automatic publication.

**RISK-004 — No generic UK assumption.** England and Wales, Scotland and Northern Ireland MUST NOT be treated as one legal rule set where the applicable requirement differs. Hong Kong and any other material territory MUST be evaluated separately.

**RISK-005 — Omit before escalate.** Where a risky detail is not necessary to the public-interest value of the story, the system SHOULD omit or generalise it and revalidate the draft instead of escalating the entire candidate.

**RISK-006 — No model legal conclusion.** A model's unsupported statement that publication is lawful, fair, necessary or in the public interest MUST NOT satisfy a legal or risk gate.

### Identifiable people and organisations

**RISK-010 — Public official identity.** A public office-holder or authorised organisational representative MAY be named for an official public act or statement when a formal source confirms identity and role, the identity is relevant and no restriction applies.

**RISK-011 — Other-person identity test.** Any other person MAY be considered for identification only when all of the following are evidenced:

1. a reliable formal source published the identity;
2. the identity is directly relevant;
3. the person has been entity-resolved with sufficient confidence; and
4. no known automatic restriction, court order or other legal protection prohibits identification.

**RISK-012 — Additional proportionality record.** For a private person, victim, suspected offender, person linked to an allegation or person whose sensitive information is involved, the decision record MUST also address necessity, proportionality, likely harm, privacy expectation, less intrusive alternatives and the sensitive-data class.

**RISK-013 — Public availability is insufficient.** A name or detail appearing online MUST NOT by itself satisfy accuracy, necessity, privacy or reporting-restriction requirements.

**RISK-014 — Identity uncertainty.** Unresolved entity matching, spelling, transliteration or same-name risk MUST block identification. The story MAY proceed without the identity if it remains useful and accurate.

**RISK-015 — Organisation allegations.** A serious allegation concerning an organisation remains within the hold boundary unless a later accepted policy defines a narrow automatic path based on appropriate public findings or formal procedural facts.

### Serious allegations and disputed conduct

**RISK-020 — Mandatory hold.** A candidate containing a serious allegation about an identifiable person or organisation MUST be `HOLD_FOR_REVIEW` unless an explicit accepted exception applies.

**RISK-021 — Mandatory rejection.** An allegation supported only by anonymous, leaked, social-media, unverifiable or lead-only material MUST be rejected as confirmed news.

**RISK-022 — Attribution does not remove harm.** Saying that another publication reported an allegation MUST NOT bypass the hold or evidence requirement.

**RISK-023 — No inferred motive or guilt.** Motive, guilt, dishonesty, intent, collective behaviour or criminal responsibility MUST NOT be inferred by a model or from circumstantial public material.

**RISK-024 — Formal procedural fact.** Arrest, charge, filing, investigation, trial, judgment and sentence MAY be reported only as the precise procedural fact established by an appropriate source and subject to current jurisdictional restrictions.

**RISK-025 — Exception policy.** Any future automatic-publication exception for a formal procedural fact MUST define source type, permitted language, jurisdiction, identity treatment, current-check method and disqualifying conditions. Absence of such an accepted rule means hold.

### Children, schools, victims and protected identities

**RISK-030 — Child identity.** The system MUST NOT identify a protected child or expose details that create direct or jigsaw identification.

**RISK-031 — School reporting.** Verified school closures, outbreaks, admissions, examinations, fees, strikes, safety notices and policy changes MAY use the normal autonomous path when they do not identify protected or unnecessarily private individuals.

**RISK-032 — Rumour exclusion.** Parent-group messages, pupil rumours, staff allegations and unattributed school screenshots are lead-only and MUST NOT be published as fact.

**RISK-033 — Victim and complainant protection.** A complainant, victim or witness MUST NOT be named or indirectly identified where an automatic or ordered protection applies or where the applicable check is indeterminate.

**RISK-034 — Jigsaw check.** The system MUST evaluate the combination of locality, school, age, relationship, image, chronology and other details for indirect identification, not merely the presence of a name.

### Crime, courts and legal proceedings

**RISK-040 — Procedural states.** The system MUST represent arrest, charge, trial, conviction, sentence, appeal, inquest, civil proceeding and investigation as distinct states.

**RISK-041 — Current legal check.** Before publishing or updating a story that touches current or contemplated proceedings or protected court material, the system MUST complete a current check for:

- whether proceedings are active;
- automatic and court-ordered restrictions;
- protected complainants, witnesses, children and family proceedings;
- postponement and anonymity orders;
- jigsaw identification;
- prejudice to the current or linked proceeding; and
- the applicable jurisdiction.

**RISK-042 — Indeterminate check.** If the current legal check cannot establish a reliable position, the candidate MUST be held. A search that simply finds no named order is insufficient.

**RISK-043 — Neutral procedural language.** A story MUST NOT use language implying guilt before conviction or broader wrongdoing than the formal source establishes.

**RISK-044 — Archive change.** A decision not to charge, acquittal, appeal outcome, later anonymity order or new disproportionate-harm risk MUST trigger lifecycle reassessment of related published and archived stories.

### Health and medical content

**RISK-050 — Permitted health reporting.** Public-health evidence, service changes, medicine information and named sourced analysis MAY follow the normal autonomous path when they satisfy evidence and content requirements.

**RISK-051 — No diagnosis or treatment instruction.** The product MUST NOT diagnose a reader, tell a reader to start, stop or change treatment, or present general reporting as personalised medical advice.

**RISK-052 — Preliminary evidence.** A small, preliminary, preclinical or non-replicated study MUST retain its limitations and MUST NOT be presented as a proven cure, established risk or clinical recommendation.

**RISK-053 — Patient privacy.** Patient or treatment details that identify a private person MUST be omitted or held under the personal-information rules.

### Finance and markets

**RISK-060 — Permitted finance reporting.** Economic policy, household finances, official market events and sourced analysis MAY follow the normal autonomous path.

**RISK-061 — Prohibited advice.** The product MUST NOT provide personalised investment instructions, stock or crypto promotion, direct buy/sell recommendations, price targets generated by the newsroom or affiliate-style financial content.

**RISK-062 — Forecast attribution.** A forecast MUST be attributed to its named source with method, conditions and material interests where available.

**RISK-063 — Market-sensitive uncertainty.** A central market-moving claim that relies on anonymous, leaked or conflicting evidence MUST NOT be automatically published.

### War and conflict

**RISK-070 — Belligerent attribution.** A claim by a belligerent MUST remain explicitly attributed and MUST NOT become an unqualified fact through repetition.

**RISK-071 — Casualty categories.** Casualty figures MUST preserve the source's categories, source name and reporting time. The system MUST NOT estimate civilian/combatant or death/injury splits absent from the source.

**RISK-072 — Operational security.** The product MUST NOT publish operational details that may endanger people.

**RISK-073 — Propaganda and prediction.** Propaganda MUST NOT be presented as fact, and the system MUST NOT make unsupported predictions about victory, collapse or an end date.

**RISK-074 — Graphic imagery.** Unnecessary graphic injury or death imagery is prohibited under the visual specification.

### Suicide and self-harm

**RISK-080 — Public-importance gate.** Suicide or self-harm coverage MUST have clear public importance. Otherwise the candidate MUST be rejected.

**RISK-081 — Method restriction.** The story MUST omit method detail beyond what is strictly necessary and safe for the public-interest purpose.

**RISK-082 — No simplistic causation.** The story MUST NOT reduce the event to a single cause, romanticise it, reproduce a note or unnecessarily identify the person or family.

**RISK-083 — Support information.** Whether and how to include support information MUST be defined by a later accepted presentation policy appropriate to the distribution territory.

### Escalation record

**RISK-090 — Hold reason.** Every sensitive-content hold MUST identify the risk class, affected content, jurisdiction, failed or indeterminate check and authorised reviewer role required.

**RISK-091 — Rejection reason.** A rejection MUST distinguish prohibited content, insufficient evidence, known legal or rights barrier and unresolved risk that cannot be cured through the permitted workflow.

**RISK-092 — Review scope.** A reviewer decision MUST address the stated risk; it MUST NOT be treated as approval of unrelated failed gates.

**RISK-093 — Revalidation.** Redaction, omission, new evidence or reviewer amendment MUST trigger all affected evidence, content, rights and risk checks again.

**RISK-094 — Policy provenance.** The final risk outcome MUST record the policy version and jurisdiction rule set used.

## Acceptance criteria

1. A routine NHS service-policy story with no private patient information can proceed autonomously after ordinary gates pass.
2. A serious allegation about a named person is held even when an established outlet reports it anonymously.
3. A child can be indirectly identified from combined details and the jigsaw check blocks publication until those details are removed.
4. A charge is described as a charge, not as guilt or conviction.
5. An indeterminate active-proceedings check results in a hold, not automatic publication.
6. A named public official can be identified for a formally recorded official act when no restriction applies.
7. A private person's identity is omitted when the story remains useful without it.
8. Belligerent casualty figures remain attributed and preserve the source categories and timestamp.
9. A market forecast is attributed and cannot become the newsroom's own price target.
10. A suicide story without clear public importance is rejected.

## Non-goals

This specification is not legal advice and does not encode the final law of any jurisdiction. It defines product behaviour that must be reviewed by appropriately qualified advisers before launch.

It does not establish a general investigative, whistleblowing or confidential-source workflow.

## Open questions

- Which procedural facts, if any, may receive a narrow automatic-publication rule after legal review?
- Which external legal or restriction data sources can support reliable automated jurisdictional checks?
- Which reviewer roles are required for privacy, court, allegation and child-protection holds?
- What territory-specific support-information policy should apply to suicide and self-harm coverage?
