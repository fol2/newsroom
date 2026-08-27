# Documentation map

Newsroom documentation is loaded by authority and by need. Do not preload the
whole tree for an ordinary change.

## Authority order

1. The current GitHub issue defines the ordinary change intent.
2. Accepted specifications and ADRs define durable behaviour and architecture.
3. `.sdlc/gates.toml` and current workflows define machine execution.
4. Operations/evaluation records define bounded run or admission authority.
5. Research is evidence only unless promoted by an accepted decision.
6. Plans sequence accepted work; they do not independently authorise it.

A merged draft, passing test, historical review or linked research file does not
create implementation, provider, deployment or activation authority.

## Development

- [`../AGENTS.md`](../AGENTS.md) — concise always-loaded agent authority
- [`../REVIEW.md`](../REVIEW.md) — current feature-review policy
- [`testing.md`](testing.md) — Focus Gate execution and stopping behaviour
- [`agents/issue-tracker.md`](agents/issue-tracker.md) — proportional issue/PR use
- [`specs/sdlc/ai-native-focus-gated-sdlc.md`](specs/sdlc/ai-native-focus-gated-sdlc.md) — accepted AI-native SDLC
- [`../.sdlc/gates.toml`](../.sdlc/gates.toml) — current hardening and retained compatibility contract

The GitHub issue is the ordinary intent SSOT. Do not duplicate it into another
intent/specification/plan artefact without a concrete ambiguity or independent
durable decision boundary.

## Durable product authority

- [`adr/`](adr/) — accepted architecture decisions
- [`specs/editorial-automation/`](specs/editorial-automation/) — accepted and
  draft product contracts; inspect each document's status
- [`decisions/`](decisions/) — focused accepted product decisions
- [`reference/editorial/`](reference/editorial/) — retained charter and context

## Execution records

- [`operations/`](operations/) — bounded operational contracts, rollback and
  exact run records
- [`evaluation/`](evaluation/) — immutable evaluation/admission evidence
- [`traceability/`](traceability/) — retained closeout and requirement mapping
- [`plans/`](plans/) — sequencing and readiness records

## Research and history

- [`research/`](research/) — dated non-normative investigations and historical
  snapshots
- The 2026-02-09 OpenClaw architecture review is retained as
  [`research/2026-02-09-openclaw-architecture-review.md`](research/2026-02-09-openclaw-architecture-review.md).
- Earlier SDLC v2 specifications, research and migration records are historical
  provenance for retained receipt compatibility. They do not define the current
  ordinary pull-request topology.

## Current workflow surfaces

| Workflow | Purpose |
|---|---|
| `focus-gates.yml` | ordinary PR F0-F4 selected evidence |
| `evidence.yml` | post-merge main, scheduled and manual full product health |
| `ci.yml` | isolated provider-free Graphiti research |
| `pr-lifecycle.yml` | lightweight trusted PR metadata policy |

Repository documents and code use UK English. Git history is the archive for
superseded content.
