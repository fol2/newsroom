# Discovery reliability and operations specification

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
**Accepted search contract:** [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md)  
**Accepted evaluation contract:** [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Decision state:** The scheduling, health, retry, quarantine, capacity, monitoring, recovery and operational-admission rules below are proposals. Committing this Draft does not authorise a source, schedule, provider, credential, shadow run, production process or public action.  
**Supersedes:** None

## Purpose

Define the operational conditions under which discovery components can run reliably without confusing silence with failure, retries with new work, source absence with source action or a healthy individual adapter with adequate portfolio coverage.

The contract turns the accepted semantic design into an operable system while remaining implementation-neutral. It establishes what must be configured, measured, alerted, contained, reconciled and proven before a discovery scope can receive production authority.

## Scope

This specification defines:

- versioned Operational Profiles and scoped admission decisions;
- cadence classes, due-work semantics, jitter, missed schedules and catch-up;
- execution ownership, leases, heartbeats, concurrency and idempotency;
- multidimensional source, dependency and coverage health;
- transport, response and parser-contract safeguards;
- retry, backoff, circuit-breaker and quarantine behaviour;
- queueing, backpressure, fairness, expiry and capacity controls;
- durable transition, downstream-delivery and reconciliation requirements;
- operational metrics, logs, alerts, runbooks and incidents;
- security boundaries for source access and untrusted content;
- backup, restore, replay and disaster-recovery evidence;
- canary, rollout, rollback, containment and source-version changes; and
- scoped operational qualification after accepted evaluation evidence.

It does not select a scheduler, agent framework, queue, database, observability service, deployment platform or on-call vendor. It does not set one global polling interval or numerical SLO. Exact values are source- and scope-specific, require evidence and are recorded in an owner-approved Operational Profile before executable use.

It does not authorise production. Topic 12 maps accepted requirements to implementation and migration, and a separate owner activation decision remains required.

## Current-system replacement boundary

The legacy system contains useful implementation experience but does not satisfy this target contract:

- `newsroom/rss_news.py` silently falls back to broad built-in feeds when configuration is missing, empty or invalid;
- malformed RSS or Atom XML is returned as an empty article list, after which the fetch is recorded as successful;
- RSS requests do not retain per-source validators, watermarks, health state or source-specific revision contracts;
- the current collector uses a fixed inter-request delay rather than source and host budgets, `Retry-After`, jitter and circuit state;
- `scripts/news_pool_update.py` records page errors but advances shared fetch state after any successful page, which is not the accepted per-request and partial-outcome model;
- current cron cadence and LLM early-exit behaviour do not establish source freshness, queue fairness, operational coverage posture or crash reconciliation; and
- SQLite WAL and a connection timeout provide useful local concurrency behaviour but do not by themselves prove leases, atomic downstream delivery, backup, restore or recovery.

These are current-state observations, not implementation instructions. Topic 12 decides how to replace or isolate them.

## Operational principles

1. **Successful silence is proved.** `Unchanged` exists only after a complete successful check under the exact source contract.
2. **Freshness is not last change.** A source can be healthy for months without changing; health uses last successful observation, not last news item.
3. **Coverage consequence drives priority.** A sole Urgent Anchor becoming stale matters more than many redundant Comparator errors.
4. **Profiles are source-specific.** Observation model, cadence, timeout, retry, health and catch-up behaviour are versioned per scope.
5. **At-least-once work has at-most-once semantic effects.** Duplicate delivery and crash replay do not create duplicate transitions.
6. **Retries are bounded.** Backoff protects sources and the Newsroom; it does not hide stale coverage or create retry storms.
7. **Quarantine protects integrity.** Unsafe or ambiguous adapters stop automatically within the affected scope and preserve history.
8. **Fallback is explicit.** A contingency has a named role, activation decision, limit and coverage consequence.
9. **Backpressure is visible.** Capacity limits retain or close work through accepted decisions rather than silent loss.
10. **Dependencies fail honestly.** Storage, scheduler, network, parser, model, retrieval, search and Evidence Intake failures remain distinguishable.
11. **Recovery is designed before failure.** Reconciliation, replay, restore and rollback are tested, not improvised during an incident.
12. **Production authority is scoped and versioned.** One healthy source or successful Run does not authorise the whole portfolio.

## Operational records

These are semantic contracts, not required tables or services.

### Operational Profile

An immutable, owner-approved configuration for one exact Source Definition Version, Search Purpose and provider version, worker or retrieval dependency, queue class, Evidence Intake boundary or other operational scope.

Where applicable it records:

- accepted coverage role, portfolio function and urgency class;
- trigger type, cadence or event source and permitted active windows;
- maximum due-to-start delay and maximum age since a successful qualifying observation;
- connection, read, total execution and body-size limits;
- conditional-request and cache-validator behaviour;
- host concurrency, rate, request and cost limits;
- retryable and non-retryable outcomes;
- retry count, elapsed retry horizon, backoff, jitter and `Retry-After` policy;
- first-run, catch-up, reset and missed-schedule policy;
- complete, partial and malformed-response contract;
- queue, batch, deadline and starvation controls;
- required dependencies and degraded-operation permissions;
- health dimensions, warning and critical conditions;
- circuit-breaker and quarantine criteria;
- contingency paths and their limits;
- metrics, alerts, owner and runbook;
- backup, restore, reconciliation and rollback requirements;
- approved credentials, network destination and security controls;
- evaluation and release-evidence references; and
- known limitations and coverage consequence when unavailable.

A material value change creates a new Profile version. Runtime agents cannot edit it.

### Schedule Occurrence

One immutable record that a versioned trigger became due, fired or was received. It distinguishes scheduled time, actual scheduler observation time, allowed start window, missed or coalesced state and the resulting Check Request or other authorised work.

A scheduler tick is not a Schedule Occurrence for every source unless that source was actually due.

### Execution Lease

A bounded ownership claim for one exact queued operation or state version. It prevents concurrent workers from committing competing effects while allowing recovery after verified expiry.

Lease expiry alone does not prove the previous worker failed before performing an external action. Ambiguous external effects require reconciliation before retry.

### Health Observation and Health Assessment

A Health Observation records one measurable operational fact, such as last complete success, transport failure, parser shape mismatch, queue age or budget state.

A Health Assessment is a versioned deterministic interpretation of observations for one component and scope. Current health is a rebuildable projection, not the only history.

### Coverage Availability Assessment

A scoped decision that records whether accepted coverage paths are operationally available, degraded, unavailable or unknown. It identifies the affected obligations, healthy paths, failed paths, approved contingencies, time since loss and required containment.

It does not redefine the coverage contract or treat a Comparator as an Anchor.

### Operational Incident

A stable case for an integrity, availability, latency, capacity, rights, security or authority-boundary problem requiring coordinated response. It links observations, affected scope, timeline, containment, recovery, root cause and follow-up.

### Contingency Activation

An immutable decision enabling one pre-approved contingency for an exact failed path, duration, budget and coverage role. It preserves the original failure and ends through an explicit deactivation or supersession decision.

### Operational Admission Decision

An owner decision that binds exact evaluated component versions, Operational Profiles, accepted gaps, capacity evidence, alerts, runbooks, recovery evidence, canary scope and rollback target.

Possible decisions include not ready, qualification required, canary eligible, production eligible for a bounded scope, Comparator-only, Held, quarantined, retired or blocked by coverage deficiency. Admission does not itself perform production activation.

## Scheduling and cadence

### Cadence classes

Operational Profiles use the accepted qualitative classes without forcing one interval across all sources:

- **Urgent current-state:** warnings, severe incidents and states where stale observation could hide active public risk;
- **Time-sensitive:** actionable rules, deadlines, service changes or developing disruptions;
- **Planned-window:** cadence that changes around a known Agenda window and its occurrence-confirmation requirement;
- **Routine:** lower-frequency source or portfolio checks with bounded fairness; and
- **Event-driven or manual:** authenticated webhook, authorised lead or bounded request rather than recurring polling.

Exact intervals and objectives are evidence-based Profile values. A source's published update interval, cache policy and provider limits constrain the profile; polling faster than meaningful source change is not automatically more reliable.

### Due-work semantics

One due occurrence creates at most one logical Check Request or authorised operation. Repeated scheduler ticks, process restarts and duplicate webhook delivery must not create another logical obligation for the same due identity.

The scheduler and preflight complete without a model. If nothing is due, the tick ends without downstream work.

### Jitter and coordinated load

Clocked requests use bounded jitter where it does not violate an Urgent or Planned window. Jitter prevents all sources and hosts being hit at the same wall-clock boundary. Per-host concurrency and rate limits remain enforceable across workers.

### Missed schedules and catch-up

Scheduler downtime, lease contention or host unavailability creates a visible missed or delayed occurrence. Catch-up policy is source-specific:

- maintained pages may need one current-state check rather than one request per missed interval;
- append-only feeds may use a bounded backfill or watermark window;
- current-state warnings may require immediate current observation plus preserved uncertainty about the missed interval;
- Planned paths retain the expected window and missed-confirmation semantics; and
- high-volume historical work may be coalesced only through an explicit rule that preserves the coverage consequence.

Restart must not cause an uncontrolled historical request or Signal storm.

### Time correctness

Source-asserted time, planned time, scheduler wall-clock time, monotonic elapsed time and authoritative recording time remain distinct. Time zones, date-only schedules, daylight-saving changes and clock skew are explicit. Lease and timeout safety should use monotonic elapsed time where available.

## Execution ownership and concurrency

Every executable operation has exact identity, state preconditions, Profile version, attempt history and bounded ownership.

- Concurrent workers may execute at-least-once delivery, but only one valid transition for one state version may commit.
- A worker renews ownership only while it is alive and making permitted progress.
- Long external calls cannot extend ownership indefinitely without heartbeats and upper bounds.
- Lease loss prevents later commit until ownership and external-effect ambiguity are reconciled.
- Duplicate webhooks, queue deliveries and scheduler invocations retain occurrences while suppressing duplicate semantic effects.
- A worker cannot take ownership of arbitrary URLs, sources, providers or purposes outside accepted configuration.

Exact lease or fencing technology belongs to Topic 12.

## Health and coverage posture

### Health dimensions

Health remains multidimensional rather than one mutable `ok` flag:

1. **Authority and configuration:** accepted version, rights, credentials and policy are valid.
2. **Schedule:** due work is being created and started within its allowed window.
3. **Transport:** DNS, TLS, connection, response and rate behaviour satisfy contract.
4. **Parser and shape:** expected content type, structure and extraction invariants hold.
5. **Observation freshness:** a qualifying complete success occurred within the Profile's maximum age.
6. **Semantic integrity:** identity, revision, transition and deduplication controls are behaving correctly.
7. **Downstream availability:** gates, queues, retrieval, workers and handoff can process admitted work.
8. **Budget and capacity:** request, cost, storage and processing limits are not exhausted.

A source may be transport-healthy but parser-broken, or parser-healthy but stale because the scheduler stopped. These states remain distinguishable.

### Healthy unchanged versus stale

A source is operationally quiet only when its latest required check completed successfully and established unchanged under the accepted observation model.

The following cannot be reported as healthy unchanged:

- no recent Check Attempt;
- timeout, TLS, authentication or rate failure;
- malformed, truncated or partial response;
- parser contract failure;
- unknown snapshot completeness;
- missing required page or cursor;
- rights, configuration or budget block; or
- expired freshness objective.

`last_successful_observation_at`, `last_complete_observation_at` and `last_source_change_at` remain separate.

### Portfolio coverage posture

Coverage health is derived from accepted roles and path dependencies:

- a healthy Anchor may satisfy its operational path even when a Comparator is failing;
- a failed Anchor may leave a class degraded when a valid Complement remains, but the exact missing capability stays visible;
- an Explicit contingency contributes only while an approved activation is in effect;
- a Comparator or search result cannot repair the operational status of a missing Anchor; and
- an Active obligation with no credible healthy path becomes operationally uncovered and triggers its pre-approved containment policy.

A source outage does not automatically invalidate already discovered Leads or evidence work. It changes coverage posture and may require scoped hold, pause or warning according to the Operational Profile and autonomy controls.

## Transport and response safeguards

Executable source access follows the exact approved method and destination.

### HTTP and network behaviour

Profiles define:

- strict TLS verification and approved certificate handling;
- allowed schemes, hosts, ports and redirect limits;
- DNS and egress controls that prevent server-side request forgery and private-network access;
- connection, read, total and idle timeouts;
- maximum response and decompressed sizes;
- accepted content types and encodings;
- conditional headers, cache validators and cache-control handling;
- User-Agent and contact information where appropriate;
- per-host concurrency and rate budgets; and
- response handling by status and source contract.

TLS verification, authentication, robots or technical access controls are never disabled to gain coverage.

### Conditional requests and status meaning

A valid `304 Not Modified` may establish unchanged only when a valid prior baseline and exact validator contract exist. A `2xx` empty body may be valid, partial or malformed according to the adapter contract. `404` remains locator ambiguity unless source-specific evidence supports another transition. `410`, explicit tombstones and typed delete events remain subject to the accepted change semantics. `429` and provider back-pressure invoke the accepted rate and retry policy.

Redirect targets are validated against egress and source-identity rules before following. A redirect cannot silently change Source Item identity or permitted rights scope.

### Parser and payload safety

Parsers have resource and shape limits. XML external entities, unexpected network resolution, unsafe deserialisation, decompression bombs and unbounded nested structures are disabled or contained. HTML or browser-based adapters run within an approved isolation and egress boundary.

A response can produce independently valid partial outputs only under the accepted partial-result contract. Parser shape drift creates degraded or quarantined state rather than false publisher change.

### Webhooks, email and event inputs

Webhooks require origin authentication where available, replay protection, bounded payloads, timestamp or sequence checks and durable receipt before acknowledgement.

Email and other delivered channels retain message identity, delivery attempts and attachment or link safety. A delivered message receives no evidence or workflow bypass.

## Retry, circuit breaker and quarantine

### Retry classification

Profiles distinguish outcomes that may be retried automatically from those requiring configuration, rights, parser or operator action.

Retryable examples may include bounded transient network failure, selected `5xx`, rate limit after an allowed delay, short dependency outage and ambiguous downstream acknowledgement.

Non-retryable or immediately blocking examples include prohibited rights state, invalid source configuration, unsafe redirect, persistent authentication authority failure, payload exceeding approved safety bounds and parser behaviour that may fabricate transitions.

### Backoff and budgets

Automatic retry uses bounded exponential or source-appropriate backoff with jitter and respects valid `Retry-After` or provider reset signals. Limits cover attempts, total elapsed horizon, concurrent retries, host load, monetary cost and downstream amplification.

Retries do not reset freshness or coverage-loss clocks. Exhaustion creates a visible Finding and health change. A Routine retry budget cannot consume a separately reserved Urgent capacity pool.

### Circuit breaker

Repeated or integrity-significant failure may open a circuit for the exact source, provider, adapter or dependency scope. While open, new automatic attempts are suppressed or reduced according to policy, and required coverage remains visibly stale or unavailable.

A probe or half-open attempt is bounded and does not automatically restore production authority.

### Quarantine

Quarantine is required where continued automatic processing could produce false transitions, duplicate work, unsafe access or authority violations. Triggers may include:

- parser or source-shape drift beyond contract;
- identity collision or unstable revision rule;
- false clearance, deletion or publisher activity;
- repeated malformed or unsafe payload;
- rights or terms conflict;
- unauthorised redirect or network destination;
- duplicate semantic emission;
- uncontrolled volume or amplification; or
- failed canary or integrity check.

Quarantine is scoped narrowly where isolation is safe. It preserves baselines, attempts, Findings, pending work and coverage consequences.

Release from quarantine requires an authorised decision, repaired version, applicable fixtures and a bounded live or replay canary. One successful request alone does not clear quarantine.

### Contingency

A contingency is named in advance with its source role, coverage difference, budget, activation criteria and maximum duration. Activation and deactivation are recorded. Silent broadening to media, search or a weaker source is prohibited.

## Queueing, capacity and backpressure

### Queue semantics

Queued work retains exact identity, urgency, deadline context, state version and attempt history. Capacity exhaustion, provider unavailability or worker failure cannot silently drop it.

Potentially Urgent work has reserved or isolated capacity and does not wait behind unbounded Routine backlog. Time-sensitive and Planned work preserves relevant windows. Routine work receives fairness and starvation control.

### Backpressure

When downstream capacity is constrained, the system may slow due-work admission, reduce non-essential Comparator execution or pause newly optional work under an accepted policy. It must not:

- skip a required Anchor silently;
- discard a Lead because a model batch is full;
- convert backlog into editorial rejection;
- borrow budget without authority; or
- create larger unbounded batches to hide capacity shortage.

### Stale work

Queued work is revalidated against current coverage, rights, source, Candidate, policy and component versions before commit. Expired, superseded or redundant work closes through an explicit decision and retains lineage.

A deadline or Watch Condition passing while work waits creates a visible operational outcome. It is not silently processed as though timely.

### Capacity model

Operational admission records expected and stress volumes, host limits, worker throughput, queue headroom, storage growth, reviewer or operator burden and Urgent reserve. Capacity evidence includes no-change-heavy and failure-heavy conditions, not only average successful traffic.

## Durable state and dependency behaviour

### Authoritative recording before effects

When safe idempotency and audit depend on durable state, the system confirms the authoritative record can accept the Attempt before making the external call. Incoming webhooks or delivered messages are durably received before successful acknowledgement where the sender can retry.

A state transition and its required downstream work are committed atomically or through a design with deterministic reconciliation. An accepted transition cannot exist permanently without its work item, and an external submission cannot be blindly repeated after an ambiguous result.

### Storage and audit failure

Authoritative-store, audit-write, disk-full or corruption signals fail closed for affected transitions. The system does not continue fetching or committing editorial effects that cannot be recorded safely. Read-only degraded operation is permitted only where an accepted policy proves no authority or replay risk.

### Dependency isolation

Scheduler, network, DNS, credential, parser, state store, retrieval, model, Search provider and Evidence Intake health remain separate. One dependency failure blocks only the affected scope when isolation is safe.

- model or worker outage creates retry, approved fallback or Operational hold, not rejection;
- advisory retrieval outage is not `no match` and follows the guarded Urgent rule;
- exact collision-check outage blocks Candidate admission;
- Search provider failure receives no silent provider switch;
- Evidence Intake ambiguity leaves the same Handoff pending; and
- scheduler failure creates stale or missed work rather than healthy silence.

### Credential and rights lifecycle

Credential expiry, rotation, revoked access, provider terms change and rights-review expiry have visible lead time and blocking behaviour. Secrets are least-privileged, never logged and rotated without silently changing Source Definition or provider authority.

## Reconciliation, replay and recovery

### Reconciliation

A deterministic reconciler detects and handles:

- expired or orphaned leases;
- Attempts without terminal outcomes;
- committed transitions without required downstream work;
- ambiguous source, model, provider or Handoff calls;
- duplicate queue or webhook delivery;
- stale Work Items and pending Handoffs;
- mismatched current projections;
- source state left active across reset or restore; and
- operational Findings lacking closure or escalation.

Reconciliation does not use a model to guess operational truth.

### Replay

Replay preserves exact input, component and policy versions where rights allow. Reprocessing under a new version creates new Representations, proposals or decisions and does not rewrite historical output.

A replay that could create external effects runs in an isolated authority scope. Duplicate semantic effects remain suppressed.

### Catch-up after outage

Recovery plans define which work is coalesced, backfilled, rechecked, expired or prioritised after downtime. Urgent current state and Planned windows are assessed before Routine history. Catch-up respects source and host limits and cannot create a request, Signal or model-call storm.

### Backup and restore

Before production admission, the authoritative discovery state required for identity, baselines, deduplication, pending work and audit has tested backup, integrity verification, restore and rebuild procedures. Operational Profiles define recovery-point and recovery-time objectives by scope.

A restored system reconciles source baselines, leases, queues, pending Handoffs and coverage posture before automatic operation resumes. Restore testing uses isolated data and produces retained evidence.

## Monitoring, alerts and incidents

### Required operational metrics

Metrics are attributable to exact source, adapter, parser, profile, provider, worker and policy versions. At minimum they include:

- due, started, completed, delayed, missed and coalesced operations;
- complete unchanged, changed, partial, malformed, blocked and failed outcomes;
- last successful and last complete observation age;
- last source change age as a separate measure;
- duration, response status, bytes, validators and item counts;
- parse drops, schema drift, identity collisions and transition counts;
- retries, backoff, rate limits, circuit and quarantine state;
- Signal, Lead, Work Item, Candidate and model-wakeup counts;
- queue depth, oldest age, deadline risk and starvation;
- exact and advisory retrieval availability;
- Search Purpose requests, costs and budget state;
- pending and ambiguous Evidence Handoffs;
- coverage availability by obligation and role;
- storage, audit, backup and reconciliation health; and
- cost and capacity utilisation.

Structured logs carry correlation identities from Schedule Occurrence through Check, Signal, Lead, Work Item, Candidate and Handoff while excluding secrets and prohibited source content.

### Alert design

Alerts are based on coverage consequence, integrity and urgency, not raw error volume. Owner-approved conditions include:

- an Urgent or sole Active Anchor exceeding its success-age objective;
- an Active class becoming operationally uncovered;
- failure, partial response or budget block reported as healthy silence;
- parser drift or fabricated source transition risk;
- duplicate semantic transition or identity collision;
- queue age threatening an Urgent, Time-sensitive or Planned window;
- authoritative store, audit or reconciliation failure;
- rights, terms or credential expiry affecting an active path;
- uncontrolled amplification, cost or host load;
- failed quarantine containment; and
- public-effect or authority-boundary attempt.

Repeated related failures are grouped without hiding individual occurrences. Alert suppression cannot suppress the underlying health state or coverage consequence.

### Ownership and runbooks

Every production-eligible source, dependency and alert class has an accountable owner, escalation route and versioned runbook. Runbooks cover diagnosis, safe retry, quarantine, contingency, catch-up, rollback, restore, evidence preservation and closure.

### Incident lifecycle

An incident records detection, affected obligations and versions, impact window, containment, communications, recovery, validation, root cause and follow-up. Confirmed integrity errors and material near misses create regression Cases and may trigger source, Profile, adapter or specification change.

Closure does not erase Findings, alerts or failed Attempts. Re-entry follows a fresh operational and, where material, evaluation decision.

## Security and trust boundaries

Production source access uses least-privileged credentials and an approved egress boundary. Runtime workers cannot add sources, providers, hosts, redirects, query purposes or budgets.

Untrusted source, email, webhook, search and model content remains data. It cannot alter instructions, tools, credentials, budgets, network destinations, Profile versions or authority.

Operational controls include:

- SSRF-resistant URL and redirect validation;
- private-network and metadata-service egress protection;
- strict TLS and hostname verification;
- authenticated webhook and replay protection;
- bounded payload, archive and decompression handling;
- safe XML, HTML, JSON and document parsing;
- browser isolation where a browser is explicitly approved;
- secret redaction and credential rotation;
- dependency and image provenance where applicable; and
- audit of manual retry, quarantine release, contingency and override actions.

A security or authority-boundary failure is a containment and requalification event, not an ordinary source error.

## Rollout, rollback and operational admission

### Version progression

A new source, adapter, parser, Profile, worker, retrieval or Search provider version progresses through applicable research, fixture, replay, shadow evaluation, operational qualification, canary and production decisions. A new version does not inherit authority from its predecessor.

### Canary

Canary scope is explicit by source, coverage role, traffic, queue or operation. Where safe, old and new versions may run side by side in evaluation authority to compare state and outcomes. Canary must not duplicate production effects.

### Rollback

Every admitted version has a tested rollback target or scoped disable path. Rollback preserves attempts, state and incident history. Baseline or cursor compatibility is defined so rollback does not re-emit history, lose current active state or create duplicate transitions.

### Containment

Emergency containment may pause one source, adapter, provider, worker, queue or coverage scope while leaving unrelated healthy work running. Broader pause is required when authority, state integrity or shared dependency isolation is uncertain.

Containment never deletes evidence or Findings and never weakens another gate.

### Operational qualification

A scope is eligible for an Operational Admission Decision only when:

- Topic 8 release evidence marks the exact versions eligible for scoped operational qualification;
- accepted rights, credentials and network access are ready;
- exact Operational Profiles and numerical objectives are approved;
- source, dependency, queue and capacity health controls exist;
- alert ownership and runbooks exist;
- quarantine, contingency and rollback paths are tested;
- backup, restore and reconciliation evidence exists;
- known Active gaps and containment policy are explicit; and
- canary and activation scope are defined.

Operational admission and production activation are separate decisions. Acceptance of this specification provides neither.

## Requirements

### Profiles, schedules and execution

**DOPS-001 — Versioned Operational Profile.** Every executable source, provider, worker, queue and handoff scope MUST reference one exact owner-approved Operational Profile.

**DOPS-002 — Exact objectives before execution.** Source-specific timing, freshness, retry, capacity and alert values MUST be approved before executable shadow or production use. This specification defines required fields, not global numbers.

**DOPS-003 — One logical due operation.** Duplicate scheduler ticks, deliveries or process restarts MUST NOT create duplicate logical Check Requests or semantic work.

**DOPS-004 — No-model scheduling.** Due-work determination, preflight and no-work completion MUST occur without a model.

**DOPS-005 — Jitter and host coordination.** Clocked work MUST use permitted jitter, host concurrency and rate controls without violating accepted Urgent or Planned windows.

**DOPS-006 — Missed-schedule visibility.** Delayed, missed and coalesced work MUST remain visible and follow source-specific catch-up policy.

**DOPS-007 — Time separation.** Source, planned, wall-clock, monotonic and authoritative record times MUST remain distinguishable.

**DOPS-008 — Bounded ownership.** Execution ownership MUST be bounded, renewable only with valid progress and protected against competing commits.

### Health and coverage

**DOPS-010 — Multidimensional health.** Authority, schedule, transport, parser, freshness, semantic integrity, downstream and budget health MUST remain distinguishable.

**DOPS-011 — Successful silence only.** Healthy unchanged status requires a successful qualifying check under the exact observation model.

**DOPS-012 — Freshness is last success.** Last successful and complete observation MUST remain separate from last source change.

**DOPS-013 — Stale is not quiet.** Missing, failed, partial, malformed, blocked or over-age observation MUST NOT be represented as healthy silence.

**DOPS-014 — Coverage posture.** Operational health MUST derive availability by accepted obligation, role and path dependency rather than source count.

**DOPS-015 — Active-path containment.** Loss of all credible healthy paths for an Active obligation MUST create a scoped coverage-blocked state and invoke its approved containment policy.

**DOPS-016 — Comparator non-substitution.** Comparator or search availability MUST NOT repair the health state of a failed Anchor.

### Transport, parsing and input security

**DOPS-020 — Strict access contract.** Source access MUST enforce approved scheme, host, redirect, TLS, credential, timeout, body, content-type and egress limits.

**DOPS-021 — Conditional request correctness.** Validators and `304` MAY establish unchanged only with valid baseline and source-specific contract.

**DOPS-022 — Status-code honesty.** Empty `2xx`, `404`, `410`, `429`, redirect and failure outcomes MUST retain their source-specific meanings and MUST NOT be collapsed into no news or deletion.

**DOPS-023 — Parser resource safety.** Parsers MUST block unsafe external entity resolution, unbounded decompression, unsafe deserialisation and uncontrolled resource use.

**DOPS-024 — Shape drift containment.** Parser or source-shape drift MUST create degraded or quarantined state rather than publisher change.

**DOPS-025 — Authenticated event inputs.** Webhooks and delivered channels MUST support authentication or provenance, replay control, bounded payload and durable receipt as applicable.

**DOPS-026 — Untrusted input boundary.** Source and model content MUST NOT change operational policy, tools, egress, budgets or authority.

### Retry, circuit and quarantine

**DOPS-030 — Retry classification.** Each Profile MUST distinguish retryable, non-retryable and operator-required outcomes.

**DOPS-031 — Bounded backoff.** Retry MUST have attempt, elapsed, concurrency, cost and amplification limits, use jitter and respect valid provider back-pressure.

**DOPS-032 — Retry does not refresh health.** A scheduled retry or backoff MUST NOT reset successful-observation or coverage-loss clocks.

**DOPS-033 — Exhaustion remains visible.** Retry exhaustion MUST create a durable Finding and health change, not no news.

**DOPS-034 — Circuit isolation.** Circuit breaking MUST apply to the narrowest safe source, provider, adapter or dependency scope.

**DOPS-035 — Quarantine triggers.** Integrity, rights, unsafe access, false transition, identity and amplification failures MUST support quarantine.

**DOPS-036 — No automatic unquarantine.** Quarantine release requires authorised repair, applicable tests and bounded canary evidence.

**DOPS-037 — Explicit contingency.** Contingency activation and deactivation MUST be explicit, bounded and role-aware; silent fallback is prohibited.

### Queues, capacity and dependencies

**DOPS-040 — No silent queue loss.** Capacity, provider or worker failure MUST retain or explicitly close work and MUST NOT create editorial rejection.

**DOPS-041 — Urgent capacity.** Potentially Urgent work MUST have isolated or reserved capacity and cannot be starved by Routine work.

**DOPS-042 — Deadline and fairness controls.** Time-sensitive, Planned and Routine queues MUST retain deadline, starvation and fairness state.

**DOPS-043 — Backpressure authority.** Optional work MAY be reduced under accepted policy, but required Anchors, Leads and deadlines MUST NOT be skipped silently.

**DOPS-044 — Stale-work revalidation.** Queued work MUST be revalidated against current authority, versions, Candidate state and deadlines before commit.

**DOPS-045 — Capacity evidence.** Operational admission MUST include average, peak, no-change-heavy and failure-heavy capacity evidence.

**DOPS-046 — Durable transition delivery.** A committed transition and its required downstream work MUST be atomic or deterministically reconcilable.

**DOPS-047 — Store failure is fail-closed.** Authoritative state or audit unavailability MUST block affected external and semantic effects where safe recording cannot be guaranteed.

**DOPS-048 — Dependency-specific failure.** Scheduler, network, parser, store, retrieval, model, search and Evidence Intake failure MUST remain separate and scoped.

### Reconciliation and recovery

**DOPS-050 — Deterministic reconciliation.** Reconciliation MUST detect orphaned ownership, missing outcomes, ambiguous calls, duplicate delivery, stale work, pending Handoffs and projection mismatch without model guesswork.

**DOPS-051 — Ambiguous effect guard.** An external call that may have succeeded MUST be reconciled or retried idempotently rather than repeated blindly.

**DOPS-052 — Versioned replay.** Replay MUST retain exact versions and create later outputs rather than rewrite history.

**DOPS-053 — Bounded catch-up.** Recovery after downtime MUST prioritise current Urgent and Planned state, respect host limits and prevent historical storms.

**DOPS-054 — Backup and restore evidence.** Required discovery authority, baseline, dedupe, pending-work and audit state MUST have tested backup, restore, integrity and rebuild procedures before production admission.

**DOPS-055 — Restore reconciliation.** Automatic operation MUST NOT resume after restore until baselines, leases, queues, Handoffs and coverage posture are reconciled.

### Monitoring, incidents and security

**DOPS-060 — Version-attributed observability.** Metrics, logs, alerts and incidents MUST identify exact source, component, Profile, provider and policy versions.

**DOPS-061 — Health metrics.** Monitoring MUST include schedule, complete success age, outcome, parser, retry, queue, budget, coverage, storage and reconciliation metrics.

**DOPS-062 — Correlated path.** Structured records MUST support tracing from due trigger through Check, transition, Lead, Work Item, Candidate and Handoff without logging prohibited data.

**DOPS-063 — Consequence-based alerts.** Alert priority MUST reflect coverage, integrity and urgency rather than raw error count.

**DOPS-064 — Owner and runbook.** Every production-eligible scope and alert class MUST have accountable ownership, escalation and a versioned runbook.

**DOPS-065 — Incident record.** Material operational or integrity failure MUST create a retained incident with scope, timeline, containment, recovery, root cause and follow-up.

**DOPS-066 — Regression learning.** Confirmed integrity errors and material near misses SHOULD create evaluation regression Cases.

**DOPS-067 — Least privilege and egress.** Credentials, source access and network destinations MUST be least-privileged and restricted to approved scope.

**DOPS-068 — Authenticated manual action.** Retry, requeue, quarantine release, contingency and override actions MUST be authenticated and audited.

### Rollout and admission

**DOPS-070 — No inherited authority.** New source, adapter, parser, Profile, worker, retrieval or provider version MUST NOT inherit operational authority automatically.

**DOPS-071 — Scoped canary.** Material operational changes MUST support bounded canary or equivalent qualification where technically appropriate.

**DOPS-072 — Tested rollback.** Admitted versions MUST have a tested rollback or scoped-disable path with baseline and cursor compatibility.

**DOPS-073 — Scoped containment.** The system MUST pause the narrowest safe affected scope and broaden containment when shared authority or integrity is uncertain.

**DOPS-074 — Terms and credential change.** Material rights, terms, pricing, access or credential changes MUST trigger affected-scope review and blocking where authority is no longer current.

**DOPS-075 — Operational admission evidence.** Production eligibility MUST bind Topic 8 evidence, exact Profiles, objectives, alerts, runbooks, capacity, recovery, contingency, canary and rollback.

**DOPS-076 — Admission is not activation.** Accepting this specification or issuing an Operational Admission Decision MUST NOT itself start production.

## Acceptance criteria

1. A successful complete unchanged check and a source that has not been checked for two hours cannot share the same health meaning.
2. `last_changed_at` cannot be used as the freshness clock for a source that legitimately changes rarely.
3. An invalid RSS configuration fails closed rather than activating broad defaults.
4. Malformed XML creates parser failure and cannot be reported as a successful empty feed.
5. A valid conditional `304` creates unchanged only when the prior baseline and validator contract are known.
6. One `404`, TLS failure or timeout cannot become deletion or no news.
7. Duplicate scheduler ticks and webhook deliveries create at most one logical operation and semantic transition.
8. Scheduler downtime creates visible stale or missed work and a bounded catch-up plan rather than historical flooding.
9. Retries respect `Retry-After`, use bounded jitter and do not refresh source health.
10. A parser version producing false warning clearance is quarantined and cannot restore itself after one success.
11. A contingency search may find a Lead but cannot restore a failed Anchor's coverage posture.
12. A sole Urgent Anchor exceeding its success-age objective creates scoped coverage containment.
13. Routine backlog cannot consume reserved Urgent capacity or silently drop Leads.
14. Advisory retrieval outage is not `no match`, and exact collision-check outage blocks Candidate admission.
15. State-store or audit failure prevents effects that cannot be recorded safely.
16. An ambiguous Handoff or provider call is reconciled before repeat execution.
17. Restore testing proves that baselines, pending work, active states and coverage posture are reconciled before resume.
18. Metrics distinguish last successful complete observation from last source change.
19. Alert severity reflects affected coverage and integrity rather than the number of repeated errors.
20. Source text cannot alter egress, tools, credentials, budgets or quarantine policy.
21. A new parser or Profile version receives no production authority merely because the earlier version was healthy.
22. Rollback does not re-emit historical Signals or lose an active warning state.
23. Operational admission identifies exact sources, versions, objectives, alerts, runbooks, recovery and known blockers.
24. Acceptance of Topic 9 authorises no scheduler, source, provider, credential, run or production activation.

## Owner decisions required to complete Topic 9

The Draft recommends these decisions:

1. Accept a versioned Operational Profile for every executable source, provider, worker, queue and handoff scope, with exact numerical objectives approved separately rather than one global cadence or SLO.
2. Accept due-work, jitter, missed-schedule, catch-up and one-logical-operation semantics that prevent duplicate checks and historical storms while preserving Urgent and Planned windows.
3. Accept bounded execution ownership, heartbeats and reconciliation so at-least-once delivery produces at-most-once semantic transitions and ambiguous external effects are not repeated blindly.
4. Accept multidimensional health across authority, schedule, transport, parser, observation freshness, semantic integrity, downstream capacity and budget.
5. Accept that healthy unchanged requires a successful qualifying check, that stale is not quiet and that last successful observation remains separate from last source change.
6. Accept portfolio-level Coverage Availability Assessments in which loss of every credible healthy path for an Active obligation triggers scoped coverage containment and cannot be repaired by a Comparator.
7. Accept strict transport, egress, redirect, TLS, timeout, body, content-type, conditional-request and parser-resource controls, including authenticated and replay-resistant delivered inputs.
8. Accept bounded retry with source-specific classification, exponential or appropriate backoff, jitter, `Retry-After`, hard retry and amplification budgets, and no health refresh from retries.
9. Accept source-, adapter- and dependency-scoped circuit breaking and quarantine, with no automatic unquarantine and explicit tested release.
10. Accept pre-approved, role-aware Contingency Activation and prohibit silent fallback or source-role transfer.
11. Accept queue and backpressure rules that preserve every Lead or explicit closure, reserve Urgent capacity, retain deadlines and fairness, and revalidate stale work before commit.
12. Accept durable or deterministically reconcilable transition-to-downstream delivery, fail-closed authoritative-store and audit behaviour, and dependency-specific failure semantics.
13. Accept deterministic reconciliation, idempotent replay, bounded outage catch-up and tested backup, restore, integrity and rebuild evidence before production admission.
14. Accept version-attributed metrics and correlated logs covering schedules, successful observation age, outcomes, parser health, retries, queues, budgets, coverage posture, storage and reconciliation.
15. Accept consequence-based alerts, accountable owners, versioned runbooks and retained incidents with containment, recovery, root cause and regression follow-up.
16. Accept least-privileged credentials, restricted egress, SSRF resistance, safe parsing, webhook authentication, secret protection and audited manual actions.
17. Accept version-specific progression through evaluation, operational qualification, canary and activation, with no inherited authority, tested rollback and scoped containment.
18. Accept that exact operational numbers are not guessed in this Topic: they are evidence-based Profile values and are `Needs experiment` until an owner-approved qualification and admission package sets them.
19. Accept that an Operational Admission Decision binds exact Topic 8 evidence, Profiles, objectives, capacity, alerts, runbooks, recovery, contingencies and rollback, but remains separate from production activation.
20. Accept that Topic 9 itself authorises no schedule, source, provider, credential, process, spending, shadow run or production activation.
