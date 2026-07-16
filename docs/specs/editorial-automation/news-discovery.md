# News discovery documentation map

**Status:** Consolidated Draft; non-normative navigation  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Completed review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted implementation plan:** [`../../plans/2026-07-16-005-native-graphrag-production-implementation.md`](../../plans/2026-07-16-005-native-graphrag-production-implementation.md)  
**Increment 1 readiness package:** [`../../plans/2026-07-16-006-increment-1-implementation-readiness.md`](../../plans/2026-07-16-006-increment-1-implementation-readiness.md)  
**Supersedes:** The earlier version of this file that duplicated focused requirements as `DISC-*` summaries.

## Purpose

Provide a navigation map for the Accepted discovery, GraphRAG and architecture records.

This file defines no independent requirement, acceptance criterion, implementation authority or runtime permission. Do not cite it as the canonical source for product behaviour. Cite the focused Accepted specification requirement ID, Accepted ADR or accepted implementation plan instead.

A conflict is resolved in this order:

1. the applicable Accepted ADR or focused Accepted specification;
2. an explicit owner decision;
3. an accepted implementation plan for sequencing only; then
4. this non-normative navigation file.

The current Brave, RSS, GDELT, Gemini and Discord implementation is not evidence that the target contracts are implemented or qualified.

## Canonical focused specifications

| Area | Canonical document | Requirement prefixes |
|---|---|---|
| Coverage obligations and portfolio | [`discovery-coverage-contract.md`](discovery-coverage-contract.md) | `COV` |
| Scheduler-neutral workflow | [`discovery-workflow.md`](discovery-workflow.md) | `FLOW` |
| Canonical identities, versions and lineage | [`discovery-record-semantics.md`](discovery-record-semantics.md) | `DREC` |
| Source roles and selection | [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md) | `SRC` |
| Change detection and Planned Agenda | [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md) | `CHG`, `AGEN` |
| Triage and event grouping | [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md) | `TRI` |
| Bounded search and coverage audit | [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md) | `SRCH`, `CAUD` |
| Shadow evaluation | [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md) | `DEVAL` |
| Reliability and operations | [`discovery-reliability-and-operations.md`](discovery-reliability-and-operations.md) | `DOPS` |
| Prioritisation and outcomes | [`discovery-prioritisation-and-outcomes.md`](discovery-prioritisation-and-outcomes.md) | `DPRI`, `DOUT` |
| Locality scope and expansion | [`discovery-locality-scope-and-expansion.md`](discovery-locality-scope-and-expansion.md) | `LOC` |
| Governed GraphRAG and projection | [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md) | `GRAG` |
| Native production GraphRAG deployment | [`graphrag-native-production-deployment.md`](graphrag-native-production-deployment.md) | `GRPROD` |

Each requirement is defined once in its focused document. Cross-cutting implementation work must reference all applicable focused IDs rather than creating a new consolidated requirement namespace here.

## Canonical architecture decisions

| Decision | Canonical ADR |
|---|---|
| Relational ledger and governed object authority; rebuildable graph/vector/full-text projections | [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md) |
| SQLite in the integrated target architecture | [`../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md) |
| Source-portfolio-first, change-driven and natively GraphRAG discovery | [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md) |
| Repository-native mandatory GraphRAG production deployment | [`../../adr/0005-native-graphrag-production-deployment.md`](../../adr/0005-native-graphrag-production-deployment.md) |

The accepted direction is one graph-aware canonical identity, trust, temporal and ordered-event contract from schema v1. Neo4j Community plus Graphiti is the initial production-target implementation. Models and extractors propose; deterministic or authorised controllers commit. Production, canary and complete live-shadow configurations cannot omit GraphRAG.

## Implementation sequencing

[`../../plans/2026-07-16-005-native-graphrag-production-implementation.md`](../../plans/2026-07-16-005-native-graphrag-production-implementation.md) is the accepted programme plan. Its increments are merge and verification boundaries, not independently activatable product stages.

[`../../plans/2026-07-16-006-increment-1-implementation-readiness.md`](../../plans/2026-07-16-006-increment-1-implementation-readiness.md) is the completed post-merge authority audit, traceability matrix, technical design, PR #75 donor map and three-PR Increment 1 epic boundary.

Neither plan starts live source access, Graphiti, models, embeddings, spending, shadow operation, canary or production activation.

## Historical and non-normative material

- [`../../plans/2026-07-16-003-discovery-implementation-and-migration.md`](../../plans/2026-07-16-003-discovery-implementation-and-migration.md) and [`../../plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md`](../../plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md) are superseded historical records.
- [`../../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../../plans/2026-07-15-001-integrated-newsroom-architecture.md) remains Proposed; its earlier discovery and GraphRAG staging does not override the Accepted records above.
- `docs/research/` and `docs/reference/` remain evidence or context unless an Accepted specification adopts a constraint.
- Draft publication, rights, autonomy and lifecycle specifications do not become normative through a link from discovery documentation.
- PR #75 remains an open donor, not an approved implementation base.

## Usage rule

A code pull request must list the exact focused requirement IDs it implements, the accepted ADRs it relies on, explicit exclusions, evidence, rollback and any Deferred or Needs-experiment item. A reference only to this file is insufficient.