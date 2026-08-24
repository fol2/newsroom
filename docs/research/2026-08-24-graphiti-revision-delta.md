# Graphiti revision-delta and deterministic semantic no-op research (#766)

- Role: Dated research closeout
- Status: Completed — `REJECT` for the measured distribution
- Owner: fol2
- Canonical language: English
- Date: 2026-08-24
- Parent: [#739](https://github.com/fol2/newsroom/issues/739)
- Ticket: [#766](https://github.com/fol2/newsroom/issues/766)
- Exact-reuse prerequisite: [#765](https://github.com/fol2/newsroom/issues/765)
- Primary extraction prerequisite: [#747](https://github.com/fol2/newsroom/issues/747)
- Deterministic-work prerequisite: [#748](https://github.com/fol2/newsroom/issues/748)
- Integrated implementation gate: [#731](https://github.com/fol2/newsroom/issues/731)

This document is non-normative research evidence. It does not specify or authorise a delta runtime, semantic no-op, provider call, `GING-010` amendment, cache serving, live-store or Neo4j mutation, backlog activation, or publication.

## 1. Decision

Recommendation: **`REJECT` for the measured retained distribution**.

The revision-chain population does not justify the state, prompt, reconstruction and mismatch complexity of `RevisionDeltaExtractionV1`. The safely provable deterministic semantic no-op allow-list is empty.

The terminal policy is:

```text
DETERMINISTIC_SEMANTIC_NO_OP_V1 = {}
RevisionDeltaExtractionV1 = not qualified
exact identity = owned by #765
all other revisions = DELTA_INELIGIBLE → ordinary full #747 path
```

## 2. Research question

After exact #765 reuse is exhausted, can a materially changed effective revision send only a bounded changed expression plus predecessor proposal context, then reconstruct the complete current #747 proposal set with lower average provider tokens and no loss of additions, deletions, negations, corrections, temporal changes or evidence attribution?

A second question was whether a closed deterministic transform could prove that a new revision was semantically unchanged and therefore required zero provider leaves.

The study deliberately rejected generic whitespace, punctuation or similarity normalisation as proof of semantic equivalence.

## 3. Method and evidence boundary

The study used a provider-free, read-only scan of an immutable proving snapshot. It analysed adjacent revisions within the same stable source item and retained aggregate counts rather than source text.

The snapshot contained:

```text
landed effective-revision denominator:          1,790
reconstructable effective revisions:            1,079
distinct source items represented:                779
revisions with an adjacent predecessor:           300
multi-revision source items:                       127
unresolved outside retained-expression view:      711
```

The unresolved 711 revisions were not extrapolated into the similarity or savings distributions.

All 1,079 reconstructed revisions were one chunk. The retained data therefore provides no evidence about chunk-boundary churn, unchanged partial chunks or multi-chunk reconstruction.

The deterministic scan repeated byte-for-byte on `origin/main@7c94ac03f93cc6d836768e0ea0a343bf224e62bf`. The focused #747 and #748 suites passed with **193 tests**. No provider, live-store, Neo4j, publication or activation effect occurred.

## 4. Measured revision-chain distribution

### 4.1 Exact in-chain reuse

There were **zero** in-chain exact #765 semantic-request hits among the 300 adjacent predecessor pairs.

Exact identity therefore does not remove any measured predecessor-chain primary calls in this snapshot.

### 4.2 Identical bytes with changed semantic time context

Of the 300 adjacent pairs, **152** had identical retained expression bytes but a changed reference-time identity.

They do not qualify as deterministic semantic no-ops. The same words can yield different absolute temporal meaning when the reference time, temporal basis or temporal policy changes, especially for relative expressions.

The research did not permit reuse merely because source bytes were equal or final absolute timestamps might happen to compare equal.

### 4.3 Byte-changing near-duplicates

The remaining **148** adjacent pairs changed bytes.

Diagnostic five-byte-shingle Jaccard thresholds identified:

```text
threshold 0.99:  4 pairs
threshold 0.95: 31 pairs
threshold 0.90: 48 pairs
```

These are opportunity diagnostics only. A similarity threshold cannot prove that a changed number, date, entity, negation, certainty marker, relation or punctuation is semantically harmless.

## 5. Token-effectiveness ceiling

Before counting any delta manifest, predecessor proposal context, operation schema, model output, reconstruction, validation, mismatch or full-path recovery cost, the deliberately optimistic gross input-saving ceiling was approximately:

```text
low threshold opportunity:  1.98 byte/4 token-proxy units per effective revision
base threshold opportunity: 5.35 byte/4 token-proxy units per effective revision
high threshold opportunity: 6.87 byte/4 token-proxy units per effective revision
```

These are source-safe proxies, not provider-reported tokens.

At the base candidate threshold, the median additional-overhead headroom was only **298 bytes**, and the tenth percentile had **zero** headroom. A real delta contract would need to spend that headroom on:

- exact delta and omitted-byte manifests;
- predecessor proposal IDs and bounded context anchors;
- `RETAIN`, `ADD`, `REPLACE` and `WITHDRAW` operation schema;
- current temporal and evidence context;
- output operations;
- deterministic reconstruction and comparison; and
- mismatch handling.

The fixed transport/context cost and missing donor evidence make net savings unlikely and unproved.

## 6. Why deterministic semantic no-op was rejected

A no-op policy needs a closed, versioned transform whose semantic effect is completely specified and whose current source/evidence mapping is retained.

No candidate class passed that standard:

- exact byte/semantic identity belongs to #765;
- identical bytes with changed reference-time identity are temporally different requests;
- punctuation, whitespace and Unicode transformations were not proved semantically inert under the governed lexical and evidence contracts;
- wrapper or boilerplate changes should already be removed before the retained corpus expression and therefore do not require a second semantic no-op layer; and
- no multi-chunk repacking evidence exists in the measured distribution.

Accordingly, the allow-list is intentionally empty rather than permissive.

## 7. Why `RevisionDeltaExtractionV1` was not specified

The initial opportunity scan is a stop gate. It did not justify building a second extraction workflow.

A safe delta contract would have needed to express at least:

```text
RETAIN predecessor proposal
ADD current proposal and evidence
REPLACE predecessor proposal with current proposal and evidence
WITHDRAW predecessor proposal with current evidence and basis
```

It would also need to reconstruct the complete current proposal set and compare it against a fresh full #747 gold result for adversarial cases including:

- added and deleted facts;
- entity, number and date corrections;
- negation and certainty changes;
- `valid_at` and `invalid_at` corrections;
- same-name entities;
- segment movement;
- changed reference times;
- chunk-boundary shifts;
- unavailable or invalid predecessor donors;
- rights loss; and
- restart/concurrency/replay.

Because the measured gross opportunity is too small and the current population contains zero qualified #747 predecessor donors, specifying the schema and differential harness would add complexity without an evidence-backed average-token benefit.

## 8. Recommendation to #731

Use the ordinary full #747 path for every non-exact revision. Do not add delta eligibility, semantic no-op normalisation or a second provider workflow to #731.

The current recommended Graphiti token-efficiency method remains:

1. one combined entity/relation/temporal/evidence primary leaf per admitted chunk;
2. deterministic common-case Entity Resolution Proposal and summary work from #748;
3. exact pre-dispatch request identity and duplicate refusal;
4. distinct usage receipts for chat and embeddings;
5. no unchanged retry;
6. at most one typed, separately receipted fallback when policy permits; and
7. effective-revision-grain measurement of primary, conditional, embedding and failed-attempt usage.

Exact semantic reuse remains `RESEARCH_ONLY` under #765 and is not a substitute for the full path until qualified donors and fresh adoption evidence exist.

## 9. Reconsideration conditions

Reopen delta research only after the retained environment is materially different and all of the following are present:

1. a substantial qualified donor population under #765 identities;
2. materially more retained predecessor-chain coverage;
3. multi-chunk revisions with measurable unchanged-chunk opportunity;
4. provider-reported full-path and candidate-delta usage rather than byte proxies;
5. positive low/base/high net savings after manifests, context, output, reconstruction and mismatch cost;
6. full differential gold evidence covering deletion, negation, correction and temporal cases; and
7. no new unbounded retry, fallback, authority or rollback risk.

Until then, implementing a revision-delta path would be optimisation by speculation rather than measured effectiveness.
