# Superseded discovery-only implementation Draft

**Status:** Superseded Draft  
**Owner:** Product owner  
**Originally drafted:** 2026-07-16  
**Superseded:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None  
**Successor:** [`2026-07-16-004-integrated-discovery-graphrag-implementation.md`](2026-07-16-004-integrated-discovery-graphrag-implementation.md)

## Why this Draft was superseded

The first Topic 13 Draft proposed:

- a separate discovery-v2 authority scope;
- a discovery-specific SQLite store for offline, replay and shadow work; and
- governed GraphRAG work after a substantially complete relational discovery implementation.

The product owner rejected that sequencing.

Although the Draft correctly separated relational authority from graph projection, it incorrectly treated graph independence as permission to defer the knowledge-graph contract. That would have created a planned semantic migration:

```text
discovery-only identities, events and retrieval
        ↓ later redesign
graph-aware identity, ontology, trust and retrieval
```

The accepted Topic 12 decision instead requires:

```text
canonical identity, temporal, trust and ordered-event contract from schema v1
        ├── SQLite relational authority
        ├── governed object store
        ├── graph projection
        ├── vector and full-text indexes
        └── bounded hybrid GraphRAG tools
```

## Decisions retained by the successor

The following principles from the first Draft remain valid and are carried into the successor plan:

- side-by-side replacement of the legacy Brave, RSS, GDELT and Gemini pipeline;
- no in-place mutation of legacy `links` and `events` as the target authority model;
- no automatic import of legacy event identity;
- no silent dual write;
- scheduler-neutral deterministic commands;
- generic adapters and fixtures before live source activation;
- offline-by-default development;
- separate approval for every live source, provider, model and budget;
- an evaluation-scoped Evidence Intake sink before governed downstream integration;
- milestone-sized implementation pull requests;
- no source-count ranking, category or finance caps, Hong Kong guaranteed slots or filler quotas; and
- separate Evaluation Plan, Operational Admission, canary, production activation and legacy-retirement decisions.

## Decisions rejected by the successor

The following are not carried forward:

- a discovery-only semantic schema that later migrates to a graph-aware model;
- a separate `DiscoveryStore` contract that omits the canonical graph event and trust model;
- treating GraphRAG as a later product-wide dependency rather than part of the first programme;
- qualifying the complete target architecture through a live shadow that omits governed graph projection and hybrid retrieval; and
- using a temporary discovery database as the conceptual production authority.

## Historical status

Git history preserves the complete earlier Draft and review sequence. This file is a tombstone so future agents do not treat the rejected plan as current guidance.

No code or runtime action was authorised or performed under the superseded Draft.