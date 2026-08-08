# Increment 5D1 — exact-first hybrid composition

## Scope

This record covers the read-only composition boundary admitted by Increment
5D1/#330. The composer consumes independently attributable 5C dispatch evidence
for the four retrieval branches and, when the declared purpose requires them,
the current collision/authority and source/revision-impact tools. It produces
one immutable composition receipt.

Authority-backed receipt semantics are validated through the pure
`named_tool_authority_receipt_validation` boundary. It checks retained bytes,
component identities, rights and lifecycle state, temporal lineage and truthful
outcomes without opening SQLite or another authority backend. The same closed
validator can be reused by 5D2 hydration.

The composer does not execute a retriever, read an authority store, hydrate
factual bytes, construct the final Retrieval Context reserved for 5D2/#331, create or
mutate a
Hypothesis or Candidate, call a provider or model, access a live source,
publish, or activate production.

## Fixed input manifest

Every receipt contains exactly six manifest entries in this order:

1. `EXACT_AUTHORITY_LOOKUP`;
2. `BOUNDED_FULL_TEXT_RETRIEVAL`;
3. `BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL`;
4. `BOUNDED_ADMITTED_GRAPH_TRAVERSAL`;
5. `CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP`; and
6. `BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP`.

All four retrieval branches are mandatory. Auxiliary evidence is mandatory only
under the fixed purpose map:

- `TRIAGE_PRIOR_MATCH`: neither auxiliary tool;
- `CORRECTION_REVIEW`: source/revision impact;
- `COLLISION_REVIEW`: current collision/authority metadata; and
- `REPLAY_AUDIT`: both auxiliary tools.

Request text or source content cannot alter this map. Each entry is explicitly
`COMPLETE_RESULTS`, `COMPLETE_NO_MATCH`, `INCOMPLETE`, `POLICY_BLOCKED`,
`STALE`, `UNAVAILABLE`, `MISSING`, or `NOT_REQUIRED`.

## One-request plan coherence

Each supplied input retains the exact canonical 5C named-tool request bytes in
addition to its dispatch, child execution and raw upstream receipt bytes. The
composer decodes those request bytes and verifies the request digest and
envelope digest against both retained receipt layers. It also recomputes the
child execution-request digest and dispatch-request digest from their exact
request, authorization and registry identities.

One composition request explicitly binds one actor, authenticated principal,
policy id/digest, accepted named-tool contract, profile, query-valid time and
serving time. Every supplied tool request must match that context. Tool-specific
grant, generation, scope, request id and payload may differ, but the request
purpose must be compatible with the fixed composition-purpose map. A receipt
from another caller, principal, policy, profile, time window or incompatible
purpose is rejected before manifest evaluation and cannot be mixed into one
hybrid result.

The immutable composition receipt retains the resulting plan-context digest
and, for every present manifest entry, the exact named-tool purpose, request
digest, envelope digest and canonical request-bytes digest. Receipt decoding
recomputes that plan-context digest from the top-level caller/policy/time fields
and the six-entry manifest; a substituted context cannot survive merely by
recomputing the outer receipt digest. Missing and not-required entries retain
none of those identities.

## Receipt validation

Before fusion, the composer revalidates every retained layer:

- exact canonical named-tool request bytes, request digest and envelope digest;
- typed 5C dispatch receipt and exact canonical round trip;
- recomputed dispatch-request digest;
- exact child execution receipt digest, authorization identity and recomputed execution-request digest;
- independently attributable raw upstream bytes, byte count and digest;
- branch request digest, profile, generation and outcome binding;
- query-valid and serving-time binding;
- exact result count and no-match state;
- canonical branch receipt shape, including duplicate-key rejection; and
- complete semantic validation of every supplied collision/authority and
  source/revision-impact receipt, including coverage, current rights/lifecycle,
  bounded temporal lineage and canonical ordering.

Fixed bounds, ranks and zero-effect counters require exact non-boolean integer
types; numerically equal floating-point or boolean substitutions fail closed.
Retained origins also preserve mode-specific passage/trust semantics. Graph
paths accept only the closed admitted predicate set, typed incoming/outgoing
directions and non-self-loop hops.

Every supplied independently attributable raw receipt is revalidated before
blocker precedence is interpreted. A recomputed malformed receipt therefore
cannot hide behind a genuine missing, stale, policy-blocked, unavailable or
incomplete manifest entry.

The vector branch retains large exact integer proof values. Those mode-specific
proof bytes are content-addressed with deterministic JSON but are never copied
into the composition receipt or compared with scores from another mode.

A malformed or self-inconsistent retained receipt produces
`INCOMPLETE / RECEIPT_INVALID`; it cannot become absence or no-match.

## Exact-first deterministic fusion

Fusion is fixed to equal-weight reciprocal-rank fusion:

```text
score(root) = sum over represented modes of 1 / (60 + best_rank_for_mode)
```

The score is stored as a reduced rational numerator and denominator. Floating
point and pooled raw branch scores are not used.

Candidates are ordered by:

1. roots supported by the exact branch;
2. roots supported by explicit admitted-lineage graph evidence;
3. approximate-only full-text/vector roots;
4. reciprocal-rank score descending within each precedence class;
5. best contributing branch rank ascending; and
6. authoritative dependency-root identity ascending.

This exact / explicit admitted-lineage / approximate ordering is independent of
raw scores and can intentionally place a lower-RRF admitted lineage root before
a higher-RRF similarity-only root.

The caller cannot change `k=60`, weights, ordering, branch participation,
result bound, or deduplication rule.

## Authoritative dependency-root deduplication

Hits merge only when their upstream receipts provide the same exact
`dependency_root_id`. Similar text, vector proximity, shared graph labels,
source names, or raw scores cannot merge roots.

For each root, only the best-ranked hit from each mode contributes to RRF. Every
origin remains in the candidate receipt with its mode, rank, result identity,
source identity, passage identity where applicable, trust/provenance digest,
branch-hit digest, dispatch/upstream receipt digests, exact match signal, and
complete admitted-graph path. The receipt marks the one score-bearing origin
per represented mode.

Full-text origins retain the branch receipt's authority-view digest as their
provenance identity. The per-hit digest remains separate, so an audit can
distinguish the authority snapshot that admitted the result from the individual
ranked hit bytes.

At most 12 roots are returned. Additional roots are retained as ordered
`RESULT_BOUND` exclusions with their would-be rank, exact rational score and
origin digests. Truncation is therefore explicit and auditable.

## Outcomes

- `COMPLETE`: every mandatory tool completed and all supplied optional evidence
  completed; positive candidates or a truthful complete no-match may be
  returned.
- `DEGRADED`: mandatory tools completed but supplied optional evidence did not;
  no no-match claim is permitted.
- `POLICY_BLOCKED`, `STALE`, or `UNAVAILABLE`: at least one mandatory tool has
  that state, using the fixed fail-closed priority.
- `INCOMPLETE`: a mandatory tool is missing/incomplete, retained receipt
  validation fails, or the fixed response bound is exceeded.

`NO_MATCH` is valid only when all four mandatory retrieval branches completed
bounded work with zero permitted hits and every purpose-required auxiliary tool
also completed. Missing, blocked, stale, unavailable, malformed, or truncated
work cannot become no-match.

## Bounds and non-effects

- four mandatory branch receipts;
- at most six total tool inputs;
- at most 32 branch origins;
- fixed RRF `k=60`;
- at most 12 retained dependency roots;
- fixed 262,144-byte composition receipt bound;
- zero external, provider, model, or embedding calls;
- zero provider spend;
- `authority_effect=NONE`;
- no qualification authority; and
- no production activation authority.

Raw upstream receipts remain in the accepted 5C journals. The 5D1 composition
receipt retains their content identities and selected provenance, not an
unbounded copy of raw branch evidence.

## Replay and monitoring

The local journal is first-writer-wins by idempotency key and semantic request
digest. It stores canonical receipt bytes and digest. On restart it parses the
retained receipt and independently re-derives the deterministic receipt from
the current exact request before returning the retained bytes. It therefore
rejects semantic idempotency conflicts, duplicate JSON keys, scalar type
confusion, ordinary retained-byte tamper, and attacker-recomputed row digests
whose receipt semantics differ from deterministic replay.

Monitor the plan-context digest, actor/principal/policy binding, six manifest
states, named-tool purposes and request/envelope digests, known omissions,
exact-first/explicit admitted-lineage/approximate precedence, contributing
modes, score-bearing origins, dependency-root count,
result-bound exclusions, receipt validation failures and response-bound
failures separately. Do not infer absence from any non-complete outcome.

## Rollback

1. stop issuing the 5D1 composition profile;
2. retain 5C and 5D1 canonical receipts for audit;
3. remove the exact composer commit while preserving the completed 5C tools;
4. verify no factual hydration, Candidate, publication or activation effect
   occurred; and
5. return parent 5D to the accepted post-5C boundary.

Rollback requires no provider, live-source, model, publication or authority
cleanup because 5D1 creates none.
