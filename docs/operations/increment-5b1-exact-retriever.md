# Increment 5B1 exact retriever operating boundary

- **Issue:** #289, child of #251
- **Base:** `main@cce9312b9349eaa3e1ef15e984728581ffd30b67`
- **5A contract:** `sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c`
- **Effect:** independent read-only exact-branch evidence only

## Scope

This atom supplies the common immutable request, hit, exclusion and receipt
records needed by the four independent 5B branches, one non-authoritative
SQLite receipt journal, one fixed-query SQLite exact retriever, and the separate
read-only Candidate collision seam.

It does **not** implement full-text, vector or admitted-graph retrieval. It does
not fuse branches, compare raw scores, deduplicate by similarity, hydrate final
context, claim a hybrid result, create a Candidate, admit a relation, establish
a fact, or activate production.

## Exact lookup surface

`SQLiteExactRetriever` admits only typed lookup kinds:

1. source-definition-scoped source-native identity;
2. global Source Revision identity or item-scoped source-native revision token;
3. Discovery Representation identity;
4. Canonical Entity identity;
5. retained authority Alias equality; and
6. retained formal-process identity.

Every SQL statement is fixed in repository code and every caller value is a
bound parameter. There is no caller-selected table, column, predicate, sort,
index, page size or SQL fragment. The authority database is opened with SQLite
`mode=ro`, `query_only=ON`, `trusted_schema=OFF`, and a second authorizer that
denies write, schema, attach, detach and transaction actions.

The branch limit remains exactly eight results and the hard timeout remains
5,000 ms. The query asks for at most nine rows so an over-bound result becomes
`INCOMPLETE / RESULT_BOUND_EXCEEDED`; it is never silently truncated. Timeout
comparison is performed at nanosecond precision. Even a one-nanosecond overrun
becomes `INCOMPLETE / QUERY_TIMEOUT` and cannot retain hits or Candidate
collision occupancy.

## Authority, current-version and eligibility rules

SQLite tables and governed records remain authoritative. A hit retains its
exact authority kind and identifier, dependency root, match signal, source
identity, trust scope and provenance digest.

Every source lookup binds both:

- the looked-up row's own immutable `definition_version_id`; and
- the current `source_definition_version_heads.current_version_id`.

The current head supplies current rights and lifecycle policy. The looked-up
row is eligible only when its own source-definition version is still that exact
current head. A historical Source Item, Source Revision or Discovery
Representation therefore cannot inherit a later permitted version and appear as
a current match. Such a row is retained as an explicit
`STALE_SOURCE_VERSION` exclusion. If every matching row is stale, the branch is
`STALE / SOURCE_VERSION_STALE`, never `COMPLETE / NO_MATCH`.

Current versions whose allowed use is prohibited, denied or revoked are
excluded as `RIGHTS_NOT_CURRENT`; a matching set that is wholly rights-blocked
is `POLICY_BLOCKED / RIGHTS_BLOCKED`. Retired, rejected, merged, split or
reversed authority state is excluded. Alias validity is checked against the
request's exact query-valid time.

A stale ledger watermark is `STALE`. Missing schema or an unreadable authority
database is `UNAVAILABLE`. A fixed-query timeout or over-bound result is
`INCOMPLETE`. Only a successfully completed current-version exact query may
report an empty `COMPLETE / NO_MATCH` branch receipt.

## Receipt journal

The journal is explicitly non-authoritative. It stores canonical request and
receipt bytes, their SHA-256 identities, request type and idempotency key. Rows
are immutable and retained. Restart or replay returns the first receipt bytes
without minting a new receipt or changing a replay flag inside the signed
record. Reuse of one idempotency key for materially different bytes fails with
an explicit conflict. Digest or canonical-byte corruption fails closed.

Blocked, stale, unavailable and incomplete attempts are journalled too. A later
retry after state changes must use a new request identity and idempotency key;
prior evidence is not rewritten.

## Candidate collision seam

Candidate collision checking is a separate relational read over the exact
`semantic_collision_digest`. Its receipt contains only occupied/unoccupied
state and the retained Candidate identity when occupied. It has no rank, score,
semantic merge, Candidate creation or admission effect.

## Non-effects

Every receipt fixes zero external calls, zero provider cost, `authority_effect`
`NONE`, and no hybrid claim. No source credential, model, embedding provider,
network egress, live source, search provider, write credential, publication,
shadow, canary or production activation is introduced.

## Rollback

Rollback removes the 5B1 application modules and tests. The separate receipt
journal can be retained as non-authoritative audit evidence or deleted only
under an explicit evidence-retention decision. Rollback never rewrites SQLite
authority and does not select a graph-free production path.
