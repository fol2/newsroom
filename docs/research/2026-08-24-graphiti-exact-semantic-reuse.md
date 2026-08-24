# Graphiti exact semantic and embedding reuse research (#765)

- Role: Dated research closeout
- Status: Completed — `RESEARCH_ONLY`
- Owner: fol2
- Canonical language: English
- Date: 2026-08-24
- Parent: [#739](https://github.com/fol2/newsroom/issues/739)
- Ticket: [#765](https://github.com/fol2/newsroom/issues/765)
- Primary extraction prerequisite: [#747](https://github.com/fol2/newsroom/issues/747)
- Deterministic-work prerequisite: [#748](https://github.com/fol2/newsroom/issues/748)
- Integrated implementation gate: [#731](https://github.com/fol2/newsroom/issues/731)

This document is non-normative research evidence. It does not amend `GING-010`, authorise cache serving, authorise a provider call, change credentials, mutate Neo4j or a live store, activate backlog ingest, or publish.

## 1. Decision

Recommendation: **`RESEARCH_ONLY`**.

The retained deployment snapshot contains a non-zero exact-request opportunity, but the repository has no qualified `NewsroomCombinedTemporalExtractionV1` donor artefacts that can be safely reused. Historical receipts do not carry the semantic-request and embedding-request identities required to prove an exact hit, and source-specific prompt fields have not been proved removable from semantic identity.

Do not activate cross-revision semantic or embedding reuse in #731 from this evidence.

## 2. Research question

Can a later effective revision or admitted chunk reuse an already validated #747 extraction result with zero new chat leaves, while creating fresh current source, evidence and proposal identities and rerunning all current rights, Entity Resolution, admission, journal, rollback and projection controls?

The research also considered whether exact embedding inputs could reuse a retained vector under an identical provider/model/configuration contract.

A cache hit was defined as proposal-material reuse only. It could never inherit source authority, Canonical Entity authority, a governed relation, admission, a graph effect, a completion marker or projection state from a donor.

## 3. Method and evidence boundary

The study used a provider-free, read-only scan of immutable deployment-store snapshots. Reports retained aggregate counts and digests rather than source text.

The current landed denominator was **1,790 effective revisions**. Of these, **1,079** had enough retained expression evidence to reconstruct the semantic-request opportunity set. The remaining **711** were classified as unresolved retention coverage; they were not counted as misses or zero-hit rows.

The scan distinguished:

- whole-revision and admitted-chunk exact request candidates;
- same-ingest completed-marker replay, which is already handled and must not be counted again;
- cross-item, cross-source and same-chain candidates;
- temporal or policy identity differences that force a miss;
- repeated embedding strings, which are only diagnostic until exact embedding identities and vectors are retained; and
- near-duplicate chains, which were passed to #766 and never counted as exact hits.

The complete #747 regression file passed with **172 tests**. No provider, graph mutation, live-store mutation, publication or activation occurred.

## 4. Measured opportunity

The reconstructable population contained:

```text
landed effective revisions:                    1,790
reconstructable effective revisions:           1,079
unresolved outside retained-expression view:     711
later exact request candidates:                   124
candidate groups:                                 112
candidate rate of reconstructable population: 11.492%
```

If every one of the 124 later candidates eventually had a qualified donor, the optimistic primary-leaf floor would be:

```text
primary misses = 1,079 - 124 = 955
optimistic primary leaves per reconstructable revision = 955 / 1,079 = 0.885
```

All 124 candidates were **cross-item within one source** in this snapshot. None was cross-source and none was an exact hit within a predecessor chain.

This is an opportunity ceiling, not a realised saving. A candidate without a qualified donor still requires the ordinary #747 primary path.

## 5. Why adoption failed

### 5.1 No qualified donors

The retained population contained **zero** qualified `NewsroomCombinedTemporalExtractionV1` donor artefacts.

Forty-three historical receipts were retained, but they predate the exact request and embedding identities required by this research. They therefore cannot be retrospectively upgraded into donors merely because their source bytes or model outputs look compatible.

A reusable donor must be terminal, schema-valid, duplicate-key-free, temporally valid, evidence-grounded, and validated under the exact current prompt, schema, validator and model-semantics identities.

### 5.2 Semantic request identity is not yet source-independent

The current #747 prompt includes `REVISION_ID` and `PREDECESSOR_REVISION_ID`. This research did not prove that those fields are controller-only metadata with no effect on extraction behaviour, correction interpretation or temporal meaning.

Until that is proved, removing them from the request identity or prompt would be an unsupported semantic change. A source-independent cache key is therefore not qualified.

### 5.3 Embedding opportunity is diagnostic only

Repeated entity and fact strings exist, but current retained evidence does not prove the exact embedding input-construction identity, model/configuration identity, vector integrity and provider receipt required for safe vector reuse.

Repeated strings are not reusable embeddings by themselves.

## 6. Candidate contracts retained for future work

The research identified four contracts that may be useful after a later explicit implementation decision.

### 6.1 `SemanticExtractionRequestIdentityV1`

A future exact request identity must bind at least:

- exact admitted chunk bytes digest and byte length;
- deterministic evidence-segment manifest and segmentation version;
- reference time, temporal basis and temporal-policy version;
- extraction-instruction and prompt-semantics digest;
- #747 schema and validator identities;
- proposal vocabulary and normalisation identities;
- exact framework/model/product semantics;
- language/output contract identity; and
- every other field capable of changing a valid result.

A one-byte content change, segment-boundary change, temporal-context change, prompt/schema/validator drift or model-semantics drift is a miss.

### 6.2 `ValidatedSemanticExtractionArtifactV1`

A donor artefact may contain only source-independent, already validated proposal material:

- canonical Entity Mentions and Relation Proposals using local and segment IDs;
- absolute or null temporal values;
- canonical output and raw-output digests;
- request identity and validator receipt;
- prompt/schema/framework/model identities; and
- terminal validity class.

It must contain no source rights decision, source authority, Canonical Entity authority, governed relation, Neo4j identity, graph effect, admission or projection state.

### 6.3 Current-revision binding receipt

An exact hit must still create a new current-revision receipt that proves:

- current retained bytes reproduce the donor segment manifest exactly;
- current rights and coverage obligation are valid;
- evidence segment IDs resolve to the current revision's exact byte ranges;
- proposal identities are newly derived for the current revision;
- current Entity Resolution and admission are rerun; and
- current journal, rollback and projection paths are used.

### 6.4 `EmbeddingRequestIdentityV1`

Exact vector reuse must bind provider, exact embedding model/version, dimensions, encoding, input-construction and normalisation versions, provider options, and exact input UTF-8 bytes digest and length.

On read, vector length, finite values, vector digest, model identity and source bytes must be revalidated. Configuration drift is a miss.

## 7. Average-token model

The research extends the programme's expected-count model to cache misses:

```text
T_avg_revision =
    E[Σ_(primary misses) T_primary]
  + E[Σ_(conditional leaves) T_conditional]
  + E[Σ_(embedding misses) T_embedding]
  + deterministic validation and rebinding work
```

An exact hit would have zero **new provider tokens**, but not zero CPU, storage, validation, rights, admission or projection work. Missing provider usage remains unresolved rather than zero.

## 8. Recommendation to #731

Keep #731's base path:

- one #747 combined-temporal primary leaf per admitted cache miss/chunk;
- #748 deterministic common-case resolution and summary work;
- distinct pre-dispatch leaf identities and usage receipts;
- duplicate-request refusal;
- bounded typed fallback and route circuits; and
- effective-revision-grain runtime measurement.

Do not serve semantic or embedding cache hits now.

A low-risk later atom may begin retaining future semantic-request and embedding identities without reading from a cache or skipping provider work. Actual reuse still requires a new adoption decision after qualified donors exist, retained-denominator coverage is adequate and end-to-end low/base/high savings are measured.

## 9. Reconsideration conditions

Reconsider exact reuse only when all of the following are available:

1. qualified #747 donor artefacts with exact request and validator identities;
2. proven separation, or deliberate retention, of source-specific prompt metadata;
3. exact embedding input/vector identities and integrity evidence;
4. materially improved retained-expression coverage beyond the unresolved 711 rows;
5. provider-free hit, rebinding, rights, corruption and concurrency fixtures; and
6. provider-reported low/base/high net savings with no quality, evidence, temporal, rights or rollback regression.

Until then, #765 remains research evidence rather than implementation authority.
