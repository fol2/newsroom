# Increment 5C2 — six bounded named read-only tools

## Scope

Increment 5C2 executes exactly the six request contracts admitted by 5C1:

1. `EXACT_AUTHORITY_LOOKUP`;
2. `BOUNDED_FULL_TEXT_RETRIEVAL`;
3. `BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL`;
4. `BOUNDED_ADMITTED_GRAPH_TRAVERSAL`;
5. `CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP`; and
6. `BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP`.

The first four tools use typed adapters over the accepted Increment 5B
retrievers. The last two use fixed read-only SQLite authority ports. The common
dispatcher selects a route only from the closed `NamedToolId` inventory; request
or source content cannot select a backend, port, query language, index,
predicate, callback or write surface.

This boundary is tool-local. It does not combine results from more than one
tool, perform dependency-root deduplication, construct a complete Retrieval
Context, create or mutate a Hypothesis or Candidate, call a provider or model,
collect a live source, publish, or authorise production activation.

## Call sequence

Every call follows one fixed sequence:

1. decode one strict typed 5C1 request;
2. obtain one immutable 5C1 authorization receipt;
3. bind request, authorization and the exact dispatcher registry;
4. route by the request's typed `NamedToolId`;
5. invoke exactly one registered branch or authority port;
6. retain the exact route-execution receipt and raw upstream receipt bytes;
7. emit one common dispatch receipt; and
8. retain all three receipt layers in first-writer-wins journals.

A blocked or stale authorization is evaluated before any branch or authority
port call. It returns no port identity and no upstream bytes. This prevents an
unauthorised caller from using the tool surface to test whether a configured
object, source, index, graph root or collision exists.

## Four retrieval-backed tools

### Exact authority lookup

The exact adapter translates only the closed exact lookup kinds into an
`ExactBranchRequest`. It binds the reviewed actor, purpose, policy, authority
scope and minimum ledger sequence. The adapter returns the exact underlying
request and receipt identities, authority watermark, component identities and
exclusions without broadening the query.

### Bounded full-text retrieval

The full-text adapter sends the query as data to the fixed full-text retriever.
Language and source scope remain separate typed fields. Named `source_ids` are
sorted, bounded, included in the branch request digest and enforced by the
fixed parameterised Neo4j query; they are neither appended to Lucene text nor
silently ignored.

### Deterministic fixture-vector retrieval

The vector adapter accepts only a repository-owned fixture/replay query identity
and digest. It does not accept arbitrary vectors, embedding models, providers or
credentials. The retained receipt binds the catalogue, profile, generation,
watermark and deterministic component identities.

### Bounded admitted-graph traversal

The graph adapter binds the reviewed profile, component, allow-listed relation
identities, root identity, depth, fan-out, temporal window, timeout and minimum
watermark. It invokes the typed admitted-graph retriever and retains exact graph
receipt metadata. It exposes no raw Cypher and no graph write credential.

## Two authority-backed tools

Both authority ports open SQLite with `mode=ro`, set `query_only=ON` and
`trusted_schema=OFF`, use one read snapshot, install a write-denying SQLite
authorizer and execute only repository-owned parameterised statements. The
hard timeout is 5,000 ms. A schema, integrity, timestamp, rights or result-bound
problem is explicit and is never converted to `NO_MATCH`.

### Current collision and authority metadata lookup

The collision tool checks the exact current relational collision digest in the
`candidate-development` namespace and returns current metadata for the named
object-admission and passage identities. Usability requires all of the
following at serving time:

- current admission lifecycle is `ACTIVE`;
- current blob lifecycle is `ACTIVE` with verified integrity;
- the current rights decision is allowed;
- admission and rights validity intervals contain serving time; and
- admission, rights, access-decision and passage metadata agree exactly.

Missing object and passage identities are explicit. Ambiguous passage identity
is an integrity failure. The tool returns metadata and receipt identities only;
it deliberately does not return factual object or passage bytes. Exact content
loading remains the 5D authoritative hydration boundary.

### Bounded source/revision impact lookup

The impact tool binds an exact source identity, optional exact revision,
`[window_start, window_end)` interval, lineage depth one or two and the explicit
`include_superseded` flag. Depth one returns revision records. Depth two may
also return representations and source occurrences. When superseded records
are excluded, a revision with a successor is not returned. The query reads at
most `result_limit + 1` rows so an excessive result set becomes `INCOMPLETE`
rather than silent truncation.

## Bounds and outcomes

The 5C1 hard maxima remain authoritative:

- eight results;
- 5,000 ms;
- 262,144 caller-response or raw upstream-receipt bytes;
- graph depth two;
- graph fan-out 32; and
- temporal window 2,678,400 seconds.

Every route and common receipt uses one of:

- `COMPLETE`;
- `INCOMPLETE`;
- `POLICY_BLOCKED`;
- `STALE`; or
- `UNAVAILABLE`.

`NO_MATCH` is permitted only after a complete route execution with a retained
upstream receipt. A route that was not executed cannot claim complete
no-match. A low caller payload limit does not discard internal audit receipts;
the call instead returns an explicit response-bound outcome while the exact
upstream bytes remain retained outside the caller payload.

## Receipt chain

A completed or degraded call retains:

1. the 5C1 authorization receipt;
2. the typed branch or authority execution receipt;
3. the exact raw Increment 5B branch receipt or fixed authority receipt, when a
   port executed; and
4. the common six-tool dispatch receipt.

The common receipt binds the request and envelope digests, authorization
receipt and decision, dispatcher and child-registry digests, route, mode, port,
child execution identity, child receipt digest, upstream receipt digest,
outcome, reason, bounds and execution flags. It mirrors the child receipt
exactly and grants no authority.

The non-authoritative SQLite journals retain canonical bytes and digests only.
They use first-writer-wins idempotency, return byte-identical replay after
restart, reject semantic idempotency conflicts and fail closed on common,
child, or upstream receipt tamper. Branch or authority work occurs outside the
common journal's short write reservation.

## Security and non-effects

All six tools are read-only. The surface contains no unrestricted SQL, Cypher,
Lucene, graph mutation, arbitrary index, dynamic predicate, generic store
callback, model or provider call. Request content cannot change actor, grant,
purpose, scope, policy, contract, generation, route, port, budget, outcome,
authority effect or activation state.

Every authorization, route and common receipt fixes all external, provider,
model and embedding call counters and spend to exact integer zero, fixes
`authority_effect=NONE`, grants no qualification authority and grants no
production activation authority.

Complete operational policy, credentials, egress and Operational Admission
remain Increment 8/#148 responsibilities. 5C2 claims no `DOPS-*` delivery.

## Monitoring and recovery

Operational inspection at this boundary is receipt-based:

- compare request, authorization, child and common receipt digests;
- inspect route outcome and reason;
- inspect exact component, profile, generation and watermark attribution;
- distinguish no-match from stale, blocked, incomplete and unavailable; and
- verify zero external work and zero authority effect.

To recover or roll back:

1. stop accepting the 5C named-tool profile or revoke affected grants;
2. retain all historical authorization, route and common receipts;
3. revert the 5C2 product commits to the accepted 5C1 boundary;
4. rebuild read-only projections or authority databases under their owning
   contracts when required; and
5. rerun the affected focused, service and immutable-replay evidence.

Rollback creates no Candidate, publication or activation side effect because
5C2 owns none.
