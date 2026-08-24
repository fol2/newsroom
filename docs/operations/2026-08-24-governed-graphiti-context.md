# Governed admitted Graphiti context

**Issue:** [#759](https://github.com/fol2/newsroom/issues/759)

**Role:** Operational implementation record

**Status:** Implemented, not activated

**Owner:** Newsroom

**Canonical language:** English

**Date:** 2026-08-24

**Profile:** provider-free, admitted-only structured editorial context

**Authority boundary:** SQLite authority and current rights decisions remain
authoritative. The reconciled Increment 4 projection is an admitted,
generation-scoped derivative. Graphiti, Neo4j and that projection remain
rebuildable proposal/retrieval infrastructure.

## Hydration seam

`GovernedContextHydrator` reads immutable admission requests, ADMIT decisions,
active projection receipts and their latest reconciliation. A reduced
`GovernedContextAuthority` port re-reads the current canonical entity or
editorial relation authority; `GraphitiRightsAuthority` rechecks use currency at
the same read instant. The concrete existing-authority adapter returns exact
entity/relation IDs and versions, admitted entity aliases or relation facts,
and admitted temporal values.

The hydrator never reads Graphiti nodes, edges, ranks, invalidations or a Neo4j
query surface. It returns only `READY`, `EMPTY` or `HOLD`:

- `READY` contains canonical admitted items with exact source revision, passage,
  temporal, authority, rights, generation, watermark and trust bindings;
- `EMPTY` is the deterministic result when no admitted current item exists; and
- `HOLD` contains no items and records stale authority, rights loss, receipt
  drift, unresolved gaps, ambiguous watermarks or exceeded bounds.

Each returned item repeats the read-time rights/admission currency,
gap/currentness indicators and `ADMITTED_GOVERNED_AUTHORITY_CONTEXT` label. The
bundle records the exact canonical envelope byte size and a conservative
one-token-per-UTF-8-byte ceiling. Item, byte and token limits hold the whole context rather than
silently truncating it.

## Editorial and CONT integration

`form_candidates(..., governed_context_builder=...)` invokes hydration once per
deterministically formed source/item Hypothesis scope, before constructing its
Hypothesis and Candidate records. Bounds therefore apply to that scope rather
than unrelated admitted rows. Context cannot create or merge a Hypothesis,
allocate a Candidate or change its identity. `package_for()` binds the same
scoped context into the Evidence Package digest. CONT receives that
package and the canonical admitted structured value; candidate/package drift or
a `HOLD` result blocks writer dispatch before any provider call.

`run_cycle(..., governed_context_builder=...)` is the optional injection seam.
No context builder is installed or activated by this change.

## Recovery and non-effects

Loss of Graphiti or Neo4j context is recovered by rebuilding the admitted
projection from governed authority. No graph-to-ledger recovery exists.

Hydration performs zero provider/model calls and creates no admission,
Candidate, Handoff, publication, schedule, public TargetOperation or production
activation authority.
