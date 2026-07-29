# Increment 3E discovery-lineage projection and health operations

**Issue:** #209
**Parent:** #143
**Authorised base:** `main@65ba31c403c84b9fbe82243912fd57612c097735`
**Runtime boundary:** repository fixtures and approved replay only

## Authority rule

SQLite ledger records, immutable Source/Check/Signal/Gate/Lead decisions and governed lifecycle IDs are authoritative. Neo4j is a disposable, rebuildable structural projection. Never perform graph-to-ledger recovery, infer source change from graph absence, or edit graph state to repair authority.

The only Increment 3E family is `graph.discovery_lineage`. Its ontology, mapping and projector versions are fixed in source. Operators and callers cannot select labels, relationship types, property names, Cypher fragments or another family through the bounded read surface.

## Start and stop

There is no live source worker, credential, schedule, recurring collector, browser, model, Graphiti runtime, embedding job, search process, publication worker or public effect to start.

To stop 3E processing, stop issuing projection delivery, rebuild, validation, promotion and health-read commands. Existing SQLite records remain immutable and inspectable. Stopping Neo4j cannot lose canonical authority.

## Normal fixture qualification

From a locked Python 3.12 environment:

```bash
uv lock --check
uv sync --dev --locked
uv run python -m pytest -q newsroom/tests/test_discovery_projection_3e_*.py
uv run python -m pytest -q
uv run python scripts/eval_clustering_metrics.py \
  --dataset newsroom/evals/clustering_eval_dataset_v1.jsonl \
  --baseline newsroom/evals/clustering_eval_metrics_baseline_v1.json \
  --fail-on-regression
```

The permanent authenticated Neo4j workflow must execute all eight allow-listed `test_projection_b3_neo4j_service` cases exactly once, including both Increment 3E lineage cases, with zero skips, failures or errors.

## Replacement-generation rebuild

1. Register the fixed `graph.discovery_lineage` family if it is not retained.
2. Create a new `BUILDING` generation. Never write into the current `ACTIVE` generation as a repair mechanism.
3. Rebuild through an exact SQLite authority watermark. The rebuild reads accepted authority events; it never copies the old graph.
4. Inspect the retained checkpoint, required gaps and dead letters.
5. Run server-computed reconciliation. Client-supplied counts are not qualification evidence.
6. Promote only an exact validated generation with current family, ontology, mapping and projector contracts.
7. Retire the prior ACTIVE generation atomically through projection authority.

A failed, stale, gapped, dead-lettered, wrong-contract or graph-tampered generation must not become ACTIVE.

## Graph loss and tamper

Graph loss is an availability incident, not an authority loss. A bounded read against missing governed roots must fail closed. Projection health becomes `UNAVAILABLE` for service outage or `QUARANTINED` for graph inconsistency; neither state becomes source unchanged, no prior match or editorial rejection.

Recover by rebuilding a replacement generation from SQLite authority and re-running reconciliation and promotion. Exact rebuild replay is limited to a generation that remains `BUILDING`; an `ACTIVE` generation is immutable projection history and graph-loss recovery must replace it rather than destructively rewriting it.

Relation deletion, endpoint mutation, unexpected identity, count mismatch, wrong ontology/projector metadata or missing governed roots must fail reconciliation or bounded serving.

## Gaps and dead letters

A required out-of-order event creates a visible required gap and blocks contiguous watermark advancement. An unsupported required contract dead-letters and blocks validation. Optional handling is permitted only by the retained mapping allow-list; lack of projector support is not permission to ignore a required event.

Do not delete a gap, dead letter, checkpoint or validation row to make health appear green. Resolve through an authorised retry, supported forward correction or replacement generation.

## Source and parser health

Health is dimension-specific. Inspect source access, source contract, parser, Check execution, observation freshness and semantic lineage separately.

`HEALTHY` requires positive qualifying evidence. No attempt is `UNKNOWN`; transport failure is not parser failure; partial and malformed outcomes remain distinct; review/quarantine is not healthy. Quiet publication history is not stale by itself. Last complete observation, last successful observation and last source change are separate timestamps.

Source and coverage health reads rederive current evidence from SQLite. Authentication and authorization occur before definition or obligation lookup.

## Coverage availability

Coverage derives from retained Source Definition Version responsibility, contribution and portfolio-function mappings. A healthy Comparator or source count cannot repair an unavailable sole Anchor. Only an explicit retained contingency path may yield degraded substitute coverage. No configured path is `UNKNOWN`, never healthy by default.

## Bounded serving

The public lineage facade accepts only typed governed IDs, the fixed family and bounded limits. It rejects stale or incomplete ACTIVE generations, open required gaps, dead letters, contract drift, duplicate nodes, missing subjects, missing relation endpoints, wrong identity sources and oversized responses.

The surface exposes no Neo4j driver, arbitrary Cypher, caller-selected label/relation/property, unbounded traversal or cross-family discovery.

## Rights removal and non-resurrection

Increment 3E does not invent source deletion or rights authority. When current accepted authority marks a source version retired, rejected or otherwise projection-ineligible, health and serving must fail closed and a reviewed replacement generation must omit the covered current derivative lineage. A rebuild must use current retained eligibility and must not resurrect material excluded by accepted tombstone or removal authority.

## Rollback

Before merge, rollback is branch deletion or ordinary source revert. After a new projection contract has been used, apply a reviewed forward correction. Neo4j rollback is replacement-generation selection or complete graph loss followed by rebuild.

Never delete SQLite authority, migration history, checkpoints, gaps, dead letters, validation evidence or health evidence to simulate rollback. Increment 4 remains blocked until #209 and parent #143 close on `main` with exact completion evidence.
