# Increment 5 production-retrieval operating contract

This runbook covers implementation and non-production qualification authorized
by 5A. Production activation is outside Increment 5.

## Profiles and validation

`FIXTURE_REPLAY` is hermetic, zero-call, and never qualification evidence.
`PRODUCTION_SHAPED_QUALIFICATION` may use actual Neo4j and a signed,
rights-cleared, repository-safe dataset, but it still has zero provider spend,
no model load, no protected content, no write authority, no public effect, and
no production activation.

Every 5E evidence manifest is canonical JSON validated inside the fresh
exact-head signed process with:

```text
CODE_COMMIT_SHA="$(git rev-parse --verify 'HEAD^{commit}')"
CODE_TREE_SHA="$(git rev-parse --verify 'HEAD^{tree}')"
python -I scripts/sdlc/increment5_profile_validator.py \
  --expected-code-commit-sha "$CODE_COMMIT_SHA" \
  --expected-code-tree-sha "$CODE_TREE_SHA"
```

The validator verifies the supplied Git commit and tree against a clean checkout
before importing repository code. Receipt v2 binds the manifest digest, profile
kind, `code_commit_sha`, `code_tree_sha`, and `repository_clean=true` while
stating `authority_effect=NONE`, `qualification_authority_granted=false`, and
`production_activation_authorized=false`. The receipt tree must equal the
frozen Epoch tree; mismatch is `NOT_EVALUATED`. It is necessary profile
evidence, never sufficient qualification evidence.

## Epoch admission

Every qualification Run binds a canonical Epoch record before execution. The
Epoch digest covers the reviewed contract and evaluation-plan digests; exact
components; source inventory; source/provider, adapter, and parser versions;
query, threshold, and policy sets; dataset manifest; label/adjudication policy;
code tree; and generation.

Any frozen identity difference is material. A component, source, query,
threshold, or policy change starts a new Epoch. A Run with missing or mismatched
Epoch identity is `NOT_EVALUATED`. Cross-Epoch pooling is prohibited, and
superseded Epoch Runs remain retained.

## Closed-world requirement ownership

Increment 5 uses 155 accepted requirements. The machine inventory includes the
exact selected `GRAG-*`, `GRPROD-*`, and `TRI-*` ranges plus every requirement
heading in the accepted `DEVAL-*` and `DOPS-*` specifications.

The exact delivery split is `10 / 0 / 4 / 11 / 122 / 7 / 1` for 5A, 5B, 5C,
5D, 5E, prior Increment 4, and outside activation respectively. 5E is derived as
the closed-world remainder after the six smaller explicit groups are removed.
It is not a manually maintained list.

Tests parse the two accepted specifications and require exact equality with the
43-row `DEVAL-*` and 61-row `DOPS-*` machine inventories.

## Implementation ownership

- **5B / #251:** four independent retriever branches and exact receipts.
  This is partial implementation: it closes no selected whole requirement
  until 5D composes the branches.
- **5C / #252:** six typed bounded read-only tools and tool-local authorization.
- **5D / #253:** exact/source-native, formal-process, and explicit-lineage
  retrieval before approximate similarity; deterministic fusion, authoritative
  dependency-root deduplication, complete six-stage discovery lineage,
  hydration, freshness, an exact request collision receipt, and honest
  request-level no-match or incomplete outcomes. It creates no upstream or
  downstream operational or editorial effect.
- **5E / #254:** the complete closed-world evaluation and operating system:
  universe, labels, review and adjudication; Operational Profiles; scheduling;
  access and parser security; health and coverage; queues and capacity;
  monitoring and incidents; security; rights purge; full reconciliation
  recovery; containment; the complete governed-projection/hybrid-retrieval/
  triage/Candidate-admission vertical slice; downstream decision fallback,
  Candidate non-creation and collision-gated admission, collection/Lead
  isolation and system outage semantics; production/canary/live-shadow
  GraphRAG enforcement; rollback and rebuild; and actual-service
  qualification.

## Decision-bearing system

`HYBRID` is the sole qualification target. Exact-only, full-text-only,
vector-only, and admitted-graph-only are mandatory comparative ablations whose
quality cannot rescue `HYBRID`. A safety or rights violation in any executed
system blocks the affected scope.

## Evaluation universe, labels and review

Before execution, the Epoch binds the exact dataset manifest and
label/adjudication policy. 5E must prove:

- event-level deduplication rather than URL counting;
- no provider, source, index, legacy pipeline, feed, search system, or model as
  complete ground truth;
- prospective methods fixed before review, with retrospective additions
  separately labelled;
- contemporaneous primary labels and later outcomes retained separately;
- explicit unreviewable status where rights or evidence are insufficient;
- negative and failure sampling, not positive-only selection;
- authorised human-reviewed release labels;
- practical blinding of path, confidence, and system outcome;
- independent review or adjudication for blockers, zero-tolerance failures,
  Urgent material errors, and a planned ordinary sample; and
- retained reviewer disagreement that cannot be resolved by model confidence or
  metric preference.

Source promotion, removal, or role change must cite event-level coverage,
resilience, rights, cost, and operational evidence. Quiet-period absence alone
cannot remove a rare-event Anchor. A Comparator cannot become an Anchor merely
because it returns more results. Search value, noise, and cost remain attributed
to exact Purpose and provider version.

## Scheduling, access and parser controls

5E owns every operational `DOPS-*` row except `DOPS-076`. In particular:

- duplicate ticks, deliveries, or restarts create one logical due operation;
- due-work determination and no-work completion require no model;
- jitter, host coordination, missed work, bounded ownership, and catch-up remain
  explicit;
- source access enforces scheme, host, redirect, TLS, credentials, timeout,
  body, content type, and egress;
- conditional requests and status codes retain source-specific semantics;
- parsers block external entities, unsafe deserialisation, decompression bombs,
  and uncontrolled resource use;
- shape drift creates degraded or quarantined state rather than publisher
  activity; and
- delivered channels retain authentication or provenance, replay control,
  bounded payload, and durable receipt.

## Hard limits

Limits are 5,000 ms end-to-end, 8 results per branch, 12 retained candidates,
262,144 response bytes, zero external calls, zero provider cost, graph depth 2,
fan-out 32, and date window 31 days. Limits are never silently widened.

## Outcomes

Outcomes are:

- `COMPLETE` — every mandatory branch, authority, hydration, freshness,
  collision, and reconciliation check for the request completed;
- `DEGRADED` — a named optional contribution failed but bounded meaning remains;
- `INCOMPLETE` — missing authority, mandatory branch, collision, or
  reconciliation prevents complete meaning;
- `POLICY_BLOCKED` — rights, scope, or security forbids the material;
- `STALE` — selected generation or authority is outside the admitted boundary;
  and
- `UNAVAILABLE` — no safe bounded response can be produced.

An empty result is no-match only with `COMPLETE`. This request outcome does
not itself create a Hypothesis or Candidate, authorize Candidate admission,
select Watch or Operational Hold, continue source collection, or change the
product profile; those effects require 5E integration and current authority.

## Security and DOPS-026 / DOPS-067

Only six named tools expose retrieval. Inputs and outputs are typed and bounded.
Raw/generated Cypher, caller Lucene syntax, arbitrary indexes or predicates,
writes, unrestricted source text, model/provider credentials, and projection
text as factual authority are prohibited.

5C proves tool-local caller, purpose, and scope authorization. 5E separately
proves that source/model content cannot alter operational policy, tools, egress,
budgets, credentials, destinations, scope, authority, or admission state.

5E also proves least-privilege credential identity, exact source-access scope,
secret storage/redaction, approved destinations, and rejection of broader,
substituted, or unadmitted credentials, access, or destinations. A successful
tool call is neither `DOPS-026` nor `DOPS-067` evidence.

## Queues, capacity and durable delivery

5E must prove reserved or isolated Urgent capacity; deadline, starvation, and
fairness state for Time-sensitive, Planned, and Routine work; bounded
backpressure that never silently skips required Anchors, Leads, or deadlines;
and current-authority revalidation before commit.

Average, peak, no-change-heavy, and failure-heavy capacity evidence is
mandatory. A committed transition and required downstream work must be atomic
or deterministically reconcilable. Authoritative-state or audit failure blocks
affected effects.

## Reconciliation and recovery

5D can reconcile one retrieval request through fusion, deduplication, hydration,
freshness, collision, and explicit outcomes. That is not the complete
operational reconciliation required by `DOPS-050`.

5E detects and retains evidence for orphaned ownership, missing outcomes,
ambiguous external effects, duplicate delivery, stale work, pending Handoffs,
and projection mismatch. Ambiguous effects are reconciled or retried
idempotently rather than repeated blindly.

Replay retains exact versions and creates later outputs rather than rewriting
history. Catch-up is bounded and prioritises current Urgent and Planned state.
After restore, automatic operation remains blocked until baselines, leases,
queues, Handoffs, and coverage posture are reconciled.

## Monitoring, incidents and manual action

5E monitoring includes schedule, complete-success age, outcome, parser, retry,
queue, budget, coverage, storage, and reconciliation metrics. Structured
records trace due trigger through Check, transition, Lead, Work Item, Candidate,
and Handoff without prohibited data.

Alert priority reflects consequence, coverage, integrity, and urgency rather
than raw error count. Material operational or integrity failures create retained
incidents with scope, timeline, containment, recovery, root cause, and follow-up.
Confirmed errors and material near misses create rights-permitted regression
Cases where applicable.

Retry, requeue, quarantine release, contingency, and override actions are
authenticated and audited.

## Scoped containment and DOPS-073

A per-request `DEGRADED`, `INCOMPLETE`, or `UNAVAILABLE` result is not a
system-level containment mechanism. 5E proves the ability to pause the
narrowest safe affected scope and broaden containment when shared authority,
rights, security, or integrity is uncertain.

Containment actions are role-bounded, authenticated, audited, reversible where
safe, and retained with their trigger, scope, dependencies, exit criteria, and
recovery evidence.

## Rights, purge and recovery

Rights are checked at read time. Personal data, secrets, rights-restricted text,
and public governed source text cannot enter the v1 vector lane.

Withdrawal stops derivative creation. Purge removes passages, full-text entries,
fixed-point vectors, graph derivatives, and cached contexts; records derivative
identities and a purge receipt; rebuilds an isolated generation; and proves
non-resurrection before selection. Any residual blocks qualification.

Rollback selects a prior generation only when exact component identities match,
rights remain current, freshness and completeness pass, and no purged material
returns. Otherwise return `UNAVAILABLE`, `STALE`, or `POLICY_BLOCKED` until a
safe isolated generation qualifies.

## DEVAL-046 evidence

Retain separate counts, opportunity denominators, and ppm rates for false merge,
fragmentation, snowball absorption, false or missed development, duplicate
Candidate creation, and unnecessary Candidate creation. Every class requires at
least ten relevant preregistered cases. Cross-class pooling is prohibited; a
missing class is `NOT_EVALUATED`.

Candidate-related checks use read-only expected dispositions and create no
Candidate.

## Version, challenger, canary and operational admission

Before 5E qualifies a scope, Operational Admission enumerates exact source,
adapter, parser, Profile, worker, retrieval, and provider versions and proves
that every new version starts without inherited authority.

Material operational changes support a bounded canary or equivalent
qualification where technically appropriate. Canary evidence cannot activate
production and cannot weaken rights, safety, authority, or zero-tolerance gates.

A second graph engine may be tested only after a retained measured blocker
against Neo4j Community plus Graphiti or an owner-approved bounded comparison
purpose. Without that record, evidence must prove one implementation only.

## Evidence and stopping conditions

Retain Plan/Epoch/Run/profile/generation identity, branch receipts,
fusion/dedup/hydration outcomes, rights and collision state, event universe,
prospective method, samples, labels, reviewer assignments, adjudications,
disagreement, exposure counts, family metrics, six error-class reports,
comparative results, temporal and rebuild counts, exact components,
purge/rebuild linkage, credential/source/destination evidence, queue and
capacity evidence, health metrics, incidents, manual actions, reconciliation
and containment evidence, and final owner outcome.

Stop and preserve evidence on any successful write, generated query execution,
external call or spend, model load, protected-content vector, authority bypass,
false no-match, purge residual, identity drift, wrong Epoch, unadmitted version,
unapproved challenger, credential/access/destination violation, unresolved
reconciliation, failed containment, or silent branch loss. CI success alone
never activates production.
