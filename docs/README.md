# Documentation map

This repository is an automated, agentic newsroom system. Its documentation is separated by how humans and AI development agents are allowed to use it.

## Document authority

| Path | Purpose | Authority for implementation | Default canonical language |
|---|---|---|---|
| [`specs/`](specs/) | Target application behaviour, agent and tool boundaries, workflows, automation, pipeline contracts, data models, quality gates and other testable requirements | Normative only when the document status is `Accepted`, or when the owner explicitly instructs implementation | English |
| [`plans/`](plans/) | Time-bound implementation sequencing, milestones, migrations, rollout and validation work | Operational guidance only; a plan does not create or change product requirements | English |
| [`reference/`](reference/) | Editorial principles, legal and compliance notes, research, business context, company material and other retained knowledge | Non-normative; it may inform a spec, but must not be implemented as a requirement on its own | Hong Kong Traditional Chinese (`zh-HK`) for repository-authored human reference, unless the document declares an exception |

A spec may adopt selected constraints from a reference document. It must state those constraints explicitly. Linking to a reference document does not make the whole reference document normative.

Each translated document must state its canonical language and translation status. A translation must not silently introduce a requirement or policy decision absent from the canonical version.

## How development agents should use these documents

1. Identify the document type, status and canonical language before acting on it.
2. Implement an `Accepted` spec or an explicit owner instruction.
3. Use an active plan to organise work against one or more specs; do not use a plan to invent requirements.
4. Use reference material for context, research and risk awareness only, unless a spec explicitly adopts a requirement from it.
5. If an accepted spec conflicts with current code, tests or current-system documentation, surface the conflict instead of silently choosing one side.
6. Keep target behaviour separate from current behaviour. A spec describes the intended target; code, tests and current-system documentation describe what exists now.
7. Preserve provenance, status, canonical language and review dates so later agents can judge whether a document is current.
8. Where a development translation conflicts with its canonical document, use the canonical document and report the mismatch.

## Current future-product documents

- [`specs/editorial-automation/`](specs/editorial-automation/) contains the draft normative specification suite derived from the autonomous product and editorial charter.
- [`reference/editorial/product-editorial-charter.zh-HK.md`](reference/editorial/product-editorial-charter.zh-HK.md) is the canonical human reference charter.
- [`reference/editorial/product-editorial-charter.en.md`](reference/editorial/product-editorial-charter.en.md) is its English development translation.

## Existing current-system documentation

This taxonomy does not automatically reclassify the repository's established technical documentation:

- `ARCHITECTURE.md`, `AGENTS.md` and `PROMPTS.md` describe the current system and its operation.
- `CONTRIBUTING.md` describes contribution procedures.
- `docs/evaluation/` contains evaluation methodology and supporting documentation.
- `docs/cleanup_runs/` contains retained run evidence and generated artefacts.

New future-product requirements should normally be written under `docs/specs/`. New implementation work programmes should normally be written under `docs/plans/`. Background material that should be retained without directly controlling implementation should normally be written under `docs/reference/`.

## Recommended metadata

Every new document should begin with enough metadata to establish its role. Use the folder-specific README for the minimum fields and status values.

When a document is replaced, mark it `Superseded` or `Historical` and link to its successor rather than silently rewriting the record.
