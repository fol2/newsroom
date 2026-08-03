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

## Package neutrality

`GraphRAG` names the repository architecture and semantic boundary. It **must not be equated with mandatory use of Microsoft GraphRAG community summarisation**. Microsoft GraphRAG, its community-summarisation pipeline and any equivalent third-party package are not required runtime dependencies, qualification modes or authority surfaces for Increment 5.

The selected initial target remains Neo4j Community plus Graphiti, reached only through repository-owned typed interfaces. An implementation may reproduce the reviewed retrieval and graph semantics without importing Microsoft GraphRAG or a community-summarisation package. Conversely, installing or invoking such a package cannot satisfy a required retrieval mode, create identity or relation authority, replace authoritative SQLite/governed-object hydration, or alter rights, budget, security, temporal or failure-semantics rules.

Any future package addition or replacement is an implementation choice that requires an exact reviewed version identity, licence and rights review, compatibility evidence and the applicable 5E qualification. Package availability, popularity or naming alone does not change the contract or authorize execution.

## Profiles, reviewed bindings and non-effects

Only `FIXTURE_REPLAY` and `PRODUCTION_SHAPED_QUALIFICATION` are admitted. Both enforce zero external calls, zero provider spend, no model load, no protected content, no write authority, no public effect and no production activation.

The qualification profile may use an authenticated Neo4j service and a signed, rights-cleared, repository-safe dataset manifest. Its evidence is limited to retriever/index/hydration/degradation behaviour. Fixture replay is hermetic and is never qualification evidence.

Profile schemas have two non-circular layers:

1. the contract identifies exact structural schema bytes; and
2. each public profile schema is deterministically derived from that exact structure and replaces only identity patterns with JSON-Schema `const` values for the reviewed contract digest and all component digests.

Standalone JSON-Schema consumers therefore receive the same identity checks as the Python API. The reviewed-binding schema digests are source-governed by PR #255 but are intentionally not inserted back into the contract they bind; doing so would create a schema-digest/contract-digest cycle.

These are non-production profiles. They do not claim the production-profile enforcement or production build/readiness validation required by `GRPROD-004` and `GRPROD-015`; those controls remain assigned to 5E/#254.

## Frozen evaluation extension

The contract contains the exact retrieval thresholds, slices and ablation inventory. The canonical machine plan `newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json` binds that summary exactly and adds the decision scope that the contract summary alone does not express:

- `HYBRID` is the sole qualification-bearing system;
- exact-only, full-text-only, vector-only and admitted-graph-only are mandatory comparative ablations;
- every contract threshold, mandatory-family criterion, temporal gate and rebuild gate applies independently to `HYBRID`;
- comparative quality results are reported separately and cannot replace, pool with or rescue the hybrid target;
- any safety or rights violation in any executed system remains blocking;
- all three mandatory GraphRAG query families have independent blocking criteria;
- exposure floors are 100 unique qualification cases, 30/30/40 by family, at least 10 per required case type, at least 20 per required slice and at least 10 per mandatory family/required-slice intersection; and
- temporal-correctness and reproducible-rebuild mismatches are zero-tolerance.

The machine-plan digest is `sha256:79bd07c69a69933d3a8fc1c218d638101d3c10e4a15cb482a8ee724ee973127b`. It remains outside the contract it binds, using the same non-circular reviewed-binding pattern as the public profile schemas. The loader requires the embedded contract summary to equal the reviewed contract byte-for-byte before accepting the decision target, comparative roles, additional families and gates.

Exposure sufficiency cannot be chosen after outcomes are visible: cross-family case reuse and calibration counting are prohibited, and any family, case-type, slice, family/slice or total shortfall is `NOT_EVALUATED`. A hybrid family must independently meet its frozen precision, recall and additional blocker. A strong comparative branch cannot manufacture a pass. Required-slice recall of 0.80 cannot excuse one temporal-correctness error. A rebuild that completes but changes eligible identities, ordering, receipts, provenance, trust, temporal fields, exclusions or outcomes is a blocking mismatch.

## Dependency boundaries

- **5B / #251:** four independent typed retriever implementations and their branch receipts; fixed-point vector seam only. 5B intentionally stops before fusion or dependency-root deduplication.
- **5C / #252:** six bounded named read-only tools; no raw Cypher, arbitrary index or writes.
- **5D / #253:** deterministic hybrid fusion and dependency-root deduplication, complete projectable and hydratable `Source → Revision → Signal → Lead → Hypothesis → Candidate` lineage with unverified states explicit, authoritative hydration, freshness, collision checks and explicit outcomes.
- **5E / #254:** hybrid-target qualification, comparative ablations, conditional challenger policy, production-readiness validation, Operational Profiles, per-family blocking criteria, zero-tolerance temporal/rebuild gates, security, purge, recovery and actual-Neo4j qualification.

The boundary is intentionally end-to-end rather than prefix-based. `GRAG-031` belongs to 5D because four independently working branches are not yet a hybrid system; fusion and dependency-aware deduplication create that system. `GRAG-042` also belongs to 5D. The accepted Increment 3 graph work is a useful foundation, but its trace expressly excluded the Event Hypothesis handoff and therefore did not deliver the six-stage lineage required by the normative requirement.

`GRAG-051` is not claimed by the generic material-change rule. 5E may execute a challenger-engine comparison only after a measured blocker or an owner-approved comparison purpose is retained. Multiple engines are not implemented in parallel by default, and no challenger can be introduced merely because the qualification issue exists.

The exact 114-requirement map is in `newsroom/increment5/traceability.py`. It distinguishes a decision bound by 5A from implementation/evidence delivered later. `DOPS-070` remains a required no-inherited-authority rule, but its complete executable version-admission enforcement is delivered in 5E rather than claimed by 5A’s narrower material-change text.

## Completion

PR #255 is the review unit. When its exact clean head passes repository-required checks, substantive review has no unresolved P1/P2 finding, actionable threads are resolved, and it is merged to `main`, this decision becomes effective and #250 may close. No follow-up admission PR is required.

That merge authorizes starting 5B. It authorizes none of the stated runtime non-effects.
