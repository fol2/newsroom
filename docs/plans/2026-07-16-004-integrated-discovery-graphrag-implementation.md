# Superseded POC-framed GraphRAG implementation Draft

**Status:** Superseded Draft  
**Owner:** Product owner  
**Originally drafted:** 2026-07-16  
**Superseded:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None  
**Successor:** [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md)

## Why this Draft was superseded

This Draft correctly integrated graph-aware identities, ontology, projection and hybrid retrieval into the initial programme, but it still described Neo4j Community plus Graphiti as a `proof of concept` or `POC lane` before production admission.

The product owner rejected that framing because it preserves an implicit two-stage architecture:

```text
build the principal relational product
→ run a GraphRAG POC
→ decide whether GraphRAG graduates into production
```

The required direction is:

```text
one repository-native production system from schema v1
  ├── SQLite relational authority
  ├── governed objects
  ├── governed graph projection
  ├── vector and full-text indexes
  ├── Graphiti proposal and admission path
  └── hybrid GraphRAG retrieval
```

GraphRAG is mandatory in the first production deployment. Qualification decides whether an exact implementation is safe and effective enough to activate; it does not decide whether GraphRAG exists.

## Decisions retained by the successor

The successor retains:

- one canonical relational-plus-graph identity, temporal, trust and event contract;
- relational and object authority with graph and indexes as projections;
- side-by-side legacy replacement;
- no legacy identity import or silent dual write;
- scheduler-neutral commands;
- generic adapters before live sources;
- Graphiti proposal isolation and separate admission;
- hybrid exact, full-text, vector and bounded graph retrieval;
- exact relational Candidate collision authority;
- evaluation Evidence Intake before governed downstream integration;
- focused pull requests;
- no source-count ranking, quotas or filler; and
- separate Evaluation Plan, Operational Admission, canary, activation and retirement gates.

## Decision rejected by the successor

The successor rejects any interpretation that:

- GraphRAG is a proof of concept whose production adoption remains optional;
- a complete live-shadow or canary architecture may omit GraphRAG;
- Neo4j qualification failure permits a graph-less production release;
- GraphRAG may remain outside the main repository or production deployment definition; or
- dependency-ordered implementation creates two product stages.

Git history preserves the full earlier Draft. No code or runtime action was authorised or performed under it.