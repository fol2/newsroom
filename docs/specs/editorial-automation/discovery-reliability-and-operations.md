# Discovery reliability and operations specification

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
**Accepted search contract:** [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md)  
**Accepted evaluation contract:** [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Implementation authority:** None. Acceptance defines operational semantics and admission evidence; it authorises no source, schedule, provider, credential, spending, shadow run, process or production activation.  
**Supersedes:** None

## Purpose

Define the operational conditions under which discovery may run reliably without confusing silence with failure, retries with new work, source absence with publisher action, or individual-source health with portfolio coverage.

The contract is implementation-neutral. It defines what must be configured, measured, alerted, contained, reconciled and proven before an exact discovery scope may become production-eligible.

## Scope

This specification defines:

- versioned Operational Profiles and scoped admission decisions;
- cadence classes, due-work identity, jitter, missed schedules and catch-up;
- execution ownership, heartbeats, concurrency and idempotency;
- multidimensional source, dependency and coverage health;
- transport, response and parser safeguards;
- retry, backoff, circuit-breaker and quarantine behaviour;
- queueing, backpressure, fairness, expiry and capacity controls;
- durable transition delivery and deterministic reconciliation;
- metrics, logs, alerts, runbooks and incidents;
- least-privilege, egress and untrusted-input controls;
- backup, restore, replay and disaster-recovery evidence; and
- canary, rollback, containment and operational admission.

It does not select a scheduler, agent framework, queue, database, observability service, deployment platform or on-call vendor. It does not set one global polling interval or numerical service objective. Exact values are evidence-based, source- and scope-specific Operational Profile values approved separately.

Topic 12 maps these requirements to implementation and migration. Operational admission and production activation remain separate owner decisions.

## Current-system replacement boundary

The legacy system contains useful implementation experience but does not satisfy this contract:

- `newsroom/rss_news.py` silently falls back to broad built-in feeds when configuration is missing, empty or invalid;
- malformed RSS or Atom XML becomes an empty article list and may then be recorded as a successful fetch;
- RSS collection has no source-specific validator, watermark, health or revision contract;
- the current fixed inter-request delay is not a source- and host-specific rate, retry and circuit policy;
- `scripts/news_pool_update.py` may advance shared fetch state after one page succeeds while other pages fail; and
- SQLite WAL and connection timeout do not prove leases, atomic downstream delivery, reconciliation, backup, restore or recovery.

These are current-state observations, not implementation instructions.

## Operational principles

1. **Successful silence is proved.** `Unchanged` exists only after a complete successful check under the exact source contract.
2. **Freshness is not last change.** A source may be healthy for a long period without publishing anything new.
3. **Coverage consequence drives priority.** Failure of a sole Urgent Anchor matters more than many redundant Comparator errors.
4. **Profiles are source-specific.** Cadence, timeout, retry, health and catch-up behaviour are versioned per scope.
5. **At-least-once work has at-most-once semantic effects.** Duplicate delivery and replay do not create duplicate transitions.
6. **Retries are bounded.** Backoff protects the source and the Newsroom without hiding stale coverage.
7. **Quarantine protects integrity.** Unsafe or ambiguous processing stops within the narrowest safe scope.
8. **Fallback is explicit.** A contingency has a named role, activation decision, budget, duration and coverage consequence.
9. **Backpressure is visible.** Capacity shortage never becomes silent loss or editorial rejection.
10. **Dependencies fail honestly.** Scheduler, transport, parser, store, model, retrieval, search and handoff failures remain separate.
11. **Recovery is designed before failure.** Reconciliation, replay, restore and rollback are tested.
12. **Authority is scoped and versioned.** One healthy source or successful evaluation does not authorise the full portfolio.

## Operational records

These are semantic contracts, not required tables or services.

### Operational Profile

An immutable, owner-approved configuration for one exact Source Definition Version, Search Purpose and provider version, worker or retrieval dependency, queue class, Evidence Intake boundary or other executable scope.

Where applicable it records:

- coverage role, portfolio function and urgency class;
- trigger type, cadence, permitted active windows and due-to-start objective;
- maximum age since a successful qualifying observation;
- connection, read, total execution and body-size limits;
- conditional-request and cache-validator behaviour;
- host concurrency, rate, request and cost limits;
- retry classification, count, elapsed horizon, backoff, jitter and `Retry-After` policy;
- first-run, catch-up, reset and missed-schedule policy;
- complete, partial and malformed-response contracts;
- queue, batch, deadline, fairness and starvation controls;
- dependencies and guarded degraded-operation permissions;
- health dimensions, warning and critical conditions;
- circuit-breaker and quarantine criteria;
- contingency paths and limits;
- metrics, alerts, owner and runbook;
- backup, restore, reconciliation and rollback requirements;
- approved credentials, network destinations and security controls;
- evaluation and release-evidence references; and
- known limitations and coverage consequence when unavailable.

A material value change creates a new Profile version. Runtime agents cannot edit it.

### Schedule Occurrence

An immutable record that a versioned trigger became due, fired or was received. It distinguishes scheduled time, scheduler observation time, permitted start window, missed or coalesced state and resulting work.

A scheduler tick is not a due occurrence for every source.

### Execution Lease

A bounded ownership claim for one exact operation and state version. Lease expiry does not prove that a previous worker performed no external effect; ambiguous effects require reconciliation before retry.

### Health Observation and Health Assessment

A Health Observation records one measurable operational fact. A Health Assessment applies a versioned deterministic interpretation. Current health is a rebuildable projection, not the sole history.

### Coverage Availability Assessment

A scoped decision recording whether accepted coverage paths are available, degraded, unavailable or unknown. It identifies obligations, healthy and failed paths, contingencies, time since loss and required containment. It cannot promote a Comparator to Anchor.

### Operational Incident

A stable case for an integrity, availability, latency, capacity, rights, security or authority-boundary problem, linking timeline, scope, containment, recovery, root cause and follow-up.

### Contingency Activation

An immutable decision enabling one pre-approved contingency for an exact failed path, duration, budget and role. The original failure remains visible.

### Operational Admission Decision

An owner decision binding exact evaluated versions, Operational Profiles, known gaps, numerical objectives, alerts, runbooks, capacity evidence, recovery evidence, canary scope and rollback target.

Possible outcomes include not ready, qualification required, canary eligible, production eligible for a bounded scope, Comparator-only, Held, quarantined, retired or blocked by coverage deficiency. Admission does not activate production.

## Scheduling and execution

Operational Profiles use qualitative cadence classes without forcing one interval across all sources:

- **Urgent current-state**;
- **Time-sensitive**;
- **Planned-window**;
- **Routine**; and
- **Event-driven or manual**.

Exact intervals reflect source behaviour, cache policy, rate limits, urgency and evaluation evidence. Polling faster than the source can meaningfully change is not automatically more reliable.

One due occurrence creates at most one logical operation. Duplicate ticks, process restarts and webhook redelivery retain occurrence history while suppressing duplicate semantic effects. Due-work determination, preflight and no-work completion use no model.

Clocked work uses bounded jitter and shared per-host limits where this does not violate an Urgent or Planned window.

Missed schedules remain visible. Catch-up is source-specific:

- maintained pages normally require a current-state check, not one call per missed interval;
- append-only feeds use a bounded backfill or watermark window;
- current-state warnings require immediate current observation while preserving uncertainty about the missed interval;
- Planned paths retain their expected window and confirmation semantics; and
- high-volume history may be coalesced only through an explicit rule preserving the coverage consequence.

Source-asserted, planned, scheduler wall-clock, monotonic elapsed and authoritative recording times remain distinct.

Every operation has exact identity, state preconditions, Profile version, attempt history and bounded ownership. Concurrent execution may be at least once, but only one valid transition for one state version may commit. Lease loss blocks commit until ownership and external-effect ambiguity are reconciled.

## Health and coverage posture

Health remains multidimensional:

1. authority and configuration;
2. schedule;
3. transport;
4. parser and response shape;
5. observation freshness;
6. semantic integrity;
7. downstream availability; and
8. budget and capacity.

A source is operationally quiet only when its latest required check completed successfully and established unchanged. No recent attempt, timeout, TLS or authentication failure, rate limit, malformed or partial response, parser break, unknown completeness, missing cursor, rights block, budget block or expired success-age objective cannot be reported as healthy unchanged.

`last_successful_observation_at`, `last_complete_observation_at` and `last_source_change_at` remain separate.

Coverage posture derives from accepted roles and dependencies:

- a healthy Anchor may satisfy its path while a Comparator fails;
- a failed Anchor may leave a class degraded if a valid Complement remains, with the missing capability explicit;
- a contingency contributes only during an approved activation;
- search and Comparators cannot repair a failed Anchor's health; and
- an Active obligation with no credible healthy path becomes operationally uncovered and invokes its approved containment policy.

A source outage does not automatically invalidate already discovered Leads or evidence work. It changes future coverage posture.

## Transport, parsing and delivered inputs

Executable access enforces the exact approved method and destination, including:

- strict TLS and hostname verification;
- allowed scheme, host, port and redirect limits;
- DNS and egress controls against SSRF and private-network access;
- connection, read, idle and total timeouts;
- compressed and decompressed size limits;
- permitted content types and encodings;
- conditional validators and cache handling;
- User-Agent and contact information where appropriate; and
- per-host concurrency and rate limits.

TLS, authentication, robots or technical controls are never disabled to gain coverage.

A valid `304` may establish unchanged only with a valid baseline and exact validator contract. Empty `2xx`, `404`, `410`, `429`, redirect and failure outcomes retain source-specific meaning. A redirect cannot silently change Source Item identity or rights scope.

Parsers enforce shape and resource limits. External XML entities, unexpected network resolution, unsafe deserialisation, decompression bombs and unbounded nesting are disabled or contained. Browser-based adapters use an approved isolation and egress boundary.

Partial outputs are accepted only under the source's partial-result contract. Shape drift becomes degraded or quarantined state, not publisher change.

Webhooks and delivered channels use origin authentication where available, replay control, bounded payloads, sequence or timestamp checks and durable receipt before acknowledgement. Email and delivered content receive no workflow or evidence bypass.

## Retry, circuit breaker and quarantine

Profiles distinguish retryable, non-retryable and operator-required outcomes.

Automatic retry uses bounded source-appropriate backoff with jitter and respects valid `Retry-After` or reset information. Limits include attempts, elapsed horizon, concurrent retries, host load, monetary cost and downstream amplification.

Retries do not reset freshness or coverage-loss clocks. Exhaustion creates a visible Finding and health change.

Circuit breaking applies to the narrowest safe source, provider, adapter or dependency scope. Half-open probes are bounded and do not restore authority automatically.

Quarantine is required where continued automation could create false transitions, duplicate work, unsafe access or authority violations, including parser drift, identity collision, unstable revision rules, false clearance or deletion, rights conflict, unsafe redirect, duplicate semantic emission, uncontrolled amplification or failed canary.

Quarantine preserves baselines, attempts, Findings, pending work and coverage consequences. Release requires an authorised repaired version, applicable tests and bounded replay or live-canary evidence. One successful request is insufficient.

A contingency is named and approved in advance with role, coverage difference, budget, activation criteria and duration. Silent broadening to media, search or a weaker role is prohibited.

## Queueing, capacity and durable delivery

Queued work retains identity, urgency, deadline, state version and attempt history. Capacity or dependency failure cannot silently drop it.

Potentially Urgent work has isolated or reserved capacity. Time-sensitive and Planned work retain windows. Routine work has fairness and starvation controls.

Backpressure may reduce optional Comparator or newly optional work under accepted policy, but cannot silently skip a required Anchor, discard a Lead, convert backlog into editorial rejection, borrow budget or create unbounded batches.

Queued work is revalidated against current coverage, rights, source, Candidate, policy and component versions before commit. Expired, superseded or redundant work closes through an explicit decision with lineage.

Operational admission includes expected and stress volumes, host limits, worker throughput, queue headroom, storage growth, operator burden and Urgent reserve. Evidence covers no-change-heavy and failure-heavy conditions.

Where idempotency and audit depend on durable state, the system establishes that the authoritative record can accept an Attempt before performing the external effect. A transition and its required downstream work are atomic or deterministically reconcilable.

Authoritative-store, audit-write, disk-full and corruption conditions fail closed for affected effects. Dependency failures remain separate and scoped:

- worker outage creates retry, approved fallback or Operational hold, not rejection;
- advisory retrieval outage is not `no match`;
- exact collision-check outage blocks Candidate admission;
- Search failure receives no silent provider switch;
- Evidence Intake ambiguity leaves the same Handoff pending; and
- scheduler failure creates stale or missed work, not healthy silence.

Credential expiry, rotation, revocation, provider-terms change and rights-review expiry have visible lead time and blocking behaviour. Secrets are least-privileged and never logged.

## Reconciliation, replay and recovery

A deterministic reconciler detects orphaned leases, Attempts without outcomes, transitions without required work, ambiguous calls, duplicate deliveries, stale Work Items, pending Handoffs, projection mismatch, active state across reset or restore, and Findings lacking closure.

Reconciliation does not use a model to guess operational truth.

Replay preserves exact inputs, component and policy versions. Reprocessing under a new version creates later Representations or decisions rather than rewriting history. Replay capable of external effects runs in isolated authority.

Outage catch-up prioritises current Urgent state and Planned windows before Routine history, respects source limits and prevents request, Signal or model-call storms.

Before production admission, identity, baseline, dedupe, active-state, pending-work and audit state have tested backup, integrity verification, restore and rebuild procedures. Automatic operation does not resume after restore until baselines, leases, queues, Handoffs and coverage posture are reconciled.

## Monitoring, alerts, incidents and security

Metrics, logs, alerts and incidents are attributable to exact source, adapter, parser, Profile, provider, worker and policy versions. Monitoring includes:

- due, started, completed, delayed, missed and coalesced operations;
- unchanged, changed, partial, malformed, blocked and failed outcomes;
- last successful and complete observation age;
- last source-change age as a separate measure;
- response, validator, parser and identity behaviour;
- retry, rate-limit, circuit and quarantine state;
- Signal, Lead, Work Item, Candidate and model-wakeup counts;
- queue age, deadlines and starvation;
- exact and advisory retrieval health;
- Search Purpose use, cost and budget;
- pending Handoffs;
- coverage availability; and
- store, audit, backup and reconciliation health.

Correlation records trace due trigger through Check, transition, Lead, Work Item, Candidate and Handoff without logging prohibited data.

Alerts reflect coverage consequence, integrity and urgency rather than raw error count. Every production-eligible scope and alert class has an accountable owner, escalation route and versioned runbook.

Material incidents retain scope, timeline, containment, recovery, validation, root cause and follow-up. Closure does not erase Findings or failed Attempts. Confirmed integrity errors and material near misses feed regression evaluation.

Source, email, webhook, search and model content remains untrusted data. Operational controls include least-privileged credentials, restricted egress, SSRF resistance, strict TLS, authenticated webhooks, replay protection, bounded and safe parsing, browser isolation where approved, secret redaction and audited manual retry, requeue, quarantine release, contingency and override actions.

A security or authority-boundary failure is a containment and requalification event.

## Rollout, rollback and admission

A new source, adapter, parser, Profile, worker, retrieval or provider version progresses through applicable research, fixtures, replay, shadow evaluation, operational qualification, canary and activation. Authority is not inherited.

Canary scope is explicit and cannot duplicate production effects.

Every admitted version has a tested rollback target or scoped-disable path with baseline and cursor compatibility so rollback does not re-emit history, lose current active state or create duplicate transitions.

Containment pauses the narrowest safe scope and broadens when shared authority or integrity is uncertain. It never deletes audit history or weakens another gate.

Operational eligibility requires:

- Topic 8 release evidence for exact versions;
- current rights, credentials and network access;
- approved Operational Profiles and numerical objectives;
- source, dependency, queue and capacity controls;
- alert ownership and runbooks;
- tested quarantine, contingency and rollback;
- backup, restore and reconciliation evidence;
- explicit Active gaps and containment; and
- defined canary and activation scope.

Operational admission and production activation are separate.

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

**DOPS-022 — Status-code honesty.** Empty `2xx`, `404`, `410`, `429`, redirect and failure outcomes MUST retain source-specific meanings and MUST NOT be collapsed into no news or deletion.

**DOPS-023 — Parser resource safety.** Parsers MUST block unsafe external entity resolution, unbounded decompression, unsafe deserialisation and uncontrolled resource use.

**DOPS-024 — Shape drift containment.** Parser or source-shape drift MUST create degraded or quarantined state rather than publisher change.

**DOPS-025 — Authenticated event inputs.** Webhooks and delivered channels MUST support authentication or provenance, replay control, bounded payload and durable receipt as applicable.

**DOPS-026 — Untrusted input boundary.** Source and model content MUST NOT change operational policy, tools, egress, budgets or authority.

### Retry, circuit and quarantine

**DOPS-030 — Retry classification.** Each Profile MUST distinguish retryable, non-retryable and operator-required outcomes.

**DOPS-031 — Bounded backoff.** Retry MUST have attempt, elapsed, concurrency, cost and amplification limits, use jitter and respect valid provider back-pressure.

**DOPS-032 — Retry does not refresh health.** Retry or backoff MUST NOT reset successful-observation or coverage-loss clocks.

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

**DOPS-046 — Durable transition delivery.** A committed transition and required downstream work MUST be atomic or deterministically reconcilable.

**DOPS-047 — Store failure is fail-closed.** Authoritative state or audit unavailability MUST block affected effects where safe recording cannot be guaranteed.

**DOPS-048 — Dependency-specific failure.** Scheduler, network, parser, store, retrieval, model, search and Evidence Intake failures MUST remain separate and scoped.

### Reconciliation and recovery

**DOPS-050 — Deterministic reconciliation.** Reconciliation MUST detect orphaned ownership, missing outcomes, ambiguous calls, duplicate delivery, stale work, pending Handoffs and projection mismatch without model guesswork.

**DOPS-051 — Ambiguous effect guard.** An external call that may have succeeded MUST be reconciled or retried idempotently rather than repeated blindly.

**DOPS-052 — Versioned replay.** Replay MUST retain exact versions and create later outputs rather than rewrite history.

**DOPS-053 — Bounded catch-up.** Recovery after downtime MUST prioritise current Urgent and Planned state, respect host limits and prevent historical storms.

**DOPS-054 — Backup and restore evidence.** Required authority, baseline, dedupe, pending-work and audit state MUST have tested backup, restore, integrity and rebuild procedures before production admission.

**DOPS-055 — Restore reconciliation.** Automatic operation MUST NOT resume after restore until baselines, leases, queues, Handoffs and coverage posture are reconciled.

### Monitoring, incidents and security

**DOPS-060 — Version-attributed observability.** Metrics, logs, alerts and incidents MUST identify exact source, component, Profile, provider and policy versions.

**DOPS-061 — Health metrics.** Monitoring MUST include schedule, complete-success age, outcome, parser, retry, queue, budget, coverage, storage and reconciliation metrics.

**DOPS-062 — Correlated path.** Structured records MUST trace due trigger through Check, transition, Lead, Work Item, Candidate and Handoff without logging prohibited data.

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

**DOPS-076 — Admission is not activation.** Acceptance of this specification or an Operational Admission Decision MUST NOT start production.

## Acceptance criteria

1. Successful complete unchanged and a source not checked within its objective cannot share the same health meaning.
2. `last_changed_at` cannot be the freshness clock for a rarely changing source.
3. Invalid RSS configuration fails closed rather than enabling broad defaults.
4. Malformed XML is parser failure, not a successful empty feed.
5. `304` means unchanged only with a valid baseline and validator contract.
6. `404`, TLS failure or timeout cannot become deletion or no news.
7. Duplicate scheduler or webhook delivery creates one logical operation and semantic transition.
8. Downtime creates visible stale or missed work and bounded catch-up rather than historical flooding.
9. Retry respects back-pressure, uses bounded jitter and does not refresh health.
10. A parser producing false clearance is quarantined and cannot restore itself after one success.
11. Contingency search cannot restore a failed Anchor's coverage posture.
12. Loss of a sole Urgent Anchor triggers scoped coverage containment.
13. Routine backlog cannot consume reserved Urgent capacity or silently drop Leads.
14. Advisory retrieval outage is not `no match`; exact collision-check outage blocks Candidate admission.
15. State-store or audit failure blocks effects that cannot be recorded safely.
16. Ambiguous external effects are reconciled before repeat execution.
17. Restore testing reconciles baselines, pending work, active states and coverage posture before resume.
18. Metrics distinguish last complete success from last source change.
19. Alert severity reflects coverage and integrity consequence rather than repeated error count.
20. Untrusted content cannot alter egress, tools, credentials, budgets or quarantine policy.
21. New versions receive no inherited authority.
22. Rollback does not re-emit history or lose active state.
23. Operational admission identifies exact versions, objectives, alerts, runbooks, recovery and blockers.
24. Acceptance authorises no scheduler, source, provider, credential, run or production activation.

## Completion record

The product owner accepted this specification on 2026-07-15 with these decisions:

- every executable source, provider, worker, queue and handoff scope has a versioned Operational Profile, while exact numbers are approved separately;
- due-work, jitter, missed-schedule, catch-up and one-logical-operation semantics prevent duplicate checks and historical storms while preserving Urgent and Planned windows;
- bounded ownership, heartbeats and reconciliation make at-least-once delivery produce at-most-once semantic transitions and prevent blind repetition of ambiguous effects;
- health is multidimensional across authority, schedule, transport, parser, observation freshness, semantic integrity, downstream capacity and budget;
- healthy unchanged requires a successful qualifying check, stale is not quiet and last successful observation remains separate from last source change;
- portfolio Coverage Availability Assessments trigger scoped containment when every credible path for an Active obligation is lost, and Comparators cannot repair Anchor health;
- strict transport, egress, redirect, TLS, timeout, body, content-type, conditional-request, parser-resource and authenticated-delivery controls apply;
- retry is source-specific, bounded, backoff- and jitter-aware, respects provider back-pressure and does not refresh health;
- circuit breaking and quarantine are scoped, no automatic unquarantine is allowed and release requires repair and tested evidence;
- contingency activation is pre-approved and role-aware, with no silent fallback or source-role transfer;
- queue and backpressure controls preserve or explicitly close work, reserve Urgent capacity, retain deadlines and fairness and revalidate stale work;
- transition-to-downstream delivery is durable or deterministically reconcilable, authoritative-store and audit failure fail closed and dependencies retain separate failure meaning;
- reconciliation, idempotent replay, bounded catch-up and tested backup, restore, integrity and rebuild evidence precede production admission;
- metrics and correlated logs are version-attributed and cover schedule, successful-observation age, parser, retry, queue, budget, coverage, store and reconciliation;
- alerts are consequence-based, ownership and runbooks are explicit and incidents retain containment, recovery, root cause and regression follow-up;
- least privilege, restricted egress, SSRF resistance, safe parsing, webhook authentication, secret protection and audited manual actions are required;
- each version progresses independently through evaluation, operational qualification, canary and activation, with no inherited authority and with tested rollback and scoped containment;
- exact operational values are **Needs experiment** and are set only by an owner-approved qualification and admission package;
- an Operational Admission Decision binds Topic 8 evidence, Profiles, objectives, capacity, alerts, runbooks, recovery, contingencies and rollback but is not production activation; and
- Topic 9 authorises no schedule, source, provider, credential, process, spending, shadow run or production activation.
