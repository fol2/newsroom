# Newsroom Agent Guide

## 0. Development DNA

Optimise for **maximum relevant evidence with minimum wall time, model context
and compute**. This is not permission to do less. Every demonstrated failure
mode and affected boundary must remain covered; irrelevant work must not enter
the critical path.

Use one coherent issue, one branch and one ordinary pull request by default. A
sub-agent may investigate or implement inside that delivery context. Create
another issue or PR only when the work has an independent merge, rollback,
owner, dependency or release boundary. Parallel machines are not themselves a
decomposition reason.

The normal AI-native loop is:

`issue intent -> implementation and tests -> focus manifest -> focused evidence -> one feature-complete review -> agent merge -> independent main health`

Agents own that loop. Human input is an exception for unresolved ambiguity,
credentials, regulated or irreversible effects, and explicit owner decisions.

## 1. Owner-above boundary

The owner sits above the loop by defining the outcome, constraints, risk
appetite, permitted effects and stop condition. The owner does not need to
choose test files, prescribe every implementation step, poll workflows or
approve ordinary non-F4 merges.

The GitHub issue is the ordinary change-intent source of truth. Do not create a
duplicate `intent.md`, specification, plan or review packet when the issue is
already implementation-complete. Add an artefact only when it resolves a real
ambiguity or has an independent durable authority boundary.

This repository has no organisation ruleset or merge queue. For ordinary work,
the agent may merge after one observed exact-head Focus Gate success and one
clean feature-complete review. F4 remains owner gated.

## 2. Focus Gates

Every ordinary change is routed deterministically:

- **F0 — change integrity:** exact diff identity, syntax and contract
  consistency. Documentation-only changes stop here.
- **F1 — direct behaviour:** the smallest positive, negative and boundary
  matrix for the changed behaviour, including the exact reproduction for a
  defect.
- **F2 — affected contract boundary:** direct callers and consumers selected
  from paths, imports, public symbols and explicit repository contracts.
  Persistence, replay, migration and authority evidence appears only when that
  boundary is touched.
- **F3 — actual service or runtime effect:** a bounded real service only when
  local evidence cannot establish the changed service semantics. Ordinary code
  and research receive no provider call.
- **F4 — irreversible or externally visible effect:** credentials, security,
  deletion, migration, publication, deployment, admission, activation and
  release controls remain exact and fail-closed.

Broaden after a concrete failure, unresolved dependency or newly discovered
risk. Do not broaden merely because a larger suite exists.

## 3. Work and evidence discipline

- Read the issue, touched code, direct contracts and nearest tests. Do not
  preload broad history or unrelated design documents.
- Default to the deterministic manifest produced by
  `scripts.sdlc.focus_gate_v2`.
- Prepare the locked environment once after checkout or a dependency change,
  not before each command.
- Run a check once per unchanged code, configuration and environment state.
- Do not poll remote workflows, increase a timeout merely to keep a run alive,
  or repeat review after all current findings are addressed.
- One feature-complete review is the default. Review again only after a
  material follow-up change or unresolved high-risk finding.
- Report the exact selected checks, outcomes, omissions and remaining
  uncertainty. Never convert an unobserved workflow into a claimed pass.
- Keep touched code slim: delete duplication, reuse existing contracts and
  avoid speculative abstractions, runners, caches and compatibility layers.
- Keep the existing `ponytail` coding skill active where available; use it to
  find the simplest complete solution, not to add ceremony.
- Conditional future machinery stays dormant until its trigger is observed or
  owner-authorised.

Full repository health, research qualification and release evidence are
independent lanes. Their existence does not make them ordinary-PR
prerequisites.

## 4. Research isolation

Research answers an explicit uncertainty and produces a compact promoted
output: a contract, fixture, policy, benchmark result or implementation
decision. Normal development consumes that output; it does not replay the
research campaign.

Graphiti research remains provider-free unless a separate owner-authorised
experiment explicitly permits a live provider. Research fixtures run only in
the research workflow or by explicit diagnosis.

## 5. Operational Newsroom

The operational Newsroom is the **Hermes Control Plane**: a distinct daemon
LaunchAgent with veto, ledger, broker, signed stop, Newsroom schedule and live
dispatcher. `newsroom-hub` is private Control Plane UI, not the Control Plane.
Canonical terms live in `CONTEXT.md`. Hard-to-reverse decisions live in
`docs/adr/`.

This repository does not run OpenClaw cron planners, the OpenClaw runner,
Discord publishing, Brave News, GDELT DOC 2.0, the broad media RSS pool,
`news_pool.sqlite3` or per-link Gemini clustering. That stack is dead and must
not be restarted. RSS/Atom remains a Source Definition transport. Git history
is the archive. See
[ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).

Increment 11B is a Hermes fresh start. This file grants no live source,
credential, spend, publication or activation authority.

## 6. Development references

- Python 3.12+, dependencies in `pyproject.toml`, lock in `uv.lock`
- Current review policy: [`REVIEW.md`](REVIEW.md)
- Detailed test behaviour: [`docs/testing.md`](docs/testing.md)
- Accepted Focus Gate contract:
  [`docs/specs/sdlc/ai-native-focus-gated-sdlc.md`](docs/specs/sdlc/ai-native-focus-gated-sdlc.md)
- Issue tracker: [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md)
- Documentation map: [`docs/README.md`](docs/README.md)
- Repository documents and code use UK English
