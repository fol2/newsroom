# Autonomous News Product and Editorial Charter

**Status:** Draft for owner review  
**Type:** Product and editorial reference charter (non-normative)  
**Canonical language:** Hong Kong Traditional Chinese (`zh-HK`)  
**Translation status:** English development translation; if the two versions diverge, the `zh-HK` version controls  
**Decisions captured through:** 11 July 2026  
**Scope:** Product positioning, coverage, evidence, writing, visuals, autonomous publication boundaries and accountability  
**Related specification suite:** [`../../specs/editorial-automation/`](../../specs/editorial-automation/)  
**Document role:** This charter records the intended future product and the policy boundary within which an automated newsroom may operate. It is reference material, not an implementation instruction. Accepted specifications convert selected principles into normative, testable requirements. It does not assert that the current Discord newsroom implements these rules.

> This English file is maintained for development agents and technical contributors. The canonical human reference is the [`zh-HK` charter](product-editorial-charter.zh-HK.md).

## 1. Product definition

The initial product is a news app for Hong Kong people and families living in the United Kingdom. It is written in Hong Kong Traditional Chinese with a natural Cantonese voice. A public news website is not part of the initial product scope.

The app helps readers follow:

- life and public affairs in the UK;
- news affecting family, assets and decisions in Hong Kong; and
- world events that materially affect the UK, Hong Kong or families connected to either place.

The reader promise is:

> One app for understanding life in the UK, events in Hong Kong, and world events that materially affect the UK, Hong Kong or families connected to either place.

The product prioritises accurate, practical, evidence-led reporting over being first or publishing the most.

The product is not a translation service. It uses published news as a lead, returns to public evidence and data, and produces an original Traditional Chinese report in a Hong Kong register.

It is also not an investigative newsroom. The system does not interview witnesses, pursue private documents, solicit leaks or investigate allegations. It works from public, verifiable material.

The target operating model is an autonomous, agentic newsroom. Eligible stories may be discovered, verified, drafted, checked and published without routine per-story human approval. Human responsibility sits at the policy, release, exception, complaint, correction and emergency-control layers. Autonomy is bounded by versioned rules, evidence gates, rights checks, risk controls, auditable decisions and fail-closed behaviour.

## 2. Core editorial and automation model

Every published story follows the same underlying model:

1. Discover a possible story through official channels, established media or other permitted public sources.
2. Build a traceable evidence package from authoritative documents, data or reliable published reporting.
3. Identify what is confirmed, whether an authoritative source expressly marks any information as provisional, and what has changed since earlier reports.
4. Write an original report rather than translating or closely paraphrasing a source article.
5. Use analysis only when that analysis has already been published by a named, credible source and is supported by traceable evidence.
6. Run the required evidence, originality, rights, visual, sensitive-content, legal-risk, schema and presentation checks.
7. Produce one of three publication decisions: automatically publish, hold for authorised human review, or reject.
8. Record the sources, claim-to-evidence links, rights status, model and prompt versions, validation results, risk flags, publication decision, publication time and any later correction or withdrawal.

A story may be published automatically only when every required gate passes and no mandatory hold condition applies. Routine per-story human approval is not part of the target operating model. A human reviewer is required only for an exception that the accepted specifications classify as reviewable rather than automatically rejectable.

The service publishes confirmed facts. It does not turn rumours, anonymous claims, social-media reaction or model-generated inference into news. No model or agent may waive a gate, change the governing policy, treat a timeout as approval or publish merely to satisfy a quota.

## 3. Geographical scope

Each story has one or more geography labels. These identify where the event occurred or the decision was made and any other place where the evidence establishes a material effect.

For example, a UK decision changing BN(O) status may carry both UK and Hong Kong labels. A reader filtering for either geography sees the story.

### 3.1 United Kingdom

UK coverage includes both national and local news. UK stories may carry three levels of geographical information:

1. UK-wide;
2. England, Scotland, Wales or Northern Ireland; and
3. the relevant city, county, borough, council or other meaningful locality.

A story stops at the most specific location supported by the evidence. The system must not infer a more precise location.

### 3.2 Hong Kong

Hong Kong is one geographical section. It is not subdivided into districts for filtering or navigation.

Hong Kong coverage does not need to prove a direct UK effect. News about Hong Kong has intrinsic value to readers whose family, property, finances or future decisions remain connected to Hong Kong.

### 3.3 Global

Global is one geographical section. It is not subdivided by country or continent.

A world story normally qualifies only when it:

- affects safety in the UK or Hong Kong;
- affects energy, food, travel, supply chains, currencies, interest rates or household costs;
- changes UK or Hong Kong policy;
- affects travel or contact between the two places;
- creates a material risk for families connected to both; or
- is an event of exceptional international public importance.

The effect should be explained naturally where evidence supports it. Stories must not contain a repetitive, formulaic "why this matters to you" section.

## 4. Content categories

Every story has at least one content category as well as its geographical information. A story may belong to several categories when the same report genuinely spans them, but categories are not added merely because the article mentions a subject in passing.

| Category | Typical coverage |
|---|---|
| Politics and law | Government decisions, legislation, elections, courts and civil rights |
| Immigration and status | BN(O), visas, settlement, citizenship, asylum and irregular migration policy |
| Safety and crime | Verified incidents, police warnings, charges, court outcomes and public safety |
| Weather and disasters | Storms, flooding, extreme weather, fires and environmental hazards |
| Transport and infrastructure | Material disruption, strikes, closures, major works and policy changes, including major UK-Hong Kong aviation, airport or airspace disruption, route changes, travel-rule changes and passenger-rights developments |
| Health and healthcare | Public health, outbreaks, NHS and Hospital Authority policy, medicines and service changes |
| Education and campuses | Early years through university, admissions, examinations, closures, safety and policy |
| Tax and welfare | Tax, benefits, pensions, household support and official deadlines |
| Work and employment | Employment rights, strikes, major redundancies, labour policy and job scams |
| Housing and local life | Rent, mortgages, housing policy, building safety, planning and utilities |
| Economy and finance | Inflation, interest rates, currencies, major market events and household effects |
| Consumer rights and scams | Recalls, service failures, fraud, refunds, data breaches and consumer protection |
| Technology and cyber security | Major outages, cyber incidents, technology policy and safety |
| War and international affairs | Wars, sanctions, diplomacy, supply chains and material international risks |
| Community and public services | Council services, consultations, support programmes and material community changes |

### 4.1 Explicit exclusions

The product does not cover:

- entertainment, celebrity news or gossip;
- ordinary sports results, transfers or club news;
- restaurant, shopping, hotel or lifestyle recommendations;
- product round-ups, discount codes or affiliate-style content;
- general event listings or commercial community promotion;
- ordinary individual flight, train or road delays;
- live flight tracking or a general transport status service;
- world news with no material UK, Hong Kong or exceptional public-interest connection; or
- opinion columns, editorials or party-political advocacy.

An entertainment or sporting event may still be reported when it causes a material transport, safety or public-service effect. It is then covered under the relevant public-impact category, not as entertainment or sport.

## 5. Newsworthiness and publication volume

Monitoring may run every hour, but there is no hourly, daily or category publication quota.

A story is published only when it has sufficient evidence and substantive new information. The product must not create filler to maintain activity, balance categories or meet a word target.

Transport, aviation, weather and utility incidents become news when they affect a meaningful group of people, last for a material period or have a clear effect on daily life. The app does not reproduce every service-status update.

For internal selection, a story normally qualifies when verified facts establish at least one of the following:

- a change to a law, right, status, official deadline or public policy;
- a credible effect on safety or public health;
- material disruption to an essential service, route, school, workplace or locality;
- a practical effect on household money, work, housing, education, healthcare or UK-Hong Kong travel;
- an official deadline, instruction or process that affected readers may need to act on; or
- exceptional public importance in Hong Kong or internationally.

This is a news-selection test, not a reader-facing urgency score. An ordinary delayed flight, a short isolated road closure or a generic foreign political statement without one of these effects does not qualify.

There is no fixed morning briefing, evening briefing, daily top-ten list or popularity chart in the initial product.

## 6. Evidence and source policy

### 6.1 Source tiers

Sources are assessed in four tiers:

1. **Primary and official evidence:** legislation, court judgments, government documents, official statistics, police and emergency-service statements, school or transport notices, regulatory filings and company announcements.
2. **Established news organisations:** reporting with a visible editorial process, sourcing and corrections practice.
3. **Local and specialist publications:** useful for local or subject-specific coverage, with additional corroboration where the claim is material.
4. **Lead-only sources:** social media, forums, blogs, anonymous sites, messaging groups and unattributed screenshots.

Tier four may reveal a possible story. It cannot establish that the story is true.

### 6.2 Evidence gate

Where authoritative primary evidence exists, the article uses it directly and states where it was found. Examples include:

- HMRC for tax rules;
- the Immigration Rules or Home Office guidance for immigration policy;
- ONS for official statistics;
- the Met Office for UK weather warnings;
- a school or council notice for a closure;
- National Rail or the operator for a material rail disruption;
- a published judgment for a court decision; and
- Hong Kong legislation, Gazette notices or department publications for Hong Kong policy.

If no public, reliable evidence can be found, the system rejects the item or holds it only where an authorised reviewer could resolve a defined uncertainty. It does not contact witnesses, ask a family for private documents or continue as an investigator.

The minimum evidence gate depends on the claim:

| Claim type | Minimum publication basis |
|---|---|
| Official rule, decision or deadline | The current primary document may establish what the responsible body decided, published or brought into force. |
| Official number or dataset | The originating publication, dataset, table or release may establish the reported figure for its stated reference period. |
| Developing incident or service disruption | An authoritative body or operator confirms the observable facts. If no suitable primary source exists, at least two independent, reliable published sources must corroborate the same narrow fact. |
| Other factual event | A directly responsible authoritative public source confirms the narrow fact, or at least two independent, reliable published sources corroborate it. |
| Serious allegation, identity, motive or criminal responsibility | Appropriate public, verifiable evidence and a recorded defamation, privacy and court-risk assessment are required. Without both, the allegation is not published. |
| Analysis, model or forecast | A named, credible and traceable source must have published the analysis and its evidential basis. |

Several outlets repeating the same originating report do not count as independent corroboration.

### 6.3 Official fact versus official opinion

An official source can establish what that body decided, did, recorded or publicly stated, when a rule starts, what a document says or what an official data series reports.

It does not automatically prove an allegation about another person, disputed conduct, causation, guilt or the body's own assessment of success and blame. A police statement may establish that a person was arrested or charged; it does not establish guilt. A published programme cost may be a fact, while a minister's assertion that the programme was a success remains the minister's assessment unless supported by evidence.

A statement is not automatically a standalone story merely because an official made it. It must record a decision, cause a material public consequence or have another independent news value. A headline or introduction does not repeat an unproven official allegation as an unqualified fact.

### 6.4 Anonymous sources

A core factual claim supported only by an unnamed official, anonymous source, leak or unverifiable screenshot is not published as confirmed news.

Attribution to an established news organisation does not make an anonymous or unverifiable allegation publishable. Repeating that allegation may repeat the same legal and factual harm. The app waits for public, verifiable evidence before reporting the underlying claim.

### 6.5 Data

Data reporting must identify the provider, publication, reference period, relevant dataset, table or section where applicable, and a direct source link.

Comparisons are reproduced only when the same authoritative source has itself published the comparison using a consistent definition. The system does not calculate new comparisons, rates, ratios, rankings or per-capita figures under this charter.

If a definition changed, figures from before and after the change are not presented as directly comparable.

### 6.6 Social media

Official social accounts may serve as official statements. Other social posts are leads only.

The product does not publish articles based on "online outrage", a handful of comments, likes or unattributed videos. Formal polling may be reported according to its published result and method, without extrapolating beyond what the poll establishes.

### 6.7 Attribution in the article

The source is identified clearly when a fact is first introduced. Consecutive facts from the same clearly identified source do not need a repetitive attribution in every sentence.

Disputed claims, analysis, estimates, forecasts and an organisation's assessment of its own performance are attributed individually. Full source links remain in the article footer.

## 7. Analysis policy

The app does not invent analysis.

Analysis may be included when it is traceable to:

- an official or regulatory assessment;
- a named expert;
- an academic study;
- a published institutional model;
- an established market or sector analysis; or
- historical data that the source itself uses to support the conclusion.

The analyst or organisation must have relevant expertise, and the method, evidence or data must be traceable enough to assess the claim. The article identifies a material commercial, political or advocacy interest where one is apparent. A title such as "expert", "analyst" or "think tank" is not sufficient by itself.

The article identifies who made the analysis, the evidence used and any stated conditions. For example:

> Reuters reported, citing named energy analysts, that a prolonged shipping disruption could raise refining and transport costs.

The app may explain this analysis in clear Chinese, but it must not present it as the app's own prediction. If no credible published analysis exists, the article reports the facts and omits speculative effects.

Identity, motive, collective behaviour and criminal responsibility are not inferred. They are reported only when established by an appropriate official source or court.

## 8. Originality and copyright

### 8.1 Text

The app must not:

- translate an entire source article;
- closely paraphrase it paragraph by paragraph;
- reproduce its structure, distinctive selection or analysis as a substitute for the original;
- reconstruct paywalled reporting from fragments; or
- treat attribution as permission.

The app may use facts, public records and lawfully reusable data to write a new report with its own structure. Public availability does not automatically permit copying the wording, table, chart or image.

Direct quotation is limited to wording that matters, such as a statutory phrase, official commitment or material statement. It must be fair, no more than necessary and sufficiently acknowledged. The speaker, document and date are identified, and the original wording may be shown beside the Chinese translation when precision matters. The current-events copyright exception does not permit copying a news photograph.

Source links provide evidence and transparency. They do not transfer the checking responsibility to the reader.

### 8.2 Source access and storage

Lawful publication of an original article does not automatically make every collection method lawful. Before any automated retrieval, copying, extraction, storage or model submission begins, including during development or prototyping, the source's access and use require a documented rights review covering:

- access terms;
- automated retrieval, extraction and access-control restrictions;
- full-text, headline, snippet, metadata, cache and embedding rights;
- whether material may be submitted to a model or other service and how that provider retains it;
- commercial reuse rights;
- quotation and attribution requirements; and
- retention, deletion and repeated database-extraction limits.

Development for a commercial product must not assume that the UK text-and-data-mining exception applies merely because the product has not launched: the present exception is limited to non-commercial research. Detailed ingestion, retention and storage design remains outside this charter.

The product must not store or redistribute publisher text, photographs or paywalled content beyond the rights granted by the source or applicable law.

## 9. Visual policy

The visual hierarchy is:

1. a real, event-specific image with a valid editorial licence or explicit reuse permission;
2. an independently created factual information graphic based only on verified material; and
3. a consistent branded news card when neither of the first two is suitable.

### 9.1 Real photographs

An event photograph may be used only when the app can record:

- the rights holder or authorised licensor;
- the licence or permission;
- the permitted platform, territory and duration;
- the required credit; and
- any limits on cropping, editing or reuse.

Copyright clearance is separate from subject and content clearance. Before publication, the system must complete the applicable check for a protected identity, child, victim, person receiving medical treatment, private information, number plate or other detail that creates privacy, data-protection, reporting-restriction or contempt risk. An indeterminate result prevents automatic publication.

An image on a government or police page is not assumed reusable. The page must explicitly place the image under an applicable licence, and any third-party credit or excluded logo must be respected.

### 9.2 No AI transformation of unlicensed photographs

The app must not upload an unlicensed BBC, agency, social-media or other publisher photograph to an image model and turn it into a cartoon, Q-style image, painting, tracing, recolouring or other derivative.

This is a strict product rule rather than a claim that every style conversion is automatically unlawful. Uploading the source may itself make or transfer an unauthorised copy, and the output may separately infringe if it reproduces a qualitatively substantial part of the original photograph's composition or expression.

### 9.3 Factual information graphics

An information graphic visualises verified facts without pretending to be a photograph of the event. It may show:

- a route or location map;
- affected junctions, lines or areas;
- a timeline;
- official numbers;
- an old-versus-new policy comparison;
- service changes; or
- a sourced chart.

Every factual element must be supported by a listed source. The graphic carries its source time and an explicit description such as:

> Incident information graphic based on police and National Highways data. Not an image of the scene.

The graphic must not invent a vehicle model, colour, number of ambulances, weather condition, injury or cause.

Simple, independently drawn or properly licensed icons may represent a verified fact, such as a closure, ambulance response or weather warning. They must not reconstruct the scene, imply an unsourced spatial arrangement or imitate the composition of a source photograph. Base maps, source charts and underlying datasets also require appropriate reuse rights; the team does not trace a proprietary map or chart.

### 9.4 File images

A licensed generic or file image may be used when it adds genuine context. It must be labelled clearly as a file image and must not imply that it depicts the reported event.

### 9.5 Prohibited visuals

The product does not use:

- unlicensed publisher images, thumbnails or screenshots;
- photorealistic or cartoon scene reconstructions of accidents, crimes, wars or disasters;
- fabricated people or scenes presented as evidence;
- unnecessary graphic injury or death imagery; or
- visuals whose factual details cannot be sourced.

## 10. Writing and presentation

### 10.1 Language

Articles use Traditional Chinese in a Hong Kong written register, with a natural Cantonese voice where appropriate. They do not use forced colloquial writing for serious news.

The first reference to an unfamiliar UK institution or policy gives a clear Chinese explanation and preserves the official English name or abbreviation, for example:

> 永久居留（Indefinite Leave to Remain，ILR）

Where no settled Chinese translation exists, the official English term is retained rather than replaced with an invented translation.

### 10.2 Neutrality

The app is non-partisan. It does not endorse parties or candidates, publish editorials or disguise opinion as news.

Neutrality does not require weakening a proven fact or giving an unsupported claim equal status. Confirmed facts are stated clearly. Claims, proposals and opinions are attributed to their source.

Politically sensitive place names, institutions and identities use common neutral Hong Kong terminology and official names. Loaded labels and political slogans appear only when their use is itself material and attributed.

### 10.3 Headlines

Headlines state the place, event and most important confirmed development. They must not:

- use clickbait or emotional bait;
- imply an unconfirmed cause;
- turn a possibility into a certainty;
- treat arrest or charge as conviction; or
- insert immigration status, nationality or identity when it is not materially relevant and officially confirmed.

### 10.4 Length and structure

There is no fixed word count. A local disruption may need only a few paragraphs. A complex tax, immigration or international story may require a longer explanation.

The article stops when the reader has enough verified information to understand the story. It must not add generic conclusions or filler to meet a target length.

The following are an internal editorial checklist, not mandatory visible headings:

- what happened;
- what is confirmed;
- whether any published figure or status is expressly provisional according to the authoritative source;
- what changed;
- whether there is a sourced effect on UK or Hong Kong readers; and
- whether any official action or deadline matters.

### 10.5 Dates and times

An event uses the local time at the place of the event. Important cross-border deadlines may show both UK and Hong Kong time. GMT, BST and HKT are stated where ambiguity matters.

Full dates are preferred over relative phrases such as "today" when the information needs to remain clear in the archive.

## 11. Sensitive coverage

### 11.1 Names and personal information

A public office-holder or authorised organisational representative may be named in connection with an official public act or statement when a formal source confirms the identity and role, the identity is relevant, and no legal restriction applies.

For any other person, the four agreed conditions for editorial eligibility are:

1. a reliable, formal source has published the identity;
2. the identity is directly relevant to the story;
3. the system or an authorised reviewer has confirmed that it is the same person;
4. no court order, automatic reporting restriction or other legal protection prohibits identification.

Meeting those four conditions does not itself create legal permission to publish. For a private person, or any person named in connection with an allegation, victimhood, suspected offending, sensitive personal information or non-public conduct, the publication decision record must also state why identification is necessary and proportionate, likely harm, any reasonable expectation of privacy, any less intrusive alternative, and any special-category or criminal-offence data involved.

Public availability alone does not remove privacy, accuracy or court-reporting duties.

### 11.2 Children and schools

Coverage may include early years, schools, colleges and universities. The app reports verified closures, outbreaks, safety incidents, admissions, examinations, fees, strikes and policy changes.

It does not identify protected children, reproduce parent-group rumours or publish unverified allegations about pupils or staff.

### 11.3 Crime

Arrest, charge, trial, conviction and sentence are distinct stages. The correct term is used at each stage.

Race, religion, nationality, immigration status and motive are not inferred. They appear only when officially established and materially relevant.

Before publishing or updating any story that touches current or contemplated legal proceedings or protected court material, the system must complete the current jurisdictional check required by the accepted specification. If that check cannot produce a reliable result, the story is held for authorised review. This includes criminal and civil proceedings, family cases, appeals and inquests, not only arrest, charge, trial and sentencing reports. The check covers:

- whether proceedings are active;
- automatic and court-ordered reporting restrictions in the relevant jurisdiction;
- protected complainants, witnesses, children and family proceedings;
- postponement or anonymity orders;
- jigsaw identification through combined details; and
- prejudice to the current case or linked proceedings.

A search that finds no named anonymity order is not enough. If the applicable restriction or active-proceedings position cannot be established, the identifying or prejudicial detail is omitted and the story is held where necessary.

### 11.4 Health

The app reports public-health evidence, service changes and sourced medical analysis. It does not diagnose readers, tell them to stop or change treatment, or present a small preliminary study as a proven cure.

### 11.5 Finance

The app reports economic policy, household finances and major market effects. It does not provide stock tips, price targets, personalised investment instructions, crypto promotion or affiliate-style financial content.

### 11.6 War

Claims by a belligerent remain attributed claims. Casualty figures use the source's own categories and state the source and reporting time. Where the source distinguishes civilians and combatants, or deaths and injuries, the article preserves that distinction. Where it does not, the article says so and does not estimate the split.

The app does not publish operational details that may endanger people, graphic imagery, propaganda as fact or unsupported predictions about victory, collapse or an end date.

### 11.7 Suicide and self-harm

Coverage requires clear public importance. It avoids method details, simplistic explanations, romanticisation, suicide notes and unnecessary identification of the person or family.

## 12. Article lifecycle and app presentation

### 12.1 Feed and filtering

The main feed shows all published stories in reverse order of first publication. It does not rank by popularity, clicks, inferred preference or editorial importance.

Readers may filter by:

- UK, Hong Kong or Global;
- UK locality where applicable; and
- one or more content categories.

The editorial system does not assign red, amber or other urgency levels.

All published stories remain available in the app regardless of notification settings. Notifications are optional and use a simple on/off control. When enabled, they follow the reader's selected geography. There is no separate emergency-notification mode or urgency-based notification tier.

### 12.2 Developments and related stories

A material new development receives a new article. The original article is not continually rewritten to absorb every later event.

A development is material when it adds a newly confirmed decision, rule, deadline, official finding, charge, judgment, measurable change or substantive incident outcome. A new article leads with that development and repeats only the background needed to understand it.

Articles about the same event, case, policy, bill or formal process link to one another as related stories. A shared keyword or broad category is not enough. For example, an arrest, charge and judgment in one case are related; two unrelated immigration stories are not.

### 12.3 Article metadata and accountability

The article header shows:

- title;
- first publication time;
- last update time, when applicable;
- geography or geographies;
- content category or categories; and
- the responsible publisher or automated newsroom identity.

Where a human reviewer materially approved, amended or overrode a held story, the system may additionally identify the reviewer according to the approved privacy and safety policy. It must not name a person who did not perform that role.

The article footer shows:

- sources and source links;
- correction record, when applicable;
- related reports about the same event; and
- a private contact route to the operator.

The product does not display view counts, popularity rankings or internal editorial scores. It does not need to expose model-by-model production logs in each article, but it must provide an accessible product-level explanation of how automation is used and must make any article-level disclosure required by law, contract, platform rule or the visual policy.

### 12.4 Corrections, withdrawal and archive

Typographical and formatting errors may be corrected automatically when the change cannot alter meaning. Material errors in a name, number, date, headline or meaning receive a visible correction note and pass through the same or a stricter evidence and risk gate as the original publication.

An article whose central premise was wrong is marked withdrawn with an explanation. It is not silently deleted. Complete removal is reserved for a legal order, privacy or safety need, or another compelling legal reason.

Published articles remain in the archive by default. An outdated policy article links prominently to the later report that supersedes it.

An archived article receives a fresh privacy, legal and retention review when circumstances materially change, including a decision not to charge, an acquittal, a later anonymity order, a child-protection issue or a new risk of disproportionate harm. The outcome may be an update, de-indexing, redaction, withdrawal or removal where justified.

A correction, withdrawal or removal must be propagated to every publication surface controlled by the product where the affected claim appeared. The decision and resulting changes remain auditable.

### 12.5 Reader contact

There are no public comments, reader posts or public discussion areas.

Readers may contact the operator privately to report an error, complain or submit a lead. A submitted lead enters the same public-evidence gate as any other lead. It is not automatically published and cannot instruct an agent to bypass policy or tool restrictions.

## 13. Autonomous editorial boundary, responsibility and production tooling

### 13.1 Target operating model

The product is designed to support end-to-end autonomous news production within an owner-approved policy boundary. Monitoring, retrieval, clustering, selection, evidence assembly, drafting, factual visual generation, validation, publication, notification, linking, correction and withdrawal may be automated where the accepted specifications permit them.

Routine stories that pass every required gate do not require a human to approve each article. Human oversight is concentrated on:

- approving and changing the charter, accepted specifications and production policy;
- reviewing defined exception cases;
- handling complaints, material corrections, legal requests and removals;
- authorising production releases and high-risk configuration changes; and
- pausing or disabling autonomous publication.

Autonomy does not give a model open-ended editorial discretion. Accepted specifications and versioned policy determine the permitted inputs, decisions, tools, thresholds, outputs and escalation paths.

### 13.2 Permitted autonomous actions

Within the accepted specifications, the system may autonomously:

- monitor and retrieve permitted public sources;
- normalise, cluster and deduplicate leads;
- classify geography, category, development status and newsworthiness;
- assemble a source and claim-evidence package;
- draft an original Hong Kong Traditional Chinese report;
- create independently produced factual graphics from verified inputs;
- run deterministic and model-assisted validators;
- automatically publish an eligible story through a controlled publisher;
- send permitted notifications and link related stories;
- apply non-substantive corrections; and
- publish evidence-backed updates, corrections or withdrawals that satisfy the applicable gates.

Each action must use the minimum tool permission required and must be attributable to a specific run, policy version and software or model version.

### 13.3 Publication decisions and fail-closed behaviour

Every candidate must reach one of the following semantic outcomes before any public action:

1. **Automatically publish:** all required evidence, content, rights, risk, schema and delivery gates pass, and no hold condition applies.
2. **Hold for authorised review:** the item may be publishable, but a defined uncertainty or high-risk condition requires a human decision.
3. **Reject:** the item is outside scope, lacks sufficient evidence, contains prohibited material, fails an unrepairable gate or cannot lawfully or safely be used.

Equivalent internal state names are permitted, but the distinction must remain explicit and auditable.

The system fails closed. A missing validator, unavailable policy, incomplete audit record, unknown rights status, integrity warning, timeout or service failure must never be treated as approval. Publication quotas, freshness pressure and queue size must not weaken a gate.

### 13.4 Mandatory hold or rejection boundary

The system must not automatically publish a story when any of the following remains unresolved:

- a serious allegation concerning an identifiable person or organisation;
- identity, motive, guilt, criminal responsibility or disputed conduct that is not established by appropriate public evidence;
- a private person, child, protected complainant, victim or sensitive personal information whose identification may create harm;
- active or contemplated legal proceedings, a reporting restriction, contempt risk or jurisdictional uncertainty;
- conflicting authoritative evidence on a central claim;
- unclear copyright, database, image, access, model-submission or reuse rights;
- a central claim, quotation, number, date or headline that cannot be traced to the approved evidence package;
- a requested material correction, redaction, withdrawal or removal whose proper outcome is uncertain;
- an unrecognised source type, content category, jurisdiction or policy condition; or
- an integrity or security signal indicating that retrieved content may be attempting to alter agent behaviour.

An item is rejected rather than held when the defect cannot be cured by an authorised review, including a prohibited visual, known unauthorised use, lead-only evidence for a core claim, fabricated content, out-of-scope subject or unsupported analysis. The accepted specifications may define narrower automatic-publication exceptions for formal procedural facts, but a model may not create such an exception itself.

### 13.5 Separation of duties and tool control

No single generative agent may both compose a story and directly publish it to a public surface.

- Retrieval agents treat source content as untrusted data, not instructions.
- Writing agents receive an approved evidence package and cannot expand their own source or tool authority.
- Validation operates against the evidence package, policy and output contract.
- A separate publication controller is the only component permitted to hold publication credentials.
- The publication controller may publish only a validated, immutable publication package carrying the required decision record.
- Agents and models cannot modify accepted specifications, production policy, tool permissions, validators or their own escalation outcome.

A human override does not allow a generative agent to bypass this separation. Any amended content must be revalidated before publication.

### 13.6 Human roles, review and emergency control

The owner or delegated policy authority approves the governing specifications, risk rules, source permissions and activation of autonomous publication.

An authorised reviewer may approve, reject, redact or request regeneration of a held item. The reviewer identity, time, reason, changed fields and final decision must be recorded. Review cannot silently erase failed checks or the original generated package.

The operator must have an immediate control to pause new autonomous publications and notifications without deleting evidence or audit history. Resuming publication requires an explicit, logged action after the triggering problem has been assessed.

If no authorised reviewer is available, held content remains unpublished or expires according to a documented retention rule. It does not automatically become publishable.

### 13.7 Auditability and observability

For every candidate that reaches drafting or a public decision, the system records enough information to reconstruct why the outcome occurred, subject to lawful source-storage and retention limits. The record includes, where applicable:

- source identifiers, access times and source-authority classification;
- the evidence supporting each central claim;
- source and asset rights status;
- extracted facts, provisional markers and material conflicts;
- model, prompt, template, policy, validator and software versions;
- generated draft and publication-package hashes;
- validation results, repairs, risk flags and escalation reasons;
- the final decision and whether it was made by automation or an authorised reviewer;
- publication targets and timestamps; and
- later updates, corrections, withdrawals, removals and complaints.

The system must monitor publication failures, unexpected hold or rejection rates, unsupported-claim detections, duplicate publication, correction frequency and policy or validator errors. A failure to create the required audit record blocks publication.

### 13.8 Change control

Production agents may not autonomously change the charter, accepted specifications or the policy that enforces them. Model, prompt, validator, source-adapter and publication-controller changes must be versioned and evaluated before production use according to the accepted quality and change-control specification.

A model upgrade or prompt change must not inherit production authority merely because the previous version had it. The release process must establish that the new version still satisfies the accepted requirements and can be rolled back.

### 13.9 Reader-facing accountability

The product maintains a clear, accessible explanation that the newsroom uses automated and generative systems, what those systems are permitted to do, what conditions cause human review, how readers can report errors and who operates the service.

Each article identifies the responsible publisher or automated newsroom identity, its sources, publication and update times, and corrections. A human is identified as reviewer or author only when that statement is true under the recorded workflow. The product must not claim that machine-assisted content was wholly written or approved by a person when it was not.

The product does not need to expose internal prompts, model reasoning or complete production logs to readers. Any disclosure required by law, platform rules, provider terms, distribution territories or the visual policy overrides this presentation rule.

## 14. Legal risk posture

This model materially reduces risk compared with translating and republishing a source article, but it does not remove publisher responsibility. Autonomous publication changes who or what makes the operational decision; it does not transfer legal responsibility away from the operator.

The applicable law is not uniform across England and Wales, Scotland, Northern Ireland, Hong Kong or other distribution territories. Defamation, privacy, child-protection and court-reporting checks must use the law of the relevant jurisdiction rather than a generic UK assumption.

The operator remains responsible for:

- copyright and database rights;
- defamation and malicious falsehood;
- privacy and data protection;
- court-reporting restrictions and contempt;
- the rights and licence terms attached to photographs, graphics, feeds and data;
- the design, validation and monitoring of autonomous publication controls; and
- accurate corrections and takedown decisions.

The following are launch prerequisites under this draft. They must be represented in accepted specifications and approved by the owner before autonomous public publication is enabled:

1. a source and asset rights register;
2. a prohibited-source and prohibited-use list;
3. a written correction, complaint and removal process;
4. a court, child, privacy and allegation risk policy with machine-actionable hold and reject conditions;
5. a fail-closed publication controller, complete decision audit, exception queue and emergency stop;
6. a versioned evaluation and change-control process for models, prompts, validators and source adapters; and
7. a review by appropriately qualified media and copyright lawyers for the UK jurisdictions, Hong Kong and any other material distribution territory, using representative article, automation and visual examples.

This charter is an editorial and automation policy, not a guarantee that a particular story, automated decision or asset is lawful.

## 15. Worked example: M4 vehicle incident

Assume established reporting says that a vehicle overturned on the M4 and emergency services attended.

The autonomous system must:

1. verify the location, time, road status and confirmed casualties through police, National Highways or other authoritative public material;
2. publish only the details those sources support;
3. write an original report and cite the sources;
4. use the original scene photograph only if a suitable editorial licence has been obtained and recorded;
5. never feed an unlicensed publisher photograph to an image model to create a Q-style or other derivative image;
6. if no licensed photograph is available, create a sourced route map, timeline or incident card labelled as an information graphic rather than an image of the scene; and
7. automatically publish only if every evidence, rights, content and risk gate passes; otherwise reject the item or hold it for authorised review according to the defined reason.

The graphic may show the affected junction, direction, closure, confirmed response and update time. It must not invent the vehicle type, colour, people, number of ambulances, weather or cause.

This example is intended to show the autonomy boundary: routine, well-sourced public-service reporting can proceed without per-story human approval, while uncertainty about casualties, identity, cause, image rights or legal risk prevents automatic publication.

## 16. Out of scope for this charter

The following require separate product or engineering decisions and are deliberately not settled here:

- price, billing, trials or subscription design;
- account creation and identity-provider behaviour;
- App Store and Play Store implementation;
- model, provider, agent or SDK choice;
- newsroom infrastructure and hosting;
- detailed ingestion, storage and retrieval architecture;
- marketing, acquisition and revenue planning; and
- implementation changes to the existing repository, which require accepted specifications and implementation plans.

## 17. Selected authoritative legal references

- [Copyright, Designs and Patents Act 1988](https://www.legislation.gov.uk/ukpga/1988/48/contents)
- [UK Intellectual Property Office: exceptions to copyright](https://www.gov.uk/guidance/exceptions-to-copyright)
- [UK Intellectual Property Office: digital images, photographs and the internet](https://www.gov.uk/government/publications/copyright-notice-digital-images-photographs-and-the-internet/copyright-notice-digital-images-photographs-and-the-internet)
- [Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
- [Defamation Act 2013 (England and Wales)](https://www.legislation.gov.uk/ukpga/2013/26/contents)
- [Defamation and Malicious Publication (Scotland) Act 2021](https://www.legislation.gov.uk/asp/2021/10/contents)
- [Data Protection Act 2018](https://www.legislation.gov.uk/ukpga/2018/12/contents)
- [ICO Data protection and journalism code of practice](https://ico.org.uk/media2/migrated/4025760/data-protection-and-journalism-code-202307.pdf)
- [GOV.UK contempt of court guidance](https://www.gov.uk/contempt-of-court)
- [Crown Prosecution Service: contempt of court guidance](https://www.cps.gov.uk/prosecution-guidance/contempt-court)
- [UK Government report on Copyright and Artificial Intelligence](https://www.gov.uk/government/publications/report-and-impact-assessment-on-copyright-and-artificial-intelligence/report-on-copyright-and-artificial-intelligence)
