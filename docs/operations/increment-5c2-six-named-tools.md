# Increment 5C2 — six bounded named read-only tools

## Scope

This operating record covers the complete tool-local Increment 5C execution
boundary. It joins the accepted 5C1 request and local authorization contract to
exactly six reviewed read-only tools:

1. `EXACT_AUTHORITY_LOOKUP`;
2. `BOUNDED_FULL_TEXT_RETRIEVAL`;
3. `BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL`;
4. `BOUNDED_ADMITTED_GRAPH_TRAVERSAL`;
5. `CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP`; and
6. `BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP`.

The first four tools route through independently attributable 5B retrievers. The
last two route through fixed read-only SQLite authority ports. The dispatcher
covers the six-tool inventory exactly and has no generic fallback route.

5C2 does not fuse tools, deduplicate dependency roots across tools, construct a
complete Retrieval Context, return factual object bytes, create or change a
Hypothesis or Candidate, call a provider or model, access a live source,
publish, or activate production. Those boundaries remain with 5D, Increment 6,
or Increment 8 as assigned by the accepted ownership map.

## Call sequence

Every invocation follows one closed sequence:

1. decode one strict typed 5C1 request;
2. verify one immutable 5C1 local authorization receipt;
3. bind request, authorization and exact registry identities;
4. select the route solely from the typed `NamedToolId`;
5. execute exactly one registered branch or authority port;
6. validate and retain the complete canonical upstream receipt;
7. emit one normalized dispatch receipt; and
8. retain the dispatch and upstream evidence in a non-authoritative,
   first-writer-wins journal.

A blocked or stale authorization is evaluated before any port lookup or read.
It therefore reveals neither whether a requested identity exists nor which
backend could have served it.

## Closed routing

### Branch-backed tools

- `EXACT_AUTHORITY_LOOKUP` translates to one fixed `ExactBranchRequest` and
  invokes `SQLiteExactRetriever`.
- `BOUNDED_FULL_TEXT_RETRIEVAL` translates to one fixed
  `FullTextBranchRequest` and invokes `FullTextRetriever` through the owned
  Neo4j full-text authority port.
- `BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL` translates to one admitted fixture or
  replay `VectorBranchRequest` and invokes `VectorFixtureRetriever`; callers
  cannot supply arbitrary vectors, embedding models or providers.
- `BOUNDED_ADMITTED_GRAPH_TRAVERSAL` translates to one fixed
  `AdmittedGraphRequest` and invokes `AdmittedGraphRetriever`; callers cannot
  supply Cypher, labels, predicates, directions or write operations.

Every branch result retains the exact translated request digest, upstream
receipt digest, branch profile and generation identities, component digests,
query-valid and serving times, and complete canonical upstream receipt bytes.

### Authority-backed tools

- `CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP` reads one current candidate
  collision state and current metadata for explicitly named authority objects
  and passages. It revalidates lifecycle, rights decision, rights validity,
  access decision and byte-range bindings. It returns metadata and exact
  identities only; factual bytes and complete hydration remain 5D.
- `BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP` reads one exact source definition,
  optional revision, bounded validity window, lineage depth and supersession
  choice. It returns deterministic revision, representation and occurrence
  metadata through fixed parameterized statements.

Both authority ports open SQLite in URI `mode=ro`, set `query_only=ON` and
`trusted_schema=OFF`, install a write-denying authorizer, and execute inside one
read snapshot. No caller-provided SQL or generic store callback exists.

Source-impact reads close the observation window at the exact query-valid time.
A source definition must already be recorded; revisions must be both observed
and recorded; representations must be both produced and recorded; and
occurrences must be both observed and recorded no later than that cutoff. A
successor observed or recorded after the cutoff cannot retrospectively hide a
revision that was current at the requested time.

## Bounds

The common request maxima remain:

- 8 returned results;
- 5,000 ms total tool timeout;
- 262,144 bytes global raw upstream-receipt bound;
- caller-declared response payload bound between 1,024 and 262,144 bytes;
- graph depth 2, fan-out 32 and temporal window 2,678,400 seconds; and
- at most 8 sorted unique source identities.

A source-scoped full-text request scans at most 65 deterministically ordered
Neo4j candidates. All candidates inside that bounded scan are returned to the
authority layer before source filtering. This prevents a lower-ranked in-scope
match from being lost behind higher-ranked out-of-scope candidates. Reaching the
65-candidate scan sentinel is `INCOMPLETE / SOURCE_SCOPE_SCAN_BOUND_EXCEEDED`,
never `NO_MATCH`.

The result limit is applied to authority-confirmed in-scope candidates. More
than eight such candidates is `INCOMPLETE / RESULT_LIMIT_EXCEEDED`; no ninth hit
is silently truncated into a complete response.

## Outcomes

Every layer uses the same five truthful outcome classes:

- `COMPLETE`;
- `INCOMPLETE`;
- `POLICY_BLOCKED`;
- `STALE`; and
- `UNAVAILABLE`.

`NO_MATCH` is valid only when the selected port completed its bounded work,
retained an independently attributable receipt, and found zero permitted
results. A timeout, missing schema or index, stale watermark or generation,
rights block, scan overflow, result overflow, malformed upstream receipt or
unavailable port cannot become `NO_MATCH`.

## Receipt and audit boundary

The caller-facing evidence is the bounded typed dispatch outcome and its
canonical identity. The execution and dispatch result objects additionally
retain canonical upstream receipt bytes for replay, tamper detection and audit.
Those raw bytes are **internal audit evidence, not caller response payload**.
They must not be serialized to an agent, model or external caller merely because
they are present on an internal result object.

A caller payload bound can therefore produce
`INCOMPLETE / RESPONSE_LIMIT_EXCEEDED` while the internal journal still retains
the exact oversized upstream receipt needed to prove what happened. The journal
stores no authoritative identity, relationship, Candidate, evidence,
publication or activation decision.

Every journal verifies canonical bytes and digests on replay, rejects duplicate
JSON keys and scalar type confusion, rejects semantic idempotency conflicts,
and returns byte-identical retained receipts after restart. Branch or authority
work occurs outside the short SQLite write reservation.

## Security boundary

Request and source content remain data. They cannot select another tool, route,
port, backend, index, query language, callable, credential, destination, write
surface, budget, authority effect or activation state.

All 5C receipts fix external, provider, model and embedding call counts and spend
to zero. They fix `authority_effect=NONE`, grant no qualification authority and
grant no production activation. Complete operational credential and egress
admission remains Increment 8/#148.

## Monitoring

Inspect the normalized dispatch outcome, reason, route, exact registry and
contract digests, upstream component identities, generation/profile identity,
authority watermark, and raw-receipt digest. Treat these conditions as
operationally distinct:

- authorization blocked before execution;
- source-scope scan overflow;
- result or response bound exceeded;
- stale generation, projection or authority watermark;
- rights or lifecycle block;
- unavailable branch, authority database or Neo4j index; and
- receipt or authority-integrity failure.

Do not infer absence from a blocked, stale, incomplete or unavailable result.

## Rollback

1. stop issuing the 5C2 profile and revoke or expire its grants;
2. retain all canonical authorization, execution, dispatch and upstream
   receipts for audit;
3. remove the exact 5C2 adapter/dispatcher commit while preserving 5C1;
4. verify no write, Candidate, publication or activation effect occurred; and
5. return parent 5C to the merged 5C1 boundary.

Rollback requires no provider, model, live-source or publication cleanup because
5C2 creates none. Neo4j and relational authority remain governed by their
existing projection and ledger recovery contracts.
