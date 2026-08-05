# Increment 5B2 bilingual full-text retriever operating boundary

- **Issue:** #292, child of #251
- **Accepted base:** `main@4acc389e1a2709cdb09a96de937cb163ad6525ba`
- **5A retrieval contract:** `sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c`
- **Full-text component:** `sha256:ec859d0a25d7684f6c3a693b59dca96337946b07552eae6aa870910eaf24465a`
- **Normalization component:** `sha256:0ed4fa41238d589933905cb3bf55b4dd9fe290c563ff07ee8676d776ad104070`
- **Effect:** one independently attributable, non-authoritative, read-only branch

## Scope

This atom implements only the `FULL_TEXT` branch required by Increment 5B. It
adds immutable request, hit, exclusion and receipt contracts; deterministic
bilingual normalization; one repository-owned Lucene expression builder; one
bounded authority-owned Neo4j read capability; and an immutable
non-authoritative SQLite receipt journal.

It does not implement the SQLite exact branch, vector retrieval, admitted-graph
traversal, fusion, cross-mode score comparison, dependency-root deduplication,
authoritative hydration, complete Retrieval Context assembly, Candidate
creation or relation admission. It does not activate production.

## Normalization and query construction

The normalizer is deterministic and repository-owned:

- CRLF and CR become LF before whitespace collapse;
- Unicode normalization is NFKC;
- Latin text is case-folded;
- traditional Han is preserved without script conversion;
- contiguous Han text emits exact bigrams;
- retained formal identifiers remain exact tokens;
- only typed current authority aliases valid at query-valid time contribute;
- no free transliteration is performed; and
- all Lucene metacharacters remain inside escaped, repository-built,
  field-scoped clauses.

The caller supplies bounded surface text and a typed language mode. It cannot
supply Lucene syntax, an index name, node label, property, provider, analyzer,
predicate, sort order or result limit. The retriever derives every graph-read
control from the accepted contract and the authoritative projection snapshot.

## Private Neo4j ownership

The existing repository invariant remains unchanged:

`newsroom/authority/_neo4j_projection_system.py` is the sole production
importer of `newsroom.projection.neo4j._adapter`.

The 5B2 retriever therefore never receives a driver, session, transaction,
private adapter or generic query callback. It receives only a typed
`Neo4jFullTextReader` capability. That capability exposes one phased `read`
operation restricted to `COMPONENT`, `INDEX` and `QUERY`, plus the exact driver
version; it exposes no driver, session,
`execute_query`, raw Cypher or write surface. Its private opener remains inside
the authority composition module and is not exported as a standalone public
connection factory.

The private adapter owns exactly three fixed, fail-fast read phases:

1. exact Neo4j component and edition identity;
2. exact generation-scoped full-text index inventory; and
3. one fixed full-text query returning only generation identity, passage
   identity, projection-document digest, language and raw branch-local score.

All three managed transactions share one cumulative monotonic deadline. Each
transaction receives only its remaining server-owned timeout. A timeout at any
stage becomes a typed timeout without retaining partial hits. Other driver or
service failures become a fixed credential-free unavailable result.

## Authority and projection checks

Before `COMPLETE` is possible, the branch binds and verifies:

- the accepted retrieval, full-text and normalization component digests;
- the exact active generation and generation-identity digest;
- the exact signed/current rights-manifest digest;
- a contiguous authority watermark at or above the request minimum;
- zero open gaps and zero dead letters;
- validation time, freshness deadline and the one-hour maximum age;
- exact Neo4j Community `2026.06.0` and driver `6.2.0` compatibility;
- one online generation-scoped `fulltext-2.0` index;
- analyzer `standard-no-stop-words`;
- synchronous index updates; and
- indexed fields `authority_aliases`, `formal_tokens`, `han_bigrams`,
  `latin_terms` and `retrieval_text`.

Every graph row must match an authoritative document binding for the same
passage, digest and language. Current rights, lifecycle and valid-time are
rechecked before a hit is exposed. Projection text is not returned as fact.
A wholly ineligible matched set is `POLICY_BLOCKED`, never `NO_MATCH`.

`COMPLETE / NO_MATCH` is possible only after the authoritative view is current,
the live component and index are compatible, and the fixed graph query
successfully returns no eligible result inside the hard deadline.

## Hard limits and receipts

The branch fixes:

- 5,000 ms cumulative timeout;
- eight admitted results plus a ninth overflow sentinel;
- 262,144 response bytes;
- zero external calls;
- zero provider spend;
- `authority_effect=NONE`;
- `hybrid_result_claimed=false`; and
- `projection_text_factual_use_allowed=false`.

A ninth row becomes `INCOMPLETE / RESULT_BOUND_EXCEEDED`; it is not silently
truncated. A one-nanosecond overrun becomes `INCOMPLETE / QUERY_TIMEOUT` and
clears hits and exclusions.

The separate SQLite journal stores canonical request and receipt bytes and
their SHA-256 identities. Reuse of an idempotency key with different request
bytes fails. Replay and restart return the first receipt bytes without rerunning
authority or Neo4j reads. Mutation, deletion and corrupted-byte paths fail
closed. The journal is evidence only and never authority.

## Outcomes

- `COMPLETE`: healthy branch, including an honest `NO_MATCH`;
- `STALE`: inactive or mismatched generation, rights manifest, watermark or
  freshness;
- `INCOMPLETE`: gaps, dead letters, populating index, overflow or timeout;
- `POLICY_BLOCKED`: request/contract policy failure or wholly ineligible hits;
- `UNAVAILABLE`: authority view, component, index, projection-integrity or
  graph-read failure.

## Rollback

Rollback removes only the 5B2 contracts, retriever, authority capability,
private fixed-read extension, tests and documentation. The immutable receipt
journal may be retained as non-authoritative evidence or removed only under an
explicit evidence-retention decision. Rollback never mutates SQLite authority,
selects a graph-free production path, enables an alternate analyzer or index,
or authorizes a model/provider, live source, credential, spend, publication,
shadow, canary or public effect.
