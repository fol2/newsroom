# Increment 3C Check and observable-transition operations

**Status:** implementation review unit for issue #207
**Parent:** #143
**Authorised base:** `main@707519cebcc18fd8010b9b1b608b361ab2f6de03`
**Execution boundary:** fixture and approved replay only

Increment 3C converts an exact Increment 3B `ObservationProposal` into authenticated, append-only Check, baseline, Source Revision, Discovery Representation, Discovery Occurrence, observable-transition and Operational Finding authority. It does not fetch a source, schedule work, use credentials, run a browser or model, create a Discovery Signal, make an editorial decision, publish, spend or produce a public effect.

## Public boundary

The public combined system is `newsroom.authority.check_system.GovernedCheckAuthoritySystem`:

```text
system.sources  -> retained Increment 3A source authority
system.checks   -> Check, baseline, transition and Finding authority
```

Both facades share one SQLite writer, command registry, payload registry, capability issuer, authentication and authorization boundary, audit stream and ledger. Raw SQLite connections, command grants and private writers are not exported.

`system.checks.admit_proposal(...)` is the deterministic 3B-to-3C admission boundary. It accepts an exact retained Check Request and Attempt, the corresponding typed Adapter Request and Observation Proposal, an explicit baseline control, and at most one typed transition directive per source item. Every durable record remains a separately authenticated command; there is no hidden multi-domain transaction.

## Commands and scopes

| Command | Required scope | Durable meaning |
| --- | --- | --- |
| `check.request.register` | `authority.checks.manage` | Retain one semantic request bound to trigger, source version, coverage, rights, adapter and policy versions. |
| `check.attempt.start` | `authority.checks.execute` | Start one immutable primary, retry, replay or confirmation attempt with exact predecessor order. |
| `check.outcome.record` | `authority.checks.observe` | Retain one terminal or degraded result for one exact Attempt and Proposal. |
| `check.baseline.decide` | `authority.checks.decide` | Establish, reset or rebuild one source-specific baseline head. |
| `source.observable_transition.record` | `authority.checks.decide` | Retain one deterministic observable transition for one item under one Check Outcome. |
| `operational.finding.open` | `authority.findings.manage` | Open one stable operational case. |
| `operational.finding.occurrence.record` | `authority.findings.observe` | Append one exact contributing occurrence to a Finding. |

Source Item, Revision, Representation and Occurrence writes continue to require the Increment 3A source scopes. Admission pre-authorizes every required source, baseline, transition and Finding command before recording the Check Outcome, so missing authority cannot leave a misleading partial Outcome.

Metadata reads require `authority.checks.read`; sensitive canonical request, outcome and lineage details require the separate `authority.checks.read_sensitive` scope. Authorization occurs before lookup.

## Checked schema v11

Schema version 11 adds immutable tables for:

```text
check_requests
check_attempts
check_outcomes
baseline_decisions
baseline_manifest_entries
baseline_decision_heads
observable_transitions
operational_findings
operational_finding_occurrences
discovery_occurrence_check_links
```

The migration is forward-only and is named `check_transition_authority_v11`. Startup rehydrates canonical bytes and validates normalized columns, event envelopes, exact attempt order, Outcome lineage, baseline heads, transition Revision/Representation lineage, Finding lineage, post-v11 Occurrence links and complete ledger-event coverage. Trigger-bypassing SQL changes must cause reopen failure.

One Attempt has at most one Outcome. One Check Outcome may create at most one Baseline Decision and at most one transition classification per Source Item. A later call cannot reinterpret the same observation as a different baseline or transition.

## Check lifecycle

1. Register one `CheckRequestRequest`. Its semantic identity excludes only request identity and request time; trigger, exact Source Definition Version, coverage, rights, adapter request, producer slot and all policy versions remain bound.
2. Start Attempt 1 as `PRIMARY`. Every later Attempt names the exact immediately preceding Attempt and uses the next ordinal.
3. Execute the fixture adapter outside authority. The adapter returns evidence only and retains `authority_effect = NONE`.
4. Admit the exact proposal. Admission verifies the current source version, Check Request and Attempt, Adapter Request and Parser Result lineage before authorizing writes.
5. Record the Check Outcome. Empty, unchanged, changed, partial, truncated, blocked, redirected, rate-limited, unauthorised, not-found, gone, malformed, drifted and transport-failed results remain distinct.
6. Resolve or create stable Source Items, Source Revisions and producer-specific Representations. Re-observation creates another Occurrence rather than another Revision.
7. Establish or advance the explicit source baseline when policy requires it.
8. Record only deterministic observable transitions permitted by the source model and exact evidence.
9. Open or reuse an Operational Finding for incomplete or failed source operation and append an exact occurrence.

Exact replay returns the retained records. A crash after any prefix is resumed from the first missing command. A competing worker may lose a semantic race, but it reloads the winner's exact record and cannot report a duplicate creation.

## Source-model policy matrix

| Observation model | First baseline | Later default or required classification |
| --- | --- | --- |
| `MUTABLE_ITEM` | Exactly one `MAINTAINED_BASELINE_ONLY` item; first observation is not “new publication”. | A different permitted state creates `REVISED`; parser-only changes create a Representation and Occurrence only. |
| `APPEND_ONLY` | `BOUNDED_BACKFILL`; every observed entry remains in the manifest, but only policy-fresh entries are included. | A genuinely later item creates `FIRST_OBSERVED`. Disappearance has no ending authority. |
| `ROLLING_LIST` | `BOUNDED_BACKFILL`. | New items may create `FIRST_OBSERVED`; disappearance can only be `AMBIGUOUS_ABSENCE` under a non-authorizing guard. |
| `COMPLETE_CURRENT_STATE` | `FIRST_OBSERVED_ACTIVE`; a valid empty snapshot is an explicit empty baseline. Included first items create `ACTIVATED`. | Present changed items may advance independently. Absence can end state only with a complete, identity-confirmed, pagination-complete, grace-satisfied guard and no alternative explanation. |
| `EXPLICIT_DELTA` | `EXPLICIT_DELTA_SEQUENCE`. | Every new or changed candidate requires an explicit typed directive such as activation, escalation, de-escalation, cancellation, withdrawal, replacement or reactivation. |
| `PLANNED_AGENDA` | `FUTURE_EXPECTATIONS_ONLY`; past or unknown expectations remain explicit excluded entries. Future included entries create `AGENDA_CREATED`. | Reschedule, cancellation, occurrence, late occurrence and miss require Agenda transition directives. A miss additionally requires a closed window and complete confirmation guard. |

`BaselineControl.AUTO` establishes only the first baseline. `RESET` and `REBUILD` require a `RESET_REBUILD` trigger and the exact current predecessor identity. `MANUAL_HOLD` is itself a retained decision, including when the underlying Outcome is incomplete. Replaying one baseline decision must reproduce its exact control, entries and canonical digest.

## Partial and degraded observations

`SUCCESS_PARTIAL` and `SUCCESS_TRUNCATED` remain incomplete Outcomes and always create or update an Operational Finding. Independently valid present candidates may still create Source Revisions and current-item transitions because their positive evidence is retained. They may not establish clean absence, ending, deletion, withdrawal or a clean Agenda miss. Missing items under partial or rolling evidence remain unknown or ambiguous.

The persistence guard therefore permits an incomplete Outcome transition only when either:

- the transition has an exact current Revision and Representation; or
- the transition is explicitly `AMBIGUOUS_ABSENCE` with a non-authorizing guard.

An incomplete Outcome with no current Revision cannot infer authoritative state.

## Operational Findings

Unsuccessful or incomplete proposals map deterministically to stable cases:

| Proposal outcome | Finding category | Severity |
| --- | --- | --- |
| `BLOCKED` | Policy | Blocking |
| `SUCCESS_PARTIAL`, `SUCCESS_TRUNCATED`, `MALFORMED` | Parser | Degraded or Blocking |
| `REDIRECTED`, `NOT_FOUND`, `GONE`, `SHAPE_DRIFT` | Source contract | Degraded, Blocking or Integrity |
| `RATE_LIMITED`, `TRANSPORT_FAILED` | Transport | Degraded |
| `UNAUTHORISED` | Rights | Blocking |

A clean `SUCCESS_EMPTY` is not a Finding. Repeated occurrences reuse the stable case and append separate evidence. A Finding is operational authority only; it is not a Coverage Gap, Discovery Signal, Lead, Candidate, factual conclusion or editorial rejection.

## Transition safeguards

- Source-published, source-updated and expected Agenda times remain untrusted source metadata, separate from observation and record time.
- A changed URL is locator evidence only and cannot silently choose Source Item continuity.
- `404`, `410`, timeout, TLS failure, authentication failure or malformed input cannot independently establish deletion or withdrawal.
- Re-observation requires a previously observed exact Revision.
- Reactivation requires a retained ending transition and explicit change facets.
- Replacement requires a separate related Source Item.
- A transition directive is source-local, version-bound and may classify at most one transition for its item under one Outcome.
- The same Check Outcome and item cannot later be reclassified.
- No transition creates a Signal, Lead, Candidate, materiality decision or public effect.

## Stop and rollback

Stopping Increment 3C means stop issuing Check and proposal-admission commands. There is no source scheduler, network worker, credential, queue consumer, Neo4j discovery projector, model invocation or publication process to disable. Existing rows remain immutable audit history.

Before schema v11 has opened a database, rollback is an ordinary source revert. After v11 has opened a database, restore a verified pre-v11 backup or apply a reviewed forward correction. Do not delete migration history, baseline heads, Check records, transitions, Findings or source lineage. Do not reconstruct canonical authority from Neo4j or another projection.

## Evidence commands

Run from the repository root in the locked environment:

```bash
uv lock --check
uv sync --dev --locked
uv run python -m pytest -q \
  newsroom/tests/test_check_3c_contracts.py \
  newsroom/tests/test_check_3c_baselines.py \
  newsroom/tests/test_check_3c_transitions.py \
  newsroom/tests/test_check_3c_agenda.py \
  newsroom/tests/test_check_3c_findings.py \
  newsroom/tests/test_check_3c_transition_planning.py \
  newsroom/tests/test_check_3c_migrations.py \
  newsroom/tests/test_check_3c_authority_store.py \
  newsroom/tests/test_check_3c_authority_integrity.py \
  newsroom/tests/test_check_3c_admission.py \
  newsroom/tests/test_check_3c_admission_findings.py \
  newsroom/tests/test_check_3c_model_policies.py \
  newsroom/tests/test_check_3c_concurrency.py \
  newsroom/tests/test_check_3c_traceability.py
uv run python -m pytest -q
uv run python scripts/eval_clustering_metrics.py \
  --dataset newsroom/evals/clustering_eval_dataset_v1.jsonl \
  --baseline newsroom/evals/clustering_eval_metrics_baseline_v1.json \
  --fail-on-regression
```

Required exact-head evidence includes all permanent repository workflows, zero required skips, migration history and fingerprint checks, raw-SQL tamper rejection, exact replay, crash-prefix recovery, competing-worker convergence, one transition classification per Outcome/item, and current-head substantive review with zero unresolved P1/P2 findings or review threads.

## Deferred by design

Increment 3D owns Discovery Signal admission, deterministic Gate Decisions, News Leads, urgency and Watch Conditions. Increment 3E owns disposable Neo4j discovery-lineage projection and source/parser/projection/coverage health. Named live sources, credentials, source-specific schedules, browser collection, production retry/circuit profiles, shadow, canary, publication and public activation remain separately blocked.
