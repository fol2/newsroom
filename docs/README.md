# Documentation map

This repository is an automated, agentic newsroom system. Its documentation is separated by how humans and AI development agents are allowed to use it.

## Document authority

| Path | Purpose | Authority for implementation | Default canonical language |
|---|---|---|---|
| [`specs/`](specs/) | Target application behaviour, agent and tool boundaries, workflows, automation, pipeline contracts, data models, quality gates and other testable requirements | Normative only when the document status is `Accepted`, or when the owner explicitly instructs implementation | English |
| [`plans/`](plans/) | Time-bound implementation sequencing, milestones, migrations, rollout and validation work | Operational guidance only; a plan does not create or change product requirements | English |
| [`reference/`](reference/) | Editorial principles, legal and compliance notes, research, business context and retained knowledge | Non-normative unless a specification explicitly adopts a requirement | Hong Kong Traditional Chinese (`zh-HK`) unless declared otherwise |
| [`research/`](research/) | Dated technical investigations, reviews and option studies | Non-normative; conclusions require an Accepted spec, ADR or explicit owner decision | Declared by each document |
| [`adr/`](adr/) | Durable architecture decisions and trade-offs | Normative only when the ADR status is `accepted` | English |

A link does not make an entire reference or research document normative. Translations must state canonical language and must not introduce requirements absent from the canonical version.

## How development agents should use these documents

1. Identify document type, status and canonical language before acting.
2. Implement only an Accepted specification or explicit owner instruction.
3. Use plans to organise accepted requirements, not invent them.
4. Use reference and research for context unless a spec adopts a constraint.
5. Apply only Accepted ADRs and surface conflicts for owner resolution.
6. Keep target behaviour separate from current code and tests.
7. Preserve provenance, versions and review status.
8. Do not infer approval from a merged PR, passing tests, committed Draft, Proposed plan or Proposed ADR.

## Current future-product documents

- [`specs/editorial-automation/`](specs/editorial-automation/) contains the normative specification suite; each file's own status controls authority.
- [`plans/2026-07-15-002-discovery-specification-review.md`](plans/2026-07-15-002-discovery-specification-review.md) is the active owner-led discovery review sequence. It is not an implementation plan or run authorisation.
- [`specs/editorial-automation/discovery-coverage-contract.md`](specs/editorial-automation/discovery-coverage-contract.md) is the Accepted Topic 1 coverage contract.
- [`specs/editorial-automation/discovery-workflow.md`](specs/editorial-automation/discovery-workflow.md) is the Accepted Topic 2 workflow.
- [`specs/editorial-automation/discovery-record-semantics.md`](specs/editorial-automation/discovery-record-semantics.md) is the Accepted Topic 3 identity and lineage contract.
- [`specs/editorial-automation/discovery-source-roles-and-selection.md`](specs/editorial-automation/discovery-source-roles-and-selection.md) is the Accepted Topic 4 source-role and candidate-path contract. It authorises no collection.
- [`specs/editorial-automation/discovery-change-and-planned-agenda.md`](specs/editorial-automation/discovery-change-and-planned-agenda.md) is the Accepted Topic 5 source-change and Planned Agenda contract.
- [`specs/editorial-automation/discovery-triage-and-event-grouping.md`](specs/editorial-automation/discovery-triage-and-event-grouping.md) is the Accepted Topic 6 triage and grouping contract. It authorises no model calls.
- [`specs/editorial-automation/discovery-search-and-coverage-audit.md`](specs/editorial-automation/discovery-search-and-coverage-audit.md) is the Accepted Topic 7 search and audit contract. It authorises no provider, query, account or spending.
- [`specs/editorial-automation/discovery-shadow-evaluation.md`](specs/editorial-automation/discovery-shadow-evaluation.md) is the Accepted Topic 8 evaluation and release-evidence contract. It authorises no run.
- [`specs/editorial-automation/discovery-reliability-and-operations.md`](specs/editorial-automation/discovery-reliability-and-operations.md) is the Accepted Topic 9 operational contract. Exact Profile values remain Needs experiment and it authorises no process or activation.
- [`specs/editorial-automation/discovery-prioritisation-and-outcomes.md`](specs/editorial-automation/discovery-prioritisation-and-outcomes.md) is the Topic 10 Draft for decision order, canonical outcomes, reason taxonomy, ordinal priority and scoring boundaries. It authorises no score or queue configuration.
- [`adr/0004-source-registry-first-change-driven-discovery.md`](adr/0004-source-registry-first-change-driven-discovery.md) remains `proposed`; the complete architecture decision is not owner-accepted.
- The discovery section in [`plans/2026-07-15-001-integrated-newsroom-architecture.md`](plans/2026-07-15-001-integrated-newsroom-architecture.md) remains Proposed. Any stale parenthetical describing ADR 0004 as Accepted is non-authoritative and superseded by the ADR status and active review sequence.
- ADR 0001 and ADR 0002 remain Proposed.
- The dated database, graph/RAG and discovery research documents remain non-normative evidence.
- [`reference/editorial/product-editorial-charter.zh-HK.md`](reference/editorial/product-editorial-charter.zh-HK.md) is the canonical human reference charter; the English file is a development translation.

## Existing current-system documentation

`ARCHITECTURE.md`, `AGENTS.md` and `PROMPTS.md` describe the current system. `CONTRIBUTING.md` describes contribution procedures. `docs/evaluation/` and `docs/cleanup_runs/` retain evaluation and run evidence.

New future-product requirements normally belong under `docs/specs/`; implementation programmes under `docs/plans/`; dated investigations under `docs/research/`; and broader background under `docs/reference/`.

## Recommended metadata

Every new document should state its role, status, owner, canonical language and relevant dates. Replaced documents should be marked Superseded or Historical and linked to successors rather than silently rewritten.
