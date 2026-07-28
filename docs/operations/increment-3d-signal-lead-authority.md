# Increment 3D Signal, deterministic-gate and Lead operations

**Status:** implementation review unit for issue #208
**Parent:** #143
**Authorised base:** `main@074ba35b160de87762d57f438c9720f1b27d87b4`
**Execution boundary:** repository fixtures and approved replay only

Increment 3D converts exact retained Increment 3C source-transition lineage into authenticated, append-only Discovery Signal, deterministic Gate Decision and News Lead authority. It adds no source scheduler, external request, browser, model, Graphiti, embedding, search, Candidate, evidence, publication or public-effect capability.

## Public boundary

Open the combined authority through:

```python
from newsroom.authority.discovery_system import (
    open_governed_discovery_authority_system,
)
```

The returned system exposes one shared authority database and writer:

```text
system.sources    retained Source Definition/Version/Item/Revision/Representation/Occurrence authority
system.checks     retained Check/Baseline/Transition/Finding authority
system.discovery Signal/Gate/Lead/Watch/Disposition authority
```

Raw SQLite connections, command grants, capability issuers and private stores do not escape the facade.

`system.discovery.admit_signal_to_lead(...)` is the crash-safe deterministic 3C-to-3D controller. It pre-authorises every required command before the first write and then commits each immutable record independently. A retry resumes from the first missing record; it does not hide a cross-domain transaction.

## Commands and scopes

| Command | Required scope | Durable meaning |
| --- | --- | --- |
| `discovery.signal.admit` | `authority.discovery.signals.admit` | Admit one exact source-transition Signal. |
| `discovery.gate.decide` | `authority.discovery.gates.decide` | Commit one ordered deterministic Gate Decision. |
| `discovery.lead.open` | `authority.discovery.leads.open` | Open one stable Lead for one promoted Signal. |
| `discovery.watch_condition.record` | `authority.discovery.watch.manage` | Retain one finite inspectable Watch Condition. |
| `discovery.lead.disposition.record` | `authority.discovery.leads.disposition` | Append one ordered foundation disposition. |

Metadata/current-status reads require `authority.discovery.read`. Canonical Signal, Gate, Lead, Watch and disposition lineage requires the separate `authority.discovery.read_sensitive` scope. Read limits are checked before lookup.

## Checked schema v12

Schema version 12, migration `signal_gate_lead_authority_v12`, adds immutable authority for:

```text
discovery_signals
discovery_signal_findings
discovery_gate_decisions
discovery_gate_decision_heads
news_leads
discovery_watch_conditions
lead_disposition_decisions
lead_disposition_heads
```

The migration is forward-only from the retained v11 authority. It preserves source/check history, uses exact foreign keys and semantic uniqueness, and installs guarded current heads plus update/delete immutability triggers.

Startup rehydrates every canonical payload and checks its normalized columns, ledger event, audit/command envelope, source lineage, source-role/dependency manifest, Gate and disposition chain, current heads and complete domain-record coverage. Trigger-bypassing SQL changes must cause reopen failure.

## Normal Signal-to-Lead lifecycle

1. Retain one admissible Increment 3C `CheckOutcome`, `DiscoveryOccurrence` and `ObservableTransition` over an exact Source Revision and Representation.
2. Construct one `DiscoverySignalRequest` with the exact source/version/item/revision/representation/outcome/occurrence/transition identities and the versioned Signal-admission policy.
3. Construct one `GateDecisionRequest`. The typed deterministic basis fixes the only allowed outcome:
   - exact duplicate suppression;
   - exact non-change suppression;
   - clear accepted exclusion;
   - operational hold; or
   - promotion to Lead.
4. For promotion, construct one `NewsLeadRequest` and the exact ordinal-1 `LEAD_QUEUED_FOR_TRIAGE` disposition.
5. Call `system.discovery.admit_signal_to_lead(...)` with an authenticated proof.
6. Inspect `SignalLeadAdmissionResult` states:
   - `CREATED`: this invocation committed the record;
   - `REPLAYED`: exact command replay returned the retained record;
   - `REUSED`: another writer committed the exact semantic winner.
7. Read current action through `system.discovery.current_status(...)`. Current status is rebuilt from immutable Gate and disposition heads and is not independent authority.

A later Gate re-evaluation appends an exact predecessor decision. A later non-promoting Gate becomes current action while preserving the historical Lead and its dispositions for audit.

## Deterministic Gate rules

The Gate is fail-closed in this order:

1. identity, rights, policy, version or required operational context unavailable → `SIGNAL_OPERATIONAL_HOLD`;
2. exact accepted duplicate → `SIGNAL_SUPPRESSED_DUPLICATE`;
3. exact repeat, parser-only state or expectation-only transition → `SIGNAL_SUPPRESSED_NON_CHANGE`;
4. unambiguous accepted exclusion → `SIGNAL_REJECTED_CLEAR_EXCLUSION`;
5. genuine source-observable transition with current executable authority → `SIGNAL_PROMOTED_TO_LEAD`;
6. remaining unknown state → operational hold.

Keyword absence, one source, media/domain count, model confidence, similarity, publisher tier, category balance, geography quota, finance quota, spare writing capacity and backlog pressure have no Gate field and no authority.

Cross-source reports remain separate Signals and Leads. Exact duplicate suppression is source/item/revision-local and retains both the suppressed Signal and every Discovery Occurrence.

## Partial and degraded observations

A partial or truncated Check may create a Signal only for an independently valid item already admitted by Increment 3C. The Signal must carry the complete exact Operational Finding set for its Check Outcome, and a promoted Lead must retain an incompleteness warning.

The following cannot create a Signal:

```text
blocked preflight
transport failure
unauthorised or prohibited rights state
malformed or shape-drifted result without an independently valid item
quarantined or disabled source state
```

Operational failure is not no news, deterministic exclusion or editorial rejection.

## News Lead and urgency

One promoted Signal has at most one stable News Lead. The Lead retains exact source roles, portfolio functions and source dependencies from its Source Definition Version.

Urgency remains qualitative:

```text
URGENT
TIME_SENSITIVE
PLANNED
ROUTINE
```

`URGENT` requires an isolation requirement. `PLANNED` requires an inspectable window. No numeric score, quota or media-volume field exists. Urgency changes after Lead creation require later authorised history; the Lead is never silently mutated.

## Watch and disposition seam

A Watch Condition requires at least one finite, inspectable resume or closure basis: transition kind, expected occurrence, distinct corroborating Lead, review time, expiry or authorised operator-review condition. It cannot name itself as corroboration, precede its Lead or outlive contradictory chronology.

Increment 3D may commit only:

```text
LEAD_QUEUED_FOR_TRIAGE
LEAD_OPERATIONAL_HOLD
LEAD_WATCH_DEFER
```

Editorial reject, association, supplemental discovery and Candidate routes remain unavailable until later triage/Candidate authority exists.

A Watch Condition or later disposition may commit only while the current Gate still promotes the Signal, and it records that exact Gate Decision identity. A later Gate hold/suppression blocks new Watch or disposition authority while preserving retained history. A later re-promotion does not silently reactivate an older disposition: the Gate's queue action remains current until a new disposition explicitly binds the re-promoting Gate.

## Crash, replay and competing writers

The controller is safe after each prefix:

```text
Signal
Signal + Gate
Signal + Gate + Lead
Signal + Gate + Lead + initial disposition
```

All required grants are obtained before the first write. Deterministic identities, semantic uniqueness and exact lookups let a retry resume without duplication. A competing writer either creates the record or reloads the exact semantic winner; changed bytes, outcome, policy, urgency, reason or lineage fail closed.

Writer lock contention is scoped to the one SQLite writer. Callers may retry `AuthorityWriterBusy` under an accepted bounded retry policy. They must not create a second authority database or bypass the command service.

## Inspection and diagnosis

Use typed facade reads; do not query mutable heads as sole evidence.

For one Signal inspect, in order:

```text
Signal canonical lineage
Gate history and current Gate
Lead by Signal when promotion exists
Lead disposition history and current disposition
Watch Condition when referenced
source/check/transition records through the sibling facades
ledger/audit evidence through existing authority inspection
```

Interpret current phases distinctly:

```text
SIGNAL_ADMITTED
SIGNAL_SUPPRESSED
SIGNAL_OPERATIONAL_HOLD
LEAD_QUEUED
LEAD_OPERATIONAL_HOLD
LEAD_WATCH_DEFER
```

A missing current Gate may represent an explicit recoverable Signal-only crash prefix. A Lead whose current promoting Gate has no matching disposition is a valid bounded crash prefix: current action derives from that Gate until the next disposition commits. A Lead with no retained original promoting Gate, or a disposition whose recorded Gate lineage is inconsistent, is integrity failure and must prevent reopen.

## Stop and rollback

Stopping Increment 3D means stop issuing Signal/Gate/Lead/Watch/disposition commands. There is no network worker, scheduler, model, search, graph projector, Evidence Intake or publisher to disable.

Before schema v12 opens a database, rollback is branch deletion or an ordinary reviewed source revert. After v12 has opened a database:

- do not downgrade schema history;
- do not delete Signals, Gate Decisions, Leads, Watch Conditions or dispositions;
- restore a verified pre-v12 backup or apply a reviewed forward correction;
- never reconstruct canonical discovery authority from Neo4j, parser output, mutable status or legacy link/event tables.

Executable rollback must preserve retained v12 records and fail closed on commands the older executable cannot understand.

## Evidence commands

Run in the locked Python 3.12 project environment:

```bash
uv lock --check
uv sync --dev --locked
uv run --no-sync python -m pytest -q \
  newsroom/tests/test_discovery_3d_contracts.py \
  newsroom/tests/test_discovery_3d_payloads.py \
  newsroom/tests/test_discovery_3d_policy.py \
  newsroom/tests/test_discovery_3d_traceability.py \
  newsroom/tests/test_discovery_3d_migrations.py \
  newsroom/tests/test_discovery_3d_authority_store.py \
  newsroom/tests/test_discovery_3d_admission.py
uv run --no-sync python -m scripts.sdlc.workflow_lane core-tests \
  --repo-root . \
  --report .sdlc-increment-3d-core.xml \
  --clustering
```

The exact reviewed head must additionally pass CI, Authority A2a, Authority A2b, Projection B1, authenticated Projection B2/B3/C1 Neo4j and the signed SDLC route/core/service/final-decision workflow. Required fixture cases may have no failure, error or required skip.

## Explicit deferred work

Increment 3E owns structural Neo4j discovery-lineage projection and source/parser/projection/coverage health. Later increments own Triage Work Items, retrieval, model proposals, Event Hypotheses, editorial dispositions, Candidates and Evidence Handoff. Named live sources, credentials, schedules, external requests, search, Graphiti, embeddings, spending, shadow, canary, publication and production activation remain disabled.
