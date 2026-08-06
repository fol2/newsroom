# Increment 5B4 — bounded admitted-graph retriever

## Scope and identity

This record applies only to the independently attributable `ADMITTED_GRAPH`
branch delivered by Increment 5B4 / issue #308.

Fixed identities:

- retrieval contract: `sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c`;
- graph-query component: `sha256:98a92b1c46c08b614a0e15714a5cd071d49e916d6d2b45ead4924b194cf4525b`;
- graph profile: `increment5-admitted-graph-retrieval-v1`;
- graph policy: `increment5-admitted-graph-read-v1`;
- accepted trust scope: `ADMITTED` only.

This branch grants no identity, relationship, Candidate, evidence, operational,
production, publication or public-effect authority. It cannot activate a source,
model, provider, schedule, shadow, canary, Evidence Intake or publication.

## Fixed graph contract

The only accepted relationship predicates are:

- `ABOUT_EVENT`;
- `CORRECTS`;
- `DEVELOPMENT_OF`;
- `DISPUTES`;
- `SAME_EVENT_AS`;
- `SAME_PROCESS_AS`;
- `SUPERSEDES`; and
- `SUPPORTS`.

The only accepted projected node labels are `Source`, `Revision`, `Signal`,
`Lead`, `Hypothesis`, `Candidate`, `CanonicalEntity` and `FormalProcess`.

The fixed budgets are:

- maximum depth: `2`;
- maximum fan-out per frontier node: `32`;
- temporal observation window: `2,678,400` seconds;
- result limit: `8` plus a ninth overflow sentinel;
- cumulative timeout: `5,000` ms, including adapter-lock wait;
- response limit: `262,144` bytes;
- required open gaps: `0`;
- required dead letters: `0`;
- external/model/embedding/provider calls and provider spend: `0`.

## Request boundary

A caller supplies only one accepted canonical root and its exact relational
identity digest. The request also binds the actor, purpose, policy, retrieval
contract, graph component, relation contract, query-valid time, serving time,
minimum contiguous watermark and the exact fixed budgets.

The public request contains no Cypher, label, relationship type, predicate,
direction, property, depth, fan-out, order, limit, index, driver, session,
transaction or write field.

## Authority-owned Neo4j port

The retriever receives a private `AdmittedGraphReadPort` with exactly two
operations:

1. read one exact root in one exact generation; and
2. expand one sorted unique bounded frontier in one exact generation and time
   window.

`Neo4jAdmittedGraphReadPort` owns the Cypher bytes. Labels, relationship types,
direction, temporal predicates, ordering and absolute row limits are fixed in
repository code. The adapter opens read-mode sessions and executes immutable
queries with the remaining transaction timeout. Adapter-lock acquisition is
inside the same cumulative 5,000 ms budget.

No raw query, Neo4j driver, session, transaction, credential or write capability
crosses the port.

## Current-authority validation

Before projection reads can produce a complete result, the branch requires one
current authority view proving:

- one exact active complete generation;
- exact profile, graph component and relation contract identities;
- exact rights-manifest identity;
- a sufficient contiguous watermark;
- zero required gaps and zero dead letters;
- validation freshness within the fixed maximum age;
- one current accepted node authority record for the root and every endpoint;
- one current accepted relation authority record for every projected edge; and
- exact node identity/labels plus relation endpoint, predicate and temporal
  binding between Neo4j and authoritative records.

Neo4j remains a disposable generation-scoped projection. A projected path cannot
repair missing or contradictory SQLite/governed authority.

## Traversal and ordering

Traversal is a fixed two-phase breadth-first expansion. Every port response is
checked for generation isolation, requested-frontier scope, fixed predicates,
fan-out, record shape and authoritative binding. The branch rejects root
repetition and path cycles. Multiple paths to one endpoint retain the
lexicographically deterministic best path and record the other paths as
explicit duplicate exclusions.

Ordering is deterministic:

1. shorter path first;
2. then the ordered tuple of predicate, source, target, relation identity and
   direction for every hop; and
3. then endpoint canonical identity.

Graph proximity and path order are advisory. They establish no fact or identity.

## Rights, lifecycle, trust and time

Every node and relation must have current rights and `ACTIVE` lifecycle. Every
relation must have trust scope `ADMITTED`, be valid at query-valid time and have
an observation inside the fixed temporal window.

Held, unresolved, proposal-only, revoked, superseded, tombstoned, non-current
rights, unadmitted trust and temporally ineligible state cannot rank. Tombstoned
or revoked authority cannot be resurrected by an old projection or rebuild.

## Outcomes

The branch emits typed `COMPLETE`, `INCOMPLETE`, `POLICY_BLOCKED`, `STALE` or
`UNAVAILABLE` receipts. `NO_MATCH` is valid only after every mandatory contract,
authority, generation, rights, lifecycle, trust, freshness, watermark, gap,
dead-letter, root, projection, temporal and budget check succeeds.

A thirty-third edge for one frontier is `INCOMPLETE / FANOUT_EXCEEDED`. A ninth
distinct eligible endpoint is `INCOMPLETE / RESULT_LIMIT_EXCEEDED`. Neither is
silently truncated. Projection unavailability, malformed records, generation
crossing, missing authority and binding mismatch remain explicit and cannot be
represented as no match.

## Immutable journal

The non-authoritative SQLite journal stores only the idempotency key, request
digest, canonical receipt bytes and receipt digest. Initial lookup is read-only.
Authority production and Neo4j reads occur outside a SQLite write reservation.
A short first-writer-wins `BEGIN IMMEDIATE` transaction retains the completed
canonical receipt.

Restart replay returns byte-identical bytes. Semantic idempotency conflict,
retained-byte tamper, digest mismatch or request-binding conflict fails closed.
The journal creates no editorial or operational authority.

## Monitoring boundary

Until 5E operational admission, receipts support deterministic diagnosis of
contract, generation, watermark, gap, dead-letter, rights, lifecycle, trust,
root, projection, fan-out, cycle, duplicate, timeout, result and journal
failures. They do not establish system-level coverage, health, reconciliation,
containment, operational admission, production eligibility or publication
readiness.

## Rollback

1. stop callers from selecting the 5B4 graph profile;
2. retain historical request and receipt bytes for audit;
3. remove or revert the 5B4 product commit;
4. discard the affected Neo4j generation only after authority and retained
   evidence are safe;
5. retain SQLite/governed node and relation authority unchanged; and
6. return parent 5B to the completed exact/full-text/vector boundary.

Rebuilding a replacement graph generation never restores tombstoned, revoked,
non-current-rights, proposal-only or otherwise prohibited state.
