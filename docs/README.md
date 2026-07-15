# Documentation map

This repository is an automated, agentic newsroom system. Its documentation is separated by how humans and AI development agents are allowed to use it.

## Document authority

| Path | Purpose | Authority for implementation | Default canonical language |
|---|---|---|---|
| [`specs/`](specs/) | Target application behaviour, agent and tool boundaries, workflows, automation, pipeline contracts, data models, quality gates and other testable requirements | Normative only when the document status is `Accepted`, or when the owner explicitly instructs implementation | English |
| [`plans/`](plans/) | Time-bound implementation sequencing, milestones, migrations, rollout and validation work | Operational guidance only; a plan does not create or change product requirements | English |
| [`reference/`](reference/) | Editorial principles, legal and compliance notes, research, business context, company material and other retained knowledge | Non-normative; it may inform a spec, but must not be implemented as a requirement on its own | Hong Kong Traditional Chinese (`zh-HK`) for repository-authored human reference, unless the document declares an exception |
| [`research/`](research/) | Dated technical investigations, expert reviews and option studies | Non-normative; conclusions require an accepted spec, ADR or explicit owner decision before implementation | Declared by each document |
| [`adr/`](adr/) | Durable architecture decisions and their trade-offs | Normative only when the ADR status is `accepted` | English |

A spec may adopt selected constraints from a reference document. It must state those constraints explicitly. Linking to a reference document does not make the whole reference document normative.

Each translated document must state its canonical language and translation status. A translation must not silently introduce a requirement or policy decision absent from the canonical version.

## How development agents should use these documents

1. Identify the document type, status and canonical language before acting on it.
2. Implement an `Accepted` spec or an explicit owner instruction.
3. Use an active plan to organise work against one or more specs; do not use a plan to invent requirements.
4. Use reference material for context, research and risk awareness only, unless a spec explicitly adopts a requirement from it.
5. Use research to compare evidence and alternatives; do not treat a research recommendation as an approved decision.
6. Apply only an accepted ADR, and surface any conflict between that ADR and an accepted specification for owner resolution.
7. If an accepted spec conflicts with current code, tests or current-system documentation, surface the conflict instead of silently choosing one side.
8. Keep target behaviour separate from current behaviour. A spec describes the intended target; code, tests and current-system documentation describe what exists now.
9. Preserve provenance, status, canonical language and review dates so later agents can judge whether a document is current.
10. Where a development translation conflicts with its canonical document, use the canonical document and report the mismatch.
11. Do not infer owner approval from a merged pull request, passing test suite, committed Draft, Proposed plan or Proposed ADR.

## Current future-product documents

- [`specs/editorial-automation/`](specs/editorial-automation/) contains the normative specification suite derived from the autonomous product and editorial charter. Each file's own status controls whether it is accepted.
- [`plans/2026-07-15-002-discovery-specification-review.md`](plans/2026-07-15-002-discovery-specification-review.md) is the active owner-led discovery review sequence. It is not an implementation plan or shadow-run authorisation.
- [`specs/editorial-automation/discovery-coverage-contract.md`](specs/editorial-automation/discovery-coverage-contract.md) is the Accepted Topic 1 coverage contract.
- [`specs/editorial-automation/discovery-workflow.md`](specs/editorial-automation/discovery-workflow.md) is the Accepted Topic 2 trigger-to-evidence-handoff workflow.
- [`specs/editorial-automation/discovery-record-semantics.md`](specs/editorial-automation/discovery-record-semantics.md) is the Accepted Topic 3 identity, revision, decision and lineage contract.
- [`specs/editorial-automation/discovery-source-roles-and-selection.md`](specs/editorial-automation/discovery-source-roles-and-selection.md) is the Accepted Topic 4 source-role, portfolio, readiness and candidate-path contract. It authorises no collection.
- [`specs/editorial-automation/discovery-change-and-planned-agenda.md`](specs/editorial-automation/discovery-change-and-planned-agenda.md) is the Topic 5 Draft for source-change, current-state, baseline and Planned Agenda semantics. It is not yet accepted.
- [`adr/0004-source-registry-first-change-driven-discovery.md`](adr/0004-source-registry-first-change-driven-discovery.md) remains `proposed`. The complete source-registry, search and orchestration decision is not owner-accepted.
- The discovery section in [`plans/2026-07-15-001-integrated-newsroom-architecture.md`](plans/2026-07-15-001-integrated-newsroom-architecture.md) remains Proposed. Any stale parenthetical describing ADR 0004 as Accepted is non-authoritative and superseded by the ADR's current status and this review sequence.
- [`adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md) and [`adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md) remain Proposed.
- [`research/2026-07-15-database-architecture.md`](research/2026-07-15-database-architecture.md), [`research/2026-07-15-local-agentic-graph-rag-database-options.md`](research/2026-07-15-local-agentic-graph-rag-database-options.md), [`research/2026-07-15-low-cost-news-discovery-options.md`](research/2026-07-15-low-cost-news-discovery-options.md) and [`research/2026-07-15-concrete-news-source-map.md`](research/2026-07-15-concrete-news-source-map.md) retain non-normative research evidence.
- [`reference/editorial/product-editorial-charter.zh-HK.md`](reference/editorial/product-editorial-charter.zh-HK.md) is the canonical human reference charter.
- [`reference/editorial/product-editorial-charter.en.md`](reference/editorial/product-editorial-charter.en.md) is its English development translation.

## Existing current-system documentation

This taxonomy does not automatically reclassify the repository's established technical documentation:

- `ARCHITECTURE.md`, `AGENTS.md` and `PROMPTS.md` describe the current system and its operation.
- `CONTRIBUTING.md` describes contribution procedures.
- `docs/evaluation/` contains evaluation methodology and supporting documentation.
- `docs/cleanup_runs/` contains retained run evidence and generated artefacts.

New future-product requirements should normally be written under `docs/specs/`. New implementation work programmes should normally be written under `docs/plans/`. Dated investigations and option studies belong under `docs/research/`; broader retained background belongs under `docs/reference/`. Neither category controls implementation without explicit adoption.

## Recommended metadata

Every new document should begin with enough metadata to establish its role. Use the folder-specific README for the minimum fields and status values.

When a document is replaced, mark it `Superseded` or `Historical` and link to its successor rather than silently rewriting the record.
