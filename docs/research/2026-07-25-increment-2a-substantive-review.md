# Increment 2A substantive implementation review

- Role: Dated current-head review evidence
- Status: Completed for the corrected source tree; exact-head CI still required
- Owner: Product owner
- Canonical language: English
- Date: 2026-07-25
- Related issue: #155
- Parent epic: #142
- Related draft PR: #159
- Authorised base: `main@f29a24201d9808cf8079646c40eaedece5b98ec0`
- Reviewed pre-correction head: `d4877f47e9399964ebaea75bd7fc56daa09258c4`
- Corrected review boundary: the commit containing this record; its exact SHA is recorded on PR #159 after push

## Scope

The review covers only owner-authorised Increment 2A:

- governed Relation Proposal, Admission Decision and Relation Assertion authority;
- the repository-owned `integrated_fixture_v2` schema and bilingual data;
- authenticated and authorised proposal, decision and read boundaries;
- checked SQLite migration and startup integrity;
- idempotency, collision, stale-decision and lifecycle semantics;
- admitted-only projection events;
- governed-object rights, revocation, deletion and tombstone linkage;
- tests, traceability, operations and rollback.

The review explicitly excludes Increment 2B, Neo4j writes or indexes, Graphiti, models, embeddings, live sources, hybrid retrieval, shadow, canary, publication and production activation.

## Review dimensions

The corrected tree was examined for:

- authority separation between immutable SQLite records, governed objects and disposable projections;
- mutation and read-scope least privilege;
- proposal-only versus admitted relation visibility;
- replay, collision, stale decision and immutable-history behavior;
- current-state rebuild behavior after relation and object invalidation;
- result-bound correctness after rights and temporal filtering;
- migration checksums, schema fingerprint and startup cross-record validation;
- bilingual fixture ownership, provenance and lifecycle evidence;
- absence of arbitrary Cypher, caller-selected predicates and graph mutation authority;
- exclusions, rollback and the stop boundary before issue #156.

## Result

- P1 findings: 0
- P2 findings: 7
- Remaining unresolved P1/P2 after correction: 0
- Pull-request review submissions at review time: 0
- Unresolved inline review threads at review time: 0
- Actionable top-level comments requiring source changes at review time: 0

GitGuardian's current PR comment reports that no secrets remain in the pull request. That automated result is security evidence only and does not replace source review or credential revocation when a real secret has previously escaped.

## Findings and corrections

### P2-1 — Projection read authority could inspect proposal metadata

The pre-correction `RelationReadPolicy` used one `authority.relation.read` scope for fixture bindings, proposals, decisions, admitted assertions and projection events. A principal intended only to project admitted relations could therefore read proposal-only and decision metadata.

Correction:

- replace the shared scope with `authority.relation.metadata.read` and `authority.relation.project`;
- require the metadata scope for fixture-binding, Proposal and Decision reads;
- require the projection scope for admitted assertions and projection events;
- reject a policy that assigns both surfaces the same scope;
- add adversarial tests proving a projection-only principal cannot read metadata and a metadata-only principal cannot consume the projection seam.

This correction does not grant either reader mutation authority.

### P2-2 — Rebuild could transiently resurrect a revoked or tombstoned assertion

The pre-correction projection event scan emitted the historical admission `UPSERT` before a later relation or governed-object `REMOVE` when rebuilding from ledger sequence zero. The final state was absent, but a projector applying events in order could briefly recreate prohibited relation content.

Correction:

- determine current relation and governed-object authority before exposing an assertion payload;
- emit only `REMOVE` for a relation that is currently revoked, invalidated, superseded or backed by invalid governed objects;
- never attach a Relation Assertion to `REMOVE`;
- fail closed when current object authority is invalid but no ordered lifecycle event can justify the removal;
- add rebuild-from-zero tests for relation revocation, evidence revocation and evidence tombstone.

Immutable admission history remains in SQLite. The correction changes only the current-state projection seam and prevents derivative resurrection.

### P2-3 — Pre-filter SQL limit could underfill a valid admitted result

The pre-correction admitted read applied `LIMIT` before governed-object and relation-valid-time filtering. An invalid earlier assertion could consume the result budget and conceal a later valid assertion.

Correction:

- scan current `ADMITTED` heads in bounded relation-key pages;
- apply object-authority and valid-time checks before counting a retained result;
- stop only after the requested retained-result limit is reached or the ordered source is exhausted;
- add a regression probe where an invalid first row cannot starve a valid second row under `limit=1`.

### P2-4 — Output limits did not bound internal current-state scans

The pre-correction reads bounded returned rows but could still scan every retained Relation Assertion while resolving current object and decision state. A large or adversarial retained set could therefore consume unbounded work even though the public result limit was small.

Correction:

- retain stable keyset pagination for admitted assertions;
- enforce a server-owned finite scan ceiling derived from the requested result bound and capped by a fixed hard maximum;
- apply the same hard current-state candidate ceiling to projection-event reads;
- fail closed with an explicit state error when complete bounded evaluation is impossible, rather than silently returning an incomplete current view;
- add adversarial tests that lower the hard ceiling and prove both read surfaces stop before decoding an over-bound candidate set.

### P2-5 — Projection pagination could skip sibling effects at one ledger sequence

The pre-correction projection read truncated the sorted event list directly to the caller limit. When one relation or governed-object lifecycle event affects several assertions at the same source ledger sequence, returning only part of that sequence would let a projector advance its cursor and permanently skip the sibling effects.

Correction:

- group projection effects by exact source ledger sequence before applying the result limit;
- return only complete sequence groups in stable relation-key order;
- fail closed when one sequence group itself exceeds the caller limit;
- add a regression test proving `limit=1` cannot split two effects from ledger sequence 42 while `limit=2` returns both.

### P2-6 — Supersession could point backward in authority history

The pre-correction supersession check required a compatible relation axis but did not require the named successor Proposal to have been recorded after the predecessor. A backward edge could therefore create cyclic or causally inverted proposal history.

Correction:

- require the successor Proposal to preserve the exact binding, subject, predicate and object axis;
- require its authoritative ledger sequence to be strictly greater than the predecessor Proposal sequence;
- revalidate the same forward-only condition on store open;
- require the successor Proposal event to precede the supersession Decision event;
- add a regression test proving a later held Proposal cannot supersede itself toward an earlier Proposal.

### P2-7 — Startup validation did not fully bind relation chronology

The pre-correction startup pass reconstructed canonical Decision and Assertion records but did not compare a Decision's retained ledger sequence with its source ledger event, re-run the allowed decision transition history, or bind an Assertion's admission time back to the exact admitting Decision. Re-digested raw-SQL tampering could therefore alter chronology without being rejected by the relation-specific integrity layer.

Correction:

- bind every Proposal event after its exact fixture-binding event;
- bind every Decision sequence to its exact source event and require Proposal, predecessor Decision and successor Proposal causation to precede it;
- re-run the decision state machine from the immutable predecessor action;
- require an Assertion's `admitted_at` value to equal its admitting Decision time exactly;
- add raw-SQL tamper/reopen tests for Decision sequence rebinding and Assertion admission-time rebinding.

## Validation performed

The corrected implementation passed the complete repository test set in five bounded file-list shards:

```text
shard 1: 195 passed
shard 2: 246 passed, 1 skipped
shard 3: 208 passed, 6 skipped
shard 4: 142 passed, 4 skipped
shard 5: 240 passed
---------------------------------
total:   1,031 passed, 11 skipped, 0 failed
```

Additional checks:

- Increment 2A focused selection: `52 passed`;
- `python -m compileall -q newsroom scripts`: passed;
- clustering evaluation gate with `--fail-on-regression`: passed with no regressions;
- `git diff --check`: passed;
- PR #159 review submissions and inline review threads: zero at review time.

The working environment could not complete `uv lock --check` because the configured internal package mirror repeatedly returned HTTP 503 while fetching declared dependencies; the final attempt failed on `requests`. `pyproject.toml` and `uv.lock` are unchanged by Increment 2A. Exact-head GitHub CI must still execute the repository lockfile check and all applicable SDLC gates before merge.

The unsharded local pytest process was stopped by the execution wrapper timeout after reaching 76 percent, so the complete result above comes from deterministic file-list shards rather than a claim that the timed-out process completed.

## Residual merge gates

This review closes the known substantive P1/P2 findings but does not authorise merge. PR #159 remains draft until:

1. the corrected source and this review record are committed and pushed;
2. every applicable workflow runs against the exact final head and passes;
3. SDLC exact-head evidence is green;
4. review submissions, unresolved threads and actionable comments remain zero or are resolved; and
5. the final exact head and evidence are recorded on issue #155.

CI is regression evidence, not owner approval. Issue #156 remains blocked until Increment 2A is merged and issue #155 is closed with exact evidence.
