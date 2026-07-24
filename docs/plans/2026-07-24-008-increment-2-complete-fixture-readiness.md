# Increment 2 complete-fixture implementation readiness

**Status:** Proposed — owner review required  
**Owner:** Product owner  
**Prepared:** 2026-07-24  
**Canonical language:** English  
**Base:** `main@843f6baddd3bf44a0f993c3f2e54df6d4746a059`  
**Parent programme:** [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md), Increment 2  
**Completed dependency:** issue #79 / Increment 1  
**Accepted specifications:** [`../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md), [`../specs/editorial-automation/graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md), [`../specs/editorial-automation/discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md), [`../specs/editorial-automation/discovery-triage-and-event-grouping.md`](../specs/editorial-automation/discovery-triage-and-event-grouping.md), and [`../specs/editorial-automation/discovery-workflow.md`](../specs/editorial-automation/discovery-workflow.md)  
**Architecture decisions:** ADR 0001, ADR 0002, ADR 0004 and ADR 0005  
**Implementation authority:** None. Merging or accepting this document does not start code, Neo4j, Graphiti, an embedding or model call, source access, spending, shadow, canary or production. A separate owner-authorised implementation issue and exact-head review remain required.

## 1. Decision requested

Approve Increment 2 as the next implementation boundary and authorise focused code work only after this readiness package is accepted.

Increment 2 closes the deliberate gap between Increment 1C and the first complete graph-native fixture slice. Increment 1C proved authenticated SQLite and governed-object authority, structural Neo4j projection, authoritative hydration, exact structural retrieval and deterministic Candidate admission. It also retained exact negative evidence that no full-text, vector, Graphiti, model, embedding or live-source retrieval executed.

Increment 2 adds the smallest production-shaped, deterministic and actual-Neo4j path that proves:

```text
synthetic Source Revisions
→ canonical ordered events and governed objects
→ deterministic structure plus one governed editorial relation
→ Neo4j structural, full-text and vector projection
→ bounded exact/full-text/vector/graph retrieval
→ deterministic fusion and dependency-aware deduplication
→ authoritative passage hydration
→ trust-labelled Retrieval Context
→ deterministic SQLite-authoritative Candidate admission
```

The complete-slice proof has no graph-free, missing-index or ungoverned-relation passing variant.

## 2. Fixed authority and safety boundaries

1. SQLite ledger records, immutable decisions, governed objects, Retrieval Contexts and Candidate records remain authoritative.
2. Neo4j structural, full-text and vector data remain disposable, rebuildable projections.
3. A model, embedding score, full-text rank, graph path or fusion score cannot allocate identity, admit a relation or commit a Candidate.
4. The factual bytes used by triage or Candidate admission are rehydrated from governed authority, not trusted from Neo4j.
5. Editorially meaningful relationships are reified proposals and admission decisions. They are not ordinary ungoverned graph edges.
6. The public surface exposes typed commands and one bounded named read tool. It exposes no driver, arbitrary Cypher, caller-selected labels, unrestricted predicates or graph-write authority.
7. Graph, full-text or vector unavailability, staleness or gaps never become `no prior match`.
8. Rights revocation, deletion and tombstones propagate to every derivative and prevent resurrection after rebuild.
9. Production profiles reject the fixture-only vector and extraction contracts defined here.
10. This increment contains no live RSS, JSON, search, Brave, GDELT or other source execution; no Graphiti execution; no external model or embedding call; no publication target; no scheduler; no shadow, canary, activation, spending or public effect.

## 3. Normative requirement boundary

The implementation PRs must identify the exact requirements they satisfy. The minimum intended boundary is:

- `DREC-001`–`DREC-007`, `DREC-030`–`DREC-057` and `DREC-070`–`DREC-077`;
- `FLOW-050`–`FLOW-065`, `FLOW-080`–`FLOW-092` and `FLOW-100`–`FLOW-101`;
- `TRI-020`–`TRI-028`, `TRI-040`–`TRI-058` and applicable proposal-validation requirements;
- `GRAG-010`–`GRAG-016`, `GRAG-020`–`GRAG-035` and `GRAG-040`–`GRAG-046`;
- `GRPROD-013`–`GRPROD-016` and `GRPROD-020`–`GRPROD-024`;
- ADR 0001, ADR 0002 and ADR 0005.

Increment 2 does not claim full implementation of source collection, extraction, entity resolution, triage, Evidence Intake, evaluation or operational admission.

## 4. Exact synthetic fixture family

The implementation uses a rights-free repository-owned fixture family named `integrated_fixture_v2`. It contains no copied news expression and no personal data.

### 4.1 Prior state

The fixture records:

- one maintained-document Source Item;
- Source Revision 1 describing a synthetic formal process with canonical process identifier `SYN-PROC-2042`;
- English and Hong Kong Traditional Chinese aliases retained as attributed fixture fields;
- one admitted prior Event Hypothesis Version and Candidate Version representing the initial process state;
- exact permitted passages stored through governed-object authority; and
- deterministic structural lineage from Source Definition Version through Candidate Version.

### 4.2 New state

Source Revision 2 changes one material effective deadline and instruction for the same formal process. It creates a new Signal and Lead lineage and is expected to retrieve the prior Candidate as a likely development context.

### 4.3 Governed relation

A deterministic repository-owned fixture rule creates one immutable Relation Proposal:

```text
new Event Hypothesis Version
DEVELOPMENT_OF
prior Event Hypothesis Version
```

A separate authenticated admission command admits the exact proposal for the fixture purpose. The proposal, evidence references, temporal scope, rule version and decision remain authoritative in SQLite. Only the admitted assertion is projected on the admitted retrieval surface.

### 4.4 Distractors and negative cases

The fixture also contains:

- a similarly named but distinct process in a different jurisdiction and year;
- an unadmitted `SAME_EVENT_AS` proposal that must remain absent from the admitted surface;
- a lexically similar passage with an incompatible formal identifier;
- a vector-near passage that lacks compatible time and process lineage; and
- one deleted/tombstoned passage that must not return or reappear after rebuild.

The expected result set and exclusions are committed as canonical fixture data before implementation tests are written.

## 5. Increment 2 contract choices

These choices are scoped to the deterministic fixture proof and do not select final production thresholds or providers.

### 5.1 Index contracts

One complete projection generation binds exact identities for:

- ontology and structural projector;
- admitted-relation projector;
- full-text normalisation and index contract;
- vector fixture contract;
- projection mapping;
- retrieval and fusion policy; and
- expected fixture manifest.

A material change creates a new isolated generation. Validation must reconcile expected and actual nodes, admitted relations, full-text documents, vector documents, dimensions, digests, trust scopes and tombstones before atomic promotion.

### 5.2 Full-text fixture contract

`fixture_fulltext_v1` projects a repository-normalised retrieval field from exact permitted fixture passages. The implementation must pin the actual Neo4j full-text configuration supported by the qualified Neo4j release and prove compatibility in the actual-service lane. Query text is parameterised and passed only through the private adapter.

### 5.3 Vector fixture contract

`fixture_vector_v1` uses repository-committed deterministic vectors:

- fixed dimension: 16;
- fixed finite numeric values;
- cosine similarity;
- exact vector digest retained in authority;
- no external embedding provider or model call; and
- explicit rejection in evaluation and production profiles.

The vector index and vector query path are real Neo4j operations even though vector production is deterministic fixture data.

### 5.4 Named retrieval tool

The initial named tool is:

`find_related_event_candidates`

Its fixture policy fixes:

- accepted purpose: development-context retrieval;
- allowed identity and relation types;
- trust scopes: deterministic structural and exact admitted relations only;
- graph depth: at most 2;
- relation fan-out: at most 32;
- exact, full-text and vector branch result cap: 8 each;
- total retained candidate cap: 12;
- one declared query-valid time and one serving time;
- required ACTIVE generation and contiguous watermark;
- zero unresolved required gaps and zero dead letters;
- timeout and response-size bounds; and
- mandatory provenance and hydration fields.

These are fixture qualification values, not production objectives.

### 5.5 Deterministic fusion

`hybrid_fixture_fusion_v1` performs:

1. exact identity and explicit-lineage retrieval;
2. admitted graph traversal;
3. full-text retrieval;
4. vector retrieval;
5. canonical-ID deduplication;
6. reciprocal-rank fusion with fixed `k = 60` and equal branch weights; and
7. deterministic canonical-ID tie-break.

Every retained candidate records contributing branches, branch ranks, raw mode metadata, fusion version and exclusion reason where applicable. Fusion orders context only. It cannot establish relationship or Candidate authority.

### 5.6 Authoritative hydration

Every retained factual passage is hydrated from the exact governed-object admission and immutable blob identity. The Retrieval Context records the complete access decision, policy contract, byte range, digest, rights state, lifecycle state, query identity, projection metadata and serving time.

A result that cannot be fully and currently hydrated is excluded or blocks the complete fixture result according to the fixed policy. It is never silently replaced by graph properties or a search-like snippet.

## 6. Dependency-ordered review units

These are review and merge boundaries inside one Increment 2. They are not independently activatable product stages.

### 2A — Governed relation authority and fixture schema

Deliver:

- typed Relation Proposal, Relation Admission Decision and admitted assertion records;
- checked SQLite migration and startup integrity;
- authenticated proposal and admission commands;
- exact subject, object, predicate, temporal scope, provenance and evidence references;
- immutable rejection, hold, revocation and supersession semantics;
- deterministic fixture rule through the same public interface later used by Graphiti proposals;
- structural and admitted-relation projection mapping;
- proposal-only surface separation; and
- traceability, adversarial tests and rollback.

Exit evidence:

- an unadmitted proposal never appears on the admitted surface;
- admission cannot be inferred from confidence or graph state;
- replay is idempotent;
- tampered cross-record identity fails store open;
- revocation removes the admitted derivative without deleting history; and
- no Graphiti or model execution occurs.

### 2B — Full-text and vector projection foundation

Depends on 2A.

Deliver:

- versioned full-text and vector index contracts;
- deterministic fixture vector admission;
- index-aware projection generation, checkpoint, gap, validation and promotion state;
- private parameterised Neo4j index create, write, read and cleanup operations;
- expected/actual index reconciliation;
- rights-safe purge and rebuild;
- wrong-dimension, non-finite, digest-conflict and wrong-generation rejection;
- actual-Neo4j compatibility tests; and
- production-profile rejection of fixture-only contracts.

Exit evidence:

- actual full-text and vector queries execute;
- graph or index deletion loses no authority;
- replacement generation restores exact state from SQLite and governed objects;
- rebuild reruns no stochastic extraction or embedding;
- tombstoned material does not return; and
- a missing mandatory index cannot qualify the generation.

### 2C — Bounded hybrid retrieval and authoritative context

Depends on 2B.

Deliver:

- `find_related_event_candidates` typed request and response;
- exact, graph, full-text and vector retrieval branches;
- deterministic fusion and dependency-aware deduplication;
- authoritative hydration;
- trust-labelled Retrieval Context version 2;
- query, branch, fusion, limit, watermark, generation, gap and serving metadata;
- explicit unavailable, stale, incomplete and policy-blocked outcomes;
- no arbitrary Cypher or public driver surface; and
- negative and adversarial tests for caller-selected scope, truncation and injection.

Exit evidence:

- all four branches execute exactly once in the required fixture case;
- the correct prior Candidate is retained;
- the distinct distractor remains distinct;
- the unadmitted relation remains absent;
- no graph/index failure becomes `REL_NO_ADEQUATE_PRIOR_MATCH`;
- every factual passage is rehydrated from authority; and
- fusion score remains non-authoritative.

### 2D — Complete actual-Neo4j fixture proof

Depends on 2C.

Extend the integrated proof through:

```text
fixture authority
→ relation proposal and admission
→ complete structural/full-text/vector rebuild
→ validation and ACTIVE promotion
→ bounded hybrid retrieval
→ governed hydration
→ retained trust-labelled context
→ deterministic development-Candidate admission
```

The permanent actual-service case must prove:

- exact initial admission and exact replay;
- all required retrieval modes executed;
- admitted relation contribution and unadmitted proposal exclusion;
- complete expected/actual generation reconciliation;
- graph loss, full-text loss and vector loss fail closed;
- unresolved required gap blocks complete context;
- replacement-generation recovery from authority only;
- restart revalidates retained context and Candidate records;
- equivalent replay or recovery deduplicates deterministically;
- relation revocation changes later context without rewriting history;
- governed deletion purges every derivative;
- tombstone non-resurrection after rebuild; and
- no graph-free or missing-index passing variant exists.

## 7. Test and evidence topology

Every review unit includes applicable:

- unit and property tests for typed identity, canonicalisation and finite bounds;
- checked-migration and raw-SQL tamper/reopen tests;
- authority, authentication and authorisation tests;
- projection, checkpoint, gap, dead-letter and generation tests;
- actual Neo4j structural, full-text and vector tests;
- replay, crash, restart, deletion and rebuild tests;
- query security, truncation and provenance tests;
- traceability and documentation-contract tests;
- full repository CI and clustering regression; and
- SDLC v2 exact-head evidence.

The permanent actual-service workflow may extend `.github/workflows/projection-b2-neo4j.yml` only when the resulting gate remains bounded, exact-head, credential-isolated and truthful. A separate service workflow is permitted if the accepted budget or evidence topology requires it.

Before each merge:

1. all required gates pass for the exact reviewed head;
2. actual-service evidence proves required cases executed without skip;
3. current-head substantive review records zero unresolved P1/P2 findings;
4. unresolved review threads and actionable PR comments are zero;
5. temporary qualification transport is removed or closed without merge;
6. requirements, exclusions, deferrals and rollback are updated; and
7. CI is treated as regression evidence rather than owner approval.

## 8. Definition of done

Increment 2 closes only when:

1. one editorial relation is governed by immutable proposal and admission authority;
2. structural, admitted-relation, full-text and vector derivatives share one validated complete generation contract;
3. actual Neo4j full-text and vector indexes execute through the private adapter;
4. exact, graph, full-text and vector branches execute in one retained query;
5. deterministic fusion and canonical dependency-aware deduplication are versioned and inspectable;
6. exact permitted passages are hydrated from governed authority;
7. every context item carries trust, provenance and temporal metadata;
8. watermark, projector, ontology, generation, index contracts, gap and serving state are retained;
9. Candidate admission remains SQLite-authoritative and relation/rank/similarity non-authoritative;
10. graph or index unavailability never becomes no match;
11. no graph-free, missing-index or unadmitted-relation variant passes;
12. rebuild, restart, revocation, deletion, purge and tombstone tests pass;
13. no live source, Graphiti, external model or embedding call occurs;
14. all exact-head gates and actual-service cases pass; and
15. operations, traceability, exclusions and rollback records are merged.

## 9. Explicit exclusions and deferred work

Excluded from Increment 2:

- live source access and named source configuration;
- Graphiti runtime execution;
- external model, prompt or embedding selection;
- production protected-content vector generation;
- complete entity resolution, merge, split or reversal;
- general editorial relation admission beyond the exact generic contract and fixture;
- production retrieval thresholds, latency or capacity objectives;
- full Triage Work Items and worker execution;
- Evidence Intake transport;
- scheduler and Operational Profiles;
- evaluation shadow, canary, activation and legacy retirement;
- spending and public effect.

Deferred to later increments:

- generic source adapters and discovery lineage — Increment 3;
- Graphiti, entity resolution and full relation admission — Increment 4;
- production embedding, hybrid thresholds and complete named tools — Increment 5;
- full triage, Hypotheses, Candidates and Handoff — Increment 6;
- Agenda, bounded search and Event-Scoped Local Watch — Increment 7;
- evaluation, operations, backup, security and readiness — Increment 8;
- production-equivalent shadow — Increment 9;
- governed Evidence Intake canary — Increment 10; and
- activation and legacy retirement — Increment 11.

## 10. Rollback

Each review unit is independently revertible. Rollback removes the new source, migration, workflow, documentation and test unit and deletes only disposable fixture graph/index generations. It never reconstructs authority from Neo4j, reruns stochastic extraction, restores deleted material from projections or changes production state.

A forward fix creates a new generation, rebuilds from verified retained authority, validates all mandatory derivatives and promotes atomically. Retired or failed generations are not directly reactivated.

## 11. Stop boundary

Do not begin Increment 3 implementation merely because an Increment 2 branch exists or individual review units merge. Increment 3 begins only after:

- all Increment 2 review units are merged;
- the Increment 2 epic is closed as completed;
- exact completion evidence and deferred work are recorded on `main`; and
- a fresh-session implementation issue confirms the current head and accepted Increment 3 readiness boundary.
