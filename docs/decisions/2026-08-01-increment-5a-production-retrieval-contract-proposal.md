# Increment 5A production retrieval contract proposal

**Status:** Proposed — exact owner comment and repository approval record required
**Owner:** Product owner
**Prepared:** 2026-08-01
**Issue:** #250
**Parent:** #145
**Implementation base:** `main@c9e31879421083e82e2538d57087d04e9b454d34`
**Decision packet:** `newsroom/increment5/data/increment5a_production_retrieval_decision_v1.json`
**Decision payload:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`
**Decision record:** `sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913`
**Contract bundle:** `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`
**Approval contract:** [`2026-08-01-increment-5a-owner-approval-attestation.md`](2026-08-01-increment-5a-owner-approval-attestation.md)

## Decision requested

Approve the immutable proposal identified above together with the hardened
effective qualification schema and exact non-effects. The proposal packet
itself remains `PENDING_OWNER_REVIEW`; approval is represented by an exact
owner comment on issue #250 and a canonical, digest-pinned repository record.

Until that record is reviewed and admitted, only contract validation and
non-qualifying fixture replay are authorized. Model loading, vector creation,
protected content, external embedding calls, credentials, spending, live
sources, shadow, canary, publication and production activation remain blocked.

## Exact proposed embedding identity

| Field | Exact value |
|---|---|
| Runtime | local process only; no external embedding API |
| Package | `sentence-transformers==5.6.0` |
| Package wheel SHA-256 | `d2075b5e687a1611005e20ab04a6846994d51adfcf39610aed066af3c0c0b81f` |
| Model | `BAAI/bge-m3` |
| Model revision | `5617a9f61b028005a4858fdac845db406aefb181` |
| Upstream licence record | MIT |
| Dense dimensions | 1,024 |
| Maximum input tokens | 8,192 |
| Pooling | CLS |
| Embedding normalization | L2 enabled |
| Inference/output | float32 / float32 |
| Remote code | prohibited |
| Request-time download | prohibited; immutable preload required |
| Credential reference | none |
| External calls and provider spend | zero |
| Protected content | prohibited by effective v2 profile |

Model identity never expands source rights. Every datum still requires the
rights decision and purpose declared by the packet.

## Exact retrieval contracts

- Passage construction uses UTF-8 byte offsets, paragraph then sentence then
  safe-UTF8 boundaries, a 3,072-byte target, 4,096-byte maximum and 384-byte
  maximum overlap. It never crosses Representation or Revision boundaries.
- Search normalization uses NFKC, LF, Latin casefold, collapsed whitespace,
  preserved Hong Kong Traditional Chinese, authority aliases only and Han
  bigrams. It performs no free transliteration or automatic Han conversion and
  never mutates authoritative bytes.
- Full text uses Neo4j `2026.06.0-community-trixie`, driver `6.2.0`,
  `fulltext-2.0`, `standard-no-stop-words`, synchronous generation-scoped
  indexes and no caller-supplied Lucene syntax.
- Vector retrieval uses the exact 1,024-dimensional self-hosted embedding,
  Neo4j `vector-2026.06`, cosine similarity, float32 and no quantization.
- Graph retrieval is fixed-template, read-only, depth 2, fan-out 32, a 31-day
  default window, admitted/observed trust scopes, zero open gaps and dead
  letters, and no generated Cypher or write capability.
- Fusion is equal-weight reciprocal-rank fusion with `k=60`, represented as
  reduced rational scores. Rank and fusion are never authority.
- Deduplication uses authoritative dependency roots, best hit per mode,
  retained receipts and a canonical root-ID tie break.
- Hydration rechecks rights and retrieves exact permitted bytes or decisions
  from SQLite and governed objects. Projection text cannot become factual
  authority.
- Outcomes are explicit `COMPLETE`, `DEGRADED`, `INCOMPLETE`,
  `POLICY_BLOCKED`, `STALE` or `UNAVAILABLE`. A failed or missing branch is not
  a no-match.

## Effective profiles and owner record

The historical proposal schema digest remains inside the immutable packet but
cannot validate an effective production profile. All unqualified production
schema exports resolve to v2.

Effective production-equivalent qualification requires:

- qualification profile schema
  `sha256:1dfdb4de6d2d184efb486d1601a3eb246f1d74352f55955a2b69e962336c31ef`;
- approval-record schema
  `sha256:8e69e5a66949e103ec4a960af34a509f3ba8b86a9f32b08ed77930f0898b8577`;
- the exact proposal record, bundle, components and owner comment evidence;
- a canonical approval record whose digest is pinned in reviewed source; and
- `protected_content_allowed=false` as a schema constant.

Runtime production gates accept no caller-supplied authority or verifier. They
read only the source-pinned repository record. Fixture replay remains
separately identified by
`sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`
and can never substitute for production qualification.

## Evaluation and rollback

The pre-registered Evaluation Plan compares exact-only, full-text-only,
vector-only, admitted-graph-only and hybrid modes on English, Hong Kong
Traditional Chinese, mixed-language, temporal, correction, shared-origin,
false-merge, long-running timeline and rights-purge/rebuild slices. Calibration
and qualification are disjoint.

Material changes create a new epoch and isolated index generation. The active
generation is never destructively rewritten. Rollback requires a rights-current
prior generation with exact contracts. `DOPS-072` remains delivered and tested
in 5E/#254, not in this decision unit.

## Dependency boundaries

- 5B/#251 implements the four independently inspectable retrievers.
- 5C/#252 implements the six closed authenticated read-only tools.
- 5D/#253 implements immutable Retrieval Contexts, authority hydration,
  freshness and explicit degradation.
- 5E/#254 runs pre-registered ablation, security, purge/rebuild, recovery and
  authenticated actual-Neo4j qualification.

Issue #251 remains blocked until the exact owner comment and repository record
are reviewed, 5A merges, and exact `main` qualifies. Approval creates no
shadow, canary, production activation, publication, external embedding API
authority, protected-content vector authority or spend.
