# Increment 4B substantive review — entity-resolution authority

**Issue:** #226
**Parent:** #144
**Authorised base:** `main@da65dbef7b8d6707555f820e7835aada64ed061f`
**Review status:** local current-tree review; exact remote-head qualification still required

## Review question

Does the Increment 4B implementation create a production-shaped, append-only and rights-safe entity-resolution authority without allowing extractor confidence, name equality, transliteration, proposal state or graph-private state to allocate or merge identity automatically?

## Review conclusion

At the current local review point, the implementation meets the 4B authority boundary:

- Entity Mentions bind exact retained Increment 4A Proposal and evidence lineage.
- Canonical Entity identity is stable and independent of names, locators, digests and graph IDs.
- English and Hong Kong Traditional Chinese aliases retain exact language, script, provenance and uncertainty.
- Same-name bilingual people remain separate because equivalence binds exact occurrence-level evidence, not text equality.
- Resolution Proposals remain separate from accept, reject, hold and unresolved decisions.
- Merge, split and reversal are append-only decisions over exact typed entity/version pairs.
- Materially unresolved identity blocks a dependent relation Proposal from later admission.
- Proposal, admitted and preferred-projection surfaces use distinct authorization scopes.
- Preferred identities are rebuildable from immutable heads and projection events without rerunning extraction.
- Current rights, source version and deletion state are revalidated before current use or rebuild.
- No Graphiti/model/network/Cypher/governed-Neo4j write surface enters the public entity authority.

The review found no P1 issue. Fourteen P2 findings identified during implementation were corrected and covered by focused tests. This document is not final merge evidence: the clean source must still be published to PR #236, receive exact-head workflow evidence and pass current-head review with zero actionable findings and unresolved threads.

## Corrected findings

### P2-01 — downstream entities could appear independently usable after one required Extraction Run passage was prohibited

The first current-use helper followed the mention's direct evidence range only. Increment 4A, however, defines a Run over all required passages. Treating another Proposal from the same immutable Run as independently usable after one required passage was revoked would create a new authority boundary that 4A never granted.

**Correction:** every mention now resolves and validates its exact retained Proposal Envelope through the 4A authority path. Current-use checks therefore revalidate the complete Run input binding. Rights revocation, tombstone and Source Definition Version change block every entity, alias, lineage decision, dependency and projection derived from that Run while preserving historical rows.

### P2-02 — separately sorted entity IDs and version IDs could silently cross-pair lineage

An early merge/reversal shape carried one sorted identity list and one separately sorted version list. Equal lengths do not prove each version belongs to the intended entity.

**Correction:** lineage requests and retained results carry explicit typed `EntityLineageVersion(entity_id, entity_version_id)` pairs. Canonical ordering sorts pairs, never their components independently. Store and SQLite checks verify each version belongs to its paired entity and is the exact current version.

### P2-03 — lineage commits omitted the authority recording timestamp

The first merge/split/reversal implementation called the inherited command commit helper without `recorded_at`, then used inconsistent timestamp conversion in later rows.

**Correction:** each lineage transaction captures one authority clock value, passes its canonical text to command/event persistence, and uses the same typed timestamp for all decision, version, head and projection rows in that transaction. Chronology remains separate from source and alias validity time.

### P2-04 — reversal restoration insertion conflicted with immediate foreign-key ordering

A restoration row referenced the new restored Entity Version before the version row could be inserted under the lineage trigger's required ordering.

**Correction:** the restoration foreign key is deferred inside the atomic transaction. Trigger and startup checks still require the exact restored entity/version pair before commit, so deferral changes ordering only and does not weaken lineage integrity.

### P2-05 — split authority needed proof of a complete, non-overlapping admitted-mention partition

A split that omitted an admitted mention, duplicated it or allocated an unrelated mention could create successors whose continuity was not reconstructable.

**Correction:** the split contract requires sorted unique allocations; the store derives every current admitted mention for the source entity and requires set equality with request allocations. SQLite guards verify each allocation targets one declared successor. Focused evidence covers complete partition, omission, unrelated mention, stale source version and replay.

### P2-06 — lineage descendants needed current-rights validation, not only creation-time validation

Merge and split successors have no independent source text. A naïve read could validate only their own lineage rows and miss prohibited predecessor provenance.

**Correction:** current entity use recursively resolves creation and lineage provenance back to admitted mention(s), exact 4A Proposal(s) and the complete Extraction Run. Merge successors, split successors, restored predecessors and retained lineage decisions all fail closed after rights revocation, tombstone or source-version change.

### P2-07 — projection rebuild could have become a resurrection or silent repair path

A generic rebuild that inserted current rows before validating all entities, or overwrote divergent rows, could partially restore prohibited material or hide tampering.

**Correction:** rebuild is a dedicated operational seam outside the public facade. It derives the complete expected projection, validates existing rows, revalidates rights for every entity before the first insert, inserts only missing rows in one transaction and creates no ledger/projection events. Divergent rows and any prohibited source cause atomic failure.

### P2-08 — the relation precondition was implicit and rejection could be mistaken for resolution

Without an explicit retained binding, Increment 4C could not prove which entity uncertainty materially affected a relation Proposal. Treating `REJECTED` as resolved would also unblock a relation without an admitted identity.

**Correction:** `EntityResolutionDependency` binds an exact retained `RELATION` Proposal digest to an exact current Resolution Proposal Version and records whether it is material. The guard blocks every material dependency unless the current state is exactly `ACCEPTED`; proposed, held, unresolved, rejected and reversed states remain blocking. Non-material dependencies remain traceable but do not block.

### P2-09 — projection events lacked one typed public reconstruction path

Projection events were validated through ad hoc dictionaries and had no bounded admitted-only stream for later projectors.

**Correction:** `EntityProjectionEvent` is a typed admitted contract with exact source event/ledger sequence, action, entity/version, preferred identity, lifecycle and canonical digest. Startup, rebuild and public `projection_events_after` use the same decoder. The stream is ordered, cutoff-based, finite and protected by the projection read scope.

### P2-10 — startup integrity needed direct evidence for lineage and derivative tampering

Schema triggers prevented normal mutation, but the first suite did not prove checked reopen would detect trigger-bypassed changes to dependency, projection and typed-event coverage.

**Correction:** focused raw-SQL tests drop and restore individual guards, then prove reopen rejects request/canonical mismatch, missing projection-event coverage, divergent preferred identity and a ledger event whose typed dependency record was removed. Direct updates to merge, split, reversal, dependency and projection rows are rejected by immutable triggers.

### P2-11 — safe representations exposed retained source expression

Default dataclass representations included mention and alias text. Logs, assertion failures or debug traces could therefore disclose retained source expression outside an intentional read surface.

**Correction:** mention request normalised text, retained mention text/normalised text and alias text/normalised text are `repr=False`. Canonical persistence and explicit typed reads remain unchanged. Security evidence proves English source expression is absent from safe mention, alias and proposal representations.

### P2-12 — concurrent identical decisions could return stale instead of exact replay

Two threads could be authorised before either committed. After the first decision committed, the second entered the serialized store with an unmarked grant and hit the decision-head stale check even when its idempotency namespace/key and payload were identical.

**Correction:** decision persistence checks/commits the idempotency record at the start of the same transaction. An existing exact command returns the retained typed decision with `replayed=True`; an incompatible concurrent command writes nothing and receives a typed stale conflict. Evidence proves one decision row, one durable result and one exact replay.

### P2-13 — identical bilingual names could be cross-paired by placeholder equality

The first equivalence guard required the source Proposal's English and Traditional Chinese placeholder set to equal the two retained mention texts. In a same-name fixture, that condition is true for multiple distinct people and therefore did not prove which occurrence pair the extractor proposed.

**Correction:** the deterministic fixture contract now includes a separately versioned bilingual homonym case with two same-name people in distinct organisational contexts. Every mention and equivalence Proposal binds exact byte occurrences. Resolution proposal admission requires the equivalence source's two evidence ranges to equal the exact retained evidence ranges of the selected mentions, so a crossed pair fails closed even when both languages and normalised names are identical. Focused evidence then admits two separate Canonical Entities, adds the correct bilingual alias to each only after explicit acceptance, and proves neither identity is silently merged.

### P2-14 — permanent focused workflows did not directly select 4B authority evidence

The repository-wide CI suite would execute the new tests, but the permanent Authority A2a, Authority A2b and Projection B1 workflows select filename-specific inventories. Without dedicated bridge files, those focused gates could pass while exercising only predecessor authority.

**Correction:** `test_authority_a2a_entity.py` verifies exact authenticated command and ledger-event envelopes for mention, proposal and decision authority; `test_authority_a2b_entity.py` proves current reads recheck complete extraction rights after governed-object revocation while immutable entity rows remain; and `test_projection_b1_entity.py` proves proposed identity emits no projection event while acceptance emits exactly one admitted typed event. These files are selected automatically by the existing permanent workflow globs. Actual Neo4j entity projection remains deferred to 4E.

## Authority and runtime boundary review

The current implementation has no import or public callable surface for:

```text
Graphiti or a model-provider SDK
network access, source credentials or schedules
arbitrary SQL/Cypher or governed Neo4j writes
caller-selected graph labels or graph-internal IDs
editorial predicate registration or relation admission decisions
Candidate or Evidence Intake writes
publication, spending, shadow, canary or production activation
legacy mutable link/event/cluster identity import or dual write
```

The entity normaliser performs only NFC, whitespace collapse and case-folding. It does not translate, transliterate, fuzzy match, embed or infer identity. Bilingual equivalence still requires an explicit accepted decision against an already admitted identity.

## Current local evidence

```text
Dedicated Increment 4B entity-authority tests:                         57 passed
Inherited 4A extraction contracts/output/migration regression:         28 passed
Permanent A2a/A2b/Projection B1 entity bridges:                         3 passed
Combined focused qualification:                                         88 passed
Focused required skips:                                                   0
Focused failures/errors:                                                  0
Compile and diff checks:                                                pass
Fresh schema v14 and checked v13-to-v14 migration:                     pass
Rights revocation, tombstone and source-version blocking:              pass
Merge, split, reversal and exact replay:                                pass
Dependency guard state transitions and rights checks:                   pass
Projection-event stream and rights-safe rebuild:                        pass
Same-name bilingual false-merge and occurrence binding:                 pass
Security, forged-authorizer and read-scope isolation:                   pass
Raw-SQL tamper and startup integrity:                                   pass
```

The 57-test entity inventory executes every `test_entity_4b_*.py` file, including bilingual same-name, security, concurrency, lineage, dependency, projection-rebuild, integrity and traceability evidence. The 28 inherited tests execute the 4A extraction contract/output-schema suite and checked migration regression with `ResourceWarning` promoted to an error. The three permanent-lane bridge tests extend that inventory to one 88-test local review qualification with no skip, failure or error. This remains local review evidence rather than a substitute for permanent exact-head workflows.

A complete serial repository run was attempted in the constrained execution environment but reached the local five-minute process ceiling during service-heavy files without reporting a test failure. Final complete-inventory evidence must therefore come from the normal pinned CI and signed SDLC workflows on the exact clean PR head rather than being inferred from that interrupted local run.

## Review disposition

```text
P1 findings:             0
P2 findings corrected:  14
Unresolved P1/P2:        0 on the current local reviewed tree
Review threads:          pending current remote-head audit
Exact-head workflows:    pending final clean publication
```

Before PR #236 may merge, the same clean source tree must be durably present on the PR branch, all permanent workflows must pass on that exact head, the signed SDLC decision must be `PASS`, and current-head review must retain zero actionable comments, review blockers and unresolved threads.

Issue #227 remains blocked. Neither this review nor completion of entity-resolution authority authorises relation admission, real Graphiti/model execution, Graphiti workspace integration, actual-Neo4j bilingual proof or any production/public effect.
