# Increment 3D substantive review

**Issue:** #208
**Parent:** #143
**Authorised base:** `main@074ba35b160de87762d57f438c9720f1b27d87b4`
**Reviewed local executable-product commit:** `c7e8ecfcd8c48af01b1da1e0de8a04c483fe99ea`
**Reviewed local executable-product tree:** `6fe927db09b8c589534c0caed4a66f39463ae5e1`
**Status:** current-tree review checkpoint; remote exact-head qualification pending

## Review method

The review traced the full fixture-only path from retained Increment 3C authority through typed payload canonicalisation, authenticated commands, checked migration, transactional persistence, replay/recovery, bounded reads and startup rehydration. It also inspected negative authority boundaries for deterministic exclusions, ambiguity, rights/currentness, urgency, Watch Conditions, later triage authority and external I/O.

Machine evidence for this checkpoint:

```text
Focused Increment 3D tests:                    78 passed
Focused plus retained migration tests:         86 passed
Core shard 0: 385 passed
Core shard 1: 366 passed
Core shard 2: 337 passed, 7 intentional skips
Core shard 3: 385 passed, 25 intentional skips
Merged core topology: 1,473 passed, 32 intentional service-only skips
Clustering regression: pass
Python compilation: pass
Whitespace validation: pass
```

The local environment uses an externally supplied project environment. The repository test `test_uv_command_uses_the_locked_project_environment` passes when `UV_PROJECT_ENVIRONMENT=/opt/pyvenv` is set; GitHub qualification must still perform the canonical `uv sync --dev --locked` under Python 3.12.

## Corrected findings

### P2-01 — schema vocabulary could diverge from accepted source authority

The initial v12 draft duplicated source-role, portfolio-function, dependency and coverage vocabulary as handwritten SQL strings. That could accept a value rejected by the typed Increment 3A registry or reject a newly accepted typed value.

**Correction:** schema constraints are generated from the retained typed enums, and migration tests tie the v12 vocabulary to those exact enums.

### P2-02 — terminal Gate outcomes could omit an inspectable close action

A terminal duplicate, non-change or clear-exclusion decision could previously carry no explicit next action, weakening outcome/reason/action separation.

**Correction:** each terminal Gate outcome requires an exact typed `CLOSE` action, and a close action cannot retain owner, dependency, due or expiry metadata.

### P2-03 — stale authority could be converted into a terminal Gate outcome

The first contract draft allowed some non-hold outcomes when one of identity, rights, policy or operational-executability currentness was false.

**Correction:** any unavailable mandatory authority or non-current time basis deterministically resolves to `SIGNAL_OPERATIONAL_HOLD`; non-hold outcomes require current executable authority.

### P2-04 — duplicate policy could exist without an exact duplicate target

A duplicate rule without a retained duplicate Signal allowed an uninspectable suppression basis.

**Correction:** duplicate rule and exact distinct Signal target are mutually required. Self-duplicate, cross-source and cross-state duplicate targets fail closed.

### P2-05 — incomplete Signal Finding lineage could be caller-selected

A partial Signal could originally name an arbitrary subset or superset of Operational Findings.

**Correction:** admission rederives the exact Findings opened by or occurring under the Check Outcome; supplied Finding identities must match exactly. Promoted incomplete Leads retain an explicit incompleteness warning.

### P2-06 — current action could expose an obsolete Lead disposition

After a promoted Signal later received a Gate hold or suppression, a current-status read could have continued to expose the old Lead disposition as current action.

**Correction:** current Gate authority takes precedence. Historical Lead/disposition records remain inspectable, but current status returns the later Gate action until the Signal is promoted again under accepted rules.

### P2-07 — Watch/disposition writes could continue after Gate authority changed

A retained Lead could receive a new Watch Condition or disposition even after the current Gate no longer promoted its Signal.

**Correction:** both writes require the current Gate head to remain `SIGNAL_PROMOTED_TO_LEAD` and require the exact current Source Definition Version.

### P2-08 — replay completion state collapsed exact replay and race reuse

The admission result could report every retained record as replayed, hiding whether this command was an exact idempotent replay or another worker had won the semantic race.

**Correction:** result state distinguishes `CREATED`, exact-command `REPLAYED` and semantic-winner `REUSED`. `replayed=True` requires every constituent record to be exact replay.

### P2-09 — source contract details could drift at Lead creation

Lead source roles, portfolio functions and dependency declarations could have been accepted from caller bytes without exact comparison to the Source Definition Version.

**Correction:** Lead commitment rehydrates the current source version and requires exact canonical role/function/dependency equality.

### P2-10 — source/version chronology was not uniformly fail-closed

A Signal, Gate, Lead or Watch record could theoretically claim authority before its retained source evidence or under a later source version.

**Correction:** typed time constraints, migration guards and store validators require source version, outcome, transition, Gate, Lead and Watch chronology in order. Current-version revalidation occurs at Gate, Lead, Watch and disposition commitment.

### P2-11 — one promoted Signal could acquire competing Lead authority

The early schema/store design relied mainly on deterministic IDs and did not make the one-Lead-per-Signal invariant sufficiently explicit at every layer.

**Correction:** typed plan validation, semantic uniqueness, a unique Signal reference in `news_leads`, exact promoting-Gate checks and competing-writer tests converge on one Lead.

### P2-12 — temporary transport material could remain in the product diff

Recovery payloads and materialiser workflows had become part of the PR while the ordinary source implementation was absent or incomplete.

**Correction:** the clean product tree deletes every manifest, payload chunk, recovery exporter and materialiser. Transport files are not part of Increment 3D authority.


### P2-13 — historical observation and current Gate version were conflated

The first store and SQL guard required a News Lead to use the Signal's historical Source Definition Version. That prevented a retained source observation from being deterministically re-evaluated after a locator, rights, coverage or role update, even when the identity, revision, canonicalisation, observation-model and baseline contracts remained compatible.

**Correction:** the Signal remains pinned to its exact historical observation version. The Gate explicitly evaluates the current version, rejects incompatible observation contracts unless held, and a promoted Lead records the Gate-evaluated version while preserving the Signal's exact Item/Revision/Representation/Occurrence/Transition lineage. The v12 SQL promotion guard now follows the exact promoting Gate rather than forcing the historical Signal version.

### P2-14 — re-promotion could silently resurrect a stale disposition

A retained Lead's prior disposition could become current again when a later Gate moved from hold or suppression back to promotion, even though that disposition had not consumed the new Gate or its current policy basis.

**Correction:** every Watch Condition and Lead Disposition records the exact current promoting Gate Decision. Writes require that exact Gate head and current evaluated source version. Current status ignores disposition heads bound to an older Gate; during the valid re-promotion crash prefix, action derives from the new Gate until a new Gate-bound disposition commits.


### P2-15 — startup rejected a valid Lead-to-disposition crash prefix

The authority controller deliberately commits Signal, Gate, Lead and initial disposition as separately authenticated records. Startup integrity nevertheless treated a retained promoted Lead with no disposition head as corruption, so a crash after the Lead commit could not reopen and resume even though the admission contract promised prefix recovery.

**Correction:** startup still requires the exact retained promoting Gate and Signal lineage, but permits the bounded missing-first-disposition prefix. Current status derives action from the current promoting Gate, and idempotent admission replay commits the missing disposition. A Lead with a missing or non-promoting Gate remains an integrity failure.

### P2-16 — bounded reads accepted untyped lifecycle identities

Several authenticated read methods converted caller-supplied values to strings before storage lookup. Although no authority mutation was possible, this weakened the typed lifecycle boundary and could produce authorization or lookup behavior for malformed caller identities.

**Correction:** every Signal, Gate, Lead, Watch Condition, Lead Disposition and current-status read validates its exact typed ID before authorization and lookup. A focused regression proves all raw-string identity calls fail before storage access.

### P2-17 — substantive-review evidence was pinned to an earlier local tree

The review record retained the commit, tree and core-shard counts from the first revalidation correction even after later review-only and typed-read fixes advanced the reviewed product. That made the prose evidence stale despite the code and tests being current.

**Correction:** the review record now names the exact latest reviewed executable-product commit and tree, records the then-current 76-case focused suite, 84-case retained migration set and 1,471-passed/32-intentional-skip core topology; the later P2-18 and P2-19 corrections advance final evidence to 78 focused cases, 86 retained cases and 1,473 passed with the same 32 intentional service-only skips, and requires remote exact-head evidence to supersede these local identifiers after publication. The evidence-only commit containing this record is intentionally not self-hashed inside the record.

### P2-18 — exact duplicate suppression could erase a distinct Signal purpose

The duplicate Gate path originally required the target Signal to share the same source, Item and Revision, but it did not require the same deterministic purpose and discriminator. Two legitimate Signals derived from one Revision for different accepted purposes could therefore be collapsed as an exact duplicate even though Increment 3D explicitly permits several Signals only through distinct stable discriminators.

**Correction:** both the transactional store and the v12 SQL outcome guard require the duplicate target to share the exact source, Item, Revision, purpose and discriminator. A focused regression creates two Signals from one Revision with distinct deterministic purposes and proves the second cannot be suppressed as an exact duplicate of the first.

### P2-19 — duplicate direction could form an authority cycle

The duplicate target was required to be retained and equivalent, but it was not required to precede the Signal being closed. Two equivalent Signals could therefore be suppressed in opposite directions, or an earlier Signal could be closed in favour of a later authority event. That would leave no stable prior duplicate survivor and make current duplicate lineage cyclic.

**Correction:** the transactional store and v12 SQL guard compare immutable ledger sequence and require the duplicate target's Signal authority event to precede the current Signal. A regression proves an earlier Signal cannot name a later-admitted Signal as its exact duplicate.

## Boundary review

The current implementation has no import or callable surface for:

```text
external network or browser collection
source credentials or schedules
model, Graphiti, embedding or search execution
Triage Work Items or Retrieval Context
editorial reject, association or supplemental-discovery authority
Event Hypothesis, Candidate or Evidence Handoff authority
Neo4j discovery-lineage projection or health authority
publication, spending, production activation or public effect
legacy link/event/cluster identity import
```

Signals, Gate Decisions and Leads remain unverified discovery records and never become evidence or publication authority.

## Review disposition

```text
P1 findings:             0
P2 findings corrected:  19
Unresolved P1/P2:        0 on the reviewed local product tree
```

This is not final merge evidence. Before PR #217 may merge, the same clean tree must be durably present on the PR branch, receive a normal exact-head qualification commit, pass all six permanent workflows, and have zero actionable comments, submitted-review blockers and unresolved review threads.
