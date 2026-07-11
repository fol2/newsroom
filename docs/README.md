# Documentation map

This repository is an automated, agentic newsroom system. Its documentation is separated by how humans and AI development agents are allowed to use it.

## Document authority

| Path | Purpose | Authority for implementation |
|---|---|---|
| [`specs/`](specs/) | Target application behaviour, agent and tool boundaries, workflows, automation, pipeline contracts, data models, quality gates and other testable requirements | Normative only when the document status is `Accepted`, or when the owner explicitly instructs implementation |
| [`plans/`](plans/) | Time-bound implementation sequencing, milestones, migrations, rollout and validation work | Operational guidance only; a plan does not create or change product requirements |
| [`reference/`](reference/) | Editorial principles, legal and compliance notes, research, business context, company material and other retained knowledge | Non-normative; it may inform a spec, but must not be implemented as a requirement on its own |

A spec may adopt selected constraints from a reference document. It must state those constraints explicitly. Linking to a reference document does not make the whole reference document normative.

## How development agents should use these documents

1. Identify the document type and status before acting on it.
2. Implement an `Accepted` spec or an explicit owner instruction.
3. Use an active plan to organise work against one or more specs; do not use a plan to invent requirements.
4. Use reference material for context, research and risk awareness only, unless a spec explicitly adopts a requirement from it.
5. If an accepted spec conflicts with current code, tests or current-system documentation, surface the conflict instead of silently choosing one side.
6. Keep target behaviour separate from current behaviour. A spec describes the intended target; code, tests and current-system documentation describe what exists now.
7. Preserve provenance, status and review dates so later agents can judge whether a document is current.

## Existing documentation

This taxonomy does not move or reclassify the repository's established technical documentation in this change:

- `ARCHITECTURE.md`, `AGENTS.md` and `PROMPTS.md` describe the current system and its operation.
- `CONTRIBUTING.md` describes contribution procedures.
- `docs/evaluation/` contains evaluation methodology and supporting documentation.
- `docs/cleanup_runs/` contains retained run evidence and generated artefacts.

New future-product requirements should normally be written under `docs/specs/`. New implementation work programmes should normally be written under `docs/plans/`. Background material that should be retained without directly controlling the implementation should normally be written under `docs/reference/`.

## Recommended metadata

Every new document should begin with enough metadata to establish its role. Use the folder-specific README for the minimum fields and status values.

When a document is replaced, mark it `Superseded` or `Historical` and link to its successor rather than silently rewriting the record.