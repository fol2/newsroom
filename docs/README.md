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

A link does not make an entire reference or research document normative. A merged pull request, passing test, committed Draft, Proposed plan or Proposed ADR does not imply owner acceptance.

## Development-agent rules

1. Identify document type, status and canonical language before acting.
2. Implement only an Accepted specification or explicit owner instruction.
3. Use plans to sequence accepted requirements, not invent them.
4. Use reference and research as evidence unless a specification adopts a constraint.
5. Apply only Accepted ADRs and surface conflicts.
6. Keep target behaviour separate from current code and tests.
7. Preserve provenance, versions, review status, supersession and explicit deferrals.
8. Treat specification acceptance, implementation authority, Evaluation Plan, Operational Admission, canary and production activation as separate authorities.

## Current discovery and GraphRAG documents

- [`plans/2026-07-15-002-discovery-specification-review.md`](plans/2026-07-15-002-discovery-specification-review.md) is the completed owner-led decision record for Topics 0–13 and ADR 0004.
- Topic 1–11 focused discovery specifications under [`specs/editorial-automation/`](specs/editorial-automation/) are Accepted and authorise no runtime action.
- [`specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](specs/editorial-automation/governed-graphrag-and-knowledge-projection.md) and [`specs/editorial-automation/graphrag-native-production-deployment.md`](specs/editorial-automation/graphrag-native-production-deployment.md) are the Accepted governed and native-production GraphRAG contracts.
- [`adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`adr/0004-source-registry-first-change-driven-discovery.md`](adr/0004-source-registry-first-change-driven-discovery.md) and [`adr/0005-native-graphrag-production-deployment.md`](adr/0005-native-graphrag-production-deployment.md) are Accepted.
- [`plans/2026-07-16-005-native-graphrag-production-implementation.md`](plans/2026-07-16-005-native-graphrag-production-implementation.md) is the Accepted Topic 13 implementation plan. Acceptance authorises no code or run.
- [`plans/2026-07-16-003-discovery-implementation-and-migration.md`](plans/2026-07-16-003-discovery-implementation-and-migration.md) and [`plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md`](plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md) are superseded tombstones retained for decision history.
- [`specs/editorial-automation/news-discovery.md`](specs/editorial-automation/news-discovery.md) is a non-normative consolidated Draft retained for navigation; the focused Accepted specifications and ADRs govern.
- [`plans/2026-07-15-001-integrated-newsroom-architecture.md`](plans/2026-07-15-001-integrated-newsroom-architecture.md) remains Proposed. Its earlier discovery wording, old ADR-status references and statement that discovery RAG was deferred are superseded by the completed review, Accepted ADRs and Accepted Topic 13 plan.
- Dated database, GraphRAG and discovery research remains non-normative evidence.
- [`reference/editorial/product-editorial-charter.zh-HK.md`](reference/editorial/product-editorial-charter.zh-HK.md) is the canonical human charter; the English file is a development translation.

## Current-system documentation

`ARCHITECTURE.md`, `AGENTS.md` and `PROMPTS.md` describe the existing Brave, RSS, GDELT, Gemini and Discord system. `CONTRIBUTING.md` describes contribution procedures. `docs/evaluation/` and `docs/cleanup_runs/` retain current evaluation and run evidence.

Future requirements normally belong under `docs/specs/`; implementation programmes under `docs/plans/`; dated investigations under `docs/research/`; and broader retained background under `docs/reference/`.

## Recommended metadata

Every new document should state its role, status, owner, canonical language and relevant dates. Replaced documents should be marked Superseded or Historical and linked to successors rather than silently rewritten.