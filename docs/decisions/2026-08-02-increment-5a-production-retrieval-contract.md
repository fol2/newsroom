# Increment 5A — production retrieval contract decision

- **Status:** owner-accepted when this record reaches `main` through reviewed PR #255
- **Owner:** `fol2`
- **Issue:** #250; parent #145; programme #141
- **Implementation base:** `main@3ea1874de5e1bd6c622a3760eabb74adfe75d169`
- **Machine record:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Contract digest:** `sha256:c7dabaf97301f851c67a2d831f6ac87b34b38c78626ea7edf8f5725ff97f1c58`
- **Superseded stack:** `archive/increment-5a-stack-20260802`

## Decision

5A approves one exact contract for implementation and non-production qualification in #251–#254. It does not activate production.

The required branches are:

1. exact authority lookup;
2. bounded full-text retrieval;
3. vector retrieval through a typed interface; and
4. bounded traversal of admitted graph relations.

Branches return ordered receipts and are fused by deterministic reciprocal-rank fusion with `k=60`. Raw branch scores are never compared. Rank, similarity, graph paths and projection text are advisory. Candidate identity, collisions, rights, retained bytes and facts remain authoritative only in the SQLite ledger and governed objects.

Deduplication occurs only at the authoritative dependency root. Hydration re-reads authoritative bytes and rights. A missing branch, stale generation, denied authority, failed collision check or incomplete reconciliation cannot become a silent empty result.

## Source governance, not recursive self-admission

The previous branch attempted to make application code prove its own future merge, workflow history, comments, import closure and post-merge authority. Every added proof mechanism widened the trusted code base and created another unpinned or temporally impossible edge.

5A instead uses two layers:

- repository governance decides which source revision is accepted: owner control, review, required exact-head checks, resolved review threads and merge to `main`;
- deterministic product code identifies and parses the exact reviewed contract bytes and safe profile manifests.

The product layer does not call GitHub, inspect a PR, authenticate comments, spawn a verifier, pin its own import graph, mint a capability or require a second post-merge materialisation record. Digests identify content; they are not a competing authorization system. A material contract change requires a new contract version and a new reviewed merge.

## Vector and embedding boundary

Increment 5 v1 selects no embedding model, provider, credential, destination, download or spend. `EMBEDDING` is disabled.

The vector seam is qualification-only:

- 1,024-dimensional float32 vectors;
- cosine similarity;
- deterministic fixed-point fixture vectors;
- a generation-scoped index in an actual Neo4j service during 5E qualification;
- no model execution, external call, protected content or production activation.

This qualifies index construction, querying, rank handling, fusion, hydration, degradation and rebuild behaviour. It does not claim embedding relevance or approve a real production vector lane. A later model selection needs a fresh owner decision, rights review, model evaluation, component identity and new vector generation.

## Profiles, reviewed bindings and non-effects

Only `FIXTURE_REPLAY` and `PRODUCTION_SHAPED_QUALIFICATION` are admitted. Both enforce zero external calls, zero provider spend, no model load, no protected content, no write authority, no public effect and no production activation.

The qualification profile may use an authenticated Neo4j service and a signed, rights-cleared, repository-safe dataset manifest. Its evidence is limited to retriever/index/hydration/degradation behaviour. Fixture replay is hermetic and is never qualification evidence.

Profile schemas have two non-circular layers:

1. the contract identifies exact structural schema bytes; and
2. each public profile schema is deterministically derived from that exact structure and replaces only identity patterns with JSON-Schema `const` values for the reviewed contract digest and all component digests.

Standalone JSON-Schema consumers therefore receive the same identity checks as the Python API. The reviewed-binding schema digests are source-governed by PR #255 but are intentionally not inserted back into the contract they bind; doing so would create a schema-digest/contract-digest cycle.

These are non-production profiles. They do not claim the production-profile enforcement or production build/readiness validation required by `GRPROD-004` and `GRPROD-015`; those controls remain assigned to 5E/#254.

## Frozen evaluation extension

The contract contains the exact retrieval thresholds, slices and ablation summary. The canonical machine plan `newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json` binds that summary exactly and adds two decision-critical dimensions that cannot be reduced to aggregate ranking metrics:

- all three mandatory GraphRAG query families: event/development precision, source-revision impact and a long-running policy/case/process timeline; and
- zero-tolerance blocking gates for temporal-correctness errors and reproducible-rebuild mismatches.

The machine-plan digest is `sha256:6d52ea47056a8df4cd71213ae68c47471f7c2f546bd834053b27d747a0247c29`. It remains outside the contract it binds, using the same non-circular reviewed-binding pattern as the public profile schemas. The loader requires the embedded contract summary to equal the reviewed contract byte-for-byte before accepting the additional families and gates.

Required-slice recall of 0.80 cannot excuse one temporal-correctness error. A rebuild that completes but changes eligible identities, ordering, receipts, provenance, trust, temporal fields, exclusions or outcomes is a blocking mismatch.

## Dependency boundaries

- **5B / #251:** four typed retriever implementations; fixed-point vector seam only.
- **5C / #252:** six bounded named read-only tools; no raw Cypher, arbitrary index or writes.
- **5D / #253:** authoritative hydration, freshness, collision checks and explicit outcomes.
- **5E / #254:** production-readiness validation, Operational Profiles, all mandatory query families, zero-tolerance temporal/rebuild gates, preregistered ablation, security, purge, recovery and actual-Neo4j qualification.

The exact 114-requirement map is in `newsroom/increment5/traceability.py`. It distinguishes a decision bound by 5A from implementation/evidence delivered later.

## Completion

PR #255 is the review unit. When its exact clean head passes repository-required checks, substantive review has no unresolved P1/P2 finding, actionable threads are resolved, and it is merged to `main`, this decision becomes effective and #250 may close. No follow-up admission PR is required.

That merge authorizes starting 5B. It authorizes none of the stated runtime non-effects.
