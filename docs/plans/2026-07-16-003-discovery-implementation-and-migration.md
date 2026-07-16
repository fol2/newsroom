# News discovery implementation and migration plan — first Draft

**Status:** Revision required; not accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This historical Draft authorises no code, external request, model call, graph-engine installation, source activation, spending, shadow run, canary or cutover.  
**Related review sequence:** [`2026-07-15-002-discovery-specification-review.md`](2026-07-15-002-discovery-specification-review.md)  
**Blocking review:** [`../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md)  
**Successor:** A revised integrated relational-plus-GraphRAG implementation plan will be written after Topic 12 is accepted or amended.  
**Historical version:** The complete first Draft remains available in Git history at blob `80b871a18118d847b61ea2514995112f700ee50a`.

## Decision record

The first Draft proposed:

- a side-by-side discovery v2 rather than in-place mutation of legacy `links` and `events`;
- a scheduler-neutral deterministic command surface;
- a separate append-only discovery SQLite store for offline, replay and shadow;
- generic adapters before named live sources;
- an evaluation Evidence Intake sink before real downstream integration;
- milestone pull requests through evaluation, canary, activation and legacy retirement; and
- no carry-forward of source-count ranking, category or finance caps, Hong Kong guaranteed slots or filler quotas.

The product owner accepted several of those boundaries in principle but **rejected the sequencing that treated GraphRAG as later product-wide work after a separate discovery-only implementation**.

The rejected shape was:

```text
discovery-only relational model
        ↓ later
GraphRAG ontology, projection and hybrid retrieval
```

The required replacement shape is:

```text
canonical identity, temporal, trust and ordered-event contract from schema v1
        ├── relational ledger and governed object authority
        ├── governed graph projection
        ├── vector and full-text indexes
        └── bounded hybrid retrieval tools
```

## Elements retained for the revised plan

The successor plan should retain, subject to the GraphRAG and ADR decisions:

1. side-by-side migration from the legacy pool rather than in-place mutation;
2. separate target identities and no automatic legacy event import;
3. no silent target-to-legacy dual-write;
4. scheduler-neutral repository-owned deterministic commands;
5. append-only authoritative history and rebuildable projections;
6. generic adapters and offline fixtures before named live source activation;
7. external requests, models, embeddings and providers disabled by default;
8. an evaluation Evidence Intake sink before governed downstream integration;
9. requirement-traced milestone pull requests with tests and rollback;
10. explicit Evaluation Plan, Operational Admission, canary, activation and retirement gates; and
11. reversible legacy retirement.

## Required changes in the successor plan

The successor must:

- adopt the final authority boundary from ADR 0001;
- adopt or amend the integrated SQLite-ledger boundary in ADR 0002;
- include graph ontology and projection event contracts in canonical schema v1;
- implement the graph projector, Graphiti proposal and admission path, hybrid retrieval and named tools in the first architectural workstreams;
- include Neo4j Community plus Graphiti as the initial POC lane if Topic 12 accepts it;
- require GraphRAG replay, ablation, provenance, temporal and rebuild evidence before complete live-shadow qualification;
- define graph-gap and graph-outage behaviour without treating failure as no match;
- prevent a graph engine or extractor from becoming editorial authority; and
- preserve the accepted discovery workflow, evidence boundary, operational and locality contracts.

## Current authority

No part of this historical Draft may be implemented merely because it was committed. Topic 13 begins only after Topic 12 and the relevant ADR decisions are complete.
