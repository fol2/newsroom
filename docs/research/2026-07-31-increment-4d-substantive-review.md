# Increment 4D substantive review — isolated proposal-only Graphiti adapter

**Issue:** #228
**Parent:** #144
**Authorised base:** `main@b2f12922e5ec853991f95ac41bf46a977a70dc1a`
**Review status:** local current-tree review; exact remote-head qualification still required

## Review question

Does Increment 4D provide a production-shaped but non-activating Graphiti integration boundary that can only create retained proposals through the qualified Extraction Run authority, while private workspace state, model output and Graphiti identifiers remain untrusted and disposable?

## Review conclusion

At the current local review point, the implementation meets the deterministic 4D boundary:

- one final typed adapter interface is shared by deterministic fake and approved replay;
- real Graphiti/model execution remains disabled and unqualified;
- exact configuration, manifest, attempt, usage, outcome, cleanup and replay authority is retained under checked schema v16;
- private workspace state is isolated, bounded, credential-free, deny-all egress and disposable;
- private graph IDs and Cypher cannot enter public canonical contracts;
- Extraction Run output and proposals persist atomically before adapter-attempt authority and before any downstream admission can reference them;
- the adapter exposes no entity, relation, Candidate, Evidence Intake, publication or governed graph decision surface;
- approved replay survives complete workspace loss and never reruns extraction;
- rights revocation, tombstone and Source Definition Version change block current attempt/replay use without deleting history;
- source/prompt injection cannot alter tools, schema, egress, credentials, budget or admission authority; and
- permanent Authority and Projection bridge files select 4D evidence directly.

The review found no P1 issue. Seventeen P2 findings identified during implementation were corrected and covered by focused tests. This document is not final merge evidence: the clean source must still be published to the 4D PR, receive all exact-head workflow evidence and pass current-head review with zero actionable findings and unresolved threads.

## Corrected findings

### P2-01 — a structurally valid real configuration could be mistaken for execution approval

A configuration object can bind framework, model, prompt, destination, credential and budget placeholders, but structural completeness is not owner authorization.

**Correction:** `REAL_GRAPHITI_RUNTIME_ENABLED = False` is an explicit repository boundary. Evaluation and production require a separately typed owner authority packet and still fail closed until a reviewed code change enables the exact runtime.

### P2-02 — private graph identifiers could leak into canonical authority

A framework workspace may need internal node and relation identifiers. Carrying them into Proposal Envelopes or public records would make Graphiti private state hidden authority.

**Correction:** canonical validators reject private node/relation IDs, Graphiti/Neo4j IDs, Cypher, credentials and secret fields. Public adapter records retain only Newsroom identities, digests and typed provenance.

### P2-03 — workspace cleanup needed positive absence proof

Deleting files without checking the namespace could leave private state that later appears recoverable or authoritative.

**Correction:** every attempt records lifecycle and a cleanup receipt with file/node/relation counts and `workspace_absent=True`. Checked reopen rejects a recreated supposedly cleaned namespace.

### P2-04 — hydration manifest could become a second source-text authority

Retaining source expression inside the adapter manifest would duplicate governed-object authority and complicate rights deletion.

**Correction:** the manifest retains exact Source/Revision/Representation/Passage, Admission, Access Decision, byte and digest metadata only. Text is rehydrated through the current Extraction Run authority and is excluded from safe representations.

### P2-05 — Extraction Run and adapter metadata could commit in separate transactions

If output/proposals committed first and adapter metadata failed later, the system could not prove which private attempt produced the retained output.

**Correction:** the extraction store accepts a private post-persist callback inside the same transaction. Extraction output, proposals, cleanup, attempt, head and event now commit or roll back together.

### P2-06 — the attempt decoder was incorrectly class-scoped

The first decoder shape was a class method even though it needed retained configuration and contract decoders bound to the store instance.

**Correction:** attempt decoding is instance-bound and checked reopen reconstructs the complete extraction, configuration, manifest, replay and event lineage.

### P2-07 — Passage canonical digest was incorrectly globally unique

The initial v16 draft made a manifest-passage canonical digest unique across the database. The same governed Passage must be allowed in multiple immutable attempts and approved replays.

**Correction:** uniqueness is scoped by `(manifest_id, passage_ordinal)` and Passage identity inside the manifest. Replay through a later Run Version is now valid without weakening canonical checks.

### P2-08 — configuration identifier reuse could surface as a generic event conflict

Committing the command grant before semantic identifier checks made incompatible reuse fail through a lower-level aggregate-version error.

**Correction:** identifier and semantic collision checks happen before the new event is committed. Callers receive typed `GraphitiAdapterIdentifierReuse` or semantic collision and no partial authority row.

### P2-09 — replay reads shared a broader attempt-read scope

Replay approval is admitted authority and should not become visible merely because a principal can inspect proposal attempts.

**Correction:** configuration, attempt and replay reads use three independent scopes. Tests prove every denied combination fails before storage access.

### P2-10 — concurrent identical commands could execute the adapter more than once

The SQLite writer lock serialized commits, but two threads could both run private workspace code before one became an exact replay.

**Correction:** the authenticated boundary uses a process-local reentrant command lock around authorization, preflight, execution and commit. Concurrent identical attempts execute the adapter once and return one durable record plus replay.

### P2-11 — producer timing could decide timeout authority

A producer-reported elapsed value could understate a late completion and retain output beyond the approved budget.

**Correction:** the boundary measures start/end with the authority clock. A late result becomes `TIMEOUT`; output and proposals are discarded, cleanup reason is changed to timeout, exact replay does not rerun the workspace and a later contiguous retry is permitted.

### P2-12 — lower-layer rights errors leaked through the adapter API

Preflight and current reads could expose Extraction Rights exceptions directly, making the public adapter boundary inconsistent.

**Correction:** current-input and retained-attempt rights failures are normalized to `GraphitiAdapterRightsDenied` while preserving the original cause.

### P2-13 — source/prompt injection needed proof before workspace activation

A source could contain instructions to run Cypher, exfiltrate credentials, enable network, increase budgets or auto-admit relations.

**Correction:** execution compares exact hydrated bytes, allowed length, digest and Access Decision before activating a workspace. A modified injection fixture fails closed, creates no Run Version or attempt and cannot change deny-all egress, credential class, budget or admission state.

### P2-14 — startup integrity needed direct trigger-bypass evidence

Immutable triggers alone do not prove a copied or deliberately altered database will be rejected on reopen.

**Correction:** tests bypass individual guards and prove reopen rejects changed manifest Passage data, a missing attempt head, a missing replay binding and a recreated private workspace. Ordinary updates to configurations, attempts, manifests and replay sources are rejected by immutable triggers.

### P2-15 — permanent workflows did not automatically select adapter evidence

The repository-wide suite would run 4D tests, but focused Authority and Projection workflows select filename-specific bridge inventories.

**Correction:** dedicated A2a, A2b and Projection B1 files prove ordered command envelopes, rights revalidation and zero admitted entity/relation projection from workspace/proposal state.

### P2-16 — workspace loss and replay could be conflated with private-state recovery

A replay path that depended on reconstructing private graph state would make the disposable workspace a hidden recovery source and would rerun stochastic extraction.

**Correction:** replay requires one exact admitted approval over retained Run Version, Output, Proposal Set and payload digests. It uses no private workspace recovery and survives complete workspace deletion. Fake/replay profiles remain invalid production substitutes.

### P2-17 — a pre-existing Extraction Run surfaced a generic type failure instead of ambiguous effect

If the Extraction Run command committed without the coupled adapter-attempt event, the boundary correctly detected an exact Extraction Run replay, but commit validation checked for a fresh execution result before classifying the crash-gap state. That leaked a generic `TypeError` and obscured the explicit reconciliation requirement.

**Correction:** extraction-grant replay is classified before typed execution validation. The authority now raises `GraphitiAdapterAmbiguousEffect`, never reruns the private workspace and preserves the retained Extraction Run while creating no adapter-attempt row.

## Authority and runtime boundary review

The current implementation has no import or public callable surface for:

```text
Graphiti or a model-provider SDK
network, HTTP clients, source credentials or schedules
arbitrary SQL/Cypher or governed Neo4j writes
caller-selected graph labels, node IDs or relation IDs
entity-resolution or relation-admission decisions
Candidate or Evidence Intake writes
publication, spending, shadow, canary or production activation
```

The deterministic fake and approved replay are qualification mechanisms through the final interface. Neither is a real-runtime substitute. No model, embedding, live source, provider credential or network call occurred during this implementation.

## Current local evidence

```text
Dedicated Increment 4D adapter-authority tests:                         69 passed
Permanent A2a/A2b/Projection B1 adapter bridges:                         3 passed
Predecessor 4A/4B/4C migration regressions:                             12 passed
Combined focused qualification:                                         84 passed
Permanent Authority A2a inventory (overlapping):                         33 passed
Permanent Authority A2b inventory (overlapping):                         90 passed
Permanent Projection B1 inventory (overlapping):                         38 passed
Focused required skips:                                                   0
Focused failures/errors:                                                  0
Compile, lock and diff checks:                                           pass
Fresh schema v16 and checked v15-to-v16 migration:                       pass
Atomic output/proposal/attempt persist ordering:                         pass
Workspace cleanup and complete-loss replay:                              pass
Timeout, exact replay and later retry:                                   pass
Rights revocation, tombstone and source-version blocking:                pass
Injection, redaction, scope and import/API guards:                       pass
Raw-SQL tamper and checked startup integrity:                            pass
```

The exact count above must be re-derived by the final local run and replaced if the inventory changes. Final complete repository and authenticated-service evidence must come from the permanent exact-head workflows rather than being inferred from focused local tests.

## Review disposition

```text
P1 findings:             0
P2 findings corrected:  17
Unresolved local P1/P2:  0
Review threads:          pending current remote-head audit
Exact-head workflows:    pending clean publication
Real runtime:            disabled and unqualified
```

Issue #229 remains blocked. Neither this review nor completion of the deterministic adapter authorises real Graphiti/model execution, provider credentials, governed graph writes, publication or production effects.
