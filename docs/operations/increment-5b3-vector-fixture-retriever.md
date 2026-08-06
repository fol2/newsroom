# Increment 5B3 — deterministic vector fixture/replay retriever

## Status and identity

This operating record applies only to the independently attributable `VECTOR`
branch delivered by Increment 5B3 / issue #303.

The fixed identities are:

- retrieval contract: `sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c`;
- vector component: `sha256:efa34511338c4f28f7698db3aab7afbdde36c36e7d9ea36745367180b678db82`;
- embedding component: `sha256:cb084be3748ace7a75f68e2f2641566248c53566365f8f802c6c24b75e99c5e9`;
- provider identity: `vector-2026.06`;
- profile: `increment5-vector-fixture-replay-v1`.

The lane is fixture/replay-only. It grants no production, qualification,
provider, embedding, model, credential, spending, Evidence Intake, publication,
Candidate, relation, or public-effect authority.

## Fixed materialisation

A repository-admitted fixture query contains exactly sixteen signed fixed-point
integers at scale 1,000,000. Each component is materialised with IEEE-754
binary32 round-to-nearest-even semantics. The remaining 1,008 components are
right-zero-padded, producing exactly 1,024 `FLOAT32` values and 4,096 canonical
big-endian bytes. The vector identity is the SHA-256 digest of those bytes.

Cosine ordering is not delegated to platform floating-point comparison. The
materialised binary32 values are converted to exact rational values. Ordering
compares the exact cosine sign and squared rational magnitude, then uses stable
passage identity for ties. The receipt retains the exact dot product, query norm,
document norm, and squared-cosine rational proof. That score is branch-local and
must not be compared with scores from exact, full-text, or admitted-graph modes.

## Request boundary

A caller can select only one repository-admitted fixture query and must provide
its exact canonical digest. There is no arbitrary vector, model text, embedding,
index, provider, query language, predicate, field, label, relation, sort, or
pagination surface.

Every request binds:

- UUIDv4 request and bounded idempotency identity;
- exact actor, purpose, policy, retrieval contract, catalog, profile, vector,
  and embedding identities;
- query identity and digest;
- query-valid and serving times;
- minimum contiguous watermark;
- fixed eight-result, 5,000 ms, and 262,144-byte budgets.

## Current-authority checks

Before a result can be complete, the retriever requires one typed current
authority view proving:

- the exact active, complete generation and canonical generation digest;
- exact catalog, profile, vector, embedding, and rights-manifest identities;
- a sufficient contiguous watermark;
- zero required gaps and zero dead letters;
- validation freshness within the fixed maximum age; and
- one current authority binding for every eligible passage.

Every binding retains passage, dependency root, source revision, document,
rights, provenance, lifecycle, and current-rights identity. Missing or mismatched
bindings fail closed. Non-current rights, held, unresolved, proposal-only,
revoked, superseded, tombstoned, and temporally ineligible passages cannot rank.
The fixture catalog supplies vectors and immutable expected bindings only; it
cannot declare current rights or lifecycle authority.

## Outcomes

The branch emits typed `COMPLETE`, `INCOMPLETE`, `POLICY_BLOCKED`, `STALE`, or
`UNAVAILABLE` receipts. `NO_MATCH` is permitted only after every mandatory
contract, authority, generation, rights, freshness, watermark, gap, dead-letter,
binding, temporal, and budget check succeeds.

A ninth eligible result is an explicit overflow sentinel and produces
`INCOMPLETE / RESULT_LIMIT_EXCEEDED`; it is never silently truncated. Timeout,
response overflow, stale generation, required gap, dead letter, authority
unavailability, and fixture integrity remain explicit and cannot be represented
as no match.

## Immutable journal and replay

The non-authoritative SQLite journal stores only:

- idempotency key;
- request digest;
- canonical receipt bytes; and
- receipt digest.

Initial lookup is read-only. Authority production and exact ranking occur outside
a SQLite write reservation. A short `BEGIN IMMEDIATE` first-writer-wins insert
then retains the canonical bytes. Restart replay returns byte-identical bytes;
idempotency conflict, retained-byte corruption, request-binding conflict, or
digest mismatch fails closed.

The journal allocates no identity, relationship, Candidate, evidence,
operational, production, or publication authority.

## Zero-call boundary

For every outcome the fixed counters are:

- external calls: `0`;
- provider calls: `0`;
- model calls: `0`;
- embedding calls: `0`;
- provider spend: `0`.

No Neo4j vector query, vector-index client, model client, embedding client,
provider client, credential, egress, or live index seam is imported or
constructed.

## Monitoring and incident interpretation

Until 5E operational admission, monitoring is limited to deterministic request
and receipt inspection. A receipt can be used to diagnose contract, generation,
watermark, gap, dead-letter, rights, lifecycle, binding, timeout, result-bound,
and journal-integrity failures. It cannot establish system-level health,
coverage, containment, reconciliation, operational admission, production
eligibility, or public-effect readiness.

## Rollback

Rollback is repository-only:

1. stop callers from selecting the 5B3 fixture profile;
2. retain historical canonical request and receipt bytes for audit;
3. remove or revert the 5B3 product commit;
4. delete disposable local journal databases only after retained evidence is no
   longer required; and
5. return parent 5B to the completed 5B2 boundary.

Rollback does not require provider cleanup because this atom creates no provider
resource, vector index, credential, external vector, network destination, or
spend.
