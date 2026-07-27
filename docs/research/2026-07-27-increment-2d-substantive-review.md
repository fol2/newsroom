# Increment 2D substantive implementation review

- Role: Dated current-head review evidence
- Status: Corrected local source boundary; exact-head actual-service and signed CI evidence still required
- Owner: Product owner
- Canonical language: English
- Date: 2026-07-27
- Related issue: #158
- Parent epic: #142
- Authorised base: `main@41e8bcdc1664514932c0994d58512faa4fe7658c`
- Reviewed pre-record local head: `f1efe6c53a3314b4a1798efccde3eaed351f7330`
- Corrected review boundary: the commit containing this record; its exact remote SHA must be recorded after publication

## Scope

This review covers only the owner-authorised Increment 2D complete deterministic fixture proof:

- checked SQLite schema version 9 development Candidate authority;
- the repository-owned development Candidate minimum-handoff manifest;
- authenticated and authorised Candidate admission and decision reads;
- one public non-authoritative proof controller;
- exact replay, collision and semantic deduplication;
- authenticated actual-Neo4j complete-generation, retrieval and Candidate evidence;
- replacement-generation, relation-revocation, governed-deletion and restart behavior;
- permanent workflow, SDLC, operations, traceability and rollback boundaries.

It excludes Increment 3, live sources/search, Graphiti, external models or embeddings, generalized retrieval, production protected-content vectors, full triage, shadow, canary, activation, publication, spending and public effect.

## Result

- P1 findings: 0
- P2 findings: 14
- Remaining unresolved P1/P2 after correction: 0

Review submissions, requested changes, inline threads and actionable PR comments must be rechecked against the exact final remote head before merge.

## Findings and corrections

### P2-1 — The Candidate fixture initially lacked the minimum development handoff

The first Candidate-authority checkpoint bound identity, route, relation and context but did not retain the editorially necessary development handoff: coverage basis, an explicitly unverified hypothesis, geography, category, urgency, likely new information, reader utility, uncertainties, evidence objectives and the applicable policy versions.

Correction:

- extend the immutable repository-owned manifest with bounded typed handoff content;
- keep the hypothesis trust scope `PROPOSED` and route `DEVELOPMENT`;
- include the handoff in the manifest and semantic-collision digests; and
- add exact contract and startup-integrity evidence.

### P2-2 — Candidate authority lacked explicit lifecycle and recovery evidence

The initial schema-v9 tests covered admission, replay, deduplication and tamper rejection but did not prove how already-admitted Candidate history behaves after relation revocation, governed deletion, a gap, a dead letter or a replacement generation.

Correction:

- add complete-registry helpers that preserve one SQLite writer and all retained command definitions;
- prove old Candidate, Candidate Version and decision history remains immutable;
- prove current invalid authority blocks later admission and replay as a new decision input; and
- prove replacement-generation recovery deduplicates to existing Candidate authority.

### P2-3 — The complete proof was test composition rather than a public bounded controller

A collection of helpers could demonstrate the path but did not provide the required public integrated controller boundary. That made it harder to prove the orchestrator itself owns no database, graph, relation, object or Candidate authority.

Correction:

- add `Increment2CompleteProofController` with typed preparation and Candidate-authority capabilities;
- expose no driver, Cypher, SQL, label, predicate, generation selector or result limit;
- verify exact generation, checkpoint, admitted relation, four branches, fusion and bilingual hydration; and
- prove retrieval replay, Candidate replay and restart without duplicate authority.

### P2-4 — Permanent workflows did not require the complete 2D proof

The Candidate controller initially had unit evidence only. The permanent authenticated Neo4j and signed SDLC workflows could pass without executing Increment 2D.

Correction:

- add the dedicated `NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED` boundary;
- include the complete proof file in the permanent service command;
- enumerate exact required JUnit identities; and
- classify those identities optional only in the no-service deterministic core lane.

### P2-5 — Graph, full-text and vector loss were not tested at the integrated Candidate boundary

Earlier increments separately proved projection and retrieval failure, but the complete controller still needed direct evidence that none of those missing surfaces could create Candidate authority.

Correction:

- delete the generation full-text index, vector index and admitted relation projection in separate actual-service cases;
- require explicit unavailability or contract incompleteness;
- prove all Candidate tables remain empty; and
- retain the exact three parameterized identities in the permanent JUnit gate.

### P2-6 — Replacement and revocation were not proven against actual Neo4j

Authority-only tests established the intended semantics, but issue #158 requires the same behavior through real generation rebuild, promotion and retrieval.

Correction:

- add actual-service replacement-generation rebuild and promotion from retained authority only;
- admit from the recovered context and require `DEDUPLICATED` against the original Candidate and Candidate Version;
- revoke the admitted relation, rebuild a later generation and require a later non-complete context; and
- prove the earlier Candidate and decision remain unchanged.

### P2-7 — Required gaps and dead letters could pass the integrated proof only by inference

The retrieval layer already rejected gaps and dead letters, but the final fixture proof needed exact evidence that neither state could be transformed into a Candidate decision.

Correction:

- introduce a required source gap and a retained dead letter after initial Candidate admission;
- require stale admission reuse to fail;
- require later retrieval to be explicitly non-complete; and
- prove Candidate, Candidate Version and decision counts do not increase.

### P2-8 — Tombstone evidence did not directly prove derivative purge

The first destructive-object test proved replacement validation failed, but did not explicitly inspect the active and replacement Neo4j generations for the prohibited passage derivative.

Correction:

- deliver the revocation/deletion/tombstone authority events to the current generation;
- require the tombstoned passage derivative count to become zero;
- rebuild a replacement generation and require the derivative count to remain zero; and
- require complete validation to fail rather than recreate or silently omit required authority.

### P2-9 — Proposal-only relation exclusion was inferred rather than retained in the complete proof

The complete proof verified the admitted `DEVELOPMENT_OF` relation but did not retain an explicit competing `SAME_EVENT_AS` proposal and prove that it remained proposal-only in both SQLite assertion authority and Neo4j projection state. That left one required issue #158 boundary dependent on earlier-unit evidence.

Correction:

- retain a synthetic authorised `SAME_EVENT_AS` distractor proposal before the complete rebuild;
- require it to exist in `relation_proposals` but never in `relation_assertions`;
- require the complete generation to contain zero `SAME_EVENT_AS` relationships; and
- preserve Candidate admission through only the governed admitted `DEVELOPMENT_OF` relation.

### P2-10 — The normalized Candidate tamper regression stopped at schema fingerprint validation

The first normalized-row tamper test dropped the immutable-update trigger, changed a Candidate Version column and reopened the store. Reopen correctly failed, but it failed at the earlier schema-fingerprint boundary because the trigger remained absent; the test did not prove the Candidate-specific normalized-column check.

Correction:

- capture the exact retained trigger definition;
- temporarily remove it only to inject the normalized-column tamper;
- recreate the exact trigger before reopen so the schema fingerprint remains canonical; and
- require the Candidate Version normalized-column validator itself to reject the tampered value.

### P2-11 — Complete proof preparation did not use the caller-supplied authentication proof

The actual-service proof controller accepted a typed `AuthenticationProof`, but the trusted preparation callback delegated rebuild, validation, qualification and promotion to older helper functions that created a separate static proof. The later retrieval and Candidate operations still authenticated correctly, but the complete preparation chain was not cryptographically tied to the proof supplied to the public controller.

Correction:

- make the complete preparation boundary require the supplied typed proof;
- use that exact proof for generation reads, rebuild, validation, qualification and promotion;
- retain repository-owned fixed operation identities and policy scopes; and
- keep direct lifecycle fixtures explicit by passing their own repository-owned proof rather than relying on hidden helper credentials.

### P2-12 — Candidate decision reads used the broader integrated security scope

The Candidate decision read correctly required `authority.candidate.read`, but its authorization request labelled the operation with `authority.integrated`. That broader label was inconsistent with the Candidate command and retained decision domain, and weakened provenance inspection even though the required scope still denied unauthorized principals.

Correction:

- label both the unsigned authorization digest and typed authorization request with `authority.candidate`;
- retain the separately required `authority.candidate.read` scope;
- add a recording-authorizer regression that proves the exact required and security scopes; and
- leave Candidate reads non-mutating and separately authorised from admission.

### P2-13 — Candidate restart integrity did not independently bind chronology and command payload

The first schema-v9 restart pass rederived Candidate Version and decision canonical rows, but Candidate identity chronology and the exact command/event payload envelope were not independently reconstructed. A trigger-preserving attacker capable of re-digesting several retained rows could therefore try to reclassify the first decision, shift Candidate creation time or rebind the admission payload while keeping an internally consistent decision JSON.

Correction:

- require exactly one immutable Candidate Version and at least one ledger-linked decision for every Candidate identity;
- require the first ledger-ordered decision to be `ADMITTED` at the exact Candidate/Version creation time and every later decision to be `DEDUPLICATED`;
- reconstruct every decision outcome from ledger order rather than trusting the retained outcome column;
- bind the exact proposal command, inline payload, ledger event, aggregate version, security/retention/trust scopes, Retrieval Context, manifest, Candidate and Candidate Version;
- reject a missing decision/version join rather than silently omitting it from startup validation; and
- add trigger-restored raw-SQL regressions for normalized decision linkage, re-digested outcome changes, Candidate chronology changes and command-payload rebinding.

### P2-14 — Actual-service preparation supplied the fixture alias instead of its canonical identity

The public `Increment2PreparedAuthority` correctly requires the exact repository-owned fixture UUID retained by the retrieval contract. Unit composition used that canonical identity, while every authenticated actual-Neo4j case passed the human-readable alias `"integrated_fixture_v2"`. All nine service cases therefore failed before retrieval even though generation preparation itself was valid. Treating the alias as equivalent would have weakened the fixed fixture boundary.

Correction:

- pass the exact repository-owned `INTEGRATED_FIXTURE_V2_RETRIEVAL.fixture_id` from actual-service preparation;
- retain strict equality against the canonical fixture identity;
- add a unit regression proving the human-readable alias is rejected; and
- retain the exact nine authenticated service identities and zero-skip/failure gate unchanged.


## Validation performed

The current local source passed the focused Increment 2D proof, Candidate, migration and SDLC contract selection:

```text
126 passed, 9 intentional no-service skips, 0 failed
```

The complete deterministic repository lane passed through the fixed four-shard command:

```text
shard 1: 321 passed,  1 skipped
shard 2: 283 passed,  4 skipped
shard 3: 243 passed, 19 skipped
shard 4: 361 passed,  8 skipped
---------------------------------
total:   1,208 passed, 32 skipped, 0 failed
merged report outcomes: 1,240
required skips: 0
```

Additional checks passed:

- `python -m compileall -q newsroom scripts`;
- `git diff --check`; and
- clustering evaluation with `--fail-on-regression`.

The nine Increment 2D actual-service tests intentionally skip without the dedicated service-required environment. Their exact execution against authenticated Neo4j is a residual merge gate, not inferred from this deterministic result.

## Residual merge gates

This review closes the known local substantive P1/P2 findings but does not authorise merge. Issue #158 and its future focused PR remain unmerged until:

1. the corrected source, operations, traceability and this review record are published on the authorised branch;
2. the exact final head passes full CI, Authority A2a/A2b and Projection B1;
3. all nine required Increment 2D actual-Neo4j cases execute with zero skip, failure or error;
4. the signed SDLC route, core, service and final decision report `PASS` on that same head;
5. review submissions contain no requested changes and unresolved threads/comments are zero; and
6. parent #142 receives the final 2D merge and complete Increment 2 evidence before it is closed.

Do not begin Increment 3 until parent #142 is closed as completed on `main` and a fresh owner-authorised Increment 3 boundary records the then-current head.
