# Increment 2C bounded hybrid retrieval and authoritative context

**Role:** Implementation and operations record
**Status:** Draft PR evidence — no activation authority
**Owner:** Product owner
**Implementation issue:** #157
**Parent epic:** #142
**Authorised base:** `main@cc9053e80a0198af33ed862df118dbdac625f58f`
**Canonical language:** English

## Purpose and exact boundary

Increment 2C provides one production-shaped, fixture-only named read tool: `find_related_event_candidates`. It reads the authority-selected complete ACTIVE projection generation through four bounded branches, deterministically fuses dependency roots, rehydrates the exact permitted factual passages from governed-object authority, and retains an immutable Retrieval Context version 2 in SQLite.

SQLite ledger records, immutable decisions, governed objects and Retrieval Contexts remain authoritative. Neo4j full-text, vector and admitted-relation state is disposable context projection. A rank, score, graph path or retrieved row cannot allocate identity, admit a relation, commit a Candidate or create workflow authority.

This unit does not implement Increment 2D Candidate admission or the complete fixture-to-Candidate proof.

## Fixed named-tool contract

The public request contains only exact request/context identities, the checked fixture, query revision, query hypothesis version, query-valid time and idempotency key. It contains no result limit, generation identifier, label, relationship type, predicate, query text, Cypher or policy object.

The public system opener fixes `HYBRID_FIXTURE_POLICY_V1` and `INTEGRATED_FIXTURE_V2_RETRIEVAL`; only the private test composition seam can inject substitutes. The fixed policy requires:

- accepted purpose: development-context retrieval;
- exact structural and admitted `DEVELOPMENT_OF` trust only;
- graph depth at most `2`;
- relation fan-out at most `32`;
- branch result cap `8`;
- retained dependency-root cap `12`;
- reciprocal-rank fusion `k = 60` with equal branch weight;
- date window `31 days` ending at the exact checked query-valid time;
- maximum projection-validation age `1 hour`;
- transaction timeout `5 seconds`; and
- complete response cap `262,144` bytes.

The query-valid time is the repository-owned fixture time. A caller cannot backdate, future-date or otherwise widen the temporal scope.

## Four separately retained branches

Every successful context retains exactly one execution of each branch:

1. **Exact** — fixed lookup for the checked prior source revision under the active generation.
2. **Admitted graph** — fixed `DEVELOPMENT_OF` traversal, depth one or two, admitted trust only, checked endpoint record type and generation.
3. **Full text** — fixed parameterized query against the generation-derived full-text index.
4. **Vector** — fixed parameterized query against the generation-derived vector index using the repository-owned deterministic 16-dimensional fixture vector.

Labels and index names are derived from typed generation contracts. The private adapter exposes no driver or arbitrary query surface. The official Neo4j driver and managed-transaction decorator are imported only through the repository's single private driver seam. Before any branch executes, one fixed component-identification read requires the live server to be exactly Neo4j `2026.06.0` Community; malformed or non-qualified compatibility evidence is explicit unavailability. One monotonic five-second deadline governs that compatibility read and the complete four-branch tool call. Before each managed Neo4j read, the adapter derives that read's transaction timeout from the remaining shared budget and attaches fixed non-sensitive transaction metadata. A branch is not started after the shared budget is exhausted, a post-execution monotonic check remains as defence in depth, and the retained sum of branch elapsed evidence cannot exceed five seconds.

The authority boundary revalidates exact query identities, branch order, result bounds, trust scope, source identity, branch-specific score domains and mandatory prior-candidate coverage. The admitted graph identity is derived by the shared `newsroom-governed-relation-key-v1` primitive and includes the immutable `integrated_fixture_v2` binding ID; endpoint-only digests are not relation authority. Exact and direct admitted-relation fixture scores must be one; vector scores remain within `[0, 1]`; full-text scores are finite and non-negative. Neo4j binary64 scores are retained through Python's exact `.17g` round-trip form; fixed notation permits up to twenty fractional digits because the limit is seventeen significant digits, not seventeen decimal places. Alternate spellings of the same float remain non-canonical. A substituted typed adapter cannot omit the admitted relation, relabel a query or forge score evidence and still create context authority.

## Deterministic fusion and exclusions

`hybrid_fixture_fusion_v1` groups branch hits by checked dependency root, keeps the best hit from each branch, calculates an exact rational reciprocal-rank score, orders by descending score and canonical root identity, and retains no more than twelve roots.

The exact retrieval contract identity, canonical process, query-valid time and four-root inventory are fixed. Passage and dependency identifiers cannot belong to more than one root, and exactly one non-excluded root owns the prior Candidate. Successful branch evidence must cover every checked root, including self-query and distractors, so a substituted adapter cannot omit the mandatory negative neighbourhood. This prevents tuple order, duplicate dictionary keys or selective branch output from changing fusion or hydration authority.

English and Hong Kong Traditional Chinese passages for the same prior Candidate collapse under one dependency root while preserving branch-level and passage-level lineage. Self-query material, incompatible formal identifiers, incompatible jurisdiction/year lineage and material outside the fixed date window are retained as explicit exclusions. Result-bound exclusions are retained rather than silently discarded.

Fusion orders context only. It does not establish event sameness, relation authority or Candidate identity.

## ACTIVE projection, watermark and freshness

Before graph access, SQLite must identify exactly one ACTIVE complete generation for the fixture family. Retrieval requires:

- positive contiguous checkpoint;
- checkpoint equal to the current non-projection source watermark;
- matching complete validation at that checkpoint;
- zero open required gaps;
- zero dead letters;
- exact complete/full-text/vector/fixture contract identity; and
- serving time no later than one hour after the immutable validation time.

The retained projection metadata includes validation time, date-window start, query-valid time, freshness deadline, serving time, generation/family contracts, watermark, gaps and dead letters.

The store repeats all current-generation, watermark, validation-time, freshness and contract checks inside the SQLite write transaction before retaining either a complete context or a projection-bound failure. Replay rechecks the same current projection and governed hydration state. An authority-clock value earlier than query-valid, validation or retained serving time is rejected as stale. A stale projection, source advance, replaced ACTIVE generation, open gap, dead letter, clock rollback or expired freshness deadline never becomes `no prior match`.

## Authoritative hydration and retained context

Only dependency roots retained by deterministic fusion are hydrated. Each factual passage is read by exact governed-object admission under purpose `project.discovery`. The retained context links:

- admission and immutable blob digest;
- exact byte range and text digest;
- hydration policy contract;
- immutable object access decision;
- principal and authority domain;
- current rights decision, active admission state and the distinct current blob lifecycle state;
- observed trust scope; and
- checked fixture passage identity and language.

A rights revocation, deletion request, tombstone, missing bytes, access-decision mismatch or changed source watermark blocks a complete context. Neo4j text or snippets are never substituted for governed bytes.

Retrieval attempts, complete contexts and hydration links are immutable SQLite records under checked schema version 8. Store open re-derives canonical records, normalized columns, query/fusion evidence, hydration coverage, security provenance and cross-record identities. Re-digested or trigger-bypassing tampering fails startup integrity.

## Explicit outcomes

The tool returns one of:

- `COMPLETE`;
- `DEGRADED`;
- `STALE`;
- `UNAVAILABLE`;
- `INCOMPLETE`; or
- `POLICY_BLOCKED`.

Neo4j or index failure is `UNAVAILABLE`; source/freshness change is `STALE`; a required gap, dead letter, missing admitted relation, malformed branch evidence or failed hydration is `INCOMPLETE`; invalid caller scope or response-size breach is `POLICY_BLOCKED`. None is represented as `no prior match`.

Authentication and the exact purpose-bound scope are checked before replay lookup or any Neo4j read. Authentication currency and the exact authorization provenance are checked again after graph/hydration work and inside the SQLite write transaction before either success or failure authority is retained. Replays remain bound to the original principal and repeat the current security check. Expired authority creates no attempt record.

## Actual-service evidence

`.github/workflows/projection-b2-neo4j.yml` retains the earlier B1/B2/B3/C1 and complete 2B actual-service suite and adds four mandatory 2C cases:

- all four branches execute against authenticated Neo4j, the admitted relation contributes, checked distractors are explicitly excluded, bilingual prior passages are rehydrated from authority and restart replay retains the exact context;
- deletion of the generation full-text index returns explicit unavailability;
- deletion of the generation vector index returns explicit unavailability; and
- deletion of the admitted `DEVELOPMENT_OF` relation returns explicit incompleteness.

The workflow proves the exact four test identities executed with zero skip, failure or error and publishes a new extended evidence artifact while retaining the earlier aliases. The SDLC service lane fixes `NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED=1`; these cases are optional only in the deterministic no-service core manifest.

## Operator verification

Before merge, run from the repository root:

```bash
uv lock --check
uv sync --dev --locked
python -m compileall -q newsroom scripts
python -m pytest -q
python scripts/eval_clustering_metrics.py \
  --dataset newsroom/evals/clustering_eval_dataset_v1.jsonl \
  --baseline newsroom/evals/clustering_eval_metrics_baseline_v1.json \
  --fail-on-regression
git diff --check
```

The exact final PR head must pass CI, Authority A2a, Authority A2b, Projection B1, authenticated actual-Neo4j evidence and SDLC route/core/service/decision. Evidence from an earlier head is not transferable.

## Rollback

Before schema version 8 has opened, rollback is a normal source revert.

After schema version 8 has opened, do not delete migration rows, edit immutable retrieval attempts/contexts/access decisions, treat Neo4j as authority or reconstruct SQLite from graph/index state. Use one of:

1. restore a verified pre-v8 SQLite and governed-object backup; or
2. apply a reviewed forward fix while retaining immutable history.

Disposable Neo4j generation state may be deleted and rebuilt from SQLite/governed authority. A stale or invalid retained context is not rewritten; a new request/context identity is required under current authority.

## Explicit exclusions and stop boundary

Increment 2C includes no arbitrary Cypher, public driver, caller-selected graph scope, Graphiti, external model or embedding call, live source/search execution, production protected-content vectors, generalized retrieval, full triage, Candidate admission, scheduler, shadow, canary, production activation, publication, spending or public effect.

Issue #158 remains blocked. Do not begin Increment 2D until Increment 2C is merged, issue #157 is closed with exact-head evidence, and Retrieval Context v2 is stable, bounded, trust-labelled, authority-hydrated and fail-closed across every mandatory branch.
