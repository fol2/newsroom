# Documentation map

This repository is an automated, agentic newsroom system. Documentation authority depends on document type and status.

## Document authority

| Path | Purpose | Implementation authority | Canonical language |
|---|---|---|---|
| [`specs/`](specs/) | Target behaviour, workflow, policy and testable requirements | Normative only when the individual document is `Accepted` or the owner explicitly authorises implementation | English |
| [`plans/`](plans/) | Sequencing, milestones, migration, rollout and validation | Organises accepted requirements; does not create them or activate runtime behaviour | English |
| [`reference/`](reference/) | Charter, editorial principles, legal and retained context | Non-normative unless an Accepted specification adopts a requirement | Usually Hong Kong Traditional Chinese |
| [`research/`](research/) | Dated investigations and option studies | Non-normative evidence | Declared by each document |
| [`adr/`](adr/) | Durable architecture decisions | Normative only when status is `accepted` | English |
| [`decisions/`](decisions/) | Dated product decisions that pin a slice without rewriting an ADR | Normative only when the individual record is `Accepted` | English |

A link does not make an entire reference or research document normative. A merged pull request, passing test, committed Draft, Proposed plan or Proposed ADR does not imply owner acceptance. Proposed readiness plans may be merged for traceability while implementation remains blocked until a separate owner-authorised boundary exists.

## Development-agent rules

1. Identify document type, status and canonical language before acting.
2. Implement only an Accepted specification or explicit owner instruction.
3. Use plans to sequence accepted requirements, not invent them.
4. Use reference and research as evidence unless a specification adopts a constraint.
5. Apply only Accepted ADRs and surface conflicts.
6. Keep target behaviour separate from current code and tests.
7. Preserve provenance, versions, review status, supersession and explicit deferrals.
8. Treat specification acceptance, implementation authority, Evaluation Plan, Operational Admission, canary and production activation as separate authorities.
9. Keep committed documentation `git diff --check` clean; use blank lines or ordinary paragraphs instead of trailing-space Markdown hard breaks.

## Current discovery and GraphRAG documents

- [`plans/2026-07-15-002-discovery-specification-review.md`](plans/2026-07-15-002-discovery-specification-review.md) is the completed owner-led decision record for Topics 0–13 and ADR 0004.
- Topic 1–11 focused discovery specifications under [`specs/editorial-automation/`](specs/editorial-automation/) are Accepted and authorise no runtime action.
- [`specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](specs/editorial-automation/governed-graphrag-and-knowledge-projection.md) and [`specs/editorial-automation/graphrag-native-production-deployment.md`](specs/editorial-automation/graphrag-native-production-deployment.md) are the Accepted governed and native-production GraphRAG contracts.
- [`decisions/2026-08-20-graphiti.md`](decisions/2026-08-20-graphiti.md) is the Accepted Graphiti SSOT for corpus ingest, temporal currency and drafting-context boundary. [`specs/editorial-automation/graphiti-corpus-ingestion-amendment.md`](specs/editorial-automation/graphiti-corpus-ingestion-amendment.md) is the numbered `GING-*` extract. It authorises Slice A only. It does not rewrite `GRAG-*` or `CONT-001`.
- [`research/2026-08-22-graphiti-combined-temporal-extraction.md`](research/2026-08-22-graphiti-combined-temporal-extraction.md) is the dated #747 provider-free qualification of `NewsroomCombinedTemporalExtractionV1`. It does not amend `GING-010` or authorise a live call.
- [`adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`adr/0004-source-registry-first-change-driven-discovery.md`](adr/0004-source-registry-first-change-driven-discovery.md) and [`adr/0005-native-graphrag-production-deployment.md`](adr/0005-native-graphrag-production-deployment.md) are Accepted.
- [`plans/2026-07-16-005-native-graphrag-production-implementation.md`](plans/2026-07-16-005-native-graphrag-production-implementation.md) is the Accepted Topic 13 implementation plan. Acceptance authorises no code or run.
- [`plans/2026-07-16-006-increment-1-implementation-readiness.md`](plans/2026-07-16-006-increment-1-implementation-readiness.md) is the Completed owner-authorised post-merge audit, traceability matrix, Increment 1 technical design, PR #75 donor map and three-PR implementation-epic boundary. It is documentation-only and authorises no runtime action.
- [`plans/2026-07-24-010-increments-2-11-owner-acceptance.md`](plans/2026-07-24-010-increments-2-11-owner-acceptance.md) is the **Accepted** owner decision for PR #140. It supersedes the two readiness documents’ pre-acceptance metadata, authorises only Increment 2 issue #142 after PR #140 merges and records the fixed exclusions and later-increment stop gates.
- [`plans/2026-07-24-008-increment-2-complete-fixture-readiness.md`](plans/2026-07-24-008-increment-2-complete-fixture-readiness.md) is the accepted technical readiness package for the first complete structural/full-text/vector/graph fixture slice. Implementation authority is limited by the owner-acceptance record and issue #142.
- [`plans/2026-07-24-009-increments-3-11-readiness-ladder.md`](plans/2026-07-24-009-increments-3-11-readiness-ladder.md) is the accepted dependency and decision map for Increments 3–11. It creates no present implementation or activation authority for those blocked increments.
- [`operations/neo4j-b2-qualification.md`](operations/neo4j-b2-qualification.md) records the Increment 1B2 Neo4j Community target, fixed-query adapter, credential separation and actual-service qualification boundary.
- [`operations/neo4j-b3-rebuild-promotion.md`](operations/neo4j-b3-rebuild-promotion.md) records the Increment 1B3 rebuild, reconciliation, active-generation serving, recovery and rollback procedure. It authorises no runtime activation.
- [`operations/increment-2a-governed-relation-authority.md`](operations/increment-2a-governed-relation-authority.md) records the draft Increment 2A SQLite relation authority, checked fixture, admitted-only projection seam, lifecycle handling and rollback boundary. It creates no Neo4j, source, model, shadow or production authority.
- [`operations/increment-2b-complete-projection.md`](operations/increment-2b-complete-projection.md) records the draft Increment 2B complete structural/admitted-relation/full-text/vector generation authority, actual-Neo4j qualification, source-watermark guard, lifecycle handling and rollback boundary. It creates no Increment 2C retrieval or runtime activation authority.
- [`operations/increment-2c-bounded-hybrid-retrieval.md`](operations/increment-2c-bounded-hybrid-retrieval.md) records the draft Increment 2C fixed named retrieval tool, four bounded branches, deterministic fusion, authoritative hydration, retained Retrieval Context v2, explicit failure outcomes and rollback boundary. It creates no Candidate admission or Increment 2D authority.
- [`operations/increment-2d-complete-actual-neo4j-proof.md`](operations/increment-2d-complete-actual-neo4j-proof.md) records the Increment 2D complete fixture-to-Candidate proof, schema-v9 Candidate authority, lifecycle recovery, actual-Neo4j evidence and rollback boundary. It creates no Increment 3 or runtime activation authority.
- [`plans/2026-08-14-014-increment-8-exact-qualification-readiness.md`](plans/2026-08-14-014-increment-8-exact-qualification-readiness.md) freezes the Increment 8 fixture qualification Plan, Operational Profile values, 110-row ownership map and no-activation boundary before any qualification result is collected.
- [`evaluation/2026-08-14-increment-8a-evaluation-authority.md`](evaluation/2026-08-14-increment-8a-evaluation-authority.md) records the immutable Plan/Epoch/Run/Case/review/adjudication and release-evidence authority, v30 backup gate and calibration-separation boundary.
- [`evaluation/2026-08-14-increment-8b-prospective-metrics.md`](evaluation/2026-08-14-increment-8b-prospective-metrics.md) records bounded prospective counts, required slices, source contribution, performance and non-rescuing ablation evidence.
- [`operations/2026-08-14-increment-8c-operational-authority.md`](operations/2026-08-14-increment-8c-operational-authority.md) records the v31 Operational Profile, bounded queue/lease/retry/quarantine authority and honest Handoff registration-anchor transition.
- [`operations/2026-08-14-increment-8d-observability-security.md`](operations/2026-08-14-increment-8d-observability-security.md) records multidimensional health, obligation/path coverage, safe versioned observability, incident lifecycle and fail-closed security evidence.
- [`operations/2026-08-14-increment-8e-recovery-authority.md`](operations/2026-08-14-increment-8e-recovery-authority.md) records exact-backup-gated v32 reconciliation, backup/restore, replay, purge and fixture fault-injection authority.
- [`operations/2026-08-14-increment-8f-operational-admission.md`](operations/2026-08-14-increment-8f-operational-admission.md) records intended hardware, capacity, cost, licence, exact Handoff and non-activating Operational Admission/Tier-M closeout evidence.
- [`operations/2026-08-24-graphiti-admission-consumer.md`](operations/2026-08-24-graphiti-admission-consumer.md) records the provider-free durable Graphiti proposal admission queue, governed authority/projector ports, rights tombstones and contiguous projection watermark for #758.
- [`research/2026-07-27-increment-2d-substantive-review.md`](research/2026-07-27-increment-2d-substantive-review.md) records the current-head Increment 2D substantive review and remaining exact-head merge gates.
- [`research/2026-07-26-increment-2c-substantive-review.md`](research/2026-07-26-increment-2c-substantive-review.md) records the current-head Increment 2C substantive review, corrected P1/P2 findings and remaining exact-head merge gates.
- [`research/2026-07-25-increment-2b-substantive-review.md`](research/2026-07-25-increment-2b-substantive-review.md) records the current-head Increment 2B substantive review, corrected P1/P2 findings and remaining exact-head merge gates.
- [`research/2026-07-25-increment-2a-substantive-review.md`](research/2026-07-25-increment-2a-substantive-review.md) records the completed Increment 2A substantive review, eight corrected P2 findings and its exact-head merge gates.
- [`plans/2026-07-16-003-discovery-implementation-and-migration.md`](plans/2026-07-16-003-discovery-implementation-and-migration.md) and [`plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md`](plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md) are superseded tombstones retained for decision history.
- [`specs/editorial-automation/news-discovery.md`](specs/editorial-automation/news-discovery.md) is a non-normative consolidated Draft used only as a navigation and canonical-source map; it defines no independent `DISC-*` requirements.
- [`plans/2026-07-15-001-integrated-newsroom-architecture.md`](plans/2026-07-15-001-integrated-newsroom-architecture.md) remains Proposed. Its earlier discovery wording, old ADR-status references and statement that discovery RAG was deferred are superseded by the completed review, Accepted ADRs and Accepted Topic 13 plan.
- Dated database, GraphRAG and discovery research remains non-normative evidence.
- [`reference/editorial/product-editorial-charter.zh-HK.md`](reference/editorial/product-editorial-charter.zh-HK.md) is the canonical human charter; the English file is a development translation.

## Current SDLC v2 documents

- [`specs/sdlc/high-performance-evidence-sdlc.md`](specs/sdlc/high-performance-evidence-sdlc.md) is the adopted `sdlc-v2.2` technical contract for sub-60-second machine gates, risk-routed evidence, exact provenance and scientific quality control.
- [`specs/sdlc/2026-07-22-sdlc-v2-owner-acceptance.md`](specs/sdlc/2026-07-22-sdlc-v2-owner-acceptance.md) is the **Accepted** normative record that supersedes the pre-acceptance status metadata and fixes the five owner-policy values.
- [`research/2026-07-21-high-performance-sdlc-evidence.md`](research/2026-07-21-high-performance-sdlc-evidence.md) is the Completed dated evidence study of the current five-workflow topology, exact JUnit timings, primary sources and rejected options.
- [`research/2026-07-21-sdlc-v2-substantive-review.md`](research/2026-07-21-sdlc-v2-substantive-review.md) records the completed design review and corrected P2 findings.
- [`plans/2026-07-21-007-sdlc-v2-migration.md`](plans/2026-07-21-007-sdlc-v2-migration.md) is the adopted reversible migration plan from historical increment workflows to one always-reporting router, one cached core lane and one conditional actual-service lane.
- [`../.sdlc/gates.toml`](../.sdlc/gates.toml), [`../.sdlc/route.schema.json`](../.sdlc/route.schema.json), [`../.sdlc/evidence.schema.json`](../.sdlc/evidence.schema.json) and [`../.sdlc/baselines/2026-07-21-b3.json`](../.sdlc/baselines/2026-07-21-b3.json) are the accepted machine-readable contract and exact baseline evidence.
- One decision-validated exact-head SDLC core receipt is the canonical complete deterministic evidence. Pull-request and merge-queue receipts are content-addressed, transport-verified evidence-only artifacts, not signed attestations; the signed exact-main closeout remains a separate Tier-M requirement. Fast `CI` and manually dispatched legacy Authority/Projection workflows are compatibility signals, not admission evidence. Tier S adds only route-selected affected lanes, with one review at the feature-complete stop.
- Issue #98 is closed completed. PR #99 accepted the SDLC v2 specification and PR #119 merged the reversible Phase 1/2 **SDLC Evidence Shadow** implementation.

## Current-system documentation

`ARCHITECTURE.md` and `AGENTS.md` describe the Hermes Control Plane as the operational Newsroom and record that the OpenClaw / Discord / Brave / GDELT / `news_pool` stack is dead ([ADR 0009](adr/0009-legacy-operational-newsroom-dead.md)). `CONTRIBUTING.md` describes contribution procedures. `docs/cleanup_runs/` retains dated historical run evidence only.

Future requirements normally belong under `docs/specs/`; implementation programmes under `docs/plans/`; dated investigations under `docs/research/`; and broader retained background under `docs/reference/`.

## Recommended metadata

Every new document should state its role, status, owner, canonical language and relevant dates. Replaced documents should be marked Superseded or Historical and linked to successors rather than silently rewritten.
