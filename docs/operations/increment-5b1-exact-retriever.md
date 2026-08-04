# Increment 5B1 — exact retriever and branch-receipt operations

- **Issue:** #289; parent #251
- **Base:** `main@cce9312b9349eaa3e1ef15e984728581ffd30b67`
- **5A contract:** `sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c`
- **Authority effect:** `NONE`
- **Activation:** not authorised

## Boundary

This unit introduces the common immutable request/receipt substrate and the
SQLite exact-identity branch. It also preserves the exact Candidate collision
check as a separate relational seam. It does not implement full-text, vector or
graph retrieval and performs no fusion, final hybrid ordering, dependency-root
deduplication, hydration, Retrieval Context assembly, Candidate creation or
admission.

The exact branch is read-only. Callers select a closed `ExactLookupKind`; they
cannot provide SQL, table, column, predicate, sort, page, index or Cypher text.
Every query is repository-owned and parameterised. The connection uses SQLite
`mode=ro`, `query_only=ON`, `trusted_schema=OFF`, an authorizer that denies
non-read actions, a fixed progress-handler deadline, `LIMIT 9`, and a retained
result limit of eight.

## Request binding

Each request binds:

- an opaque UUIDv4 request identity;
- the exact branch mode and admitted 5A profile;
- principal, authority domain and effective scopes;
- one fixed purpose and required read scope;
- query-valid time;
- current rights class, decision digest, policy version and permitted use;
- an immutable SQLite watermark/state snapshot;
- the reviewed Increment 5A contract digest;
- the exact branch-component and policy digests; and
- fixed budgets: 5,000 ms, eight results, zero external calls and zero provider
  cost.

Personal-data metadata additionally requires
`authority.retrieval.personal_metadata`. Secrets, credentials, tombstoned and
revoked classes cannot be marked eligible.

## Exact lookup kinds

The closed v1 surface supports:

- Source Revision ID and source-native revision token;
- Source Item ID and source-native item ID;
- Discovery Representation ID;
- current Canonical Entity ID;
- authority-owned normalised entity alias;
- canonical formal-process ID; and
- exact Candidate Version ID.

Alias normalisation is fixed to LF line endings, Unicode NFKC, Unicode casefold
and whitespace collapse. It performs no free transliteration or Han script
conversion.

## Outcomes

A successful query returns `COMPLETE`, including a legitimate empty result.
Filtered current rows remain visible as exclusion receipts. A changed watermark
or state is `STALE`; missing schema/service is `UNAVAILABLE`; rights/scope/future
time is `POLICY_BLOCKED`; required gaps, dead letters or result overflow are
`INCOMPLETE`. None is silently represented as no-match.

Every hit retains source kind/identity/digest, authoritative dependency root,
raw branch rank/score, exact match signal, trust scope and sorted provenance.
Raw score is branch-local and advisory. A 5B receipt rejects hybrid-composed,
final-order or dependency-deduplicated claims.

## Replay journal

The receipt journal is a separate SQLite file, not the authority database. It
has `authority_effect=NONE`, immutable metadata/receipt triggers and one row per
`request_id + mode`. A retry or process restart returns the byte-identical
canonical receipt. Reuse of a request identity or digest for different bytes
fails with `BranchReceiptConflict`.

The journal stores no source text, credentials or SQL. It cannot allocate
identity, establish a fact, admit a relation or create a Candidate.

## Candidate collision seam

Candidate collision uses one fixed relational query against current Candidate
identity/version/admission rows. Its receipt contains either `CLEAR` or
`EXACT_COLLISION`; it contains no rank, score or similarity and has both
`authority_effect=NONE` and `candidate_effect=NONE`. Actual Candidate admission
and cross-request enforcement remain 5E/#254 work.

## Security and failure handling

- Injection payloads remain bound values and never become SQL syntax.
- Oversized, non-canonical and wrong-type inputs fail before opening SQLite.
- Query text and retained content cannot alter scopes, rights, budgets or
  policy.
- The read connection contains no write credential or write method.
- Errors expose fixed credential-free failure text and a digest of the detail.
- The branch emits identifiers/digests and provenance only; it does not hydrate
  retained source bytes.

## Rollback

Rollback removes the 5B1 Python interface and stops opening the receipt journal.
The journal file may be retained as non-authoritative audit evidence or deleted
under repository operations policy; it is not required to recover authority.
No authoritative row or governed object is changed, so no history rewrite,
projection rollback or Candidate repair is needed. Do not select an older branch
receipt as current evidence without re-running current rights, watermark and
freshness checks.

## Verification

`newsroom/tests/test_increment5b1_exact_retriever.py` covers exact lookup,
source-native injection, bilingual normalisation, current-lifecycle filtering,
stale watermark, unavailable schema, rights and future-time blocking, overflow,
request identity conflict, restart replay, immutable journal rows, exact
Candidate collision, dependency-root lineage, malformed input and canonical
receipt reconstruction. Full repository and signed exact-head workflow evidence
remain the PR merge gate.
