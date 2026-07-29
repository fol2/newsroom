# Increment 3E final qualification addendum

**Issue:** #209  
**Parent:** #143  
**Pull request:** #222  
**Authorised base:** `main@65ba31c403c84b9fbe82243912fd57612c097735`

This addendum records the final two P2 corrections found while qualifying the permanent authenticated Neo4j path. It does not expand Increment 3E capability or alter the fixed fixture/replay-only boundary.

## P2-10 — graph-loss proof attempted destructive rebuild of an ACTIVE generation

The first actual-service graph-loss proof replayed the original rebuild request after its generation had already been promoted. Projection authority correctly rejected that operation because an ACTIVE generation is immutable projection history and only a BUILDING generation may be destructively rebuilt.

**Correction:** post-activation graph loss is recovered through a new replacement generation rebuilt from retained SQLite authority, reconciled, validated and atomically promoted while the prior ACTIVE generation is retired. The test now also proves that attempting to rebuild the prior ACTIVE generation fails closed without adding another authority event.

## P2-11 — immutable-state comparison used two different query-valid times

The first corrected proof compared two lineage responses created by separate calls to the read-request factory. Each call retained a different `query_valid_time`, so response equality could fail even though projection authority and graph state were unchanged.

**Correction:** the proof creates one exact typed read request and reuses it before and after the rejected ACTIVE-generation rebuild. The assertion now compares the same governed subjects, family, bound, query-valid time and trust scope.

## Final review disposition before exact-head workflow evidence

```text
P1 findings:             0
P2 findings corrected:  11
Unresolved P1/P2:        0
```

The complete implementation remains bounded to repository fixtures and approved replay. Named live sources, credentials, schedules, external requests, browser collection, models, Graphiti, embeddings, search, triage, Candidates, Evidence Handoffs, publication, spending, production activation and public effects remain disabled.

PR #222 may merge only after this exact corrected tree passes CI, Authority A2a/A2b, Projection B1, authenticated Projection B2/B3/C1 Neo4j and the signed SDLC final decision, with zero actionable comments, submitted-review blockers or unresolved review threads.
