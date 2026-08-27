# AI-native Focus Gate SDLC

**Status:** Accepted

**Owner:** Product owner

**Accepted:** 2026-08-27

**Issue:** #799

**Canonical language:** English (UK)

**Reference:** Anthropic, “The AI-Native Software Development Lifecycle”, 2026-08-21

## Decision

Newsroom uses an agent-owned, artefact-driven development loop. The ordinary pull-request critical path is one deterministic Focus Gate job. Full repository health, service qualification, research and irreversible operational controls are independent conditional lanes.

The objective is not fewer checks. It is complete relevant evidence with minimum wall time, model context and compute.

## Invariants

1. Agents own intent-to-merge for ordinary work; humans handle ambiguity, credentials, regulated or irreversible effects and explicit owner decisions.
2. Work enters the critical path only when it answers a concrete risk question for the exact change.
3. Unchanged context, environment setup, tests, review and remote observations are not repeated.
4. Every demonstrated failure mode and affected boundary remains covered. Unknown executable work escalates visibly and fail-closed.

## Focus Gates

- **F0:** exact change integrity. Documentation-only changes stop here.
- **F1:** direct positive, negative, boundary and regression behaviour.
- **F2:** deterministic affected callers, consumers and contracts.
- **F3:** bounded actual-service evidence only when local evidence is insufficient.
- **F4:** credentials, security, migration/deletion, publication, deployment, admission, activation and release remain exact and fail-closed.

## Machine route

`scripts/sdlc/focus_gate.py` emits `newsroom.sdlc.focus-route.v1`, a canonical content-addressed manifest containing:

- exact base/head and changed paths;
- selected gates and reasons;
- selected deterministic and actual-service tests;
- research and full-health routing;
- owner-authority and bootstrap requirements; and
- expected Focus Gate job/bootstrap counts.

The blocking selector is deterministic. An ML selector may be researched separately but cannot enter the blocking path without promotion through this contract.

## Retained compatibility tooling

The pre-Focus-Gate `sdlc-v2.6` lane, receipt and timing tables remain in
`.sdlc/gates.toml` so historical receipts and dormant diagnostic commands keep
validating fail-closed. They are not the ordinary pull-request topology. The
`[focus]` table and the three current workflow event surfaces are the execution
SSOT for new work. Retention does not authorise the retired eighteen-bootstrap
PR fan-out.

## Event surfaces

| Workflow | Event surface | Purpose |
|---|---|---|
| `focus-gates.yml` | ordinary pull requests | F0-F4 route, at most one locked bootstrap |
| `ci.yml` | research paths, schedule, manual | provider-free Graphiti research |
| `evidence.yml` | schedule, merge group, manual | full deterministic product health; research fixtures excluded |

A normal narrow PR never starts the old eighteen-shard topology or Graphiti research campaign.

## Selection rules

Changed tests select themselves. Changed source selects tests through explicit critical rules and repository import/package analysis. Migration and authority paths add their contract tests. Neo4j paths add bounded actual-service tests. Release and public-effect paths declare F4. Shared dependencies, test harnesses and unresolved executable paths escalate to full health.

A focused failure may broaden to its implicated dependency. It does not automatically broaden to the repository.

## Research

Research starts from an explicit uncertainty and produces a compact promoted contract, fixture, policy, benchmark or decision. Normal development consumes that output rather than replaying the campaign. Provider calls always require separate owner authority.

## Review and stop rule

One feature-complete review is the default. Repeat only after a material change or unresolved relevant finding. Stop after a coherent evidence set; report exact runs, omissions and uncertainty. Never claim an unobserved workflow result.

## Quantitative target

An ordinary documentation PR starts one Focus Gate evidence job and zero project-dependency bootstraps. An ordinary executable PR starts one Focus Gate evidence job and one locked bootstrap. The separate trusted PR Lifecycle metadata check remains lightweight and installs no project dependencies. Obsolete heads are cancelled. Scheduled/manual full health and research remain outside the ordinary critical path.

## Non-effects

This contract grants no publication, provider call, production admission, deployment, activation, spend or credential authority.
