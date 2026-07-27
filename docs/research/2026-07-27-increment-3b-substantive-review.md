# Increment 3B substantive review

**Date:** 2026-07-27
**Implementation issue:** #206
**Parent:** #143
**Programme:** #141
**Authorised base:** `main@86afbf878f6b138ae0c99386d42828b32f12b645`
**Review unit:** Increment 3B — Generic transport and parser adapter boundary
**Runtime authority:** Repository fixtures and approved replay only

## Review conclusion

Increment 3B now provides bounded, production-shaped transport and parser proposal contracts on top of the stable Increment 3A source authority while preserving a strict no-external-access boundary. It creates no Check, Source Revision, Signal, Lead, Operational Finding, projection, model, publication or production authority.

Current substantive-review disposition:

- P1 findings: **0**;
- P2 findings found and corrected: **14**;
- unresolved P1/P2 findings: **0**;
- focused reviewed and retained tests: **78 passed**;
- focused failures, errors and skips: **0**;
- temporary materialisation, payload or review transport retained in the PR: **0 files**.

The reviewed implementation correction was materialised and committed as `2cdc9b94d06e53468ffe3fc094c810f65504a2f0`. This document, the corrected operations record and exact traceability are the final review-record changes. The exact final PR head and permanent workflow identities are recorded in PR #211 after all required gates complete for the resulting head.

## Reviewed surface

The review covered:

- typed Adapter Request, attempt, Capture, Parser Result and Observation Proposal identities;
- fixture/replay-only execution and explicit no-authority-effect output;
- endpoint, host, port, redirect, DNS and TLS evidence contracts;
- timeout, compressed-body, decompressed-body, decompression-ratio, content-type, charset and encoding bounds;
- safe RSS/Atom, strict JSON and maintained-document parsing;
- stable source-scoped item identity and maintained-document singleton identity;
- parser/normalizer producer provenance separated from representation equality and Source Revision identity;
- exact baseline, validator and reprocessing semantics;
- honest empty, unchanged, changed, partial, truncated, blocked, redirected, rate-limited, unauthorised, not-found, gone, malformed, shape-drift and transport-failure outcomes;
- response metadata minimisation and exact cross-record lineage;
- fixture corpus, import/runtime guards, operations, exclusions, deferred work and rollback; and
- compatibility with retained Increment 3A authority and the complete repository suite.

## Corrected findings

### P2-01 — Source Item proposal equality included producer and non-identity metadata

Source-scoped item keys now use only the typed Source Definition identity plus configured required identity-field values, or the Source Definition identity plus an explicit singleton identity. Adapter, parser, normalizer and shape versions, non-identity fields, uncertainty wording, URLs, titles, timestamps and content digests cannot allocate a second logical Source Item.

### P2-02 — Maintained-document body changes could allocate changing identity

Maintained-document shapes now require an explicit stable singleton identity. Changing the maintained body changes the parsed item digest but preserves the logical item key.

### P2-03 — Baseline evidence conflated source bytes, producer and representation

`ObservationBaseline` now retains source-body digest, producer-slot digest, normalized representation digest and stable item-key set as separate exact fields, alongside Source Definition Version, validator-contract and conditional-validator evidence.

### P2-04 — Parser-version provenance was encoded as representation-content inequality

Representation equality now means parsed and normalized content equality. Parser, normalizer, adapter and shape versions are bound by the producer-slot digest. A parser upgrade can therefore retain equal representation content while recording different producer provenance, without fabricating publisher change.

### P2-05 — Same-producer replay did not fail closed on nondeterministic output

The same producer over the same source bytes must reproduce the same representation and stable item-key set. Any mismatch is classified as nondeterministic reprocessing and quarantined as `SHAPE_DRIFT`.

### P2-06 — New-producer reprocessing could silently change stable item identity

Reprocessing unchanged source bytes under a new producer is `SUCCESS_UNCHANGED` only when the stable item-key set is unchanged. Item-key drift is quarantined rather than emitted as source change.

### P2-07 — Redirect validation did not bind evidence to every target

Every redirect target now requires its own exact DNS and TLS evidence, in chain order. Missing evidence, target mismatch, private address, hostname mismatch or TLS-policy failure blocks preflight before a receipt exists.

### P2-08 — Public DNS evidence accepted noncanonical textual addresses

DNS evidence must use canonical textual IP form and must be globally routable. Private, loopback, link-local, multicast, reserved, unspecified and noncanonical addresses fail closed.

### P2-09 — One invalid item could discard independently valid output, while an all-invalid batch could look merely partial

Mixed valid/invalid collections preserve independently valid candidates as `SUCCESS_PARTIAL` with visible parser issues. An all-invalid collection is classified as `SHAPE_DRIFT`; it cannot be interpreted as a successful empty or partial source state.

### P2-10 — Strict shape and identity contracts permitted ambiguous structures

Nested unexpected fields are detected when additional fields are prohibited. Identity fields must be required, identity paths cannot overlap, and singleton contracts reject multiple items. These conditions become drift or contract errors rather than publisher changes.

### P2-11 — Transport receipts retained arbitrary provider response metadata

Receipts now retain only protocol metadata required for content handling, conditional validation, redirect evidence and retry/back-pressure. Cookies and arbitrary provider-debug headers are discarded.

### P2-12 — Generic HTTP failures could be mislabeled as connection failures

Unmapped non-success status codes such as `503` remain HTTP failure status outcomes. They are not rewritten as connection, DNS or timeout failures.

### P2-13 — Body-prohibited statuses accepted response bytes

`204`, `205` and `304` responses carrying payload bytes now fail the transport contract. A valid bodyless `304` establishes unchanged only with an exact source-version, validator-contract and retained-validator baseline.

### P2-14 — Proposal records did not fully revalidate receipt, Capture and Parser Result substitution

Observation Proposal construction now rebinds request and source-version lineage across all retained records. Capture must bind the exact receipt and attempt; Parser Result must bind the exact Capture digest, identity and source-body digest. Cross-attempt or cross-request substitution fails at the contract boundary.

## Adversarial evidence added

`newsroom/tests/test_discovery_adapter_3b_review_regressions.py`, together with updated parser and runner tests, proves:

1. item identity survives non-identity content, shape and producer-version changes;
2. maintained-document revisions retain one singleton item identity;
3. unchanged bytes reprocessed under a new producer remain unchanged while retaining new provenance;
4. same-producer nondeterminism fails closed;
5. reprocessing cannot silently change stable item keys;
6. every redirect target requires public DNS and valid TLS evidence;
7. noncanonical public-address text is rejected;
8. valid items survive an independently invalid peer as honest partial output;
9. all-invalid collections and strict nested shape drift do not become publisher change;
10. identity fields are required, paths cannot overlap and singleton multiplicity is rejected;
11. receipts discard cookies and arbitrary provider metadata;
12. body-prohibited statuses reject payload bytes; and
13. cross-record lineage substitution is rejected.

## Focused and repository evidence

Workflow run `30279144803` reconstructed the checksum-locked reviewed source, compiled it under Python 3.12, ran all Increment 3B suites plus retained Increment 3A suites, and committed the clean reviewed implementation as `2cdc9b94d06e53468ffe3fc094c810f65504a2f0`. The same run's complete repository test job and clustering evaluation also passed.

Focused artifact:

```text
name: increment-3b-reviewed-focused-evidence
artifact id: 8658045266
artifact digest: sha256:c944f1d993f10e0c2943c753867dbb31eb97c6b8b6f30c0d8721d21d374e6cd2
```

Retained JUnit result:

```text
tests: 78
failures: 0
errors: 0
skipped: 0
execution: 3.005 seconds
```

The focused set includes all Increment 3B contract, endpoint-security, parser, runner, review-regression and traceability tests plus retained Increment 3A contract, authority, lifecycle-integrity, review-regression and traceability suites.

The workflow-generated implementation head produced `action_required` follow-on runs rather than executable exact-head evidence. It is therefore not used as the merge-gate head. The final normal branch commits containing this review record trigger fresh permanent workflows, and only those final-head results may satisfy merge evidence.

## Authority and safety assessment

The implementation preserves these boundaries:

- only `FIXTURE_REPLAY_ONLY` execution is constructible;
- the package contains no HTTP client, socket, DNS resolver, credential, scheduler or browser adapter;
- supplied endpoint, DNS, TLS, timing and response objects are untrusted fixture evidence rather than acquired network facts;
- adapter output has `authority_effect = NONE` and cannot commit Check, Revision, Signal, Lead, Candidate or editorial state;
- malformed, failed, partial, missing, redirected, rate-limited and unauthorised outcomes never become healthy unchanged;
- rolling-list absence and incomplete complete-state output cannot create withdrawal or clearance;
- external content cannot alter policy, tools, egress, credentials, budgets or authority;
- parser/version reprocessing creates later representation provenance, not publisher history;
- no legacy `links`, mutable `events`, clusters or legacy IDs enter the package; and
- no named source, live request, Graphiti, model, embedding, search, Neo4j discovery projection, shadow, canary, publication, production activation, spending or public effect is present.

## Rollback assessment

Increment 3B adds no SQLite migration, authority table, queue, lease, credential, worker or external effect. Before merge, rollback is a normal branch revert. After merge, rollback is a normal code revert to the Increment 3A completion commit or a reviewed forward fix. Existing source authority remains immutable and must not be deleted or reconstructed from parser output or a derivative projection.

## Remaining exact-head merge gates

Before merge, PR #211 must retain successful evidence for its final reviewed head from:

- CI;
- Authority A2a;
- Authority A2b;
- Projection B1;
- authenticated Projection B2/B3/C1 Neo4j regression; and
- SDLC Evidence Shadow route, core, service and final decision.

The final head must also have zero unresolved review threads, zero actionable review comments and zero unresolved P1/P2 findings. CI is regression evidence, not owner or production approval.

## Stop boundary

Increment 3C remains blocked. Do not begin Check Request, Attempt, Outcome, authoritative baseline, retry, Operational Finding or observable-transition implementation until PR #211 is merged, issue #206 is closed with exact completion evidence and the generic adapters can return bounded, typed and honest proposals against the stable 3A source contracts without external access.
